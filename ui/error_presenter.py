from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import QMessageBox, QWidget

from core.errors import HookersError, build_error_message

from . import ui_messages
from .controller_types import BusySetter, LogAppender, StatusSetter, UiErrorPayload, ensure_ui_error_payload


@dataclass(slots=True)
class UiErrorDisplayPlan:
    busy_message: str | None
    state_text: str
    status_bar_text: str
    log_lines: list[str]
    show_dialog: bool
    dialog_kind: str | None


def build_error_display_plan(payload: UiErrorPayload) -> UiErrorDisplayPlan:
    log_lines = [f"{ui_messages.ERROR_LOG_PREFIX} {payload.message}"]
    if payload.hint:
        log_lines.append(f"{ui_messages.ERROR_HINT_PREFIX}{payload.hint}")

    if payload.severity == "warning":
        return UiErrorDisplayPlan(
            busy_message=None,
            state_text=payload.message,
            status_bar_text=payload.message,
            log_lines=log_lines,
            show_dialog=payload.user_visible,
            dialog_kind="warning" if payload.user_visible else None,
        )

    return UiErrorDisplayPlan(
        busy_message=ui_messages.ERROR_OCCURRED,
        state_text=payload.message,
        status_bar_text=payload.message,
        log_lines=log_lines,
        show_dialog=payload.user_visible,
        dialog_kind="critical" if payload.user_visible else None,
    )


@dataclass(slots=True)
class ErrorPresentationContext:
    owner: QWidget
    status_setter: StatusSetter
    busy_setter: BusySetter
    append_log: LogAppender


class ErrorPresenterController:
    def __init__(self, context: ErrorPresentationContext) -> None:
        self.context = context

    def present(self, error: UiErrorPayload | str) -> None:
        payload = ensure_ui_error_payload(error)
        display = build_error_display_plan(payload)

        self.context.busy_setter(False, display.busy_message)
        for line in display.log_lines:
            self.context.append_log(line)
        self.context.status_setter(display.state_text, display.status_bar_text)

        if not display.show_dialog:
            return

        dialog_body = build_error_message(
            HookersError(
                payload.message,
                hint=payload.hint,
                category=payload.category,
                dialog_title=payload.title,
                log_level=payload.log_level,
                user_visible=payload.user_visible,
                severity=payload.severity,
            )
        )
        if display.dialog_kind == "warning":
            QMessageBox.warning(self.context.owner, payload.title, dialog_body)
        elif display.dialog_kind == "critical":
            QMessageBox.critical(self.context.owner, payload.title, dialog_body)
