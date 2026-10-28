"""Acceptance of the real C++ bridge through the launcher's production adapter."""
import asyncio
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

import pytest

from hookup.native_library import library_path
from hookup.native_routes import BridgeError, NativeRoutes, executable


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
            else:
                with pytest.raises(RuntimeError):
                    original.exchange(b'{}')

            # Reopening must create a fresh, usable C++ runtime.
            await routes.ensure()
            assert (routes.library if mode == 'library' else routes.process) is not original
            assert (await routes.request('session.list', {}))['sessions'] == []
        finally:
            await routes.close()

    with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
            'BUGGCRAFT_BRIDGE_MODE': mode,
            'BUGGCRAFT_BRIDGE_LOG_DIR': temporary}):
        asyncio.run(asyncio.wait_for(exercise(), timeout=30))
