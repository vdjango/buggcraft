"""Publisher fallback order and hash-matched routing."""
import hashlib
import threading
import unittest
from unittest.mock import patch
import requests

from core.content_routes import provider, prefetch_modrinth_hashes, resolve_download_urls
from core.downloads import DownloadCancelled, MinecraftDownloader
from core.bugg_mirror import BASE_URL


class ContentRouteTests(unittest.TestCase):
    def setUp(self):
        self.cancel = threading.Event()
        self.sha1 = hashlib.sha1(b'file').hexdigest()
        self.modrinth = 'https://cdn.modrinth.com/data/abcdefgh/versions/ijklmnop/mod.jar'
        self.curseforge = 'https://edge.forgecdn.net/files/1234/567/mod.jar'
        from core import content_routes
        content_routes._CACHE.clear()
        content_routes._CURSEFORGE_CACHE.clear()
        content_routes._UNAVAILABLE_HOSTS.clear()

    def resolve(self, urls, preference):
        return resolve_download_urls(urls, self.sha1, 4, preference=preference, cancel=self.cancel)

    def test_selected_source_is_first_and_other_publisher_follows(self):
        for selected, expected in (('自动测速', [self.curseforge, self.modrinth]),
                                   ('CurseForge', [self.curseforge, self.modrinth]),
                                   ('Modrinth', [self.modrinth, self.curseforge])):
            with self.subTest(selected=selected):
                self.assertEqual(self.resolve([self.modrinth, self.curseforge], selected), expected)

    def test_every_custom_order_is_respected_including_origin_in_the_middle(self):
        from itertools import permutations
        urls = {'CurseForge': self.curseforge, 'Modrinth': self.modrinth,
                'Buggcraft': BASE_URL + '/mods/modrinth/data/file.jar'}
        for order in permutations(urls):
            with self.subTest(order=order):
                self.assertEqual(self.resolve(list(urls.values()), list(order)), [urls[name] for name in order])

    def test_buggcraft_is_last_unless_selected(self):
        self.assertEqual(self.resolve([self.curseforge, self.modrinth], 'Buggcraft'),
                         [self.curseforge, self.modrinth])
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

    def test_modrinth_alternative_requires_exact_hash_and_size(self):
        metadata = {'files': [{'size': 4, 'url': self.modrinth,
                               'hashes': {'sha1': self.sha1}}]}
        with patch('core.content_routes._get', return_value=metadata) as lookup:
            self.assertEqual(self.resolve([self.curseforge], 'CurseForge'), [self.curseforge, self.modrinth])
            lookup.assert_called_once()
        wrong = {'files': [{'size': 5, 'url': self.modrinth,
                            'hashes': {'sha1': self.sha1}}]}
        from core import content_routes
        content_routes._CACHE.clear()
        with patch('core.content_routes._get', return_value=wrong):
            self.assertEqual(self.resolve([self.curseforge], 'Modrinth'), [self.curseforge])

    def test_modrinth_search_errors_leave_the_selected_source_available(self):
        with patch('core.content_routes.requests.get', side_effect=requests.Timeout('offline')):
            self.assertEqual(self.resolve([self.curseforge], 'Modrinth'), [self.curseforge])

    def test_failed_batch_lookup_does_not_repeat_for_every_file(self):
        with patch('core.content_routes.requests.post', side_effect=requests.Timeout('offline')) as batch, \
                patch('core.content_routes._get', side_effect=AssertionError('one-file lookup repeated')):
            prefetch_modrinth_hashes([(self.sha1, 4)], self.cancel)
            self.assertEqual(self.resolve([self.curseforge], 'CurseForge'), [self.curseforge])
        batch.assert_called_once()

    def test_mediafilez_is_not_rewritten_to_mcim(self):
        download = MinecraftDownloader('.', source='BMCLAPI')
        download.content_source = 'MCIM'
        urls = download.urls('https://mediafilez.forgecdn.net/files/1234/567/mod.jar')
        self.assertEqual(urls, ['https://mediafilez.forgecdn.net/files/1234/567/mod.jar',
                                BASE_URL + '/mods/curseforge-mediafilez/files/1234/567/mod.jar'])

    def test_curseforge_uses_pack_hash_even_when_modrinth_metadata_fails(self):
        requested = []
        def lookup(url, cancel, params=None, headers=None):
            requested.append(url)
            if '/mods/search' in url:
                return {'data': [{'id': 123, 'gameId': 432}]}
            if '/mods/123/files' in url:
                return {'data': [{'id': 1234567, 'modId': 123, 'fileLength': 4,
                                  'downloadUrl': self.curseforge,
                                  'hashes': [{'algo': 1, 'value': self.sha1}]}]}
            return {}
        url = self.modrinth.replace('mod.jar', 'deeperdarker-forge-1.20.1.jar')
        with patch('core.content_routes._get', side_effect=lookup):
            self.assertEqual(self.resolve([url], 'CurseForge'), [self.curseforge, url])
        self.assertTrue(any('/mods/search' in url for url in requested))
        self.assertFalse(any('api.modrinth.com' in url for url in requested))

    def test_curseforge_search_checks_each_result_before_searching_more_terms(self):
        from core.content_routes import _curseforge
        calls = []
        def lookup(url, cancel, params=None, headers=None):
            calls.append((url, params))
            if '/mods/search' in url:
                return {'data': [{'id': 123, 'gameId': 432}]}
            self.assertEqual(params['gameVersion'], '1.20.1')
            return {'data': [{'id': 1234567, 'fileLength': 4, 'downloadUrl': self.curseforge,
                              'hashes': [{'algo': 1, 'value': self.sha1}]}]}
        file = {'filename': 'DailyShop-mc1.20.1-v1.0.10-fabric.jar',
                'hashes': {'sha1': self.sha1}, 'size': 4}
        with patch('core.content_routes._get', side_effect=lookup):
            self.assertEqual(_curseforge({}, file, self.cancel), self.curseforge)
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0][0].endswith('/mods/search'))
        self.assertEqual(calls[1][1]['modLoaderType'], 4)

    def test_curseforge_never_accepts_same_filename_with_different_hash(self):
        messages = []
        def lookup(url, cancel, params=None, headers=None):
            if '/mods/search' in url:
                return {'data': [{'id': 123, 'gameId': 432}]}
            if '/mods/123/files' in url:
                return {'data': [{'id': 1234567, 'fileLength': 4, 'downloadUrl': self.curseforge,
                                  'hashes': [{'algo': 1, 'value': '0' * 40}]}]}
            return {}
        url = self.modrinth.replace('mod.jar', 'deeperdarker.jar')
        with patch('core.content_routes._get', side_effect=lookup):
            self.assertEqual(resolve_download_urls([url], self.sha1, 4, preference='CurseForge',
                             cancel=self.cancel, report=messages.append), [url])
        self.assertIn('哈希', messages[0])

    def test_curseforge_exact_title_is_not_hidden_by_popular_search_results(self):
        from core.content_routes import _curseforge
        def lookup(url, cancel, params=None, headers=None):
            if 'api.modrinth.com/v2/project/' in url:
                return {'title': 'Additional Additions: Vanilla+ QoL', 'slug': 'addadd', 'project_type': 'mod'}
            if '/mods/search' in url:
                self.assertEqual(params['searchFilter'], 'Additional Additions')
                return {'data': [*({'id': i, 'gameId': 432, 'name': 'Unrelated Additions'} for i in range(1, 8)),
                                 {'id': 123, 'gameId': 432, 'name': 'Additional Additions', 'slug': 'additional-additions'}]}
            self.assertIn('/mods/123/files', url)
            self.assertEqual(params['gameVersion'], '1.20.1')
            return {'data': [{'id': 1234567, 'fileLength': 4, 'downloadUrl': self.curseforge,
                              'hashes': [{'algo': 1, 'value': self.sha1}]}]}
        file = {'filename': 'additionaladditions-6.0.1.jar', 'hashes': {'sha1': self.sha1}, 'size': 4}
        with patch('core.content_routes._get', side_effect=lookup):
            self.assertEqual(_curseforge({'project_id': 'abcdefgh', 'game_versions': ['1.20', '1.20.1']},
                                        file, self.cancel), self.curseforge)

    def test_cataclysm_search_singularizes_plurals_and_ignores_single_letter_initial(self):
        from core.content_routes import _curseforge_search_terms
        terms = _curseforge_search_terms('L_Enders_Cataclysm-3.31.jar')
        self.assertEqual(terms[:3], ['L Enders Cataclysm', 'Enders Cataclysm', 'Ender Cataclysm'])
        self.assertIn('Cataclysm', terms)
        self.assertIn('Ender', terms)
        self.assertNotIn('L', terms)
        self.assertNotIn('Catacly', terms)

    def test_cataclysm_search_reaches_singular_fallback_without_opening_unrelated_projects(self):
        from core.content_routes import _curseforge
        searches = []
        files = []
        def lookup(url, cancel, params=None, headers=None):
            if '/mods/search' in url:
                term = params['searchFilter']
                searches.append(term)
                if term != 'Ender Cataclysm':
                    return {'data': [dict(id=number, gameId=432, name='Unrelated Popular Mod')
                                     for number in range(1, 8)]}
                return {'data': [{'id': 123, 'gameId': 432, 'name': "L_Ender's Cataclysm"}]}
            files.append(url)
            return {'data': [{'id': 1234567, 'modId': 123, 'fileLength': 4,
                              'downloadUrl': self.curseforge,
                              'hashes': [{'algo': 1, 'value': self.sha1}]}]}
        artifact = {'filename': 'L_Enders_Cataclysm-3.31.jar',
                    'hashes': {'sha1': self.sha1}, 'size': 4}
        with patch('core.content_routes._get', side_effect=lookup):
            self.assertEqual(_curseforge({}, artifact, self.cancel), self.curseforge)
        self.assertIn('Ender Cataclysm', searches)
        self.assertTrue(files)
        self.assertTrue(all('/mods/123/files' in url for url in files))

    def test_cataclysm_search_does_not_accept_wrong_hash_from_matching_name(self):
        from core.content_routes import _curseforge
        def lookup(url, cancel, params=None, headers=None):
            if '/mods/search' in url:
                return {'data': [{'id': 123, 'gameId': 432, 'name': "L_Ender's Cataclysm"}]}
            return {'data': [{'id': 1234567, 'modId': 123, 'fileLength': 4,
                              'downloadUrl': self.curseforge,
                              'hashes': [{'algo': 1, 'value': '0' * 40}]}]}
        artifact = {'filename': 'L_Enders_Cataclysm-3.31.jar',
                    'hashes': {'sha1': self.sha1}, 'size': 4}
        with patch('core.content_routes._get', side_effect=lookup):
            self.assertEqual(_curseforge({}, artifact, self.cancel), '')

    def test_one_metadata_timeout_does_not_disable_other_curseforge_files(self):
        from core import content_routes
        from unittest.mock import MagicMock
        response = MagicMock(status_code=200)
        response.__enter__.return_value = response
        response.json.return_value = {'data': [{'id': 123}]}
        url = 'https://download.bugg.icu/api/curseforge/v1/mods/search'
        with patch('core.content_routes.requests.get', side_effect=[requests.Timeout('slow file'), response]) as get:
            self.assertEqual(content_routes._get(url, self.cancel), {})
            self.assertEqual(content_routes._get(url, self.cancel), {'data': [{'id': 123}]})
        self.assertEqual(get.call_count, 2)

    def test_unavailable_curseforge_lookup_reports_timeout_instead_of_missing_mod(self):
        from core import content_routes
        messages = []
        def timeout(*args):
            content_routes._lookup_error('查询超时')
            return ''
        with patch('core.content_routes._modrinth', return_value=({}, {})), \
                patch('core.content_routes._curseforge', side_effect=timeout):
            resolve_download_urls([self.modrinth], self.sha1, 4, preference='CurseForge',
                                  cancel=self.cancel, report=messages.append)
        self.assertIn('查询超时', messages[0])
        self.assertNotIn('未找到', messages[0])

    def test_cancel_stops_route_selection(self):
        self.cancel.set()
        with self.assertRaises(DownloadCancelled):
            self.resolve([self.curseforge], '自动测速')
