"""Opt-in real Open to LAN UI regression; never stops the user's game."""
import os
import unittest
import test_game_chat_ui as fixture


@unittest.skipUnless(os.environ.get('BUGGCRAFT_LAN_TEST_PORT'), 'Set BUGGCRAFT_LAN_TEST_PORT to an open test world')
class IntegratedLanChatTests(fixture.GameChatUiTests):
    integrated_port = int(os.environ.get('BUGGCRAFT_LAN_TEST_PORT') or 0)
    console_artifact = 'chat-integrated-ui-console.log'
    result_artifact = 'chat-integrated-ui-result.json'


if __name__ == '__main__':
    unittest.main(verbosity=2)
