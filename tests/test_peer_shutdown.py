"""Room teardown cannot hang on a Windows TCP close or a disconnected peer."""
import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/buggcraft'))
from hookup.peer import close_stream_writer


class PeerShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_stalled_socket_is_aborted_and_close_task_reaped(self):
        writer = Mock()
        finished = asyncio.Event()
        async def wait_closed():
            try:
                await asyncio.Event().wait()
            finally:
                finished.set()
        writer.wait_closed = wait_closed
        await asyncio.wait_for(close_stream_writer(writer, grace=.01), 1)
        writer.close.assert_called_once()
        writer.transport.abort.assert_called()
        self.assertTrue(finished.is_set())

    async def test_drained_socket_closes_without_abort(self):
        writer = Mock()
        async def wait_closed():
            await asyncio.sleep(0)
        writer.wait_closed = wait_closed
        await close_stream_writer(writer)
        writer.close.assert_called_once()
        writer.transport.abort.assert_not_called()

    async def test_stalled_ssh_writer_aborts_its_channel_without_tcp_transport(self):
        finished = asyncio.Event()
        async def wait_closed():
            try:
                await asyncio.Event().wait()
            finally:
                finished.set()
        writer = SimpleNamespace(close=Mock(), channel=Mock(), wait_closed=wait_closed)
        await asyncio.wait_for(close_stream_writer(writer, grace=.01), 1)
        writer.close.assert_called_once()
        writer.channel.abort.assert_called_once()
        self.assertTrue(finished.is_set())

    async def test_connection_reset_is_an_already_closed_stream(self):
        writer = Mock()
        async def wait_closed():
            raise ConnectionResetError('Peer left')
        writer.wait_closed = wait_closed
        await close_stream_writer(writer)
        writer.close.assert_called_once()

    async def test_cancellation_aborts_pending_socket_and_propagates(self):
        writer = Mock()
        ready, finished = asyncio.Event(), asyncio.Event()
        async def wait_closed():
            ready.set()
            try:
                await asyncio.Event().wait()
            finally:
                finished.set()
        writer.wait_closed = wait_closed
        task = asyncio.create_task(close_stream_writer(writer))
        await ready.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        writer.transport.abort.assert_called_once()
        self.assertTrue(finished.is_set())


if __name__ == '__main__':
    unittest.main()
