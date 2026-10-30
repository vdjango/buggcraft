"""Signed friend operations over the existing pinned directory transport."""
import base64
import asyncio
import json
import logging
import secrets
import time

LOG = logging.getLogger(__name__)

EXPIRED_CODE_MESSAGE = '节点账号登录已过期。请使用原节点地址，在浏览器重新登录并授权此设备；无需删除节点。'


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
        LOG.warning('social_credential_expired node_host=%s node_port=%s expired_seconds=%.0f',
                    profile.server_host, profile.server_port, time.time() - expiry)
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
        LOG.warning('social_credential_invalid node_host=%s node_port=%s error=%s',
                    profile.server_host, profile.server_port, type(exc).__name__)
        raise ValueError('请使用原节点地址，在浏览器重新登录并授权此设备，以恢复好友功能。') from exc


async def operate(profile, operation, target=None, **fields):
    from .native_routes import manager, REQUEST_TRACE
    trace = secrets.token_hex(6)
    context = REQUEST_TRACE.set(trace)
    started, stage = time.monotonic(), 'node_handle'
    # Never log the access code, target account, signed event or response body.
    LOG.debug('social_request_start trace=%s operation=%s node_host=%s node_port=%s',
              trace, operation, profile.server_host, profile.server_port)
    try:
        bridge = manager()
        handle = await bridge.handle(profile)
        stage = 'node_request'
        result = await bridge.request('social.operate', {
            'node': handle, 'operation': operation, 'target': target, 'fields': fields})
        stage = 'response'
        if not isinstance(result, dict):
            raise ValueError('Invalid native social response')
        LOG.debug('social_request_complete trace=%s operation=%s elapsed_ms=%.1f',
                  trace, operation, (time.monotonic() - started) * 1000)
        return result
    except asyncio.CancelledError:
        LOG.info('social_request_cancelled trace=%s operation=%s stage=%s elapsed_ms=%.1f',
                 trace, operation, stage, (time.monotonic() - started) * 1000)
        raise
    except Exception as error:
        code = getattr(error, 'code', None)
        LOG.warning('social_request_failed trace=%s operation=%s node_host=%s node_port=%s stage=%s elapsed_ms=%.1f error=%s error_code=%s',
                    trace, operation, profile.server_host, profile.server_port, stage,
                    (time.monotonic() - started) * 1000, type(error).__name__,
                    code if type(code) is int else None)
        raise
    finally:
        REQUEST_TRACE.reset(context)


async def status(profile, room_presence=None):
    return await operate(profile, 'presence', **(room_presence or {}))
