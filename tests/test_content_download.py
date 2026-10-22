import hashlib
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'buggcraft'))
from core.content import ModrinthClient, download_content, instance_environment


class ContentDownloadTests(unittest.TestCase):
    def _response(self, payload):
        response = MagicMock()
        response.__enter__.return_value = response
        response.iter_content.return_value = [payload]
        return response

    def test_verified_modpack_download_is_written_to_type_directory(self):
        payload = b'modrinth-content'
        version = {'files': [{'url': 'https://cdn.modrinth.com/pack.mrpack',
                              'filename': 'pack.mrpack', 'hashes': {'sha1': hashlib.sha1(payload).hexdigest()},
                              'size': len(payload)}]}
        with TemporaryDirectory() as root, patch('core.content.requests.get', return_value=self._response(payload)):
            download_content(version, root, 'modpack')
            self.assertEqual((Path(root) / 'modpacks/pack.mrpack').read_bytes(), payload)

    def test_hash_mismatch_does_not_publish_file(self):
        payload = b'modrinth-content'
        version = {'files': [{'url': 'https://cdn.modrinth.com/x.jar', 'filename': 'x.jar',
                              'hashes': {'sha1': '0' * 40}, 'size': len(payload)}]}
        with TemporaryDirectory() as root, patch('core.content.requests.get', return_value=self._response(payload)):
            with self.assertRaises(ValueError):
                download_content(version, root, 'mod')
            self.assertFalse((Path(root) / 'mods/x.jar').exists())

    def test_resourcepack_versions_are_not_filtered_by_loader(self):
        client = ModrinthClient()
        with patch.object(client, '_get', return_value=[]) as get:
            client.versions('sample', '1.20.1', 'fabric', 'resourcepack')
        self.assertEqual(get.call_args.args[0], '/project/sample/version')
        self.assertEqual(get.call_args.args[1], {'game_versions': '["1.20.1"]'})

    def test_inherited_instance_resolves_base_version_and_loader(self):
        with TemporaryDirectory() as directory:
            versions = Path(directory) / 'versions'
            loader = versions / 'fabric-loader-0.16.0-1.20.1'
            base = versions / '1.20.1'
            loader.mkdir(parents=True)
            base.mkdir()
            (loader / f'{loader.name}.json').write_text(json.dumps({
                'inheritsFrom': '1.20.1',
                'libraries': [{'name': 'net.fabricmc:fabric-loader:0.16.0'}],
            }), encoding='utf-8')
            (base / '1.20.1.json').write_text(json.dumps({'libraries': []}), encoding='utf-8')
            self.assertEqual(instance_environment(directory, loader.name), ('1.20.1', 'fabric'))


if __name__ == '__main__':
    unittest.main()
