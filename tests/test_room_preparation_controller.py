"""Preparation result delivery, source locking and permission regressions."""
import json
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
from types import SimpleNamespace
import unittest

import test_room_launch_flow as fixtures


class RoomPreparationControllerTests(unittest.TestCase):
    setUpClass = fixtures.RoomLaunchFlowTests.__dict__['setUpClass']
    setUp = fixtures.RoomLaunchFlowTests.setUp
    dispose_widgets = fixtures.RoomLaunchFlowTests.dispose_widgets

    def test_room_history_retry_reuses_task_and_refuses_a_disconnected_room(self):
        record = self.controller.records['room']
        history = Mock()
        history.track_room_preparation.return_value = 'history-task'
        self.parent.settings_manager.get_setting.side_effect = lambda key, default=None: (
            self.parent.launcher.minecraft_directory if key == 'minecraft.directory.enable' else default)
        with patch.object(self.controller, 'preparation_history', return_value=history), \
                patch.object(self.controller, 'report_room_state'), \
                patch.object(self.controller, 'job', side_effect=lambda key, coroutine: coroutine.close()):
            self.controller.prepare_room()
            callback = history.track_room_preparation.call_args.kwargs['retry']
            record.update(preparing=False, prepareFailed=True)
            callback('history-task')
            self.assertEqual(history.track_room_preparation.call_args.kwargs['task_id'], 'history-task')
            self.assertEqual(record['prepareHistoryTask'], 'history-task')
            self.assertFalse(record['prepareFailed'])
            record['preparing'] = False
            self.service.endpoints.clear()
            with self.assertRaisesRegex(ValueError, '房间已断开'):
                callback('history-task')

    def test_world_connection_is_automatic_even_with_quick_creation_disabled_and_ambiguity_needs_choice(self):
        record = self.controller.records['room']
        record.update(role='host', availability='waiting', game=dict(version='1.21.8'))
        self.parent.settings_manager.get_setting.return_value = '关闭'
        endpoint = SimpleNamespace(retarget_world=AsyncMock(return_value={}))
        self.service.endpoints['room'] = endpoint
        key = 'auto-lan:' + self.controller.generation
        with patch.object(self.controller, 'job', side_effect=lambda name, coro: self.controller.finish(name, __import__('asyncio').run(coro), None)):
            self.controller.finish(key, [dict(port=25565), dict(port=25566)], None)
            self.assertTrue(record['worldChoiceRequired'])
            endpoint.retarget_world.assert_not_called()
            self.controller.finish(key, [dict(port=25565, version='1.20.1')], None)
            endpoint.retarget_world.assert_not_called()
            self.controller.finish(key, [dict(port=25565, version='1.21.8')], None)
        endpoint.retarget_world.assert_awaited_once_with(25565)
        self.assertFalse(self.controller.view['openWorldPrompt'])

    def test_previous_tasks_events_cannot_pollute_current_install_or_history(self):
        record = self.controller.records['room']
        record.update(preparing=True, prepareTask='new', prepareLogs=[])
        self.controller.update_preparation_event('room', dict(kind='status', task='old', status='wrong', done=20, total=20))
        self.assertEqual(record['prepareLogs'], [])
        self.controller.update_preparation_event('room', dict(kind='status', task='new', status='安装模组', done=2, total=10))
        self.assertEqual(record['prepareProgress'], 2)
        self.assertEqual(record['prepareLogs'][-1]['category'], 'mods')

    def test_shared_logs_remove_secrets_paths_and_download_addresses_before_upload(self):
        from ui.room_preparation import shared_log_text
        message = shared_log_text('sodium.jar C:\\Users\\Alice\\mods\\sodium.jar password=secret https://example.test/private buggnode1-private')
        for private in ('Alice', 'password=secret', 'example.test', 'buggnode1-private'):
            self.assertNotIn(private, message)
        self.assertIn('sodium.jar', message)

    def test_locked_instance_launches_original_directory_after_home_selection_changes(self):
        controller = self.controller
        root = Path(self.parent.launcher.minecraft_directory)
        file = root / 'versions/original/original.json'
        file.parent.mkdir(parents=True)
        file.write_text(json.dumps(dict(id='original', buggcraftRoom=dict(version='1.21.8'), libraries=[])))
        record = controller.records['room']
        record.update(role='host', lockedSource=(str(root), 'original', str(file.parent)))
        self.parent.launcher.minecraft_version = 'another'
        controller.game = dict(version='1.20.1')
        controller.launch_room()
        self.assertEqual(self.parent.launcher.minecraft_version, 'original')
        self.assertEqual(self.parent.launcher.minecraft_isolation_directory, str(file.parent))
        self.parent.started_game.assert_called_once_with(server=None)

    def test_member_results_notify_once_and_late_snapshots_cannot_replace_newer_state(self):
        notify = Mock()
        self.controller.room_notification.connect(notify)
        base = dict(self_id='host', manager_id='host', revision=1, config_id='a' * 64,
                    members=[dict(id='guest', name='Guest', state='downloading', task='one')])
        self.controller.apply_members('room', base)
        ready = dict(base, revision=2, members=[dict(base['members'][0], state='ready')])
        self.controller.apply_members('room', ready)
        self.controller.apply_members('room', ready)
        self.controller.apply_members('room', base)
        notify.assert_called_once_with('Guest 已准备好')
        self.assertEqual(self.controller.records['room']['lobby']['revision'], 2)

    def test_logs_remain_bounded_and_failure_is_never_reported_as_ready(self):
        record = self.controller.records['room']
        for index in range(700):
            self.controller.add_prepare_log(record, 'line ' + str(index))
        self.assertEqual(len(record['prepareLogs']), 600)
        record.update(lobby=dict(config_id='a' * 64), prepareTask='one')
        self.controller.report_room_state('room', 'failed', code='install_failed')
        self.assertEqual(self.controller.room_reports['room']['state'], 'failed')
        self.assertNotIn('line ', str(self.controller.room_reports['room']))

    def test_member_pages_remain_visible_after_poll_and_reset_when_membership_changes(self):
        base = dict(self_id='host', manager_id='host', provider_id='host', revision=1,
                    config_id='a' * 64, next=2, members=[dict(id='host', name='Host', state='ready')])
        controller = self.controller
        controller.apply_members('room', base)
        controller.apply_members('room', dict(base, offset=2, next=None,
            members=[dict(id='guest', name='Guest', state='idle')]))
        controller.apply_members('room', base)
        self.assertEqual([row['id'] for row in controller.records['room']['lobby']['members']], ['host', 'guest'])
        self.assertIsNone(controller.records['room']['lobby']['next'])
        controller.apply_members('room', dict(base, revision=2))
        self.assertEqual(len(controller.records['room']['lobby']['members']), 1)
        controller.apply_members('room', dict(base, revision=3, config_id='b' * 64))
        self.assertEqual(controller.room_reports['room']['state'], 'ready')
