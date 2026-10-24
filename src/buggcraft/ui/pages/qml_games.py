"""Virtualized Minecraft catalogue and QML installation form."""
import json
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Property, QRunnable, QThreadPool, Signal, Slot

from config.settings import get_settings_manager
from core.downloads import MinecraftDownloader
from core.loader_rules import COMPONENTS, LOADERS, incompatibility
from ui.pages.qml_host import QmlPage


class WorkSignals(QObject):
    finished = Signal(int, str, object, str)


class CatalogueWork(QRunnable):
    def __init__(self, sequence, kind, callback, action):
        super().__init__()
        self.sequence, self.kind, self.action = sequence, kind, action
        self.signals = WorkSignals()
        self.signals.finished.connect(callback)

    @Slot()
    def run(self):
        try:
            self.signals.finished.emit(self.sequence, self.kind, self.action(), '')
        except Exception as exc:
            self.signals.finished.emit(self.sequence, self.kind, None, str(exc))


class GameCatalogueController(QObject):
    changed = Signal()

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.settings = get_settings_manager()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.cancel = threading.Event()
        self.cache = Path(self.settings.config_path) / 'minecraft-catalog.json'
        self.versions = []
        self.query = ''
        self.filter = 'release'
        self.status = ''
        self.busy = False
        self.sequence = 0
        self.loader_sequence = 0
        self.game = ''
        self.category = 'game'
        self.loader = ''
        self.loader_version = ''
        self.loader_options = []
        self.loader_status = ''
        self.loader_busy = False
        self.install_view = 'catalogue'
        self.pending_component = ''
        self.component_versions = []
        self.addons = {}
        try:
            cached = json.loads(self.cache.read_text(encoding='utf-8'))
            if isinstance(cached, list):
                self.versions = [item for item in cached if isinstance(item, dict) and 'id' in item]
        except (OSError, ValueError):
            pass

    @Property('QVariantMap', notify=changed)
    def view(self):
        return dict(
            versions=[item for item in self.versions if (not self.filter or item.get('type') == self.filter
                      or self.filter == 'old_beta' and item.get('type') == 'old_alpha')
                      and self.query.casefold() in item['id'].casefold()],
            status=self.status, busy=self.busy, query=self.query,
            filter={'release': '正式版', 'snapshot': '快照', 'old_beta': '旧版', '': '全部'}[self.filter],
            game=self.game, category=self.category, loader=self.loader,
            loaderVersion=self.loader_version, loaderOptions=self.loader_options,
            loaderStatus=self.loader_status, loaderBusy=self.loader_busy,
            installView=self.install_view, pendingComponent=self.pending_component,
            componentVersions=self.component_versions,
            components=[dict(name=name, reason=incompatibility(name, self.loader),
                             supported=name in LOADERS or name in ('Fabric API', 'QSL/QFAPI'),
                             version=self.loader_version if name == self.loader else
                                     self.addons.get(name, {}).get('name', ''),
                             selected=name == self.loader or name in self.addons,
                             description=self._component_description(name))
                        for name in ('Forge', 'NeoForge', 'OptiFine', 'Fabric', 'Fabric API', 'Quilt', 'QSL/QFAPI')])

    def _component_description(self, name):
        if incompatibility(name, self.loader):
            return incompatibility(name, self.loader)
        if name == self.loader:
            return self.loader_version
        if name in self.addons:
            return self.addons[name].get('name', '')
        if name == 'OptiFine':
            return '需官方安装器'
        return '不安装'

    @Slot()
    def refresh(self):
        if self.busy or self.cancel.is_set():
            return
        self.busy = True
        self.sequence += 1
        self.status = '正在获取游戏版本列表…'
        self.changed.emit()
        source = self.settings.get_setting('settings.general.mirrors', '自动')
        self.pool.start(CatalogueWork(self.sequence, 'catalogue', self._finished,
                        lambda: MinecraftDownloader(self.cache.parent / 'catalog-cache', source=source,
                                                    cancel=self.cancel).manifest()['versions']))

    @Slot(int, str, object, str)
    def _finished(self, sequence, kind, data, error):
        if self.cancel.is_set():
            return
        if kind == 'catalogue':
            if sequence != self.sequence:
                return
            self.busy = False
            if error:
                self.status = '获取失败，可重试。' + ('正在显示缓存记录。' if self.versions else '') + ' ' + error
            else:
                self.versions = data or []
                self.status = ''
                try:
                    self.cache.parent.mkdir(parents=True, exist_ok=True)
                    self.cache.write_text(json.dumps(self.versions, ensure_ascii=False), encoding='utf-8')
                except OSError:
                    pass
        elif kind.startswith('component:'):
            if sequence != self.loader_sequence:
                return
            self.loader_busy = False
            self.component_versions = data or [] if not error else []
            self.loader_status = error or ('' if self.component_versions else '此游戏版本暂无可用文件。')
        else:
            if sequence != self.loader_sequence:
                return
            self.loader_busy = False
            self.loader_options = [str(item) for item in data or []] if not error else []
            self.loader_version = self.loader_options[0] if self.loader_options else ''
            self.loader_status = error or ('' if self.loader_options else '该游戏版本没有可用的加载器版本。')
        self.changed.emit()

    @Slot(str)
    def setQuery(self, value):
        self.query = value
        self.changed.emit()

    @Slot(str)
    def setFilter(self, value):
        self.filter = {'正式版': 'release', '快照': 'snapshot', '旧版': 'old_beta', '全部': ''}.get(value, 'release')
        self.changed.emit()

    @Slot(str)
    def openContent(self, kind):
        if kind not in ('game', 'mod', 'resourcepack', 'shader', 'modpack'):
            return
        self.category = kind
        if kind != 'game':
            controller = self.page.parent.content_page.controller
            if controller.kind != kind:
                controller.setKind(kind)
            controller.setView('browse')
        self.changed.emit()

    @Slot()
    def importPack(self):
        self.page.parent.content_page.controller.setImportDirectory(
            self.settings.get_setting('minecraft.directory.enable') or '')
        self.page.parent.open_content('modpack', 'import')
        self.page.parent.content_page.controller.choosePack()

    @Slot(str)
    def selectGame(self, version):
        if not any(item['id'] == version for item in self.versions):
            return
        self.game = version
        self.install_view = 'components'
        self.pending_component = ''
        self.addons = {}
        self.loader = ''
        self.loader_version = ''
        self.loader_options = []
        self.loader_status = ''
        self.loader_sequence += 1
        self.loader_busy = False
        self.changed.emit()

    @Slot()
    def backToGames(self):
        self.install_view = 'catalogue'
        self.loader_sequence += 1
        self.loader_busy = False
        self.changed.emit()

    @Slot()
    def backToComponents(self):
        self.install_view = 'components'
        self.loader_sequence += 1
        self.loader_busy = False
        self.changed.emit()

    @Slot(str)
    def openComponent(self, name):
        if name not in (*LOADERS, 'Fabric API', 'QSL/QFAPI') or incompatibility(name, self.loader):
            return
        if name in ('Fabric API', 'QSL/QFAPI') and self.loader not in ('Fabric', 'Quilt'):
            self.loader_status = '请先选择 Fabric 或 Quilt，再选择对应 API。'
            self.changed.emit()
            return
        self.pending_component = name
        self.component_versions = []
        self.install_view = 'versions'
        self.loader_busy = True
        self.loader_status = ''
        self.loader_sequence += 1
        game, loader = self.game, self.loader
        source = self.settings.get_setting('settings.general.mirrors', '自动')
        def fetch():
            if name in LOADERS:
                from core.loaders import available_versions
                return [dict(name=value, id=value) for value in available_versions(name, game, source)]
            from core.content import ContentCatalogue
            project = dict(source='Modrinth', project_id='fabric-api' if name == 'Fabric API' else 'qsl')
            from core.content_mirrors import configured_source
            return ContentCatalogue(mirror=configured_source(self.settings)).versions(
                project, game, 'fabric' if name == 'Fabric API' else loader, 'mod')
        self.changed.emit()
        self.pool.start(CatalogueWork(self.loader_sequence, 'component:' + name, self._finished, fetch))

    @Slot(int)
    def chooseComponentVersion(self, index):
        if not 0 <= index < len(self.component_versions):
            return
        name = self.pending_component
        record = self.component_versions[index]
        if incompatibility(name, self.loader):
            return
        if name in LOADERS:
            self.loader, self.loader_version = name, record['name']
        else:
            self.addons[name] = dict(record)
        self.install_view = 'components'
        self.loader_status = ''
        self.changed.emit()

    @Slot(str)
    def removeComponent(self, name):
        if name == self.loader:
            self.loader = self.loader_version = ''
            self.addons = {}
        else:
            self.addons.pop(name, None)
        self.changed.emit()

    @Slot(str)
    def selectLoader(self, loader):
        if loader not in ('', *LOADERS):
            return
        if loader and self.loader and incompatibility(loader, self.loader):
            return
        self.loader = loader
        self.loader_version = ''
        self.loader_options = []
        self.loader_status = ''
        self.loader_sequence += 1
        self.loader_busy = bool(loader)
        self.changed.emit()
        if loader:
            from core.loaders import available_versions
            game, source = self.game, self.settings.get_setting('settings.general.mirrors', '自动')
            self.pool.start(CatalogueWork(self.loader_sequence, loader, self._finished,
                                         lambda: available_versions(loader, game, source)))

    @Slot(str)
    def selectLoaderVersion(self, version):
        if version in self.loader_options:
            self.loader_version = version
            self.changed.emit()

    @Slot()
    def install(self):
        if not self.game or self.loader_busy or (self.loader and not self.loader_version):
            return
        self.page.start_install(self.game, self.loader, self.loader_version,
                                addons=[dict(name=name, version=version) for name, version in self.addons.items()])


class MinecraftDownloadSignals(QObject):
    download = Signal(str)
    complete = Signal(str)


class GamesPage(QmlPage):
    update_signal = Signal()

    def __init__(self, parent):
        self.parent = parent
        self.signals = MinecraftDownloadSignals()
        controller = GameCatalogueController(parent)
        super().__init__(parent, parent.resource_path, 'Downloads.qml', 'gameCatalogue', controller)
        controller.page = self
        controller.setParent(self)
        self.games_content = self
        self.settings_manager = controller.settings

    def on_page_activate(self):
        if self.controller.category == 'game' and not self.controller.versions and not self.controller.busy:
            self.controller.refresh()

    def on_page_deactivate(self):
        pass

    def start_install(self, version, loader='', loader_version='', addons=None):
        directory = self.settings_manager.get_setting('minecraft.directory.enable')
        identity = version
        if loader:
            if loader == 'NeoForge':
                identity = f'neoforge-{loader_version}'
            elif loader in ('Fabric', 'Quilt'):
                identity = f'{loader.lower()}-loader-{loader_version}-{version}'
            else:
                identity = f'{version}-forge-{loader_version}'
        return self.parent.tasks_page.start_install(identity, directory, loader or None,
                                                    version if loader else None, loader_version or None,
                                                    addons=addons or [])

    def shutdown(self):
        self.controller.cancel.set()
        self.controller.pool.clear()
        return self.controller.pool.activeThreadCount() == 0
