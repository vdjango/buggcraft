"""Native launcher integration against the existing isolated node account/relay fixture."""
import asyncio
import datetime
import ipaddress
import json
import os
from pathlib import Path
import ssl
import sys
import tempfile

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


async def main():
    project = Path(__file__).resolve().parents[2]
    build = Path(os.environ.get('BUGG_TEST_BUILD_DIR', project / 'build')).resolve()
    native = project.parent / 'minecraft-tunnel-native'
    sys.path[:0] = [str(native / 'compatibility'), str(native / 'web')]
    os.environ['BUGGCRAFT_NATIVE_CORE'] = str(build / 'native/bin/buggcraft-core.exe')
    from tunnel.native_relay import RelayServer
    import tunnel.relay
    tunnel.relay.RelayServer = RelayServer
    from tests.test_web_accounts import WebAccountTests, sign, canonical
    from aiohttp.test_utils import BaseTestServer
    from aiohttp import TCPConnector

    with tempfile.TemporaryDirectory(prefix='bugg-node-tls-') as scratch:
        root = Path(scratch)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Bugg loopback test')])
        now = datetime.datetime.now(datetime.timezone.utc)
        certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=1))
            .not_valid_after(now + datetime.timedelta(hours=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
            .sign(key, hashes.SHA256()))
        ca = root / 'ca.pem'
        ca.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        private = root / 'server.pem'
        private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption()))
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(ca, private)
        os.environ['SSL_CERT_FILE'] = str(ca)
        client_tls = ssl.create_default_context(cafile=str(ca))
        fixture_module = sys.modules[WebAccountTests.__module__]
        original_client = fixture_module.TestClient
        fixture_module.TestClient = lambda *args, **kwargs: original_client(
            *args, connector=TCPConnector(ssl=client_tls), **kwargs)
        original_start = BaseTestServer.start_server
        async def start_tls(self, loop=None, **kwargs):
            return await original_start(self, loop=loop, ssl=tls, **kwargs)
        BaseTestServer.start_server = start_tls
        fixture = WebAccountTests()
        process = None
        try:
            await fixture.asyncSetUp()
            if os.environ.get('BUGG_TEST_LAUNCHER_CLIENTS') == '1':
                from launcher_clients import run_clients
                await run_clients(project, fixture, ca)
                return
            user = await fixture.create_user('launcher-approval-integration')
            peer = await fixture.create_user('NativePeer')
            peer_headers, peer_auth = await fixture.login_user(fixture.clients[1], peer)
            headers, _ = await fixture.login_user(fixture.clients[0], user)
            from tunnel.friend_codes import friend_code
            async def accept_peer():
                social = fixture.portals[0].account_api.store.social
                while True:
                    state = social.state(peer[0])
                    for request in state['requests']:
                        if request['incoming']:
                            social.apply(peer[0], fixture.event(peer_auth, 'accept', request['account'], ref=request['id']))
                    social.apply(peer[0], fixture.event(peer_auth, 'presence', peer[0]))
                    await asyncio.sleep(.2)
            peer_task = asyncio.create_task(accept_peer())
            trace = build / 'node-loopback-trace.json'
            trace.unlink(missing_ok=True)
            environment = os.environ.copy()
            environment.update(BUGG_TEST_LIVE_NODE='1', BUGG_TEST_NODE_BROWSER_APPROVAL='1',
                BUGG_TEST_NODE_ORIGIN=str(fixture.clients[0].server.make_url('/')).rstrip('/'),
                BUGG_TEST_NODE_PEER_CODE=friend_code(peer[0]), BUGG_TEST_NODE_PEER=peer[0], BUGG_TEST_NODE_CA=str(ca), BUGG_TEST_NODE_TRACE=str(trace), QTEST_FUNCTION_TIMEOUT='900000')
            environment['PATH'] = str(project.parent / '.tools/Qt/6.8.1/msvc2022_64/bin') + os.pathsep + environment['PATH']
            process = await asyncio.create_subprocess_exec(str(build / 'runtime_test.exe'),
                'live_node_authorization', '-o', str(build / 'node-loopback-native.txt') + ',txt',
                cwd=project, env=environment)
            url = ''
            for _ in range(300):
                if trace.exists():
                    snapshot = json.loads(trace.read_text(encoding='utf-8'))
                    url = snapshot.get('verificationUrl', '')
                    if url:
                        break
                    if snapshot.get('state') == 'signedOut':
                        raise AssertionError(snapshot.get('error'))
                if process.returncode is not None:
                    raise AssertionError('Native test exited before authorization')
                await asyncio.sleep(.1)
            if not url:
                raise AssertionError('No native authorization request')
            from urllib.parse import parse_qs, urlparse
            identifier = parse_qs(urlparse(url).query)['launcher'][0]
            prepared = await fixture.clients[0].post('/api/launcher/prepare', json={'id': identifier}, headers=headers)
            assert prepared.status == 200, await prepared.text()
            grant = (await prepared.json())['grant']
            approved = await fixture.clients[0].post('/api/launcher/approve',
                json={'id': identifier, 'signature': sign(user[1], canonical(grant))}, headers=headers)
            assert approved.status == 200, await approved.text()
            print('Isolated node approved the exact native device request.', flush=True)
            result = await asyncio.wait_for(process.wait(), 120)
            print((build / 'node-loopback-native.txt').read_text(encoding='mbcs', errors='replace'), flush=True)
            if result:
                raise AssertionError('Native end-to-end authorization failed')
        finally:
            if process is not None and process.returncode is None:
                process.terminate()
                await process.wait()
            if 'peer_task' in locals():
                peer_task.cancel()
                await asyncio.gather(peer_task, return_exceptions=True)
            await fixture.asyncTearDown()
            fixture.doCleanups()
            BaseTestServer.start_server = original_start
            fixture_module.TestClient = original_client


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    asyncio.run(main())
