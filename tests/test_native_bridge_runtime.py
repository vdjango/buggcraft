"""Acceptance of the real C++ bridge through the launcher's production adapter."""
import asyncio
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

import pytest

from hookup.native_library import library_path
from hookup.native_routes import BridgeError, NativeRoutes, executable


def test_cancelling_bridge_start_reaps_the_child_and_allows_restart():
    component = executable()
    if component is None or not Path(component).is_file():
        pytest.skip('Build or configure the native bridge executable first')

    async def exercise():
        routes = NativeRoutes(force_process=True)
        created, release = asyncio.Event(), asyncio.Event()
        children = []
        real_spawn = asyncio.create_subprocess_exec

        async def delayed_spawn(*args, **kwargs):
            child = await real_spawn(*args, **kwargs)
            children.append(child)
            created.set()
            await release.wait()
            return child

        try:
            with patch('hookup.native_routes.asyncio.create_subprocess_exec', delayed_spawn):
                starting = asyncio.create_task(routes.ensure())
                await asyncio.wait_for(created.wait(), 10)
                starting.cancel()
                release.set()
                with pytest.raises(asyncio.CancelledError):
                    await starting
            child = children[0]
            assert child.returncode == 0, 'Cancelling startup must reap the already-created child'
            assert child.stdin.is_closing()
            assert child.stdout.at_eof() and child.stderr.at_eof()
            await routes.ensure()
            assert (await routes.request('session.list', {}))['sessions'] == []
        finally:
            release.set()
            await routes.close()
            for child in children:
                if child.returncode is None:
                    child.kill()
                    await child.communicate()

    asyncio.run(asyncio.wait_for(exercise(), timeout=30))


@pytest.mark.parametrize('mode', ['library', 'process'])
def test_real_cpp_bridge_methods_errors_shutdown_and_restart(mode):
    component = library_path() if mode == 'library' else executable()
    configured = os.environ.get('BUGGCRAFT_BRIDGE_LIBRARY' if mode == 'library'
                                else 'BUGGCRAFT_BRIDGE_EXECUTABLE')
    if configured:
        assert component is not None and Path(component).is_file(), f'Missing configured native component: {component}'
    if component is None or not Path(component).is_file():
        pytest.skip(f'Build or configure the native bridge {mode} component first')

    async def exercise():
        routes = NativeRoutes()
        try:
            await routes.ensure()
            original = routes.library if mode == 'library' else routes.process
            assert original is not None
            info = await routes.request('bridge.initialize', {'protocol': 1})
            assert info['build']['implementation'] == 'cpp'
            assert {'room.host', 'room.join', 'social.operate', 'game.discover',
                    'mods.fetch', 'session.events'} <= set(info['methods'])
            assert (await routes.request('session.list', {}))['sessions'] == []

            # A complete native error must not destroy other room sessions.
            with pytest.raises(BridgeError) as failure:
                await routes.request('invalid.acceptance_method', {})
            assert failure.value.code == -32601
            assert (routes.library if mode == 'library' else routes.process) is original
            replies = await asyncio.gather(*(
                routes.request('session.list', {}) for _ in range(12)))
            assert all(reply['sessions'] == [] for reply in replies)

            await routes.close()
            await routes.close()
            assert routes.library is None and routes.process is None
            if mode == 'process':
                assert original.returncode == 0
                assert original.stdout.at_eof()
                assert original.stderr.at_eof()
                assert original._transport.is_closing()
            else:
                with pytest.raises(RuntimeError):
                    original.exchange(b'{}')

            # Reopening must create a fresh, usable C++ runtime.
            await routes.ensure()
            assert (routes.library if mode == 'library' else routes.process) is not original
            assert (await routes.request('session.list', {}))['sessions'] == []
            if mode == 'process':
                restarted = routes.process
                restarted.terminate()
                await restarted.wait()
                # An already-exited child still owns pipe resources. This is
                # distinct from asking a running bridge to exit normally.
                await routes.close()
                assert restarted.stdin.is_closing()
                assert restarted.stdout.at_eof()
                assert restarted.stderr.at_eof()
                assert restarted._transport.is_closing()
        finally:
            await routes.close()

    with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
            'BUGGCRAFT_BRIDGE_MODE': mode,
            'BUGGCRAFT_BRIDGE_LOG_DIR': temporary}):
        asyncio.run(asyncio.wait_for(exercise(), timeout=30))
