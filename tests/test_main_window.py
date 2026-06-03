from __future__ import annotations

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QLabel
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt

from ui import ui_messages
from ui.main_window import MainWindow, MainWindowDependencies
from ui.quick_hook_actions import QUICK_HOOK_ACTIONS, QUICK_HOOK_GROUPS


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


def test_main_window_builds_terminal_widgets(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    assert window.terminal_cli_mode_button.text() == ui_messages.CLI_MODE_ENTER_BUTTON
    assert window.log_console.cli_mode_enabled() is False
    assert window.advanced_frida_launch_button.text() == ui_messages.ADVANCED_FRIDA_BUTTON
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
