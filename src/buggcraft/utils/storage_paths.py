"""Portable launcher storage, resolved before importing Qt or settings."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import uuid

from utils.path_helper import get_launcher_directory

LOCATION = 'buggcraft-storage.txt'
PENDING = 'buggcraft-storage.pending'
ORIGIN = '.storage-origin.json'


def _read_location(name):
    launcher = get_launcher_directory()
    path = launcher / name
    if not path.is_file():
        return None
    value = path.read_text(encoding='utf-8-sig').strip()
    if not value or any(char in value for char in '\r\n\0') or len(value) > 4000:
        raise ValueError('启动器缓存位置文件无效：' + str(path))
    location = Path(value)
    return (location if location.is_absolute() else launcher / location).resolve()


def storage_root():
    return _read_location(LOCATION) or get_launcher_directory() / '.buggcraft'


def active_storage_root():
    # GUI tests and embedded callers may supply their own settings directory.
    settings = sys.modules.get('config.settings')
    manager = getattr(settings, '_settings_manager_instance', None)
    return Path(manager.config_path) if manager is not None else storage_root()


def cache_directory(*parts):
    path = active_storage_root().joinpath('cache', *parts)
    path.mkdir(parents=True, exist_ok=True)
    return path


def temporary_directory():
    path = active_storage_root() / 'temp'
    path.mkdir(parents=True, exist_ok=True)
    return path


def game_cache(directory):
    directory = Path(directory).resolve()
    launcher = get_launcher_directory()
    key = str(directory.relative_to(launcher)) if directory.is_relative_to(launcher) else str(directory)
    key = hashlib.sha256(os.path.normcase(key).encode('utf-8')).hexdigest()[:20]
    return cache_directory('downloads', key)


def publish_directory(source, target):
    """Publish an instance on its own volume when caches live on another drive."""
    import errno
    from utils.path_helper import filesystem_path
    source, target = filesystem_path(source), filesystem_path(target)
    if target.exists():
        raise FileExistsError('实例名称已被占用：' + target.name)
    try:
        source.rename(target)
        return
    except OSError as exc:
        if exc.errno != errno.EXDEV and getattr(exc, 'winerror', None) != 17:
            raise
    stage = target.parent / ('.buggcraft-publish-' + uuid.uuid4().hex)
    try:
        shutil.copytree(source, stage)
        if target.exists():
            raise FileExistsError('实例名称已被占用：' + target.name)
        stage.rename(target)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    shutil.rmtree(source, ignore_errors=True)


def _write_location(name, directory):
    launcher = get_launcher_directory()
    directory = Path(directory).resolve()
    value = str(directory.relative_to(launcher)) if directory.is_relative_to(launcher) else str(directory)
    target = launcher / name
    temporary = target.with_name(target.name + '.tmp')
    with temporary.open('w', encoding='utf-8', newline='\n') as stream:
        stream.write(value + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(target)


def pending_storage():
    return _read_location(PENDING)


def request_storage(directory):
    """Schedule a copy on the next launch; keep this process on its current root."""
    current, target = storage_root().resolve(), Path(directory).resolve()
    if current == target:
        (get_launcher_directory() / PENDING).unlink(missing_ok=True)
        return
    launcher = get_launcher_directory().resolve()
    if target == launcher or target.is_relative_to(current) or current.is_relative_to(target):
        raise ValueError('请选择独立的缓存文件夹，不能选择启动器根目录或当前缓存的上级、子目录。')
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ValueError('目标文件夹已有文件，请选择空文件夹，避免覆盖配置。')
    target.mkdir(parents=True, exist_ok=True)
    probe = target / ('.write-test-' + uuid.uuid4().hex)
    try:
        probe.write_bytes(b'')
    finally:
        probe.unlink(missing_ok=True)
    _write_location(PENDING, target)


def rebase_data(value, mappings):
    if isinstance(value, dict):
        return {rebase_data(key, mappings): rebase_data(item, mappings) for key, item in value.items()}
    if isinstance(value, list):
        return [rebase_data(item, mappings) for item in value]
    if isinstance(value, str):
        for old, new in mappings:
            if not old or str(old) == str(new):
                continue
            old = str(old).rstrip('/\\')
            normalized, prefix = os.path.normcase(value), os.path.normcase(old)
            if normalized == prefix or (normalized.startswith(prefix) and value[len(old):len(old) + 1] in ('/', '\\')):
                return str(new) + value[len(old):]
    return value


def _rebase_records(root, mappings):
    from utils.path_helper import filesystem_path
    root = filesystem_path(root)
    records = [root / 'settings.json', root / 'download_history.json', root / 'cache/auth_credentials.json']
    for folder in (root / 'etc', root / 'cache' / 'multiplayer'):
        if folder.is_dir():
            records.extend(folder.rglob('*.json'))
    for path in records:
        if not path.is_file() or path.is_symlink():
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (ValueError, UnicodeError):
            continue  # Preserve malformed files for the existing recovery UI.
        updated = rebase_data(data, mappings)
        if updated != data:
            temporary = path.with_name(path.name + '.relocate')
            temporary.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(path)


def initialize_storage():
    """Apply a requested migration and relocate records before any settings load."""
    from utils.path_helper import filesystem_path
    launcher = get_launcher_directory().resolve()
    current, requested = storage_root().resolve(), pending_storage()
    if requested and requested != current:
        requested = requested.resolve()
        if requested == launcher or requested.is_relative_to(current) or current.is_relative_to(requested):
            raise ValueError('缓存迁移目标与当前缓存目录重叠，原配置已保留。')
        requested.mkdir(parents=True, exist_ok=True)
        if any(item.name not in ('runtime', 'temp') for item in requested.iterdir()):
            raise ValueError('缓存迁移目标已有其他文件，原配置已保留，请清空目标或取消迁移。')
        stage = requested.parent / ('.buggcraft-migrate-' + uuid.uuid4().hex)
        published = []
        try:
            if current.exists():
                physical_source = filesystem_path(current)
                shutil.copytree(physical_source, filesystem_path(stage), symlinks=True,
                                ignore=lambda path, names: [name for name in names if
                                    Path(path) == physical_source and name in ('runtime', 'temp')])
            else:
                stage.mkdir()
            _rebase_records(stage, [(current, requested)])
            for item in stage.iterdir():
                item.rename(requested / item.name)
                published.append(item.name)
            _write_location(LOCATION, requested)
        except BaseException:
            for name in reversed(published):
                (requested / name).rename(stage / name)
            raise
        finally:
            if stage.exists():
                shutil.rmtree(filesystem_path(stage))
        (launcher / PENDING).unlink(missing_ok=True)
        current = requested
    elif requested:
        (launcher / PENDING).unlink(missing_ok=True)
    current.mkdir(parents=True, exist_ok=True)
    origin = current / ORIGIN
    if origin.exists():
        previous = json.loads(origin.read_text(encoding='utf-8'))
        _rebase_records(current, [(previous.get('storage'), current), (previous.get('launcher'), launcher)])
    origin.write_text(json.dumps(dict(launcher=str(launcher), storage=str(current))), encoding='utf-8')
    temporary = current / 'temp'
    temporary.mkdir(parents=True, exist_ok=True)
    for key in ('TEMP', 'TMP', 'TMPDIR'):
        os.environ[key] = str(temporary)
    for key, folder in (('QML_DISK_CACHE_PATH', 'qml'), ('QT_SHADER_CACHE_PATH', 'shaders')):
        destination = current / 'cache' / folder
        destination.mkdir(parents=True, exist_ok=True)
        os.environ[key] = str(destination)
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    sys.dont_write_bytecode = True
    tempfile.tempdir = str(temporary)
    return current
