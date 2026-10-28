"""Connectivity, game bytes and malformed journals remain separate evidence."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/buggcraft'))
from utils.p2p_evidence import summarize_player_logs


class P2pEvidenceTests(unittest.TestCase):
    def summarize(self, *rows):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'journal.jsonl'
            path.write_text('\n'.join(json.dumps(row) for row in rows), encoding='utf-8')
            return summarize_player_logs([path])

    def test_selected_ipv4_pair_does_not_prove_game_data(self):
        report = self.summarize(dict(session='a', event='peer_selected_pair',
            local_endpoint=[dict(family=4, address='192.168.1.2', port=5000)],
            remote_endpoint=[dict(family=4, address='192.168.1.3', port=5001)]))
        self.assertEqual(report['sessions'][0]['selected_pair_families'], [4])
        self.assertFalse(report['sessions'][0]['p2p_data_observed'])

    def test_game_close_before_path_and_duplicate_files_preserve_bytes(self):
        report = self.summarize(
            dict(session='a', event='stream_closed', stream='game', sent_bytes=1048593, received_bytes=1048593),
            dict(session='a', event='game_path', stream='game', path='p2p'),
            dict(session='a', event='stream_closed', stream='game', sent_bytes=1048593, received_bytes=1048593))
        session = report['sessions'][0]
        self.assertTrue(session['p2p_data_observed'])
        self.assertEqual(len(session['p2p_streams']), 1)
        self.assertEqual(session['p2p_streams'][0]['received_bytes'], 1048593)

    def test_relay_or_mixed_paths_do_not_prove_p2p_bytes(self):
        for paths in (('relay',), ('p2p', 'relay')):
            with self.subTest(paths=paths):
                rows = [dict(session='a', event='game_path', stream='game', path=path) for path in paths]
                rows.append(dict(session='a', event='stream_closed', stream='game', sent_bytes=50, received_bytes=50))
                report = self.summarize(*rows)
                self.assertFalse(report['sessions'][0]['p2p_data_observed'])

    def test_failures_without_stream_and_bad_types_are_retained_safely(self):
        report = self.summarize(None, [], dict(session='a', event='peer_timeout', reason='ice-timeout'),
            dict(session='a', event='peer_failure_details', reason='negotiation-timeout',
                 ice_state=4, local_endpoints=[], remote_endpoints=[]),
            dict(session='a', event='peer_selected_pair', local_endpoint=[{}], remote_endpoint=[{}]),
            dict(session='a', event='peer_selected_pair', local_endpoint='bad', remote_endpoint={}),
            dict(session='a', event='game_path', stream='game', path='p2p'),
            dict(session='a', event='stream_closed', stream='game', sent_bytes='10', received_bytes=True))
        session = report['sessions'][0]
        self.assertFalse(session['p2p_data_observed'])
        self.assertEqual(session['failures'][0]['reason'], 'ice-timeout')
        self.assertEqual(session['failures'][1]['reason'], 'negotiation-timeout')


if __name__ == '__main__':
    unittest.main()
