# MinecraftLauncher 类

import os
import platform
import subprocess
import signal
import time
import psutil
import logging
import minecraft_launcher_lib

from typing import List
from urllib.parse import urlparse, parse_qs, quote
from base64 import urlsafe_b64encode
from hashlib import sha256
from secrets import token_urlsafe
from PySide6.QtCore import Signal, QObject, QThread

from config.settings import get_settings_manager


logger = logging.getLogger(__name__)

class MinecraftSignals(QObject):
    """Minecraft 信号类"""
    output = Signal(str)
    started = Signal()
    stopped = Signal(int)  # 退出代码
    error = Signal(str)
    progress = Signal(int)  # 进度百分比


class OutputHandlerThread(QThread):
    """处理游戏输出的 Qt 线程"""
    output_received = Signal(str, bool)  # 消息, 是否标准输出
    
    def __init__(self, process):
        super().__init__()
        self.process = process
        self.running = True
    
    def run(self):
        """线程主函数"""
        while self.running and self.process and self.process.poll() is None:
            try:
                # 尝试读取stdout
                if self.process.stdout:
                    try:
                        raw_line = self.process.stdout.readline()
                        if raw_line:
                            try:
                                line = raw_line.decode('utf-8', errors='replace').strip()
                                self.output_received.emit(line, True)
                            except:
                                pass
                    except:
                        pass
                
                # 短暂睡眠
                time.sleep(0.01)  # 等待10毫秒
            except Exception as e:
                self.output_received.emit(f"输出处理错误: {str(e)}", False)
                break
    
    def stop(self):
        """停止线程"""
        self.running = False


class StartGameThread(QThread):
    """启动游戏的 Qt 线程"""
    finished = Signal()
    error = Signal(str)
    
    def __init__(self, launcher):
        super().__init__()
        self.launcher = launcher
    
    def run(self):
        """线程主函数"""
        try:
            self.launcher._start_game()
        except Exception as e:
            self.error.emit(f"启动错误: {str(e)}")
            import traceback
            traceback.print_exc()
        finally:
            self.finished.emit()


class MinecraftLibLauncher(QObject):
    """Minecraft 启动器核心类"""
    
    def __init__(self, config_path, parent=None):
        super().__init__(parent)
        self.signals = MinecraftSignals()
        self.settings_manager = get_settings_manager(config_path)  # 获取配置管理器

        self.process = None
        self.running = False
        self.stopping = False
        self.output_thread = None
        self.start_thread = None
        self.minecraft_directory = self.settings_manager.get_setting('minecraft.directory.enable')
        self.language = "zh_cn"  # 默认语言
        self.version = self.settings_manager.get_setting('minecraft.version.enable')
        self.username = "Player"
        self.server = None
        self.memory = 4096
        self.width = 854
        self.height = 480
        self.fullscreen = False  # 最大化

        self.languages = {
            "English": "en_us",
            "简体中文": "zh_cn",
            "繁體中文": "zh_tw",
            "Français": "fr_fr",
            "Deutsch": "de_de",
            "Español": "es_es",
            "日本語": "ja_jp",
            "한국어": "ko_kr",
            "Русский": "ru_ru"
        }
    
    def set_language(self, language='简体中文'):
        """设置游戏语言"""
        self.language = self.languages[language]

    def set_options(self,
        minecraft_directory=None,
        version=None,
        uuid=None,
        username="Player",
        token=None,
        server=None,
        memory=4096,
        width=854,
        height=480,
        fullscreen=False
    ):
        """设置通用设置
        Args:
            username (str, optional): 游戏用户名。默认为 "Player"。
            uuid (str | None, optional): 玩家的 UUID。默认为 None。
            token (str | None, optional): 认证令牌。默认为 None。
            server (str | None, optional): 要连接的服务器的 IP 地址或域名。默认为 None。
            memory (int, optional): 为游戏分配的内存大小（单位：MB）。默认为 4096。
            width (int, optional): 游戏窗口的宽度。默认为 854。
            height (int, optional): 游戏窗口的高度。默认为 480。
            fullscreen (bool, optional): 是否以全屏模式启动游戏。默认为 False。
        """
        self.uuid = uuid
        self.username = username
        self.token = token
        self.server = server
        self.memory = memory
        self.width = width
        self.height = height
        self.fullscreen = fullscreen
        self.version = version
        

    def start(self):
        """启动 Minecraft 游戏"""
        if self.running:
            self.signals.error.emit("游戏已经在运行中")
            return
        
        # 创建并启动 Qt 线程
        self.start_thread = StartGameThread(self)
        self.start_thread.finished.connect(self._on_start_finished)
        self.start_thread.error.connect(self.signals.error)
        self.start_thread.start()
    
    def _on_start_finished(self):
        """启动线程完成处理"""
        self.start_thread = None
    
    def _start_game(self):
        """在工作线程中启动游戏"""
        try:
            self.minecraft_directory = self.settings_manager.get_setting('minecraft.directory.enable')
            self.version = self.settings_manager.get_setting('minecraft.version.enable')
            
            # 准备启动环境
            if not os.path.exists(self.minecraft_directory):
                os.makedirs(self.minecraft_directory, exist_ok=True)

            # 确保游戏语言设置文件正确配置
            self._ensure_language_setting()

            java_path = self.settings_manager.get_setting("java.path", None)
            memory = self.settings_manager.get_setting("memory.allocation", "自动选择合适的Java")
            launch_jvm_args: str = self.settings_manager.get_setting('game.launch_jvm_args', "").split()
            launch_args: str = self.settings_manager.get_setting('game.launch_args', "").split()
            launch_pre_command: str = self.settings_manager.get_setting('game.launch_pre_command', "").split()

            logger.info(f'[JavaRunTime] -> {java_path}')
        
            if not java_path:
                logger.info('请安装Java环境')  # TODO
                return
            
            jvmArguments = [
                f"-Xmx{memory}M", 
                f"-Xms{memory}M",
                f"-Dfile.encoding=UTF-8",
                "-XX:+UseG1GC",
                "-XX:-UseAdaptiveSizePolicy",
                "-XX:-OmitStackTraceInFastThrow",
                "-Djdk.lang.Process.allowAmbiguousCommands=true",
                "-Dfml.ignoreInvalidMinecraftCertificates=True",
                "-Dfml.ignorePatchDiscrepancies=True",
                "-Dlog4j2.formatMsgNoLookups=true",
                "-Dsun.java2d.dpiaware=true",
                *launch_jvm_args
            ]
            
            # 准备通用设置
            options = {
                "executablePath": java_path,
                "username": self.username,
                "server": self.server,
                "gameDirectory": self.minecraft_directory,
                "version": self.version,
                "jvmArguments": list(set(jvmArguments)),
                "launcherName": "BuggCraft Launcher",
                "launcherVersion": "1.0",
            }
            
            if self.uuid: options['uuid'] = self.uuid

            if self.token:
                options['token'] = self.token
                self.signals.output.emit(f"使用离线账户: {self.username}")

            if self.server: self.signals.output.emit(f"连接服务器: {self.server}")
            
            # 安装游戏库文件
            self.signals.output.emit("正在安装游戏库文件...")
            minecraft_launcher_lib.install.install_minecraft_version(
                self.version, 
                self.minecraft_directory,
                callback={
                    "setStatus": lambda msg: self.signals.output.emit(f"[安装] {msg}"),
                    "setProgress": lambda progress: self.signals.progress.emit(progress),
                    "setMax": lambda max_value: self.signals.output.emit(f"[最大] {max_value}")
                }
            )

            # 获取启动命令
            command: list[str] = minecraft_launcher_lib.command.get_minecraft_command(
                self.version, 
                self.minecraft_directory,
                options
            )

            # 设置窗口大小
            if not self.fullscreen:
                size = ['--width', str(self.width), '--height', str(self.height)]
                if self.width is not None and self.height is not None:
                    for i in size:
                        command.append(i)
            else:
                # TODO: 当前最大化 是先开起小窗口，加载完成后最大化进入游戏菜单页面
                command.append('--fullscreen')
            
            for arg in launch_args:
                command.append(arg)

            # 清理命令参数
            command = [arg for arg in command if arg != "None" and arg is not None]

            # 打印命令用于调试
            self.signals.output.emit(f"启动命令: {' '.join(command)}")

            # 启动游戏进程
            startup_flags = 0
            if platform.system() == "Windows":
                startup_flags = subprocess.CREATE_NEW_PROCESS_GROUP
            
            # 创建环境变量副本
            env = os.environ.copy()
            # 设置环境变量确保使用UTF-8
            env['LANG'] = self.language + '.UTF-8'
            env['LC_ALL'] = self.language + '.UTF-8'
            env['JAVA_OPTS'] = '-Dfile.encoding=UTF-8'

            try:
                for com in launch_pre_command:
                    subprocess.Popen(
                        com,
                        cwd=self.minecraft_directory,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        stdin=subprocess.PIPE,
                        creationflags=startup_flags,
                        env=env
                    )
            except Exception as e:
                logger.info('[启动前指令]', e.args)

            self.process = subprocess.Popen(
                command,
                cwd=self.minecraft_directory,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                creationflags=startup_flags,
                env=env
            )
            # 记录进程ID
            self.signals.output.emit(f"游戏进程PID: {self.process.pid}")

            # 获取用户在你的 ComboBox 中选择的优先级文本
            # 假设你有一个方法来获取设置，例如从你的设置管理器
            priority_setting = self.settings_manager.get_setting("launcher.process_priority") # 例如返回 "高 (优先保证游戏运行，但可能造成其他程序卡顿)"

            # 根据用户选择映射到系统的优先级值
            # 注意：psutil 的优先级常量在不同系统上可能不同，以下是一个通用映射尝试
            if "高" in priority_setting:
                target_priority = psutil.HIGH_PRIORITY_CLASS if os.name == 'nt' else -10 # Windows HIGH_PRIORITY_CLASS, Unix nice -10
            elif "低" in priority_setting:
                target_priority = psutil.BELOW_NORMAL_PRIORITY_CLASS if os.name == 'nt' else 10 # Windows BELOW_NORMAL, Unix nice 10
            else: # 默认或"中"
                target_priority = psutil.NORMAL_PRIORITY_CLASS if os.name == 'nt' else 0 # Windows NORMAL, Unix nice 0

            try:
                # 创建 psutil.Process 对象
                p = psutil.Process(self.process.pid)
                # 设置优先级
                p.nice(target_priority)
                logger.info(f"成功将 Minecraft 进程 (PID: {self.process.pid}) 优先级设置为: {priority_setting}")
            except Exception as e:
                logger.info(f"设置进程优先级时出错: {e}. 进程可能已退出，或无足够权限。")
            # 注意：在某些系统上，设置高优先级可能需要提升的权限（如管理员/root）
            
            # 启动输出处理线程
            self.output_thread = OutputHandlerThread(self.process)
            self.output_thread.output_received.connect(self._handle_output)
            self.output_thread.start()
            
            # 设置状态
            self.running = True
            self.stopping = False
            
            # 发送启动信号
            self.signals.started.emit()
            
            # 等待进程结束
            self.exit_code = self.process.wait()
            
            # 发送停止信号
            self.signals.stopped.emit(self.exit_code)
        finally:
            self.running = False
            self.stopping = False
            self.process = None

    def _ensure_language_setting(self):
        """确保游戏语言设置文件正确配置"""
        options_file = os.path.join(self.minecraft_directory, "options.txt")
        
        try:
            # 读取现有选项
            options = {}
            if os.path.exists(options_file):
                with open(options_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        if ':' in line:
                            key, value = line.split(':', 1)
                            options[key.strip()] = value.strip()
            
            # 强制设置语言选项
            options['lang'] = self.language
            
            # 写入新选项
            with open(options_file, 'w', encoding='utf-8') as f:
                for key, value in options.items():
                    f.write(f"{key}:{value}\n")
            
            self.signals.output.emit(f"已设置游戏语言: {self.language}")
        except Exception as e:
            self.signals.error.emit(f"设置游戏语言时出错: {str(e)}")

    def _handle_output(self, message, is_stdout):
        """处理输出消息"""
        # 检查语言设置是否生效
        if "Setting user: " in message:
            self.signals.output.emit(f"语言设置: {self.language}")
        
        # 发送消息
        if is_stdout:
            self.signals.output.emit(message)
        else:
            self.signals.error.emit(message)
    
    def stop(self, force: bool = False) -> None:
        """停止游戏进程及其所有子进程
        
        Args:
            force: 是否强制终止进程。为True时跳过关闭直接强制杀死进程。
        """
        logger.info(f'[Stop] 停止请求: force={force}, 当前状态: running={self.running}, stopping={self.stopping}')
        
        # 检查是否已在停止过程中或未运行
        if not self.running or self.stopping:
            logger.info('[Stop] 进程未运行或已在停止中，无需操作')
            return
        
        self.stopping = True
        self.signals.output.emit("正在停止游戏...")
        
        try:
            # 1. 首先尝试终止
            if not force:
                if self._attempt_graceful_shutdown():
                    self._cleanup_after_stop()
                    return
            
            # 2. 强制终止路径
            # 获取需要终止的所有进程ID（包括子进程）
            pids_to_kill = self._get_all_process_pids()
            logger.info(f'[Stop] 需要终止的进程列表: {pids_to_kill}')
            
            # 首先尝试发送SIGTERM（Unix）或terminate（Windows）
            if not self._terminate_processes(pids_to_kill):
                logger.info('[Stop] 终止失败，将进行强制终止')
                # 强制终止所有进程
                self._kill_processes_forcefully(pids_to_kill)
            
            # 3. 最终清理
            self._cleanup_after_stop()
            
        except Exception as e:
            error_msg = f"停止进程时发生错误: {str(e)}"
            logger.info(f'[Stop] {error_msg}')
            self.signals.error.emit(error_msg)
        finally:
            self.stopping = False
            if not self.running:
                logger.info('[Stop] 进程已完全停止')


    def _get_all_process_pids(self) -> List[int]:
        """获取需要终止的所有进程ID（包括主进程和所有子进程）"""
        pids_to_kill = []
        
        # 添加主进程
        if hasattr(self, 'process') and self.process:
            try:
                if self.process.poll() is None:  # 进程仍在运行
                    pids_to_kill.append(self.process.pid)
                    
                    # 使用psutil获取所有子进程
                    try:
                        parent = psutil.Process(self.process.pid)
                        children = parent.children(recursive=True)  # 递归获取所有子进程
                        for child in children:
                            pids_to_kill.append(child.pid)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        logger.info('[Stop] 无法获取子进程信息，可能进程已退出')
            except:
                pass
        
        # 去重并返回
        return list(set(pids_to_kill))

    def _terminate_processes(self, pids: List[int]) -> bool:
        """尝试终止所有进程，返回是否成功"""
        all_terminated = True
        
        for pid in pids:
            try:
                proc = psutil.Process(pid)
                if platform.system() == "Windows":
                    proc.terminate()  # Windows: terminate()
                else:
                    proc.send_signal(signal.SIGTERM)  # Unix: SIGTERM
                logger.info(f'[Stop] 已向进程 {pid} 发送终止信号')
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                logger.info(f'[Stop] 进程 {pid} 已退出或无访问权限')
                continue
        
        # 等待进程退出
        timeout = 5  # 等待5秒
        start_time = time.time()
        
        for pid in pids:
            try:
                proc = psutil.Process(pid)
                while time.time() - start_time < timeout:
                    if proc.is_running():
                        time.sleep(0.1)
                    else:
                        break
                else:
                    logger.info(f'[Stop] 进程 {pid} 在{timeout}秒内未退出')
                    all_terminated = False
            except psutil.NoSuchProcess:
                continue
        
        return all_terminated

    def _kill_processes_forcefully(self, pids: List[int]) -> None:
        """强制终止所有进程"""
        for pid in pids:
            try:
                proc = psutil.Process(pid)
                if proc.is_running():
                    if platform.system() == "Windows":
                        # Windows: 使用taskkill命令强制终止进程树
                        subprocess.run([
                            "taskkill", 
                            "/F",  # 强制
                            "/T",  # 终止子进程
                            "/PID", str(pid)
                        ], capture_output=True, timeout=5)
                        logger.info(f'[Stop] 已强制终止Windows进程 {pid}')
                    else:
                        # Unix: 发送SIGKILL
                        os.kill(pid, signal.SIGKILL)
                        logger.info(f'[Stop] 已向进程 {pid} 发送SIGKILL')
                    
                    # 等待确认进程终止
                    try:
                        proc.wait(timeout=20)
                    except (psutil.NoSuchProcess, psutil.TimeoutExpired):
                        pass
                        
            except (psutil.NoSuchProcess, psutil.AccessDenied, subprocess.TimeoutExpired, Exception) as e:
                logger.info(f'[Stop] 强制终止进程 {pid} 时出错: {e}')
                continue

    def _attempt_graceful_shutdown(self) -> bool:
        """尝试关闭进程"""
        try:
            # 如果有标准输入，可以尝试发送关闭命令
            if hasattr(self, 'process') and self.process and self.process.stdin:
                try:
                    self.process.stdin.write(b'stop\n')
                    self.process.stdin.flush()
                    logger.info('[Stop] 已发送停止命令')
                    
                    # 等待一段时间看进程是否自行退出
                    for _ in range(10):  # 等待最多2秒
                        if self.process.poll() is not None:
                            return True
                        time.sleep(0.2)
                except (IOError, OSError):
                    pass  #  stdin可能已关闭
            
            return False
        except Exception as e:
            logger.info(f'[Stop] 停止尝试失败: {e}')
            return False

    def _cleanup_after_stop(self) -> None:
        """停止后的清理工作"""
        # 关闭进程标准流
        if hasattr(self, 'process') and self.process:
            for stream in [self.process.stdin, self.process.stdout, self.process.stderr]:
                if stream:
                    try:
                        stream.close()
                    except:
                        pass
        
        # 停止输出线程
        if hasattr(self, 'output_thread') and self.output_thread:
            try:
                self.output_thread.stop()
                self.output_thread.quit()
                try:
                    self.output_thread.wait(timeout=20)
                except Exception as e:
                    pass
                self.output_thread = None
                logger.info('[Stop] 输出线程已停止')
            except Exception as e:
                logger.info(f'[Stop] 停止输出线程时出错: {e}')
        
        # 重置状态
        self.running = False
        self.stopping = False
        logger.info('[Stop] 清理完成')


    
    def is_running(self):
        """检查游戏是否正在运行"""
        return self.running
    
    def get_exit_code(self):
        """获取游戏退出代码"""
        return self.exit_code if hasattr(self, 'exit_code') else None
    
    def cleanup(self):
        """清理所有资源"""
        if self.running:
            self.stop()
        
        if self.process:
            try:
                if self.process.stdin:
                    self.process.stdin.close()
                if self.process.stdout:
                    self.process.stdout.close()
                self.process.terminate()
            except:
                pass
            self.process = None


