"""Loader metadata routing and failure contracts; no public network required."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'buggcraft'))
from core import loaders


class LoaderCatalogueRegressionTests(unittest.TestCase):
    @staticmethod
    def response(records):
        response = Mock()
        response.json.return_value = records
        response.content = records if isinstance(records, bytes) else b''
        return response

    def test_neoforge_mirror_uses_per_game_api_and_sorts_valid_builds(self):
        for game, prefix in [('1.21', '21.0.'), ('1.21.8', '21.8.'), ('26.1', '26.1.')]:
            with self.subTest(game=game):
                records = [dict(mcversion=game, version=prefix + version)
                           for version in ('2-beta', '10-beta', '10', '10')]
                records += [dict(mcversion='1.20.4', version=prefix + '999'), None,
                            dict(mcversion=game, version='not a version')]
                response = self.response(records)
                with patch.object(loaders.requests, 'get', return_value=response) as get:
                    values = loaders.available_versions('NeoForge', game, 'BMCLAPI')
                self.assertEqual(values, [prefix + '10', prefix + '10-beta', prefix + '2-beta'])
                self.assertEqual(get.call_args.args[0], loaders.BMCLAPI + '/neoforge/list/' + game)
                response.close.assert_called_once()

    def test_neoforge_automatic_falls_back_from_api_to_official_maven(self):
        metadata = b'<metadata><versioning><versions><version>21.8.2-beta</version>' \
                   b'<version>21.8.10</version><version>21.7.99</version></versions></versioning></metadata>'
        response = self.response(metadata)
        with patch.object(loaders.requests, 'get', side_effect=[requests.Timeout('mirror timeout'), response]) as get:
            self.assertEqual(loaders.available_versions('NeoForge', '1.21.8'), ['21.8.10', '21.8.2-beta'])
        self.assertIn('/neoforge/list/1.21.8', get.call_args_list[0].args[0])
        self.assertIn('maven.neoforged.net', get.call_args_list[1].args[0])
        response.close.assert_called_once()

    def test_neoforge_official_only_does_not_contact_mirror(self):
        response = self.response(b'<metadata><versioning><versions><version>21.0.99</version>'
                                 b'</versions></versioning></metadata>')
        with patch.object(loaders.requests, 'get', return_value=response) as get:
            self.assertEqual(loaders.available_versions('NeoForge', '1.21', '官方'), ['21.0.99'])
        self.assertEqual(get.call_count, 1)
        self.assertIn('maven.neoforged.net', get.call_args.args[0])

    def test_empty_or_wrong_game_mirror_does_not_prevent_official_fallback(self):
        metadata = b'<metadata><versioning><versions><version>1.21.8-58.0.10</version>' \
                   b'</versions></versioning></metadata>'
        for records in ([], [dict(mcversion='1.20.1', version='47.4.0')]):
            with self.subTest(records=records):
                with patch.object(loaders.requests, 'get', side_effect=[self.response(records), self.response(metadata)]) as get:
                    self.assertEqual(loaders.available_versions('Forge', '1.21.8'), ['58.0.10'])
                self.assertEqual(get.call_count, 2)

    def test_fabric_and_quilt_reject_malformed_records_and_sort_latest_first(self):
        for name in ('Fabric', 'Quilt'):
            with self.subTest(loader=name):
                malformed = self.response([{'loader': []}, {'loader': {'version': 'bad input'}}, None])
                valid = self.response([{'loader': {'version': version}}
                                       for version in ('0.9.0', '0.29.3-beta.2', '0.29.3', '0.29.3')])
                with patch.object(loaders.requests, 'get', side_effect=[malformed, valid]) as get:
                    self.assertEqual(loaders.available_versions(name, '1.21.8'),
                                     ['0.29.3', '0.29.3-beta.2', '0.9.0'])
                self.assertIn(loaders.BMCLAPI, get.call_args_list[0].args[0])
                self.assertNotIn(loaders.BMCLAPI, get.call_args_list[1].args[0])

    def test_legacy_fabric_build_metadata_remains_selectable(self):
        records = [{'loader': {'version': value}} for value in
                   ('0.4.1+build.9', '0.4.1+build.139', '0.4.1+build.10')]
        with patch.object(loaders.requests, 'get', return_value=self.response(records)):
            self.assertEqual(loaders.available_versions('Fabric', '1.14.4', 'BMCLAPI'),
                             ['0.4.1+build.139', '0.4.1+build.10', '0.4.1+build.9'])

    def test_quilt_mirror_404_switches_to_official_in_automatic_mode(self):
        missing = self.response(None)
        missing.raise_for_status.side_effect = requests.HTTPError('404 Client Error: missing quilt metadata')
        official = self.response([{'loader': {'version': '0.29.3'}}])
        with patch.object(loaders.requests, 'get', side_effect=[missing, official]) as get:
            self.assertEqual(loaders.available_versions('Quilt', '1.21.8'), ['0.29.3'])
        self.assertIn('meta.quiltmc.org', get.call_args.args[0])
        missing.close.assert_called_once()

    def test_all_sources_failure_retains_traceback_in_logs_and_clean_ui_message(self):
        raw = 'HTTPSConnectionPool(host=example.invalid): Max retries exceeded with url: /list (ReadTimeoutError)'
        for name in ('Forge', 'NeoForge', 'Fabric', 'Quilt'):
            with self.subTest(loader=name):
                with (patch.object(loaders.requests, 'get', side_effect=requests.Timeout(raw)),
                      self.assertLogs(loaders.logger, level='WARNING') as logs,
                      self.assertRaises(RuntimeError) as raised):
                    loaders.available_versions(name, '1.21.8')
                self.assertIn('重新加载', str(raised.exception))
                self.assertIn('切换下载源', str(raised.exception))
                self.assertNotIn('ConnectionPool', str(raised.exception))
                self.assertIsInstance(raised.exception.__cause__, requests.Timeout)
                self.assertIn(raw, '\n'.join(logs.output))

    def test_invalid_metadata_can_fall_back_and_closes_both_responses(self):
        broken = self.response(None)
        broken.json.side_effect = json.JSONDecodeError('Expecting value', '<html>', 0)
        good = self.response([{'loader': {'version': '0.18.0'}}])
        with patch.object(loaders.requests, 'get', side_effect=[broken, good]):
            self.assertEqual(loaders.available_versions('Fabric', '1.21.8'), ['0.18.0'])
        broken.close.assert_called_once()
        good.close.assert_called_once()

    def test_invalid_maven_is_closed_and_not_shown_in_error(self):
        response = self.response(b'<html>temporarily unavailable</html')
        with patch.object(loaders.requests, 'get', return_value=response):
            with self.assertRaisesRegex(RuntimeError, '重新加载') as raised:
                loaders.available_versions('NeoForge', '1.21.8', '官方')
        self.assertNotIn('<html>', str(raised.exception))
        self.assertEqual(response.close.call_count, 3)
