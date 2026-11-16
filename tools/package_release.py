"""Package deployed native applications for the shared release/update service."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import zipfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', required=True)
    parser.add_argument('--executable', type=Path)
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--platform', default='windows-x64', choices=[
        'windows-x64', 'linux-x86_64', 'linux-arm64', 'macos-arm64', 'macos-x86_64'])
    parser.add_argument('--languages', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--migration-entry', action='append', default=[])
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = {'format': 1, 'version': args.version, 'platform': args.platform}
    bundle = args.output / f'Bugg-native-{args.platform}.zip'
    with zipfile.ZipFile(bundle, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        if args.directory:
            root = args.directory.resolve()
            executable = root / ('Contents/MacOS/bugg' if args.platform.startswith('macos-') else 'bugg')
            if not executable.is_file():
                raise ValueError('Deployed directory is missing its native executable')
            # Framework symlinks are represented as ordinary files. The shared
            # updater intentionally rejects links and preserves executable bits.
            for folder, directories, files in os.walk(root, followlinks=True):
                directories.sort()
                for name in sorted(files):
                    path = Path(folder) / name
                    if not path.resolve().is_relative_to(root):
                        raise ValueError('Deployment contains an external symbolic link')
                    archive.write(path, path.relative_to(root).as_posix())
        else:
            if not args.executable or args.platform != 'windows-x64':
                raise ValueError('Use --directory for a deployed macOS/Linux application')
            executable = args.executable
            archive.write(executable, 'bugg.exe')
            archive.write(executable, 'Buggcraft.exe')
            for entry in args.migration_entry:
                if Path(entry).name != entry or not entry.endswith('.exe'):
                    raise ValueError('Invalid historical executable entry')
                archive.write(executable, entry)
        archive.writestr('bugg-update.json', json.dumps(manifest) + '\n')
    (args.output / 'BUGGCRAFT_VERSION.txt').write_text(args.version + '\n', encoding='ascii')
    languages = list(args.languages.glob('Bugg-language-*.qm'))
    if not languages:
        raise ValueError('No language sidecars were built')
    for language in languages:
        shutil.copyfile(language, args.output / language.name)
    print(json.dumps({'version': args.version, 'platform': args.platform, 'executable_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
                      'bundle_sha256': hashlib.sha256(bundle.read_bytes()).hexdigest(), 'languages': len(languages)}))


if __name__ == '__main__':
    main()
