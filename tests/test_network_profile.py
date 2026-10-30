import asyncio
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/buggcraft'))
from utils.network_profile import classify_network, collect_network_profile, successful_session_counts


class NetworkProfileTests(unittest.TestCase):
    def test_network_type_requires_successful_observations(self):
        self.assertEqual(classify_network({'ipv4': {'udp': 'reachable', 'mapping': {
            'behavior': 'endpoint-independent'}}}), 'direct_easier')
        self.assertEqual(classify_network({'ipv4': {'udp': 'reachable', 'mapping': {
            'behavior': 'destination-dependent'}}}), 'relay_likely')
        self.assertEqual(classify_network({'ipv4': {'udp': 'unconfirmed', 'mapping': {
            'behavior': 'endpoint-independent'}}}), 'unknown')
        self.assertEqual(classify_network(None), 'unknown')

    def test_counts_only_sessions_with_confirmed_game_data(self):
        self.assertEqual(successful_session_counts({'sessions': [
            {'p2p_data_observed': True, 'relay_streams': []},
            {'p2p_data_observed': False, 'relay_streams': [{'data_observed': True}]},
            {'p2p_data_observed': False, 'relay_streams': [{'data_observed': False}]},
            None,
        ]}), {'direct_successes': 1, 'relay_successes': 1})

    def test_network_type_is_reported_before_local_history_scan(self):
        reported = []

        def scan(paths):
            self.assertEqual(reported, ['direct_easier'])
            return {'sessions': [{'p2p_data_observed': True, 'relay_streams': []}]}

        probe_result = {'ipv4': {'udp': 'reachable', 'mapping': {
            'behavior': 'endpoint-independent'}}}
        with patch('utils.nat_probe.probe_network', return_value=probe_result) as probe, \
                patch('utils.diagnostics.connection_session_directory',
                      return_value=Path('nonexistent-test-root/test-sessions')), \
                patch('utils.p2p_evidence.summarize_player_logs', side_effect=scan):
            result = asyncio.run(collect_network_profile(on_type=reported.append))

        probe.assert_called_once_with(budget=3.0)
        self.assertEqual(result, {'type': 'direct_easier', 'direct_successes': 1,
                                  'relay_successes': 0})


if __name__ == '__main__':
    unittest.main()
