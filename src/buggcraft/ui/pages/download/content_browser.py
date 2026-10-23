"""QML-backed browser for mods, packs, shaders, and modpacks."""
from __future__ import annotations

from pathlib import Path
import logging
import re
from html.parser import HTMLParser

from PySide6.QtCore import QObject, Property, QRunnable, QThreadPool, Signal, Slot
from PySide6.QtWidgets import QFileDialog, QWidget, QVBoxLayout

from config.settings import get_settings_manager
from core.content import ContentCatalogue, instance_environment
from core.modpacks import inspect_pack, instance_name, suggested_name
from ui.pages.qml_host import QmlPage

logger = logging.getLogger(__name__)


class _PlainDescription(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.skip += 1
        if tag in ('p', 'div', 'br', 'li', 'h1', 'h2', 'h3'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.skip = max(0, self.skip - 1)

    def handle_data(self, value):
        if not self.skip:
            self.parts.append(value)


def project_description(value, html=False):
    value = str(value or '')[:100000]
    if html or re.search(r'<(?:p|div|img|a|br|details|summary|h[1-6])\b', value, re.I):
        parser = _PlainDescription()
        parser.feed(value)
        value = ''.join(parser.parts)
    # Images remain on the original project page; details never pull a large
    # collection of external images just to show text.
    return re.sub(r'!\[[^\]]*\](?:\([^)]*\)|\[[^\]]*\])?', '', value).strip()[:24000]

class _SearchSignals(QObject):
    finished = Signal(int, str, object, str)
    progress = Signal(int, object)


class _SearchWorker(QRunnable):
    def __init__(self, request, mode, callback):
        super().__init__()
        self.request = request
        self.mode = mode
        self.callback = callback
        self.signals = _SearchSignals()
        self.signals.finished.connect(callback)

    @Slot()
    def run(self):
        try:
            mode, action = self.mode
            self.signals.finished.emit(self.request, mode, action(), "")
        except Exception as exc:
            self.signals.finished.emit(self.request, self.mode[0], None, str(exc))


class ContentBrowserController(QObject):
    changed = Signal()
    pageRequested = Signal(str)

    def __init__(self, download_pages):
        super().__init__(download_pages)
        self.download_pages = download_pages
        self.settings = get_settings_manager()
        self.catalogue = ContentCatalogue()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.request_id = 0
        self.kind = "mod"
        self.source = '自动'
        self.status = "选择内容类型并搜索。"
        self.busy = False
        self.results = []
        self.versions = []
        self.selected_version = -1
        self.selected_project = None
        self.pack_path = ""
        self.pack_name = ""
        self.pack_summary = "支持 CurseForge ZIP 和 Modrinth ZIP / MRPACK，可拖入启动器任意页面。"
        self.pack_error = ""
        self.view = "browse"
        self.import_directory = ""
        self.query = ""
        self.has_more = False
        self.offset = 0
        self.page_size = 20
        self.details_busy = False
        self._append = False
        self._all_versions = []
        self._version_has_more = False
        self._version_offset = 0
        self.file_query = ''
        self._instance_context = self._context_key()

    def _target(self):
        directory = self.settings.get_setting('minecraft.directory.enable') or ''
        if self.kind == 'modpack':
            from utils.path_helper import get_default_minecraft_dir
            return str((Path(directory) if directory else Path(get_default_minecraft_dir())) / 'downloads' / 'modpacks')
        return self.settings.get_minecraft_isolation_directory() or directory

    def _context_key(self):
        return (self.settings.get_setting('minecraft.directory.enable') or '',
                self.settings.get_setting('minecraft.version.enable') or '',
                self.settings.get_minecraft_isolation_directory() or '')

    @Property('QVariantMap', notify=changed)
    def viewState(self):
        return {key: getattr(self, key) for key in (
            'kind', 'status', 'busy', 'results', 'versions', 'selected_version',
            'selected_project', 'pack_path', 'pack_name', 'pack_summary', 'pack_error',
            'view', 'import_directory', 'source', 'query', 'has_more', 'details_busy', 'file_query')} | {
                'instance': self.settings.get_setting('minecraft.version.enable') or '尚未选择',
                'target': self._target(), 'game_version': self._context()[2],
                'loader': self._context()[3],
                'has_more_versions': len(self.versions) < len(self._filtered_versions()) or self._version_has_more,
                'selected_file': self.versions[self.selected_version] if 0 <= self.selected_version < len(self.versions) else {},
                'can_install': bool(self._context()[0] and self._context()[1])}

    @Slot()
    @Slot(str)
    def refreshContext(self, _version=''):
        context = self._context_key()
        if context == self._instance_context:
            return
        self._instance_context = context
        # The instance changes the destination and advice, never the catalogue.
        self.versions = [self._version_row(item) for item in self.versions]
        self.changed.emit()

    @Slot(str)
    def setQuery(self, query):
        self.query = query

    @Slot(str)
    def setSource(self, source):
        if source not in self.catalogue.SOURCES or source == self.source:
            return
        self.source = source
        query = self.query
        self.setKind(self.kind)
        if self.view == 'browse':
            self.search(query)

    @Slot(str)
    def setKind(self, kind):
        if kind not in ("mod", "resourcepack", "shader", "modpack"):
            return
        self.kind = kind
        self.request_id += 1
        self.busy = False
        self.selected_project = None
        self.results = []
        self.versions = []
        self.selected_version = -1
        self._all_versions = []
        self.has_more = False
        self.details_busy = False
        self.status = ""
        self.query = ""
        self.changed.emit()

    @Slot(str)
    def setView(self, view):
        if view not in ("browse", "import", "detail"):
            return
        self.view = view
        self.changed.emit()
        if view == "browse" and not self.results and not self.busy:
            self.search("")

    @Slot()
    def returnFromImport(self):
        self.view = 'browse'
        self.changed.emit()
        self.pageRequested.emit('browse')

    @Slot(str)
    def setImportDirectory(self, directory):
        self.import_directory = directory or ""
        self.changed.emit()

    def _context(self):
        directory = self.settings.get_setting("minecraft.directory.enable") or ""
        identity = self.settings.get_setting("minecraft.version.enable") or ""
        key = directory, identity
        if getattr(self, '_environment_key', None) == key:
            return self._environment
        game, loader = "", ""
        if directory and identity:
            try:
                game, loader = instance_environment(directory, identity)
            except (OSError, ValueError, TypeError):
                logger.warning('Cannot resolve content compatibility for instance %s', identity, exc_info=True)
        self._environment_key = key
        self._environment = directory, identity, game, loader
        return self._environment

    @Slot(str)
    def search(self, query):
        self._start_search(query, False)

    @Slot()
    def loadMore(self):
        if self.has_more and not self.busy and self.view == 'browse':
            self._start_search(self.query, True)

    @Slot()
    def refresh(self):
        if self.view == 'browse' and not self.busy:
            self.search(self.query)

    def _start_search(self, query, append):
        self.query = query
        self._instance_context = self._context_key()
        self.request_id += 1
        request = self.request_id
        # Browsing is independent of the selected instance. Compatibility is
        # advice in project details, never an implicit search restriction.
        game = loader = ''
        self._append = append
        if not append:
            self.results = []
            self.offset = 0
        self.has_more = False
        self.versions = []
        self.selected_version = -1
        self.status = "正在搜索…"
        self.selected_project = None
        self.details_busy = False
        self.busy = True
        self.changed.emit()
        kind = self.kind
        source = self.source
        offset = self.offset
        logger.info('Content query started: request=%s kind=%s game=%s loader=%s source=%s', request, kind, game, loader, source)
        worker = _SearchWorker(request, ("search", None), self._query_finished)
        worker.signals.progress.connect(self._query_progress)
        signals = worker.signals
        worker.mode = ("search", lambda: self.catalogue.search(
            query.strip(), kind, game, loader, source,
            progress=(None if append else lambda hits: signals.progress.emit(request, hits)),
            offset=offset, limit=self.page_size, page_info=True))
        self.pool.start(worker)

    def _project_rows(self, data):
        return [dict(hit, display_title=hit.get("title") or hit.get("name") or hit.get("slug") or "未命名项目",
                     display_summary=(hit.get("description") or "").replace("\n", " ")[:180])
                for hit in (data or []) if isinstance(hit, dict)]

    @Slot(int, object)
    def _query_progress(self, request, data):
        if request != self.request_id:
            return
        self.results = self._project_rows(data)
        self.status = ""
        self.changed.emit()

    @Slot(int)
    def chooseProject(self, index):
        if index < 0 or index >= len(self.results):
            return
        self.request_id += 1
        request = self.request_id
        self.selected_project = self.results[index]
        self.view = 'detail'
        game = loader = ''
        self.versions = []
        self.selected_version = -1
        self._all_versions = []
        self._version_has_more = False
        self._version_offset = 0
        self.file_query = ''
        self.details_busy = True
        self.status = "正在读取可用版本…"
        self.busy = True
        self.changed.emit()
        project = self.selected_project
        kind = self.kind
        action = lambda: self.catalogue.versions(project, game, loader, kind, page_info=True)
        self.pool.start(_SearchWorker(request, ("versions", action), self._query_finished))
        self.pool.start(_SearchWorker(request, ('details', lambda: self.catalogue.project(project, kind)), self._query_finished))

    @Slot()
    def backToResults(self):
        self.request_id += 1
        self.view = 'browse'
        self.busy = self.details_busy = False
        self.selected_project = None
        self.status = ''
        self.changed.emit()

    def _version_row(self, item):
        _, _, game, loader = self._context()
        games = [str(value) for value in item.get('game_versions', [])]
        loaders = [str(value).lower() for value in item.get('loaders', [])]
        if self.kind == 'modpack':
            advice, state = '整合包将导入为独立实例，不改变当前游戏', 'info'
        elif not game:
            advice, state = '尚未选择安装实例，可先浏览全部版本', 'unknown'
        elif games and game not in games:
            advice, state = '未声明支持当前 Minecraft ' + game + '，请自行确认', 'warning'
        elif self.kind == 'mod' and loaders and loader not in loaders:
            advice, state = '加载器不匹配：文件支持 ' + ' / '.join(loaders) + '，当前为 ' + (loader or '原版'), 'warning'
        elif not games:
            advice, state = '作者未提供完整兼容信息，请查看项目说明', 'unknown'
        else:
            advice, state = '支持当前 Minecraft ' + game + (' · ' + loader if loader else ''), 'compatible'
        files = item.get('files') or []
        primary = next((file for file in files if file.get('primary')), files[0] if files else {})
        size = primary.get('size') or 0
        return dict(item, display_name=item.get('name') or item.get('version_number') or '未知版本',
                    display_date=(item.get('date_published') or '')[:10],
                    game_versions_label=' / '.join(games) or '作者未声明', loaders_label=' / '.join(loaders) or '未限定',
                    filename=primary.get('filename', ''), file_size_label=f'{size / 1024 ** 2:.1f} MiB' if size else '',
                    compatibility=advice, compatibility_state=state,
                    channel_label={'release': '正式版', 'beta': '测试版', 'alpha': '预览版'}.get(item.get('version_type'), '版本文件'))

    @Slot()
    def loadMoreVersions(self):
        if self.busy or not self.selected_project:
            return
        records = self._filtered_versions()
        if len(self.versions) < len(records):
            self.versions = [self._version_row(item) for item in records[:len(self.versions) + 30]]
            self.changed.emit()
        elif self._version_has_more:
            self.busy = True
            project, kind, offset = self.selected_project, self.kind, self._version_offset
            self.changed.emit()
            self.pool.start(_SearchWorker(self.request_id, ('versions_more', lambda:
                self.catalogue.versions(project, '', '', kind, offset=offset, page_info=True)), self._query_finished))

    def _filtered_versions(self):
        words = self.file_query.casefold().split()
        if not words:
            return self._all_versions
        def matches(item):
            text = ' '.join(str(value) for value in [item.get('name', ''), item.get('version_number', ''),
                *item.get('game_versions', []), *item.get('loaders', []),
                *(file.get('filename', '') for file in item.get('files', []))]).casefold()
            return all(word in text for word in words)
        return [item for item in self._all_versions if matches(item)]

    @Slot(str)
    def setFileQuery(self, query):
        self.file_query = query[:128]
        self.versions = [self._version_row(item) for item in self._filtered_versions()[:30]]
        self.selected_version = 0 if self.versions else -1
        self.changed.emit()

    @Slot(int, str, object, str)
    def _query_finished(self, request, mode, data, error):
        if request != self.request_id:
            return
        if mode == 'details':
            self.details_busy = False
            if self.selected_project:
                if not error and isinstance(data, dict):
                    body = project_description(data.get('body'), data.get('body_html', False))
                    self.selected_project = dict(self.selected_project, **data)
                    self.selected_project['body_text'] = body
                    games = self.selected_project.get('game_versions') or self.selected_project.get('versions') or []
                    current = self._context()[2]
                    self.selected_project['game_versions'] = sorted(set(map(str, games)), key=lambda value: (
                        value == current, bool(re.fullmatch(r'\d+(?:\.\d+)+', value)),
                        tuple(map(int, re.findall(r'\d+', value))), value), reverse=True)
                elif error:
                    self.selected_project = dict(self.selected_project, detail_error='详情暂不可用，可继续选择文件或查看原站。')
            self.changed.emit()
            return
        self.busy = False
        logger.info('Content query finished: request=%s mode=%s count=%s error=%s', request, mode, len(data or []), error)
        if error:
            self.status = "获取失败：" + error
            if mode == 'search' and self._append:
                self.has_more = True
        elif mode == "search":
            hits = data.get('hits', []) if isinstance(data, dict) else data or []
            rows = self._project_rows(hits)
            previous = self.results if self._append else []
            known = {(row.get('source'), row.get('project_id')) for row in previous}
            fresh = [row for row in rows if (row.get('source'), row.get('project_id')) not in known]
            self.results = previous + fresh
            self.has_more = bool(data.get('has_more')) if isinstance(data, dict) else len(rows) >= self.page_size
            if self._append and not fresh:
                self.has_more = False
            self.offset += self.page_size
            self.status = '；'.join(data.get('warnings', [])) if isinstance(data, dict) else ''
        else:
            raw = data.get('versions', []) if isinstance(data, dict) else data or []
            records = [item for item in raw if isinstance(item, dict)]
            if mode == 'versions':
                self._all_versions = records
            else:
                known = {item.get('id') for item in self._all_versions}
                self._all_versions.extend(item for item in records if item.get('id') not in known)
            self._version_offset = data.get('next_offset', self._version_offset + 50) if isinstance(data, dict) else self._version_offset + 50
            self._version_has_more = bool(data.get('has_more')) if isinstance(data, dict) else (
                self.selected_project.get('source') == 'CurseForge' and len(records) >= 50)
            count = 30 if mode == 'versions' else len(self.versions) + 30
            self.versions = [self._version_row(item) for item in self._filtered_versions()[:count]]
            if mode == 'versions':
                self.selected_version = 0 if self.versions else -1
            self.status = '' if self.versions else '项目暂未提供可下载文件。'
        self.changed.emit()

    @Slot(int)
    def selectVersion(self, index):
        self.selected_version = index if 0 <= index < len(self.versions) else -1
        self.changed.emit()

    @Slot()
    def downloadSelected(self):
        if self._context_key() != self._instance_context:
            self.refreshContext()
            self.status = "安装实例已切换，请确认下方目标目录后再次点击安装。"
            self.changed.emit()
            return
        if self.selected_version < 0 or self.selected_version >= len(self.versions):
            self.status = "请先选择一个下载版本。"
            self.changed.emit()
            return
        directory, identity, _, _ = self._context()
        if self.kind != "modpack" and not (directory and identity):
            self.status = "请先选择一个已安装的 Minecraft 实例。"
            self.changed.emit()
            return
        if self.kind == "modpack":
            from utils.path_helper import get_default_minecraft_dir
            root = Path(directory) if directory else Path(get_default_minecraft_dir())
            directory = str(root)
            target = str(root / "downloads")
        else:
            target = self.settings.get_minecraft_isolation_directory() or directory
        version = self.versions[self.selected_version]
        title = version.get("name") or version.get("version_number") or "内容"
        task_version = f"{identity + '-' if identity else ''}{self.kind}-{title}"
        started = self.download_pages.tasks_page.start_install(
            task_version, directory or target,
            content={"kind": self.kind, "version": version, "target": target})
        if started:
            logger.info('Content install queued: kind=%s instance=%s target=%s', self.kind, identity, target)
            self.status = "下载已加入任务列表。"
            self.pageRequested.emit("tasks")
        self.changed.emit()

    @Slot()
    def choosePack(self):
        path, _ = QFileDialog.getOpenFileName(None, "选择整合包", "", "整合包 (*.zip *.mrpack)")
        if path:
            self.inspectPack(path)

    @Slot(str)
    def inspectPack(self, path):
        try:
            info = inspect_pack(path)
            resolved = str(Path(path).resolve())
            if not self.pack_name or self.pack_path != resolved:
                self.pack_name = suggested_name(path)
            self.pack_path = resolved
            self.pack_summary = (f"{info.name} · {info.version} · {info.source}\nMinecraft {info.minecraft} · "
                                 f"{info.loader + ' ' + info.loader_version if info.loader else '原版'}\n"
                                 f"{len(info.files)} 个下载文件 · 内置内容 {info.expanded_bytes / 1024**2:.1f} MiB")
            self.pack_error = ""
        except Exception as exc:
            self.pack_path = ""
            self.pack_summary = "无法读取这个整合包。"
            self.pack_error = str(exc)
        self.changed.emit()

    @Slot(str)
    def setPackName(self, name):
        self.pack_name = name.strip()

    @Slot()
    def importPack(self):
        directory = (self.import_directory or
                     self.settings.get_setting("minecraft.directory.enable") or "")
        try:
            instance_name(self.pack_name)
            if not self.pack_path:
                raise ValueError("请先选择并检查 CurseForge ZIP 或 Modrinth ZIP / MRPACK 整合包。")
            if directory and (Path(directory) / "versions" / self.pack_name).exists():
                raise ValueError("该实例名称已存在，请更换名称。")
            if not directory:
                from utils.path_helper import get_default_minecraft_dir
                directory = str(get_default_minecraft_dir())
            started = self.download_pages.tasks_page.start_install(
                self.pack_name, directory, modpack=self.pack_path)
            if started:
                self.status = "整合包导入任务已开始，可在任务页查看进度。"
                self.pageRequested.emit("tasks")
        except Exception as exc:
            self.pack_error = str(exc)
        self.changed.emit()

    @Slot()
    def shutdown(self):
        self.request_id += 1
        self.catalogue.cancel.set()
        self.pool.clear()
        return self.pool.activeThreadCount() == 0



class ContentBrowserPage(QWidget):
    def __init__(self, download_pages):
        super().__init__(download_pages)
        self.controller = ContentBrowserController(download_pages)
        self.host = QmlPage(self, download_pages.resource_path, 'DownloadHub.qml', 'contentController', self.controller)
        self.quick = self.host.quick
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.host)
