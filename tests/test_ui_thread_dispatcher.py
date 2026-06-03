from __future__ import annotations

import threading
import time

from PySide6.QtCore import QThread

from ui.ui_thread_dispatcher import UiThreadDispatcher


def _process_until(qapp, predicate, timeout: float = 1.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        qapp.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    qapp.processEvents()
    assert predicate()


def test_ui_thread_dispatcher_runs_callback_on_main_thread(qapp, owner_widget) -> None:
    dispatcher = UiThreadDispatcher(owner_widget)
    main_thread = qapp.thread()
    done = threading.Event()
    observed: dict[str, object] = {}

    def callback(value: str) -> None:
        observed["value"] = value
        observed["thread"] = QThread.currentThread()
        done.set()

    worker = threading.Thread(target=lambda: dispatcher.submit(callback, "ok"))
    worker.start()
    worker.join()

    _process_until(qapp, done.is_set)

    assert observed["value"] == "ok"
    assert observed["thread"] is main_thread
