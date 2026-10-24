"""Exercise cache deletion boundaries and real operating-system file locks."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from utils.payload_cache import PayloadCache, RECORD


class PayloadCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'Buggcraft'
        self.root.mkdir()
        self.now = time.time()

    def payload(self, number, age):
        directory = self.root / f'{number:020x}'
        (directory / 'resources/qml').mkdir(parents=True)
        (directory / 'native').mkdir()
        (directory / 'native/manifest.json').write_text('{}')
        (directory / RECORD).write_text(json.dumps({
            'schema': 1, 'tag': directory.name, 'last_used': self.now - age}))
        return directory

    def register(self, directory):
        cache = PayloadCache(directory)
        self.assertTrue(cache.register())
        self.addCleanup(cache.close)
        return cache

    def test_only_old_known_payloads_are_deleted_and_previous_release_is_kept(self):
        current = self.payload(1, 0)
        recent = self.payload(2, 20)
        previous = self.payload(3, 2 * 86400)
        old = self.payload(4, 3 * 86400)
        unknown = self.payload(5, 4 * 86400)
        (unknown / RECORD).unlink()
        user = self.root / '.minecraft'
        user.mkdir()
        (user / 'save').write_bytes(b'world')
        cache = self.register(current)
        self.assertEqual(set(cache.prune(now=self.now)), {previous.name, old.name})
        self.assertTrue(current.is_dir())
        self.assertTrue(recent.is_dir())
        self.assertTrue(unknown.is_dir())
        self.assertEqual((user / 'save').read_bytes(), b'world')

    def test_running_payload_in_another_process_is_never_removed(self):
        current = self.payload(1, 0)
        self.payload(2, 2 * 86400)
        active = self.payload(3, 3 * 86400)
        cache = self.register(current)
        code = ('from pathlib import Path; import sys; '
                'from utils.payload_cache import FileLock; '
                'lock=FileLock(Path(sys.argv[1])); print("ready",flush=True); sys.stdin.readline()')
        process = subprocess.Popen([sys.executable, '-u', '-c', code,
                                    str(active / '.active-child.lock')],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                                   env=dict(os.environ, PYTHONPATH=str(
                                       Path(__file__).resolve().parents[1] / 'src/buggcraft')))
        try:
            self.assertEqual(process.stdout.readline().strip(), 'ready')
            self.assertEqual(cache.prune(now=self.now), [])
            self.assertTrue(active.is_dir())
        finally:
            process.communicate('\n', timeout=10)
        self.assertEqual(cache.prune(now=self.now), [active.name])

    def test_wrong_root_or_unregistered_payload_cannot_prune(self):
        unregistered = PayloadCache(self.payload(1, 0))
        self.assertEqual(unregistered.prune(now=self.now), [])
        outside = Path(self.temporary.name) / 'not-a-cache' / ('a' * 20)
        outside.mkdir(parents=True)
        self.assertFalse(PayloadCache(outside).register())

    def test_symlink_and_forged_metadata_are_not_followed(self):
        current = self.payload(1, 0)
        self.payload(2, 2 * 86400)
        forged = self.payload(3, 3 * 86400)
        (forged / RECORD).write_text('{"schema": 1, "tag": "other", "last_used": 0}')
        cache = self.register(current)
        self.assertEqual(cache.prune(now=self.now), [])
        self.assertTrue(forged.is_dir())
        external = Path(self.temporary.name) / 'outside'
        external.mkdir()
        link = self.root / ('f' * 20)
        try:
            link.symlink_to(external, target_is_directory=True)
        except OSError:
            return
        self.assertEqual(cache.prune(now=self.now), [])
        self.assertTrue(external.is_dir())
