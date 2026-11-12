"""Measure an isolated native launcher's idle CPU and working set; starts no game."""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--qt-bin", required=True, type=Path)
    parser.add_argument("--support-dir", required=True, type=Path)
    parser.add_argument("--states", nargs="+", default=["panel-home", "classic-home", "panel-tasks", "classic-tasks"],
                        choices=["panel-home", "classic-home", "panel-tasks", "classic-tasks"])
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Windows process/UI measurement only")
    sys.path.insert(0, str(args.support_dir))
    import psutil
    from PIL import ImageGrab
    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.EnableWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
    args.output.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment["PATH"] = str(args.qt_bin) + os.pathsep + str(args.binary.resolve().parent) + os.pathsep + environment["PATH"]
    environment["QML_IMPORT_PATH"] = str(args.binary.resolve().parent / "qml")
    environment["QSG_INFO"] = "1"
    results = []
    for label in args.states:
        theme, route = label.split('-')
        profile = args.output / label
        profile.mkdir(exist_ok=False)
        binary = profile / "bugg-idle.exe"
        shutil.copy2(args.binary, binary)
        command = [str(binary.resolve()), "--theme", theme]
        if route != "home":
            command += ["--page", route]
        handle = None
        with (profile / "native.log").open("wb") as log:
            process = subprocess.Popen(command, env=environment, stdout=log, stderr=log)
            native = psutil.Process(process.pid)
            try:
                deadline = time.monotonic() + 30
                while handle is None and time.monotonic() < deadline:
                    matches = []
                    @callback_type
                    def enumerate_window(window, _parameter):
                        owner = wintypes.DWORD()
                        user32.GetWindowThreadProcessId(window, ctypes.byref(owner))
                        if owner.value == process.pid and user32.IsWindowVisible(window):
                            matches.append(window)
                        return True
                    user32.EnumWindows(enumerate_window, 0)
                    handle = matches[0] if matches else None
                    if process.poll() is not None:
                        raise RuntimeError("Native launcher exited before measurement")
                    if handle is None:
                        time.sleep(.1)
                if handle is None:
                    raise RuntimeError("No native launcher window")
                user32.SetWindowPos(handle, None, 100, 100, 0, 0, 0x0015)
                # Disable input only on this isolated test window; the user can
                # continue working without accidentally changing its sampled page.
                user32.EnableWindow(handle, False)
                # Fixed settling period; no UI queries/screenshots during sampling.
                time.sleep(10)
                samples = []
                native.cpu_percent()
                for _ in range(8):
                    cpu = native.cpu_percent(interval=1)
                    memory = native.memory_info()
                    samples.append({"cpuPercentOneCore": cpu, "workingSetBytes": memory.rss,
                                    "privateBytes": memory.private})
                bounds = wintypes.RECT()
                user32.GetWindowRect(handle, ctypes.byref(bounds))
                ImageGrab.grab(bbox=(bounds.left, bounds.top, bounds.right, bounds.bottom)).save(profile / "page.png")
                results.append({"state": label, "samples": samples,
                                "medianCpuPercentOneCore": statistics.median(item["cpuPercentOneCore"] for item in samples),
                                "peakWorkingSetBytes": max(item["workingSetBytes"] for item in samples)})
                print(label + ': ' + str(results[-1]), flush=True)
            finally:
                owned = native.children(recursive=True) if process.poll() is None else []
                if handle:
                    user32.PostMessageW(handle, 0x0010, 0, 0)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                for child in owned:
                    if child.is_running():
                        child.kill()
                psutil.wait_procs(owned, timeout=5)
    (args.output / "report.json").write_text(json.dumps({
        "system": platform.platform(), "logicalProcessors": os.cpu_count(),
        "binarySha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
        "method": "Fresh portable profiles, no accounts/instances/custom backgrounds; input disabled only on the owned window; 10 s settling, 8 x 1 s samples; default Qt renderer; CPU 100% means one logical core; screenshots outside sampling; inspect screenshots to verify actual page",
        "renderEnvironment": {name: environment.get(name) for name in ["QT_QUICK_BACKEND", "QSG_RHI_BACKEND", "QML_DISABLE_DISK_CACHE"]},
        "states": results}, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
