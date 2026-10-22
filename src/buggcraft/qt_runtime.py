"""Locate the Qt plugins shipped with the launcher on each supported platform."""
import logging
import os
import platform
from pathlib import Path

logger = logging.getLogger(__name__)


_qt_dll_handles = []


def configure_quick_renderer():
    """Use Qt's raster scene graph on Windows without bundling Mesa OpenGL.

    Current QML pages use 2D controls / Canvas, not shader or 3D effects.
    Selecting this before QApplication also supports machines without a GPU.
    An explicit user backend remains authoritative.
    """
    if platform.system() == 'Windows':
        os.environ.setdefault('QT_QUICK_BACKEND', 'software')


def setup_qt_environment(app_dir, dependencies_dir, packaged=False):
    """设置 Qt 运行环境并定位打包后的插件目录。

    Nuitka 的 PySide6 插件目录在不同版本中可能位于
    ``PySide6/qt-plugins``、``PySide6/Qt/plugins`` 或 ``PySide6/Qt6/plugins``。
    不能假定用户目录下存在开发环境的 ``.buggcraft/dependencies``。
    """
    configure_quick_renderer()
    from PySide6.QtCore import QLibraryInfo
    platform_name = {'Windows': 'qwindows.dll', 'Darwin': 'libqcocoa.dylib'}.get(
        platform.system(), 'libqxcb.so')
    app_dir = Path(app_dir).resolve()
    dependencies_dir = Path(dependencies_dir).resolve()
    candidates = []
    try:
        installed = QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)
        if installed:
            installed_path = Path(installed).resolve()
            # A build machine may have Qt installed outside the shipped bundle.
            # Never let that hide missing files in a packaged launcher.
            if not packaged or installed_path.is_relative_to(app_dir):
                candidates.append(installed_path)
    except Exception as exc:
        logger.warning('读取 Qt 默认插件目录失败: %s', exc)
    candidates.extend([
        app_dir / 'PySide6' / 'qt-plugins',
        app_dir / 'PySide6' / 'Qt' / 'plugins',
        app_dir / 'PySide6' / 'Qt6' / 'plugins',
        app_dir / 'qt-plugins', app_dir / 'plugins',
        dependencies_dir / 'PySide6' / 'qt-plugins',
        dependencies_dir / 'PySide6' / 'Qt' / 'plugins',
        dependencies_dir / 'PySide6' / 'Qt6' / 'plugins',
    ])
    plugin_path = next((p for p in candidates
                        if (p / 'platforms' / platform_name).is_file()), None)
    # 最后从当前运行目录查找，兼容未来 Nuitka/PyInstaller 目录布局。
    if plugin_path is None and app_dir.is_dir():
        try:
            plugin_path = next((p.parent.parent for p in app_dir.rglob(platform_name)
                                if p.parent.name == 'platforms'), None)
        except OSError as exc:
            logger.warning('搜索 Qt 插件目录失败: %s', exc)
    if plugin_path is None:
        logger.error('未找到 Qt 平台插件 %s；检查目录: %s', platform_name,
                     '; '.join(str(p) for p in candidates))
        return False

    plugin_path = plugin_path.resolve()
    platforms_dir = plugin_path / 'platforms'
    os.environ['QT_PLUGIN_PATH'] = str(plugin_path)
    os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = str(platforms_dir)
    logger.info('设置 QT_PLUGIN_PATH = %s', plugin_path)
    logger.info('设置 QT_QPA_PLATFORM_PLUGIN_PATH = %s', platforms_dir)

    dll_dirs = [app_dir, plugin_path, platforms_dir, dependencies_dir]
    if hasattr(os, 'add_dll_directory'):
        for dep_dir in dll_dirs:
            if not dep_dir.is_dir():
                continue
            try:
                _qt_dll_handles.append(os.add_dll_directory(str(dep_dir)))
                logger.info('添加 DLL 搜索目录: %s', dep_dir)
            except OSError as exc:
                logger.warning('添加 DLL 目录失败: %s - %s', dep_dir, exc)
    else:
        path = os.environ.get('PATH', '')
        os.environ['PATH'] = os.pathsep.join(str(p) for p in dll_dirs if p.is_dir()) + os.pathsep + path
    return verify_qt_files(str(plugin_path))


def verify_qt_files(plugin_path):
    """验证必要的Qt文件是否存在"""
    # 检查平台插件
    platforms_path = os.path.join(plugin_path, 'platforms')
    if not os.path.exists(platforms_path):
        logger.error(f"严重错误: 平台插件目录不存在: {platforms_path}")
        return False

    platform_name = {'Windows': 'qwindows.dll', 'Darwin': 'libqcocoa.dylib'}.get(platform.system(), 'libqxcb.so')
    qwindows_dll = os.path.join(platforms_path, platform_name)
    if not os.path.exists(qwindows_dll):
        logger.error(f"致命错误: 平台插件不存在: {qwindows_dll}")
        return False

    # 检查其他关键DLL
    required_dlls = ([os.path.join(plugin_path, 'imageformats', 'qjpeg.dll'),
                      os.path.join(plugin_path, 'styles', 'qmodernwindowsstyle.dll')]
                     if platform.system() == 'Windows' else [])

    missing_files = [dll for dll in required_dlls if not os.path.exists(dll)]
    if missing_files:
        logger.warning("缺少以下文件:")
        for file in missing_files:
            logger.warning(f"  - {file}")

    return True
