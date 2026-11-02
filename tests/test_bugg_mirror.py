"""Buggcraft is the only automatic fallback for selected download sources."""
import hashlib
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import requests
from core import bugg_mirror
from core.game_sources import source_urls
from core.downloads import DownloadSourcesExhausted, MinecraftDownloader
from tempfile import TemporaryDirectory


class BuggMirrorTests(unittest.TestCase):
    def test_selected_origin_failure_discovers_alternatives_after_first_attempt(self):
        payload = b'verified fallback mod'
        original = 'https://cdn.modrinth.com/data/project/versions/release/example.jar'
        alternate = 'https://edge.forgecdn.net/files/123/456/example.jar'
        own = bugg_mirror.mirror_url(original)
        visited = []

        def download(_session, url, **kwargs):
            visited.append(url)
            if url != alternate:
                response = requests.Response()
                response.status_code = 404
                response.url = url
                raise requests.HTTPError('not found', response=response)
            response = MagicMock()
            response.__enter__.return_value = response
            response.url, response.status_code, response.headers = url, 200, {}
            response.iter_content.return_value = [payload]
            return response

        def discover(addresses, *args, **kwargs):
            self.assertEqual(visited[0], own)
            return [*addresses, alternate]

        with TemporaryDirectory() as root, \
                patch('core.content_routes.resolve_download_urls', side_effect=discover) as lookup, \
                patch('core.downloads._DownloadSession.get', download):
            downloader = MinecraftDownloader(root, source='Buggcraft', retries=0)
            downloader.content_source = 'Buggcraft'
            downloader.resolve_content_sources = True
            downloader.fetch(original, 'mods/example.jar', hashlib.sha1(payload).hexdigest(), len(payload))
            self.assertEqual((Path(root) / 'mods/example.jar').read_bytes(), payload)
            lookup.assert_called_once()
        self.assertEqual(visited[-1], alternate)

    def test_selected_origin_hit_does_not_wait_for_publisher_discovery(self):
        payload = b'verified mod'
        original = 'https://cdn.modrinth.com/data/project/versions/release/example.jar'
        own = bugg_mirror.mirror_url(original)
        response = MagicMock()
        response.__enter__.return_value = response
        response.url, response.status_code, response.headers = own, 200, {}
        response.iter_content.return_value = [payload]
        with TemporaryDirectory() as root, \
                patch('core.content_routes.resolve_download_urls', side_effect=AssertionError('slow lookup before mirror')), \
                patch('core.downloads._DownloadSession.get', return_value=response) as get:
            downloader = MinecraftDownloader(root, source='Buggcraft', retries=0)
            downloader.content_source = 'Buggcraft'
            downloader.resolve_content_sources = True
            downloader.fetch(original, 'mods/example.jar', hashlib.sha1(payload).hexdigest(), len(payload))
            self.assertEqual((Path(root) / 'mods/example.jar').read_bytes(), payload)
        self.assertEqual(get.call_args.args, (own,))

    def test_game_cache_miss_can_follow_mirror_redirect_policy(self):
        payload = b'verified game core'
        original = 'https://piston-data.mojang.com/v1/objects/' + hashlib.sha1(payload).hexdigest() + '/client.jar'
        own = bugg_mirror.mirror_url(original)
        visited = []

        def download(_session, url, **kwargs):
            visited.append(url)
            self.assertEqual(url, own)
            self.assertNotIn('X-Buggcraft-Origin-Only', kwargs['headers'])
            response = MagicMock()
            response.__enter__.return_value = response
            response.url = original
            response.status_code = 200
            response.headers = {}
            response.iter_content.return_value = [payload]
            return response

        with TemporaryDirectory() as root, patch('core.downloads._DownloadSession.get', download):
            downloader = MinecraftDownloader(root, source='Buggcraft', retries=0)
            downloader.fetch(original, 'client.jar', hashlib.sha1(payload).hexdigest(), len(payload))
            self.assertEqual((Path(root) / 'client.jar').read_bytes(), payload)
        self.assertEqual(visited, [own])

    def test_redirect_to_already_failed_source_stops_repeated_attempts(self):
        original = 'https://edge.forgecdn.net/files/123/456/test.jar'
        own = bugg_mirror.mirror_url(original)
        visited = []

        def download(_session, url, **_kwargs):
            visited.append(url)
            error = requests.Timeout('redirected target unavailable')
            error.request = requests.Request('GET', original).prepare()
            raise error

        with TemporaryDirectory() as root, patch('core.downloads._DownloadSession.get', download):
            downloader = MinecraftDownloader(root, source='BMCLAPI', retries=6)
            downloader.content_source = 'CurseForge'
            with self.assertRaises(DownloadSourcesExhausted) as failed:
                downloader.fetch(original, 'test.jar', '0' * 40, 100)
        self.assertEqual(visited, [original, own])
        self.assertIn('重定向', str(failed.exception))

    def test_selected_source_failure_defers_to_origin_policy(self):
        payload = b'verified mod'
        original = 'https://edge.forgecdn.net/files/123/456/test.jar'
        own = bugg_mirror.mirror_url(original)
        visited = []

        def download(_session, url, **kwargs):
            visited.append((url, kwargs['headers']))
            if url == original:
                raise requests.Timeout('selected source unavailable')
            self.assertEqual(url, own)
            response = MagicMock()
            response.__enter__.return_value = response
            response.url = url
            response.status_code = 200
            response.headers = {}
            response.iter_content.return_value = [payload]
            return response

        with TemporaryDirectory() as root, patch('core.downloads._DownloadSession.get', download):
            downloader = MinecraftDownloader(root, source='BMCLAPI', retries=6)
            downloader.content_source = 'CurseForge'
            downloader.fetch(original, 'test.jar', hashlib.sha1(payload).hexdigest(), len(payload))
            self.assertEqual((Path(root) / 'test.jar').read_bytes(), payload)
        self.assertEqual([url for url, _ in visited], [original, own])
        self.assertNotIn('X-Buggcraft-Origin-Only', visited[1][1])
        self.assertNotIn('X-Buggcraft-Origin-Only', visited[0][1])

    def test_enabled_mirror_is_sole_automatic_fallback(self):
        urls = ['https://piston-meta.mojang.com/mc/game/version_manifest_v2.json',
                'https://cdn.modrinth.com/data/test/versions/test/test.jar',
                'https://edge.forgecdn.net/files/123/456/test.jar']
        self.assertTrue(bugg_mirror.ENABLED)
        with TemporaryDirectory() as root:
            downloader = MinecraftDownloader(root)
            for url in urls:
                self.assertTrue(bugg_mirror.mirror_url(url).startswith(bugg_mirror.BASE_URL))
                self.assertTrue(any('mirror.bugg.icu' in item for item in downloader.urls(url)))
        self.assertEqual(source_urls('Buggcraft', urls[0]), [bugg_mirror.mirror_url(urls[0])])

    def test_enabled_routes_match_translation_service_paths(self):
        routes = {
            'https://cdn.modrinth.com/data/test/versions/ver/file.jar': '/mods/modrinth/data/test/versions/ver/file.jar',
            'https://cdn.modrinth.com/data/test/versions/ver/pack.mrpack': '/mods/modrinth/data/test/versions/ver/pack.mrpack',
            'https://cdn.modrinth.com/data/test/versions/ver/resources.zip': '/mods/modrinth/data/test/versions/ver/resources.zip',
            'https://mediafilez.forgecdn.net/files/123/456/file.jar': '/mods/curseforge-mediafilez/files/123/456/file.jar',
            'https://edge.forgecdn.net/files/123/456/resources.zip': '/mods/curseforge/files/123/456/resources.zip',
            'https://meta.fabricmc.net/v2/versions/loader/1.21.1': '/fabric-meta/v2/versions/loader/1.21.1',
            'https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml': '/neoforge-maven/releases/net/neoforged/neoforge/maven-metadata.xml',
            'https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml': '/maven/net/minecraftforge/forge/maven-metadata.xml',
            'https://resources.download.minecraft.net/ab/' + 'ab' + '0' * 38: '/assets/ab/' + 'ab' + '0' * 38,
        }
        with patch.object(bugg_mirror, 'ENABLED', True):
            for url, path in routes.items():
                self.assertEqual(bugg_mirror.mirror_url(url), bugg_mirror.BASE_URL + path)
            for url in ['https://unknown.invalid/file.jar', 'https://cdn.modrinth.com/data/../../x.jar',
                        'https://maven.fabricmc.net/net/fabricmc/fabric-api/x.jar',
                        'https://edge.forgecdn.net/files/1/2/x.jar?token=secret']:
                self.assertIsNone(bugg_mirror.mirror_url(url))
