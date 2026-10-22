"""Cross-node account proofs, encrypted replicas, replay rejection and optional registration."""
import asyncio
import copy
import hashlib
import json
import secrets
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'.test-tools'), str(ROOT/'minecraft-tunnel/src'), str(ROOT/'buggcraft/src/buggcraft')]
import asyncssh
from aiohttp import CookieJar
from aiohttp.test_utils import TestClient, TestServer
from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag
from tunnel.accounts import Accounts, canonical, encode, decode
from tunnel.federation import Federation, TTL
from tunnel.portal import Portal, password_hash
from tunnel.relay import RelayServer
from hookup.relay import RelayProfile
from hookup.nodes import profile_data, probe
from hookup.rooms import connect_directory, request, lookup_account


def key_data(key):
    numbers = key.public_key().public_numbers()
    return dict(kty='EC', crv='P-256', x=encode(numbers.x.to_bytes(32,'big')), y=encode(numbers.y.to_bytes(32,'big')))


def signed(key, payload):
    r,s = utils.decode_dss_signature(key.sign(payload, ec.ECDSA(hashes.SHA256())))
    return encode(r.to_bytes(32,'big')+s.to_bytes(32,'big'))


def routing(key, state, copies=1):
    value = dict(account=state['account'], revision=state['revision'], copies=copies,
                 digest=hashlib.sha256(canonical(state)).hexdigest())
    return dict(routing=value, routing_signature=signed(key, canonical(value)))


def encrypted(key, password, account, revision, notes='private notes'):
    salt,iv = secrets.token_bytes(16),secrets.token_bytes(12)
    aes = hashlib.pbkdf2_hmac('sha256',password.encode(),salt,600000)
    private = key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
    payload = json.dumps({'key':private,'notes':notes}).encode()
    return dict(salt=encode(salt),iv=encode(iv),ciphertext=encode(AESGCM(aes).encrypt(iv,payload,(account+'|'+str(revision)).encode())),iterations=600000)


class AccountTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.relays=[];self.feds=[];self.portals=[];self.clients=[]
        self.admin=secrets.token_urlsafe(20)
        for index in range(2):
            key=asyncssh.generate_private_key('ssh-ed25519')
            relay=await RelayServer('127.0.0.1',0,host_key=key,token=secrets.token_urlsafe(48)).start()
            profile=RelayProfile('127.0.0.1',relay.port,relay.token,key.export_public_key().decode())
            fed=Federation(key,profile_data(profile),network_key=secrets.token_urlsafe(48),name=str(index))
            fed.relay=relay;relay.federation=fed;fed.publish()
            folder=Path(self.temporary.name)/str(index);folder.mkdir()
            state=folder/'node-state.json'
            state.write_text(json.dumps(dict(admin_user='admin',admin_hash=password_hash(self.admin),access_hash=password_hash(secrets.token_urlsafe(20)),registration_open=False)),encoding='utf-8')
            portal=Portal(relay,fed,state)
            client=TestClient(TestServer(portal.app),cookie_jar=CookieJar(unsafe=True))
            await client.start_server()
            self.relays.append(relay);self.feds.append(fed);self.portals.append(portal);self.clients.append(client)

    async def asyncTearDown(self):
        await asyncio.gather(*(client.close() for client in self.clients))
        await asyncio.gather(*(fed.close() for fed in self.feds))
        await asyncio.gather(*(relay.close() for relay in self.relays))

    async def register(self, copies=1, username='player_1', index=0):
        client=self.clients[index]
        self.portals[index].state['registration_open']=True
        # This fixture opts out of external mail to isolate identity protocols.
        self.portals[index].account_api.mail.settings['required']=False
        response=await client.post('/api/account/enroll',json={})
        self.assertEqual(response.status,200)
        challenge=await response.json()
        key=ec.generate_private_key(ec.SECP256R1())
        account=challenge['account'];password=secrets.token_urlsafe(24)
        state=dict(account=account,revision=1,box=encrypted(key,password,account,1))
        response=await client.post('/api/account/register',json=dict(nonce=challenge['nonce'],username=username,
                    public_key=key_data(key),state=state,signature=signed(key,canonical(state)),
                    copies=copies,**routing(key,state,copies),
                    proof=signed(key,challenge['message'].encode())))
        self.assertEqual(response.status,201,await response.text())
        return account,key,password

    async def login(self,index,account,key):
        client=self.clients[index]
        response=await client.post('/api/account/challenge',json=dict(account=account))
        self.assertEqual(response.status,200)
        challenge=await response.json()
        proof=dict(nonce=challenge['nonce'],signature=signed(key,challenge['message'].encode()))
        response=await client.post('/api/account/login',json=proof)
        self.assertEqual(response.status,200,await response.text())
        return await response.json(),proof

    def personal_profile(self, index, account, key, issuer=0):
        """Issue a user-proved delegated credential; exercise it over real SSH."""
        delegated = ec.generate_private_key(ec.SECP256R1())
        store = self.portals[issuer].account_api.store
        challenge = store.challenge('login', account, 'https://launcher.example', key_data(delegated))
        store.authorize(account, challenge, signed(key, challenge['message'].encode()))
        secret = encode(delegated.private_numbers().private_value.to_bytes(32, 'big'))
        return RelayProfile(**dict(self.feds[index].profile, token=store.credential(account) + '~' + secret))

    async def test_cross_node_login_after_home_offline_and_no_admin_access(self):
        account,key,password=await self.register()
        self.feds[1].join(self.feds[0].invitation())
        await self.feds[1].sync_once()
        await self.feds[0].sync_once()
        await self.feds[1].sync_once()
        self.assertIn(account,self.portals[1].account_api.store.records)
        serialized=json.dumps(self.feds[1].snapshot())
        self.assertNotIn(password,serialized)
        self.assertNotIn('private notes',serialized)
        self.assertNotIn('PRIVATE KEY',serialized)
        first,_=await self.login(0,account,key)
        response=await self.clients[0].post('/api/profile',json={})
        portable=RelayProfile(**(await response.json())['profile'])
        async with await connect_directory(portable) as connection:
            topology=await request(connection,'topology')
        self.assertTrue(topology['nodes'])
        self.assertTrue(all(p['token'].startswith('acct1.') for p in topology['nodes']))
        self.assertNotIn(self.relays[1].token,json.dumps(topology))
        await probe(RelayProfile(**topology['nodes'][0]))
        # The original signed credential also works at another member without the home.
        await probe(RelayProfile(**dict(self.feds[1].profile,token=portable.token)))
        await self.relays[0].close()
        result,proof=await self.login(1,account,key)
        client=self.clients[1]
        self.assertEqual((await client.get('/api/admin')).status,401)
        self.assertEqual((await client.post('/api/account/login',json=proof)).status,400)
        response=await client.post('/api/profile',json={})
        profile=RelayProfile(**(await response.json())['profile'])
        self.assertTrue(profile.token.startswith('acct1.'))
        self.assertNotEqual(profile.token,self.relays[1].token)
        await probe(profile)
        self.portals[1].state['blocked_accounts']=[account]
        with self.assertRaises(asyncssh.PermissionDenied):
            await probe(profile)
        self.assertEqual((await client.get('/api/account/me')).status,401)

    async def test_email_required_registration_rejects_bypass_and_consumed_ticket(self):
        client = self.clients[0]
        portal = self.portals[0]
        portal.state['registration_open'] = True
        challenge = await (await client.post('/api/account/enroll', json={})).json()
        key = ec.generate_private_key(ec.SECP256R1())
        account = challenge['account']
        state = dict(account=account, revision=1, box=encrypted(key, secrets.token_urlsafe(24), account, 1))
        payload = dict(nonce=challenge['nonce'], username='verified_user', public_key=key_data(key),
                       state=state, signature=signed(key, canonical(state)), copies=0,
                       **routing(key, state, 0), proof=signed(key, challenge['message'].encode()))
        # Default-required mail must not silently become optional without SMTP.
        self.assertEqual((await client.post('/api/account/register', json=payload)).status, 400)
        self.assertIsNone(portal.account_api.store.replication.get(account))
        mail = portal.account_api.mail
        mail.configure(dict(username='sender@example.com', password='test-smtp-secret', required=True))
        self.assertEqual((await client.post('/api/account/register', json=payload)).status, 400)
        with patch.object(mail, '_send'), patch('tunnel.mail.secrets.randbelow', return_value=123456):
            response = await client.post('/api/account/email-code', json=dict(
                nonce=challenge['nonce'], username='verified_user', email='recipient@example.com'))
        self.assertEqual(response.status, 200)
        payload.update(email_ticket=(await response.json())['ticket'], email_code='123456')
        response = await client.post('/api/account/register', json=payload)
        self.assertEqual(response.status, 201, await response.text())
        self.assertEqual(portal.account_api.store.replication.get(account)['certificate']['username'], 'verified_user')
        self.assertEqual((await client.post('/api/account/register', json=payload)).status, 400)
        self.assertFalse(mail.pending)

    async def test_registration_toggle_does_not_disable_existing_accounts(self):
        self.assertEqual((await self.clients[0].post('/api/account/enroll',json={})).status,403)
        account,key,_=await self.register()
        self.portals[0].state['registration_open']=False
        await self.login(0,account,key)
        self.assertEqual((await self.clients[0].post('/api/account/enroll',json={})).status,403)
        self.assertEqual((await self.clients[0].get('/api/account/me')).status,200)

    async def test_friend_directory_publishes_names_without_vaults_and_rejects_anonymous(self):
        private_account, key, private_password = await self.register(copies=0)
        async with await connect_directory(RelayProfile(**self.feds[0].profile)) as connection:
            with self.assertRaisesRegex(ConnectionError, '匿名'):
                await request(connection, 'account_lookup', identifier='player_1')
        private = self.personal_profile(0, private_account, key)
        async with await connect_directory(private) as connection:
            by_name = await request(connection, 'account_lookup', identifier='PLAYER_1')
            by_id = await request(connection, 'account_lookup', identifier=private_account)
        self.assertEqual(by_name['accounts'], [{'account': private_account, 'username': 'player_1'}])
        self.assertEqual(by_id['accounts'][0]['account'], private_account)
        self.assertNotIn(private_password, json.dumps(by_name))

        public_account, _, public_password = await self.register(copies=1, username='player_2')
        self.feds[1].join(self.feds[0].invitation())
        await self.feds[1].sync_once()
        public = RelayProfile(**dict(self.feds[1].profile, token=private.token))
        async with await connect_directory(public) as connection:
            found = await request(connection, 'account_lookup', identifier='player_2')
        self.assertEqual({item['account'] for item in found['accounts']}, {public_account})
        self.assertNotIn(private_account, json.dumps(found))
        serialized = json.dumps(found)
        self.assertNotIn(public_password, serialized)
        self.assertNotIn('ciphertext', serialized)
        self.assertNotIn('public_key', serialized)

        self.assertEqual(await lookup_account(public, private_account),
                         [{'account': private_account, 'username': 'player_1'}])
        self.assertNotIn(private_account, self.portals[1].account_api.store.records)
        self.assertEqual(await lookup_account(public, 'PLAYER_2'), found['accounts'])
        async with await connect_directory(public) as connection:
            for invalid in ('', '*', 'player_', 'x' * 66, ['player_2']):
                if invalid == 'player_':
                    self.assertEqual((await request(connection, 'account_lookup', identifier=invalid))['accounts'], [])
                else:
                    with self.assertRaises(ConnectionError):
                        await request(connection, 'account_lookup', identifier=invalid)

    async def test_friend_lookup_fans_out_when_selected_node_gossip_is_stale(self):
        account, key, password = await self.register(copies=1, username='network_friend')
        self.feds[1].join(self.feds[0].invitation())
        await self.feds[1].sync_once()
        await self.feds[0].sync_once()
        # Keep federation membership live, but simulate a node that has not yet
        # received the latest public account route through its gossip snapshot.
        self.portals[1].account_api.store.replication.directory.pop(account, None)
        profile = self.personal_profile(1, account, key)
        found = await lookup_account(profile, 'NETWORK_FRIEND')
        self.assertEqual(found, [{'account': account, 'username': 'network_friend'}])
        self.assertNotIn(password, json.dumps(found))
        self.assertNotIn('ciphertext', json.dumps(found))

    async def test_friend_lookup_rejects_a_remote_identity_with_invalid_signature(self):
        account, key, _ = await self.register(copies=1, username='signed_friend')
        self.feds[1].join(self.feds[0].invitation())
        await self.feds[1].sync_once()
        await self.feds[0].sync_once()
        self.portals[1].account_api.store.replication.directory.pop(account, None)
        forged = copy.deepcopy(self.portals[0].account_api.store.replication.directory[account])
        forged['certificate']['username'] = 'forged_friend'
        self.portals[0].account_api.store.replication.directory[account] = forged
        self.assertEqual(await lookup_account(self.personal_profile(1, account, key), 'forged_friend'), [])

    async def test_friend_lookup_hides_blocked_accounts(self):
        first, key, _ = await self.register()
        self.feds[1].join(self.feds[0].invitation())
        await self.feds[1].sync_once()
        second, _, _ = await self.register(index=1, username='other_player')
        await self.feds[1].sync_once()
        await self.feds[0].sync_once()
        profile = self.personal_profile(0, first, key)
        matches = await lookup_account(profile, 'PLAYER_1')
        self.assertEqual({item['account'] for item in matches}, {first})
        self.assertEqual(await lookup_account(profile, second),
                         [{'account': second, 'username': 'other_player'}])
        self.portals[0].state['blocked_accounts'] = [second]
        self.assertEqual(await lookup_account(profile, second), [])
        self.assertEqual(await lookup_account(profile, 'player_1'),
                         [{'account': first, 'username': 'player_1'}])
        self.portals[0].state['blocked_accounts'] = []
        self.feds[0].blocked.add(self.feds[1].id)
        self.assertEqual(await lookup_account(profile, second), [])

    async def test_friend_lookup_preserves_public_name_after_backup_withdrawal(self):
        account, key, _ = await self.register()
        self.feds[1].join(self.feds[0].invitation())
        await self.feds[1].sync_once()
        remote = self.personal_profile(1, account, key)
        self.assertEqual(len(await lookup_account(remote, account)), 1)
        result, _ = await self.login(0, account, key)
        state = copy.deepcopy(self.portals[0].account_api.store.records[account]['state'])
        state['revision'] += 1
        response = await self.clients[0].post('/api/account/backup',
            headers={'X-Account-CSRF':result['csrf']},
            json=dict(state=state, signature=signed(key, canonical(state)), **routing(key, state, 0)))
        self.assertEqual(response.status, 200, await response.text())
        await self.feds[1].sync_once()
        self.assertEqual(self.portals[1].account_api.store.replication.directory[account]['routing']['copies'], 0)
        self.assertEqual(await lookup_account(remote, account), [{'account': account, 'username': 'player_1'}])
        self.assertNotIn(account, self.portals[1].account_api.store.records)
        self.assertEqual(len(await lookup_account(self.personal_profile(0, account, key), account)), 1)

    async def test_personal_credential_requires_user_proof_not_just_node_signature(self):
        account,key,_=await self.register()
        await self.login(0,account,key)
        store=self.portals[0].account_api.store
        valid=store.credential(account)
        self.assertEqual(store.authenticate(valid),account)
        claims=json.loads(decode(valid.split('.')[1]))
        claims['g']['o']='https://forged.example'
        payload=canonical(claims)
        forged='acct1.'+encode(payload)+'.'+encode(self.feds[0].key.sign(payload,b'ssh-ed25519'))
        self.assertIsNone(store.authenticate(forged))

    async def test_launcher_anonymous_upgrade_reloads_real_signed_friend_state(self):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from unittest.mock import Mock
        from PySide6.QtWidgets import QApplication, QDialog
        from ui.multiplayer_controller import MultiplayerController
        from hookup.social import operate
        app = QApplication.instance() or QApplication([])
        app.setQuitOnLastWindowClosed(False)
        alice, alice_key, _ = await self.register(copies=0, username='alice_upgrade')
        bob, bob_key, _ = await self.register(copies=0, username='bob_upgrade')
        personal = self.personal_profile(0, alice, alice_key)
        friend = self.personal_profile(0, bob, bob_key)
        await operate(personal, 'request', bob)
        requests = (await operate(friend, 'presence'))['requests']
        await operate(friend, 'accept', alice, ref=requests[0]['id'])
        jobs = []
        def schedule(key, coroutine):
            jobs.append((key, coroutine))
        window = QDialog()
        with patch('ui.multiplayer_controller.TunnelService', return_value=Mock(endpoints={})):
            controller = MultiplayerController(window, Path(self.temporary.name) / 'upgrade-ui/lobby.json')
        controller.friend_timer.stop()
        try:
            with patch.object(controller, 'job', side_effect=schedule):
                anonymous = await probe(RelayProfile(**self.feds[0].profile))
                controller.finish('nodecode:' + controller.generation, anonymous, None)
                saved = controller.node_path
                self.assertFalse(controller.view['socialReady'])
                controller.finish('nodecode:' + controller.generation, await probe(personal), None)
                self.assertTrue(controller.view['nodeUpdatePrompt'])
                controller.act('confirmNodeUpdate', {})
                self.assertEqual(controller.node_path, saved)
                social_job = next((key, coroutine) for key, coroutine in jobs if key.startswith('socialstatus:'))
                value = await social_job[1]
                controller.finish(social_job[0], value, None)
                self.assertTrue(controller.view['socialReady'])
                self.assertEqual(controller.view['socialName'], 'alice_upgrade')
                self.assertEqual(controller.view['contacts'][0]['name'], 'bob_upgrade')
                self.assertEqual(controller.store.data['nodes'], [saved])
                self.assertEqual(RelayProfile.load(saved).token, personal.token)
        finally:
            for _, coroutine in jobs:
                coroutine.close()
            controller.close()
            window.close()

    async def test_cross_node_friend_consent_presence_invitation_and_game_bytes(self):
        from hookup.social import operate, signed_action
        from hookup.relay import TunnelHost, TunnelClient, RoomInvite
        alice, alice_key, _ = await self.register(copies=0, username='alice')
        self.feds[1].join(self.feds[0].invitation())
        await self.feds[1].sync_once()
        await self.feds[0].sync_once()
        bob, bob_key, _ = await self.register(index=1, copies=0, username='bob')
        for _ in range(2):
            await self.feds[0].sync_once()
            await self.feds[1].sync_once()
        a = self.personal_profile(0, alice, alice_key)
        b = self.personal_profile(1, bob, bob_key, issuer=1)
        self.assertNotIn(alice, self.portals[1].account_api.store.records)
        self.assertNotIn(bob, self.portals[0].account_api.store.records)
        # No vault replica is needed for signed social operations.
        requested = await operate(a, 'request', bob)
        self.assertEqual(requested['friends'], [])
        self.assertEqual(requested['requests'][0]['account'], bob)
        await self.feds[1].sync_once()
        pending = await operate(b, 'presence')
        self.assertTrue(pending['requests'][0]['incoming'])
        accepted = await operate(b, 'accept', alice, ref=pending['requests'][0]['id'])
        self.assertEqual([f['account'] for f in accepted['friends']], [alice])
        await self.feds[0].sync_once()
        online = await operate(a, 'presence')
        self.assertTrue(online['friends'][0]['online'])
        social = self.portals[0].account_api.store.social
        digest = social.digest(presence=True)
        with patch('tunnel.social.time.time', return_value=time.time() + 31):
            self.assertFalse(social.state(alice)['friends'][0]['online'])
            self.assertEqual(social.presence, {})
            self.assertNotEqual(social.digest(presence=True), digest)
        # A peer cannot change the signed target or act as another account.
        forged = signed_action(a, 'remove', bob)
        forged['action']['target'] = alice
        async with await connect_directory(a) as connection:
            with self.assertRaises(ConnectionError):
                await request(connection, 'social', event=forged)
        async def echo(reader, writer):
            try:
                data = await reader.read(64)
                writer.write(b'world:' + data)
                await writer.drain()
            finally:
                writer.close()
        world = await asyncio.start_server(echo, '127.0.0.1', 0)
        host = TunnelHost(a, game_port=world.sockets[0].getsockname()[1], announce=False)
        tasks, endpoints = [], [host]
        async def ready(endpoint):
            tasks.append(asyncio.create_task(endpoint.run()))
            for _ in range(100):
                if endpoint.chat_process is not None:
                    return
                if tasks[-1].done():
                    await tasks[-1]
                await asyncio.sleep(.05)
            self.fail('Endpoint did not connect')
        try:
            await ready(host)
            await self.feds[0].sync_once()
            await self.feds[1].sync_once()
            await operate(a, 'invite', bob, room=host.invite.room_id)
            await self.feds[1].sync_once()
            invitation = (await operate(b, 'presence'))['invitations'][0]
            remote_social = self.portals[1].account_api.store.social
            with patch('tunnel.social.time.time', return_value=time.time() + 301):
                self.assertEqual(remote_social.state(bob)['invitations'], [])
                self.assertEqual(remote_social.invitations, {})
            # An expired invitation cannot be reused. A newly signed one works.
            with self.assertRaises(ConnectionError):
                await operate(b, 'join', alice, ref=invitation['id'])
            await operate(a, 'invite', bob, room=host.invite.room_id)
            await self.feds[1].sync_once()
            invitation = (await operate(b, 'presence'))['invitations'][0]
            joined = await operate(b, 'join', alice, ref=invitation['id'])
            client = TunnelClient(b, RoomInvite.decode(joined['invite']), listen_port=0, announce=False)
            endpoints.append(client)
            await ready(client)
            reader, writer = await asyncio.open_connection('127.0.0.1', client.listen_port)
            try:
                writer.write(b'friend')
                await writer.drain()
                self.assertEqual(await asyncio.wait_for(reader.readexactly(12), 5), b'world:friend')
            finally:
                writer.close()
                await writer.wait_closed()
            await operate(b, 'remove', alice)
            await self.feds[0].sync_once()
            self.assertEqual((await operate(a, 'presence'))['friends'], [])
            with self.assertRaises(ConnectionError):
                await operate(a, 'invite', bob, room=host.invite.room_id)
        finally:
            await asyncio.gather(*(p.stop() for p in endpoints), return_exceptions=True)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            world.close()
            await world.wait_closed()

    async def test_username_casefold_uniqueness_is_checked_at_connected_nodes(self):
        await self.register(username='Alice')
        self.feds[1].join(self.feds[0].invitation())
        await self.feds[1].sync_once()
        with self.assertRaises(ValueError):
            await self.feds[1].reserve_username('ALICE', secrets.token_hex(16) + '.' + self.feds[1].id)

    async def test_old_peer_cannot_replicate_without_signed_backup_consent(self):
        account, _, _ = await self.register(copies=0)
        record = copy.deepcopy(self.portals[0].account_api.store.records[account])
        record.pop('routing')
        record.pop('routing_signature')
        self.feds[1].join(self.feds[0].invitation())
        store = self.portals[1].account_api.store
        store.ingest([dict(record=record, proof=self.feds[0].proof(self.feds[0].id))])
        self.assertNotIn(account, store.records)
        self.assertNotIn(account, store.replication.directory)

    async def test_recovery_file_can_restore_after_home_unreachable(self):
        account,key,_=await self.register(copies=0)
        record=self.portals[0].account_api.store.records[account]
        response=await self.clients[1].post('/api/account/recover',json=dict(record=record))
        self.assertEqual(response.status,403)  # Untrusted home cannot bypass closed registration.
        self.feds[1].join(self.feds[0].invitation())
        await self.feds[1].sync_once()
        await self.relays[0].close()
        client=self.clients[1]
        response=await client.post('/api/account/recover',json=dict(record=record))
        self.assertEqual(response.status,200)
        challenge=await response.json()
        response=await client.post('/api/account/login',json=dict(nonce=challenge['nonce'],signature=signed(key,challenge['message'].encode())))
        self.assertEqual(response.status,200)
        result=await response.json()
        state=copy.deepcopy(record['state']);state['revision']=2
        response=await client.post('/api/account/backup',headers={'X-Account-CSRF':result['csrf']},
                    json=dict(state=state,signature=signed(key,canonical(state)),**routing(key,state,1)))
        self.assertEqual(response.status,200,await response.text())
        self.assertIn(account,self.portals[1].account_api.store.records)

    async def test_encrypted_settings_signed_updates_forgery_and_reload(self):
        account,key,password=await self.register()
        result,_=await self.login(0,account,key)
        client=self.clients[0];store=self.portals[0].account_api.store
        state=dict(account=account,revision=2,box=encrypted(key,password,account,2,'second secret'))
        body=dict(state=state,signature=signed(key,canonical(state)),**routing(key,state))
        self.assertEqual((await client.post('/api/account/backup',json=body)).status,403)
        response=await client.post('/api/account/backup',json=body,headers={'X-Account-CSRF':result['csrf']})
        self.assertEqual(response.status,200)
        old=copy.deepcopy(store.records[account])
        forged=copy.deepcopy(old);forged['state']['revision']=3
        with self.assertRaises(ValueError):
            store.ingest_one(forged)
        self.assertEqual(store.records[account],old)
        restored=Accounts(self.feds[0],store.path)
        self.assertEqual(restored.records[account],old)
        box=old['state']['box']
        wrong=hashlib.pbkdf2_hmac('sha256',b'wrong password',decode(box['salt']),600000)
        with self.assertRaises(InvalidTag):
            AESGCM(wrong).decrypt(decode(box['iv']),decode(box['ciphertext']),(account+'|2').encode())
        self.feds[1].join(self.feds[0].invitation());await self.feds[1].sync_once()
        self.assertEqual(self.portals[1].account_api.store.records[account],old)

    async def test_anonymous_federation_and_heartbeat_need_no_account(self):
        self.feds[1].join(self.feds[0].invitation());await self.feds[1].sync_once();await self.feds[0].sync_once()
        self.assertEqual(len(self.feds[0].live()),2)
        profile=RelayProfile(**self.feds[0].profile)
        await probe(profile)
        self.assertFalse(self.portals[0].account_api.store.records)
        remote=self.feds[1].id
        self.assertEqual(next(n for n in self.feds[0].health() if n['id']==remote)['status'],'online')
        self.feds[0].last_success[remote]-=TTL+1
        self.feds[0].seen[remote]-=TTL+1
        self.assertEqual(next(n for n in self.feds[0].health() if n['id']==remote)['status'],'suspect')
        self.feds[0].seen[remote]-=TTL*2
        self.assertEqual(next(n for n in self.feds[0].health() if n['id']==remote)['status'],'offline')

    async def test_replicas_from_other_network_rejected_and_leave_stops_discovery(self):
        account,_,_=await self.register()
        other=self.portals[1].account_api.store
        other.ingest(self.portals[0].account_api.store.snapshot())
        self.assertNotIn(account,other.records)
        self.feds[1].join(self.feds[0].invitation());await self.feds[1].sync_once()
        self.assertIn(account,other.records)
        self.feds[1].leave()
        self.assertFalse(self.feds[1].seeds)
        self.assertEqual(set(self.feds[1].live()),{self.feds[1].id})

    async def test_public_and_admin_status_hide_transport_addresses(self):
        self.feds[1].join(self.feds[0].invitation());await self.feds[1].sync_once()
        client=self.clients[1]
        for path in ('/api/status',):
            response=await client.get(path);text=await response.text()
            for secret in ('127.0.0.1',str(self.relays[0].port),self.relays[0].token):
                self.assertNotIn(secret,text)
        response=await client.post('/api/login',json=dict(username='admin',password=self.admin))
        self.assertEqual(response.status,200)
        response=await client.get('/api/admin');value=await response.json()
        self.assertNotIn('host',value['peers'][0])
        self.assertNotIn('port',value['peers'][0])

    async def test_signed_proxy_entrance_update_replaces_cached_origin(self):
        origin, follower = self.feds
        follower.join(origin.invitation())
        origin.publish()
        follower.ingest([origin.records[origin.id]])
        changes = []
        follower.on_change = lambda: changes.append(True)
        origin.profile = dict(origin.profile, server_host='protected.example', server_port=443)
        with patch('tunnel.federation.time.time', return_value=origin.records[origin.id]['body']['issued'] + 0.001):
            origin.publish()
        follower.ingest([origin.records[origin.id]])
        self.assertEqual(follower.seeds[origin.id], origin.profile)
        self.assertEqual(len(changes), 1)
        follower.ingest([origin.records[origin.id]])
        self.assertEqual(len(changes), 1)

    async def test_proxy_entrance_is_separate_from_listen_and_no_origin_in_profile(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('node_init',ROOT/'minecraft-tunnel/deploy/init_node.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        folder=Path(self.temporary.name)/'proxy'
        module.initialize(folder,'origin.example',3334,entry_host='protected.example',entry_port=443)
        value=json.loads((folder/'relay-profile.json').read_text())
        self.assertEqual(value['server_host'],'protected.example')
        self.assertEqual(value['server_port'],443)
        self.assertNotIn('origin.example',json.dumps(value))
        self.assertIn('port = 3334',(folder/'server.conf').read_text())


if __name__=='__main__':
    unittest.main(verbosity=2)
