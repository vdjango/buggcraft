"""Load the shipped QML hall to check hierarchy, compact sizing and tab navigation."""
import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src' / 'buggcraft'))
from PySide6.QtCore import Property, QObject, QPointF, Qt, Signal, Slot, QUrl, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtQuick import QQuickView, QQuickItem


class LobbyBackend(QObject):
    viewChanged = Signal()
    copied = Signal(str)

    def __init__(self):
        super().__init__()
        self._view = {
            'page': 'hall', 'rooms': [
                {'id': 'one', 'title': 'Room one', 'game': {'version': '1.21.8', 'loader': 'vanilla'}, 'connections': 1},
                {'id': 'two', 'title': 'Room two', 'game': {'version': '1.20.1', 'loader': 'fabric'}, 'connections': 4},
            ], 'loading': False, 'roomError': '', 'busy': False, 'nodeIndex': 0,
            'nodes': [{'title': 'Local relay'}], 'nodeAvailable':True, 'selected': '', 'connections': [],
            'editIndex': -1, 'error': '', 'notice': '',
            'contacts': [{'index': 0, 'name': 'Friend', 'invite': 'secret'}],
            'socialReady': True, 'socialName': 'local_user', 'socialError': '',
            'friendRequests': [], 'friendInvitations': [],
            'step':0, 'worlds':[], 'instances':[], 'instanceId':'', 'instanceLoading':False,
            'instanceError':'', 'instanceLocked':False, 'version':'', 'loader':'vanilla',
            'loaderVersion':'', 'needsVersion':False,
            'nodeDraft':'', 'joinRoomId':'', 'joinRoomTitle':'',
            'invitePrompt':False, 'roomQuery':'', 'roomNext':None, 'roomTotal':None, 'loadingMore':False,
            'transportPolicy':'auto',
            'nodeUpdatePrompt':False, 'nodeUpdateMessage':'',
        }
        self.actions = []

    @Property('QVariantMap', notify=viewChanged)
    def view(self):
        return self._view

    @Slot(str, 'QVariantMap')
    def act(self, name, values):
        values = dict(values)
        self.actions.append((name, values))
        if name == 'navigate':
            self._view = {**self._view, 'page': values['page']}
            self.viewChanged.emit()
        elif name == 'node':
            self._view = {**self._view, 'nodeIndex': values['index']}
            self.viewChanged.emit()
        elif name == 'nodeDraft':
            self._view = {**self._view, 'nodeDraft': values['text']}
            self.viewChanged.emit()
        elif name == 'selectConnection':
            self._view = {**self._view, 'selected':values['id'], 'page':'connected'}
            self.viewChanged.emit()
        elif name == 'cancelInvite':
            self._view = {**self._view, 'invitePrompt':False, 'error':'', 'joinRoomId':'', 'joinRoomTitle':''}
            self.viewChanged.emit()
        elif name == 'copyAddress':
            self.copied.emit('address')
        elif name == 'copyInvite':
            self.copied.emit('invite')


def find_item(root, object_name):
    stack = [root.contentItem() if hasattr(root, 'contentItem') else root.rootObject()]
    while stack:
        item = stack.pop()
        if isinstance(item, QQuickItem) and item.objectName() == object_name:
            return item
        stack.extend(item.childItems())
    raise AssertionError('QML item not found: ' + object_name)


class LobbyLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.backend = LobbyBackend()
        self.window = QQuickView()
        self.window.resize(721, 505)
        self.window.rootContext().setContextProperty('lobby', self.backend)
        self.window.setSource(QUrl.fromLocalFile(str(ROOT / 'resources/qml/multiplayer/Lobby.qml')))
        self.assertEqual(self.window.status(), QQuickView.Ready,
                         '\n'.join(error.toString() for error in self.window.errors()))
        self.window.show()
        QTest.qWait(80)
        self.addCleanup(self.window.close)

    def click(self, object_name):
        item = find_item(self.window, object_name)
        point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
        QTest.mouseClick(self.window, Qt.LeftButton, Qt.NoModifier, point)
        QTest.qWait(30)
        return item

    def assert_absent_or_hidden(self, name):
        try:
            item = find_item(self.window, name)
        except AssertionError:
            return
        self.assertFalse(item.isVisible(), name)

    def open_nodes(self):
        self.click('node-picker')
        QTest.keyClick(self.window, Qt.Key_End)
        QTest.keyClick(self.window, Qt.Key_Return)
        QTest.qWait(60)
        self.assertEqual(self.backend.view['page'], 'nodes')

    def test_existing_node_update_prompts_before_overwriting_and_has_cancel(self):
        self.backend._view.update(nodeUpdatePrompt=True, nodeUpdateMessage='Update this node?')
        self.backend.viewChanged.emit()
        QTest.qWait(70)
        self.click('confirm-node-update')
        self.assertEqual(self.backend.actions[-1][0], 'confirmNodeUpdate')
        self.click('cancel-node-update')
        self.assertEqual(self.backend.actions[-1][0], 'cancelNodeUpdate')

    def test_node_picker_replaces_tab_and_opens_a_secondary_management_page(self):
        with self.assertRaises(AssertionError):
            find_item(self.window, 'nav-nodes')
        picker = find_item(self.window, 'node-picker')
        self.assertIn('Local relay', picker.property('displayText'))
        self.assertEqual(picker.height(), find_item(self.window, 'refresh-rooms').height())
        self.assertLessEqual(picker.mapToScene(QPointF(picker.width(), 0)).x(), 707)
        self.open_nodes()
        self.assert_absent_or_hidden('navigation-tabs')
        self.assertTrue(find_item(self.window, 'back-hall').isVisible())
        for name in ('nodes-list', 'node-code', 'add-node-code', 'import-node', 'nodes-done'):
            item = find_item(self.window, name)
            self.assertTrue(item.isVisible(), name)
            pos = item.mapToScene(QPointF(0, 0))
            self.assertGreaterEqual(pos.x(), 14, name)
            self.assertLessEqual(pos.x() + item.width(), 707, name)
            self.assertGreaterEqual(pos.y(), 54, name)
            self.assertLessEqual(pos.y() + item.height(), 491, name)
        self.click('back-hall')
        self.assertEqual(self.backend.view['page'], 'hall')
        self.assertEqual(find_item(self.window, 'node-picker').property('currentIndex'), 0)

    def test_node_picker_disabled_while_a_room_exists(self):
        picker = find_item(self.window, 'node-picker')
        self.assertTrue(picker.isEnabled())
        self.backend._view['connections'] = [{'id':'test', 'title':'Test', 'state':'online', 'role':'host'}]
        self.backend.viewChanged.emit()
        QTest.qWait(30)
        self.assertFalse(picker.isEnabled())
        self.backend._view['connections'] = []
        self.backend.viewChanged.emit()
        QTest.qWait(30)
        self.assertTrue(picker.isEnabled())

    def test_node_picker_switches_without_opening_management_and_escape_keeps_hall(self):
        self.backend._view = {**self.backend._view, 'nodes':[{'title':'First'},{'title':'Second'}]}
        self.backend.viewChanged.emit(); QTest.qWait(30)
        self.click('node-picker'); QTest.keyClick(self.window, Qt.Key_Down); QTest.keyClick(self.window, Qt.Key_Return)
        QTest.qWait(40)
        self.assertEqual(self.backend.actions[-1], ('node', {'index':1}))
        self.assertEqual(self.backend.view['page'], 'hall')
        self.click('node-picker'); QTest.keyClick(self.window, Qt.Key_Escape); QTest.qWait(30)
        self.assertEqual(self.backend.view['page'], 'hall')

    def test_empty_node_entry_and_draft_survive_secondary_page_navigation(self):
        self.backend._view = {**self.backend._view, 'nodes':[], 'nodeIndex':-1, 'rooms':[]}
        self.backend.viewChanged.emit(); QTest.qWait(30)
        self.click('empty-add-node')
        self.assertEqual(self.backend.view['page'], 'nodes')
        self.click('node-code'); QApplication.clipboard().setText('buggnode1-example')
        QTest.keyClick(self.window, Qt.Key_V, Qt.ControlModifier); QTest.qWait(30)
        self.assertEqual(self.backend.view['nodeDraft'], 'buggnode1-example')
        self.assertTrue(find_item(self.window, 'add-node-code').isEnabled())
        self.click('back-hall'); self.open_nodes()
        self.assertEqual(find_item(self.window, 'node-code').property('text'), 'buggnode1-example')

    def test_remove_node_requires_a_second_click(self):
        self.open_nodes(); self.click('remove-node')
        self.assertNotEqual(self.backend.actions[-1][0], 'removeNode')
        self.click('remove-node')
        self.assertEqual(self.backend.actions[-1], ('removeNode', {}))

    def test_node_management_keeps_actions_visible_with_busy_and_error_feedback(self):
        self.open_nodes()
        self.backend._view = {**self.backend._view, 'busy':True, 'nodeDraft':'buggnode1-example',
            'notice':'正在验证节点身份和连接…'}
        self.backend.viewChanged.emit(); QTest.qWait(40)
        self.assertFalse(find_item(self.window, 'add-node-code').isEnabled())
        self.assertFalse(find_item(self.window, 'import-node').isEnabled())
        self.backend._view = {**self.backend._view, 'busy':False, 'notice':'',
            'error':'添加失败：无法验证节点身份或连接，请检查添加码和网络。'}
        self.backend.viewChanged.emit(); QTest.qWait(40)
        self.assertTrue(find_item(self.window, 'add-node-code').isEnabled())
        feedback = find_item(self.window, 'feedback')
        self.assertTrue(feedback.isVisible())
        for name in ('node-code', 'add-node-code', 'import-node', 'nodes-done'):
            item = find_item(self.window, name)
            bottom = item.mapToScene(QPointF(0, item.height())).y()
            self.assertLessEqual(bottom, 491, name)

    def test_open_room_list_is_primary_and_create_join_actions_stay_compact(self):
        join = find_item(self.window, 'open-join')
        create = find_item(self.window, 'open-create')
        rooms = find_item(self.window, 'rooms-list')
        self.assertLessEqual(join.height(), 42)
        self.assertLessEqual(create.height(), 42)
        self.assertGreaterEqual(rooms.height(), 270)
        self.assertGreater(rooms.width(), 650)
        self.assertLessEqual(join.x() - create.x() - create.width(), 12)
        self.assert_absent_or_hidden('navigation-tabs')
        self.assertTrue(find_item(self.window, 'join-public-0').isVisible())
        self.assertTrue(find_item(self.window, 'join-public-1').isVisible())

    def test_room_latency_is_visible_and_distinguishes_unavailable_from_zero(self):
        for value, available, expected in [(57.4, True, '节点 57 ms'),
                                            (0, True, '节点 0 ms'),
                                            (None, True, '延迟 —'),
                                            (57, False, '延迟 —')]:
            self.backend._view = {**self.backend._view, 'nodeLatencyMs': value,
                                  'nodeAvailable': available}
            self.backend.viewChanged.emit()
            QTest.qWait(30)
            for index in range(2):
                latency = find_item(self.window, 'room-latency-' + str(index))
                self.assertTrue(latency.isVisible())
                self.assertEqual(latency.property('text'), expected)
                join = find_item(self.window, 'join-public-' + str(index))
                self.assertLess(latency.mapToScene(QPointF(latency.width(), 0)).x(),
                                join.mapToScene(QPointF(0, 0)).x())
                self.assertLessEqual(join.mapToScene(QPointF(join.width(), 0)).x(),
                                     self.window.width())

    def test_current_room_entry_opens_room_without_a_navigation_menu(self):
        self.backend._view = {**self.backend._view, 'connections': [
            {'id': 'mine', 'title': 'My world', 'role': 'host', 'state': 'online'}]}
        self.backend.viewChanged.emit()
        QTest.qWait(40)
        self.click('current-room-entry')
        self.assertEqual(self.backend.actions[-1], ('selectConnection', {'id':'mine'}))
        self.assertEqual(self.backend.view['page'], 'connected')
        for name in ('navigation-tabs', 'nav-hall', 'nav-connections', 'room-search', 'open-create'):
            self.assert_absent_or_hidden(name)
        self.backend.act('navigate', {'page':'hall'})
        QTest.qWait(40)
        self.click('open-friends-window')
        self.assertEqual(self.backend.actions[-1], ('openFriends', {}))
        self.assertEqual(self.backend.view['page'], 'hall')

    def test_current_room_entry_only_appears_after_creating_or_joining(self):
        tab = find_item(self.window, 'current-room-entry')
        self.assertFalse(tab.isVisible())
        search = find_item(self.window, 'room-search')
        empty_width = search.width()
        for role in ('host', 'client'):
            for state in ('connecting', 'online', 'reconnecting'):
                self.backend._view = {**self.backend._view, 'connections': [
                    {'id': 'mine', 'title': 'My world', 'role': role, 'state': state}]}
                self.backend.viewChanged.emit()
                QTest.qWait(30)
                self.assertTrue(tab.isVisible(), (role, state))
                self.assertEqual(search.width(), empty_width)
                self.assertIn('我创建' if role == 'host' else '我加入', tab.property('text'))
        self.backend._view = {**self.backend._view, 'connections': []}
        self.backend.viewChanged.emit()
        QTest.qWait(30)
        self.assertFalse(tab.isVisible())
        self.assertEqual(search.width(), empty_width)

    def test_primary_actions_open_the_corresponding_workflow(self):
        self.click('open-join')
        self.assertEqual(self.backend.actions[-1], ('navigate', {'page': 'join'}))
        self.assert_absent_or_hidden('navigation-tabs')
        self.click('back-hall')
        self.click('open-create')
        self.assertEqual(self.backend.actions[-1], ('navigate', {'page': 'create'}))

    def test_create_before_game_is_a_fixed_secondary_footer_action(self):
        self.backend._view = {**self.backend._view, 'version':'1.21.8',
            'instances':['1.21.8'], 'instanceId':'1.21.8',
            'worlds':[dict(version='1.21.8', port=51000 + i) for i in range(12)]}
        self.click('open-create')
        action = find_item(self.window, 'create-before-game')
        footer = find_item(self.window, 'create-footer')
        scroll = find_item(self.window, 'create-world-scroll')
        cancel = find_item(self.window, 'cancel-create')
        next_action = find_item(self.window, 'create-next')
        self.assertIs(action.parentItem(), footer)
        self.assertTrue(action.isVisible() and action.isEnabled())
        self.assertFalse(action.property('primary'))
        self.assertEqual(action.property('text'), '先创建房间')
        for notice in ('', 'Node added'):
            with self.subTest(notice=notice):
                self.backend._view = {**self.backend._view, 'notice':notice}
                self.backend.viewChanged.emit()
                QTest.qWait(50)
                self.assertGreaterEqual(footer.mapToScene(QPointF()).y(),
                    scroll.mapToScene(QPointF(0, scroll.height())).y())
                self.assertLess(action.x() + action.width(), cancel.x())
                self.assertLessEqual(cancel.x() + cancel.width(), next_action.x())
                for button in (action, cancel, next_action):
                    point = button.mapToScene(QPointF(button.width(), button.height()))
                    self.assertLessEqual(point.x(), self.window.width() - 14)
                    self.assertLessEqual(point.y(), self.window.height() - 14)
                    self.assertAlmostEqual(button.y() + button.height() / 2,
                        next_action.y() + next_action.height() / 2, delta=1)
        self.click('create-before-game')
        self.assertEqual(self.backend.actions[-1], ('createWaiting', {}))
        for values in ({'busy':True}, {'busy':False, 'instanceLoading':True},
                       {'instanceLoading':False, 'version':''}):
            self.backend._view = {**self.backend._view, **values}
            self.backend.viewChanged.emit()
            QTest.qWait(30)
            self.assertFalse(action.isEnabled())
        self.backend._view = {**self.backend._view, 'step':1}
        self.backend.viewChanged.emit()
        QTest.qWait(30)
        self.assertFalse(action.isVisible())
        self.assertTrue(find_item(self.window, 'create-back').isVisible())

    def test_empty_room_state_is_visible_without_public_rooms(self):
        self.backend._view = {**self.backend._view, 'rooms': []}
        self.backend.viewChanged.emit()
        QTest.qWait(60)
        self.assertTrue(find_item(self.window, 'rooms-empty').isVisible())

    def test_unavailable_and_checking_nodes_disable_all_hall_room_actions(self):
        for index, loading in ((-1, False), (0, True), (0, False)):
            with self.subTest(index=index, loading=loading):
                self.backend._view = {**self.backend._view, 'nodeIndex':index,
                    'nodeAvailable':False, 'loading':loading}
                self.backend.viewChanged.emit()
                QTest.qWait(30)
                self.backend.actions.clear()
                for name in ('open-create', 'open-join', 'join-public-0'):
                    self.assertFalse(find_item(self.window, name).isEnabled())
                    self.click(name)
                self.assertEqual(self.backend.actions, [])
        self.backend._view = {**self.backend._view, 'nodeIndex':0,
            'nodeAvailable':True, 'loading':False}
        self.backend.viewChanged.emit()
        QTest.qWait(30)
        self.assertTrue(find_item(self.window, 'open-create').isEnabled())
        self.assertTrue(find_item(self.window, 'open-join').isEnabled())

    def test_connection_loss_during_create_or_join_keeps_cancel_available(self):
        for page in ('create', 'join'):
            self.backend._view = {**self.backend._view, 'page':page, 'version':'1.21.8',
                                 'nodeAvailable':False, 'step':0}
            self.backend.viewChanged.emit()
            QTest.qWait(40)
            submit = 'create-next' if page == 'create' else 'join-confirm'
            self.assertFalse(find_item(self.window, submit).isEnabled())
            if page == 'create':
                self.assertFalse(find_item(self.window, 'create-before-game').isEnabled())
            self.assertTrue(find_item(self.window, page + '-node-unavailable').isVisible())
            self.click('cancel-' + page)
            self.assertEqual(self.backend.view['page'], 'hall')

    def test_lazy_room_list_does_not_request_more_before_user_scroll(self):
        rows = [dict(id=str(i), title='Room ' + str(i),
                     game={'version':'1.21.8', 'loader':'vanilla'}, members=1, capacity=100)
                for i in range(20)]
        self.backend._view = {**self.backend._view, 'rooms':rows, 'roomNext':20, 'roomTotal':45}
        self.backend.viewChanged.emit()
        QTest.qWait(80)
        self.assertEqual(find_item(self.window, 'rooms-list').property('count'), 20)
        self.assertIn('45', find_item(self.window, 'room-count').property('text'))
        self.assertFalse(any(action == 'loadMoreRooms' for action, _ in self.backend.actions))
        rooms = find_item(self.window, 'rooms-list')
        rooms.setProperty('contentY', rooms.property('contentHeight') - rooms.height())
        QTest.qWait(50)
        self.click('load-more-rooms')
        self.assertEqual(self.backend.actions[-1], ('loadMoreRooms', {}))
        self.backend._view = {**self.backend._view, 'loadingMore':True}
        self.backend.viewChanged.emit()
        QTest.qWait(30)
        self.assertFalse(find_item(self.window, 'load-more-rooms').isEnabled())

    def test_copy_game_address_feedback_does_not_move_chat_or_show_toast(self):
        self.backend._view = {**self.backend._view, 'page':'connected', 'selected':'mine',
            'connections':[dict(id='mine', title='World', role='client', state='online', availability='ready')],
            'chatState':'在线', 'chatMessages':[], 'chatDraft':'', 'chatError':'',
            'chatSending':False, 'bridgeStatus':'同步未开启'}
        self.backend.viewChanged.emit()
        QTest.qWait(50)
        chat = find_item(self.window, 'room-chat')
        before = (chat.y(), chat.height())
        self.click('copy-address')
        self.assertIn('已复制', find_item(self.window, 'copy-address').property('text'))
        self.assertEqual((chat.y(), chat.height()), before)
        self.assertFalse(find_item(self.window, 'feedback-toast').isVisible())

    def test_world_discovery_separates_game_config_list_and_manual_port(self):
        self.backend._view = {**self.backend._view, 'version':'1.21.8',
            'instances':['1.21.8'], 'instanceId':'1.21.8'}
        self.click('open-create')
        config = find_item(self.window, 'create-game-config')
        discovery = find_item(self.window, 'create-world-discovery')
        self.assertLessEqual(config.y() + config.height() + 10, discovery.y() + 1)
        self.assertTrue(find_item(self.window, 'create-worlds-empty').isVisible())
        self.assertFalse(find_item(self.window, 'create-port').isVisible())
        self.click('discover-worlds')
        self.assertEqual(self.backend.actions[-1], ('discover', {}))
        self.backend._view = {**self.backend._view, 'worlds':[
            dict(version='1.21.8', port=51001), dict(version='1.21.8', port=51002)]}
        self.backend.viewChanged.emit()
        QTest.qWait(40)
        self.assertFalse(find_item(self.window, 'create-worlds-empty').isVisible())
        self.click('world-1')
        self.assertTrue(find_item(self.window, 'world-1').property('selected'))
        self.assertFalse(find_item(self.window, 'world-0').property('selected'))
        self.click('create-next')
        self.assertEqual(self.backend.actions[-1], ('probe', {'port':'51002'}))
        self.click('show-manual')
        self.assertTrue(find_item(self.window, 'create-port').isVisible())
        self.assertLessEqual(discovery.mapToScene(QPointF(0, discovery.height())).y(),
            find_item(self.window, 'create-footer').mapToScene(QPointF()).y())

    def test_chat_sync_opt_in_discloses_virtual_player_and_validates_name(self):
        self.backend._view = {**self.backend._view, 'step':1}
        self.click('open-create')
        enabled = find_item(self.window, 'create-game-chat')
        name = find_item(self.window, 'create-game-chat-name')
        submit = find_item(self.window, 'create-next')
        self.assertFalse(enabled.property('checked'))
        self.assertFalse(name.isVisible())
        explanation = find_item(self.window, 'create-game-chat-explanation')
        self.assertTrue(explanation.isVisible())
        self.assertIn('虚拟玩家', explanation.property('text'))
        self.assertIn('占用 1 个人数名额', explanation.property('text'))
        self.click('create-next')
        self.assertFalse(self.backend.actions[-1][1]['gameChatEnabled'])
        self.click('create-game-chat')
        self.assertTrue(name.isVisible())
        for invalid in ('中文', 'ab', 'Bugg Chat', '123'):
            name.setProperty('text', invalid)
            QTest.qWait(20)
            self.assertFalse(submit.isEnabled(), invalid)
        name.setProperty('text', 'LobbyBridge')
        QTest.qWait(20)
        self.assertTrue(submit.isEnabled())
        self.click('create-next')
        self.assertEqual(self.backend.actions[-1], ('create', {
            'title':'好友的世界', 'public':False, 'requireInvite':True, 'gameChatEnabled':True,
            'gameChatName':'LobbyBridge', 'transport':'auto'}))
        self.backend._view = {**self.backend._view, 'step':0}
        self.backend.viewChanged.emit()
        QTest.qWait(25)
        self.backend._view = {**self.backend._view, 'step':1}
        self.backend.viewChanged.emit()
        QTest.qWait(25)
        self.assertTrue(enabled.property('checked'))
        self.assertEqual(name.property('text'), 'LobbyBridge')

    def test_public_room_invite_policy_and_private_room_access(self):
        self.backend._view = {**self.backend._view, 'step':1}
        self.click('open-create')
        policy = find_item(self.window, 'create-require-invite')
        description = find_item(self.window, 'create-access-description')
        self.assertFalse(policy.isVisible())
        self.assertIn('不出现在大厅', description.property('text'))
        self.click('create-next')
        self.assertFalse(self.backend.actions[-1][1]['public'])
        self.assertTrue(self.backend.actions[-1][1]['requireInvite'])
        self.click('create-public')
        self.assertTrue(policy.isVisible())
        self.assertIn('无需填写邀请码', description.property('text'))
        self.click('create-next')
        self.assertTrue(self.backend.actions[-1][1]['public'])
        self.assertFalse(self.backend.actions[-1][1]['requireInvite'])
        self.click('create-require-invite')
        self.assertIn('房主提供的邀请码', description.property('text'))
        self.click('create-next')
        self.assertTrue(self.backend.actions[-1][1]['requireInvite'])
        self.click('create-public')
        self.assertFalse(policy.isVisible())
        self.click('create-public')
        self.assertTrue(policy.property('checked'))

    def test_creation_and_join_offer_default_p2p_with_relay_choice(self):
        self.backend._view = {**self.backend._view, 'transportPolicy':'auto', 'step':1}
        self.click('open-create')
        transport = find_item(self.window, 'create-transport')
        self.assertTrue(transport.isVisible())
        self.assertEqual(transport.property('currentIndex'), 0)
        transport.activated.emit(1)
        self.assertEqual(self.backend.actions[-1], ('transport', {'policy':'relay'}))
        self.backend._view = {**self.backend._view, 'page':'join', 'transportPolicy':'relay'}
        self.backend.viewChanged.emit(); QTest.qWait(40)
        join_transport = find_item(self.window, 'join-transport')
        self.assertTrue(join_transport.isVisible())
        self.assertEqual(join_transport.property('currentIndex'), 1)

    def test_hall_uses_one_join_action_and_invite_dialog_stays_on_hall(self):
        self.backend._view = {**self.backend._view, 'rooms':[
            {**self.backend.view['rooms'][0], 'require_invite':True},
            {**self.backend.view['rooms'][1], 'require_invite':False}]}
        self.backend.viewChanged.emit(); QTest.qWait(40)
        self.assertEqual(find_item(self.window, 'room-access-0').property('text'), '需要邀请码')
        self.assertEqual(find_item(self.window, 'join-public-0').property('text'), '加入')
        self.assertEqual(find_item(self.window, 'room-access-1').property('text'), '直接加入')
        self.click('join-public-0')
        self.assertEqual(self.backend.actions[-1], ('joinPublic', {'id':'one'}))
        self.backend._view = {**self.backend._view, 'invitePrompt':True,
            'joinRoomId':'one', 'joinRoomTitle':'Room one'}
        self.backend.viewChanged.emit(); QTest.qWait(40)
        self.assertEqual(self.backend.view['page'], 'hall')
        self.assertTrue(find_item(self.window, 'room-invite-input').isVisible())
        self.assertFalse(find_item(self.window, 'confirm-room-invite').isEnabled())
        self.click('room-invite-input')
        QApplication.clipboard().setText('bugg1-test')
        QTest.keyClick(self.window, Qt.Key_V, Qt.ControlModifier); QTest.qWait(30)
        self.click('confirm-room-invite')
        self.assertEqual(self.backend.actions[-1], ('join', {'invite':'bugg1-test'}))
        self.backend._view['error'] = '邀请码不属于所选房间'
        self.backend.viewChanged.emit(); QTest.qWait(30)
        self.assertTrue(find_item(self.window, 'room-invite-error').isVisible())
        self.assertFalse(find_item(self.window, 'feedback').isVisible())
        QTest.keyClick(self.window, Qt.Key_Escape); QTest.qWait(30)
        self.assertEqual(self.backend.actions[-1], ('cancelInvite', {}))
        self.assertEqual(self.backend.view['page'], 'hall')

    def test_created_room_guidance_matches_public_join_policy(self):
        for public, required, expected in ((True, False, '无需邀请码'),
                (True, True, '大厅可见，加入需要邀请码'),
                (False, True, '把邀请码发给朋友')):
            with self.subTest(public=public, required=required):
                self.backend._view = {**self.backend._view, 'page':'connected', 'selected':'mine',
                    'connections':[dict(id='mine', title='World', role='host', state='online',
                        availability='ready', public=public, requireInvite=required, game={})],
                    'chatState':'在线', 'chatMessages':[], 'chatDraft':'', 'chatError':'',
                    'chatSending':False, 'bridgeStatus':'游戏聊天未开启'}
                self.backend.viewChanged.emit(); QTest.qWait(35)
                self.assertIn(expected, find_item(self.window, 'room-access-guidance').property('text'))

    def test_friend_entry_opens_the_separate_window(self):
        self.click('open-friends-window')
        self.assertEqual(self.backend.actions[-1][0], 'openFriends')

    def test_node_selector_is_above_search_actions_and_room_list(self):
        node_row = find_item(self.window, 'room-node-row')
        search = find_item(self.window, 'room-search')
        count = find_item(self.window, 'room-count')
        create = find_item(self.window, 'open-create')
        join = find_item(self.window, 'open-join')
        refresh = find_item(self.window, 'refresh-rooms')
        status = find_item(self.window, 'node-status')
        status_indicator = find_item(self.window, 'node-status-indicator')
        controls = find_item(self.window, 'room-search-row')
        rooms = find_item(self.window, 'rooms-list')
        self.assertEqual(count.property('text'), '2 个房间')
        self.assertAlmostEqual(create.mapToScene(QPointF(0, create.height() / 2)).y(),
                               search.mapToScene(QPointF(0, search.height() / 2)).y(), delta=1)
        self.assertAlmostEqual(join.mapToScene(QPointF(0, join.height() / 2)).y(),
                               search.mapToScene(QPointF(0, search.height() / 2)).y(), delta=1)
        self.assertAlmostEqual(count.mapToScene(QPointF(0, count.height() / 2)).y(),
                               search.mapToScene(QPointF(0, search.height() / 2)).y(), delta=1)
        self.assertGreaterEqual(node_row.height(), 30)
        self.assertEqual(find_item(self.window, 'rooms-loaded').property('text'), '已连接')
        self.assertGreater(status.mapToItem(node_row, QPointF(0, 0)).x(),
                           find_item(self.window, 'node-picker').mapToItem(node_row, QPointF(0, 0)).x())
        self.assertLess(status_indicator.mapToItem(status, QPointF(0, 0)).x(), status.width())
        self.assertGreater(refresh.mapToItem(node_row, QPointF(0, 0)).x(),
                           status.mapToItem(node_row, QPointF(status.width(), 0)).x())
        self.assertAlmostEqual(refresh.mapToItem(node_row, QPointF(refresh.width(), 0)).x(),
                               node_row.width() - 9, delta=2)
        self.assertLess(node_row.mapToScene(QPointF(0, node_row.height())).y(),
                        controls.mapToScene(QPointF(0, 0)).y())
        point = search.mapToItem(controls, QPointF(0, 0))
        self.assertGreaterEqual(point.y(), 0)
        self.assertLessEqual(point.y() + search.height(), controls.height())
        self.assertGreaterEqual(search.width(), 240)
        self.assertGreaterEqual(refresh.mapToItem(node_row, QPointF(0, 0)).y(), 0)
        self.assertLessEqual(refresh.mapToItem(node_row, QPointF(0, 0)).y() + refresh.height(), node_row.height())
        self.assertGreater(controls.mapToScene(QPointF(0, controls.height())).y(),
                           node_row.mapToScene(QPointF(0, node_row.height())).y())
        self.assertGreater(rooms.mapToScene(QPointF(0, 0)).y(),
                           controls.mapToScene(QPointF(0, controls.height())).y())
        self.click('room-search')
        QApplication.clipboard().setText('fabric')
        QTest.keyClick(self.window, Qt.Key_V, Qt.ControlModifier)
        QTest.qWait(50)
        self.assertEqual(self.backend.actions[-1], ('searchRooms', {'text':'fabric'}))
        self.backend._view = {**self.backend._view, 'roomQuery':'fabric',
            'rooms':[self.backend.view['rooms'][1]], 'roomTotal':1}
        self.backend.viewChanged.emit(); QTest.qWait(30)
        self.assertEqual(count.property('text'), '1 个房间')
        self.open_nodes()
        self.click('back-hall')
        self.assertEqual(find_item(self.window, 'rooms-list').property('count'), 1)

    def test_create_and_join_have_return_navigation_without_hall_controls(self):
        for entry, page in (('open-create', 'create'), ('open-join', 'join')):
            self.click(entry)
            self.assertEqual(self.backend.view['page'], page)
            for name in ('navigation-tabs', 'room-search', 'open-friends-window'):
                self.assert_absent_or_hidden(name)
            self.assertTrue(find_item(self.window, 'back-hall').isVisible())
            back = find_item(self.window, 'back-hall')
            title = find_item(self.window, 'window-page-title')
            self.assertEqual(title.property('text'), '创建房间' if page == 'create' else '加入房间')
            self.assertGreater(title.mapToScene(QPointF(0, 0)).x(),
                               back.mapToScene(QPointF(back.width(), 0)).x())
            self.assertLess(abs(title.mapToScene(QPointF(0, title.height() / 2)).y()
                                - back.mapToScene(QPointF(0, back.height() / 2)).y()), 1)
            stack, headings = [self.window.rootObject()], []
            while stack:
                item = stack.pop()
                if item.inherits('QQuickAbstractButton'):
                    continue
                if item.isVisible() and item.property('text') == title.property('text'):
                    headings.append(item)
                stack.extend(item.childItems())
            self.assertEqual(headings, [title], 'Page title must appear once, next to the return action')
            self.assertGreaterEqual(back.mapToScene(QPointF(0, 0)).y(), 2)
            self.assertLessEqual(back.mapToScene(QPointF(0, back.height())).y(), 44)
            self.click('back-hall')
            self.assertEqual(self.backend.view['page'], 'hall')
            self.assertFalse(find_item(self.window, 'back-hall').isVisible())

    def test_join_has_a_separate_footer_for_submit_and_cancel(self):
        self.click('open-join')
        invite = find_item(self.window, 'join-invite')
        submit = find_item(self.window, 'join-confirm')
        cancel = find_item(self.window, 'cancel-join')
        self.assertGreater(submit.mapToScene(QPointF(0, 0)).y(),
                           invite.mapToScene(QPointF(0, invite.height())).y())
        self.assertGreater(submit.mapToScene(QPointF(0, 0)).x(),
                           cancel.mapToScene(QPointF(cancel.width(), 0)).x())
        self.assertGreaterEqual(submit.mapToScene(QPointF(0, 0)).y(), 450)
        self.assertFalse(submit.isEnabled())
        self.click('cancel-join')
        self.assertEqual(self.backend.view['page'], 'hall')

    def test_return_arrow_is_centered_in_title_bar_and_not_a_font_glyph(self):
        self.click('open-create')
        arrow = find_item(self.window, 'header-back-arrow')
        button = find_item(self.window, 'back-hall')
        self.assertTrue(button.property('backArrow'))
        point = arrow.mapToItem(button, QPointF(arrow.width() / 2, arrow.height() / 2))
        self.assertAlmostEqual(point.x(), button.width() / 2, delta=.5)
        self.assertAlmostEqual(point.y(), button.height() / 2, delta=.5)
        header = find_item(self.window, 'window-header')
        center = arrow.mapToItem(header, QPointF(arrow.width() / 2, arrow.height() / 2))
        self.assertAlmostEqual(center.y(), header.height() / 2, delta=.5)

    def test_room_requirements_and_mod_list_open_without_crowding_chat(self):
        self.backend._view = {**self.backend._view, 'page': 'connected', 'selected': 'mine',
            'connections': [dict(id='mine', title='Modded world', role='client', state='online',
                availability='ready', game=dict(version='1.20.1', loader='forge', loader_version='47.3.0',
                    mods_count=2), compatibility='模组集合不一致', mods=[])],
            'chatState':'在线', 'chatMessages':[], 'chatDraft':'', 'chatError':'',
            'chatSending':False, 'bridgeStatus':'游戏聊天已同步'}
        self.backend.viewChanged.emit()
        QTest.qWait(50)
        self.assertIn('1.20.1', find_item(self.window, 'room-version-summary').property('text'))
        self.assertGreaterEqual(find_item(self.window, 'room-chat').height(), 145)
        self.click('show-room-mods')
        self.assertEqual(self.backend.actions[-1], ('loadMods', {}))
        self.assertTrue(find_item(self.window, 'room-mods-body').isVisible())

    def test_top_level_title_bar_identifies_current_page_and_does_not_overlap_window_controls(self):
        for page, expected in (('hall', 'Buggcraft · 联机大厅'), ('nodes', '联机节点')):
            if page == 'nodes':
                self.open_nodes()
            title = find_item(self.window, 'window-page-title')
            self.assertTrue(title.isVisible())
            self.assertEqual(title.property('text'), expected)
            self.assertEqual(find_item(self.window, 'back-hall').isVisible(), page == 'nodes')
            self.assertFalse(title.property('truncated'))
            self.assertLessEqual(title.mapToScene(QPointF(title.width(), 0)).x(),
                                 find_item(self.window, 'minimize-window').mapToScene(QPointF(0, 0)).x())

    def test_room_displays_members_game_players_and_game_ping_separately(self):
        self.backend._view = {**self.backend._view, 'page':'connected', 'selected':'mine',
            'connections':[dict(id='mine', title='World', role='client', state='online',
                availability='ready', members=4, capacity=10, game_players=2, latency_ms=57)],
            'chatState':'在线', 'chatMessages':[], 'chatDraft':'', 'chatError':'',
            'chatSending':False, 'bridgeStatus':'游戏聊天已同步'}
        self.backend.viewChanged.emit()
        QTest.qWait(40)
        for name, expected in [('room-member-count','房间内 4 / 10 人'),
                ('game-player-count','游戏内 2 人'), ('game-latency','游戏延迟 57 ms')]:
            item = find_item(self.window, name)
            self.assertTrue(item.isVisible())
            self.assertEqual(item.property('text'), expected)
        self.assertGreaterEqual(find_item(self.window, 'room-chat').height(),145)
        self.assert_absent_or_hidden('node-picker')

    def test_room_exit_is_in_title_bar_and_waiting_guidance_keeps_chat(self):
        for role in ('host', 'client'):
            with self.subTest(role=role):
                self.backend._view = {**self.backend._view, 'page':'connected', 'selected':'mine',
                    'connections':[dict(id='mine', title='World', role=role, state='online', availability='waiting')],
                    'chatState':'在线', 'chatMessages':[], 'chatDraft':'', 'chatError':'',
                    'chatSending':False, 'bridgeStatus':'等待世界恢复'}
                self.backend.viewChanged.emit()
                QTest.qWait(40)
                exit_button = find_item(self.window, 'back-hall')
                self.assertTrue(exit_button.property('backArrow'))
                self.assertLess(exit_button.mapToScene(QPointF(0, exit_button.height())).y(), 44)
                self.assertTrue(find_item(self.window, 'room-chat').isVisible())
                self.assertIn('世界暂未开放' if role == 'host' else '房主不在游戏内',
                              find_item(self.window, 'connection-heading').property('text'))
                if role == 'client':
                    self.assertFalse(find_item(self.window, 'copy-address').isEnabled())
                else:
                    self.click('reopen-world')
                    self.assertEqual(self.backend.actions[-1][0], 'reopenWorld')
                self.click('back-hall')
                self.assertTrue(find_item(self.window, 'confirm-leave-room').isVisible())
                self.assertFalse(any(action == 'stop' for action, _ in self.backend.actions))
                self.click('cancel-leave-room')
                self.assertEqual(self.backend.view['page'], 'connected')
                self.click('back-hall')
                self.click('confirm-leave-room')
                self.assertEqual(self.backend.actions[-1], ('stop', {'id':'mine'}))
                self.backend.actions.clear()

    def test_resume_world_page_has_working_selection_and_return(self):
        self.backend._view = {**self.backend._view, 'page':'worldPicker',
            'selected':'mine', 'worlds':[dict(port=51234, version='1.21.8')],
            'connections':[dict(id='mine', role='host', state='online')]}
        self.backend.viewChanged.emit()
        QTest.qWait(60)
        self.assert_absent_or_hidden('navigation-tabs')
        self.click('resume-world-0')
        self.assertEqual(self.backend.actions[-1], ('applyWorld', {'port':51234}))
        self.click('rediscover-worlds')
        self.assertEqual(self.backend.actions[-1][0], 'discover')
        self.click('back-hall')
        self.assertEqual(self.backend.view['page'], 'connected')

    def test_floating_friends_drags_without_opening_and_stays_within_window(self):
        button = find_item(self.window, 'open-friends-window')
        start = button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint()
        self.assertGreater(start.x(), self.window.width() - 100)
        self.assertGreater(start.y(), self.window.height() - 100)
        before = len(self.backend.actions)
        QTest.mousePress(self.window, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(self.window, start - QPointF(30, 30).toPoint(), 25)
        QTest.mouseMove(self.window, start - QPointF(140, 90).toPoint(), 25)
        QTest.mouseRelease(self.window, Qt.LeftButton, Qt.NoModifier, start - QPointF(140, 90).toPoint())
        QTest.qWait(30)
        self.assertLess(button.x(), 600)
        self.assertEqual(len(self.backend.actions), before, 'Dragging must not open the friends window')
        self.assertGreaterEqual(button.x(), 14)
        self.assertGreaterEqual(button.y(), 100)
        start = button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint()
        QTest.mousePress(self.window, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(self.window, start - QPointF(25, 25).toPoint(), 25)
        QTest.mouseMove(self.window, QPointF(-100, -100).toPoint(), 25)
        QTest.mouseRelease(self.window, Qt.LeftButton, Qt.NoModifier, QPointF(-100, -100).toPoint())
        QTest.qWait(30)
        self.assertGreaterEqual(button.x(), button.property('minimumX'))
        self.assertGreaterEqual(button.y(), button.property('minimumY'))
        self.assertEqual(len(self.backend.actions), before)
        self.click('open-friends-window')
        self.assertEqual(self.backend.actions[-1], ('openFriends', {}))
        before = len(self.backend.actions)
        QTest.keyClick(self.window, Qt.Key_Space)
        self.assertEqual(len(self.backend.actions), before + 1, 'Keyboard must open the floating entry too')

    def test_floating_friends_stays_above_feedback_after_dragging(self):
        button = find_item(self.window, 'open-friends-window')
        start = button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint()
        # Dragging removes the initial position binding; later notices must still
        # keep the button clear of feedback and its dismiss action.
        QTest.mousePress(self.window, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(self.window, start - QPointF(25, 0).toPoint(), 25)
        QTest.mouseMove(self.window, start - QPointF(50, 0).toPoint(), 25)
        QTest.mouseRelease(self.window, Qt.LeftButton, Qt.NoModifier, start - QPointF(50, 0).toPoint())
        self.backend._view = {**self.backend._view, 'notice': 'Connected'}
        self.backend.viewChanged.emit()
        QTest.qWait(60)
        feedback = find_item(self.window, 'feedback')
        self.assertTrue(feedback.isVisible())
        self.assertLess(button.mapToScene(QPointF(0, button.height())).y(),
                        feedback.mapToScene(QPointF(0, 0)).y())
        self.assertLessEqual(button.y(), button.property('maximumY'))

    def test_floating_friends_initial_feedback_keeps_default_near_bottom_right(self):
        self.backend._view = {**self.backend._view, 'notice': 'Node added'}
        self.window.setSource(QUrl())
        self.window.setSource(QUrl.fromLocalFile(str(ROOT / 'resources/qml/multiplayer/Lobby.qml')))
        QTest.qWait(80)
        button = find_item(self.window, 'open-friends-window')
        self.assertGreater(button.y(), self.window.height() - 150)
        self.assertGreater(button.x(), self.window.width() - 100)
        self.assertLess(button.y() + button.height(),
                        find_item(self.window, 'feedback').mapToScene(QPointF(0, 0)).y())


class FriendWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        class Store:
            def __init__(self):
                self.data = {'contacts': [{'name':'Friend', 'invite':'bugg1-' + 'A' * 43,
                                           'node':'node', 'account':'a' * 32 + '.' + 'b' * 32}]}

        class Backend(QObject):
            changed = Signal()
            friend_finished = Signal(bool, str)
            def __init__(self, window):
                super().__init__()
                self.window = window
                self.store = Store()
                self._view = {'page':'hall', 'contacts':[], 'error':'', 'notice':'',
                              'friendName':'', 'editIndex':-1, 'nodes':[], 'connections':[],
                              'nodeIndex':0, 'nodeAvailable':True, 'busy':False, 'friendBusy':False,
                              'socialReady':True, 'socialName':'local_user', 'socialError':'',
                              'friendRequests':[], 'friendInvitations':[]}
                self.actions = []
            @Property('QVariantMap', notify=changed)
            def view(self):
                self._view['contacts'] = [{'name': c['name'], 'node':'Test node',
                                           'account':c.get('account', ''),
                                           'online':True, 'index': i}
                                          for i, c in enumerate(self.store.data['contacts'])]
                self._view['nodes'] = [{'title':'Test node', 'path':'node',
                                        'personalCode':getattr(self, 'personal_code', False)}]
                return self._view
            def lookup_friend(self, data):
                self._view['friendBusy'] = True
                self.pending_lookup = dict(data)
                self.changed.emit()
                QTimer.singleShot(1, self.complete_lookup)
            def complete_lookup(self):
                data = self.pending_lookup
                self.pending_lookup = None
                identifier = data['identifier']
                self._view['friendRequests'].append({'username':identifier, 'incoming':False,
                    'id':'1' * 32, 'account':'c' * 32 + '.' + 'd' * 32})
                self._view['friendBusy'] = False
                self.changed.emit()
                self.friend_finished.emit(True, '好友申请已发送，请等待对方同意。')
            def cancel_friend_lookup(self):
                self.pending_lookup = None
                self._view['friendBusy'] = False
                self.changed.emit()
            def remove_friend(self, index, navigate=True):
                self.store.data['contacts'].pop(index)
                self.changed.emit()
            def act(self, action, data):
                self.actions.append((action, dict(data)))

        self.owner = QDialog()
        self.owner.show()
        self.owner.backend = Backend(self.owner)
        from ui.dialog.FriendsDialog import FriendsDialog
        self.dialog = FriendsDialog(self.owner, ROOT / 'resources')
        self.dialog.show()
        QTest.qWait(60)
        self.addCleanup(self.dialog.close)
        self.addCleanup(self.owner.close)

    def click(self, name):
        item = find_item(self.dialog.quick, name)
        point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
        QTest.mouseClick(self.dialog.quick, Qt.LeftButton, Qt.NoModifier, point)
        QTest.qWait(40)

    def test_friends_window_is_separate_and_can_close_independently(self):
        self.assertTrue(self.owner.isVisible())
        self.assertEqual(self.dialog.windowModality(), Qt.NonModal)
        self.assertGreaterEqual(self.dialog.width(), 400)
        for name, label in (('invite-friend-0', '邀请'),):
            button = find_item(self.dialog.quick, name)
            self.assertGreaterEqual(button.width(), 58)
            text = next(child for child in button.childItems()
                        if isinstance(child, QQuickItem) and child.property('text') == label)
            self.assertFalse(text.property('truncated'), name + ' label is truncated')
        # An online friend can be invited before a room exists; the backend
        # guides creation and sends the pending invite afterwards.
        self.assertTrue(find_item(self.dialog.quick, 'invite-friend-0').isEnabled())
        self.owner.backend._view['connections'] = [{'role':'host','state':'online'}]
        self.owner.backend.changed.emit()
        QTest.qWait(30)
        self.click('invite-friend-0')
        self.assertEqual(self.owner.backend.actions[-1], ('inviteFriend', {'account':'a' * 32 + '.' + 'b' * 32}))
        self.assertTrue(self.owner.isVisible())
        self.click('close-friends')
        self.assertFalse(self.dialog.isVisible())
        self.assertTrue(self.owner.isVisible())

    def test_add_friend_form_sends_pending_request_through_backend(self):
        self.click('add-friend')
        find_item(self.dialog.quick, 'friend-identifier').setProperty('text', 'New')
        self.click('save-friend')
        QTest.qWait(40)
        self.assertEqual([c['name'] for c in self.owner.backend.store.data['contacts']], ['Friend'])
        self.assertEqual(self.owner.backend.view['friendRequests'][0]['username'], 'New')

    def test_friend_access_mode_distinguishes_saved_code_from_verified_connection(self):
        label = find_item(self.dialog.quick, 'friend-access-mode')
        backend = self.owner.backend
        backend._view['socialReady'] = False
        backend.changed.emit()
        QTest.qWait(30)
        self.assertIn('匿名接入', label.property('text'))
        self.assertFalse(find_item(self.dialog.quick, 'add-friend').isVisible())
        backend.personal_code = True
        backend._view['nodeAvailable'] = False
        backend.changed.emit()
        QTest.qWait(40)
        self.assertIn('匿名接入', label.property('text'))
        backend._view['nodeAvailable'] = True
        backend._view['socialReady'] = True
        backend.changed.emit()
        QTest.qWait(40)
        self.assertEqual(label.property('text'), 'local_user')
        self.assertTrue(find_item(self.dialog.quick, 'add-friend').isVisible())

    def test_incoming_invitation_has_visible_entry_join_action_and_expires(self):
        backend = self.owner.backend
        invitation = {'id':'1' * 32, 'account':'c' * 32 + '.' + 'd' * 32,
                      'username':'Guest', 'room':'2' * 32}
        backend._view['friendInvitations'] = [invitation]
        backend.changed.emit()
        QTest.qWait(40)
        self.assertTrue(find_item(self.dialog.quick, 'friend-invite-banner').isVisible())
        self.click('show-friend-invites')
        self.assertTrue(find_item(self.dialog.quick, 'join-friend-invite').isVisible())
        self.click('join-friend-invite')
        self.assertEqual(backend.actions[-1], ('joinFriend', {
            'account': invitation['account'], 'id': invitation['id']}))
        backend.actions.clear()
        backend._view['friendInvitations'] = []
        backend.changed.emit()
        QTest.qWait(40)
        self.assertFalse(find_item(self.dialog.quick, 'friend-invite-banner').isVisible())
        with self.assertRaisesRegex(AssertionError, 'QML item not found'):
            find_item(self.dialog.quick, 'join-friend-invite')

    def test_friend_form_returns_from_title_bar_without_saving(self):
        self.assertFalse(find_item(self.dialog.quick, 'back-friends').isVisible())
        self.assertEqual(find_item(self.dialog.quick, 'window-page-title').property('text'), '我的好友')
        self.click('add-friend')
        self.assertEqual(find_item(self.dialog.quick, 'window-page-title').property('text'), '添加好友')
        back = find_item(self.dialog.quick, 'back-friends')
        self.assertTrue(back.isVisible())
        self.assertLessEqual(back.mapToScene(QPointF(0, back.height())).y(), 44)
        find_item(self.dialog.quick, 'friend-identifier').setProperty('text', 'Unsaved')
        self.click('back-friends')
        self.assertFalse(find_item(self.dialog.quick, 'back-friends').isVisible())
        self.assertEqual(find_item(self.dialog.quick, 'window-page-title').property('text'), '我的好友')
        self.assertEqual(len(self.owner.backend.store.data['contacts']), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
