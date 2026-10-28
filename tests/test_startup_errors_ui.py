"""Actual startup error dialogs, isolated from normal launcher imports."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from _qml_test_support import ROOT


@pytest.mark.parametrize('mode', ['resources', 'qt-initialization', 'qt-before-application'])
def test_startup_failure_has_recovery_message_and_persistent_log(mode):
    if mode == 'qt-before-application' and os.name != 'nt':
        pytest.skip('Windows native startup fallback')
    folder = Path(os.environ.get('BUGGCRAFT_UI_OUTPUT', ROOT.parent / '.test-tools/coverage-gaps')) / ('startup-' + mode)
    folder.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software')
    run = subprocess.run([sys.executable, str(ROOT / 'tests/startup_error_ui_fixture.py'), mode, str(folder)],
                         cwd=ROOT, env=env, capture_output=True, timeout=30)
    (folder / 'process-output.log').write_bytes(run.stdout + run.stderr)
    assert run.returncode == 0, (run.stdout + run.stderr).decode('utf-8', errors='replace')
    receipt = json.loads((folder / 'startup-result.json').read_text(encoding='utf-8'))
    assert receipt['passed'] and receipt['result'] == 1
