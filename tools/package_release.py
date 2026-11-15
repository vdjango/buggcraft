"""Package the native Windows executable for the shared release/update service."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', required=True)
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--languages', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--migration-entry', action='append', default=[])
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = {'format': 1, 'version': args.version, 'platform': 'windows-x64'}
    bundle = args.output / 'Bugg-native-windows-x64.zip'
    with zipfile.ZipFile(bundle, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.write(args.executable, 'bugg.exe')
        archive.write(args.executable, 'Buggcraft.exe')
        for entry in args.migration_entry:
            if Path(entry).name != entry or not entry.endswith('.exe'):
                raise ValueError('Invalid historical executable entry')
            archive.write(args.executable, entry)
        archive.writestr('bugg-update.json', json.dumps(manifest) + '\n')
    (args.output / 'BUGGCRAFT_VERSION.txt').write_text(args.version + '\n', encoding='ascii')
    languages = list(args.languages.glob('Bugg-language-*.qm'))
    if not languages:
        raise ValueError('No language sidecars were built')
    for language in languages:
        shutil.copyfile(language, args.output / language.name)
    print(json.dumps({'version': args.version, 'executable_sha256': hashlib.sha256(args.executable.read_bytes()).hexdigest(),
                      'bundle_sha256': hashlib.sha256(bundle.read_bytes()).hexdigest(), 'languages': len(languages)}))


if __name__ == '__main__':
    main()
