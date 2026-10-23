"""Read local instance IDs without trusting a cached installation list."""
from pathlib import Path
import json
import logging

logger = logging.getLogger(__name__)


def installed_instance_ids(directory):
    if not directory:
        return []
    try:
        versions = Path(directory) / 'versions'
        result = []
        for folder in versions.iterdir():
            metadata = folder / (folder.name + '.json')
            if not folder.is_dir() or not metadata.is_file():
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
            if not game_dir.is_relative_to(root) or version not in installed_instance_ids(root):
                continue
            found.append((str(root), version, str(game_dir)))
        except (psutil.Error, IndexError, OSError, ValueError):
            continue
    return found
