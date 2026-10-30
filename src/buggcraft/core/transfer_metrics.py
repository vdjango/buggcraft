"""Byte rates shared by the download history and room preparation views."""
from collections import deque
import threading
import time


class ProgressGate:
    """Limit routine UI updates without delaying phase changes or completion."""

    def __init__(self, interval=.1, clock=time.monotonic):
        self.interval = interval
        self.clock = clock
        self.lock = threading.Lock()
        self.last = {}

    def allow(self, key, *, force=False):
        now = self.clock()
        with self.lock:
            if force or now - self.last.get(key, float('-inf')) >= self.interval:
                self.last[key] = now
                return True
            return False


class EventBatcher:
    """Keep ordered worker events while reducing cross-thread UI notifications."""

    def __init__(self, emit, interval=.1, limit=64, clock=time.monotonic):
        self.emit = emit
        self.interval = interval
        self.limit = limit
        self.clock = clock
        self.lock = threading.Lock()
        self.pending = []
        self.last = 0.0
        self.timer = None

    def add(self, event):
        with self.lock:
            self.pending.append(event)
            now = self.clock()
            if len(self.pending) >= self.limit or now - self.last >= self.interval:
                batch, self.pending = self.pending, []
                self.last = now
                if self.timer is not None:
                    self.timer.cancel()
                    self.timer = None
                # Serialize signal delivery too: concurrent producers must not
                # deliver a completed file before its earlier progress batch.
                self.emit(batch)
            elif self.timer is None:
                self.timer = threading.Timer(self.interval, self.flush)
                self.timer.daemon = True
                self.timer.start()

    def flush(self):
        with self.lock:
            if self.timer is not None:
                self.timer.cancel()
                self.timer = None
            batch, self.pending = self.pending, []
            self.last = self.clock()
            if batch:
                self.emit(batch)


class TransferMeter:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.files = {}
        self.lock = threading.Lock()
        self.samples = deque()
        self.sample_bytes = 0
        self.since = None

    def feed(self, event):
        with self.lock:
            now = self.clock()
            key = event.get('key') or event.get('path') or event['name']
            row = self.files.setdefault(key, dict(done=0, since=now, samples=deque(),
                                                   sample_bytes=0, state='pending'))
            state = event.get('state', 'downloading')
            done = max(0, event.get('done', row['done']))
            if state == 'downloading' and row['state'] != 'downloading':
                # The first event carries the resumed offset, not new bytes.
                row['samples'].clear()
                row['sample_bytes'] = 0
                row['since'] = now
                if self.since is None:
                    self.since = now
            elif row['state'] == 'downloading' and state in ('downloading', 'verifying', 'verified') and done > row['done']:
                delta = done - row['done']
                row['samples'].append((now, delta))
                row['sample_bytes'] += delta
                self.samples.append((now, delta))
                self.sample_bytes += delta
            if state in ('pending', 'retrying') or done < row['done']:
                row['samples'].clear()
                row['sample_bytes'] = 0
                row['since'] = now
            row.update(done=done, state=state)
            while row['samples'] and now - row['samples'][0][0] > 2:
                row['sample_bytes'] -= row['samples'].popleft()[1]
            row['speed'] = (row['sample_bytes'] / max(.15, min(2, now - row['since']))) if state == 'downloading' else 0
            if state != 'downloading':
                row['samples'].clear()
                row['sample_bytes'] = 0
            while self.samples and now - self.samples[0][0] > 2:
                self.sample_bytes -= self.samples.popleft()[1]
            # Quick, completed files still contributed network bytes. Retain
            # them in the task's short rate window so the UI refresh sees them.
            total = self.sample_bytes / max(.15, min(2, now - (self.since if self.since is not None else now)))
            return dict(event, speed=round(row['speed']), task_speed=round(total))


def speed_label(value):
    return f'{value / 1048576:.2f} MiB/s' if value >= 1048576 else f'{value / 1024:.1f} KiB/s'
