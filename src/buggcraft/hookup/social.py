"""Signed friend operations over the existing pinned directory transport."""
import base64
import json
import time


EXPIRED_CODE_MESSAGE = '个人接入码已过期。请在原节点网页登录账号，重新领取个人启动器接入码，再在这里更换；无需删除节点。'


class ExpiredNodeCredential(ValueError):
    pass


def credential_expiry(profile):
    """Read expiry for presentation only; the node still authenticates the code."""
    if not profile.token.startswith('acct1.'):
        return None
    try:
        claims = json.loads(decode(profile.token.split('~', 1)[0][6:].split('.')[0]))
        expiry = claims.get('e')
        return expiry if type(expiry) is int and expiry > 0 else None
    except (ValueError, TypeError, AttributeError, IndexError):
        return None


def check_expiry(profile):
    expiry = credential_expiry(profile)
    if expiry is not None and expiry <= time.time():
        raise ExpiredNodeCredential(EXPIRED_CODE_MESSAGE)



def decode(value):
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def credential(profile):
    check_expiry(profile)
    try:
        token, secret = profile.token.split('~')
        claims = json.loads(decode(token[6:].split('.')[0]))
        if not token.startswith('acct1.') or claims['e'] <= time.time() or not claims['g'].get('d'):
            raise ValueError('Expired or legacy credential')
        return claims, None
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        raise ValueError('请在节点网页重新登录，领取支持好友的个人启动器接入码。') from exc


async def operate(profile, operation, target=None, **fields):
    from .native_routes import manager
    bridge = manager()
    result = await bridge.request('social.operate', {
        'node': await bridge.handle(profile), 'operation': operation,
        'target': target, 'fields': fields})
    if not isinstance(result, dict):
        raise ValueError('Invalid native social response')
    return result


async def status(profile):
    return await operate(profile, 'presence')
