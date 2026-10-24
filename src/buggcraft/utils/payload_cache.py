"""Bound versioned onefile payloads without touching game or settings data."""
import atexit
import json
import logging
import os
from pathlib import Path
import re
import shutil
import time
import uuid

logger = logging.getLogger(__name__)
RECORD = '.buggcraft-payload.json'
TAG = re.compile(r'[0-9a-f]{20}')


class FileLock:
    def __init__(self, path):
        if path.is_symlink():
            raise OSError('Cache lock must not be a symbolic link')
        self.stream = path.open('a+b')
        try:
            if self.stream.seek(0, 2) == 0:
                self.stream.write(b'0')
                self.stream.flush()
            self.stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            self.stream.close()
            raise

    def close(self):
        self.stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class PayloadCache:
    def __init__(self, directory):
        self.directory = Path(directory).absolute()
        self.lease = None
        self.lease_path = None

    def _recognized(self, directory):
        return (directory.parent == self.directory.parent
                and directory.parent.name == 'Buggcraft'
                and TAG.fullmatch(directory.name)
                and not directory.is_symlink() and not directory.parent.is_symlink()
                and (directory / 'resources/qml').is_dir()
                and (directory / 'native/manifest.json').is_file())

    def register(self):
        if not self._recognized(self.directory):
            return False
        try:
            with FileLock(self.directory.parent / '.payload-maintenance.lock'):
                self.lease_path = self.directory / f'.active-{os.getpid()}-{uuid.uuid4().hex}.lock'
                self.lease = FileLock(self.lease_path)
                record = self.directory / RECORD
                temporary = self.directory / (RECORD + '.tmp')
                temporary.write_text(json.dumps({'schema': 1, 'tag': self.directory.name,
                                                 'last_used': time.time()}), encoding='utf-8')
                temporary.replace(record)
            atexit.register(self.close)
            return True
        except OSError:
            self.close()
            logger.info('Payload cache registration deferred', exc_info=True)
            return False

    def close(self):
        if self.lease is not None:
            self.lease.close()
            self.lease = None
        if self.lease_path is not None:
            try:
                self.lease_path.unlink(missing_ok=True)
            except OSError:
                pass

    def prune(self, *, now=None, minimum_age=24 * 60 * 60):
        """Keep this payload, the newest previous one, recent and active versions.

        Only payloads registered by this implementation are eligible. Unknown
        legacy cache directories and user folders are deliberately left alone.
        """
        if self.lease is None:
            return []
        now = time.time() if now is None else now
        removed = []
        try:
            with FileLock(self.directory.parent / '.payload-maintenance.lock'):
                candidates = []
                for directory in self.directory.parent.iterdir():
                    if directory == self.directory or not self._recognized(directory):
                        continue
                    try:
                        record = json.loads((directory / RECORD).read_text(encoding='utf-8'))
                        if record.get('schema') != 1 or record.get('tag') != directory.name:
                            continue
                        used = float(record['last_used'])
                        if not used >= 0:
                            continue
                        candidates.append((used, directory))
                    except (OSError, ValueError, TypeError, KeyError):
                        continue
                for used, directory in sorted(candidates, reverse=True)[1:]:
                    if now - used < minimum_age:
                        continue
                    locks = []
                    try:
                        # A running launcher holds its lease even when minimized.
                        for lease in directory.glob('.active-*.lock'):
                            locks.append(FileLock(lease))
                    except OSError:
                        continue
                    finally:
                        for lock in locks:
                            lock.close()
                    try:
                        shutil.rmtree(directory)
                        removed.append(directory.name)
                    except OSError:
                        logger.info('Old payload remains busy: %s', directory.name)
        except OSError:
            logger.info('Payload cache cleanup deferred', exc_info=True)
        if removed:
            logger.info('Removed unused payload caches: %s', ', '.join(removed))
        return removed
