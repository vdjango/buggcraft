import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "buggcraft"))

from PySide6.QtCore import QUrl
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QApplication, QWidget
from ui.pages.download.tasks import TaskHistoryController


class TaskHistoryQmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_qml_loads_and_filters_existing_task_records(self):
        page = QWidget()
        page._tasks = [
            {"id": "active", "version": "1.21.8-Fabric", "game_dir": "E:/games/main",
             "state": "进行中"},
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
