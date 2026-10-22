"""Catalogue routing, authorization scope, compatibility and verified files."""
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/buggcraft'))
from core.content import ContentCatalogue, download_content
from core.curseforge import CurseForgeAPI, CurseForgeContentClient, content_file, PUBLIC_API, OFFICIAL_API
from core.downloads import DownloadCancelled, _DownloadSession


class CurseForgeTests(unittest.TestCase):
    def setUp(self):
        self.project = {'id': 10, 'gameId': 432, 'classId': 6, 'allowModDistribution': True}
        self.payload = b'published mod bytes'
        self.file = {'id': 20, 'modId': 10, 'gameId': 432, 'gameVersions': ['1.20.1', 'Fabric'],
                     'fileName': 'sample.jar', 'displayName': 'Sample for Fabric', 'isAvailable': True,
                     'downloadUrl': 'https://edge.forgecdn.net/files/0/20/sample.jar',
                     'fileLength': len(self.payload),
                     'hashes': [{'algo': 1, 'value': hashlib.sha1(self.payload).hexdigest()}]}

    def response(self, data):
        response = MagicMock()
        response.status_code = 200
        response.__enter__.return_value = response
        response.json.return_value = {'data': data}
        response.iter_content.return_value = [self.payload]
        return response

    def test_default_gateway_never_receives_a_key_and_own_key_goes_only_to_official_api(self):
        with patch.dict(os.environ, {'BUGGCRAFT_CURSEFORGE_API_KEY': ''}), \
                patch('core.curseforge.requests.get', return_value=self.response([])) as get:
            CurseForgeAPI().get('/mods/search', {'gameId': 432})
            self.assertEqual(get.call_args.args[0], PUBLIC_API + '/mods/search')
            self.assertNotIn('x-api-key', get.call_args.kwargs['headers'])
            self.assertFalse(get.call_args.kwargs['allow_redirects'])
        with patch('core.curseforge.requests.get', return_value=self.response([])) as get:
            CurseForgeAPI('personal-secret').get('/mods/search')
            self.assertEqual(get.call_args.args[0], OFFICIAL_API + '/mods/search')
            self.assertEqual(get.call_args.kwargs['headers']['x-api-key'], 'personal-secret')

    def test_auth_errors_and_cancellation_do_not_expose_credentials(self):
        response = self.response([])
        response.status_code = 403
        with patch('core.curseforge.requests.get', return_value=response):
            with self.assertRaises(ValueError) as caught:
                CurseForgeAPI('personal-secret').get('/mods/search')
        self.assertNotIn('personal-secret', str(caught.exception))
        cancel = threading.Event(); cancel.set()
        with patch('core.curseforge.requests.get') as get:
            with self.assertRaises(DownloadCancelled):
                CurseForgeAPI(cancel=cancel).get('/mods/search')
            get.assert_not_called()

    def test_search_uses_resource_class_and_filters_loader_only_for_mods(self):
        client = CurseForgeContentClient()
        with patch.object(client, 'get', return_value=[dict(self.project, name='Sample', summary='About')]) as get:
            hits = client.search('sample', 'mod', '1.20.1', 'fabric')
            self.assertEqual(hits[0]['project_id'], '10')
            self.assertEqual(get.call_args.args[1]['gameId'], 432)
            self.assertEqual(get.call_args.args[1]['modLoaderType'], 4)
        with patch.object(client, 'get', return_value=[]) as get:
            client.search('texture', 'resourcepack', '1.20.1', 'fabric')
            self.assertEqual(get.call_args.args[1]['classId'], 12)
            self.assertNotIn('modLoaderType', get.call_args.args[1])

    def test_versions_recheck_compatibility_before_verified_install_and_never_send_key_to_cdn(self):
        client = CurseForgeContentClient('personal-secret')
        with patch.object(client, 'get', side_effect=[self.project, [self.file,
                dict(self.file, gameVersions=['1.20.1', 'Forge']),
                dict(self.file, gameVersions=['1.19.4', 'Fabric'])]]):
            versions = client.versions('10', '1.20.1', 'fabric')
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0]['source'], 'CurseForge')
        with tempfile.TemporaryDirectory() as root, patch('requests.Session.request', return_value=self.response(None)) as get:
            installed = download_content(versions[0], root, 'mod')
            self.assertEqual(Path(installed[0]).read_bytes(), self.payload)
            self.assertEqual(Path(installed[0]).parent.name, 'mods')
            self.assertNotIn('x-api-key', get.call_args.kwargs['headers'])

    def test_cdn_authentication_and_401_fallback_keep_the_platform_key_private(self):
        url = self.file['downloadUrl']
        with patch('requests.Session.request', return_value=self.response(None)) as request:
            with _DownloadSession('personal-secret') as session:
                session.get(url)
                self.assertEqual(request.call_args.kwargs['headers']['x-api-key'], 'personal-secret')
                session.get('https://another.example/file')
                self.assertNotIn('x-api-key', request.call_args.kwargs['headers'])
        rejected, downloaded = self.response(None), self.response(None)
        rejected.status_code = 401
        fallback = PUBLIC_API + '/download/10/20'
        with patch('requests.Session.request', side_effect=[rejected, downloaded]) as request:
            with _DownloadSession('', {url: fallback}) as session:
                self.assertIs(session.get(url, stream=True), downloaded)
        rejected.close.assert_called_once()
        self.assertEqual(request.call_args.args[1], fallback)
        self.assertNotIn('x-api-key', request.call_args.kwargs['headers'])

    def test_author_restrictions_and_wrong_content_classes_are_not_bypassed(self):
        client = CurseForgeContentClient()
        for project in [dict(self.project, allowModDistribution=False), dict(self.project, classId=4471),
                        dict(self.project, gameId=1)]:
            with self.subTest(project=project), patch.object(client, 'get', return_value=project) as get:
                with self.assertRaises(ValueError):
                    client.versions('10', '1.20.1', 'fabric')
                self.assertEqual(get.call_count, 1)
        for change in [{'downloadUrl': None}, {'downloadUrl': 'https://forgecdn.net.evil.org/mod.jar'},
                       {'hashes': []}, {'isServerPack': True}, {'isAvailable': False}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                content_file(dict(self.file, **change))

    def test_auto_search_retains_source_identity_and_survives_one_provider_failure(self):
        catalogue = ContentCatalogue()
        with patch.object(catalogue.clients['Modrinth'], 'search', return_value=[{'project_id':'10','title':'Modrinth project'}]), \
                patch.object(catalogue.clients['CurseForge'], 'search', return_value=[{'project_id':'10','title':'CF project'}]):
            hits = catalogue.search('sample', 'mod')
        self.assertEqual([x['source'] for x in hits], ['Modrinth', 'CurseForge'])
        with patch.object(catalogue.clients['CurseForge'], 'versions', return_value=[{'files':[]}]) as versions:
            catalogue.versions(hits[1], '1.20.1', 'fabric')
            versions.assert_called_once_with('10', '1.20.1', 'fabric', 'mod')
        with patch.object(catalogue.clients['Modrinth'], 'search', side_effect=ValueError('offline')), \
                patch.object(catalogue.clients['CurseForge'], 'search', return_value=[{'project_id':'10'}]):
            self.assertEqual(len(catalogue.search('sample', 'mod')), 1)
            self.assertEqual(catalogue.warnings, ['Modrinth 暂不可用'])
        with patch.object(catalogue.clients['CurseForge'], 'search', side_effect=ValueError('offline')):
            with self.assertRaises(ValueError):
                catalogue.search('sample', 'mod', source='CurseForge')
