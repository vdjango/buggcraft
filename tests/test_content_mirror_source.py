"""Source ordering and metadata fallback for modpack downloads."""
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import MagicMock, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'buggcraft'))

from core.content_mirrors import configured_source, display_source, get_modrinth
from core.curseforge import CurseForgeAPI


class ContentMirrorSourceTests(unittest.TestCase):
    def test_official_curseforge_source_is_named_in_english(self):
        self.assertEqual(display_source('官方', 'CurseForge'), 'CurseForge')
        self.assertEqual(display_source('官方', 'Modrinth'), 'Modrinth')
        self.assertEqual(display_source('MCIM', 'CurseForge'), 'MCIM')

    def test_saved_preferences_keep_original_source_selection(self):
        for saved in ('自动测速', 'CurseForge', 'Modrinth', 'MCIM', '官方'):
            settings = MagicMock()
            settings.get_setting.return_value = saved
            self.assertEqual(configured_source(settings), saved)
        settings.get_setting.return_value = '官方优先（MCIM 最后兜底）'
        self.assertEqual(configured_source(settings), '自动测速')

    def test_modrinth_auto_tries_publisher_after_mirror_timeout(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {'checked_at': datetime.now(timezone.utc).isoformat()}
        response.__enter__.return_value = response
        urls = []

        def get(url, **kwargs):
            urls.append(url)
            if len(urls) == 1:
                raise requests.Timeout('upstream timeout')
            return response

        with patch('core.content_mirrors.requests.get', side_effect=get):
            self.assertEqual(get_modrinth('/project', None, threading.Event(),
                                          '自动测速'), response.json.return_value)
        self.assertEqual(urls, ['https://mod.mcimirror.top/modrinth/v2/project',
                                'https://api.modrinth.com/v2/project'])

    def test_modrinth_auto_preserves_failure_when_both_routes_fail(self):
        with patch('core.content_mirrors.requests.get', side_effect=requests.Timeout('both routes')) as get:
            with self.assertRaises(requests.Timeout):
                get_modrinth('/project', None, threading.Event(), '自动测速')
        self.assertEqual(get.call_count, 2)

    def test_curseforge_mcim_falls_back_to_gateway(self):
        with patch.dict(os.environ, {'BUGGCRAFT_CURSEFORGE_API_KEY': ''}):
            client = CurseForgeAPI(mirror='MCIM')
        with patch.object(client, '_request', side_effect=[requests.Timeout('gateway timeout'),
                                                           {'data': []}]) as request:
            self.assertEqual(client.get('/mods/search'), {'data': []})
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args.kwargs, {})

    def test_both_metadata_mappings_preserve_paths_parameters_and_user_agent(self):
        from utils.http_identity import USER_AGENT
        response = MagicMock()
        response.__enter__.return_value = response
        response.status_code = 200
        response.json.return_value = {'data': [], 'checked_at': datetime.now(timezone.utc).isoformat()}
        cancel = threading.Event()
        params = {'gameVersion': '1.21.1'}
        with patch('core.content_mirrors.requests.get', return_value=response) as get:
            get_modrinth('/project/sodium/version', params, cancel, 'MCIM')
        self.assertEqual(get.call_args.args[0], 'https://mod.mcimirror.top/modrinth/v2/project/sodium/version')
        self.assertEqual(get.call_args.kwargs['params'], params)
        self.assertEqual(get.call_args.kwargs['headers']['User-Agent'], USER_AGENT)
        with patch.dict(os.environ, {'BUGGCRAFT_CURSEFORGE_API_KEY': ''}), \
                patch('core.curseforge.requests.get', return_value=response) as get:
            self.assertEqual(CurseForgeAPI(mirror='MCIM').get('/mods/238222/files', params), [])
        self.assertEqual(get.call_args.args[0], 'https://mod.mcimirror.top/curseforge/v1/mods/238222/files')
        self.assertEqual(get.call_args.kwargs['params'], params)
        self.assertEqual(get.call_args.kwargs['headers']['User-Agent'], USER_AGENT)
        self.assertNotIn('x-api-key', get.call_args.kwargs['headers'])

    def test_stale_or_unknown_mcim_cache_is_checked_against_publishers(self):
        for dates in ({}, {'sync_at': '2020-01-01T00:00:00Z'},
                      {'checked_at': '2020-01-01T00:00:00Z'}):
            with self.subTest(dates=dates):
                mirror, publisher = MagicMock(), MagicMock()
                for response in (mirror, publisher):
                    response.__enter__.return_value = response
                    response.status_code = 200
                mirror.json.return_value = {'data': [], **dates}
                publisher.json.return_value = {'data': [{'id': 123}]}
                with patch('core.content_mirrors.requests.get', side_effect=[mirror, publisher]) as get:
                    self.assertEqual(get_modrinth('/version/example', {}, threading.Event(), 'MCIM'),
                                     publisher.json.return_value)
                self.assertEqual(get.call_count, 2)
                with patch.dict(os.environ, {'BUGGCRAFT_CURSEFORGE_API_KEY': ''}), \
                        patch('core.curseforge.requests.get', side_effect=[mirror, publisher]) as get:
                    self.assertEqual(CurseForgeAPI(mirror='MCIM').get('/mods/238222/files'), [{'id': 123}])
                self.assertEqual(get.call_count, 2)
                self.assertTrue(get.call_args.args[0].startswith('https://download.bugg.icu/'))

    def test_curseforge_official_uses_gateway_without_mcim_fallback(self):
        with patch.dict(os.environ, {'BUGGCRAFT_CURSEFORGE_API_KEY': ''}):
            client = CurseForgeAPI(mirror='官方')
        with patch.object(client, '_request', side_effect=requests.Timeout('gateway timeout')) as request:
            with self.assertRaises(requests.Timeout):
                client.request('GET', '/mods/search')
        request.assert_called_once_with('GET', '/mods/search', None, None)


if __name__ == '__main__':
    unittest.main()
