from __future__ import annotations

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QLabel
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt

from ui import ui_messages
from ui.main_window import MainWindow, MainWindowDependencies
from ui.quick_hook_actions import ANALYSIS_SCENARIO_PROFILES, QUICK_HOOK_ACTIONS, QUICK_HOOK_GROUPS


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


def test_set_status_text_updates_label_and_status_bar(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    window.set_status_text("测试状态", "状态栏提示")
    assert window.current_state_label.text() == ui_messages.state_text("测试状态")
    assert window.statusBar().currentMessage() == "状态栏提示"
    window.deleteLater()


def test_toggle_log_focus_mode_switches_button_text_and_message(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    window.toggle_log_focus_mode()
    assert window.log_focus_mode is True
    assert window.toggle_log_focus_button.text() == ui_messages.FOCUS_LOG_DISABLE_BUTTON
    assert window.statusBar().currentMessage() == ui_messages.FOCUS_LOG_ENABLED

    window.toggle_log_focus_mode()
    assert window.log_focus_mode is False
    assert window.toggle_log_focus_button.text() == ui_messages.FOCUS_LOG_ENABLE_BUTTON
    assert window.statusBar().currentMessage() == ui_messages.FOCUS_LOG_DISABLED
    window.deleteLater()


def test_shorten_path_keeps_short_paths_and_ellipsizes_long_ones(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    short = window.shorten_path(dummy_deps.context.project_root / "demo")
    assert short.endswith("demo")
    long_path = dummy_deps.context.project_root / ("a" * 80)
    shortened = window.shorten_path(long_path, keep=5)
    assert "..." in shortened
    window.deleteLater()


def test_main_window_builds_error_presenter_and_injects_it_into_controllers(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    assert window.controllers is not None
    assert window.error_presenter is not None
    assert window.app_workflow_controller.show_worker_error.__self__ is window.error_presenter
    assert window.hook_runtime_controller.show_worker_error.__self__ is window.error_presenter
    assert window.rpc_tool_controller.show_worker_error.__self__ is window.error_presenter
    assert window.apk_scan_controller.show_worker_error.__self__ is window.error_presenter
    assert window.terminal_console_controller.show_worker_error.__self__ is window.error_presenter
    window.deleteLater()


def test_main_window_builds_quick_hook_buttons(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    for action in QUICK_HOOK_ACTIONS:
        button = getattr(window, action.button_attr)
        assert button.text() == action.button_label
        assert button.toolTip() == action.tooltip
    window.deleteLater()


def test_main_window_builds_analysis_scenario_buttons(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    labels = []
    for profile in ANALYSIS_SCENARIO_PROFILES:
        button = getattr(window, profile.button_attr)
        labels.append(button.text())
        assert button.text() == profile.button_label
        assert profile.description in button.toolTip()
        assert profile.mode_hint in button.toolTip()
    assert labels == [profile.button_label for profile in ANALYSIS_SCENARIO_PROFILES]
    window.deleteLater()

def test_display_builder_builds_analysis_scenario_log_text() -> None:
    from ui.display_builders import build_analysis_scenario_log_text

    text = build_analysis_scenario_log_text(ANALYSIS_SCENARIO_PROFILES[0])

    assert ui_messages.ANALYSIS_SCENARIO_SUMMARY_LOG_TITLE in text
    assert ANALYSIS_SCENARIO_PROFILES[0].title in text
    assert ANALYSIS_SCENARIO_PROFILES[0].description in text


def test_main_window_mode_badge_tracks_radio_selection(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    assert window.mode_badge_label.text() == ui_messages.ATTACH_MODE_BADGE

    window.spawn_mode_radio.setChecked(True)
    assert window.mode_badge_label.text() == ui_messages.SPAWN_MODE_BADGE

    window.attach_mode_radio.setChecked(True)
    assert window.mode_badge_label.text() == ui_messages.ATTACH_MODE_BADGE
    window.deleteLater()


def test_main_window_builds_quick_hook_groups(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    assert window.quick_hook_group_titles == [group.title for group in QUICK_HOOK_GROUPS]

    labels = {
        label.text()
        for label in window.findChildren(QLabel)
        if label.objectName() == "sectionCaption"
    }
    for group in QUICK_HOOK_GROUPS:
        assert group.title in labels
        group_widget = window.quick_hook_group_widgets[group.key]
        assert group_widget.objectName() == f"quickHookGroup_{group.key}"
        for action_key in group.action_keys:
            action = next(item for item in QUICK_HOOK_ACTIONS if item.key == action_key)
            assert getattr(window, action.button_attr).parent() is group_widget
    window.deleteLater()


def test_main_window_builds_session_status_bar(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    assert window.session_status_phase_label.text() == ui_messages.SESSION_STATUS_PHASE_IDLE
    assert window.session_status_phase_label.objectName() == "sessionStatusBadgeIdle"
    assert window.session_status_summary_label.text() == ui_messages.SESSION_STATUS_SUMMARY_TEMPLATE.format(
        summary=ui_messages.SESSION_STATUS_SUMMARY_IDLE
    )
    assert window.session_status_action_label.text() == ui_messages.SESSION_STATUS_ACTION_IDLE
    assert window.session_status_detail_label.text() == ui_messages.SESSION_STATUS_DETAIL.format(detail=ui_messages.SESSION_STATUS_STOPPED_DETAIL)
    window.set_session_status(
        phase=ui_messages.SESSION_STATUS_PHASE_RUNNING,
        mode="attach",
        package="pkg.demo",
        script="demo.js",
        detail="已进入会话",
    )
    assert window.session_status_phase_label.objectName() == "sessionStatusBadgeRunning"
    assert window.session_status_summary_label.text() == ui_messages.SESSION_STATUS_SUMMARY_TEMPLATE.format(
        summary=ui_messages.SESSION_STATUS_SUMMARY_RUNNING
    )
    assert window.session_status_action_label.text() == ui_messages.SESSION_STATUS_ACTION_RUNNING
    assert window.session_status_mode_label.text() == ui_messages.SESSION_STATUS_MODE.format(mode="attach")
    assert window.session_status_target_label.text() == ui_messages.SESSION_STATUS_TARGET.format(package="pkg.demo")
    assert window.session_status_script_label.text() == ui_messages.SESSION_STATUS_SCRIPT.format(script="demo.js")
    assert window.session_status_detail_label.text() == ui_messages.SESSION_STATUS_DETAIL.format(detail="已进入会话")
    window.deleteLater()


def test_main_window_builds_terminal_widgets(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    assert window.terminal_cli_mode_button.text() == ui_messages.CLI_MODE_ENTER_BUTTON
    assert window.log_console.cli_mode_enabled() is False
    assert window.advanced_frida_launch_button.text() == f"3A. {ui_messages.ADVANCED_FRIDA_BUTTON}"
    window.deleteLater()


def test_main_window_collapses_debug_tools_into_dialog(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    # 主面板只保留一个入口按钮
    assert window.debug_tools_button.text() == "调试与分析工具"
    # 调试工具控件已收纳进弹窗：其顶层窗口是对话框，而非主窗口
    assert window.view_activity_button.window() is window.debug_tools_dialog
    assert window.object_info_button.window() is window.debug_tools_dialog
    assert window.inspect_target_input.window() is window.debug_tools_dialog
    assert window.restart_app_button.window() is window.debug_tools_dialog
    # 入口按钮本身仍在主窗口上
    assert window.debug_tools_button.window() is window
    # 点击入口会显示弹窗
    window._open_debug_tools_dialog()
    assert window.debug_tools_dialog.isVisible() is True
    window.debug_tools_dialog.close()
    window.deleteLater()


def test_main_window_set_busy_disables_debug_tools_dialog_buttons(qapp, dummy_deps) -> None:
    # 容器迁移后，弹窗内按钮的引用仍挂在主窗口上，set_busy 必须能同步禁用它们，
    # 否则注入执行期间用户仍可在弹窗里触发动作。这里固化这条 busy 同步逻辑。
    window = build_main_window(dummy_deps)
    assert window.view_activity_button.isEnabled() is True
    assert window.object_info_button.isEnabled() is True

    window.set_busy(True)
    assert window.view_activity_button.isEnabled() is False
    assert window.object_info_button.isEnabled() is False
    assert window.view_info_button.isEnabled() is False
    assert window.restart_app_button.isEnabled() is False

    window.set_busy(False)
    assert window.view_activity_button.isEnabled() is True
    assert window.object_info_button.isEnabled() is True
    window.deleteLater()


def test_refresh_script_list_shows_prefixed_workspace_builtin_scripts(qapp, dummy_deps, tmp_path) -> None:
    window = build_main_window(dummy_deps)
    workspace_script_dir = tmp_path / "workspaces" / "pkg.demo" / "js"
    workspace_script_dir.mkdir(parents=True, exist_ok=True)
    prefixed_builtin = workspace_script_dir / "内置-detect_network_stack.js"
    prefixed_builtin.write_text("// builtin", encoding="utf-8")

    window.apply_script_root(workspace_script_dir)

    labels = [window.script_combo.itemText(index) for index in range(window.script_combo.count())]
    assert "内置-detect_network_stack.js" in labels
    window.deleteLater()


def test_terminal_history_uses_up_down_keys(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    dummy_deps.context.current_app = dummy_deps.device_service.ensure_result
    window.app_combo.addItem("App", dummy_deps.device_service.ensure_result.identifier)
    window.app_combo.setCurrentIndex(0)
    window.terminal_console_controller.set_cli_mode_enabled(True)
    window.terminal_console_controller.submit_command("help")
    window.terminal_console_controller.submit_command("pid")

    QTest.keyClick(window.log_console, Qt.Key.Key_Up)
    assert window.log_console.current_input_text() == "pid"
    QTest.keyClick(window.log_console, Qt.Key.Key_Up)
    assert window.log_console.current_input_text() == "help"
    QTest.keyClick(window.log_console, Qt.Key.Key_Down)
    assert window.log_console.current_input_text() == "pid"
    QTest.keyClick(window.log_console, Qt.Key.Key_Down)
    assert window.log_console.current_input_text() == ""
    window.deleteLater()


def test_terminal_cli_mode_button_toggles_embedded_terminal_input(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    assert window.log_console.cli_mode_enabled() is False

    window.terminal_cli_mode_button.click()
    assert window.log_console.cli_mode_enabled() is True
    assert window.terminal_cli_mode_button.text() == ui_messages.CLI_MODE_EXIT_BUTTON

    window.terminal_cli_mode_button.click()
    assert window.log_console.cli_mode_enabled() is False
    assert window.terminal_cli_mode_button.text() == ui_messages.CLI_MODE_ENTER_BUTTON
    window.deleteLater()


def test_advanced_frida_button_disables_with_active_session(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)

    dummy_deps.context.active_session = type("Session", (), {"mode": "attach"})()
    window.set_busy(False)
    assert window.advanced_frida_launch_button.isEnabled() is False

    dummy_deps.context.active_session = None
    window.set_busy(False)
    assert window.advanced_frida_launch_button.isEnabled() is True
    window.deleteLater()


def test_terminal_input_does_not_delete_or_replace_prompt_or_history(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    window.terminal_console_controller.set_cli_mode_enabled(True)
    window.terminal_console_controller.submit_command("help")
    window.log_panel_controller.render_logs()

    prompt_start = window.log_console.prompt_start_position()
    cursor = window.log_console.textCursor()
    cursor.setPosition(prompt_start)
    window.log_console.setTextCursor(cursor)
    QTest.keyClick(window.log_console, Qt.Key.Key_Backspace)
    assert window.log_console.current_input_text() == ""

    cursor = window.log_console.textCursor()
    cursor.select(QTextCursor.SelectionType.Document)
    window.log_console.setTextCursor(cursor)
    QTest.keyClicks(window.log_console, "pid")
    assert window.log_console.current_input_text() == "pid"
    transcript = window.log_console.toPlainText()
    assert "[CMD] hooker > help" in transcript
    window.deleteLater()


def test_focus_error_target_maps_to_main_window_controls(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    window.show()
    qapp.processEvents()

    window.focus_error_target("app_combo")
    qapp.processEvents()
    assert window.app_combo.hasFocus()

    window.focus_error_target("script_combo")
    qapp.processEvents()
    assert window.script_combo.hasFocus()

    window.focus_error_target("hook_target_input")
    qapp.processEvents()
    assert window.hook_target_input.hasFocus()

    window.focus_error_target("inspect_target_input")
    qapp.processEvents()
    assert window.inspect_target_input.hasFocus()
    window.deleteLater()


def test_focus_error_target_ignores_unknown_key(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    window.focus_error_target("does_not_exist")
    window.deleteLater()


def test_main_window_highlights_four_step_flow(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)

    assert window.refresh_apps_button.text() == "1. 准备环境并刷新 App"
    assert window.advanced_frida_launch_button.text() == f"3A. {ui_messages.ADVANCED_FRIDA_BUTTON}"

    labels = {
        label.text()
        for label in window.findChildren(QLabel)
        if label.objectName() == "sectionCaption"
    }
    assert "2. 选择目标 App" in labels
    assert "3. 选择脚本与模式" in labels
    assert "4. 启动与会话控制" in labels
    assert "脚本生成 / 高级启动" in labels
    window.deleteLater()


def test_main_window_restart_button_is_compact_action(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    assert window.restart_app_button.objectName() == "compactButton"
    window.deleteLater()


def test_main_window_deemphasizes_optional_flow_actions(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)

    assert window.prepare_workspace_button.objectName() == "secondaryButton"
    assert window.advanced_frida_launch_button.objectName() == "secondaryButton"
    assert window.stop_frida_server_button.objectName() == "compactButton"
    assert window.restart_app_button.text() == "重启 App（必要时）"

    assert window.prepare_workspace_button.toolTip() == "只有需要工作区脚本、副本或参数化 runtime 时，再初始化工作目录。"
    window.deleteLater()


def test_main_window_moves_flow_hints_into_tooltips(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)

    helper_labels = {
        label.text()
        for label in window.findChildren(QLabel)
        if label.objectName() == "helperText"
    }
    assert ui_messages.ADVANCED_FRIDA_FLOW_HINT not in helper_labels
    assert ui_messages.HOOK_TARGET_FLOW_HINT not in helper_labels
    assert window.generate_hook_button.toolTip() == ui_messages.HOOK_TARGET_FLOW_HINT
    assert window.advanced_frida_launch_button.toolTip() == ui_messages.ADVANCED_FRIDA_FLOW_HINT
    assert window.start_hook_button.toolTip() == ui_messages.LAUNCH_STEP_HINT_IDLE

    window.set_session_status(
        phase=ui_messages.SESSION_STATUS_PHASE_RUNNING,
        mode="attach",
        package="pkg.demo",
        script="demo.js",
        detail="已进入会话",
    )
    assert window.start_hook_button.toolTip() == ui_messages.LAUNCH_STEP_HINT_RUNNING
    assert window.stop_hook_button.toolTip() == ui_messages.LAUNCH_STEP_HINT_RUNNING

    window.set_session_status(
        phase=ui_messages.SESSION_STATUS_PHASE_STOPPED,
        detail=ui_messages.SESSION_STATUS_STOPPED_DETAIL,
    )
    assert window.start_hook_button.toolTip() == ui_messages.LAUNCH_STEP_HINT_IDLE
    window.deleteLater()


def test_main_window_session_status_badges_follow_phase(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)

    cases = [
        (ui_messages.SESSION_STATUS_PHASE_STARTING, "sessionStatusBadgeStarting", ui_messages.SESSION_STATUS_SUMMARY_STARTING),
        (ui_messages.SESSION_STATUS_PHASE_STOPPING, "sessionStatusBadgeStopping", ui_messages.SESSION_STATUS_SUMMARY_STOPPING),
        (ui_messages.SESSION_STATUS_PHASE_AUTO_STOPPING, "sessionStatusBadgeStopping", ui_messages.SESSION_STATUS_SUMMARY_AUTO_STOPPING),
        (ui_messages.SESSION_STATUS_PHASE_STOPPED, "sessionStatusBadgeStopped", ui_messages.SESSION_STATUS_SUMMARY_STOPPED),
        (ui_messages.SESSION_STATUS_PHASE_DETACHED, "sessionStatusBadgeDetached", ui_messages.SESSION_STATUS_SUMMARY_DETACHED),
        (ui_messages.SESSION_STATUS_PHASE_FAILED, "sessionStatusBadgeFailed", ui_messages.SESSION_STATUS_SUMMARY_FAILED),
    ]
    action_map = {
        ui_messages.SESSION_STATUS_PHASE_STARTING: ui_messages.SESSION_STATUS_ACTION_STARTING,
        ui_messages.SESSION_STATUS_PHASE_STOPPING: ui_messages.SESSION_STATUS_ACTION_STOPPING,
        ui_messages.SESSION_STATUS_PHASE_AUTO_STOPPING: ui_messages.SESSION_STATUS_ACTION_AUTO_STOPPING,
        ui_messages.SESSION_STATUS_PHASE_STOPPED: ui_messages.SESSION_STATUS_ACTION_STOPPED,
        ui_messages.SESSION_STATUS_PHASE_DETACHED: ui_messages.SESSION_STATUS_ACTION_DETACHED,
        ui_messages.SESSION_STATUS_PHASE_FAILED: ui_messages.SESSION_STATUS_ACTION_FAILED,
    }
    for phase, badge_name, summary in cases:
        window.set_session_status(phase=phase, detail="test")
        assert window.session_status_phase_label.objectName() == badge_name
        assert window.session_status_summary_label.text() == ui_messages.SESSION_STATUS_SUMMARY_TEMPLATE.format(summary=summary)
        assert window.session_status_action_label.text() == action_map[phase]

    window.deleteLater()


def test_main_window_updates_error_recovery_banner(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)

    assert window.error_recovery_banner_label.isHidden() is True
    window.update_error_recovery_banner("app_combo")
    assert window.error_recovery_banner_label.isHidden() is False
    assert window.error_recovery_banner_label.text() == (
        f"{ui_messages.ERROR_RECOVERY_BANNER_PREFIX}{ui_messages.ERROR_RECOVERY_APP}"
    )

    window.update_error_recovery_banner(None, "请补齐参数")
    assert window.error_recovery_banner_label.text() == (
        f"{ui_messages.ERROR_RECOVERY_BANNER_PREFIX}请补齐参数"
    )

    window.clear_error_recovery_banner()
    assert window.error_recovery_banner_label.isHidden() is True
    assert window.error_recovery_banner_label.text() == ui_messages.ERROR_RECOVERY_EMPTY
    window.deleteLater()


def test_main_window_script_root_source_label_updates_for_builtin_and_workspace(qapp, dummy_deps, tmp_path) -> None:
    window = build_main_window(dummy_deps)
    builtin_dir = tmp_path / 'hookers' / 'js'
    builtin_dir.mkdir(parents=True, exist_ok=True)
    workspace_dir = tmp_path / 'workspaces' / 'pkg.demo' / 'js'
    workspace_dir.mkdir(parents=True, exist_ok=True)

    dummy_deps.context.hookers_js_dir = builtin_dir
    dummy_deps.context.project_root = tmp_path

    window.apply_script_root(builtin_dir)
    assert window.script_root_source_label.text() == ui_messages.SCRIPT_ROOT_SOURCE_LABEL.format(
        value=ui_messages.SCRIPT_ROOT_SOURCE_BUILTIN
    )

    window.apply_script_root(workspace_dir)
    assert window.script_root_source_label.text() == ui_messages.SCRIPT_ROOT_SOURCE_LABEL.format(
        value=ui_messages.SCRIPT_ROOT_SOURCE_WORKSPACE
    )
    window.deleteLater()


def test_main_window_selected_script_label_shows_source_and_kind(qapp, dummy_deps, tmp_path) -> None:
    window = build_main_window(dummy_deps)
    dummy_deps.context.project_root = tmp_path
    builtin_dir = tmp_path / 'hookers' / 'js'
    builtin_dir.mkdir(parents=True, exist_ok=True)
    dummy_deps.context.hookers_js_dir = builtin_dir

    workspace_dir = tmp_path / 'workspaces' / 'pkg.demo' / 'js'
    workspace_dir.mkdir(parents=True, exist_ok=True)
    runtime_script = workspace_dir / 'jni_method_trace.runtime.js'
    runtime_script.write_text('// runtime', encoding='utf-8')

    window.apply_script_root(workspace_dir)
    index = window.script_combo.findText('jni_method_trace.runtime.js')
    window.script_combo.setCurrentIndex(index)

    text_value = window.selected_script_label.text()
    assert ui_messages.SCRIPT_SELECTION_NAME.format(value='jni_method_trace.runtime.js') in text_value
    assert ui_messages.SCRIPT_SELECTION_SOURCE.format(value=ui_messages.ADVANCED_FRIDA_WORKSPACE_SOURCE) in text_value
    assert ui_messages.SCRIPT_SELECTION_RUNTIME in text_value
    window.deleteLater()


def test_main_window_shows_script_list_empty_hint_when_directory_has_no_scripts(qapp, dummy_deps, tmp_path) -> None:
    window = build_main_window(dummy_deps)
    empty_dir = tmp_path / 'empty-js'
    empty_dir.mkdir(parents=True, exist_ok=True)

    window.apply_script_root(empty_dir)
    assert window.script_list_hint_label.isHidden() is False
    assert window.selected_script_label.text() == ui_messages.SCRIPT_SELECTION_EMPTY
    window.deleteLater()


def test_main_window_script_panel_shows_summary_card_and_tooltip_hint(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)

    assert window.script_root_hint_label.isHidden() is True
    tooltip = window.script_dir_input.toolTip()
    assert ui_messages.SCRIPT_SELECTION_ROOT_HINT in tooltip
    assert str(window.script_root) in tooltip
    assert window.selected_script_label.objectName() == "stateLabel"
    assert window.selected_script_label.text() == ui_messages.SCRIPT_SELECTION_EMPTY

    window.deleteLater()


def test_main_window_selected_script_tooltip_contains_root_and_full_path(qapp, dummy_deps, tmp_path) -> None:
    window = build_main_window(dummy_deps)
    dummy_deps.context.project_root = tmp_path
    builtin_dir = tmp_path / 'hookers' / 'js'
    builtin_dir.mkdir(parents=True, exist_ok=True)
    (builtin_dir / 'alpha.js').write_text('// demo', encoding='utf-8')
    dummy_deps.context.hookers_js_dir = builtin_dir

    window.apply_script_root(builtin_dir)
    index = window.script_combo.findText('alpha.js')
    window.script_combo.setCurrentIndex(index)

    tooltip = window.selected_script_label.toolTip()
    assert ui_messages.SCRIPT_SELECTION_ROOT_PATH.format(value=str(builtin_dir)) in tooltip
    assert ui_messages.SCRIPT_SELECTION_TAGS.format(value="-") in tooltip
    assert ui_messages.SCRIPT_SELECTION_PATH.format(value=str(builtin_dir / 'alpha.js')) in tooltip

    window.deleteLater()


def test_main_window_selected_script_label_uses_custom_source_for_custom_directory(qapp, dummy_deps, tmp_path) -> None:
    window = build_main_window(dummy_deps)
    dummy_deps.context.project_root = tmp_path
    builtin_dir = tmp_path / 'hookers' / 'js'
    builtin_dir.mkdir(parents=True, exist_ok=True)
    dummy_deps.context.hookers_js_dir = builtin_dir

    custom_dir = tmp_path / 'custom-js'
    custom_dir.mkdir(parents=True, exist_ok=True)
    (custom_dir / 'custom.js').write_text('// custom', encoding='utf-8')

    window.apply_script_root(custom_dir)
    index = window.script_combo.findText('custom.js')
    window.script_combo.setCurrentIndex(index)

    text_value = window.selected_script_label.text()
    assert ui_messages.SCRIPT_SELECTION_SOURCE.format(value=ui_messages.SCRIPT_SELECTION_CUSTOM_SOURCE) in text_value
    assert window.script_root_source_label.text() == ui_messages.SCRIPT_ROOT_SOURCE_LABEL.format(
        value=ui_messages.SCRIPT_ROOT_SOURCE_CUSTOM
    )
    window.deleteLater()


def test_main_window_builtin_root_does_not_render_workspace_metadata_for_same_named_builtin(qapp, dummy_deps, tmp_path) -> None:
    window = build_main_window(dummy_deps)
    app = dummy_deps.device_service.ensure_result
    app.identifier = 'pkg.demo'
    dummy_deps.context.current_app = app
    window.app_combo.addItem(app.name, app.identifier)
    window.app_combo.setCurrentIndex(0)
    dummy_deps.context.project_root = tmp_path
    builtin_dir = tmp_path / 'hookers' / 'js'
    builtin_dir.mkdir(parents=True, exist_ok=True)
    dummy_deps.context.hookers_js_dir = builtin_dir
    builtin_alpha = builtin_dir / 'alpha.js'
    builtin_alpha.write_text('// builtin alpha', encoding='utf-8')
    dummy_deps.workspace_service.metadata_by_package.setdefault('pkg.demo', {})['alpha.js'] = ScriptMetadata(
        name='alpha.js',
        summary='workspace metadata summary',
        recommended_mode='spawn',
    )

    window.apply_script_root(builtin_dir)
    idx = window.script_combo.findData(str(builtin_alpha.resolve()))
    window.script_combo.setCurrentIndex(idx)

    text_value = window.selected_script_label.text()
    assert ui_messages.SCRIPT_SELECTION_SOURCE.format(value=ui_messages.ADVANCED_FRIDA_BUILTIN_SOURCE) in text_value
    assert ui_messages.SCRIPT_SELECTION_SUMMARY.format(value='-') in text_value
    assert ui_messages.SCRIPT_SELECTION_RECOMMENDED_MODE.format(value=ui_messages.SCRIPT_METADATA_MODE_EITHER) in text_value
    window.deleteLater()


def test_main_window_custom_root_does_not_render_workspace_metadata_for_same_named_custom_script(qapp, dummy_deps, tmp_path) -> None:
    window = build_main_window(dummy_deps)
    app = dummy_deps.device_service.ensure_result
    app.identifier = 'pkg.demo'
    dummy_deps.context.current_app = app
    window.app_combo.addItem(app.name, app.identifier)
    window.app_combo.setCurrentIndex(0)
    dummy_deps.context.project_root = tmp_path
    builtin_dir = tmp_path / 'hookers' / 'js'
    builtin_dir.mkdir(parents=True, exist_ok=True)
    dummy_deps.context.hookers_js_dir = builtin_dir
    custom_dir = tmp_path / 'custom-js'
    custom_dir.mkdir(parents=True, exist_ok=True)
    custom_alpha = custom_dir / 'alpha.js'
    custom_alpha.write_text('// custom alpha', encoding='utf-8')
    dummy_deps.workspace_service.metadata_by_package.setdefault('pkg.demo', {})['alpha.js'] = ScriptMetadata(
        name='alpha.js',
        summary='workspace metadata summary',
        recommended_mode='attach',
    )

    window.apply_script_root(custom_dir)
    idx = window.script_combo.findData(str(custom_alpha.resolve()))
    window.script_combo.setCurrentIndex(idx)

    text_value = window.selected_script_label.text()
    assert ui_messages.SCRIPT_SELECTION_SOURCE.format(value=ui_messages.SCRIPT_SELECTION_CUSTOM_SOURCE) in text_value
    assert ui_messages.SCRIPT_SELECTION_SUMMARY.format(value='-') in text_value
    assert ui_messages.SCRIPT_SELECTION_RECOMMENDED_MODE.format(value=ui_messages.SCRIPT_METADATA_MODE_EITHER) in text_value
    window.deleteLater()


def test_main_window_moves_session_status_to_left_panel(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)

    assert window.session_status_phase_label.parentWidget().parentWidget() is window.script_panel

    window.deleteLater()


from core.workspace_service import ScriptMetadata, ScriptSourceInfo


def test_main_window_selected_script_type_uses_ui_message_template(qapp, dummy_deps, tmp_path) -> None:
    window = build_main_window(dummy_deps)
    app = dummy_deps.device_service.ensure_result
    app.identifier = "pkg.demo"
    dummy_deps.context.current_app = app
    window.app_combo.addItem(app.name, app.identifier)
    window.app_combo.setCurrentIndex(0)
    dummy_deps.context.project_root = tmp_path
    dummy_deps.context.hookers_js_dir = tmp_path / "hookers" / "js"
    dummy_deps.context.hookers_js_dir.mkdir(parents=True, exist_ok=True)
    workspace_dir = tmp_path / "workspaces" / "pkg.demo" / "js"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    script_path = workspace_dir / "alpha.js"
    script_path.write_text("// alpha", encoding="utf-8")
    original_script_dir = dummy_deps.workspace_service.script_dir
    dummy_deps.workspace_service.script_dir = lambda _package_name: workspace_dir

    try:
        window.apply_script_root(workspace_dir)
        idx = window.script_combo.findData(str(script_path.resolve()))
        window.script_combo.setCurrentIndex(idx)
        text_value = window.selected_script_label.text()
        assert ui_messages.ADVANCED_FRIDA_DETAIL_TYPE.format(value=ui_messages.SCRIPT_SELECTION_TYPE_WORKSPACE) in text_value
    finally:
        dummy_deps.workspace_service.script_dir = original_script_dir


def test_main_window_selected_script_shows_metadata_summary_and_mode(qapp, dummy_deps, tmp_path) -> None:
    window = build_main_window(dummy_deps)
    app = dummy_deps.device_service.ensure_result
    app.identifier = "pkg.demo"
    dummy_deps.context.current_app = app
    window.app_combo.addItem(app.name, app.identifier)
    window.app_combo.setCurrentIndex(0)
    dummy_deps.context.project_root = tmp_path
    dummy_deps.context.hookers_js_dir = tmp_path / "hookers" / "js"
    dummy_deps.context.hookers_js_dir.mkdir(parents=True, exist_ok=True)
    workspace_dir = tmp_path / "workspaces" / "pkg.demo" / "js"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    script_path = workspace_dir / "alpha.js"
    script_path.write_text("// alpha", encoding="utf-8")
    original_script_dir = dummy_deps.workspace_service.script_dir
    dummy_deps.workspace_service.script_dir = lambda _package_name: workspace_dir
    dummy_deps.workspace_service.metadata_by_package.setdefault("pkg.demo", {})["alpha.js"] = ScriptMetadata(
        name="alpha.js",
        pinned=True,
        last_used_at="2026-06-08T10:30:00+08:00",
        recommended_mode="attach",
        summary="×¥È¡ÍøÂçÇëÇó",
        tags=("network", "okhttp"),
    )
    window.apply_script_root(workspace_dir)
    idx = window.script_combo.findData(str(script_path.resolve()))
    window.script_combo.setCurrentIndex(idx)
    text_value = window.selected_script_label.text()
    assert ui_messages.SCRIPT_SELECTION_RECOMMENDED_MODE.format(value=ui_messages.SCRIPT_METADATA_MODE_ATTACH) in text_value
    assert ui_messages.SCRIPT_SELECTION_SUMMARY.format(value="×¥È¡ÍøÂçÇëÇó") in text_value
    assert ui_messages.SCRIPT_SELECTION_TAGS.format(value="network, okhttp") in text_value
    assert ui_messages.SCRIPT_LAST_USED_AT.format(value="2026-06-08T10:30:00+08:00") in text_value
    window.deleteLater()


def test_main_window_selected_script_uses_resolved_metadata_consistently_for_summary_tags_and_last_used(
    qapp, dummy_deps, tmp_path, monkeypatch
) -> None:
    window = build_main_window(dummy_deps)
    app = dummy_deps.device_service.ensure_result
    app.identifier = "pkg.demo"
    dummy_deps.context.current_app = app
    window.app_combo.addItem(app.name, app.identifier)
    window.app_combo.setCurrentIndex(0)
    dummy_deps.context.project_root = tmp_path
    dummy_deps.context.hookers_js_dir = tmp_path / "hookers" / "js"
    dummy_deps.context.hookers_js_dir.mkdir(parents=True, exist_ok=True)
    workspace_dir = tmp_path / "workspaces" / "pkg.demo" / "js"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    script_path = workspace_dir / "alpha.js"
    script_path.write_text("// alpha", encoding="utf-8")
    dummy_deps.workspace_service.script_dir = lambda _package_name: workspace_dir
    original_enrich = dummy_deps.workspace_service.enrich_script_source_info

    def enrich_without_attached_metadata(package_name, info):
        enriched = original_enrich(package_name, info)
        if package_name == "pkg.demo" and enriched.name == "alpha.js":
            return ScriptSourceInfo(
                name=enriched.name,
                path=enriched.path,
                source_kind=enriched.source_kind,
                is_builtin=enriched.is_builtin,
                is_parameter_template=enriched.is_parameter_template,
                display_label=enriched.display_label,
                metadata=None,
            )
        return enriched

    monkeypatch.setattr(
        dummy_deps.workspace_service,
        "enrich_script_source_info",
        enrich_without_attached_metadata,
    )
    monkeypatch.setattr(
        dummy_deps.workspace_service,
        "resolve_script_metadata",
        lambda package_name, script_name: (
            ScriptMetadata(
                name="alpha.js",
                pinned=True,
                last_used_at="2026-06-08T10:30:00+08:00",
                recommended_mode="attach",
                summary="抓取网络请求",
                tags=("network", "okhttp"),
            )
            if package_name == "pkg.demo" and script_name == "alpha.js"
            else None
        ),
    )

    window.apply_script_root(workspace_dir)
    idx = window.script_combo.findData(str(script_path.resolve()))
    window.script_combo.setCurrentIndex(idx)

    text_value = window.selected_script_label.text()
    tooltip = window.selected_script_label.toolTip()
    assert ui_messages.SCRIPT_SELECTION_RECOMMENDED_MODE.format(value=ui_messages.SCRIPT_METADATA_MODE_ATTACH) in text_value
    assert ui_messages.SCRIPT_SELECTION_SUMMARY.format(value="抓取网络请求") in text_value
    assert ui_messages.SCRIPT_SELECTION_TAGS.format(value="network, okhttp") in text_value
    assert ui_messages.SCRIPT_LAST_USED_AT.format(value="2026-06-08T10:30:00+08:00") in text_value
    assert ui_messages.SCRIPT_SELECTION_SUMMARY.format(value="抓取网络请求") in tooltip
    assert ui_messages.SCRIPT_SELECTION_TAGS.format(value="network, okhttp") in tooltip
    assert ui_messages.SCRIPT_LAST_USED_AT.format(value="2026-06-08T10:30:00+08:00") in tooltip
    window.deleteLater()


def test_main_window_script_filter_recent_only_shows_recent_items(qapp, dummy_deps, tmp_path) -> None:
    window = build_main_window(dummy_deps)
    app = dummy_deps.device_service.ensure_result
    app.identifier = "pkg.demo"
    dummy_deps.context.current_app = app
    window.app_combo.addItem(app.name, app.identifier)
    window.app_combo.setCurrentIndex(0)
    dummy_deps.context.project_root = tmp_path
    dummy_deps.context.hookers_js_dir = tmp_path / "hookers" / "js"
    dummy_deps.context.hookers_js_dir.mkdir(parents=True, exist_ok=True)
    workspace_dir = tmp_path / "workspaces" / "pkg.demo" / "js"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    (workspace_dir / "alpha.js").write_text("// alpha", encoding="utf-8")
    (workspace_dir / "beta.js").write_text("// beta", encoding="utf-8")
    dummy_deps.workspace_service.script_dir = lambda _package_name: workspace_dir
    dummy_deps.workspace_service.metadata_by_package.setdefault("pkg.demo", {})["alpha.js"] = ScriptMetadata(name="alpha.js", last_used_at="2026-06-08T10:00:00+08:00")
    window.apply_script_root(workspace_dir)
    window.script_filter_combo.setCurrentText(ui_messages.SCRIPT_FILTER_RECENT)
    labels = [window.script_combo.itemText(index) for index in range(window.script_combo.count())]
    assert any("alpha.js" in label for label in labels)
    assert all("beta.js" not in label for label in labels)
    window.deleteLater()


def test_main_window_script_search_filters_workspace_items(qapp, dummy_deps, tmp_path) -> None:
    window = build_main_window(dummy_deps)
    app = dummy_deps.device_service.ensure_result
    app.identifier = "pkg.demo"
    dummy_deps.context.current_app = app
    window.app_combo.addItem(app.name, app.identifier)
    window.app_combo.setCurrentIndex(0)
    dummy_deps.context.project_root = tmp_path
    dummy_deps.context.hookers_js_dir = tmp_path / "hookers" / "js"
    dummy_deps.context.hookers_js_dir.mkdir(parents=True, exist_ok=True)
    workspace_dir = tmp_path / "workspaces" / "pkg.demo" / "js"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    (workspace_dir / "alpha.js").write_text("// alpha", encoding="utf-8")
    (workspace_dir / "beta.js").write_text("// beta", encoding="utf-8")
    dummy_deps.workspace_service.script_dir = lambda _package_name: workspace_dir
    window.apply_script_root(workspace_dir)

    window.script_search_input.setText("alp")

    labels = [window.script_combo.itemText(index) for index in range(window.script_combo.count())]
    assert any("alpha.js" in label for label in labels)
    assert all("beta.js" not in label for label in labels)
    window.deleteLater()


def test_main_window_script_search_reselects_first_visible_candidate_when_current_item_filtered_out(qapp, dummy_deps, tmp_path) -> None:
    window = build_main_window(dummy_deps)
    app = dummy_deps.device_service.ensure_result
    app.identifier = "pkg.demo"
    dummy_deps.context.current_app = app
    window.app_combo.addItem(app.name, app.identifier)
    window.app_combo.setCurrentIndex(0)
    dummy_deps.context.project_root = tmp_path
    dummy_deps.context.hookers_js_dir = tmp_path / "hookers" / "js"
    dummy_deps.context.hookers_js_dir.mkdir(parents=True, exist_ok=True)
    workspace_dir = tmp_path / "workspaces" / "pkg.demo" / "js"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    alpha = workspace_dir / "alpha.js"
    beta = workspace_dir / "beta.js"
    alpha.write_text("// alpha", encoding="utf-8")
    beta.write_text("// beta", encoding="utf-8")
    dummy_deps.workspace_service.script_dir = lambda _package_name: workspace_dir

    window.apply_script_root(workspace_dir)
    idx = window.script_combo.findData(str(alpha.resolve()))
    window.script_combo.setCurrentIndex(idx)


    window.script_search_input.setText("beta")

    assert window.script_combo.currentIndex() == 0
    assert window.script_combo.currentData() == str(beta.resolve())
    assert "beta.js" in window.selected_script_label.text()
    window.deleteLater()


def test_main_window_workspace_search_keeps_current_identity_when_selected_item_still_matches(qapp, dummy_deps, tmp_path) -> None:
    window = build_main_window(dummy_deps)
    app = dummy_deps.device_service.ensure_result
    app.identifier = "pkg.demo"
    dummy_deps.context.current_app = app
    window.app_combo.addItem(app.name, app.identifier)
    window.app_combo.setCurrentIndex(0)
    dummy_deps.context.project_root = tmp_path
    dummy_deps.context.hookers_js_dir = tmp_path / "hookers" / "js"
    dummy_deps.context.hookers_js_dir.mkdir(parents=True, exist_ok=True)
    workspace_dir = tmp_path / "workspaces" / "pkg.demo" / "js"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    alpha = workspace_dir / "alpha_trace.js"
    beta = workspace_dir / "beta_trace.js"
    alpha.write_text("// alpha", encoding="utf-8")
    beta.write_text("// beta", encoding="utf-8")
    dummy_deps.workspace_service.script_dir = lambda _package_name: workspace_dir

    window.apply_script_root(workspace_dir)
    idx = window.script_combo.findData(str(alpha.resolve()))
    window.script_combo.setCurrentIndex(idx)
    assert window.script_combo.currentData() == str(alpha.resolve())

    window.script_search_input.setText("trace")

    assert window.script_combo.currentData() == str(alpha.resolve())
    assert "alpha_trace.js" in window.selected_script_label.text()
    window.deleteLater()


def test_main_window_selected_script_tip_clears_metadata_actions_when_current_info_missing(qapp, dummy_deps, tmp_path) -> None:
    window = build_main_window(dummy_deps)
    app = dummy_deps.device_service.ensure_result
    app.identifier = "pkg.demo"
    dummy_deps.context.current_app = app
    window.app_combo.addItem(app.name, app.identifier)
    window.app_combo.setCurrentIndex(0)
    dummy_deps.context.project_root = tmp_path
    dummy_deps.context.hookers_js_dir = tmp_path / "hookers" / "js"
    dummy_deps.context.hookers_js_dir.mkdir(parents=True, exist_ok=True)
    workspace_dir = tmp_path / "workspaces" / "pkg.demo" / "js"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    script_path = workspace_dir / "alpha.js"
    script_path.write_text("// alpha", encoding="utf-8")
    dummy_deps.workspace_service.script_dir = lambda _package_name: workspace_dir

    window.apply_script_root(workspace_dir)
    idx = window.script_combo.findData(str(script_path.resolve()))
    window.script_combo.setCurrentIndex(idx)


    window.script_combo.setCurrentIndex(-1)
    window._update_selected_script_tip()

    assert window.selected_script_label.text() == ui_messages.SCRIPT_SELECTION_EMPTY
    window.deleteLater()


def test_main_window_script_search_filters_custom_directory_by_name(qapp, dummy_deps, tmp_path) -> None:
    window = build_main_window(dummy_deps)
    custom_dir = tmp_path / "custom_js"
    custom_dir.mkdir(parents=True, exist_ok=True)
    (custom_dir / "gamma.js").write_text("// gamma", encoding="utf-8")
    (custom_dir / "delta.js").write_text("// delta", encoding="utf-8")
    window.apply_script_root(custom_dir)

    window.script_search_input.setText("gam")

    labels = [window.script_combo.itemText(index) for index in range(window.script_combo.count())]
    assert labels == ["gamma.js"]
    window.script_search_input.clear()
    labels = [window.script_combo.itemText(index) for index in range(window.script_combo.count())]
    assert any("gamma.js" in label for label in labels)
    assert any("delta.js" in label for label in labels)
    window.deleteLater()


def test_main_window_selected_script_summary_shows_additional_builtin_knowledge_card(qapp, dummy_deps, tmp_path, monkeypatch) -> None:
    window = build_main_window(dummy_deps)
    builtin_dir = tmp_path / 'hookers' / 'js'
    builtin_dir.mkdir(parents=True, exist_ok=True)
    target = builtin_dir / 'just_trust_me.js'
    target.write_text('// builtin', encoding='utf-8')
    dummy_deps.context.hookers_js_dir = builtin_dir
    dummy_deps.context.current_app = dummy_deps.device_service.ensure_result

    from core.workspace_service import ScriptSourceInfo
    monkeypatch.setattr(
        window,
        '_current_script_source_info',
        lambda: ScriptSourceInfo(
            name='just_trust_me.js',
            path=target,
            source_kind='builtin_source',
            is_builtin=True,
            is_parameter_template=False,
            display_label='just_trust_me.js',
            metadata=None,
        ),
    )

    metadata = dummy_deps.workspace_service.resolve_script_metadata('pkg.default', 'just_trust_me.js')
    monkeypatch.setattr(window, '_script_display_metadata', lambda info: metadata)

    window._update_selected_script_tip()

    text_value = window.selected_script_label.text()
    assert '尝试统一绕过常见 SSL Pinning / 证书校验' in text_value
    assert '抓包失败、怀疑目标存在证书校验或 SSL Pinning 时优先尝试。' in text_value
    window.deleteLater()


def test_main_window_selected_script_summary_shows_builtin_use_when_and_caution(qapp, dummy_deps, tmp_path) -> None:
    window = build_main_window(dummy_deps)
    app = dummy_deps.device_service.ensure_result
    app.identifier = "pkg.demo"
    dummy_deps.context.current_app = app
    window.app_combo.addItem(app.name, app.identifier)
    window.app_combo.setCurrentIndex(0)
    dummy_deps.context.project_root = tmp_path
    workspace_dir = tmp_path / "workspaces" / "pkg.demo" / "js"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    script_path = workspace_dir / "okhttp.js"
    script_path.write_text("// okhttp", encoding="utf-8")
    dummy_deps.workspace_service.script_dir = lambda _package_name: workspace_dir

    window.apply_script_root(workspace_dir)
    window.script_combo.setCurrentIndex(window.script_combo.findData(str(script_path)))
    qapp.processEvents()

    text = window.selected_script_label.text()
    assert "适用时机：确认目标使用 OkHttp" in text
    assert "注意事项：若关键请求发生在冷启动早期" in text
    window.deleteLater()


def test_display_builder_builds_analysis_scenario_tooltip_text() -> None:
    from ui.display_builders import build_analysis_scenario_tooltip_text
    from ui.quick_hook_actions import ANALYSIS_SCENARIO_PROFILES

    text = build_analysis_scenario_tooltip_text(ANALYSIS_SCENARIO_PROFILES[0])

    assert ANALYSIS_SCENARIO_PROFILES[0].description in text
    assert ANALYSIS_SCENARIO_PROFILES[0].mode_hint in text
    if ANALYSIS_SCENARIO_PROFILES[0].expected_findings:
        assert ui_messages.ANALYSIS_SCENARIO_SUMMARY_EXPECTED_TITLE in text


def test_display_builder_builds_pinned_quick_launch_tooltip_text() -> None:
    from ui.display_builders import build_pinned_quick_launch_tooltip_text

    text = build_pinned_quick_launch_tooltip_text(
        source_text='工作区脚本',
        recommended_mode='Attach',
        summary='抓取登录接口',
        path_value=r'C:\demo\alpha.js',
    )

    assert '来源：工作区脚本' in text
    assert '推荐模式：Attach' in text
    assert '说明：抓取登录接口' in text
    assert '路径：C:\\demo\\alpha.js' in text



def test_display_builder_builds_workspace_case_home_card_text() -> None:
    from ui.display_builders import build_workspace_case_home_card_text

    text = build_workspace_case_home_card_text(
        {
            'package_name': 'pkg.demo',
            'workspace_ready': True,
            'script_asset_count': 3,
            'pinned_script_count': 1,
            'recent_script_count': 2,
            'named_template_count': 1,
            'recent_session_count': 4,
            'recent_log_count': 5,
            'recommended_entrypoint': 'resume_named_template',
            'case_entry_hint': '优先从最近模板继续',
            'last_used_template_name': '网络首轮',
            'latest_result_summary_excerpt': '发现登录 URL',
            'recommended_result_action_label': '回看网络链路',
            'recommended_result_action_description': '已命中 URL/Network，优先回看请求链路。',
            'recent_scripts': ['alpha.js', 'beta.js'],
            'recent_logs': ['latest.log'],
            'last_session': {
                'script_name': 'alpha.js',
                'mode': 'attach',
                'summary': 'alpha session',
            },
        },
        package_fallback='pkg.demo',
    )

    assert '包名：pkg.demo' in text
    assert '首页可用入口：' in text
    assert '来源：最近模板 网络首轮' in text
    assert '最近链路：' in text


def test_display_builder_builds_workspace_case_home_card_text_alias_path_removed() -> None:
    from ui.display_builders import build_workspace_case_home_card_text

    text = build_workspace_case_home_card_text(
        {
            'package_name': 'pkg.demo',
            'workspace_ready': True,
            'script_asset_count': 3,
            'pinned_script_count': 1,
            'recent_script_count': 2,
            'named_template_count': 1,
            'recent_session_count': 4,
            'recent_log_count': 5,
            'recommended_entrypoint': 'resume_named_template',
            'case_entry_hint': '优先从最近模板继续',
            'last_used_template_name': '网络首轮',
            'latest_result_summary_excerpt': '发现登录 URL',
            'recommended_result_action_label': '回看网络链路',
            'recommended_result_action_description': '已命中 URL/Network，优先回看请求链路。',
            'recent_scripts': ['alpha.js', 'beta.js'],
            'recent_logs': ['latest.log'],
            'last_session': {
                'script_name': 'alpha.js',
                'mode': 'attach',
                'summary': 'alpha session',
            },
        },
        package_fallback='pkg.demo',
    )

    assert '包名：pkg.demo' in text
    assert '最近 session / log：4 / 5' in text
    assert '最近链路：' in text
    assert '最近模板：网络首轮' in text
    assert '最近会话：alpha.js / attach / alpha session' in text


def test_display_builder_workspace_case_home_low_level_view_model_aliases_removed() -> None:
    import ui.display_builders as display_builders

    assert not hasattr(display_builders, 'build_workspace_case_home_summary_lines')
    assert not hasattr(display_builders, 'build_workspace_case_home_summary_view_model')
    assert not hasattr(display_builders, 'WorkspaceCaseHomeSummaryViewModel')


def test_workspace_case_home_builder_payloads_capture_priority_and_messages() -> None:
    from ui.display_builders import (
        build_workspace_case_home_action_payloads,
        build_workspace_case_home_resume_template_payload,
        build_workspace_case_home_run_action_payload,
    )

    manifest = {
        'recommended_entrypoint': 'resume_named_template',
        'last_used_template_name': '网络首轮',
        'recommended_result_action_label': '回看网络链路',
    }
    resume_payload = build_workspace_case_home_resume_template_payload(manifest)
    action_payload = build_workspace_case_home_run_action_payload({
        'recommended_entrypoint': 'review_latest_result_summary',
        'recommended_result_action_label': '回看网络链路',
    })
    payloads = build_workspace_case_home_action_payloads(manifest)

    assert resume_payload['enabled'] is True
    assert resume_payload['style_name'] == 'primaryButton'
    assert '当前优先' in resume_payload['tooltip']
    assert '高级启动器' in resume_payload['log_message']
    assert resume_payload['source_label'] == '最近模板 网络首轮'
    assert resume_payload['behavior_label'] == '打开高级启动器，并优先恢复该模板'
    assert any('状态提示：首页入口：已打开高级启动器，优先恢复最近模板“网络首轮”' in line for line in resume_payload['explanation_lines'])
    assert action_payload['enabled'] is True
    assert action_payload['style_name'] == 'primaryButton'
    assert '当前优先' in action_payload['tooltip']
    assert '结果建议执行链' in action_payload['log_message']
    assert action_payload['source_label'] == '最近结果摘要推导出的推荐动作 回看网络链路'
    assert action_payload['behavior_label'] == '复用当前结果建议执行链'
    assert set(payloads) == {'resume_template', 'run_action'}
    assert payloads['resume_template']['text'] == resume_payload['text']


def test_display_builder_builds_session_status_payload() -> None:
    from ui.display_builders import build_session_status_payload

    running = build_session_status_payload(ui_messages.SESSION_STATUS_PHASE_RUNNING)
    failed = build_session_status_payload(ui_messages.SESSION_STATUS_PHASE_FAILED)

    assert running['summary'] == ui_messages.SESSION_STATUS_SUMMARY_RUNNING
    assert running['action_text'] == ui_messages.SESSION_STATUS_ACTION_RUNNING
    assert running['badge_name'] == 'sessionStatusBadgeRunning'
    assert running['launch_hint'] == ui_messages.LAUNCH_STEP_HINT_RUNNING
    assert failed['summary'] == ui_messages.SESSION_STATUS_SUMMARY_FAILED
    assert failed['badge_name'] == 'sessionStatusBadgeFailed'
