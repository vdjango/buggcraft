"""Publisher settings migrate retired MCIM without contacting its services."""
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import MagicMock, patch
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'buggcraft'))
from core.content_mirrors import AUTO_SOURCES, configured_source, configured_order, source_order, display_source, get_modrinth
from core.curseforge import CurseForgeAPI, PUBLIC_API


class ContentMirrorSourceTests(unittest.TestCase):
    def test_custom_order_survives_restart_and_keeps_mcim_opt_in(self):
        saved = {'settings.general.content_mirror': '优先级',
                 'settings.general.content_order': ['Buggcraft', 'Modrinth', 'CurseForge']}
        settings = MagicMock()
        settings.get_setting.side_effect = lambda key, default: saved.get(key, default)
        self.assertEqual(configured_source(settings), saved['settings.general.content_order'])
        self.assertEqual(display_source(configured_source(settings)), 'Buggcraft → Modrinth → CurseForge')
        saved['settings.general.content_mirror'] = '自动测速'
        self.assertEqual(configured_source(settings), '自动测速')
        self.assertEqual(configured_order(settings), ['Buggcraft', 'CurseForge', 'Modrinth'])
        self.assertNotIn('MCIM', configured_order(settings))
        self.assertEqual(source_order(['MCIM', 'Buggcraft', 'MCIM', 'invalid']),
                         ['MCIM', 'Buggcraft', 'CurseForge', 'Modrinth'])

    def test_automatic_is_the_default_without_probing_external_services(self):
        settings = MagicMock()
        settings.get_setting.side_effect = lambda _key, default: default
        self.assertEqual(configured_source(settings), AUTO_SOURCES[1])
        settings.get_setting.assert_called_once_with('settings.general.content_mirror', AUTO_SOURCES[0])

    def test_saved_manual_sources_survive(self):
        settings = MagicMock()
        for saved in ('自动测速', 'CurseForge', 'Modrinth', '官方', 'MCIM', 'Buggcraft', 'unknown'):
            settings.get_setting.return_value = saved
            expected = source_order(saved) if saved == 'MCIM' else saved if saved != 'unknown' else AUTO_SOURCES[1]
            self.assertEqual(configured_source(settings), expected)
        settings.get_setting.return_value = '自动（CurseForge 优先）'
        self.assertEqual(configured_source(settings), '自动测速')
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
                expected = 'https://mod.mcimirror.top/modrinth/v2' if source == 'MCIM' else 'https://api.modrinth.com/v2'
                self.assertEqual(get.call_args.args[0], expected + '/project/id')
                self.assertEqual(get.call_args.kwargs['params'], {'limit': 10})
                self.assertEqual(get.call_args.kwargs['headers']['User-Agent'], USER_AGENT)

    def test_failed_modrinth_does_not_retry_retired_mirror(self):
        with patch('core.content_mirrors.requests.get', side_effect=requests.Timeout('unavailable')) as get:
            with self.assertRaises(requests.Timeout):
                get_modrinth('/project', None, threading.Event(), '自动测速')
        self.assertEqual(get.call_count, 1)

    def test_explicit_mcim_uses_its_gateway_without_key_leak(self):
        response = MagicMock(status_code=200)
        response.__enter__.return_value = response
        response.json.return_value = {'data': []}
        with patch.dict(os.environ, BUGGCRAFT_CURSEFORGE_API_KEY=''), \
                patch('core.curseforge.requests.get', return_value=response) as get:
            self.assertEqual(CurseForgeAPI(mirror='MCIM').get('/mods/238222/files', {'gameVersion': '1.20.1'}), [])
        self.assertEqual(get.call_args.args[0], 'https://mod.mcimirror.top/curseforge/v1/mods/238222/files')
        self.assertNotIn('x-api-key', get.call_args.kwargs['headers'])


if __name__ == '__main__':
    unittest.main()
