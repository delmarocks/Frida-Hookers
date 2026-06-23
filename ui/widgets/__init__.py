from __future__ import annotations

from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QComboBox


class NoWheelComboBox(QComboBox):
    """滚轮不改变选中项的下拉框。

    Qt 默认的 QComboBox 在鼠标悬停时滚动滚轮会直接切换选项，在长表单或可滚动面板里
    滚动页面时极易误改选择。这里忽略滚轮事件并向上传递，使滚轮只用于滚动父级区域，
    不再影响当前选择；需要切换选项时仍可点击展开或用键盘方向键。
    """

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 (Qt 命名)
        event.ignore()


__all__ = ["NoWheelComboBox"]
