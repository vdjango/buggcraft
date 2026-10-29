"""Visible Qt input tests for the compact preparation room and its disclosures."""
import os
from pathlib import Path
import unittest

from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest
import test_lobby_layout as fixtures
from test_lobby_layout import find_item

ROOT = Path(__file__).resolve().parents[1]


class RoomLobbyUiTests(unittest.TestCase):
    setUpClass = fixtures.LobbyLayoutTests.__dict__['setUpClass']
    setUp = fixtures.LobbyLayoutTests.setUp
    dispose_window = fixtures.LobbyLayoutTests.dispose_window
    click = fixtures.LobbyLayoutTests.click

    def room(self, preparing=False):
        snapshot = dict(self_id='host', manager_id='host', provider_id='host',
            config_id='a' * 64, revision=8, online=4, ready=2, transfer=None, blocked=[], members=[
                dict(id='host', name='房主', online=True, manager=True, provider=True, state='ready', path='local', stale=False),
                dict(id='guest1', name='正在同步的朋友', online=True, state='downloading', stage='assets',
                     path='p2p', rtt_ms=31, rtt_kind='game', done=40, total=100, stale=False),
                dict(id='guest2', name='已准备好的朋友', online=True, state='ready', path='relay', rtt_ms=57, rtt_kind='node', stale=False),
                dict(id='guest3', name='下载失败的朋友', online=True, state='failed', path='relay', rtt_ms=None, rtt_kind='unknown', stale=False)])
        record = dict(id='room', title='今晚一起生存', role='host', state='online', availability='waiting',
            public=False, requireInvite=True, isManager=True, lobby=snapshot,
            compatibility='', game=dict(version='1.21.8', loader='fabric', loader_version='0.16.14', mods_count=12),
            preparing=preparing, prepareStatus='', prepareLogs=[
                dict(time='20:31:08', text='正在下载游戏资源 14 / 32', category='game', level='info'),
                dict(time='20:31:09', text='sodium.jar · 校验完成', category='mods', level='info'),
                dict(time='20:31:10', text='远程资源暂不可用，等待重试', category='resources', level='error'),
                dict(time='20:31:11', text='文件完整性校验通过', category='verify', level='info')])
        self.backend._view.update(page='connected', selected='room', connections=[record],
            chatState='在线', chatMessages=[], chatDraft='', chatError='', chatSending=False,
            bridgeStatus='游戏聊天未开启')
        self.backend.viewChanged.emit(); QTest.qWait(90)
        return record

    def save(self, name):
        folder = ROOT / 'build/room-preparation-ui'
        folder.mkdir(parents=True, exist_ok=True)
        self.assertTrue(self.window.grabWindow().save(str(folder / (name + '.png'))))

    def test_compact_preparation_room_at_both_sizes_and_launch_stays_available(self):
        self.room()
        self.assertTrue(find_item(self.window, 'room-chat-input').isVisible())
        with self.assertRaises(AssertionError):
            find_item(self.window, 'copy-invite')
        self.save('room-default-chat')
        self.click('room-tab-members')
        self.window.setResizeMode(QQuickView.SizeRootObjectToView)
        for width, height in ((721, 505), (1000, 650)):
            self.window.resize(width, height); QTest.qWait(80)
            self.assertTrue(find_item(self.window, 'room-members-list').isVisible())
            self.assertGreater(find_item(self.window, 'room-members-list').height(), 150)
            self.assertEqual(find_item(self.window, 'room-ready-count').property('text'), '2 / 4 已准备')
            self.assertEqual(find_item(self.window, 'member-state-guest1').property('text'), '下载中')
            self.assertEqual(find_item(self.window, 'member-progress-guest1').property('value'), 40)
            button = find_item(self.window, 'host-start-game')
            self.assertTrue(button.isEnabled())
            self.assertLessEqual(button.mapToScene(QPointF(button.width(), 0)).x(), width - 12)
            self.save('preparation-room-' + str(width))
        self.click('host-start-game')
        self.assertEqual(self.backend.actions[-1], ('launchRoom', {}))

    def test_guest_download_room_shows_client_progress_speed_and_install_log(self):
        """Capture the actual guest room while its launcher installs the host's config."""
        record = self.room(preparing=True)
        record.update(role='client', isManager=False, compatibility='正在同步房主的模组与游戏文件',
            prepareStatus='正在下载房间客户端 · 模组与游戏资源', prepareProgress=45,
            prepareMaximum=100, prepareFile='mods/sodium.jar', prepareFileDone=3 * 1024 * 1024,
            prepareFileTotal=5 * 1024 * 1024, prepareSpeed='2.4 MiB/s',
            prepareIndex=2, prepareCount=5)
        record['lobby']['self_id'] = 'guest1'
        self.backend.viewChanged.emit(); QTest.qWait(80)
        self.assertTrue(find_item(self.window, 'room-install-progress').isVisible())
        self.assertIn('sodium.jar', find_item(self.window, 'room-download-file').property('text'))
        self.assertIn('2.4 MiB/s', find_item(self.window, 'room-download-bytes').property('text'))
        self.assertEqual(find_item(self.window, 'room-install-progress').property('value'), 45)
        self.save('guest-downloading-room-client')
        self.click('room-tab-install')
        self.save('guest-downloading-room-client-logs')

    def test_member_roster_always_shows_room_host_for_host_and_guest(self):
        """Role ids from the bridge must remain visible even without row flags."""
        record = self.room()
        self.click('room-tab-members')
        host_row = find_item(self.window, 'room-member-host')
        self.assertTrue(host_row.isVisible())
        self.assertEqual(find_item(self.window, 'member-role-host').property('text'), '房主')

        # Older nodes sent manager_id/provider_id but omitted the per-row flags.
        host = record['lobby']['members'][0]
        host.pop('manager', None)
        host.pop('provider', None)
        record.update(role='client', isManager=False)
        record['lobby']['self_id'] = 'guest1'
        self.backend.viewChanged.emit(); QTest.qWait(50)
        self.assertEqual(find_item(self.window, 'member-role-host').property('text'), '房主')

    def test_member_management_requires_explicit_confirmation_and_can_be_cancelled(self):
        self.room()
        self.click('room-tab-members')
        self.click('member-menu-guest1'); self.click('member-kick')
        self.assertFalse(any(action == 'kickMember' for action, _ in self.backend.actions))
        self.click('member-confirm-cancel')
        self.assertFalse(any(action == 'kickMember' for action, _ in self.backend.actions))
        self.click('member-menu-guest1'); self.click('member-offer-owner')
        self.save('room-member-transfer-confirmation')
        self.click('member-confirm-submit')
        self.assertEqual(self.backend.actions[-1], ('offerOwner', {'member': 'guest1'}))

    def test_host_and_guest_have_diagnostics_and_anonymous_submission_is_disabled(self):
        record = self.room()
        self.click('room-submit-diagnostics')
        self.assertEqual(self.backend.actions[-1], ('submitDiagnostics', {}))
        record.update(role='client', isManager=False)
        self.backend.viewChanged.emit(); QTest.qWait(40)
        self.click('room-submit-diagnostics')
        self.assertEqual(self.backend.actions[-1], ('submitDiagnostics', {}))
        self.backend._view['socialReady'] = False
        self.backend.viewChanged.emit(); QTest.qWait(40)
        self.assertFalse(find_item(self.window, 'room-submit-diagnostics').isEnabled())

    def test_long_member_list_has_explicit_paging_and_hides_it_after_last_page(self):
        record = self.room()
        record['lobby']['next'] = 32
        self.backend.viewChanged.emit(); QTest.qWait(50)
        self.click('room-tab-members'); self.click('room-members-more')
        self.assertEqual(self.backend.actions[-1], ('moreMembers', {}))
        record['lobby']['next'] = None
        self.backend.viewChanged.emit(); QTest.qWait(50)
        self.assertFalse(find_item(self.window, 'room-members-more').isVisible())

    def test_install_logs_are_separate_searchable_filterable_and_keep_launch_visible(self):
        self.room()
        self.click('room-tab-install')
        entries = find_item(self.window, 'room-install-log')
        self.assertEqual(entries.property('count'), 4)
        self.save('room-install-logs')
        search = find_item(self.window, 'room-log-search')
        self.click('room-log-search')
        for letter in 'sodium':
            QTest.keyClick(self.window, ord(letter.upper()))
        QTest.qWait(50); self.assertEqual(entries.property('count'), 1)
        search.setProperty('text', '')
        self.click('room-log-category'); QTest.keyClick(self.window, Qt.Key_Down); QTest.keyClick(self.window, Qt.Key_Down); QTest.keyClick(self.window, Qt.Key_Return)
        QTest.qWait(50); self.assertEqual(entries.property('count'), 1)
        self.click('room-log-copy')
        self.assertEqual(self.backend.actions[-1][0], 'copyPrepareLog')
        self.click('room-log-follow')
        self.assertFalse(find_item(self.window, 'room-log-follow').property('checked'))
        self.assertTrue(find_item(self.window, 'host-start-game').isVisible())
        self.click('room-tab-chat')
        self.assertTrue(find_item(self.window, 'room-chat-input').isVisible())
        self.click('room-tab-members')
        self.assertTrue(find_item(self.window, 'room-members-list').isVisible())

    def test_player_explicitly_allows_or_denies_log_access_and_can_stop_sharing(self):
        record = self.room()
        record.update(role='client', isManager=False)
        record['lobby'].update(self_id='guest1', logs=dict(request=dict(id='consent-1', name='房主'), sharing=False))
        self.backend.viewChanged.emit(); QTest.qWait(70)
        self.assertTrue(find_item(self.window, 'room-log-allow').isVisible())
        self.assertFalse(any(action == 'answerLogRequest' for action, _ in self.backend.actions))
        self.click('room-log-deny')
        self.assertEqual(self.backend.actions[-1], ('answerLogRequest', {'request':'consent-1', 'allow':False}))
        record['lobby']['logs']['request']['id'] = 'consent-2'
        self.backend.viewChanged.emit(); QTest.qWait(70)
        self.save('room-player-log-consent')
        self.click('room-log-allow')
        self.assertEqual(self.backend.actions[-1], ('answerLogRequest', {'request':'consent-2', 'allow':True}))
        record['lobby']['logs'].update(request=None, sharing=True)
        self.backend.viewChanged.emit(); QTest.qWait(50)
        self.click('revoke-room-log-access')
        self.assertEqual(self.backend.actions[-1], ('revokeLogAccess', {}))

    def test_manager_requests_logs_before_reading_and_authorized_logs_have_separate_view(self):
        record = self.room()
        self.click('room-tab-members')
        self.click('member-menu-guest1'); self.click('member-install-logs')
        self.assertEqual(self.backend.actions[-1], ('requestMemberLogs', {'member':'guest1'}))
        record['lobby']['logs'] = dict(allowed=['guest1'])
        record.update(remoteLogMember='guest1', remoteLogName='正在同步的朋友', remoteLogs=record['prepareLogs'])
        self.backend.viewChanged.emit(); QTest.qWait(50)
        self.click('member-menu-guest1'); self.click('member-install-logs')
        self.assertEqual(self.backend.actions[-1], ('viewMemberLogs', {'member':'guest1'}))
        self.assertTrue(find_item(self.window, 'remote-room-install-log').isVisible())
        self.assertEqual(find_item(self.window, 'remote-room-install-log').property('count'), 4)
        self.save('room-authorized-player-logs')
        self.click('remote-room-log-copy')
        self.assertEqual(self.backend.actions[-1], ('copyPrepareLog', {'remote':True}))
        self.click('close-remote-log')
