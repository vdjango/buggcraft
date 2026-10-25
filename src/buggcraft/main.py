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

from PySide6.QtGui import QIcon
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
    if startup_report is None:
        _schedule_launcher_update_checks(launcher, app)
    if _payload_cache is not None and startup_report is None:
        from PySide6.QtCore import QTimer
        from threading import Thread
        QTimer.singleShot(5000, lambda: Thread(
            target=_payload_cache.prune, name='payload-cache-cleanup', daemon=True).start())
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
    if not IS_PACKAGED:
        return
    from PySide6.QtCore import QThread, QTimer, QUrl, Qt, Signal
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QMessageBox, QProgressDialog
    from core.update_client import apply_update, check_for_update, current_version, download_update

    resource_path = Path(RESOURCE_DIR)
    version = current_version(resource_path)
    setting = get_settings_manager().get_setting('settings.general.update', 'stable')
    channel = 'beta' if setting == 'development' else 'stable'
    prompted = set()

    class CheckWorker(QThread):
        result = Signal(object)

        def run(self):
            try:
                self.result.emit(check_for_update(version, channel))
            except Exception as exc:
                logger.info('Launcher update check unavailable: %s', exc)
                self.result.emit(None)

    class DownloadWorker(QThread):
        progress = Signal(int)
        completed = Signal(object, str)

        def __init__(self, update):
            super().__init__(launcher)
            self.update = update

        def run(self):
            try:
                executable = Path(sys.argv[0]).resolve()
                directory = executable.parent
                if platform.system() == 'Darwin':
                    bundle = next(parent for parent in executable.parents if parent.suffix == '.app')
                    directory = bundle.parent
                package = download_update(
                    self.update, directory,
                    lambda done, total: self.progress.emit(int(done * 1000 / total)))
                self.completed.emit(package, '')
            except Exception as exc:
                self.completed.emit(None, str(exc))

    workers = []
    launcher._update_workers = workers

    def offer(update):
        if not update or update['version'] in prompted:
            return
        prompted.add(update['version'])
        box = QMessageBox(launcher)
        box.setWindowTitle('发现启动器更新')
        box.setIcon(QMessageBox.Information)
        box.setTextFormat(Qt.PlainText)
        box.setText(f"Buggcraft {update['version']} 已发布。\n当前版本：{version}")
        box.setInformativeText(update.get('notes') or '修复问题并改进启动器体验。')
        install_button = box.addButton('立即更新', QMessageBox.AcceptRole)
        box.addButton('稍后提醒', QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not install_button:
            return
        if getattr(launcher, 'started_page', None) and launcher.started_page.launcher.running:
            QMessageBox.information(launcher, '请先关闭游戏', '游戏运行期间无法替换启动器，请关闭游戏后再次启动启动器。')
            return

        progress = QProgressDialog('正在下载并校验更新…', None, 0, 1000, launcher)
        progress.setWindowTitle('更新 Buggcraft')
        progress.setWindowModality(Qt.WindowModal)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setValue(0)
        worker = DownloadWorker(update)
        workers.append(worker)
        worker.progress.connect(progress.setValue)

        def complete(package, error):
            worker.wait()
            progress.close()
            workers.remove(worker)
            if error:
                logger.warning('Launcher update download failed: %s', error)
                QMessageBox.warning(launcher, '更新下载失败', error + '\n\n将打开官网对应平台的下载页面。')
                QDesktopServices.openUrl(QUrl(update['download_page']))
                return
            try:
                apply_update(Path(package))
                app.quit()
            except Exception as exc:
                logger.exception('Could not install launcher update')
                QMessageBox.warning(launcher, '无法自动安装', str(exc) + '\n\n将打开官网对应平台的下载页面。')
                QDesktopServices.openUrl(QUrl(update['download_page']))

        worker.completed.connect(complete)
        worker.start()
        progress.show()

    def start_check():
        worker = CheckWorker(launcher)
        workers.append(worker)

        def completed(update):
            workers.remove(worker)
            offer(update)

        worker.result.connect(completed)
        worker.start()

    QTimer.singleShot(7000, start_check)
    timer = QTimer(launcher)
    timer.setInterval(60 * 60 * 1000)
    timer.timeout.connect(start_check)
    timer.start()
    launcher._update_check_timer = timer


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

