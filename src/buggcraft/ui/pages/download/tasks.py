"""Minecraft installation task history and progress UI."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QHBoxLayout,
    QDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)

from config.settings import get_settings_manager
from utils.path_helper import get_default_minecraft_dir
from core.downloads import DownloadCancelled, MinecraftDownloader
from core.loaders import install_loader
from ui.widgets.ComboBox import QMComboBox

logger = logging.getLogger(__name__)


class DownloadWorkerSignals(QObject):
    status = Signal(str, str)
    progress = Signal(str, int, int)
    resolved = Signal(str, str)
    finished = Signal(str, bool, str)


class DownloadWorker(QRunnable):
    def __init__(self, task_id: str, version: str, game_dir: str, source: str,
                 loader=None, base_version=None, loader_version=None, java=None, modpack=None, api_key=None, content=None):
        super().__init__()
        self.task_id = task_id
        self.version = version
        self.game_dir = game_dir
        self.source = source
        self.loader = loader
        self.base_version = base_version
        self.loader_version = loader_version
        self.java = java
        self.modpack = modpack
        self.api_key = api_key
        self.content = content
        self.cancel_event = threading.Event()
        self.signals = DownloadWorkerSignals()

    @Slot()
    def run(self):
        try:
            progress = lambda current, maximum: self.signals.progress.emit(
                self.task_id, int(current), int(maximum)
            )
            status = lambda value: self.signals.status.emit(self.task_id, str(value))
            if self.modpack:
                from core.modpacks import ModpackImporter
                ModpackImporter(self.game_dir, self.source, self.java, self.cancel_event,
                                status, progress, self.api_key).install(self.modpack, self.version)
            elif self.content:
                from core.content import download_content
                download_content(self.content['version'], self.content['target'], self.content['kind'],
                                 self.cancel_event, status, progress)
            elif self.loader:
                version_id = install_loader(self.loader, self.base_version, self.loader_version,
                    self.game_dir, self.java, {"setStatus": status,
                    "setProgress": lambda current: progress(current, -1),
                    "setMax": lambda maximum: progress(-1, maximum)}, self.cancel_event,
                    source=self.source)
                if not isinstance(version_id, str) or not version_id or version_id in ('.', '..') \
                        or any(char in version_id for char in ('/', '\\', ':')):
                    raise RuntimeError("加载器安装出的版本 ID 无效")
                self.version = version_id
            else:
                downloader = MinecraftDownloader(
                    self.game_dir, source=self.source, cancel=self.cancel_event,
                    status=status, progress=progress,
                )
                downloader.install(self.version)
            if not self.content:
                version_json = os.path.join(self.game_dir, "versions", self.version, f"{self.version}.json")
                if not os.path.isfile(version_json):
                    raise RuntimeError("下载结束，但版本文件没有生成")
            if self.loader:
                self.signals.resolved.emit(self.task_id, self.version)
            message = '整合包导入完成' if self.modpack else '内容下载完成' if self.content else f"{self.loader + ' ' if self.loader else ''}安装完成"
            self.signals.finished.emit(self.task_id, True, message)
        except DownloadCancelled as exc:
            self.signals.finished.emit(self.task_id, False, str(exc))
        except Exception as exc:
            logger.exception("Minecraft loader installation failed: %s", self.version)
            self.signals.finished.emit(self.task_id, False, str(exc))


class TasksPage(QWidget):
    """显示正在安装的游戏、进度和可追溯的安装记录。"""

    installed = Signal(str, str)
    ACTIVE = ("等待中", "进行中", "正在取消")

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.resource_path = parent.resource_path
        self.settings_manager = get_settings_manager()
        self.history_path = os.path.join(
            self.settings_manager.config_path, "download_history.json"
        )
        self._tasks = self._load_history()
        self._workers = {}
        self._rows = {}
        self._closing = False
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(500)
        self._save_timer.timeout.connect(self._flush_history)
        self.init_ui()
        self.refresh_tasks()
        self._flush_history()

    def _load_history(self):
        try:
            with open(self.history_path, "r", encoding="utf-8") as source:
                tasks = json.load(source)
            if not isinstance(tasks, list):
                return []
            tasks = [task for task in tasks if isinstance(task, dict)
                     and all(isinstance(task.get(key), str) for key in ("id", "version", "game_dir"))]
            cleaned, seen = [], set()
            for task in tasks:
                if task['id'] in seen:
                    continue
                seen.add(task['id'])
                for key in ('status', 'created_at', 'error'):
                    if not isinstance(task.get(key), str):
                        task[key] = ''
                for key in ('progress', 'maximum'):
                    try:
                        task[key] = max(0, int(task.get(key) or 0))
                    except (ValueError, TypeError, OverflowError):
                        task[key] = 0
                logs = task.get('logs', [])
                task['logs'] = [line for line in logs if isinstance(line, str)][-200:] if isinstance(logs, list) else []
                if task.get('state') not in (*self.ACTIVE, '已完成', '失败', '已取消', '已中断'):
                    task['state'] = '已中断'
                if task.get("state") in self.ACTIVE:
                    task["state"] = "已中断"
                    task["status"] = "上次安装未完成，可点击重试；已校验的文件会复用。"
                cleaned.append(task)
            return cleaned[:200]
        except FileNotFoundError:
            return []
        except (OSError, ValueError):
            logger.exception("Unable to read download task history")
            return []

    def _save_history(self):
        os.makedirs(os.path.dirname(self.history_path), exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=".download-history-", dir=os.path.dirname(self.history_path)
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(self._tasks, output, ensure_ascii=False, indent=2)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.history_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(15, 10, 15, 0)
        root.setSpacing(10)
        self.setStyleSheet('''
            QPushButton { background: #383047; color: #eeeaf6; border: 1px solid #625277;
                          border-radius: 4px; padding: 5px 10px; }
            QPushButton:hover { background: #514065; }
            QPushButton:disabled { color: #77717e; border-color: #45404c; }
            QLineEdit { background: #211f2b; color: #efedf5; border: 1px solid #494152;
                        border-radius: 4px; padding: 6px; }
        ''')

        header = QHBoxLayout()
        title = QLabel("游戏安装记录")
        title.setStyleSheet("color: #f2f2f2; font-size: 14px; font-weight: bold;")
        header.addWidget(title)
        header.addStretch(1)
        self.clear_button = QPushButton("清除已结束记录")
        self.clear_button.clicked.connect(self.clear_completed)
        header.addWidget(self.clear_button)
        root.addLayout(header)

        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索版本或安装目录")
        self.search.textChanged.connect(self.refresh_tasks)
        self.filter = QMComboBox(self)
        self.filter.addItems(["全部记录", "正在安装", "已完成", "失败", "已取消", "已中断"])
        self.filter.currentTextChanged.connect(self.refresh_tasks)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.filter)
        root.addLayout(filters)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.list_widget = QWidget()
        self.list_widget.setStyleSheet('background: transparent;')
        self.list_layout = QVBoxLayout(self.list_widget)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(8)
        self.scroll.setWidget(self.list_widget)
        root.addWidget(self.scroll, 1)

    def start_install(self, version: str, game_dir: str, loader=None, base_version=None,
                      loader_version=None, modpack=None, api_key=None, content=None):
        """Record the requested install and run it off the UI thread."""
        if self._closing:
            return False
        game_dir = os.path.abspath(os.path.expanduser(game_dir)) if game_dir else ""
        if not game_dir:
            game_dir = str(get_default_minecraft_dir())
            self.settings_manager.set_setting("minecraft.directory.enable", game_dir)
            directories = self.settings_manager.get_setting("minecraft.directory.installed", []) or []
            if game_dir not in directories:
                self.settings_manager.set_setting("minecraft.directory.installed", directories + [game_dir])
            self.settings_manager.save_settings()
        if any(
            task.get("version") == version and task.get("game_dir") == game_dir
            and task.get("state") in self.ACTIVE
            for task in self._tasks
        ):
            self.parent.on_progress_clicked()
            return False

        task_id = uuid.uuid4().hex
        task = {
            "id": task_id,
            "version": version,
            "loader": loader or "",
            "base_version": base_version or "",
            "loader_version": loader_version or "",
            "modpack": modpack or "",
            "content": content or {},
            "game_dir": game_dir,
            "state": "等待中",
            "status": "已加入安装队列…",
            "progress": 0,
            "maximum": 0,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "error": "",
            "logs": [],
        }
        self._tasks.insert(0, task)
        # Bound history without dropping a live task.
        live = [item for item in self._tasks if item["state"] in self.ACTIVE]
        ended = [item for item in self._tasks if item["state"] not in self.ACTIVE]
        self._tasks = sorted(live + ended[:max(0, 200 - len(live))],
                             key=lambda item: item["created_at"], reverse=True)
        self.filter.setCurrentIndex(0)
        self.search.clear()
        self._persist_and_refresh()

        source = self.settings_manager.get_setting(
            "settings.general.mirrors", "自动选择下载源（自动选择速度快的源）"
        )
        java = self.settings_manager.get_version_setting("java.path", None)
        worker = DownloadWorker(task_id, version, game_dir, source, loader, base_version, loader_version, java,
                                modpack, api_key, content)
        worker.signals.status.connect(self.update_status)
        worker.signals.progress.connect(self.update_progress)
        worker.signals.resolved.connect(self.resolve_version)
        worker.signals.finished.connect(self.finish_task)
        self._workers[task_id] = worker
        self.pool.start(worker)
        self.parent.on_progress_clicked()
        return True

    def import_modpack(self, archive='', identity='', game_dir=None):
        from ui.dialog.ModpackImportDialog import ModpackImportDialog
        directory = game_dir or self.settings_manager.get_setting('minecraft.directory.enable') or str(get_default_minecraft_dir())
        dialog = ModpackImportDialog(self, directory, archive, identity)
        if dialog.exec() == QDialog.Accepted:
            self.start_install(dialog.identity, directory, modpack=dialog.archive)

    def download_content(self, kind=None):
        from ui.dialog.ContentDownloadDialog import ContentDownloadDialog
        directory = self.settings_manager.get_setting('minecraft.directory.enable') or ''
        version = self.settings_manager.get_setting('minecraft.version.enable') or ''
        if kind != 'modpack' and (not directory or not version):
            QMessageBox.warning(self, '无法下载内容', '请先选择或安装一个 Minecraft 实例。')
            return
        game_version, loader = version, ''
        if directory and version:
            try:
                from core.content import instance_environment
                game_version, loader = instance_environment(directory, version)
            except (OSError, ValueError, TypeError) as exc:
                QMessageBox.warning(self, '无法读取实例', f'当前实例的版本信息无效：{exc}')
                return
        dialog = ContentDownloadDialog(self, game_version, loader, kind or 'mod')
        if kind in ('mod', 'resourcepack', 'shader', 'modpack'):
            dialog.kind.setCurrentIndex({'mod': 0, 'resourcepack': 1, 'shader': 2, 'modpack': 3}[kind])
        if dialog.exec() != QDialog.Accepted or not dialog.selected_version:
            return
        kind = dialog.kind.currentData()
        if kind != 'modpack' and (not directory or not version):
            QMessageBox.warning(self, '无法下载内容', '请先选择或安装一个 Minecraft 实例。')
            return
        target = (os.path.join(self.settings_manager.config_path, 'downloads')
                  if kind == 'modpack'
                  else self.settings_manager.get_minecraft_isolation_directory() or directory)
        title = dialog.selected_version.get('name') or dialog.selected_version.get('version_number') or '内容'
        task_version = f'{version + "-" if version else ""}{kind}-{title}'
        self.start_install(task_version, directory, content={'kind': kind, 'version': dialog.selected_version, 'target': target})

    @Slot(str, str)
    def resolve_version(self, task_id, version):
        task = self._find_task(task_id)
        if task and task['version'] != version:
            self._log(task, f"安装器生成的实例：{version}")
            task['version'] = version
            self._schedule_save()

    @Slot(str, str)
    def update_status(self, task_id, status):
        task = self._find_task(task_id)
        if task:
            if task["state"] == "等待中":
                task["state"] = "进行中"
            task["status"] = status
            self._log(task, status)
            self._update_row(task)
            self._schedule_save()

    @Slot(str, int, int)
    def update_progress(self, task_id, progress, maximum):
        task = self._find_task(task_id)
        if not task:
            return
        if progress >= 0:
            task["progress"] = progress
        if maximum >= 0:
            task["maximum"] = maximum
        self._update_row(task)
        self._schedule_save()

    @Slot(str, bool, str)
    def finish_task(self, task_id, succeeded, message):
        task = self._find_task(task_id)
        if task:
            cancelled = task["state"] == "正在取消"
            task["state"] = "已完成" if succeeded else ("已取消" if cancelled else "失败")
            task["status"] = message if succeeded else "安装失败"
            task["error"] = "" if succeeded or cancelled else message
            if cancelled:
                task["status"] = "已停止下载，点击重试可复用已校验文件。"
            task["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self._log(task, message)
            if succeeded:
                task["progress"] = task["maximum"] or task["progress"]
            self._persist_and_refresh()
            if succeeded and not self._closing and not task.get('content'):
                self._select_installed_version(task)
        self._workers.pop(task_id, None)

    def _select_installed_version(self, task):
        settings = self.settings_manager
        main_window = self.parent.parent
        started_page = getattr(main_window, "started_page", None)
        if started_page and started_page.current_client:
            self.installed.emit(task["version"], task["game_dir"])
            return
        current = os.path.normcase(os.path.abspath(settings.get_setting("minecraft.directory.enable") or "."))
        if current != os.path.normcase(task["game_dir"]):
            self.installed.emit(task["version"], task["game_dir"])
            return
        settings.set_setting("minecraft.version.enable", task["version"])
        settings.save_settings()

        version_page = getattr(main_window, "version_page", None)
        versions_page = getattr(version_page, "versions_page", None)
        if versions_page:
            versions_page.refresh_version_list(task["game_dir"])
        if started_page:
            started_page.launcher.minecraft_directory = task["game_dir"]
            started_page.instance_changed.emit()
        self.installed.emit(task["version"], task["game_dir"])

    def _find_task(self, task_id):
        return next((task for task in self._tasks if task.get("id") == task_id), None)

    def _persist_and_refresh(self):
        self._flush_history()
        self.refresh_tasks()

    def _schedule_save(self):
        if not self._save_timer.isActive():
            self._save_timer.start()

    def _flush_history(self):
        self._save_timer.stop()
        try:
            self._save_history()
        except OSError:
            logger.exception("Unable to persist download task history")

    def _log(self, task, message):
        log = task.setdefault("logs", [])
        log.append(datetime.now().strftime("%H:%M:%S") + "  " + message)
        del log[:-200]

    def refresh_tasks(self):
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._rows.clear()
        query = self.search.text().strip().casefold()
        selected = self.filter.currentText()
        tasks = [task for task in self._tasks if query in (task["version"] + " " + task["game_dir"]).casefold()
                 and (selected == "全部记录" or task["state"] == selected
                      or (selected == "正在安装" and task["state"] in self.ACTIVE))]
        if not tasks:
            empty = QLabel("还没有安装记录。选择一个 Minecraft 版本并点击安装后，进度和结果会显示在这里。")
            empty.setWordWrap(True)
            empty.setStyleSheet("color: rgba(255,255,255,0.68); padding: 18px;")
            self.list_layout.addWidget(empty)
        else:
            for task in tasks:
                row = self._create_task_row(task)
                self.list_layout.addWidget(row)
                self._rows[task["id"]] = row
        self.list_layout.addStretch(1)
        self.clear_button.setEnabled(any(task.get("state") not in self.ACTIVE for task in self._tasks))

    def _create_task_row(self, task):
        row = QWidget()
        row.setObjectName('downloadTask')
        row.setStyleSheet("QWidget#downloadTask { background-color: rgba(190, 183, 255, 0.10); border-radius: 8px; }")
        row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        row.setMinimumHeight(175 if not task.get('error') else 220)
        layout = QVBoxLayout(row)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(5)

        top = QHBoxLayout()
        name = QLabel(("整合包 " if task.get('modpack') else "Minecraft ") + task.get('version', ''))
        name.setTextFormat(Qt.PlainText)
        name.setStyleSheet("color: #f2f2f2; font-weight: bold;")
        state = QLabel(task.get("state", "未知"))
        state.setStyleSheet("color: #bfb4ff;")
        top.addWidget(name)
        top.addStretch(1)
        top.addWidget(state)
        layout.addLayout(top)

        path = QLabel(task["game_dir"])
        path.setToolTip(task["game_dir"])
        path.setWordWrap(True)
        path.setStyleSheet("color: rgba(255,255,255,0.5); font-size: 11px;")
        layout.addWidget(path)

        status = QLabel(task.get("status", ""))
        status.setWordWrap(True)
        status.setStyleSheet("color: rgba(255,255,255,0.72);")
        layout.addWidget(status)

        progress = QProgressBar()
        self._set_progress(progress, task)
        layout.addWidget(progress)

        created = task.get("created_at", "")
        if created:
            date = QLabel(created.replace("T", " ").replace("+00:00", " UTC"))
            date.setStyleSheet("color: rgba(255,255,255,0.45); font-size: 9px;")
            layout.addWidget(date)
        if task.get("error"):
            error = QLabel(task["error"])
            error.setWordWrap(True)
            error.setStyleSheet("color: #ff9b9b;")
            layout.addWidget(error)
        actions = QHBoxLayout()
        actions.addStretch()
        log = QPushButton("查看日志")
        log.clicked.connect(lambda checked=False, tid=task["id"]: self.show_log(tid))
        actions.addWidget(log)
        action = QPushButton("取消" if task["state"] in self.ACTIVE else "重新安装" if task["state"] == "已完成" else "重试")
        action.setEnabled(task["state"] != "正在取消" and not (task.get('modpack') and task['state'] == '已完成'))
        if task.get('modpack') and task['state'] == '已完成':
            action.setText('已导入')
        action.clicked.connect(lambda checked=False, tid=task["id"]: self.task_action(tid))
        actions.addWidget(action)
        layout.addLayout(actions)
        row._status = status
        row._state = state
        row._progress = progress
        return row

    def _set_progress(self, bar, task):
        maximum = int(task.get("maximum") or 0)
        current = int(task.get("progress") or 0)
        if task["state"] == "已完成":
            bar.setRange(0, 100)
            bar.setValue(100)
            bar.setFormat("安装完成")
        elif maximum > 0:
            bar.setRange(0, maximum)
            bar.setValue(min(current, maximum))
            bar.setFormat(f"%p%  ·  {current}/{maximum} 个文件")
        elif task["state"] in self.ACTIVE:
            bar.setRange(0, 0)
        else:
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setFormat(task["state"])
        bar.setStyleSheet("QProgressBar {border: none; background: #242232; color: white; text-align: center; min-height: 18px;} QProgressBar::chunk {background: #7859db;}")

    def _update_row(self, task):
        row = self._rows.get(task["id"])
        if row:
            row._status.setText(task["status"])
            row._state.setText(task["state"])
            self._set_progress(row._progress, task)

    def task_action(self, task_id):
        task = self._find_task(task_id)
        if not task:
            return
        if task["state"] in self.ACTIVE:
            task["state"] = "正在取消"
            task["status"] = "正在停止下载，已完成文件会保留…"
            self._workers[task_id].cancel_event.set()
            self._persist_and_refresh()
        elif task.get('modpack'):
            self.import_modpack(task['modpack'], task['version'], task['game_dir'])
        elif task.get('content'):
            self.start_install(task['version'], task['game_dir'], content=task['content'])
        else:
            self.start_install(task["version"], task["game_dir"], task.get("loader") or None,
                               task.get("base_version") or None,
                               task.get("loader_version") or None)

    def show_log(self, task_id):
        task = self._find_task(task_id)
        if not task:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Minecraft {task['version']} · 安装日志")
        dialog.resize(640, 400)
        dialog.setStyleSheet('QDialog { background: #211e2d; } '
                            'QTextEdit { background: #2c273b; color: #e8e1ef; '
                            'border: 1px solid #514461; border-radius: 7px; padding: 10px; }')
        layout = QVBoxLayout(dialog)
        text = QTextEdit()
        text.setReadOnly(True)
        layout.addWidget(text)
        def refresh():
            updated = "\n".join(task.get("logs", []))
            if text.toPlainText() != updated:
                text.setPlainText(updated)
                text.moveCursor(text.textCursor().MoveOperation.End)
        refresh()
        timer = QTimer(dialog)
        timer.timeout.connect(refresh)
        timer.start(1000)
        dialog.exec()

    def shutdown(self):
        if self._closing:
            return not self._workers
        self._closing = True
        for task_id in list(self._workers):
            task = self._find_task(task_id)
            if task and task["state"] in self.ACTIVE:
                self.task_action(task_id)
        self._flush_history()
        return not self._workers

    def clear_completed(self):
        self._tasks = [task for task in self._tasks if task.get("state") in self.ACTIVE]
        self._persist_and_refresh()

    def on_page_activate(self):
        self.refresh_tasks()

    def on_page_deactivate(self):
        pass
