"""Room preparation with native-endpoint fixtures and real isolated game files."""
import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from hookup.modpack import manifest_hash
from hookup.preparation import install_game, prepare_configuration
from hookup.rooms import compatibility, instance_metadata, metadata_loader


class RoomLoaderTests(unittest.TestCase):
    def test_forge_and_neoforge_launch_profiles_are_recognized(self):
        self.assertEqual(metadata_loader({'libraries': [{'name':'net.minecraftforge:fmlloader:1.20.1-47.4.0'}],
            'arguments': {'game':['--fml.forgeVersion', '47.4.0']}}), ('forge', '47.4.0'))
        self.assertEqual(metadata_loader({'libraries': [{'name':'net.neoforged:fancymodloader:4.0'}],
            'arguments': {'game':['--fml.neoForgeVersion', '21.1.77']}}), ('neoforge', '21.1.77'))

    def test_loader_build_is_advisory_but_game_and_loader_type_must_match(self):
        game = dict(version='1.20.1', loader='forge', loader_version='47.4.0', mods_hash='a')
        errors, warnings = compatibility(dict(game, loader_version='47.3.0'), game)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, ['加载器版本不一致'])
        for overrides in ({'loader':'fabric'}, {'version':'1.20.2'}, {'mods_hash':'b'}):
            self.assertTrue(compatibility(dict(game, **overrides), game)[0])

    def test_host_build_is_preferred_and_missing_build_uses_newest_same_loader(self):
        for host, available, expected in [('47.4.0', ['47.5.0','47.4.0'], '47.4.0'),
                                         ('47.3.0', ['47.5.0','47.4.0'], '47.5.0'),
                                         ('', ['47.5.0'], '47.5.0')]:
            with self.subTest(host=host), patch('core.loaders.available_versions', return_value=available) as catalogue, \
                    patch('core.loaders.install_loader', return_value='installed') as install:
                report = Mock()
                result = install_game(dict(version='1.20.1', loader='forge', loader_version=host),
                                      'isolated', 'java', 'BMCLAPI', threading.Event(), report)
                self.assertEqual(result, 'installed')
                catalogue.assert_called_once_with('Forge', '1.20.1', 'BMCLAPI')
                self.assertEqual(install.call_args.args[:3], ('Forge','1.20.1',expected))

    def test_catalogue_outage_keeps_exact_host_build_and_vanilla_never_receives_mods(self):
        with patch('core.loaders.available_versions', side_effect=OSError('offline')), \
                patch('core.loaders.install_loader', return_value='installed') as install:
            install_game(dict(version='1.20.1', loader='forge', loader_version='47.4.0'),
                         'isolated', 'java', 'BMCLAPI', threading.Event(), Mock())
            self.assertEqual(install.call_args.args[:3], ('Forge','1.20.1','47.4.0'))
        with patch('core.downloads.MinecraftDownloader') as downloader:
            with self.assertRaisesRegex(ValueError, '未识别到加载器'):
                install_game(dict(version='1.20.1', loader='vanilla', mods_count=1),
                             'isolated', 'java', 'BMCLAPI', threading.Event(), Mock())
            downloader.assert_not_called()

    def test_empty_loader_catalogue_has_actionable_error(self):
        with patch('core.loaders.available_versions', return_value=[]), patch('core.loaders.install_loader') as install:
            with self.assertRaisesRegex(ValueError, '没有适用于 Minecraft 1.20.1 的 Forge'):
                install_game(dict(version='1.20.1', loader='forge', loader_version='47.4.0'),
                             'isolated', 'java', 'BMCLAPI', threading.Event(), Mock())
            install.assert_not_called()


class RoomPreparationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.payload = b'mod bytes' * 20000
        self.item = dict(name='example.jar', size=len(self.payload), sha256=hashlib.sha256(self.payload).hexdigest())
        self.game = dict(version='1.20.1', loader='forge', loader_version='47.4.0',
                         mods_count=1, mods_hash=manifest_hash([self.item]))
        async def transfer(item, target, cancel, progress):
            target.write_bytes(self.payload)
            progress(len(self.payload), len(self.payload))
        self.endpoint = SimpleNamespace(room_info={'game':self.game},
            mod_manifest=AsyncMock(return_value=[self.item]), download_mod=AsyncMock(side_effect=transfer))
        self.events, self.progress = [], []

    def install(self, game, directory, *args):
        for identity, value in [('1.20.1', dict(id='1.20.1', libraries=[], arguments={'game':['base']})),
                ('forge-installed', dict(id='forge-installed', inheritsFrom='1.20.1',
                    mainClass='cpw.mods.bootstraplauncher.BootstrapLauncher',
                    libraries=[{'name':'net.minecraftforge:fmlloader:1.20.1-47.4.0'}],
                    arguments={'game':['--fml.forgeVersion','47.4.0']}))]:
            file = Path(directory) / 'versions' / identity / (identity + '.json')
            file.parent.mkdir(parents=True)
            file.write_text(json.dumps(value), encoding='utf8')
        return 'forge-installed'

    async def prepare(self, cancel=None, existing_instance=None):
        with patch('hookup.preparation.install_game', side_effect=self.install):
            return await prepare_configuration(self.endpoint, self.root, 'java', 'BMCLAPI',
                cancel or threading.Event(), lambda *value: self.progress.append(value), event=self.events.append,
                existing_instance=existing_instance)

    async def test_downloads_are_verified_and_isolated_with_loader_and_detailed_events(self):
        existing = self.root / 'mods/existing.jar'
        existing.parent.mkdir()
        existing.write_bytes(b'keep')
        identity = await self.prepare()
        folder = self.root / 'versions' / identity
        self.assertEqual((folder / 'mods/example.jar').read_bytes(), self.payload)
        self.assertEqual(existing.read_bytes(), b'keep')
        metadata = instance_metadata(self.root, identity, folder)
        self.assertEqual(metadata['loader'], 'forge')
        self.assertEqual(metadata['loader_version'], '47.4.0')
        self.assertEqual(metadata['mods_hash'], self.game['mods_hash'])
        self.assertEqual(metadata['version'], '1.20.1')
        self.assertFalse((folder / '.buggcraft-preparing').exists())
        self.assertTrue(any(item['kind'] == 'progress' and item['done'] == len(self.payload) for item in self.events))
        verified = next(item for item in self.events if item.get('state') == 'verified')
        self.assertEqual(verified['sha256'], self.item['sha256'])
        self.assertTrue(all(0 <= done <= total for _, done, total in self.progress if total))

    async def test_existing_instance_reuses_sixty_five_matching_mods_and_downloads_only_missing_one(self):
        versions = self.root / 'versions'
        (versions / '1.20.1').mkdir(parents=True)
        (versions / '1.20.1' / '1.20.1.json').write_text(
            json.dumps(dict(id='1.20.1', libraries=[], arguments={'game':['base']})), encoding='utf8')
        (versions / 'forge-installed').mkdir()
        (versions / 'forge-installed' / 'forge-installed.json').write_text(json.dumps(dict(
            id='forge-installed', inheritsFrom='1.20.1', mainClass='cpw.mods.bootstraplauncher.BootstrapLauncher',
            libraries=[{'name':'net.minecraftforge:fmlloader:1.20.1-47.4.0'}],
            arguments={'game':['--fml.forgeVersion','47.4.0']})), encoding='utf8')
        old_mods = self.root / 'mods'
        old_mods.mkdir()
        items, payloads = [], {}
        for index in range(66):
            payload = f'jar contents {index}'.encode()
            name = f'host-{index:02}.jar'
            item = dict(name=name, size=len(payload), sha256=hashlib.sha256(payload).hexdigest())
            items.append(item)
            payloads[item['sha256']] = payload
            if index < 65:
                (old_mods / f'local-{index:02}.jar').write_bytes(payload)
        self.game.update(mods_count=len(items), mods_hash=manifest_hash(items))
        self.endpoint.room_info['game'] = self.game
        self.endpoint.mod_manifest.return_value = items
        async def download(item, target, cancel, progress):
            target.write_bytes(payloads[item['sha256']])
            progress(item['size'], item['size'])
        self.endpoint.download_mod.side_effect = download
        with patch('hookup.preparation.install_game', side_effect=AssertionError('existing install must be reused')):
            identity = await prepare_configuration(self.endpoint, self.root, 'java', 'BMCLAPI',
                threading.Event(), lambda *value: None, event=self.events.append,
                existing_instance={'version':'forge-installed', 'game_directory':str(self.root)})
        self.endpoint.download_mod.assert_awaited_once()
        call = self.endpoint.download_mod.await_args
        self.assertEqual(call.args[0], items[-1])
        self.assertTrue(call.args[1].name.startswith('.p2p-'))
        self.assertEqual(call.args[1].parent, self.root / 'versions' / identity / 'mods')
        installed = self.root / 'versions' / identity / 'mods'
        self.assertEqual(len(list(installed.glob('*.jar'))), 66)
        self.assertEqual((installed / items[0]['name']).read_bytes(), payloads[items[0]['sha256']])
        self.assertEqual((installed / items[-1]['name']).read_bytes(), payloads[items[-1]['sha256']])
        self.assertEqual((old_mods / 'local-00.jar').read_bytes(), payloads[items[0]['sha256']])

    async def test_public_hash_match_is_tried_before_host_transfer(self):
        item = dict(self.item, sha1=hashlib.sha1(self.payload).hexdigest())
        self.game['mods_hash'] = manifest_hash([item])
        self.endpoint.room_info['game'] = self.game
        self.endpoint.mod_manifest.return_value = [item]
        async def public_download(item, base, target, source, cancel, progress):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.payload)
            progress(len(self.payload), len(self.payload))
            return True
        with patch('hookup.preparation.fetch_public_mod', side_effect=public_download) as resource:
            identity = await self.prepare()
        resource.assert_awaited_once()
        self.endpoint.download_mod.assert_not_awaited()
        self.assertEqual((self.root / 'versions' / identity / 'mods' / item['name']).read_bytes(), self.payload)

    async def test_public_resource_lookup_requires_exact_hash_and_size(self):
        from hookup.preparation import fetch_public_mod
        from unittest.mock import ANY
        item = dict(self.item, sha1=hashlib.sha1(self.payload).hexdigest(),
                    sha512=hashlib.sha512(self.payload).hexdigest())
        url = 'https://cdn.modrinth.com/data/project/version/example.jar'
        response = {'files': [
            {'hashes': {'sha1': item['sha1'], 'sha512': item['sha512']}, 'size': item['size'] + 1,
             'primary': True, 'url': url},
            {'hashes': {'sha1': item['sha1'], 'sha512': item['sha512']}, 'size': item['size'],
             'primary': True, 'url': url},
        ]}
        with patch('core.content_mirrors.get_modrinth', return_value=response) as lookup, \
                patch('core.downloads.MinecraftDownloader') as downloader:
            found = await fetch_public_mod(item, self.root, self.root / 'mods' / item['name'],
                                           'BMCLAPI', threading.Event(), Mock())
        self.assertTrue(found)
        lookup.assert_called_once_with('/version_file/' + item['sha1'], {}, ANY, 'MCIM')
        downloader.return_value.fetch.assert_called_once_with(url, 'mods/example.jar', item['sha1'],
                                                               item['size'], file_progress=ANY)

    async def test_invited_install_surfaces_host_transfer_denial_without_publishing_partial_instance(self):
        denial = '房主尚未允许房间成员从本机接收模组，请房主在房间设置中开启模组共享。'
        with patch('hookup.preparation.fetch_public_mod', new=AsyncMock(return_value=False)):
            self.endpoint.download_mod.side_effect = ConnectionError(denial)
            with self.assertRaisesRegex(ConnectionError, '房主尚未允许'):
                await self.prepare()
        failed = next(event for event in self.events if event.get('state') == 'failed')
        self.assertIn('房主尚未允许', failed['error'])
        for folder in (self.root / 'versions').glob('room-*'):
            self.assertFalse((folder / (folder.name + '.json')).exists())

    async def test_wrong_installed_loader_never_downloads_or_publishes_configuration(self):
        original = self.install
        def vanilla(*args):
            original(*args)
            return '1.20.1'
        self.install = vanilla
        with self.assertRaisesRegex(ValueError, '加载器安装校验失败'):
            await self.prepare()
        self.endpoint.download_mod.assert_not_called()
        self.assertEqual(list((self.root / 'versions').glob('room-*')), [])

    async def test_corruption_and_host_changes_never_publish_a_launchable_instance(self):
        for corrupt in (True, False):
            with self.subTest(corrupt=corrupt):
                async def transfer(item, target, cancel, progress):
                    target.write_bytes(b'bad' if corrupt else self.payload)
                    if not corrupt:
                        self.endpoint.room_info['game'] = dict(self.game, loader_version='47.5.0')
                self.endpoint.room_info['game'] = self.game
                self.endpoint.download_mod.side_effect = transfer
                # Each run gets its own fixture root, just like separate clients.
                self.root = self.root / str(corrupt)
                with self.assertRaisesRegex(ValueError, '校验失败|配置发生变化'):
                    await self.prepare()
                if corrupt:
                    self.assertTrue(any(item.get('state') == 'failed' and item['name'] == 'example.jar'
                                        and '校验失败' in item['error'] for item in self.events))
                for folder in (self.root / 'versions').glob('room-*'):
                    self.assertFalse((folder / (folder.name + '.json')).exists())

    async def test_cancel_before_install_creates_no_game_files(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(InterruptedError):
            await self.prepare(cancel)
        self.assertFalse((self.root / 'versions').exists())


if __name__ == '__main__':
    unittest.main()
