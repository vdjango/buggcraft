"""Real node/room acceptance, isolated from the launcher's Python imports.

The native project's management service has a Python `tunnel` package. It is
test infrastructure for the C++ data plane, never a launcher transport fallback.
"""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest

from hookup.native_library import library_path
from hookup.native_routes import executable


ROOT = Path(__file__).resolve().parents[1]


def test_cpp_bridge_real_node_room_chat_mods_and_social():
    configured = os.environ.get('BUGGCRAFT_NATIVE_SOURCE')
    native = Path(configured).resolve() if configured else ROOT.parent / 'minecraft-tunnel-native'
    if not (native / 'tests/test_bridge_services.py').is_file():
        if configured:
            pytest.fail(f'Missing configured native test source: {native}')
        pytest.skip('Provide BUGGCRAFT_NATIVE_SOURCE with the native integration tests')
    binary, library = executable(), library_path()
    if not binary or not Path(binary).is_file():
        pytest.skip('Build the C++ bridge and core before running live node tests')
    python = os.environ.get('BUGGCRAFT_NATIVE_TEST_PYTHON', sys.executable)
    if python == sys.executable and importlib.util.find_spec('asyncssh') is None:
        pytest.skip('Install the native repository test requirements or set BUGGCRAFT_NATIVE_TEST_PYTHON')
    output = Path(os.environ.get('BUGGCRAFT_NATIVE_TEST_OUTPUT',
                  ROOT.parent / '.test-tools/native-bridge-services'))
    output.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, PYTHONIOENCODING='utf-8',
                       BUGGCRAFT_LAUNCHER_SOURCE=str(ROOT / 'src/buggcraft'),
                       BUGGCRAFT_BRIDGE_EXECUTABLE=str(binary),
                       BUGGCRAFT_NATIVE_CORE=str(Path(binary).with_name(
                           'buggcraft-core.exe' if os.name == 'nt' else 'buggcraft-core')),
                       BUGGCRAFT_BRIDGE_SOAK_LOG_DIR=str(output / 'players'))
    if library:
        environment['BUGGCRAFT_BRIDGE_LIBRARY'] = str(library)
    # Keep the explicitly configured dependency environment. The child cwd
    # isolates node imports from the launcher; stripping PYTHONPATH also removed
    # the workspace's installed asyncssh test dependency.
    environment['PATH'] = str(Path(binary).parent) + os.pathsep + environment.get('PATH', '')
    methods = [
        'test_launcher_add_code_uses_cpp_without_python_ssh_modules',
        'test_launcher_endpoints_validate_full_native_manifest_and_send_chat',
        'test_native_manifest_pages_hash_download_and_simultaneous_game_data',
        'test_personal_code_and_native_social_signature',
        'test_optional_resources_manifest_and_verified_direct_download',
    ]
    result = subprocess.run([python, '-X', 'utf8', '-m', 'unittest', '-v', *[
        'tests.test_bridge_services.BridgeServicesTests.' + method for method in methods]],
        cwd=native, env=environment, capture_output=True, text=True, encoding='utf-8',
        errors='replace', timeout=240,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    log = result.stdout + result.stderr
    (output / 'native-services.log').write_text(log, encoding='utf-8')
    assert result.returncode == 0, log[-14000:]
    assert f'Ran {len(methods)} tests' in log and '\nOK\n' in log, log[-5000:]
