"""Invitation based room control, independent of UI and game data forwarding."""
import asyncio
import hashlib
import json
import logging
from pathlib import Path
import socket
import time
import struct
import re


logger = logging.getLogger(__name__)


def varint(value):
    value &= 0xffffffff
    result = bytearray()
    while True:
        part, value = value & 127, value >> 7
        result.append(part | (128 if value else 0))
        if not value:
            return bytes(result)


async def read_varint(reader):
    value = 0
    for index in range(5):
        byte = (await reader.readexactly(1))[0]
        value |= (byte & 127) << (index * 7)
        if not byte & 128:
            return value
    raise ValueError('Invalid Minecraft variable integer')


async def game_status(port, timeout=4):
    class Probe:
        def __init__(self):
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.setblocking(False)
            self.loop = asyncio.get_running_loop()

        async def connect(self):
            await self.loop.sock_connect(self.sock, ('127.0.0.1', port))

        async def readexactly(self, count):
            data = bytearray()
            while len(data) < count:
                chunk = await self.loop.sock_recv(self.sock, count - len(data))
                if not chunk:
                    raise asyncio.IncompleteReadError(bytes(data), count)
                data.extend(chunk)
            return bytes(data)

        async def send(self, data):
            await self.loop.sock_sendall(self.sock, data)

    async def query():
        probe = Probe()
        try:
            async with asyncio.timeout(min(timeout / 2, 2)):
                await probe.connect()
                address = b'localhost'
                handshake = b'\x00' + varint(-1) + varint(len(address)) + address + struct.pack('>H', port) + b'\x01'
                await probe.send(varint(len(handshake)) + handshake + b'\x01\x00')
                length = await read_varint(probe)
                if not 1 <= length <= 1024 * 1024:
                    raise ValueError('Minecraft status exceeds size limit')
                packet = await probe.readexactly(length)
            if packet[0] != 0:
                raise ValueError('Unexpected Minecraft status packet')
            offset = 1
            size = 0
            for index in range(5):
                byte = packet[offset]
                offset += 1
                size |= (byte & 127) << (7 * index)
                if not byte & 128:
                    break
            if offset + size != len(packet):
                raise ValueError('Invalid Minecraft status string')
            status = json.loads(packet[offset:].decode('utf-8'))
            if not isinstance(status, dict) or not isinstance(status.get('version', {}), dict):
                raise ValueError('Invalid Minecraft status')
            version = status.get('version', {})
            latency = None
            # Minecraft server-list ping/pong, after status, on the game path.
            # Missing pong must not discard valid version/player information.
            nonce = struct.pack('>q', time.monotonic_ns())
            started = time.perf_counter()
            try:
                await probe.send(b'\x09\x01' + nonce)
                async with asyncio.timeout(min(.7, timeout / 4)):
                    pong_length = await read_varint(probe)
                    if pong_length == 9 and await probe.readexactly(9) == b'\x01' + nonce:
                        latency = round((time.perf_counter() - started) * 1000)
            except (OSError, ValueError, asyncio.TimeoutError, asyncio.IncompleteReadError):
                pass
            return {'port':port, 'version':str(version.get('name', ''))[:64],
                    'protocol':version.get('protocol'), 'players':status.get('players', {}),
                    'latency_ms':latency}
        finally:
            probe.sock.close()
    async def legacy_query():
        from .legacy_chat import text
        probe = Probe()
        try:
            await probe.connect()
            payload = b'\x4e' + text('localhost') + struct.pack('>i', port)
            await probe.send(b'\xfe\x01\xfa' + text('MC|PingHost') + struct.pack('>H', len(payload)) + payload)
            if await probe.readexactly(1) != b'\xff':
                raise ValueError('Unexpected legacy status packet')
            length = struct.unpack('>H', await probe.readexactly(2))[0]
            if length > 32767:
                raise ValueError('Legacy status exceeds limit')
            fields = (await probe.readexactly(length * 2)).decode('utf-16-be').split('\0')
            if len(fields) != 6 or fields[0] != '§1':
                raise ValueError('Invalid legacy game status')
            protocol = int(fields[1])
            # Modern servers cap the legacy ping field at 127. Resolve only an
            # exact known release name; never mistake that sentinel for its ID.
            if protocol == 127:
                from .game_chat import PROFILES
                protocol = next((int(key) for key, profile in PROFILES.items()
                                 if fields[2] in profile.get('releases', [])), protocol)
            return {'port':port, 'version':fields[2][:64], 'protocol':protocol,
                    'players':{'online':int(fields[4]), 'max':int(fields[5])}}
        finally:
            probe.sock.close()
    async def detect():
        try:
            return await query()
        except (OSError, ValueError, asyncio.TimeoutError, asyncio.IncompleteReadError, IndexError):
            return await legacy_query()
    return await asyncio.wait_for(detect(), timeout)


def _java_listening_ports():
    """Read local Java listeners without collecting account/launch arguments."""
    import psutil
    ports = set()
    for process in psutil.process_iter(['name']):
        if (process.info.get('name') or '').lower() not in ('java', 'java.exe', 'javaw', 'javaw.exe'):
            continue
        try:
            for connection in process.net_connections(kind='tcp'):
                if connection.status == psutil.CONN_LISTEN and connection.laddr:
                    ports.add(connection.laddr.port)
                    if len(ports) >= 64:
                        return ports
        except (psutil.Error, OSError) as exc:
            logger.debug('lan_discovery_java_unavailable pid=%s reason=%s', process.pid, type(exc).__name__)
    return ports


async def _advertised_world_ports(excluded_ports, seconds):
    ports = set()
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('', 4445))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                        socket.inet_aton('224.0.2.60') + socket.inet_aton('0.0.0.0'))
        sock.setblocking(False)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + seconds
        while loop.time() < deadline:
            remaining = deadline - loop.time()
            try:
                packet, _ = await asyncio.wait_for(loop.sock_recvfrom(sock, 2048), remaining)
            except asyncio.TimeoutError:
                break
            text = packet.decode('utf-8', errors='replace')
            if '[AD]' not in text or '[/AD]' not in text:
                continue
            port = text.split('[AD]', 1)[1].split('[/AD]', 1)[0]
            if port.isdecimal() and 1 <= int(port) <= 65535 and int(port) not in excluded_ports:
                ports.add(int(port))
                if len(ports) >= 32:
                    break
    except OSError as exc:
        # A blocked UDP listener must not disable detection of this computer's game.
        logger.warning('lan_discovery_multicast_unavailable reason=%s', exc)
    finally:
        if sock is not None:
            sock.close()
    return ports


async def discover_local_worlds(excluded_ports=(), seconds=3):
    started = time.perf_counter()
    excluded = set(excluded_ports)
    logger.info('lan_discovery_start excluded_ports=%s', sorted(excluded))
    advertised, local = await asyncio.gather(
        _advertised_world_ports(excluded, seconds),
        asyncio.to_thread(_java_listening_ports), return_exceptions=True)
    if isinstance(advertised, Exception):
        logger.warning('lan_discovery_multicast_failed reason=%s', type(advertised).__name__)
        advertised = set()
    if isinstance(local, Exception):
        logger.warning('lan_discovery_java_failed reason=%s', type(local).__name__)
        local = set()
    ports = sorted((advertised | local) - excluded)
    logger.info('lan_discovery_candidates advertised=%s java=%s probing=%s',
                sorted(advertised), sorted(local), ports)
    # Probe loopback only: an advertisement cannot turn this into a LAN scanner.
    results = await asyncio.gather(*(game_status(port) for port in ports), return_exceptions=True)
    worlds = []
    for port, result in zip(ports, results):
        if isinstance(result, dict):
            worlds.append(result)
            logger.info('lan_discovery_world port=%s version=%s protocol=%s',
                        port, result.get('version'), result.get('protocol'))
        else:
            logger.info('lan_discovery_rejected port=%s reason=%s', port, type(result).__name__)
    logger.info('lan_discovery_complete worlds=%s elapsed_ms=%d',
                len(worlds), (time.perf_counter() - started) * 1000)
    return worlds


async def request(connection, operation, **fields):
    if getattr(connection, '_native_bridge', False):
        return await connection.request(operation, **fields)
    async with connection.create_process(subsystem='buggcraft-rooms-v1', encoding='utf-8') as process:
        process.stdin.write(json.dumps({'op': operation, **fields}, ensure_ascii=True) + '\n')
        # Read incrementally: an untrusted community node cannot allocate an unbounded line.
        response = ''
        while not response.endswith('\n'):
            chunk = await asyncio.wait_for(process.stdout.read(4096), 10)
            if not chunk:
                raise ConnectionError('节点未返回房间信息')
            response += chunk
            if len(response) > 65536:
                raise ValueError('节点响应超过限制')
        value = json.loads(response)
        if not isinstance(value, dict) or value.get('ok') is not True:
            raise ConnectionError(value.get('error', '房间操作失败') if isinstance(value, dict) else '无效节点响应')
        return value['result']


async def connect_directory(profile, failover=True):
    from .native_routes import manager
    routes = manager()
    handle = await routes.handle(profile)
    return NativeDirectoryConnection(routes, handle, profile)


class NativeDirectoryConnection:
    """Compatibility-shaped directory session; all I/O is a C++ bridge RPC."""
    _native_bridge = True

    def __init__(self, routes, handle, profile):
        self.routes, self.handle, self._buggcraft_profile = routes, handle, profile

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def request(self, operation, **fields):
        return await self.routes.request('node.request', {
            'node': self.handle, 'request': {'op': operation, **fields}})


async def lookup_account(profile, identifier):
    """Resolve a public account identity across the selected node's federation."""
    if not isinstance(identifier, str) or not 1 <= len(identifier.strip()) <= 65:
        raise ValueError('请输入用户名或完整账号 ID')
    identifier = identifier.strip()
    async with await connect_directory(profile) as connection:
        result = await request(connection, 'account_lookup', identifier=identifier)
    accounts = result.get('accounts') if isinstance(result, dict) else None
    if not isinstance(accounts, list) or len(accounts) > 8:
        raise ValueError('节点返回的账号列表无效')
    seen = set()
    for item in accounts:
        if not isinstance(item, dict):
            raise ValueError('节点返回的账号信息无效')
        account, username = item.get('account'), item.get('username')
        if (not isinstance(account, str) or not re.fullmatch('[0-9a-f]{32}\\.[0-9a-f]{32}', account) or
                not isinstance(username, str) or not re.fullmatch('[A-Za-z0-9_-]{3,32}', username) or
                (identifier != account and identifier.casefold() != username.casefold()) or account in seen):
            raise ValueError('节点返回的账号信息与查询不符')
        seen.add(account)
    return accounts


async def remember_topology(profile, connection):
    from .nodes import remember, profile_data
    topology = await request(connection, 'topology')
    nodes = topology['nodes']
    if not isinstance(nodes, list) or len(nodes) > 31:
        raise ValueError('Invalid network topology')
    entry = getattr(connection, '_buggcraft_profile', profile)
    nodes = [profile_data(entry)] + nodes
    nodes = [node for node in nodes if node != profile_data(profile)]
    remember(profile, nodes)


async def locate_room(profile, room_id):
    from .profiles import RelayProfile
    try:
        async with await connect_directory(profile) as connection:
            try:
                await remember_topology(profile, connection)
            except (OSError, ValueError, KeyError):
                pass
            result = await request(connection, 'locate', id=room_id)
            return RelayProfile(**result['profile']) if result.get('profile') else None
    except (OSError, ConnectionError):
        return None


async def list_room_page(profile, offset=0, limit=20, query=''):
    """Fetch one visible batch; old nodes are scanned only as far as needed."""
    if type(offset) is not int or not 0 <= offset <= 4096:
        raise ValueError('无效房间列表位置')
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError('无效房间列表数量')
    if not isinstance(query, str) or len(query) > 100:
        raise ValueError('无效房间搜索条件')
    query = query.strip()
    started = time.perf_counter()
    async with await connect_directory(profile) as connection:
        ping_started = time.perf_counter()
        info = await request(connection, 'ping')
        node_latency_ms = round((time.perf_counter() - ping_started) * 1000, 1)
        if offset == 0:
            try:
                await remember_topology(profile, connection)
            except (OSError, ValueError, KeyError):
                pass
        paged = isinstance(info, dict) and 'room-list-page-v1' in info.get('capabilities', [])
        rooms, total = [], None
        while True:
            page = await request(connection, 'list', offset=offset, limit=limit, query=query)
            if not isinstance(page, dict) or not isinstance(page.get('rooms'), list) or len(page['rooms']) > 50:
                raise ValueError('节点房间列表格式无效')
            entries = [validate_room(room) for room in page['rooms']]
            following = page.get('next')
            if following is not None and (type(following) is not int or not offset < following <= 4096
                                           or following != offset + len(entries)):
                raise ValueError('节点分页响应无效')
            if paged:
                total = page.get('total')
                if len(entries) > limit or type(total) is not int or not offset + len(entries) <= total <= 100000:
                    raise ValueError('节点分页数量无效')
                if (following is None) != (offset + len(entries) >= total):
                    raise ValueError('节点分页响应无效')
                rooms, next_offset = entries, following
                break
            # Older nodes return up to 50 entries and do not filter. Keep the
            # cursor at the last consumed entry so no rooms are lost on slicing.
            next_offset = following
            for index, room in enumerate(entries):
                game = room['game']
                haystack = ' '.join([room['title'], game.get('version', ''), game.get('loader', '')])
                if query.casefold() in haystack.casefold():
                    rooms.append(room)
                if len(rooms) == limit:
                    next_offset = offset + index + 1 if index + 1 < len(entries) else following
                    break
            if len(rooms) == limit or next_offset is None:
                break
            offset = next_offset
        entry = getattr(connection, '_buggcraft_profile', profile)
        name = info.get('name', '') if isinstance(info, dict) else ''
        same_entry = (entry.server_host, entry.server_port, entry.server_public_key) == (
            profile.server_host, profile.server_port, profile.server_public_key)
        return {'rooms': rooms, 'next': next_offset, 'total': total,
                'node_latency_ms': node_latency_ms,
                'connect_ms': round((time.perf_counter() - started) * 1000, 1),
                'node_name': name if same_entry and isinstance(name, str) and
                0 < len(name) <= 80 and all(c.isprintable() for c in name) else ''}


async def list_rooms(profile):
    started = time.perf_counter()
    async with await connect_directory(profile) as connection:
        info = await request(connection, 'ping')
        try:
            await remember_topology(profile, connection)
        except (OSError, ValueError, KeyError):
            pass
        latency = (time.perf_counter() - started) * 1000
        rooms, offset = [], 0
        while True:
            page = await request(connection, 'list', offset=offset)
            if not isinstance(page, dict) or not isinstance(page.get('rooms'), list) or len(page['rooms']) > 50:
                raise ValueError('节点房间列表格式无效')
            rooms.extend(validate_room(room) for room in page['rooms'])
            next_offset = page.get('next')
            if next_offset is None:
                break
            if type(next_offset) is not int or next_offset <= offset or len(rooms) > 4096:
                raise ValueError('节点分页响应无效')
            offset = next_offset
        entry = getattr(connection, '_buggcraft_profile', profile)
        name = info.get('name', '') if isinstance(info, dict) else ''
        same_entry = (entry.server_host, entry.server_port, entry.server_public_key) == (
            profile.server_host, profile.server_port, profile.server_public_key)
        return {'rooms': rooms, 'connect_ms': round(latency, 1),
                'node_name': name if same_entry and isinstance(name, str) and
                0 < len(name) <= 80 and all(c.isprintable() for c in name) else ''}


async def resolve_room(profile, room_id):
    async with await connect_directory(profile) as connection:
        result = await request(connection, 'resolve', id=room_id)
        validate_room(result['room'])
        if 'secret' not in result and result.get('profile'):
            from .profiles import RelayProfile
            async with await connect_directory(RelayProfile(**result['profile']), failover=False) as owner:
                result = await request(owner, 'resolve', id=room_id)
                validate_room(result['room'])
        return result


def validate_room(value):
    if not isinstance(value, dict) or not isinstance(value.get('id'), str) or not re.fullmatch('[0-9a-f]{32}', value['id']):
        raise ValueError('节点房间标识无效')
    if not isinstance(value.get('title'), str) or len(value['title']) > 80:
        raise ValueError('节点房间名称无效')
    if type(value.get('require_invite', False)) is not bool:
        raise ValueError('节点房间加入方式无效')
    for key in ('connections', 'capacity'):
        if type(value.get(key)) is not int or not 0 <= value[key] <= 100000:
            raise ValueError('节点连接数或容量无效')
    for key in ('members', 'game_players'):
        if value.get(key) is not None and (type(value[key]) is not int or not 0 <= value[key] <= 100000):
            raise ValueError('节点玩家人数无效')
    game = value.get('game')
    if not isinstance(game, dict) or any(not isinstance(game.get(key, ''), str) or len(game.get(key, '')) > 128
            for key in ('version', 'loader', 'loader_version', 'mods_hash')):
        raise ValueError('节点版本信息无效')
    mods = game.get('mods', [])
    if (not isinstance(mods, list) or len(mods) > 24 or
            any(not isinstance(item, dict) or
                not isinstance(item.get('name'), str) or len(item['name']) > 64 or
                not isinstance(item.get('sha256'), str) or
                not re.fullmatch(r'[0-9a-f]{64}', item['sha256']) or
                type(item.get('size')) is not int or not 0 <= item['size'] <= 2147483647
                for item in mods)):
        raise ValueError('节点模组列表无效')
    if type(game.get('mods_count', 0)) is not int or not 0 <= game.get('mods_count', 0) <= 10000:
        raise ValueError('节点模组数量无效')
    return value


def compatibility(local, remote):
    """Conservative checks. This relay never translates Minecraft or mod protocols."""
    errors, warnings = [], []
    for key, label in [('version', '游戏版本'), ('protocol', '协议版本'),
                       ('loader', '加载器'), ('loader_version', '加载器版本'), ('mods_hash', '模组集合')]:
        left, right = local.get(key), remote.get(key)
        if left is not None and right is not None and left != '' and right != '':
            if left != right:
                errors.append(f'{label}不一致')
        elif key in ('version', 'loader', 'mods_hash'):
            warnings.append(f'{label}未检测，需自行核对')
    return errors, warnings


def instance_metadata(directory, version, game_directory=None):
    """Inspect installed version inheritance and byte hashes of instance mod jars."""
    base = Path(directory)
    result = {'version': '', 'protocol': None, 'loader': 'vanilla', 'loader_version': '',
              'mods_hash': '', 'mods_count': 0, 'mods': []}
    current, seen = version, set()
    while current and current not in seen:
        seen.add(current)
        metadata = json.loads((base / 'versions' / current / (current + '.json')).read_text(encoding='utf-8'))
        room_version = metadata.get('buggcraftRoom', {}).get('version')
        if room_version:
            result['version'] = room_version
        for library in metadata.get('libraries', []):
            name = library.get('name', '')
            for prefix, loader in [('net.minecraftforge:forge:', 'forge'),
                                   ('net.neoforged:neoforge:', 'neoforge'),
                                   ('net.fabricmc:fabric-loader:', 'fabric'),
                                   ('org.quiltmc:quilt-loader:', 'quilt')]:
                if name.startswith(prefix):
                    result['loader'], result['loader_version'] = loader, name.split(':')[2]
        inherited = metadata.get('inheritsFrom')
        if not inherited and not result['version']:
            result['version'] = metadata.get('id', current)
        current = inherited
    mods = Path(game_directory or base) / 'mods'
    jars = sorted(mods.glob('*.jar'), key=lambda item: item.name.lower())
    result['mods_count'] = len(jars)
    hashes = []
    for jar in jars:
        digest = hashlib.sha256()
        with jar.open('rb') as source:
            for block in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(block)
        hashes.append(digest.hexdigest())
        if len(result['mods']) < 24 and len(jar.name) <= 64:
            result['mods'].append({'name': jar.name, 'sha256': digest.hexdigest(),
                                   'size': jar.stat().st_size})
    result['mods_hash'] = hashlib.sha256('\n'.join(sorted(hashes)).encode()).hexdigest()
    if result['loader'] == 'forge' and result['loader_version'].startswith(result['version'] + '-'):
        result['loader_version'] = result['loader_version'][len(result['version']) + 1:]
    return result


class LanAnnouncer:
    """Deliver LAN discovery to this computer only, matching the loopback proxy.

    Minecraft's MulticastSocket also receives unicast on UDP 4445. Sending to
    127.0.0.1 keeps the packet source reachable without exposing a LAN listener.
    """
    def __init__(self, port, title):
        self.port = port
        self.title = ''.join(ch for ch in str(title) if ch.isprintable() and ch not in '[]')[:80]

    def packet(self):
        return f'[MOTD]{self.title}[/MOTD][AD]{self.port}[/AD]'.encode('utf-8')

    async def run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('127.0.0.1', 0))
        sock.setblocking(False)
        try:
            while True:
                try:
                    await asyncio.get_running_loop().sock_sendto(sock, self.packet(), ('127.0.0.1', 4445))
                except OSError:
                    # Discovery is optional; a blocked UDP socket must not kill game traffic.
                    pass
                await asyncio.sleep(1.5)
        finally:
            sock.close()
