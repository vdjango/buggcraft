"""Negotiated, bounded, adaptive Zstandard framing for native relay streams.

Every block has an independent context; no authentication/control data enters
the codec. Already compressed data is sent raw, and incompressible streams only
sample periodically. The node forwards these frames without decompressing.
"""
import asyncio
import logging
import time

try:
    import zstandard
except ImportError:
    zstandard = None

LOG = logging.getLogger(__name__)
MAGIC = b'BCZ1'
BLOCK = 65536


def varint(value):
    result = bytearray()
    while True:
        byte, value = value & 127, value >> 7
        result.append(byte | (128 if value else 0))
        if not value:
            return bytes(result)


async def read_length(reader, *, eof=False):
    value = 0
    for index in range(3):
        try:
            byte = (await reader.readexactly(1))[0]
        except asyncio.IncompleteReadError as exc:
            if eof and index == 0 and not exc.partial:
                return None
            raise ValueError('Truncated relay length') from exc
        value |= (byte & 127) << (7 * index)
        if not byte & 128:
            return value
    raise ValueError('Invalid relay length')


class Codec:
    def __init__(self):
        if zstandard is None:
            raise RuntimeError('Zstandard is unavailable')
        self.compressor = zstandard.ZstdCompressor(level=1, write_content_size=True)
        self.decompressor = zstandard.ZstdDecompressor(max_window_size=128 * 1024)
        self.skip = self.misses = 0
        self.blocks = 0
        self.passthrough = False
        self.raw_bytes = self.wire_bytes = self.compressed_blocks = 0

    def encode(self, data):
        if not 1 <= len(data) <= BLOCK:
            raise ValueError('Invalid relay block size')
        # Small movement/keepalive packets and Minecraft's existing compressed
        # streams must not keep paying a per-read framing cost. Marker zero
        # ends framing for this direction only; all subsequent bytes are raw.
        if self.passthrough or ((self.raw_bytes >= 2048 or self.blocks >= 64)
                                and self.wire_bytes >= self.raw_bytes):
            result = (b'' if self.passthrough else b'\0') + data
            self.passthrough = True
            self.raw_bytes += len(data)
            self.wire_bytes += len(result)
            return result
        encoded, kind = data, 0
        if self.skip:
            self.skip -= 1
        elif len(data) >= 256:
            candidate = self.compressor.compress(data)
            if len(candidate) + 32 < len(data):
                encoded, kind = candidate, 1
                self.misses = 0
                self.compressed_blocks += 1
            else:
                self.misses += 1
                if self.misses >= 4:
                    self.skip = 31
        result = varint((len(encoded) << 1) | kind) + (varint(len(data)) if kind else b'') + encoded
        self.raw_bytes += len(data)
        self.wire_bytes += len(result)
        self.blocks += 1
        return result

    def decode(self, kind, length, payload):
        if kind not in (0, 1) or not 1 <= length <= BLOCK or not 1 <= len(payload) <= BLOCK:
            raise ValueError('Invalid relay block')
        if kind == 0:
            if length != len(payload):
                raise ValueError('Invalid raw relay block')
            return payload
        try:
            parameters = zstandard.get_frame_parameters(payload)
            if parameters.content_size != length or parameters.window_size > BLOCK:
                raise ValueError('Invalid relay decompression size')
            result = self.decompressor.decompress(payload, max_output_size=BLOCK, allow_extra_data=False)
        except zstandard.ZstdError as exc:
            raise ValueError('Invalid Zstandard relay block') from exc
        if len(result) != length:
            raise ValueError('Invalid decompressed relay block')
        return result


async def bridge(raw_reader, raw_writer, wire_reader, wire_writer, *, trace=''):
    codec = Codec()
    started = time.monotonic()

    async def outbound():
        wire_writer.write(MAGIC)
        await wire_writer.drain()
        while data := await raw_reader.read(BLOCK):
            wire_writer.write(codec.encode(data))
            await wire_writer.drain()
        wire_writer.write_eof()

    async def inbound():
        if await wire_reader.readexactly(len(MAGIC)) != MAGIC:
            raise ValueError('Invalid compressed relay protocol')
        decoder = Codec()
        while True:
            frame = await read_length(wire_reader, eof=True)
            if frame is None:
                break
            if frame == 0:
                while data := await wire_reader.read(BLOCK):
                    raw_writer.write(data)
                    await raw_writer.drain()
                break
            kind, size = frame & 1, frame >> 1
            length = await read_length(wire_reader) if kind else size
            if not 1 <= length <= BLOCK or not 1 <= size <= BLOCK:
                raise ValueError('Invalid relay frame limits')
            payload = await wire_reader.readexactly(size)
            raw_writer.write(decoder.decode(kind, length, payload))
            await raw_writer.drain()
        if raw_writer.can_write_eof():
            raw_writer.write_eof()

    tasks = [asyncio.create_task(outbound()), asyncio.create_task(inbound())]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        LOG.info('relay_compression trace=%s codec=zstd-1 raw_bytes=%d wire_bytes=%d blocks_compressed=%d passthrough=%s elapsed_ms=%d',
                 trace, codec.raw_bytes, codec.wire_bytes + len(MAGIC), codec.compressed_blocks,
                 codec.passthrough, (time.monotonic() - started) * 1000)


class CompressionHost:
    def __init__(self, endpoint):
        self.endpoint = endpoint
        self.tasks = set()
        self.listener = None

    async def start(self, connection):
        self.listener = await connection.start_server(lambda _host, _port: self.handle,
                                                       'buggcraft-zstd', 0, encoding=None)
        return self

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        raw_writer = None
        try:
            raw_reader, raw_writer = await asyncio.wait_for(asyncio.open_connection(
                self.endpoint.game_host, self.endpoint.game_port), 5)
            await bridge(raw_reader, raw_writer, reader, writer, trace=self.endpoint.diagnostic_trace)
        except (OSError, ValueError, asyncio.IncompleteReadError, asyncio.TimeoutError) as exc:
            LOG.info('relay_compression_closed trace=%s role=host reason=%s',
                     self.endpoint.diagnostic_trace, type(exc).__name__)
        finally:
            await _close(raw_writer, writer)
            self.tasks.discard(task)

    def close(self):
        if self.listener:
            self.listener.close()
        for task in self.tasks:
            task.cancel()

    async def wait_closed(self):
        if self.listener:
            await self.listener.wait_closed()
        await asyncio.gather(*self.tasks, return_exceptions=True)


class CompressionListener:
    def __init__(self, connection, room, trace):
        self.connection, self.room, self.trace = connection, room, trace
        self.server = None
        self.tasks = set()

    @classmethod
    async def start(cls, connection, room, port, trace=''):
        instance = cls(connection, room, trace)
        instance.server = await asyncio.start_server(instance.handle, '127.0.0.1', port)
        return instance

    def get_port(self):
        return self.server.sockets[0].getsockname()[1]

    async def handle(self, reader, writer):
        import asyncssh
        task = asyncio.current_task()
        self.tasks.add(task)
        wire_writer = None
        try:
            try:
                wire_reader, wire_writer = await asyncio.wait_for(
                    self.connection.open_connection(self.room, 25566, encoding=None), 10)
            except (asyncssh.ChannelOpenError, OSError, asyncio.TimeoutError) as exc:
                LOG.info('relay_compression_fallback trace=%s reason=%s path=ssh-raw', self.trace, type(exc).__name__)
                wire_reader, wire_writer = await asyncio.wait_for(
                    self.connection.open_connection(self.room, 25565, encoding=None), 10)
                await raw_bridge(reader, writer, wire_reader, wire_writer)
            else:
                await bridge(reader, writer, wire_reader, wire_writer, trace=self.trace)
        except (OSError, ValueError, asyncio.IncompleteReadError, asyncio.TimeoutError, asyncssh.Error) as exc:
            LOG.info('relay_compression_closed trace=%s role=client reason=%s', self.trace, type(exc).__name__)
        finally:
            await _close(wire_writer, writer)
            self.tasks.discard(task)

    def close(self):
        self.server.close()
        for task in self.tasks:
            task.cancel()

    async def wait_closed(self):
        await self.server.wait_closed()
        await asyncio.gather(*self.tasks, return_exceptions=True)


async def raw_bridge(left_reader, left_writer, right_reader, right_writer):
    async def pump(reader, writer):
        while data := await reader.read(BLOCK):
            writer.write(data)
            await writer.drain()
        if writer.can_write_eof():
            writer.write_eof()
    tasks = [asyncio.create_task(pump(left_reader, right_writer)), asyncio.create_task(pump(right_reader, left_writer))]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _close(*writers):
    for writer in writers:
        if writer:
            writer.close()
    await asyncio.gather(*(w.wait_closed() for w in writers if w), return_exceptions=True)
