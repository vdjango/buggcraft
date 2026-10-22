"""Validate a downloaded archive before writing any member."""
from pathlib import Path
import stat


def extract_zip(archive, destination, max_expanded_bytes=2 * 1024 ** 3):
    root = Path(destination).resolve()
    members = archive.infolist()
    if len(members) > 50000 or sum(item.file_size for item in members) > max_expanded_bytes:
        raise ValueError('资源压缩包超过解压限制')
    for item in members:
        name = item.filename.replace('\\', '/')
        target = (root / name).resolve()
        if target != root and root not in target.parents:
            raise ValueError('压缩包包含越界路径')
        if ':' in name or stat.S_ISLNK(item.external_attr >> 16):
            raise ValueError('压缩包包含不允许的路径或符号链接')
    archive.extractall(root)
