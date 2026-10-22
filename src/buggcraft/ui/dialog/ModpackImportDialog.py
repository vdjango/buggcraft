"""Local CurseForge pack import preview."""
import os
from pathlib import Path

from PySide6.QtWidgets import (QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                              QLineEdit, QPushButton, QVBoxLayout)

from core.modpacks import inspect_pack, instance_name, suggested_name


class ModpackImportDialog(QDialog):
    def __init__(self, parent=None, game_dir='', archive='', identity=''):
        super().__init__(parent)
        self.setWindowTitle('导入整合包')
        self.resize(610, 420)
        self.setStyleSheet('QDialog { background: #272937; color: #eee; } '
                          'QLabel { color: #ddd; } QLineEdit { background: #211f2b; color: #eee; padding: 7px; } '
                          'QPushButton { background: #514065; color: #eee; padding: 8px 14px; }')
        self.game_dir = game_dir
        self.pack = None
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        form = QFormLayout()
        row = QHBoxLayout()
        self.archive_input = QLineEdit(archive)
        self.archive_input.setPlaceholderText('选择 CurseForge 整合包 ZIP')
        browse = QPushButton('浏览…')
        browse.clicked.connect(self.browse)
        row.addWidget(self.archive_input, 1)
        row.addWidget(browse)
        form.addRow('整合包', row)
        self.name_input = QLineEdit(identity)
        form.addRow('新实例名称', self.name_input)
        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.Password)
        self.key_input.setPlaceholderText('CurseForge API 密钥（或使用环境变量）')
        form.addRow('下载授权', self.key_input)
        layout.addLayout(form)
        self.preview = QLabel('选择压缩包后显示游戏版本、加载器和文件数。')
        self.preview.setWordWrap(True)
        layout.addWidget(self.preview)
        note = QLabel('导入到：' + (game_dir or '启动器默认 Minecraft 目录') +
                      '\n整合包使用独立游戏目录。不会覆盖已有实例。\n密钥仅在本次运行中使用，不写入设置或任务记录。')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet('color: #ffb8ad;')
        layout.addWidget(self.error)
        layout.addStretch()
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.import_button = QPushButton('开始导入')
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self.submit)
        cancel = QPushButton('取消')
        cancel.clicked.connect(self.reject)
        buttons.addWidget(self.import_button)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        self.archive_input.editingFinished.connect(self.inspect)
        if archive:
            self.inspect()

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择整合包', '', 'CurseForge 整合包 (*.zip)')
        if path:
            self.archive_input.setText(path)
            self.name_input.clear()
            self.inspect()

    def inspect(self):
        self.pack = None
        self.import_button.setEnabled(False)
        try:
            self.pack = inspect_pack(self.archive_input.text().strip())
            if not self.name_input.text().strip():
                self.name_input.setText(suggested_name(self.archive_input.text().strip()))
            info = self.pack
            self.preview.setText(f'{info.name} · 清单版本 {info.version}\nMinecraft {info.minecraft} · '
                                 f'{info.loader + " " + info.loader_version if info.loader else "原版"}\n'
                                 f'{len(info.files)} 个下载条目 · 内置文件展开约 {info.expanded_bytes / 1024**2:.1f} MiB'
                                 + (f' · 建议内存 {info.recommended_ram} MiB' if info.recommended_ram else ''))
            self.error.clear()
            self.import_button.setEnabled(True)
        except Exception as exc:
            self.preview.setText('无法导入此压缩包')
            self.error.setText(str(exc))

    def submit(self):
        self.inspect()
        if not self.pack:
            return
        try:
            instance_name(self.identity)
            if self.game_dir and (Path(self.game_dir) / 'versions' / self.identity).exists():
                raise ValueError('该实例名称已存在，请更换名称')
            if self.pack.files and not self.api_key and not os.environ.get('BUGGCRAFT_CURSEFORGE_API_KEY'):
                raise ValueError('此整合包需要下载 CurseForge 文件，请填写 API 密钥（或设置 BUGGCRAFT_CURSEFORGE_API_KEY）')
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self.accept()

    @property
    def identity(self):
        return self.name_input.text().strip()

    @property
    def archive(self):
        return str(Path(self.archive_input.text().strip()).resolve())

    @property
    def api_key(self):
        return self.key_input.text().strip()
