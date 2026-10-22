"""Isolated mod preparation, authenticated transport, corruption and cancellation."""
import asyncio
import hashlib
import json
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / '.test-tools'), str(ROOT / 'buggcraft/src/buggcraft'),
               str(ROOT / 'minecraft-tunnel/src')]
import asyncssh
from hookup.modpack import manifest, validate_manifest, fetch_manifest, fetch_mod
from hookup.preparation import prepare_configuration, resolved_metadata
from hookup.rooms import instance_metadata
from hookup.relay import RelayProfile, TunnelHost, TunnelClient
from tunnel.relay import RelayServer
from config.settings import SettingsManager
from core.launch_options import configure_room_join


class ModManifestTests(unittest.TestCase):
    def test_resolved_loader_keeps_native_classifiers_and_overrides_library_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent = dict(id='base', libraries=[{'name': 'org.lwjgl:lwjgl:3.3.1'},
                {'name': 'org.lwjgl:lwjgl:3.3.1:natives-windows'},
                {'name': 'org.lwjgl:lwjgl:3.3.1:natives-linux'}], arguments={'game': ['base']})
            child = dict(id='fabric', inheritsFrom='base', libraries=[{'name': 'org.lwjgl:lwjgl:3.3.2'}],
                         arguments={'game': ['loader']})
            for value in (parent, child):
                path = root / 'versions' / value['id'] / (value['id'] + '.json')
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps(value))
            metadata = resolved_metadata(root, 'fabric')
            names = [item['name'] for item in metadata['libraries']]
            self.assertIn('org.lwjgl:lwjgl:3.3.2', names)
            self.assertIn('org.lwjgl:lwjgl:3.3.1:natives-windows', names)
            self.assertIn('org.lwjgl:lwjgl:3.3.1:natives-linux', names)
            self.assertNotIn('org.lwjgl:lwjgl:3.3.1', names)
            self.assertEqual(metadata['arguments']['game'], ['base', 'loader'])
            self.assertEqual(metadata['jar'], 'base')
            self.assertNotIn('inheritsFrom', metadata)

    def test_untrusted_paths_duplicates_and_sizes_are_rejected(self):
        item = dict(name='safe.jar', sha256='a' * 64, size=10)
        validate_manifest([item])
        for name in ('../bad.jar', 'C:bad.jar', 'folder/bad.jar', 'folder\\bad.jar', 'bad.exe'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_manifest([{**item, 'name': name}])
        with self.assertRaises(ValueError):
            validate_manifest([item, {**item, 'name': 'SAFE.jar'}])
        for size in (-1, True, 2 ** 40):
            with self.assertRaises(ValueError):
                validate_manifest([{**item, 'size': size}])

    def test_room_configuration_keeps_isolation_when_global_is_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = SettingsManager(str(root / 'settings'))
            settings.set_setting('minecraft.directory.enable', str(root))
            settings.set_setting('minecraft.version.enable', 'room-example')
            settings.set_setting('minecraft.isolation', False)
            path = root / 'versions/room-example/room-example.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'buggcraftRoom': {}}))
            self.assertEqual(Path(settings.get_minecraft_isolation_directory()), path.parent)

    def test_quick_play_and_legacy_ports_use_the_installed_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for identity, metadata in (('old', {}), ('new', {'arguments': {'game': [
                    {'rules': [{'action': 'allow', 'features': {'is_quick_play_multiplayer': True}}],
                     'value': ['--quickPlayMultiplayer', '${quickPlayMultiplayer}']}]}})):
                path = root / 'versions' / identity / (identity + '.json')
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps(metadata))
                options = {'gameDirectory': str(path.parent)}
                configure_room_join(options, '127.0.0.1:45678', root, identity)
                if identity == 'old':
                    self.assertEqual(options['server'], '127.0.0.1')
                    self.assertEqual(options['port'], '45678')
                else:
                    self.assertEqual(options['quickPlayMultiplayer'], '127.0.0.1:45678')
                    self.assertNotIn('server', options)


class RoomPreparationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.work = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.host_root = self.work / 'host'
        (self.host_root / 'mods').mkdir(parents=True)
        (self.host_root / 'mods/example.jar').write_bytes(b'mod bytes' * 20000)
        metadata = self.host_root / 'versions/1.20.1/1.20.1.json'
        metadata.parent.mkdir(parents=True)
        metadata.write_text(json.dumps({'id': '1.20.1'}))
        self.game = instance_metadata(self.host_root, '1.20.1', self.host_root)
        key = asyncssh.generate_private_key('ssh-ed25519')
        self.relay = await RelayServer('127.0.0.1', 0, host_key=key, token=secrets.token_urlsafe(48)).start()
        self.profile = RelayProfile('127.0.0.1', self.relay.port, self.relay.token, key.export_public_key().decode())
        self.host = TunnelHost(self.profile, game_port=0, announce=False,
            game_directory=str(self.host_root), room_settings={'title': 'Mods', 'game': self.game})
        self.tasks = [asyncio.create_task(self.host.run())]
        self.client = None
        await self.wait(lambda: self.host.pack_listener is not None)
        self.client = TunnelClient(self.profile, self.host.invite, listen_port=0, announce=False)
        self.tasks.append(asyncio.create_task(self.client.run()))
        await self.wait(lambda: self.client.chat_process is not None)

    async def asyncTearDown(self):
        await asyncio.gather(*(p.stop() for p in (self.client, self.host) if p), return_exceptions=True)
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.relay.close()

    async def wait(self, predicate):
        async with asyncio.timeout(15):
            while not predicate():
                await asyncio.sleep(.02)

    async def test_waiting_room_transfers_hash_verified_mods_to_new_isolated_configuration(self):
        await self.wait(lambda: self.client.room_state == 'waiting')
        items = await fetch_manifest(self.client)
        self.assertEqual(items, manifest(self.host_root))
        root = self.work / 'client'
        existing = root / 'mods/existing.jar'
        existing.parent.mkdir(parents=True)
        existing.write_bytes(b'keep')
        def install(game, directory, *args):
            path = Path(directory) / 'versions/1.20.1/1.20.1.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'id': '1.20.1', 'mainClass': 'net.minecraft.client.main.Main'}))
            return '1.20.1'
        progress = []
        with patch('hookup.preparation.install_game', side_effect=install):
            identity = await prepare_configuration(self.client, root, 'java', 'BMCLAPI', threading.Event(),
                                                   lambda *state: progress.append(state))
        path = root / 'versions' / identity
        self.assertEqual((path / 'mods/example.jar').read_bytes(), (self.host_root / 'mods/example.jar').read_bytes())
        self.assertEqual(existing.read_bytes(), b'keep')
        self.assertEqual(instance_metadata(root, identity, path)['mods_hash'], self.game['mods_hash'])
        self.assertEqual(instance_metadata(root, identity, path)['version'], '1.20.1')
        self.assertTrue(any(total > 0 for _, done, total in progress))
        self.assertFalse((path / '.buggcraft-preparing').exists())
        other = TunnelHost(self.profile, game_port=0, announce=False)
        other_task = asyncio.create_task(other.run())
        try:
            await self.wait(lambda: other.chat_process is not None)
            with self.assertRaises(asyncssh.ChannelOpenError):
                await self.client.connection.open_connection(other.invite.room_id, 25564)
        finally:
            await other.stop()
            await asyncio.gather(other_task, return_exceptions=True)

    async def test_changed_host_mod_fails_verification_and_never_publishes_bad_file(self):
        item = (await fetch_manifest(self.client))[0]
        original = self.host_root / 'mods/example.jar'
        original.write_bytes(b'X' * original.stat().st_size)
        target = self.work / 'download.jar'
        with self.assertRaisesRegex(ValueError, '校验失败'):
            await fetch_mod(self.client, item, target, threading.Event(), lambda *args: None)
        self.assertFalse(target.exists())
        self.assertFalse(target.with_suffix('.jar.part').exists())

    async def test_cancellation_never_selects_or_publishes_partial_configuration(self):
        cancel = threading.Event()
        cancel.set()
        with patch('hookup.preparation.install_game') as install:
            with self.assertRaises(InterruptedError):
                await prepare_configuration(self.client, self.work / 'cancelled', 'java', '官方', cancel,
                                            lambda *args: None)
        install.assert_not_called()

    async def test_host_version_change_reaches_joined_player_without_leaving_room(self):
        await self.wait(lambda: self.client.room_state == 'waiting')
        await self.host.update_game({**self.game, 'version': '1.20.2'})
        await self.wait(lambda: self.client.room_info.get('game', {}).get('version') == '1.20.2')
        self.assertIsNotNone(self.client.chat_process)

    async def test_refreshing_same_mod_directory_republishes_manifest(self):
        await self.wait(lambda: self.client.room_state == 'waiting')
        (self.host_root / 'mods/second.jar').write_bytes(b'another mod')
        changed = instance_metadata(self.host_root, '1.20.1', self.host_root)
        await self.host.update_game(changed, str(self.host_root))
        await self.wait(lambda: self.client.room_info['game']['mods_hash'] == changed['mods_hash'])
        self.assertEqual(await fetch_manifest(self.client), manifest(self.host_root))


if __name__ == '__main__':
    unittest.main()
