"""Ask on the UI thread while an import worker waits for an explicit choice."""
import threading

from PySide6.QtCore import QObject, QTimer, Qt, Slot

from core.downloads import DownloadCancelled


class MissingModDecision:
    def __init__(self, mods):
        self.mods = [dict(item) for item in mods]
        self._answered = threading.Event()
        self.accepted = False

    def answer(self, accepted):
        if not self._answered.is_set():
            self.accepted = accepted is True
            self._answered.set()

    def wait(self, cancel):
        while not self._answered.wait(.1):
            if cancel.is_set():
                raise DownloadCancelled('整合包导入已取消，已下载文件会保留。')
        if cancel.is_set():
            raise DownloadCancelled('整合包导入已取消，已下载文件会保留。')
        return self.accepted


class MissingModPrompts(QObject):
    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.pending = []
        self.dialog = None
        self.current = None
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._check_cancelled)

    @Slot(str, object)
    def request(self, task_id, decision):
        worker = self.page._workers.get(task_id)
        if self.page._closing or worker is None or worker.cancel_event.is_set():
            decision.answer(False)
            return
        self.pending.append((task_id, decision))
        self._open_next()

    def _open_next(self):
        if self.dialog is not None or not self.pending or self.page._closing:
            return
        task_id, decision = self.pending.pop(0)
        worker = self.page._workers.get(task_id)
        if worker is None or worker.cancel_event.is_set():
            decision.answer(False)
            self._open_next()
            return
        task = self.page._find_task(task_id)
        task['status'] = '有模组暂时无法下载，等待选择是否跳过…'
        self.page._log(task, task['status'])
        self.page._persist_and_refresh()
        from ui.dialog.qml_dialog import QmlDialog
        dialog = QmlDialog(self.page.window(), resources=self.page.resource_path,
            title='有模组暂时无法下载', width=550, height=min(500, 350 + len(decision.mods) * 50),
            source='MissingModsDialog.qml', data=dict(mods=decision.mods, instance=task['version']),
            actions=['停止导入', '跳过并继续'], primary_action='跳过并继续')
        dialog.setWindowModality(Qt.WindowModal)
        self.dialog, self.current = dialog, (task_id, decision)

        def action(name):
            if name == '跳过并继续':
                task['skipped_mods'] = [dict(item) for item in decision.mods]
                for item in decision.mods:
                    self.page._log(task, '已确认跳过模组：' + item['name'])
                self.page._log(task, '联机时，房主使用的缺失模组需要向房主索要；房主未使用的模组无需补齐。')
                self.page._persist_and_refresh()
                decision.answer(True)
                dialog.accept()
            elif name == '停止导入':
                dialog.reject()

        def closed(_result):
            if not decision.accepted:
                if task['state'] in self.page.ACTIVE and task_id in self.page._workers:
                    self.page.task_action(task_id)
                decision.answer(False)
            self.timer.stop()
            self.dialog, self.current = None, None
            dialog.shutdown()
            QTimer.singleShot(0, dialog, dialog.deleteLater)
            QTimer.singleShot(0, self, self._open_next)

        dialog.controller.actionRequested.connect(action)
        dialog.finished.connect(closed)
        self.timer.start()
        dialog.show()

    def _check_cancelled(self):
        if self.current is not None:
            worker = self.page._workers.get(self.current[0])
            if worker is None or worker.cancel_event.is_set():
                self.dialog.reject()

    def close(self):
        self.timer.stop()
        for _task_id, decision in self.pending:
            decision.answer(False)
        self.pending.clear()
        if self.dialog is not None:
            self.dialog.reject()
