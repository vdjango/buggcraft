"""Build the native bridge; no Python network runtime is bundled."""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--native-source', type=Path, default=ROOT.parent / 'minecraft-tunnel-native')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/bridge-build')
    args = parser.parse_args()
    source = args.native_source.resolve()
    if not (source / 'CMakeLists.txt').is_file():
        raise FileNotFoundError('Clone git@github.com:vdjango/minecraft-tunnel-native.git alongside the launcher')
    subprocess.run([sys.executable, str(source / 'scripts/fetch_deps.py')], check=True)
    build = source / 'build'
    subprocess.run(['cmake', '-S', str(source), '-B', str(build), '-DCMAKE_BUILD_TYPE=Release'], check=True)
    subprocess.run(['cmake', '--build', str(build), '--config', 'Release', '--parallel', '2'], check=True)
    subprocess.run(['cmake', '--install', str(build), '--config', 'Release', '--prefix', str(args.output.resolve())], check=True)

if __name__ == '__main__':
    main()
