"""Data-only dependency isolation, old-client interoperation and DTLS identity."""
import asyncio
import importlib.util
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/buggcraft'))

from hookup._rtc import RTCPeerConnection, RTCConfiguration, RTCSessionDescription
from hookup.peer import PeerTransport, prepare_native_crypto


class DataChannelIsolationTests(unittest.TestCase):
    def test_real_exchange_without_importing_media_or_upstream_aiortc(self):
        script = '''
import asyncio, importlib.abc, sys
class NoMedia(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'av', 'aiortc', 'pylibsrtp'}:
            raise AssertionError('Unnecessary dependency imported: ' + fullname)
sys.meta_path.insert(0, NoMedia())
from runtime_check import check_peer
asyncio.run(check_peer())
assert not any(n.split('.')[0] in {'av', 'aiortc', 'pylibsrtp'} for n in sys.modules)
'''
        env = dict(os.environ, PYTHONPATH=str(ROOT / 'src/buggcraft'))
        result = subprocess.run([sys.executable, '-c', script], cwd=ROOT, env=env,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class DataChannelTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        prepare_native_crypto()
        self.transport = PeerTransport(None)
        self.connections = []

    async def asyncTearDown(self):
        await asyncio.gather(*(self.transport.close_pc(pc) for pc in self.connections))

    def connection(self, upstream=False):
        if upstream:
            import aiortc
            pc = aiortc.RTCPeerConnection(aiortc.RTCConfiguration(iceServers=[]))
        else:
            pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        self.connections.append(pc)
        return pc

    async def exchange(self, old_offer=False, old_answer=False, legacy=False):
        first, second = self.connection(old_offer), self.connection(old_answer)
        first._sctpLegacySdp = legacy
        received = asyncio.get_running_loop().create_future()
        payload = secrets.token_bytes(65536)
        channel = first.createDataChannel('compatibility', ordered=True)
        channel.on('open', lambda: channel.send(payload))

        @second.on('datachannel')
        def incoming(remote):
            remote.on('message', lambda data: remote.send(data))

        @channel.on('message')
        def returned(data):
            if not received.done():
                received.set_result(data)

        await first.setLocalDescription(await first.createOffer())
        await second.setRemoteDescription(first.localDescription)
        await second.setLocalDescription(await second.createAnswer())
        await first.setRemoteDescription(second.localDescription)
        self.assertEqual(await asyncio.wait_for(received, 15), payload)
        self.assertEqual(first.connectionState, 'connected')
        self.assertEqual(second.connectionState, 'connected')

    @unittest.skipUnless(importlib.util.find_spec('aiortc'), 'Install requirements-interop.txt for old-client tests')
    async def test_new_offer_connects_to_old_client(self):
        await self.exchange(old_answer=True)

    @unittest.skipUnless(importlib.util.find_spec('aiortc'), 'Install requirements-interop.txt for old-client tests')
    async def test_old_offer_connects_to_new_client(self):
        await self.exchange(old_offer=True)

    async def test_legacy_sctp_sdp_still_connects(self):
        await self.exchange(legacy=True)

    async def test_media_and_multiple_application_sections_are_rejected(self):
        first, second = self.connection(), self.connection()
        first.createDataChannel('data')
        offer = await first.createOffer()
        media = offer.sdp.replace('m=application ', 'm=audio ')
        with self.assertRaises((ValueError, AssertionError)):
            await second.setRemoteDescription(RTCSessionDescription(media, 'offer'))
        duplicate = offer.sdp + 'm=application' + offer.sdp.split('m=application', 1)[1]
        with self.assertRaisesRegex(ValueError, 'Exactly one'):
            await second.setRemoteDescription(RTCSessionDescription(duplicate, 'offer'))
        self.assertEqual(second.signalingState, 'stable')
        self.assertIsNone(second.sctp)
        with self.assertRaisesRegex(NotImplementedError, 'Only data'):
            first.addTransceiver('audio')

    async def test_wrong_remote_certificate_fingerprint_fails_before_data_delivery(self):
        first, second = self.connection(), self.connection()
        first.createDataChannel('must-not-open')
        failures = asyncio.Event()
        delivered = []

        @second.on('connectionstatechange')
        def changed():
            if second.connectionState == 'failed':
                failures.set()

        second.on('datachannel', delivered.append)
        await first.setLocalDescription(await first.createOffer())
        tampered = re.sub(r'(a=fingerprint:[^ ]+ )[^\r\n]+', r'\g<1>00:00', first.localDescription.sdp)
        await second.setRemoteDescription(RTCSessionDescription(tampered, 'offer'))
        await second.setLocalDescription(await second.createAnswer())
        await first.setRemoteDescription(second.localDescription)
        await asyncio.wait_for(failures.wait(), 15)
        self.assertEqual(second.sctp.transport.state, 'failed')
        self.assertEqual(delivered, [])


if __name__ == '__main__':
    unittest.main()
