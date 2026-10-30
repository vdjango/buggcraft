"""The lobby should show the network type before local history finishes."""
import asyncio
import os
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/buggcraft'))

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from hookup.native_transport import TunnelService
from ui.multiplayer_controller import MultiplayerController


class NetworkProfileControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        controller = MultiplayerController.__new__(MultiplayerController)
        QObject.__init__(controller)
        controller.closed = False
        controller.jobs = set()
        controller.generation = 'network-profile-test'
        controller.service = TunnelService()
        controller._state = {'playerNetworkTypeReady': False, 'playerNetworkProfileReady': False}
        controller.player_network_profile = {
            'type': 'unknown', 'direct_successes': 0, 'relay_successes': 0}
        controller.player_network_profile_task = None
        controller.completed.connect(controller.finish)
        controller.network_type_detected.connect(controller.update_network_type)
        self.controller = controller

    def tearDown(self):
        self.controller.closed = True
        self.controller.service.close()
        self.controller.deleteLater()

    def wait_until(self, condition, seconds=2):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.app.processEvents()
            if condition():
                return
            time.sleep(0.01)
        self.fail('network profile did not reach the expected state')

    def test_network_type_appears_while_history_is_still_loading(self):
        release_history = threading.Event()

        async def collect(on_type=None):
            on_type('direct_easier')
            await asyncio.to_thread(release_history.wait)
            return {'type': 'direct_easier', 'direct_successes': 2, 'relay_successes': 1}

        try:
            with patch('utils.network_profile.collect_network_profile', new=collect):
                self.controller.refresh_network_profile()
                self.wait_until(lambda: self.controller._state['playerNetworkTypeReady'])
                self.assertFalse(self.controller._state['playerNetworkProfileReady'])
                self.assertEqual(self.controller._state['playerNetworkProfile']['type'], 'direct_easier')
                release_history.set()
                self.wait_until(lambda: self.controller._state['playerNetworkProfileReady'])
        finally:
            release_history.set()

        self.assertEqual(self.controller._state['playerNetworkProfile']['direct_successes'], 2)
        self.assertFalse(self.controller.player_network_profile_task)

    def test_history_error_keeps_the_detected_network_type(self):
        self.controller.player_network_profile_task = True
        self.controller.update_network_type(self.controller.generation, 'relay_likely')
        self.controller.finish('network-profile:' + self.controller.generation, None, 'history unavailable')

        self.assertEqual(self.controller._state['playerNetworkProfile']['type'], 'relay_likely')
        self.assertTrue(self.controller._state['playerNetworkProfileReady'])
        self.assertFalse(self.controller.player_network_profile_task)


if __name__ == '__main__':
    unittest.main()
