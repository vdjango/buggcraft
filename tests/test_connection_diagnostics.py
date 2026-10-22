"""Diagnostic exports retain connection evidence without settings or credentials."""
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/buggcraft'))
from utils.diagnostics import SafeFormatter, export_diagnostics, redact
from utils.network_diagnostics import address_scope, capture_network


class ConnectionDiagnosticsTests(unittest.TestCase):
    def test_redaction_covers_headers_json_and_ice_credentials(self):
        for text in ('Authorization: Bearer top-secret', 'password="top-secret"',
                     '{"refresh_token": "top-secret"}', 'a=ice-pwd:top-secret',
                     "{'x-api-key': 'top-secret'}"):
            with self.subTest(text=text):
                self.assertNotIn('top-secret', redact(text))
        record = logging.LogRecord('hookup._rtc.rtcpeerconnection', logging.DEBUG, '', 1,
                                   'setRemoteDescription(offer)\nv=0\na=ice-pwd:top-secret', (), None)
        formatted = SafeFormatter('%(message)s').format(record)
        self.assertNotIn('v=0', formatted)
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
            target = export_diagnostics(root / 'report.zip', root)
            with ZipFile(target) as archive:
                names = set(archive.namelist())
                self.assertIn('p2p-sessions/old.log.1', names)
                self.assertIn('p2p-sessions/network-one.json', names)
                self.assertNotIn('settings.json', names)
                self.assertNotIn('p2p-sessions/node-profile.json', names)
                self.assertNotIn(b'top-secret', archive.read('buggcraft.log'))
                self.assertIn(b'192.168.1.2', archive.read('p2p-sessions/new.log'))
                self.assertEqual(len(json.loads(archive.read('diagnostics.json'))['files']), 4)

    def test_route_snapshot_is_independent_of_nat_classification_and_proxy_credentials(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch.dict(os.environ, HTTPS_PROXY='http://user:proxy-secret@127.0.0.1:1234'), \
                patch('utils.network_diagnostics.subprocess.run', return_value=subprocess.CompletedProcess(
                    [], 0, b'{"routes":[{"NextHop":"192.168.1.1"}]}', b'')) as run:
            snapshot = capture_network(temporary, 'trace-one')
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
            result = capture_network(temporary, 'timeout')
            self.assertEqual(result['route_error'], 'TimeoutExpired')
            self.assertTrue((Path(temporary) / 'network-timeout.json').is_file())

    def test_address_scope_does_not_mislabel_cgnat_space_as_public(self):
        self.assertEqual(address_scope('100.72.0.1'), 'shared-address-space')
        self.assertEqual(address_scope('192.168.1.2'), 'private-or-special')
        self.assertEqual(address_scope('8.8.8.8'), 'global')
        self.assertEqual(address_scope('fe80::1%3'), 'link-local')


if __name__ == '__main__':
    unittest.main()
