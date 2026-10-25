"""QML-backed browser for mods, packs, shaders, and modpacks."""
from __future__ import annotations

from pathlib import Path
from copy import deepcopy
import logging
import re
import time
from html.parser import HTMLParser

from PySide6.QtCore import QObject, Property, QRunnable, QThreadPool, Signal, Slot, QTimer
from PySide6.QtWidgets import QFileDialog, QWidget, QVBoxLayout

from config.settings import get_settings_manager
from core.content import ContentCatalogue, instance_environment
from core.content_mirrors import configured_source
from core.translation import TranslationClient, endpoint as translation_endpoint
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
        self.catalogue = ContentCatalogue(mirror=configured_source(self.settings))
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
        self._download_dialog = None
        self._instance_context = self._context_key()
        self.translation_pool = QThreadPool(self)
        self.translation_pool.setMaxThreadCount(1)
        self.translation_client = TranslationClient(self.settings.config_path)
        self.translation_enabled = False
        self.translation_status = ''
        self.show_original = False
        self._translation_signature = None
        self._translation_running = False
        self._translation_next = 0
        self._translation_generation = 0
        self._translation_closed = False
        self.translation_timer = QTimer(self)
        self.translation_timer.setInterval(500)
        self.translation_timer.timeout.connect(self._translation_tick)
        self.translation_timer.start()

    def _target(self):
        directory = self.settings.get_setting('minecraft.directory.enable') or ''
        if self.kind == 'modpack':
            from utils.path_helper import get_default_minecraft_dir
            return str((Path(directory) if directory else Path(get_default_minecraft_dir())) / 'versions')
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
            'view', 'import_directory', 'source', 'query', 'has_more', 'details_busy', 'file_query',
            'translation_enabled', 'translation_status', 'show_original')} | {
                'instance': self.settings.get_setting('minecraft.version.enable') or '尚未选择',
                'target': self._target(), 'game_version': self._context()[2],
                'loader': self._context()[3],
                'project_compatibility': self._project_compatibility(),
                'has_more_versions': len(self.versions) < len(self._filtered_versions()) or self._version_has_more,
                'selected_file': self.versions[self.selected_version] if 0 <= self.selected_version < len(self.versions) else {},
                'can_install': bool(self._context()[0] and self._context()[1]),
                'installable': bool(self._context()[0] and self._context()[1]) and not (
                    0 <= self.selected_version < len(self.versions) and
                    self.versions[self.selected_version].get('compatibility_state') == 'incompatible')}

    def _installed_instances(self, directory=None):
        directory = (self.settings.get_setting('minecraft.directory.enable') or '') if directory is None else directory
        if not directory:
            return []
        from utils.instances import installed_instance_ids
        try:
            return installed_instance_ids(directory)
        except OSError:
            return []

    @Slot()
    def toggleOriginal(self):
        self.show_original = not self.show_original
        self.changed.emit()

    def _translation_tick(self):
        if self._translation_closed:
            return
        enabled = bool(self.settings.get_setting('translation.enabled', False))
        if not enabled and not self.translation_enabled:
            return
        rows = [self.selected_project] if self.view == 'detail' and self.selected_project else self.results if self.view == 'browse' else []
        try:
            source = translation_endpoint(self.settings.get_setting('translation.source', 'Buggcraft'))
        except ValueError:
            self.translation_status = '翻译源配置无效，继续显示原文'
            return
        signature = (enabled, source, self.request_id, self.view,
                     tuple((r.get('source'), str(r.get('project_id')), r.get('title'), r.get('description'), r.get('body'), r.get('body_html')) for r in rows))
        if signature != self._translation_signature:
            was_enabled = self.translation_enabled
            self._translation_signature = signature
            self._translation_generation += 1
            self._translation_next = 0
            self.translation_enabled = enabled
            self.translation_status = ''
            if enabled and not was_enabled:
                self.show_original = False
            # Never label a previous source revision as the current translation.
            # This also clears translations when switching service providers.
            for row in rows:
                revision = (source, row.get('source'), str(row.get('project_id')),
                            row.get('title'), row.get('description'), row.get('body'), row.get('body_html'))
                if row.get('_translation_source') != revision:
                    row.pop('translated_summary', None)
                    row.pop('translated_body', None)
                    row['display_summary'] = (row.get('description') or '').replace('\n', ' ')[:180]
            if not enabled:
                self.results = [dict(row, display_summary=(row.get('description') or '').replace('\n',' ')[:180], translated_summary='', translated_body='') for row in self.results]
                if self.selected_project:
                    self.selected_project = dict(self.selected_project, translated_summary='', translated_body='')
            self.changed.emit()
        if not enabled or not rows or self._translation_running or time.monotonic()<self._translation_next:
            return
        self._translation_running = True
        generation = self._translation_generation
        detail = self.view == 'detail'
        # A separate pool keeps model availability independent of catalogue work.
        self.translation_pool.start(_SearchWorker(generation, ('translation', lambda:
            dict(self.translation_client.resolve(source, rows, detail), signature=signature)), self._translation_finished))

    @Slot(int, str, object, str)
    def _translation_finished(self, generation, _mode, data, error):
        self._translation_running = False
        if self._translation_closed or generation != self._translation_generation or not self.settings.get_setting('translation.enabled',False):
            return
        if isinstance(data,dict) and data.get('signature'):
            rows = [self.selected_project] if self.view == 'detail' and self.selected_project else self.results if self.view == 'browse' else []
            current = (True,translation_endpoint(self.settings.get_setting('translation.source','Buggcraft')),self.request_id,self.view,
                       tuple((r.get('source'),str(r.get('project_id')),r.get('title'),r.get('description'),r.get('body'),r.get('body_html')) for r in rows))
            if data['signature'] != current:
                return
        if error or not isinstance(data,dict):
            self.translation_status = '翻译服务暂不可用，继续显示原文'
            self._translation_next = time.monotonic()+30
        else:
            self.translation_status = data['status']
            self._translation_next = time.monotonic()+data.get('retry',2) if data['pending'] else float('inf')
            rows = [dict(self.selected_project)] if self.view == 'detail' and self.selected_project else [dict(row) for row in self.results]
            for index, row in enumerate(rows):
                translated = data['translations'].get(str(index),{})
                row['_translation_source'] = (
                    translation_endpoint(self.settings.get_setting('translation.source', 'Buggcraft')),
                    row.get('source'), str(row.get('project_id')), row.get('title'),
                    row.get('description'), row.get('body'), row.get('body_html'))
                if 'summary' in translated:
                    row['translated_summary'] = translated['summary']['text']
                    row['display_summary'] = row['translated_summary'].replace('\n',' ')[:180]
                if 'body' in translated:
                    row['translated_body'] = project_description(translated['body']['text'], html=translated['body']['format']=='html')
            if self.view == 'detail' and rows:
                self.selected_project = rows[0]
            else:
                self.results = rows
        self.changed.emit()

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
        for client in self.catalogue.clients.values():
            client.mirror = configured_source(self.settings)
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

    def _version_row(self, item, *, environment=None, kind=None):
        _, _, game, loader = self._context() if environment is None else environment
        kind = self.kind if kind is None else kind
        games = [str(value) for value in item.get('game_versions', [])]
        loaders = [str(value).lower() for value in item.get('loaders', [])]
        loader = (loader or 'vanilla').lower()
        loader_name = {'vanilla': '原版（未安装模组加载器）', 'forge': 'Forge', 'fabric': 'Fabric', 'neoforge': 'NeoForge', 'quilt': 'Quilt'}
        required = ' / '.join(loader_name.get(value, value) for value in loaders)
        if kind == 'modpack':
            advice, state = '整合包将导入为独立实例，不改变当前游戏', 'info'
        elif not game:
            advice, state = '无法识别目标实例的游戏版本，请检查实例后再下载', 'unknown'
        else:
            errors, unknown = [], []
            if games and game not in games:
                errors.append('游戏版本不支持：当前实例是 Minecraft ' + game + '，此文件支持 ' + ' / '.join(games))
            elif not games:
                unknown.append('文件未声明支持的 Minecraft 版本，无法确认游戏版本是否兼容')
            if kind == 'mod' and loaders and loader not in loaders:
                prefix = 'Minecraft ' + game + ' 版本号受支持，但' if game in games else ''
                errors.append('加载器不匹配：' + prefix + '此文件要求 ' + required + '，当前实例使用 ' + loader_name.get(loader, loader))
            elif kind == 'mod' and not loaders:
                unknown.append('文件未声明支持的模组加载器，请查看作者说明')
            advice = '；'.join(errors + unknown) or ('兼容 Minecraft ' + game + (' · ' + loader_name.get(loader, loader) if kind == 'mod' else ''))
            state = 'incompatible' if errors else 'unknown' if unknown else 'compatible'
        files = item.get('files') or []
        primary = next((file for file in files if file.get('primary')), files[0] if files else {})
        size = primary.get('size') or 0
        return dict(item, display_name=item.get('name') or item.get('version_number') or '未知版本',
                    display_date=(item.get('date_published') or '')[:10],
                    game_versions_label=' / '.join(games) or '作者未声明', loaders_label=' / '.join(loaders) or '未限定',
                    filename=primary.get('filename', ''), file_size_label=f'{size / 1024 ** 2:.1f} MiB' if size else '',
                    compatibility=advice, compatibility_state=state,
                    channel_label={'release': '正式版', 'beta': '测试版', 'alpha': '预览版'}.get(item.get('version_type'), '版本文件'))

    def _project_compatibility(self):
        if not self.selected_project or self.kind == 'modpack':
            return ''
        _, _, game, loader = self._context()
        games = self.selected_project.get('game_versions') or self.selected_project.get('versions') or []
        if game and game in games:
            if self.kind == 'mod':
                matching = any(self._version_row(item)['compatibility_state'] == 'compatible' for item in self._all_versions)
                if matching:
                    return '已找到同时支持 Minecraft ' + game + ' 和 ' + (loader or '原版') + ' 的文件，请在版本文件中选择。'
                return ('项目包含 Minecraft ' + game + ' 版本，但' +
                        ('当前已加载文件中未找到' if self._version_has_more else '尚未找到') + '与 ' + (loader or '原版') +
                        ' 匹配的文件；游戏版本和加载器必须由同一个文件同时支持。')
            return '此项目有支持 Minecraft ' + game + ' 的版本；请选择对应游戏版本的文件。'
        return ''

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
                # Recommend a compatible file without excluding other versions.
                # Use all returned records so an older match is not hidden past
                # the first page. Keep the author's order within each group.
                self._all_versions = sorted(records, key=lambda item: (
                    self.kind != 'modpack' and self._version_row(item)['compatibility_state'] == 'compatible'), reverse=True)
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
        if self._download_dialog is not None:
            self._download_dialog.raise_()
            self._download_dialog.activateWindow()
            return
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
        version = deepcopy(self.versions[self.selected_version])
        from ui.dialog.qml_dialog import QmlDialog
        instances = self._installed_instances(directory)
        selected = identity if identity in instances else (instances[0] if instances else '')
        title = version.get("name") or version.get("version_number") or "内容"
        dialog = QmlDialog(self.download_pages.window(), resources=self.download_pages.resource_path,
                           title='确认下载', width=560, height=420,
                           source='ContentDownloadConfirm.qml', data={
                               'project': (self.selected_project or {}).get('display_title') or (self.selected_project or {}).get('title') or '资源',
                               'version': title, 'filename': version.get('filename') or '',
                               'size': version.get('file_size_label') or '', 'kind': self.kind,
                               'instance': selected, 'instances': instances, 'directory': directory,
                               'targetExpanded': False,
                               'compatibility': version.get('compatibility') or '',
                               'compatibilityState': version.get('compatibility_state') or 'unknown'})
        dialog.controller.actionRequested.connect(
            lambda action: self._content_download_dialog_action(dialog, version, action))
        def finished(_result):
            if self._download_dialog is dialog:
                self._download_dialog = None
            dialog.shutdown()
            QTimer.singleShot(0, dialog, dialog.deleteLater)
        dialog.finished.connect(finished)
        self._download_dialog = dialog
        self._refresh_download_target(dialog, version)
        dialog.open()

    def _refresh_download_target(self, dialog, version):
        data = dialog.controller.data
        kind, directory, identity = data['kind'], data['directory'], data['instance']
        if kind == 'modpack':
            from utils.path_helper import get_default_minecraft_dir
            directory = directory or str(get_default_minecraft_dir())
            data.update(target=str(Path(directory) / 'downloads'), directory=directory,
                        compatibility='整合包将创建独立游戏实例，游戏版本和加载器由整合包决定。',
                        compatibilityState='info', targetValid=True, environment='独立游戏实例', error='')
        elif identity not in self._installed_instances(directory):
            data.update(compatibility='所选 Minecraft 实例已不存在，请重新选择',
                        compatibilityState='incompatible', targetValid=False, target='', environment='', error='')
        else:
            try:
                game, loader = instance_environment(directory, identity)
            except (OSError, ValueError):
                data.update(compatibility='无法读取目标实例的游戏版本和加载器，请检查实例后重试。',
                            compatibilityState='incompatible', targetValid=False, target='', environment='', error='')
                dialog.controller.changed.emit()
                return
            row = self._version_row(version, environment=(directory, identity, game, loader), kind=kind)
            data.update(target=self.settings.get_minecraft_isolation_directory(directory=directory, version=identity),
                        compatibility=row['compatibility'], compatibilityState=row['compatibility_state'],
                        environment='Minecraft ' + (game or '未知') + (' · ' + (loader or '原版') if kind == 'mod' else ''),
                        targetValid=bool(game) and row['compatibility_state'] != 'incompatible', error='')
        dialog.controller.changed.emit()

    def _content_download_dialog_action(self, dialog, version, action):
        if self._download_dialog is not dialog or dialog.controller.working:
            return
        if action == 'toggle-target':
            dialog.controller.data['targetExpanded'] = not dialog.controller.data.get('targetExpanded', False)
            dialog.controller.changed.emit()
            return
        if action.startswith('目标:'):
            dialog.controller.data['instance'] = action[3:]
            self._refresh_download_target(dialog, version)
            return
        if action == '取消':
            dialog.reject()
            return
        if action != '确认下载':
            return
        self._refresh_download_target(dialog, version)
        data = dialog.controller.data
        if not data.get('targetValid'):
            return
        identity, kind, target, directory = data['instance'], data['kind'], data['target'], data['directory']
        title = version.get("name") or version.get("version_number") or "内容"
        task_version = f"{identity + '-' if identity else ''}{kind}-{title}"
        dialog.controller.working = True
        try:
            started = self.download_pages.tasks_page.start_install(
                task_version, directory, content={"kind": kind, "version": version, "target": target})
        except Exception as exc:
            logger.exception('Unable to queue content download')
            dialog.controller.data['error'] = '无法创建下载任务：' + str(exc)
            started = False
        if started:
            logger.info('Content install queued: kind=%s instance=%s target=%s', kind, identity, target)
            self.status = "下载已加入任务列表。"
            dialog.accept()
            self.pageRequested.emit("tasks")
        else:
            dialog.controller.data['error'] = dialog.controller.data.get('error') or '该下载任务已存在，请在下载记录中查看。'
        dialog.controller.working = False
        dialog.controller.changed.emit()

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
        if self._download_dialog is not None:
            self._download_dialog.reject()
        self._translation_closed = True
        self.translation_timer.stop()
        self.request_id += 1
        self.catalogue.cancel.set()
        self.pool.clear()
        self.translation_pool.clear()
        done = self.pool.activeThreadCount() == 0 and self.translation_pool.activeThreadCount() == 0
        if done:
            self.translation_client.close()
        return done



class ContentBrowserPage(QWidget):
    def __init__(self, download_pages):
        super().__init__(download_pages)
        self.controller = ContentBrowserController(download_pages)
        self.host = QmlPage(self, download_pages.resource_path, 'DownloadHub.qml', 'contentController', self.controller)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.host)

    @property
    def quick(self):
        return self.host.quick
