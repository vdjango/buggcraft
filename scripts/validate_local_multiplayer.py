"""Opt-in: three native Minecraft clients over real local P2P and SSH paths.

Uses an existing game installation, an isolated temporary world, and only a
loopback relay. Does not read account credentials or modify player saves.
Example:
  python scripts/validate_local_multiplayer.py --minecraft E:/games/.minecraft \
      --server-jar E:/fixtures/server.jar --output dist/local-multiplayer
"""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
import traceback
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src/buggcraft'), str(ROOT.parent / 'minecraft-tunnel/src')]


async def validate(args):
    import asyncssh
    import minecraft_launcher_lib
    from core.launch_options import configure_room_join
    from hookup.peer import PeerTransport
    from hookup.relay import RelayProfile, TunnelClient, TunnelHost
    from hookup.rooms import game_status
    from tunnel.relay import RelayServer
    from utils.diagnostics import configure_connection_logging, export_diagnostics

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    logging.basicConfig(filename=output / 'buggcraft.log', level=logging.INFO, encoding='utf-8')
    configure_connection_logging(output)
    report = {'passed': False, 'network': 'loopback', 'version': args.version,
              'started_utc': datetime.now(timezone.utc).isoformat(), 'clients': [], 'checks': []}
    endpoints, tasks, games, logs = [], [], [], []
    server = relay = None
    started = time.monotonic()

    async def wait(predicate, timeout=120):
        async with asyncio.timeout(timeout):
            while not predicate():
                if server and server.returncode is not None:
                    raise RuntimeError('Minecraft server exited; see server/console.log')
                await asyncio.sleep(.1)

    def say_progress(text):
        print(text, flush=True)

    async def endpoint(kind, invite=None, **options):
        item = kind(profile, invite, listen_port=0, announce=False, **options)
        ready = asyncio.Event()
        item.on_chat = lambda event: ready.set() if event.get('type') == 'ready' else None
        endpoints.append(item)
        task = asyncio.create_task(item.run())
        tasks.append(task)
        await asyncio.wait_for(ready.wait(), 30)
        return item

    async def launch(name, tunnel):
        directory = output / name
        directory.mkdir(exist_ok=True)
        (directory / 'options.txt').write_text(
            'lang:en_us\nrenderDistance:2\nsimulationDistance:5\nmaxFps:20\n'
            'guiScale:2\nautoJump:false\npauseOnLostFocus:false\nsoundCategory_master:0.0\n'
            'onboardAccessibility:false\n', encoding='utf-8')
        options = {'username': name, 'uuid': str(uuid.UUID(bytes=hashlib.md5(
            ('OfflinePlayer:' + name).encode()).digest(), version=3)), 'token': '0',
            'executablePath': args.java, 'jvmArguments': ['-Xms256M', '-Xmx1536M'],
            'gameDirectory': str(directory), 'launcherName': 'BuggcraftValidation',
            'launcherVersion': '1', 'customResolution': True,
            'resolutionWidth': '800', 'resolutionHeight': '450'}
        configure_room_join(options, f'127.0.0.1:{tunnel.listen_port}', args.minecraft, args.version)
        command = minecraft_launcher_lib.command.get_minecraft_command(
            args.version, str(args.minecraft), options)
        # No account tokens are passed: all names belong to this offline fixture.
        log = (directory / ('launch-' + str(len(games)) + '.log')).open('wb')
        logs.append(log)
        process = await asyncio.create_subprocess_exec(*command, cwd=directory, stdout=log,
            stderr=asyncio.subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        games.append(process)
        record = {'name': name, 'pid': process.pid, 'path': tunnel.transport_state,
                  'listen_port': tunnel.listen_port, 'trace_id': tunnel.diagnostic_trace}
        report['clients'].append(record)
        previous = server_text().count(name + ' joined the game')
        await wait(lambda: process.returncode is not None or
                   server_text().count(name + ' joined the game') > previous, 180)
        if process.returncode is not None:
            raise RuntimeError(f'{name} exited with {process.returncode}; see {directory}')
        record['entered_world'] = True
        say_progress(f'{name}: entered world via {tunnel.transport_state}, PID {process.pid}')
        return process

    def server_text():
        return (output / 'server/console.log').read_text(encoding='utf-8', errors='replace')

    async def command(value):
        server.stdin.write((value + '\n').encode())
        await server.stdin.drain()

    try:
        if not args.server_jar.is_file():
            raise FileNotFoundError(args.server_jar)
        work = output / 'server'
        work.mkdir()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        (work / 'eula.txt').write_text('eula=true\n')
        (work / 'server.properties').write_text(
            f'server-ip=127.0.0.1\nserver-port={port}\nonline-mode=false\n'
            'enforce-secure-profile=false\nwhite-list=false\nmax-players=10\nview-distance=2\n'
            'simulation-distance=2\nlevel-type=minecraft:flat\ngamemode=creative\n'
            'difficulty=peaceful\nspawn-protection=0\nenable-rcon=false\n', encoding='utf-8')
        console = (work / 'console.log').open('wb')
        logs.append(console)
        server = await asyncio.create_subprocess_exec(args.java, '-Xms256M', '-Xmx1536M', '-jar',
            str(args.server_jar.resolve()), 'nogui', cwd=work, stdin=asyncio.subprocess.PIPE,
            stdout=console, stderr=asyncio.subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        await wait(lambda: 'Done (' in server_text(), 120)
        actual = await game_status(port)
        if actual['version'] != args.version:
            raise RuntimeError('Client/server version mismatch: ' + str(actual))
        say_progress('Isolated Minecraft server ready on loopback')
        key = asyncssh.generate_private_key('ssh-ed25519')
        relay = await RelayServer('127.0.0.1', 0, host_key=key, token=secrets.token_urlsafe(48)).start()
        profile = RelayProfile('127.0.0.1', relay.port, relay.token, key.export_public_key().decode())
        host = await endpoint(TunnelHost, game_port=port)
        direct = await endpoint(TunnelClient, host.invite)
        if direct.transport_state != 'p2p':
            raise RuntimeError('Expected local P2P, got ' + direct.transport_state)
        first = await launch('BuggP2P', direct)
        # Forced relay must not even construct an ICE connection.
        with patch.object(PeerTransport, 'create_pc', side_effect=AssertionError('Forced relay started ICE')):
            forced = await endpoint(TunnelClient, host.invite, transport_policy='relay')
        if forced.transport_state != 'relay':
            raise RuntimeError('Forced relay did not select relay')
        await launch('BuggRelay', forced)
        with patch.object(PeerTransport, 'create_pc', side_effect=OSError('Test fixture: UDP unavailable')):
            fallback = await endpoint(TunnelClient, host.invite)
        if fallback.transport_state != 'relay':
            raise RuntimeError('ICE failure did not fall back to relay')
        await launch('BuggAuto', fallback)
        status = await game_status(port)
        if status['players']['online'] != 3:
            raise RuntimeError('Expected three actual game players: ' + str(status))
        report['checks'].extend(['three-native-clients-entered-world', 'p2p-path',
                                 'relay-skips-ice', 'ice-failure-falls-back'])
        # Exercise movement/chunk updates and messages while all clients stay online.
        for turn in range(5):
            marker = 'Buggcraft-network-round-' + str(turn)
            await command('tp @a ' + str(turn * 16) + ' -60 0')
            await command('say ' + marker)
            await wait(lambda: all(marker in (output / name / 'logs/latest.log').read_text(
                encoding='utf-8', errors='replace') for name in ('BuggP2P', 'BuggRelay', 'BuggAuto')), 25)
            await asyncio.sleep(4)
            status = await game_status(port)
            if status['players']['online'] != 3 or any(p.returncode is not None for p in games):
                raise RuntimeError('A client disconnected during mixed transport gameplay')
            say_progress(f'Gameplay round {turn + 1}/5: all three clients received server message')
        report['checks'].append('five-movement-and-message-rounds')
        # Actual loss of the direct channel; reconnect the real game to the same port.
        same_port = direct.listen_port
        await direct.peer_transport.client_pc.close()
        await wait(lambda: direct.transport_state == 'relay', 10)
        await wait(lambda: 'BuggP2P lost connection' in server_text(), 25)
        first.terminate()
        await asyncio.wait_for(first.wait(), 15)
        await launch('BuggP2P', direct)
        if direct.listen_port != same_port:
            raise RuntimeError('Relay fallback changed the local game address')
        await command('say Buggcraft-after-p2p-failure')
        await wait(lambda: 'Buggcraft-after-p2p-failure' in
            (output / 'BuggP2P/logs/latest.log').read_text(encoding='utf-8', errors='replace'), 25)
        status = await game_status(port)
        if status['players']['online'] != 3:
            raise RuntimeError('Rejoin did not restore three players')
        report['checks'].append('native-game-rejoined-via-relay-at-same-port')
        report['players_online'] = 3
        report['passed'] = True
    except Exception:
        report['error'] = traceback.format_exc()
        say_progress(report['error'])
    finally:
        for game in games:
            if game.returncode is None:
                game.terminate()
                try:
                    await asyncio.wait_for(game.wait(), 15)
                except asyncio.TimeoutError:
                    game.kill()
                    await game.wait()
        await asyncio.gather(*(item.stop() for item in endpoints), return_exceptions=True)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if relay:
            await relay.close()
        if server and server.returncode is None:
            await command('stop')
            try:
                await asyncio.wait_for(server.wait(), 30)
            except asyncio.TimeoutError:
                server.kill()
                await server.wait()
        for log in logs:
            log.close()
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        report['elapsed_seconds'] = round(time.monotonic() - started, 2)
        (output / 'result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        export_diagnostics(output / 'diagnostics.zip', output)
    say_progress(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--minecraft', type=Path, required=True)
    parser.add_argument('--server-jar', type=Path, required=True)
    parser.add_argument('--version', default='1.21.8')
    parser.add_argument('--java', default=shutil.which('java'))
    parser.add_argument('--output', type=Path, required=True)
    raise SystemExit(asyncio.run(validate(parser.parse_args())))
