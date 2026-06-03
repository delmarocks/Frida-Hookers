from __future__ import annotations

from dataclasses import dataclass

from ui.controller_types import UiErrorPayload
from ui import ui_messages


@dataclass(slots=True)
class HookersError(Exception):
    message: str
    hint: str | None = None
    category: str = "general"
    dialog_title: str | None = None
    log_level: str = "error"
    user_visible: bool = True
    severity: str = "critical"

    def __post_init__(self) -> None:
        if self.severity not in {"warning", "critical"}:
            raise ValueError(f"Unsupported severity: {self.severity}")
        Exception.__init__(self, self.message)

    def __str__(self) -> str:
        return self.message


class DeviceError(HookersError):
    def __init__(self, message: str, **kwargs) -> None:
        super().__init__(message, category="device", **kwargs)


class RootRequiredError(DeviceError):
    pass


class FridaServerStartError(DeviceError):
    pass


class FridaServerStopError(DeviceError):
    pass


class AppNotSelectedError(HookersError):
    def __init__(self, message: str, **kwargs) -> None:
        super().__init__(
            message,
            category="hook",
            severity="warning",
            dialog_title=ui_messages.APP_NOT_SELECTED_TITLE,
            **kwargs,
        )


class AppNotRunningError(HookersError):
    def __init__(self, message: str, **kwargs) -> None:
        super().__init__(
            message,
            category="hook",
            severity="warning",
            **kwargs,
        )


class ScriptSelectionError(HookersError):
    def __init__(self, message: str, **kwargs) -> None:
        super().__init__(
            message,
            category="hook",
            severity="warning",
            dialog_title=ui_messages.SCRIPT_NOT_SELECTED_TITLE,
            **kwargs,
        )


class HookStartError(HookersError):
    def __init__(self, message: str, **kwargs) -> None:
        super().__init__(message, category="hook", **kwargs)


class SessionError(HookersError):
    def __init__(self, message: str, **kwargs) -> None:
        super().__init__(message, category="session", **kwargs)


class FridaDeviceNotReadyError(SessionError):
    pass


class CurrentAppMissingError(SessionError):
    def __init__(self, message: str, **kwargs) -> None:
        super().__init__(
            message,
            severity="warning",
            dialog_title=ui_messages.APP_NOT_SELECTED_TITLE,
            **kwargs,
        )


class CurrentPidMissingError(SessionError):
    pass


class ScriptFileMissingError(SessionError):
    pass


class AppWorkflowError(HookersError):
    def __init__(self, message: str, **kwargs) -> None:
        super().__init__(message, category="app_workflow", **kwargs)


class WorkspaceAppNotSelectedError(AppWorkflowError):
    def __init__(self, message: str, **kwargs) -> None:
        super().__init__(
            message,
            severity="warning",
            dialog_title=ui_messages.APP_NOT_SELECTED_TITLE,
            **kwargs,
        )


class NoAppsFoundError(AppWorkflowError):
    def __init__(self, message: str, **kwargs) -> None:
        super().__init__(
            message,
            severity="warning",
            dialog_title=ui_messages.NO_APPS_FOUND_TITLE,
            **kwargs,
        )


class AppPreparationError(AppWorkflowError):
    pass


class HookStopError(HookersError):
    def __init__(self, message: str, **kwargs) -> None:
        super().__init__(message, category="hook", **kwargs)


class AttachStageError(HookStartError):
    pass


class SpawnStageError(HookStartError):
    pass


class ScriptLoadStageError(HookStartError):
    pass


class ResumeStageError(HookStartError):
    pass


class RestartAppError(SessionError):
    pass


class WorkspaceError(HookersError):
    def __init__(self, message: str, **kwargs) -> None:
        super().__init__(message, category="workspace", **kwargs)


class WorkspaceResourceMissingError(WorkspaceError):
    pass


class WorkspaceScriptMissingError(WorkspaceError):
    pass


class WorkspaceFileReadError(WorkspaceError):
    pass


class WorkspaceFileWriteError(WorkspaceError):
    pass


class WorkspaceApkPullError(WorkspaceError):
    pass


class WorkspaceInitializationError(WorkspaceError):
    pass


class RpcToolError(HookersError):
    def __init__(self, message: str, **kwargs) -> None:
        super().__init__(message, category="rpc", **kwargs)


class RpcTargetMissingError(RpcToolError):
    def __init__(self, message: str, **kwargs) -> None:
        super().__init__(
            message,
            severity="warning",
            dialog_title=ui_messages.MISSING_TARGET_TITLE,
            **kwargs,
        )


class RpcCallError(RpcToolError):
    pass


class ApkScanError(HookersError):
    def __init__(self, message: str, **kwargs) -> None:
        super().__init__(message, category="apk_scan", **kwargs)


class ApkNotSelectedError(ApkScanError):
    def __init__(self, message: str, **kwargs) -> None:
        super().__init__(
            message,
            severity="warning",
            dialog_title=ui_messages.APK_SCAN_TITLE,
            **kwargs,
        )


class ApkScanExecutionError(ApkScanError):
    pass


def build_error_message(exc: HookersError) -> str:
    if exc.hint:
        return f"{exc.message}\n\n建议：{exc.hint}"
    return exc.message


def to_ui_error_payload(exc: Exception) -> UiErrorPayload:
    if isinstance(exc, HookersError):
        return UiErrorPayload(
            title=exc.dialog_title or ui_messages.ERROR_DIALOG_TITLE,
            message=exc.message,
            hint=exc.hint,
            category=exc.category,
            log_level=exc.log_level,
            user_visible=exc.user_visible,
            severity=exc.severity,
        )
    return UiErrorPayload(
        title=ui_messages.ERROR_DIALOG_TITLE,
        message=str(exc),
        hint=None,
        category="general",
        log_level="error",
        user_visible=True,
        severity="critical",
    )
