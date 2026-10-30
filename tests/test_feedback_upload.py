"""Consent and failure cleanup are enforced before collecting diagnostics."""
import asyncio
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/buggcraft'))
from utils.feedback_upload import submit_diagnostics


class FeedbackUploadTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_and_oversized_archives_rejected_before_connect_and_cleaned(self):
        from utils.feedback_upload import MAX_ARCHIVE
        for size in (0, MAX_ARCHIVE + 1):
            paths = []
            async def export(path):
                paths.append(path)
                with path.open('wb') as stream:
                    stream.truncate(size)
            with self.subTest(size=size), \
                    patch('utils.diagnostics.export_connection_diagnostics', new=export), \
                    patch('hookup.native_routes.NativeRoutes') as connect:
                with self.assertRaisesRegex(ValueError, '20 MiB'):
                    await submit_diagnostics(None, 'Network', 'Failure', consent=True)
                connect.assert_not_called()
                self.assertFalse(paths[0].parent.exists())

    async def test_blank_overlong_and_whitespace_metadata_rejected_before_collecting(self):
        with patch('utils.diagnostics.export_connection_diagnostics', new=AsyncMock()) as export, \
                patch('hookup.native_routes.NativeRoutes') as connect:
            for title, description in (('', 'Failed'), (' \t\n', 'Failed'), ('T' * 121, 'Failed'),
                                       ('Network', ''), ('Network', ' \t\n'), ('Network', 'D' * 4001)):
                with self.subTest(title_length=len(title), description_length=len(description)), \
                        self.assertRaisesRegex(ValueError, '标题和描述'):
                    await submit_diagnostics(None, title, description, consent=True)
            export.assert_not_awaited()
            connect.assert_not_called()

    async def test_collection_failure_removes_partial_archive_without_opening_bridge(self):
        paths = []
        async def export(path):
            paths.append(path)
            path.write_bytes(b'partial diagnostics')
            raise OSError('disk full')
        with patch('utils.diagnostics.export_connection_diagnostics', new=export), \
                patch('hookup.native_routes.NativeRoutes') as connect:
            with self.assertRaisesRegex(OSError, 'disk full'):
                await submit_diagnostics(None, 'Network', 'Failure', consent=True)
            connect.assert_not_called()
        self.assertFalse(paths[0].parent.exists())

    async def test_without_consent_does_not_collect_or_connect(self):
        with patch('utils.diagnostics.export_connection_diagnostics', new=AsyncMock()) as export, \
                patch('hookup.native_routes.NativeRoutes') as routes:
            for consent in (False, None, 1, 'yes'):
                with self.subTest(consent=consent), self.assertRaises(ValueError):
                    await submit_diagnostics(None, 'P2P', 'Failed', consent=consent)
            export.assert_not_awaited()
            routes.assert_not_called()

    async def test_oversized_utf8_description_is_rejected_before_collection(self):
        with patch('utils.diagnostics.export_connection_diagnostics', new=AsyncMock()) as export:
            with self.assertRaisesRegex(ValueError, '6500'):
                await submit_diagnostics(None, '诊断', '卡' * 3000, consent=True)
            export.assert_not_awaited()

    async def test_uses_independent_bridge_and_removes_temporary_archive(self):
        routes = Mock(handle=AsyncMock(return_value='node'),
                      request=AsyncMock(return_value={'ok': True, 'issue': 'abc'}), close=AsyncMock())
        paths = []
        async def export(path):
            paths.append(path); path.write_bytes(b'ZIP diagnostic fixture')
        with patch('utils.diagnostics.export_connection_diagnostics', new=export), \
                patch('hookup.native_routes.NativeRoutes', return_value=routes) as create:
            result = await submit_diagnostics(object(), 'P2P', 'Failed', consent=True)
        create.assert_called_once_with(force_process=True)
        self.assertEqual(result['issue'], 'abc')
        routes.close.assert_awaited_once()
        self.assertFalse(paths[0].exists())
        self.assertIs(routes.request.call_args.args[1]['consent'], True)

    async def test_upload_error_closes_only_its_bridge_and_deletes_archive(self):
        routes = Mock(handle=AsyncMock(return_value='node'),
                      request=AsyncMock(side_effect=ConnectionError('node offline')), close=AsyncMock())
        paths = []
        async def export(path):
            paths.append(path); path.write_bytes(b'diagnostics')
        with patch('utils.diagnostics.export_connection_diagnostics', new=export), \
                patch('hookup.native_routes.NativeRoutes', return_value=routes):
            with self.assertRaises(ConnectionError):
                await submit_diagnostics(object(), 'P2P', 'Failed', consent=True)
        routes.close.assert_awaited_once()
        self.assertFalse(paths[0].exists())

    async def test_older_bridge_is_rejected_without_sending_archive(self):
        routes = Mock(feedback_support=False, handle=AsyncMock(return_value='node'),
                      request=AsyncMock(), close=AsyncMock())
        async def export(path):
            path.write_bytes(b'diagnostics')
        with patch('utils.diagnostics.export_connection_diagnostics', new=export), \
                patch('hookup.native_routes.NativeRoutes', return_value=routes):
            with self.assertRaisesRegex(ValueError, '完整启动器'):
                await submit_diagnostics(object(), 'P2P', 'Failed', consent=True)
        routes.request.assert_not_awaited()
        routes.close.assert_awaited_once()


class FeedbackConsentUiTests(unittest.TestCase):
    def setUp(self):
        from types import SimpleNamespace
        self.controller = SimpleNamespace(jobs=set(), node_path='node', _state={'socialReady': True},
            show_feedback=Mock(), patch=Mock(), job=Mock())

    def act(self):
        from ui.multiplayer_controller import MultiplayerController
        MultiplayerController.act(self.controller, 'submitDiagnostics', {})

    def test_opening_form_does_not_collect_or_upload(self):
        with patch('utils.feedback_upload.submit_diagnostics') as submit:
            self.act()
        self.controller.show_feedback.assert_called_once()
        submit.assert_not_called()
        self.controller.job.assert_not_called()

    def test_pending_upload_ignores_duplicate_click(self):
        self.controller.jobs.add('feedback-upload')
        self.act()
        self.controller.show_feedback.assert_not_called()

    def test_anonymous_identity_or_missing_node_cannot_open_form(self):
        self.controller._state['socialReady'] = False
        self.act()
        self.controller._state['socialReady'] = True
        self.controller.node_path = ''
        self.act()
        self.controller.show_feedback.assert_not_called()
        self.controller.job.assert_not_called()


class FeedbackFormMetadataTests(unittest.TestCase):
    def test_one_report_generates_node_title_without_losing_description(self):
        from ui.dialog.feedback import feedback_metadata
        content = '  ' + 'T' * 180 + '\nSteps and symptoms 🧪  '
        title, description = feedback_metadata(content)
        self.assertEqual(title, 'T' * 120)
        self.assertEqual(description, content.strip())

    def test_empty_oversized_and_utf8_limits_are_rejected(self):
        from ui.dialog.feedback import feedback_metadata
        for content in (' \t\n ', 'D' * 4001, '卡' * 3000):
            with self.subTest(length=len(content)), self.assertRaises(ValueError):
                feedback_metadata(content)
