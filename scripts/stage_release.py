"""Validate and collect downloadable files after the packaged app passes checks."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


ARCHIVES = {
    'windows-x64': 'Buggcraft-runtime-windows-x64.zip',
    'macos-x86_64': 'Buggcraft-macos-x86_64.zip',
    'macos-arm64': 'Buggcraft-macos-arm64.zip',
}
ONEFILES = {'windows-x64': 'Buggcraft.exe', 'linux-x86_64': 'Buggcraft'}


def stage(output, platform, repository_root):
    manifest = json.loads((output / 'release.json').read_text(encoding='utf-8'))
    if platform in ONEFILES:
        executable = output / ONEFILES[platform]
        if not executable.is_file():
            raise FileNotFoundError(executable)
        if (manifest.get('platform') != platform or manifest.get('format') != 'onefile'
                or manifest.get('entrypoint') != executable.name):
            raise ValueError('Release platform or executable does not match the build')
        with executable.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if executable.stat().st_size != manifest.get('size') or digest != manifest.get('sha256'):
            raise ValueError('Release executable size or SHA-256 does not match its manifest')
        destination = output / 'release'
        destination.mkdir(exist_ok=False)
        shutil.copy2(executable, destination / executable.name)
        (destination / ('SHA256SUMS-' + platform + '.txt')).write_text(
            digest + '  ' + executable.name + '\n', encoding='ascii')
        return destination
    if manifest.get('platform') != platform or manifest.get('archive') != ARCHIVES[platform]:
        raise ValueError('Release platform or archive name does not match the build')
    archive = output / ARCHIVES[platform]
    with archive.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if archive.stat().st_size != manifest['size'] or digest != manifest['sha256']:
        raise ValueError('Release archive size or SHA-256 does not match its manifest')
    files = {archive: archive.name,
             output / 'release.json': 'release-' + platform + '.json'}
    for path in files:
        if not path.is_file():
            raise FileNotFoundError(path)
    destination = output / 'release'
    # A fresh directory prevents an earlier build's files being published.
    destination.mkdir(exist_ok=False)
    checksums = []
    for source, name in files.items():
        target = destination / name
        shutil.copy2(source, target)
        with target.open('rb') as stream:
            checksums.append(hashlib.file_digest(stream, 'sha256').hexdigest() + '  ' + name)
    (destination / ('SHA256SUMS-' + platform + '.txt')).write_text(
        '\n'.join(checksums) + '\n', encoding='ascii')
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('dist'))
    parser.add_argument('--platform', required=True, choices=tuple(ARCHIVES) + tuple(ONEFILES))
    args = parser.parse_args()
    print(stage(args.output, args.platform, Path(__file__).resolve().parents[1]))
