"""Automatic ICE / DTLS / reliable SCTP transport behind the room SDK."""
import asyncio
import ipaddress
import json
import logging
import secrets
import struct
import time
from functools import cache

import asyncssh

LOG = logging.getLogger(__name__)
CHUNK = 16384
WINDOW = CHUNK * 16


async def close_stream_writer(writer, grace=1):
    """Bound TCP teardown, including Windows pending overlapped writes.

    Bridge traffic has already drained before normal closure. A cancelled
    room must not wait forever for a peer which is no longer reading.
    """
    writer.close()
    closing = asyncio.create_task(writer.wait_closed())
    try:
        await asyncio.wait_for(asyncio.shield(closing), grace)
    except asyncio.TimeoutError:
        pass  # Abort once below, after either timeout or cancellation.
    except OSError:
        pass  # A reset during teardown is already a closed stream.
    finally:
        if not closing.done():
            transport = getattr(writer, 'transport', None)
            if transport is None:
                transport = writer.channel  # AsyncSSH relay stream.
            transport.abort()
            closing.cancel()
        await asyncio.gather(closing, return_exceptions=True)


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
        self.started = time.monotonic()
        self.sent_bytes = self.received_bytes = 0
        self.last_progress = self.started
        channel.on('open', self.ready.set)
        channel.on('message', self.receive)
        channel.on('close', self.close)
        if channel.readyState == 'open':
            self.ready.set()

    def close(self):
        if self.closed:
            return
        self.closed = True
        LOG.info('stream_closed channel=%s id=%s sent=%d received=%d inflight=%d pending=%d elapsed_ms=%d remote_eof=%s',
                 self.channel.label, getattr(self.channel, 'id', None), self.sent_bytes, self.received_bytes,
                 self.inflight, self.pending, (time.monotonic() - self.started) * 1000, self.remote_eof)
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
            self.received_bytes += len(data)
        else:
            self.close()
            return
        try:
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
                self.sent_bytes += len(data)
                self.channel.send(b'D' + data)
                if time.monotonic() - self.last_progress >= 5:
                    LOG.debug('stream_progress id=%s sent=%d received=%d inflight=%d',
                              getattr(self.channel, 'id', None), self.sent_bytes, self.received_bytes, self.inflight)
                    self.last_progress = time.monotonic()

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
            LOG.warning('stream_error channel=%s id=%s', self.channel.label, getattr(self.channel, 'id', None), exc_info=True)
        finally:
            LOG.debug('peer stream close %s', self.channel.label)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.close()
            await close_stream_writer(writer)


class PeerTransport:
    def __init__(self, endpoint):
        self.endpoint = endpoint
        self.process = self.task = None
        self.peers = {}
        self.jobs = set()
        self.answer_jobs = {}
        self.bridges = set()
        self.connected = asyncio.Event()
        self.negotiation_finished = asyncio.Event()
        self.client_pc = None
        self.next_game_channel_id = 3
        self.closed = False
        self.signal_buffer = bytearray()
        self.stun_profile = None
        self.closing_peers = set()
        self.peer_closers = {}
        self.close_task = None
        self.trace_id = getattr(endpoint, 'diagnostic_trace', None) or secrets.token_hex(8)
        self.pc_counter = 0
        self.stage = 'created'
        self.started = time.monotonic()

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
            # real socket shutdown tests and pinned to the vendored ICE adapter.
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
            started = time.monotonic()
            try:
                async with asyncio.timeout(.4):
                    transport, _ = await loop.create_datagram_endpoint(Probe,
                        remote_addr=(profile.server_host, profile.server_port))
                    transport.sendto(packet)
                    await replied
                    available.put_nowait(profile)
                    LOG.info('stun_probe trace=%s server=%s:%s result=ok elapsed_ms=%d',
                             self.trace_id, profile.server_host, profile.server_port, (time.monotonic() - started) * 1000)
            except (OSError, asyncio.TimeoutError) as exc:
                LOG.info('stun_probe trace=%s server=%s:%s result=%s',
                         self.trace_id, profile.server_host, profile.server_port, type(exc).__name__)
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
        LOG.info('peer_signal_sent trace=%s type=%s elapsed_ms=%d',
                 self.trace_id, message.get('type'), (time.monotonic() - self.started) * 1000)

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
        from ._rtc import RTCPeerConnection, RTCConfiguration, RTCIceServer
        profile = self.stun_profile
        host = profile.server_host if profile else ''
        if ':' in host:
            host = '[' + host + ']'
        servers = [] if profile is None else [
            RTCIceServer(urls=f'stun:{host}:{profile.server_port}')]
        pc = RTCPeerConnection(RTCConfiguration(iceServers=servers))
        self.pc_counter += 1
        pc_trace = f'{self.trace_id}-{self.pc_counter}'
        LOG.info('peer_created trace=%s stun=%s', pc_trace, [s.urls for s in servers])
        def ice_state():
            if pc.sctp:
                pc.sctp.transport.transport.iceGatherer._connection.diagnostic_trace = pc_trace
            LOG.info('ice_state trace=%s connection=%s gathering=%s', pc_trace, pc.iceConnectionState, pc.iceGatheringState)
            if pc.iceGatheringState == 'complete' and pc.sctp:
                for candidate in pc.sctp.transport.transport.iceGatherer.getLocalCandidates():
                    LOG.info('ice_candidate trace=%s type=%s address=%s port=%s related=%s:%s',
                             pc_trace, candidate.type, candidate.ip, candidate.port,
                             candidate.relatedAddress, candidate.relatedPort)
        pc.on('iceconnectionstatechange', ice_state)
        pc.on('icegatheringstatechange', ice_state)
        @pc.on('connectionstatechange')
        async def state_changed():
            LOG.info('peer_state trace=%s state=%s', pc_trace, pc.connectionState)
            if pc.connectionState == 'connected' and pc.sctp:
                ice = pc.sctp.transport.transport.iceGatherer._connection
                for component, pair in getattr(ice, '_nominated', {}).items():
                    LOG.info('selected_pair trace=%s component=%s local=%s remote=%s',
                             pc_trace, component, pair.local_candidate, pair.remote_candidate)
            if pc is self.client_pc:
                if pc.connectionState == 'connected':
                    self.connected.set()
                    self.negotiation_finished.set()
                else:
                    self.connected.clear()
                    if pc.connectionState in ('failed', 'closed'):
                        self.negotiation_finished.set()
            if pc.connectionState == 'failed':
                self.spawn(self.close_pc(pc))
        return pc

    async def start(self, connection):
        LOG.info('peer_start trace=%s role=%s', self.trace_id, self.endpoint.role)
        self.stage = 'signaling-handshake'
        self.process = await connection.create_process(subsystem='buggcraft-peer-v1', encoding=None)
        ready = await asyncio.wait_for(self.read(), 2)
        if ready.get('type') != 'ready':
            raise ValueError('Invalid peer handshake')
        self.stage = 'stun-probe'
        await self.select_stun()
        self.task = asyncio.create_task(self.run())
        self.stage = 'listening' if self.endpoint.role == 'host' else 'host-unavailable'
        if self.endpoint.role == 'client' and ready.get('available'):
            try:
                self.stage = 'local-candidates'
                self.client_pc = pc = self.create_pc()
                # This side offers and controls ICE, so SCTP uses odd IDs.
                # Reserve 1 for the probe and do not recycle game stream IDs:
                # the remote stream reset may still be completing.
                self.next_game_channel_id = 3
                channel = pc.createDataChannel('probe', ordered=True, id=1)
                # The probe establishes SCTP; each game socket gets its own channel.
                await pc.setLocalDescription(await pc.createOffer())
                self.stage = 'waiting-answer'
                self.send({'type': 'offer', 'sdp': validate_sdp(pc.localDescription.sdp)})
                await self.negotiation_finished.wait()
                if not self.connected.is_set():
                    raise ConnectionError('Peer negotiation ended before connection')
                self.stage = 'connected'
                LOG.info('peer_ready trace=%s elapsed_ms=%d',
                         self.trace_id, (time.monotonic() - self.started) * 1000)
            except BaseException:
                if self.client_pc:
                    await self.close_pc(self.client_pc)
                raise

    async def answer(self, message):
        from ._rtc import RTCSessionDescription
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
        except BaseException as exc:
            LOG.info('peer_answer_aborted trace=%s peer=%s reason=%s',
                     self.trace_id, key, type(exc).__name__)
            await self.close_pc(pc)
            self.peers.pop(key, None)
            raise

    async def run(self):
        from ._rtc import RTCSessionDescription
        try:
            while True:
                message = await self.read()
                LOG.info('peer_signal_received trace=%s type=%s elapsed_ms=%d',
                         self.trace_id, message.get('type'), (time.monotonic() - self.started) * 1000)
                if self.endpoint.role == 'host' and message.get('type') == 'offer':
                    key = message['peer']
                    if key not in self.answer_jobs and len(self.jobs) < 128:
                        job = self.spawn(asyncio.wait_for(self.answer(message), 8))
                        self.answer_jobs[key] = job
                        def answered(done, key=key):
                            if self.answer_jobs.get(key) is done:
                                self.answer_jobs.pop(key, None)
                        job.add_done_callback(answered)
                elif self.endpoint.role == 'host' and message.get('type') == 'left':
                    key = message.get('peer')
                    job = self.answer_jobs.get(key)
                    if job:
                        job.cancel()
                        await asyncio.gather(job, return_exceptions=True)
                    pc = self.peers.get(key)
                    if pc:
                        await self.close_pc(pc)
                        self.peers.pop(key, None)
                elif self.endpoint.role == 'client' and message.get('type') == 'answer' and self.client_pc:
                    self.stage = 'ice-connect'
                    await self.client_pc.setRemoteDescription(RTCSessionDescription(
                        validate_sdp(message['sdp']), 'answer'))
                elif self.endpoint.role == 'client' and message.get('type') == 'unavailable':
                    self.stage = 'host-unavailable'
                    self.negotiation_finished.set()
                    return
        except (OSError, ValueError, KeyError, asyncssh.Error):
            if self.closed or getattr(self.endpoint, '_stopped', False):
                LOG.info('peer_signal_closed trace=%s reason=endpoint-stopping', self.trace_id)
            else:
                LOG.warning('peer_signal_failed trace=%s', self.trace_id, exc_info=True)
        finally:
            self.connected.clear()
            self.negotiation_finished.set()

    async def forward(self, reader, writer):
        pc = self.client_pc
        if (self.connected.is_set() and pc and pc.connectionState == 'connected'
                and self.next_game_channel_id <= 65533):
            LOG.debug('peer client opening game channel')
            channel_id = self.next_game_channel_id
            self.next_game_channel_id += 2
            LOG.info('game_path trace=%s path=p2p channel_id=%d', self.trace_id, channel_id)
            bridge = StreamBridge(pc.createDataChannel('game', ordered=True, id=channel_id))
            self.bridges.add(bridge)
            try:
                await bridge.run(reader, writer)
            finally:
                self.bridges.discard(bridge)
            return
        if self.next_game_channel_id > 65533:
            self.connected.clear()
        # Path selection happens before handing any bytes to a transport.
        # Never replay a partially delivered game stream on another path.
        tasks = []
        remote_writer = None
        LOG.info('game_path trace=%s path=ssh-relay reason=%s', self.trace_id,
                 'channel-id-exhausted' if self.next_game_channel_id > 65533 else 'peer-not-connected')
        from .compression import CompressionListener, zstandard
        if (zstandard is not None and
                (getattr(self.endpoint, 'room_info', None) or {}).get('relay_compression') == 'zstd-1'):
            await CompressionListener(self.endpoint.connection, self.endpoint.invite.room_id,
                                      self.trace_id).handle(reader, writer)
            return
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
            LOG.warning('relay_stream_error trace=%s', self.trace_id, exc_info=True)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            writer.close()
            if remote_writer:
                await close_stream_writer(remote_writer)
            await close_stream_writer(writer)

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
        LOG.info('peer_shutdown trace=%s peers=%d bridges=%d jobs=%d',
                 self.trace_id, len(self.peers), len(self.bridges), len(self.jobs))
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
