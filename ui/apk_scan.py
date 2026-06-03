from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QFileDialog, QLabel, QLineEdit, QPushButton, QWidget

from core.errors import ApkNotSelectedError, ApkScanExecutionError, to_ui_error_payload

from .controller_types import (
    ApkScanResultPayload,
    BusySetter,
    ErrorPresenter,
    GuiDepsLike,
    LogAppender,
    ShortenPath,
    StatusSetter,
    WorkerAction,
    WorkerSuccessHandler,
)
from .workers.action_worker import ActionWorker
from .ui_thread_dispatcher import UiThreadDispatcher
from . import ui_messages


@dataclass
class ApkScanWidgets:
    apk_scan_path_input: QLineEdit
    apk_scan_status_label: QLabel
    select_apk_scan_button: QPushButton
    start_apk_scan_button: QPushButton


class ApkScanController:
    def __init__(
        self,
        owner: QWidget,
        widgets: ApkScanWidgets,
        deps: GuiDepsLike,
        *,
        set_busy: BusySetter,
        set_status_text: StatusSetter,
        append_log: LogAppender,
        show_worker_error: ErrorPresenter,
        shorten_path: ShortenPath,
    ) -> None:
        self.owner = owner
        self.widgets = widgets
        self.deps = deps
        self.set_busy = set_busy
        self.set_status_text = set_status_text
        self.append_log = append_log
        self.show_worker_error = show_worker_error
        self.shorten_path = shorten_path

        self.selected_apk_scan_path: Path | None = None
        self.apk_scan_thread: QThread | None = None
        self.apk_scan_worker: ActionWorker | None = None
        self.ui_dispatcher = UiThreadDispatcher(owner)

    def update_apk_scan_display(self) -> None:
        if self.selected_apk_scan_path is None:
            self.widgets.apk_scan_path_input.clear()
            self.widgets.apk_scan_path_input.setToolTip("")
            self.widgets.apk_scan_status_label.setText(ui_messages.APK_SCAN_EMPTY_STATUS)
            self.widgets.start_apk_scan_button.setDisabled(True)
            return

        self.widgets.apk_scan_path_input.setText(
            self.shorten_path(self.selected_apk_scan_path)
        )
        self.widgets.apk_scan_path_input.setToolTip(str(self.selected_apk_scan_path))
        self.widgets.apk_scan_status_label.setText(
            ui_messages.APK_SCAN_TARGET_STATUS.format(
                name=self.selected_apk_scan_path.name
            )
        )
        self.widgets.start_apk_scan_button.setDisabled(False)

    def sync_button_state(self, busy: bool) -> None:
        self.widgets.select_apk_scan_button.setDisabled(busy)
        self.widgets.start_apk_scan_button.setDisabled(
            busy or self.selected_apk_scan_path is None
        )

    def choose_apk_for_scan(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self.owner,
            "选择 APK 文件",
            str(self.deps.context.project_root),
            "APK Files (*.apk);;All Files (*.*)",
        )
        if not selected:
            return

        selected_path = Path(selected)
        self.selected_apk_scan_path = selected_path
        self.update_apk_scan_display()
        self.append_log(ui_messages.APK_SELECTED_LOG.format(path=selected_path))

    def start_scan_action(
        self,
        *,
        busy_message: str,
        action: WorkerAction,
        on_success: WorkerSuccessHandler,
    ) -> None:
        if self.apk_scan_thread is not None:
            return

        self.set_busy(True, busy_message)
        self.apk_scan_thread = QThread(self.owner)
        self.apk_scan_worker = ActionWorker(action)
        self.apk_scan_worker.moveToThread(self.apk_scan_thread)

        self.apk_scan_thread.started.connect(self.apk_scan_worker.run)
        self.apk_scan_worker.succeeded.connect(
            lambda payload: self.ui_dispatcher.submit(on_success, payload)
        )
        self.apk_scan_worker.failed.connect(
            lambda error: self.ui_dispatcher.submit(self.show_worker_error, error)
        )
        self.apk_scan_worker.finished.connect(self.apk_scan_thread.quit)
        self.apk_scan_worker.finished.connect(self.apk_scan_worker.deleteLater)
        self.apk_scan_thread.finished.connect(self.apk_scan_thread.deleteLater)
        self.apk_scan_thread.finished.connect(self._clear_apk_scan_thread)
        self.apk_scan_thread.start()

    def _clear_apk_scan_thread(self) -> None:
        self.apk_scan_thread = None
        self.apk_scan_worker = None

    def start_apk_scan(self) -> None:
        if self.selected_apk_scan_path is None:
            self.show_worker_error(
                to_ui_error_payload(ApkNotSelectedError(ui_messages.APK_SCAN_BODY))
            )
            return

        apk_path = self.selected_apk_scan_path

        def action() -> ApkScanResultPayload:
            self.deps.context.emit(ui_messages.APK_SCAN_START_LOG.format(path=apk_path))
            self.deps.context.emit(
                ui_messages.APK_SCAN_TOOL_LOG.format(
                    tool_path=self.deps.context.local_apk_check_pack_exe
                )
            )
            result = self.deps.apk_scan_service.scan_apk(apk_path)
            stdout = str(result.get("stdout") or "")
            stderr = str(result.get("stderr") or "")
            returncode = int(result.get("returncode") or 0)
            if stdout:
                self.deps.context.emit(ui_messages.APK_SCAN_OUTPUT_HEADER)
                for line in stdout.splitlines():
                    self.deps.context.emit(f"[TOOL] {line}")
            if stderr:
                self.deps.context.emit(ui_messages.APK_SCAN_ERROR_HEADER)
                for line in stderr.splitlines():
                    self.deps.context.emit(f"[TOOL] {line}")
            if returncode != 0:
                raise ApkScanExecutionError(
                    ui_messages.APK_SCAN_FAILED_BODY.format(returncode=returncode),
                    hint="请结合上面的扫描工具输出检查 APK 内容或扫描工具运行环境。",
                )
            return ApkScanResultPayload(
                apk_path=apk_path,
                stdout=stdout,
                stderr=stderr,
                returncode=returncode,
            )

        self.start_scan_action(
            busy_message=ui_messages.SCANNING_APK,
            action=action,
            on_success=self.on_apk_scan_succeeded,
        )

    def on_apk_scan_succeeded(self, payload: ApkScanResultPayload) -> None:
        self.append_log(
            ui_messages.APK_SCAN_FINISHED_LOG.format(apk_path=payload.apk_path)
        )
        self.set_status_text(ui_messages.APK_SCAN_COMPLETE, ui_messages.APK_SCAN_COMPLETE)
        self.set_busy(False, ui_messages.APK_SCAN_COMPLETE)
