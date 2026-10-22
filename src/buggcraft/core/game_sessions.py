"""Own game workers independently so stopping one never stops another."""
import copy

from PySide6.QtCore import QObject, Signal

from config.settings import get_settings_manager
from core.launcher import MinecraftLibLauncher, MinecraftSignals


class GameSessions(QObject):
    changed = Signal()

    def __init__(self, config_path, parent=None):
        super().__init__(parent)
        self.config_path = config_path
        self.settings_manager = get_settings_manager()
        self.signals = MinecraftSignals(self)
        self.minecraft_directory = self.settings_manager.get_setting('minecraft.directory.enable')
        self.minecraft_version = self.settings_manager.get_setting('minecraft.version.enable')
        self.minecraft_isolation_directory = self.settings_manager.get_minecraft_isolation_directory()
        self._options = {}
        self._language = '简体中文'
        self._sessions = []
        self._sequence = 0
        self.selected_id = None

    @property
    def sessions(self):
        return [record for record in self._sessions if record['phase'] != 'exited']

    @property
    def running(self):
        return any(record['phase'] == 'running' for record in self.sessions)

    @property
    def starting(self):
        return any(record['phase'] == 'starting' for record in self.sessions)

    @property
    def start_thread(self):
        return next((record['launcher'].start_thread for record in self._sessions
                     if record['launcher'].start_thread is not None and
                     record['launcher'].start_thread.isRunning()), None)

    @property
    def selected(self):
        return next((record for record in self.sessions if record['id'] == self.selected_id),
                    self.sessions[-1] if self.sessions else None)

    @property
    def process(self):
        return self.selected['launcher'].process if self.selected else None

    @property
    def running_instance(self):
        # Keep the room's original source stable while additional games run.
        record = next((record for record in self.sessions if record['phase'] == 'running'), None)
        return record['instance'] if record else None

    def set_language(self, language):
        self._language = language

    def set_options(self, **options):
        self._options = dict(options)
        self.minecraft_version = options.get('version', self.minecraft_version)

    def start(self):
        if self.starting:
            self.signals.error.emit('已有游戏正在启动，请等待启动完成。')
            return False
        if self.sessions and not self.settings_manager.get_setting('launcher.allow_multiple', False):
            self.signals.error.emit('游戏已经在运行；如需多开，请在设置 → 通用设置中启用允许多开游戏。')
            return False
        # A later version/account/settings change must not affect an active worker.
        snapshot = copy.copy(self.settings_manager)
        snapshot.current_settings = copy.deepcopy(self.settings_manager.current_settings)
        launcher = MinecraftLibLauncher(self.config_path, self)
        launcher.settings_manager = snapshot
        launcher.set_language(self._language)
        launcher.set_options(**self._options)
        self._sequence += 1
        record = {'id': self._sequence, 'launcher': launcher, 'phase': 'starting',
                  'instance': (launcher.minecraft_directory, launcher.minecraft_version,
                               launcher.minecraft_isolation_directory)}
        self._sessions.append(record)
        self.selected_id = record['id']
        launcher.signals.output.connect(lambda text: self.signals.output.emit(
            f"[游戏 {record['id']} · {record['instance'][1]}] {text}"))
        launcher.signals.progress.connect(self.signals.progress)
        launcher.signals.started.connect(lambda: self._started(record))
        launcher.signals.stopped.connect(lambda code: self._stopped(record, code))
        launcher.signals.error.connect(self.signals.error)
        launcher.start()
        # The worker clears launcher.start_thread in its first finished slot;
        # retain the QThread until our own completion slot has also run.
        record['thread'] = launcher.start_thread
        launcher.start_thread.finished.connect(lambda: self._finished(record))
        self.changed.emit()
        return True

    def _started(self, record):
        record['phase'] = 'running'
        self.changed.emit()
        self.signals.started.emit()

    def _stopped(self, record, code):
        record['phase'] = 'exited'
        record['exit_code'] = code
        self.changed.emit()
        self.signals.stopped.emit(code)

    def _finished(self, record):
        if record['phase'] != 'exited':
            self._stopped(record, 1)
        self._sessions.remove(record)
        record['launcher'].deleteLater()
        self.changed.emit()

    def stop(self, force=False):
        record = self.selected
        if record is not None and record['phase'] == 'running':
            record['launcher'].stop(force=force)

    def is_running(self):
        return self.running
