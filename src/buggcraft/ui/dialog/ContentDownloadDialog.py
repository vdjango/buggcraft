from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QLineEdit, QPushButton, QVBoxLayout,
)

from core.content import ModrinthClient


class _QuerySignals(QObject):
    finished = Signal(int, str, object, str)


class _QueryWorker(QRunnable):
    def __init__(self, request_id, mode, action, callback):
        super().__init__()
        self.request_id = request_id
        self.mode = mode
        self.action = action
        self.signals = _QuerySignals()
        self.signals.finished.connect(callback)

    @Slot()
    def run(self):
        try:
            self.signals.finished.emit(self.request_id, self.mode, self.action(), "")
        except Exception as exc:
            self.signals.finished.emit(self.request_id, self.mode, None, str(exc))


class ContentDownloadDialog(QDialog):
    KINDS = (("模组", "mod"), ("资源包", "resourcepack"), ("光影", "shader"), ("整合包", "modpack"))

    def __init__(self, parent, game_version="", loader="", kind="mod"):
        super().__init__(parent)
        self.setWindowTitle("下载模组 / 资源包 / 光影 / 整合包")
        self.resize(680, 540)
        self.client = ModrinthClient()
        self.game_version = game_version
        self.loader = loader
        self.selected_version = None
        self._available_versions = []
        self._request_id = 0
        self._closed = False
        self._workers = {}
        self._pool = QThreadPool.globalInstance()

        root = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.kind = QComboBox()
        for title, value in self.KINDS:
            self.kind.addItem(title, value)
        self.query = QLineEdit()
        self.query.setPlaceholderText("搜索名称或关键词")
        self.search_button = QPushButton("搜索")
        controls.addWidget(self.kind)
        controls.addWidget(self.query, 1)
        controls.addWidget(self.search_button)
        root.addLayout(controls)

        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setStyleSheet("color: #bfb4ff;")
        root.addWidget(self.info)
        self.versions = QComboBox()
        self.versions.currentIndexChanged.connect(self._set_version)
        self.versions.hide()
        root.addWidget(self.versions)
        self.results = QListWidget()
        self.results.itemDoubleClicked.connect(self.choose)
        root.addWidget(self.results, 1)

        actions = QHBoxLayout()
        actions.addStretch()
        self.install = QPushButton("下载")
        self.install.setEnabled(False)
        self.install.clicked.connect(self.accept)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        actions.addWidget(self.install)
        actions.addWidget(cancel)
        root.addLayout(actions)

        self.search_button.clicked.connect(self.search)
        self.query.returnPressed.connect(self.search)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self._show_context()
        index = self.kind.findData(kind)
        if index >= 0:
            self.kind.setCurrentIndex(index)

    def _show_context(self):
        kind = self.kind.currentData()
        if kind == "modpack":
            self.info.setText("整合包按 .mrpack 文件下载；当前自动导入仅支持 CurseForge ZIP。")
        elif kind == "shader":
            self.info.setText("光影需要与当前 Minecraft 版本兼容的光影加载模组。")
        elif kind == "mod":
            self.info.setText("Minecraft {} · {}。模组依赖需按项目说明另行安装。".format(
                self.game_version or "未选择版本", self.loader or "未选择加载器"))
        else:
            self.info.setText("Minecraft {}。资源包按游戏版本筛选，不受模组加载器限制。".format(
                self.game_version or "未选择版本"))

    def _clear_version(self):
        self.selected_version = None
        self._available_versions = []
        self.versions.blockSignals(True)
        self.versions.clear()
        self.versions.hide()
        self.versions.blockSignals(False)
        self.install.setEnabled(False)

    def _invalidate(self):
        self._request_id += 1
        return self._request_id

    def _kind_changed(self, _index):
        self._invalidate()
        self.results.clear()
        self._clear_version()
        self.search_button.setEnabled(True)
        self._show_context()

    def _start_query(self, mode, action):
        request_id = self._invalidate()
        worker = _QueryWorker(request_id, mode, action, self._query_finished)
        self._workers[request_id] = worker
        self._pool.start(worker)

    def search(self):
        query = self.query.text().strip()
        kind = self.kind.currentData()
        game_version = self.game_version
        loader = self.loader if kind in ("mod", "modpack") else ""
        self.results.clear()
        self._clear_version()
        self.search_button.setEnabled(False)
        self.info.setText("正在搜索…")
        self._start_query("search", lambda: self.client.search(query, kind, game_version, loader))

    def choose(self, item):
        project = item.data(Qt.ItemDataRole.UserRole)
        kind = self.kind.currentData()
        game_version = self.game_version
        loader = self.loader if kind in ("mod", "modpack") else ""
        self._clear_version()
        self.info.setText("正在查询可用版本…")
        self._start_query("versions", lambda: self.client.versions(project, game_version, loader, kind))

    def _query_finished(self, request_id, mode, result, error):
        self._workers.pop(request_id, None)
        if self._closed or request_id != self._request_id:
            return
        self.search_button.setEnabled(True)
        if error:
            self.info.setText(error)
            return
        if mode == "search":
            for hit in result:
                identity = hit.get("project_id") or hit.get("slug")
                if not identity:
                    continue
                title = hit.get("title") or hit.get("name") or hit.get("slug") or identity
                description = (hit.get("description") or "").replace("\n", " ")
                item = QListWidgetItem(f"{title}  ·  {description[:120]}")
                item.setData(Qt.ItemDataRole.UserRole, identity)
                self.results.addItem(item)
            self.info.setText(f"找到 {self.results.count()} 个项目，双击项目查看可用版本。")
            return
        self._available_versions = result if isinstance(result, list) else []
        if not self._available_versions:
            self.info.setText("没有找到兼容当前条件的版本。")
            return
        self.versions.blockSignals(True)
        for version in self._available_versions:
            label = version.get("name") or version.get("version_number") or "未知版本"
            published = (version.get("date_published") or "")[:10]
            self.versions.addItem(f"{label} · {published}" if published else label)
        self.versions.blockSignals(False)
        self.versions.show()
        self.versions.setCurrentIndex(0)
        self._set_version(0)

    def _set_version(self, index):
        if 0 <= index < len(self._available_versions):
            self.selected_version = self._available_versions[index]
            self.install.setEnabled(True)
            label = self.selected_version.get("name") or self.selected_version.get("version_number") or ""
            self.info.setText(f"已选择 {label}，下载后会校验文件哈希。")
        else:
            self.selected_version = None
            self.install.setEnabled(False)

    def done(self, result):
        self._closed = True
        self._invalidate()
        super().done(result)
