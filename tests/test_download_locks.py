"""Shared-cache locking survives Windows path aliases and cancellation."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from utils.download_locks import download_lock


class DownloadLockTests(unittest.TestCase):
    def test_extended_and_plain_windows_paths_cannot_write_the_same_cache_concurrently(self):
        for plain, extended in ((r'C:\Games\libraries\shared.jar', r'\\?\C:\Games\libraries\shared.jar'),
                                (r'\\server\games\shared.jar', r'\\?\UNC\server\games\shared.jar')):
            with self.subTest(path=plain):
                held, attempted, entered, release = (threading.Event() for _ in range(4))
                def writer(alias):
                    if alias == extended:
                        attempted.set()
                    with download_lock(alias):
                        if alias == plain:
                            held.set()
                            if not release.wait(3):
                                raise TimeoutError('First writer was not released')
                        else:
                            entered.set()
                # Reproduce the two real return values of Windows resolve().
                with patch('utils.download_locks.Path', side_effect=lambda value: Mock(resolve=lambda: value)):
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        first = pool.submit(writer, plain)
                        try:
                            self.assertTrue(held.wait(2))
                            second = pool.submit(writer, extended)
                            self.assertTrue(attempted.wait(2))
                            self.assertFalse(entered.wait(.15), 'Same cache file had two simultaneous writers')
                        finally:
                            release.set()
                        first.result(timeout=2)
                        second.result(timeout=2)
                self.assertTrue(entered.is_set())

    def test_cancelled_waiter_releases_its_reference_without_unlocking_active_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'runtime/java'
            cancelled = threading.Event()
            attempted = threading.Event()
            def waiter():
                attempted.set()
                with download_lock(target, cancelled):
                    self.fail('Cancelled waiter acquired the active download')
            with download_lock(target), ThreadPoolExecutor(max_workers=1) as pool:
                task = pool.submit(waiter)
                self.assertTrue(attempted.wait(2))
                cancelled.set()
                with self.assertRaises(InterruptedError):
                    task.result(timeout=2)
            with download_lock(target):
                target.parent.mkdir(parents=True)
                target.write_bytes(b'verified Java cache')
            self.assertEqual(target.read_bytes(), b'verified Java cache')
