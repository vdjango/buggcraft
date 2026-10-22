"""Application fonts supplied by the operating system, without resource files."""
from PySide6.QtGui import QFont


def system_font(point_size, weight=QFont.Weight.Normal):
    font = QFont()
    font.setPointSize(point_size)
    font.setWeight(weight)
    return font
