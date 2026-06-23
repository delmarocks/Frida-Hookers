from __future__ import annotations

from PySide6.QtWidgets import QDialog, QScrollArea, QVBoxLayout, QWidget


class DebugToolsDialog(QDialog):
    """调试与分析工具面板对话框。

    采用“容器迁移、引用保留”的设计：所有按钮/输入框仍由主窗口创建并持有引用，
    本对话框只负责把它们收纳进一个可滚动的弹窗里；主界面用单个按钮触发显示。
    因此主窗口的 set_busy / composition 接线 / 各 controller 全部无需改动。
    """

    def __init__(self, owner: QWidget | None = None) -> None:
        super().__init__(owner)
        self.setWindowTitle("调试与分析工具")
        # 非模态：注入动作的结果输出到主界面日志区，弹窗期间用户仍可查看日志。
        self.setModal(False)
        self.resize(620, 760)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        # 工具项较多，放进可滚动区域，避免弹窗过高。
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setObjectName("debugToolsScroll")
        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(10)
        self._scroll.setWidget(content)
        outer.addWidget(self._scroll)
