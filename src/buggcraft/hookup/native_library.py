"""Find the native C ABI and load its packaged Python FFI binding."""
import importlib.util
import os
from pathlib import Path
import sys


def library_path():
    configured = os.environ.get('BUGGCRAFT_BRIDGE_LIBRARY')
    if configured:
        return Path(configured).resolve()
    name = 'buggcraft_bridge.dll' if os.name == 'nt' else (
        'libbuggcraft_bridge.dylib' if sys.platform == 'darwin' else 'libbuggcraft_bridge.so')
    roots = [Path(__file__).resolve().parent.parent / 'native',
             Path(sys.executable).resolve().parent / 'native']
    source = next((parent for parent in Path(__file__).resolve().parents
                   if (parent / 'build.py').is_file() and (parent / 'src/buggcraft').is_dir()), None)
    native = source.parent / 'minecraft-tunnel-native' if source else None
    if native and (native / 'CMakeLists.txt').is_file():
        roots.extend([native / 'runtime', native / 'build'])
    for root in roots:
        for folder in ('bin', 'lib', 'Release', ''):
            candidate = root / folder / name
            if candidate.is_file():
                return candidate
    return None


def load_library(path):
    path = Path(path).resolve()
    choices = [path.parent.parent / 'share/buggcraft-native/python/buggcraft_bridge.py',
               path.parent / 'share/buggcraft-native/python/buggcraft_bridge.py']
    source = next((parent for parent in Path(__file__).resolve().parents
                   if (parent / 'build.py').is_file() and (parent / 'src/buggcraft').is_dir()), None)
    if source:
        native = source.parent / 'minecraft-tunnel-native'
        choices.append(native / 'bindings/python/buggcraft_bridge.py')
    binding = next((item for item in choices if item.is_file()), None)
    if binding is None:
        raise FileNotFoundError('原生联机库的调用文件缺失，请安装完整 native 目录。')
    spec = importlib.util.spec_from_file_location('_buggcraft_native_ffi', binding)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Bridge(path)
