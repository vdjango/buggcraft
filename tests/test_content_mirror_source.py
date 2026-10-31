"""Publisher settings migrate retired MCIM without contacting its services."""
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import MagicMock, patch
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'buggcraft'))
from core.content_mirrors import configured_source, display_source, get_modrinth
from core.curseforge import CurseForgeAPI, PUBLIC_API


class ContentMirrorSourceTests(unittest.TestCase):
    def test_saved_sources_survive_and_retired_source_migrates_to_curseforge(self):
        settings = MagicMock()
        for saved in ('自动测速', 'CurseForge', 'Modrinth', '官方', 'MCIM', 'unknown'):
            settings.get_setting.return_value = saved
            self.assertEqual(configured_source(settings), '自动（CurseForge 优先）' if saved == '自动测速'
                             else saved if saved not in ('MCIM', 'unknown') else 'CurseForge')
        self.assertEqual(display_source('官方', 'CurseForge'), 'CurseForge')
        self.assertEqual(display_source('官方', 'Modrinth'), 'Modrinth')

    def test_modrinth_metadata_always_uses_publisher_with_original_parameters(self):
        from utils.http_identity import USER_AGENT
        response = MagicMock(status_code=200)
        response.__enter__.return_value = response
        response.json.return_value = {'id': 'actual-project'}
        for source in ('CurseForge', '自动测速', 'Modrinth', 'MCIM'):
            with self.subTest(source=source), patch('core.content_mirrors.requests.get', return_value=response) as get:
                self.assertEqual(get_modrinth('/project/id', {'limit': 10}, threading.Event(), source), {'id': 'actual-project'})
                self.assertEqual(get.call_args.args[0], 'https://api.modrinth.com/v2/project/id')
                self.assertEqual(get.call_args.kwargs['params'], {'limit': 10})
                self.assertEqual(get.call_args.kwargs['headers']['User-Agent'], USER_AGENT)

    def test_failed_modrinth_does_not_retry_retired_mirror(self):
        with patch('core.content_mirrors.requests.get', side_effect=requests.Timeout('unavailable')) as get:
            with self.assertRaises(requests.Timeout):
                get_modrinth('/project', None, threading.Event(), '自动测速')
        self.assertEqual(get.call_count, 1)

    def test_curseforge_legacy_preference_still_uses_gateway_without_key_leak(self):
        response = MagicMock(status_code=200)
        response.__enter__.return_value = response
        response.json.return_value = {'data': []}
        with patch.dict(os.environ, BUGGCRAFT_CURSEFORGE_API_KEY=''), \
                patch('core.curseforge.requests.get', return_value=response) as get:
            self.assertEqual(CurseForgeAPI(mirror='MCIM').get('/mods/238222/files', {'gameVersion': '1.20.1'}), [])
        self.assertEqual(get.call_args.args[0], PUBLIC_API + '/mods/238222/files')
        self.assertNotIn('x-api-key', get.call_args.kwargs['headers'])


if __name__ == '__main__':
    unittest.main()
