import os
import sys
import logging

from pathlib import Path
from config.settings import get_settings_manager, get_conf_or_cache_manager


class UTF8FileHandler(logging.FileHandler):
    """自定义文件处理器，使用 UTF-8 编码"""
    def __init__(self, filename, mode='a', encoding=None, delay=False):
        if encoding is None:
            encoding = 'utf-8'
        super().__init__(filename, mode, encoding, delay)


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        UTF8FileHandler('buggcraft.log', mode='w')  # 使用自定义的FileHandler
    ]
)
logger = logging.getLogger(__name__)

# 全局配置
BASE_DIR = Path.cwd()
HOME_DIR = os.path.join(BASE_DIR, '.buggcraft')

_, HOME_DIR = get_conf_or_cache_manager()

CACHE_DIR = os.path.join(HOME_DIR, 'cache')
CONFIG_DIR = os.path.join(HOME_DIR, 'etc')
RESOURCE_DIR = os.path.join(HOME_DIR, 'resources')  # 资源目录，存放字体、图标等
DEPENDENCIES_DIR = os.path.join(HOME_DIR, 'dependencies')  # 依赖目录，存放PySide6等DLL

DOWNLOAD_URLS = {
    'resources': "https://pan.erguanmingmin.com/file/10007988/resources.zip",
    'dependencies': 'https://pan.erguanmingmin.com/file/10007988/dependencies.zip'
}

NOTIFICATION_MESSAGES = {
    'resources': '下载字体等资源...',
    'dependencies': '下载运行时库...',
    'complete': '资源下载完成',
    'error': '资源下载失败'
}

RESOURCE_DIR = Path.cwd() / 'resources'


def download_and_extract(url, download_dir, extract_dir):
    """
    下载并解压资源
    :param url: 下载URL
    :param download_dir: 下载目录
    :param extract_dir: 解压目录
    :return: 成功返回True，否则False
    """
    import zipfile
    from utils.network import minecraft_httpx, urlparse
    os.makedirs(download_dir, exist_ok=True)
    os.makedirs(extract_dir, exist_ok=True)

    try:
        logger.info(f"开始下载: {url}")
        data = minecraft_httpx.download(url)
        if not data:
            logger.error("下载失败，无数据返回")
            return False

        # 保存ZIP文件
        zip_name = Path(urlparse(url).path).name or "resources.zip"
        zip_path = os.path.join(download_dir, zip_name)
        with open(zip_path, 'wb') as f:
            f.write(data)
        logger.info(f"文件保存至: {zip_path}")

        # 解压
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
        logger.info(f"解压到: {extract_dir}")

        # 清理：删除下载的ZIP文件
        os.remove(zip_path)
        return True

    except Exception as e:
        logger.exception(f"下载或解压过程中出错: {e}")
        return False


def setup_qt_environment():
    """设置Qt运行环境"""
    # 设置Qt插件路径
    qt_plugins_dir = os.path.join(DEPENDENCIES_DIR, 'PySide6', 'qt-plugins')
    os.environ['QT_PLUGIN_PATH'] = str(qt_plugins_dir)
    logger.info(f"设置 QT_PLUGIN_PATH = {qt_plugins_dir}")
    
    # 设置Qt平台插件路径
    platforms_dir = os.path.join(qt_plugins_dir, 'platforms')
    os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = str(platforms_dir)
    logger.info(f"设置 QT_QPA_PLATFORM_PLUGIN_PATH = {platforms_dir}")
    
    # 将依赖目录添加到DLL搜索路径
    if hasattr(os, 'add_dll_directory'):
        # Python 3.8+
        for dep_dir in [DEPENDENCIES_DIR, qt_plugins_dir, platforms_dir]:
            try:
                os.add_dll_directory(str(dep_dir))
                logger.info(f"添加DLL: {dep_dir}")
            except Exception as e:
                logger.error(f"添加DLL目录失败: {dep_dir} - {e}")
    else:
        # 旧版Python：添加到PATH
        path = os.environ.get('PATH', '')
        new_path = str(DEPENDENCIES_DIR) + os.pathsep + str(qt_plugins_dir) + os.pathsep + path
        os.environ['PATH'] = new_path
        logger.info(f"更新PATH环境变量以包含依赖目录")
    
    return verify_qt_files(qt_plugins_dir)


def verify_qt_files(plugin_path):
    """验证必要的Qt文件是否存在"""
    # 检查平台插件
    platforms_path = os.path.join(plugin_path, 'platforms')
    if not os.path.exists(platforms_path):
        logger.error(f"严重错误: 平台插件目录不存在: {platforms_path}")
        return False
    
    # 检查qwindows.dll
    qwindows_dll = os.path.join(platforms_path, 'qwindows.dll')
    if not os.path.exists(qwindows_dll):
        logger.error(f"致命错误: qwindows.dll 不存在: {qwindows_dll}")
        return False
    
    # 检查其他关键DLL
    required_dlls = [
        os.path.join(plugin_path, 'imageformats', 'qjpeg.dll'),
        os.path.join(plugin_path, 'styles', 'qmodernwindowsstyle.dll')
    ]
    
    missing_files = [dll for dll in required_dlls if not os.path.exists(dll)]
    if missing_files:
        logger.warning("缺少以下文件:")
        for file in missing_files:
            logger.warning(f"  - {file}")
    
    return True


def send_notification(title, message, icon_path=None):
    """
    发送桌面通知
    :param title: 标题
    :param message: 消息内容
    :param icon_path: 图标路径（可选）
    """
    from notifypy import Notify
    icon_path = os.path.abspath(os.path.join(RESOURCE_DIR, "icons/app.ico"))
    try:
        notification = Notify()
        notification.title = title
        notification.message = message
        notification.application_name='Buggcraft Minecraft Launcher'
        print('icon_path', icon_path)
        if icon_path and Path(icon_path).exists():
            notification.icon = str(icon_path)
        notification.send()
    except Exception as e:
        logger.error(f"发送通知失败: {e}")


def download_resources():
    """下载并解压所有必要资源"""
    download_dir = os.path.join(CACHE_DIR, 'downloads')
    
    for name, url in DOWNLOAD_URLS.items():
        
        if os.path.exists(os.path.join(HOME_DIR, name)):
            logger.info(f"校验资源: {os.path.join(HOME_DIR, name)}")
            continue

        extract_dir = os.path.join(HOME_DIR)
        send_notification("资源下载", NOTIFICATION_MESSAGES.get(name, "下载资源"))
        if not download_and_extract(url, download_dir, extract_dir):
            send_notification("下载失败", f"{name}资源下载失败")
            return False
    
    send_notification("下载完成", f"仅在第一次启动下载，现在，您可以玩了~")
    return True


def initialize_application():
    """初始化并运行Qt应用程序"""
    # 设置Qt环境
    if not setup_qt_environment():
        logger.error("Qt环境设置失败，无法启动应用")
        send_notification("启动失败", "Qt环境设置失败")
        return 1
    
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from windows.main_window import MinecraftLauncher

    # 设置渲染
    # 软件渲染（兼容性最好，推荐尝试）
    QApplication.setAttribute(Qt.AA_UseSoftwareOpenGL)
    # OpenGL ES（通过ANGLE）
    # QApplication.setAttribute(Qt.AA_UseOpenGLES)
    # OpenGL（性能最好，但需要显卡支持）
    # QApplication.setAttribute(Qt.AA_UseDesktopOpenGL)

    # 创建Qt应用
    app = QApplication(sys.argv)
    # 注释掉字体加载功能，使用系统默认字体
    # load_custom_font(RESOURCE_DIR)
    
    # 设置应用样式
    app.setStyle('Fusion')
    
    # 创建并显示主窗口
    launcher = MinecraftLauncher(
        base_path=BASE_DIR,
        cache_path=CACHE_DIR,
        config_path=CONFIG_DIR,
        resource_path=RESOURCE_DIR
    )
    launcher.show()
    
    # 运行应用
    return app.exec()


def main():
    """应用程序主入口"""
    # 下载必要资源
    if not download_resources():
        logger.error("资源下载失败，无法继续")
        return 1
    
    # 初始化并运行Qt应用
    return initialize_application()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        logger.exception("程序异常退出")
        send_notification("程序错误", f"发生未处理的异常: {str(e)}")
        sys.exit(1)

