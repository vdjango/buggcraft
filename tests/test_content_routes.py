"""Switch publishers using exact hashes, never similar names or version labels."""
import hashlib
import threading
import unittest
from unittest.mock import patch

from core import content_routes as routes
from core.downloads import DownloadCancelled


class ContentRouteTests(unittest.TestCase):
    def setUp(self):
        routes._CACHE.clear()
        self.cancel = threading.Event()
        self.sha1 = hashlib.sha1(b'file').hexdigest()
        self.modrinth = 'https://cdn.modrinth.com/data/abcdefgh/versions/ijklmnop/mod.jar'
        self.curseforge = 'https://edge.forgecdn.net/files/1234/567/mod.jar'
        self.file = dict(url=self.modrinth, size=4, hashes={'sha1': self.sha1})

    def resolve(self, addresses, preference='自动测速', **kwargs):
        return routes.resolve_download_urls(addresses, self.sha1, 4,
            preference=preference, cancel=self.cancel, **kwargs)

    def metadata(self, url, cancel, params=None, headers=None):
        if '/version_file/' in url:
            return {'project_id': 'abcdefgh', 'game_versions': ['1.21.1'], 'files': [self.file]}
        if '/project/' in url:
            return {'slug': 'example-mod', 'title': 'Example Mod', 'project_type': 'mod'}
        if url.endswith('/mods/search'):
            self.assertEqual(params, {'gameId': 432, 'classId': 6,
                                     'searchFilter': 'example-mod', 'pageSize': 3,
                                     'sortField': 6, 'sortOrder': 'desc'})
            return {'data': [{'id': 123, 'gameId': 432}]}
        self.assertTrue(url.endswith('/mods/123/files'))
        self.assertEqual(params['gameVersion'], '1.21.1')
        return {'data': [dict(fileLength=4, hashes=[{'algo': 1, 'value': self.sha1}],
                              downloadUrl=self.curseforge)]}

    def test_modrinth_selection_replaces_curseforge_via_exact_hash(self):
        with patch.object(routes, '_get', side_effect=self.metadata) as get:
            self.assertEqual(self.resolve([self.curseforge], 'Modrinth'),
                             [self.curseforge, self.modrinth])
        self.assertEqual(get.call_count, 1)

    def test_curseforge_selection_resolves_same_modrinth_file_and_caches_lookup(self):
        with patch.object(routes, '_get', side_effect=self.metadata) as get:
            expected = [self.modrinth, self.curseforge]
            self.assertEqual(self.resolve([self.modrinth], 'CurseForge'), expected)
            self.assertEqual(self.resolve([self.modrinth], 'CurseForge'), expected)
        self.assertEqual(get.call_count, 4)

    def test_auto_collects_both_publishers_for_speed_measurement(self):
        with patch.object(routes, '_get', side_effect=self.metadata):
            self.assertEqual(self.resolve([self.modrinth]), [self.modrinth, self.curseforge])

    def test_wrong_hash_or_size_never_becomes_an_alternative(self):
        for overrides in ({'hashes': {'sha1': '0' * 40}}, {'size': 5},
                          {'url': 'https://cdn.modrinth.com.evil.test/mod.jar'}):
            with self.subTest(overrides=overrides):
                routes._CACHE.clear()
                self.file = {**self.file, **overrides}
                with patch.object(routes, '_get', side_effect=self.metadata):
                    self.assertEqual(self.resolve([self.curseforge], 'Modrinth'), [self.curseforge])

    def test_curseforge_names_are_insufficient_without_matching_hash(self):
        def metadata(*args, **kwargs):
            value = self.metadata(*args, **kwargs)
            if args[0].endswith('/files'):
                value['data'][0]['hashes'][0]['value'] = '0' * 40
            return value
        with patch.object(routes, '_get', side_effect=metadata):
            self.assertEqual(self.resolve([self.modrinth], 'CurseForge'), [self.modrinth])

    def test_manual_existing_source_and_mcim_need_no_cross_publisher_lookup(self):
        with patch.object(routes, '_get') as get:
            for selected, url in (('Modrinth', self.modrinth), ('CurseForge', self.curseforge),
                                  ('MCIM', self.modrinth), ('官方', self.curseforge)):
                self.assertEqual(self.resolve([url], selected), [url])
        get.assert_not_called()

    def test_unavailable_or_malformed_alternative_preserves_original(self):
        for response in ({}, {'files': None}, {'files': [None]}, {'files': [self.file], 'project_id': None}):
            with self.subTest(response=response):
                routes._CACHE.clear()
                with patch.object(routes, '_get', return_value=response):
                    self.assertEqual(self.resolve([self.modrinth], 'CurseForge'), [self.modrinth])

    def test_cancel_stops_discovery(self):
        self.cancel.set()
        with patch.object(routes, '_get') as get, self.assertRaises(DownloadCancelled):
            self.resolve([self.modrinth])
        get.assert_not_called()
