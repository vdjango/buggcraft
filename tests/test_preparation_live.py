"""Opt-in real loader install -> room mod transfer -> graphical game joins LAN."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / '.test-tools'), str(ROOT / 'buggcraft/src/buggcraft'),
               str(ROOT / 'minecraft-tunnel/src')]
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import requests
import asyncssh
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from core.loaders import install_loader
from core.downloads import verified_installation
from core.launcher import MinecraftLibLauncher
from config.settings import SettingsManager
from hookup.rooms import instance_metadata
from hookup.preparation import prepare_configuration
from hookup.relay import RelayProfile, TunnelHost, TunnelClient
from tunnel.relay import RelayServer


@unittest.skipUnless(os.environ.get('BUGGCRAFT_LIVE_PREPARATION_PORT'), 'Opt-in real install and LAN test')
class LivePreparationTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    async def wait(self, predicate, timeout=120):
        async with asyncio.timeout(timeout):
            while not predicate():
                self.app.processEvents()
                await asyncio.sleep(.05)

    async def test_fabric_install_and_verified_room_configuration_reaches_real_world(self):
        root = ROOT / 'multiplayer-tests/download-live/minecraft'
        work = ROOT / 'multiplayer-tests/preparation-live'
        work.mkdir(exist_ok=True)
        java = r'C:\Program Files\Microsoft\jdk-21.0.8.9-hotspot\bin\java.exe'
        events, progress = [], []
        def report(status, done=0, total=0):
            progress.append((str(status)[:200], done, total))
        callback = dict(setStatus=lambda text: report(text), setMax=lambda total: None,
                        setProgress=lambda done: None)
        installed = await asyncio.to_thread(install_loader, 'Fabric', '1.21.8', '0.16.14',
            str(root), java, callback, threading.Event(), 'BMCLAPI')
        shared = work / 'host-game'
        (shared / 'mods').mkdir(parents=True, exist_ok=True)
        # Official Fabric API publication supplies the actual downloadable test mod.
        def download_mod():
            response = requests.get('https://api.modrinth.com/v2/project/fabric-api/version',
                params={'game_versions':'["1.21.8"]', 'loaders':'["fabric"]'}, timeout=30)
            response.raise_for_status()
            versions = [v for v in response.json() if v['date_published'] < '2026-10-21']
            item = next(file for file in versions[0]['files'] if file['primary'])
            target = shared / 'mods' / item['filename']
            if not target.exists() or hashlib.sha512(target.read_bytes()).hexdigest() != item['hashes']['sha512']:
                # Use the publisher's Maven endpoint when the Modrinth CDN is
                # unreachable; always verify against the independent SHA-512.
                version = versions[0]['version_number']
                url = 'https://maven.fabricmc.net/net/fabricmc/fabric-api/fabric-api/' + version + '/' + item['filename']
                data = requests.get(url, timeout=(8, 30))
                data.raise_for_status()
                self.assertEqual(hashlib.sha512(data.content).hexdigest(), item['hashes']['sha512'])
                target.write_bytes(data.content)
            return item['filename']
        mod_name = await asyncio.to_thread(download_mod)
        game = await asyncio.to_thread(instance_metadata, root, installed, shared)
        game['protocol'] = 772
        # A dedicated offline fixture verifies automatic startup independently
        # of the game's LAN-vs-Quick-Play identity policy.
        server = None
        server_log = None
        game_port = int(os.environ['BUGGCRAFT_LIVE_PREPARATION_PORT'])
        if os.environ.get('BUGGCRAFT_PREPARATION_DEDICATED'):
            import socket
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                game_port = sock.getsockname()[1]
            server_work = work / 'server'
            server_work.mkdir(exist_ok=True)
            (server_work / 'eula.txt').write_text('eula=true\n')
            (server_work / 'server.properties').write_text(f'server-ip=127.0.0.1\nserver-port={game_port}\nonline-mode=false\nenforce-secure-profile=false\nwhite-list=false\nview-distance=2\nsimulation-distance=2\n')
            server_log = (server_work / 'console.log').open('wb')
            server = await asyncio.create_subprocess_exec(java, '-Xms512M', '-Xmx2G', '-jar',
                str(ROOT / 'multiplayer-tests/game-server/server.jar'), 'nogui', cwd=server_work,
                stdin=asyncio.subprocess.PIPE, stdout=server_log, stderr=asyncio.subprocess.STDOUT)
            await self.wait(lambda: b'Done (' in (server_work / 'console.log').read_bytes(), 90)
        key = asyncssh.generate_private_key('ssh-ed25519')
        relay = await RelayServer('127.0.0.1', 0, host_key=key, token=secrets.token_urlsafe(48)).start()
        profile = RelayProfile('127.0.0.1', relay.port, relay.token, key.export_public_key().decode())
        host = TunnelHost(profile, game_port=game_port,
            announce=False, game_directory=str(shared), room_settings={'title':'Live preparation', 'game':game})
        tasks = [asyncio.create_task(host.run())]
        client = launcher = None
        try:
            await self.wait(lambda: host.pack_listener is not None)
            client = TunnelClient(profile, host.invite, listen_port=0, announce=False)
            tasks.append(asyncio.create_task(client.run()))
            await self.wait(lambda: client.chat_process is not None)
            identity = await prepare_configuration(client, root, java, 'BMCLAPI', threading.Event(), report)
            directory = root / 'versions' / identity
            self.assertEqual((directory / 'mods' / mod_name).read_bytes(), (shared / 'mods' / mod_name).read_bytes())
            detected = instance_metadata(root, identity, directory)
            self.assertEqual(detected['version'], '1.21.8')
            self.assertEqual(detected['loader'], 'fabric')
            self.assertEqual(detected['mods_hash'], game['mods_hash'])
            self.assertTrue(verified_installation(root, identity))
            settings = SettingsManager(str(work / 'config'))
            for name, value in [('minecraft.directory.enable', str(root)), ('minecraft.version.enable', identity),
                    ('minecraft.isolation', False), ('java.path', java), ('memory.allocation', 2048),
                    ('minecraft.auto_allocate_memory', False), ('game.launch_jvm_args', ''),
                    ('game.launch_args', ''), ('game.launch_pre_command', '')]:
                settings.set_setting(name, value)
            settings.save_settings()
            (directory / 'options.txt').write_text('lang:zh_cn\nsoundCategory_master:0.0\nsoundCategory_music:0.0\n'
                'renderDistance:2\nsimulationDistance:5\nmaxFps:20\nonboardAccessibility:false\npauseOnLostFocus:false\n', encoding='utf8')
            from unittest.mock import patch
            with patch('core.launcher.get_settings_manager', return_value=settings):
                launcher = MinecraftLibLauncher(str(work))
            errors = []
            launcher.signals.error.connect(errors.append)
            launcher.signals.output.connect(lambda line: events.append(line), Qt.DirectConnection)
            name = 'Prepare' + secrets.token_hex(3)
            player_id = uuid.UUID(bytes=hashlib.md5(('OfflinePlayer:' + name).encode()).digest(), version=3)
            launcher.set_options(uuid=str(player_id), username=name, token='0', version=identity,
                                 server=f'127.0.0.1:{client.listen_port}', width=854, height=480)
            launcher.start()
            log = directory / 'logs/latest.log'
            # The authoritative LAN server, rather than its menu, proves actual entry.
            host_log = work / 'server/console.log' if server else root / 'versions/1.21.8/logs/latest.log'
            await self.wait(lambda: errors or any(name + '[' in line and 'logged in' in line for line in
                host_log.read_text(encoding='utf8', errors='replace').splitlines()), 180)
            self.assertFalse(errors, errors)
            await asyncio.sleep(2)
            self.assertTrue(launcher.running)
            self.assertIn('fabric-api', log.read_text(encoding='utf8', errors='replace'))
            (work / 'result.json').write_text(json.dumps(dict(result='passed', version='1.21.8',
                loader='Fabric', loader_version='0.16.14', mod=mod_name, configuration=identity,
                enteredWorld=True, isolated=True, progressEvents=len(progress),
                server='dedicated-offline' if server else 'integrated-lan'), indent=2), encoding='utf8')
        finally:
            if launcher:
                launcher.stop()
                await self.wait(lambda: not launcher.running, 20)
            for endpoint in (client, host):
                if endpoint:
                    await endpoint.stop()
            await asyncio.gather(*tasks, return_exceptions=True)
            await relay.close()
            if server and server.returncode is None:
                server.stdin.write(b'stop\n')
                await asyncio.wait_for(server.wait(), 30)
            if server_log:
                server_log.close()
            (work / 'progress.json').write_text(json.dumps(progress[-300:], ensure_ascii=False, indent=2), encoding='utf8')
            (work / 'game-output.log').write_text('\n'.join(events[-500:]), encoding='utf8')


if __name__ == '__main__':
    unittest.main(verbosity=2)
