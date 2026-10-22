"""Signed friend operations over the existing pinned directory transport."""
import base64
import json
import time
import uuid

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from .rooms import connect_directory, request


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
        scalar = int.from_bytes(decode(secret), 'big')
        key = ec.derive_private_key(scalar, ec.SECP256R1())
        public = key.public_key().public_numbers()
        delegated = claims['g']['d']
        if public.x != int.from_bytes(decode(delegated['x']), 'big') or public.y != int.from_bytes(decode(delegated['y']), 'big'):
            raise ValueError('Delegation key mismatch')
        return claims, key
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        raise ValueError('请在节点网页重新登录，领取支持好友的个人接入码。') from exc


def signed_action(profile, operation, target=None, **fields):
    claims, key = credential(profile)
    action = {'op': operation, 'target': target or claims['a'], 'at': time.time(), 'id': uuid.uuid4().hex, **fields}
    r, s = utils.decode_dss_signature(key.sign(canonical(action), ec.ECDSA(hashes.SHA256())))
    signature = base64.urlsafe_b64encode(r.to_bytes(32, 'big') + s.to_bytes(32, 'big')).decode().rstrip('=')
    return {'grant': claims['g'], 'proof': claims['s'], 'action': action, 'signature': signature}


async def operate(profile, operation, target=None, **fields):
    event = signed_action(profile, operation, target, **fields)
    async with await connect_directory(profile) as connection:
        result = await request(connection, 'social', event=event)
    if not isinstance(result, dict):
        raise ValueError('好友服务返回无效数据。')
    return result


async def status(profile):
    return await operate(profile, 'presence')
