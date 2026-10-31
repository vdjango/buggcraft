"""Game repair and installation must use the same source policy."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/buggcraft'))
from core.downloads import MinecraftDownloader
from core.loaders import _download_urls, _source_urls
from core.game_sources import MCMIRROR, publisher_url, mirror_url


class GameDownloadSourceTests(unittest.TestCase):
    def test_default_uses_selected_mirror_and_only_buggcraft_fallback(self):
        with tempfile.TemporaryDirectory() as root:
            for source in ('自动', '自动选择下载源（自动选择速度快的源）',
                           '自动（镜像优先，失败切换官方）'):
                downloader = MinecraftDownloader(root, source=source)
                for url in ('https://libraries.minecraft.net/com/google/gson/gson/2.10.1/gson-2.10.1.jar',
                            'https://resources.download.minecraft.net/aa/aabb',
                            'https://piston-data.mojang.com/v1/objects/abc/client.jar'):
                    with self.subTest(source=source, url=url):
                        routes = downloader.urls(url)
                        self.assertTrue(routes[0].startswith('https://bmclapi2.bangbang93.com/'))
                        self.assertTrue(all('mirror.minguncle.cn' not in item for item in routes))
                        self.assertNotIn(url, routes)
                        self.assertLessEqual(len(routes), 2)
                        self.assertEqual(_download_urls(url, source), routes)
                self.assertEqual(_source_urls(source, 'official', 'mirror'), ['mirror'])
                neoforge = 'https://maven.neoforged.net/releases/net/neoforged/neoforge/21.1.265/a.jar'
                self.assertEqual(_download_urls(neoforge, source)[0],
                    'https://bmclapi2.bangbang93.com/maven/net/neoforged/neoforge/21.1.265/a.jar')
                self.assertTrue(all('mirror.minguncle.cn' not in item for item in _download_urls(neoforge, source)))

    def test_explicit_official_policy_remains_respected(self):
        url = 'https://libraries.minecraft.net/a.jar'
        mirror = 'https://bmclapi2.bangbang93.com/maven/a.jar'
        with tempfile.TemporaryDirectory() as root:
            own = 'https://mirror.bugg.icu/maven/a.jar'
            for source, expected in [('官方', [url, own]),
                                     ('自动（官方优先，失败切换镜像）', [url, own]),
                                     ('MCMirror', [MCMIRROR + '/maven/a.jar', own])]:
                self.assertEqual(MinecraftDownloader(root, source=source).urls(url), expected)
                self.assertEqual(_download_urls(url, source), expected)

    def test_minguncle_rewritten_urls_are_reversible_when_source_changes(self):
        for url in ('https://piston-data.mojang.com/v1/objects/abc/client.jar',
                    'https://resources.download.minecraft.net/aa/aabb',
                    'https://maven.neoforged.net/releases/net/neoforged/a.jar',
                    'https://meta.fabricmc.net/v2/versions/loader/1.21.1'):
            with self.subTest(url=url):
                mirrored = mirror_url(url, MCMIRROR)
                self.assertEqual(publisher_url(mirrored), url)
                self.assertEqual(_download_urls(mirrored, '官方')[0], url)
        self.assertIsNone(mirror_url('https://mediafilez.forgecdn.net/files/a.jar', MCMIRROR))
        self.assertIsNone(mirror_url('https://maven.quiltmc.org/a.jar', MCMIRROR))

    def test_unsupported_route_does_not_escape_selected_source(self):
        url = 'https://unlisted.example.net/a.jar'
        for source in ('BMCLAPI', 'MCMirror', 'Buggcraft'):
            with self.subTest(source=source):
                self.assertEqual(MinecraftDownloader('.', source=source).urls(url), [])
