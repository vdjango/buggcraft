import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "buggcraft"))

from PySide6.QtCore import QUrl
from PySide6.QtTest import QSignalSpy
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QApplication, QWidget
from ui.pages.download.tasks import TaskHistoryController


class TaskHistoryQmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_progress_changes_keep_existing_task_rows_and_only_update_changed_data(self):
        page = QWidget()
        page._external_retries = {}
        controller = TaskHistoryController(page)
        task = dict(id='active', state='进行中', version='game', progress=0, maximum=100)
        controller.set_tasks([task])
        controller._publish_tasks()
        model = controller.taskModel
        resets, updates = QSignalSpy(model.modelReset), QSignalSpy(model.dataChanged)
        try:
            for progress in range(1, 101):
                task['progress'] = progress
                controller._publish_tasks()
            self.assertEqual(resets.count(), 0)
            self.assertEqual(updates.count(), 100)
            self.assertEqual(model.data(model.index(0, 0), model.RecordRole)['progress'], 100)
            controller._publish_tasks()
            self.assertEqual(updates.count(), 100)
        finally:
            page.close()

    def test_task_and_file_presentations_hide_raw_error_but_preserve_details(self):
        raw = '{"code": "UPSTREAM_FAILED", "message": "internal detail"}'
        page = QWidget()
        page._external_retries = {}
        task = dict(id='failed', state='失败', version='pack', error=raw, status=raw,
                    files=[dict(name='mod.jar', state='failed', error=raw)], logs=[raw,
                        '12:34:56  详细错误：下载 mod.jar 失败：HTTPSConnectionPool(host=mirror.invalid): ReadTimeoutError'])
        page._find_task = lambda _task_id: task
        controller = TaskHistoryController(page)
        controller.set_tasks([task])
        try:
            self.assertNotIn('{', controller.tasks[0]['error'])
            self.assertNotIn('{', controller.tasks[0]['status'])
            controller.showLog('failed')
            self.assertNotIn('{', controller.currentFiles[0]['error'])
            self.assertNotIn('{', controller.logLines[0])
            self.assertEqual(task['logs'][0], raw)
            self.assertTrue(controller.logLines[1].startswith('12:34:56  mod.jar 下载失败：'))
            self.assertNotIn('ConnectionPool', controller.logLines[1])
            self.assertEqual(task['files'][0]['error'], raw)
        finally:
            controller.closeLog()
            page.close()

    def test_large_file_log_uses_one_shared_model_and_progress_updates_one_row(self):
        page = QWidget()
        page._external_retries = {}
        task = dict(id='assets', state='进行中', version='game',
                    files=[dict(name=f'asset-{index}', key=str(index), state='cached', done=1, total=1)
                           for index in range(20000)], logs=[])
        page._find_task = lambda _task_id: task
        controller = TaskHistoryController(page)
        controller.showLog('assets')
        model = controller.fileModel
        resets, updates = QSignalSpy(model.modelReset), QSignalSpy(model.dataChanged)
        try:
            task['files'][100]['done'] = 2
            controller._refresh_log()
            self.assertEqual(model.rowCount(), 20000)
            self.assertEqual(controller.fileCount, 20000)
            self.assertEqual(resets.count(), 0)
            self.assertEqual(updates.count(), 1)
            self.assertEqual(model.data(model.index(100, 0), model.RecordRole)['done'], 2)
        finally:
            controller.closeLog()
            page.close()

    def test_qml_loads_and_filters_existing_task_records(self):
        page = QWidget()
        page._external_retries = {}
        page._tasks = [
            {"id": "active", "version": "1.21.8-Fabric", "game_dir": "E:/games/main",
             "state": "进行中", "modpack": "pack.mrpack", "status": "安装完成",
             "progress": 100, "maximum": 100},
            {"id": "failed", "version": "1.20.1-Forge", "game_dir": "E:/games/old",
             "state": "失败"},
        ]
        page._find_task = lambda task_id: next((task for task in page._tasks if task["id"] == task_id), None)
        page.task_action = Mock()
        page.clear_completed = Mock()
        controller = TaskHistoryController(page)
        controller.set_tasks(page._tasks)
        widget = QQuickWidget()
        widget.rootContext().setContextProperty("taskHistory", controller)
        qml = Path(__file__).resolve().parents[1] / "resources" / "qml" / "launcher" / "TaskHistory.qml"
        widget.setSource(QUrl.fromLocalFile(str(qml)))
        self.app.processEvents()
        try:
            self.assertEqual(widget.status(), QQuickWidget.Ready,
                             "\n".join(error.toString() for error in widget.errors()))
            self.assertEqual(len(controller.tasks), 2)
            controller.setFilter("失败")
            self.assertEqual([task["id"] for task in controller.tasks], ["failed"])
            controller.setQuery("1.21.8")
            self.assertEqual(controller.tasks, [])
            controller.resetFilters()
            self.assertEqual(len(controller.tasks), 2)
            controller.taskAction("active")
            page.task_action.assert_called_once_with("active")
            controller.clearCompleted()
            page.clear_completed.assert_called_once_with()
        finally:
            widget.close()
            page.close()


if __name__ == "__main__":
    unittest.main()
