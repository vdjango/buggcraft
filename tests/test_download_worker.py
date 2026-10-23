"""Worker tests cover vanilla publication and loader-generated instance IDs."""
import os
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'buggcraft'))
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication
from ui.pages.download.tasks import DownloadWorker


class DownloadWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def run_worker(self, root, version, loader=None):
        worker = DownloadWorker('task-id', version, str(root), '官方', loader,
                                '1.20.1' if loader else None, '47.2.0' if loader else None, None)
        resolved = QSignalSpy(worker.signals.resolved)
        finished = QSignalSpy(worker.signals.finished)
        worker.run()
        return worker, resolved, finished

    def test_vanilla_worker_publishes_success_without_a_loader_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata = root / 'versions' / '1.21.8' / '1.21.8.json'
            with patch('ui.pages.download.tasks.MinecraftDownloader') as downloader:
                downloader.return_value.install.side_effect = lambda version: (
                    metadata.parent.mkdir(parents=True, exist_ok=True),
                    metadata.write_text('{}', encoding='utf-8'),
                )
                worker, resolved, finished = self.run_worker(root, '1.21.8')
            self.assertEqual(resolved.count(), 0)
            self.assertEqual(finished.at(0), ['task-id', True, '安装完成'])
            self.assertEqual(worker.version, '1.21.8')

    def test_loader_worker_uses_actual_generated_instance_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            actual = '1.20.1-forge-47.2.0-branch'
            metadata = root / 'versions' / actual / (actual + '.json')

            def install(*args, **kwargs):
                metadata.parent.mkdir(parents=True, exist_ok=True)
                metadata.write_text('{}', encoding='utf-8')
                return actual

            with patch('ui.pages.download.tasks.install_loader', side_effect=install):
                worker, resolved, finished = self.run_worker(
                    root, '1.20.1-forge-47.2.0', loader='Forge'
                )
            self.assertEqual(resolved.at(0), ['task-id', actual])
            self.assertEqual(finished.at(0), ['task-id', True, 'Forge 安装完成'])
            self.assertEqual(worker.version, actual)

    def test_selected_api_is_verified_and_installed_into_resolved_instance(self):
        payload = b'api jar fixture'
        record = dict(name='API fixture', game_versions=['1.20.1'], files=[dict(
            url='https://cdn.modrinth.com/fixture.jar', filename='fixture.jar',
            size=len(payload), hashes={'sha1': hashlib.sha1(payload).hexdigest()})])
        for isolated in (True, False):
            with self.subTest(isolated=isolated), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                actual = 'fabric-loader-actual-1.20.1'
                metadata = root / 'versions' / actual / (actual + '.json')
                def install(*args, **kwargs):
                    metadata.parent.mkdir(parents=True)
                    metadata.write_text('{}', encoding='utf-8')
                    return actual
                response = MagicMock()
                response.__enter__.return_value = response
                response.iter_content.return_value = [payload]
                worker = DownloadWorker('api', 'requested', str(root), '官方', 'Fabric',
                                        '1.20.1', 'actual', addons=[dict(name='Fabric API', version=record)],
                                        isolated=isolated)
                finished = QSignalSpy(worker.signals.finished)
                with patch('ui.pages.download.tasks.install_loader', side_effect=install), \
                        patch('core.content.requests.get', return_value=response):
                    worker.run()
                self.assertTrue(finished.at(0)[1])
                target = metadata.parent if isolated else root
                self.assertEqual((target / 'mods/fixture.jar').read_bytes(), payload)

    def test_incompatible_api_fails_before_installing_and_bad_hash_never_succeeds(self):
        with tempfile.TemporaryDirectory() as temporary:
            worker = DownloadWorker('api', 'requested', temporary, '官方', 'Forge', '1.20.1',
                '47', addons=[dict(name='Fabric API', version={})])
            finished = QSignalSpy(worker.signals.finished)
            with patch('ui.pages.download.tasks.install_loader') as install:
                worker.run()
            install.assert_not_called()
            self.assertFalse(finished.at(0)[1])
            actual = 'fabric-fixture'
            metadata = Path(temporary) / 'versions' / actual / (actual + '.json')
            metadata.parent.mkdir(parents=True)
            metadata.write_text('{}')
            record = dict(files=[dict(url='https://cdn.modrinth.com/fixture.jar', filename='fixture.jar',
                                      hashes={'sha1': '0' * 40}, size=3)])
            worker = DownloadWorker('bad-api', 'requested', temporary, '官方', 'Fabric', '1.20.1',
                                    'actual', addons=[dict(name='Fabric API', version=record)])
            finished = QSignalSpy(worker.signals.finished)
            resolved = QSignalSpy(worker.signals.resolved)
            response = MagicMock()
            response.__enter__.return_value = response
            response.iter_content.return_value = [b'bad']
            with patch('ui.pages.download.tasks.install_loader', return_value=actual), \
                    patch('core.content.requests.get', return_value=response):
                worker.run()
            self.assertFalse(finished.at(0)[1])
            self.assertEqual(resolved.count(), 0)
            self.assertFalse((metadata.parent / 'mods/fixture.jar').exists())
            self.assertFalse(list(metadata.parent.rglob('*.buggcraft-part')))


if __name__ == '__main__':
    unittest.main(verbosity=2)
