import sys
import os
from pathlib import Path

import logging
logger = logging.getLogger(__name__)


def get_launcher_directory():
    """Return the deployed launcher location, independent of its working directory."""
    configured = os.environ.get('BUGGCRAFT_LAUNCHER_DIR')
    if configured:
        return Path(configured).expanduser().resolve()
    if getattr(sys, 'frozen', False) or '__compiled__' in globals():
        # Nuitka onefile keeps the outer executable in argv[0].
        executable = Path(sys.argv[0] if '__compiled__' in globals() else sys.executable).resolve()
        for parent in executable.parents:
            if parent.suffix.lower() == '.app':
                return parent.parent
        return executable.parent
    # Source launches use the project directory, never src/buggcraft or the IDE cwd.
    return Path(__file__).resolve().parents[3]


def get_default_minecraft_dir():
    return get_launcher_directory() / '.minecraft'


class NuitkaPathHelper:
    """
    Nuitka 打包环境下的路径获取工具类
    用于正确处理 --onefile 和 --standalone 模式下的路径问题
    """
    
    @staticmethod
    def is_nuitka_packaged():
        """
        判断程序是否被 Nuitka 打包
        
        Returns:
            bool: 如果是 Nuitka 打包环境返回 True，否则返回 False
        """
        return hasattr(sys, 'frozen') and sys.frozen
    
    @staticmethod
    def get_temp_unpack_dir():
        """
        获取临时解压目录（仅适用于 --onefile 模式）
        
        Returns:
            Path: 临时解压目录的 Path 对象，如果不是 onefile 模式返回 None
        """
        if not NuitkaPathHelper.is_nuitka_packaged():
            return None
            
        # 在 onefile 模式下，__file__ 指向临时解压目录中的文件
        if hasattr(sys, '_MEIPASS') or (hasattr(sys, 'frozen') and sys.frozen):
            try:
                # 尝试通过 __file__ 获取临时目录
                file_path = Path(__file__)
                if file_path.exists():
                    return file_path.parent
            except (NameError, AttributeError):
                pass
                
            # 尝试通过 sys.path 获取
            if len(sys.path) > 1:
                temp_path = Path(sys.path[1])
                if temp_path.exists():
                    return temp_path
        
        return None
    
    @staticmethod
    def get_exe_dir():
        """
        获取 EXE 文件所在的目录（真实部署位置）
        
        Returns:
            Path: EXE 文件所在目录的 Path 对象
        """
        if NuitkaPathHelper.is_nuitka_packaged():
            # 方法1: 使用 sys.argv[0] (最可靠)
            exe_path = Path(sys.argv[0])
            if exe_path.exists():
                return exe_path.parent
                
            # 方法2: 使用 sys.path[0]
            if len(sys.path) > 0:
                path0 = Path(sys.path[0])
                if path0.exists():
                    return path0
        
        # 开发环境，返回当前文件所在目录或工作目录
        return Path.cwd()
    
    @staticmethod
    def get_exe_path():
        """
        获取 EXE 文件的完整路径
        
        Returns:
            Path: EXE 文件的 Path 对象
        """
        if NuitkaPathHelper.is_nuitka_packaged():
            exe_dir = NuitkaPathHelper.get_exe_dir()
            # 尝试查找 .exe 文件
            for file in exe_dir.iterdir():
                if file.suffix.lower() == '.exe' and file.is_file():
                    return file
            # 如果没找到，返回 sys.argv[0] 的路径
            return Path(sys.argv[0])
        else:
            # 开发环境
            return Path(sys.argv[0])
    
    @staticmethod
    def get_resource_path(relative_path):
        """
        获取资源文件的正确路径（优先在 EXE 目录查找，找不到则在临时目录查找）
        
        Args:
            relative_path: 资源文件相对于 EXE 目录的路径
            
        Returns:
            Path: 资源文件的完整路径
        """
        exe_dir = NuitkaPathHelper.get_exe_dir()
        resource_path = exe_dir / relative_path
        
        # 先在 EXE 目录查找
        if resource_path.exists():
            return resource_path
            
        # 如果在 EXE 目录找不到，尝试在临时解压目录查找
        temp_dir = NuitkaPathHelper.get_temp_unpack_dir()
        if temp_dir:
            temp_resource_path = temp_dir / relative_path
            if temp_resource_path.exists():
                return temp_resource_path
        
        # 都找不到，返回 EXE 目录下的预期路径
        return resource_path

# 使用示例
if __name__ == "__main__":
    logger.info("=== Nuitka 路径诊断 ===")
    logger.info(f"是否 Nuitka 打包: {NuitkaPathHelper.is_nuitka_packaged()}")
    logger.info(f"EXE 所在目录: {NuitkaPathHelper.get_exe_dir()}")
    logger.info(f"EXE 文件路径: {NuitkaPathHelper.get_exe_path()}")
    logger.info(f"临时解压目录: {NuitkaPathHelper.get_temp_unpack_dir()}")
    
    # 获取资源文件路径示例
    image_path = NuitkaPathHelper.get_resource_path("images/minecraft_bg.png")
    icon_path = NuitkaPathHelper.get_resource_path("icons/union@2x.png")
    
    logger.info(f"\n=== 资源文件路径 ===")
    logger.info(f"背景图片路径: {image_path} (存在: {image_path.exists()})")
    logger.info(f"图标文件路径: {icon_path} (存在: {icon_path.exists()})")
