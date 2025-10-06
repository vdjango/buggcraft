import os
import sys
import json
import time
import hashlib
import requests
import platform
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
from enum import Enum
from core.optifine import OptiFineInstaller


class MirrorSource(Enum):
    """下载源枚举"""
    MOJANG = "mojang"
    BMCLAPI = "bmclapi"


class OSPlatform(Enum):
    """操作系统平台枚举"""
    WINDOWS = "windows"
    LINUX = "linux"
    OSX = "osx"
    UNKNOWN = "unknown"


class InstallerCallback:
    """安装回调类，用于报告进度和状态"""
    def __init__(self):
        self.status = ""
        self.progress = 0
        self.max_progress = 0
    
    def set_status(self, status: str):
        """设置状态信息"""
        self.status = status
        print(f"状态: {status}")
    
    def set_progress(self, progress: int):
        """设置进度"""
        self.progress = progress
        if self.max_progress > 0:
            percent = (progress / self.max_progress) * 100
            print(f"进度: {progress}/{self.max_progress} ({percent:.1f}%)")
    
    def set_max(self, max_value: int):
        """设置最大值"""
        self.max_progress = max_value


class CrossPlatformMinecraftInstaller:
    """Minecraft安装器"""
    
    # 支持的下载源配置
    MIRRORS = {
        MirrorSource.MOJANG: {
            "root": "https://launchermeta.mojang.com",
            "assets": "https://resources.download.minecraft.net",
            "libraries": "https://libraries.minecraft.net",
            "version_manifest": "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json"
        },
        MirrorSource.BMCLAPI: {
            "root": "https://bmclapi2.bangbang93.com",
            "assets": "https://bmclapi2.bangbang93.com/assets",
            "libraries": "https://bmclapi2.bangbang93.com/maven",
            "version_manifest": "https://bmclapi2.bangbang93.com/mc/game/version_manifest_v2.json"
        }
    }
    
    def __init__(self, game_dir: str = None, mirror: MirrorSource = MirrorSource.BMCLAPI, 
                 max_workers: int = 8, callback: InstallerCallback = None):
        # 确定Minecraft目录
        if game_dir is None:
            self.game_dir = self.get_default_minecraft_dir()
        else:
            self.game_dir = Path(game_dir)
        
        self.mirror = mirror
        self.max_workers = max_workers
        self.callback = callback if callback else InstallerCallback()
        self.mirror_config = self.MIRRORS[mirror]
        
        # 检测当前操作系统
        self.current_os = self.detect_os()
        
        # 创建必要的目录结构
        self.versions_dir = self.game_dir / "versions"
        self.assets_dir = self.game_dir / "assets"
        self.libraries_dir = self.game_dir / "libraries"
        self.mods_dir = self.game_dir / "mods"
        self.natives_dir = self.game_dir / "natives"
        
        for directory in [self.versions_dir, self.assets_dir, self.libraries_dir, 
                         self.mods_dir, self.natives_dir]:
            directory.mkdir(parents=True, exist_ok=True)
        
        # 会话对象用于保持连接
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': f'MinecraftLauncher/1.0 ({self.current_os.value})',
            'Accept': '*/*'
        })
    
    def detect_os(self) -> OSPlatform:
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
    
    def get_default_minecraft_dir(self) -> Path:
        """获取默认Minecraft目录（跨平台）"""
        system = platform.system()
        if system == "Windows":
            return Path(os.environ.get('APPDATA', '')) / ".minecraft"
        elif system == "Darwin":  # macOS
            return Path.home() / "Library" / "Application Support" / "minecraft"
        else:  # Linux和其他Unix系统
            return Path.home() / ".minecraft"
    
    def set_mirror(self, mirror: MirrorSource):
        """设置下载源"""
        self.mirror = mirror
        self.mirror_config = self.MIRRORS[mirror]
    
    def download_file(self, url: str, filepath: Path, expected_sha1: str = None, 
                     max_retries: int = 3) -> Tuple[bool, str]:
        """
        下载文件并验证完整性
        参考minecraft-launcher-lib的下载逻辑
        """
        # 检查文件是否已存在且完整
        if filepath.exists():
            if expected_sha1 and self.verify_file_sha1(filepath, expected_sha1):
                return True, "文件已存在且验证通过"
            elif not expected_sha1 and filepath.stat().st_size > 0:
                return True, "文件已存在"
        
        # 尝试多个备用源
        sources = self.get_alternate_sources(url)
        
        for source_url in sources:
            for attempt in range(max_retries):
                try:
                    # 确保目录存在
                    filepath.parent.mkdir(parents=True, exist_ok=True)
                    
                    # 下载文件
                    response = self.session.get(source_url, stream=True, timeout=30)
                    response.raise_for_status()
                    
                    # 临时文件路径
                    temp_path = filepath.with_suffix('.download')
                    
                    # 下载到临时文件
                    with open(temp_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                    
                    # 验证文件完整性
                    if expected_sha1 and not self.verify_file_sha1(temp_path, expected_sha1):
                        raise Exception(f"SHA1哈希不匹配: 预期 {expected_sha1}")
                    
                    # 重命名为最终文件
                    if sys.platform == "win32":
                        # Windows上可能需要先删除已存在的文件
                        if filepath.exists():
                            filepath.unlink()
                    temp_path.rename(filepath)
                    return True, "下载成功"
                    
                except requests.exceptions.RequestException as e:
                    error_msg = f"下载失败 ({attempt+1}/{max_retries}): {e}"
                    if attempt < max_retries - 1:
                        time.sleep(2)  # 重试前等待
                except Exception as e:
                    error_msg = f"下载错误: {e}"
                    if attempt < max_retries - 1:
                        time.sleep(2)
        
        return False, f"所有下载尝试均失败: {url}"
    
    def get_alternate_sources(self, original_url: str) -> List[str]:
        """获取备用下载源列表"""
        sources = [original_url]
        
        # 如果是Mojang官方URL，替换为镜像源
        if "launchermeta.mojang.com" in original_url:
            sources.append(original_url.replace(
                "https://launchermeta.mojang.com",
                self.mirror_config["root"]
            ))
        elif "resources.download.minecraft.net" in original_url:
            sources.append(original_url.replace(
                "https://resources.download.minecraft.net",
                self.mirror_config["assets"]
            ))
        elif "libraries.minecraft.net" in original_url:
            sources.append(original_url.replace(
                "https://libraries.minecraft.net",
                self.mirror_config["libraries"]
            ))
        
        return sources
    
    def verify_file_sha1(self, filepath: Path, expected_hash: str) -> bool:
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
            
            return sha1.hexdigest() == expected_hash.lower()
        except Exception:
            return False
    
    def get_version_manifest(self) -> Optional[Dict]:
        """获取版本清单"""
        try:
            self.callback.set_status("获取版本清单")
            response = self.session.get(self.mirror_config["version_manifest"], timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.callback.set_status(f"获取版本清单失败: {e}")
            return None
    
    def get_version_data(self, version_id: str) -> Optional[Dict]:
        """获取特定版本的详细数据"""
        manifest = self.get_version_manifest()
        if not manifest:
            return None
        
        # 查找版本URL
        version_url = None
        for version in manifest.get("versions", []):
            if version["id"] == version_id:
                version_url = version["url"]
                break
        
        if not version_url:
            self.callback.set_status(f"未找到版本: {version_id}")
            return None
        
        # 替换URL中的源
        if self.mirror != MirrorSource.MOJANG:
            version_url = version_url.replace(
                "https://launchermeta.mojang.com",
                self.mirror_config["root"]
            )
        
        try:
            self.callback.set_status(f"获取版本 {version_id} 数据")
            response = self.session.get(version_url, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.callback.set_status(f"获取版本数据失败: {e}")
            return None
    
    def install_version(self, version_id: str) -> bool:
        """安装Minecraft版本"""
        self.callback.set_status(f"开始安装 Minecraft {version_id}")
        
        # 获取版本数据
        version_data = self.get_version_data(version_id)
        if not version_data:
            return False
        
        # 处理版本继承（Forge等）
        if "inheritsFrom" in version_data:
            parent_version = version_data["inheritsFrom"]
            self.callback.set_status(f"安装父版本: {parent_version}")
            if not self.install_version(parent_version):
                return False
            
            # 合并版本数据（简化版）
            parent_path = self.versions_dir / parent_version / f"{parent_version}.json"
            if parent_path.exists():
                with open(parent_path, 'r', encoding='utf-8') as f:
                    parent_data = json.load(f)
                
                # 合并库和资源
                if "libraries" in parent_data:
                    version_data["libraries"] = parent_data["libraries"] + version_data.get("libraries", [])
        
        # 创建版本目录
        version_dir = self.versions_dir / version_id
        version_dir.mkdir(exist_ok=True)
        
        # 保存版本JSON
        version_json_path = version_dir / f"{version_id}.json"
        with open(version_json_path, 'w', encoding='utf-8') as f:
            json.dump(version_data, f, indent=2, ensure_ascii=False)
        
        # 下载各个组件
        components = [
            ("客户端JAR", self._download_client_jar, [version_data, version_id]),
            ("资源文件", self._download_assets, [version_data]),
            ("依赖库", self._download_libraries, [version_data]),
            ("日志配置", self._download_logging_config, [version_data]),
        ]
        
        success_count = 0
        for name, func, args in components:
            self.callback.set_status(f"-安装{name}")
            try:
                if func(*args):
                    success_count += 1
                    self.callback.set_status(f"+{name}安装成功")
                else:
                    self.callback.set_status(f"{name}安装失败")
            except Exception as e:
                self.callback.set_status(f"{name}安装错误: {e}")
        
        # 提取原生库
        if self._extract_natives(version_data, version_id):
            success_count += 1
        
        if success_count == len(components) + 1:  # +1 for natives
            self.callback.set_status(f"Minecraft {version_id} 安装完成")
            return True
        else:
            self.callback.set_status(f"Minecraft {version_id} 安装部分成功 ({success_count}/{len(components)+1})")
            return False
    
    def _download_client_jar(self, version_data: Dict, version_id: str) -> bool:
        """下载客户端JAR文件"""
        downloads = version_data.get("downloads", {})
        client_download = downloads.get("client")
        if not client_download:
            self.callback.set_status("未找到客户端下载信息")
            return False
        
        client_url = client_download["url"]
        if self.mirror != MirrorSource.MOJANG:
            client_url = client_url.replace(
                "https://launcher.mojang.com",
                self.mirror_config["root"]
            )
        
        client_jar_path = self.versions_dir / version_id / f"{version_id}.jar"
        success, message = self.download_file(
            client_url, client_jar_path, expected_sha1=client_download.get("sha1")
        )
        
        if not success:
            self.callback.set_status(f"客户端JAR下载失败: {message}")
        return success
    
    def _download_assets(self, version_data: Dict) -> bool:
        """下载资源文件"""
        asset_index = version_data.get("assetIndex")
        if not asset_index:
            return True
        
        # 下载资源索引
        index_url = asset_index["url"]
        if self.mirror != MirrorSource.MOJANG:
            index_url = index_url.replace(
                "https://launchermeta.mojang.com",
                self.mirror_config["root"]
            )
        
        index_path = self.assets_dir / "indexes" / f"{asset_index['id']}.json"
        success, message = self.download_file(
            index_url, index_path, expected_sha1=asset_index.get("sha1")
        )
        
        if not success:
            self.callback.set_status(f"资源索引下载失败: {message}")
            return False
        
        # 读取资源索引
        try:
            with open(index_path, 'r', encoding='utf-8') as f:
                assets_data = json.load(f)
        except Exception as e:
            self.callback.set_status(f"解析资源索引失败: {e}")
            return False
        
        # 并行下载所有资源对象
        objects = assets_data.get("objects", {})
        download_tasks = []
        
        for asset_name, asset_info in objects.items():
            hash_value = asset_info["hash"]
            asset_url = f"{self.mirror_config['assets']}/{hash_value[:2]}/{hash_value}"
            asset_path = self.assets_dir / "objects" / hash_value[:2] / hash_value
            
            # 检查文件是否已存在
            if not asset_path.exists() or not self.verify_file_sha1(asset_path, hash_value):
                download_tasks.append((asset_url, asset_path, hash_value))
        
        if not download_tasks:
            return True
        
        self.callback.set_status(f"开始下载 {len(download_tasks)} 个资源文件")
        self.callback.set_max(len(download_tasks))
        
        success_count = 0
        
        def download_asset(task):
            url, path, expected_hash = task
            return self.download_file(url, path, expected_sha1=expected_hash)[0]
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = [executor.submit(download_asset, task) for task in download_tasks]
            for i, future in enumerate(as_completed(futures)):
                if future.result():
                    success_count += 1
                self.callback.set_progress(i + 1)
        
        self.callback.set_status(f"资源下载完成: {success_count}/{len(download_tasks)} 成功")
        return success_count > len(download_tasks) * 0.95  # 允许5%的失败率
    
    def _download_libraries(self, version_data: Dict) -> bool:
        """下载依赖库"""
        libraries = version_data.get("libraries", [])
        download_tasks = []
        
        for library in libraries:
            # 检查库规则
            rules = library.get("rules", [])
            if rules and not self._check_library_rules(rules):
                continue
            
            # 优先使用downloads中的信息
            downloads = library.get("downloads", {})
            artifact = downloads.get("artifact")
            if artifact:
                library_url = artifact["url"]
                library_path = self.libraries_dir / artifact["path"]
                expected_sha1 = artifact.get("sha1")
            else:
                # 回退到传统方式构建URL
                name_parts = library["name"].split(":")
                if len(name_parts) < 3:
                    continue
                
                group, artifact_name, version = name_parts[0:3]
                group_path = group.replace(".", "/")
                filename = f"{artifact_name}-{version}.jar"
                
                library_url = f"{self.mirror_config['libraries']}/{group_path}/{artifact_name}/{version}/{filename}"
                library_path = self.libraries_dir / group_path / artifact_name / version / filename
                expected_sha1 = None
            
            # 检查文件是否已存在
            if not library_path.exists() or (expected_sha1 and not self.verify_file_sha1(library_path, expected_sha1)):
                download_tasks.append((library_url, library_path, expected_sha1))
        
        if not download_tasks:
            return True
        
        self.callback.set_status(f"开始下载 {len(download_tasks)} 个依赖库")
        self.callback.set_max(len(download_tasks))
        
        success_count = 0
        
        def download_library(task):
            url, path, expected_hash = task
            return self.download_file(url, path, expected_sha1=expected_hash)[0]
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = [executor.submit(download_library, task) for task in download_tasks]
            for i, future in enumerate(as_completed(futures)):
                if future.result():
                    success_count += 1
                self.callback.set_progress(i + 1)
        
        self.callback.set_status(f"依赖库下载完成: {success_count}/{len(download_tasks)} 成功")
        return success_count == len(download_tasks)
    
    def _download_logging_config(self, version_data: Dict) -> bool:
        """下载日志配置"""
        logging_config = version_data.get("logging", {})
        if not logging_config:
            return True
        
        client_logging = logging_config.get("client", {})
        if not client_logging:
            return True
        
        file_info = client_logging.get("file", {})
        if not file_info:
            return True
        
        logger_url = file_info.get("url")
        logger_path = self.assets_dir / "log_configs" / file_info.get("id")
        expected_sha1 = file_info.get("sha1")
        
        if logger_url:
            success, message = self.download_file(logger_url, logger_path, expected_sha1)
            if not success:
                self.callback.set_status(f"日志配置下载失败: {message}")
            return success
        
        return True
    
    def _extract_natives(self, version_data: Dict, version_id: str) -> bool:
        """提取原生库文件 - 基于库名称识别"""
        # 清理之前的原生文件
        natives_dir = self.natives_dir / version_id
        if natives_dir.exists():
            import shutil
            shutil.rmtree(natives_dir)
        natives_dir.mkdir(parents=True, exist_ok=True)
        
        # 查找需要提取的原生库
        libraries = version_data.get("libraries", [])
        extracted_count = 0
        
        for library in libraries:
            # 检查库规则
            rules = library.get("rules", [])
            if rules and not self._check_library_rules(rules):
                continue
            
            # 获取库名称
            name = library.get("name", "")
            if not name:
                continue
                
            # 检查是否是原生库（基于命名约定）
            is_native = False
            platform_key = ""
            
            if self.current_os == OSPlatform.WINDOWS and "natives-windows" in name:
                is_native = True
                platform_key = "natives-windows"
            elif self.current_os == OSPlatform.LINUX and "natives-linux" in name:
                is_native = True
                platform_key = "natives-linux"
            elif self.current_os == OSPlatform.OSX and ("natives-osx" in name or "natives-macos" in name):
                is_native = True
                platform_key = "natives-osx"
            
            if not is_native:
                continue
                
            # 获取下载信息
            downloads = library.get("downloads", {})
            artifact = downloads.get("artifact")
            if not artifact:
                continue
                
            # 下载原生库文件
            native_url = artifact["url"]
            native_path = self.libraries_dir / artifact["path"]
            
            # 确保目录存在
            native_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 下载文件
            success, message = self.download_file(native_url, native_path, artifact.get("sha1"))
            
            if success and native_path.exists():
                # 提取原生文件
                if self._extract_native_file(native_path, natives_dir):
                    extracted_count += 1
        
        return extracted_count > 0

    def _extract_native_file(self, archive_path: Path, target_dir: Path) -> bool:
        """提取原生库文件 - 使用默认排除规则"""
        try:
            import zipfile
            
            # 默认排除规则（来自Minecraft启动器）
            exclude_patterns = ["META-INF/"]
            
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                for file_info in zip_ref.infolist():
                    file_name = file_info.filename
                    
                    # 检查是否在排除列表中
                    excluded = any(file_name.startswith(pattern) for pattern in exclude_patterns)
                    if excluded:
                        continue
                    
                    # 提取文件
                    zip_ref.extract(file_name, target_dir)
                    
                    # 在Unix系统上设置可执行权限
                    if self.current_os != OSPlatform.WINDOWS and file_name.endswith(('.so', '.dylib')):
                        extracted_file = target_dir / file_name
                        extracted_file.chmod(0o755)  # 设置可执行权限
            
            return True
        except Exception as e:
            print(f"提取原生文件失败: {e}")
            return False
    
    def _check_library_rules(self, rules: List[Dict]) -> bool:
        """检查库规则"""
        allow = False
        
        for rule in rules:
            action = rule.get("action", "allow")
            os_info = rule.get("os", {})
            
            # 检查操作系统规则
            if os_info:
                os_name = os_info.get("name")
                if os_name and os_name != self.current_os.value:
                    continue
                
                # 检查架构规则（如果有）
                arch = os_info.get("arch")
                if arch and arch != platform.machine():
                    continue
            
            # 检查其他规则（如特征）
            features = rule.get("features", {})
            if features:
                # 这里可以添加更复杂的特征检查
                continue
            
            # 如果规则匹配，设置允许状态
            allow = (action == "allow")
        
        return allow
    
    def _backup_original_version(self, mc_version: str) -> Optional[Dict]:
        """备份原始版本 JSON"""
        original_dir = self.game_dir / mc_version
        original_json_path = original_dir / f"{mc_version}.json"
        
        if not original_json_path.exists():
            print(f"警告: 找不到原始版本 JSON: {original_json_path}")
            return None
        
        try:
            with open(original_json_path, 'r', encoding='utf-8') as f:
                original_data = json.load(f)
            print(f"已备份原始版本 JSON: {mc_version}")
            return original_data
        except Exception as e:
            print(f"读取原始版本 JSON 失败: {e}")
            return None
    
    def _fix_version_json(self, minecraft_dir, mc_version, forge_version, original_version):
        minecraft_forge_version_path: Path = Path(minecraft_dir) / mc_version / f"{mc_version}-forge-{forge_version}.json"  # 1.20.1-forge-47.0.1
        print('_fix_version_json.minecraft_forge_version_path', minecraft_forge_version_path)
        if not minecraft_forge_version_path.exists():
            print(f"❌ 版本 JSON 不存在: {minecraft_forge_version_path}")
            return
        
        # 读取当前 JSON
        with open(minecraft_forge_version_path, 'r', encoding='utf-8') as f:
            forge_data = json.load(f)
                
    def merge_minecraft_version(self, vanilla_data: Dict[str, Any], forge_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        合并原版与Forge版的 version.json，生成独立可启动的版本配置。
        
        Args:
            vanilla_data: 原版版本JSON数据
            forge_data: Forge版版本JSON数据
        
        Returns:
            合并后的版本JSON数据
        """
        # 创建基础合并结果，以forge数据为基底
        merged_data = forge_data.copy()
        
        # 1. 处理核心标识字段
        # 保留原版ID并在其后标注Forge，明确版本来源
        if 'id' in vanilla_data:
            merged_data['id'] = f"{vanilla_data['id']}-forge-{forge_data.get('id', 'unknown').split('-')[-1]}"
        
        # 移除inheritsFrom，确保独立性
        merged_data.pop('inheritsFrom', None)
        
        # 2. 合并libraries（关键步骤）
        # 确保libraries字段存在
        if 'libraries' not in merged_data:
            merged_data['libraries'] = []
        
        # 添加原版的libraries（避免重复）
        vanilla_libraries = vanilla_data.get('libraries', [])
        merged_library_names = {lib['name'] if isinstance(lib, dict) else lib for lib in merged_data['libraries']}
        
        for lib in vanilla_libraries:
            lib_name = lib['name'] if isinstance(lib, dict) else lib
            if lib_name not in merged_library_names:
                merged_data['libraries'].append(lib)
                merged_library_names.add(lib_name)
        
        # 3. 合并arguments（游戏与JVM参数）
        # 处理游戏参数
        if 'arguments' in merged_data and 'arguments' in vanilla_data:
            merged_game_args = merged_data['arguments'].get('game', [])
            vanilla_game_args = vanilla_data['arguments'].get('game', [])
            
            # 合并时去重
            for arg in vanilla_game_args:
                if arg not in merged_game_args:
                    merged_game_args.append(arg)
            merged_data['arguments']['game'] = merged_game_args
            
            # 合并JVM参数
            merged_jvm_args = merged_data['arguments'].get('jvm', [])
            vanilla_jvm_args = vanilla_data['arguments'].get('jvm', [])
            
            for arg in vanilla_jvm_args:
                if arg not in merged_jvm_args:
                    merged_jvm_args.append(arg)
            merged_data['arguments']['jvm'] = merged_jvm_args
        
        # 4. 确保关键下载项存在
        # 若合并后数据缺少核心客户端jar信息，尝试从原版数据补充
        if 'downloads' not in merged_data and 'downloads' in vanilla_data:
            merged_data['downloads'] = vanilla_data['downloads'].copy()
        elif 'downloads' in merged_data and 'downloads' in vanilla_data:
            if 'client' not in merged_data['downloads'] and 'client' in vanilla_data['downloads']:
                merged_data['downloads']['client'] = vanilla_data['downloads']['client']
        
        # 5. 资源索引指向
        # 确保assets配置正确
        if 'assets' not in merged_data and 'assets' in vanilla_data:
            merged_data['assets'] = vanilla_data['assets']
        
        if 'assetIndex' not in merged_data and 'assetIndex' in vanilla_data:
            merged_data['assetIndex'] = vanilla_data['assetIndex']
        
        return merged_data

    def create_merged_version(self, mc_version: str, forge_version: str):
        """
        从文件读取原版和Forge版JSON，合并后保存到新文件。
        """
        vanilla_json_path: Path = Path(minecraft_dir) / 'versions' / mc_version / f"{mc_version}.json"
        forge_json_path: Path = Path(minecraft_dir) / 'versions' / f"{mc_version}-forge-{forge_version}" / f"{mc_version}-forge-{forge_version}.json"  # 1.20.1-forge-47.0.1
        print('create_merged_version.vanilla_json_path', vanilla_json_path)
        print('create_merged_version.forge_json_path', forge_json_path)
        if not vanilla_json_path.exists():
            print(f"❌ 原版 JSON 不存在: {vanilla_json_path}")
            return
        if not forge_json_path.exists():
            print(f"❌ Forge版 JSON 不存在: {forge_json_path}")
            return
        
        try:
            # 读取原版JSON
            with open(vanilla_json_path, 'r', encoding='utf-8') as f:
                vanilla_data = json.load(f)
            
            # 读取Forge版JSON
            with open(forge_json_path, 'r', encoding='utf-8') as f:
                forge_data = json.load(f)
            
            # 合并数据
            merged_data = self.merge_minecraft_version(vanilla_data, forge_data)
            
            # 保存合并后的JSON
            with open(forge_json_path, 'w', encoding='utf-8') as f:
                json.dump(merged_data, f, indent=2, ensure_ascii=False)
            
            print(f"✅ 版本合并完成！输出文件：{forge_json_path}")
            return True
        
        except Exception as e:
            print(f"❌ 合并过程中出错：{e}")
            return False
    
    def install_forge(self, mc_version: str, forge_version: str) -> bool:
        """安装Forge模组加载器"""
        # 获取Minecraft目录（绝对路径）
        minecraft_dir = Path(self.game_dir).resolve()  # 确保是绝对路径
        self.callback.set_status(f"Minecraft目录: {minecraft_dir}")

        with open(minecraft_dir / 'launcher_profiles.json', 'w', encoding='utf-8') as f:
            json.dump({
                "selectedProfile": "(Default)",
                "profiles": {
                    "(Default)": {"name": "(Default)"}
                },
                "clientToken": "88888888-8888-8888-8888-888888888888"
            }, f, indent=2, ensure_ascii=False)
        
        self.callback.set_status(f"安装Forge {mc_version}-{forge_version}")
        
        # 构建Forge安装器URL
        forge_installer_url = (
            f"{self.mirror_config['libraries']}/net/minecraftforge/forge/"
            f"{mc_version}-{forge_version}/forge-{mc_version}-{forge_version}-installer.jar"
        )
        
        # 下载安装器
        installer_path = self.game_dir / "forge-installer.jar"
        success, message = self.download_file(forge_installer_url, installer_path)
        
        if not success:
            self.callback.set_status(f"Forge安装器下载失败: {message}")
            return False
        
        # 运行Forge安装器
        try:
            # 获取Java路径
            java_path = self._find_java_executable()
            if not java_path:
                self.callback.set_status("未找到Java运行时环境")
                return False
            
            # 构建安装命令
            install_cmd = [
                java_path,
                "-jar", str(installer_path),
                f"--installClient",
                str(minecraft_dir)  # 添加--installDir参数
            ]
            
            # 5. 运行安装器并捕获输出
            success = self._run_installer(install_cmd, installer_path)
            
            # 6. 多版本合并 version.json 文件，只保留forge
            if success:
                self.create_merged_version(mc_version, forge_version)
            return success
           
        except Exception as e:
            self.callback.set_status(f"运行Forge安装器错误: {e}")
            return False
        finally:
            # 清理安装器文件
            # if installer_path.exists():
            #     installer_path.unlink()
            pass
    
    def _run_installer(self, install_cmd: list, installer_path: Path) -> bool:
        """运行 Forge 安装器并捕获输出"""
        self.callback.set_status("运行 Forge 安装器...")
        
        try:
            # 启动进程
            process = subprocess.Popen(
                install_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # 将 stderr 合并到 stdout
                universal_newlines=True,
                bufsize=1
            )
            
            # 实时读取输出
            output_lines = []
            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                if line:
                    output_lines.append(line.strip())
                    self.callback.set_status(f"Forge安装器: {line.strip()}")
            
            # 等待进程结束
            return_code = process.wait()
            
            # 记录完整输出
            full_output = "\n".join(output_lines)
            self.callback.set_status(f"Forge安装器完整输出:\n{full_output}")
            
            if return_code == 0:
                self.callback.set_status("Forge 安装成功")
                return True
            else:
                self.callback.set_status(f"Forge 安装失败，退出代码: {return_code}")
                return False
                
        except subprocess.TimeoutExpired:
            self.callback.set_status("Forge 安装超时")
            return False
        except Exception as e:
            self.callback.set_status(f"运行 Forge 安装器时出错: {str(e)}")
            return False
        finally:
            # 清理安装器文件
            try:
                if installer_path.exists():
                    # installer_path.unlink()
                    self.callback.set_status("已清理安装器文件")
            except Exception as e:
                self.callback.set_status(f"清理安装器文件时出错: {str(e)}")
    
    def _find_java_executable(self) -> Optional[str]:
        """查找Java可执行文件路径（跨平台）"""
        # 首先尝试检查JAVA_HOME环境变量
        java_home = os.environ.get('JAVA_HOME')
        if java_home:
            if self.current_os == OSPlatform.WINDOWS:
                java_path = Path(java_home) / "bin" / "java.exe"
            else:
                java_path = Path(java_home) / "bin" / "java"
            
            if java_path.exists():
                return str(java_path)
        
        # 尝试在PATH中查找java
        java_executable = "java.exe" if self.current_os == OSPlatform.WINDOWS else "java"
        try:
            # 使用which/where命令查找java
            if self.current_os == OSPlatform.WINDOWS:
                result = subprocess.run(["where", java_executable], capture_output=True, text=True)
            else:
                result = subprocess.run(["which", java_executable], capture_output=True, text=True)
            
            if result.returncode == 0:
                return result.stdout.strip().split('\n')[0]  # 返回第一个找到的java路径
        except Exception:
            pass
        
        # 最后尝试一些常见路径
        common_paths = []
        if self.current_os == OSPlatform.WINDOWS:
            # Windows常见Java路径
            program_files = os.environ.get('ProgramFiles', 'C:\\Program Files')
            program_files_x86 = os.environ.get('ProgramFiles(x86)', 'C:\\Program Files (x86)')
            common_paths.extend([
                Path(program_files) / "Java" / "jre*" / "bin" / "java.exe",
                Path(program_files_x86) / "Java" / "jre*" / "bin" / "java.exe",
                Path(program_files) / "Java" / "jdk*" / "bin" / "java.exe",
                Path(program_files_x86) / "Java" / "jdk*" / "bin" / "java.exe",
            ])
        elif self.current_os == OSPlatform.OSX:
            # macOS常见Java路径
            common_paths.extend([
                Path("/Library/Java/JavaVirtualMachines/*/Contents/Home/bin/java"),
                Path("/usr/libexec/java_home"),
            ])
        else:
            # Linux常见Java路径
            common_paths.extend([
                Path("/usr/lib/jvm/*/bin/java"),
                Path("/usr/lib/jvm/*/jre/bin/java"),
                Path("/usr/bin/java"),
            ])
        
        # 检查常见路径
        for pattern in common_paths:
            for path in Path(pattern.parent).glob(pattern.name):
                if path.exists():
                    return str(path)
        
        return None

    def download_optifine(self, mc_version: str, optifine_version: str) -> bool:
        """下载OptiFine"""
        self.callback.set_status(f"下载OptiFine {mc_version} {optifine_version}")
        
        optifine_versions = installer.get_optifine_versions(mc_version)
        # all_optifine_versions = installer.get_all_optifine_versions()  # 或者获取所有OptiFine版本
        if optifine_versions:
            optifine = optifine_versions[0]  # 选择第一个OptiFine版本
            optifine_type = optifine["type"]
            optifine_patch = optifine["patch"]
            
            self.callback.set_status(f"下载OptiFine {mc_version} {optifine_type} {optifine_patch}")
            
            # 1. 下载OptiFine安装器
            installer_url = f"{self.mirror_config['root']}/optifine/{mc_version}/{optifine_type}/{optifine_patch}"
            installer_filename = f"OptiFine_{mc_version}_{optifine_type}_{optifine_patch}_installer.jar"
            installer_path = self.game_dir / installer_filename
        
            success, message = self.download_file(installer_url, installer_path)
            if not success:
                self.callback.set_status(f"OptiFine安装器下载失败: {message}")
                return None
            
            return installer_path
        
        self.callback.set_status("OptiFine下载成功")
        return None
    
        # 2. 提取OptiFine库文件从安装器中
        # optifine_lib_path = self._extract_optifine_library(installer_path, mc_version, optifine_type, optifine_patch)
        # if not optifine_lib_path:
        #     self.callback.set_status("提取OptiFine库文件失败")
        #     return False
        
        # # 3. 修改版本json添加OptiFine依赖
        # version_json_path = self.versions_dir / mc_version / f"{mc_version}.json"
        # if not self._add_optifine_to_version_json(version_json_path, optifine_lib_path, mc_version, optifine_type, optifine_patch):
        #     self.callback.set_status("修改版本json失败")
        #     return False

    
    def get_optifine_versions(self, mc_version: str) -> List[Dict]:
        """获取指定Minecraft版本的OptiFine版本列表"""
        try:
            # 使用BMCLAPI的OptiFine版本列表API
            url = f"{self.mirror_config['root']}/optifine/{mc_version}"
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.callback.set_status(f"获取OptiFine版本列表失败: {e}")
            return []

    def get_all_optifine_versions(self) -> List[Dict]:
        """获取所有OptiFine版本列表"""
        try:
            # 使用BMCLAPI的全部OptiFine版本列表API
            url = f"{self.mirror_config['root']}/optifine/versionList"
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.callback.set_status(f"获取全部OptiFine版本列表失败: {e}")
            return []

    def install_optifine_to_libraries(self, mc_version: str, optifine_type: str, optifine_patch: str) -> bool:
        """安装OptiFine到libraries目录并修改版本json"""
        self.callback.set_status(f"安装OptiFine {mc_version} {optifine_type} {optifine_patch}")
        
        # 1. 下载OptiFine安装器
        installer_url = f"{self.mirror_config['root']}/optifine/{mc_version}/{optifine_type}/{optifine_patch}"
        installer_filename = f"OptiFine_{mc_version}_{optifine_type}_{optifine_patch}_installer.jar"
        installer_path = self.game_dir / installer_filename
        
        success, message = self.download_file(installer_url, installer_path)
        if not success:
            self.callback.set_status(f"OptiFine安装器下载失败: {message}")
            return False
        
        # 2. 提取OptiFine库文件从安装器中
        # optifine_lib_path = self._extract_optifine_library(installer_path, mc_version, optifine_type, optifine_patch)
        # if not optifine_lib_path:
        #     self.callback.set_status("提取OptiFine库文件失败")
        #     return False
        
        # # 3. 修改版本json添加OptiFine依赖
        # version_json_path = self.versions_dir / mc_version / f"{mc_version}.json"
        # if not self._add_optifine_to_version_json(version_json_path, optifine_lib_path, mc_version, optifine_type, optifine_patch):
        #     self.callback.set_status("修改版本json失败")
        #     return False
        
        
        self.callback.set_status("OptiFine下载成功")
        return True

    def _extract_optifine_library(self, installer_path: Path, mc_version: str, optifine_type: str, optifine_patch: str) -> Optional[Path]:
        """从OptiFine安装器中提取库文件"""
        try:
            import zipfile
            import re
            
            # OptiFine库文件的命名模式
            pattern = re.compile(r"optifine.*\.jar$", re.IGNORECASE)
            
            with zipfile.ZipFile(installer_path, 'r') as zip_ref:
                for file_info in zip_ref.infolist():
                    print('file_info', file_info)
                    if pattern.search(file_info.filename):
                        # 提取文件到libraries目录
                        lib_filename = file_info.filename
                        lib_path = self.libraries_dir / "optifine" / mc_version / f"{optifine_type}_{optifine_patch}" / lib_filename
                        
                        # 确保目录存在
                        lib_path.parent.mkdir(parents=True, exist_ok=True)
                        
                        # 提取文件
                        with zip_ref.open(file_info) as source, open(lib_path, 'wb') as target:
                            target.write(source.read())
                        
                        return lib_path
            
            return None
        except Exception as e:
            self.callback.set_status(f"提取OptiFine库文件错误: {e}")
            return None

    def _add_optifine_to_version_json(self, version_json_path: Path, optifine_lib_path: Path, 
                                    mc_version: str, optifine_type: str, optifine_patch: str) -> bool:
        """修改版本json添加OptiFine依赖"""
        try:
            # 读取版本json
            with open(version_json_path, 'r', encoding='utf-8') as f:
                version_data = json.load(f)
            
            # 计算库文件的相对路径和SHA1哈希
            lib_relative_path = str(optifine_lib_path.relative_to(self.libraries_dir))
            sha1_hash = self._calculate_file_sha1(optifine_lib_path)
            
            # 创建OptiFine库条目
            optifine_library = {
                "name": f"optifine:OptiFine:{mc_version}_{optifine_type}_{optifine_patch}",
                "downloads": {
                    "artifact": {
                        "path": lib_relative_path,
                        "url": f"{self.mirror_config['libraries']}/{lib_relative_path}",
                        "sha1": sha1_hash,
                        "size": optifine_lib_path.stat().st_size
                    }
                }
            }
            
            # 添加OptiFine到库列表
            if "libraries" not in version_data:
                version_data["libraries"] = []
            
            version_data["libraries"].append(optifine_library)
            
            # 保存修改后的版本json
            with open(version_json_path, 'w', encoding='utf-8') as f:
                json.dump(version_data, f, indent=2, ensure_ascii=False)
            
            return True
        except Exception as e:
            self.callback.set_status(f"修改版本json错误: {e}")
            return False

    def _calculate_file_sha1(self, file_path: Path) -> str:
        """计算文件的SHA1哈希值"""
        sha1 = hashlib.sha1()
        with open(file_path, 'rb') as f:
            while True:
                data = f.read(65536)
                if not data:
                    break
                sha1.update(data)
        return sha1.hexdigest()



    def get_available_versions(self) -> List[Dict]:
        """获取所有可用版本列表"""
        manifest = self.get_version_manifest()
        if not manifest:
            return []
        
        return manifest.get("versions", [])

    def get_forge_versions(self, mc_version: str) -> List[Dict]:
        """获取指定Minecraft版本的Forge版本列表"""
        # 使用BMCLAPI的Forge版本列表API
        forge_manifest_url = f"{self.mirror_config['root']}/forge/minecraft/{mc_version}"
        try:
            response = self.session.get(forge_manifest_url, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.callback.set_status(f"获取Forge版本列表失败: {e}")
            return []

    def get_optifine_versions(self, mc_version: str) -> List[Dict]:
        """获取指定Minecraft版本的OptiFine版本列表"""
        # 使用BMCLAPI的OptiFine版本列表API
        optifine_manifest_url = f"{self.mirror_config['root']}/optifine/{mc_version}"
        try:
            response = self.session.get(optifine_manifest_url, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.callback.set_status(f"获取OptiFine版本列表失败: {e}")
            return []


# 使用示例
if __name__ == "__main__":
    # 设置 Minecraft 目录
    minecraft_dir = Path.cwd() / ".minecraft"
    # 安装1.20.1版本
    target_version = "1.20.1"
    
    # 创建回调对象
    callback = InstallerCallback()
    
    # 创建安装器实例
    installer = CrossPlatformMinecraftInstaller(
        game_dir=minecraft_dir,  # 使用默认Minecraft目录
        mirror=MirrorSource.BMCLAPI,
        max_workers=15,
        callback=callback
    )
    # 创建安装器实例
    optifine_installer = OptiFineInstaller(minecraft_dir)
    
    print(f"检测到操作系统: {installer.current_os.value}")
    print(f"Minecraft目录: {installer.game_dir}")
    
    # 获取可用版本列表
    print("\n获取可用版本列表...")
    versions = installer.get_available_versions()
    release_versions = [v for v in versions if v.get("type") == "release"]
    
    if release_versions:
        print(f"找到 {len(release_versions)} 个正式版")
        # 显示最新的5个版本
        for version in release_versions[:5]:
            print(f" - {version['id']} ({version['releaseTime']})")
    
    
    print(f"\n开始安装 Minecraft {target_version}...")
    
    if installer.install_version(target_version):
        print("✓ Minecraft 安装成功")
        
        # 安装OptiFine
        print("\n查找OptiFine版本...")
        optifine_versions = installer.get_optifine_versions(target_version)
        if optifine_versions:
            print(f"找到 {len(optifine_versions)} 个OptiFine版本")
            # 显示可用的版本
            for optifine in optifine_versions:
                print(f" - {optifine.get('type', '未知类型')} {optifine.get('patch', '未知补丁')}")
            
            # 安装第一个OptiFine版本
            first_optifine = optifine_versions[0]
            optifine_id = f"{first_optifine.get('type', 'HD_U')}_{first_optifine.get('patch', '')}"
            optifine_versions = installer.download_optifine(target_version, optifine_id)
            
            optifine_jar = minecraft_dir / Path("OptiFine_1.20.1_HD_U_I5_installer.jar")
            optifine_install_jar_path = minecraft_dir / Path("optifine-installer.jar")
            
            success = optifine_installer.install_optifine(target_version, optifine_jar, optifine_install_jar_path, optifine_id)
            if success:
                print("✅ OptiFine 安装成功！")
                # 验证安装
                # optifine_installer.validate_installation(target_version, optifine_id)
            else:
                print("❌ OptiFine 安装失败！")

        # 尝试安装Forge
        print("\n查找Forge版本...")
        forge_versions = installer.get_forge_versions(target_version)
        if forge_versions:
            print(f"找到 {len(forge_versions)} 个Forge版本")
            # 显示最新的3个版本
            for forge in forge_versions[:3]:
                print(f" - {forge['version']} (构建号: {forge['build']})")
            
            # 安装最新Forge版本
            latest_forge = forge_versions[0]
            if installer.install_forge(target_version, latest_forge["version"]):
                print("✓ Forge 安装成功")
            else:
                print("✗ Forge 安装失败")
            
    else:
        print("✗ Minecraft 安装失败")
    
    print("\n安装过程完成")
