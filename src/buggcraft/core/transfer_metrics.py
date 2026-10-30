"""Byte rates shared by the download history and room preparation views."""
from collections import deque
import threading
import time


class TransferMeter:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.files = {}
        self.lock = threading.Lock()
        self.samples = deque()
        self.since = None

    def feed(self, event):
        with self.lock:
            now = self.clock()
            key = event.get('key') or event.get('path') or event['name']
            row = self.files.setdefault(key, dict(done=0, since=now, samples=deque(), state='pending'))
            state = event.get('state', 'downloading')
            done = max(0, event.get('done', row['done']))
            if state == 'downloading' and row['state'] != 'downloading':
                # The first event carries the resumed offset, not new bytes.
                row['samples'].clear()
                row['since'] = now
                if self.since is None:
                    self.since = now
            elif row['state'] == 'downloading' and state in ('downloading', 'verifying', 'verified') and done > row['done']:
                delta = done - row['done']
                row['samples'].append((now, delta))
                self.samples.append((now, delta))
            if state in ('pending', 'retrying') or done < row['done']:
                row['samples'].clear()
                row['since'] = now
            row.update(done=done, state=state)
            for current in self.files.values():
                while current['samples'] and now - current['samples'][0][0] > 2:
                    current['samples'].popleft()
                current['speed'] = (sum(size for _, size in current['samples']) /
                    max(.15, min(2, now - current['since']))) if current['state'] == 'downloading' else 0
            while self.samples and now - self.samples[0][0] > 2:
                self.samples.popleft()
            # Quick, completed files still contributed network bytes. Retain
            # them in the task's short rate window so the UI refresh sees them.
            total = sum(size for _, size in self.samples) / max(.15, min(2, now - (self.since if self.since is not None else now)))
            return dict(event, speed=round(row['speed']), task_speed=round(total))


def speed_label(value):
    return f'{value / 1048576:.2f} MiB/s' if value >= 1048576 else f'{value / 1024:.1f} KiB/s'
