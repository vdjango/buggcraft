"""Stable public aliases; signed operations always use the full account ID."""
import base64
import hashlib
import re


def friend_code(account):
    digest = hashlib.sha256(('buggcraft-friend-v1:' + account).encode('ascii')).digest()
    code = base64.b32encode(digest).decode('ascii')[:12]
    return '-'.join(code[i:i + 4] for i in range(0, 12, 4))


def matches_account(identifier, account, username):
    return (identifier == account or identifier.casefold() == username.casefold() or
            identifier.upper().replace('-', '') == friend_code(account).replace('-', ''))


def valid_identifier(value):
    return isinstance(value, str) and re.fullmatch(
        r'(?:[A-Za-z0-9_-]{3,32}|[0-9a-f]{32}\.[0-9a-f]{32})', value.strip()) is not None
