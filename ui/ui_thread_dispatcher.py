from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, Signal, Slot


class UiThreadDispatcher(QObject):
    """把任意 Python 回调安全切回当前 QObject 所在线程执行。"""

    _invoke = Signal(object, tuple)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._invoke.connect(self._dispatch)

    def submit(self, callback: Callable[..., Any], *args: Any) -> None:
        self._invoke.emit(callback, args)

    @Slot(object, tuple)
    def _dispatch(self, callback: Callable[..., Any], args: tuple[Any, ...]) -> None:
        callback(*args)
