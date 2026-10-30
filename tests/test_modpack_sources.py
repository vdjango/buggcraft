"""Public mod lookup must fail closed when a catalogue or CDN is unavailable."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'buggcraft'))
from core.modpack_sources import _fingerprint, find_public_mod_downloads


class _Response:
    def __init__(self, data, status=200, headers=None):
        self.data, self.status_code, self.headers = data, status, headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise ValueError('lookup unavailable')

    def json(self):
        return self.data

    def iter_content(self, chunk_size=1):
        yield b'x'


class PublicModLookupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'sample.jar'
        self.path.write_bytes(b'local mod bytes')
        self.item = {'path': 'mods/sample.jar', 'source': self.path,
                     'sha1': hashlib.sha1(self.path.read_bytes()).hexdigest(),
                     'size': self.path.stat().st_size}

    def test_modrinth_exact_hash_and_reachable_cdn_are_linked(self):
        url = 'https://cdn.modrinth.com/data/test/sample.jar'
        version = {'files': [{'url': url, 'size': self.item['size'],
                              'hashes': {'sha1': self.item['sha1']}}]}
        with patch('core.modpack_sources.requests.post', side_effect=[
                _Response({self.item['sha1']: version}), _Response({'data': {'exactMatches': []}})]) as post, \
                patch('core.modpack_sources.requests.get', return_value=_Response(
                    None, 206, {'Content-Range': f"bytes 0-0/{self.item['size']}"})):
            progress = []
            result = find_public_mod_downloads([self.item], progress=lambda *row: progress.append(row))
        self.assertEqual(result['mods/sample.jar']['downloads'], [url])
        self.assertEqual(progress[-1][1:], (4, 4))
        self.assertEqual([row[1] for row in progress], sorted(row[1] for row in progress))
        self.assertIn('/version_files', post.call_args_list[0].args[0])
        self.assertIn('/fingerprints/432', post.call_args_list[1].args[0])

    def test_curseforge_exact_fingerprint_and_hash_are_linked(self):
        url = 'https://edge.forgecdn.net/files/1/2/sample.jar'
        fingerprint = _fingerprint(self.path)
        file = {'fileFingerprint': fingerprint, 'fileLength': self.item['size'],
                'isAvailable': True, 'hashes': [{'algo': 1, 'value': self.item['sha1']}],
                'downloadUrl': url}
        with patch('core.modpack_sources.requests.post', side_effect=[
                _Response({}), _Response({'data': {'exactMatches': [{'id': 999, 'file': file}]}})]), \
                patch('core.modpack_sources.requests.get', return_value=_Response(
                    None, 206, {'Content-Range': f"bytes 0-0/{self.item['size']}"})):
            result = find_public_mod_downloads([self.item])
        self.assertEqual(result['mods/sample.jar']['downloads'], [url])

    def test_transient_cdn_timeout_is_retried_before_embedding(self):
        url = 'https://cdn.modrinth.com/data/test/sample.jar'
        version = {'files': [{'url': url, 'size': self.item['size'],
                              'hashes': {'sha1': self.item['sha1']}}]}
        with patch('core.modpack_sources.requests.post', side_effect=[
                _Response({self.item['sha1']: version}), _Response({'data': {'exactMatches': []}})]), \
                patch('core.modpack_sources.requests.get', side_effect=[
                    requests.Timeout('temporary timeout'),
                    _Response(None, 206, {'Content-Range': f"bytes 0-0/{self.item['size']}"})]) as get, \
                patch('core.modpack_sources.time.sleep'):
            result = find_public_mod_downloads([self.item])
        self.assertEqual(result['mods/sample.jar']['downloads'], [url])
        self.assertEqual(get.call_count, 2)

    def test_stale_url_wrong_hash_or_missing_publication_stays_embedded(self):
        url = 'https://cdn.modrinth.com/data/test/sample.jar'
        wrong = {'files': [{'url': url, 'size': self.item['size'], 'hashes': {'sha1': '0' * 40}}]}
        valid = {'files': [{'url': url, 'size': self.item['size'],
                            'hashes': {'sha1': self.item['sha1']}}]}
        for version, status in ((wrong, 206), (valid, 404)):
            with self.subTest(version=version, status=status), \
                    patch('core.modpack_sources.requests.post', side_effect=[
                        _Response({self.item['sha1']: version}),
                        _Response({'data': {'exactMatches': []}})]), \
                    patch('core.modpack_sources.requests.get', return_value=_Response(None, status)):
                self.assertEqual(find_public_mod_downloads([self.item]), {})


if __name__ == '__main__':
    unittest.main()
