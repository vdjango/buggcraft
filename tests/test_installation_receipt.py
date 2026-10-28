"""Receipts must track installed files, not JVM-generated temporary DLLs."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.downloads import MinecraftDownloader, verified_installation


class InstallationReceiptTests(unittest.TestCase):
    def test_new_receipt_does_not_publish_jna_runtime_temporary_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            native = root / 'versions/1.21.8/natives'
            native.mkdir(parents=True)
            for name in ('glfw.dll', 'jna.dll', 'jna12345.dll', 'jna12345.dll.x'):
                (native / name).write_bytes(b'native fixture')
            downloader = MinecraftDownloader(root)
            metadata = dict(id='1.21.8', downloads=dict(client=dict(url='https://example.invalid/client.jar')))

            def download_client(_jobs, _message):
                client = root / 'versions/1.21.8/1.21.8.jar'
                client.write_bytes(b'client fixture')
                downloader._verified[str(client.relative_to(root))] = hashlib.sha1(client.read_bytes()).hexdigest()

            with patch.object(downloader, '_batch', side_effect=download_client):
                downloader.install_metadata('1.21.8', metadata)
            receipt = json.loads((native.parent / '.buggcraft-complete.json').read_text())
            paths = {item['path'].replace('\\', '/') for item in receipt['files']}
            self.assertIn('versions/1.21.8/natives/glfw.dll', paths)
            self.assertIn('versions/1.21.8/natives/jna.dll', paths)
            self.assertNotIn('versions/1.21.8/natives/jna12345.dll', paths)
            self.assertNotIn('versions/1.21.8/natives/jna12345.dll.x', paths)
            (native / 'jna12345.dll').unlink()
            (native / 'jna12345.dll.x').unlink()
            self.assertTrue(verified_installation(root, '1.21.8'))

    def test_old_jna_temporary_files_do_not_trigger_full_reinstallation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            version = root / 'versions/1.21.8'
            version.mkdir(parents=True)
            client = version / '1.21.8.jar'
            client.write_bytes(b'validated client')
            files = [dict(path='versions/1.21.8/1.21.8.jar',
                          sha1=hashlib.sha1(client.read_bytes()).hexdigest())]
            for path in ('jna12345.dll', 'jna12345.dll.x'):
                files.append(dict(path='versions\\1.21.8\\natives\\' + path, sha1='old-temporary-hash'))
            receipt = version / '.buggcraft-complete.json'
            receipt.write_text(json.dumps(dict(version='1.21.8', files=files)))
            self.assertTrue(verified_installation(root, '1.21.8'))
            client.write_bytes(b'corrupted client')
            self.assertFalse(verified_installation(root, '1.21.8'))

    def test_required_native_and_jna_files_outside_temporary_directory_still_validate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            version = root / 'versions/1.21.8'
            version.mkdir(parents=True)
            receipt = version / '.buggcraft-complete.json'
            for path in ('versions/1.21.8/natives/glfw.dll', 'libraries/jna12345.dll',
                         'versions/1.21.8/natives/jna.dll'):
                with self.subTest(path=path):
                    receipt.write_text(json.dumps(dict(version='1.21.8', files=[dict(path=path)])))
                    self.assertFalse(verified_installation(root, '1.21.8'))
