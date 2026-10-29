"""Four unmodified Minecraft GUI clients, exercised by a pytest test case.

This intentionally opens four visible game windows, creates only a fresh world
and uses a local production C++ node or the authorized remote test server. It never uses
the launcher's removed Python transport. Reports include screenshots, game logs,
block/chat synchronization, death/respawn and a real client reconnect.
"""
import asyncio
import importlib.util
import os
from pathlib import Path

import pytest


@pytest.mark.skipif(os.environ.get('BUGGCRAFT_FOUR_GAME_LIVE') != '1',
                    reason='Set BUGGCRAFT_FOUR_GAME_LIVE=1 to open four actual Minecraft windows')
def test_four_real_minecraft_clients_move_build_chat_respawn_and_reconnect():
    native = Path(os.environ.get('BUGGCRAFT_NATIVE_SOURCE',
                                Path(__file__).resolve().parents[2] / 'minecraft-tunnel-native'))
    helper = native / 'scripts/vanilla_multiplayer.py'
    assert helper.is_file(), f'Missing native GUI acceptance fixture: {helper}'
    spec = importlib.util.spec_from_file_location('four_game_fixture', helper)
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    print('FOUR_GAME_ARTIFACT', fixture.ARTIFACTS, flush=True)
    report = asyncio.run(fixture.main())
    assert report['passed'] is True, report.get('failure')
    assert len(report['clients']) == 4
    assert report['operations']['passed']
    assert report['cross_client_chat_sync'] is True
    assert len(report['death_respawn']) == 3
    assert report['real_client_rejoin'] is True
    assert report['preparation_room']['online'] == 4
    assert report['preparation_room']['world_waiting'] is True
    assert report['management_transfer_kept_game_connected'] is True
