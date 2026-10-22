"""Preview an archive before importing it into a separate game instance."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel,
                              QLineEdit, QPushButton, QVBoxLayout)

from core.modpacks import inspect_pack, instance_name, suggested_name


class ModpackImportDialog(QDialog):
    def __init__(self, parent=None, game_dir='', archive='', identity=''):
        super().__init__(parent)
        self.setWindowTitle('导入整合包')
        self.setMinimumWidth(650)
        self.resize(690, 570)
        self.setStyleSheet('''
            QDialog { background: #211e2d; }
            QLabel { color: #e8e1ef; background: transparent; }
            QLabel#heading { font-size: 25px; font-weight: 700; }
            QLabel#subtitle, QLabel#destination { color: #aaa0b8; font-size: 12px; }
            QLabel#section { color: #c9b7dd; font-size: 12px; font-weight: 600; }
            QFrame#card { background: #2c273b; border: 1px solid #40364f; border-radius: 12px; }
            QLabel#preview { font-size: 14px; }
            QLabel#error { color: #ffb5b1; font-size: 12px; }
            QLineEdit { background: #201c2c; color: #f2edf7; border: 1px solid #514461;
                        border-radius: 7px; padding: 11px; font-size: 13px; }
            QLineEdit:focus { border: 1px solid #b190d0; }
            QPushButton { background: #3b324c; color: #eee6f6; border: 1px solid #594769;
                          border-radius: 7px; padding: 10px 18px; font-size: 13px; }
            QPushButton:hover { background: #514160; }
            QPushButton#primary { background: #ad89cb; color: #201729; border: none; font-weight: 700; }
            QPushButton#primary:hover { background: #c39de0; }
            QPushButton#primary:disabled { background: #4a3d59; color: #91819e; }
        ''')
        self.game_dir = game_dir
        self.pack = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 25, 28, 24)
        layout.setSpacing(15)
        heading = QLabel('导入你的整合包')
        heading.setObjectName('heading')
        layout.addWidget(heading)
        subtitle = QLabel('选择本地 ZIP，自动下载所需模组、资源与游戏环境。')
        subtitle.setObjectName('subtitle')
        layout.addWidget(subtitle)
        source = QFrame()
        source.setObjectName('card')
        form = QVBoxLayout(source)
        form.setContentsMargins(18, 16, 18, 18)
        form.setSpacing(10)
        label = QLabel('01  选择整合包')
        label.setObjectName('section')
        form.addWidget(label)
        row = QHBoxLayout()
        self.archive_input = QLineEdit(archive)
        self.archive_input.setPlaceholderText('CurseForge 整合包 · .zip')
        self.archive_input.setClearButtonEnabled(True)
        browse = QPushButton('选择文件')
        browse.clicked.connect(self.browse)
        row.addWidget(self.archive_input, 1)
        row.addWidget(browse)
        form.addLayout(row)
        label = QLabel('新实例名称')
        label.setObjectName('section')
        form.addWidget(label)
        self.name_input = QLineEdit(identity)
        self.name_input.setPlaceholderText('为这个整合包起个名字')
        form.addWidget(self.name_input)
        layout.addWidget(source)
        details = QFrame()
        details.setObjectName('card')
        detail_layout = QVBoxLayout(details)
        detail_layout.setContentsMargins(18, 16, 18, 17)
        detail_layout.setSpacing(10)
        label = QLabel('02  确认内容')
        label.setObjectName('section')
        detail_layout.addWidget(label)
        self.preview = QLabel('选择文件后，这里会显示 Minecraft、加载器版本与下载数量。')
        self.preview.setObjectName('preview')
        self.preview.setTextFormat(Qt.PlainText)
        self.preview.setWordWrap(True)
        self.preview.setMinimumHeight(70)
        detail_layout.addWidget(self.preview)
        layout.addWidget(details)
        self.destination = QLabel()
        self.destination.setObjectName('destination')
        self.destination.setTextFormat(Qt.PlainText)
        self.destination.setWordWrap(True)
        layout.addWidget(self.destination)
        self.name_input.textChanged.connect(self.update_destination)
        self.update_destination()
        self.error = QLabel()
        self.error.setObjectName('error')
        self.error.setTextFormat(Qt.PlainText)
        self.error.setWordWrap(True)
        self.error.hide()
        layout.addWidget(self.error)
        layout.addStretch()
        buttons = QHBoxLayout()
        hint = QLabel('开始后可在下载记录中查看进度、取消或重试')
        hint.setObjectName('subtitle')
        hint.setWordWrap(True)
        buttons.addWidget(hint, 1)
        cancel = QPushButton('取消')
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.import_button = QPushButton('开始导入  →')
        self.import_button.setObjectName('primary')
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self.submit)
        buttons.addWidget(self.import_button)
        layout.addLayout(buttons)
        self.archive_input.textChanged.connect(self.invalidate)
        self.archive_input.editingFinished.connect(self.inspect)
        if archive:
            self.inspect()

    def update_destination(self):
        root = Path(self.game_dir) if self.game_dir else Path('.minecraft')
        self.destination.setText('独立实例目录：' + str(root / 'versions' / (self.identity or '实例名称')))

    def invalidate(self):
        self.pack = None
        self.import_button.setEnabled(False)
        self.preview.setText('文件已更改，确认路径后将重新读取整合包信息。')
        self.error.clear()
        self.error.hide()

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择整合包', '', 'CurseForge 整合包 (*.zip)')
        if path:
            self.archive_input.setText(path)
            self.name_input.clear()
            self.inspect()

    def inspect(self):
        self.pack = None
        self.import_button.setEnabled(False)
        if not self.archive_input.text().strip():
            self.preview.setText('选择文件后，这里会显示 Minecraft、加载器版本与下载数量。')
            self.error.hide()
            return
        try:
            self.pack = inspect_pack(self.archive_input.text().strip())
            if not self.name_input.text().strip():
                self.name_input.setText(suggested_name(self.archive_input.text().strip()))
            info = self.pack
            self.preview.setText(f'{info.name}  ·  {info.version}\n'
                                 f'Minecraft {info.minecraft}    /    '
                                 f'{info.loader + " " + info.loader_version if info.loader else "原版"}\n'
                                 f'{len(info.files)} 个下载文件    ·    内置内容 {info.expanded_bytes / 1024**2:.1f} MiB'
                                 + (f'    ·    建议内存 {info.recommended_ram} MiB' if info.recommended_ram else ''))
            self.error.clear()
            self.error.hide()
            self.import_button.setEnabled(True)
        except Exception as exc:
            self.preview.setText('暂时无法读取这个整合包，请检查所选文件。')
            self.error.setText(str(exc))
            self.error.show()

    def submit(self):
        self.inspect()
        if not self.pack:
            return
        try:
            instance_name(self.identity)
            if self.game_dir and (Path(self.game_dir) / 'versions' / self.identity).exists():
                raise ValueError('该实例名称已存在，请更换名称')
        except ValueError as exc:
            self.error.setText(str(exc))
            self.error.show()
            return
        self.accept()

    @property
    def identity(self):
        return self.name_input.text().strip()

    @property
    def archive(self):
        return str(Path(self.archive_input.text().strip()).resolve())
