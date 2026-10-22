import os
import sys
import logging
import logging.handlers
import platform
import faulthandler
import multiprocessing
from pathlib import Path

if platform.system().lower() == "linux":
    # 设置环境变量（关键！）
    # Preserve Wayland, remote X11 and headless environments chosen by the user.
    os.environ.setdefault("XLIB_SKIP_ARGB_VISUALS", "1")


APP_DIR = Path(sys.executable).resolve().parent
IS_PACKAGED = getattr(sys, 'frozen', False) or '__compiled__' in globals()
BASE_DIR = APP_DIR if IS_PACKAGED else Path.cwd()
_default_log_dir = (Path.home() / 'Library/Logs/Buggcraft'
                    if IS_PACKAGED and platform.system() == 'Darwin'
                    else APP_DIR if IS_PACKAGED else BASE_DIR)
LOG_DIR = Path(os.environ.get('BUGGCRAFT_LOG_DIR') or _default_log_dir).resolve()
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / 'buggcraft.log'
if IS_PACKAGED:
    sys.stderr = open(LOG_DIR / 'buggcraft-stderr.log', 'a', encoding='utf-8', buffering=1)


class UTF8FileHandler(logging.handlers.RotatingFileHandler):
    """自定义文件处理器，使用 UTF-8 编码"""
    def __init__(self, filename, mode='a', encoding=None, delay=False):
        if encoding is None:
            encoding = 'utf-8'
        super().__init__(filename, mode, maxBytes=5 * 1024 * 1024, backupCount=3,
                         encoding=encoding, delay=delay)


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        UTF8FileHandler(str(LOG_PATH), mode='a')
    ]
)
logger = logging.getLogger(__name__)
_crash_log = open(LOG_DIR / 'buggcraft-crash.log', 'a', encoding='utf-8')
faulthandler.enable(_crash_log, all_threads=True)


def _log_unhandled_exception(exc_type, exc_value, exc_traceback):
    logger.critical('Unhandled exception', exc_info=(exc_type, exc_value, exc_traceback))


sys.excepthook = _log_unhandled_exception
logger.info('Startup diagnostics: OS=%s; architecture=%s; Python=%s; CPU_count=%s; '
            'process_64bit=%s; executable=%s; working_directory=%s',
            platform.platform(), platform.machine(), sys.version.split()[0],
            multiprocessing.cpu_count(), sys.maxsize > 2**32, sys.executable, Path.cwd())
logger.info('Application log directory: %s', LOG_DIR)

if __name__ == '__main__' and '--package-check' in sys.argv:
    from qt_runtime import setup_qt_environment as configure_qt
    if not configure_qt(APP_DIR, APP_DIR / '.buggcraft/dependencies', packaged=IS_PACKAGED):
        raise SystemExit(1)
    from runtime_check import main as check_package
    raise SystemExit(check_package(sys.argv[sys.argv.index('--package-check') + 1]))

from PySide6.QtGui import QFontDatabase, QFont, QIcon
from config.settings import get_conf_or_cache_manager

# Global app paths

# 全局配置
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

for _resource_candidate in (APP_DIR / 'resources',
                            Path(__file__).resolve().parent / 'resources',
                            Path(__file__).resolve().parents[2] / 'resources'):
    if (_resource_candidate / 'images/minecraft_bg.png').is_file():
        RESOURCE_DIR = _resource_candidate
        break

def get_app_icon(RESOURCE_DIR) -> QIcon:
    """获取应用程序图标"""

    # 尝试从系统图标主题加载
    icon = QIcon.fromTheme("app")
    if icon.isNull():
        # 如果主题中没有，则从绝对路径加载
        icon = QIcon()
        icon_path = os.path.abspath(os.path.join(RESOURCE_DIR, 'icons', 'app.ico'))
        if os.path.exists(icon_path):
            icon = QIcon(icon_path)

    return icon


def load_custom_font(resource_dir):
    """
    加载自定义字体文件
    :param resource_dir: 资源目录路径
    :return: 字体家族名称列表，用于后续设置字体
    """
    QFont.insertSubstitution('Source Han Sans CN Normal', 'Source Han Sans CN')
    font_families = []
    fonts_dir = os.path.join(resource_dir, 'fonts')
    
    if not os.path.exists(fonts_dir):
        logger.warning(f"字体目录不存在: {fonts_dir}")
        return font_families
    
    # 支持的字体文件扩展名
    font_extensions = ['.ttf', '.otf', '.woff', '.woff2']
    
    for file_name in os.listdir(fonts_dir):
        if any(file_name.lower().endswith(ext) for ext in font_extensions):
            font_path = os.path.join(fonts_dir, file_name)
            
            try:
                # 方法1: 使用文件路径加载
                font_id = QFontDatabase.addApplicationFont(font_path)
                if font_id != -1:
                    families = QFontDatabase.applicationFontFamilies(font_id)
                    font_families.extend(families)
                    logger.info(f"成功加载字体: {file_name} -> {families}")
                else:
                    logger.warning(f"字体加载失败: {file_name}")
                    
            except Exception as e:
                logger.error(f"加载字体时出错 {file_name}: {e}")
    
    return font_families


def download_and_extract(url, download_dir, extract_dir):
    """
    下载并解压资源
    :param url: 下载URL
    :param download_dir: 下载目录
    :param extract_dir: 解压目录
    :return: 成功返回True，否则False
    """
    import zipfile
    from utils.archives import extract_zip
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
            extract_zip(zip_ref, extract_dir)
        logger.info(f"解压到: {extract_dir}")

        # 清理：删除下载的ZIP文件
        os.remove(zip_path)
        return True

    except Exception as e:
        logger.exception(f"下载或解压过程中出错: {e}")
        return False


def setup_qt_environment():
    from qt_runtime import setup_qt_environment as configure_qt
    return configure_qt(APP_DIR, DEPENDENCIES_DIR, packaged=IS_PACKAGED)



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
    from PySide6.QtCore import QLibraryInfo, qVersion
    from PySide6.QtWidgets import QApplication
    from windows.main_window import MinecraftLauncher
    import PySide6

    logger.info('Qt diagnostics: PySide6=%s; Qt=%s; plugin_path=%s',
                PySide6.__version__, qVersion(), QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
    

    # Windows 特定设置
    if os.name == 'nt':
        try:
            from ctypes import windll
            # 设置唯一的应用程序 ID
            myappid = 'bugg.icu'  # 替换为你的应用标识
            windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except ImportError:
            pass

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
    load_custom_font(RESOURCE_DIR)
    
    app.setWindowIcon(get_app_icon(RESOURCE_DIR))
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
    if os.path.isdir(os.path.join(RESOURCE_DIR, 'images')):
        return initialize_application()
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

