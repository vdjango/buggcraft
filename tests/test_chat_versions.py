"""Real vanilla protocol-family coverage, using publisher-hash-verified jars."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / '.test-tools'), str(ROOT / 'buggcraft/src/buggcraft')]
from hookup.game_chat import GameChatBridge
from hookup.rooms import game_status

VERSIONS = [('1.6.4',78), ('1.7.10',5), ('1.8.9',47), ('1.12.2',340),
            ('1.16.5',754), ('1.18.2',758), ('1.19',759), ('1.19.2',760),
            ('1.19.3',761), ('1.20.1',763), ('1.20.4',765), ('26.2',776), ('26.3',777)]
ASSETS = ROOT / 'multiplayer-tests/chat-servers'
if os.environ.get('BUGGCRAFT_CHAT_VERSIONS'):
    from hookup.game_chat import PROFILES
    requested = os.environ['BUGGCRAFT_CHAT_VERSIONS'].split(',')
    if requested == ['protocols']:
        VERSIONS = [('1.6.4', 78)] + [(profile['releases'][0], int(key))
                                    for key, profile in PROFILES.items()]
    else:
        if requested == ['all']:
            manifest = json.loads((Path(__file__).parent / 'fixtures/java_releases.json')
                                 .read_text(encoding='utf8'))
            requested = manifest['releases']
        VERSIONS = [(version, 78 if version == '1.6.4' else next(
                    int(key) for key, profile in PROFILES.items()
                    if version in profile.get('releases', []))) for version in requested]


@unittest.skipUnless(shutil.which('java') and all((ASSETS/v/'server.jar').exists()
                     for v, _ in VERSIONS), 'Verified version-matrix server jars required')
class ChatVersionTests(unittest.IsolatedAsyncioTestCase):
    async def wait(self, condition, timeout=40):
        async with asyncio.timeout(timeout):
            while not condition():
                await asyncio.sleep(.04)

    async def exercise(self, version, protocol):
        server = None
        bridges, tasks, states, received = [], [], [], []
        with tempfile.TemporaryDirectory(prefix='chat-version-', dir=ROOT/'multiplayer-tests') as directory:
            work = Path(directory)
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            (work/'eula.txt').write_text('eula=true\n')
            (work/'server.properties').write_text(
                f'server-ip=127.0.0.1\nserver-port={port}\nonline-mode=false\n'
                'enforce-secure-profile=false\nwhite-list=false\nmax-players=10\nview-distance=3\n'
                'simulation-distance=2\nlevel-type=FLAT\ngamemode=1\n'
                'difficulty=0\nspawn-protection=0\nnetwork-compression-threshold=256\n')
            log = (work/'console.log').open('wb')
            try:
                java = str(ROOT / 'multiplayer-tests/java25/mojang/bin/java.exe') if protocol >= 775 else 'java'
                server = await asyncio.create_subprocess_exec(java,'-Xms256M','-Xmx1G','-jar',
                    str(ASSETS/version/'server.jar'), 'nogui', cwd=work,
                    stdin=asyncio.subprocess.PIPE, stdout=log, stderr=asyncio.subprocess.STDOUT)
                await self.wait(lambda: b'Done (' in (work/'console.log').read_bytes()
                                or server.returncode is not None, 90)
                self.assertIsNone(server.returncode, (work/'console.log').read_text(errors='replace'))
                info = await game_status(port)
                self.assertEqual(info['protocol'], protocol)
                async def message(name, value):
                    received.append((name, value))
                def create(previous=None):
                    bridge = GameChatBridge(port, protocol, message, lambda *s: states.append(s))
                    if previous:
                        bridge.name, bridge.uuid = previous.name, previous.uuid
                    bridges.append(bridge)
                    tasks.append(asyncio.create_task(bridge.run()))
                    return bridge
                # Cold vanilla registries in 1.20.x are not safe to encode on
                # two login IO threads at once. Start the observer first, as the
                # launcher does, then keep both participants online throughout
                # the chat/rejoin checks. Concurrent game clients are covered
                # separately by the four-player game integration tests.
                first = create()
                await self.wait(lambda: first.ready or tasks[0].done())
                self.assertTrue(first.ready, states)
                second = create()
                await self.wait(lambda: all(b.ready for b in (first, second))
                                or any(t.done() for t in tasks))
                self.assertTrue(all(b.ready for b in bridges), states)
                for turn in range(10):
                    sent = 'version-' + version + '-round-' + str(turn) + ' 中文'
                    await bridges[turn % 2].send_message('Player', sent)
                    await self.wait(lambda: any(sent in value for _, value in received))
                    await asyncio.sleep(.6)
                tasks[1].cancel()
                await asyncio.gather(tasks[1], return_exceptions=True)
                await asyncio.sleep(.5)
                third = create(second)
                await self.wait(lambda: third.ready or tasks[-1].done())
                self.assertTrue(third.ready, states)
                await third.send_message('Player', 'same-world-rejoin-' + version)
                await self.wait(lambda: any('same-world-rejoin-' + version in value for _, value in received))
                await asyncio.sleep(12)
                self.assertTrue(first.ready and third.ready, states)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                if server and server.returncode is None:
                    server.stdin.write(b'stop\n')
                    try:
                        await asyncio.wait_for(server.wait(), 20)
                    except asyncio.TimeoutError:
                        server.kill()
                        await server.wait()
                log.close()
                shutil.copyfile(work/'console.log', ASSETS/version/'chat-console.log')

    async def test_protocol_families_ten_rounds_and_world_rejoin(self):
        result_path = ROOT/'multiplayer-tests/chat-version-results.json'
        if result_path.exists():
            results = {item['version']: item for item in json.loads(result_path.read_text(encoding='utf8'))
                       if item.get('result') == 'passed'}
        else:
            results = {}
        # Each version has its own loopback server and temp world. Keep three
        # in flight: full release-matrix coverage stays practical without
        # spawning dozens of JVMs at once on an ordinary test machine.
        limit = asyncio.Semaphore(3)
        result_lock = asyncio.Lock()
        def save():
            ordered = sorted(results.values(), key=lambda item: tuple(map(int, item['version'].split('.'))))
            temporary = result_path.with_suffix('.json.tmp')
            temporary.write_text(json.dumps(ordered, ensure_ascii=False, indent=2), encoding='utf8')
            temporary.replace(result_path)
        async def run_version(version, protocol):
            async with limit:
                try:
                    await self.exercise(version, protocol)
                except Exception as error:
                    outcome = {'version':version, 'protocol':protocol, 'result':'failed', 'error':str(error)}
                else:
                    outcome = {'version':version, 'protocol':protocol, 'result':'passed',
                               'rounds':10, 'samePlayerRejoin':True, 'keepalive':True}
                async with result_lock:
                    results[version] = outcome
                    save()
                print(version, outcome['result'], flush=True)
                return outcome
        outcomes = await asyncio.gather(*(run_version(v, p) for v, p in VERSIONS))
        for item in outcomes:
            with self.subTest(version=item['version']):
                self.assertEqual(item['result'], 'passed', item.get('error', ''))


if __name__ == '__main__':
    unittest.main(verbosity=2)
