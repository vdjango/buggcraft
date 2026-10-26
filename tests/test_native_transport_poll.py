"""The displayed multiplayer path follows the bridge's live session state."""
import sys
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/buggcraft'))

from hookup.native_transport import NativeEndpoint


class NativeTransportPollTests(unittest.IsolatedAsyncioTestCase):
    async def test_poll_publishes_initial_and_changed_transport(self):
        class Routes:
            def __init__(self):
                self.polls = 0

            async def handle(self, profile):
                return 'fixture-node'

            async def request(self, method, params):
                if method == 'room.join':
                    return {'session': 'fixture-session', 'transport': 'relay',
                            'address': '127.0.0.1:42317', 'info': {}}
                if method == 'session.events':
                    return {'events': []}
                if method == 'session.list':
                    self.polls += 1
                    state = 'online' if self.polls == 1 else 'stopped'
                    route = 'p2p' if self.polls == 1 else 'relay'
                    return {'sessions': [{'session': 'fixture-session', 'state': state,
                                          'transport': route, 'info': {}}]}
                raise AssertionError(method)

        endpoint = NativeEndpoint({}, role='client')
        events = []
        endpoint.on_chat = events.append
        routes = Routes()
        with patch('hookup.native_transport.manager', return_value=routes), \
                patch('hookup.native_transport.asyncio.sleep', new=AsyncMock()):
            await endpoint.run()

        self.assertEqual(events, [
            {'type': 'transport', 'transport': 'relay'},
            {'type': 'transport', 'transport': 'p2p'},
        ])


if __name__ == '__main__':
    unittest.main()
