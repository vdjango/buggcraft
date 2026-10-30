"""Load the shipped QML hall to check hierarchy, compact sizing and tab navigation."""
import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src' / 'buggcraft'))
from PySide6.QtCore import Property, QObject, QPointF, Qt, Signal, Slot, QUrl, QTimer, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtQuick import QQuickView, QQuickItem
from PySide6.QtQuickWidgets import QQuickWidget
from _qml_test_support import qt_mouse_click, qt_mouse_drag


class LobbyBackend(QObject):
    viewChanged = Signal()
    copied = Signal(str)
    roomSettingsSaved = Signal()

    def __init__(self):
        super().__init__()
        self._view = {
            'page': 'hall', 'rooms': [
                {'id': 'one', 'title': 'Room one', 'node_name': '宿迁节点', 'node_region': '中国·江苏宿迁',
                 'game': {'version': '1.21.8', 'loader': 'vanilla'}, 'connections': 1},
                {'id': 'two', 'title': 'Room two', 'game': {'version': '1.20.1', 'loader': 'fabric'}, 'connections': 4},
            ], 'loading': False, 'roomError': '', 'busy': False, 'nodeIndex': 0,
            'nodes': [{'title': 'Local relay'}], 'nodeAvailable':True, 'selected': '', 'connections': [],
            'editIndex': -1, 'error': '', 'notice': '',
            'contacts': [{'index': 0, 'name': 'Friend', 'invite': 'secret'}],
            'socialReady': True, 'friendEntryAvailable': True, 'socialName': 'local_user', 'socialError': '',
            'friendRequests': [], 'friendInvitations': [],
            'step':0, 'worlds':[], 'worldScanning':False, 'instances':[], 'instanceId':'', 'instanceLoading':False,
            'instanceError':'', 'instanceLocked':False, 'version':'', 'loader':'vanilla',
            'loaderVersion':'', 'needsVersion':False,
            'nodeDraft':'', 'joinRoomId':'', 'joinRoomTitle':'',
            'invitePrompt':False, 'roomQuery':'', 'roomNext':None, 'roomTotal':None, 'loadingMore':False,
            'transportPolicy':'auto',
            'nodeUpdatePrompt':False, 'nodeUpdateMessage':'',
            'deviceOrigin':'https://node.bugg.icu', 'deviceLoginBusy':False,
            'deviceLoginStage':'idle', 'deviceLoginMessage':'', 'deviceLoginUrl':'',
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
        elif name == 'deviceOrigin':
            self._view = {**self._view, 'deviceOrigin': values['text']}
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
        elif name == 'dismissPublicGuide':
            for record in self._view['connections']:
                if record['id'] == self._view['selected']:
                    record['publicGuide'] = False
            self.viewChanged.emit()


def find_item(root, object_name):
    stack = [root.contentItem() if hasattr(root, 'contentItem') else root.rootObject()]
    if isinstance(root, QQuickWidget):
        stack.append(root.quickWindow().contentItem())
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
        self.addCleanup(self.dispose_window)

    def dispose_window(self):
        self.window.close()
        self.window.setSource(QUrl())
        self.window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)

    def click(self, object_name):
        item = find_item(self.window, object_name)
        ancestor = item.parentItem()
        while ancestor:
            if ancestor.inherits('QQuickFlickable'):
                position = item.mapToItem(ancestor, QPointF())
                if position.y() < 0 or position.y() + item.height() > ancestor.height():
                    offset = ancestor.property('contentY') + position.y() - ancestor.height() / 2
                    ancestor.setProperty('contentY', max(0, min(offset,
                        ancestor.property('contentHeight') - ancestor.height())))
                    QTest.qWait(20)
                break
            ancestor = ancestor.parentItem()
        point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
        qt_mouse_click(self.window, point)
        QTest.qWait(30)
        return item

    def assert_absent_or_hidden(self, name):
        try:
            item = find_item(self.window, name)
        except AssertionError:
            return
        self.assertFalse(item.isVisible(), name)

    def snapshot(self, name):
        folder = os.environ.get('BUGGCRAFT_QML_SNAPSHOTS')
        if folder:
            target = Path(folder)
            target.mkdir(parents=True, exist_ok=True)
            self.assertTrue(self.window.grabWindow().save(str(target / (name + '.png'))))

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
        for name in ('node-advanced', 'node-code', 'add-node-code', 'import-node', 'export-node'):
            self.assert_absent_or_hidden(name)
        for name in ('nodes-list', 'node-web-address', 'remember-device-login', 'login-official-device', 'nodes-done'):
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

    def test_empty_node_entry_and_address_survive_secondary_page_navigation(self):
        self.backend._view = {**self.backend._view, 'nodes':[], 'nodeIndex':-1, 'rooms':[]}
        self.backend.viewChanged.emit(); QTest.qWait(30)
        self.click('empty-add-node')
        self.assertEqual(self.backend.view['page'], 'nodes')
        self.click('node-web-address')
        QTest.keyClick(self.window, Qt.Key_A, Qt.ControlModifier)
        QApplication.clipboard().setText('community.example:18443')
        QTest.keyClick(self.window, Qt.Key_V, Qt.ControlModifier); QTest.qWait(30)
        self.assertEqual(self.backend.view['deviceOrigin'], 'community.example:18443')
        self.assertTrue(find_item(self.window, 'login-official-device').isEnabled())
        self.click('back-hall'); self.open_nodes()
        self.assertEqual(find_item(self.window, 'node-web-address').property('text'), 'community.example:18443')

    def test_remove_node_requires_a_second_click(self):
        self.open_nodes(); self.click('remove-node')
        self.assertNotEqual(self.backend.actions[-1][0], 'removeNode')
        self.click('remove-node')
        self.assertEqual(self.backend.actions[-1], ('removeNode', {}))

    def test_node_management_keeps_actions_visible_with_busy_and_error_feedback(self):
        self.open_nodes()
        self.backend._view = {**self.backend._view, 'busy':True,
            'deviceLoginMessage':'正在连接节点并准备登录页面…'}
        self.backend.viewChanged.emit(); QTest.qWait(40)
        self.assertFalse(find_item(self.window, 'login-official-device').isEnabled())
        self.assertFalse(find_item(self.window, 'node-web-address').isEnabled())
        self.backend._view = {**self.backend._view, 'busy':False, 'notice':'',
            'error':'无法发起网页登录：节点代理拒绝了启动器请求（HTTP 403）。'}
        self.backend.viewChanged.emit(); QTest.qWait(40)
        self.assertTrue(find_item(self.window, 'login-official-device').isEnabled())
        self.assertEqual(find_item(self.window, 'node-login-status').property('text'), self.backend.view['error'])
        feedback = find_item(self.window, 'feedback')
        self.assertFalse(feedback.isVisible())
        self.assertTrue(find_item(self.window, 'node-login-status').isVisible())
        for name in ('node-web-address', 'login-official-device', 'nodes-done'):
            item = find_item(self.window, name)
            bottom = item.mapToScene(QPointF(0, item.height())).y()
            self.assertLessEqual(bottom, 491, name)

    def test_remember_device_label_is_readable_and_checkbox_can_be_toggled(self):
        self.open_nodes()
        label = find_item(self.window, 'remember-device-label')
        self.assertEqual(label.property('text'), '保持登录')
        self.assertEqual(label.property('color').name(), '#f0e8ff')
        self.assertGreaterEqual(label.property('font').pixelSize(), 13)
        self.assertTrue(find_item(self.window, 'remember-device-login').property('checked'))
        self.click('remember-device-login')
        self.assertFalse(find_item(self.window, 'remember-device-login').property('checked'))

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

    def test_room_list_shows_assigned_node_and_region(self):
        location = find_item(self.window, 'room-node-location-0')
        self.assertEqual(location.property('text'), '宿迁节点 · 中国·江苏宿迁')

    def test_room_latency_is_visible_and_distinguishes_unavailable_from_zero(self):
        for value, available, expected in [(57.4, True, '到大厅节点 57 ms'),
                                            (0, True, '到大厅节点 0 ms'),
                                            (None, True, '到大厅节点 —'),
                                            (57, False, '到大厅节点 —')]:
            self.backend._view = {**self.backend._view, 'nodeLatencyMs': value,
                                  'nodeAvailable': available}
            self.backend.viewChanged.emit()
            QTest.qWait(30)
            self.assertEqual(find_item(self.window, 'hall-node-latency').property('text'), expected)
            for index in range(2):
                latency = find_item(self.window, 'room-latency-' + str(index))
                self.assertTrue(latency.isVisible())
                self.assertEqual(latency.property('text'), '加入后测量')
                join = find_item(self.window, 'join-public-' + str(index))
                self.assertLess(latency.mapToScene(QPointF(latency.width(), 0)).x(),
                                join.mapToScene(QPointF(0, 0)).x())
                self.assertLessEqual(join.mapToScene(QPointF(join.width(), 0)).x(),
                                     self.window.width())

    def test_hall_host_latency_comes_from_own_game_path_not_directory_or_host_advertisement(self):
        self.backend._view.update(nodeLatencyMs=999, connections=[dict(id='joined', roomId='one',
            role='client', state='online', latency_ms=42)])
        self.backend.viewChanged.emit()
        QTest.qWait(40)
        self.assertEqual(find_item(self.window, 'room-latency-0').property('text'), '到房主 42 ms')
        self.assertEqual(find_item(self.window, 'room-latency-1').property('text'), '加入后测量')
        self.backend._view['connections'][0]['latency_ms'] = None
        self.backend.viewChanged.emit()
        QTest.qWait(30)
        self.assertEqual(find_item(self.window, 'room-latency-0').property('text'), '到房主 —')

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
        self.assertIn(('navigate', {'page': 'create'}), self.backend.actions)
        self.assertFalse(any(action == 'discover' for action, _ in self.backend.actions))
        self.click('create-mode-world')
        self.assertEqual(self.backend.actions[-1], ('discover', {}))

    def test_open_lan_world_prompt_is_chinese_and_offers_one_clear_action(self):
        self.backend._view = {**self.backend._view, 'openWorldPrompt':True, 'openWorldPort':51234}
        self.backend.viewChanged.emit()
        QTest.qWait(40)
        popup = self.window.rootObject().findChild(QObject, 'open-world-create-room-dialog')
        self.assertIsNotNone(popup)
        self.assertTrue(popup.property('visible'))
        for name in ('create-room-for-open-world', 'dismiss-open-world-prompt'):
            self.assertIsNotNone(self.window.rootObject().findChild(QObject, name))

    def test_single_create_action_stays_visible_and_handles_world_not_open_yet(self):
        self.backend._view.update(version='1.21.8', instances=['1.21.8'], instanceId='1.21.8')
        self.click('open-create')
        action = find_item(self.window, 'create-next')
        self.assertTrue(action.isEnabled())
        self.assertEqual(action.property('text'), '先创建房间')
        self.assertFalse(find_item(self.window, 'create-game-chat').isVisible())
        self.assertFalse(find_item(self.window, 'create-transport').isVisible())
        self.snapshot('create-preparation-room')
        self.click('create-next')
        self.assertEqual(self.backend.actions[-1][0], 'quickCreate')
        self.assertEqual(self.backend.actions[-1][1]['port'], 0)
        self.assertTrue(self.backend.actions[-1][1]['requireInvite'])
        self.assertFalse(find_item(self.window, 'create-world-discovery').isVisible())
        self.assertFalse(any(action == 'discover' for action, _ in self.backend.actions))
        for values in ({'busy':True},
                       {'busy':False, 'instanceLoading':True}, {'instanceLoading':False, 'version':''}):
            self.backend._view.update(values)
            self.backend.viewChanged.emit()
            QTest.qWait(30)
            self.assertFalse(action.isEnabled())
            self.assertTrue(find_item(self.window, 'cancel-create').isEnabled())
        bottom = action.mapToScene(QPointF(action.width(), action.height()))
        self.assertLessEqual(bottom.y(), self.window.height() - 14)

    def test_empty_room_state_is_visible_without_public_rooms(self):
        self.backend._view = {**self.backend._view, 'rooms': []}
        self.backend.viewChanged.emit()
        QTest.qWait(60)
        self.assertTrue(find_item(self.window, 'rooms-empty').isVisible())

    def test_waiting_world_allows_client_installation_but_never_connects_early(self):
        record = dict(id='room', role='client', state='online', availability='waiting',
            title='Waiting room', compatibility='模组集合不一致', game=dict(version='1.21.8', mods_count=2))
        self.backend._view.update(page='connected', selected='room', connections=[record])
        self.backend.viewChanged.emit()
        QTest.qWait(50)
        self.assertEqual(self.backend._view['page'], 'connected')
        self.assertFalse(self.window.rootObject().findChild(QObject, 'leave-room-dialog').property('visible'))
        self.assertEqual(find_item(self.window, 'room-quick-launch').property('text'), '同步安装')
        self.assertTrue(find_item(self.window, 'room-quick-launch').isEnabled())
        self.click('room-quick-launch')
        self.assertTrue(self.window.rootObject().findChild(QObject, 'prepare-room-dialog').property('visible'))
        self.click('confirm-room-install')
        self.assertEqual(self.backend.actions[-1], ('prepareRoom', {'mode': 'fresh'}))
        record['compatibility'] = ''
        self.backend.viewChanged.emit()
        QTest.qWait(40)
        self.assertEqual(find_item(self.window, 'room-quick-launch').property('text'), '启动到主菜单')
        self.assertTrue(find_item(self.window, 'room-quick-launch').isEnabled())
        self.click('room-quick-launch')
        self.assertEqual(self.backend.actions[-1], ('launchRoom', {}))

    def test_preparation_mode_ignores_discovered_worlds_until_explicitly_selected(self):
        self.backend._view.update(version='1.21.8', instances=['1.21.8'], instanceId='1.21.8',
            worlds=[dict(version='1.21.8', port=51001), dict(version='1.21.8', port=51002)])
        self.click('open-create')
        self.assertTrue(find_item(self.window, 'create-next').isEnabled())
        self.click('create-next')
        self.assertEqual(self.backend.actions[-1][1]['port'], 0)
        self.click('create-mode-world')
        self.assertTrue(find_item(self.window, 'create-world-discovery').isVisible())
        self.assertFalse(find_item(self.window, 'create-next').isEnabled())
        self.click('world-1')
        self.click('create-next')
        self.assertEqual(self.backend.actions[-1][1]['port'], '51002')
        self.click('create-mode-prepare')
        self.assertFalse(find_item(self.window, 'create-world-discovery').isVisible())
        self.click('create-next')
        self.assertEqual(self.backend.actions[-1][1]['port'], 0)

    def test_open_world_entry_keeps_explicit_world_selection(self):
        self.backend._view.update(version='1.21.8', pendingOpenWorldPort=51001,
            worlds=[dict(version='1.21.8', port=51001)])
        self.click('open-create')
        self.assertTrue(find_item(self.window, 'create-world-discovery').isVisible())
        self.assertTrue(find_item(self.window, 'world-0').property('selected'))
        self.click('create-next')
        self.assertEqual(self.backend.actions[-1][1]['port'], '51001')
        self.click('create-mode-prepare')
        self.backend._view.update(notice='Another room event')
        self.backend.viewChanged.emit()
        QTest.qWait(30)
        self.assertFalse(find_item(self.window, 'create-world-discovery').isVisible())
        self.click('create-next')
        self.assertEqual(self.backend.actions[-1][1]['port'], 0)

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

    def test_world_scan_has_visible_activity_and_clears_when_finished(self):
        self.click('open-create')
        self.click('create-mode-world')
        self.backend._view = {**self.backend._view, 'busy':True, 'worldScanning':True}
        self.backend.viewChanged.emit()
        QTest.qWait(40)
        banner = find_item(self.window, 'create-world-scanning')
        self.assertTrue(banner.isVisible())
        self.assertGreater(banner.height(), 65)
        self.assertTrue(find_item(self.window, 'create-world-scan-spinner').property('running'))
        self.assertFalse(find_item(self.window, 'create-worlds-empty').isVisible())
        self.assertFalse(find_item(self.window, 'discover-worlds').isEnabled())
        self.assertTrue(find_item(self.window, 'cancel-create').isEnabled())
        folder = os.environ.get('BUGGCRAFT_QML_SNAPSHOTS')
        if folder:
            target = Path(folder)
            target.mkdir(parents=True, exist_ok=True)
            self.window.grabWindow().save(str(target / 'create-world-scanning.png'))
        self.backend._view = {**self.backend._view, 'busy':False, 'worldScanning':False}
        self.backend.viewChanged.emit()
        QTest.qWait(40)
        self.assertFalse(banner.isVisible())
        self.assertTrue(find_item(self.window, 'create-worlds-empty').isVisible())

    def test_world_discovery_separates_game_config_list_and_manual_port(self):
        self.backend._view = {**self.backend._view, 'version':'1.21.8',
            'instances':['1.21.8'], 'instanceId':'1.21.8'}
        self.click('open-create')
        config = find_item(self.window, 'create-game-config')
        self.click('create-mode-world')
        discovery = find_item(self.window, 'create-world-discovery')
        self.assertLess(config.mapToScene(QPointF(0, config.height())).y(), discovery.mapToScene(QPointF()).y())
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
        self.snapshot('create-linked-world')
        self.click('create-next')
        self.assertEqual(self.backend.actions[-1][0], 'quickCreate')
        self.assertEqual(self.backend.actions[-1][1]['port'], '51002')
        self.click('create-advanced')
        self.click('show-manual')
        self.assertTrue(find_item(self.window, 'create-port').isVisible())
        self.assertTrue(find_item(self.window, 'create-next').isVisible())

    def test_chat_sync_opt_in_discloses_virtual_player_and_validates_name(self):
        self.backend._view = {**self.backend._view, 'step':1, 'version':'1.21.8'}
        self.click('open-create')
        self.click('create-advanced')
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
        self.assertEqual(self.backend.actions[-1], ('quickCreate', {
            'port':0, 'title':'玩家的房间', 'public':False, 'requireInvite':True, 'gameChatEnabled':True,
            'gameChatName':'LobbyBridge', 'transport':'auto'}))
        self.backend._view = {**self.backend._view, 'step':0}
        self.backend.viewChanged.emit()
        QTest.qWait(25)
        self.backend._view = {**self.backend._view, 'step':1, 'version':'1.21.8'}
        self.backend.viewChanged.emit()
        QTest.qWait(25)
        self.assertTrue(enabled.property('checked'))
        self.assertEqual(name.property('text'), 'LobbyBridge')

    def test_public_room_invite_policy_and_private_room_access(self):
        self.backend._view = {**self.backend._view, 'step':1, 'version':'1.21.8'}
        self.click('open-create')
        self.click('create-advanced')
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
        self.click('create-advanced')
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

    def test_hall_shows_preparation_and_open_worlds_with_same_join_policies(self):
        for required in (False, True):
            with self.subTest(require_invite=required):
                self.backend._view.update(rooms=[
                    dict(id='preparing', title='一起下载客户端', availability='waiting',
                         require_invite=required, members=3, capacity=4,
                         game=dict(version='1.21.8', loader='vanilla')),
                    dict(id='playing', title='世界已开放的房间', availability='ready',
                         require_invite=required, members=2, capacity=4,
                         game=dict(version='1.20.1', loader='fabric'))])
                self.backend.viewChanged.emit(); QTest.qWait(40)
                for index, state in enumerate(('准备中', '世界已开放')):
                    status = find_item(self.window, 'room-availability-' + str(index))
                    self.assertTrue(status.isVisible())
                    self.assertEqual(status.property('text'), state)
                    self.assertEqual(find_item(self.window, 'room-access-' + str(index)).property('text'),
                                     '需要邀请码' if required else '直接加入')
                    self.assertTrue(find_item(self.window, 'join-public-' + str(index)).isEnabled())
                    self.click('join-public-' + str(index))
                    self.assertEqual(self.backend.actions[-1],
                                     ('joinPublic', {'id': 'preparing' if index == 0 else 'playing'}))
                self.snapshot('hall-waiting-ready-' + ('invite' if required else 'direct'))

    def test_hall_world_state_changes_without_losing_room_or_join_action(self):
        room = dict(id='same-room', title='一起准备再进入世界', availability='waiting',
                    require_invite=False, game=dict(version='1.21.8', loader='vanilla'))
        for state, label in (('waiting', '准备中'), ('ready', '世界已开放'),
                             ('waiting', '准备中'), (None, '状态未知')):
            with self.subTest(availability=state):
                self.backend._view.update(rooms=[dict(room, availability=state)])
                self.backend.viewChanged.emit(); QTest.qWait(40)
                self.assertEqual(find_item(self.window, 'room-availability-0').property('text'), label)
                self.click('join-public-0')
                self.assertEqual(self.backend.actions[-1], ('joinPublic', {'id': 'same-room'}))

    def test_created_room_guidance_matches_public_join_policy(self):
        for public, required, expected in ((True, False, '直接加入'),
                (True, True, '需要邀请码'), (False, True, '仅邀请好友')):
            with self.subTest(public=public, required=required):
                self.backend._view = {**self.backend._view, 'page':'connected', 'selected':'mine',
                    'connections':[dict(id='mine', title='World', role='host', state='online',
                        availability='ready', public=public, requireInvite=required, game={})],
                    'chatState':'在线', 'chatMessages':[], 'chatDraft':'', 'chatError':'',
                    'chatSending':False, 'bridgeStatus':'游戏聊天未开启'}
                self.backend.viewChanged.emit(); QTest.qWait(35)
                self.click('room-details')
                self.assertIn(expected, find_item(self.window, 'room-access-summary').property('text'))
                self.assertLess(len(find_item(self.window, 'room-access-guidance').property('text')), 40)
                QTest.keyClick(self.window, Qt.Key_Escape); QTest.qWait(30)

    def test_node_and_transport_labels_and_fields_share_alignment(self):
        node = find_item(self.window, 'node-picker')
        transport = find_item(self.window, 'hall-transport')
        self.assertEqual(node.width(), transport.width())
        self.assertEqual(node.height(), transport.height())
        self.assertAlmostEqual(node.mapToScene(QPointF()).x(), transport.mapToScene(QPointF()).x(), delta=1)
        for label_name, control in [('node-picker-label', node), ('hall-transport-label', transport)]:
            label = find_item(self.window, label_name)
            self.assertAlmostEqual(label.mapToScene(QPointF(0, label.height()/2)).y(),
                                   control.mapToScene(QPointF(0, control.height()/2)).y(), delta=1)

    def test_host_has_compact_room_settings_and_save_waits_for_confirmation(self):
        self.backend._view.update(page='connected', selected='mine', connections=[
            dict(id='mine', title='Friends', role='host', state='online', availability='ready',
                 public=False, requireInvite=True, game={'version':'1.21.8', 'mods_count':2})],
            chatState='在线', chatMessages=[], chatDraft='', chatError='', chatSending=False)
        self.backend.viewChanged.emit(); QTest.qWait(50)
        self.click('room-settings')
        dialog = self.window.rootObject().findChild(QObject, 'room-settings-dialog')
        self.assertIsNotNone(dialog)
        self.assertTrue(dialog.property('visible'))
        room_title = find_item(self.window, 'room-settings-title')
        room_title.setProperty('text', 'New Friends')
        access = find_item(self.window, 'room-settings-access')
        access.setProperty('currentIndex', 2)
        self.click('save-room-settings')
        self.assertEqual(self.backend.actions[-1], ('updateRoomSettings', {
            'title':'New Friends', 'public':True, 'requireInvite':False,
            'allowModTransfer':False, 'modTransferLimitKib':512}))
        self.assertTrue(dialog.property('visible'))
        self.backend.roomSettingsSaved.emit(); QTest.qWait(30)
        self.assertFalse(dialog.property('visible'))
        self.assertGreaterEqual(find_item(self.window, 'room-chat').height(), 145)

    def test_public_room_guide_glows_and_offers_settings_without_changing_access(self):
        room = dict(id='mine', title='朋友的房间', role='host', state='online', availability='ready',
                    public=False, requireInvite=True, publicGuide=True, game={'version':'1.21.8'})
        self.backend._view.update(page='connected', selected='mine', connections=[room],
            chatState='在线', chatMessages=[], chatDraft='', chatError='', chatSending=False)
        self.backend.viewChanged.emit(); QTest.qWait(60)
        self.assertTrue(find_item(self.window, 'room-public-guide').isVisible())
        glow = find_item(self.window, 'room-public-guide-glow')
        self.assertTrue(glow.property('active'))
        phase = glow.property('phase')
        QTest.qWait(80)
        self.assertNotEqual(phase, glow.property('phase'))
        self.click('room-public-guide-settings')
        dialog = self.window.rootObject().findChild(QObject, 'room-settings-dialog')
        self.assertTrue(dialog.property('visible'))
        self.assertFalse(find_item(self.window, 'room-public-guide').isVisible())
        self.assertFalse(glow.property('active'))
        self.assertFalse(room['public'])
        self.assertFalse(any(action == 'updateRoomSettings' for action, _ in self.backend.actions))
        dialog.setProperty('visible', False)
        room['publicGuide'] = True
        self.backend.viewChanged.emit(); QTest.qWait(30)
        self.click('room-public-guide-private')
        self.assertFalse(room['publicGuide'])
        self.assertFalse(room['public'])

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
        card = find_item(self.window, 'join-form-card')
        actions = find_item(self.window, 'join-form-actions')
        self.assertIs(submit.parentItem(), actions)
        self.assertLess(submit.mapToScene(QPointF(0, submit.height())).y(),
                        card.mapToScene(QPointF(0, card.height())).y())
        self.assertLessEqual(card.width(), 548)
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
                    mods_count=2), compatibility='模组集合不一致', preparing=True,
                    prepareFile='example.jar', prepareFileDone=1048576, prepareFileTotal=2097152,
                    prepareIndex=1, prepareCount=2, prepareSpeed='2.00 MiB/s',
                    mods=[dict(name='example.jar', size=2097152, state='downloading'),
                          dict(name='second.jar', size=1280, state='pending')])],
            'chatState':'在线', 'chatMessages':[], 'chatDraft':'', 'chatError':'',
            'chatSending':False, 'bridgeStatus':'游戏聊天已同步'}
        self.backend.viewChanged.emit()
        QTest.qWait(50)
        self.assertIn('1.20.1', find_item(self.window, 'room-version-summary').property('text'))
        self.assertGreaterEqual(find_item(self.window, 'room-chat').height(), 145)
        self.assertIn('example.jar', find_item(self.window, 'room-download-file').property('text'))
        self.assertIn('1.0 MiB / 2.0 MiB', find_item(self.window, 'room-download-bytes').property('text'))
        self.assertIn('正在同步房主', find_item(self.window, 'room-compatibility').property('text'))
        self.assertNotIn('模组集合不一致', find_item(self.window, 'room-compatibility').property('text'))
        self.click('show-room-mods')
        self.assertEqual(self.backend.actions[-1], ('loadMods', {}))
        self.assertTrue(find_item(self.window, 'room-mods-body').isVisible())
        self.assertEqual(find_item(self.window, 'room-mods-list').property('count'), 2)
        snapshot = ROOT / 'dist' / 'room-mods-preview.png'
        snapshot.parent.mkdir(exist_ok=True)
        self.assertTrue(self.window.grabWindow().save(str(snapshot)))

    def test_room_connecting_state_and_online_members_layout(self):
        from PySide6.QtCore import QPointF
        room = dict(id='mine', title='Friend world', role='client', state='connecting',
                    detail='Connecting to node', game=dict(version='1.21.1'),
                    lobby=dict(online=2, ready=1, self_id='guest', members=[
                        dict(id='host', name='Host', online=True, state='ready'),
                        dict(id='guest', name='Guest', online=True, state='idle'),
                        dict(id='old', name='Old session', online=False, state='idle')]))
        self.backend._view.update(page='connected', selected='mine', connections=[room])
        self.backend.viewChanged.emit()
        QTest.qWait(60)
        self.assertTrue(find_item(self.window, 'room-connecting-card').isVisible())
        self.assertIn('Connecting to node', find_item(self.window, 'room-connecting-detail').property('text'))
        room = dict(room, state='online', availability='ready', nodeName='Test node',
                    nodeRegion='Test region', nodeLatencyMs=15, latency_ms=25)
        self.backend._view['connections'] = [room]
        self.backend.viewChanged.emit()
        QTest.qWait(60)
        self.assertFalse(find_item(self.window, 'room-connecting-card').isVisible())
        self.click('room-tab-members')
        QTest.qWait(30)
        self.assertEqual(find_item(self.window, 'room-members-list').property('count'), 2)
        summary = find_item(self.window, 'room-summary')
        latency = find_item(self.window, 'room-node-latency')
        self.assertLessEqual(latency.mapToScene(QPointF(0, latency.height())).y(),
                             summary.mapToScene(QPointF(0, summary.height())).y())

    def test_top_level_title_bar_identifies_current_page_and_does_not_overlap_window_controls(self):
        for page, expected in (('hall', '· 联机大厅'), ('nodes', '联机节点')):
            if page == 'nodes':
                self.open_nodes()
            title = find_item(self.window, 'window-page-title')
            self.assertTrue(title.isVisible())
            self.assertEqual(title.property('text'), expected)
            logo = find_item(self.window, 'window-brand-logo')
            self.assertEqual(logo.isVisible(), page == 'hall')
            if page == 'hall':
                self.assertGreater(logo.implicitWidth(), 0)
                self.assertLessEqual(logo.mapToScene(QPointF(logo.width(), 0)).x(),
                                     title.mapToScene(QPointF()).x())
            self.assertEqual(find_item(self.window, 'back-hall').isVisible(), page == 'nodes')
            self.assertFalse(title.property('truncated'))
            self.assertLessEqual(title.mapToScene(QPointF(title.width(), 0)).x(),
                                 find_item(self.window, 'minimize-window').mapToScene(QPointF(0, 0)).x())

    def test_room_displays_members_game_players_and_game_ping_separately(self):
        self.backend._view = {**self.backend._view, 'page':'connected', 'selected':'mine',
            'connections':[dict(id='mine', title='World', role='client', state='online',
                availability='ready', members=4, capacity=10, game_players=2, latency_ms=57, nodeLatencyMs=12.4)],
            'chatState':'在线', 'chatMessages':[], 'chatDraft':'', 'chatError':'',
            'chatSending':False, 'bridgeStatus':'游戏聊天已同步'}
        self.backend.viewChanged.emit()
        QTest.qWait(40)
        self.assertEqual(find_item(self.window, 'room-node-latency').property('text'), '到联机节点 12 ms')
        self.assertEqual(find_item(self.window, 'room-host-latency').property('text'), '到房主 57 ms')
        self.click('room-details')
        for name, expected in [('room-member-count','房间内 4 / 10 人'),
                ('game-player-count','游戏内 2 人'), ('game-latency','游戏延迟 57 ms')]:
            item = find_item(self.window, name)
            self.assertTrue(item.isVisible())
            self.assertEqual(item.property('text'), expected)
        self.assertGreaterEqual(find_item(self.window, 'room-chat').height(),145)
        self.assert_absent_or_hidden('node-picker')

    def test_local_host_game_ping_can_display_zero(self):
        self.backend._view = {**self.backend._view, 'page':'connected', 'selected':'mine',
            'connections':[dict(id='mine', title='World', role='host', state='online',
                availability='ready', latency_ms=0)],
            'chatMessages':[], 'chatDraft':'', 'chatError':'', 'chatSending':False}
        self.backend.viewChanged.emit()
        QTest.qWait(40)
        self.click('room-details')
        self.assertEqual(find_item(self.window, 'game-latency').property('text'), '游戏延迟 0 ms · 本地')

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
                self.assertIn('等待世界开放',
                              find_item(self.window, 'connection-heading').property('text'))
                if role == 'client':
                    self.assertFalse(find_item(self.window, 'copy-address').isVisible())
                else:
                    self.assertFalse(find_item(self.window, 'choose-detected-world').isVisible())
                    self.assertIn('自动连接', find_item(self.window, 'room-access-guidance').property('text'))
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
        qt_mouse_drag(self.window, start, start - QPointF(140, 90).toPoint())
        QTest.qWait(30)
        self.assertLess(button.x(), 600)
        self.assertEqual(len(self.backend.actions), before, 'Dragging must not open the friends window')
        self.assertGreaterEqual(button.x(), 14)
        self.assertGreaterEqual(button.y(), 100)
        start = button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint()
        qt_mouse_drag(self.window, start, QPointF(-100, -100).toPoint())
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
        qt_mouse_drag(self.window, start, start - QPointF(50, 0).toPoint())
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
                              'socialReady':True, 'socialName':'local_user', 'socialAccount':'e' * 32 + '.' + 'f' * 32, 'socialError':'',
                              'friendRequests':[], 'friendInvitations':[]}
                self.actions = []
            @Property('QVariantMap', notify=changed)
            def view(self):
                self._view['contacts'] = [{'name': c['name'], 'node':'Test node',
                                           'account':c.get('account', ''),
                                           'online':c.get('online', True), 'index': i,
                                           'favorite':c.get('favorite',False), 'alias':c.get('alias',''), 'room':c.get('room')}
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
                account = (self._view['socialAccount'] if identifier == 'local_user' else
                           self.store.data['contacts'][0]['account'] if identifier == 'Friend' else
                           identifier if '.' in identifier else 'c' * 32 + '.' + 'd' * 32)
                duplicate = (account == self._view['socialAccount'] or
                             any(c.get('account') == account for c in self.store.data['contacts']) or
                             any(r['account'] == account for r in self._view['friendRequests']))
                if duplicate:
                    self._view['friendBusy'] = False
                    self.changed.emit()
                    self.friend_finished.emit(False, '不能重复添加相同账号 ID。')
                    return
                self._view['friendRequests'].append({'username':identifier, 'incoming':False,
                    'id':'1' * 32, 'account':account})
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
                if action in ('setFriendFavorite', 'setFriendAlias'):
                    field = 'favorite' if action == 'setFriendFavorite' else 'alias'
                    contact = next(c for c in self.store.data['contacts'] if c['account'] == data['account'])
                    contact[field] = data[field]
                    self.changed.emit()
            def social_operation(self, operation, account):
                self.actions.append((operation, {'account':account}))
                if operation == 'remove':
                    self.store.data['contacts'] = [c for c in self.store.data['contacts'] if c['account'] != account]
                    self.changed.emit()

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
        qt_mouse_click(self.dialog.quick, point)
        QTest.qWait(40)

    def test_friends_window_is_separate_and_can_close_independently(self):
        self.assertTrue(self.owner.isVisible())
        self.assertEqual(self.dialog.windowModality(), Qt.NonModal)
        self.assertGreaterEqual(self.dialog.width(), 400)
        for name, label in (('invite-friend-0', '邀请联机'),):
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

    def test_invite_without_room_explains_flow_before_sending(self):
        self.click('invite-friend-0')
        popup = self.dialog.quick.rootObject().findChild(QObject, 'friend-invite-preflight')
        self.assertTrue(popup.property('visible'))
        self.assertFalse(any(a[0] == 'inviteFriend' for a in self.owner.backend.actions))
        self.assertEqual(find_item(self.dialog.quick, 'confirm-friend-invite-preflight').property('text'), '去创建并邀请')
        self.click('cancel-friend-invite-preflight')
        self.assertFalse(popup.property('visible'))
        self.assertFalse(self.owner.backend.actions)
        self.click('invite-friend-0')
        self.click('confirm-friend-invite-preflight')
        self.assertEqual(self.owner.backend.actions[-1], ('inviteFriend', {'account':'a' * 32 + '.' + 'b' * 32}))

    def test_waiting_room_invitation_explains_open_world_and_can_resume(self):
        self.owner.backend._view['connections'] = [{'role':'host', 'state':'online', 'availability':'waiting'}]
        self.owner.backend.changed.emit(); QTest.qWait(20)
        self.click('invite-friend-0')
        self.assertEqual(find_item(self.dialog.quick, 'confirm-friend-invite-preflight').property('text'), '去开放并邀请')
        self.click('cancel-friend-invite-preflight')
        self.owner.backend._view.update(pendingFriendInvite='Friend', friendInviteFlow=dict(
            stage='waiting', step=1, title='等待你在游戏中开放世界', detail='开放后自动邀请',
            friend='Friend', account='a' * 32 + '.' + 'b' * 32, action='continue'))
        self.owner.backend.changed.emit(); QTest.qWait(20)
        self.assertTrue(find_item(self.dialog.quick, 'pending-friend-invite-banner').isVisible())
        self.click('continue-friend-invite')
        self.assertEqual(self.owner.backend.actions[-1], ('continueFriendInvite', {}))

    def test_more_menu_uses_explicit_readable_theme_for_every_item(self):
        self.click('friend-more-0')
        for name in ('friend-toggle-favorite', 'friend-edit-alias', 'friend-copy-name', 'friend-remove'):
            item = find_item(self.dialog.quick, name)
            label = item.property('contentItem')
            self.assertEqual(label.property('color').name(), '#ffc1c1' if name == 'friend-remove' else '#f1e8fc')
            self.assertGreater(item.width(), 100)
            point = item.mapToScene(QPointF(0, 0))
            self.assertGreaterEqual(point.x(), 0)
            self.assertLessEqual(point.y() + item.height(), self.dialog.height())

    def test_accepting_invitation_shows_busy_state_until_result(self):
        account = 'c' * 32 + '.' + 'd' * 32
        self.owner.backend._view.update(friendInvitations=[dict(account=account, username='Alice', id='1' * 32)])
        self.owner.backend.changed.emit(); QTest.qWait(20)
        self.click('show-friend-invites')
        self.click('join-friend-invite')
        self.assertEqual(self.owner.backend.actions[-1], ('joinFriend', {'account':account, 'id':'1' * 32}))
        self.assertIn('正在接受邀请', self.dialog.backend.view['notice'])
        self.owner.backend._view.update(friendBusy=True, joiningFriendAccount=account)
        self.owner.backend.changed.emit(); QTest.qWait(20)
        join = find_item(self.dialog.quick, 'join-friend-invite')
        self.assertEqual(join.property('text'), '连接中…')
        self.assertFalse(join.isEnabled())
        self.owner.backend._view.update(friendBusy=False, joiningFriendAccount='')
        self.owner.backend.friend_finished.emit(False, '邀请已过期，请好友重新邀请。')
        QTest.qWait(20)
        self.assertIn('邀请已过期', self.dialog.backend.view['error'])

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

    def test_notification_selects_invites_without_pinning_the_tab(self):
        invitation = dict(id='notification', account='a' * 32 + '.' + 'b' * 32, username='Friend')
        self.owner.backend._view['friendInvitations'] = [invitation]
        self.owner.backend.changed.emit()
        self.dialog.backend.showInvitations.emit()
        QTest.qWait(40)
        self.assertTrue(find_item(self.dialog.quick, 'join-friend-invite').isVisible())
        self.dialog.backend.changed.emit()
        QTest.qWait(20)
        self.assertEqual(self.dialog.quick.status(), QQuickWidget.Ready)

    def test_unread_tab_badges_room_status_join_actions_and_urgent_theme(self):
        backend = self.owner.backend
        account = backend.store.data['contacts'][0]['account']
        room = dict(id='f' * 32, title='Alice world', role='host', availability='ready', can_request=True)
        backend.store.data['contacts'][0].update(online=True, room=room)
        backend._view.update(contacts=[], friendNotifications=dict(requests=2, invitations=1, joinRequests=1,
                              total=4, urgent=True, homeAttention=True),
                             friendRequests=[dict(id=str(i), account=account, username='Friend', incoming=True) for i in (1, 2)],
                             friendInvitations=[dict(id='invite', account=account, username='Friend')],
                             joinRequests=[dict(id='a' * 32, account=account, username='Friend',
                                                room='b' * 32, incoming=True, status='pending')],
                             socialCapabilities=dict(room_presence=True, join_requests=True),
                             outgoingInvitations={})
        backend.changed.emit(); QTest.qWait(40)
        self.assertEqual(find_item(self.dialog.quick, 'friends-tab-1').property('count'), 2)
        self.assertEqual(find_item(self.dialog.quick, 'friends-tab-2').property('count'), 1)
        self.assertEqual(find_item(self.dialog.quick, 'friends-tab-3').property('count'), 1)
        self.assertTrue(find_item(self.dialog.quick, 'friends-tab-2').property('urgent'))
        row = find_item(self.dialog.quick, 'friend-row-0')
        self.assertIn('Alice world', row.property('person').toVariant()['room']['title'])
        self.assertTrue(find_item(self.dialog.quick, 'request-join-friend-0').isVisible())
        self.click('friends-tab-3')
        self.assertTrue(find_item(self.dialog.quick, 'accept-join-request').isVisible())
        self.assertTrue(find_item(self.dialog.quick, 'decline-join-request').isVisible())

    def test_friend_search_filters_and_online_first_sort_use_real_presence(self):
        backend = self.owner.backend
        backend.store.data['contacts'] = [
            dict(name='Alice', account='alice', online=False),
            dict(name='Zoe', account='zoe', online=True, alias='一起盖房子', favorite=True),
            dict(name='Bob', account='bob', online=True)]
        backend.changed.emit(); QTest.qWait(50)
        listing = find_item(self.dialog.quick, 'friends-list')
        self.assertEqual(listing.property('count'), 3)
        self.assertLess(find_item(self.dialog.quick, 'friend-row-1').y(), find_item(self.dialog.quick, 'friend-row-2').y())
        self.assertLess(find_item(self.dialog.quick, 'friend-row-2').y(), find_item(self.dialog.quick, 'friend-row-0').y())
        self.click('friend-filter-online')
        self.assertEqual(listing.property('count'), 2)
        self.click('friend-filter-favorite')
        self.assertEqual(listing.property('count'), 1)
        search = find_item(self.dialog.quick, 'friend-search')
        search.setProperty('text', '盖房'); QTest.qWait(30)
        self.assertEqual(listing.property('count'), 1)
        search.setProperty('text', 'absent'); QTest.qWait(30)
        self.assertEqual(listing.property('count'), 0)
        self.assertTrue(find_item(self.dialog.quick, 'friends-empty').isVisible())
        search.setProperty('text', 'zoe'); QTest.qWait(30)
        self.assertEqual(listing.property('count'), 1)

    def test_more_menu_favorite_alias_and_remove_confirmation(self):
        account = self.owner.backend.store.data['contacts'][0]['account']
        self.click('friend-more-0')
        self.owner.backend.changed.emit(); QTest.qWait(30)
        menu = self.dialog.quick.rootObject().findChild(QObject, 'friend-actions-menu')
        self.assertTrue(menu.property('visible'))
        self.click('friend-toggle-favorite')
        self.assertEqual(self.owner.backend.actions[-1], ('setFriendFavorite', {'account':account, 'favorite':True}))
        self.click('friend-more-0')
        self.click('friend-edit-alias')
        find_item(self.dialog.quick, 'friend-alias-input').setProperty('text', '一起生存')
        self.click('save-friend-alias')
        self.assertEqual(self.owner.backend.actions[-1], ('setFriendAlias', {'account':account, 'alias':'一起生存'}))
        self.click('friend-more-0')
        self.click('friend-remove')
        self.assertEqual(len(self.owner.backend.store.data['contacts']), 1)
        self.click('cancel-remove-friend')
        self.assertEqual(len(self.owner.backend.store.data['contacts']), 1)
        self.click('friend-more-0')
        self.click('friend-remove')
        self.click('confirm-remove-friend')
        self.assertEqual(self.owner.backend.store.data['contacts'], [])

    def test_add_friend_rejects_self_and_existing_friend_without_request(self):
        self.click('add-friend')
        field = find_item(self.dialog.quick, 'friend-identifier')
        for name in ('local_user', 'Friend'):
            field.setProperty('text', name)
            self.click('save-friend')
            for _ in range(200):
                if not self.owner.backend.view['friendBusy']:
                    break
                QTest.qWait(10)
            self.assertFalse(self.owner.backend.view['friendBusy'])
            self.assertTrue(find_item(self.dialog.quick, 'friend-feedback').property('text'))
            self.assertEqual(self.owner.backend.view['friendRequests'], [])

    def test_request_success_goes_to_requests_and_duplicate_is_not_resent(self):
        self.click('add-friend')
        find_item(self.dialog.quick, 'friend-identifier').setProperty('text', 'New')
        self.click('save-friend'); QTest.qWait(50)
        self.assertEqual(self.dialog.backend.local['friendTab'], 1)
        self.assertTrue(find_item(self.dialog.quick, 'friends-tab-1').property('selected'))
        self.click('add-friend')
        find_item(self.dialog.quick, 'friend-identifier').setProperty('text', 'New')
        self.click('save-friend')
        self.assertEqual(len(self.owner.backend.view['friendRequests']), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
