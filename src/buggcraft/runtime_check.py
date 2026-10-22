"""Exercise shipped GUI and native libraries without touching user settings."""
import asyncio
import json
import logging
import os
from pathlib import Path
import tempfile
import traceback


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
        asyncio.run(check_peer())
        result['checks'].extend(['webrtc-dtls-key', 'webrtc-65536-bytes-roundtrip'])

        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QTimer
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
            from windows.main_window import MinecraftLauncher
            window = MinecraftLauncher(str(resources.parent), temp, temp, str(resources))
            def exercise():
                try:
                    window.show()
                    window.started_page.show_multiplayer_dialog()
                    lobby = window.started_page._multiplayer_dialog
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
