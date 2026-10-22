"""Automatic ICE / DTLS / reliable SCTP transport behind the room SDK."""
import asyncio
import ipaddress
import json
import logging
import secrets
import struct
from functools import cache

LOG = logging.getLogger(__name__)
CHUNK = 16384
WINDOW = CHUNK * 16


@cache
def prepare_native_crypto():
    """Resolve Rust serialization types before pyOpenSSL's lazy DTLS path.

    Nuitka's compiled pyOpenSSL frame can lack the builtins mapping required
    by the first Rust type lookup. Resolve it from this explicit import path.
    Keys remain ephemeral; nothing is written to disk or shared with peers.
    """
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
    from OpenSSL.crypto import PKey
    key = ec.generate_private_key(ec.SECP256R1())
    key.private_bytes(Encoding.DER, PrivateFormat.PKCS8, NoEncryption())
    PKey.from_cryptography_key(key)


def validate_sdp(sdp):
    if not isinstance(sdp, str) or len(sdp) > 12288:
        raise ValueError('Invalid peer description')
    candidates = 0
    for line in sdp.splitlines():
        if line.startswith('m=') and not line.startswith('m=application '):
            raise ValueError('Only data channels are supported')
        if line.startswith('a=candidate:'):
            candidates += 1
            fields = line.split()
            if len(fields) < 8 or fields[2].lower() != 'udp':
                raise ValueError('Invalid ICE candidate')
            address = ipaddress.ip_address(fields[4])
            if address.is_unspecified or address.is_multicast or address.is_link_local or address.is_loopback:
                raise ValueError('Invalid ICE address')
            if not 1 <= int(fields[5]) <= 65535 or candidates > 32:
                raise ValueError('Invalid ICE candidate count or port')
    return sdp


class StreamBridge:
    """One TCP stream per ordered reliable data channel, with receive credits."""
    def __init__(self, channel):
        self.channel = channel
        self.ready = asyncio.Event()
        self.credit = asyncio.Event()
        self.credit.set()
        self.queue = asyncio.Queue(maxsize=18)
        self.inflight = self.pending = 0
        self.closed = False
        self.remote_eof = False
        self.writer = None
        self.task = None
        channel.on('open', self.ready.set)
        channel.on('message', self.receive)
        channel.on('close', self.close)
        if channel.readyState == 'open':
            self.ready.set()

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.ready.set()
        self.credit.set()
        if self.writer:
            self.writer.close()
        if self.task and self.task is not asyncio.current_task():
            self.task.cancel()
        if self.channel.readyState != 'closed':
            self.channel.close()

    def receive(self, frame):
        if self.closed:
            return
        if (isinstance(frame, bytes) and frame[:1] == b'A' and len(frame) == 5):
            count = struct.unpack('!I', frame[1:])[0]
            if not 1 <= count <= self.inflight:
                self.close()
                return
            self.inflight -= count
            self.credit.set()
            return
        if frame == 'EOF' and not self.remote_eof:
            self.remote_eof = True
            data = None
        elif (not self.remote_eof and isinstance(frame, bytes) and frame[:1] == b'D'
              and 1 < len(frame) <= CHUNK + 1 and self.pending + len(frame) - 1 <= WINDOW):
            data = frame[1:]
            self.pending += len(data)
        else:
            self.close()
            return
        try:
            LOG.debug('peer frame %s bytes on %s', len(data) if data is not None else 'EOF', self.channel.label)
            self.queue.put_nowait(data)
        except asyncio.QueueFull:
            self.close()

    async def run(self, reader, writer):
        self.task = asyncio.current_task()
        self.writer = writer

        async def outgoing():
            while not self.closed:
                while self.inflight >= WINDOW and not self.closed:
                    self.credit.clear()
                    await self.credit.wait()
                data = await reader.read(min(CHUNK, WINDOW - self.inflight))
                if self.closed:
                    return
                if not data:
                    self.channel.send('EOF')
                    return
                self.inflight += len(data)
                self.channel.send(b'D' + data)

        async def incoming():
            while not self.closed:
                data = await self.queue.get()
                if data is None:
                    if writer.can_write_eof():
                        writer.write_eof()
                    return
                writer.write(data)
                await writer.drain()
                self.pending -= len(data)
                self.channel.send(b'A' + struct.pack('!I', len(data)))

        tasks = []
        try:
            await asyncio.wait_for(self.ready.wait(), 5)
            LOG.debug('peer stream open %s', self.channel.label)
            if not self.closed:
                tasks = [asyncio.create_task(outgoing()), asyncio.create_task(incoming())]
                await asyncio.gather(*tasks)
                async with asyncio.timeout(5):
                    while self.inflight and not self.closed:
                        self.credit.clear()
                        await self.credit.wait()
        except (OSError, ValueError, asyncio.TimeoutError):
            pass
        finally:
            LOG.debug('peer stream close %s', self.channel.label)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.close()
            await writer.wait_closed()


class PeerTransport:
    def __init__(self, endpoint):
        self.endpoint = endpoint
        self.process = self.task = None
        self.peers = {}
        self.jobs = set()
        self.bridges = set()
        self.connected = asyncio.Event()
        self.client_pc = None
        self.closed = False
        self.signal_buffer = bytearray()
        self.stun_profile = None
        self.closing_peers = set()
        self.peer_closers = {}
        self.close_task = None

    async def close_pc(self, pc):
        # RTCPeerConnection.close() is not safe to abandon halfway through.
        # Keep cleanup alive when an endpoint task is being cancelled.
        task = self.peer_closers.get(pc)
        if task is None:
            task = asyncio.create_task(self._close_pc(pc))
            self.peer_closers[pc] = task
            self.closing_peers.add(task)
            def finished(result):
                self.closing_peers.discard(result)
                if self.peer_closers.get(pc) is result:
                    self.peer_closers.pop(pc, None)
            task.add_done_callback(finished)
        await asyncio.shield(task)

    async def _close_pc(self, pc):
        closing = asyncio.create_task(pc.close())
        try:
            await asyncio.wait_for(asyncio.shield(closing), 1)
        except asyncio.TimeoutError:
            # Windows UDP close can wait indefinitely for buffered datagrams
            # to an unreachable peer. Discard them after graceful shutdown.
            # aioice exposes no public abort API; this adapter is covered by
            # real socket shutdown tests and pinned to the bundled aiortc.
            if pc.sctp:
                connection = pc.sctp.transport.transport.iceGatherer._connection
                for protocol in tuple(connection._protocols):
                    if protocol.transport:
                        protocol.transport.abort()
            await closing

    async def select_stun(self):
        """Choose a responding network member; a dead seed must not stall ICE."""
        from .nodes import candidates
        loop = asyncio.get_running_loop()
        available = asyncio.Queue()

        async def check(profile):
            if profile.server_host in ('127.0.0.1', '::1', 'localhost'):
                return
            transaction = secrets.token_bytes(12)
            packet = struct.pack('!HHI', 1, 0, 0x2112A442) + transaction
            replied = loop.create_future()
            closed = loop.create_future()
            class Probe(asyncio.DatagramProtocol):
                def connection_lost(self, error):
                    if not closed.done():
                        closed.set_result(None)

                def datagram_received(self, data, address):
                    if (len(data) >= 32 and data[:2] == b'\x01\x01' and
                            data[4:8] == packet[4:8] and data[8:20] == transaction and not replied.done()):
                        replied.set_result(True)
            transport = None
            try:
                async with asyncio.timeout(.4):
                    transport, _ = await loop.create_datagram_endpoint(Probe,
                        remote_addr=(profile.server_host, profile.server_port))
                    transport.sendto(packet)
                    await replied
                    available.put_nowait(profile)
            except (OSError, asyncio.TimeoutError):
                pass
            finally:
                if transport:
                    transport.close()
                    await closed

        profiles = [self.endpoint._active_profile] + candidates(self.endpoint.profile)
        seen, checks = set(), []
        for profile in profiles[:33]:
            key = (profile.server_host, profile.server_port)
            if key not in seen:
                seen.add(key)
                checks.append(asyncio.create_task(check(profile)))
        try:
            await asyncio.gather(*checks)
            if not available.empty():
                self.stun_profile = available.get_nowait()
        finally:
            for task in checks:
                task.cancel()
            await asyncio.gather(*checks, return_exceptions=True)

    def spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.jobs.add(task)
        def done(result):
            self.jobs.discard(result)
            if not result.cancelled():
                error = result.exception()
                if error:
                    LOG.debug('Peer task ended: %s', type(error).__name__)
        task.add_done_callback(done)
        return task

    def send(self, message):
        self.process.stdin.write(json.dumps(message).encode() + b'\n')

    async def read(self):
        # AsyncSSH's readuntil limit is not a frame budget. Keep a small
        # buffer so an SDP exchange does not turn into one syscall per byte.
        data = getattr(self, 'signal_buffer', bytearray())
        self.signal_buffer = data
        while b'\n' not in data:
            if len(data) >= 16384:
                raise ValueError('Peer signal frame exceeded')
            part = await self.process.stdout.read(min(1024, 16384 - len(data)))
            if not part:
                raise ConnectionError('Peer signal closed')
            data.extend(part)
            if len(data) > 16384:
                raise ValueError('Peer signal frame exceeded')
        line, _, remaining = data.partition(b'\n')
        self.signal_buffer = bytearray(remaining)
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError('Invalid peer signal')
        return value

    def create_pc(self):
        prepare_native_crypto()
        from aiortc import RTCPeerConnection, RTCConfiguration, RTCIceServer
        profile = self.stun_profile
        host = profile.server_host if profile else ''
        if ':' in host:
            host = '[' + host + ']'
        servers = [] if profile is None else [
            RTCIceServer(urls=f'stun:{host}:{profile.server_port}')]
        pc = RTCPeerConnection(RTCConfiguration(iceServers=servers))
        @pc.on('connectionstatechange')
        async def state_changed():
            if pc is self.client_pc:
                if pc.connectionState == 'connected':
                    self.connected.set()
                else:
                    self.connected.clear()
            if pc.connectionState == 'failed':
                self.spawn(self.close_pc(pc))
        return pc

    async def start(self, connection):
        self.process = await connection.create_process(subsystem='buggcraft-peer-v1', encoding=None)
        ready = await asyncio.wait_for(self.read(), 2)
        if ready.get('type') != 'ready':
            raise ValueError('Invalid peer handshake')
        await self.select_stun()
        self.task = asyncio.create_task(self.run())
        if self.endpoint.role == 'client' and ready.get('available'):
            try:
                self.client_pc = pc = self.create_pc()
                channel = pc.createDataChannel('probe', ordered=True)
                # The probe establishes SCTP; each game socket gets its own channel.
                await pc.setLocalDescription(await pc.createOffer())
                self.send({'type': 'offer', 'sdp': validate_sdp(pc.localDescription.sdp)})
                await self.connected.wait()
            except BaseException:
                if self.client_pc:
                    await self.close_pc(self.client_pc)
                raise

    async def answer(self, message):
        from aiortc import RTCSessionDescription
        key = message['peer']
        if key in self.peers or len(self.peers) >= 128:
            return
        pc = self.create_pc()
        self.peers[key] = pc
        channels = set()
        probe_seen = False
        @pc.on('datachannel')
        def datachannel(channel):
            nonlocal probe_seen
            LOG.debug('peer host channel %s', channel.label)
            if channel.label == 'probe':
                if probe_seen:
                    channel.close()
                probe_seen = True
                return
            if channel.label != 'game' or len(channels) >= 8:
                channel.close()
                return
            bridge = StreamBridge(channel)
            channels.add(channel)
            channel.on('close', lambda: channels.discard(channel))
            self.bridges.add(bridge)
            async def connect():
                try:
                    endpoint = self.endpoint
                    if not endpoint.game_port or endpoint.room_state != 'ready':
                        return
                    reader, writer = await asyncio.wait_for(asyncio.open_connection(
                        endpoint.game_host, endpoint.game_port), 3)
                    LOG.debug('peer host connected game %s', endpoint.game_port)
                    await bridge.run(reader, writer)
                finally:
                    bridge.close()
                    self.bridges.discard(bridge)
            self.spawn(connect())
        try:
            await pc.setRemoteDescription(RTCSessionDescription(validate_sdp(message['sdp']), 'offer'))
            await pc.setLocalDescription(await pc.createAnswer())
            self.send({'type': 'answer', 'peer': key, 'sdp': validate_sdp(pc.localDescription.sdp)})
        except BaseException:
            await self.close_pc(pc)
            self.peers.pop(key, None)
            raise

    async def run(self):
        from aiortc import RTCSessionDescription
        try:
            while True:
                message = await self.read()
                if self.endpoint.role == 'host' and message.get('type') == 'offer':
                    if len(self.jobs) < 128:
                        self.spawn(asyncio.wait_for(self.answer(message), 8))
                elif self.endpoint.role == 'host' and message.get('type') == 'left':
                    pc = self.peers.get(message.get('peer'))
                    if pc:
                        await self.close_pc(pc)
                        self.peers.pop(message.get('peer'), None)
                elif self.endpoint.role == 'client' and message.get('type') == 'answer' and self.client_pc:
                    await self.client_pc.setRemoteDescription(RTCSessionDescription(
                        validate_sdp(message['sdp']), 'answer'))
        except (OSError, ValueError, KeyError):
            self.connected.clear()

    async def forward(self, reader, writer):
        pc = self.client_pc
        if self.connected.is_set() and pc and pc.connectionState == 'connected':
            LOG.debug('peer client opening game channel')
            bridge = StreamBridge(pc.createDataChannel('game', ordered=True))
            self.bridges.add(bridge)
            try:
                await bridge.run(reader, writer)
            finally:
                self.bridges.discard(bridge)
            return
        # Path selection happens before handing any bytes to a transport.
        # Never replay a partially delivered game stream on another path.
        tasks = []
        remote_writer = None
        try:
            remote_reader, remote_writer = await self.endpoint.connection.open_connection(
                self.endpoint.invite.room_id, 25565)
            async def copy(source, target):
                while data := await source.read(CHUNK):
                    target.write(data)
                    await target.drain()
                if target.can_write_eof():
                    target.write_eof()
            tasks = [asyncio.create_task(copy(reader, remote_writer)),
                     asyncio.create_task(copy(remote_reader, writer))]
            await asyncio.gather(*tasks)
        except (OSError, ValueError):
            pass
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            writer.close()
            if remote_writer:
                remote_writer.close()
                await remote_writer.wait_closed()
            await writer.wait_closed()

    async def close(self):
        # Endpoint cancellation may interrupt shutdown after the SSH socket
        # closes. Retain the entire cleanup, not just individual PC closes.
        if self.close_task is None:
            self.close_task = asyncio.create_task(self._close())
        await asyncio.shield(self.close_task)

    async def _close(self):
        if self.closed:
            return
        self.closed = True
        for bridge in tuple(self.bridges):
            bridge.close()
        if self.task:
            self.task.cancel()
        for job in tuple(self.jobs):
            job.cancel()
        await asyncio.gather(*(list(self.jobs) + ([self.task] if self.task else [])), return_exceptions=True)
        peers = list(self.peers.values())
        if self.client_pc:
            peers.append(self.client_pc)
        await asyncio.gather(*(self.close_pc(pc) for pc in peers), return_exceptions=True)
        await asyncio.gather(*tuple(self.closing_peers), return_exceptions=True)
        self.peers.clear()
        self.client_pc = None
        if self.process:
            self.process.close()
            await self.process.wait_closed()


class GameListener:
    def __init__(self, peer):
        self.peer = peer
        self.server = None
        self.tasks = set()

    @classmethod
    async def start(cls, peer, port):
        listener = cls(peer)
        def accepted(reader, writer):
            if len(listener.tasks) >= 8:
                writer.close()
                return
            task = asyncio.create_task(peer.forward(reader, writer))
            listener.tasks.add(task)
            def done(result):
                listener.tasks.discard(result)
                if not result.cancelled():
                    result.exception()
            task.add_done_callback(done)
        listener.server = await asyncio.start_server(accepted, '127.0.0.1', port)
        return listener

    def get_port(self):
        return self.server.sockets[0].getsockname()[1]

    def close(self):
        self.server.close()
        for task in tuple(self.tasks):
            task.cancel()

    async def wait_closed(self):
        await self.server.wait_closed()
        await asyncio.gather(*tuple(self.tasks), return_exceptions=True)
