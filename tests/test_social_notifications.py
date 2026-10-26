"""Notification priority, read markers, original audio assets and sound pacing."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/buggcraft'))
from ui.social_notifications import SocialNotifications
from utils.social_sound import SocialSound


class SocialNotificationTests(unittest.TestCase):
    def test_priority_badges_and_reading_only_the_open_tab(self):
        notices = SocialNotifications()
        state = dict(friendRequests=[dict(id='request', incoming=True), dict(id='outbound', incoming=False)],
                     friendInvitations=[dict(id='invite')],
                     joinRequests=[dict(id='join', incoming=True), dict(id='mine', incoming=False)])
        self.assertEqual(notices.update(state), 'invite')
        self.assertEqual(notices.update(state), '')
        self.assertEqual(notices.view(state)['total'], 3)
        self.assertTrue(notices.view(state)['urgent'])
        notices.acknowledge_home(state)
        self.assertFalse(notices.view(state)['homeAttention'])
        self.assertEqual(notices.view(state)['invitations'], 1)
        self.assertTrue(notices.mark_read(state, 'invitations'))
        self.assertFalse(notices.mark_read(state, 'invitations'))
        self.assertEqual(notices.view(state)['invitations'], 0)
        self.assertTrue(notices.view(state)['urgent'])
        notices.mark_read(state, 'joinRequests')
        self.assertFalse(notices.view(state)['urgent'])
        self.assertEqual(notices.view(state)['requests'], 1)
        state['friendInvitations'].append(dict(id='new'))
        self.assertEqual(notices.update(state), 'invite')
        self.assertTrue(notices.view(state)['homeAttention'])

    def test_disappeared_and_repolled_notifications_do_not_chime_again(self):
        notices = SocialNotifications()
        state = dict(friendRequests=[dict(id='one', incoming=True)])
        self.assertEqual(notices.update(state), 'request')
        notices.update({})
        self.assertEqual(notices.view({})['total'], 0)
        self.assertEqual(notices.update(state), '')
        state['friendRequests'].append(dict(id='two', incoming=True))
        self.assertEqual(notices.update(state), 'request')

    def test_generated_audio_assets_are_short_distinct_pcm_chimes(self):
        assets = []
        for filename in ('friend-request.wav', 'social-invite.wav'):
            with wave.open(str(ROOT / 'resources/sounds' / filename)) as audio:
                self.assertEqual((audio.getnchannels(), audio.getsampwidth()), (1, 2))
                self.assertGreater(audio.getnframes() / audio.getframerate(), .1)
                self.assertLess(audio.getnframes() / audio.getframerate(), 1.5)
                assets.append(audio.readframes(audio.getnframes()))
        self.assertNotEqual(*assets)

    def test_sound_coalesces_bursts_but_urgent_overrides_low_priority(self):
        sound = SocialSound(ROOT / 'resources')
        playback = Mock(SND_FILENAME=1, SND_ASYNC=2, SND_NODEFAULT=4)
        with patch('utils.social_sound.sys.platform', 'win32'), patch.dict(sys.modules, winsound=playback), \
                patch('utils.social_sound.time.monotonic', side_effect=[0, .1, .2, .3, 3]):
            self.assertTrue(sound.play('request'))
            self.assertFalse(sound.play('request'))
            self.assertTrue(sound.play('invite'))
            self.assertFalse(sound.play('invite'))
            self.assertTrue(sound.play('invite'))
        self.assertEqual(playback.PlaySound.call_count, 3)


if __name__ == '__main__':
    unittest.main()
