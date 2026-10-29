"""Minecraft installation task history and progress UI."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import uuid
import time
from datetime import datetime, timezone

from PySide6.QtCore import QObject, Property, QRunnable, QThreadPool, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QVBoxLayout,
    QWidget,
)

from config.settings import get_settings_manager
from ui.pages.qml_host import QmlPage
from utils.path_helper import get_default_minecraft_dir, filesystem_path
from core.downloads import DownloadCancelled, MinecraftDownloader, download_error_message
from core.loaders import install_loader
from core.modpacks import suggested_name
from core.transfer_metrics import TransferMeter

logger = logging.getLogger(__name__)


class TaskHistoryController(QObject):
    """QML presentation model for the existing download task engine."""

    changed = Signal()
    logChanged = Signal()

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self._tasks = []
        self._query = ""
        self._filter = "全部记录"
        self._log_task_id = ""
        self._log_title = ""
        self._log_lines = []
        self._log_files = []
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
        return [dict({key: value for key, value in task.items() if key not in ('files', 'logs', '_last_status')},
                     canRetry=task['id'] in self.page._external_retries,
                     speed=task.get('speed', 0) if task.get('state') in TasksPage.ACTIVE and time.monotonic() - task.get('_speedAt', 0) < 3 else 0) for task in self._tasks
                if query in (task.get("version", "") + " " + task.get("game_dir", "") + " " +
                             " ".join(item.get('name', '') for item in task.get('files', []))).casefold()
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

    @Property("QVariantList", notify=logChanged)
    def logLines(self):
        return self._log_lines

    @Property('QVariantList', notify=logChanged)
    def currentFiles(self):
        return self._log_files

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
        self._log_files = []
        self._log_lines = []
        self.logChanged.emit()

    def set_tasks(self, tasks):
        self._tasks = tasks
        if not self._tasks_timer.isActive():
            self._tasks_timer.start()

    def _refresh_log(self):
        task = self.page._find_task(self._log_task_id)
        if task:
            self._log_lines = list(task.get("logs", []))
            order = {'failed': 0, 'retrying': 1, 'downloading': 2, 'verifying': 3, 'pending': 4}
            self._log_files = sorted([dict(item) for item in task.get('files', [])],
                                     key=lambda item: order.get(item.get('state'), 5))
            self.logChanged.emit()
        elif self._log_task_id:
            self.closeLog()


class DownloadWorkerSignals(QObject):
    status = Signal(str, str)
    # Byte totals may exceed Qt's signed 32-bit int (large modpacks).
    progress = Signal(str, object, object)
    file_event = Signal(str, object)
    resolved = Signal(str, str)
    downloaded = Signal(str, object)
    pack_ready = Signal(str, str)
    archive_identified = Signal(str, str)
    finished = Signal(str, bool, str)


class DownloadWorker(QRunnable):
    def __init__(self, task_id: str, version: str, game_dir: str, source: str,
                 loader=None, base_version=None, loader_version=None, java=None, modpack=None, api_key=None, content=None,
                 addons=None, isolated=True, archive_sha256=None, content_source=None):
        super().__init__()
        self.task_id = task_id
        self.version = version
        self.game_dir = game_dir
        self.source = source
        self.content_source = content_source
        self.loader = loader
        self.base_version = base_version
        self.loader_version = loader_version
        self.java = java
        self.modpack = modpack
        self.archive_sha256 = archive_sha256
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
            meter = TransferMeter()
            file_event = lambda event: self.signals.file_event.emit(self.task_id, meter.feed(event))
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
            if self.content and self.content.get('kind') == 'modpack' and (not self.modpack or not os.path.isfile(self.modpack)):
                from core.content import download_content
                files = download_content(self.content['version'], self.content['target'], 'modpack',
                                         self.cancel_event, status, progress, source=self.source, content_source=self.content_source,
                                         file_event=file_event)
                if len(files) != 1:
                    raise ValueError('整合包版本必须包含唯一的主文件')
                self.signals.downloaded.emit(self.task_id, files)
                self.modpack = files[0]
                self.signals.pack_ready.emit(self.task_id, self.modpack)
                status('整合包下载并校验完成，正在安装…')
            if self.modpack:
                from core.modpacks import ModpackImporter
                ModpackImporter(self.game_dir, self.source, self.java, self.cancel_event,
                                status, progress, self.api_key, content_source=self.content_source,
                                file_event=file_event).install(
                                    self.modpack, self.version, expected_archive_sha256=self.archive_sha256,
                                    archive_identified=lambda digest: self.signals.archive_identified.emit(self.task_id, digest))
            elif self.content:
                from core.content import download_content
                files = download_content(self.content['version'], self.content['target'], self.content['kind'],
                                         self.cancel_event, status, progress, source=self.source, content_source=self.content_source,
                                         file_event=file_event)
                self.signals.downloaded.emit(self.task_id, files)
            elif self.loader:
                version_id = install_loader(self.loader, self.base_version, self.loader_version,
                    self.game_dir, self.java, {"setStatus": status,
                    "setProgress": lambda current: progress(current, -1),
                    "setMax": lambda maximum: progress(-1, maximum),
                    "fileEvent": file_event}, self.cancel_event,
                    source=self.source)
                if not isinstance(version_id, str) or not version_id or version_id in ('.', '..') \
                        or any(char in version_id for char in ('/', '\\', ':')):
                    raise RuntimeError("加载器安装出的版本 ID 无效")
                self.version = version_id
            else:
                downloader = MinecraftDownloader(
                    self.game_dir, source=self.source, cancel=self.cancel_event,
                    status=status, progress=progress, file_event=file_event,
                )
                downloader.install(self.version)
            if not self.content or self.modpack:
                version_json = os.path.join(self.game_dir, "versions", self.version, f"{self.version}.json")
                if not filesystem_path(version_json).is_file():
                    raise RuntimeError("下载结束，但版本文件没有生成")
            if self.addons:
                from core.content import download_content
                target = os.path.join(self.game_dir, 'versions', self.version) if self.isolated else self.game_dir
                for addon in self.addons:
                    status('正在安装 ' + addon['name'])
                    download_content(addon['version'], target, 'mod', self.cancel_event, status, progress,
                                     source=self.source, content_source=self.content_source,
                                     file_event=file_event)
            if self.loader:
                self.signals.resolved.emit(self.task_id, self.version)
            message = '整合包导入完成' if self.modpack else '内容下载完成' if self.content else f"{self.loader + ' ' if self.loader else ''}安装完成"
            self.signals.finished.emit(self.task_id, True, message)
        except DownloadCancelled as exc:
            self.signals.finished.emit(self.task_id, False, str(exc))
        except Exception as exc:
            logger.exception("Download/install failed: version=%s kind=%s source=%s", self.version,
                             self.content.get('kind') if self.content else 'modpack' if self.modpack else 'game', self.source)
            self.signals.finished.emit(self.task_id, False, download_error_message(exc))


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
        self._file_indexes = {}
        self._workers = {}
        self._external_cancellations = {}
        self._external_retries = {}
        self._closing = False
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(4)
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
                limit = 5000 if task.get('kind') == 'room' else 200
                task['logs'] = [line for line in logs if isinstance(line, str)][-limit:] if isinstance(logs, list) else []
                files = task.get('files', [])
                task['files'] = [item for item in files if isinstance(item, dict) and isinstance(item.get('name'), str)] \
                    if isinstance(files, list) else []
                for item in task['files']:
                    for key in ('done', 'total', 'size'):
                        try:
                            item[key] = max(0, int(item.get(key) or 0))
                        except (ValueError, TypeError, OverflowError):
                            item[key] = 0
                    if item.get('state') in ('pending', 'downloading', 'verifying', 'retrying'):
                        item['state'] = 'interrupted'
                if task.get('state') not in (*self.ACTIVE, '已完成', '失败', '已取消', '已中断'):
                    task['state'] = '已中断'
                if task.get("state") in self.ACTIVE:
                    task["state"] = "已中断"
                    task["status"] = ("上次房间配置准备未完成，请回到房间重新准备。" if task.get('kind') == 'room'
                                      else "上次安装未完成，可点击重试；已校验的文件会复用。")
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
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.host)

    @property
    def quick(self):
        return self.host.quick

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
            (task.get("version") == version or (content and content == task.get('content')))
            and task.get("game_dir") == game_dir
            and task.get("state") in self.ACTIVE
            for task in self._tasks
        ):
            self.parent.on_progress_clicked()
            return False

        if content and content.get('kind') == 'modpack':
            version = self._available_pack_name(content, game_dir)

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
        self._start_worker(task, api_key)
        self.parent.on_progress_clicked()
        return True

    def _start_worker(self, task, api_key=None):
        source = self.settings_manager.get_setting(
            "settings.general.mirrors", "自动选择下载源（自动选择速度快的源）"
        )
        java = self.settings_manager.get_version_setting("java.path", None)
        task_id = task['id']
        task['source'] = source
        from core.content_mirrors import configured_source
        task['content_source'] = configured_source(self.settings_manager)
        worker = DownloadWorker(task_id, task['version'], task['game_dir'], source,
                                task.get('loader') or None, task.get('base_version') or None,
                                task.get('loader_version') or None, java,
                                task.get('modpack') or None, api_key, task.get('content') or None,
                                addons=task.get('addons') or [],
                                isolated=bool(self.settings_manager.get_version_setting('minecraft.isolation', True)),
                                archive_sha256=task.get('archive_sha256'),
                                content_source=task['content_source'])
        worker.signals.status.connect(self.update_status)
        worker.signals.progress.connect(self.update_progress)
        worker.signals.file_event.connect(self.update_file_event)
        worker.signals.resolved.connect(self.resolve_version)
        worker.signals.downloaded.connect(self.resolve_files)
        worker.signals.pack_ready.connect(self.resolve_pack)
        worker.signals.archive_identified.connect(self.resolve_archive)
        worker.signals.finished.connect(self.finish_task)
        self._workers[task_id] = worker
        self.pool.start(worker)
        self._schedule_save()

    def track_room_preparation(self, title, game_dir, game, cancel, *, retry=None, task_id=None):
        """Track the lobby's async installer in the same persistent history."""
        previous = self._find_task(task_id) if task_id else None
        task_id = previous['id'] if previous else uuid.uuid4().hex
        task = dict(id=task_id, version=title, game_dir=os.path.abspath(game_dir),
                    kind='room', loader=game.get('loader', ''), base_version=game.get('version', ''),
                    loader_version=game.get('loader_version', ''),
                    state='进行中', status='正在核对房间文件…', progress=0, maximum=0,
                    created_at=datetime.now(timezone.utc).isoformat(timespec='seconds'),
                    error='', logs=list(previous.get('logs', [])) if previous else [], files=[])
        if previous:
            previous.clear()
            previous.update(task)
            task = previous
        else:
            self._tasks.insert(0, task)
        self._file_indexes.pop(task_id, None)
        live = [item for item in self._tasks if item['state'] in self.ACTIVE]
        ended = [item for item in self._tasks if item['state'] not in self.ACTIVE]
        self._tasks = sorted(live + ended[:max(0, 200 - len(live))],
                             key=lambda item: item['created_at'], reverse=True)
        self._external_cancellations[task_id] = cancel
        if retry:
            self._external_retries[task_id] = retry
        self._log(task, f"准备房间配置：Minecraft {game.get('version', '')} · {game.get('loader', '')} {game.get('loader_version', '')}")
        self._persist_and_refresh()
        return task_id

    def room_preparation_event(self, task_id, event):
        task = self._find_task(task_id)
        if not task or task.get('kind') != 'room':
            return
        kind = event.get('kind')
        if kind == 'manifest':
            task['files'] = [dict(item, state='pending') for item in event['files'] + event.get('resources', [])]
            self._file_indexes.pop(task_id, None)
            self._log(task, f"已收到 {len(task['files'])} 个模组，来源：房主，下载后逐个校验 SHA-256。")
        elif kind == 'download':
            self.update_file_event(task_id, event)
        elif kind in ('file', 'progress'):
            if 'task_speed' in event:
                task.update(speed=event['task_speed'], _speedAt=time.monotonic())
            for item in task.get('files', []):
                if item['name'] == event['name']:
                    item.update({key: value for key, value in event.items() if key != 'kind'})
            if event.get('state') == 'verified':
                self._log(task, f"已下载并校验：{event['name']} · {event['size']:,} 字节 · SHA-256 {event['sha256']} · {event['path']}")
            elif event.get('state') == 'failed':
                self._log(task, f"模组下载失败：{event['name']} · {event.get('error') or '未知错误'}")
        elif kind == 'complete':
            task['installed_version'] = event['version']
            self._log(task, '已生成隔离实例：' + event['version'])
        self._schedule_save()
        self._update_row(task)

    def finish_room_preparation(self, task_id, succeeded, message, cancelled=False):
        task = self._find_task(task_id)
        self._external_cancellations.pop(task_id, None)
        if not task:
            return
        task.update(state='已完成' if succeeded else '已取消' if cancelled else '失败',
                    status=message, error='' if succeeded or cancelled else message,
                    finished_at=datetime.now(timezone.utc).isoformat(timespec='seconds'))
        if succeeded:
            self._external_retries.pop(task_id, None)
            task['progress'] = task['maximum'] or 1
            task['maximum'] = task['maximum'] or 1
        self._log(task, message)
        self._persist_and_refresh()

    def _available_pack_name(self, content, game_dir):
        files = content.get('version', {}).get('files') or []
        primary = next((item for item in files if item.get('primary')), files[0] if files else {})
        base = suggested_name(primary.get('filename') or 'Downloaded-Modpack.zip')
        identity, index = base, 2
        occupied = {item['version'].casefold() for item in self._tasks
                    if item['game_dir'] == game_dir and item['state'] in self.ACTIVE}
        while os.path.exists(os.path.join(game_dir, 'versions', identity)) or identity.casefold() in occupied:
            identity = f'{base}-{index}'
            index += 1
        return identity

    def _resume_modpack(self, task):
        if self._closing or (task['state'] == '已完成' and task.get('modpack')):
            return
        # Old releases marked downloaded archives complete without installing.
        if task['state'] == '已完成':
            task['version'] = self._available_pack_name(task['content'], task['game_dir'])
        if any(item.get('version') == task['version'] and item.get('game_dir') == task['game_dir']
               and item.get('state') in self.ACTIVE for item in self._tasks):
            self.parent.on_progress_clicked()
            return
        task.update(state='等待中', status='正在恢复整合包安装，复用已校验的下载文件…',
                    error='', progress=0, maximum=0,
                    resumed_at=datetime.now(timezone.utc).isoformat(timespec='seconds'))
        task.pop('finished_at', None)
        self._log(task, task['status'])
        self.view_controller.resetFilters()
        self._persist_and_refresh()
        self._start_worker(task)
        self.parent.on_progress_clicked()

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
    def resolve_pack(self, task_id, archive):
        task = self._find_task(task_id)
        if task:
            task['modpack'] = archive
            self._schedule_save()

    @Slot(str, str)
    def resolve_archive(self, task_id, digest):
        task = self._find_task(task_id)
        if task:
            task['archive_sha256'] = digest
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
            if task.get('_last_status') != status:
                self._log(task, status)
                task['_last_status'] = status
            self._update_row(task)
            self._schedule_save()

    @Slot(str, object, object)
    def update_progress(self, task_id, progress, maximum):
        task = self._find_task(task_id)
        if not task:
            return
        if maximum >= 0:
            if progress < 0 or maximum != task.get('maximum'):
                task['progress'] = 0
            task["maximum"] = maximum
        if progress >= 0:
            task["progress"] = progress
        # Different installation phases count bytes/files/processors. Never
        # interpret an old phase's count against the new phase's total.
        task['progress'] = max(0, min(task['progress'], task['maximum'])) if task['maximum'] else 0
        self._update_row(task)
        self._schedule_save()

    @Slot(str, object)
    def update_file_event(self, task_id, event):
        task = self._find_task(task_id)
        if not task:
            return
        files = task.setdefault('files', [])
        if task_id not in self._file_indexes:
            self._file_indexes[task_id] = {item.get('key', item['name']): item for item in files}
        index = self._file_indexes[task_id]
        key = event.get('key', event['name'])
        entry = index.get(key)
        if entry is None:
            entry = dict(name=event['name'], done=0, total=0, state='pending')
            files.append(entry)
            index[key] = entry
        entry.update(event)
        task.update(speed=event.get('task_speed', 0), _speedAt=time.monotonic())
        self._update_row(task)
        # Only the open detail view needs byte updates; avoid rebuilding every
        # task row for each chunk of thousands of assets.
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
            for item in task.get('files', []):
                if item.get('state') in ('pending', 'downloading', 'verifying', 'retrying'):
                    item['state'] = 'cancelled' if cancelled else 'interrupted'
            self._log(task, message)
            if succeeded:
                task["progress"] = task["maximum"] or task["progress"]
            self._persist_and_refresh()
            if succeeded and not self._closing and (not task.get('content') or task.get('modpack')):
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
        self.parent.content_page.controller.refreshContext()

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
        del log[:-(5000 if task.get('kind') == 'room' else 200)]

    def refresh_tasks(self):
        self.view_controller.set_tasks(self._tasks)

    def _update_row(self, task):
        self.view_controller.set_tasks(self._tasks)

    def task_action(self, task_id):
        task = self._find_task(task_id)
        if not task:
            return
        if task.get('kind') == 'room':
            cancel = self._external_cancellations.get(task_id)
            if cancel and task['state'] in self.ACTIVE:
                cancel.set()
                task.update(state='正在取消', status='正在停止房间配置下载…')
                self._persist_and_refresh()
            elif task['state'] not in self.ACTIVE and task_id in self._external_retries:
                try:
                    self._external_retries[task_id](task_id)
                except ValueError as exc:
                    task.update(error=str(exc), status='房间下载暂时无法重试')
                    self._log(task, str(exc))
                    self._persist_and_refresh()
            return
        if task["state"] in self.ACTIVE:
            task["state"] = "正在取消"
            task["status"] = "正在停止下载，已完成文件会保留…"
            self._workers[task_id].cancel_event.set()
            self._persist_and_refresh()
        elif task.get('modpack') or task.get('content', {}).get('kind') == 'modpack':
            self._resume_modpack(task)
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
        for cancel in self._external_cancellations.values():
            cancel.set()
        for task_id in list(self._workers):
            task = self._find_task(task_id)
            if task and task["state"] in self.ACTIVE:
                self.task_action(task_id)
        self._flush_history()
        return not self._workers

    def clear_completed(self):
        self._tasks = [task for task in self._tasks if task.get("state") in self.ACTIVE]
        self._external_retries = {task_id: retry for task_id, retry in self._external_retries.items()
                                  if self._find_task(task_id)}
        self._file_indexes = {task_id: index for task_id, index in self._file_indexes.items()
                              if self._find_task(task_id)}
        self._persist_and_refresh()

    def on_page_activate(self):
        self.refresh_tasks()

    def on_page_deactivate(self):
        pass
