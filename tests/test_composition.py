from __future__ import annotations

import types

import pytest

from ui.composition import MainWindowControllers
from ui.composition import build_main_window_controllers, wire_main_window_controller_signals
from ui.main_window import MainWindow, MainWindowDependencies
from ui.quick_hook_actions import QUICK_HOOK_ACTIONS


def build_main_window(dummy_deps):
    deps = MainWindowDependencies(
        device_service=dummy_deps.device_service,
        session_service=dummy_deps.session_service,
        workspace_service=dummy_deps.workspace_service,
        rpc_service=dummy_deps.rpc_service,
        apk_scan_service=dummy_deps.apk_scan_service,
        context=dummy_deps.context,
    )
    return MainWindow(deps)


def test_main_window_builds_controller_bundle(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    assert isinstance(window.controllers, MainWindowControllers)
    assert window.controllers.log_panel is window.log_panel_controller
    assert window.controllers.error_presenter is window.error_presenter
    assert window.controllers.app_workflow is window.app_workflow_controller
    assert window.controllers.hook_runtime is window.hook_runtime_controller
    assert window.controllers.rpc_tools is window.rpc_tool_controller
    assert window.controllers.apk_scan is window.apk_scan_controller
    assert window.controllers.terminal_console is window.terminal_console_controller
    window.deleteLater()


def test_composition_injects_presenter_and_cross_controller_bridges(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    assert window.app_workflow_controller.show_worker_error.__self__ is window.error_presenter
    assert window.hook_runtime_controller.show_worker_error.__self__ is window.error_presenter
    assert window.rpc_tool_controller.show_worker_error.__self__ is window.error_presenter
    assert window.apk_scan_controller.show_worker_error.__self__ is window.error_presenter
    assert window.hook_runtime_controller.selected_package_name.__self__ is window.app_workflow_controller
    assert window.hook_runtime_controller.ensure_current_app_ready.__self__ is window.app_workflow_controller
    assert window.hook_runtime_controller.refresh_app_status_panel.__self__ is window.app_workflow_controller
    assert window.hook_runtime_controller.apply_apps_payload.__self__ is window.app_workflow_controller
    assert window.rpc_tool_controller.ensure_current_app_ready.__self__ is window.app_workflow_controller
    assert window.terminal_console_controller.ensure_current_app_ready.__self__ is window.app_workflow_controller
    window.deleteLater()


def test_build_main_window_controllers_raises_clear_error_for_missing_window_attrs(
    dummy_deps,
) -> None:
    incomplete_window = types.SimpleNamespace()

    with pytest.raises(AttributeError) as exc_info:
        build_main_window_controllers(incomplete_window, dummy_deps)

    assert "MainWindow 缺少 composition 所需属性" in str(exc_info.value)
    assert "log_console" in str(exc_info.value)
    assert "set_busy" in str(exc_info.value)


class _FakeSignal:
    def __init__(self) -> None:
        self.connected = []

    def connect(self, callback) -> None:
        self.connected.append(callback)


class _FakeButton:
    def __init__(self) -> None:
        self.clicked = _FakeSignal()


class _FakeCombo:
    def __init__(self) -> None:
        self.currentIndexChanged = _FakeSignal()


class _FakeLineEdit:
    def __init__(self) -> None:
        self.textChanged = _FakeSignal()
        self.returnPressed = _FakeSignal()


class _FakeCheckbox:
    def __init__(self) -> None:
        self.toggled = _FakeSignal()


def _build_fake_window_for_wiring():
    window = types.SimpleNamespace(
        log_emitted=_FakeSignal(),
        session_event_emitted=_FakeSignal(),
        log_filter_combo=_FakeCombo(),
        choose_log_file_button=_FakeButton(),
        clear_log_button=_FakeButton(),
        log_search_input=_FakeLineEdit(),
        prev_log_match_button=_FakeButton(),
        next_log_match_button=_FakeButton(),
        clear_log_search_button=_FakeButton(),
        log_search_case_checkbox=_FakeCheckbox(),
        log_search_regex_checkbox=_FakeCheckbox(),
        log_search_matches_only_checkbox=_FakeCheckbox(),
        refresh_apps_button=_FakeButton(),
        app_combo=_FakeCombo(),
        prepare_workspace_button=_FakeButton(),
        start_hook_button=_FakeButton(),
        spawn_mode_radio=types.SimpleNamespace(isChecked=lambda: True),
        stop_hook_button=_FakeButton(),
        stop_frida_server_button=_FakeButton(),
        restart_app_button=_FakeButton(),
        generate_hook_button=_FakeButton(),
        advanced_frida_launch_button=_FakeButton(),
        view_activity_button=_FakeButton(),
        view_service_button=_FakeButton(),
        object_info_button=_FakeButton(),
        object_explain_button=_FakeButton(),
        view_info_button=_FakeButton(),
        select_apk_scan_button=_FakeButton(),
        start_apk_scan_button=_FakeButton(),
        terminal_cli_mode_button=_FakeButton(),
    )
    for action in QUICK_HOOK_ACTIONS:
        setattr(window, action.button_attr, _FakeButton())
    return window


def _build_fake_controllers():
    return MainWindowControllers(
        log_panel=types.SimpleNamespace(
            append_log=lambda *args, **kwargs: None,
            on_log_view_controls_changed=lambda *args, **kwargs: None,
            choose_log_file=lambda *args, **kwargs: None,
            clear_logs=lambda *args, **kwargs: None,
            on_log_search_changed=lambda *args, **kwargs: None,
            find_next_log_match=lambda *args, **kwargs: None,
            find_previous_log_match=lambda *args, **kwargs: None,
            clear_log_search=lambda *args, **kwargs: None,
        ),
        error_presenter=types.SimpleNamespace(present=lambda *args, **kwargs: None),
        app_workflow=types.SimpleNamespace(
            start_device_prepare=lambda *args, **kwargs: None,
            on_package_changed=lambda *args, **kwargs: None,
            prepare_selected_workspace=lambda *args, **kwargs: None,
        ),
        hook_runtime=types.SimpleNamespace(
            handle_session_event=lambda *args, **kwargs: None,
            start_hook=lambda *args, **kwargs: None,
            stop_hook=lambda *args, **kwargs: None,
            stop_frida_server=lambda *args, **kwargs: None,
            restart_current_app=lambda *args, **kwargs: None,
            start_advanced_frida_launcher=lambda *args, **kwargs: None,
            start_trace_init_proc=lambda *args, **kwargs: None,
            start_quick_hook=lambda *args, **kwargs: None,
        ),
        rpc_tools=types.SimpleNamespace(
            generate_hook_script=lambda *args, **kwargs: None,
            show_activities=lambda *args, **kwargs: None,
            show_services=lambda *args, **kwargs: None,
            show_object_info=lambda *args, **kwargs: None,
            show_object_explain=lambda *args, **kwargs: None,
            show_view_info=lambda *args, **kwargs: None,
        ),
        apk_scan=types.SimpleNamespace(
            choose_apk_for_scan=lambda *args, **kwargs: None,
            start_apk_scan=lambda *args, **kwargs: None,
        ),
        terminal_console=types.SimpleNamespace(
            update_prompt=lambda *args, **kwargs: None,
            toggle_cli_mode=lambda *args, **kwargs: None,
        ),
    )


def test_wire_main_window_controller_signals_is_idempotent() -> None:
    window = _build_fake_window_for_wiring()
    controllers = _build_fake_controllers()
    tracked_signals = [
        window.log_emitted,
        window.session_event_emitted,
        window.log_filter_combo.currentIndexChanged,
        window.choose_log_file_button.clicked,
        window.clear_log_button.clicked,
        window.log_search_input.textChanged,
        window.log_search_input.returnPressed,
        window.prev_log_match_button.clicked,
        window.next_log_match_button.clicked,
        window.clear_log_search_button.clicked,
        window.log_search_case_checkbox.toggled,
        window.log_search_regex_checkbox.toggled,
        window.log_search_matches_only_checkbox.toggled,
        window.refresh_apps_button.clicked,
        window.app_combo.currentIndexChanged,
        window.prepare_workspace_button.clicked,
        window.terminal_cli_mode_button.clicked,
        window.start_hook_button.clicked,
        window.stop_hook_button.clicked,
        window.stop_frida_server_button.clicked,
        window.restart_app_button.clicked,
        window.generate_hook_button.clicked,
        window.advanced_frida_launch_button.clicked,
        window.view_activity_button.clicked,
        window.view_service_button.clicked,
        *[getattr(window, action.button_attr).clicked for action in QUICK_HOOK_ACTIONS],
        window.object_info_button.clicked,
        window.object_explain_button.clicked,
        window.view_info_button.clicked,
        window.select_apk_scan_button.clicked,
        window.start_apk_scan_button.clicked,
    ]

    wire_main_window_controller_signals(window, controllers)
    first_counts = [len(signal.connected) for signal in tracked_signals]

    wire_main_window_controller_signals(window, controllers)
    second_counts = [len(signal.connected) for signal in tracked_signals]

    assert getattr(window, "_controllers_wired", False) is True
    assert first_counts == second_counts
