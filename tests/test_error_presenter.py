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
    focus_calls: list[str] = []
    recovery_calls: list[tuple[str | None, str | None]] = []
    presenter = ErrorPresenterController(
        ErrorPresentationContext(
            owner=owner_widget,
            busy_setter=lambda busy, message: busy_calls.append((busy, message)),
            status_setter=lambda message, status: status_calls.append((message, status)),
            append_log=log_lines.append,
            focus_target=focus_calls.append,
            update_recovery_banner=lambda focus_target, next_step: recovery_calls.append((focus_target, next_step)),
        )
    )
    return presenter, busy_calls, status_calls, log_lines, focus_calls, recovery_calls


def test_build_error_display_plan_for_warning_keeps_busy_message_empty() -> None:
    payload = ensure_ui_error_payload(
        to_ui_error_payload(RpcTargetMissingError(ui_messages.MISSING_HOOK_TARGET_BODY))
    )
    plan = build_error_display_plan(payload)
    assert plan.busy_message is None
    assert plan.state_text == ui_messages.MISSING_HOOK_TARGET_BODY
    assert plan.status_bar_text == ui_messages.MISSING_HOOK_TARGET_BODY
    assert plan.dialog_kind == "warning"
    assert plan.log_lines == [
        f"{ui_messages.ERROR_LOG_PREFIX} {ui_messages.MISSING_HOOK_TARGET_BODY}",
        f"{ui_messages.ERROR_NEXT_STEP_PREFIX}{ui_messages.MISSING_HOOK_TARGET_NEXT_STEP}",
    ]


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
    presenter, busy_calls, status_calls, log_lines, _, recovery_calls = build_presenter(owner_widget)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))

    presenter.present(to_ui_error_payload(NoAppsFoundError(ui_messages.NO_APPS_FOUND_BODY)))

    assert busy_calls == [(False, None)]
    assert status_calls[-1] == (ui_messages.NO_APPS_FOUND_BODY, ui_messages.NO_APPS_FOUND_BODY)
    assert log_lines == [
        f"{ui_messages.ERROR_LOG_PREFIX} {ui_messages.NO_APPS_FOUND_BODY}",
        f"{ui_messages.ERROR_NEXT_STEP_PREFIX}{ui_messages.NO_APPS_FOUND_NEXT_STEP}",
    ]
    assert warnings
    assert warnings[-1][1] == ui_messages.NO_APPS_FOUND_TITLE


def test_error_presenter_warning_rpc_behaves_like_regular_warning(owner_widget, monkeypatch) -> None:
    presenter, busy_calls, status_calls, log_lines, _, recovery_calls = build_presenter(owner_widget)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))

    presenter.present(to_ui_error_payload(RpcTargetMissingError(ui_messages.MISSING_HOOK_TARGET_BODY)))

    assert busy_calls == [(False, None)]
    assert status_calls[-1] == (ui_messages.MISSING_HOOK_TARGET_BODY, ui_messages.MISSING_HOOK_TARGET_BODY)
    assert log_lines == [
        f"{ui_messages.ERROR_LOG_PREFIX} {ui_messages.MISSING_HOOK_TARGET_BODY}",
        f"{ui_messages.ERROR_NEXT_STEP_PREFIX}{ui_messages.MISSING_HOOK_TARGET_NEXT_STEP}",
    ]
    assert warnings
    assert warnings[-1][1] == ui_messages.MISSING_TARGET_TITLE


def test_error_presenter_critical_workspace_logs_hint_and_shows_critical(owner_widget, monkeypatch) -> None:
    presenter, busy_calls, status_calls, log_lines, _, recovery_calls = build_presenter(owner_widget)
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


def test_build_error_display_plan_includes_next_step_log() -> None:
    payload = to_ui_error_payload(
        HookersError("设备失败", hint="请检查连接。", next_step="点击“准备环境并刷新 App”后重试。", category="device", severity="critical")
    )
    plan = build_error_display_plan(payload)
    assert plan.log_lines[-1] == f"{ui_messages.ERROR_NEXT_STEP_PREFIX}点击“准备环境并刷新 App”后重试。"


def test_error_presenter_accepts_plain_string_as_critical(owner_widget, monkeypatch) -> None:
    presenter, busy_calls, status_calls, log_lines, _, recovery_calls = build_presenter(owner_widget)
    criticals = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: criticals.append(args))

    presenter.present("plain failure")

    assert busy_calls == [(False, ui_messages.ERROR_OCCURRED)]
    assert status_calls[-1] == ("plain failure", "plain failure")
    assert log_lines == [f"{ui_messages.ERROR_LOG_PREFIX} plain failure"]
    assert criticals
    assert criticals[-1][1] == ui_messages.ERROR_DIALOG_TITLE


def test_error_presenter_focuses_target_after_present(owner_widget, monkeypatch) -> None:
    presenter, _, _, _, focus_calls, recovery_calls = build_presenter(owner_widget)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))

    presenter.present(
        ensure_ui_error_payload(
            to_ui_error_payload(RpcTargetMissingError(ui_messages.INSPECT_TARGET_BODY))
        )
    )

    assert warnings
    assert focus_calls == ["inspect_target_input"]


def test_error_presenter_skips_focus_when_target_missing(owner_widget, monkeypatch) -> None:
    presenter, _, _, _, focus_calls, recovery_calls = build_presenter(owner_widget)
    criticals = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: criticals.append(args))

    presenter.present("plain failure")

    assert criticals
    assert focus_calls == []


def test_error_presenter_focus_failure_is_silently_ignored(owner_widget, monkeypatch) -> None:
    busy_calls: list[tuple[bool, str | None]] = []
    status_calls: list[tuple[str, str | None]] = []
    log_lines: list[str] = []
    presenter = ErrorPresenterController(
        ErrorPresentationContext(
            owner=owner_widget,
            busy_setter=lambda busy, message: busy_calls.append((busy, message)),
            status_setter=lambda message, status: status_calls.append((message, status)),
            append_log=log_lines.append,
            focus_target=lambda target: (_ for _ in ()).throw(RuntimeError("focus boom")),
        )
    )
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))

    presenter.present(to_ui_error_payload(RpcTargetMissingError(ui_messages.MISSING_HOOK_TARGET_BODY)))

    assert warnings
    assert status_calls[-1] == (ui_messages.MISSING_HOOK_TARGET_BODY, ui_messages.MISSING_HOOK_TARGET_BODY)


def test_error_presenter_updates_recovery_banner_with_focus_target(owner_widget, monkeypatch) -> None:
    presenter, _, _, _, _, recovery_calls = build_presenter(owner_widget)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))

    presenter.present(to_ui_error_payload(RpcTargetMissingError(ui_messages.MISSING_HOOK_TARGET_BODY)))

    assert warnings
    assert recovery_calls[-1] == ("hook_target_input", ui_messages.MISSING_HOOK_TARGET_NEXT_STEP)


def test_error_presenter_updates_recovery_banner_for_plain_error(owner_widget, monkeypatch) -> None:
    presenter, _, _, _, _, recovery_calls = build_presenter(owner_widget)
    criticals = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: criticals.append(args))

    presenter.present("plain failure")

    assert criticals
    assert recovery_calls[-1] == (None, None)


def test_error_presenter_next_step_messages_follow_recovery_style() -> None:
    app_payload = to_ui_error_payload(NoAppsFoundError(ui_messages.NO_APPS_FOUND_BODY))
    hook_payload = ensure_ui_error_payload(to_ui_error_payload(RpcTargetMissingError(ui_messages.MISSING_HOOK_TARGET_BODY)))

    assert app_payload.next_step == ui_messages.NO_APPS_FOUND_NEXT_STEP
    assert hook_payload.next_step == ui_messages.MISSING_HOOK_TARGET_NEXT_STEP
    assert app_payload.next_step.startswith(ui_messages.NO_APPS_FOUND_NEXT_STEP[:2])
    assert hook_payload.next_step == ui_messages.MISSING_HOOK_TARGET_NEXT_STEP


def test_error_presenter_recovery_banner_prefers_structured_next_step(owner_widget, monkeypatch) -> None:
    presenter, _, _, _, _, recovery_calls = build_presenter(owner_widget)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))

    presenter.present(to_ui_error_payload(NoAppsFoundError(ui_messages.NO_APPS_FOUND_BODY)))

    assert warnings
    assert recovery_calls[-1] == (None, ui_messages.NO_APPS_FOUND_NEXT_STEP)
