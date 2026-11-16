"""Stage the published native bridge beside the Qt-deployed desktop app."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--platform', required=True)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    node_platform = args.platform.replace('x86_64', 'x64')
    headers = {'Authorization': 'Bearer ' + os.environ['GH_TOKEN'], 'User-Agent': 'Bugg-desktop-package'}
    with urlopen(Request('https://api.github.com/repos/vdjango/minecraft-tunnel-native/releases/tags/v0.3.12', headers=headers), timeout=45) as response:
        release = json.load(response)
    name = f'buggcraft-native-0.3.12-{node_platform}.tar.gz'
    asset = next(item for item in release['assets'] if item['name'] == name)
    archive = Path(name)
    with urlopen(asset['browser_download_url'], timeout=120) as response:
        archive.write_bytes(response.read(asset['size'] + 1))
    assert archive.stat().st_size == asset['size']
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert asset['digest'] == 'sha256:' + digest
    root = Path('deployed-desktop')
    if args.platform.startswith('macos-'):
        app = root / 'Bugg.app'
        shutil.copytree('deployed/bugg.app', app, symlinks=False)
        payload = app
        native = app / 'Contents/MacOS/native'
    else:
        shutil.copytree('deployed', root, symlinks=False)
        payload = root
        native = root / 'native'
    notices = payload / ('Contents/Resources/licenses' if args.platform.startswith('macos-') else 'licenses')
    notices.mkdir(parents=True, exist_ok=True)
    shutil.copyfile('LICENSE', notices / 'Bugg-AGPL-3.0.txt')
    shutil.copyfile('third_party/notices/qt-6.8.1.txt', notices / 'Qt-6.8.1-and-third-party.txt')
    with tarfile.open(archive) as source:
        for entry in source.getmembers():
            # Reuse only the existing bridge runtime and its licenses. Do not
            # distribute the server core, SDK, tests or Python bindings.
            archived = Path(entry.name)
            if not archived.parts or archived.parts[0] != 'runtime':
                raise ValueError('Unexpected native runtime archive root')
            relative = Path(*archived.parts[1:])
            parts = relative.parts
            if relative.is_absolute() or '..' in parts:
                raise ValueError('Unsafe native runtime archive')
            selected = (relative.as_posix() == 'bin/buggcraft-bridge' or
                        (parts and parts[0] == 'lib' and not entry.name.endswith('.a')) or
                        relative.as_posix().startswith('share/buggcraft-native/licenses/') or
                        relative.name in ('LICENSE', 'THIRD_PARTY_NOTICES.md'))
            if selected and entry.isfile():
                destination = native / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(entry) as data, destination.open('wb') as output:
                    shutil.copyfileobj(data, output)
                destination.chmod(entry.mode & 0o777)
            elif selected and entry.issym():
                # Convert validated in-archive aliases to ordinary files; the
                # portable updater deliberately does not extract symbolic links.
                linked = relative.parent / entry.linkname
                if linked.is_absolute() or '..' in linked.parts:
                    raise ValueError('Unsafe native runtime link')
                data = source.extractfile(entry)
                destination = native / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                with data, destination.open('wb') as output:
                    shutil.copyfileobj(data, output)
                destination.chmod(0o755)
    if args.platform.startswith('macos-'):
        # Qt's QML deployment uses Resources/qml inside an app bundle.
        # Pin relative paths so lookup never depends on the build SDK.
        (payload / 'Contents/Resources/qt.conf').write_text(
            '[Paths]\nPrefix=.\nPlugins=PlugIns\nQmlImports=Resources/qml\nLibraries=Frameworks\n',
            encoding='utf-8')
        # MacOS is a code location. Keep native notices in Resources so that
        # codesign does not interpret text files as unsigned helper programs.
        resources = payload / 'Contents/Resources/NativeRuntime'
        resources.mkdir(parents=True, exist_ok=True)
        for notice in list(native.iterdir()):
            if notice.name not in ('bin', 'lib'):
                shutil.move(str(notice), resources / notice.name)
        # The updater accepts ordinary files only. Turn Qt's versioned
        # frameworks into flat frameworks and rewrite their Mach-O references;
        # duplicating both Resources and Versions makes codesign reject them.
        for framework in payload.rglob('*.framework'):
            versions = framework / 'Versions'
            if versions.is_dir():
                assert versions.resolve().is_relative_to(payload.resolve())
                shutil.rmtree(versions)
        machos = []
        for path in payload.rglob('*'):
            if not path.is_file():
                continue
            with path.open('rb') as stream:
                magic = stream.read(4)
            if magic not in (b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe'):
                continue
            machos.append(path)
            links = subprocess.check_output(['otool', '-L', str(path)], text=True).splitlines()[1:]
            for line in links:
                dependency = line.strip().split(' (', 1)[0]
                flattened = dependency.replace('.framework/Versions/A/', '.framework/').replace('.framework/Versions/Current/', '.framework/')
                if flattened != dependency:
                    subprocess.run(['install_name_tool', '-change', dependency, flattened, str(path)], check=True)
                if dependency.startswith('/') and not dependency.startswith(('/System/Library/', '/usr/lib/')):
                    raise ValueError('Application retains an external runtime dependency: ' + dependency)
        # Signing the main executable signs its enclosing app. Sign nested
        # code first and seal the app only after every helper is ready.
        main_executable = payload / 'Contents/MacOS/bugg'
        for path in sorted(machos, key=lambda item: len(item.parts), reverse=True):
            if path != main_executable:
                subprocess.run(['codesign', '--force', '--sign', '-', str(path)], check=True)
        subprocess.run(['codesign', '--force', '--deep', '--sign', '-', str(payload)], check=True)
        subprocess.run(['codesign', '--verify', '--deep', '--strict', str(payload)], check=True)
    subprocess.run(['python', 'tools/package_release.py', '--version', args.version,
                    '--platform', args.platform, '--directory', str(payload),
                    '--languages', 'build-desktop/language-assets', '--output', 'desktop-release'], check=True)
    Path('desktop-deployment.json').write_text(json.dumps({
        'platform': args.platform, 'version': args.version, 'node_release': release['html_url'],
        'node_asset': name, 'node_sha256': digest, 'runtime_python': False}, indent=2)+'\n')


if __name__ == '__main__':
    main()
