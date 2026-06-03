from __future__ import annotations

from core.errors import HookersError, NoAppsFoundError, RpcTargetMissingError, WorkspaceResourceMissingError, to_ui_error_payload
from PySide6.QtWidgets import QMessageBox

from ui import ui_messages
from ui.controller_types import ensure_ui_error_payload
from ui.error_presenter import ErrorPresentationContext, ErrorPresenterController, build_error_display_plan


def build_presenter(owner_widget):
    busy_calls: list[tuple[bool, str | None]] = []
    status_calls: list[tuple[str, str | None]] = []
    log_lines: list[str] = []
    presenter = ErrorPresenterController(
        ErrorPresentationContext(
            owner=owner_widget,
            busy_setter=lambda busy, message: busy_calls.append((busy, message)),
            status_setter=lambda message, status: status_calls.append((message, status)),
            append_log=log_lines.append,
        )
    )
    return presenter, busy_calls, status_calls, log_lines


def test_build_error_display_plan_for_warning_keeps_busy_message_empty() -> None:
    payload = ensure_ui_error_payload(
        to_ui_error_payload(RpcTargetMissingError(ui_messages.MISSING_HOOK_TARGET_BODY))
    )
    plan = build_error_display_plan(payload)
    assert plan.busy_message is None
    assert plan.state_text == ui_messages.MISSING_HOOK_TARGET_BODY
    assert plan.status_bar_text == ui_messages.MISSING_HOOK_TARGET_BODY
    assert plan.dialog_kind == "warning"
    assert plan.log_lines == [f"{ui_messages.ERROR_LOG_PREFIX} {ui_messages.MISSING_HOOK_TARGET_BODY}"]


def test_build_error_display_plan_for_critical_uses_error_occurred_and_hint_log() -> None:
    payload = to_ui_error_payload(
        HookersError("设备失败", hint="请检查连接。", category="device", severity="critical")
    )
    plan = build_error_display_plan(payload)
    assert plan.busy_message == ui_messages.ERROR_OCCURRED
    assert plan.state_text == "设备失败"
    assert plan.status_bar_text == "设备失败"
    assert plan.dialog_kind == "critical"
    assert plan.log_lines == [
        f"{ui_messages.ERROR_LOG_PREFIX} 设备失败",
        f"{ui_messages.ERROR_HINT_PREFIX}请检查连接。",
    ]


def test_error_presenter_warning_app_workflow_uses_warning_dialog(owner_widget, monkeypatch) -> None:
    presenter, busy_calls, status_calls, log_lines = build_presenter(owner_widget)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))

    presenter.present(to_ui_error_payload(NoAppsFoundError(ui_messages.NO_APPS_FOUND_BODY)))

    assert busy_calls == [(False, None)]
    assert status_calls[-1] == (ui_messages.NO_APPS_FOUND_BODY, ui_messages.NO_APPS_FOUND_BODY)
    assert log_lines == [f"{ui_messages.ERROR_LOG_PREFIX} {ui_messages.NO_APPS_FOUND_BODY}"]
    assert warnings
    assert warnings[-1][1] == ui_messages.NO_APPS_FOUND_TITLE


def test_error_presenter_warning_rpc_behaves_like_regular_warning(owner_widget, monkeypatch) -> None:
    presenter, busy_calls, status_calls, log_lines = build_presenter(owner_widget)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))

    presenter.present(to_ui_error_payload(RpcTargetMissingError(ui_messages.MISSING_HOOK_TARGET_BODY)))

    assert busy_calls == [(False, None)]
    assert status_calls[-1] == (ui_messages.MISSING_HOOK_TARGET_BODY, ui_messages.MISSING_HOOK_TARGET_BODY)
    assert log_lines == [f"{ui_messages.ERROR_LOG_PREFIX} {ui_messages.MISSING_HOOK_TARGET_BODY}"]
    assert warnings
    assert warnings[-1][1] == ui_messages.MISSING_TARGET_TITLE


def test_error_presenter_critical_workspace_logs_hint_and_shows_critical(owner_widget, monkeypatch) -> None:
    presenter, busy_calls, status_calls, log_lines = build_presenter(owner_widget)
    criticals = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: criticals.append(args))

    presenter.present(
        to_ui_error_payload(
            WorkspaceResourceMissingError("缺少内置资源: android_ui.js", hint="请检查 js 资源是否完整。")
        )
    )

    assert busy_calls == [(False, ui_messages.ERROR_OCCURRED)]
    assert status_calls[-1] == ("缺少内置资源: android_ui.js", "缺少内置资源: android_ui.js")
    assert log_lines == [
        f"{ui_messages.ERROR_LOG_PREFIX} 缺少内置资源: android_ui.js",
        f"{ui_messages.ERROR_HINT_PREFIX}请检查 js 资源是否完整。",
    ]
    assert criticals
    assert criticals[-1][1] == ui_messages.ERROR_DIALOG_TITLE


def test_error_presenter_accepts_plain_string_as_critical(owner_widget, monkeypatch) -> None:
    presenter, busy_calls, status_calls, log_lines = build_presenter(owner_widget)
    criticals = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: criticals.append(args))

    presenter.present("plain failure")

    assert busy_calls == [(False, ui_messages.ERROR_OCCURRED)]
    assert status_calls[-1] == ("plain failure", "plain failure")
    assert log_lines == [f"{ui_messages.ERROR_LOG_PREFIX} plain failure"]
    assert criticals
    assert criticals[-1][1] == ui_messages.ERROR_DIALOG_TITLE
