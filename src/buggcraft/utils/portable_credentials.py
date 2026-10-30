"""Folder-local credentials; Windows protects their contents with DPAPI."""
import base64
import json
import os
from pathlib import Path
import secrets
import threading

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from utils.storage_paths import active_storage_root

_lock = threading.RLock()


def _windows_protect(value, decrypt=False):
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(value)
    source = Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob), ctypes.c_void_p,
                         ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise OSError('登录信息无法在当前 Windows 账号解密，请重新登录。')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree(ctypes.cast(target.data, ctypes.c_void_p))


class PortableCredentials:
    def __init__(self):
        self.root = active_storage_root() / 'etc' / 'credentials'
        self.root.mkdir(parents=True, exist_ok=True)

    def _cipher(self):
        path = self.root / 'local.key'
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(secrets.token_bytes(32))
                stream.flush()
                os.fsync(stream.fileno())
        return AESGCM(path.read_bytes())

    def _read(self):
        path = self.root / 'vault.json'
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}

    def _save(self, data):
        path = self.root / 'vault.json'
        temporary = path.with_suffix('.tmp')
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w', encoding='utf-8') as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)

    def set_password(self, service, account, value):
        identity = service + '\n' + account
        with _lock:
            data = self._read()
            if os.name == 'nt':
                data[identity] = 'dpapi:' + base64.b64encode(_windows_protect(value.encode())).decode()
            else:
                nonce = secrets.token_bytes(12)
                data[identity] = base64.b64encode(nonce + self._cipher().encrypt(nonce, value.encode(), identity.encode())).decode()
            self._save(data)

    def get_password(self, service, account):
        identity = service + '\n' + account
        with _lock:
            value = self._read().get(identity)
            if not value:
                return None
            if value.startswith('dpapi:'):
                try:
                    return _windows_protect(base64.b64decode(value[6:]), decrypt=True).decode()
                except OSError:
                    return None
            raw = base64.b64decode(value)
            return self._cipher().decrypt(raw[:12], raw[12:], identity.encode()).decode()

    def delete_password(self, service, account):
        with _lock:
            data = self._read()
            data[service + '\n' + account] = None
            self._save(data)

    def is_deleted(self, service, account):
        data = self._read()
        identity = service + '\n' + account
        return identity in data and data[identity] is None
