import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/buggcraft'))
from utils.network_profile import classify_network, successful_session_counts


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


if __name__ == '__main__':
    unittest.main()
