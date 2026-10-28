"""Verified content provenance shared by downloads, room sync and pack export."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading

_lock = threading.RLock()
_filename = '.buggcraft-content.json'


def read_records(directory):
    try:
        value = json.loads((Path(directory) / _filename).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    return [item for item in value if isinstance(item, dict) and isinstance(item.get('path'), str)] if isinstance(value, list) else []


def record_content(directory, path, downloads):
    root, path = Path(directory).resolve(), Path(path).resolve()
    relative = path.relative_to(root).as_posix()
    if relative.split('/')[0] not in ('mods', 'resourcepacks', 'shaderpacks'):
        return
    sha1, sha256 = hashlib.sha1(), hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            sha1.update(block)
            sha256.update(block)
    record = dict(path=relative, size=path.stat().st_size, sha1=sha1.hexdigest(),
                  sha256=sha256.hexdigest(), downloads=list(downloads))
    with _lock:
        records = {item['path'].casefold(): item for item in read_records(root)}
        records[relative.casefold()] = record
        descriptor, temporary = tempfile.mkstemp(prefix=_filename + '-', dir=root)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
                json.dump(list(records.values()), output, ensure_ascii=False, indent=2)
            os.replace(temporary, root / _filename)
        finally:
            Path(temporary).unlink(missing_ok=True)
