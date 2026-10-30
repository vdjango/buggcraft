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
from core.downloads import DownloadCancelled, MinecraftDownloader
from core.modpack_missing import unavailable_mod
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
