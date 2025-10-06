import os
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Optional
import zipfile



class OptiFineInstaller:
    """OptiFine 安装器 - 修复版本 JSON 问题"""
    
    def __init__(self, minecraft_dir: str):
        self.minecraft_dir = Path(minecraft_dir)
        self.versions_dir = self.minecraft_dir / "versions"
        self.libraries_dir = self.minecraft_dir / "libraries"
        
        # 确保目录存在
        self.versions_dir.mkdir(parents=True, exist_ok=True)
        self.libraries_dir.mkdir(parents=True, exist_ok=True)
    
    def install_optifine(self, mc_version: str, optifine_jar_path: Path, optifine_install_jar_path: Path, edition: str) -> bool:
        """安装 OptiFine 并修复版本 JSON"""
        try:
            print(f"开始安装 OptiFine for Minecraft {mc_version} ({edition})")
            
            # 1. 备份原始版本 JSON
            original_json = self._backup_original_version(mc_version)
            
            # 3. 使用静默安装器
            success = self._run_silent_installer(optifine_jar_path, optifine_install_jar_path, mc_version)
            
            if not success:
                print("安装失败")
                return False
            
            # 4. 修复版本 JSON
            if success:
                print('修复版本 JSON')
                self._fix_version_json(mc_version, edition, original_json)
            
            return success
            
        except Exception as e:
            print(f"安装过程中出错: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _backup_original_version(self, mc_version: str) -> Optional[Dict]:
        """备份原始版本 JSON"""
        original_dir = self.versions_dir / mc_version
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
    
    def _run_silent_installer(self, optifine_jar_path: Path, optifine_install_jar_path: Path = Path('optifine-installer.jar'), mc_version: str = '1.20.1') -> bool:
        """运行静默安装器"""
        try:
            # 构建命令
            cmd = [
                "java",
                "-cp",
                f"{optifine_jar_path};{optifine_install_jar_path}",
                "net.stevexmh.OptifineInstaller",
                str(self.minecraft_dir),
                mc_version
            ]
            
            print(f"执行命令: {' '.join(cmd)}")
            
            # 运行安装器
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5分钟超时
                cwd=str(self.minecraft_dir)
            )
            
            if result.returncode == 0:
                print("✅ 静默安装成功")
                return True
            else:
                print(f"❌ 静默安装失败: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            print("❌ 安装超时")
            return False
        except Exception as e:
            print(f"❌ 运行安装器失败: {e}")
            return False

    def _fix_version_json(self, mc_version: str, edition: str, original_json: Optional[Dict] = None):
        """修复版本 JSON 文件"""
        version_dir = self.versions_dir / mc_version
        json_path = version_dir / f"{mc_version}.json"

        if not json_path.exists():
            print(f"❌ 版本 JSON 不存在: {json_path}")
            return
        
        try:
            # 读取当前 JSON
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 使用原始 JSON 作为基础（如果可用）
            if original_json:
                data = original_json.copy()
            
            # 确保 libraries 数组存在
            if "libraries" not in data:
                data["libraries"] = []
            
            # 添加 OptiFine 库
            optifine_lib = {
                "name": f"optifine:OptiFine:{mc_version}_{edition}"
            }
            
            # 添加 launchwrapper 库
            launchwrapper_lib = {
                "name": "optifine:launchwrapper-of:2.3"
            }
            
            # 确保库在开头
            data["libraries"].insert(0, launchwrapper_lib)
            data["libraries"].insert(0, optifine_lib)
            
            # 设置正确的 mainClass
            data["mainClass"] = "net.minecraft.launchwrapper.Launch"
            
            # 处理启动参数
            if "arguments" in data and "game" in data["arguments"]:
                # 新版本格式 (1.13+)
                if not any("optifine.OptiFineTweaker" in arg for arg in data["arguments"]["game"]):
                    data["arguments"]["game"].extend(["--tweakClass", "optifine.OptiFineTweaker"])
            elif "minecraftArguments" in data:
                # 旧版本格式 (1.12-)
                if "--tweakClass optifine.OptiFineTweaker" not in data["minecraftArguments"]:
                    data["minecraftArguments"] += " --tweakClass optifine.OptiFineTweaker"
            else:
                # 创建新的 arguments 部分
                data["arguments"] = {
                    "game": [
                        "--username", "${auth_player_name}",
                        "--version", "${version_name}",
                        "--gameDir", "${game_directory}",
                        "--assetsDir", "${assets_root}",
                        "--assetIndex", "${assets_index_name}",
                        "--uuid", "${auth_uuid}",
                        "--accessToken", "${auth_access_token}",
                        "--userType", "${user_type}",
                        "--versionType", "${version_type}",
                        "--tweakClass", "optifine.OptiFineTweaker"
                    ],
                    "jvm": [
                        "-Djava.library.path=${natives_directory}",
                        "-Dminecraft.launch.brand=${launcher_brand}",
                        "-Dminecraft.launcher.version=${launcher_version}",
                        "-cp", "${classpath}"
                    ]
                }
            
            # 保存修复后的 JSON
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            print(f"✅ 版本 JSON 修复成功: {json_path}")
            
        except Exception as e:
            print(f"❌ 修复版本 JSON 失败: {e}")
    
    def validate_installation(self, mc_version: str, edition: str) -> bool:
        """验证安装是否成功"""
        version_id = f"{mc_version}-OptiFine_{edition}"
        version_dir = self.versions_dir / version_id
        
        # 检查版本目录是否存在
        if not version_dir.exists():
            print(f"❌ 版本目录不存在: {version_dir}")
            return False
        
        # 检查 JSON 文件是否存在
        json_path = version_dir / f"{version_id}.json"
        if not json_path.exists():
            print(f"❌ JSON 文件不存在: {json_path}")
            return False

        # 检查 JSON 内容
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 检查必要字段
            required_fields = ["id", "inheritsFrom", "mainClass", "libraries"]
            for field in required_fields:
                if field not in data:
                    print(f"❌ JSON 缺少必要字段: {field}")
                    return False
            
            # 检查 OptiFine 库
            optifine_lib = f"optifine:OptiFine:{mc_version}_{edition}"
            if not any(lib.get("name") == optifine_lib for lib in data["libraries"]):
                print(f"❌ JSON 缺少 OptiFine 库: {optifine_lib}")
                return False
            
            # 检查启动参数
            has_tweakclass = False
            if "arguments" in data and "game" in data["arguments"]:
                has_tweakclass = any("optifine.OptiFineTweaker" in arg for arg in data["arguments"]["game"])
            elif "minecraftArguments" in data:
                has_tweakclass = "--tweakClass optifine.OptiFineTweaker" in data["minecraftArguments"]
            
            if not has_tweakclass:
                print("❌ JSON 缺少 tweakClass 参数")
                return False
            
            print("✅ 安装验证通过")
            return True
            
        except Exception as e:
            print(f"❌ 验证失败: {e}")
            return False


# 使用示例
if __name__ == "__main__":
    # 设置 Minecraft 目录
    minecraft_dir = Path.cwd() / ".minecraft"
    
    # 创建安装器实例
    installer = OptiFineInstaller(minecraft_dir)
    
    # 安装 OptiFine
    mc_version = "1.20.1"
    edition = "HD_U_I5"
    optifine_jar = minecraft_dir / Path("OptiFine_1.20.1_HD_U_I5_installer.jar")
    optifine_install_jar_path = minecraft_dir / Path("optifine-installer.jar")
    
    success = installer.install_optifine(mc_version, optifine_jar, optifine_install_jar_path, edition)
    
    if success:
        print("✅ OptiFine 安装成功！")
        # 验证安装
        installer.validate_installation(mc_version, edition)
    else:
        print("❌ OptiFine 安装失败！")
