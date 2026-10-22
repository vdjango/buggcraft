"""Shared custom Java picker for global and per-instance settings."""
import os

from PySide6.QtWidgets import QFileDialog, QMessageBox

from config.javafinder import JavaPathFinder


def choose_java(page):
    path, _ = QFileDialog.getOpenFileName(page, '选择 Java 可执行文件', '',
                                         'Java (java.exe javaw.exe java);;所有文件 (*)')
    if not path:
        return False
    path = os.path.realpath(path)
    if os.path.basename(path).lower() == 'javaw.exe':
        path = os.path.join(os.path.dirname(path), 'java.exe')
    raw, version = JavaPathFinder()._get_java_version(path)
    if not os.path.isfile(path) or not raw or not version or version == (0, 0, 0):
        QMessageBox.warning(page, '无法使用 Java', '无法读取所选程序的 Java 版本，请选择 Java bin 目录中的可执行文件。')
        return False
    manager = page.settings_manager
    entries = manager.get_setting('java.installations', []) or []
    entries = [entry for entry in entries if os.path.normcase(entry[0]) != os.path.normcase(path)]
    manager.set_setting('java.installations', entries + [[path, raw, list(version)]])
    manager.set_version_setting('java.path', path)
    manager.set_version_setting('java.name', '自定义 Java 路径|None')
    manager.save_settings()
    page.custom_java_label.setText(path)
    page.custom_java_label.setToolTip(path)
    page.java_panel.set_messages(path)
    return True
