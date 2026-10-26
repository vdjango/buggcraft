"""Play BUGG's original synthesized chimes without blocking the UI."""
import sys
import time
from pathlib import Path


class SocialSound:
    def __init__(self, resources):
        self.resources = Path(resources)
        self.last_at = float('-inf')
        self.last_priority = ''
        self.effects = {}

    def play(self, priority):
        now = time.monotonic()
        if now - self.last_at < 2 and not (priority == 'invite' and self.last_priority != 'invite'):
            return False
        path = self.resources / 'sounds' / ('social-invite.wav' if priority == 'invite' else 'friend-request.wav')
        if not path.is_file():
            return False
        try:
            if sys.platform == 'win32':
                import winsound
                winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            else:
                from PySide6.QtCore import QUrl
                from PySide6.QtMultimedia import QSoundEffect
                if priority not in self.effects:
                    effect = QSoundEffect()
                    effect.setSource(QUrl.fromLocalFile(str(path)))
                    effect.setVolume(0.45)
                    self.effects[priority] = effect
                self.effects[priority].play()
        except (ImportError, OSError, RuntimeError):
            return False
        self.last_at, self.last_priority = now, priority
        return True
