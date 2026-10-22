"""Room-scoped, hash-verified mod transfer over authenticated SSH channels."""
import asyncio
import hashlib
import json
from pathlib import Path
import re

MAX_MODS = 1000
MAX_MANIFEST = 512 * 1024
MAX_MOD_SIZE = 2 * 1024 * 1024 * 1024


def validate_manifest(value):
    if not isinstance(value, list) or len(value) > MAX_MODS:
        raise ValueError('房间模组列表无效或过大。')
    names = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError('房间模组信息无效。')
        name, digest, size = item.get('name'), item.get('sha256'), item.get('size')
        if (not isinstance(name, str) or not 1 <= len(name) <= 240 or
                any(ch in name for ch in '/\\:') or name in ('.', '..') or
                not name.lower().endswith('.jar') or any(not ch.isprintable() for ch in name) or
                name.casefold() in names or not isinstance(digest, str) or
                not re.fullmatch('[0-9a-f]{64}', digest) or type(size) is not int or
                not 0 <= size <= MAX_MOD_SIZE):
            raise ValueError('房间模组文件名、校验值或大小无效。')
        names.add(name.casefold())
    return value


def manifest(directory):
    root = (Path(directory) / 'mods').resolve()
    result = []
    for path in sorted(root.glob('*.jar'), key=lambda p: p.name.casefold()):
        if not path.resolve().is_relative_to(root):
            raise ValueError('模组链接指向游戏目录之外。')
        digest = hashlib.sha256()
        with path.open('rb') as source:
            for block in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(block)
        result.append(dict(name=path.name, sha256=digest.hexdigest(), size=path.stat().st_size))
    return validate_manifest(result)


def manifest_hash(items):
    return hashlib.sha256('\n'.join(sorted(item['sha256'] for item in items)).encode()).hexdigest()


class ModPackServer:
    def __init__(self, directory):
        self.root = (Path(directory) / 'mods').resolve()
        self.listener = None
        self.items = []
        self.limit = asyncio.Semaphore(4)
        self.tasks = set()

    async def start(self):
        self.items = await asyncio.to_thread(manifest, self.root.parent)
        self.listener = await asyncio.start_server(self.serve, '127.0.0.1', 0, limit=512)
        return self.listener.sockets[0].getsockname()[1]

    async def serve(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        try:
            async with asyncio.timeout(300), self.limit:
                request = json.loads(await asyncio.wait_for(reader.readline(), 10))
                if request == {'op': 'manifest'}:
                    data = json.dumps(self.items, ensure_ascii=True).encode()
                    if len(data) > MAX_MANIFEST:
                        raise ValueError('Manifest too large')
                    writer.write(json.dumps({'size': len(data)}).encode() + b'\n' + data)
                    await writer.drain()
                elif isinstance(request, dict) and request.get('op') == 'file':
                    item = next((i for i in self.items if i['sha256'] == request.get('sha256')), None)
                    if item is None:
                        raise ValueError('Unknown file')
                    path = (self.root / item['name']).resolve()
                    if not path.is_relative_to(self.root) or path.stat().st_size != item['size']:
                        raise ValueError('Mod changed; reopen the room')
                    with path.open('rb') as source:
                        writer.write(json.dumps({'size': item['size']}).encode() + b'\n')
                        while block := await asyncio.to_thread(source.read, 128 * 1024):
                            writer.write(block)
                            await writer.drain()
                else:
                    raise ValueError('Invalid request')
        except (OSError, ValueError, asyncio.TimeoutError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            await asyncio.gather(writer.wait_closed(), return_exceptions=True)
            self.tasks.discard(task)

    async def close(self):
        if self.listener:
            self.listener.close()
            await self.listener.wait_closed()
        for task in tuple(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)


async def open_request(endpoint, message, maximum):
    if not endpoint.connection or endpoint.connection.is_closed():
        raise ConnectionError('房间连接已断开。')
    reader, writer = await endpoint.connection.open_connection(endpoint.invite.room_id, 25564)
    try:
        writer.write(json.dumps(message).encode() + b'\n')
        await writer.drain()
        line = bytearray()
        async with asyncio.timeout(15):
            while not line.endswith(b'\n'):
                if len(line) >= 256:
                    raise ValueError('模组传输响应过大。')
                line.extend(await reader.readexactly(1))
        size = json.loads(line).get('size')
        if type(size) is not int or not 0 <= size <= maximum:
            raise ValueError('模组传输大小无效。')
        return reader, writer, size
    except BaseException:
        writer.close()
        raise


async def fetch_manifest(endpoint):
    reader, writer, size = await open_request(endpoint, {'op': 'manifest'}, MAX_MANIFEST)
    try:
        data = await asyncio.wait_for(reader.readexactly(size), 30)
        items = validate_manifest(json.loads(data))
        expected = (endpoint.room_info or {}).get('game', {})
        if (expected.get('mods_count', len(items)) != len(items) or
                expected.get('mods_hash') and manifest_hash(items) != expected['mods_hash']):
            raise ValueError('房间模组已改变，请刷新后重试。')
        return items
    finally:
        writer.close()


async def fetch_mod(endpoint, item, target, cancel, progress):
    reader, writer, size = await open_request(endpoint, {'op': 'file', 'sha256': item['sha256']}, item['size'])
    path = Path(target)
    temporary = path.with_suffix('.jar.part')
    try:
        if size != item['size']:
            raise ValueError('模组大小不匹配。')
        digest, received = hashlib.sha256(), 0
        with temporary.open('wb') as output:
            while received < size:
                if cancel.is_set():
                    raise InterruptedError('安装已取消。')
                block = await asyncio.wait_for(reader.read(min(128 * 1024, size - received)), 30)
                if not block:
                    raise ConnectionError('模组传输中断。')
                output.write(block)
                digest.update(block)
                received += len(block)
                progress(received, size)
        if digest.hexdigest() != item['sha256']:
            raise ValueError('模组校验失败：' + item['name'])
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
        writer.close()
