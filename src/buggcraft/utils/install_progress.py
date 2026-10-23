"""Adapt installer counters to percentages without mixing stage units."""
import threading


class InstallProgress:
    def __init__(self, emit):
        self.emit = emit
        self.maximum = 0
        self.lock = threading.RLock()

    def set_max(self, value):
        with self.lock:
            self.maximum = max(0, int(value))
            self.emit(0)

    def set_progress(self, value):
        with self.lock:
            self.emit(max(0, min(100, int(int(value) * 100 / self.maximum))) if self.maximum else 0)
