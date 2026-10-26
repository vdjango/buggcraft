import os
import sys
import logging
import logging.handlers
import platform
import faulthandler
from pathlib import Path
from time import perf_counter

_STARTUP_STARTED = perf_counter()

if platform.system().lower() == "linux":
    # 设置环境变量（关键！）
    # Preserve Wayland, remote X11 and headless environments chosen by the user.
    os.environ.setdefault("XLIB_SKIP_ARGB_VISUALS", "1")


IS_PACKAGED = getattr(sys, 'frozen', False) or '__compiled__' in globals()
from utils.path_helper import get_launcher_directory
APP_DIR = Path(__file__).resolve().parent if IS_PACKAGED else Path(sys.executable).resolve().parent
BASE_DIR = get_launcher_directory() if IS_PACKAGED else Path.cwd()
_default_log_dir = (Path.home() / 'Library/Logs/Buggcraft'
                    if IS_PACKAGED and platform.system() == 'Darwin'
                    else BASE_DIR)
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
from utils.diagnostics import SafeFormatter, configure_connection_logging
for _handler in logging.getLogger().handlers:
    _handler.setLevel(logging.INFO)
    _handler.setFormatter(SafeFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
_connection_log = configure_connection_logging(LOG_DIR)
logger = logging.getLogger(__name__)
_crash_log = open(LOG_DIR / 'buggcraft-crash.log', 'a', encoding='utf-8')
faulthandler.enable(_crash_log, all_threads=True)


def _log_unhandled_exception(exc_type, exc_value, exc_traceback):
    logger.critical('Unhandled exception', exc_info=(exc_type, exc_value, exc_traceback))


sys.excepthook = _log_unhandled_exception
logger.info('Startup diagnostics: OS=%s; architecture=%s; Python=%s; CPU_count=%s; '
            'process_64bit=%s; executable=%s; working_directory=%s',
            platform.platform(), platform.machine(), sys.version.split()[0],
            os.cpu_count() or 1, sys.maxsize > 2**32, sys.executable, Path.cwd())
logger.info('Application log directory: %s', LOG_DIR)
logger.info('Persistent P2P session log: %s', _connection_log)

_payload_cache = None
if IS_PACKAGED:
    from utils.payload_cache import PayloadCache
    _payload_cache = PayloadCache(APP_DIR)
    _payload_cache.register()

if __name__ == '__main__' and '--package-check' in sys.argv:
    from qt_runtime import setup_qt_environment as configure_qt
    if not configure_qt(APP_DIR, APP_DIR / '.buggcraft/dependencies', packaged=IS_PACKAGED):
        raise SystemExit(1)
    from runtime_check import main as check_package
    raise SystemExit(check_package(sys.argv[sys.argv.index('--package-check') + 1]))

from utils.app_icon import get_app_icon
from config.settings import get_conf_or_cache_manager, get_settings_manager

# Global app paths

# 全局配置
HOME_DIR = os.path.join(BASE_DIR, '.buggcraft')

_, HOME_DIR = get_conf_or_cache_manager()

CACHE_DIR = os.path.join(HOME_DIR, 'cache')
CONFIG_DIR = os.path.join(HOME_DIR, 'etc')
RESOURCE_DIR = os.path.join(HOME_DIR, 'resources')  # 资源目录，存放字体、图标等
DEPENDENCIES_DIR = os.path.join(HOME_DIR, 'dependencies')  # 依赖目录，存放PySide6等DLL

for _resource_candidate in (APP_DIR / 'resources',
                            *(parent / 'resources' for parent in
                              list(Path(__file__).resolve().parents)[:3])):
    if (_resource_candidate / 'images/minecraft_bg.png').is_file():
        RESOURCE_DIR = _resource_candidate
        break

def setup_qt_environment():
    from qt_runtime import setup_qt_environment as configure_qt
    return configure_qt(APP_DIR, DEPENDENCIES_DIR, packaged=IS_PACKAGED)



def send_notification(title, message, icon_path=None):
    """Report startup failures with the GUI toolkit already shipped with us."""
    logger.error('%s: %s', title, message)
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance()
        if app is not None:
            QMessageBox.critical(None, title, message)
        elif os.name == 'nt':
            # Qt initialization may itself have failed. A native Windows
            # message box needs no notifier package or GUI application.
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
    except Exception:
        logger.exception('Could not display startup failure notification')


def initialize_application():
    """初始化并运行Qt应用程序"""
    # 设置Qt环境
    if not setup_qt_environment():
        logger.error("Qt环境设置失败，无法启动应用")
        send_notification("启动失败", "Qt环境设置失败")
        return 1
    
    from PySide6.QtCore import QLibraryInfo, qVersion
    from PySide6.QtWidgets import QApplication
    startup_report = None
    startup_config = None
    if '--startup-check' in sys.argv:
        import tempfile
        import config.settings as check_settings
        startup_report = Path(sys.argv[sys.argv.index('--startup-check') + 1])
        startup_config = tempfile.TemporaryDirectory(prefix='buggcraft-startup-check-')
        check_settings.get_conf_or_cache_manager = lambda: ('startup-check', startup_config.name)
        check_settings._settings_manager_instance = check_settings.SettingsManager(startup_config.name)
    from windows.main_window import MinecraftLauncher
    import PySide6
    imports_seconds = perf_counter() - _STARTUP_STARTED

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

    # qt_runtime selects the Windows raster scene graph before Qt starts.
    # Do not force software OpenGL: this package intentionally omits Mesa.

    app = QApplication(sys.argv)
    app.setApplicationName('BUGG启动器')
    app.setApplicationDisplayName('BUGG启动器')
    
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
    window_seconds = perf_counter() - _STARTUP_STARTED
    if startup_report is not None:
        from PySide6.QtCore import Qt
        launcher.setAttribute(Qt.WA_ShowWithoutActivating)
        launcher.move(-20000, -20000)
    launcher.show()
    update_handshake = os.environ.pop('BUGGCRAFT_UPDATE_HANDSHAKE', '')
    completed_update = os.environ.pop('BUGGCRAFT_UPDATE_INSTALLED', '') == '1'
    if update_handshake:
        def acknowledge_update_startup():
            try:
                ready_path = Path(update_handshake).resolve()
                if (ready_path.parent == BASE_DIR.resolve() and
                        ready_path.name.startswith('.buggcraft-update-ready-')):
                    ready_path.touch(exist_ok=False)
            except OSError:
                logger.exception('Could not acknowledge successful launcher update startup')
        from PySide6.QtCore import QTimer
        QTimer.singleShot(750, acknowledge_update_startup)
    if startup_report is None:
        _schedule_launcher_update_checks(launcher, app)
    if _payload_cache is not None and startup_report is None:
        from PySide6.QtCore import QTimer
        from threading import Thread
        minimum_age = 0 if completed_update else 24 * 60 * 60
        QTimer.singleShot(5000, lambda: Thread(
            target=lambda: _payload_cache.prune(minimum_age=minimum_age, keep_previous=not completed_update),
            name='payload-cache-cleanup', daemon=True).start())
    logger.info('Startup timing: imports=%.3fs; window=%.3fs; shown=%.3fs',
                imports_seconds, window_seconds, perf_counter() - _STARTUP_STARTED)
    if startup_report is not None:
        from PySide6.QtCore import QTimer
        import json
        def finish_startup_check():
            snapshot = launcher.grab()
            snapshot.save(str(startup_report.with_suffix('.png')))
            result = {'passed': launcher.isVisible() and launcher.width() > 0,
                      'resource_directory': str(RESOURCE_DIR),
                      'game_directory': str(launcher.launcher.minecraft_directory),
                      'launcher_directory': str(BASE_DIR),
                      'rendered': not snapshot.isNull(),
                      'imports_seconds': imports_seconds,
                      'window_seconds': window_seconds,
                      'ready_seconds': perf_counter() - _STARTUP_STARTED,
                      'normal_startup': True}
            startup_report.write_text(json.dumps(result, indent=2), encoding='utf-8')
            launcher.close()
            app.quit()
        QTimer.singleShot(100, finish_startup_check)
    
    # 运行应用
    result = app.exec()
    if startup_config is not None:
        startup_config.cleanup()
    return result


def _schedule_launcher_update_checks(launcher, app):
    from ui.launcher_updates import LauncherUpdateController

    updates = LauncherUpdateController(launcher, app, Path(RESOURCE_DIR), packaged=IS_PACKAGED)
    launcher.launcher_updates = updates
    launcher._update_workers = updates.workers
    launcher._update_check_timer = updates.timer
    settings_page = getattr(launcher, 'settings_page', None)
    if settings_page is not None:
        settings_page.general_page.controller.bind_updates(updates)
    updates.start()
    return updates


def main():
    """Start from the complete, verified resource bundle."""
    if os.path.isdir(os.path.join(RESOURCE_DIR, 'images')):
        return initialize_application()
    logger.error('Bundled resources are missing: %s', RESOURCE_DIR)
    send_notification('启动失败', '启动器资源缺失，请重新解压或安装完整运行包。')
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        logger.exception("程序异常退出")
        send_notification("程序错误", f"发生未处理的异常: {str(e)}")
        sys.exit(1)

