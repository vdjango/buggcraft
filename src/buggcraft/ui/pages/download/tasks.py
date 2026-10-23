"""Minecraft installation task history and progress UI."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone

from PySide6.QtCore import QObject, Property, QRunnable, QThreadPool, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QVBoxLayout,
    QWidget,
)

from config.settings import get_settings_manager
from ui.pages.qml_host import QmlPage
from utils.path_helper import get_default_minecraft_dir
from core.downloads import DownloadCancelled, MinecraftDownloader
from core.loaders import install_loader

logger = logging.getLogger(__name__)


class TaskHistoryController(QObject):
    """QML presentation model for the existing download task engine."""

    changed = Signal()

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self._tasks = []
        self._query = ""
        self._filter = "全部记录"
        self._log_task_id = ""
        self._log_title = ""
        self._log_lines = []
        self._tasks_timer = QTimer(self)
        self._tasks_timer.setSingleShot(True)
        self._tasks_timer.setInterval(80)
        self._tasks_timer.timeout.connect(self.changed.emit)
        self._log_timer = QTimer(self)
        self._log_timer.setInterval(500)
        self._log_timer.timeout.connect(self._refresh_log)

    @Property("QVariantList", notify=changed)
    def tasks(self):
        query = self._query.casefold()
        return [task for task in self._tasks
                if query in (task.get("version", "") + " " + task.get("game_dir", "")).casefold()
                and (self._filter == "全部记录" or task.get("state") == self._filter
                     or (self._filter in ("进行中", "正在安装") and task.get("state") in TasksPage.ACTIVE))]

    @Property(bool, notify=changed)
    def canClear(self):
        return any(task.get("state") not in TasksPage.ACTIVE for task in self._tasks)

    @Property(str, notify=changed)
    def filterValue(self):
        return self._filter

    @Property(str, notify=changed)
    def query(self):
        return self._query

    @Property(str, notify=changed)
    def logTitle(self):
        return self._log_title

    @Property("QVariantList", notify=changed)
    def logLines(self):
        return self._log_lines

    @Slot(str)
    def setQuery(self, value):
        self._query = value.strip()
        self.changed.emit()

    @Slot(str)
    def setFilter(self, value):
        self._filter = value
        self.changed.emit()

    @Slot()
    def resetFilters(self):
        self._query = ""
        self._filter = "全部记录"
        self.changed.emit()

    @Slot()
    def clearCompleted(self):
        self.page.clear_completed()

    @Slot(str)
    def taskAction(self, task_id):
        self.page.task_action(task_id)

    @Slot(str)
    def showLog(self, task_id):
        task = self.page._find_task(task_id)
        if not task:
            return
        self._log_task_id = task_id
        self._log_title = f"{task['version']} · 任务日志"
        self._refresh_log()
        self._log_timer.start()
        self.changed.emit()

    @Slot()
    def closeLog(self):
        self._log_timer.stop()
        self._log_task_id = ""

    def set_tasks(self, tasks):
        self._tasks = tasks
        if not self._tasks_timer.isActive():
            self._tasks_timer.start()

    def _refresh_log(self):
        task = self.page._find_task(self._log_task_id)
        if task:
            self._log_lines = list(task.get("logs", []))
            self.changed.emit()


class DownloadWorkerSignals(QObject):
    status = Signal(str, str)
    progress = Signal(str, int, int)
    resolved = Signal(str, str)
    downloaded = Signal(str, object)
    finished = Signal(str, bool, str)


class DownloadWorker(QRunnable):
    def __init__(self, task_id: str, version: str, game_dir: str, source: str,
                 loader=None, base_version=None, loader_version=None, java=None, modpack=None, api_key=None, content=None,
                 addons=None, isolated=True):
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
        self.addons = addons or []
        self.isolated = isolated
        self.cancel_event = threading.Event()
        self.signals = DownloadWorkerSignals()

    @Slot()
    def run(self):
        try:
            progress = lambda current, maximum: self.signals.progress.emit(
                self.task_id, int(current), int(maximum)
            )
            status = lambda value: self.signals.status.emit(self.task_id, str(value))
            if self.addons:
                from core.loader_rules import incompatibility
                for addon in self.addons:
                    if addon['name'] not in ('Fabric API', 'QSL/QFAPI') or self.loader not in ('Fabric', 'Quilt') \
                            or incompatibility(addon['name'], self.loader):
                        raise ValueError('API 与所选加载器不兼容')
                    supported = addon['version'].get('game_versions', [])
                    if supported and self.base_version not in supported:
                        raise ValueError(addon['name'] + ' 不支持所选游戏版本')
            if self.modpack:
                from core.modpacks import ModpackImporter
                ModpackImporter(self.game_dir, self.source, self.java, self.cancel_event,
                                status, progress, self.api_key).install(self.modpack, self.version)
            elif self.content:
                from core.content import download_content
                files = download_content(self.content['version'], self.content['target'], self.content['kind'],
                                         self.cancel_event, status, progress)
                self.signals.downloaded.emit(self.task_id, files)
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
            if self.addons:
                from core.content import download_content
                target = os.path.join(self.game_dir, 'versions', self.version) if self.isolated else self.game_dir
                for addon in self.addons:
                    status('正在安装 ' + addon['name'])
                    download_content(addon['version'], target, 'mod', self.cancel_event, status, progress)
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
        self._closing = False
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.view_controller = TaskHistoryController(self)
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
        self.host = QmlPage(self, self.resource_path, 'TaskHistory.qml', 'taskHistory', self.view_controller)
        self.quick = self.host.quick
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.host)

    def start_install(self, version: str, game_dir: str, loader=None, base_version=None,
                      loader_version=None, modpack=None, api_key=None, content=None, addons=None):
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
            "addons": addons or [],
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
        self.view_controller.resetFilters()
        self._persist_and_refresh()

        source = self.settings_manager.get_setting(
            "settings.general.mirrors", "自动选择下载源（自动选择速度快的源）"
        )
        java = self.settings_manager.get_version_setting("java.path", None)
        worker = DownloadWorker(task_id, version, game_dir, source, loader, base_version, loader_version, java,
                                modpack, api_key, content, addons=addons,
                                isolated=bool(self.settings_manager.get_version_setting('minecraft.isolation', True)))
        worker.signals.status.connect(self.update_status)
        worker.signals.progress.connect(self.update_progress)
        worker.signals.resolved.connect(self.resolve_version)
        worker.signals.downloaded.connect(self.resolve_files)
        worker.signals.finished.connect(self.finish_task)
        self._workers[task_id] = worker
        self.pool.start(worker)
        self.parent.on_progress_clicked()
        return True

    def import_modpack(self, archive='', identity='', game_dir=None):
        controller = self.parent.content_page.controller
        controller.setImportDirectory(game_dir or self.settings_manager.get_setting('minecraft.directory.enable') or '')
        controller.pack_name = identity
        if archive:
            controller.inspectPack(archive)
        self.parent.open_content('modpack', 'import')

    def download_content(self, kind=None):
        self.parent.open_content(kind or 'mod', 'browse')

    @Slot(str, object)
    def resolve_files(self, task_id, files):
        task = self._find_task(task_id)
        if task:
            task['downloaded_files'] = files
            self._schedule_save()

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
        self.view_controller.set_tasks(self._tasks)

    def _update_row(self, task):
        self.view_controller.set_tasks(self._tasks)

    def task_action(self, task_id):
        task = self._find_task(task_id)
        if not task:
            return
        if task["state"] in self.ACTIVE:
            task["state"] = "正在取消"
            task["status"] = "正在停止下载，已完成文件会保留…"
            self._workers[task_id].cancel_event.set()
            self._persist_and_refresh()
        elif task.get('state') == '已完成' and task.get('content', {}).get('kind') == 'modpack' and task.get('downloaded_files'):
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(os.path.abspath(task['downloaded_files'][0]))))
        elif task.get('modpack'):
            self.import_modpack(task['modpack'], task['version'], task['game_dir'])
        elif task.get('content'):
            self.start_install(task['version'], task['game_dir'], content=task['content'])
        else:
            self.start_install(task["version"], task["game_dir"], task.get("loader") or None,
                               task.get("base_version") or None,
                               task.get("loader_version") or None, addons=task.get('addons') or [])

    def show_log(self, task_id):
        self.view_controller.showLog(task_id)

    def shutdown(self):
        self.view_controller._log_timer.stop()
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
