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

    def test_quick_creation_uses_player_name_and_checks_world_before_hosting(self):
        self.parent.auth_manager.current.username = '小明'
        self.controller.game = {'version': '1.21.8'}
        world = dict(port=51234, version='1.21.8', protocol=772)
        bridge = SimpleNamespace(request=AsyncMock(return_value=world))
        for port in (0, world['port']):
            with self.subTest(port=port), patch.object(self.controller, 'profile', return_value=Mock()), \
                    patch.object(self.controller, 'start') as start, \
                    patch.object(self.controller, 'job', side_effect=self.run_job), \
                    patch('ui.multiplayer_controller.native_bridge', return_value=bridge):
                self.controller.act('quickCreate', {'port': port})
                endpoint, title = start.call_args.args
                self.assertEqual(title, '小明的房间')
                self.assertEqual(endpoint.room_settings['title'], title)
                self.assertFalse(endpoint.room_settings['public'])
                self.assertTrue(endpoint.room_settings['require_invite'])
        bridge.request.assert_awaited_once_with('game.status', {'port':51234, 'timeout_ms':4000})

    def test_quick_creation_never_hosts_when_world_verification_fails(self):
        self.controller.game = {'version': '1.21.8'}
        with patch.object(self.controller, 'job', side_effect=self.run_job), \
                patch('ui.multiplayer_controller.native_bridge', return_value=SimpleNamespace(
                    request=AsyncMock(side_effect=ValueError('world closed')))), \
                patch.object(self.controller, 'start') as start:
            self.controller.act('quickCreate', {'port': 51234})
        start.assert_not_called()
        self.assertIsNone(self.controller.quick_creation_data)
        self.assertTrue(self.controller.view['error'])

    def test_clipboard_join_validates_code_waits_for_node_and_avoids_duplicate_join(self):
        self.controller.records.clear()
        self.controller.patch(connections=[], page='hall', nodeAvailable=False)
        invite = RoomInvite.create().encode()
        QApplication.clipboard().setText(invite)
        with patch.object(self.controller, 'join') as join:
            self.controller.join_from_clipboard()
            join.assert_not_called()
            self.assertEqual(self.controller.clipboard_invite, invite)
            self.controller.patch(nodeAvailable=True)
            self.controller.join_from_clipboard()
            join.assert_called_once_with(invite, room_id=None)
            self.controller.join_from_clipboard()
            join.assert_called_once()
            QApplication.clipboard().setText('not an invitation')
            self.controller.join_from_clipboard()
            QApplication.clipboard().setText(invite)
            self.controller.join_from_clipboard()
            join.assert_called_once()
            another = RoomInvite.create().encode()
            QApplication.clipboard().setText(another)
            self.controller.join_from_clipboard()
            self.assertEqual(join.call_count, 2)
            join.assert_called_with(another, room_id=None)
        QApplication.clipboard().clear()

    def test_managed_game_is_monitored_even_before_hall_is_shown(self):
        self.parent.launcher.running = True
        self.controller.runtime_job = True
        world = dict(port=51234, version='1.21.8', protocol=772)
        with patch.object(self.controller, 'job', side_effect=self.run_job), \
                patch('ui.multiplayer_controller.native_bridge', return_value=SimpleNamespace(
                    request=AsyncMock(return_value={'worlds':[world]}))):
            self.controller.detect_runtime()
        self.assertFalse(self.window.isVisible())
        self.assertTrue(self.controller.view['openWorldPrompt'])

    def test_native_scan_runs_when_process_command_line_cannot_be_identified(self):
        self.controller.runtime_job = True
        self.controller.patch(connections=[])
        world = dict(port=51234, version='1.21.8')
        with patch.object(self.controller, 'job', side_effect=self.run_job), \
                patch('ui.multiplayer_controller.native_bridge', return_value=SimpleNamespace(
                    request=AsyncMock(return_value={'worlds': [world]}))):
            self.controller.detect_runtime()
        self.assertFalse(self.parent.launcher.running)
        self.assertIsNone(self.controller.external_running)
        self.assertTrue(self.controller.view['openWorldPrompt'])

    def test_reopening_world_on_same_port_prompts_without_a_missed_scan(self):
        from utils.instances import lan_world_token
        directory = Path(self.parent.launcher.minecraft_directory)
        log = directory / 'logs/latest.log'
        log.parent.mkdir()
        first = '[12:00:00] [Render thread/INFO]: Started serving on 25565\n'
        log.write_text(first, encoding='utf-8')
        self.controller.instance_source = (str(directory), 'selected', str(directory))
        self.controller.runtime_job = True
        self.controller.patch(connections=[])
        world = dict(port=25565, version='1.21.8')
        with patch.object(self.controller, 'job', side_effect=self.run_job), \
                patch('ui.multiplayer_controller.native_bridge', return_value=SimpleNamespace(
                    request=AsyncMock(return_value={'worlds': [world]}))):
            self.controller.detect_runtime()
            self.assertTrue(self.controller.view['openWorldPrompt'])
            self.controller.act('dismissOpenWorld', {})
            self.controller.detect_runtime()
            self.assertFalse(self.controller.view['openWorldPrompt'])
            log.write_text(first + '[12:00:09] [Render thread/INFO]: Started serving on 25565\n', encoding='utf-8')
            self.controller.detect_runtime()
            self.assertTrue(self.controller.view['openWorldPrompt'])
            self.controller.act('dismissOpenWorld', {})
            self.controller.detect_runtime()
            self.assertFalse(self.controller.view['openWorldPrompt'])
        self.assertEqual(lan_world_token(directory)[0], 25565)
        self.assertIsNone(lan_world_token(directory / 'missing'))

    def test_waiting_and_mismatched_clients_cannot_launch_wrong_game(self):
        record = self.controller.records['room']
        record['availability'] = 'waiting'
        with self.assertRaisesRegex(ValueError, '请等待'):
            self.controller.launch_room()
        record.update(availability='ready', compatibility='模组集合不同')
        with self.assertRaisesRegex(ValueError, '配置与房间不符'):
            self.controller.launch_room()
        self.parent.started_game.assert_not_called()

    def test_modded_room_cannot_launch_vanilla_even_when_compatibility_text_is_stale(self):
        self.controller.records['room']['game'] = dict(version='1.20.1', loader='forge', mods_count=2)
        self.controller.game = dict(version='1.20.1', loader='vanilla')
        with self.assertRaisesRegex(ValueError, '一致的加载器'):
            self.controller.launch_room()
        self.controller.patch(instanceLoading=True)
        with self.assertRaisesRegex(ValueError, '正在核对游戏加载器'):
            self.controller.launch_room()
        self.parent.started_game.assert_not_called()

    def test_same_loader_with_another_build_can_launch_with_a_warning(self):
        game = dict(version='1.20.1', loader='forge', loader_version='47.4.0', mods_hash='a')
        self.controller.records['room']['game'] = game
        self.controller.game = dict(game, loader_version='47.3.0')
        self.controller.check_room_compatibility(self.controller.records['room'])
        self.assertEqual(self.controller.records['room']['compatibility'], '')
        self.assertIn('加载器版本与房主不同', self.controller.records['room']['loaderWarning'])
        self.controller.launch_room()
        self.parent.started_game.assert_called_once_with(server='127.0.0.1:34567')

    def test_prepared_game_waits_for_selected_metadata_verification_before_launch(self):
        game = dict(version='1.20.1', loader='forge', loader_version='47.4.0', mods_hash='a')
        self.controller.records['room']['game'] = game
        self.controller.records['room']['preparing'] = True
        self.controller.prepared_launch = None
        with patch.object(self.controller, 'detect_instance'), patch.object(self.controller, 'select_instance') as select:
            self.controller.finish('prepare:room', 'room-prepared', None)
        select.assert_called_once_with('room-prepared')
        self.parent.started_game.assert_not_called()
        self.assertEqual(self.controller.prepared_launch, ('room','room-prepared'))
        self.controller.instance_job = 'instance:verified'
        self.controller.patch(instanceId='room-prepared')
        self.controller.finish('instance:verified', game, None)
        self.parent.started_game.assert_called_once_with(server='127.0.0.1:34567')

    def test_prepared_game_never_launches_when_final_metadata_reports_vanilla(self):
        game = dict(version='1.20.1', loader='forge', loader_version='47.4.0', mods_hash='a')
        self.controller.records['room']['game'] = game
        self.controller.prepared_launch = ('room','room-prepared')
        self.controller.instance_job = 'instance:verified'
        self.controller.patch(instanceId='room-prepared')
        self.controller.finish('instance:verified', dict(game, loader='vanilla'), None)
        self.parent.started_game.assert_not_called()
        self.assertIn('复核失败', self.controller.view['error'])

    def test_host_can_launch_before_opening_world(self):
        self.controller.records['room'].update(role='host', availability='waiting')
        self.controller.launch_room()
        self.parent.started_game.assert_called_once_with(server=None)

    def test_host_settings_update_preserves_game_and_publishes_only_on_success(self):
        from hookup.native_transport import NativeEndpoint
        game = {'version': '1.21.8', 'mods_count': 2}
        endpoint = NativeEndpoint(Mock(), role='host', room_settings={
            'title': '原名称', 'public': False, 'require_invite': True, 'game': game})
        endpoint.session = 'native-host-session'
        result = {'title': '新的房间', 'public': True, 'require_invite': False, 'game': game}
        endpoint._routes = SimpleNamespace(request=AsyncMock(return_value=result))
        self.service.endpoints['room'] = endpoint
        self.controller.records['room'].update(role='host', title='原名称')
        with patch.object(self.controller, 'job', side_effect=self.run_job):
            self.controller.act('updateRoomSettings', {'title': '新的房间', 'public': True, 'requireInvite': False})
        endpoint._routes.request.assert_awaited_once_with('room.configure', {
            'session': endpoint.session, 'settings': dict(result)})
        self.assertEqual(self.controller.records['room']['title'], '新的房间')
        self.assertFalse(self.controller.records['room']['requireInvite'])
        self.assertEqual(endpoint.room_settings['game'], game)
        endpoint._routes.request.side_effect = ConnectionError('节点不可用')
        with patch.object(self.controller, 'job', side_effect=self.run_job):
            self.controller.act('updateRoomSettings', {'title': '不应保存', 'public': False, 'requireInvite': True})
        self.assertEqual(self.controller.records['room']['title'], '新的房间')
        self.assertEqual(endpoint.room_settings['title'], '新的房间')
        self.assertFalse(self.controller.view['busy'])

    def test_guest_cannot_change_host_settings(self):
        with patch.object(self.controller, 'job') as job:
            self.controller.act('updateRoomSettings', {'title': '名称', 'public': True, 'requireInvite': False})
        job.assert_not_called()
        self.assertIn('房主', self.controller.view['error'])

    def test_friend_preferences_survive_refresh_and_are_scoped_to_my_account(self):
        from hookup.storage import LobbyStore
        friend = dict(name='Alice', account='friend-account', online=True)
        self.controller.patch(contacts=[friend], socialAccount='my-account')
        self.controller.act('setFriendFavorite', {'account':friend['account'], 'favorite':True})
        self.controller.act('setFriendAlias', {'account':friend['account'], 'alias':'一起建房子'})
        stored = LobbyStore(self.controller.store.path)
        self.controller.store = stored
        self.controller.patch(contacts=[dict(friend, online=False)])
        self.assertEqual(self.controller.view['contacts'][0]['alias'], '一起建房子')
        self.assertTrue(self.controller.view['contacts'][0]['favorite'])
        self.assertFalse(self.controller.view['contacts'][0]['online'])
        self.assertEqual(self.controller.view['contacts'][0]['name'], 'Alice')
        self.controller.patch(socialAccount='another-account')
        self.assertNotIn('alias', self.controller.view['contacts'][0])
        self.controller.patch(socialAccount='my-account')
        with patch.object(stored, 'save', side_effect=OSError('磁盘不可写')):
            self.controller.act('setFriendAlias', {'account':friend['account'], 'alias':'不应保存'})
        self.assertEqual(self.controller.view['contacts'][0]['alias'], '一起建房子')
        self.assertIn('磁盘', self.controller.view['error'])
        self.controller.act('setFriendAlias', {'account':'missing', 'alias':'错的人'})
        self.assertIn('不在列表', self.controller.view['error'])

    def test_disabled_quick_mode_stops_scans_pending_prompts_and_clipboard_joins(self):
        self.parent.settings_manager.get_setting.return_value = '关闭'
        self.controller.runtime_job = True
        self.controller.patch(connections=[], openWorldPrompt=True, openWorldPort=25565)
        with patch.object(self.controller, 'job') as job, patch.object(self.controller, 'join') as join:
            self.controller.detect_runtime()
            job.assert_not_called()
            self.assertFalse(self.controller.view['openWorldPrompt'])
            self.controller.finish('auto-lan:' + self.controller.generation, [dict(port=25565)], None)
            self.assertFalse(self.controller.view['openWorldPrompt'])
            QApplication.clipboard().setText(RoomInvite.create().encode())
            self.controller.join_from_clipboard()
            join.assert_not_called()
        QApplication.clipboard().clear()

    def test_public_room_guide_waits_for_auto_host_and_is_saved_once(self):
        from config.settings import SettingsManager
        folder = Path(self.parent.launcher.minecraft_directory) / 'guide-settings'
        settings = SettingsManager(folder)
        self.parent.settings_manager = settings
        record = self.controller.records['room']
        record.update(role='host', state='online', availability='waiting', public=False,
                      automaticPublicGuide=True)
        self.controller.offer_public_room_guide(record)
        self.assertFalse(record.get('publicGuide', False))
        self.assertFalse(settings.get_setting('multiplayer.public_guide_seen', False))
        record['availability'] = 'ready'
        self.controller.update_chat('room', {'type':'room', 'state':'ready'})
        self.assertTrue(record['publicGuide'])
        self.assertTrue(SettingsManager(folder).get_setting('multiplayer.public_guide_seen', False))
        self.controller.act('dismissPublicGuide', {})
        self.assertFalse(record['publicGuide'])
        record['automaticPublicGuide'] = True
        self.controller.update_chat('room', {'type':'room', 'state':'ready'})
        self.assertFalse(record['publicGuide'])
        self.assertFalse(record['public'])

    def test_manual_rooms_guests_and_public_rooms_do_not_get_public_guide(self):
        settings = Mock()
        settings.get_setting.return_value = False
        self.parent.settings_manager = settings
        base = dict(role='host', state='online', availability='ready', automaticPublicGuide=True, public=False)
        for override in (dict(automaticPublicGuide=False), dict(role='client'),
                         dict(state='connecting'), dict(public=True)):
            record = dict(base, **override)
            self.controller.offer_public_room_guide(record)
            self.assertFalse(record.get('publicGuide', False))
        settings.set_setting.assert_not_called()

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
            self.assertFalse(self.controller.view['worldScanning'])
            bridge.return_value.request.assert_awaited_once_with('game.discover', {'exclude': [34567], 'duration_ms': 3000})
            self.controller.act('probe', {'port': world['port']})
        self.assertEqual(self.controller.view['step'], 1)
        self.assertEqual(self.controller.view['worldPort'], world['port'])
        with patch.object(self.controller, 'profile', return_value=Mock()), \
                patch.object(self.controller, 'start') as start:
            self.controller.act('create', {'title': 'Already running world'})
        self.assertEqual(start.call_args.args[0].game_port, world['port'])

    def test_world_scan_state_is_cleared_on_failure_and_navigation(self):
        jobs = []
        def hold(key, coroutine):
            coroutine.close()
            jobs.append(key)
        with patch.object(self.controller, 'job', side_effect=hold):
            self.controller.act('discover', {})
            self.assertTrue(self.controller.view['worldScanning'])
            self.controller.finish(jobs[-1], None, 'scan failed')
            self.assertFalse(self.controller.view['worldScanning'])
            self.assertFalse(self.controller.view['busy'])
            self.controller.act('discover', {})
            self.controller.navigate('hall')
            self.assertFalse(self.controller.view['worldScanning'])
            self.controller.finish(jobs[-1], [], None)
            self.assertEqual(self.controller.view['page'], 'hall')

    def test_open_lan_world_is_found_automatically_and_prompts_for_a_room(self):
        world = dict(port=51234, version='1.21.8', protocol=772)
        self.controller.external_running = ('game-dir', '1.21.8', 'game-dir')
        self.controller.runtime_job = True
        bridge = SimpleNamespace(request=AsyncMock(return_value={'worlds':[world]}))
        with patch.object(self.controller, 'job', side_effect=self.run_job), \
                patch('ui.multiplayer_controller.native_bridge', return_value=bridge):
            self.controller.detect_runtime()
        bridge.request.assert_awaited_once_with('game.discover', {'exclude':[34567], 'duration_ms':2500})
        self.assertTrue(self.controller.view['openWorldPrompt'])
        self.assertEqual(self.controller.view['openWorldPort'], world['port'])
        self.controller.act('dismissOpenWorld', {})
        self.assertFalse(self.controller.view['openWorldPrompt'])
        self.assertIn(world['port'], self.controller.auto_lan_seen)

    def test_world_hint_is_consumed_until_world_closes_or_a_new_port_appears(self):
        self.controller.patch(connections=[])
        key = 'auto-lan:' + self.controller.generation
        world = dict(port=51234, version='1.21.8')
        self.controller.finish(key, [world], None)
        self.assertTrue(self.controller.view['openWorldPrompt'])
        self.controller.act('dismissOpenWorld', {})
        self.controller.finish(key, [world], None)
        self.assertFalse(self.controller.view['openWorldPrompt'])
        self.controller.finish(key, None, 'temporary network failure')
        self.controller.finish(key, [world], None)
        self.assertFalse(self.controller.view['openWorldPrompt'])
        self.controller.finish(key, [], None)
        self.controller.finish(key, [world], None)
        self.assertFalse(self.controller.view['openWorldPrompt'])
        self.controller.finish(key, [dict(world, port=51235)], None)
        self.assertTrue(self.controller.view['openWorldPrompt'])
        self.assertEqual(self.controller.view['openWorldPort'], 51235)
        self.controller.act('dismissOpenWorld', {})
        self.controller.finish(key, [], None)
        self.controller.finish(key, [], None)
        self.assertFalse(self.controller.view['openWorldPrompt'])
        self.controller.finish(key, [dict(world, port=51235)], None)
        self.assertTrue(self.controller.view['openWorldPrompt'])

    def test_pending_world_hint_is_cleared_when_world_closes_before_click(self):
        self.controller.patch(connections=[])
        key = 'auto-lan:' + self.controller.generation
        self.controller.finish(key, [dict(port=51234)], None)
        self.assertTrue(self.controller.view['openWorldPrompt'])
        self.controller.finish(key, [], None)
        self.controller.finish(key, [], None)
        self.assertFalse(self.controller.view['openWorldPrompt'])
        self.assertEqual(self.controller.view['openWorldPort'], 0)

    def test_open_lan_world_associates_with_a_room_created_before_game(self):
        world = dict(port=51234, version='1.21.8', protocol=772)
        endpoint = SimpleNamespace(role='host', retarget_world=AsyncMock(return_value=world))
        self.service.endpoints['room'] = endpoint
        self.controller.records['room'].update(role='host', availability='waiting')
        self.controller.external_running = ('game-dir', '1.21.8', 'game-dir')
        self.controller.runtime_job = True
        bridge = SimpleNamespace(request=AsyncMock(return_value={'worlds':[world]}))
        with patch.object(self.controller, 'job', side_effect=self.run_job), \
                patch('ui.multiplayer_controller.native_bridge', return_value=bridge):
            self.controller.detect_runtime()
            self.assertEqual(self.controller.view['openWorldMode'], 'associate')
            self.controller.act('createFromOpenWorld', {'port':world['port']})
        endpoint.retarget_world.assert_awaited_once_with(world['port'])
        self.assertFalse(self.controller.view['openWorldPrompt'])
        self.assertEqual(self.controller.view['page'], 'connected')

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


class BackgroundLanMonitorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_startup_starts_hidden_monitor_without_saved_nodes(self):
        from ui.pages.qml_start import StartGamePage
        page = SimpleNamespace(_ensure_multiplayer_dialog=Mock())
        StartGamePage._start_background_social(page)
        page._ensure_multiplayer_dialog.assert_called_once_with()

    def test_hidden_dialog_continues_checking_node_health(self):
        from ui.dialog.MultiplayerDialog import MultiplayerDialog
        with tempfile.TemporaryDirectory() as folder, \
                patch('ui.multiplayer_controller.TunnelService', return_value=Mock(endpoints={})), \
                patch.object(MultiplayerController, 'check_node') as check:
            dialog = MultiplayerDialog(storage_path=Path(folder) / 'rooms.json')
            try:
                self.assertFalse(dialog.isVisible())
                self.assertTrue(dialog.runtime_timer.isActive())
                dialog.timer.timeout.emit()
                check.assert_called_once_with()
            finally:
                dialog.shutdown()


if __name__ == '__main__':
    unittest.main()
