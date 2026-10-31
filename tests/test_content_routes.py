"""The selected publisher remains the only external download route."""
import hashlib
import threading
import unittest
from unittest.mock import patch

from core.content_routes import provider, resolve_download_urls
from core.downloads import DownloadCancelled, MinecraftDownloader
from core.bugg_mirror import BASE_URL


class ContentRouteTests(unittest.TestCase):
    def setUp(self):
        self.cancel = threading.Event()
        self.sha1 = hashlib.sha1(b'file').hexdigest()
        self.modrinth = 'https://cdn.modrinth.com/data/abcdefgh/versions/ijklmnop/mod.jar'
        self.curseforge = 'https://edge.forgecdn.net/files/1234/567/mod.jar'

    def resolve(self, urls, preference):
        return resolve_download_urls(urls, self.sha1, 4, preference=preference, cancel=self.cancel)

    def test_auto_and_curseforge_never_probe_or_download_modrinth(self):
        for selected in ('自动', '自动测速', '自动（CurseForge 优先）', 'CurseForge'):
            with self.subTest(selected=selected):
                self.assertEqual(self.resolve([self.modrinth, self.curseforge], selected), [self.curseforge])
                self.assertEqual(self.resolve([self.modrinth], selected), [])

    def test_explicit_modrinth_is_honored_and_source_is_only_fallback(self):
        self.assertEqual(self.resolve([self.curseforge, self.modrinth], 'Modrinth'), [self.modrinth])
        for selected, original in [('CurseForge', self.curseforge), ('Modrinth', self.modrinth),
                                   ('MCIM', self.curseforge), ('Buggcraft', self.modrinth)]:
            with self.subTest(selected=selected):
                download = MinecraftDownloader('.', source='BMCLAPI')
                download.content_source = selected
                urls = download.urls(original)
                self.assertTrue(urls[-1].startswith(BASE_URL + '/mods/'))
                self.assertLessEqual(len(urls), 2)
                if selected == 'MCIM':
                    self.assertEqual(provider(urls[0]), '')
                    self.assertTrue(urls[0].startswith('https://mod.mcimirror.top/'))
                elif selected == 'Buggcraft':
                    self.assertEqual(len(urls), 1)
                else:
                    self.assertEqual(urls[0], original)

    def test_modrinth_hash_lookup_only_when_explicitly_selected(self):
        metadata = {'files': [{'size': 4, 'url': self.modrinth,
                               'hashes': {'sha1': self.sha1}}]}
        with patch('core.content_routes._get', return_value=metadata) as lookup:
            self.assertEqual(self.resolve([self.curseforge], '自动测速'), [self.curseforge])
            self.assertEqual(self.resolve([self.curseforge], 'CurseForge'), [self.curseforge])
            lookup.assert_not_called()
            self.assertEqual(self.resolve([self.curseforge], 'Modrinth'), [self.modrinth])
            lookup.assert_called_once()

    def test_mediafilez_is_not_rewritten_to_mcim(self):
        download = MinecraftDownloader('.', source='BMCLAPI')
        download.content_source = 'MCIM'
        urls = download.urls('https://mediafilez.forgecdn.net/files/1234/567/mod.jar')
        self.assertEqual(urls, ['https://mediafilez.forgecdn.net/files/1234/567/mod.jar',
                                BASE_URL + '/mods/curseforge-mediafilez/files/1234/567/mod.jar'])

    def test_cancel_stops_route_selection(self):
        self.cancel.set()
        with self.assertRaises(DownloadCancelled):
            self.resolve([self.curseforge], '自动测速')
