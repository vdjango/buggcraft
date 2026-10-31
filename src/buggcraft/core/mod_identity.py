"""Identify a mod from bounded JAR metadata without extracting or running it."""
import json
import tomllib
from zipfile import BadZipFile, ZipFile


def jar_mods(path):
    """Return declared identities, independent of the archive's filename."""
    result = []
    try:
        with ZipFile(path) as archive:
            def read(name):
                try:
                    entry = archive.getinfo(name)
                except KeyError:
                    return ''
                if entry.file_size > 256 * 1024:
                    return ''
                data = archive.read(entry)
                try:
                    return data.decode('utf-8-sig')
                except UnicodeError:
                    try:
                        return data.decode('gb18030')
                    except UnicodeError:
                        return ''

            manifest = read('META-INF/MANIFEST.MF').replace('\r\n', '\n').replace('\n ', '')
            attributes = dict(line.split(': ', 1) for line in manifest.splitlines() if ': ' in line)

            def add(values, loader):
                if not isinstance(values, dict):
                    return
                identifier = values.get('modId') or values.get('modid') or values.get('id')
                version = values.get('version', '')
                if version == '${file.jarVersion}':
                    version = attributes.get('Implementation-Version', '')
                name = values.get('displayName') or values.get('name') or identifier
                if isinstance(identifier, str) and identifier and all(isinstance(item, str) for item in (name, version)):
                    identity = dict(id=identifier[:128], name=name[:200], version=version[:128], loader=loader)
                    if identity not in result:
                        result.append(identity)

            for filename, loader in (('META-INF/neoforge.mods.toml', 'NeoForge'), ('META-INF/mods.toml', 'Forge')):
                text = read(filename)
                if text:
                    try:
                        for mod in tomllib.loads(text).get('mods', []):
                            add(mod, loader)
                    except (ValueError, TypeError):
                        pass
            for filename, loader in (('fabric.mod.json', 'Fabric'), ('quilt.mod.json', 'Quilt'), ('mcmod.info', 'Forge')):
                text = read(filename)
                if not text:
                    continue
                try:
                    value = json.loads(text)
                    if filename == 'quilt.mod.json' and isinstance(value, dict):
                        value = value.get('quilt_loader', {})
                        value = dict(value, name=(value.get('metadata') or {}).get('name', value.get('id')))
                    if filename == 'mcmod.info' and isinstance(value, dict):
                        value = value.get('modList', [])
                    for mod in value if isinstance(value, list) else [value]:
                        add(mod, loader)
                except (ValueError, TypeError, AttributeError):
                    pass
    except (OSError, BadZipFile, RuntimeError, UnicodeError):
        pass
    return result
