"""Worker tests cover vanilla publication and loader-generated instance IDs."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

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


if __name__ == '__main__':
    unittest.main(verbosity=2)
