"""Public mod lookup must fail closed when a catalogue or CDN is unavailable."""
import hashlib
import json
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

    def test_no_curseforge_publication_does_not_query_or_probe_modrinth(self):
        with patch('core.modpack_sources.requests.post', return_value=_Response(
                {'data': {'exactMatches': []}})) as post, \
                patch('core.modpack_sources.requests.get') as get:
            result = find_public_mod_downloads([self.item])
        self.assertEqual(result, {})
        self.assertEqual(post.call_count, 1)
        self.assertIn('/fingerprints/432', post.call_args.args[0])
        get.assert_not_called()

    def test_modrinth_only_uses_hash_endpoint_without_curseforge_or_filename_search(self):
        url = 'https://cdn.modrinth.com/data/project/versions/version/original.jar'
        response = {self.item['sha1']: {'files': [dict(url=url, size=self.item['size'],
                    hashes={'sha1': self.item['sha1']})]}}
        with patch('core.modpack_sources.requests.post', return_value=_Response(response)) as post, \
                patch('core.modpack_sources.requests.get', return_value=_Response(
                    None, 206, {'Content-Range': f"bytes 0-0/{self.item['size']}"})), \
                patch('core.modpack_sources._fingerprint', side_effect=AssertionError('CF not selected')):
            result = find_public_mod_downloads([self.item], publisher='Modrinth')
        self.assertEqual(result[self.item['path']]['downloads'], [url])
        self.assertEqual(post.call_args.args[0], 'https://api.modrinth.com/v2/version_files')
        self.assertEqual(post.call_args.kwargs['json'], {'hashes': [self.item['sha1']], 'algorithm': 'sha1'})

    def test_mixed_lists_curseforge_before_modrinth_and_never_uses_wrong_build(self):
        cf, mr = 'https://edge.forgecdn.net/files/1/2/sample.jar', 'https://cdn.modrinth.com/data/x.jar'
        file = dict(fileFingerprint=_fingerprint(self.path), fileLength=self.item['size'],
                    hashes=[{'algo': 1, 'value': self.item['sha1']}], downloadUrl=cf)
        for sha1 in (self.item['sha1'], '0' * 40):
            with self.subTest(sha1=sha1), patch('core.modpack_sources.requests.post', side_effect=[
                    _Response({'data': {'exactMatches': [{'file': file}]}}),
                    _Response({self.item['sha1']: {'files': [dict(url=mr, size=self.item['size'], hashes={'sha1': sha1})]}})]), \
                    patch('core.modpack_sources.requests.get', return_value=_Response(
                        None, 206, {'Content-Range': f"bytes 0-0/{self.item['size']}"})):
                result = find_public_mod_downloads([self.item], publisher='混合')
            self.assertEqual(result[self.item['path']]['downloads'], [cf, mr] if sha1 == self.item['sha1'] else [cf])

    def test_curseforge_exact_fingerprint_and_hash_are_linked(self):
        url = 'https://edge.forgecdn.net/files/1/2/sample.jar'
        fingerprint = _fingerprint(self.path)
        file = {'fileFingerprint': fingerprint, 'fileLength': self.item['size'],
                'isAvailable': True, 'hashes': [{'algo': 1, 'value': self.item['sha1']}],
                'downloadUrl': url}
        with patch('core.modpack_sources.requests.post', return_value=
                _Response({'data': {'exactMatches': [{'id': 999, 'file': file}]}})), \
                patch('core.modpack_sources.requests.get', return_value=_Response(
                    None, 206, {'Content-Range': f"bytes 0-0/{self.item['size']}"})):
            progress = []
            result = find_public_mod_downloads([self.item], progress=lambda *row: progress.append(row))
        self.assertEqual(result['mods/sample.jar']['downloads'], [url])
        self.assertEqual(progress[-1][1:], (3, 3))
        self.assertEqual([row[1] for row in progress], sorted(row[1] for row in progress))

    def test_transient_cdn_timeout_is_retried_before_embedding(self):
        url = 'https://edge.forgecdn.net/files/1/2/sample.jar'
        file = dict(fileFingerprint=_fingerprint(self.path), fileLength=self.item['size'],
                    hashes=[{'algo': 1, 'value': self.item['sha1']}], downloadUrl=url)
        with patch('core.modpack_sources.requests.post', return_value=
                _Response({'data': {'exactMatches': [{'file': file}]}})), \
                patch('core.modpack_sources.requests.get', side_effect=[
                    requests.Timeout('temporary timeout'),
                    _Response(None, 206, {'Content-Range': f"bytes 0-0/{self.item['size']}"})]) as get, \
                patch('core.modpack_sources.time.sleep'):
            result = find_public_mod_downloads([self.item])
        self.assertEqual(result['mods/sample.jar']['downloads'], [url])
        self.assertEqual(get.call_count, 2)

    def test_stale_url_wrong_hash_or_missing_publication_stays_embedded(self):
        valid = dict(fileFingerprint=_fingerprint(self.path), fileLength=self.item['size'],
                     hashes=[{'algo': 1, 'value': self.item['sha1']}],
                     downloadUrl='https://edge.forgecdn.net/files/1/2/sample.jar')
        for digest, status in (('0' * 40, 206), (self.item['sha1'], 404)):
            file = dict(valid, hashes=[{'algo': 1, 'value': digest}])
            with self.subTest(digest=digest, status=status), \
                    patch('core.modpack_sources.requests.post', return_value=
                        _Response({'data': {'exactMatches': [{'file': file}]}})), \
                    patch('core.modpack_sources.requests.get', return_value=_Response(None, status)):
                self.assertEqual(find_public_mod_downloads([self.item]), {})

    def test_null_download_url_uses_exact_curseforge_file_id_and_validates_hash(self):
        file = dict(id=8644600, fileName='sample.jar', downloadUrl=None,
                    fileFingerprint=_fingerprint(self.path), fileLength=self.item['size'],
                    hashes=[{'algo': 1, 'value': self.item['sha1']}])
        with patch('core.modpack_sources.requests.post', return_value=_Response(
                {'data': {'exactMatches': [{'file': file}]}})), \
                patch('core.modpack_sources.requests.get', return_value=_Response(
                    None, 206, {'Content-Range': f"bytes 0-0/{self.item['size']}"})) as get:
            result = find_public_mod_downloads([self.item])
        self.assertEqual(result[self.item['path']]['downloads'],
                         ['https://edge.forgecdn.net/files/8644/600/sample.jar'])
        self.assertIn('edge.forgecdn.net', get.call_args.args[0])

    def test_curseforge_redirect_to_modrinth_is_not_exported(self):
        file = dict(fileFingerprint=_fingerprint(self.path), fileLength=self.item['size'],
                    hashes=[{'algo': 1, 'value': self.item['sha1']}],
                    downloadUrl='https://edge.forgecdn.net/files/1/2/sample.jar')
        with patch('core.modpack_sources.requests.post', return_value=_Response(
                {'data': {'exactMatches': [{'file': file}]}})), \
                patch('core.modpack_sources.requests.get', return_value=_Response(
                    None, 302, {'Location': 'https://cdn.modrinth.com/data/a.jar'})) as get:
            self.assertEqual(find_public_mod_downloads([self.item]), {})
        self.assertEqual(get.call_count, 2)
        self.assertTrue(all('forgecdn.net/' in call.args[0] for call in get.call_args_list))

    def test_edge_404_uses_same_file_on_mediafilez_before_embedding(self):
        file = dict(id=8644600, fileName='sample.jar', downloadUrl=None,
                    fileFingerprint=_fingerprint(self.path), fileLength=self.item['size'],
                    hashes=[{'algo': 1, 'value': self.item['sha1']}])
        with patch('core.modpack_sources.requests.post', return_value=_Response(
                {'data': {'exactMatches': [{'file': file}]}})), \
                patch('core.modpack_sources.requests.get', side_effect=[_Response(None, 404),
                    _Response(None, 206, {'Content-Range': f"bytes 0-0/{self.item['size']}"})]) as get:
            result = find_public_mod_downloads([self.item])
        self.assertEqual(result[self.item['path']]['downloads'],
                         ['https://mediafilez.forgecdn.net/files/8644/600/sample.jar'])
        self.assertEqual(get.call_count, 2)

    def test_reexport_and_rename_reuse_fingerprint_but_still_validate_server_hash(self):
        cache = self.path.parent / 'cache/fingerprints.json'
        fingerprint = _fingerprint(self.path)
        file = dict(fileFingerprint=fingerprint, fileLength=self.item['size'],
                    hashes=[{'algo': 1, 'value': self.item['sha1']}],
                    downloadUrl='https://edge.forgecdn.net/files/1/2/sample.jar')
        response = _Response({'data': {'exactMatches': [{'file': file}]}})
        with patch('core.modpack_sources.requests.post', return_value=response), \
                patch('core.modpack_sources.requests.get', return_value=_Response(
                    None, 206, {'Content-Range': f"bytes 0-0/{self.item['size']}"})):
            self.assertTrue(find_public_mod_downloads([self.item], cache_file=cache))
            self.assertEqual(json.loads(cache.read_text())[self.item['sha1'] + ':' + str(self.item['size'])], fingerprint)
            renamed = dict(self.item, path='mods/unrelated.jar')
            with patch('core.modpack_sources._fingerprint', side_effect=AssertionError('recomputed')):
                self.assertIn(renamed['path'], find_public_mod_downloads([renamed], cache_file=cache))
                file['hashes'][0]['value'] = '0' * 40
                self.assertEqual(find_public_mod_downloads([renamed], cache_file=cache), {})

    def test_changed_bytes_or_invalid_cache_recompute_fingerprint(self):
        cache = self.path.parent / 'cache.json'
        with patch('core.modpack_sources.requests.post', return_value=_Response(
                {'data': {'exactMatches': []}})):
            for contents in ('invalid JSON', '[]', json.dumps({self.item['sha1'] + ':' + str(self.item['size']): -1}),
                             json.dumps({'other-sha1:' + str(self.item['size']): 42})):
                with self.subTest(contents=contents), patch('core.modpack_sources._fingerprint', return_value=42) as fingerprint:
                    cache.write_text(contents, encoding='utf-8')
                    self.assertEqual(find_public_mod_downloads([self.item], cache_file=cache), {})
                    fingerprint.assert_called_once_with(self.path, None)


if __name__ == '__main__':
    unittest.main()
