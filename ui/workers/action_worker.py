from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, Signal, Slot


class ActionWorker(QObject):
    # 负责在后台线程里执行一次性动作，例如 RPC 查询、生成脚本、重启 App。
    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, action: Callable[[], Any]) -> None:
        super().__init__()
        self.action = action

    @Slot()
    def run(self) -> None:
        try:
            result = self.action()
            self.succeeded.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()
