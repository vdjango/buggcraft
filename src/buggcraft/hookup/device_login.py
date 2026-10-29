"""Native login approval polling and OS-protected launcher credentials."""
import asyncio
import base64
import json
from pathlib import Path
import time
from urllib.parse import urlsplit
import urllib.error
import urllib.request

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

NODE_WEB = 'https://node.bugg.icu'
SERVICE = 'Buggcraft launcher device v1'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def _keyring():
    try:
        import keyring
    except ImportError as exc:
        raise RuntimeError('需要系统凭据库组件，请重新安装最新版启动器。') from exc
    if keyring.get_keyring().priority <= 0:
        raise RuntimeError('此系统没有可用的安全凭据库，请启用系统钥匙串后重试。')
    return keyring


def save_private_key(account, private_key):
    serialized = private_key.private_bytes(serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    _keyring().set_password(SERVICE, account, base64.urlsafe_b64encode(serialized).decode())


def load_private_key(account):
    value = _keyring().get_password(SERVICE, account)
    if not value:
        return None
    try:
        return serialization.load_der_private_key(base64.urlsafe_b64decode(value), password=None)
    except (ValueError, TypeError):
        return None


def delete_private_key(account):
    try:
        _keyring().delete_password(SERVICE, account)
    except Exception:
        pass


def claims(token):
    if not token.startswith('acct1.'):
        return {}
    try:
        encoded = token[6:].split('.', 1)[0]
        return json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
    except (ValueError, TypeError):
        return {}


def protect_data(value):
    """New device credentials never write private scalars into profile/cache JSON."""
    if isinstance(value, list):
        return [protect_data(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = dict(value)
    token = result.get('token', '')
    grant = claims(token).get('g', {}) if isinstance(token, str) else {}
    if grant.get('p') == 'buggcraft-launcher-device-v1':
        identifier = 'token:' + grant['i'] + ':' + grant['r']
        _keyring().set_password(SERVICE, identifier, token)
        result['token'] = 'vault1:' + identifier
    return result


def reveal_token(token):
    if isinstance(token, str) and token.startswith('vault1:'):
        value = _keyring().get_password(SERVICE, token[7:])
        if not value:
            raise ValueError('系统凭据库中没有此设备的登录授权，请重新登录。')
        return value
    return token


def validate_origin(origin):
    if isinstance(origin, str):
        origin = origin.strip()
        if '://' not in origin:
            origin = 'https://' + origin
    if not isinstance(origin, str):
        raise ValueError('Invalid HTTPS node address')
    value = urlsplit(origin)
    try:
        value.port
    except ValueError as exc:
        raise ValueError('Invalid HTTPS node port') from exc
    if (value.scheme != 'https' or not value.hostname or value.username or value.password or
            value.query or value.fragment or value.path not in ('', '/') or
            any(char.isspace() for char in value.netloc) or '\\' in value.netloc or '%' in value.netloc):
        raise ValueError('请输入可信节点的 HTTPS 网址。')
    return 'https://' + value.netloc


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise urllib.error.HTTPError(request.full_url, code,
                                     'HTTPS API redirects are not accepted', headers, response)


def _open(request, origin, timeout):
    expected = urlsplit(validate_origin(origin))
    actual = urlsplit(request.full_url)
    if (actual.scheme != expected.scheme or actual.netloc.casefold() != expected.netloc.casefold() or
            actual.username or actual.password):
        raise ValueError('Launcher API request does not match the selected node')
    opener = urllib.request.build_opener(_RejectRedirects())
    return opener.open(request, timeout=timeout)


def public_jwk(key):
    numbers = key.public_key().public_numbers()
    encode = lambda number: base64.urlsafe_b64encode(number.to_bytes(32, 'big')).decode().rstrip('=')
    return {'kty': 'EC', 'crv': 'P-256', 'x': encode(numbers.x), 'y': encode(numbers.y)}


def sign(key, payload):
    der = key.sign(canonical(payload), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    return base64.urlsafe_b64encode(r.to_bytes(32, 'big') + s.to_bytes(32, 'big')).decode().rstrip('=')


def request(path, body, origin=NODE_WEB):
    origin = validate_origin(origin)
    payload = json.dumps(body, separators=(',', ':')).encode()
    call = urllib.request.Request(origin + path, data=payload,
        headers={'Content-Type': 'application/json', 'Cache-Control': 'no-store'})
    try:
        with _open(call, origin, timeout=12) as response:
            raw = response.read(65537)
    except urllib.error.HTTPError as exc:
        detail = exc.read(2048).decode('utf-8', 'replace')
        try:
            detail = json.loads(detail).get('error', detail)
        except ValueError:
            pass
        raise ValueError(detail[:500]) from None
    if len(raw) > 65536:
        raise ValueError('联机节点返回的数据超过限制。')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('联机节点响应无效。')
    return value


async def begin(name, remember, origin=NODE_WEB):
    origin = validate_origin(origin)
    # Test the system vault before asking the user to approve a device.
    await asyncio.to_thread(_keyring)
    status = await asyncio.to_thread(get_status, origin)
    if status.get('launcher_login') != 1:
        raise ValueError('此节点尚未支持浏览器设备登录，请让管理员升级节点，或在“更多选项”中输入旧接入码。')
    key = ec.generate_private_key(ec.SECP256R1())
    result = await asyncio.to_thread(request, '/api/launcher/start',
        {'key': public_jwk(key), 'name': name[:64], 'remember': bool(remember)}, origin)
    result['origin'] = origin
    if result.get('verification_uri') != origin + '/account/access?launcher=' + result.get('id', ''):
        raise ValueError('节点返回的登录网址不匹配。')
    result['deadline'] = time.monotonic() + min(result.get('expires_in', 600), 600)
    return result, key


def get_status(origin):
    origin = validate_origin(origin)
    call = urllib.request.Request(origin + '/api/status', headers={'Cache-Control': 'no-store'})
    with _open(call, origin, timeout=10) as response:
        raw = response.read(65537)
    if len(raw) > 65536:
        raise ValueError('节点状态响应过大。')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('节点状态响应无效。')
    return value


async def poll(result, key):
    if time.monotonic() > result['deadline']:
        raise ValueError('登录请求已过期，请重新点击登录。')
    try:
        value = await asyncio.to_thread(request, '/api/launcher/poll',
            {'id': result['id'], 'signature': sign(key, {'p': 'buggcraft-launcher-poll-v1',
                                                         'id': result['id'], 'nonce': result['nonce']})}, result['origin'])
        return value if value.get('status') == 'approved' else None
    except (OSError, TimeoutError):
        return None


async def refresh(profile_path):
    from .nodes import profile_data, save_json
    from .profiles import RelayProfile
    profile = RelayProfile.load(profile_path)
    metadata = json.loads(Path(str(profile_path) + '.device.json').read_text(encoding='utf-8'))
    origin = validate_origin(metadata['origin'])
    key = await asyncio.to_thread(load_private_key, metadata['id'])
    if key is None:
        raise ValueError('系统凭据库中的设备密钥不可用，请重新登录。')
    grant = claims(profile.token).get('g', {})
    if grant.get('r') != metadata['id'] or grant.get('d') != public_jwk(key):
        raise ValueError('此节点登录设备已变更，请重新登录。')
    challenge = await asyncio.to_thread(request, '/api/launcher/challenge', {'id': metadata['id']}, origin)
    message = challenge['message']
    if (message.get('p') != 'buggcraft-launcher-refresh-v1' or message.get('id') != metadata['id'] or
            message.get('i') != grant['i'] or message.get('o') != origin):
        raise ValueError('设备续期挑战与登录节点不匹配。')
    token = await asyncio.to_thread(request, '/api/launcher/refresh',
                                    {'nonce': challenge['message']['nonce'],
                                     'signature': sign(key, challenge['message'])}, origin)
    updated = approved_profile(token, key)
    from .nodes import node_identity
    if node_identity(updated) != node_identity(profile):
        raise ValueError('节点身份发生变化，请核实后重新登录。')
    save_json(profile_path, profile_data(updated))
    return updated


def _private_scalar(key):
    return base64.urlsafe_b64encode(key.private_numbers().private_value.to_bytes(32, 'big')).decode().rstrip('=')


def approved_profile(value, key):
    from .profiles import RelayProfile
    profile = value.get('profile')
    if not isinstance(profile, dict):
        raise ValueError('节点没有返回启动器配置。')
    result = RelayProfile(**{**profile, 'token': profile['token'] + '~' + _private_scalar(key)})
    object.__setattr__(result, '_name', str(value.get('name', '社区节点'))[:80])
    object.__setattr__(result, '_region', str(value.get('region', ''))[:80])
    return result
