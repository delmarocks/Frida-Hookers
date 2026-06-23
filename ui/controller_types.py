from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol, TypedDict

class AppInfoLike(Protocol):
    name: str
    identifier: str
    pid: int | None
    uid: int | None
    version: str | None


class ActiveSessionLike(Protocol):
    mode: str


class ContextLike(Protocol):
    project_root: Path
    js_dir: Path
    hookers_js_dir: Path
    frida_server_arm64: str
    local_apk_check_pack_exe: Path
    apps: list[AppInfoLike]
    current_app: AppInfoLike | None
    active_session: ActiveSessionLike | None
    log_handler: Callable[[str], None] | None
    session_event_handler: Callable[[str, object], None] | None

    def emit(self, message: str) -> None: ...


class DeviceServiceLike(Protocol):
    def ensure_app_running(self, package_name: str) -> AppInfoLike: ...
    def refresh_applications(self) -> list[AppInfoLike]: ...
    def stop_frida_server(self) -> None: ...


class SessionServiceLike(Protocol):
    def stop_active_session(self) -> None: ...
    def restart_current_app(self) -> None: ...
    def attach_script(self, script_name_or_path: str, use_v8: bool = False) -> object: ...
    def spawn_script(self, script_name_or_path: str, use_v8: bool = False) -> object: ...


class WorkspaceServiceLike(Protocol):
    def workspace_dir(self, package_name: str) -> Path: ...
    def script_dir(self, package_name: str) -> Path: ...
    def list_scripts(self, package_name: str) -> list[Path]: ...
    def script_names(self, package_name: str) -> list[str]: ...
    def available_script_names(self, package_name: str) -> list[str]: ...
    def materialize_multi_script_bundle(
        self,
        package_name: str,
        script_paths: list[str | Path],
        *,
        output_name: str = ...,
    ) -> Path: ...


class RpcServiceLike(Protocol):
    def invalidate_persistent_session(self) -> None: ...
    def generate_hook_script(self, hook_target: str) -> Path: ...
    def activitys(self) -> object: ...
    def services(self) -> object: ...
    def object_info(self, target: str) -> object: ...
    def object_to_explain(self, target: str) -> object: ...
    def view_info(self, target: str) -> object: ...


class ApkScanServiceLike(Protocol):
    def scan_apk(self, apk_path: Path) -> dict[str, object]: ...


class GuiDepsLike(Protocol):
    device_service: DeviceServiceLike
    session_service: SessionServiceLike
    workspace_service: WorkspaceServiceLike
    rpc_service: RpcServiceLike
    apk_scan_service: ApkScanServiceLike
    context: ContextLike


BusySetter = Callable[[bool, str | None], None]
StatusSetter = Callable[[str, str | None], None]
LogAppender = Callable[[str], None]
FocusTargetSetter = Callable[[str], None]
ScriptRootApplier = Callable[[Path], None]
SelectedScriptProvider = Callable[[], Path | None]
SelectedPackageProvider = Callable[[], str | None]
EnsureCurrentAppReady = Callable[[], str]
RefreshAppStatus = Callable[[str | None], None]
ShortenPath = Callable[[Path], str]
WorkerAction = Callable[[], object]
WorkerSuccessHandler = Callable[[object], None]
AppsPayloadApplier = Callable[[list["AppListItem"], str | None], None]


@dataclass(slots=True)
class UiErrorPayload:
    title: str
    message: str
    hint: str | None
    next_step: str | None
    category: str
    log_level: str
    user_visible: bool
    severity: str
    focus_target: str | None = None


def ensure_ui_error_payload(value: UiErrorPayload | str) -> UiErrorPayload:
    if isinstance(value, UiErrorPayload):
        return value
    return UiErrorPayload(
        title="执行失败",
        message=str(value),
        hint=None,
        next_step=None,
        category="general",
        log_level="error",
        user_visible=True,
        severity="critical",
        focus_target=None,
    )


ErrorPresenter = Callable[[UiErrorPayload | str], None]


class AppListItem(TypedDict):
    name: str
    identifier: str
    pid: int | None


class DetachedSessionPayload(TypedDict, total=False):
    package_name: str
    mode: str
    reason: str
    old_pid: int | None
    new_pid: int | None


@dataclass(slots=True)
class AppsReadyPayload:
    apps: list[AppListItem]
    foreground_package: str | None = None


@dataclass(slots=True)
class RestartAppPayload:
    package_name: str
    apps: list[AppListItem]


@dataclass(slots=True)
class GeneratedHookScriptPayload:
    package_name: str
    script_path: Path


@dataclass(slots=True)
class RpcResultPayload:
    package_name: str
    result: object
    target: str | None = None


@dataclass(slots=True)
class ApkScanResultPayload:
    apk_path: Path
    stdout: str
    stderr: str
    returncode: int
