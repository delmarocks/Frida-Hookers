from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Callable
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
from core.workspace_service import (
    AdvancedLauncherPresetEntry,
    AdvancedLauncherPresetSnapshot,
    ScriptSourceInfo,
    SessionRecord,
)

from .controller_types import (
    AppsPayloadApplier,
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
from .quick_hook_actions import (
    ANALYSIS_SCENARIO_PROFILES_BY_KEY,
    QUICK_HOOK_ACTIONS_BY_KEY,
    QUICK_HOOK_BUTTON_ATTRS,
)
from .workers.action_worker import ActionWorker
from .workers.hook_worker import HookWorker
from .ui_thread_dispatcher import UiThreadDispatcher
from .frida_multi_launcher_dialog import (
    FridaMultiLauncherDialog,
    FridaScriptOption,
)
from . import ui_messages


@dataclass
class HookRuntimeWidgets:
    start_hook_button: QPushButton
    stop_hook_button: QPushButton
    current_state_label: QLabel
    app_combo: QComboBox
    set_session_status: Callable[[str, str | None, str | None, str | None, str | None], None]


@dataclass
class TraceInitProcParams:
    target_so: str
    start_addr: str
    end_addr: str


@dataclass(frozen=True)
class LaunchRequest:
    package_name: str
    script_path: Path
    use_spawn: bool
    busy_message: str
    action_log: str | None = None
    bundle_log_message: str | None = None
    script_log_path: Path | None = None
    mode_log_message: str | None = None
    order_log_message: str | None = None
    note_log_message: str | None = None
    skip_default_selected_script_log: bool = False


@dataclass(frozen=True)
class SessionStatusSnapshot:
    phase: str
    mode: str | None = None
    package_name: str | None = None
    script_name: str | None = None
    detail: str | None = None


class ParameterizedResolutionStatus(str, Enum):
    SUCCESS = "success"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True)
class ParameterizedTemplateResolution:
    status: ParameterizedResolutionStatus
    payload: object | None = None
    option: FridaScriptOption | None = None

    @property
    def cancelled(self) -> bool:
        return self.status is ParameterizedResolutionStatus.CANCELLED

    @property
    def failed(self) -> bool:
        return self.status is ParameterizedResolutionStatus.FAILED


class TraceInitProcDialog(QDialog):
    def _parameterized_runtime_write_error(self, message: str, *, hint: str) -> HookStartError:
        return _ParameterizedRuntimeWriteError(message, hint=hint)

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




@dataclass(frozen=True)
class _ParameterizedTemplateSpec:
    kind: str
    script_name: str
    runtime_name: str
    collect_method_name: str
    summary_method_name: str
    single_materialize_method_name: str
    advanced_materialize_method_name: str

class _ParameterizedRuntimeWriteError(HookStartError):
    pass


class HookRuntimeController:
    PARAMETERIZED_TEMPLATE_SPECS = (
        _ParameterizedTemplateSpec(
            kind="jni_method_trace",
            script_name="jni_method_trace.js",
            runtime_name="jni_method_trace.runtime.js",
            collect_method_name="collect_jni_method_trace_params",
            summary_method_name="_summarize_jni_method_trace_params",
            single_materialize_method_name="_materialize_jni_method_trace_script",
            advanced_materialize_method_name="_materialize_advanced_jni_method_trace_script",
        ),
        _ParameterizedTemplateSpec(
            kind="trace_init_proc",
            script_name="trace_init_proc.js",
            runtime_name="trace_init_proc.runtime.js",
            collect_method_name="collect_trace_init_proc_params",
            summary_method_name="_summarize_trace_init_proc_params",
            single_materialize_method_name="_materialize_trace_init_proc_script",
            advanced_materialize_method_name="_materialize_advanced_trace_init_proc_script",
        ),
    )

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
        self._parameterized_template_specs = {
            spec.kind: spec for spec in self.PARAMETERIZED_TEMPLATE_SPECS
        }
        self._parameterized_template_script_map = {
            spec.script_name: spec for spec in self.PARAMETERIZED_TEMPLATE_SPECS
        }
        self._set_session_status_idle()

    def _present_local_error(
        self,
        exc: HookersError,
        *,
        mark_session_failed: bool = True,
    ) -> None:
        if mark_session_failed:
            self._set_session_status_failed()
        self.show_worker_error(to_ui_error_payload(exc))

    def _set_session_status(self, snapshot: SessionStatusSnapshot) -> None:
        self.widgets.set_session_status(
            snapshot.phase,
            snapshot.mode,
            snapshot.package_name,
            snapshot.script_name,
            snapshot.detail,
        )

    def _set_session_status_idle(self) -> None:
        self._set_session_status(
            SessionStatusSnapshot(
                phase=ui_messages.SESSION_STATUS_PHASE_IDLE,
                detail=ui_messages.SESSION_STATUS_STOPPED_DETAIL,
            )
        )

    def _set_session_status_failed(self) -> None:
        self._set_session_status(
            SessionStatusSnapshot(
                phase=ui_messages.SESSION_STATUS_PHASE_FAILED,
                detail=ui_messages.SESSION_STATUS_FAILED_DETAIL,
            )
        )

    def _set_session_status_starting(self, *, mode: str, package_name: str, script_name: str) -> None:
        self._set_session_status(
            SessionStatusSnapshot(
                phase=ui_messages.SESSION_STATUS_PHASE_STARTING,
                mode=mode,
                package_name=package_name,
                script_name=script_name,
                detail=ui_messages.SESSION_STATUS_STARTING_DETAIL,
            )
        )

    def _set_session_status_running(self, *, mode: str, package_name: str, script_name: str) -> None:
        self._set_session_status(
            SessionStatusSnapshot(
                phase=ui_messages.SESSION_STATUS_PHASE_RUNNING,
                mode=mode,
                package_name=package_name,
                script_name=script_name,
                detail=ui_messages.HOOK_STARTED_STATUS.format(mode=mode),
            )
        )

    def _set_session_status_stopping(self) -> None:
        active_mode = getattr(self.deps.context.active_session, "mode", None)
        self._set_session_status(
            SessionStatusSnapshot(
                phase=ui_messages.SESSION_STATUS_PHASE_STOPPING,
                mode=active_mode,
                package_name=self.selected_package_name(),
                detail=ui_messages.SESSION_STATUS_STOPPING_DETAIL,
            )
        )

    def _set_session_status_auto_stopping(self) -> None:
        active_mode = getattr(self.deps.context.active_session, "mode", None)
        self._set_session_status(
            SessionStatusSnapshot(
                phase=ui_messages.SESSION_STATUS_PHASE_AUTO_STOPPING,
                mode=active_mode,
                package_name=self.selected_package_name(),
                detail=ui_messages.SESSION_STATUS_AUTO_STOPPING_DETAIL,
            )
        )

    def _set_session_status_detached(self, *, mode: str, package_name: str | None) -> None:
        self._set_session_status(
            SessionStatusSnapshot(
                phase=ui_messages.SESSION_STATUS_PHASE_DETACHED,
                mode=mode,
                package_name=package_name,
                detail=ui_messages.SESSION_STATUS_DETACHED_DETAIL,
            )
        )

    def _prepare_hook_launch_context(
        self,
        *,
        require_idle_session: bool = False,
        active_session_error: HookersError | None = None,
    ) -> str | None:
        if self.hook_thread is not None:
            self._present_local_error(
                HookStartError(
                    ui_messages.HOOK_START_BUSY_BODY,
                    severity="warning",
                    dialog_title=ui_messages.ERROR_DIALOG_TITLE,
                    next_step=ui_messages.HOOK_START_BUSY_NEXT_STEP,
                ),
                mark_session_failed=False,
            )
            return None
        if require_idle_session and self.deps.context.active_session is not None:
            self._present_local_error(
                active_session_error
                or HookStartError(
                    ui_messages.ADVANCED_FRIDA_ACTIVE_SESSION_BODY,
                    severity="warning",
                    dialog_title=ui_messages.ERROR_DIALOG_TITLE,
                ),
                mark_session_failed=False,
            )
            return None
        package_name = self.selected_package_name()
        if not package_name:
            self._present_local_error(
                AppNotSelectedError(ui_messages.APP_NOT_SELECTED_BODY),
                mark_session_failed=False,
            )
            return None
        return package_name

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
        self._set_session_status_detached(mode=mode, package_name=package_name or None)
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
        self._set_session_status_auto_stopping()
        self.start_runtime_action(
            busy_message=ui_messages.STOPPING_HOOK,
            action=self.deps.session_service.stop_active_session,
            on_success=self.on_auto_stop_finished,
        )

    def start_hook(self, use_spawn: bool) -> None:
        package_name = self._prepare_hook_launch_context(
            require_idle_session=True,
            active_session_error=HookStartError(
                ui_messages.ADVANCED_FRIDA_ACTIVE_SESSION_BODY,
                severity="warning",
                dialog_title=ui_messages.ERROR_DIALOG_TITLE,
                next_step=ui_messages.ADVANCED_FRIDA_ACTIVE_SESSION_NEXT_STEP,
            ),
        )
        if not package_name:
            return

        script_path = self.selected_script_path()
        if script_path is None:
            self._present_local_error(
                ScriptSelectionError(ui_messages.SCRIPT_NOT_SELECTED_BODY),
                mark_session_failed=False,
            )
            return

        self._start_launch_request(
            LaunchRequest(
                package_name=package_name,
                script_path=script_path,
                use_spawn=use_spawn,
                busy_message=ui_messages.STARTING_HOOK,
            )
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
        self._start_parameterized_template_quick_hook(
            self._parameterized_template_spec("jni_method_trace"),
            use_spawn,
            busy_message=ui_messages.TRACING_JNI_METHODS,
            action_log=ui_messages.JNI_METHOD_TRACE_ACTION_LOG,
            script_log_message=ui_messages.JNI_METHOD_TRACE_SCRIPT_LOG,
            mode_log_message=ui_messages.JNI_METHOD_TRACE_MODE_LOG,
            detail_log_builder=lambda payload: ui_messages.JNI_METHOD_TRACE_TARGET_SO_LOG.format(target_so=payload),
        )

    def start_trace_init_proc(self, use_spawn: bool) -> None:
        self._start_parameterized_template_quick_hook(
            self._parameterized_template_spec("trace_init_proc"),
            use_spawn,
            busy_message=ui_messages.TRACING_INIT_PROC,
            action_log=ui_messages.TRACE_INIT_PROC_ACTION_LOG,
            script_log_message=ui_messages.TRACE_INIT_PROC_SCRIPT_LOG,
            mode_log_message=ui_messages.TRACE_INIT_PROC_MODE_LOG,
            detail_log_builder=lambda payload: ui_messages.TRACE_INIT_PROC_PARAMS_LOG.format(
                target_so=payload.target_so,
                start_addr=payload.start_addr,
                end_addr=payload.end_addr,
            ),
        )

    def start_analysis_scenario(self, scenario_key: str, use_spawn: bool) -> None:
        package_name = self._prepare_hook_launch_context(
            require_idle_session=True,
            active_session_error=HookStartError(
                ui_messages.ADVANCED_FRIDA_ACTIVE_SESSION_BODY,
                severity="warning",
                dialog_title=ui_messages.ERROR_DIALOG_TITLE,
                next_step=ui_messages.ADVANCED_FRIDA_ACTIVE_SESSION_NEXT_STEP,
            ),
        )
        if not package_name:
            return
        profile = ANALYSIS_SCENARIO_PROFILES_BY_KEY[scenario_key]
        resolved = self._resolve_analysis_scenario_options(package_name, scenario_key)
        if resolved is None:
            return
        selected_options, scenario_note = resolved
        if not selected_options:
            return
        try:
            script_path = self.deps.workspace_service.materialize_multi_script_bundle(
                package_name,
                [option.path for option in selected_options],
            )
        except HookersError as exc:
            self.append_log(profile.action_log)
            self._present_local_error(exc, mark_session_failed=False)
            return

        mode = "spawn" if use_spawn else "attach"
        self._start_launch_request(
            LaunchRequest(
                package_name=package_name,
                script_path=script_path,
                use_spawn=use_spawn,
                busy_message=profile.busy_message,
                action_log=profile.action_log,
                bundle_log_message=ui_messages.ADVANCED_FRIDA_BUNDLE_LOG.format(script_path=script_path),
                order_log_message=ui_messages.ANALYSIS_SCENARIO_OPTION_LOG.format(
                    scripts=" -> ".join(self._advanced_frida_option_log_label(option) for option in selected_options)
                ),
                note_log_message="\n".join(
                    [
                        ui_messages.ANALYSIS_SCENARIO_MODE_LOG.format(mode=mode),
                        ui_messages.ANALYSIS_SCENARIO_NOTE_LOG.format(note=scenario_note),
                    ]
                ),
            )
        )

    def open_analysis_scenario_as_template(self, scenario_key: str, use_spawn: bool) -> None:
        package_name = self._prepare_hook_launch_context(
            require_idle_session=True,
            active_session_error=HookStartError(
                ui_messages.ADVANCED_FRIDA_ACTIVE_SESSION_BODY,
                severity="warning",
                dialog_title=ui_messages.ERROR_DIALOG_TITLE,
                next_step=ui_messages.ADVANCED_FRIDA_ACTIVE_SESSION_NEXT_STEP,
            ),
        )
        if not package_name:
            return
        resolved = self._resolve_analysis_scenario_options(package_name, scenario_key)
        if resolved is None:
            return
        selected_options, _ = resolved
        if not selected_options:
            return
        dialog = self._open_advanced_launcher_dialog(
            package_name,
            use_spawn=use_spawn,
            initial_selected_options=selected_options,
        )
        dialog.exec()

    def start_advanced_frida_launcher(self, use_spawn: bool) -> None:
        package_name = self._prepare_hook_launch_context(
            require_idle_session=True,
            active_session_error=HookStartError(
                ui_messages.ADVANCED_FRIDA_ACTIVE_SESSION_BODY,
                severity="warning",
                dialog_title=ui_messages.ERROR_DIALOG_TITLE,
                next_step=ui_messages.ADVANCED_FRIDA_ACTIVE_SESSION_NEXT_STEP,
            ),
        )
        if not package_name:
            return

        dialog = self._open_advanced_launcher_dialog(package_name, use_spawn=use_spawn)
        if dialog is None:
            return
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        selected_options = dialog.selected_options()
        self._save_advanced_launcher_preset_options(package_name, selected_options)
        if not selected_options:
            if not getattr(dialog, "had_add_cancelled", lambda: False)():
                self.append_log(ui_messages.ADVANCED_FRIDA_ACTION_LOG)
            self._present_local_error(
                HookStartError(
                    ui_messages.ADVANCED_FRIDA_NO_SCRIPT_BODY,
                    severity="warning",
                    dialog_title=ui_messages.SCRIPT_NOT_SELECTED_TITLE,
                    next_step=ui_messages.ADVANCED_FRIDA_EMPTY_SELECTION_NEXT_STEP,
                ),
                mark_session_failed=False,
            )
            return

        try:
            script_path = self.deps.workspace_service.materialize_multi_script_bundle(
                package_name,
                [option.path for option in selected_options],
            )
        except HookersError as exc:
            self.append_log(ui_messages.ADVANCED_FRIDA_ACTION_LOG)
            self._present_local_error(exc, mark_session_failed=False)
            return

        self._start_launch_request(
            LaunchRequest(
                package_name=package_name,
                script_path=script_path,
                use_spawn=use_spawn,
                busy_message=ui_messages.STARTING_ADVANCED_FRIDA,
                action_log=ui_messages.ADVANCED_FRIDA_ACTION_LOG,
                bundle_log_message=ui_messages.ADVANCED_FRIDA_BUNDLE_LOG.format(script_path=script_path),
                order_log_message=ui_messages.ADVANCED_FRIDA_ORDER_LOG.format(
                    scripts=" -> ".join(self._advanced_frida_option_log_label(option) for option in selected_options)
                ),
                note_log_message=self._advanced_frida_combined_note_log_message(selected_options),
            )
        )

    def _open_advanced_launcher_dialog(
        self,
        package_name: str,
        *,
        use_spawn: bool,
        initial_selected_options: list[FridaScriptOption] | None = None,
    ) -> FridaMultiLauncherDialog:
        mode = "spawn" if use_spawn else "attach"
        preset_snapshot = self._load_advanced_launcher_preset_snapshot(package_name)
        selected_options = list(preset_snapshot.entries) if initial_selected_options is None else list(initial_selected_options)
        return FridaMultiLauncherDialog(
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
            initial_selected_options=selected_options,
        )

    def _parameterized_template_spec(self, kind: str) -> _ParameterizedTemplateSpec:
        return self._parameterized_template_specs[kind]

    def _parameterized_template_spec_for_script(self, script_name: str) -> _ParameterizedTemplateSpec | None:
        return self._parameterized_template_script_map.get(script_name)

    def _collect_parameterized_template_params(
        self,
        spec: _ParameterizedTemplateSpec,
        initial_payload: object | None = None,
    ) -> ParameterizedTemplateResolution:
        collector = getattr(self, spec.collect_method_name)
        if initial_payload is None:
            payload = collector()
        else:
            payload = collector(initial_payload)
        if payload is None:
            return ParameterizedTemplateResolution(
                status=ParameterizedResolutionStatus.CANCELLED
            )
        return ParameterizedTemplateResolution(
            status=ParameterizedResolutionStatus.SUCCESS,
            payload=payload,
        )

    def _summarize_jni_method_trace_params(self, target_so: str) -> str:
        return target_so.strip()

    def _normalize_runtime_summary(self, summary: str | None, *, fallback: str) -> str:
        normalized = str(summary or "").strip()
        return normalized or fallback

    def _summarize_parameterized_template(
        self,
        spec: _ParameterizedTemplateSpec,
        payload: object,
    ) -> str | None:
        summary_builder = getattr(self, spec.summary_method_name)
        try:
            summary = summary_builder(payload)
        except Exception:
            return self._runtime_name_fallback_summary(spec.runtime_name)
        return self._normalize_runtime_summary(
            summary,
            fallback=self._runtime_name_fallback_summary(spec.runtime_name) or spec.runtime_name,
        )

    def _materialize_parameterized_template_runtime(
        self,
        spec: _ParameterizedTemplateSpec,
        *,
        package_name: str,
        payload: object,
        runtime_key: str | None = None,
        advanced: bool,
        runtime_write_failed_hint: str,
    ) -> Path:
        method_name = (
            spec.advanced_materialize_method_name if advanced else spec.single_materialize_method_name
        )
        materializer = getattr(self, method_name)
        if spec.kind == "jni_method_trace":
            kwargs = {
                "package_name": package_name,
                "target_so": payload,
            }
        else:
            params = payload
            kwargs = {
                "package_name": package_name,
                "target_so": params.target_so,
                "start_addr": params.start_addr,
                "end_addr": params.end_addr,
            }
        if advanced:
            kwargs["runtime_key"] = runtime_key
        try:
            return materializer(**kwargs)
        except _ParameterizedRuntimeWriteError as exc:
            raise self._parameterized_runtime_write_error(
                str(exc),
                hint=runtime_write_failed_hint,
            ) from exc

    def _build_parameterized_runtime_option(
        self,
        spec: _ParameterizedTemplateSpec,
        *,
        package_name: str,
        template_option: FridaScriptOption,
        payload: object,
    ) -> FridaScriptOption:
        runtime_key = template_option.runtime_key or uuid4().hex[:8]
        runtime_path = self._materialize_parameterized_template_runtime(
            spec,
            package_name=package_name,
            payload=payload,
            runtime_key=runtime_key,
            advanced=True,
            runtime_write_failed_hint=ui_messages.ADVANCED_PARAMETERIZED_RUNTIME_WRITE_FAILED_HINT,
        )
        summary = self._summarize_parameterized_template(spec, payload)
        return FridaScriptOption(
            label=self._format_advanced_runtime_label(
                runtime_name=spec.runtime_name,
                source_kind="workspace",
                summary=summary,
            ),
            path=runtime_path,
            kind=spec.kind,
            source_kind="workspace",
            display_name=spec.runtime_name,
            summary=summary,
            template_path=template_option.template_path or template_option.path,
            config_payload=payload,
            runtime_key=runtime_key,
            is_pinned=template_option.is_pinned,
            last_used_at=template_option.last_used_at,
            tags=template_option.tags,
        )

    def _resolve_parameterized_runtime_option(
        self,
        spec: _ParameterizedTemplateSpec,
        *,
        package_name: str,
        template_option: FridaScriptOption,
        initial_payload: object | None = None,
    ) -> ParameterizedTemplateResolution:
        collected = self._collect_parameterized_template_params(
            spec,
            initial_payload=initial_payload,
        )
        if collected.cancelled or collected.failed:
            return collected
        try:
            option = self._build_parameterized_runtime_option(
                spec,
                package_name=package_name,
                template_option=template_option,
                payload=collected.payload,
            )
        except HookersError as exc:
            self._present_local_error(exc, mark_session_failed=False)
            return ParameterizedTemplateResolution(
                status=ParameterizedResolutionStatus.FAILED
            )
        return ParameterizedTemplateResolution(
            status=ParameterizedResolutionStatus.SUCCESS,
            payload=collected.payload,
            option=option,
        )

    def _resolved_parameterized_option_or_none(
        self,
        spec: _ParameterizedTemplateSpec,
        *,
        package_name: str,
        template_option: FridaScriptOption,
        initial_payload: object | None = None,
    ) -> FridaScriptOption | None:
        resolved = self._resolve_parameterized_runtime_option(
            spec,
            package_name=package_name,
            template_option=template_option,
            initial_payload=initial_payload,
        )
        if resolved.cancelled or resolved.failed:
            return None
        return resolved.option

    def _start_parameterized_template_quick_hook(
        self,
        spec: _ParameterizedTemplateSpec,
        use_spawn: bool,
        *,
        busy_message: str,
        action_log: str,
        script_log_message: str,
        mode_log_message: str,
        detail_log_builder,
    ) -> None:
        if self.hook_thread is not None:
            self._present_local_error(
                HookStartError(
                    ui_messages.HOOK_START_BUSY_BODY,
                    severity="warning",
                    dialog_title=ui_messages.ERROR_DIALOG_TITLE,
                    next_step=ui_messages.HOOK_START_BUSY_NEXT_STEP,
                ),
                mark_session_failed=False,
            )
            return

        package_name = self.selected_package_name()
        if not package_name:
            self._present_local_error(
                AppNotSelectedError(ui_messages.APP_NOT_SELECTED_BODY),
                mark_session_failed=False,
            )
            return

        collected = self._collect_parameterized_template_params(spec)
        if collected.cancelled or collected.failed:
            return
        payload = collected.payload
        assert payload is not None
        try:
            script_path = self._materialize_parameterized_template_runtime(
                spec,
                package_name=package_name,
                payload=payload,
                advanced=False,
                runtime_write_failed_hint=ui_messages.PARAMETERIZED_RUNTIME_WRITE_FAILED_HINT,
            )
        except HookersError as exc:
            self._present_local_error(exc, mark_session_failed=False)
            return

        mode = "spawn" if use_spawn else "attach"
        self.append_log(action_log)
        self.append_log(script_log_message.format(script_path=script_path))
        self.append_log(detail_log_builder(payload))
        self.append_log(mode_log_message.format(mode=mode))
        self._start_hook_with_script_path(
            package_name=package_name,
            script_path=script_path,
            use_spawn=use_spawn,
            busy_message=busy_message,
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
            raise self._parameterized_runtime_write_error(
                "写入 JNI 跟踪运行时脚本失败。",
                hint=ui_messages.PARAMETERIZED_RUNTIME_WRITE_FAILED_HINT,
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
                    next_step=ui_messages.JNI_TARGET_SO_REQUIRED_NEXT_STEP,
                ),
                mark_session_failed=False,
            )
            return None
        if ".so" not in normalized_target_so:
            self._present_local_error(
                HookStartError(
                    ui_messages.JNI_TARGET_SO_INVALID_BODY,
                    severity="warning",
                    dialog_title=ui_messages.MISSING_TARGET_TITLE,
                    next_step=ui_messages.JNI_TARGET_SO_INVALID_NEXT_STEP,
                ),
                mark_session_failed=False,
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
            raise self._parameterized_runtime_write_error(
                "写入 init_proc 跟踪运行时脚本失败。",
                hint=ui_messages.PARAMETERIZED_RUNTIME_WRITE_FAILED_HINT,
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
            raise self._parameterized_runtime_write_error(
                "写入 JNI 跟踪运行时脚本失败。",
                hint=ui_messages.PARAMETERIZED_RUNTIME_WRITE_FAILED_HINT,
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
            raise self._parameterized_runtime_write_error(
                "写入 init_proc 跟踪运行时脚本失败。",
                hint=ui_messages.PARAMETERIZED_RUNTIME_WRITE_FAILED_HINT,
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
                    next_step=ui_messages.TRACE_INIT_PROC_REQUIRED_SO_NEXT_STEP,
                ),
                mark_session_failed=False,
            )
            return None
        if ".so" not in normalized_target_so:
            self._present_local_error(
                HookStartError(
                    ui_messages.TRACE_INIT_PROC_INVALID_SO_BODY,
                    severity="warning",
                    dialog_title=ui_messages.MISSING_TARGET_TITLE,
                    next_step=ui_messages.TRACE_INIT_PROC_INVALID_SO_NEXT_STEP,
                ),
                mark_session_failed=False,
            )
            return None

        raw_start_addr = params.start_addr.strip()
        if not raw_start_addr:
            self._present_local_error(
                HookStartError(
                    ui_messages.TRACE_INIT_PROC_REQUIRED_START_BODY,
                    severity="warning",
                    dialog_title=ui_messages.MISSING_TARGET_TITLE,
                    next_step=ui_messages.TRACE_INIT_PROC_REQUIRED_START_NEXT_STEP,
                ),
                mark_session_failed=False,
            )
            return None
        raw_end_addr = params.end_addr.strip()
        if not raw_end_addr:
            self._present_local_error(
                HookStartError(
                    ui_messages.TRACE_INIT_PROC_REQUIRED_END_BODY,
                    severity="warning",
                    dialog_title=ui_messages.MISSING_TARGET_TITLE,
                    next_step=ui_messages.TRACE_INIT_PROC_REQUIRED_END_NEXT_STEP,
                ),
                mark_session_failed=False,
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
                    next_step=ui_messages.TRACE_INIT_PROC_INVALID_ADDR_NEXT_STEP,
                ),
                mark_session_failed=False,
            )
            return None

        if int(normalized_end_addr, 16) < int(normalized_start_addr, 16):
            self._present_local_error(
                HookStartError(
                    ui_messages.TRACE_INIT_PROC_RANGE_BODY,
                    severity="warning",
                    dialog_title=ui_messages.MISSING_TARGET_TITLE,
                    next_step=ui_messages.TRACE_INIT_PROC_RANGE_NEXT_STEP,
                ),
                mark_session_failed=False,
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
        for info in self.deps.workspace_service.list_launcher_candidate_scripts(package_name):
            if info.source_kind == "workspace_builtin_copy":
                source_kind = "workspace_builtin_copy"
            else:
                source_kind = info.source_kind
            options.append(
                self._make_advanced_frida_option_from_source(
                    package_name,
                    info,
                    source_kind=source_kind,
                )
            )
        return options

    def _resolve_analysis_scenario_options(
        self,
        package_name: str,
        scenario_key: str,
    ) -> tuple[list[FridaScriptOption], str] | None:
        profile = ANALYSIS_SCENARIO_PROFILES_BY_KEY[scenario_key]
        options: list[FridaScriptOption] = []
        for entry in profile.entries:
            option = self._resolve_analysis_scenario_entry(package_name, entry.action_key)
            if option is None:
                action = QUICK_HOOK_ACTIONS_BY_KEY.get(entry.action_key)
                script_name = action.script_name if action is not None else entry.action_key
                if entry.required:
                    self._present_local_error(
                        HookStartError(
                            ui_messages.ANALYSIS_SCENARIO_MISSING_REQUIRED_SCRIPT.format(script_name=script_name),
                            hint=ui_messages.ANALYSIS_SCENARIO_MISSING_REQUIRED_SCRIPT_HINT,
                        ),
                        mark_session_failed=False,
                    )
                    return None
                continue
            options.append(option)
        return options, f"{profile.title}；{profile.description}"

    def _resolve_analysis_scenario_entry(
        self,
        package_name: str,
        action_key: str,
    ) -> FridaScriptOption | None:
        action = QUICK_HOOK_ACTIONS_BY_KEY.get(action_key)
        if action is None:
            return None
        try:
            script_path = self.resolve_builtin_quick_script_path(action.script_name)
        except HookersError:
            try:
                script_path = self.resolve_quick_script_path(package_name, action.script_name)
            except HookersError:
                return None
        try:
            candidates = self.deps.workspace_service.list_launcher_candidate_scripts(package_name)
        except Exception:
            candidates = []
        matched_info = None
        for info in candidates:
            try:
                if info.path.resolve() == script_path.resolve():
                    matched_info = info
                    break
            except Exception:
                continue
        if matched_info is None:
            source_kind = "builtin_source"
            try:
                if script_path.parent == self.deps.workspace_service.script_dir(package_name):
                    source_kind = self.deps.workspace_service._script_source_kind(script_path.name, in_workspace=True)
            except Exception:
                pass
            matched_info = self.deps.workspace_service.build_script_source_info(
                script_path,
                source_kind=source_kind,
            )
        option = self._make_advanced_frida_option_from_source(
            package_name,
            matched_info,
            source_kind=matched_info.source_kind,
        )
        return self._resolve_advanced_frida_option(package_name, option)

    def _advanced_frida_option_metadata(
        self,
        package_name: str,
        info: ScriptSourceInfo,
    ):
        if info.metadata is not None:
            return info.metadata
        if getattr(info, "source_kind", None) != "builtin_source":
            return None
        try:
            return self.deps.workspace_service.resolve_script_metadata(package_name, info.name)
        except Exception:
            return None

    def _make_advanced_frida_option_from_source(
        self,
        package_name: str,
        info: ScriptSourceInfo,
        *,
        source_kind: str,
    ) -> FridaScriptOption:
        metadata = self._advanced_frida_option_metadata(package_name, info)
        return FridaScriptOption(
            label=info.display_label,
            path=info.path,
            kind=self._advanced_frida_option_kind(info.name),
            source_kind=source_kind,
            display_name=info.name,
            summary=metadata.summary if metadata and metadata.summary else None,
            is_pinned=bool(metadata and metadata.pinned),
            last_used_at=metadata.last_used_at if metadata and metadata.last_used_at else None,
            tags=metadata.tags if metadata and metadata.tags else (),
        )

    def _advanced_frida_option_kind(self, script_name: str) -> str:
        spec = self._parameterized_template_spec_for_script(script_name)
        if spec is None:
            return "plain"
        return spec.kind

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

    def _advanced_frida_source_label(self, source_kind: str) -> str:
        if source_kind == "workspace":
            return ui_messages.ADVANCED_FRIDA_WORKSPACE_SOURCE
        if source_kind == "workspace_builtin_copy":
            return ui_messages.ADVANCED_FRIDA_WORKSPACE_COPY_SOURCE
        return ui_messages.ADVANCED_FRIDA_BUILTIN_SOURCE

    def _format_advanced_runtime_label(
        self,
        *,
        runtime_name: str,
        source_kind: str,
        summary: str | None,
    ) -> str:
        parts = [ui_messages.ADVANCED_FRIDA_PARAM_PREFIX, self._advanced_frida_source_label(source_kind)]
        prefix = "] [".join(parts)
        label = f"[{prefix}] {runtime_name}"
        if summary:
            label += f" ({summary})"
        return label

    def _advanced_frida_option_log_label(self, option: FridaScriptOption) -> str:
        return option.label

    def _preset_entry_display_fallback_metadata(self, package_name: str, entry: AdvancedLauncherPresetEntry):
        try:
            candidates = self._available_frida_script_options(package_name)
        except Exception:
            candidates = []
        entry_path = Path(entry.path)
        for option in candidates:
            try:
                if option.path.resolve() == entry_path.resolve():
                    return option
            except Exception:
                continue
        for option in candidates:
            if option.path.name.lower() == entry_path.name.lower():
                return option
        return None

    def _preset_entry_to_option(self, package_name: str, entry: AdvancedLauncherPresetEntry) -> FridaScriptOption | None:
        path = Path(entry.path)
        if not path.is_file():
            return None
        template_path = Path(entry.template_path) if entry.template_path else None
        fallback_option = self._preset_entry_display_fallback_metadata(package_name, entry)
        summary = entry.summary if entry.summary else (fallback_option.summary if fallback_option and fallback_option.summary else None)
        is_pinned = entry.is_pinned or bool(fallback_option and fallback_option.is_pinned)
        last_used_at = entry.last_used_at or (fallback_option.last_used_at if fallback_option and fallback_option.last_used_at else None)
        tags = entry.tags if entry.tags else (fallback_option.tags if fallback_option and fallback_option.tags else ())
        note = entry.note
        return FridaScriptOption(
            label=entry.label,
            path=path,
            kind=entry.kind,
            source_kind=entry.source_kind,
            display_name=entry.display_name,
            summary=summary,
            template_path=template_path,
            config_payload=entry.config_payload,
            runtime_key=entry.runtime_key,
            is_pinned=is_pinned,
            last_used_at=last_used_at,
            tags=tags,
            note=note,
            mode_strategy=entry.mode_strategy,
            auto_stop=entry.auto_stop,
        )

    def _option_to_preset_entry(self, option: FridaScriptOption) -> AdvancedLauncherPresetEntry:
        return AdvancedLauncherPresetEntry(
            label=option.label,
            path=str(option.path),
            kind=option.kind,
            source_kind=option.source_kind,
            display_name=option.display_name,
            summary=option.summary,
            template_path=str(option.template_path) if option.template_path is not None else None,
            config_payload=option.config_payload,
            runtime_key=option.runtime_key,
            is_pinned=option.is_pinned,
            last_used_at=option.last_used_at,
            tags=option.tags,
            note=option.note,
            mode_strategy=option.mode_strategy,
            auto_stop=option.auto_stop,
        )

    def _advanced_frida_item_strategy_log_message(self, selected_options: list[FridaScriptOption]) -> str | None:
        summarized: list[str] = []
        for option in selected_options:
            mode_strategy = str(option.mode_strategy or "inherit").strip().lower() or "inherit"
            auto_stop = "yes" if option.auto_stop else "no"
            summarized.append(
                f"{self._advanced_frida_option_log_label(option)}: mode={mode_strategy} auto_stop={auto_stop}"
            )
        if not summarized:
            return None
        return ui_messages.ADVANCED_FRIDA_ITEM_STRATEGY_LOG.format(strategies=" | ".join(summarized))

    def _advanced_frida_item_note_log_message(self, selected_options: list[FridaScriptOption]) -> str | None:
        noted = [
            f"{self._advanced_frida_option_log_label(option)}: {option.note.strip()}"
            for option in selected_options
            if str(option.note or '').strip()
        ]
        if not noted:
            return None
        return ui_messages.ADVANCED_FRIDA_ITEM_NOTE_LOG.format(notes=" | ".join(noted))

    def _advanced_frida_combined_note_log_message(
        self,
        selected_options: list[FridaScriptOption],
    ) -> str | None:
        lines: list[str] = []
        item_note_line = self._advanced_frida_item_note_log_message(selected_options)
        if item_note_line:
            lines.append(item_note_line)
        item_strategy_line = self._advanced_frida_item_strategy_log_message(selected_options)
        if item_strategy_line:
            lines.append(item_strategy_line)
        if not lines:
            return None
        return "\n".join(lines)

    def _load_advanced_launcher_preset_snapshot(self, package_name: str) -> AdvancedLauncherPresetSnapshot:
        try:
            snapshot = self.deps.workspace_service.load_advanced_launcher_preset_snapshot(package_name)
        except Exception as exc:
            self.append_log(f"[TOOL] 读取高级启动器预设失败：{package_name} -> {exc}")
            return AdvancedLauncherPresetSnapshot()
        options: list[FridaScriptOption] = []
        for entry in snapshot.entries:
            option = self._preset_entry_to_option(package_name, entry)
            if option is not None:
                options.append(option)
        return AdvancedLauncherPresetSnapshot(note=snapshot.note, entries=tuple(options))

    def _load_advanced_launcher_preset_options(self, package_name: str) -> list[FridaScriptOption]:
        try:
            entries = self.deps.workspace_service.load_advanced_launcher_presets(package_name)
        except Exception as exc:
            self.append_log(f"[TOOL] 读取高级启动器预设失败：{package_name} -> {exc}")
            return []
        options: list[FridaScriptOption] = []
        for entry in entries:
            option = self._preset_entry_to_option(package_name, entry)
            if option is not None:
                options.append(option)
        return options

    def _save_advanced_launcher_preset_options(
        self,
        package_name: str,
        selected_options: list[FridaScriptOption],
        *,
        note: str = "",
    ) -> None:
        try:
            entries = [self._option_to_preset_entry(option) for option in selected_options]
            self.deps.workspace_service.save_advanced_launcher_presets(package_name, entries, note=note)
        except Exception as exc:
            self.append_log(f"[TOOL] 保存高级启动器预设失败：{package_name} -> {exc}")

    def _normalize_hex_summary_value(self, value: str) -> str:
        normalized = (value or "").strip().lower()
        if normalized.startswith("0x"):
            return normalized
        return f"0x{normalized}"

    def _summarize_trace_init_proc_params(self, params: TraceInitProcParams) -> str:
        return (
            f"{params.target_so}, "
            f"{self._normalize_hex_summary_value(params.start_addr)}-"
            f"{self._normalize_hex_summary_value(params.end_addr)}"
        )

    def _resolve_advanced_frida_option(
        self,
        package_name: str,
        option: FridaScriptOption,
    ) -> FridaScriptOption | None:
        if option.kind == "plain":
            return option
        spec = self._parameterized_template_spec(option.kind)
        return self._resolved_parameterized_option_or_none(
            spec,
            package_name=package_name,
            template_option=option,
        )

    def _reconfigure_advanced_frida_option(
        self,
        package_name: str,
        option: FridaScriptOption,
    ) -> FridaScriptOption | None:
        if option.kind == "plain":
            return option
        spec = self._parameterized_template_spec(option.kind)
        return self._resolved_parameterized_option_or_none(
            spec,
            package_name=package_name,
            template_option=option,
            initial_payload=option.config_payload,
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
        package_name = self._prepare_hook_launch_context(
            require_idle_session=True,
            active_session_error=HookStartError(
                ui_messages.ADVANCED_FRIDA_ACTIVE_SESSION_BODY,
                severity="warning",
                dialog_title=ui_messages.ERROR_DIALOG_TITLE,
                next_step=ui_messages.ADVANCED_FRIDA_ACTIVE_SESSION_NEXT_STEP,
            ),
        )
        if not package_name:
            return

        script_name_or_path = script_name_or_path.strip()
        if not script_name_or_path:
            self._present_local_error(
                ScriptSelectionError(ui_messages.SCRIPT_NOT_SELECTED_BODY),
                mark_session_failed=False,
            )
            return

        try:
            script_path = Path(script_name_or_path)
            if not script_path.is_file():
                script_path = self.resolve_quick_script_path(package_name, script_name_or_path)
        except HookersError as exc:
            self._present_local_error(exc, mark_session_failed=False)
            return

        if not script_path.is_file():
            self._present_local_error(
                HookStartError(
                    ui_messages.SCRIPT_NOT_FOUND_BODY.format(value=script_name_or_path),
                    hint=ui_messages.SCRIPT_NOT_FOUND_HINT,
                    severity="warning",
                ),
                mark_session_failed=False,
            )
            return

        self._start_launch_request(
            LaunchRequest(
                package_name=package_name,
                script_path=script_path,
                use_spawn=use_spawn,
                busy_message=ui_messages.STARTING_HOOK,
                action_log=(
                    ui_messages.TERMINAL_SPAWN_ACTION_LOG.format(script_name=script_name_or_path)
                    if use_spawn
                    else ui_messages.TERMINAL_ATTACH_ACTION_LOG.format(script_name=script_name_or_path)
                ),
            )
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
            self._present_local_error(
                HookStartError(
                    ui_messages.HOOK_START_BUSY_BODY,
                    severity="warning",
                    dialog_title=ui_messages.ERROR_DIALOG_TITLE,
                    next_step=ui_messages.HOOK_START_BUSY_NEXT_STEP,
                ),
                mark_session_failed=False,
            )
            return

        package_name = self.selected_package_name()
        if not package_name:
            self._present_local_error(
                AppNotSelectedError(ui_messages.APP_NOT_SELECTED_BODY),
                mark_session_failed=False,
            )
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
        return self.deps.workspace_service.resolve_script_path(script_name, package_name)

    def resolve_builtin_quick_script_path(self, script_name: str) -> Path:
        builtin_script = self.deps.context.hookers_js_dir / script_name
        if builtin_script.is_file():
            return builtin_script

        raise HookStartError(
            ui_messages.BUILTIN_SCRIPT_NOT_FOUND_BODY.format(value=script_name),
            hint=ui_messages.BUILTIN_SCRIPT_NOT_FOUND_HINT,
        )

    def _log_launch_request(self, request: LaunchRequest) -> None:
        if request.action_log:
            self.append_log(request.action_log)
        if request.bundle_log_message:
            self.append_log(request.bundle_log_message)
        if request.order_log_message:
            self.append_log(request.order_log_message)
        self.append_log(ui_messages.TARGET_APP_LOG.format(package=request.package_name))
        if not request.skip_default_selected_script_log:
            self.append_log(
                ui_messages.SELECTED_SCRIPT_LOG.format(script_name=request.script_path.name)
            )
        if request.note_log_message:
            self.append_log(request.note_log_message)
        if request.script_log_path is not None:
            self.append_log(
                ui_messages.SELECTED_SCRIPT_LOG.format(script_name=request.script_log_path.name)
            )
        if request.mode_log_message:
            self.append_log(request.mode_log_message)

    def _script_usage_summary(self, script_path: Path) -> str | None:
        package_name = self.selected_package_name()
        if not package_name:
            return self._runtime_name_fallback_summary(script_path.name)
        try:
            infos = self.deps.workspace_service.list_script_sources(package_name)
        except Exception:
            return self._runtime_name_fallback_summary(script_path.name)

        matched_info = self._match_script_source_info_by_path(
            infos,
            script_path,
            allow_case_insensitive_path=True,
        )
        if matched_info is None:
            return self._runtime_name_fallback_summary(script_path.name)
        if matched_info.metadata and matched_info.metadata.summary:
            return matched_info.metadata.summary
        return self._fallback_script_usage_summary(matched_info)

    def _fallback_script_usage_summary(self, info: ScriptSourceInfo) -> str | None:
        if info.is_parameter_template and info.name.endswith(".runtime.js"):
            return self._runtime_name_fallback_summary(info.name)
        return None

    def _runtime_name_fallback_summary(self, script_name: str) -> str | None:
        normalized_name = script_name.strip()
        if not normalized_name.endswith(".runtime.js"):
            return None
        lowered = normalized_name.lower()
        if lowered.startswith("jni_method_trace"):
            return "参数化 JNI 方法跟踪 runtime"
        if lowered.startswith("trace_init_proc"):
            return "参数化 init_proc 跟踪 runtime"
        if lowered.startswith("frida_multi_bundle"):
            return "多脚本组合 runtime"
        return normalized_name

    def _match_script_source_info_by_path(
        self,
        infos: list[ScriptSourceInfo],
        script_path: Path,
        *,
        allow_case_insensitive_path: bool,
    ) -> ScriptSourceInfo | None:
        exact_match: ScriptSourceInfo | None = None
        case_insensitive_match: ScriptSourceInfo | None = None
        target_path_text = str(script_path).strip().lower()

        for info in infos:
            try:
                if info.path.resolve() == script_path.resolve():
                    exact_match = info
                    break
            except Exception:
                pass
            if not allow_case_insensitive_path or not target_path_text:
                continue
            info_path_text = str(info.path).strip().lower()
            if info_path_text and info_path_text == target_path_text and case_insensitive_match is None:
                case_insensitive_match = info
        return exact_match or case_insensitive_match

    def _mark_script_launch_requested(
        self,
        package_name: str,
        script_path: Path,
        *,
        mode: str,
        summary: str | None = None,
    ) -> None:
        source_kind = self._script_asset_source_kind(package_name, script_path)
        if source_kind not in {"workspace", "workspace_builtin_copy"}:
            return
        try:
            self.deps.workspace_service.mark_script_used(
                package_name,
                script_path.name,
                mode=mode,
                summary=summary,
            )
        except Exception as exc:
            self.append_log(f"[TOOL] 记录脚本最近使用失败：{script_path.name} -> {exc}")

    def _script_asset_source_kind(self, package_name: str, script_path: Path) -> str | None:
        try:
            matched_info = self._match_script_source_info_by_path(
                self.deps.workspace_service.list_script_sources(package_name),
                script_path,
                allow_case_insensitive_path=True,
            )
        except Exception:
            return None
        return matched_info.source_kind if matched_info is not None else None

    def _record_session_launch_request(
        self,
        request: LaunchRequest,
        *,
        mode: str,
        summary: str | None = None,
    ) -> None:
        resolved_source_kind = self._script_asset_source_kind(request.package_name, request.script_path)
        try:
            self.deps.workspace_service.append_session_record(
                SessionRecord(
                    timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
                    package_name=request.package_name,
                    script_name=request.script_path.name,
                    script_path=str(request.script_path),
                    mode=mode,
                    source_kind=resolved_source_kind,
                    summary=summary or "",
                )
            )
        except Exception as exc:
            self.append_log(f"[TOOL] 记录会话启动失败：{request.script_path.name} -> {exc}")

    def _start_hook_with_script_path(
        self,
        *,
        package_name: str,
        script_path: Path,
        use_spawn: bool,
        busy_message: str,
    ) -> None:
        self._start_launch_request(
            LaunchRequest(
                package_name=package_name,
                script_path=script_path,
                use_spawn=use_spawn,
                busy_message=busy_message,
            )
        )

    def _start_launch_request(self, request: LaunchRequest) -> None:
        self._log_launch_request(request)
        mode = "spawn" if request.use_spawn else "attach"
        summary = self._script_usage_summary(request.script_path)
        self._mark_script_launch_requested(
            request.package_name,
            request.script_path,
            mode=mode,
            summary=summary,
        )
        self._record_session_launch_request(
            request,
            mode=mode,
            summary=summary,
        )
        self._set_session_status_starting(
            mode=mode,
            package_name=request.package_name,
            script_name=request.script_path.name,
        )
        self.set_busy(True, request.busy_message)

        self.hook_thread = QThread(self.owner)
        self.hook_worker = HookWorker(
            device_service=self.deps.device_service,
            session_service=self.deps.session_service,
            workspace_service=self.deps.workspace_service,
            package_name=request.package_name,
            script_path=request.script_path,
            use_spawn=request.use_spawn,
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
        self._set_session_status_running(
            mode=mode,
            package_name=package_name,
            script_name=script_name,
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
            self._present_local_error(
                HookStartError(
                    ui_messages.RUNTIME_ACTION_BUSY_BODY,
                    severity="warning",
                    dialog_title=ui_messages.ERROR_DIALOG_TITLE,
                    next_step=ui_messages.RUNTIME_ACTION_BUSY_NEXT_STEP,
                ),
                mark_session_failed=False,
            )
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
                    ui_messages.STOP_HOOK_FAILED_BODY,
                    hint=ui_messages.STOP_HOOK_FAILED_HINT,
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
        self._set_session_status(
            SessionStatusSnapshot(
                phase=ui_messages.SESSION_STATUS_PHASE_STOPPED,
                detail=ui_messages.SESSION_STATUS_STOPPED_DETAIL,
            )
        )
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
        self._set_session_status(
            SessionStatusSnapshot(
                phase=ui_messages.SESSION_STATUS_PHASE_STOPPED,
                detail=ui_messages.SESSION_STATUS_STOPPED_DETAIL,
            )
        )
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
                    ui_messages.STOP_FRIDA_SERVER_FAILED_BODY,
                    hint=ui_messages.STOP_FRIDA_SERVER_FAILED_HINT,
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
        self._set_session_status_idle()
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
                    ui_messages.RESTART_APP_FAILED_BODY,
                    hint=ui_messages.RESTART_APP_FAILED_HINT,
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
        self._set_session_status(
            SessionStatusSnapshot(
                phase=ui_messages.SESSION_STATUS_PHASE_STOPPED,
                package_name=package_name,
                detail=ui_messages.SESSION_STATUS_STOPPED_DETAIL,
            )
        )
