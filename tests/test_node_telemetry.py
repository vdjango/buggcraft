"""Launcher latency/path reports reach the real room node without payloads."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from tests import test_room_chat as fixtures
from tests import test_game_status as game_fixture
from tunnel.diagnostics import Diagnostics
from hookup.relay import TunnelHost,TunnelClient


class NodeTelemetryTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.RoomChatTests.asyncSetUp
    asyncTearDown=fixtures.RoomChatTests.asyncTearDown
    endpoint=fixtures.RoomChatTests.endpoint
    wait=fixtures.RoomChatTests.wait
    server=game_fixture.GameStatusTests.server

    async def test_real_game_pong_and_control_roundtrip_are_reported_by_current_session(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        diag=Diagnostics(Path(directory.name)/'players',self.relay);self.relay.diagnostics=diag
        port=await self.server(pong_delay=.025)
        host=await self.endpoint(TunnelHost,game_port=port,game_chat_enabled=False,transport_policy='relay')
        client=await self.endpoint(TunnelClient,host.invite,transport_policy='relay')
        await self.wait(lambda:any(row['event']=='client_report' and row.get('game_rtt_ms') is not None
                                   for _,_,row in diag.queue),timeout=10)
        report=next(row for _,_,row in diag.queue if row['event']=='client_report' and row.get('game_rtt_ms') is not None)
        self.assertEqual(report['path'],'relay');self.assertEqual(report['source'],'launcher_report')
        self.assertGreaterEqual(report['game_rtt_ms'],20);self.assertGreater(report['control_rtt_ms'],0)
        self.assertNotIn('token',report);self.assertNotIn('password',report)
        self.assertFalse(client._stopped);self.assertFalse(host._stopped)
        # Also exercise forwarding after telemetry, rather than only asserting a callback.
        await client.send_chat('telemetry does not interrupt the room')
        await self.wait(lambda:any(e.get('text')=='telemetry does not interrupt the room' for e in self.events[host]))
