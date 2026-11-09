from enum import Enum
from pathlib import Path

import requests

from download.mirror import MirrorSource, DownloadMirror
from utils.http_identity import USER_AGENT
from utils.path_helper import get_default_minecraft_dir

# TODO MC 加载器安装，check有，分平台下载安装未写
class ModPlatform(Enum):
    """ 模组加载器枚举 """
    NEO = "neo"
    FORGE = "forge"
    FABRIC = "fabric"


class InstallCallback:
    """ 安装回调 """

    def __init__(self):
        self.status = ""
        self.progress = 0
        self.max_progress = 0

    def set_status(self, status: str):
        self.status = status
        print(f"模组加载器 状态: {status}")

    def set_progress(self, progress: int):
        """ 设置进度 """
        self.progress = progress
        if self.max_progress > 0:
            percent = (progress / self.max_progress) * 100
            print(f"模组加载器 安装进度 {progress}/{self.max_progress} ({percent:.1f}%)")

    def set_progress_max(self, progress: int):
        """ 进度条最大值 """
        self.max_progress = progress


class ModPlatformInstall:
    """ 模组加载器安装 """

    def __init__(self, platform: ModPlatform, game_dir: str | None = None, mirror: str | None = None,
                 callback: InstallCallback | None = None,
                 max_workers: int = 8):
        if game_dir is None:
            self.game_dir = get_default_minecraft_dir()
        else:
            self.game_dir = Path(game_dir)

        self.platform = platform
        self.source = DownloadMirror()

        if mirror is not None:
            self.source.set_source(mirror)
        self.callback = callback
        self.max_workers = max_workers

        self.install_check()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': USER_AGENT,
            'Accept': '*/*'
        })


    def install_check(self):
        """ 安装检查 """
        for directory in [self.game_dir / "versions", self.game_dir / "assets", self.game_dir / "libraries",
                          self.game_dir / "mods", self.game_dir / "natives"]:
            directory.mkdir(parents=True, exist_ok=True)

