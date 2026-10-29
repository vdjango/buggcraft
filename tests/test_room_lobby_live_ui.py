"""Mouse/keyboard acceptance of shipped room QML against a real C++ node.

Only the launcher shell and account are fixtures. Controllers, native endpoints,
SSH authentication, membership, consent, chat and ownership are production code.
"""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest

from PySide6.QtCore import QEvent, QPointF, Qt, QUrl
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from _qml_test_support import qt_mouse_click
from test_lobby_layout import find_item
from hookup.native_transport import TunnelClient, TunnelHost, TunnelService
from hookup.profiles import RelayProfile
from ui.multiplayer_controller import MultiplayerController

ROOT = Path(__file__).resolve().parents[1]
NATIVE = Path(os.environ.get('BUGGCRAFT_NATIVE_SOURCE', ROOT.parent / 'minecraft-tunnel-native'))
GAME = dict(version='1.21.8', loader='vanilla', mods_count=0,
            mods_hash=hashlib.sha256(b'').hexdigest())


class Settings:
    def get_setting(self, name, default=None):
        return default


class LiveRoomUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        if not (NATIVE / 'scripts/benchmark_server.py').is_file():
            self.skipTest('Requires the native node source and built C++ runtime')
        self.work = tempfile.TemporaryDirectory(prefix='buggcraft-room-ui-')
        self.addCleanup(self.work.cleanup)
        self.node_errors = open(Path(self.work.name) / 'node.log', 'wb')
        self.node = subprocess.Popen([sys.executable, '-X', 'utf8',
            str(NATIVE / 'scripts/benchmark_server.py'), 'native', '--workers', '2'],
            cwd=NATIVE, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=self.node_errors, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self.addCleanup(self.close_node)
        with concurrent.futures.ThreadPoolExecutor(1) as pool:
            line = pool.submit(self.node.stdout.readline).result(timeout=20)
        self.assertTrue(line, 'Native node did not start; see isolated node.log')
        data = json.loads(line)
        self.profile = RelayProfile('127.0.0.1', data['port'], data['token'], data['key'])
        self.service = TunnelService()
        self.addCleanup(self.service.close)
        self.clients = []
        self.host = self.client('房主', 0)
        self.guest = self.client('朋友', 1)
        endpoint = TunnelHost(self.profile, game_port=0, transport_policy='relay',
            room_settings=dict(title='真实房间 UI 验收', public=False,
                game=GAME))
        self.host_id = self.host[0].start(endpoint, '真实房间 UI 验收')
        self.until(lambda: self.record(self.host).get('state') == 'online', 'Host failed to authenticate')
        self.guest_id = self.guest[0].start(TunnelClient(self.profile, endpoint.invite,
            transport_policy='relay'), '真实房间 UI 验收')
        self.until(lambda: all(self.record(client).get('lobby', {}).get('online') == 2
            for client in self.clients), 'Real member roster did not converge')
        self.until(lambda: all(self.record(client).get('chatState') == '在线'
            for client in self.clients), 'Native room chat is not ready')

    def close_node(self):
        if self.node.poll() is None:
            try:
                self.node.stdin.write(b'stop\n'); self.node.stdin.flush()
                self.node.wait(timeout=12)
            except (OSError, subprocess.TimeoutExpired):
                self.node.kill(); self.node.wait(timeout=5)
        self.node_errors.close()
        self.node.stdin.close()
        self.node.stdout.close()

    def client(self, nickname, index):
        shell = QWidget()
        shell.settings_manager = Settings()
        shell.auth_manager = SimpleNamespace(current=SimpleNamespace(username=nickname))
        shell.launcher = SimpleNamespace(running=False, start_thread=None,
            minecraft_directory=self.work.name, minecraft_version='')
        shell.current_client = False
        dialog = QDialog(shell)
        controller = MultiplayerController(dialog, Path(self.work.name) / (str(index) + '.json'))
        controller.service.close()
        controller.service = self.service
        controller.friend_timer.stop()
        controller.game = GAME.copy()
        controller.patch(nodeAvailable=True)
        window = QQuickView()
        window.resize(721, 505)
        window.setPosition(20 + index * 745, 50)
        window.rootContext().setContextProperty('lobby', controller)
        window.setSource(QUrl.fromLocalFile(str(ROOT / 'resources/qml/multiplayer/Lobby.qml')))
        self.assertEqual(window.status(), QQuickView.Ready)
        window.show()
        client = (controller, window, dialog, shell)
        self.clients.append(client)
        def dispose():
            window.close(); window.setSource(QUrl()); window.deleteLater()
            controller.close(); dialog.close(); shell.close()
            self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.addCleanup(dispose)
        return client

    def until(self, condition, message, seconds=18):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.app.processEvents()
            if condition():
                return
            QTest.qWait(40)
        self.fail(message)

    def record(self, client):
        controller = client[0]
        return controller.records.get(controller.view['selected'], {})

    def click(self, client, name):
        window = client[1]
        window.raise_(); window.requestActivate(); QTest.qWait(40)
        item = find_item(window, name)
        self.assertTrue(item.isVisible(), name)
        self.assertTrue(item.isEnabled(), name)
        point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
        qt_mouse_click(window, point); QTest.qWait(80)

    def test_real_room_chat_consent_revocation_and_ownership_from_visible_controls(self):
        host, guest = self.host, self.guest
        manager_id = self.record(host)['lobby']['manager_id']
        for client in (host, guest):
            self.click(client, 'room-tab-members')
            self.assertTrue(find_item(client[1], 'room-member-' + manager_id).isVisible())
            role = find_item(client[1], 'member-role-' + manager_id)
            self.assertTrue(role.isVisible())
            self.assertEqual(role.property('text'), '房主')
        self.click(guest, 'room-tab-chat')
        self.click(guest, 'room-chat-input')
        self.assertTrue(find_item(guest[1], 'room-chat-input').hasActiveFocus(),
            'Chat field did not receive focus from the mouse click')
        message = 'NATIVE UI CHAT'
        for character in message:
            QTest.keyClick(guest[1], ord(character))
        self.assertEqual(find_item(guest[1], 'room-chat-input').property('text'), message)
        self.click(guest, 'room-chat-send')
        self.until(lambda: any(message in str(row) for row in
            self.record(host).get('chatMessages', [])), 'Chat did not reach host through C++ bridge')
        target = self.record(guest)['lobby']['self_id']
        self.click(host, 'room-tab-members')
        self.click(host, 'member-menu-' + target)
        self.click(host, 'member-install-logs')
        self.until(lambda: bool(self.record(guest)['lobby']['logs'].get('request')),
            'Consent request was not delivered')
        self.assertFalse(self.record(host).get('remoteLogs'))
        self.click(guest, 'room-log-allow')
        self.until(lambda: target in self.record(host)['lobby']['logs'].get('allowed', []),
            'Grant was not authenticated by node')
        guest[0].add_prepare_log(self.record(guest), 'sodium.jar verified C:\\Users\\Private\\mods token=secret', 'mods')
        self.until(lambda: self.record(guest).get('_logUploadCursor', 0) > 0,
            'Authorized log was not uploaded')
        self.click(host, 'member-menu-' + target)
        self.click(host, 'member-install-logs')
        self.until(lambda: bool(self.record(host).get('remoteLogs')), 'Authorized log did not reach UI')
        rows = self.record(host)['remoteLogs']
        self.assertIn('sodium.jar', rows[0]['text'])
        self.assertNotIn('Private', rows[0]['text'])
        self.assertNotIn('secret', rows[0]['text'])
        output = ROOT / 'build/room-preparation-ui'
        output.mkdir(parents=True, exist_ok=True)
        self.assertTrue(host[1].grabWindow().save(str(output / 'real-node-authorized-logs.png')))
        self.click(guest, 'revoke-room-log-access')
        self.until(lambda: not self.record(host).get('remoteLogs') and
            target not in self.record(host)['lobby']['logs'].get('allowed', []), 'Revoked logs remained accessible')
        self.click(host, 'close-remote-log')
        self.click(host, 'member-menu-' + target)
        self.click(host, 'member-offer-owner')
        self.click(host, 'member-confirm-submit')
        self.until(lambda: bool(self.record(guest)['lobby'].get('transfer')), 'Transfer offer was not delivered')
        self.assertTrue(self.record(host)['isManager'])
        self.click(guest, 'room-tab-members')
        self.click(guest, 'room-owner-accept')
        self.until(lambda: self.record(guest).get('isManager') and not self.record(host).get('isManager'),
            'Ownership did not converge across native sessions')
        self.assertEqual(self.record(guest)['lobby']['provider_id'], self.record(host)['lobby']['self_id'])
        self.assertEqual(self.record(guest)['availability'], 'waiting')
        self.assertTrue(guest[1].grabWindow().save(str(output / 'real-node-transferred-manager.png')))
