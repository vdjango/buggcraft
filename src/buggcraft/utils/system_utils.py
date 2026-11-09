import hashlib
import platform
from enum import Enum
from pathlib import Path

# TODO 源码内还有不少相同调用函数需要替换成 utils 实现

class OSPlatform(Enum):
    """操作系统平台枚举"""
    WINDOWS = "windows"
    LINUX = "linux"
    OSX = "osx"
    UNKNOWN = "unknown"


def get_os() -> OSPlatform:
    """检测当前操作系统"""
    system = platform.system().lower()
    if system == "windows":
        return OSPlatform.WINDOWS
    elif system == "linux":
        return OSPlatform.LINUX
    elif system == "darwin":
        return OSPlatform.OSX
    else:
        return OSPlatform.UNKNOWN


def verify_file_sha1(self, filepath: Path, hash: str) -> bool:
    """验证文件SHA1哈希值"""
    if not filepath.exists():
        return False

    try:
        sha1 = hashlib.sha1()
        with open(filepath, 'rb') as f:
            while True:
                data = f.read(65536)
                if not data:
                    break
                sha1.update(data)

        return sha1.hexdigest() == hash.lower()
    except Exception:
        return False
