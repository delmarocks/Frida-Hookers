from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QWheelEvent

from ui.widgets import NoWheelComboBox


def _wheel_event(widget, delta: int) -> QWheelEvent:
    pos = QPoint(5, 5)
    global_pos = widget.mapToGlobal(pos)
    return QWheelEvent(
        pos,
        global_pos,
        QPoint(0, 0),
        QPoint(0, delta),
        Qt.NoButton,
        Qt.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )


def test_no_wheel_combo_box_ignores_wheel(qapp) -> None:
    combo = NoWheelComboBox()
    combo.addItems(["甲", "乙", "丙"])
    combo.setCurrentIndex(1)

    # 向上/向下滚轮都不应改变当前选中项
    combo.wheelEvent(_wheel_event(combo, 120))
    assert combo.currentIndex() == 1
    combo.wheelEvent(_wheel_event(combo, -120))
    assert combo.currentIndex() == 1

    # 键盘/编程切换仍正常
    combo.setCurrentIndex(2)
    assert combo.currentIndex() == 2
    combo.deleteLater()
