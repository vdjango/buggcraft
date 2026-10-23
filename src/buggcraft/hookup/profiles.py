"""Validated node profiles and room invitations shared with the native bridge."""
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import secrets


@dataclass(frozen=True)
class RelayProfile:
    server_host: str
    server_port: int
    token: str = field(repr=False)
    server_public_key: str
    _source: str = field(default='', init=False, repr=False, compare=False)
    _nodes: tuple = field(default=(), init=False, repr=False, compare=False)

    def __post_init__(self):
        if (not isinstance(self.server_host, str) or not self.server_host.strip()
                or len(self.server_host) > 253
                or any(char.isspace() or char in '/\\@?#' for char in self.server_host)):
            raise ValueError('Invalid relay address')
        if type(self.server_port) is not int or not 1 <= self.server_port <= 65535:
            raise ValueError('Invalid relay port')
        if not isinstance(self.token, str) or not 32 <= len(self.token) <= 2048:
            raise ValueError('Invalid relay service token')
        parts = self.server_public_key.strip().split()
        if (len(parts) < 2 or parts[0] not in
                ('ssh-ed25519', 'ssh-rsa', 'ecdsa-sha2-nistp256',
                 'ecdsa-sha2-nistp384', 'ecdsa-sha2-nistp521')
                or len(parts[1]) > 4096):
            raise ValueError('Invalid pinned node key')

    @classmethod
    def load(cls, path):
        path = Path(path).resolve()
        if path.stat().st_size > 8192:
            raise ValueError('Node configuration exceeds size limit')
        profile = cls(**json.loads(path.read_text(encoding='utf-8')))
        object.__setattr__(profile, '_source', str(path))
        return profile

    def known_hosts(self):
        raise RuntimeError('SSH host-key handling belongs to the C++ bridge')


@dataclass(frozen=True)
class RoomInvite:
    secret: str = field(repr=False)

    def __post_init__(self):
        if (not isinstance(self.secret, str) or not 32 <= len(self.secret) <= 128
                or any(char not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'
                       for char in self.secret)):
            raise ValueError('Invalid room invitation')

    @property
    def room_id(self):
        return hashlib.sha256(self.secret.encode('ascii')).hexdigest()[:32]

    @classmethod
    def create(cls):
        return cls(secrets.token_urlsafe(32))

    def encode(self):
        return 'bugg1-' + self.secret

    @classmethod
    def decode(cls, value):
        if not isinstance(value, str):
            raise ValueError('Invalid room invitation')
        value = value.strip()
        if not value.startswith('bugg1-'):
            raise ValueError('Invalid room invitation')
        return cls(value[6:])
