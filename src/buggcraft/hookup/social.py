"""Signed friend operations over the existing pinned directory transport."""
import base64
import json
import time




def decode(value):
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def credential(profile):
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
