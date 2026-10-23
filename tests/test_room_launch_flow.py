"""Room membership, runtime locking and launch decisions in the real controller."""
import asyncio
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / '.test-tools'), str(ROOT / 'buggcraft/src/buggcraft')]
from PySide6.QtWidgets import QApplication, QDialog, QWidget
from ui.multiplayer_controller import MultiplayerController
from hookup.relay import RoomInvite


class RoomLaunchFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.parent = QWidget()
        self.addCleanup(self.parent.close)
        self.parent.current_client = False
        self.parent.launcher = SimpleNamespace(running=False, start_thread=None,
            minecraft_directory=work.name, minecraft_version='selected')
        self.parent.settings_manager = Mock()
        self.parent.settings_manager.get_minecraft_isolation_directory.return_value = work.name
        self.parent.auth_manager = Mock()
        self.parent.auth_manager.is_authenticated.return_value = True
        self.parent.started_game = Mock()
        self.window = QDialog(self.parent)
        self.addCleanup(self.window.close)
        self.service = Mock(endpoints={})
        with patch('ui.multiplayer_controller.TunnelService', return_value=self.service):
            self.controller = MultiplayerController(self.window, Path(work.name) / 'rooms.json')
        self.addCleanup(self.controller.close)
        self.controller.records['room'] = dict(id='room', role='client', state='online',
            availability='ready', compatibility='', game={'version':'1.21.8'}, preparing=False)
        self.service.endpoints['room'] = SimpleNamespace(listen_port=34567, role='client')
        self.controller.node_path = 'fixture-node'
        self.controller.patch(selected='room', nodeAvailable=True)

    def test_quick_launch_supports_both_account_modes_and_never_stops_running_game(self):
        for mode in ('online', 'offline'):
            self.parent.auth_manager.current_mode = mode
            self.controller.launch_room()
            self.parent.started_game.assert_called_with(server='127.0.0.1:34567')
        self.parent.started_game.reset_mock()
        self.parent.launcher.running = True
        self.controller.launch_room()
        self.parent.started_game.assert_not_called()
        self.assertIn('已经运行', self.controller.view['notice'])

    def test_waiting_and_mismatched_clients_cannot_launch_wrong_game(self):
        record = self.controller.records['room']
        record['availability'] = 'waiting'
        with self.assertRaisesRegex(ValueError, '请等待'):
            self.controller.launch_room()
        record.update(availability='ready', compatibility='模组集合不同')
        with self.assertRaisesRegex(ValueError, '配置与房间不符'):
            self.controller.launch_room()
        self.parent.started_game.assert_not_called()

    def test_host_can_launch_before_opening_world(self):
        self.controller.records['room'].update(role='host', availability='waiting')
        self.controller.launch_room()
        self.parent.started_game.assert_called_once_with(server=None)

    def run_job(self, key, coroutine):
        self.controller.finish(key, asyncio.run(coroutine), None)

    def test_running_game_discovery_can_proceed_to_room_creation(self):
        world = dict(port=51234, version='1.21.8', protocol=772)
        self.controller.game = {'version': '1.21.8', 'loader': 'forge'}
        with patch.object(self.controller, 'job', side_effect=self.run_job), \
                patch.object(self.controller, 'profile', return_value=Mock()), \
                patch('ui.multiplayer_controller.native_bridge', return_value=SimpleNamespace(
                    request=AsyncMock(side_effect=[{'worlds': [world]}, world]))) as bridge:
            self.controller.act('discover', {})
            self.assertEqual(self.controller.view['worlds'], [world])
            self.assertFalse(self.controller.view['busy'])
            bridge.return_value.request.assert_awaited_once_with('game.discover', {'exclude': [34567], 'duration_ms': 3000})
            self.controller.act('probe', {'port': world['port']})
        self.assertEqual(self.controller.view['step'], 1)
        self.assertEqual(self.controller.view['worldPort'], world['port'])
        with patch.object(self.controller, 'profile', return_value=Mock()), \
                patch.object(self.controller, 'start') as start:
            self.controller.act('create', {'title': 'Already running world'})
        self.assertEqual(start.call_args.args[0].game_port, world['port'])

    def test_waiting_host_can_discover_and_reselect_world_after_starting_game(self):
        world = dict(port=51234, version='1.21.8', protocol=772)
        self.controller.records['room'].update(role='host', availability='waiting')
        endpoint = SimpleNamespace(role='host', retarget_world=AsyncMock(return_value=world))
        self.service.endpoints['room'] = endpoint
        with patch.object(self.controller, 'job', side_effect=self.run_job), \
                patch('ui.multiplayer_controller.native_bridge', return_value=SimpleNamespace(
                    request=AsyncMock(return_value={'worlds': [world]}))):
            self.controller.act('reopenWorld', {})
            self.assertEqual(self.controller.view['page'], 'worldPicker')
            self.assertEqual(self.controller.view['worlds'], [world])
            self.controller.act('applyWorld', {'port': world['port']})
        endpoint.retarget_world.assert_awaited_once_with(world['port'])
        self.assertEqual(self.controller.view['page'], 'connected')
        self.assertFalse(self.controller.view['busy'])
        self.assertEqual(self.controller.view['error'], '')

    def test_membership_and_chat_do_not_require_installed_version(self):
        self.service.endpoints.clear()
        invite = RoomInvite.create()
        self.controller.game = {}
        with patch.object(self.controller, 'profile', return_value=Mock()), \
                patch.object(self.controller, 'start') as start:
            self.controller.join(invite.encode())
        endpoint = start.call_args.args[0]
        self.assertEqual(endpoint.role, 'client')
        self.assertIsNone(endpoint.local_game)
        self.assertIsNone(self.controller.pending)

    def test_runtime_snapshot_controls_version_and_lock_instead_of_current_selection(self):
        self.parent.current_client = True
        self.parent.running_instance = ('runtime-root', 'running-version', 'runtime-data')
        def close_job(key, coroutine):
            coroutine.close()
        with patch.object(self.controller, 'job', side_effect=close_job), \
                patch('ui.multiplayer_controller.installed_instance_ids', return_value=['selected', 'running-version']):
            self.controller.detect_instance()
        self.assertEqual(self.controller.view['instanceId'], 'running-version')
        self.assertTrue(self.controller.view['instanceLocked'])
        self.assertEqual(self.controller.instance_source, self.parent.running_instance)

    def test_waiting_host_metadata_refresh_updates_room_for_joined_players(self):
        self.controller.records['room'].update(role='host', availability='waiting', game={'version':'old'})
        endpoint = SimpleNamespace(role='host', update_game=AsyncMock())
        self.service.endpoints['room'] = endpoint
        self.controller.instance_source = ('root', 'new', 'new-data')
        self.controller.instance_job = 'instance:new'
        submitted = []
        def job(key, coroutine):
            submitted.append(key)
            coroutine.close()
        with patch.object(self.controller, 'job', side_effect=job):
            self.controller.finish('instance:new', {'version':'new', 'loader':'fabric'}, None)
        endpoint.update_game.assert_called_once_with({'version':'new', 'loader':'fabric'}, 'new-data')
        self.assertIn('syncgame:room', submitted)

    def test_room_creation_requires_explicit_game_chat_opt_in_and_passes_identity(self):
        for data, enabled, name in (({}, False, None),
                ({'gameChatEnabled':False, 'gameChatName':'中文未启用'}, False, None),
                ({'gameChatEnabled':True, 'gameChatName':'LobbyBridge'}, True, 'LobbyBridge')):
            with self.subTest(data=data):
                self.controller.creation = {'path':self.controller.node_path,
                    'game':{'version':'1.21.8', 'protocol':772}, 'port':0}
                self.controller.patch(step=1)
                with patch.object(self.controller, 'profile', return_value=Mock()), \
                        patch.object(self.controller, 'start') as start:
                    self.controller.create({'title':'Chat choices', **data})
                endpoint = start.call_args.args[0]
                self.assertEqual(endpoint.game_chat_enabled, enabled)
                self.assertEqual(endpoint.game_chat_name, name)
                self.assertIsNone(self.controller.creation)

    def test_invalid_or_duplicate_virtual_identity_never_starts_room(self):
        self.parent.auth_manager.current = SimpleNamespace(username='RealPlayer')
        self.controller.creation = {'path':self.controller.node_path,
            'game':{'version':'1.21.8', 'protocol':772}, 'port':0}
        self.controller.patch(step=1)
        for data in ({'gameChatEnabled':True, 'gameChatName':'中文'},
                     {'gameChatEnabled':True, 'gameChatName':'realplayer'},
                     {'gameChatEnabled':'false'}):
            with self.subTest(data=data), patch.object(self.controller, 'start') as start:
                with self.assertRaises(ValueError):
                    self.controller.create({'title':'Chat choices', **data})
                start.assert_not_called()
                self.assertIsNotNone(self.controller.creation)

    def test_room_creation_applies_all_three_access_modes(self):
        for public, required, expected in ((False, False, True), (True, False, False),
                                            (True, True, True)):
            with self.subTest(public=public, require_invite=required):
                self.controller.creation = {'path':self.controller.node_path,
                    'game':{'version':'1.21.8'}, 'port':0}
                self.controller.patch(step=1)
                with patch.object(self.controller, 'profile', return_value=Mock()), \
                        patch.object(self.controller, 'start') as start:
                    self.controller.create({'title':'Access choices', 'public':public,
                                            'requireInvite':required})
                self.assertEqual(start.call_args.args[0].room_settings['public'], public)
                self.assertEqual(start.call_args.args[0].room_settings['require_invite'], expected)

    def test_protected_listing_requests_matching_invite_and_back_clears_target(self):
        self.service.endpoints.clear()
        invite = RoomInvite.create()
        result = {'path':self.controller.node_path, 'room':{
            'id':invite.room_id, 'title':'Protected world', 'require_invite':True}}
        with patch.object(self.controller, 'join') as join:
            self.controller.finish('resolve:' + self.controller.generation, result, None)
            join.assert_not_called()
        self.assertEqual(self.controller.view['page'], 'hall')
        self.assertTrue(self.controller.view['invitePrompt'])
        self.assertEqual(self.controller.view['joinRoomId'], invite.room_id)
        self.assertEqual(self.controller.view['joinRoomTitle'], 'Protected world')
        with patch.object(self.controller, 'profile', return_value=Mock()), \
                patch.object(self.controller, 'start') as start:
            self.controller.act('join', {'invite':RoomInvite.create().encode()})
            start.assert_not_called()
            self.assertIn('不属于所选房间', self.controller.view['error'])
            self.controller.act('join', {'invite':invite.encode()})
            self.assertEqual(start.call_args.args[0].invite, invite)
        self.controller.navigate('hall')
        self.assertEqual(self.controller.view['joinRoomId'], '')
        self.assertEqual(self.controller.view['joinRoomTitle'], '')

    def test_direct_public_listing_joins_without_an_invite_form(self):
        invite = RoomInvite.create()
        with patch.object(self.controller, 'join') as join:
            self.controller.finish('resolve:' + self.controller.generation,
                {'path':self.controller.node_path, 'secret':invite.secret,
                 'room':{'id':invite.room_id, 'title':'Open world', 'require_invite':False}}, None)
            join.assert_called_once_with(invite.encode())

    def test_selected_policy_reaches_host_and_public_or_invited_visitor(self):
        self.service.endpoints.clear()
        self.controller.patch(connections=[])
        for policy in ('auto', 'relay'):
            self.controller.act('transport', {'policy':policy})
            self.assertEqual(self.controller.view['transportPolicy'], policy)
            with patch.object(self.controller, 'profile', return_value=Mock()), \
                    patch.object(self.controller, 'start') as start:
                self.controller.join(RoomInvite.create().encode())
                self.assertEqual(start.call_args.args[0].transport_policy, policy)
                self.controller.creation = {'path':self.controller.node_path, 'game':{}, 'port':0}
                self.controller.patch(step=1)
                self.controller.create({'title':'Path choice', 'transport':policy})
                self.assertEqual(start.call_args.args[0].transport_policy, policy)


if __name__ == '__main__':
    unittest.main()
