"""Shipping QML chat -> actual game roles -> shipping QML chat, with recovery."""
import asyncio
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / '.test-tools'), str(ROOT / 'buggcraft/src/buggcraft')]
import test_game_chat as game_fixture
from PySide6.QtCore import QPointF, Qt, Signal, qInstallMessageHandler
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from config.settings import SettingsManager
from ui.dialog.MultiplayerDialog import MultiplayerDialog


class StartPage(QWidget):
    instance_changed = Signal()

    def __init__(self, work, game_root, index):
        super().__init__()
        self.settings_manager = SettingsManager(str(work / f'settings-{index}'))
        self.settings_manager.set_setting('minecraft.directory.enable', str(game_root))
        self.settings_manager.set_setting('minecraft.version.enable', '1.21.8')
        self.launcher = SimpleNamespace(minecraft_directory=str(game_root),
            minecraft_version='1.21.8', minecraft_isolation_directory=str(game_root))
        self.auth_manager = SimpleNamespace(current=SimpleNamespace(username=f'LobbyTest{index}'))
        self.current_client = False


@unittest.skipIf(getattr(game_fixture.RealGameChatTests, '__unittest_skip__', False),
                 'Local Java 21, server 1.21.8 and Mineflayer fixtures required')
class GameChatUiTests(unittest.IsolatedAsyncioTestCase):
    console_artifact = 'chat-game-ui-console.log'

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    async def asyncSetUp(self):
        self.dialogs, self.parents, self.qml_messages = [], [], []
        self.old_handler = qInstallMessageHandler(lambda kind, context, text: self.qml_messages.append(text))
        self.addCleanup(lambda: qInstallMessageHandler(self.old_handler))
        await game_fixture.RealGameChatTests.asyncSetUp(self)
        self.game_root = self.work / 'minecraft'
        metadata = self.game_root / 'versions/1.21.8/1.21.8.json'
        metadata.parent.mkdir(parents=True)
        metadata.write_text(json.dumps({'id': '1.21.8'}), encoding='utf8')
        self.profile_path = self.work / 'relay.json'
        self.profile_path.write_text(json.dumps(dict(server_host=self.profile.server_host,
            server_port=self.profile.server_port, token=self.profile.token,
            server_public_key=self.profile.server_public_key)), encoding='utf8')

    async def wait(self, condition, timeout=20):
        async with asyncio.timeout(timeout):
            while True:
                self.app.processEvents()
                if condition():
                    return
                await asyncio.sleep(.02)

    async def cleanup(self):
        try:
            # Keep the relay's event loop running while the UI services disconnect.
            async def stop(service):
                await asyncio.gather(*(e.stop() for e in service.endpoints.values()),
                                     return_exceptions=True)
                service.endpoints.clear()
            await asyncio.gather(*(asyncio.wrap_future(d.service.submit(stop(d.service)))
                                   for d in self.dialogs))
            for dialog in self.dialogs:
                dialog.shutdown()
            for parent in self.parents:
                parent.close()
        finally:
            await game_fixture.RealGameChatTests.cleanup(self)

    def item(self, dialog, name):
        stack = [dialog.quick.quickWindow().contentItem()]
        while stack:
            item = stack.pop()
            if isinstance(item, QQuickItem) and item.objectName() == name:
                return item
            stack.extend(item.childItems())
        self.fail('Missing QML item ' + name)

    def click(self, dialog, name):
        target = self.item(dialog, name)
        self.assertTrue(target.isVisible() and target.isEnabled(), name)
        parent = target.parentItem()
        while parent:
            if parent.metaObject().indexOfProperty('contentY') >= 0:
                y = target.mapToItem(parent, QPointF(0, 0)).y()
                if y < 0 or y + target.height() > parent.height():
                    parent.setProperty('contentY', max(0., parent.property('contentY') + y - 12))
            parent = parent.parentItem()
        QTest.qWait(25)
        point = target.mapToScene(QPointF(target.width() / 2, target.height() / 2)).toPoint()
        self.assertTrue(0 <= point.x() < dialog.width() and 0 <= point.y() < dialog.height(), (name, point))
        QTest.mouseClick(dialog.quick, Qt.LeftButton, Qt.NoModifier, point)
        self.app.processEvents()

    def fill(self, dialog, name, text):
        self.click(dialog, name)
        dialog.activateWindow()
        dialog.quick.setFocus()
        self.item(dialog, name).forceActiveFocus()
        dialog.quick.quickWindow().requestActivate()
        QTest.qWait(80)
        QTest.keyClick(dialog.quick.quickWindow(), Qt.Key_A, Qt.ControlModifier)
        QApplication.clipboard().setText(text)
        QTest.keyClick(dialog.quick.quickWindow(), Qt.Key_V, Qt.ControlModifier)
        self.app.processEvents()
        self.assertEqual(self.item(dialog, name).property('text'), text, name)

    async def window(self):
        index = len(self.dialogs)
        parent = StartPage(self.work, self.game_root, index)
        self.parents.append(parent)
        dialog = MultiplayerDialog(parent, storage_path=self.work / f'lobby-{index}.json')
        self.dialogs.append(dialog)
        dialog.show()
        dialog.timer.stop()
        await self.wait(lambda: dialog.backend.game.get('version') == '1.21.8'
                        and not dialog.backend.view['instanceLoading'])
        dialog.backend.import_node(str(self.profile_path))
        await self.wait(lambda: not dialog.backend.view['busy'] and
                        dialog.backend.view['nodeIndex'] >= 0 and not dialog.backend.view['loading'])
        return dialog

    def endpoint(self, dialog):
        return dialog.service.endpoints[dialog.backend.view['selected']]

    async def online(self, dialog):
        await self.wait(lambda: dialog.backend.view['chatState'] == '在线'
            and dialog.backend.view['selected']
            and dialog.backend.records[dialog.backend.view['selected']]['state'] == 'online')

    def visible_message(self, dialog, text):
        stack = list(self.item(dialog, 'room-chat-messages').childItems())
        while stack:
            item = stack.pop()
            if item.isVisible() and text in str(item.property('text') or ''):
                return True
            stack.extend(item.childItems())
        return False

    async def send_lobby(self, dialog, text, enter=False):
        self.fill(dialog, 'room-chat-input', text)
        if enter:
            QTest.keyClick(dialog.quick.quickWindow(), Qt.Key_Return)
        else:
            self.click(dialog, 'room-chat-send')
        await self.wait(lambda: not dialog.backend.view['chatSending']
                        and dialog.backend.view['chatDraft'] == '')
        self.assertEqual(dialog.backend.view['chatError'], '')
        await self.wait(lambda: all(any(e['type'] == 'message' and e['index'] == i
            and text in e['text'] for e in self.game_events) for i in range(4)))

    async def send_game(self, index, text):
        self.players.stdin.write((json.dumps({'op': 'chat', 'index': index, 'text': text}) + '\n').encode())
        await self.players.stdin.drain()
        await self.wait(lambda: all(self.visible_message(d, text) for d in self.dialogs))
        for dialog in self.dialogs:
            messages = [m for m in dialog.backend.view['chatMessages'] if m.get('text') == text]
            self.assertEqual(len(messages), 1)
            self.assertEqual(messages[0]['source'], 'game')
            self.assertEqual(messages[0]['sender'], 'ChatTest' + str(index))

    async def test_four_launcher_windows_ten_rounds_chat_reaches_game_and_visible_ui(self):
        host = await self.window()
        self.click(host, 'open-create')
        self.click(host, 'show-manual')
        self.fill(host, 'create-port', str(self.port))
        self.click(host, 'create-next')
        await self.wait(lambda: host.backend.view['step'] == 1)
        self.fill(host, 'create-title', 'Game and lobby chat')
        self.assertFalse(self.item(host, 'create-game-chat').property('checked'))
        self.click(host, 'create-game-chat')
        self.fill(host, 'create-game-chat-name', 'LobbyBridge')
        self.click(host, 'create-next')
        await self.online(host)
        await self.wait(lambda: host.backend.view['bridgeStatus'] == '游戏聊天已同步', 30)
        self.assertEqual(self.endpoint(host).bridge.name, 'LobbyBridge')
        self.click(host, 'copy-invite')
        invite = QApplication.clipboard().text()
        clients = []
        for _ in range(3):
            client = await self.window()
            self.click(client, 'open-join')
            self.fill(client, 'join-invite', invite)
            self.click(client, 'join-confirm')
            await self.online(client)
            clients.append(client)
        self.players = await asyncio.create_subprocess_exec('node', str(game_fixture.FIXTURE),
            str(self.port), *(str(self.endpoint(d).listen_port) for d in clients),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        self.tasks.append(asyncio.create_task(game_fixture.RealGameChatTests.read_players(self)))
        await self.wait(lambda: sum(e['type'] == 'spawn' for e in self.game_events) == 4, 40)
        for turn in range(10):
            await self.send_lobby(self.dialogs[turn % 4], f'界面到游戏-{turn}-😀', enter=bool(turn % 2))
            await self.send_game(turn % 4, f'游戏到大厅-{turn}-你好')
            await asyncio.sleep(.7)
        client = clients[0]
        old_process = self.endpoint(client).chat_process
        async def disconnect_chat():
            old_process.close()
        await asyncio.wrap_future(client.service.submit(disconnect_chat()))
        await self.wait(lambda: client.backend.view['chatState'] == '在线'
                        and self.endpoint(client).chat_process is not None
                        and self.endpoint(client).chat_process is not old_process)
        await self.send_lobby(client, '界面重连后到游戏')
        await self.send_game(1, '游戏到重连后的大厅')
        for dialog in self.dialogs:
            dialog.quick.grab().save(str(ROOT / 'multiplayer-tests' /
                                        f'chat-game-ui-{self.dialogs.index(dialog)}.png'))
        self.assertFalse([e for e in self.game_events if e['type'] in ('error', 'kicked')])
        self.assertFalse([m for m in self.qml_messages if any(error in m for error in
            ('TypeError:', 'ReferenceError:', 'Unable to assign', 'Binding loop', 'Cannot anchor'))])
        result = dict(version='1.21.8', protocol=772, launcherWindows=4, gamePlayers=4,
            clientTunnels=3, rounds=10, directions=['qml-to-game', 'game-to-visible-qml'],
            chatReconnect=True, network='public-relay' if self.profile.server_host != '127.0.0.1' else 'loopback', result='passed',
            server='integrated-encrypted-lan' if getattr(self, 'integrated_port', None) else 'dedicated-offline')
        (ROOT / 'multiplayer-tests' / getattr(self, 'result_artifact', 'chat-game-ui-result.json')).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')

    async def test_public_direct_and_invite_access_from_qml_enter_real_world(self):
        from hookup.relay import RoomInvite
        from hookup.rooms import game_status
        host = await self.window()
        clients = [await self.window() for _ in range(3)]
        results = []
        for require_invite in (False, True):
            with self.subTest(require_invite=require_invite):
                self.click(host, 'open-create')
                self.click(host, 'show-manual')
                self.fill(host, 'create-port', str(self.port))
                self.click(host, 'create-next')
                await self.wait(lambda: host.backend.view['step'] == 1)
                self.fill(host, 'create-title', 'Public access verification')
                self.click(host, 'create-public')
                if require_invite:
                    self.click(host, 'create-require-invite')
                self.click(host, 'create-next')
                await self.online(host)
                endpoint = self.endpoint(host)
                invite = endpoint.invite.encode()
                self.assertEqual(endpoint.room_info['require_invite'], require_invite)
                for client in clients:
                    client.backend.refresh()
                    await self.wait(lambda: any(r['id'] == endpoint.invite.room_id
                        for r in client.backend.view['rooms']) and not client.backend.view['loading'])
                    self.click(client, 'join-public-0')
                    if require_invite:
                        await self.wait(lambda: client.backend.view['invitePrompt'])
                        self.assertEqual(client.backend.view['joinRoomId'], endpoint.invite.room_id)
                        self.fill(client, 'room-invite-input', RoomInvite.create().encode())
                        self.click(client, 'confirm-room-invite')
                        self.assertIn('不属于所选房间', client.backend.view['error'])
                        self.assertEqual(client.backend.view['connections'], [])
                        self.fill(client, 'room-invite-input', invite)
                        self.click(client, 'confirm-room-invite')
                    await self.online(client)
                self.game_events.clear()
                self.players = await asyncio.create_subprocess_exec('node', str(game_fixture.FIXTURE),
                    str(self.port), *(str(self.endpoint(d).listen_port) for d in clients),
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE)
                self.tasks.append(asyncio.create_task(game_fixture.RealGameChatTests.read_players(self)))
                await self.wait(lambda: sum(e['type'] == 'spawn' for e in self.game_events) == 4, 40)
                self.assertEqual((await game_status(self.port))['players']['online'], 4)
                for turn in range(10):
                    text = f'access-{int(require_invite)}-round-{turn}'
                    self.players.stdin.write((json.dumps({'op':'chat', 'index':turn % 4,
                                                          'text':text}) + '\n').encode())
                    await self.players.stdin.drain()
                    await self.wait(lambda: all(any(e['type'] == 'message' and e['index'] == i
                        and text in e['text'] for e in self.game_events) for i in range(4)))
                self.assertFalse([e for e in self.game_events if e['type'] in ('error', 'kicked')])
                self.players.stdin.write(b'{"op":"close"}\n')
                await self.players.stdin.drain()
                await asyncio.wait_for(self.players.wait(), 10)
                await self.wait(lambda: sum(e['type'] == 'spawn' for e in self.game_events) == 4)
                self.click(host, 'back-hall')
                self.assertTrue(host.backend.view['connections'])
                self.click(host, 'confirm-leave-room')
                await self.wait(lambda: all(not d.backend.view['connections'] for d in self.dialogs))
                self.assertTrue(all(d.backend.view['page'] == 'hall' for d in self.dialogs))
                results.append(dict(requireInvite=require_invite, gamePlayers=4,
                    chatRounds=10, closedRoomNotified=True, result='passed'))
        self.assertFalse([m for m in self.qml_messages if any(error in m for error in
            ('TypeError:', 'ReferenceError:', 'Unable to assign', 'Binding loop', 'Cannot anchor'))])
        (ROOT / 'multiplayer-tests/room-access-game-ui-result.json').write_text(
            json.dumps(dict(version='1.21.8', launcherWindows=4, modes=results,
                            network='loopback', result='passed'), indent=2), encoding='utf8')


if __name__ == '__main__':
    unittest.main(verbosity=2)
