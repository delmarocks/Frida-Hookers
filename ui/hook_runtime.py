from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast
from uuid import uuid4

from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
    QInputDialog,
)

from core.errors import (
    AppNotSelectedError,
    FridaServerStopError,
    HookStartError,
    HookersError,
    HookStopError,
    RestartAppError,
    ScriptSelectionError,
    to_ui_error_payload,
)
from core.workspace_service import BUILTIN_JS_FILES

from .controller_types import (
    AppsPayloadApplier,
    AppListItem,
    BusySetter,
    DetachedSessionPayload,
    EnsureCurrentAppReady,
    ErrorPresenter,
    GuiDepsLike,
    LogAppender,
    RefreshAppStatus,
    RestartAppPayload,
    SelectedPackageProvider,
    SelectedScriptProvider,
    StatusSetter,
    WorkerAction,
    WorkerSuccessHandler,
)
from .quick_hook_actions import QUICK_HOOK_ACTIONS_BY_KEY, QUICK_HOOK_BUTTON_ATTRS
from .workers.action_worker import ActionWorker
from .workers.hook_worker import HookWorker
from .ui_thread_dispatcher import UiThreadDispatcher
from .frida_multi_launcher_dialog import FridaMultiLauncherDialog, FridaScriptOption
from . import ui_messages


@dataclass
class HookRuntimeWidgets:
    start_hook_button: QPushButton
    stop_hook_button: QPushButton
    current_state_label: QLabel
    app_combo: QComboBox


@dataclass
class TraceInitProcParams:
    target_so: str
    start_addr: str
    end_addr: str


class TraceInitProcDialog(QDialog):
    def __init__(
        self,
        owner: QWidget | None,
        *,
        target_so: str,
        start_addr: str,
        end_addr: str,
    ) -> None:
        super().__init__(owner)
        self.setWindowTitle(ui_messages.TRACE_INIT_PROC_DIALOG_TITLE)

        layout = QFormLayout(self)
        self.target_so_input = QLineEdit(target_so, self)
        self.start_addr_input = QLineEdit(start_addr, self)
        self.end_addr_input = QLineEdit(end_addr, self)
        layout.addRow(ui_messages.TRACE_INIT_PROC_SO_LABEL, self.target_so_input)
        layout.addRow(ui_messages.TRACE_INIT_PROC_START_ADDR_LABEL, self.start_addr_input)
        layout.addRow(ui_messages.TRACE_INIT_PROC_END_ADDR_LABEL, self.end_addr_input)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def values(self) -> TraceInitProcParams:
        return TraceInitProcParams(
            target_so=self.target_so_input.text(),
            start_addr=self.start_addr_input.text(),
            end_addr=self.end_addr_input.text(),
        )


class HookRuntimeController:
    JNI_TARGET_SO_PLACEHOLDER = "__HOOKERS_TARGET_SO__"
    TRACE_INIT_SO_PLACEHOLDER = "__HOOKERS_TRACE_SO__"
    TRACE_INIT_START_PLACEHOLDER = "__HOOKERS_TRACE_START_ADDR__"
    TRACE_INIT_END_PLACEHOLDER = "__HOOKERS_TRACE_END_ADDR__"

    def __init__(
        self,
        owner: QWidget,
        widgets: HookRuntimeWidgets,
        deps: GuiDepsLike,
        *,
        set_busy: BusySetter,
        set_status_text: StatusSetter,
        append_log: LogAppender,
        show_worker_error: ErrorPresenter,
        selected_package_name: SelectedPackageProvider,
        selected_script_path: SelectedScriptProvider,
        ensure_current_app_ready: EnsureCurrentAppReady,
        refresh_app_status_panel: RefreshAppStatus,
        apply_apps_payload: AppsPayloadApplier,
    ) -> None:
        self.owner = owner
        self.widgets = widgets
        self.deps = deps
        self.set_busy = set_busy
        self.set_status_text = set_status_text
        self.append_log = append_log
        self.show_worker_error = show_worker_error
        self.selected_package_name = selected_package_name
        self.selected_script_path = selected_script_path
        self.ensure_current_app_ready = ensure_current_app_ready
        self.refresh_app_status_panel = refresh_app_status_panel
        self.apply_apps_payload = apply_apps_payload

        self.hook_thread: QThread | None = None
        self.hook_worker: HookWorker | None = None
        self.runtime_action_thread: QThread | None = None
        self.runtime_action_worker: ActionWorker | None = None
        self.ui_dispatcher = UiThreadDispatcher(owner)
        self._auto_stop_in_progress = False
        self._last_jni_target_so = ""
        self._last_trace_init_target_so = ""
        self._last_trace_init_start_addr = ""
        self._last_trace_init_end_addr = ""

    def _present_local_error(self, exc: HookersError) -> None:
        self.show_worker_error(to_ui_error_payload(exc))

    def _set_quick_hook_buttons_disabled(self, disabled: bool) -> None:
        for button_attr in QUICK_HOOK_BUTTON_ATTRS:
            if hasattr(self.owner, button_attr):
                getattr(self.owner, button_attr).setDisabled(disabled)

    def handle_session_event(self, event_type: str, payload: object) -> None:
        if event_type == "auto_stop_requested":
            self.handle_auto_stop_requested(payload)
            return
        if event_type != "detached":
            return
        payload_dict: DetachedSessionPayload = (
            cast(DetachedSessionPayload, payload) if isinstance(payload, dict) else {}
        )

        package_name = str(payload_dict.get("package_name") or self.selected_package_name() or "")
        mode = str(payload_dict.get("mode") or "attach")
        reason = str(payload_dict.get("reason") or "unknown")
        old_pid = payload_dict.get("old_pid")
        new_pid = payload_dict.get("new_pid")

        if new_pid is not None and old_pid is not None and new_pid != old_pid:
            self.set_status_text(
                ui_messages.SESSION_DETACHED_PID_CHANGED_STATE.format(
                    mode=mode,
                    old_pid=old_pid,
                    new_pid=new_pid,
                ),
                ui_messages.SESSION_DETACHED_PID_CHANGED_STATUS.format(
                    mode=mode,
                    new_pid=new_pid,
                ),
            )
        else:
            self.set_status_text(
                ui_messages.SESSION_DETACHED_STATE.format(mode=mode, reason=reason),
                ui_messages.SESSION_DETACHED_STATUS.format(mode=mode),
            )

        self.widgets.start_hook_button.setDisabled(False)
        self.widgets.stop_hook_button.setDisabled(True)
        self._set_quick_hook_buttons_disabled(False)
        self.refresh_app_status_panel(package_name or None)
        self._auto_stop_in_progress = False

    def handle_auto_stop_requested(self, payload: object) -> None:
        if self.runtime_action_thread is not None or self._auto_stop_in_progress:
            return
        if self.deps.context.active_session is None:
            return

        payload_dict = payload if isinstance(payload, dict) else {}
        message = str(payload_dict.get("message") or "").strip()
        if message:
            self.append_log(f"[TOOL] {message}")
        self._auto_stop_in_progress = True
        self.start_runtime_action(
            busy_message=ui_messages.STOPPING_HOOK,
            action=self.deps.session_service.stop_active_session,
            on_success=self.on_auto_stop_finished,
        )

    def start_hook(self, use_spawn: bool) -> None:
        if self.hook_thread is not None:
            return

        package_name = self.selected_package_name()
        if not package_name:
            self._present_local_error(AppNotSelectedError(ui_messages.APP_NOT_SELECTED_BODY))
            return

        script_path = self.selected_script_path()
        if script_path is None:
            self._present_local_error(ScriptSelectionError(ui_messages.SCRIPT_NOT_SELECTED_BODY))
            return

        self._start_hook_with_script_path(
            package_name=package_name,
            script_path=script_path,
            use_spawn=use_spawn,
            busy_message=ui_messages.STARTING_HOOK,
        )

    def start_detect_network_stack(self, use_spawn: bool) -> None:
        self.start_quick_hook("detect_network_stack", use_spawn)

    def start_print_okhttp_interceptors(self, use_spawn: bool) -> None:
        self.start_quick_hook("print_okhttp_interceptors", use_spawn)

    def start_okhttp_capture(self, use_spawn: bool) -> None:
        self.start_quick_hook("okhttp_capture", use_spawn)

    def start_hook_register_natives(self, use_spawn: bool) -> None:
        self.start_quick_hook("hook_register_natives", use_spawn)

    def start_find_anti_frida_so(self, use_spawn: bool) -> None:
        self.start_quick_hook("find_anti_frida_so", use_spawn)

    def start_click_trace(self, use_spawn: bool) -> None:
        self.start_quick_hook("click_trace", use_spawn)

    def start_edit_text_trace(self, use_spawn: bool) -> None:
        self.start_quick_hook("edit_text_trace", use_spawn)

    def start_text_view_trace(self, use_spawn: bool) -> None:
        self.start_quick_hook("text_view_trace", use_spawn)

    def start_url_trace(self, use_spawn: bool) -> None:
        self.start_quick_hook("url_trace", use_spawn)

    def start_activity_events_trace(self, use_spawn: bool) -> None:
        self.start_quick_hook("activity_events_trace", use_spawn)

    def start_jni_method_trace(self, use_spawn: bool) -> None:
        if self.hook_thread is not None:
            return

        package_name = self.selected_package_name()
        if not package_name:
            self._present_local_error(AppNotSelectedError(ui_messages.APP_NOT_SELECTED_BODY))
            return

        target_so = self.collect_jni_method_trace_params()
        if target_so is None:
            return
        try:
            script_path = self._materialize_jni_method_trace_script(
                package_name=package_name,
                target_so=target_so,
            )
        except HookersError as exc:
            self._present_local_error(exc)
            return

        mode = "spawn" if use_spawn else "attach"
        self.append_log(ui_messages.JNI_METHOD_TRACE_ACTION_LOG)
        self.append_log(
            ui_messages.JNI_METHOD_TRACE_SCRIPT_LOG.format(script_path=script_path)
        )
        self.append_log(
            ui_messages.JNI_METHOD_TRACE_TARGET_SO_LOG.format(target_so=target_so)
        )
        self.append_log(ui_messages.JNI_METHOD_TRACE_MODE_LOG.format(mode=mode))
        self._start_hook_with_script_path(
            package_name=package_name,
            script_path=script_path,
            use_spawn=use_spawn,
            busy_message=ui_messages.TRACING_JNI_METHODS,
        )

    def start_trace_init_proc(self, use_spawn: bool) -> None:
        if self.hook_thread is not None:
            return

        package_name = self.selected_package_name()
        if not package_name:
            self._present_local_error(AppNotSelectedError(ui_messages.APP_NOT_SELECTED_BODY))
            return

        params = self.collect_trace_init_proc_params()
        if params is None:
            return

        try:
            script_path = self._materialize_trace_init_proc_script(
                package_name=package_name,
                target_so=params.target_so,
                start_addr=params.start_addr,
                end_addr=params.end_addr,
            )
        except HookersError as exc:
            self._present_local_error(exc)
            return

        mode = "spawn" if use_spawn else "attach"
        self.append_log(ui_messages.TRACE_INIT_PROC_ACTION_LOG)
        self.append_log(
            ui_messages.TRACE_INIT_PROC_SCRIPT_LOG.format(script_path=script_path)
        )
        self.append_log(
            ui_messages.TRACE_INIT_PROC_PARAMS_LOG.format(
                target_so=params.target_so,
                start_addr=params.start_addr,
                end_addr=params.end_addr,
            )
        )
        self.append_log(ui_messages.TRACE_INIT_PROC_MODE_LOG.format(mode=mode))
        self._start_hook_with_script_path(
            package_name=package_name,
            script_path=script_path,
            use_spawn=use_spawn,
            busy_message=ui_messages.TRACING_INIT_PROC,
        )

    def start_advanced_frida_launcher(self, use_spawn: bool) -> None:
        if self.hook_thread is not None:
            return
        if self.deps.context.active_session is not None:
            self._present_local_error(
                HookStartError(
                    ui_messages.ADVANCED_FRIDA_ACTIVE_SESSION_BODY,
                    severity="warning",
                    dialog_title=ui_messages.ERROR_DIALOG_TITLE,
                )
            )
            return

        package_name = self.selected_package_name()
        if not package_name:
            self._present_local_error(AppNotSelectedError(ui_messages.APP_NOT_SELECTED_BODY))
            return

        mode = "spawn" if use_spawn else "attach"
        dialog = FridaMultiLauncherDialog(
            self.owner,
            package_name=package_name,
            mode=mode,
            options=self._available_frida_script_options(package_name),
            add_option_resolver=lambda option: self._resolve_advanced_frida_option(
                package_name,
                option,
            ),
            reconfigure_option_resolver=lambda option: self._reconfigure_advanced_frida_option(
                package_name,
                option,
            ),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        selected_options = dialog.selected_options()
        if not selected_options:
            self._present_local_error(
                HookStartError(
                    ui_messages.ADVANCED_FRIDA_NO_SCRIPT_BODY,
                    severity="warning",
                    dialog_title=ui_messages.SCRIPT_NOT_SELECTED_TITLE,
                )
            )
            return

        try:
            script_path = self.deps.workspace_service.materialize_multi_script_bundle(
                package_name,
                [option.path for option in selected_options],
            )
        except HookersError as exc:
            self._present_local_error(exc)
            return

        self.append_log(ui_messages.ADVANCED_FRIDA_ACTION_LOG)
        self.append_log(ui_messages.ADVANCED_FRIDA_BUNDLE_LOG.format(script_path=script_path))
        self.append_log(
            ui_messages.ADVANCED_FRIDA_ORDER_LOG.format(
                scripts=" -> ".join(option.label for option in selected_options)
            )
        )
        self._start_hook_with_script_path(
            package_name=package_name,
            script_path=script_path,
            use_spawn=use_spawn,
            busy_message=ui_messages.STARTING_ADVANCED_FRIDA,
        )

    def _materialize_jni_method_trace_script(self, *, package_name: str, target_so: str) -> Path:
        builtin_script_path = self.resolve_builtin_quick_script_path("jni_method_trace.js")
        try:
            template = builtin_script_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise HookStartError(
                "读取 JNI 跟踪脚本模板失败。",
                hint="请检查项目内置 jni_method_trace.js 脚本是否存在且可读。",
            ) from exc

        runtime_script = template.replace(self.JNI_TARGET_SO_PLACEHOLDER, target_so)
        script_dir = self.deps.workspace_service.script_dir(package_name)
        script_path = script_dir / "jni_method_trace.runtime.js"
        try:
            script_dir.mkdir(parents=True, exist_ok=True)
            script_path.write_text(runtime_script, encoding="utf-8", newline="")
        except OSError as exc:
            raise HookStartError(
                "写入 JNI 跟踪运行时脚本失败。",
                hint="请检查当前工作区脚本目录是否可写后重试。",
            ) from exc
        return script_path

    def collect_jni_method_trace_params(self, initial_target_so: str | None = None) -> str | None:
        target_so, accepted = QInputDialog.getText(
            self.owner,
            ui_messages.JNI_TARGET_SO_DIALOG_TITLE,
            ui_messages.JNI_TARGET_SO_DIALOG_LABEL,
            text=initial_target_so if initial_target_so is not None else self._last_jni_target_so,
        )
        if not accepted:
            return None

        normalized_target_so = target_so.strip()
        if not normalized_target_so:
            self._present_local_error(
                HookStartError(
                    ui_messages.JNI_TARGET_SO_REQUIRED_BODY,
                    severity="warning",
                    dialog_title=ui_messages.MISSING_TARGET_TITLE,
                )
            )
            return None
        if ".so" not in normalized_target_so:
            self._present_local_error(
                HookStartError(
                    ui_messages.JNI_TARGET_SO_INVALID_BODY,
                    severity="warning",
                    dialog_title=ui_messages.MISSING_TARGET_TITLE,
                )
            )
            return None

        self._last_jni_target_so = normalized_target_so
        return normalized_target_so

    def _materialize_trace_init_proc_script(
        self,
        *,
        package_name: str,
        target_so: str,
        start_addr: str,
        end_addr: str,
    ) -> Path:
        builtin_script_path = self.resolve_builtin_quick_script_path("trace_init_proc.js")
        try:
            template = builtin_script_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise HookStartError(
                "读取 init_proc 跟踪脚本模板失败。",
                hint="请检查项目内置 trace_init_proc.js 脚本是否存在且可读。",
            ) from exc

        runtime_script = (
            template.replace(self.TRACE_INIT_SO_PLACEHOLDER, target_so)
            .replace(self.TRACE_INIT_START_PLACEHOLDER, start_addr)
            .replace(self.TRACE_INIT_END_PLACEHOLDER, end_addr)
        )
        script_dir = self.deps.workspace_service.script_dir(package_name)
        script_path = script_dir / "trace_init_proc.runtime.js"
        try:
            script_dir.mkdir(parents=True, exist_ok=True)
            script_path.write_text(runtime_script, encoding="utf-8", newline="")
        except OSError as exc:
            raise HookStartError(
                "写入 init_proc 跟踪运行时脚本失败。",
                hint="请检查当前工作区脚本目录是否可写后重试。",
            ) from exc
        return script_path

    def _materialize_advanced_jni_method_trace_script(
        self,
        *,
        package_name: str,
        target_so: str,
        runtime_key: str,
    ) -> Path:
        builtin_script_path = self.resolve_builtin_quick_script_path("jni_method_trace.js")
        try:
            template = builtin_script_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise HookStartError(
                "读取 JNI 跟踪脚本模板失败。",
                hint="请检查项目内置 jni_method_trace.js 脚本是否存在且可读。",
            ) from exc

        runtime_script = template.replace(self.JNI_TARGET_SO_PLACEHOLDER, target_so)
        script_dir = self.deps.workspace_service.script_dir(package_name)
        script_path = script_dir / f"jni_method_trace.{runtime_key}.runtime.js"
        try:
            script_dir.mkdir(parents=True, exist_ok=True)
            script_path.write_text(runtime_script, encoding="utf-8", newline="")
        except OSError as exc:
            raise HookStartError(
                "写入 JNI 跟踪运行时脚本失败。",
                hint="请检查当前工作区脚本目录是否可写后重试。",
            ) from exc
        return script_path

    def _materialize_advanced_trace_init_proc_script(
        self,
        *,
        package_name: str,
        target_so: str,
        start_addr: str,
        end_addr: str,
        runtime_key: str,
    ) -> Path:
        builtin_script_path = self.resolve_builtin_quick_script_path("trace_init_proc.js")
        try:
            template = builtin_script_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise HookStartError(
                "读取 init_proc 跟踪脚本模板失败。",
                hint="请检查项目内置 trace_init_proc.js 脚本是否存在且可读。",
            ) from exc

        runtime_script = (
            template.replace(self.TRACE_INIT_SO_PLACEHOLDER, target_so)
            .replace(self.TRACE_INIT_START_PLACEHOLDER, start_addr)
            .replace(self.TRACE_INIT_END_PLACEHOLDER, end_addr)
        )
        script_dir = self.deps.workspace_service.script_dir(package_name)
        script_path = script_dir / f"trace_init_proc.{runtime_key}.runtime.js"
        try:
            script_dir.mkdir(parents=True, exist_ok=True)
            script_path.write_text(runtime_script, encoding="utf-8", newline="")
        except OSError as exc:
            raise HookStartError(
                "写入 init_proc 跟踪运行时脚本失败。",
                hint="请检查当前工作区脚本目录是否可写后重试。",
            ) from exc
        return script_path

    def collect_trace_init_proc_params(
        self,
        initial_params: TraceInitProcParams | None = None,
    ) -> TraceInitProcParams | None:
        dialog = TraceInitProcDialog(
            self.owner,
            target_so=(
                initial_params.target_so
                if initial_params is not None
                else self._last_trace_init_target_so
            ),
            start_addr=(
                initial_params.start_addr
                if initial_params is not None
                else self._last_trace_init_start_addr
            ),
            end_addr=(
                initial_params.end_addr
                if initial_params is not None
                else self._last_trace_init_end_addr
            ),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None

        params = dialog.values()
        normalized_target_so = params.target_so.strip()
        if not normalized_target_so:
            self._present_local_error(
                HookStartError(
                    ui_messages.TRACE_INIT_PROC_REQUIRED_SO_BODY,
                    severity="warning",
                    dialog_title=ui_messages.MISSING_TARGET_TITLE,
                )
            )
            return None
        if ".so" not in normalized_target_so:
            self._present_local_error(
                HookStartError(
                    ui_messages.TRACE_INIT_PROC_INVALID_SO_BODY,
                    severity="warning",
                    dialog_title=ui_messages.MISSING_TARGET_TITLE,
                )
            )
            return None

        raw_start_addr = params.start_addr.strip()
        if not raw_start_addr:
            self._present_local_error(
                HookStartError(
                    ui_messages.TRACE_INIT_PROC_REQUIRED_START_BODY,
                    severity="warning",
                    dialog_title=ui_messages.MISSING_TARGET_TITLE,
                )
            )
            return None
        raw_end_addr = params.end_addr.strip()
        if not raw_end_addr:
            self._present_local_error(
                HookStartError(
                    ui_messages.TRACE_INIT_PROC_REQUIRED_END_BODY,
                    severity="warning",
                    dialog_title=ui_messages.MISSING_TARGET_TITLE,
                )
            )
            return None

        try:
            normalized_start_addr = self._normalize_hex_address(raw_start_addr)
            normalized_end_addr = self._normalize_hex_address(raw_end_addr)
        except ValueError:
            self._present_local_error(
                HookStartError(
                    ui_messages.TRACE_INIT_PROC_INVALID_ADDR_BODY,
                    severity="warning",
                    dialog_title=ui_messages.MISSING_TARGET_TITLE,
                )
            )
            return None

        if int(normalized_end_addr, 16) < int(normalized_start_addr, 16):
            self._present_local_error(
                HookStartError(
                    ui_messages.TRACE_INIT_PROC_RANGE_BODY,
                    severity="warning",
                    dialog_title=ui_messages.MISSING_TARGET_TITLE,
                )
            )
            return None

        self._last_trace_init_target_so = normalized_target_so
        self._last_trace_init_start_addr = normalized_start_addr
        self._last_trace_init_end_addr = normalized_end_addr
        return TraceInitProcParams(
            target_so=normalized_target_so,
            start_addr=normalized_start_addr,
            end_addr=normalized_end_addr,
        )

    def _normalize_hex_address(self, value: str) -> str:
        raw = value.strip().lower()
        if raw.startswith("0x"):
            raw = raw[2:]
        if not raw:
            raise ValueError("empty")
        parsed = int(raw, 16)
        return f"0x{parsed:x}"

    def _available_frida_script_options(self, package_name: str) -> list[FridaScriptOption]:
        options: list[FridaScriptOption] = []
        workspace_scripts = sorted(
            self.deps.workspace_service.list_scripts(package_name),
            key=lambda path: path.name.lower(),
        )
        options.extend(
            FridaScriptOption(
                label=self._format_advanced_frida_option_label(
                    path.name,
                    ui_messages.ADVANCED_FRIDA_WORKSPACE_SOURCE,
                    self._advanced_frida_option_kind(path.name),
                ),
                path=path,
                kind=self._advanced_frida_option_kind(path.name),
            )
            for path in workspace_scripts
        )

        builtin_scripts = sorted(
            [
                self.deps.context.hookers_js_dir / script_name
                for script_name in BUILTIN_JS_FILES
                if (self.deps.context.hookers_js_dir / script_name).is_file()
            ],
            key=lambda path: path.name.lower(),
        )
        options.extend(
            FridaScriptOption(
                label=self._format_advanced_frida_option_label(
                    path.name,
                    ui_messages.ADVANCED_FRIDA_BUILTIN_SOURCE,
                    self._advanced_frida_option_kind(path.name),
                ),
                path=path,
                kind=self._advanced_frida_option_kind(path.name),
            )
            for path in builtin_scripts
        )
        return options

    def _advanced_frida_option_kind(self, script_name: str) -> str:
        if script_name == "jni_method_trace.js":
            return "jni_method_trace"
        if script_name == "trace_init_proc.js":
            return "trace_init_proc"
        return "plain"

    def _format_advanced_frida_option_label(
        self,
        script_name: str,
        source_label: str,
        kind: str,
    ) -> str:
        parts = []
        if kind != "plain":
            parts.append(ui_messages.ADVANCED_FRIDA_PARAM_PREFIX)
        parts.append(source_label)
        prefix = "] [".join(parts)
        return f"[{prefix}] {script_name}"

    def _resolve_advanced_frida_option(
        self,
        package_name: str,
        option: FridaScriptOption,
    ) -> FridaScriptOption | None:
        if option.kind == "plain":
            return option
        if option.kind == "jni_method_trace":
            target_so = self.collect_jni_method_trace_params()
            if target_so is None:
                return None
            return self._build_jni_method_trace_runtime_option(
                package_name=package_name,
                template_option=option,
                target_so=target_so,
            )
        if option.kind == "trace_init_proc":
            params = self.collect_trace_init_proc_params()
            if params is None:
                return None
            return self._build_trace_init_proc_runtime_option(
                package_name=package_name,
                template_option=option,
                params=params,
            )
        return option

    def _reconfigure_advanced_frida_option(
        self,
        package_name: str,
        option: FridaScriptOption,
    ) -> FridaScriptOption | None:
        if option.kind == "plain":
            return option
        if option.kind == "jni_method_trace":
            initial_target_so = (
                option.config_payload if isinstance(option.config_payload, str) else None
            )
            target_so = self.collect_jni_method_trace_params(initial_target_so)
            if target_so is None:
                return None
            return self._build_jni_method_trace_runtime_option(
                package_name=package_name,
                template_option=option,
                target_so=target_so,
            )
        if option.kind == "trace_init_proc":
            initial_params = (
                option.config_payload
                if isinstance(option.config_payload, TraceInitProcParams)
                else None
            )
            params = self.collect_trace_init_proc_params(initial_params)
            if params is None:
                return None
            return self._build_trace_init_proc_runtime_option(
                package_name=package_name,
                template_option=option,
                params=params,
            )
        return option

    def _build_jni_method_trace_runtime_option(
        self,
        *,
        package_name: str,
        template_option: FridaScriptOption,
        target_so: str,
    ) -> FridaScriptOption:
        runtime_key = template_option.runtime_key or uuid4().hex[:8]
        runtime_path = self._materialize_advanced_jni_method_trace_script(
            package_name=package_name,
            target_so=target_so,
            runtime_key=runtime_key,
        )
        return FridaScriptOption(
            label=f"[{ui_messages.ADVANCED_FRIDA_PARAM_PREFIX}] jni_method_trace.runtime.js",
            path=runtime_path,
            kind="jni_method_trace",
            template_path=template_option.template_path or template_option.path,
            config_payload=target_so,
            runtime_key=runtime_key,
        )

    def _build_trace_init_proc_runtime_option(
        self,
        *,
        package_name: str,
        template_option: FridaScriptOption,
        params: TraceInitProcParams,
    ) -> FridaScriptOption:
        runtime_key = template_option.runtime_key or uuid4().hex[:8]
        runtime_path = self._materialize_advanced_trace_init_proc_script(
            package_name=package_name,
            target_so=params.target_so,
            start_addr=params.start_addr,
            end_addr=params.end_addr,
            runtime_key=runtime_key,
        )
        return FridaScriptOption(
            label=f"[{ui_messages.ADVANCED_FRIDA_PARAM_PREFIX}] trace_init_proc.runtime.js",
            path=runtime_path,
            kind="trace_init_proc",
            template_path=template_option.template_path or template_option.path,
            config_payload=params,
            runtime_key=runtime_key,
        )

    def start_quick_hook(self, action_key: str, selected_use_spawn: bool) -> None:
        action = QUICK_HOOK_ACTIONS_BY_KEY[action_key]
        self._start_builtin_quick_hook(
            script_name=action.script_name,
            use_spawn=selected_use_spawn,
            busy_message=action.busy_message,
            action_log=action.action_log,
            script_log_template=action.script_log_template,
            mode_log_template=action.mode_log_template,
        )

    def start_script_command(self, script_name_or_path: str, use_spawn: bool) -> None:
        if self.hook_thread is not None:
            return

        package_name = self.selected_package_name()
        if not package_name:
            self._present_local_error(AppNotSelectedError(ui_messages.APP_NOT_SELECTED_BODY))
            return

        script_name_or_path = script_name_or_path.strip()
        if not script_name_or_path:
            self._present_local_error(
                ScriptSelectionError(ui_messages.SCRIPT_NOT_SELECTED_BODY)
            )
            return

        try:
            script_path = Path(script_name_or_path)
            if not script_path.is_file():
                script_path = self.resolve_quick_script_path(package_name, script_name_or_path)
        except HookersError as exc:
            self._present_local_error(exc)
            return

        if not script_path.is_file():
            self._present_local_error(
                HookStartError(
                    f"脚本不存在：{script_name_or_path}",
                    hint="请确认脚本位于当前工作区 js 目录、项目内置 hookers/js 目录，或直接输入可访问的脚本路径。",
                    severity="warning",
                )
            )
            return

        if use_spawn:
            self.append_log(
                ui_messages.TERMINAL_SPAWN_ACTION_LOG.format(script_name=script_name_or_path)
            )
        else:
            self.append_log(
                ui_messages.TERMINAL_ATTACH_ACTION_LOG.format(script_name=script_name_or_path)
            )
        self._start_hook_with_script_path(
            package_name=package_name,
            script_path=script_path,
            use_spawn=use_spawn,
            busy_message=ui_messages.STARTING_HOOK,
        )

    def _start_builtin_quick_hook(
        self,
        *,
        script_name: str,
        use_spawn: bool,
        busy_message: str,
        action_log: str,
        script_log_template: str,
        mode_log_template: str,
    ) -> None:
        if self.hook_thread is not None:
            return

        package_name = self.selected_package_name()
        if not package_name:
            self._present_local_error(AppNotSelectedError(ui_messages.APP_NOT_SELECTED_BODY))
            return

        try:
            script_path = self.resolve_builtin_quick_script_path(script_name)
        except HookersError as exc:
            self._present_local_error(exc)
            return

        mode = "spawn" if use_spawn else "attach"
        self.append_log(action_log)
        self.append_log(script_log_template.format(script_path=script_path))
        self.append_log(mode_log_template.format(mode=mode))
        self._start_hook_with_script_path(
            package_name=package_name,
            script_path=script_path,
            use_spawn=use_spawn,
            busy_message=busy_message,
        )

    def resolve_quick_script_path(self, package_name: str, script_name: str) -> Path:
        workspace_script = self.deps.workspace_service.script_dir(package_name) / script_name
        if workspace_script.is_file():
            return workspace_script

        return self.resolve_builtin_quick_script_path(script_name)

    def resolve_builtin_quick_script_path(self, script_name: str) -> Path:
        builtin_script = self.deps.context.hookers_js_dir / script_name
        if builtin_script.is_file():
            return builtin_script

        raise HookStartError(
            f"快捷脚本不存在：{script_name}",
            hint="请检查工作区脚本目录或项目内置 js 目录中是否存在该脚本。",
        )

    def _start_hook_with_script_path(
        self,
        *,
        package_name: str,
        script_path: Path,
        use_spawn: bool,
        busy_message: str,
    ) -> None:
        self.append_log(ui_messages.TARGET_APP_LOG.format(package=package_name))
        self.append_log(
            ui_messages.SELECTED_SCRIPT_LOG.format(script_name=script_path.name)
        )
        self.set_busy(True, busy_message)

        self.hook_thread = QThread(self.owner)
        self.hook_worker = HookWorker(
            device_service=self.deps.device_service,
            session_service=self.deps.session_service,
            workspace_service=self.deps.workspace_service,
            package_name=package_name,
            script_path=script_path,
            use_spawn=use_spawn,
            ensure_workspace=False,
        )
        self.hook_worker.moveToThread(self.hook_thread)

        self.hook_thread.started.connect(self.hook_worker.run)
        self.hook_worker.started.connect(
            lambda mode, package_name, script_name: self.ui_dispatcher.submit(
                self.on_hook_started,
                mode,
                package_name,
                script_name,
            )
        )
        self.hook_worker.failed.connect(
            lambda error: self.ui_dispatcher.submit(self.show_worker_error, error)
        )
        self.hook_worker.finished.connect(self.hook_thread.quit)
        self.hook_worker.finished.connect(self.hook_worker.deleteLater)
        self.hook_thread.finished.connect(self.hook_thread.deleteLater)
        self.hook_thread.finished.connect(self._clear_hook_thread)
        self.hook_thread.start()

    def _clear_hook_thread(self) -> None:
        self.hook_thread = None
        self.hook_worker = None

    def on_hook_started(self, mode: str, package_name: str, script_name: str) -> None:
        self.set_busy(False, ui_messages.HOOK_STARTED_STATUS.format(mode=mode))
        self.widgets.start_hook_button.setDisabled(True)
        self.widgets.stop_hook_button.setDisabled(False)
        self._set_quick_hook_buttons_disabled(True)
        self.set_status_text(
            ui_messages.HOOK_RUNNING_STATE.format(
                mode=mode,
                package=package_name,
                script_name=script_name,
            )
        )
        self.append_log(
            ui_messages.HOOK_STARTED_LOG.format(
                mode=mode,
                package=package_name,
                script_name=script_name,
            )
        )
        self.refresh_app_status_panel(package_name)

    def start_runtime_action(
        self,
        *,
        busy_message: str,
        action: WorkerAction,
        on_success: WorkerSuccessHandler,
    ) -> None:
        if self.runtime_action_thread is not None:
            return

        self.set_busy(True, busy_message)
        self.runtime_action_thread = QThread(self.owner)
        self.runtime_action_worker = ActionWorker(action)
        self.runtime_action_worker.moveToThread(self.runtime_action_thread)

        self.runtime_action_thread.started.connect(self.runtime_action_worker.run)
        self.runtime_action_worker.succeeded.connect(
            lambda payload: self.ui_dispatcher.submit(on_success, payload)
        )
        self.runtime_action_worker.failed.connect(
            lambda error: self.ui_dispatcher.submit(self.show_worker_error, error)
        )
        self.runtime_action_worker.finished.connect(self.runtime_action_thread.quit)
        self.runtime_action_worker.finished.connect(self.runtime_action_worker.deleteLater)
        self.runtime_action_thread.finished.connect(self.runtime_action_thread.deleteLater)
        self.runtime_action_thread.finished.connect(self._clear_runtime_action_thread)
        self.runtime_action_thread.start()

    def _clear_runtime_action_thread(self) -> None:
        self.runtime_action_thread = None
        self.runtime_action_worker = None

    def stop_hook(self) -> None:
        def action() -> None:
            try:
                self.deps.session_service.stop_active_session()
            except Exception as exc:
                raise HookStopError(
                    "停止 Hook 失败。",
                    hint="请确认当前会话仍然有效，或重新准备环境后再试。",
                ) from exc

        self.start_runtime_action(
            busy_message=ui_messages.STOPPING_HOOK,
            action=action,
            on_success=self.on_hook_stopped,
        )

    def on_hook_stopped(self, _payload: object) -> None:
        self.deps.rpc_service.invalidate_persistent_session()
        self.set_status_text(ui_messages.HOOK_STOPPED_STATE, ui_messages.HOOK_STOPPED_STATUS)
        self.append_log(ui_messages.HOOK_STOPPED_LOG)
        self.widgets.start_hook_button.setDisabled(False)
        self.widgets.stop_hook_button.setDisabled(True)
        self._set_quick_hook_buttons_disabled(False)
        self.refresh_app_status_panel(None)
        self.set_busy(False, ui_messages.READY)
        self._auto_stop_in_progress = False

    def on_auto_stop_finished(self, _payload: object) -> None:
        self.deps.rpc_service.invalidate_persistent_session()
        self.set_status_text(ui_messages.HOOK_STOPPED_STATE, ui_messages.HOOK_STOPPED_STATUS)
        self.append_log(ui_messages.NETWORK_STACK_AUTO_STOPPED_LOG)
        self.widgets.start_hook_button.setDisabled(False)
        self.widgets.stop_hook_button.setDisabled(True)
        self._set_quick_hook_buttons_disabled(False)
        self.refresh_app_status_panel(None)
        self.set_busy(False, ui_messages.READY)
        self._auto_stop_in_progress = False

    def stop_frida_server(self) -> None:
        def action() -> None:
            try:
                self.deps.rpc_service.invalidate_persistent_session()
                if self.deps.context.active_session is not None:
                    self.deps.session_service.stop_active_session()
                self.deps.device_service.stop_frida_server()
            except Exception as exc:
                if isinstance(exc, FridaServerStopError):
                    raise
                raise FridaServerStopError(
                    "停止 Frida Server 失败。",
                    hint="请检查当前会话状态、设备 root 权限和 rusda 进程状态后重试。",
                ) from exc

        self.start_runtime_action(
            busy_message=ui_messages.STOPPING_FRIDA_SERVER,
            action=action,
            on_success=self.on_frida_server_stopped,
        )

    def on_frida_server_stopped(self, _payload: object) -> None:
        self.set_status_text(
            ui_messages.FRIDA_SERVER_STOPPED,
            ui_messages.FRIDA_SERVER_STOPPED,
        )
        self.append_log(ui_messages.FRIDA_SERVER_STOPPED_LOG)
        self.widgets.start_hook_button.setDisabled(False)
        self.widgets.stop_hook_button.setDisabled(True)
        self._set_quick_hook_buttons_disabled(False)
        self.refresh_app_status_panel(None)
        self.set_busy(False, ui_messages.READY)

    def restart_current_app(self) -> None:
        def action() -> RestartAppPayload:
            try:
                package_name = self.ensure_current_app_ready()
                self.deps.rpc_service.invalidate_persistent_session()
                if self.deps.context.active_session is not None:
                    self.deps.session_service.stop_active_session()
                self.deps.session_service.restart_current_app()
                apps = self.deps.device_service.refresh_applications()
                return RestartAppPayload(
                    package_name=package_name,
                    apps=[
                        {"name": app.name, "identifier": app.identifier, "pid": app.pid}
                        for app in apps
                    ],
                )
            except Exception as exc:
                if isinstance(exc, HookersError):
                    raise
                raise RestartAppError(
                    "重启 App 失败。",
                    hint="请检查目标 App 状态、设备连接以及当前会话状态后重试。",
                ) from exc

        self.start_runtime_action(
            busy_message=ui_messages.RESTARTING_APP,
            action=action,
            on_success=self.on_restart_current_app_finished,
        )

    def on_restart_current_app_finished(self, payload: RestartAppPayload) -> None:
        self.deps.rpc_service.invalidate_persistent_session()
        package_name = payload.package_name
        self.append_log(ui_messages.RESTARTED_APP_LOG.format(package=package_name))
        self.apply_apps_payload(payload.apps, None)
        current_index = self.widgets.app_combo.findData(package_name)
        if current_index >= 0:
            self.widgets.app_combo.setCurrentIndex(current_index)
        self.refresh_app_status_panel(package_name)
        self.set_busy(False, ui_messages.READY)
