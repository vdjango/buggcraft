import os
import subprocess
import sys
import platform
import re
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
import logging

logger = logging.getLogger(__name__)


class JavaPathFinder:
    """自动查找系统中Java安装路径的工具类"""
    
    def __init__(self):
        self.system = platform.system().lower()
        self.found_java_paths = []
        self.min_required_version = (17, 0)  # Minecraft 1.17+ 需要 Java 17+
    
    def find_all_java_installations(self) -> List[Tuple[str, str, Tuple[int, int, int]]]:
        """
        查找系统中所有Java安装路径
        
        Returns:
            List[Tuple[str, str, Tuple[int, int, int]]]: 
                包含(路径, 原始版本字符串, 解析后的版本元组)的列表
        """
        self.found_java_paths = []
        
        # 按优先级尝试不同的查找方法
        methods = [
            self._check_environment_variables,
            self._check_common_install_paths,
            self._search_with_system_command,
            self._search_in_program_files
        ]
        
        for method in methods:
            try:
                method()
            except Exception as e:
                logger.info(f"方法 {method.__name__} 执行出错: {e}")
                continue
        
        return self._remove_duplicates_and_validate()
    
    def _check_environment_variables(self):
        """检查环境变量中的Java路径"""
        env_vars = ['JAVA_HOME', 'JRE_HOME']
        
        for env_var in env_vars:
            java_home = os.environ.get(env_var)
            if java_home and os.path.exists(java_home):
                java_exe = self._find_java_exe_in_path(java_home)
                if java_exe:
                    raw_version, parsed_version = self._get_java_version(java_exe)
                    self.found_java_paths.append((java_exe, raw_version, parsed_version))
    
    def _check_common_install_paths(self):
        """检查常见的Java安装路径"""
        common_paths = []
        
        if self.system == "windows":
            common_paths = [
                "C:\\Program Files\\Java",
                "C:\\Program Files (x86)\\Java",
                os.path.expanduser("~\\AppData\\Local\\Programs\\Java"),
                os.path.expanduser("~\\AppData\\Local\\Packages"),
                "C:\\Program Files",
                "C:\\Program Files (x86)",
            ]
        elif self.system == "darwin":  # macOS
            common_paths = [
                "/Library/Java/JavaVirtualMachines",
                "/System/Library/Java/JavaVirtualMachines",
                os.path.expanduser("~/Library/Java/JavaVirtualMachines")
            ]
        elif self.system == "linux":
            common_paths = [
                "/usr/lib/jvm",
                "/usr/java",
                "/opt/java"
            ]
        
        for base_path in common_paths:
            if os.path.exists(base_path):
                self._search_java_in_directory(base_path)
    
    def _search_with_system_command(self):
        """使用系统命令查找Java"""
        try:
            if self.system == "windows":
                # 使用where命令查找java.exe
                result = subprocess.run(
                    ["where", "java.exe"], 
                    capture_output=True, 
                    text=True, 
                    timeout=10
                )
                if result.returncode == 0:
                    for line in result.stdout.strip().split('\n'):
                        java_path = line.strip()
                        if java_path and os.path.exists(java_path):
                            raw_version, parsed_version = self._get_java_version(java_path)
                            self.found_java_paths.append((java_path, raw_version, parsed_version))
            
            else:  # Linux/MacOS
                # 使用which命令查找java
                result = subprocess.run(
                    ["which", "java"], 
                    capture_output=True, 
                    text=True, 
                    timeout=5
                )
                if result.returncode == 0:
                    java_path = result.stdout.strip()
                    if java_path and os.path.exists(java_path):
                        raw_version, parsed_version = self._get_java_version(java_path)
                        self.found_java_paths.append((java_path, raw_version, parsed_version))
                        
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            pass  # 命令执行失败时静默处理
    
    def _search_in_program_files(self):
        """在Program Files目录中搜索Java安装"""
        if self.system != "windows":
            return
        
        program_files_dirs = [
            os.environ.get("ProgramFiles", "C:\\Program Files"),
            os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")
        ]
        
        for program_files in program_files_dirs:
            if os.path.exists(program_files):
                for item in os.listdir(program_files):
                    if item.lower().startswith("java"):
                        java_dir = os.path.join(program_files, item)
                        if os.path.isdir(java_dir):
                            self._search_java_in_directory(java_dir)
    
    def _search_java_in_directory(self, directory: str):
        """在指定目录中搜索Java可执行文件"""
        for root, dirs, files in os.walk(directory):
            for file in files:
                if file.lower() in ["java", "java.exe"]:
                    java_path = os.path.join(root, file)
                    # 检查是否是真正的可执行文件
                    if self._is_valid_java_exe(java_path):
                        raw_version, parsed_version = self._get_java_version(java_path)
                        self.found_java_paths.append((java_path, raw_version, parsed_version))
    
    def _find_java_exe_in_path(self, java_home: str) -> Optional[str]:
        """在JAVA_HOME路径中查找java可执行文件"""
        possible_paths = []
        
        if self.system == "windows":
            possible_paths = [
                os.path.join(java_home, "bin", "java.exe"),
                os.path.join(java_home, "java.exe")
            ]
        else:
            possible_paths = [
                os.path.join(java_home, "bin", "java"),
                os.path.join(java_home, "java")
            ]
        
        for path in possible_paths:
            if os.path.exists(path) and self._is_valid_java_exe(path):
                return path
        
        return None
    
    def _is_valid_java_exe(self, path: str) -> bool:
        """验证找到的文件是真正的Java可执行文件"""
        if not os.path.isfile(path):
            return False
        
        # 检查文件大小（Java可执行文件通常不会太小）
        file_size = os.path.getsize(path)
        if file_size < 1024:  # 小于1KB可能是无效文件
            return False
        
        # 检查文件权限（在Unix系统上需要可执行权限）
        if self.system != "windows":
            return os.access(path, os.X_OK)
        
        return True
    
    def _get_java_version(self, java_path: str) -> Tuple[Optional[str], Optional[Tuple[int, int, int]]]:
        """获取Java版本信息并解析为元组"""
        try:
            result = subprocess.run(
                [java_path, "-version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 or result.stderr:
                # Java版本信息通常输出到stderr
                output = result.stderr or result.stdout
                lines = output.split('\n')
                raw_version = None
                
                # 查找包含版本信息的行
                for line in lines:
                    if "version" in line.lower():
                        raw_version = line.strip()
                        break
                
                # 解析版本号
                if raw_version:
                    parsed_version = self._parse_version_string(raw_version)
                    return raw_version, parsed_version
            return None, None
        except Exception as e:
            logger.error(f"获取Java版本时出错: {e}")
            return None, None
    
    def _parse_version_string(self, version_str: str) -> Tuple[int, int, int]:
        """
        解析Java版本字符串为(主版本, 次版本, 补丁版本)元组
        """
        try:
            # 尝试匹配带引号的版本号
            quoted_match = re.search(r'["\'](\d+\.\d+\.\d+[^"\']*)["\']', version_str)
            if quoted_match:
                version_part = quoted_match.group(1)
            else:
                # 尝试匹配不带引号的版本号
                version_match = re.search(r'\d+\.\d+\.\d+', version_str)
                if version_match:
                    version_part = version_match.group(0)
                else:
                    # 尝试匹配简单版本号
                    version_match = re.search(r'\d+\.\d+', version_str)
                    if version_match:
                        version_part = version_match.group(0)
                    else:
                        return (0, 0, 0)
            
            # 提取版本号各部分
            version_parts = version_part.split('.')
            major = int(version_parts[0])
            
            # 处理Java 9+的版本格式
            if major > 1:
                minor = int(version_parts[1]) if len(version_parts) > 1 else 0
                patch = int(version_parts[2]) if len(version_parts) > 2 else 0
                return (major, minor, patch)
            else:
                # Java 8及更早版本使用1.x格式
                minor = int(version_parts[1]) if len(version_parts) > 1 else 0
                # 处理补丁版本（可能包含下划线）
                if len(version_parts) > 2:
                    patch_parts = version_parts[2].split('_')
                    patch = int(patch_parts[0]) if patch_parts else 0
                    if len(patch_parts) > 1:
                        # 返回额外的更新版本作为补丁版本的一部分
                        return (major, minor, int(patch_parts[1]))
                else:
                    patch = 0
                return (major, minor, patch)
        except Exception as e:
            logger.error(f"解析版本字符串 '{version_str}' 时出错: {e}")
            return (0, 0, 0)
    
    def _remove_duplicates_and_validate(self) -> List[Tuple[str, str, Tuple[int, int, int]]]:
        """去除重复路径并验证Java有效性"""
        unique_paths = {}
        valid_entries = []
        
        for path, raw_version, parsed_version in self.found_java_paths:
            # 跳过无效的版本信息
            if parsed_version is None:
                logger.warning(f"跳过无效的Java安装: {path} - 无法解析版本")
                continue
                
            try:
                # 规范化路径（解析符号链接等）
                real_path = os.path.realpath(path)
                if real_path not in unique_paths:
                    unique_paths[real_path] = (raw_version, parsed_version)
                    valid_entries.append((real_path, raw_version, parsed_version))
            except Exception as e:
                logger.warning(f"处理路径时出错 {path}: {e}")
                continue
        
        # 返回排序后的结果（按版本从高到低）
        return sorted(
            valid_entries,
            key=lambda x: x[2],  # 按解析后的版本元组排序
            reverse=True
        )
    
    def recommend_best_java(self, java_installations: List[Tuple[str, str, Tuple[int, int, int]]]) -> Optional[str]:
        """从找到的Java安装中推荐最佳选择"""
        if not java_installations:
            return None
        
        # 优先选择满足最低版本要求的Java
        compatible_java = [
            (path, raw, ver) for path, raw, ver in java_installations
            if self._is_compatible_version(ver)
        ]
        
        if compatible_java:
            # 选择最高版本的兼容Java
            return compatible_java[0][0]
        
        # 如果没有兼容版本，选择最高版本（即使不兼容）
        return java_installations[0][0] if java_installations else None
    
    def _is_compatible_version(self, version_tuple: Tuple[int, int, int]) -> bool:
        """检查Java版本是否兼容"""
        if not version_tuple:
            return False
        
        # Minecraft 1.17+ 需要 Java 17+
        return version_tuple[0] >= self.min_required_version[0]
    
    def get_java_version_info(self, java_path: str) -> Dict[str, Any]:
        """获取Java的详细信息"""
        try:
            result = subprocess.run(
                [java_path, "-version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            output = result.stderr or result.stdout
            
            # 解析详细信息
            vendor = "未知"
            if "OpenJDK" in output:
                vendor = "OpenJDK"
            elif "Java(TM)" in output:
                vendor = "Oracle"
            elif "AdoptOpenJDK" in output:
                vendor = "AdoptOpenJDK"
            elif "Eclipse Temurin" in output:
                vendor = "Eclipse Temurin"
            
            # 解析版本信息
            raw_version, parsed_version = self._get_java_version(java_path)
            
            return {
                "path": java_path,
                "vendor": vendor,
                "raw_version": raw_version,
                "parsed_version": parsed_version,
                "is_compatible": self._is_compatible_version(parsed_version),
                "min_required": self.min_required_version
            }
        except Exception:
            return {
                "path": java_path,
                "vendor": "未知",
                "raw_version": "无法获取",
                "parsed_version": (0, 0, 0),
                "is_compatible": False,
                "min_required": self.min_required_version
            }

    def is_java_version_low(self, java_path: str) -> bool:
        """
        检查Java版本是否低于Minecraft所需的最低版本
        
        Args:
            java_path: Java可执行文件路径
            
        Returns:
            bool: 如果版本低于17则返回True，否则返回False
        """
        # 获取Java版本信息
        _, parsed_version = self._get_java_version(java_path)
        
        # 如果无法解析版本，保守起见认为版本过低
        if parsed_version is None:
            return True
        
        # Minecraft 1.17+ 需要 Java 17+
        return parsed_version[0] < self.min_required_version[0]
    
# 使用示例
if __name__ == "__main__":
    finder = JavaPathFinder()
    java_installations = finder.find_all_java_installations()
    
    logger.info("找到的Java安装路径:")
    for i, (path, raw_version, parsed_version) in enumerate(java_installations, 1):
        compatible = "✓" if finder._is_compatible_version(parsed_version) else "✗"
        logger.info(f"{i}. {compatible} {raw_version} -> {parsed_version} - {path}")
    
    if java_installations:
        best_java = finder.recommend_best_java(java_installations)
        best_info = finder.get_java_version_info(best_java)
        logger.info(f"\n推荐使用的Java: {best_java}")
        logger.info(f"版本信息: {best_info['raw_version']}")
        logger.info(f"解析版本: {best_info['parsed_version']}")
        logger.info(f"是否兼容: {'是' if best_info['is_compatible'] else '否'}")
    else:
        logger.info("未找到Java安装")
