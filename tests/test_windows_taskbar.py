"""Exercise the real Windows property store, including Unicode and cleanup."""
import ctypes
import os
from pathlib import Path
import struct
import sys
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'buggcraft'))


@unittest.skipUnless(os.name == 'nt', 'Windows taskbar integration')
class WindowsTaskbarTests(unittest.TestCase):
    def test_taskbar_relaunch_properties_round_trip_and_release(self):
        from ctypes import wintypes
        from utils.windows_taskbar import _set_properties

        ole = ctypes.WinDLL('ole32')
        initialized = ole.CoInitializeEx(None, 2)
        if initialized >= 0:
            self.addCleanup(ole.CoUninitialize)
        user = ctypes.WinDLL('user32')
        user.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
        user.CreateWindowExW.restype = wintypes.HWND
        user.DestroyWindow.argtypes = [wintypes.HWND]
        hwnd = user.CreateWindowExW(0, 'STATIC', 'Taskbar integration', 0, 0, 0, 1, 1, None, None, None, None)
        self.assertTrue(hwnd)
        self.addCleanup(user.DestroyWindow, hwnd)

        shell = ctypes.WinDLL('shell32')
        shell.SHGetPropertyStoreForWindow.argtypes = [wintypes.HWND, ctypes.c_void_p, ctypes.c_void_p]
        shell.SHGetPropertyStoreForWindow.restype = ctypes.c_long
        iid = ctypes.create_string_buffer(uuid.UUID('886d8eeb-8cf2-4446-8d02-cdba1dbdcf99').bytes_le)
        store = ctypes.c_void_p()
        self.assertEqual(shell.SHGetPropertyStoreForWindow(hwnd, iid, ctypes.byref(store)), 0)
        table = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        release = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(table[2])
        self.addCleanup(release, store)
        read = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(table[5])
        ole.PropVariantClear.argtypes = [ctypes.c_void_p]

        def get(pid):
            key = ctypes.create_string_buffer(uuid.UUID('9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3').bytes_le + struct.pack('<I', pid))
            value = ctypes.create_string_buffer(24 if ctypes.sizeof(ctypes.c_void_p) == 8 else 16)
            self.assertEqual(read(store, key, value), 0)
            try:
                kind = ctypes.c_ushort.from_buffer(value).value
                if kind == 0:
                    return None
                self.assertEqual(kind, 31)  # VT_LPWSTR
                return ctypes.wstring_at(ctypes.c_void_p.from_buffer(value, 8).value)
            finally:
                ole.PropVariantClear(value)

        values = [(2, '"C:\\Program Files\\BUGG\\启动器.exe"'),
                  (3, str(Path(__file__).resolve().parents[1] / 'resources/icons/app.ico') + ',0'),
                  (4, 'BUGG启动器'), (5, 'bugg.icu.test.' + uuid.uuid4().hex)]
        clear = [(pid, None) for pid, _ in reversed(values)]
        self.addCleanup(_set_properties, hwnd, clear)
        _set_properties(hwnd, values)
        for pid, value in values:
            self.assertEqual(get(pid), value)
        _set_properties(hwnd, clear)
        for pid, _ in values:
            self.assertIsNone(get(pid))
