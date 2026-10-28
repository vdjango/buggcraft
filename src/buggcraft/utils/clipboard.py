"""Copy through Qt, allowing a briefly busy system clipboard to recover."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication


def cancel_copy(owner):
    previous = getattr(owner, '_clipboard_copy_timer', None)
    if previous is not None:
        previous.stop()
        previous.deleteLater()
        owner._clipboard_copy_timer = None


def copy_text(owner, text, succeeded, failed):
    cancel_copy(owner)
    timer = QTimer(owner)
    timer.setInterval(25)
    owner._clipboard_copy_timer = timer
    remaining = 20

    def attempt():
        nonlocal remaining
        remaining -= 1
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        success = clipboard.text() == text
        if success or remaining == 0:
            timer.stop()
            timer.deleteLater()
            owner._clipboard_copy_timer = None
            (succeeded if success else failed)()
        elif not timer.isActive():
            timer.start()

    timer.timeout.connect(attempt)
    attempt()
