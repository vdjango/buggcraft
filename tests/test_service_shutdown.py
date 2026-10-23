"""Closing the launcher's real background service releases node membership."""
import asyncio
import unittest

from . import test_room_chat as fixture
from hookup.relay import TunnelClient, TunnelHost, TunnelService


class ServiceShutdownTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.RoomChatTests.asyncSetUp
    asyncTearDown = fixture.RoomChatTests.asyncTearDown
    wait = fixture.RoomChatTests.wait

    async def service_endpoint(self, service, kind, invite=None):
        endpoint = kind(self.profile, invite, listen_port=0,
                        game_port=0 if kind is TunnelHost else 25565, announce=False)
        service.add(kind.__name__, endpoint)
        # The native endpoint exposes a session handle, not a Python SSH channel.
        await self.wait(lambda: endpoint.session is not None and endpoint.connection is not None, 15)
        return endpoint

    async def test_client_launcher_close_releases_member_and_keeps_host_room(self):
        host_service, client_service = TunnelService(), TunnelService()
        try:
            host = await self.service_endpoint(host_service, TunnelHost)
            await self.service_endpoint(client_service, TunnelClient, host.invite)
            await self.wait(lambda: self.relay.capacity.members(host.invite.room_id) == 2)
            await asyncio.to_thread(client_service.close)
            await self.wait(lambda: self.relay.capacity.members(host.invite.room_id) == 1)
            self.assertIn(host.invite.room_id, self.relay.rooms)
            self.assertFalse(client_service.thread.is_alive())
            self.assertTrue(client_service.loop.is_closed())
            await asyncio.to_thread(client_service.close)  # aboutToQuit can run after closeEvent.
        finally:
            await asyncio.to_thread(client_service.close)
            await asyncio.to_thread(host_service.close)

    async def test_host_launcher_close_ends_room_and_stops_visitor_retry(self):
        host_service, client_service = TunnelService(), TunnelService()
        try:
            host = await self.service_endpoint(host_service, TunnelHost)
            visitor = await self.service_endpoint(client_service, TunnelClient, host.invite)
            await asyncio.to_thread(host_service.close)
            await self.wait(lambda: host.invite.room_id not in self.relay.rooms
                            and visitor.connection is None and visitor.room_state == 'closed')
            self.assertFalse(host_service.thread.is_alive())
            self.assertTrue(host_service.loop.is_closed())
            self.assertEqual(visitor.room_state, 'closed')
        finally:
            await asyncio.to_thread(client_service.close)
            await asyncio.to_thread(host_service.close)

    async def test_closed_service_rejects_new_work(self):
        service = TunnelService()
        await asyncio.to_thread(service.close)
        with self.assertRaises(RuntimeError):
            service.add('new', TunnelHost(self.profile))
        with self.assertRaises(RuntimeError):
            service.submit(asyncio.sleep(0))

    async def test_quit_during_pending_leave_still_closes_the_host_room(self):
        service = TunnelService()
        try:
            host = await self.service_endpoint(service, TunnelHost)
            leaving = service.remove('TunnelHost')
            await asyncio.to_thread(service.close)
            await self.wait(lambda: host.invite.room_id not in self.relay.rooms)
            self.assertTrue(leaving.done())
            self.assertFalse(service.thread.is_alive())
        finally:
            await asyncio.to_thread(service.close)
