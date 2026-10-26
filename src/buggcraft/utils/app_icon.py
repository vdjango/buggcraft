"""Use the shipped launcher artwork for application and window icons."""
from pathlib import Path

from PySide6.QtGui import QIcon


def get_app_icon(resource_path) -> QIcon:
    root = Path(resource_path)
    for relative in ('icons/app.ico', 'icons/1024x1024/app.png'):
        icon = QIcon(str(root / relative))
        if not icon.isNull():
            return icon
    return QIcon.fromTheme('app')
