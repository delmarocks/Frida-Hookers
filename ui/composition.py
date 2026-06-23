from __future__ import annotations

from dataclasses import dataclass
from PySide6.QtCore import QObject

from .apk_scan import ApkScanController, ApkScanWidgets
from .app_workflow import AppWorkflowController, AppWorkflowWidgets
from .error_presenter import ErrorPresentationContext, ErrorPresenterController
from .hook_runtime import HookRuntimeController, HookRuntimeWidgets
from .log_panel import LogPanelController, LogPanelWidgets
from .quick_hook_actions import (
    ANALYSIS_SCENARIO_BUTTON_ATTRS,
    ANALYSIS_SCENARIO_PROFILES,
    QUICK_HOOK_ACTIONS,
    QUICK_HOOK_BUTTON_ATTRS,
)
from .rpc_tools import RpcToolController, RpcToolWidgets
from .terminal_console import TerminalConsoleController, TerminalConsoleWidgets
from .ui_thread_dispatcher import UiThreadDispatcher

_BUILD_REQUIRED_WINDOW_ATTRS = (
    "status_bar",
    "set_busy",
    "set_status_text",
    "selected_script_path",
    "apply_script_root",
    "shorten_path",
    "log_console",
    "log_filter_combo",
    "log_search_input",
    "log_search_status_label",
    "prev_log_match_button",
    "next_log_match_button",
    "log_search_case_checkbox",
    "log_search_regex_checkbox",
    "log_search_matches_only_checkbox",
    "choose_log_file_button",
    "clear_log_button",
    "clear_log_search_button",
    "app_combo",
    "refresh_apps_button",
    "prepare_workspace_button",
    "workspace_path_input",
    "left_pid_uid_status_value",
    "left_version_mode_status_value",
    "current_state_label",
    "start_hook_button",
    "stop_hook_button",
    "stop_frida_server_button",
    "restart_app_button",
    "spawn_mode_radio",
    "hook_target_input",
    "inspect_target_input",
    "script_combo",
    "generate_hook_button",
    "advanced_frida_launch_button",
    "view_activity_button",
    "view_service_button",
    *QUICK_HOOK_BUTTON_ATTRS,
    *ANALYSIS_SCENARIO_BUTTON_ATTRS,
    "object_info_button",
    "object_explain_button",
    "view_info_button",
    "apk_scan_path_input",
    "apk_scan_status_label",
    "select_apk_scan_button",
    "start_apk_scan_button",
    "terminal_cli_mode_button",
)

_WIRE_REQUIRED_WINDOW_ATTRS = (
    "log_emitted",
    "session_event_emitted",
    "choose_log_file_button",
    "clear_log_button",
    "clear_log_search_button",
    "log_filter_combo",
    "log_search_input",
    "prev_log_match_button",
    "next_log_match_button",
    "log_search_case_checkbox",
    "log_search_regex_checkbox",
    "log_search_matches_only_checkbox",
    "refresh_apps_button",
    "app_combo",
    "prepare_workspace_button",
    "start_hook_button",
    "spawn_mode_radio",
    "stop_hook_button",
    "stop_frida_server_button",
    "restart_app_button",
    "generate_hook_button",
    "advanced_frida_launch_button",
    "view_activity_button",
    "view_service_button",
    *QUICK_HOOK_BUTTON_ATTRS,
    *ANALYSIS_SCENARIO_BUTTON_ATTRS,
    "object_info_button",
    "object_explain_button",
    "view_info_button",
    "select_apk_scan_button",
    "start_apk_scan_button",
    "terminal_cli_mode_button",
)


def _assert_window_attrs(window, required_names: tuple[str, ...]) -> None:
    missing = [name for name in required_names if not hasattr(window, name)]
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise AttributeError(
            "MainWindow 缺少 composition 所需属性: "
            f"{missing_list}. 请确保先完成 _build_ui()，且未破坏既有控件/ helper 命名。"
        )


@dataclass(slots=True)
class MainWindowControllers:
    log_panel: LogPanelController
    error_presenter: ErrorPresenterController
    app_workflow: AppWorkflowController
    hook_runtime: HookRuntimeController
    rpc_tools: RpcToolController
    apk_scan: ApkScanController
    terminal_console: TerminalConsoleController


def build_main_window_controllers(window, deps) -> MainWindowControllers:
    _assert_window_attrs(window, _BUILD_REQUIRED_WINDOW_ATTRS)
    log_panel = LogPanelController(
        owner=window,
        widgets=LogPanelWidgets(
            log_console=window.log_console,
            log_filter_combo=window.log_filter_combo,
            log_search_input=window.log_search_input,
            log_search_status_label=window.log_search_status_label,
            prev_log_match_button=window.prev_log_match_button,
            next_log_match_button=window.next_log_match_button,
            log_search_case_checkbox=window.log_search_case_checkbox,
            log_search_regex_checkbox=window.log_search_regex_checkbox,
            log_search_matches_only_checkbox=window.log_search_matches_only_checkbox,
            choose_log_file_button=window.choose_log_file_button,
        ),
        status_bar=window.status_bar,
        project_root=deps.context.project_root,
        selected_package_name=lambda: window.app_combo.currentData(),
        selected_script_path=window.selected_script_path,
    )
    error_presenter = ErrorPresenterController(
        ErrorPresentationContext(
            owner=window,
            status_setter=window.set_status_text,
            busy_setter=window.set_busy,
            append_log=log_panel.append_log,
            focus_target=window.focus_error_target,
            update_recovery_banner=window.update_error_recovery_banner,
        )
    )
    app_workflow = AppWorkflowController(
        owner=window,
        widgets=AppWorkflowWidgets(
            app_combo=window.app_combo,
            prepare_workspace_button=window.prepare_workspace_button,
            workspace_path_input=window.workspace_path_input,
            left_pid_uid_status_value=window.left_pid_uid_status_value,
            left_version_mode_status_value=window.left_version_mode_status_value,
            current_state_label=window.current_state_label,
        ),
        deps=deps,
        set_busy=window.set_busy,
        set_status_text=window.set_status_text,
        append_log=log_panel.append_log,
        show_worker_error=error_presenter.present,
        apply_script_root=window.apply_script_root,
    )
    hook_runtime = HookRuntimeController(
        owner=window,
        widgets=HookRuntimeWidgets(
            start_hook_button=window.start_hook_button,
            stop_hook_button=window.stop_hook_button,
            current_state_label=window.current_state_label,
            app_combo=window.app_combo,
            set_session_status=lambda phase, mode=None, package=None, script=None, detail=None: window.set_session_status(
                phase=phase,
                mode=mode,
                package=package,
                script=script,
                detail=detail,
            ),
        ),
        deps=deps,
        set_busy=window.set_busy,
        set_status_text=window.set_status_text,
        append_log=log_panel.append_log,
        show_worker_error=error_presenter.present,
        selected_package_name=app_workflow.selected_package_name,
        selected_script_path=window.selected_script_path,
        ensure_current_app_ready=app_workflow.ensure_current_app_ready,
        refresh_app_status_panel=app_workflow.refresh_app_status_panel,
        apply_apps_payload=app_workflow.apply_apps_payload_silent,
    )
    rpc_tools = RpcToolController(
        owner=window,
        widgets=RpcToolWidgets(
            hook_target_input=window.hook_target_input,
            inspect_target_input=window.inspect_target_input,
            script_combo=window.script_combo,
        ),
        deps=deps,
        set_busy=window.set_busy,
        set_status_text=window.set_status_text,
        append_log=log_panel.append_log,
        show_worker_error=error_presenter.present,
        ensure_current_app_ready=app_workflow.ensure_current_app_ready,
        apply_script_root=window.apply_script_root,
    )
    apk_scan = ApkScanController(
        owner=window,
        widgets=ApkScanWidgets(
            apk_scan_path_input=window.apk_scan_path_input,
            apk_scan_status_label=window.apk_scan_status_label,
            select_apk_scan_button=window.select_apk_scan_button,
            start_apk_scan_button=window.start_apk_scan_button,
        ),
        deps=deps,
        set_busy=window.set_busy,
        set_status_text=window.set_status_text,
        append_log=log_panel.append_log,
        show_worker_error=error_presenter.present,
        shorten_path=window.shorten_path,
    )
    terminal_console = TerminalConsoleController(
        owner=window,
        widgets=TerminalConsoleWidgets(
            terminal_view=window.log_console,
            terminal_cli_mode_button=window.terminal_cli_mode_button,
            app_combo=window.app_combo,
        ),
        deps=deps,
        set_busy=window.set_busy,
        set_status_text=window.set_status_text,
        append_log=log_panel.append_log,
        show_worker_error=error_presenter.present,
        ensure_current_app_ready=app_workflow.ensure_current_app_ready,
        selected_package_name=app_workflow.selected_package_name,
        apply_apps_payload=app_workflow.apply_apps_payload_silent,
        apply_script_root=window.apply_script_root,
        hook_runtime=hook_runtime,
    )
    return MainWindowControllers(
        log_panel=log_panel,
        error_presenter=error_presenter,
        app_workflow=app_workflow,
        hook_runtime=hook_runtime,
        rpc_tools=rpc_tools,
        apk_scan=apk_scan,
        terminal_console=terminal_console,
    )


def wire_main_window_controller_signals(window, controllers: MainWindowControllers) -> None:
    if getattr(window, "_controllers_wired", False):
        return
    _assert_window_attrs(window, _WIRE_REQUIRED_WINDOW_ATTRS)
    dispatcher = getattr(window, "_main_thread_dispatcher", None)
    if dispatcher is None:
        dispatcher = UiThreadDispatcher(window if isinstance(window, QObject) else None)
        window._main_thread_dispatcher = dispatcher

    window.log_emitted.connect(
        lambda message: dispatcher.submit(controllers.log_panel.append_log, message)
    )
    window.session_event_emitted.connect(
        lambda event_type, payload: dispatcher.submit(
            controllers.hook_runtime.handle_session_event,
            event_type,
            payload,
        )
    )

    window.log_filter_combo.currentIndexChanged.connect(
        controllers.log_panel.on_log_view_controls_changed
    )
    window.choose_log_file_button.clicked.connect(controllers.log_panel.choose_log_file)
    window.clear_log_button.clicked.connect(controllers.log_panel.clear_logs)
    window.log_search_input.textChanged.connect(controllers.log_panel.on_log_search_changed)
    window.log_search_input.returnPressed.connect(controllers.log_panel.find_next_log_match)
    window.prev_log_match_button.clicked.connect(controllers.log_panel.find_previous_log_match)
    window.next_log_match_button.clicked.connect(controllers.log_panel.find_next_log_match)
    window.clear_log_search_button.clicked.connect(controllers.log_panel.clear_log_search)
    window.log_search_case_checkbox.toggled.connect(controllers.log_panel.on_log_search_changed)
    window.log_search_regex_checkbox.toggled.connect(controllers.log_panel.on_log_search_changed)
    window.log_search_matches_only_checkbox.toggled.connect(
        controllers.log_panel.on_log_search_changed
    )

    window.refresh_apps_button.clicked.connect(controllers.app_workflow.start_device_prepare)
    window.app_combo.currentIndexChanged.connect(controllers.app_workflow.on_package_changed)
    window.app_combo.currentIndexChanged.connect(controllers.terminal_console.update_prompt)
    window.prepare_workspace_button.clicked.connect(
        controllers.app_workflow.prepare_selected_workspace
    )

    window.start_hook_button.clicked.connect(
        lambda: controllers.hook_runtime.start_hook(window.spawn_mode_radio.isChecked())
    )
    window.stop_hook_button.clicked.connect(controllers.hook_runtime.stop_hook)
    window.stop_frida_server_button.clicked.connect(controllers.hook_runtime.stop_frida_server)
    window.restart_app_button.clicked.connect(controllers.hook_runtime.restart_current_app)

    window.generate_hook_button.clicked.connect(controllers.rpc_tools.generate_hook_script)
    window.advanced_frida_launch_button.clicked.connect(
        lambda: controllers.hook_runtime.start_advanced_frida_launcher(
            window.spawn_mode_radio.isChecked()
        )
    )
    window.view_activity_button.clicked.connect(controllers.rpc_tools.show_activities)
    window.view_service_button.clicked.connect(controllers.rpc_tools.show_services)
    for action in QUICK_HOOK_ACTIONS:
        if action.key == "jni_method_trace":
            getattr(window, action.button_attr).clicked.connect(
                lambda: controllers.hook_runtime.start_jni_method_trace(
                    window.spawn_mode_radio.isChecked()
                )
            )
            continue
        if action.key == "trace_init_proc":
            getattr(window, action.button_attr).clicked.connect(
                lambda: controllers.hook_runtime.start_trace_init_proc(
                    window.spawn_mode_radio.isChecked()
                )
            )
            continue
        getattr(window, action.button_attr).clicked.connect(
            lambda action_key=action.key: controllers.hook_runtime.start_quick_hook(
                action_key,
                window.spawn_mode_radio.isChecked(),
            )
        )
    for profile in ANALYSIS_SCENARIO_PROFILES:
        getattr(window, profile.button_attr).clicked.connect(
            lambda _checked=False, profile_key=profile.key: controllers.hook_runtime.start_analysis_scenario(
                profile_key,
                window.spawn_mode_radio.isChecked(),
            )
        )
    window.object_info_button.clicked.connect(controllers.rpc_tools.show_object_info)
    window.object_explain_button.clicked.connect(controllers.rpc_tools.show_object_explain)
    window.view_info_button.clicked.connect(controllers.rpc_tools.show_view_info)

    window.select_apk_scan_button.clicked.connect(controllers.apk_scan.choose_apk_for_scan)
    window.start_apk_scan_button.clicked.connect(controllers.apk_scan.start_apk_scan)
    window.terminal_cli_mode_button.clicked.connect(controllers.terminal_console.toggle_cli_mode)
    window._controllers_wired = True
