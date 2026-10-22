"""Read bounded mod metadata and runtime evidence; never load or execute a mod."""
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import subprocess
import os
import tomllib
from zipfile import BadZipFile, ZipFile

METADATA = ('fabric.mod.json', 'quilt.mod.json', 'META-INF/mods.toml',
            'META-INF/neoforge.mods.toml', 'mcmod.info', 'META-INF/MANIFEST.MF')


def game_inventory(directory, java=None, version=None):
    root = Path(directory).resolve()
    result = {'schema': 1, 'collected_utc': datetime.now(timezone.utc).isoformat(),
              'directory': str(root), 'system': {'platform': platform.platform(),
                  'machine': platform.machine(), 'processor': platform.processor()},
              'mods': [], 'resourcepacks': [], 'shaderpacks': [],
              'version_metadata': [], 'errors': [],
              'notice': 'Mod metadata is read without executing JAR files. SHA-256 of all mods is not computed during export to avoid heavy disk load.'}
    try:
        import psutil
        result['system'].update(logical_cpus=psutil.cpu_count(), physical_cpus=psutil.cpu_count(logical=False),
                                memory_bytes=psutil.virtual_memory().total)
    except Exception as error:
        result['errors'].append({'component': 'system', 'error': type(error).__name__})
    if java:
        result['java'] = {'path': str(java)}
        try:
            run = subprocess.run([str(java), '-version'], capture_output=True, timeout=5,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            result['java'].update(returncode=run.returncode,
                                  version_output=(run.stdout + run.stderr)[:8192].decode('utf-8', errors='replace'))
        except (OSError, subprocess.TimeoutExpired) as error:
            result['java']['error'] = type(error).__name__
    metadata_budget = 8 * 1024 * 1024
    for group in ('mods', 'resourcepacks', 'shaderpacks'):
        folder = root / group
        if not folder.is_dir() or folder.is_symlink():
            continue
        for path in sorted(folder.iterdir(), key=lambda value: value.name.lower())[:5000]:
            if path.is_symlink():
                continue
            try:
                stat = path.stat()
                item = {'file': path.name, 'bytes': stat.st_size, 'modified_utc': datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                        'directory': path.is_dir()}
                if group == 'mods' and path.is_file() and path.suffix.lower() == '.jar':
                    item['metadata'] = {}
                    with ZipFile(path) as archive:
                        for name in METADATA:
                            try:
                                info = archive.getinfo(name)
                            except KeyError:
                                continue
                            if info.file_size > 256 * 1024 or info.file_size > metadata_budget:
                                item['metadata'][name] = {'skipped': 'Metadata exceeds 256 KiB per entry or 8 MiB total budget'}
                                continue
                            metadata_budget -= info.file_size
                            text = archive.read(info).decode('utf-8-sig', errors='replace')
                            try:
                                value = json.loads(text) if name.endswith(('.json', '.info')) else tomllib.loads(text) if name.endswith('.toml') else text
                            except (ValueError, tomllib.TOMLDecodeError):
                                value = text
                            item['metadata'][name] = value
                result[group].append(item)
            except (OSError, BadZipFile, RuntimeError) as error:
                result[group].append({'file': path.name, 'error': type(error).__name__ + ': ' + str(error)})
    # Installed isolated instances use versions/<id>/<id>.json; follow only safe inheritance names.
    current, seen = root, set()
    if (isinstance(version, str) and version not in ('', '.', '..') and not any(c in version for c in '/\\:')
            and (root / 'versions' / version).is_dir()):
        current = root / 'versions' / version
    versions = current.parent
    for _ in range(16):
        if current.name in seen:
            result['errors'].append({'component': 'version_metadata', 'error': 'Inheritance cycle'})
            break
        seen.add(current.name)
        path = current / (current.name + '.json')
        if not path.is_file() or path.is_symlink():
            break
        try:
            if path.stat().st_size > 2 * 1024 * 1024:
                raise ValueError('Version metadata exceeds 2 MiB')
            value = json.loads(path.read_text(encoding='utf-8-sig'))
            result['version_metadata'].append({'version': current.name, 'metadata': value})
            parent = value.get('inheritsFrom')
            if not parent:
                break
            if not isinstance(parent, str) or parent in ('.', '..') or any(c in parent for c in '/\\:'):
                raise ValueError('Unsafe inherited version')
            current = versions / parent
        except (OSError, ValueError, AttributeError) as error:
            result['errors'].append({'component': 'version_metadata', 'error': type(error).__name__ + ': ' + str(error)})
            break
    return result
