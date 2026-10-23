"""Build a self-contained launcher, including Qt Quick and its QML resources.

Install requirements.txt and Nuitka first. Use --dry-run to inspect the command.
"""
import argparse
import os
import hashlib
import json
import platform
import plistlib
import shutil
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent


def stage_native_bridge(runtime, package):
    """Ship one complete CMake install tree; preserve relative runtime paths."""
    runtime, package = Path(runtime).resolve(), Path(package).resolve()
    name = 'buggcraft-bridge.exe' if os.name == 'nt' else 'buggcraft-bridge'
    library = 'buggcraft_bridge.dll' if os.name == 'nt' else (
        'libbuggcraft_bridge.dylib' if sys.platform == 'darwin' else 'libbuggcraft_bridge.so')
    has_library = any((package / folder / library).is_file() for folder in ('bin', 'lib'))
    if not has_library and not (package / 'bin' / name).is_file():
        raise FileNotFoundError('Use the native project CMake install directory: ' + str(package))
    if has_library and not (package / 'share/buggcraft-native/python/buggcraft_bridge.py').is_file():
        raise FileNotFoundError('Native library binding missing from install directory: ' + str(package))
    destination = runtime / 'native'
    if package == destination or destination in package.parents:
        raise ValueError('Native install source must be outside the runtime destination')
    if destination.exists():
        if destination.resolve().parent != runtime or destination.is_symlink():
            raise ValueError('Unexpected native runtime destination')
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    for folder in ('bin', 'lib', 'share'):
        if (package / folder).is_dir():
            shutil.copytree(package / folder, destination / folder,
                ignore=shutil.ignore_patterns('buggcraft-core', 'buggcraft-core.exe', '__pycache__', '*.pyc', '*.pyo'))
    files = {path.relative_to(destination).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in destination.rglob('*') if path.is_file()}
    (destination / 'manifest.json').write_text(json.dumps(dict(schema=1, files=files), indent=2), encoding='utf-8')


def validate_runtime_inventory(directory):
    """Fail a release if an unused media or PDF dependency reappears."""
    forbidden_packages = {'asyncssh', 'aioice', 'aiortc', 'av', 'av.libs', 'pylibsrtp', 'notifypy', 'loguru', 'plyer'}
    unexpected = []
    for path in directory.rglob('*'):
        if not path.is_file():
            continue
        relative = path.relative_to(directory)
        name = path.name.lower()
        if (forbidden_packages.intersection(part.lower() for part in relative.parts)
                or name in {'qpdf.dll', 'qt6pdf.dll', 'libqpdf.dylib', 'libqpdf.so'}
                or (platform.system() == 'Windows' and name in {
                    'opengl32sw.dll', 'qdirect2d.dll', 'qminimal.dll'})):
            unexpected.append(relative.as_posix())
    if unexpected:
        raise ValueError('Unneeded dependencies in runtime; rebuild with current rules: '
                         + ', '.join(sorted(unexpected)))


def trim_qt_libraries(directory, quarantine):
    """Remove Qt DLLs pulled solely by QML plugins excluded from the build.

    Nuitka still scans dependencies of excluded QML DLLs. Follow actual PE
    imports from every shipped executable, extension and non-Qt DLL instead.
    Only Qt6 DLLs are candidates; Python/OpenSSL/FFmpeg stay intact.
    """
    import pefile
    binaries = [p for p in directory.rglob('*') if p.is_file() and
                p.suffix.lower() in ('.dll', '.pyd', '.exe')]
    candidates = {p.name.lower(): p for p in binaries if
                  p.name.lower().startswith('qt6') and p.suffix.lower() == '.dll'}
    by_name = {}
    for path in binaries:
        by_name.setdefault(path.name.lower(), []).append(path)
    pending = [p for p in binaries if p not in candidates.values()]
    visited = set()
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        binary = pefile.PE(str(path), fast_load=True)
        try:
            binary.parse_data_directories(directories=[
                pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT'],
                pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT']])
            imports = list(getattr(binary, 'DIRECTORY_ENTRY_IMPORT', []))
            imports += list(getattr(binary, 'DIRECTORY_ENTRY_DELAY_IMPORT', []))
            for record in imports:
                pending.extend(by_name.get(record.dll.decode('ascii').lower(), []))
        finally:
            binary.close()
    removed = []
    for path in candidates.values():
        if path not in visited:
            target = quarantine / path.relative_to(directory)
            target.parent.mkdir(exist_ok=True, parents=True)
            removed.append({'name': path.name, 'size': path.stat().st_size})
            path.replace(target)
    return removed


def qml_exclusions():
    """Keep Qt's scanner dependency closure, including Basic style internals."""
    import PySide6
    from PySide6.QtCore import QLibraryInfo
    qt = Path(PySide6.__file__).parent
    scanner_name = 'qmlimportscanner.exe' if os.name == 'nt' else 'qmlimportscanner'
    scanner = next((p for p in (qt / scanner_name, qt / 'Qt/libexec' / scanner_name,
                               qt / 'Qt/bin' / scanner_name) if p.is_file()), None)
    if scanner is None:
        raise FileNotFoundError('Qt qmlimportscanner was not found in ' + str(qt))
    qml_root = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.QmlImportsPath)).resolve()
    result = subprocess.run([str(scanner), '-rootPath', str(ROOT / 'resources/qml'),
                             '-importPath', str(qml_root)], check=True,
                            capture_output=True, text=True, encoding='utf-8')
    modules = json.loads(result.stdout)
    keep = {Path(m['path']).resolve() for m in modules if m.get('path')}
    if not keep or not any(m.get('name') == 'QtQuick.Controls.Basic' for m in modules):
        raise RuntimeError('QML dependency scan did not resolve the Basic style')
    excluded = []
    def visit(directory):
        for child in sorted(directory.iterdir()):
            if not child.is_dir():
                continue
            if any(child == p or child in p.parents for p in keep):
                visit(child)
            else:
                # Nuitka normalizes the platform-specific wheel layout.
                pattern = 'PySide6/qml/' + child.relative_to(qml_root).as_posix() + '/*'
                excluded.extend(['--noinclude-dlls=' + pattern,
                                 '--noinclude-data-files=' + pattern])
    visit(qml_root)
    return excluded, sorted(m['name'] for m in modules)


def make_command(onefile=False, output=None, jobs=None):
    root = Path(__file__).resolve().parent
    resources = root / 'resources'
    required = [resources / 'qml/multiplayer/Lobby.qml', resources / 'images/minecraft_bg.png',
                *[resources / 'qml/launcher' / name for name in
                  ('LauncherHeader.qml', 'Home.qml', 'Downloads.qml', 'GameCatalogue.qml', 'GameInstallation.qml',
                   'InstallationComponent.qml', 'DownloadHub.qml',
                   'TaskHistory.qml', 'TaskRecord.qml', 'SettingsForm.qml', 'Instances.qml', 'RecordList.qml',
                   'DialogContent.qml', 'ChoiceBox.qml', 'ModalDialog.qml', 'SettingsSection.qml', 'SettingOption.qml',
                   'ListRow.qml', 'IconButton.qml', 'CatalogueList.qml', 'ContentCatalogue.qml', 'VersionPicker.qml',
                   'HeaderAction.qml', 'ContentDetails.qml', 'PagedListView.qml')]]
    if any(not path.is_file() for path in required):
        raise FileNotFoundError('Missing launcher resources; build from a complete checkout')
    command = [sys.executable, '-m', 'nuitka', '--onefile' if onefile else '--standalone',
               '--enable-plugin=pyside6', '--include-qt-plugins=sensible,qml',
               '--noinclude-dlls=PySide6/qt-plugins/imageformats/*qpdf*',
               '--noinclude-qt-translations',
               '--include-module=PySide6.QtQuickWidgets', '--include-module=PySide6.QtQml',
               '--include-package=minecraft_launcher_lib', '--include-package-data=minecraft_launcher_lib',
               '--nofollow-import-to=asyncssh,aioice,aiortc,av,pylibsrtp,hookup._rtc,hookup.peer,hookup.ice,hookup.compression,hookup.game_chat,hookup.legacy_chat',
               '--nofollow-import-to=notifypy,loguru,plyer,multiprocessing,concurrent.futures.process,_uuid',
               f'--include-data-files={root / "src/buggcraft/hookup/THIRD_PARTY_NOTICES.txt"}=hookup/THIRD_PARTY_NOTICES.txt',
               f'--include-data-dir={resources}=resources',
               f'--output-dir={output or root / "dist"}',
               f'--report={(output or root / "dist") / "compilation-report.xml"}',
               f'--jobs={jobs or min(os.cpu_count() or 2, 8)}',
               '--assume-yes-for-downloads', '--lto=yes',
               '--nofollow-import-to=*.tests,*.test,pytest,unittest,tkinter,IPython',
               '--noinclude-data-files=resources/icons/*/app.png',
               '--noinclude-data-files=resources/fonts/*']
    if platform.system() == 'Windows':
        command += ['--windows-console-mode=disable', '--output-filename=Buggcraft.exe',
                    '--noinclude-dlls=opengl32sw.dll',
                    '--noinclude-dlls=PySide6/qt-plugins/platforms/qdirect2d.dll',
                    '--noinclude-dlls=PySide6/qt-plugins/platforms/qminimal.dll',
                    '--include-windows-runtime-dlls=yes', '--msvc=latest',
                    f'--windows-icon-from-ico={resources / "icons/app.ico"}']
    elif platform.system() == 'Darwin':
        if onefile:
            raise ValueError('macOS builds use a standalone .app bundle; omit --onefile')
        command += ['--macos-create-app-bundle', '--macos-app-name=Buggcraft',
                    '--output-filename=Buggcraft',
                    f'--macos-app-icon={resources / "icons/app.icns"}',
                    '--macos-app-category-type=public.app-category.games']
    exclusions, _ = qml_exclusions()
    command.extend(exclusions)
    command.append(str(root / 'src/buggcraft/main.py'))
    return command


def package_macos(output):
    """Archive a native .app with ditto, preserving framework symlinks and modes."""
    bundles = [p for p in output.glob('*.app') if (p / 'Contents/Info.plist').is_file()]
    if len(bundles) != 1:
        raise RuntimeError('Expected one compiled .app in ' + str(output))
    bundle = bundles[0]
    info = plistlib.loads((bundle / 'Contents/Info.plist').read_bytes())
    executable = bundle / 'Contents/MacOS' / info['CFBundleExecutable']
    if not executable.is_file():
        raise FileNotFoundError('Missing macOS executable: ' + str(executable))
    validate_runtime_inventory(bundle)
    architecture = {'aarch64': 'arm64', 'AMD64': 'x86_64'}.get(platform.machine(), platform.machine())
    archive = output / ('Buggcraft-macos-' + architecture + '.zip')
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(bundle)], check=True)
    subprocess.run(['/usr/bin/ditto', '-c', '-k', '--sequesterRsrc', '--keepParent',
                    str(bundle), str(archive)], check=True)
    manifest = {'schema': 1, 'platform': 'macos-' + architecture, 'archive': archive.name,
                'size': archive.stat().st_size, 'bundle': bundle.name,
                'entrypoint': executable.relative_to(output).as_posix(),
                'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
                'signing': 'ad-hoc', 'notarized': False}
    (output / 'release.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest


def package_runtime(directory, output, urls, certificate_pins=None):
    """Version a complete runtime. Never mix loose DLLs from different builds."""
    if not (directory / 'Buggcraft.exe').is_file():
        raise FileNotFoundError('No compiled Buggcraft.exe found in ' + str(directory))
    validate_runtime_inventory(directory)
    files = []
    archive = output / 'Buggcraft-runtime-windows-x64.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in sorted(directory.rglob('*')):
            if not path.is_file():
                continue
            relative = path.relative_to(directory).as_posix()
            data = path.read_bytes()
            files.append({'path': relative, 'size': len(data),
                          'sha256': hashlib.sha256(data).hexdigest()})
            entry = zipfile.ZipInfo(relative, date_time=(2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            bundle.writestr(entry, data, compresslevel=9)
    with archive.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    manifest = {'schema': 1, 'version': digest[:16], 'platform': 'windows-x64',
                'entrypoint': 'Buggcraft.exe', 'archive': archive.name,
                'size': archive.stat().st_size, 'sha256': digest,
                'urls': [url.replace('{version}', digest[:16]) for url in urls],
                'files': files, 'certificate_pins': certificate_pins or {}}
    destination = output / 'release.json'
    destination.write_text(json.dumps(manifest, ensure_ascii=True, indent=2), encoding='utf-8')
    verify_release(directory, output)
    return manifest, destination


def verify_release(directory, output):
    """Reject a changed runtime or damaged archive before publishing it."""
    manifest = json.loads((output / 'release.json').read_text(encoding='utf-8'))
    archive = output / manifest['archive']
    if archive.stat().st_size != manifest['size']:
        raise ValueError('Runtime archive size mismatch')
    with archive.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != manifest['sha256']:
            raise ValueError('Runtime archive SHA-256 mismatch')
    with zipfile.ZipFile(archive) as bundle:
        if set(bundle.namelist()) != {record['path'] for record in manifest['files']}:
            raise ValueError('Runtime archive file list mismatch')
        for record in manifest['files']:
            path = directory / record['path']
            data = path.read_bytes()
            if len(data) != record['size'] or hashlib.sha256(data).hexdigest() != record['sha256']:
                raise ValueError('Runtime file changed: ' + record['path'])
            if bundle.read(record['path']) != data:
                raise ValueError('Archived runtime differs: ' + record['path'])
    return manifest


def build_bootstrap(manifest, output):
    compiler = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    if not compiler.is_file():
        raise RuntimeError('Windows .NET Framework C# compiler is not installed')
    subprocess.run([str(compiler), '/nologo', '/target:winexe', '/platform:x64',
        '/optimize+', '/r:System.Net.Http.dll', '/r:System.IO.Compression.dll',
        '/r:System.IO.Compression.FileSystem.dll', '/r:System.Runtime.Serialization.dll',
        '/r:System.Windows.Forms.dll', '/r:System.Drawing.dll',
        '/win32icon:' + str(ROOT / 'resources/icons/app.ico'),
        '/resource:' + str(manifest) + ',release.json',
        '/out:' + str(output / 'Buggcraft-Setup.exe'),
        str(ROOT / 'packaging/windows/Bootstrap.cs')], check=True)


def sign_artifacts(output, certificate, password=None, timestamp_url=None, require=False, names=None,
                   thumbprint=None, machine_store=False):
    """Sign selected Windows entrypoints when a trusted certificate is configured."""
    names = names or ['Buggcraft-Setup.exe', 'main.dist/Buggcraft.exe']
    artifacts = [output / name for name in names]
    if certificate and thumbprint:
        raise ValueError('Choose a PFX file or a certificate thumbprint')
    if not certificate and not thumbprint:
        if require:
            raise RuntimeError('A trusted code-signing certificate is required; set --sign-certificate')
        return {'signed': False, 'reason': 'no certificate configured'}
    signtool = os.environ.get('BUGGCRAFT_SIGNTOOL')
    if not signtool:
        candidates = sorted(Path(os.environ.get('ProgramFiles(x86)', '')).glob('Windows Kits/10/bin/*/x64/signtool.exe'))
        signtool = str(candidates[-1]) if candidates else None
    if not signtool or not Path(signtool).is_file():
        raise RuntimeError('signtool.exe not found; set BUGGCRAFT_SIGNTOOL')
    password_env = os.environ.get('BUGGCRAFT_SIGN_PASSWORD_ENV', 'BUGGCRAFT_SIGN_PASSWORD')
    password = password if password is not None else os.environ.get(password_env)
    command = [signtool, 'sign', '/fd', 'sha256']
    if thumbprint:
        thumbprint = thumbprint.replace(' ', '')
        if len(thumbprint) != 40 or any(c not in '0123456789abcdefABCDEF' for c in thumbprint):
            raise ValueError('Certificate thumbprint must contain 40 hexadecimal digits')
        command += ['/sha1', thumbprint, '/s', 'My']
        if machine_store:
            command += ['/sm']
    else:
        command += ['/f', str(certificate)]
        if password:
            command += ['/p', password]
    if timestamp_url:
        command += ['/tr', timestamp_url, '/td', 'sha256']
    for artifact in artifacts:
        try:
            subprocess.run(command + [str(artifact)], check=True)
        except subprocess.CalledProcessError as error:
            # CalledProcessError includes the command, which may contain /p.
            raise RuntimeError('Authenticode signing failed for ' + artifact.name +
                               '; exit code ' + str(error.returncode)) from None
        subprocess.run([signtool, 'verify', '/pa', '/all', str(artifact)], check=True)
    return {'signed': True, 'artifacts': [str(path) for path in artifacts],
            'hashes': {path.relative_to(output).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                       for path in artifacts}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--onefile', action='store_true', help='Produce a single executable instead of a directory')
    parser.add_argument('--dry-run', action='store_true', help='Print arguments without compiling or downloading')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    parser.add_argument('--jobs', type=int)
    parser.add_argument('--runtime-url', action='append', default=[],
                        help='HTTPS URL for the generated runtime ZIP; repeat for mirrors')
    parser.add_argument('--package-only', action='store_true',
                        help='Package an existing main.dist without recompiling')
    parser.add_argument('--native-bridge-dir', type=Path,
                        help='CMake install directory for this platform; bundle the native bridge and all its libraries')
    parser.add_argument('--certificate-pin', action='append', default=[], metavar='HOST:PORT=SHA256',
                        help='Pin a temporary HTTPS endpoint certificate SHA-256')
    parser.add_argument('--sign-certificate', type=Path,
                        help='Trusted Authenticode PFX certificate; password comes from BUGGCRAFT_SIGN_PASSWORD')
    parser.add_argument('--sign-thumbprint', help='Code-signing certificate in Windows My store (including hardware token keys)')
    parser.add_argument('--sign-machine-store', action='store_true', help='Use the local machine certificate store')
    parser.add_argument('--timestamp-url', default='', help='RFC 3161 timestamp URL for Authenticode signing')
    parser.add_argument('--require-signature', action='store_true',
                        help='Fail the build unless the installer and launcher are signed')
    args = parser.parse_args()
    if args.onefile and args.native_bridge_dir:
        parser.error('--native-bridge-dir requires a standalone runtime; omit --onefile')
    if platform.system() not in ('Windows', 'Darwin'):
        parser.error('Release packaging currently supports Windows and macOS hosts')
    if platform.system() == 'Darwin' and (args.runtime_url or args.certificate_pin or
            args.sign_certificate or args.sign_thumbprint or args.require_signature):
        parser.error('Windows bootstrap and Authenticode options do not apply to macOS')
    if any(not u.startswith('https://') for u in args.runtime_url):
        parser.error('Runtime download URLs must use HTTPS')
    pins = {}
    for value in args.certificate_pin:
        authority, separator, digest = value.partition('=')
        if not separator or len(digest) != 64 or any(c not in '0123456789abcdefABCDEF' for c in digest):
            parser.error('Certificate pin must be HOST:PORT=64-hex-digit-SHA256')
        pins[authority.lower()] = digest.lower()
    output = args.output.resolve()
    command = make_command(args.onefile, output, args.jobs)
    if args.dry_run:
        print('\n'.join(command))
        return 0
    output.mkdir(parents=True, exist_ok=True)
    if args.sign_certificate and args.sign_thumbprint:
        parser.error('Choose --sign-certificate or --sign-thumbprint')
    if args.require_signature and not (args.sign_certificate or args.sign_thumbprint):
        parser.error('--require-signature requires a trusted code-signing certificate')
    if args.require_signature and not args.timestamp_url:
        parser.error('--require-signature requires --timestamp-url to retain signatures after certificate expiry')
    (output / 'signing-status.json').unlink(missing_ok=True)
    if not args.package_only:
        status = subprocess.run(command, cwd=ROOT).returncode
        if status:
            return status
    if platform.system() == 'Darwin':
        if args.native_bridge_dir:
            bundles = list(output.glob('*.app'))
            if len(bundles) != 1:
                raise RuntimeError('Expected one .app to stage the native bridge')
            stage_native_bridge(bundles[0] / 'Contents/MacOS', args.native_bridge_dir)
            subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-', str(bundles[0])], check=True)
        print(json.dumps(package_macos(output)))
        return 0
    if args.onefile:
        signing = sign_artifacts(output, args.sign_certificate, timestamp_url=args.timestamp_url or None,
                                 require=args.require_signature, names=['Buggcraft.exe'],
                                 thumbprint=args.sign_thumbprint, machine_store=args.sign_machine_store)
        (output / 'signing-status.json').write_text(json.dumps(signing, indent=2), encoding='utf-8')
    if not args.onefile:
        if args.native_bridge_dir:
            stage_native_bridge(output / 'main.dist', args.native_bridge_dir)
        removed = trim_qt_libraries(output / 'main.dist', output / 'qt-unused')
        (output / 'qt-trim-report.json').write_text(json.dumps(removed, indent=2), encoding='utf-8')
        runtime_binaries = [path.relative_to(output).as_posix()
                            for path in sorted((output / 'main.dist').rglob('*'))
                            if path.is_file() and path.suffix.lower() in ('.exe', '.dll', '.pyd')]
        signing = sign_artifacts(output, args.sign_certificate, timestamp_url=args.timestamp_url or None,
                                 require=args.require_signature, names=runtime_binaries,
                                 thumbprint=args.sign_thumbprint, machine_store=args.sign_machine_store)
        manifest, manifest_path = package_runtime(output / 'main.dist', output, args.runtime_url, pins)
        if os.name == 'nt':
            build_bootstrap(manifest_path, output)
            installer_signing = sign_artifacts(output, args.sign_certificate,
                timestamp_url=args.timestamp_url or None, require=args.require_signature,
                names=['Buggcraft-Setup.exe'], thumbprint=args.sign_thumbprint,
                machine_store=args.sign_machine_store)
            signing['artifacts'] = signing.get('artifacts', []) + installer_signing.get('artifacts', [])
            signing['signed'] = signing['signed'] and installer_signing['signed']
            signing.setdefault('hashes', {}).update(installer_signing.get('hashes', {}))
            signing['release_sha256'] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            signing['archive_sha256'] = manifest['sha256']
            (output / 'signing-status.json').write_text(json.dumps(signing, indent=2), encoding='utf-8')
        print(json.dumps({'runtime_zip_mb': round(manifest['size'] / 1_000_000, 2),
                          'installed_mb': round(sum(f['size'] for f in manifest['files']) / 1_000_000, 2),
                          'files': len(manifest['files']), 'download_urls': args.runtime_url}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
