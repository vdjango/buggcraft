"""Byte rates shared by the download history and room preparation views."""
from collections import deque
import threading
import time


class TransferMeter:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.files = {}
        self.lock = threading.Lock()

    def feed(self, event):
        with self.lock:
            now = self.clock()
            key = event.get('key') or event.get('path') or event['name']
            row = self.files.setdefault(key, dict(done=0, since=now, samples=deque(), state='pending'))
            state = event.get('state', 'downloading')
            done = max(0, event.get('done', row['done']))
            if state == 'downloading' and done > row['done']:
                row['samples'].append((now, done - row['done']))
            if state in ('pending', 'retrying') or done < row['done']:
                row['samples'].clear()
                row['since'] = now
            row.update(done=done, state=state)
            total = 0
            for current in self.files.values():
                while current['samples'] and now - current['samples'][0][0] > 2:
                    current['samples'].popleft()
                current['speed'] = (sum(size for _, size in current['samples']) /
                    max(.15, min(2, now - current['since']))) if current['state'] == 'downloading' else 0
                total += current['speed']
            return dict(event, speed=round(row['speed']), task_speed=round(total))


def speed_label(value):
    return f'{value / 1048576:.2f} MiB/s' if value >= 1048576 else f'{value / 1024:.1f} KiB/s'
