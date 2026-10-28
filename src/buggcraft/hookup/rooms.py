"""Invitation based room control, independent of UI and game data forwarding."""
import asyncio
import hashlib
import json
import logging
import time
from pathlib import Path
import re


logger = logging.getLogger(__name__)


async def game_status(port, timeout=4):
    from .native_routes import manager
    return await manager().request('game.status', {'port': int(port), 'timeout_ms': int(timeout * 1000)})


async def discover_local_worlds(excluded_ports=(), seconds=3):
    from .native_routes import manager
    result = await manager().request('game.discover', {'exclude': list(excluded_ports), 'duration_ms': int(seconds * 1000)})
    return result['worlds']


async def request(connection, operation, **fields):
    return await connection.request(operation, **fields)


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
    from .friend_codes import matches_account
    if not isinstance(identifier, str) or not 1 <= len(identifier.strip()) <= 65:
        raise ValueError('请输入好友码、用户名或完整账号 ID')
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
        if (not isinstance(account, str) or not re.fullmatch(r'[0-9a-f]{32}\.[0-9a-f]{32}', account) or
                not isinstance(username, str) or not re.fullmatch('[A-Za-z0-9_-]{3,32}', username) or
                not matches_account(identifier, account, username) or account in seen):
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
    from .native_routes import manager
    bridge = manager()
    node = await bridge.handle(profile)
    rooms, metadata, filtered = [], None, False
    while True:
        page = await bridge.request('room.list', {'node': node,
            'offset': offset, 'limit': limit - len(rooms), 'query': query})
        if not isinstance(page, dict) or not isinstance(page.get('rooms'), list) or len(page['rooms']) > 50:
            raise ValueError('Invalid native room list')
        entries = [validate_room(room) for room in page['rooms']]
        following = page.get('next')
        if following is not None and (type(following) is not int
                or not offset < following <= 4096 or following != offset + len(entries)):
            raise ValueError('Invalid native room cursor')
        total = page.get('total')
        if total is not None and (type(total) is not int or not offset + len(entries) <= total <= 100000):
            raise ValueError('Invalid native room total')
        if metadata is None:
            metadata = dict(page)
        next_offset = following
        for index, room in enumerate(entries):
            game = room['game']
            haystack = ' '.join((room['title'], game.get('version', ''), game.get('loader', '')))
            if not query or query.casefold() in haystack.casefold():
                rooms.append(room)
            else:
                filtered = True
            if len(rooms) == limit:
                # Older nodes may ignore limit/query. Resume at the last consumed
                # entry, not the end of their oversized page, to avoid omissions.
                next_offset = offset + index + 1 if index + 1 < len(entries) else following
                break
        if len(rooms) == limit or next_offset is None:
            metadata.update(rooms=rooms, next=next_offset, total=None if filtered else total)
            return metadata
        offset = next_offset


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
    from .native_routes import manager
    bridge = manager()
    result = await bridge.request('room.resolve', {'node': await bridge.handle(profile), 'id': room_id})
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
    resources = game.get('resources', [])
    if (not isinstance(resources, list) or len(resources) > 24 or
            any(not isinstance(item, dict) or
                not isinstance(item.get('name'), str) or len(item['name']) > 240 or
                not isinstance(item.get('path'), str) or
                not item['path'].startswith(('resourcepacks/', 'shaderpacks/')) or
                Path(item['path']).name != item['name'] or item['path'].count('/') != 1 or
                not isinstance(item.get('sha256'), str) or
                not re.fullmatch(r'[0-9a-f]{64}', item['sha256']) or
                type(item.get('size')) is not int or not 0 <= item['size'] <= 2147483647
                for item in resources)):
        raise ValueError('Room resource list is invalid')
    for key in ('resources_hash',):
        if not isinstance(game.get(key, ''), str) or len(game.get(key, '')) > 128:
            raise ValueError('Room resource hash is invalid')
    if type(game.get('resources_count', 0)) is not int or not 0 <= game.get('resources_count', 0) <= 2000:
        raise ValueError('Room resource count is invalid')
    return value


def compatibility(local, remote):
    """Conservative checks. This relay never translates Minecraft or mod protocols."""
    errors, warnings = [], []
    for key, label in [('version', '游戏版本'), ('protocol', '协议版本'),
                       ('loader', '加载器'), ('loader_version', '加载器版本'), ('mods_hash', '模组集合')]:
        left, right = local.get(key), remote.get(key)
        if left is not None and right is not None and left != '' and right != '':
            if left != right:
                (warnings if key == 'loader_version' else errors).append(f'{label}不一致')
        elif key in ('version', 'loader', 'mods_hash'):
            warnings.append(f'{label}未检测，需自行核对')
    return errors, warnings


def metadata_loader(metadata):
    """Read real launch libraries/arguments, including modern Forge profiles."""
    arguments = [arg for arg in metadata.get('arguments', {}).get('game', []) if isinstance(arg, str)]
    options = dict(zip(arguments, arguments[1:]))
    libraries = [item.get('name', '') for item in metadata.get('libraries', []) if isinstance(item, dict)]
    if options.get('--fml.neoForgeVersion') and any(name.startswith('net.neoforged') for name in libraries):
        return 'neoforge', options['--fml.neoForgeVersion']
    for prefix, loader in [('net.neoforged:neoforge:', 'neoforge'),
                           ('net.fabricmc:fabric-loader:', 'fabric'),
                           ('org.quiltmc:quilt-loader:', 'quilt'),
                           ('net.minecraftforge:forge:', 'forge'),
                           ('net.minecraftforge:fmlloader:', 'forge'),
                           ('net.minecraftforge:fmlcore:', 'forge')]:
        name = next((name for name in libraries if name.startswith(prefix)), '')
        if name:
            return loader, options.get('--fml.forgeVersion', name.split(':')[2]) if loader == 'forge' else name.split(':')[2]
    return 'vanilla', ''


def instance_metadata(directory, version, game_directory=None):
    """Inspect required mods and optional resource/shader files for a room."""
    base = Path(directory)
    result = {'version': '', 'protocol': None, 'loader': 'vanilla', 'loader_version': '',
              'mods_hash': '', 'mods_count': 0, 'mods': [],
              'resources_hash': '', 'resources_count': 0, 'resources': []}
    current, seen = version, set()
    while current and current not in seen:
        seen.add(current)
        metadata = json.loads((base / 'versions' / current / (current + '.json')).read_text(encoding='utf-8'))
        room_version = metadata.get('buggcraftRoom', {}).get('version')
        if room_version:
            result['version'] = room_version
        loader, loader_version = metadata_loader(metadata)
        if result['loader'] == 'vanilla' and loader != 'vanilla':
            result['loader'], result['loader_version'] = loader, loader_version
        inherited = metadata.get('inheritsFrom')
        if not inherited and not result['version']:
            from core.version_metadata import base_version
            result['version'] = base_version(metadata, metadata.get('id', current))
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
    game_root = Path(game_directory or base)
    resource_hashes = []
    for folder in ('resourcepacks', 'shaderpacks'):
        resource_directory = game_root / folder
        if not resource_directory.is_dir():
            continue
        for item in sorted(resource_directory.iterdir(), key=lambda value: value.name.casefold()):
            if not item.is_file() or item.is_symlink():
                continue
            digest = hashlib.sha256()
            with item.open('rb') as source:
                for block in iter(lambda: source.read(1024 * 1024), b''):
                    digest.update(block)
            value = digest.hexdigest()
            resource_hashes.append(value)
            if len(result['resources']) < 24 and len(item.name) <= 240:
                result['resources'].append({'name': item.name, 'path': f'{folder}/{item.name}',
                                            'sha256': value, 'size': item.stat().st_size})
    result['resources_count'] = len(resource_hashes)
    result['resources_hash'] = hashlib.sha256('\n'.join(sorted(resource_hashes)).encode()).hexdigest()
    if result['loader'] == 'forge' and result['loader_version'].startswith(result['version'] + '-'):
        result['loader_version'] = result['loader_version'][len(result['version']) + 1:]
    return result


class LanAnnouncer:
    """Compatibility control wrapper; native code owns the UDP socket."""
    def __init__(self, port, title):
        self.port, self.title = port, title

    async def run(self):
        from .native_routes import manager
        while True:
            await manager().request('game.announce', {'port': self.port, 'title': self.title})
            await asyncio.sleep(1.5)
