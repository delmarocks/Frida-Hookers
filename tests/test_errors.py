from __future__ import annotations

from core.errors import (
    AppNotRunningError,
    AttachStageError,
    HookersError,
    NoAppsFoundError,
    RpcTargetMissingError,
    WorkspaceAppNotSelectedError,
    WorkspaceResourceMissingError,
    build_error_message,
    to_ui_error_payload,
)
from ui import ui_messages


def test_build_error_message_includes_hint_when_present() -> None:
    exc = HookersError("失败", hint="请重试。")
    assert build_error_message(exc) == "失败\n\n建议：请重试。"


def test_to_ui_error_payload_preserves_hookers_error_metadata() -> None:
    exc = RpcTargetMissingError(ui_messages.MISSING_HOOK_TARGET_BODY)
    payload = to_ui_error_payload(exc)
    assert payload.title == ui_messages.MISSING_TARGET_TITLE
    assert payload.message == ui_messages.MISSING_HOOK_TARGET_BODY
    assert payload.category == "rpc"
    assert payload.severity == "warning"
    assert payload.focus_target == "hook_target_input"


def test_to_ui_error_payload_falls_back_for_generic_exception() -> None:
    payload = to_ui_error_payload(RuntimeError("boom"))
    assert payload.title == ui_messages.ERROR_DIALOG_TITLE
    assert payload.message == "boom"
    assert payload.severity == "critical"
    assert payload.focus_target is None


def test_to_ui_error_payload_preserves_session_stage_error_metadata() -> None:
    exc = AttachStageError("attach 阶段失败", hint="请检查 App 状态。")
    payload = to_ui_error_payload(exc)
    assert payload.title == ui_messages.ERROR_DIALOG_TITLE
    assert payload.message == "attach 阶段失败"
    assert payload.hint == "请检查 App 状态。"
    assert payload.category == "hook"


def test_to_ui_error_payload_preserves_workspace_error_metadata() -> None:
    exc = WorkspaceResourceMissingError("缺少内置资源: android_ui.js", hint="请检查 js 资源是否完整。")
    payload = to_ui_error_payload(exc)
    assert payload.title == ui_messages.ERROR_DIALOG_TITLE
    assert payload.message == "缺少内置资源: android_ui.js"
    assert payload.hint == "请检查 js 资源是否完整。"
    assert payload.category == "workspace"


def test_to_ui_error_payload_preserves_next_step_metadata() -> None:
    exc = AppNotRunningError("目标 App 未运行")
    payload = to_ui_error_payload(exc)
    assert payload.next_step is not None
    assert "Spawn" in payload.next_step


def test_to_ui_error_payload_preserves_app_workflow_warning_metadata() -> None:
    exc = WorkspaceAppNotSelectedError(ui_messages.WORKSPACE_APP_NOT_SELECTED_BODY)
    payload = to_ui_error_payload(exc)
    assert payload.title == ui_messages.APP_NOT_SELECTED_TITLE
    assert payload.message == ui_messages.WORKSPACE_APP_NOT_SELECTED_BODY
    assert payload.category == "app_workflow"
    assert payload.severity == "warning"
    assert payload.focus_target == "app_combo"


def test_to_ui_error_payload_preserves_no_apps_found_warning_metadata() -> None:
    exc = NoAppsFoundError(ui_messages.NO_APPS_FOUND_BODY)
    payload = to_ui_error_payload(exc)
    assert payload.title == ui_messages.NO_APPS_FOUND_TITLE
    assert payload.message == ui_messages.NO_APPS_FOUND_BODY
    assert payload.category == "app_workflow"
    assert payload.severity == "warning"


def test_to_ui_error_payload_preserves_app_not_running_warning_metadata() -> None:
    exc = AppNotRunningError("目标 App 未运行", hint="请先启动 App。")
    payload = to_ui_error_payload(exc)
    assert payload.title == ui_messages.ERROR_DIALOG_TITLE
    assert payload.message == "目标 App 未运行"
    assert payload.hint == "请先启动 App。"
    assert payload.category == "hook"
    assert payload.severity == "warning"
