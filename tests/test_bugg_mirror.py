"""The unfinished mirror stays dormant and only maps supported origin routes."""
import unittest
from unittest.mock import patch
from core import bugg_mirror
from core.game_sources import source_urls
from core.downloads import MinecraftDownloader
from tempfile import TemporaryDirectory


class BuggMirrorTests(unittest.TestCase):
    def test_disabled_mirror_never_enters_download_candidates(self):
        urls = ['https://piston-meta.mojang.com/mc/game/version_manifest_v2.json',
                'https://cdn.modrinth.com/data/test/versions/test/test.jar',
                'https://edge.forgecdn.net/files/123/456/test.jar']
        self.assertFalse(bugg_mirror.ENABLED)
        with TemporaryDirectory() as root:
            downloader = MinecraftDownloader(root)
            for url in urls:
                self.assertIsNone(bugg_mirror.mirror_url(url))
                self.assertTrue(all('mirror.bugg.icu' not in item for item in downloader.urls(url)))
        self.assertTrue(all('mirror.bugg.icu' not in item for item in source_urls('Buggcraft', urls[0])))

    def test_enabled_routes_match_translation_service_paths(self):
        routes = {
            'https://cdn.modrinth.com/data/test/versions/ver/file.jar': '/mods/modrinth/data/test/versions/ver/file.jar',
            'https://mediafilez.forgecdn.net/files/123/456/file.jar': '/mods/curseforge/files/123/456/file.jar',
            'https://meta.fabricmc.net/v2/versions/loader/1.21.1': '/fabric-meta/v2/versions/loader/1.21.1',
            'https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml': '/neoforge-maven/releases/net/neoforged/neoforge/maven-metadata.xml',
            'https://resources.download.minecraft.net/ab/' + 'ab' + '0' * 38: '/assets/ab/' + 'ab' + '0' * 38,
        }
        with patch.object(bugg_mirror, 'ENABLED', True):
            for url, path in routes.items():
                self.assertEqual(bugg_mirror.mirror_url(url), bugg_mirror.BASE_URL + path)
            for url in ['https://unknown.invalid/file.jar', 'https://cdn.modrinth.com/data/../../x.jar',
                        'https://maven.fabricmc.net/net/fabricmc/fabric-api/x.jar',
                        'https://edge.forgecdn.net/files/1/2/x.jar?token=secret']:
                self.assertIsNone(bugg_mirror.mirror_url(url))
