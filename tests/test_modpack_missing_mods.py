"""Real HTTP missing files, transactional import and explicit skip decisions."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/buggcraft'))
from core.downloads import DownloadCancelled, DownloadSourcesExhausted, MinecraftDownloader
from core.modpack_missing import unavailable_mod, recoverable_mod_download
from core.modpacks import CurseForgeClient, ModpackImporter, export_pack
from client_ui_fixtures import ClientUiFixtures


class MissingModImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.game = self.root / 'game'
        self.fixtures = ClientUiFixtures(self.root)
        self.addCleanup(self.fixtures.close)
        origin = patch('core.client_file_source._origin', '')
        origin.start()
        self.addCleanup(origin.stop)
        self.original_urls = MinecraftDownloader.urls
        def urls(downloader, url):
            if url.startswith(('https://cdn.modrinth.com/', ClientUiFixtures.ORIGIN)):
                return [f'http://127.0.0.1:{self.fixtures.server.server_port}/' + url.rsplit('/', 1)[-1]]
            return self.fixtures.route(downloader, url)
        route = patch.object(MinecraftDownloader, 'urls', urls)
        route.start()
        self.addCleanup(route.stop)

    def pack(self, paths=('mods/missing.jar', 'mods/available.jar'), source='Buggcraft'):
        files = []
        for path in paths:
            payload = (path + ' verified bytes').encode()
            self.fixtures.payloads[Path(path).name] = payload
            hashes = {name: hashlib.new(name, payload).hexdigest() for name in ('sha1', 'sha256', 'sha512')}
            files.append(dict(path=path, fileSize=len(payload), hashes=hashes,
                downloads=['https://cdn.modrinth.com/data/fixture/' + Path(path).name]))
        self.fixtures.failures.add('missing.jar')
        archive = self.root / ('pack.buggpack' if source == 'Buggcraft' else 'pack.mrpack')
        with zipfile.ZipFile(archive, 'w') as output:
            if source == 'Buggcraft':
                output.writestr('buggcraft.pack.json', json.dumps(dict(format='buggcraft', formatVersion=1,
                    name='Missing mod pack', minecraft='1.21.8', files=[dict(path=item['path'],
                    size=item['fileSize'], embedded=False, sha1=item['hashes']['sha1'],
                    sha256=item['hashes']['sha256'], downloads=item['downloads']) for item in files])))
            else:
                output.writestr('modrinth.index.json', json.dumps(dict(formatVersion=1, game='minecraft',
                    name='Missing mod pack', dependencies={'minecraft': '1.21.8'}, files=files)))
        return archive

    def test_skip_requires_explicit_consent_and_saves_missing_list(self):
        for source in ('Buggcraft', 'Modrinth'):
            with self.subTest(source=source):
                archive = self.pack(source=source)
                decisions, events = [], []
                def approve(mods):
                    decisions.append(mods)
                    self.assertFalse((self.game / 'versions' / source).exists())
                    return True
                importer = ModpackImporter(self.game, content_source='官方', unavailable_mods=approve,
                                           file_event=events.append)
                importer.install(archive, source)
                self.assertEqual(len(decisions), 1)
                self.assertEqual([item['path'] for item in decisions[0]], ['mods/missing.jar'])
                target = self.game / 'versions' / source
                self.assertFalse((target / 'mods/missing.jar').exists())
                self.assertEqual((target / 'mods/available.jar').read_bytes(), self.fixtures.payloads['available.jar'])
                receipt = json.loads((target / 'buggcraft-modpack.json').read_text(encoding='utf-8'))
                self.assertEqual(receipt['skippedMods'], importer.skipped_mods)
                self.assertEqual([item['path'] for item in receipt['resources']], ['mods/available.jar'])
                self.assertTrue(any(item['state'] == 'skipped' and item['path'] == 'mods/missing.jar' for item in events))
                self.assertTrue((target / (source + '.jar')).is_file())

    def test_multiple_missing_mods_are_confirmed_together(self):
        archive = self.pack(paths=('mods/missing.jar', 'mods/second.jar', 'mods/available.jar'))
        self.fixtures.failures.add('second.jar')
        decisions = []
        importer = ModpackImporter(self.game, content_source='官方',
            unavailable_mods=lambda mods: decisions.append(mods) or True)
        importer.install(archive, 'Multiple')
        self.assertEqual(len(decisions), 1)
        self.assertEqual([item['path'] for item in decisions[0]], ['mods/missing.jar', 'mods/second.jar'])
        self.assertEqual(len(importer.skipped_mods), 2)

    def test_headless_import_never_silently_skips_mods(self):
        with self.assertRaisesRegex(RuntimeError, 'missing.jar'):
            ModpackImporter(self.game, content_source='官方').install(self.pack(), 'Strict')
        self.assertFalse((self.game / 'versions/Strict').exists())

    def test_public_origin_repairs_missing_mod_without_redownloading_successes(self):
        archive = self.pack()
        def lookup(missing, cancel):
            self.assertEqual([item['path'] for item in missing], ['mods/missing.jar'])
            self.fixtures.failures.clear()
            return {'mods/missing.jar': ClientUiFixtures.ORIGIN + '/missing.jar'}
        with patch('core.client_file_source.lookup', side_effect=lookup):
            ModpackImporter(self.game, content_source='官方').install(archive, 'Origin-Repaired')
        target = self.game / 'versions/Origin-Repaired'
        self.assertEqual((target / 'mods/missing.jar').read_bytes(), self.fixtures.payloads['missing.jar'])
        self.assertEqual(sum(row['file'] == 'available.jar' for row in self.fixtures.requests), 1)

    def test_curseforge_missing_mod_can_finish_after_explicit_choice(self):
        archive = self.root / 'missing-curseforge.zip'
        with zipfile.ZipFile(archive, 'w') as output:
            output.writestr('manifest.json', json.dumps(dict(manifestType='minecraftModpack',
                manifestVersion=1, name='Private CF mod', minecraft={'version': '1.21.8', 'modLoaders': []},
                files=[dict(projectID=10, fileID=20, required=True)])))
            output.writestr('overrides/config/private.txt', 'settings remain installed')
        decisions = []
        with patch.object(CurseForgeClient, 'post', side_effect=lambda route, _body:
                [dict(id=10, classId=6, name='Private mod')] if route == '/mods' else []):
            ModpackImporter(self.game, content_source='官方',
                unavailable_mods=lambda mods: decisions.append(mods) or True).install(archive, 'Private-CF')
        self.assertEqual(decisions[0][0]['fileId'], 20)
        target = self.game / 'versions/Private-CF'
        self.assertTrue((target / 'config/private.txt').is_file())
        receipt = json.loads((target / 'buggcraft-modpack.json').read_text(encoding='utf-8'))
        self.assertEqual(receipt['skippedMods'][0]['name'], 'Private mod')

    def test_stop_then_retry_reuses_downloads_and_reasks(self):
        archive = self.pack()
        decisions = []
        def stop(mods):
            decisions.append(mods)
            return False
        with self.assertRaises(DownloadCancelled):
            ModpackImporter(self.game, content_source='官方', unavailable_mods=stop).install(archive, 'Retry')
        self.assertFalse((self.game / 'versions/Retry').exists())
        before = len([row for row in self.fixtures.requests if row['file'] == 'available.jar'])
        importer = ModpackImporter(self.game, content_source='官方', unavailable_mods=lambda mods: decisions.append(mods) or True)
        importer.install(archive, 'Retry')
        self.assertEqual(len(decisions), 2)
        self.assertEqual(before, len([row for row in self.fixtures.requests if row['file'] == 'available.jar']))

    def test_missing_resource_pack_cannot_be_skipped_as_a_mod(self):
        decisions = []
        archive = self.pack(paths=('resourcepacks/missing.jar',))
        with self.assertRaises(RuntimeError):
            ModpackImporter(self.game, content_source='官方', unavailable_mods=lambda mods: decisions.append(mods) or True).install(archive, 'Resources')
        self.assertEqual(decisions, [])
        self.assertFalse((self.game / 'versions/Resources').exists())

    def test_server_error_is_collected_without_losing_other_mods(self):
        archive = self.pack()
        self.fixtures.failure_statuses = {'missing.jar': 503}
        decisions = []
        importer = ModpackImporter(self.game, content_source='官方',
            unavailable_mods=lambda mods: decisions.append(mods) or True)
        importer.install(archive, 'Network-Failure')
        self.assertIn('503', decisions[0][0]['reason'])
        target = self.game / 'versions/Network-Failure'
        self.assertEqual((target / 'mods/available.jar').read_bytes(), self.fixtures.payloads['available.jar'])
        report = (target / '缺失模组清单.txt').read_text(encoding='utf-8')
        self.assertIn('missing.jar', report)
        self.assertIn(decisions[0][0]['hashes']['sha256'], report)
        self.assertIn('https://cdn.modrinth.com/data/fixture/missing.jar', report)

    def test_retry_failed_mod_only_then_finishes_without_skip(self):
        archive = self.pack()
        decisions = []
        before = []
        def retry(mods):
            decisions.append(mods)
            before.append(sum(row['file'] == 'available.jar' for row in self.fixtures.requests))
            self.fixtures.failures.clear()
            return 'retry'
        importer = ModpackImporter(self.game, content_source='官方', unavailable_mods=retry)
        importer.install(archive, 'Retry-In-Place')
        target = self.game / 'versions/Retry-In-Place'
        self.assertEqual((target / 'mods/missing.jar').read_bytes(), self.fixtures.payloads['missing.jar'])
        self.assertEqual(before[0], sum(row['file'] == 'available.jar' for row in self.fixtures.requests))
        self.assertEqual(importer.skipped_mods, [])
        self.assertFalse((target / '缺失模组清单.txt').exists())

    def test_manual_file_must_match_all_manifest_hashes_before_install(self):
        archive = self.pack()
        wrong = self.root / 'wrong.jar'
        correct = self.root / 'correct.jar'
        payload = self.fixtures.payloads['missing.jar']
        wrong.write_bytes(b'X' * len(payload))
        correct.write_bytes(payload)
        decisions = []
        def supply(mods):
            decisions.append(mods)
            return dict(action='manual', path='mods/missing.jar',
                        file=str(wrong if len(decisions) == 1 else correct))
        importer = ModpackImporter(self.game, content_source='官方', unavailable_mods=supply)
        importer.install(archive, 'Manual-Repair')
        self.assertEqual(len(decisions), 2)
        self.assertIn('校验不匹配', decisions[1][0]['reason'])
        self.assertEqual(decisions[0][0]['hashes']['sha256'], hashlib.sha256(payload).hexdigest())
        self.assertEqual((self.game / 'versions/Manual-Repair/mods/missing.jar').read_bytes(), payload)
        self.assertEqual(importer.skipped_mods, [])
        self.assertEqual(correct.read_bytes(), payload, 'manual repair must not move the user download')
        self.assertFalse(list(self.game.rglob('.manual-mod-*')))

    def test_curseforge_metadata_retry_downloads_exact_file_and_updates_receipt(self):
        archive = self.root / 'metadata-retry.zip'
        payload = b'actual recovered CF publication'
        self.fixtures.payloads['recovered.jar'] = payload
        with zipfile.ZipFile(archive, 'w') as output:
            output.writestr('manifest.json', json.dumps(dict(manifestType='minecraftModpack',
                manifestVersion=1, minecraft={'version': '1.21.8', 'modLoaders': []},
                files=[dict(projectID=10, fileID=20, required=True)])))
        available = [False]
        def metadata(route, _body):
            if route == '/mods':
                return [dict(id=10, classId=6, name='Recovered mod', allowModDistribution=False)]
            return [dict(id=20, modId=10, fileName='recovered.jar', fileLength=len(payload),
                         downloadUrl=ClientUiFixtures.ORIGIN + '/recovered.jar',
                         hashes=[dict(algo=1, value=hashlib.sha1(payload).hexdigest())])] if available[0] else []
        def retry(_mods):
            available[0] = True
            return 'retry'
        with patch.object(CurseForgeClient, 'post', side_effect=metadata), \
                patch('core.modpacks.download_url', return_value=ClientUiFixtures.ORIGIN + '/recovered.jar'):
            importer = ModpackImporter(self.game, content_source='官方', unavailable_mods=retry)
            importer.install(archive, 'Metadata-Retry')
        target = self.game / 'versions/Metadata-Retry'
        self.assertEqual((target / 'mods/recovered.jar').read_bytes(), payload)
        receipt = json.loads((target / 'buggcraft-modpack.json').read_text(encoding='utf-8'))
        self.assertEqual(receipt['resources'][0]['path'], 'mods/recovered.jar')

    def test_corrupt_mod_does_not_offer_skip(self):
        decisions = []
        archive = self.pack(paths=('mods/available.jar',))
        self.fixtures.payloads['available.jar'] = b'corrupt bytes'
        with self.assertRaises(RuntimeError):
            ModpackImporter(self.game, content_source='官方', unavailable_mods=lambda mods: decisions.append(mods) or True).install(archive, 'Corrupt')
        self.assertEqual(decisions, [])

    def test_unpublished_local_mod_is_embedded_and_imports_without_prompt(self):
        instance = self.root / 'source/versions/Private'
        (instance / 'mods').mkdir(parents=True)
        (instance / 'Private.json').write_text(json.dumps(dict(id='Private', clientVersion='1.21.8')))
        (instance / 'mods/private.jar').write_bytes(b'local unpublished build')
        archive = self.root / 'private.buggpack'
        with patch('core.modpack_sources.find_public_mod_downloads', return_value={}):
            export_pack(instance.parents[1], 'Private', archive)
        with zipfile.ZipFile(archive) as pack:
            self.assertEqual(pack.read('files/mods/private.jar'), b'local unpublished build')
        decisions = []
        ModpackImporter(self.game, unavailable_mods=lambda mods: decisions.append(mods) or True).install(archive, 'Private')
        self.assertEqual((self.game / 'versions/Private/mods/private.jar').read_bytes(), b'local unpublished build')
        self.assertEqual(decisions, [])


class MissingModPolicyTests(unittest.TestCase):
    def test_remote_failures_allow_explicit_repair_but_local_and_integrity_errors_do_not(self):
        for error, expected in [(requests.Timeout('slow'), True), (requests.ConnectionError('reset'), True),
                                (requests.HTTPError(response=type('R', (), {'status_code': 403})()), True),
                                (ValueError('SHA1 mismatch'), False), (PermissionError('denied'), False)]:
            with self.subTest(error=error):
                self.assertEqual(recoverable_mod_download('mods/test.jar', error), expected)
                self.assertFalse(recoverable_mod_download('libraries/test.jar', error))
                self.assertFalse(recoverable_mod_download('resourcepacks/test.jar', error))
        self.assertFalse(recoverable_mod_download('mods/test.jar', DownloadSourcesExhausted(
            'failed', source_errors=[requests.Timeout('slow'), ValueError('SHA1 mismatch')])))
        self.assertFalse(recoverable_mod_download('mods/test.jar', DownloadSourcesExhausted('failed')))
    def test_all_sources_must_confirm_missing_before_a_mod_can_be_skipped(self):
        missing = requests.HTTPError(response=type('Response', (), {'status_code': 404})())
        gone = requests.HTTPError(response=type('Response', (), {'status_code': 410})())
        for errors, expected in [((missing, gone), True),
                                 ((missing, requests.Timeout('read timed out')), False),
                                 ((missing, ValueError('hash mismatch')), False), ((), False)]:
            with self.subTest(errors=errors):
                error = DownloadSourcesExhausted('全部下载源失败', source_errors=errors)
                self.assertEqual(unavailable_mod('mods/private.jar', error), expected)

    def test_only_missing_jar_in_mods_qualifies(self):
        for path, error, expected in [
            ('mods/private.jar', RuntimeError('404 Client Error for url: https://example.invalid/file'), True),
            ('mods/private.jar', RuntimeError('410 Client Error: Gone'), True),
            ('mods/private.jar', requests.Timeout('read timeout'), False),
            ('mods/private.jar', PermissionError('access denied'), False),
            ('mods/private.jar', ValueError('SHA1 verification failed'), False),
            ('resourcepacks/private.jar', RuntimeError('404 Client Error'), False),
            ('libraries/private.jar', RuntimeError('404 Client Error'), False),
            ('mods/config.json', RuntimeError('404 Client Error'), False),
        ]:
            with self.subTest(path=path, error=error):
                self.assertEqual(unavailable_mod(path, error), expected)

    def test_curseforge_unpublished_or_missing_mod_metadata_is_collected(self):
        client = CurseForgeClient()
        missing = []
        project = dict(id=10, classId=6, name='Private mod')
        with patch.object(client, 'post', side_effect=lambda route, _body: [project] if route == '/mods' else []):
            self.assertEqual(client.resolve([(10, 20)], unavailable=missing), [])
        self.assertEqual(missing[0]['name'], 'Private mod')
        self.assertEqual(missing[0]['fileId'], 20)
        early = dict(id=20, modId=10, fileName='private.jar', isEarlyAccessContent=True)
        with patch.object(client, 'post', side_effect=lambda route, _body: [project] if route == '/mods' else [early]):
            self.assertEqual(client.resolve([(10, 20)], unavailable=[]), [])
        with patch.object(client, 'post', side_effect=lambda route, _body: [project] if route == '/mods' else []):
            with self.assertRaises(ValueError):
                client.resolve([(10, 20)])

    def test_curseforge_mismatched_project_never_becomes_skippable(self):
        client, missing = CurseForgeClient(), []
        with patch.object(client, 'post', side_effect=lambda route, _body:
            [dict(id=10, classId=6)] if route == '/mods' else [dict(id=20, modId=99)]):
            with self.assertRaises(ValueError):
                client.resolve([(10, 20)], unavailable=missing)
        self.assertEqual(missing, [])

    def test_decision_wait_can_be_cancelled_without_a_ui_reply(self):
        from ui.dialog.modpack_missing import MissingModDecision
        decision = MissingModDecision([dict(name='private.jar')])
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(DownloadCancelled):
            decision.wait(cancel)
        decision.answer(False)
        decision.answer(True)
        self.assertFalse(decision.accepted)
