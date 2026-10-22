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
    from hookup.peer import PeerTransport
    transport = PeerTransport(None)
    first = transport.create_pc()
    second = transport.create_pc()
    payload = os.urandom(65536)
    received = asyncio.get_running_loop().create_future()
    channel = first.createDataChannel('package-check', ordered=True)
    channel.on('open', lambda: channel.send(payload))
    @second.on('datachannel')
    def on_channel(remote):
        @remote.on('message')
        def on_message(data):
            remote.send(data)
    @channel.on('message')
    def on_message(data):
        if not received.done():
            received.set_result(data)
    try:
        await first.setLocalDescription(await first.createOffer())
        await second.setRemoteDescription(first.localDescription)
        await second.setLocalDescription(await second.createAnswer())
        await first.setRemoteDescription(second.localDescription)
        if await asyncio.wait_for(received, 15) != payload:
            raise RuntimeError('P2P payload mismatch')
    finally:
        await asyncio.gather(transport.close_pc(first), transport.close_pc(second))


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
        import asyncssh
        import certifi
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        key = asyncssh.generate_private_key('ssh-ed25519')
        signature = key.sign(b'package-check', b'ssh-ed25519')
        if not asyncssh.import_public_key(key.export_public_key()).verify(b'package-check', signature):
            raise RuntimeError('SSH signature failed')
        cipher = AESGCM(AESGCM.generate_key(bit_length=256))
        nonce = os.urandom(12)
        if cipher.decrypt(nonce, cipher.encrypt(nonce, b'check', b'context'), b'context') != b'check':
            raise RuntimeError('AES-GCM failed')
        if not Path(certifi.where()).is_file():
            raise RuntimeError('Missing HTTPS CA bundle')
        from hookup.game_chat import PROFILES
        from hookup.legacy_chat import PACKETS
        if not PROFILES or not PACKETS:
            raise RuntimeError('Missing protocol resources')
        result['checks'].extend(['ssh-ed25519', 'aes-gcm', 'https-ca', 'game-protocol-data'])
        from core.launch_options import complete_auth_arguments, offline_uuid
        if (offline_uuid('Notch') != 'b50ad385-829d-3141-a216-7e7d7539ba7f'
                or complete_auth_arguments(['${clientid}', '${auth_xuid}']) != ['', '0']):
            raise RuntimeError('Broken modern Minecraft authentication arguments')
        result['checks'].append('modern-minecraft-auth-arguments')
        asyncio.run(check_peer())
        result['checks'].extend(['webrtc-dtls-key', 'webrtc-65536-bytes-roundtrip'])

        from PySide6.QtWidgets import QApplication, QLineEdit
        from PySide6.QtCore import QTimer, QObject
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
            def exercise():
                try:
                    window.show()
                    from core.game_sessions import GameSessions
                    if not isinstance(window.launcher, GameSessions):
                        raise RuntimeError('Missing independent game session ownership')
                    if not hasattr(window.started_page, 'additional_game_btn'):
                        raise RuntimeError('Missing additional game launch control')
                    result['checks'].append('independent-game-sessions')
                    window.started_page.show_multiplayer_dialog()
                    lobby = window.started_page._multiplayer_dialog
                    from ui.dialog.ModpackImportDialog import ModpackImportDialog
                    importer = ModpackImportDialog()
                    if hasattr(importer, 'key_input') or len(importer.findChildren(QLineEdit)) != 2:
                        raise RuntimeError('Modpack import must not request an API key')
                    importer.close()
                    if lobby.quick.rootObject().findChild(QObject, 'export-diagnostics') is None:
                        raise RuntimeError('Missing multiplayer diagnostic export action')
                    from utils.diagnostics import export_diagnostics
                    from zipfile import ZipFile
                    game_logs = Path(temp) / 'test-game/logs'
                    game_logs.mkdir(parents=True)
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
                    lobby.show_friends()
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
