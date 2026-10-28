"""Diagnostic exports retain connection evidence without settings or credentials."""
import json
import asyncio
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from unittest.mock import AsyncMock
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/buggcraft'))
from utils.diagnostics import SafeFormatter, export_diagnostics, redact
from utils.network_diagnostics import address_scope, capture_network


class ConnectionDiagnosticsTests(unittest.TestCase):
    def test_export_button_runs_collection_in_worker_without_blocking_ui(self):
        from ui.multiplayer_controller import MultiplayerController
        controller = SimpleNamespace(window=None, patch=unittest.mock.Mock(), job=unittest.mock.Mock())
        with patch('ui.multiplayer_controller.QFileDialog.getSaveFileName', return_value=('report.zip', 'ZIP')), \
                patch('utils.diagnostics.export_diagnostics', return_value=Path('report.zip')) as export:
            MultiplayerController.act(controller, 'exportDiagnostics', {})
            export.assert_not_called()
            key, coroutine = controller.job.call_args.args
            self.assertEqual(key, 'diagnostics')
            asyncio.run(coroutine)
            export.assert_called_once_with('report.zip', native_diagnostics={'status': 'not_running', 'flushed': False})

    def test_export_drains_native_journal_before_collecting_incident_files(self):
        from utils.diagnostics import export_connection_diagnostics
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            events = root / 'players/account-one'
            events.mkdir(parents=True)
            def drain():
                (events / 'session.events.jsonl').write_text('{"event":"endpoint_disconnected"}\n', encoding='utf-8')
                return dict(status='collected', flushed=True, dropped_events=7, write_errors=2)
            # The archive collector sees the file created by the flush, not a stale scan.
            from utils import diagnostics
            with patch('hookup.native_routes.diagnostic_snapshot', new=AsyncMock(side_effect=drain)), \
                    patch.object(diagnostics, '_log_root', root), \
                    patch('utils.network_diagnostics.capture_network', return_value={'trace_id': 'test'}):
                archive = asyncio.run(export_connection_diagnostics(root / 'report.zip'))
            with ZipFile(archive) as exported:
                self.assertIn('players/account-one/session.events.jsonl', exported.namelist())
                health = json.loads(exported.read('diagnostics.json'))['native_journal']
                self.assertEqual(health['write_errors'], 2)
                self.assertEqual(health['dropped_events'], 7)
                self.assertTrue(health['flushed'])

    def test_old_launches_and_snapshots_are_pruned_without_other_files(self):
        from utils.diagnostics import prune_connection_logs
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ('old.log', 'old.log.1', 'network-old.json'):
                path = root / name
                path.write_text('old', encoding='utf-8')
                os.utime(path, (1, 1))
            (root / 'node-profile.json').write_text('keep', encoding='utf-8')
            (root / 'recent.log').write_text('recent', encoding='utf-8')
            prune_connection_logs(root)
            self.assertEqual({path.name for path in root.iterdir()}, {'node-profile.json', 'recent.log'})

    def test_redaction_covers_headers_json_and_ice_credentials(self):
        for text in ('Authorization: Bearer top-secret', 'password="top-secret"',
                     '{"refresh_token": "top-secret"}', 'a=ice-pwd:top-secret',
                     "{'x-api-key': 'top-secret'}", '--accessToken top-secret --xuid top-secret',
                     '--accessToken "top-secret"'):
            with self.subTest(text=text):
                self.assertNotIn('top-secret', redact(text))
        record = logging.LogRecord('hookup.native_routes', logging.DEBUG, '', 1,
                                   'bridge failure token=top-secret', (), None)
        formatted = SafeFormatter('%(message)s').format(record)
        self.assertIn('bridge failure', formatted)
        self.assertNotIn('top-secret', formatted)

    def test_export_keeps_separate_sessions_routes_and_rotations_excludes_settings(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sessions = root / 'p2p-sessions'
            sessions.mkdir()
            (root / 'buggcraft.log').write_text('Authorization: Bearer top-secret', encoding='utf-8')
            (root / 'settings.json').write_text('account-token', encoding='utf-8')
            (sessions / 'old.log.1').write_text('old session', encoding='utf-8')
            (sessions / 'new.log').write_text('selected_pair local=192.168.1.2', encoding='utf-8')
            (sessions / 'network-one.json').write_text('{"nat_type":"unknown"}', encoding='utf-8')
            (sessions / 'node-profile.json').write_text('room-secret', encoding='utf-8')
            def snapshot(directory, trace):
                value = {'trace_id': trace, 'routes_and_adapters': {'routes': [{'NextHop': '192.168.1.1'}]}}
                (Path(directory) / ('network-' + trace + '.json')).write_text(json.dumps(value), encoding='utf-8')
                return value
            with patch('utils.network_diagnostics.capture_network', side_effect=snapshot) as capture:
                target = export_diagnostics(root / 'report.zip', root)
            capture.assert_called_once()
            with ZipFile(target) as archive:
                names = set(archive.namelist())
                self.assertIn('p2p-sessions/old.log.1', names)
                self.assertIn('p2p-sessions/network-one.json', names)
                self.assertNotIn('settings.json', names)
                self.assertNotIn('p2p-sessions/node-profile.json', names)
                self.assertNotIn(b'top-secret', archive.read('buggcraft.log'))
                self.assertIn(b'192.168.1.2', archive.read('p2p-sessions/new.log'))
                metadata = json.loads(archive.read('diagnostics.json'))
                self.assertEqual(len(metadata['files']), 6)
                self.assertIn('p2p-evidence.json', [item['path'] for item in metadata['files']])
                self.assertEqual(metadata['network_collection']['status'], 'collected')

    def test_export_keeps_native_player_logs_separate_and_allowlisted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            account = root / 'players/account-abc'
            anonymous = root / 'players/anonymous-def'
            account.mkdir(parents=True)
            anonymous.mkdir(parents=True)
            (account / 'first.jsonl').write_text('{"event":"connected","player":"account-abc"}\n', encoding='utf-8')
            (account / 'first.1.jsonl').write_text('{"event":"sample","player":"account-abc"}\n', encoding='utf-8')
            (anonymous / 'second.jsonl').write_text('{"event":"connected","player":"anonymous-def"}\n', encoding='utf-8')
            (account / 'ignored.txt').write_text('not a journal', encoding='utf-8')
            with patch('utils.network_diagnostics.capture_network', return_value={'trace_id': 'native'}):
                destination = export_diagnostics(root / 'diagnostics.zip', root)
            with ZipFile(destination) as archive:
                names = set(archive.namelist())
                self.assertIn('players/account-abc/first.jsonl', names)
                self.assertIn('players/account-abc/first.1.jsonl', names)
                self.assertIn('players/anonymous-def/second.jsonl', names)
                self.assertNotIn('players/account-abc/ignored.txt', names)
                self.assertEqual(json.loads(archive.read('players/account-abc/first.jsonl'))['player'], 'account-abc')

    def test_configure_logging_sets_native_bridge_child_log_root(self):
        import utils.diagnostics as diagnostics
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ):
            with patch.object(diagnostics, '_session_file', None), patch.object(diagnostics, '_log_root', None), \
                    patch('utils.diagnostics.atexit.register'), patch('utils.diagnostics.RotatingFileHandler'), \
                    patch('logging.getLogger') as logger:
                logger.return_value.handlers = []
                session = diagnostics.configure_connection_logging(temporary)
            self.assertTrue(session.parent.is_dir())
            self.assertEqual(os.environ['BUGGCRAFT_BRIDGE_LOG_DIR'], str(Path(temporary).resolve() / 'players'))

    def test_export_without_room_keeps_network_failure_and_selected_game_crash_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / 'instance'
            (game / 'logs').mkdir(parents=True)
            (game / 'crash-reports').mkdir()
            (game / 'saves').mkdir()
            (game / 'logs/latest.log').write_text('renderer error --accessToken top-secret', encoding='utf-8')
            (game / 'crash-reports/crash-client.txt').write_text('Renderer failed', encoding='utf-8')
            (game / 'hs_err_pid1.log').write_text('EXCEPTION_ACCESS_VIOLATION', encoding='utf-8')
            (game / 'saves/world.dat').write_text('private world', encoding='utf-8')
            (game / 'options.txt').write_text('private options', encoding='utf-8')
            with patch('utils.network_diagnostics.capture_network', side_effect=OSError('route probe blocked')):
                target = export_diagnostics(root / 'report.zip', root, game)
            with ZipFile(target) as archive:
                self.assertIn('game/logs/latest.log', archive.namelist())
                self.assertIn('game/crash-reports/crash-client.txt', archive.namelist())
                self.assertIn('game/jvm/hs_err_pid1.log', archive.namelist())
                self.assertNotIn(b'top-secret', archive.read('game/logs/latest.log'))
                self.assertFalse(any('world.dat' in name or 'options.txt' in name for name in archive.namelist()))
                metadata = json.loads(archive.read('diagnostics.json'))
                self.assertEqual(metadata['network_collection']['status'], 'failed')
                self.assertIn('route probe blocked', metadata['network_collection']['error'])
                self.assertIn('game/logs/debug.log', metadata['missing_game_logs'])

    def test_route_snapshot_is_independent_of_nat_classification_and_proxy_credentials(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch.dict(os.environ, HTTPS_PROXY='http://user:proxy-secret@127.0.0.1:1234'), \
                patch('utils.network_diagnostics.subprocess.run', return_value=subprocess.CompletedProcess(
                    [], 0, b'{"routes":[{"NextHop":"192.168.1.1"}]}', b'')) as run:
            snapshot = capture_network(temporary, 'trace-one', active_probe=False)
            self.assertEqual(snapshot['nat_type'], 'unknown')
            self.assertTrue(snapshot['proxy_environment_present']['HTTPS_PROXY'])
            self.assertEqual(snapshot['routes_and_adapters']['routes'][0]['NextHop'], '192.168.1.1')
            self.assertLessEqual(run.call_args.kwargs['timeout'], 8)
            data = (Path(temporary) / 'network-trace-one.json').read_text(encoding='utf-8')
            self.assertNotIn('proxy-secret', data)
            self.assertFalse(list(Path(temporary).glob('*.tmp')))

    def test_route_probe_timeout_still_saves_interface_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch('utils.network_diagnostics.subprocess.run', side_effect=subprocess.TimeoutExpired('probe', 8)):
            result = capture_network(temporary, 'timeout', active_probe=False)
            self.assertEqual(result['route_error'], 'TimeoutExpired')
            self.assertTrue((Path(temporary) / 'network-timeout.json').is_file())

    def test_missing_interface_discovery_does_not_claim_ipv6_absent(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch('psutil.net_if_stats', side_effect=OSError('unavailable')), \
                patch('utils.network_diagnostics.subprocess.run', side_effect=OSError('unavailable')):
            result = capture_network(temporary, 'interfaces-unavailable', active_probe=False)
        self.assertIsNone(result['global_ipv6_configured'])
        self.assertEqual(result['interfaces_error'], 'OSError')

    def test_address_scope_does_not_mislabel_cgnat_space_as_public(self):
        self.assertEqual(address_scope('100.72.0.1'), 'shared-address-space')
        self.assertEqual(address_scope('192.168.1.2'), 'private-or-special')
        self.assertEqual(address_scope('8.8.8.8'), 'global')
        self.assertEqual(address_scope('fe80::1%3'), 'link-local')


if __name__ == '__main__':
    unittest.main()
