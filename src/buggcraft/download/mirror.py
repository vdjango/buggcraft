import re
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from utils.http_identity import USER_AGENT
from utils.system_utils import verify_file_sha1, get_os, OSPlatform

# TODO Optifine 的镜像地址考虑一下要不要分平台进行特殊处理，或者开一个安装器下载类和Optifine一起涂加，目前主要是原版资源下载
@dataclass
class MirrorSource:
    Root: str
    Assets: str
    Libraries: str
    VersionManifest: str


@dataclass
class DownloadRequest:
    Url: str
    Path: Path
    Sha1: str


class DownloadMirror:
    """ 下资源配置 """

    def __init__(self, default: str = "BMCLAPI"):
        """ 默认自带源 """
        self.mirrors: dict[str, MirrorSource] = {
            "MOJANG": MirrorSource(
                Root="https://launchermeta.mojang.com",
                Assets="https://resources.download.minecraft.net",
                Libraries="https://libraries.minecraft.net",
                VersionManifest="https://launchermeta.mojang.com/mc/game/version_manifest_v2.json", ),
            "BMCLAPI": MirrorSource(
                Root="https://bmclapi2.bangbang93.com",
                Assets="https://bmclapi2.bangbang93.com/assets",
                Libraries="https://bmclapi2.bangbang93.com/maven",
                VersionManifest="https://bmclapi2.bangbang93.com/mc/game/version_manifest_v2.json"
            ),
            "MODRINTH": MirrorSource(
                Root="https://staging-api.modrinth.com/v2/tag/game_version",
                Assets="https://bmclapi2.bangbang93.com/assets",
                Libraries="https://bmclapi2.bangbang93.com/maven",
                VersionManifest="https://bmclapi2.bangbang93.com/mc/game/version_manifest_v2.json"
            ),
        }
        self.default = default
        # 会话对象用于保持连接
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': USER_AGENT,
            'Accept': '*/*'
        })

    def add_source(self, source: tuple[str, MirrorSource]) -> bool:
        """ 涂加自定义源 """
        if source[0] not in self.mirrors:
            self.mirrors[source[0]] = source[1]
            return True
        print("涂加重复的下载源")
        return False

    def remove_source(self, source_name: str) -> bool:
        """ 删除源 """
        if source_name in self.mirrors:
            del self.mirrors[source_name]
            return True
        print("下载源不存在")
        return False

    def get_source(self) -> MirrorSource:
        """ 获取默认源 """
        return self.mirrors[self.default]

    def get_all_sources(self) -> list[str]:
        """ 获取所有源名字 """
        return list(self.mirrors)

    def set_source(self, source_name: str) -> None:
        """ 设置默认源 """
        if source_name not in self.mirrors:
            print("设置失败，无效的源")
            return
        self.default = source_name

    def get_custom_source(self, source_name: str) -> None | MirrorSource:
        """ 获取指定源 """
        if source_name not in self.mirrors:
            print("无效的源")
            return None
        return self.mirrors[source_name]

    def download(self, request: DownloadRequest, max_retries: int) -> tuple[bool, str]:
        """ 下载文件，自动替换源，只支持bugjump标准url """
        # 检查文件是否已存在且完整
        if request.Path.exists():
            if request.Sha1 and verify_file_sha1(request.Path, request.Sha1):
                return True, "文件已存在且验证通过"
            elif not request.Sha1 and request.Path.stat().st_size > 0:
                return True, "文件已存在"

        # URL 换源
        source = self.get_source()
        patterns = [
            (
                re.compile(
                    r'https?://launchermeta(?:\.[A-Za-z0-9-]+)+'
                    r'(?::\d+)?(?=[:/?#]|$)',
                    re.IGNORECASE,
                ),
                source.Root,
            ),
            (
                re.compile(
                    r'https?://resources(?:\.[A-Za-z0-9-]+)+'
                    r'(?::\d+)?(?=[:/?#]|$)',
                    re.IGNORECASE,
                ),
                source.Assets,
            ),
            (
                re.compile(
                    r'https?://libraries(?:\.[A-Za-z0-9-]+)+'
                    r'(?::\d+)?(?=[:/?#]|$)',
                    re.IGNORECASE,
                ),
                source.Libraries,
            ),
        ]

        for pattern, mirror in patterns:
            mirror = mirror.rstrip("/")

            request.Url, count = pattern.subn(
                mirror,
                request.Url,
                count=1,
            )

            if count:
                break

        # 开始下载
        for attempt in range(max_retries):
            try:
                # 确保目录存在
                request.Path.parent.mkdir(parents=True, exist_ok=True)

                response = self.session.get(request.Url, stream=True, timeout=30)
                response.raise_for_status()

                # 临时文件路径
                temp_path = request.Path.with_suffix('.download')

                # 下载到临时文件
                with open(temp_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)

                # 验证文件完整性
                if request.Sha1 and not verify_file_sha1(temp_path, request.Sha1):
                    raise Exception(f"SHA1哈希不匹配: 预期 {request.Sha1}")

                # 重命名为最终文件
                if get_os() == OSPlatform.WINDOWS:
                    # Windows上可能需要先删除已存在的文件
                    if request.Path.exists():
                        request.Path.unlink()
                temp_path.rename(request.Path)
                return True, "下载成功"
            except requests.exceptions.RequestException as e:
                print(f"下载失败 ({attempt + 1}/{max_retries}): {e}")

            except Exception as e:
                print(f"下载错误: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2)
        return False, f"所有下载尝试均失败: {request.Url}"

    def get_manifest(self) -> dict:
        response = self.session.get(self.get_source().VersionManifest, timeout=30)
        response.raise_for_status()
        return response.json()

    def get_version_data(self, version_id: str) -> dict | None:
        """ Dict 成功获取 Exception 内部错误 None 获取为空"""
        manifest = self.get_manifest()
        if not manifest:
            return None

        # 查找版本URL
        version_url: str | None = None
        for version in manifest.get("versions", []):
            if version["id"] == version_id:
                version_url = version["url"]
                break

        if not version_url:
            return None

        try:
            response = self.session.get(version_url, timeout=30)
            response.raise_for_status()
            return response.json()
        # TODO Error 未处理
        except Exception as e:
            return e
