"""Room actions stay locked until a directory node has been verified."""
import os
import asyncio
import secrets
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[2]
import sys
sys.path[:0] = [str(ROOT / '.test-tools'), str(ROOT / 'buggcraft/src/buggcraft'),
               str(ROOT / 'minecraft-tunnel/src')]

from PySide6.QtWidgets import QApplication, QDialog
from ui.multiplayer_controller import MultiplayerController
from hookup.relay import RoomInvite
from hookup.relay import RelayProfile
from hookup.nodes import save_json, profile_data
import hookup.rooms as room_sdk
import asyncssh
from tunnel.relay import RelayServer, Room
from tunnel.directory import RoomControlSession


class NodeAvailabilityControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.window = QDialog()
        self.service = Mock(endpoints={})
        with patch('ui.multiplayer_controller.TunnelService', return_value=self.service):
            self.controller = MultiplayerController(self.window, Path(self.work.name) / 'lobby.json')
        self.addCleanup(self.controller.close)
        self.addCleanup(self.window.close)
        self.controller.node_path = 'configured-node'
        self.job_patch = patch.object(self.controller, 'job',
            side_effect=lambda key, coroutine: coroutine.close())
        self.job = self.job_patch.start()
        self.addCleanup(self.job_patch.stop)

    def test_no_configured_node_blocks_create_and_invite_join(self):
        self.controller.node_path = ''
        self.controller.act('createWaiting', {})
        self.assertIn('可用的联机节点', self.controller.view['error'])
        invite = RoomInvite.create().encode()
        self.controller.act('join', {'invite': invite})
        self.assertIn('可用的联机节点', self.controller.view['error'])
        self.assertEqual(self.service.endpoints, {})

    def test_configured_but_unverified_node_blocks_every_join_path(self):
        self.controller.patch(nodeAvailable=False)
        self.controller.act('navigate', {'page': 'create'})
        self.assertEqual(self.controller.view['page'], 'hall')
        self.controller.act('joinPublic', {'id': '0' * 32})
        self.assertIn('节点不可用', self.controller.view['error'])
        self.controller.act('join', {'invite': RoomInvite.create().encode()})
        self.assertIn('节点不可用', self.controller.view['error'])

    def test_successful_first_page_unlocks_and_failed_refresh_locks_again(self):
        generation = self.controller.room_generation
        self.controller.finish('rooms:' + generation + ':0',
            {'rooms': [], 'next': None, 'total': 0, 'node_name': ''}, None)
        self.assertTrue(self.controller.view['nodeAvailable'])
        self.controller.refresh()
        self.assertFalse(self.controller.view['nodeAvailable'])
        self.assertEqual(self.controller.view['rooms'], [])
        current = self.controller.room_generation
        self.controller.finish('rooms:' + current + ':0', None, ConnectionError('offline'))
        self.assertFalse(self.controller.view['nodeAvailable'])
        self.assertIn('无法连接节点', self.controller.view['roomError'])

    def test_old_page_result_cannot_unlock_after_a_new_refresh(self):
        old = self.controller.room_generation
        self.controller.refresh()
        self.assertNotEqual(old, self.controller.room_generation)
        self.controller.finish('rooms:' + old + ':0',
            {'rooms': [], 'next': None, 'total': 0, 'node_name': ''}, None)
        self.assertFalse(self.controller.view['nodeAvailable'])

    def test_node_loss_during_creation_disables_backend_submission(self):
        c = self.controller
        c.creation = {'path': c.node_path, 'game': {'version':'1.21.8'}, 'port':0}
        c.game = {'version':'1.21.8'}
        c.patch(page='create', step=1, nodeAvailable=False)
        with patch.object(c, 'start') as start:
            for action, data in [('create', {'title':'World'}), ('createWaiting', {}),
                                 ('probe', {'port':25565}), ('joinFriend', {'index':0})]:
                with self.subTest(action=action):
                    c.act(action, data)
                    self.assertIn('节点不可用', c.view['error'])
            start.assert_not_called()
        self.assertEqual(c.view['page'], 'create')

    def test_health_failure_and_recovery_preserve_loaded_rooms_and_form(self):
        c = self.controller
        rows = [{'id':'one', 'title':'World'}]
        c.patch(page='join', rooms=rows, roomNext=20, nodeAvailable=True)
        key = 'nodehealth:' + c.node_check_generation
        c.finish(key, None, 'connection refused')
        self.assertFalse(c.view['nodeAvailable'])
        self.assertEqual(c.view['rooms'], rows)
        self.assertEqual(c.view['page'], 'join')
        c.finish(key, None, None)
        self.assertTrue(c.view['nodeAvailable'])
        self.assertEqual(c.view['roomError'], '')
        self.assertEqual(c.view['roomNext'], 20)

    def test_refresh_invalidates_in_flight_health_check(self):
        c = self.controller
        key = 'nodehealth:' + c.node_check_generation
        c.refresh()
        c.finish(key, None, None)
        self.assertFalse(c.view['nodeAvailable'])

    def test_removed_last_node_cannot_be_unlocked_by_its_pending_response(self):
        c = self.controller
        old = 'rooms:' + c.room_generation + ':0'
        c.patch(nodeAvailable=True)
        c.reload_store()
        self.assertEqual(c.node_path, '')
        self.assertFalse(c.view['nodeAvailable'])
        c.finish(old, {'rooms':[], 'next':None, 'total':0, 'node_name':''}, None)
        self.assertFalse(c.view['nodeAvailable'])

    def test_invalid_saved_profile_is_not_a_usable_node(self):
        c = self.controller
        c.patch(nodeAvailable=True)
        c.act('navigate', {'page':'join'})
        self.assertFalse(c.view['nodeAvailable'])
        self.assertEqual(c.view['page'], 'hall')
        self.assertIn('重新导入', c.view['error'])

    def test_pagination_retries_same_cursor_and_deduplicates_on_success(self):
        c = self.controller
        rows = [{'id':str(i)} for i in range(20)]
        c.patch(rooms=rows, roomNext=20, roomTotal=45, nodeAvailable=True)
        with patch.object(c, 'profile', return_value=Mock()):
            c.load_more_rooms()
            key = self.job.call_args.args[0]
            self.assertTrue(c.view['loadingMore'])
            c.load_more_rooms()
            self.assertEqual(self.job.call_count, 1)
            c.finish(key, None, 'network failure')
            self.assertEqual(c.view['roomNext'], 20)
            self.assertEqual(c.view['rooms'], rows)
            self.assertFalse(c.view['nodeAvailable'])
            c.load_more_rooms()
            self.assertEqual(self.job.call_args.args[0], key)
            c.finish(key, {'rooms':[rows[-1], {'id':'20'}], 'next':40, 'total':45, 'node_name':''}, None)
        self.assertEqual(len(c.view['rooms']), 21)
        self.assertTrue(c.view['nodeAvailable'])
        self.assertFalse(c.view['loadingMore'])

    def test_search_debounces_and_invalidates_previous_page(self):
        c = self.controller
        old = c.room_generation
        c.patch(rooms=[{'id':'old'}], roomNext=20)
        c.act('searchRooms', {'text':'fabric'})
        self.assertTrue(c.room_search_timer.isActive())
        self.assertEqual(c.view['roomQuery'], 'fabric')
        self.assertEqual(c.view['rooms'], [])
        c.finish('rooms:' + old + ':20',
                 {'rooms':[{'id':'stale'}], 'next':None, 'total':21, 'node_name':''}, None)
        self.assertEqual(c.view['rooms'], [])

    def test_cancelled_invite_dialog_ignores_late_room_resolution(self):
        c = self.controller
        old = c.generation
        c.patch(invitePrompt=True, joinRoomId='old', joinRoomTitle='Old')
        c.act('cancelInvite', {})
        c.finish('resolve:' + old, {'path':c.node_path, 'room':{
            'id':'old', 'title':'Old', 'require_invite':True}}, None)
        self.assertFalse(c.view['invitePrompt'])
        self.assertEqual(c.view['joinRoomId'], '')


class RoomPageSdkTests(unittest.IsolatedAsyncioTestCase):
    def room(self, number, title=None):
        return {'id': f'{number:032x}', 'title': title or f'Room {number}',
                'require_invite': False, 'connections': 1, 'capacity': 100,
                'members': 1, 'game_players': None,
                'game': {'version': '1.21.8', 'loader': 'vanilla',
                         'loader_version': '', 'mods_hash': '', 'mods_count': 0, 'mods': []}}

    async def test_new_node_returns_stable_twenty_room_pages(self):
        profile = SimpleNamespace(server_host='node', server_port=1, server_public_key='key')
        pages = {0: list(range(0, 20)), 20: list(range(20, 40)), 40: list(range(40, 45))}
        class Connection:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return False

        async def request(connection, operation, **fields):
            if operation == 'ping':
                return {'capabilities': ['room-list-page-v1'], 'name': ''}
            offset = fields['offset']
            values = pages[offset]
            end = offset + len(values)
            return {'rooms': [self.room(i) for i in values],
                    'next': end if end < 45 else None, 'total': 45}

        with patch.object(room_sdk, 'connect_directory', AsyncMock(return_value=Connection())), \
                patch.object(room_sdk, 'request', side_effect=request), \
                patch.object(room_sdk, 'remember_topology', AsyncMock()):
            result = await room_sdk.list_room_page(profile)
            all_rooms = list(result['rooms'])
            self.assertEqual((len(all_rooms), result['next'], result['total']), (20, 20, 45))
            result = await room_sdk.list_room_page(profile, offset=result['next'])
            all_rooms.extend(result['rooms'])
            result = await room_sdk.list_room_page(profile, offset=result['next'])
            all_rooms.extend(result['rooms'])
        self.assertEqual(len({room['id'] for room in all_rooms}), 45)

    async def test_old_node_cursor_preserves_rooms_after_local_filtering(self):
        profile = SimpleNamespace(server_host='node', server_port=1, server_public_key='key')
        rows = [self.room(i, title=('match ' if i >= 22 else 'other ') + str(i)) for i in range(25)]
        class Connection:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return False

        async def request(connection, operation, **fields):
            if operation == 'ping':
                return {'capabilities': [], 'name': ''}
            offset = fields['offset']
            return {'rooms': rows[offset:], 'next': None}

        with patch.object(room_sdk, 'connect_directory', AsyncMock(return_value=Connection())), \
                patch.object(room_sdk, 'request', side_effect=request), \
                patch.object(room_sdk, 'remember_topology', AsyncMock()):
            result = await room_sdk.list_room_page(profile, query='match')
        self.assertEqual([room['title'] for room in result['rooms']],
                         ['match 22', 'match 23', 'match 24'])
        self.assertIsNone(result['next'])


class LocalNodeAvailabilityTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    async def wait(self, condition):
        async with asyncio.timeout(12):
            while True:
                self.app.processEvents()
                if condition():
                    return
                await asyncio.sleep(.01)

    async def asyncSetUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.window = QDialog()
        self.controller = MultiplayerController(self.window, Path(self.work.name) / 'lobby.json')
        self.key = asyncssh.generate_private_key('ssh-ed25519')
        self.token = secrets.token_urlsafe(48)
        self.relay = await RelayServer('127.0.0.1', 0, host_key=self.key, token=self.token).start()
        self.port = self.relay.port
        self.profile = RelayProfile('127.0.0.1', self.port, self.token,
                                    self.key.export_public_key().decode())
        self.profile_path = Path(self.work.name) / 'node.json'
        save_json(self.profile_path, profile_data(self.profile))
        self.controller.store.add_node(str(self.profile_path))
        self.controller.reload_store()
        await self.wait(lambda: not self.controller.view['loading'])
        self.assertTrue(self.controller.view['nodeAvailable'])

    async def asyncTearDown(self):
        self.controller.close()
        self.window.close()
        await self.relay.close()
        self.app.processEvents()
        self.work.cleanup()

    async def test_ten_actual_node_disconnects_and_recoveries_gate_room_creation(self):
        c = self.controller
        for turn in range(10):
            with self.subTest(turn=turn):
                await self.relay.close()
                c.check_node()
                key = 'nodehealth:' + c.node_check_generation
                await self.wait(lambda: key not in c.jobs)
                self.assertFalse(c.view['nodeAvailable'])
                c.act('createWaiting', {})
                self.assertIn('节点不可用', c.view['error'])
                c.act('join', {'invite':RoomInvite.create().encode()})
                self.assertIn('节点不可用', c.view['error'])
                self.assertEqual(c.service.endpoints, {})
                self.relay = await RelayServer('127.0.0.1', self.port,
                                              host_key=self.key, token=self.token).start()
                c.check_node()
                await self.wait(lambda: key not in c.jobs)
                self.assertTrue(c.view['nodeAvailable'])
                c.act('navigate', {'page':'create'})
                self.assertEqual(c.view['page'], 'create')
                c.act('navigate', {'page':'hall'})

    async def test_real_encrypted_directory_pages_and_search_beyond_initial_twenty(self):
        for index in reversed(range(45)):
            self.relay.rooms[f'{index:032x}'] = Room(owner=SimpleNamespace(relay=self.relay),
                title='Target room' if index == 44 else f'Room {index}', port=25565,
                public=True, game={'version':'1.21.8', 'loader':'vanilla'})
        c = self.controller
        c.refresh()
        await self.wait(lambda: not c.view['loading'])
        self.assertEqual((len(c.view['rooms']), c.view['roomNext'], c.view['roomTotal']), (20, 20, 45))
        c.load_more_rooms()
        await self.wait(lambda: not c.view['loadingMore'])
        self.assertEqual((len(c.view['rooms']), c.view['roomNext']), (40, 40))
        c.load_more_rooms()
        await self.wait(lambda: not c.view['loadingMore'])
        self.assertEqual(len(c.view['rooms']), 45)
        self.assertEqual(len({room['id'] for room in c.view['rooms']}), 45)
        self.assertIsNone(c.view['roomNext'])
        c.act('searchRooms', {'text':'target'})
        await self.wait(lambda: not c.room_search_timer.isActive() and not c.view['loading'])
        self.assertEqual([room['title'] for room in c.view['rooms']], ['Target room'])
        self.assertEqual(c.view['roomTotal'], 1)

    async def test_server_rejects_invalid_page_parameters(self):
        async with await room_sdk.connect_directory(self.profile) as connection:
            for fields in ({'limit':True}, {'limit':0}, {'limit':51},
                           {'offset':-1}, {'offset':True}, {'query':'a' * 101}):
                with self.subTest(fields=fields), self.assertRaises(ConnectionError):
                    await room_sdk.request(connection, 'list', **fields)

    async def test_older_node_slices_full_pages_without_losing_any_rooms(self):
        for index in range(65):
            self.relay.rooms[f'{index:032x}'] = Room(owner=SimpleNamespace(relay=self.relay),
                title=f'Room {index}', port=25565, public=True, game={'version':'1.21.8'})
        original = RoomControlSession.dispatch
        def old_dispatch(session, payload):
            if payload.get('op') == 'ping':
                return {'capabilities':[], 'name':''}
            if payload.get('op') == 'list':
                payload = {'op':'list', 'offset':payload.get('offset', 0)}
            return original(session, payload)
        with patch.object(RoomControlSession, 'dispatch', old_dispatch):
            offset, rows, sizes = 0, [], []
            while True:
                page = await room_sdk.list_room_page(self.profile, offset=offset)
                rows.extend(page['rooms'])
                sizes.append(len(page['rooms']))
                if page['next'] is None:
                    break
                offset = page['next']
        self.assertEqual(sizes, [20, 20, 20, 5])
        self.assertEqual([room['id'] for room in rows], [f'{i:032x}' for i in range(65)])


if __name__ == '__main__':
    unittest.main()
