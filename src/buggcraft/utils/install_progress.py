"""Adapt installer counters to percentages without mixing stage units."""
import threading


class InstallProgress:
    def __init__(self, emit):
        self.emit = emit
        self.maximum = 0
        self.last_percentage = None
        self.lock = threading.RLock()

    def _report(self, percentage):
        if percentage != self.last_percentage:
            self.last_percentage = percentage
            self.emit(percentage)

    def set_max(self, value):
        with self.lock:
            self.maximum = max(0, int(value))
            self._report(0)

    def set_progress(self, value):
        with self.lock:
            self._report(max(0, min(100, int(int(value) * 100 / self.maximum))) if self.maximum else 0)
