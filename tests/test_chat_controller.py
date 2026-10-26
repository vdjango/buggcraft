"""Room switching and failed-send drafts in the real presentation controller."""
from concurrent.futures import Future
import asyncio
import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / '.test-tools'), str(ROOT / 'buggcraft/src/buggcraft')]
from PySide6.QtWidgets import QApplication, QDialog
from ui.multiplayer_controller import MultiplayerController
import asyncssh
from hookup.relay import RelayProfile
from hookup.nodes import remember, candidates, save_json, profile_data
from hookup.social import ExpiredNodeCredential, credential_expiry


class ChatControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.window = QDialog()
        self.addCleanup(self.window.close)
        self.service = Mock(endpoints={})
        with patch('ui.multiplayer_controller.TunnelService', return_value=self.service):
            self.controller = MultiplayerController(self.window, Path(self.temporary.name) / 'lobby.json')
        self.addCleanup(self.controller.close)
        for name in ('first', 'second'):
            self.controller.records[name] = dict(id=name, title=name, state='online',
                chatMessages=[], chatState='在线', chatDraft='', chatError='',
                chatSending=False, bridgeStatus='等待游戏')
        self.controller.patch(selected='first')

    def test_failed_send_preserves_draft_and_retry_success_clears_it(self):
        controller = self.controller
        record = controller.records['first']
        record.update(chatSending=True, chatDraft='你好 😀')
        future = Future()
        future.set_exception(ConnectionError('connection lost'))
        controller.finish_chat('first', future)
        self.assertEqual(controller.view['chatDraft'], '你好 😀')
        self.assertIn('connection lost', controller.view['chatError'])
        self.assertFalse(controller.view['chatSending'])
        future = Future()
        future.set_result(None)
        controller.finish_chat('first', future)
        self.assertEqual(controller.view['chatDraft'], '')
        self.assertEqual(controller.view['chatError'], '')

    def test_verified_node_add_persists_fallbacks_and_deduplicates(self):
        key = asyncssh.generate_private_key('ssh-ed25519').export_public_key().decode()
        profile = RelayProfile('127.0.0.1', 3333, 'a' * 48, key)
        backup = dict(server_host='127.0.0.1', server_port=3334, token='b' * 48, server_public_key=key)
        remember(profile, [backup])
        object.__setattr__(profile, '_name', '朋友的社区节点')
        controller = self.controller
        with patch.object(controller, 'job', side_effect=lambda key, coroutine: coroutine.close()):
            controller.finish('nodecode:' + controller.generation, profile, None)
            controller.finish('nodecode:' + controller.generation, profile, None)
        self.assertFalse(controller.view['busy'])
        self.assertEqual(controller.view['error'], '')
        self.assertNotIn('127.0.0.1', controller.view['nodes'][0]['title'])
        self.assertIn('社区节点', controller.view['nodes'][0]['title'])
        self.assertEqual(controller.view['nodes'][0]['title'], '朋友的社区节点')
        self.assertEqual(len(controller.store.data['nodes']), 1)
        saved = RelayProfile.load(controller.store.data['nodes'][0])
        self.assertEqual(saved, profile)
        self.assertEqual([p.server_port for p in candidates(saved)], [3333, 3334])
        self.assertTrue(Path(saved._source).name.endswith('.json'))

    def test_personal_code_replaces_anonymous_credentials_for_same_node(self):
        key = asyncssh.generate_private_key('ssh-ed25519').export_public_key().decode()
        anonymous = RelayProfile('127.0.0.1', 3333, 'a' * 48, key)
        personal = RelayProfile('127.0.0.1', 3333, 'acct1.' + 'b' * 48, key)
        controller = self.controller
        with patch.object(controller, 'job', side_effect=lambda key, coroutine: coroutine.close()):
            controller.finish('nodecode:' + controller.generation, anonymous, None)
            controller.finish('nodecode:' + controller.generation, personal, None)
            self.assertTrue(controller.view['nodeUpdatePrompt'])
            self.assertEqual(RelayProfile.load(controller.store.data['nodes'][0]).token, anonymous.token)
            controller.act('confirmNodeUpdate', {})
        self.assertEqual(len(controller.store.data['nodes']), 1)
        self.assertEqual(RelayProfile.load(controller.store.data['nodes'][0]).token, personal.token)
        self.assertTrue(controller.view['nodes'][0]['personalCode'])
        controller.reload_store()
        self.assertTrue(controller.view['nodes'][0]['personalCode'])
        self.assertIn('个人接入码已更新', controller.view['notice'])

    def test_node_selection_cannot_bypass_active_room_lock(self):
        controller = self.controller
        controller.node_path = 'original'
        controller.patch(nodes=[{'title': 'Other', 'path': 'other'}], nodeIndex=0,
                         connections=[{'id': 'first'}])
        controller.act('node', {'index': 0})
        self.assertEqual(controller.node_path, 'original')
        self.assertIn('不能切换', controller.view['error'])

    def test_room_refresh_updates_saved_node_name_without_changing_selection(self):
        controller = self.controller
        path = Path(self.temporary.name) / 'node.json'
        key = asyncssh.generate_private_key('ssh-ed25519').export_public_key().decode()
        save_json(path, profile_data(RelayProfile('127.0.0.1', 3333, 'a' * 48, key)))
        controller.store.add_node(str(path))
        controller.node_path = str(path.resolve())
        controller.finish('rooms:' + controller.room_generation + ':0',
                          {'rooms': [], 'next':None, 'total':0, 'node_name': '新节点名称'}, None)
        self.assertEqual(controller.view['nodes'][0]['title'], '新节点名称')
        self.assertEqual(controller.node_path, str(path.resolve()))
        self.assertEqual(controller.store.data['node_names'][controller.node_path], '新节点名称')

    def test_friend_account_id_matches_authenticated_chat_instead_of_nickname(self):
        controller = self.controller
        account = 'a' * 32 + '.' + 'b' * 32
        controller.patch(contacts=[dict(name='小明', account=account, online=True)])
        controller.update_chat('first', dict(type='message', id='verified', sender='完全不同的昵称', text='hello', account=account))
        controller.update_chat('first', dict(type='message', id='guest', sender='小明', text='fake'))
        messages = controller.view['chatMessages']
        self.assertEqual(messages[0]['identityLabel'], '好友账号 · 小明')
        self.assertEqual(messages[1]['identityLabel'], '未验证账号')

    def _friend_node(self):
        key = asyncssh.generate_private_key('ssh-ed25519').export_public_key().decode()
        path = Path(self.temporary.name) / 'friend-node.json'
        save_json(path, profile_data(RelayProfile('127.0.0.1', 3333, 'a' * 48, key)))
        self.controller.store.add_node(str(path))
        self.controller.node_path = str(path.resolve())
        self.controller.reload_store()
        self.controller.apply_social_state(self._social_state())

    def test_expired_personal_code_is_visible_and_can_be_replaced(self):
        key = asyncssh.generate_private_key("ssh-ed25519").export_public_key().decode()
        path = Path(self.temporary.name) / "expiring-node.json"

        def personal_code(expiry):
            claims = {"e": expiry, "g": {"d": True}}
            payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
            return "acct1." + payload + ".signature~secret"

        expired = RelayProfile("127.0.0.1", 3333, personal_code(int(time.time()) - 10), key)
        self.assertLess(credential_expiry(expired), time.time())
        save_json(path, profile_data(expired))
        self.controller.store.add_node(str(path))
        with patch.object(self.controller, "job", side_effect=lambda key, coroutine: coroutine.close()):
            self.controller.reload_store(select=str(path.resolve()))
        self.assertTrue(self.controller.view["nodeAccessExpired"])
        self.assertTrue(self.controller.view["nodes"][0]["codeExpired"])
        with self.assertRaises(ExpiredNodeCredential):
            self.controller.require_available_node()
        self.controller.act("replaceNodeCode", {})
        self.assertEqual(self.controller.view["page"], "nodes")
        self.assertTrue(path.is_file())

        refreshed = RelayProfile("127.0.0.1", 3333, personal_code(int(time.time()) + 3600), key)
        save_json(path, profile_data(refreshed))
        with patch.object(self.controller, "job", side_effect=lambda key, coroutine: coroutine.close()):
            self.controller.reload_store(refresh_identity=True)
        self.assertFalse(self.controller.view["nodeAccessExpired"])
        self.assertFalse(self.controller.view["nodes"][0]["codeExpired"])

    def test_inviting_without_room_waits_until_host_is_online(self):
        controller = self.controller
        account = "c" * 32 + "." + "d" * 32
        controller.apply_social_state({
            "account": "a" * 32 + "." + "b" * 32, "username": "owner",
            "friends": [{"account": account, "username": "Alice", "online": True}],
            "requests": [], "invitations": [],
        })
        controller.patch(nodeAvailable=True)
        controller.node_path = "dummy-node.json"
        with patch.object(controller, "profile", return_value=Mock()):
            controller.invite_friend(account)
        self.assertEqual(controller.view["page"], "create")
        self.assertEqual(controller.pending_friend_invite, (controller.social_generation, account))
        self.assertEqual(controller.view['friendInviteFlow']['stage'], 'create')
        self.assertIn('未发送', controller.view['friendInviteFlow']['title'])

        name = "new-room"
        controller.pending_friend_invite = (*controller.pending_friend_invite, name)
        controller.records[name] = dict(id=name, title="World", role="host", state="connecting",
                                        availability="ready", public=False, requireInvite=True,
                                        chatMessages=[], chatState="", chatDraft="", chatSending=False,
                                        chatError="", bridgeStatus="")
        controller.service.endpoints[name] = Mock(room_info={}, connection=True,
                                                   invite=Mock(room_id="invited-room"))
        with patch.object(controller, "invite_friend") as invite:
            controller.update_status(name, "connecting", "Preparing")
            invite.assert_not_called()
            controller.update_status(name, "online", "Ready")
            invite.assert_called_once_with(account)
        self.assertIsNone(controller.pending_friend_invite)
        self.assertEqual(controller.view["pendingFriendInvite"], "")

    def test_friend_invitation_notifies_once_and_disappears_when_consumed(self):
        controller = self.controller
        notifications = []
        controller.friend_invited.connect(notifications.append)
        invitation = dict(id='1' * 32, account='c' * 32 + '.' + 'd' * 32,
                          username='Alice', room='room-1', expires_at=int(time.time()) + 300)
        controller.apply_social_state(self._social_state(invitations=[invitation]))
        self.assertEqual(notifications, [invitation])
        controller.apply_social_state(self._social_state(invitations=[invitation]))
        self.assertEqual(len(notifications), 1)
        self.assertEqual(controller.view['friendInvitations'], [invitation])
        controller.apply_social_state(self._social_state(invitations=[]))
        self.assertEqual(controller.view['friendInvitations'], [])

    def test_friend_room_invite_reports_success_and_failure_for_retry(self):
        controller = self.controller
        account = 'c' * 32 + '.' + 'd' * 32
        invitation = dict(id='1' * 32, account='a' * 32 + '.' + 'b' * 32,
                          username='owner', room='room-1')
        controller.apply_social_state(self._social_state(
            friends=[dict(account=account, username='Alice', online=True)]))
        controller.node_path = 'dummy-node.json'
        endpoint = Mock(connection=True, invite=Mock(room_id='room-1'), room_info={})
        controller.service.endpoints['first'] = endpoint
        controller.records['first'].update(role='host', availability='ready', state='online')
        outcomes, jobs = [], []
        controller.friend_finished.connect(lambda success, message: outcomes.append((success, message)))
        with patch.object(controller, 'profile', return_value=Mock()), \
                patch.object(controller, 'job', side_effect=lambda key, coroutine: jobs.append((key, coroutine))), \
                patch('hookup.social.operate', return_value=self._social_state(
                    friends=[dict(account=account, username='Alice', online=True)])):
            controller.invite_friend(account)
            self.assertEqual(controller.view['outgoingInvitations'][account]['status'], '发送中…')
            self.assertEqual(controller.view['friendInviteFlow']['stage'], 'sending')
            key, task = jobs.pop()
            controller.finish(key, asyncio.run(task), None)
            self.assertEqual(controller.view['outgoingInvitations'][account]['status'], '已发送')
            self.assertEqual(controller.view['friendInviteFlow']['stage'], 'sent')
            self.assertTrue(outcomes[-1][0])

        jobs = []
        with patch.object(controller, 'profile', return_value=Mock()), \
                patch.object(controller, 'job', side_effect=lambda key, coroutine: jobs.append((key, coroutine))), \
                patch('hookup.social.operate', side_effect=ConnectionError('节点暂不可用')):
            controller.invite_friend(account)
            key, task = jobs.pop()
            with self.assertRaises(ConnectionError) as caught:
                asyncio.run(task)
            controller.finish(key, None, caught.exception)
        self.assertEqual(controller.view['outgoingInvitations'][account]['status'], '发送失败，重试')
        self.assertEqual(controller.view['friendInviteFlow']['stage'], 'error')
        self.assertFalse(outcomes[-1][0])

    def test_queued_invite_reports_waiting_world_and_cancellation_never_sends(self):
        controller = self.controller
        account = 'c' * 32 + '.' + 'd' * 32
        controller.apply_social_state(self._social_state(friends=[dict(account=account, username='Alice', online=True)]))
        controller.node_path = 'dummy-node.json'
        controller.patch(nodeAvailable=True)
        controller.records['first'].update(role='host', state='online', availability='waiting')
        with patch.object(controller, 'profile', return_value=Mock()), patch.object(controller, 'social_operation') as send:
            controller.invite_friend(account)
            self.assertEqual(controller.view['friendInviteFlow']['stage'], 'waiting')
            self.assertEqual(controller.view['friendInviteFlow']['step'], 1)
            controller.act('continueFriendInvite', {})
            self.assertEqual(controller.view['page'], 'connected')
            self.assertEqual(controller.view['selected'], 'first')
            controller.act('cancelFriendInvite', {})
            self.assertEqual(controller.view['friendInviteFlow'], {})
            controller.records['first']['availability'] = 'ready'
            controller._dispatch_pending_friend_invite('first')
            send.assert_not_called()

    def test_invite_setup_failure_does_not_leave_sending_state(self):
        controller = self.controller
        account = 'c' * 32 + '.' + 'd' * 32
        controller.apply_social_state(self._social_state(friends=[dict(account=account, username='Alice', online=True)]))
        controller.records['first'].update(role='host', state='online', availability='ready')
        controller.service.endpoints['first'] = Mock(connection=True, invite=Mock(room_id='room-1'))
        with patch.object(controller, 'social_operation', side_effect=ValueError('接入码已过期')):
            with self.assertRaisesRegex(ValueError, '接入码已过期'):
                controller.invite_friend(account)
        self.assertEqual(controller.view['friendInviteFlow']['stage'], 'error')
        self.assertEqual(controller.view['friendInviteFlow']['action'], 'retry')

    def _social_state(self, **changes):
        state = dict(account='a' * 32 + '.' + 'b' * 32, username='local_user',
                     friends=[], requests=[], invitations=[])
        state.update(changes)
        return state

    def test_multiple_queued_friends_dispatch_independently_and_cancel_one(self):
        controller = self.controller
        accounts = [c * 32 + '.' + 'd' * 32 for c in ('c', 'e', 'f')]
        controller.apply_social_state(self._social_state(friends=[
            dict(account=account, username='Friend' + str(i), online=True) for i, account in enumerate(accounts)]))
        controller.node_path = 'dummy-node.json'
        controller.patch(nodeAvailable=True)
        controller.records['first'].update(role='host', state='online', availability='waiting')
        with patch.object(controller, 'profile', return_value=Mock()):
            for account in accounts:
                controller.invite_friend(account)
        self.assertEqual(controller.view['pendingFriendInviteCount'], 3)
        self.assertEqual({pending[1] for pending in controller.pending_friend_invites.values()}, set(accounts))
        controller.act('cancelFriendInvite', {'account':accounts[1]})
        self.assertEqual(controller.view['pendingFriendInviteCount'], 2)
        controller.records['first']['availability'] = 'ready'
        controller.service.endpoints['first'] = Mock(connection=True, invite=Mock(room_id='1' * 32))
        with patch.object(controller, 'invite_friend') as invite:
            controller._dispatch_pending_friend_invites('first')
        self.assertEqual([call.args[0] for call in invite.call_args_list], [accounts[0], accounts[2]])
        self.assertFalse(controller.pending_friend_invites)

    def test_concurrent_invite_failure_only_changes_its_own_friend(self):
        controller = self.controller
        accounts = [c * 32 + '.' + 'd' * 32 for c in ('c', 'e')]
        controller.apply_social_state(self._social_state(friends=[
            dict(account=account, username='Friend' + str(i), online=True) for i, account in enumerate(accounts)]))
        controller.service.endpoints['first'] = Mock(connection=True, invite=Mock(room_id='1' * 32))
        controller.records['first'].update(role='host', availability='ready')
        jobs = []
        with patch.object(controller, 'profile', return_value=Mock()), \
                patch.object(controller, 'job', side_effect=lambda key, task: jobs.append((key, task))):
            for account in accounts:
                controller.invite_friend(account)
        for _, task in jobs:
            task.close()
        controller.finish(jobs[0][0], None, ValueError('first request failed'))
        self.assertEqual(controller.view['outgoingInvitations'][accounts[0]]['status'], '发送失败，重试')
        self.assertEqual(controller.view['outgoingInvitations'][accounts[1]]['status'], '发送中…')
        self.assertTrue(controller.view['friendBusy'])
        controller.cancel_friend_lookup()
        self.assertTrue(controller.view['friendBusy'])
        controller.finish(jobs[1][0], dict(path=controller.node_path, operation='invite', target=accounts[1],
                                          state=self._social_state()), None)
        self.assertEqual(controller.view['outgoingInvitations'][accounts[1]]['status'], '已发送')
        self.assertFalse(controller.view['friendBusy'])

    def test_friend_room_presence_request_join_and_old_node_fallback(self):
        controller = self.controller
        controller.records.clear()
        account = 'c' * 32 + '.' + 'd' * 32
        room = dict(id='1' * 32, title='Friend world', role='host', availability='ready', can_request=True)
        state = self._social_state(friends=[dict(account=account, username='Alice', online=True, room=room)],
                                   capabilities=dict(room_presence=True, join_requests=True))
        controller.apply_social_state(state)
        self.assertEqual(controller.view['contacts'][0]['room'], room)
        with patch.object(controller, 'social_operation') as operation:
            controller.act('requestJoinFriend', {'account':account})
            operation.assert_called_once_with('request_join', account, room=room['id'])
        controller.apply_social_state(self._social_state(friends=[dict(account=account, username='Alice', online=True)]))
        with patch.object(controller, 'social_operation') as operation:
            controller.act('requestJoinFriend', {'account':account})
            operation.assert_not_called()
        self.assertIn('尚未支持', controller.view['error'])

    def test_backend_emits_one_prioritized_notification_and_rearms_for_new_id(self):
        controller = self.controller
        emitted = []
        controller.social_notification.connect(emitted.append)
        account = 'c' * 32 + '.' + 'd' * 32
        request = dict(id='1' * 32, account=account, username='Alice', incoming=True)
        invitation = dict(id='2' * 32, account=account, username='Alice', room='3' * 32)
        state = self._social_state(requests=[request], invitations=[invitation])
        controller.apply_social_state(state)
        controller.apply_social_state(state)
        self.assertEqual(emitted, ['invite'])
        controller.act('acknowledgeFriendHome', {})
        self.assertFalse(controller.view['friendNotifications']['homeAttention'])
        controller.act('readFriendNotifications', {'kind':'invitations'})
        self.assertEqual(controller.view['friendNotifications']['requests'], 1)
        self.assertFalse(controller.view['friendNotifications']['urgent'])
        controller.apply_social_state(self._social_state(requests=[dict(request, id='4' * 32)]))
        self.assertEqual(emitted, ['invite', 'request'])
        self.assertTrue(controller.view['friendNotifications']['homeAttention'])

    def test_friend_lookup_sends_request_and_waits_for_consent(self):
        self._friend_node()
        account = 'c' * 32 + '.' + 'd' * 32
        response = self._social_state()
        response['requests'] = [dict(account=account, username='Alice', incoming=False, id='1' * 32)]
        jobs = []
        with patch('ui.multiplayer_controller.lookup_account', return_value=[dict(account=account, username='Alice')]), \
                patch('hookup.social.operate', return_value=response) as operate, \
                patch.object(self.controller, 'job', side_effect=lambda key, coroutine: jobs.append((key, coroutine))):
            self.controller.lookup_friend({'identifier': 'Alice'})
            self.assertTrue(self.controller.view['friendBusy'])
            key, task = jobs.pop()
            self.controller.finish(key, asyncio.run(task), None)
        self.assertEqual(operate.call_args.args[1:], ('request', account))
        self.assertEqual(self.controller.view['contacts'], [])
        self.assertEqual(self.controller.view['friendRequests'][0]['account'], account)
        self.assertFalse(self.controller.view['friendBusy'])

    def test_friend_lookup_offers_duplicate_ids_and_rejects_empty_results(self):
        self._friend_node()
        outcomes = []
        self.controller.friend_finished.connect(lambda success, message: outcomes.append((success, message)))
        for value in (
                [{'account': 'a' * 32 + '.' + 'b' * 32, 'username': 'Alice'},
                 {'account': 'c' * 32 + '.' + 'd' * 32, 'username': 'Alice'}],
                []):
            jobs = []
            with patch('ui.multiplayer_controller.lookup_account', return_value=value), \
                    patch('hookup.social.operate') as operate, \
                    patch.object(self.controller, 'job', side_effect=lambda key, coroutine: jobs.append((key, coroutine))):
                self.controller.lookup_friend({'identifier': 'Alice'})
                key, task = jobs.pop()
                if value:
                    self.controller.finish(key, asyncio.run(task), None)
                    self.assertEqual(self.controller.view['friendLookupResults'], value)
                else:
                    with self.assertRaises(ValueError) as caught:
                        asyncio.run(task)
                    self.controller.finish(key, None, caught.exception)
                operate.assert_not_called()
            self.assertEqual(self.controller.view['contacts'], [])
            self.assertFalse(outcomes[-1][0])
            self.assertTrue(outcomes[-1][1])

    def test_friend_lookup_full_id_and_copy_preserve_identity_for_duplicate_names(self):
        self._friend_node()
        account = 'c' * 32 + '.' + 'd' * 32
        response = self._social_state()
        jobs = []
        with patch('ui.multiplayer_controller.lookup_account', return_value=[dict(account=account, username='Alice')]) as lookup, \
                patch('hookup.social.operate', return_value=response) as operate, \
                patch.object(self.controller, 'job', side_effect=lambda key, coroutine: jobs.append((key, coroutine))):
            self.controller.lookup_friend({'identifier': account})
            key, task = jobs.pop()
            self.controller.finish(key, asyncio.run(task), None)
        self.assertEqual(lookup.call_args.args[1], account)
        self.assertEqual(operate.call_args.args[1:], ('request', account))
        with patch('ui.multiplayer_controller.QApplication.clipboard') as clipboard:
            self.controller.act('copySocialName', {})
            self.assertEqual(clipboard.return_value.setText.call_args.args[0], self.controller.view['socialAccount'])

    def test_cancelled_friend_lookup_cannot_save_late_result(self):
        self._friend_node()
        with patch.object(self.controller, 'job', side_effect=lambda key, coroutine: coroutine.close()):
            self.controller.lookup_friend({'identifier': 'Alice'})
            key = self.controller.friend_request['key']
            self.controller.cancel_friend_lookup()
            self.controller.finish(key, [{'account': 'c' * 32 + '.' + 'd' * 32, 'username': 'Alice'}], None)
        self.assertEqual(self.controller.store.data['contacts'], [])

    def test_anonymous_user_cannot_request_friends(self):
        with self.assertRaises(ValueError):
            self.controller.lookup_friend({'identifier':'Alice'})
        self.assertEqual(self.controller.view['contacts'], [])

    def test_node_change_discards_late_friend_response(self):
        self._friend_node()
        account = 'a' * 32 + '.' + 'b' * 32
        with patch.object(self.controller, 'job', side_effect=lambda key, coroutine: coroutine.close()):
            self.controller.lookup_friend({'identifier': 'Alice'})
            key = self.controller.friend_request['key']
            self.controller.node_path = 'different-node'
            response = self._social_state()
            response['friends'] = [dict(account=account, username='Alice', online=True)]
            self.controller.finish(key, response, None)
        self.assertEqual(self.controller.view['contacts'], [])

    def test_player_metrics_remain_separate_and_unknown_counts_are_cleared(self):
        controller = self.controller
        controller.update_chat('first', dict(type='room', state='ready', members=4,
            capacity=8, game_players=2, latency_ms=56))
        record = controller.records['first']
        self.assertEqual([record[k] for k in ('members','capacity','game_players','latency_ms')], [4,8,2,56])
        controller.update_chat('first', dict(type='room', state='waiting', game_players=None, latency_ms=None))
        self.assertEqual(record['members'], 4)
        self.assertIsNone(record['game_players'])
        self.assertIsNone(record['latency_ms'])
        controller.update_chat('first', dict(type='room', members=True, capacity=-1,
            game_players='7', latency_ms=1000001))
        self.assertTrue(all(record[k] is None for k in ('members','capacity','game_players','latency_ms')))

    def test_failed_or_stale_verification_does_not_save_node(self):
        controller = self.controller
        controller.finish('nodecode:expired-generation', None, None)
        self.assertEqual(controller.store.data['nodes'], [])
        controller.patch(busy=True, nodeDraft='keep this code')
        controller.finish('nodecode:' + controller.generation, None, ConnectionError())
        self.assertFalse(controller.view['busy'])
        self.assertEqual(controller.view['nodeDraft'], 'keep this code')
        self.assertTrue(controller.view['error'])
        self.assertEqual(controller.store.data['nodes'], [])

    def test_json_import_requires_verification_and_copies_the_verified_profile(self):
        key = asyncssh.generate_private_key('ssh-ed25519').export_public_key().decode()
        profile = RelayProfile('127.0.0.1', 3333, 'a' * 48, key)
        source = Path(self.temporary.name) / 'downloaded.json'
        save_json(source, profile_data(profile))
        controller = self.controller
        with patch.object(controller, 'job', side_effect=lambda key, coroutine: coroutine.close()) as job:
            controller.import_node(str(source))
            self.assertTrue(controller.view['busy'])
            self.assertEqual(controller.store.data['nodes'], [])
            self.assertEqual(job.call_args.args[0], 'nodecode:' + controller.generation)
            controller.finish('nodecode:' + controller.generation, profile, None)
        saved = Path(controller.store.data['nodes'][0])
        self.assertNotEqual(saved, source)
        source.unlink()
        self.assertEqual(RelayProfile.load(saved), profile)

    def test_room_switch_keeps_messages_drafts_and_pending_results_separate(self):
        controller = self.controller
        controller.act('chatDraft', {'text':'first draft'})
        controller.update_chat('first', {'type':'message', 'id':'one', 'text':'first message'})
        controller.act('selectConnection', {'id':'second'})
        controller.act('chatDraft', {'text':'second draft'})
        self.assertEqual(controller.view['chatMessages'], [])
        future = Future()
        future.set_result(None)
        controller.finish_chat('first', future)
        self.assertEqual(controller.view['chatDraft'], 'second draft')
        controller.act('selectConnection', {'id':'first'})
        self.assertEqual(controller.view['chatMessages'][0]['text'], 'first message')
        self.assertEqual(controller.view['chatDraft'], '')

    def test_duplicate_replay_is_deduplicated_and_old_history_is_bounded(self):
        controller = self.controller
        event = {'type':'message', 'id':'same', 'text':'one'}
        controller.update_chat('first', event)
        controller.update_chat('first', {**event, 'replay':True})
        self.assertEqual(len(controller.view['chatMessages']), 1)
        for i in range(205):
            controller.update_chat('first', {'type':'message', 'id':str(i), 'text':str(i)})
        self.assertEqual(len(controller.view['chatMessages']), 200)
        self.assertEqual(controller.view['chatMessages'][0]['id'], '5')


if __name__ == '__main__':
    unittest.main()
