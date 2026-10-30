"""Read local instance IDs without trusting a cached installation list."""
from pathlib import Path
import hashlib
import json
import logging
import re
from utils.path_helper import filesystem_path

logger = logging.getLogger(__name__)


def lan_world_token(game_directory):
    """Identify a new LAN opening even when Minecraft reuses its fixed port."""
    if not game_directory:
        return None
    try:
        log = Path(game_directory) / 'logs/latest.log'
        with log.open('rb') as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - 131072))
            lines = stream.read().decode('utf-8', errors='replace').splitlines()
        for line in reversed(lines):
            match = re.search(r'(?:Started serving on|Local game hosted on port)\s+(\d{1,5})\b', line)
            if match and 0 < int(match[1]) <= 65535:
                return (int(match[1]), hashlib.sha256(line.encode('utf-8')).hexdigest())
    except OSError:
        pass
    return None


REMOVED_MARKER = '.buggcraft-removed'


def installed_instance_ids(directory, *, include_removed=False):
    if not directory:
        return []
    try:
        versions = filesystem_path(Path(directory) / 'versions')
        result = []
        for folder in versions.iterdir():
            metadata = folder / (folder.name + '.json')
            if not folder.is_dir() or not metadata.is_file():
                continue
            if not include_removed and (folder / REMOVED_MARKER).is_file():
                continue
            try:
                data = json.loads(metadata.read_text(encoding='utf-8-sig'))
                if not isinstance(data, dict):
                    raise ValueError('版本 JSON 必须为对象')
            except (OSError, ValueError) as exc:
                logger.warning('跳过无法读取的版本文件 %s: %s；其他版本仍可正常使用', metadata, exc)
                continue
            result.append(folder.name)
        return sorted(result, key=str.casefold)
    except OSError:
        return []


def running_games(directory):
    """Return runtime identities only; never retain or log account arguments."""
    if not directory:
        return []
    import psutil
    root = Path(directory).resolve()
    found = []
    for process in psutil.process_iter(['name']):
        if (process.info.get('name') or '').lower() not in ('java', 'java.exe', 'javaw', 'javaw.exe'):
            continue
        try:
            arguments = process.cmdline()
            if '--gameDir' not in arguments or '--version' not in arguments:
                continue
            game_dir = Path(arguments[arguments.index('--gameDir') + 1]).resolve()
            version = arguments[arguments.index('--version') + 1]
            if not game_dir.is_relative_to(root) or version not in installed_instance_ids(root, include_removed=True):
                continue
            found.append((str(root), version, str(game_dir)))
        except (psutil.Error, IndexError, OSError, ValueError):
            continue
    return found
