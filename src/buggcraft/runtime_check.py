"""Exercise shipped GUI and native libraries without touching user settings."""
import asyncio
import json
import logging
import os
from pathlib import Path
import tempfile
import traceback


def check_python_runtime():
    """Exercise extensions which are easy to break by deleting small DLLs."""
    import bz2
    import ctypes
    from decimal import Decimal
    import hashlib
    import io
    import lzma
    import ssl
    import tarfile
    import uuid
    import xml.etree.ElementTree as ET
    import zipfile
    from concurrent.futures import ThreadPoolExecutor

    payload = b'Python runtime and archive integrity\n' * 100
    for compress, decompress in ((bz2.compress, bz2.decompress),
                                 (lzma.compress, lzma.decompress)):
        if decompress(compress(payload)) != payload:
            raise RuntimeError('Broken Python compression extension')
    for method in (zipfile.ZIP_DEFLATED, zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', compression=method) as archive:
            archive.writestr('config/check.txt', payload)
        buffer.seek(0)
        with zipfile.ZipFile(buffer) as archive:
            if archive.read('config/check.txt') != payload:
                raise RuntimeError('Broken ZIP support')
    for mode in ('gz', 'bz2', 'xz'):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w:' + mode) as archive:
            member = tarfile.TarInfo('runtime/check.txt')
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
        buffer.seek(0)
        with tarfile.open(fileobj=buffer, mode='r:*') as archive:
            if archive.extractfile('runtime/check.txt').read() != payload:
                raise RuntimeError('Broken Java archive support')
    if ET.fromstring('<versions><version>1.20.1</version></versions>').findtext('version') != '1.20.1':
        raise RuntimeError('Broken XML parser')
    if Decimal('0.1') + Decimal('0.2') != Decimal('0.3'):
        raise RuntimeError('Broken decimal extension')
    if uuid.UUID(str(uuid.uuid4())).version != 4:
        raise RuntimeError('Broken UUID fallback')
    if ctypes.sizeof(ctypes.c_void_p) != 8:
        raise RuntimeError('Unexpected Python ABI')
    with ThreadPoolExecutor(max_workers=2) as pool:
        digests = list(pool.map(lambda data: hashlib.sha256(data).hexdigest(), [payload] * 2))
    if digests[0] != digests[1] or not ssl.create_default_context().get_ciphers():
        raise RuntimeError('Broken TLS, hashing or threaded downloads')


async def check_peer():
    from hookup.native_routes import manager, close
    try:
        result = await manager().request('bridge.initialize', {'protocol': 1})
        if result.get('build', {}).get('implementation') != 'cpp':
            raise RuntimeError('The installed multiplayer bridge is not C++')
        if not {'mods.fetch', 'room.host', 'room.join', 'social.operate'} <= set(result.get('methods', [])):
            raise RuntimeError('The native multiplayer bridge is out of date')
    finally:
        await close()


def main(report):
    result = {'passed': False, 'checks': []}
    os.environ.setdefault('QT_QUICK_BACKEND', 'software')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    logging.basicConfig(filename=str(Path(report).with_suffix('.log')), encoding='utf-8',
                        level=logging.DEBUG, force=True)
    try:
        check_python_runtime()
        result['checks'].extend(['python-stdlib-extensions', 'zip-bzip2-lzma',
                                 'java-tar-gz-bz2-xz', 'xml-decimal-uuid',
                                 'threaded-hashing-tls'])
        import certifi
        if not Path(certifi.where()).is_file():
            raise RuntimeError('Missing HTTPS CA bundle')
        result['checks'].append('https-ca')
        from core.launch_options import complete_auth_arguments, offline_uuid
        if (offline_uuid('Notch') != 'b50ad385-829d-3141-a216-7e7d7539ba7f'
                or complete_auth_arguments(['${clientid}', '${auth_xuid}']) != ['', '0']):
            raise RuntimeError('Broken modern Minecraft authentication arguments')
        result['checks'].append('modern-minecraft-auth-arguments')
        if os.name == 'nt':
            import ctypes
            if ctypes.windll.kernel32.GetConsoleWindow():
                raise RuntimeError('Packaged launcher unexpectedly owns a console window')
            result['checks'].append('no-windows-console')
        asyncio.run(check_peer())
        result['checks'].append('native-multiplayer-api')

        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QEventLoop, QMetaObject, QTimer, QObject, Qt
        from PySide6.QtQuickWidgets import QQuickWidget
        import config.settings as settings
        resources = Path(__import__('sys').executable).resolve().parent / 'resources'
        if not resources.exists():
            resources = Path(__file__).resolve().parent / 'resources'
        if not resources.exists():
            resources = Path(__file__).resolve().parents[2] / 'resources'
        if not (resources / 'images/minecraft_bg.png').is_file():
            raise RuntimeError('Missing packaged images')
        app = QApplication([])
        failures = []
        with tempfile.TemporaryDirectory(prefix='buggcraft-package-check-') as temp:
            from utils.instances import installed_instance_ids
            fixture_root = Path(temp) / 'test-game'
            for identity, metadata in [('base', {'id': 'base'}),
                                       ('imported', {'id': 'imported', 'inheritsFrom': 'base'})]:
                path = fixture_root / 'versions' / identity / (identity + '.json')
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps(metadata), encoding='utf-8')
            (fixture_root / 'versions/broken').mkdir()
            (fixture_root / 'versions/broken/broken.json').write_text('{broken', encoding='utf-8')
            if installed_instance_ids(fixture_root) != ['base', 'imported']:
                raise RuntimeError('Missing safe version scanning for inherited modpacks')
            result['checks'].append('inherited-version-scan-safety')
            settings.get_conf_or_cache_manager = lambda: ('package-check', temp)
            settings._settings_manager_instance = settings.SettingsManager(temp)
            from utils.path_helper import get_default_minecraft_dir
            expected_game_dir = str(get_default_minecraft_dir())
            if settings._settings_manager_instance.get_setting('minecraft.directory.enable') != expected_game_dir:
                raise RuntimeError('Game downloads must default to launcher/.minecraft')
            result['game_directory'] = expected_game_dir
            result['checks'].append('portable-game-directory')
            from windows.main_window import MinecraftLauncher
            window = MinecraftLauncher(str(resources.parent), temp, temp, str(resources))
            window.setAttribute(Qt.WA_ShowWithoutActivating)
            window.move(-20000, -20000)
            def exercise():
                try:
                    window.show()
                    from core.game_sessions import GameSessions
                    if not isinstance(window.launcher, GameSessions):
                        raise RuntimeError('Missing independent game session ownership')
                    home = (resources / 'qml/launcher/Home.qml').read_text(encoding='utf-8')
                    if '"launch-game"' not in home or 'launch-additional-game' in home:
                        raise RuntimeError('Game launch and multi-launch must reuse one primary control')
                    result['checks'].append('independent-game-sessions')
                    from ui.dialog.MultiplayerDialog import MultiplayerDialog
                    lobby = MultiplayerDialog(window.started_page)
                    window.started_page._multiplayer_dialog = lobby
                    lobby.setAttribute(Qt.WA_ShowWithoutActivating)
                    lobby.move(-20000, -20000)
                    lobby.show()
                    if lobby.parentWidget() is not None or lobby.windowHandle().transientParent() is not None:
                        raise RuntimeError('Lobby must minimize independently of launcher')
                    window.showMinimized()
                    app.processEvents()
                    if not lobby.isVisible() or lobby.isMinimized():
                        raise RuntimeError('Launcher minimize incorrectly minimized lobby')
                    result['checks'].append('independent-lobby-window')
                    if window.download_page.tasks_page.pool.maxThreadCount() < 2:
                        raise RuntimeError('Downloads unexpectedly restricted to one task')
                    from utils.install_progress import InstallProgress
                    percentages = []
                    tracker = InstallProgress(percentages.append)
                    tracker.set_max(5 * 1024 ** 3)
                    tracker.set_progress(4 * 1024 ** 3)
                    if percentages[-1] != 80:
                        raise RuntimeError('Broken large-byte installer progress')
                    result['checks'].extend(['concurrent-download-tasks', 'bounded-installer-progress'])
                    importer = window.download_page.content_page.controller
                    if hasattr(importer, 'key_input') or hasattr(importer, 'api_key'):
                        raise RuntimeError('Modpack import must not request an API key')
                    from ui.pages.qml_host import QmlPage
                    for host in window.findChildren(QmlPage):
                        host.ensure_loaded()
                    result['checks'].append('qml-all-launcher-pages')
                    # Exercise the actual shipped QML button signal and its
                    # close callback; controller-only checks missed a native
                    # crash caused by unloading the executing QML component.
                    deletion_root = Path(temp) / 'delete-check'
                    identity = '1.20.1'
                    metadata = deletion_root / 'versions' / identity / (identity + '.json')
                    metadata.parent.mkdir(parents=True)
                    metadata.write_text(json.dumps(dict(id=identity)), encoding='utf-8')
                    settings._settings_manager_instance.set_setting('minecraft.directory.enable', str(deletion_root))
                    instances = window.version_page.versions_page.controller
                    instances.reload()
                    def find_item(item, name):
                        if item.objectName() == name:
                            return item
                        for child in item.childItems():
                            found = find_item(child, name)
                            if found is not None:
                                return found
                    for index in (0, 0, 1):
                        instances.action(identity, 'deleteVersion')
                        dialog = instances._delete_dialog
                        dialog.setAttribute(Qt.WA_ShowWithoutActivating)
                        dialog.move(-20000, -20000)
                        app.processEvents()
                        if index == 0:
                            dialog.grab().save(str(Path(report).with_name(Path(report).stem + '-delete.png')))
                        button = find_item(dialog.quick.rootObject(), 'dialog-action-' + str(index))
                        if button is None or not QMetaObject.invokeMethod(button, 'clicked', Qt.DirectConnection):
                            raise RuntimeError('Missing instance deletion QML action')
                        if instances._delete_worker is not None:
                            finished = QEventLoop()
                            instances._delete_worker.signals.finished.connect(finished.quit)
                            QTimer.singleShot(5000, finished, finished.quit)
                            finished.exec()
                        app.processEvents()
                        if instances._delete_dialog is not None or metadata.exists() != (index == 0):
                            raise RuntimeError('Instance deletion cancel/confirm did not complete safely')
                    result['checks'].append('instance-delete-qml-cancel-confirm')
                    if lobby.quick.rootObject().findChild(QObject, 'export-diagnostics') is None:
                        raise RuntimeError('Missing multiplayer diagnostic export action')
                    from utils.diagnostics import export_diagnostics
                    from zipfile import ZipFile
                    game_logs = Path(temp) / 'test-game/logs'
                    game_logs.mkdir(parents=True, exist_ok=True)
                    (game_logs / 'latest.log').write_text('fixture --accessToken package-check-secret', encoding='utf-8')
                    diagnostic = export_diagnostics(Path(temp) / 'diagnostics.zip', game_directory=game_logs.parent)
                    with ZipFile(diagnostic) as bundle:
                        if 'diagnostics.json' not in bundle.namelist():
                            raise RuntimeError('Broken diagnostic archive')
                        exported = json.loads(bundle.read('diagnostics.json'))
                        if (exported['network_collection']['status'] != 'collected'
                                or not any(name.startswith('p2p-sessions/network-export-') for name in bundle.namelist())):
                            raise RuntimeError('Missing fresh network topology export')
                        if b'package-check-secret' in bundle.read('game/logs/latest.log'):
                            raise RuntimeError('Game diagnostic credentials were not redacted')
                        if json.loads(bundle.read('game/inventory.json'))['schema'] != 1:
                            raise RuntimeError('Missing mod and runtime inventory')
                    result['checks'].extend(['modpack-no-api-key', 'diagnostic-export',
                                             'network-topology-export', 'game-crash-log-export', 'mod-runtime-inventory'])
                    from ui.dialog.FriendsDialog import FriendsDialog
                    lobby.friends_window = FriendsDialog(lobby, lobby.resources)
                    lobby.friends_window.setAttribute(Qt.WA_ShowWithoutActivating)
                    lobby.friends_window.move(-20000, -20000)
                    lobby.friends_window.show()
                    app.processEvents()
                    quicks = window.findChildren(QQuickWidget) + [lobby.quick, lobby.friends_window.quick]
                    for quick in quicks:
                        if quick.status() != QQuickWidget.Ready:
                            raise RuntimeError('; '.join(error.toString() for error in quick.errors()))
                    lobby.grab().save(str(Path(report).with_suffix('.png')))
                    result['checks'].extend(['main-window', 'qml-lobby', 'qml-friends'])
                    lobby.shutdown()
                    window.close()
                except Exception:
                    failures.append(traceback.format_exc())
                finally:
                    app.quit()
            QTimer.singleShot(0, exercise)
            app.exec()
        if failures:
            raise RuntimeError('\n'.join(failures))
        result['passed'] = True
    except Exception:
        result['error'] = traceback.format_exc()
    Path(report).write_text(json.dumps(result, ensure_ascii=True, indent=2), encoding='utf-8')
    return 0 if result['passed'] else 1
