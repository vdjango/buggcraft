"""Click diagnostics controls and verify archives delivered through real SSH.

The local node uses the production portal/relay/store; the launcher uses its
production exporter, native bridge subprocess, worker completion and QML. Only
public STUN is disabled in these deterministic cases; Windows adapters/routes
are collected for real. Microsoft authentication is outside this suite.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
from types import MethodType
from unittest.mock import patch
from zipfile import ZipFile

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtWidgets import QDialogButtonBox, QFileDialog, QInputDialog, QLineEdit, QMessageBox, QPlainTextEdit, QTextEdit

from _qml_test_support import QTest, qt_mouse_click
from test_client_ui_acceptance import ClientUiAcceptanceCase as _UiCase
from ui.multiplayer_controller import MultiplayerController
from hookup.profiles import RelayProfile
from utils.network_diagnostics import capture_network

_REAL_JOB = MultiplayerController.job


class DiagnosticsUiTests(_UiCase):
    def record(self, kind, target, detail=''):
        super().record(kind, target, detail)
        with (self.output / 'live-actions.jsonl').open('a', encoding='utf-8') as log:
            log.write(json.dumps(self.actions[-1], ensure_ascii=False) + '\n')

    def setUp(self):
        super().setUp()
        self.dialog = self.window.started_page._ensure_multiplayer_dialog()
        self.backend = self.dialog.backend
        self.backend.friend_timer.stop()
        self.backend.room_search_timer.stop()
        self.backend.job = MethodType(_REAL_JOB, self.backend)
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self.backend.service.submit.side_effect = lambda task: asyncio.run_coroutine_threadsafe(task, self.loop)
        self.addCleanup(self.close_loop)
        self.logs = self.directory / 'diagnostic-logs'
        self.logs.mkdir()
        (self.logs / 'buggcraft.log').write_text(
            'heartbeat timeout node=127.0.0.1 Authorization: Bearer test-private-token\n', encoding='utf-8')
        sessions = self.logs / 'p2p-sessions'
        sessions.mkdir()
        (sessions / 'connection.log').write_text('ICE selected_pair local=192.0.2.8 remote=198.51.100.4\n', encoding='utf-8')
        (self.game_dir / 'versions/1.21.8/logs').mkdir()
        (self.game_dir / 'versions/1.21.8/logs/latest.log').write_text('Game diagnostic test --accessToken test-private-token', encoding='utf-8')
        (self.logs / 'settings.json').write_text('must-not-export-private-settings', encoding='utf-8')
        self.manager.set_setting('minecraft.isolation', True)
        self._patch(patch('utils.diagnostics._log_root', self.logs))
        self._patch(patch.dict(os.environ, BUGGCRAFT_BRIDGE_LOG_DIR=str(self.logs / 'players')))
        self._patch(patch('utils.network_diagnostics.capture_network',
                          side_effect=lambda directory, trace: capture_network(directory, trace, active_probe=False)))
        self.backend.patch(page='hall', busy=False, loading=False, socialLoading=False)
        self.dialog.show()
        self.pump(100)
        self.node = None

    def close_loop(self):
        if self.loop.is_running():
            async def drain():
                # This case replaces TunnelService with a UI fixture. Close the
                # real bridge on its owning loop before that fixture stops it.
                from hookup.native_routes import close as close_native_routes
                await close_native_routes()
                tasks = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await self.loop.shutdown_default_executor()
            asyncio.run_coroutine_threadsafe(drain(), self.loop).result(20)
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(5)
            self.loop.close()

    def start_node(self):
        configured = os.environ.get('BUGGCRAFT_NATIVE_SOURCE') or os.environ.get('BUGGCRAFT_NATIVE_REPO')
        native = Path(configured or Path(__file__).resolve().parents[2] / 'minecraft-tunnel-native')
        if not configured and not (native / 'web/tunnel/portal.py').is_file():
            self.skipTest('Set BUGGCRAFT_NATIVE_SOURCE to the production node checkout')
        self.assertTrue((native / 'web/tunnel/portal.py').is_file(), 'Configured production node checkout is required')
        self.node_errors = (self.output / 'node-stderr.log').open('w', encoding='utf-8')
        self.node = subprocess.Popen([sys.executable, '-u', str(native / 'tests/launcher_diagnostics_fixture.py')],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.node_errors,
            text=True, encoding='utf-8', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.addCleanup(self.close_node)
        self.responses = queue.Queue()
        def read_responses():
            for line in self.node.stdout:
                self.responses.put(line)
        threading.Thread(target=read_responses, daemon=True).start()
        self.profile = RelayProfile(**self.response()['profile'])
        self.backend.profile = lambda: self.profile
        self.backend.node_path = str(self.directory / 'isolated-node.json')
        self.backend.patch(nodeAvailable=True, nodeIndex=0, socialReady=True,
                           socialAccount='diagnostics-test', socialName='Local reporter',
                           nodes=[dict(path=self.backend.node_path, title='Local test node', personalCode=True)])
        self.pump()

    def close_node(self):
        if self.node.poll() is None:
            self.node.stdin.write('{"op":"close"}\n')
            self.node.stdin.flush()
            try:
                self.node.wait(15)
            except subprocess.TimeoutExpired:
                self.node.kill()
                self.node.wait(5)
        self.node.stdin.close()
        self.node.stdout.close()
        self.node_errors.close()

    def response(self):
        try:
            value = json.loads(self.responses.get(timeout=25))
        except queue.Empty:
            self.fail('Local node did not respond; inspect node-stderr.log')
        self.assertNotIn('error', value, value)
        return value

    def node_call(self, **request):
        self.node.stdin.write(json.dumps(request) + '\n')
        self.node.stdin.flush()
        return self.response()

    def modal_actions(self, actions):
        """Use actual keystrokes/buttons in nested Qt modal event loops."""
        pending = list(actions)
        errors = []
        timer = QTimer(self.dialog)
        timer.setInterval(30)
        seen = []
        discovered = {}
        deadline = time.monotonic() + 15
        def act():
            modal = self.app.activeModalWidget()
            if time.monotonic() > deadline:
                errors.append(AssertionError('Timed out waiting for modal actions: ' + repr(pending)))
                timer.stop()
                if modal is not None:
                    modal.reject()
                return
            if modal is None or any(modal is previous for previous in seen):
                if not pending and (modal is None or not modal.isVisible()):
                    timer.stop()
                return
            # Windows can register a modal before its focus and escape button
            # have been initialized. Send input only after the dialog is shown.
            first = discovered.setdefault(id(modal), time.monotonic())
            if not modal.isVisible() or time.monotonic() - first < .12:
                return
            try:
                self.assertTrue(pending, 'Unexpected modal: ' + modal.windowTitle())
                kind, value = pending.pop(0)
                self.record('modal', kind, str(value))
                seen.append(modal)
                if isinstance(modal, QMessageBox):
                    self.check(modal.defaultButton() is modal.button(QMessageBox.No), 'Upload consent defaults to No')
                    if value == 'escape':
                        # Target the current dialog, not QApplication's stale
                        # focus widget left over from the preceding input box.
                        QTest.keyClick(modal, Qt.Key_Escape)
                    elif value == 'close':
                        modal.close()
                    else:
                        button = modal.button(QMessageBox.Yes if value else QMessageBox.No)
                        qt_mouse_click(button, button.rect().center())
                elif isinstance(modal, (QInputDialog, QFileDialog)):
                    if kind.endswith('-escape'):
                        QTest.keyClick(modal, Qt.Key_Escape)
                    elif kind.endswith('-close'):
                        modal.close()
                    elif value is None:
                        button = modal.findChild(QDialogButtonBox).button(QDialogButtonBox.Cancel)
                        qt_mouse_click(button, button.rect().center())
                    else:
                        editor = (modal.findChild(QLineEdit, 'fileNameEdit') if isinstance(modal, QFileDialog)
                                  else modal.findChild(QPlainTextEdit) or modal.findChild(QTextEdit) or modal.findChild(QLineEdit))
                        self.assertIsNotNone(editor)
                        editor.setFocus()
                        QTest.keyClick(editor, Qt.Key_A, Qt.ControlModifier)
                        text_event = QInputMethodEvent()
                        text_event.setCommitString(str(value))
                        self.app.sendEvent(editor, text_event)
                        button = modal.findChild(QDialogButtonBox).button(
                            QDialogButtonBox.Save if isinstance(modal, QFileDialog) else QDialogButtonBox.Ok)
                        qt_mouse_click(button, button.rect().center())
                else:
                    self.fail('Unexpected modal class: ' + type(modal).__name__)
            except Exception as error:
                errors.append(error)
                modal.reject()
                timer.stop()
        timer.timeout.connect(act)
        timer.start()
        return timer, pending, errors

    def submit(self, *, title='Network diagnostics', description='Heartbeat and ICE connection failure', consent=True):
        timer, pending, errors = self.modal_actions([('title', title), ('description', description), ('consent', consent)])
        self.click_ui(self.dialog, 'submit-diagnostics')
        timer.stop()
        if errors:
            raise errors[0]
        self.check(not pending, 'All actual title/description/consent dialogs were exercised')

    def wait_job(self, key):
        self.wait_for(lambda: key not in self.backend.jobs, key + ' completed', 45000)
        self.pump()

    def check_archive(self, path):
        with ZipFile(path) as archive:
            manifest = json.loads(archive.read('diagnostics.json'))
            self.check(manifest['network_collection']['status'] == 'collected', 'Fresh network snapshot included')
            network, = [name for name in archive.namelist() if name.startswith('p2p-sessions/network-export-')]
            snapshot = json.loads(archive.read(network))
            self.check(bool(snapshot['interfaces']), 'Actual host adapters and addresses collected')
            self.check(snapshot.get('route_probe_exit') == 0 and bool(snapshot.get('routes_and_adapters')),
                       'Actual operating system route/DNS/adapter query succeeded')
            if os.name == 'nt':
                self.check(all(key in snapshot['routes_and_adapters'] for key in ('adapters', 'routes', 'dns', 'gateways')),
                           'Windows route, DNS, gateway and adapter evidence present')
            self.check(snapshot['nat_type'] == 'unknown' and snapshot['p2p_capability']['status'] == 'not-verified-by-network-probe',
                       'Passive evidence does not invent a NAT class or P2P success')
            self.check('p2p-evidence.json' in archive.namelist() and 'game/logs/latest.log' in archive.namelist(),
                       'Game log and P2P evidence accompany network snapshot')
            self.check(b'192.0.2.8' in archive.read('p2p-sessions/connection.log'), 'Troubleshooting network addresses retained')
            self.check('settings.json' not in archive.namelist(), 'Settings and tokens excluded')
            for entry in manifest['files']:
                payload = archive.read(entry['path'])
                self.check(len(payload) == entry['bytes'] and hashlib.sha256(payload).hexdigest() == entry['sha256'],
                           'Manifest matches exported bytes: ' + entry['path'])
                self.check(b'test-private-token' not in payload, 'Credentials redacted: ' + entry['path'])
        return manifest

    @staticmethod
    def save_dialog(parent, title, initial, file_filter):
        dialog = QFileDialog(parent, title, initial, file_filter)
        dialog.setOption(QFileDialog.DontUseNativeDialog, True)
        dialog.setAcceptMode(QFileDialog.AcceptSave)
        return (dialog.selectedFiles()[0], file_filter) if dialog.exec() else ('', '')

    def test_export_cancel_escape_and_close_create_no_archive_or_snapshot(self):
        self.start_node()
        for action in ('save', 'save-escape', 'save-close'):
            timer, pending, errors = self.modal_actions([(action, None)])
            with patch('ui.multiplayer_controller.QFileDialog.getSaveFileName', side_effect=self.save_dialog):
                self.click_ui(self.dialog, 'export-diagnostics')
            timer.stop()
            if errors:
                raise errors[0]
            self.check(not pending and 'diagnostics' not in self.backend.jobs,
                       'Dismissed save dialog cannot start export: ' + action)
            self.check(self.dialog.isVisible() and not list(self.logs.glob('p2p-sessions/network-export-*')),
                       'Dismissed save dialog preserves lobby and does not collect network data: ' + action)
            self.check(not list(self.output.glob('*.zip')), 'No archive from cancelled export')
        self.check(self.node_call(op='inspect')['count'] == 0, 'Cancelled export never uploads')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_export_click_saves_network_game_archive_without_uploading(self):
        self.start_node()
        destination = self.output / 'network-game-diagnostics.zip'
        timer, pending, errors = self.modal_actions([('save', str(destination.with_suffix('')))])
        with patch('ui.multiplayer_controller.QFileDialog.getSaveFileName', side_effect=self.save_dialog):
            self.click_ui(self.dialog, 'export-diagnostics')
        timer.stop()
        if errors:
            raise errors[0]
        self.check(not pending, 'Actual save dialog received path from keyboard')
        self.wait_job('diagnostics')
        self.check(destination.is_file() and not self.backend.view['error'], 'ZIP suffix added and export succeeded')
        self.check_archive(destination)
        self.check(self.node_call(op='inspect')['count'] == 0, 'Local export creates no node feedback')
        self.screenshot_ui('diagnostics-export-complete', self.dialog)
        self.assert_no_qml_errors()
        self.finish_test()

    def test_submit_click_uploads_to_current_node_and_federated_admin_download(self):
        self.start_node()
        title = '上海节点联机心跳与协商诊断'
        description = '房主在上海，玩家在宿迁。\n复现：加入后等待，确认网络与游戏日志。🧪'
        self.submit(title=title, description=description)
        self.check('feedback-upload' in self.backend.jobs, 'Actual asynchronous upload started')
        self.click_ui(self.dialog, 'submit-diagnostics')
        self.check(self.app.activeModalWidget() is None, 'Duplicate submit creates no dialog or second upload')
        self.wait_job('feedback-upload')
        self.check(not self.backend.view['error'], self.backend.view['error'])
        notice = self.backend.view['notice']
        self.check(notice.startswith('反馈已提交，编号：'), 'Node receipt displayed in launcher')
        issue = notice.split('：', 1)[1]
        destination = self.output / 'node-received-diagnostics.zip'
        received = self.node_call(op='verify', issue=issue, destination=str(destination))
        self.check(received['count'] == 1 and received['attachments'] == 1, 'One click creates exactly one feedback and attachment')
        self.check(received['title'] == title and received['description'] == description,
                   'Chinese, newline and emoji survive actual UI, native SSH and node storage')
        self.check(received['anonymous_status'] == 401 and received['nodes_verified'] == 2,
                   'Private attachment downloaded byte-for-byte by both authenticated node admins')
        self.check(received['sha256'] == hashlib.sha256(destination.read_bytes()).hexdigest(), 'Node receipt matches actual archive')
        self.check_archive(destination)
        (self.output / 'node-receipt.json').write_text(json.dumps(received, indent=2), encoding='utf-8')
        self.screenshot_ui('diagnostics-submit-complete', self.dialog)
        self.assert_no_qml_errors()
        self.finish_test()

    def test_invalid_metadata_fails_before_network_collection_or_node_upload(self):
        self.start_node()
        for title, description in ((' \t ', 'Failure'), ('T' * 121, 'Failure'),
                                   ('Network', 'D' * 4001), ('网络', '卡' * 3000)):
            self.submit(title=title, description=description)
            self.wait_job('feedback-upload')
            self.check(bool(self.backend.view['error']) and '上传未完成' in self.backend.view['notice'],
                       'Invalid metadata reports failure through actual asynchronous worker')
            self.check('反馈已提交' not in self.backend.view['notice'] and
                       not list(self.logs.glob('p2p-sessions/network-export-*')),
                       'Rejected metadata creates no network snapshot or success notice')
        self.check(self.node_call(op='inspect')['count'] == 0, 'Invalid metadata never reaches node feedback storage')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_cancel_consent_or_anonymous_never_collects_or_uploads(self):
        self.start_node()
        for actions in ([('title', None)], [('title-escape', None)], [('title-close', None)],
                        [('title', 'Network'), ('description', None)],
                        [('title', 'Network'), ('description-escape', None)],
                        [('title', 'Network'), ('description-close', None)],
                        [('title', 'Network'), ('description', 'Failed'), ('consent', False)],
                        [('title', 'Network'), ('description', 'Failed'), ('consent', 'escape')],
                        [('title', 'Network'), ('description', 'Failed'), ('consent', 'close')]):
            timer, pending, errors = self.modal_actions(actions)
            self.click_ui(self.dialog, 'submit-diagnostics')
            timer.stop()
            if errors:
                raise errors[0]
            self.check(not pending and 'feedback-upload' not in self.backend.jobs, 'Dismissed consent cannot start upload')
            self.check(self.dialog.isVisible(), 'Native dialog cancellation preserves the lobby window')
            self.check(not list(self.logs.glob('p2p-sessions/network-export-*')), 'Dismissal does not collect network data')
        self.backend.patch(socialReady=False)
        self.check(not self.item(self.dialog, 'submit-diagnostics').isEnabled(), 'Anonymous upload button disabled')
        self.click_ui(self.dialog, 'submit-diagnostics')
        self.check(self.app.activeModalWidget() is None, 'Disabled anonymous click opens no upload dialogs')
        self.check(self.node_call(op='inspect')['count'] == 0, 'No feedback from cancelled or anonymous action')
        self.key_ui(self.dialog, Qt.Key_Escape, 'lobby-escape-after-native-dialog')
        self.check(not self.dialog.isVisible(), 'Lobby Escape works again when no native modal is open')
        self.assert_no_qml_errors()
        self.finish_test()

    def test_actual_node_rejects_invalid_token_and_retry_uploads_after_repair(self):
        self.start_node()
        valid = self.profile
        self.profile = RelayProfile(valid.server_host, valid.server_port, 'invalid-token-' * 4, valid.server_public_key)
        self.submit()
        self.wait_job('feedback-upload')
        self.check(bool(self.backend.view['error']) and '上传未完成' in self.backend.view['notice'], 'Real authentication rejection is visible')
        self.check('反馈已提交' not in self.backend.view['notice'] and self.node_call(op='inspect')['count'] == 0,
                   'Rejected SSH auth cannot claim success or create feedback')
        self.screenshot_ui('diagnostics-auth-rejected', self.dialog)
        self.profile = valid
        self.submit()
        self.wait_job('feedback-upload')
        self.check(not self.backend.view['error'] and self.backend.view['notice'].startswith('反馈已提交，编号：'),
                   'Restored real account credential succeeds through same UI: ' + str(self.backend.view['error']))
        self.check(self.node_call(op='inspect')['count'] == 1, 'Retry creates one valid feedback')
        self.assert_no_qml_errors()
        self.finish_test()
