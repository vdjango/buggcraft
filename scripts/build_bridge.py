"""Build the native bridge; no Python network runtime is bundled."""
import argparse
from collections import deque
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--native-source', type=Path, default=ROOT.parent / 'minecraft-tunnel-native')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/bridge-build')
    parser.add_argument('--log', type=Path)
    args = parser.parse_args()
    source = args.native_source.resolve()
    if not (source / 'CMakeLists.txt').is_file():
        raise FileNotFoundError('Clone git@github.com:vdjango/minecraft-tunnel-native.git alongside the launcher')
    def run(command):
        if args.log is None:
            subprocess.run(command, check=True)
            return
        args.log.parent.mkdir(parents=True, exist_ok=True)
        tail = deque(maxlen=25)
        with args.log.open('a', encoding='utf-8') as log:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, encoding='utf-8', errors='replace')
            for line in process.stdout:
                print(line, end='', flush=True)
                log.write(line)
                tail.append(line.rstrip())
            status = process.wait()
        if status:
            message = '\n'.join(tail)[-3500:]
            if 'GITHUB_ACTIONS' in os.environ:
                message = message.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
                print('::error title=Native runtime build failed::' + message)
            raise SystemExit(status)

    run([sys.executable, str(source / 'scripts/fetch_deps.py')])
    build = source / 'build'
    run(['cmake', '-S', str(source), '-B', str(build), '-DCMAKE_BUILD_TYPE=Release'])
    run(['cmake', '--build', str(build), '--config', 'Release', '--parallel', '2'])
    run(['cmake', '--install', str(build), '--config', 'Release', '--prefix', str(args.output.resolve())])

if __name__ == '__main__':
    main()
