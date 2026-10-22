"""Build a portable network component on each target OS."""
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    system = {'Windows': 'windows', 'Linux': 'linux', 'Darwin': 'macos'}[platform.system()]
    arch = {'amd64': 'x64', 'x86_64': 'x64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(platform.machine().lower())
    if not arch:
        raise ValueError('Unsupported target architecture')
    output = ROOT / 'dist/bridge-build'
    output.mkdir(parents=True, exist_ok=True)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    info = {'protocol': 1, 'commit': commit, 'platform': system + '-' + arch,
            'python': platform.python_version(), 'signed': False}
    (output / 'bridge_build.json').write_text(json.dumps(info, indent=2) + '\n', encoding='utf-8')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
                    '--distpath', str(output), '--workpath', str(output / 'work'),
                    str(ROOT / 'packaging/bridge.spec')], cwd=ROOT, check=True)
    bundle = output / 'buggcraft-bridge'
    shutil.copyfile(ROOT / 'LICENSE', bundle / 'LICENSE')
    shutil.copyfile(ROOT / 'docs/technical/bridge-integration.md', bundle / 'INTEGRATION.md')
    shutil.copyfile(output / 'bridge_build.json', bundle / 'build-info.json')
    # Keep corresponding source and dependency notices beside every binary.
    subprocess.run(['git', 'archive', '--format=tar.gz', '-o', str(bundle / 'SOURCE.tar.gz'), 'HEAD'],
                   cwd=ROOT, check=True)
    licenses = bundle / 'licenses'
    licenses.mkdir(exist_ok=True)
    inventory = []
    for dist in metadata.distributions():
        name = dist.metadata['Name']
        if name.lower() in ('pip', 'setuptools', 'wheel', 'pyinstaller', 'pyinstaller-hooks-contrib', 'altgraph'):
            continue
        inventory.append({'name': name, 'version': dist.version})
        for item in dist.files or []:
            if '.dist-info' in str(item) and any(word in item.name.lower() for word in ('license', 'copying', 'notice')):
                source = Path(dist.locate_file(item))
                if source.is_file():
                    target = licenses / name / Path(str(item)).name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
    (bundle / 'dependencies.json').write_text(json.dumps(inventory, indent=2), encoding='utf-8')
    archive = output / ('buggcraft-bridge-' + info['platform'] + ('.zip' if system == 'windows' else '.tar.gz'))
    if system == 'windows':
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as target:
            for source in sorted(bundle.rglob('*')):
                if source.is_file():
                    target.write(source, source.relative_to(output).as_posix())
    else:
        with tarfile.open(archive, 'w:gz') as target:
            target.add(bundle, arcname=bundle.name)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_name(archive.name + '.sha256').write_text(digest + '  ' + archive.name + '\n', encoding='ascii')
    print(json.dumps({'archive': str(archive), 'bytes': archive.stat().st_size, 'sha256': digest}))


if __name__ == '__main__':
    main()
