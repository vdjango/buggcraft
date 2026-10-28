import hashlib
import json
import sys
import unittest
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'buggcraft'))
from core.content import ContentCatalogue, ModrinthClient, download_content, instance_environment
from config.downloads import DEFAULT_CONCURRENCY
from core.downloads import _CONTENT_ROUTE_CACHE, _rank_content_candidates
from core.curseforge import CurseForgeContentClient


class ContentDownloadTests(unittest.TestCase):
    def setUp(self):
        probe = patch('core.downloads._measure_content_route', return_value=100_000)
        probe.start()
        self.addCleanup(probe.stop)
        _CONTENT_ROUTE_CACHE.clear()
        self.addCleanup(_CONTENT_ROUTE_CACHE.clear)

    def test_automatic_source_ranking_uses_cached_measured_speed(self):
        mirror = 'https://mod.mcimirror.top/data/sample.jar'
        upstream = 'https://cdn.modrinth.com/data/sample.jar'
        with patch('core.downloads._measure_content_route', side_effect=lambda url: 200_000 if 'mcimirror' in url else 1_000_000):
            _CONTENT_ROUTE_CACHE.clear()
            self.assertEqual(_rank_content_candidates([mirror, upstream]), [upstream, mirror])
            with patch('core.downloads._measure_content_route', side_effect=AssertionError('probe cache missed')):
                self.assertEqual(_rank_content_candidates([mirror, upstream]), [upstream, mirror])
        _CONTENT_ROUTE_CACHE.clear()

    def test_mcim_preference_only_wins_when_close_to_fastest_source(self):
        mirror = 'https://mod.mcimirror.top/data/sample.jar'
        upstream = 'https://cdn.modrinth.com/data/sample.jar'
        with patch('core.downloads._measure_content_route', side_effect=lambda url: 900_000 if 'mcimirror' in url else 1_000_000):
            _CONTENT_ROUTE_CACHE.clear()
            self.assertEqual(_rank_content_candidates([upstream, mirror], 'MCIM'), [mirror, upstream])
        _CONTENT_ROUTE_CACHE.clear()

    def test_both_provider_searches_receive_offset_without_implicit_version_filters(self):
        catalogue = ContentCatalogue()
        with patch.object(catalogue.clients['Modrinth'], 'search', return_value=[dict(project_id='mr')]) as mr, \
                patch.object(catalogue.clients['CurseForge'], 'search', return_value=[dict(project_id='cf')]) as cf:
            data = catalogue.search('fixture', 'mod', offset=20, limit=1, page_info=True)
        for call in (mr, cf):
            call.assert_called_once_with('fixture', 'mod', '', '', 1, 20)
        self.assertTrue(data['has_more'])
        self.assertEqual([row['source'] for row in data['hits']], ['Modrinth', 'CurseForge'])

    def test_curseforge_keeps_pagination_when_page_contains_unavailable_files(self):
        client = CurseForgeContentClient()
        project = dict(id=10, gameId=432, classId=6)
        item = dict(id=20, modId=10, fileName='fixture.jar', fileLength=1,
            gameVersions=['1.20.1', '1.20.2', 'Forge'], hashes=[dict(algo=1, value='0' * 40)])
        with patch.object(client, 'get', side_effect=[project, [dict(item, id=i, isAvailable=i != 1) for i in range(1, 51)]]):
            page = client.versions('10', page_info=True)
        self.assertEqual(len(page['versions']), 49)
        self.assertTrue(page['has_more'])
        self.assertEqual(page['next_offset'], 50)
        self.assertEqual(page['versions'][0]['game_versions'], ['1.20.1', '1.20.2'])
        self.assertEqual(page['versions'][0]['loaders'], ['forge'])

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
        with TemporaryDirectory() as root, patch('core.downloads._DownloadSession.get', return_value=self._response(payload)):
            download_content(version, root, 'modpack')
            self.assertEqual((Path(root) / 'modpacks/pack.mrpack').read_bytes(), payload)

    def test_hash_mismatch_does_not_publish_file(self):
        payload = b'modrinth-content'
        version = {'files': [{'url': 'https://cdn.modrinth.com/x.jar', 'filename': 'x.jar',
                              'hashes': {'sha1': '0' * 40}, 'size': len(payload)}]}
        with TemporaryDirectory() as root, patch('core.downloads._DownloadSession.get', return_value=self._response(payload)):
            with self.assertRaisesRegex(RuntimeError, '校验失败'):
                download_content(version, root, 'mod')
            self.assertFalse((Path(root) / 'mods/x.jar').exists())

    def test_content_files_download_in_parallel_with_a_bounded_pool(self):
        payloads = {f'mod-{index}.jar': f'payload-{index}'.encode() for index in range(4)}
        version = {'files': [
            {'url': f'https://cdn.modrinth.com/{name}', 'filename': name,
             'hashes': {'sha1': hashlib.sha1(payload).hexdigest()}, 'size': len(payload)}
            for name, payload in payloads.items()]}
        version['kind'] = 'modpack'
        active = 0
        peak = 0
        lock = threading.Lock()

        def response(session, url, **kwargs):
            nonlocal active, peak
            name = Path(url).name
            body = payloads[name]
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.03)
            with lock:
                active -= 1
            return self._response(body)

        with TemporaryDirectory() as root, patch('core.downloads.download_concurrency', return_value=DEFAULT_CONCURRENCY), \
                patch('core.downloads._DownloadSession.get', response):
            download_content(version, root, 'modpack')
            self.assertGreaterEqual(peak, 2)
            self.assertLessEqual(peak, DEFAULT_CONCURRENCY)
            self.assertEqual(sorted(path.name for path in (Path(root) / 'modpacks').iterdir()), sorted(payloads))

    def test_content_download_supports_the_configured_64_file_ceiling(self):
        barrier = threading.Barrier(64, timeout=15)
        payloads = {f'mod-{index}.jar': f'payload-{index}'.encode() for index in range(64)}
        version = {'files': [
            {'url': f'https://cdn.modrinth.com/{name}', 'filename': name,
             'hashes': {'sha1': hashlib.sha1(payload).hexdigest()}, 'size': len(payload)}
            for name, payload in payloads.items()]}
        version['kind'] = 'modpack'
        active = 0
        peak = 0
        lock = threading.Lock()

        def response(session, url, **kwargs):
            nonlocal active, peak
            name = Path(url).name
            with lock:
                active += 1
                peak = max(peak, active)
            barrier.wait()
            with lock:
                active -= 1
            return self._response(payloads[name])

        with TemporaryDirectory() as root, patch('core.downloads.download_concurrency', return_value=64), \
                patch('core.downloads._DownloadSession.get', response):
            download_content(version, root, 'modpack')
        self.assertEqual(peak, 64)
        self.assertLessEqual(peak, 64)

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
