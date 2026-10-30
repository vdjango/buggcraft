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
    def test_default_uses_mirror_and_preserves_publisher_fallback(self):
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
                        self.assertEqual(routes[-1], url)
                        self.assertEqual(_download_urls(url, source), routes)
                self.assertEqual(_source_urls(source, 'official', 'mirror'), ['mirror', 'official'])
                neoforge = 'https://maven.neoforged.net/releases/net/neoforged/neoforge/21.1.265/a.jar'
                self.assertEqual(_download_urls(neoforge, source), [
                    'https://bmclapi2.bangbang93.com/maven/net/neoforged/neoforge/21.1.265/a.jar',
                    MCMIRROR + '/maven.neoforged.net/releases/net/neoforged/neoforge/21.1.265/a.jar', neoforge])

    def test_explicit_official_policy_remains_respected(self):
        url = 'https://libraries.minecraft.net/a.jar'
        mirror = 'https://bmclapi2.bangbang93.com/maven/a.jar'
        with tempfile.TemporaryDirectory() as root:
            for source, expected in [('官方', [url, mirror, MCMIRROR + '/maven/a.jar']),
                                     ('自动（官方优先，失败切换镜像）', [url, mirror, MCMIRROR + '/maven/a.jar']),
                                     ('MCMirror', [MCMIRROR + '/maven/a.jar', mirror, url])]:
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
