# 版本管理

import os
import shutil
import platform
import logging

logger = logging.getLogger(__name__)

def delete_minecraft_directory(minecraft_directory):
    """
    删除指定目录
    :param minecraft_directory: Minecraft 根目录路径
    :return: 删除成功返回 True，失败返回 False
    """
    try:
        # 验证路径和版本 ID
        if not os.path.isdir(minecraft_directory):
            logger.error(f"无效的 Minecraft 目录: {minecraft_directory}")
            return False
        
        versions_dir = os.path.join(minecraft_directory)
        
        # 删除版本目录
        logger.info(f"正在删除目录: {versions_dir}")
        shutil.rmtree(versions_dir)
        
        logger.info(f"成功删除目录: {versions_dir}")
        return True
    
    except Exception as e:
        logger.error(f"删除版本失败: {e}")
        return False
    
def delete_minecraft_version(minecraft_directory, version_id):
    """
    删除指定目录下的 Minecraft 版本
    :param minecraft_directory: Minecraft 根目录路径
    :param version_id: 要删除的版本 ID
    :return: 删除成功返回 True，失败返回 False
    """
    try:
        # 验证路径和版本 ID
        if not os.path.isdir(minecraft_directory):
            logger.error(f"无效的 Minecraft 目录: {minecraft_directory}")
            return False
        
        if not version_id:
            logger.error("未提供版本 ID")
            return False
        
        # 获取版本目录路径
        versions_dir = os.path.join(minecraft_directory, "versions")
        version_dir = os.path.join(versions_dir, version_id)
        
        # 验证版本目录是否存在
        if not os.path.isdir(version_dir):
            logger.error(f"版本目录不存在: {version_dir}")
            return False
        
        # 删除版本目录
        logger.info(f"正在删除版本目录: {version_dir}")
        shutil.rmtree(version_dir)
        
        # 删除版本相关的其他文件
        # _delete_version_related_files(minecraft_directory, version_id)
        
        logger.info(f"成功删除版本: {version_id}")
        return True
    
    except Exception as e:
        logger.error(f"删除版本失败: {e}")
        return False

def _delete_version_related_files(self, minecraft_directory, version_id):
    """
    删除与版本相关的其他文件
    :param minecraft_directory: Minecraft 根目录路径
    :param version_id: 要删除的版本 ID
    """
    try:
        # 删除版本 JSON 文件
        json_file = os.path.join(minecraft_directory, "versions", f"{version_id}.json")
        if os.path.exists(json_file):
            os.remove(json_file)
            logger.info(f"删除 JSON 文件: {json_file}")
        
        # 删除版本 JAR 文件
        jar_file = os.path.join(minecraft_directory, "versions", f"{version_id}.jar")
        if os.path.exists(jar_file):
            os.remove(jar_file)
            logger.info(f"删除 JAR 文件: {jar_file}")
        
        # 删除日志文件
        logs_dir = os.path.join(minecraft_directory, "logs")
        log_file = os.path.join(logs_dir, f"{version_id}.log")
        if os.path.exists(log_file):
            os.remove(log_file)
            logger.info(f"删除日志文件: {log_file}")
        
        # 删除资源索引文件
        assets_dir = os.path.join(minecraft_directory, "assets", "indexes")
        index_file = os.path.join(assets_dir, f"{version_id}.json")
        if os.path.exists(index_file):
            os.remove(index_file)
            logger.info(f"删除资源索引文件: {index_file}")
        
        # 删除版本特定的资源文件
        version_assets_dir = os.path.join(minecraft_directory, "assets", "virtual", "legacy", version_id)
        if os.path.isdir(version_assets_dir):
            shutil.rmtree(version_assets_dir)
            logger.info(f"删除版本资源目录: {version_assets_dir}")
        
        # 删除版本特定的库文件
        libraries_dir = os.path.join(minecraft_directory, "libraries")
        self._delete_version_libraries(libraries_dir, version_id)
    
    except Exception as e:
        logger.warning(f"删除相关文件时出错: {e}")

def _delete_version_libraries(self, libraries_dir, version_id):
    """
    删除版本特定的库文件
    :param libraries_dir: 库文件目录
    :param version_id: 要删除的版本 ID
    """
    try:
        # 遍历库目录
        for root, dirs, files in os.walk(libraries_dir):
            for file in files:
                # 检查文件名是否包含版本 ID
                if version_id in file:
                    file_path = os.path.join(root, file)
                    try:
                        os.remove(file_path)
                        logger.info(f"删除库文件: {file_path}")
                    except Exception as e:
                        logger.warning(f"无法删除库文件 {file_path}: {e}")
    except Exception as e:
        logger.warning(f"遍历库目录时出错: {e}")

def get_versions_directory(minecraft_directory):
    """
    获取版本目录路径（跨平台）
    :param minecraft_directory: Minecraft 根目录路径
    :return: 版本目录路径
    """
    # 不同平台的默认目录
    default_dirs = {
        "win32": os.path.join(os.getenv("APPDATA"), ".minecraft"),
        "darwin": os.path.expanduser("~/Library/Application Support/minecraft"),
        "linux": os.path.expanduser("~/.minecraft")
    }
    
    # 如果未提供目录，使用平台默认目录
    if not minecraft_directory:
        system = platform.system().lower()
        if system == "windows":
            minecraft_directory = default_dirs["win32"]
        elif system == "darwin":
            minecraft_directory = default_dirs["darwin"]
        else:  # Linux 或其他 Unix 系统
            minecraft_directory = default_dirs["linux"]
    
    return os.path.join(minecraft_directory, "versions")

import os
import platform
import subprocess
import logging

logger = logging.getLogger(__name__)

def open_folder(path):
    """
    打开指定路径的文件夹（资源管理器）
    :param path: 要打开的文件夹路径
    """
    try:
        # 确保路径存在
        if not os.path.exists(path):
            logger.error(f"路径不存在: {path}")
            return False
        
        # 获取系统平台
        system = platform.system().lower()
        
        # Windows 系统
        if system == "windows":
            # 使用 explorer 命令打开文件夹
            # /select 参数会选中指定文件，如果传入文件夹则打开该文件夹
            subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')
            return True
        
        # macOS 系统
        elif system == "darwin":
            # 使用 open 命令打开文件夹
            subprocess.Popen(["open", path])
            return True
        
        # Linux 系统
        elif system == "linux":
            # 尝试使用 xdg-open 命令
            try:
                subprocess.Popen(["xdg-open", path])
                return True
            except FileNotFoundError:
                # 如果 xdg-open 不可用，尝试其他文件管理器
                return _try_linux_file_managers(path)
        
        # 其他系统
        else:
            logger.warning(f"不支持的操作系统: {system}")
            return False
    
    except Exception as e:
        logger.error(f"打开文件夹失败: {e}")
        return False

def _try_linux_file_managers(path):
    """尝试在 Linux 上使用其他文件管理器"""
    # 列出常见的 Linux 文件管理器
    file_managers = [
        "nautilus",  # GNOME
        "dolphin",   # KDE
        "thunar",    # XFCE
        "pcmanfm",   # LXDE
        "caja",      # MATE
        "nemo"       # Cinnamon
    ]
    
    for fm in file_managers:
        try:
            subprocess.Popen([fm, path])
            logger.info(f"使用 {fm} 打开文件夹")
            return True
        except FileNotFoundError:
            continue
    
    logger.error("未找到可用的文件管理器")
    return False
