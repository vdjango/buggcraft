"""Public node identities for bridge adapter tests, without a Python SSH runtime."""
import base64
import hashlib
import json
import struct
import time


def ssh_public_key(label='node'):
    """Encode a stable Ed25519 public key; no private key or SSH server is used."""
    algorithm = b'ssh-ed25519'
    public = hashlib.sha256(label.encode('utf-8')).digest()
    blob = struct.pack('!I', len(algorithm)) + algorithm + struct.pack('!I', len(public)) + public
    return 'ssh-ed25519 ' + base64.b64encode(blob).decode('ascii') + '\n'


def personal_access_token():
    """Presentation-valid claims for tests; the remote signature is a fixture."""
    claims = {'e': int(time.time()) + 3600, 'g': {'d': True}}
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')
    return 'acct1.' + payload + '.fixture-signature~fixture-secret'
