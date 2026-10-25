"""Portable player codes and bounded, pinned fallback profiles."""
import base64
import json
import os
from pathlib import Path
import tempfile


def node_identity(profile):
    """A pinned SSH key identifies a node across address aliases and key comments."""
    parts = profile.server_public_key.strip().split()
    return 'SHA256:' + __import__('hashlib').sha256((parts[0] + ' ' + parts[1]).encode()).hexdigest()


def profile_data(profile):
    return {key: getattr(profile, key) for key in ('server_host', 'server_port', 'token', 'server_public_key')}


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.node-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as target:
            json.dump(value, target, ensure_ascii=False, indent=2)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def decode_code(code):
    from .profiles import RelayProfile
    code = code.strip()
    if not code.startswith('buggnode1-') or len(code) > 4096:
        raise ValueError('请粘贴节点网页提供的 buggnode1- 添加码。')
    try:
        encoded = code[10:]
        value = json.loads(base64.b64decode(encoded + '=' * (-len(encoded) % 4),
                                          altchars=b'-_', validate=True))
        return RelayProfile(**value)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ValueError('节点添加码格式无效，请重新复制。') from exc


def encode_code(profile):
    return 'buggnode1-' + base64.urlsafe_b64encode(
        json.dumps(profile_data(profile), separators=(',', ':')).encode()).decode().rstrip('=')


async def import_code(code):
    """Let the native bridge redeem, validate and pin the supplied access code."""
    from .native_routes import manager
    from .profiles import RelayProfile
    if not isinstance(code, str) or len(code) > 4096:
        raise ValueError('请粘贴节点网页提供的启动器接入码。')
    routes = manager()
    result = await routes.request('node.add', {'code': code.strip()})
    handle = result['node']
    try:
        selected = await routes.request('node.selected', {'node': handle})
        profile = RelayProfile(**selected['profile'])
        remember(profile, selected.get('backups', []))
        object.__setattr__(profile, '_name', result.get('name', 'Node'))
        return profile
    finally:
        await routes.request('node.remove', {'node': handle})


def candidates(profile):
    from .profiles import RelayProfile
    values = list(profile._nodes)
    if not values and profile._source:
        path = Path(profile._source + '.network.json')
        try:
            if path.stat().st_size <= 65536:
                values = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            pass
    result, seen = [profile], {(profile.server_host, profile.server_port, profile.server_public_key)}
    if not isinstance(values, list) or len(values) > 32:
        return result
    for item in values:
        try:
            other = RelayProfile(**item)
            key = (other.server_host, other.server_port, other.server_public_key)
            if key not in seen:
                result.append(other)
                seen.add(key)
        except (ValueError, TypeError):
            continue
    return result


def remember(profile, nodes):
    from .profiles import RelayProfile
    if not isinstance(nodes, list) or len(nodes) > 32:
        raise ValueError('节点网络列表超过限制')
    cleaned = [profile_data(RelayProfile(**item)) for item in nodes]
    # A failed refresh must not erase the last known-good route set. Keep the
    # newest signed topology first and retain only distinct pinned endpoints.
    previous = list(profile._nodes)
    if profile._source:
        path = Path(profile._source + '.network.json')
        try:
            if path.stat().st_size <= 65536:
                previous = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError, TypeError):
            pass
    merged = []
    seen = set()
    for item in cleaned + (previous if isinstance(previous, list) else []):
        try:
            candidate = profile_data(RelayProfile(**item))
        except (ValueError, TypeError):
            continue
        identity = (candidate['server_host'], candidate['server_port'], candidate['server_public_key'])
        if identity not in seen:
            merged.append(candidate)
            seen.add(identity)
        if len(merged) >= 32:
            break
    cleaned = merged
    object.__setattr__(profile, '_nodes', tuple(cleaned))
    if profile._source:
        save_json(profile._source + '.network.json', cleaned)


async def probe(profile):
    from .rooms import connect_directory, request
    async with await connect_directory(profile, failover=False) as conn:
        result = await request(conn, 'ping')
        name = result.get('name', '')
        if isinstance(name, str) and 1 <= len(name) <= 80 and all(c.isprintable() for c in name):
            object.__setattr__(profile, '_name', name)
        try:
            result = await request(conn, 'topology')
            remember(profile, result['nodes'])
        except (ConnectionError, ValueError, KeyError):
            pass  # Compatible with independent v1 relays.
    return profile
