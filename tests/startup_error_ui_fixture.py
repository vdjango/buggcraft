"""Isolated startup import: logging/excepthook must not leak into other UI cases."""
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/buggcraft'))
sys.path.insert(0, str(ROOT / 'tests'))
from _qml_test_support import Qt, qt_mouse_click
import config.settings as settings

mode, folder = sys.argv[1], Path(sys.argv[2])
os.environ['BUGGCRAFT_LOG_DIR'] = str(folder)
settings.get_conf_or_cache_manager = lambda: ('startup-test', str(folder / 'configuration'))
import main as startup

if mode == 'qt-before-application':
    import ctypes
    with patch.object(startup, 'setup_qt_environment', return_value=False), \
            patch.object(ctypes.windll.user32, 'MessageBoxW', return_value=1) as native:
        result = startup.initialize_application()
    assert result == 1 and native.call_count == 1
    _, message, title, flags = native.call_args.args
    assert title == '启动失败' and '完整运行包' in message and str(startup.LOG_PATH) in message
    assert flags == 0x10
    receipt = dict(result=result, message=message, native_fallback=True,
                   boundary='Windows native display dispatch; no desktop dialog opened')
else:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    seen, errors = [], []
    timer = QTimer()

    def accept_message():
        for widget in app.topLevelWidgets():
            if isinstance(widget, QMessageBox) and widget.isVisible():
                timer.stop()
                try:
                    seen.append(dict(title=widget.windowTitle(), message=widget.text()))
                    widget.grab().save(str(folder / 'startup-error.png'))
                    button = widget.button(QMessageBox.Ok)
                    qt_mouse_click(button, button.rect().center())
                except BaseException as exc:
                    errors.append(repr(exc))
                    widget.reject()

    timer.timeout.connect(accept_message)
    timer.start(20)
    if mode == 'resources':
        startup.RESOURCE_DIR = folder / 'missing-resources'
        with patch.object(startup, 'initialize_application', side_effect=AssertionError('missing resources reached normal initialization')):
            result = startup.main()
    else:
        with patch.object(startup, 'setup_qt_environment', return_value=False):
            result = startup.initialize_application()
    timer.stop()
    assert not errors, errors
    assert result == 1 and len(seen) == 1
    assert seen[0]['title'] == '启动失败' and '完整运行包' in seen[0]['message']
    assert ('资源缺失' if mode == 'resources' else 'Qt 运行环境初始化失败') in seen[0]['message']
    assert (folder / 'startup-error.png').stat().st_size > 0
    receipt = dict(result=result, **seen[0], qt_platform=app.platformName(),
                   mouse_input='QApplication.sendEvent')

for handler in __import__('logging').getLogger().handlers:
    handler.flush()
log = startup.LOG_PATH.read_text(encoding='utf-8')
assert receipt['message'] in log
receipt['log'] = str(startup.LOG_PATH)
receipt['passed'] = True
(folder / 'startup-result.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
