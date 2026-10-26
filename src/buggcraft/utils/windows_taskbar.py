"""Give hosted source launches the same taskbar identity as the launcher."""
import ctypes
import logging
import os
from pathlib import Path
import subprocess
import sys
import uuid

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QGuiApplication, QPlatformSurfaceEvent

logger = logging.getLogger(__name__)
APP_ID = 'bugg.icu'


def _set_properties(hwnd, values):
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [('data1', wintypes.DWORD), ('data2', wintypes.WORD),
                    ('data3', wintypes.WORD), ('data4', ctypes.c_byte * 8)]

    class PropertyKey(ctypes.Structure):
        _fields_ = [('fmtid', GUID), ('pid', wintypes.DWORD)]

    class Value(ctypes.Union):
        _fields_ = [('pointer', ctypes.c_void_p),
                    ('padding', ctypes.c_byte * (16 if ctypes.sizeof(ctypes.c_void_p) == 8 else 8))]

    class PropVariant(ctypes.Structure):
        _fields_ = [('vt', wintypes.WORD), ('reserved', wintypes.WORD * 3), ('value', Value)]

    shell = ctypes.WinDLL('shell32')
    shell.SHGetPropertyStoreForWindow.argtypes = [wintypes.HWND, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
    shell.SHGetPropertyStoreForWindow.restype = ctypes.c_long

    def check(result):
        if result < 0:
            raise OSError('Windows taskbar property error: 0x%08x' % (result & 0xffffffff))

    iid = GUID.from_buffer_copy(uuid.UUID('886d8eeb-8cf2-4446-8d02-cdba1dbdcf99').bytes_le)
    fmtid = GUID.from_buffer_copy(uuid.UUID('9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3').bytes_le)
    store = ctypes.c_void_p()
    check(shell.SHGetPropertyStoreForWindow(hwnd, ctypes.byref(iid), ctypes.byref(store)))
    vtable = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    release = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(vtable[2])
    set_value = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p,
                                  ctypes.POINTER(PropertyKey), ctypes.POINTER(PropVariant))(vtable[6])
    try:
        for pid, text in values:
            key = PropertyKey(fmtid, pid)
            value = PropVariant()
            if text is not None:
                # SetValue copies the string; Python owns this temporary buffer.
                buffer = ctypes.create_unicode_buffer(text)
                value.vt = 31  # VT_LPWSTR
                value.value.pointer = ctypes.cast(buffer, ctypes.c_void_p).value
            check(set_value(store, ctypes.byref(key), ctypes.byref(value)))
    finally:
        release(store)


class _TaskbarIdentity(QObject):
    def __init__(self, window, resource_path):
        super().__init__(window)
        self.hwnd = None
        icon = Path(resource_path).resolve() / 'icons' / 'app.ico'
        if getattr(sys, 'frozen', False) or '__compiled__' in globals():
            executable = sys.argv[0] if '__compiled__' in globals() else sys.executable
            command = subprocess.list2cmdline([str(Path(executable).resolve())])
        else:
            command = subprocess.list2cmdline([sys.executable, str(Path(__file__).resolve().parents[1] / 'main.py')])
        # Windows refreshes the group when ID is set, so publish it last.
        self.values = [(2, command), (3, str(icon) + ',0'), (4, 'BUGG启动器'), (5, APP_ID)]
        window.installEventFilter(self)

    def eventFilter(self, window, event):
        try:
            if event.type() == QEvent.Show and self.hwnd is None:
                self.hwnd = int(window.winId())
                _set_properties(self.hwnd, self.values)
            elif (event.type() == QEvent.PlatformSurface and
                  event.surfaceEventType() == QPlatformSurfaceEvent.SurfaceAboutToBeDestroyed and self.hwnd):
                # Release strings while the native HWND still exists.
                _set_properties(self.hwnd, [(pid, None) for pid, _ in reversed(self.values)])
                self.hwnd = None
        except (OSError, AttributeError):
            logger.warning('Could not update Windows taskbar identity', exc_info=True)
        return False


def install_taskbar_identity(window, resource_path):
    if os.name == 'nt' and QGuiApplication.platformName() == 'windows':
        window._taskbar_identity = _TaskbarIdentity(window, resource_path)
