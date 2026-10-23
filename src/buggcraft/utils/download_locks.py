"""Coordinate concurrent tasks that share verified caches and library files."""
from contextlib import contextmanager
import os
from pathlib import Path
import threading

_guard = threading.Lock()
_files = {}


@contextmanager
def download_lock(path, cancel=None):
    key = os.path.normcase(str(Path(path).resolve()))
    with _guard:
        entry = _files.setdefault(key, [threading.RLock(), 0])
        entry[1] += 1
    acquired = False
    try:
        while not acquired:
            if cancel is not None and cancel.is_set():
                raise InterruptedError('下载已取消')
            acquired = entry[0].acquire(timeout=0.1)
        yield
    finally:
        if acquired:
            entry[0].release()
        with _guard:
            entry[1] -= 1
            if not entry[1]:
                _files.pop(key)
