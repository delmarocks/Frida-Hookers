from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QStatusBar,
    QTextEdit,
)
from ui.cli_terminal_view import CliTerminalView

from ui import ui_messages
from ui.log_panel import LogPanelController, LogPanelWidgets


def build_log_controller(owner_widget):
    log_filter_combo = QComboBox()
    log_filter_combo.addItems(
        [
            ui_messages.LOG_FILTER_ALL,
            ui_messages.LOG_FILTER_JS,
            ui_messages.LOG_FILTER_ERRORS,
            ui_messages.LOG_FILTER_TOOL,
        ]
    )
    widgets = LogPanelWidgets(
        log_console=QTextEdit(),
        log_filter_combo=log_filter_combo,
        log_search_input=QLineEdit(),
        log_search_status_label=QLabel(),
        prev_log_match_button=QPushButton(),
        next_log_match_button=QPushButton(),
        log_search_case_checkbox=QCheckBox(),
        log_search_regex_checkbox=QCheckBox(),
        log_search_matches_only_checkbox=QCheckBox(),
        choose_log_file_button=QPushButton(),
    )
    status_bar = QStatusBar()
    controller = LogPanelController(
        owner=owner_widget,
        widgets=widgets,
        status_bar=status_bar,
        project_root=Path.cwd(),
    )
    return controller, widgets


def test_normalize_js_log_message_compresses_blank_lines(owner_widget) -> None:
    controller, _ = build_log_controller(owner_widget)
    message = "[JS]\r\nfoo  \r\n\r\n\r\nbar \n"
    assert controller.normalize_js_log_message(message) == "[JS]\nfoo\n\nbar"


def test_is_effectively_empty_js_log_detects_blank_payload(owner_widget) -> None:
    controller, _ = build_log_controller(owner_widget)
    assert controller.is_effectively_empty_js_log("[JS]   \n")
    assert controller.is_effectively_empty_js_log("[JS:WARN]\n")
    assert not controller.is_effectively_empty_js_log("[TOOL] x")


def test_classify_log_detects_expected_categories(owner_widget) -> None:
    controller, _ = build_log_controller(owner_widget)
    assert controller.classify_log("[JS] ok").category == "js"
    assert controller.classify_log("[TOOL] ok").category == "tool"
    assert controller.classify_log("[!] boom").level == "error"


def test_render_logs_reports_invalid_regex(owner_widget) -> None:
    controller, widgets = build_log_controller(owner_widget)
    controller.append_log("[TOOL] hello world")
    widgets.log_search_input.setText("[")
    widgets.log_search_regex_checkbox.setChecked(True)
    controller.render_logs()
    assert widgets.log_search_status_label.text() == ui_messages.LOG_SEARCH_INVALID.format(
        scope=ui_messages.LOG_FILTER_ALL
    )


def test_render_logs_reports_match_progress(owner_widget) -> None:
    controller, widgets = build_log_controller(owner_widget)
    controller.append_log("[TOOL] alpha hook")
    controller.append_log("[TOOL] beta hook")
    widgets.log_search_input.setText("hook")
    controller.render_logs()
    assert widgets.log_search_status_label.text() == ui_messages.LOG_SEARCH_PROGRESS.format(
        scope=ui_messages.LOG_FILTER_ALL,
        current=1,
        total=2,
    )


def test_incremental_append_js_logs_does_not_insert_extra_blank_line(owner_widget) -> None:
    log_filter_combo = QComboBox()
    log_filter_combo.addItems(
        [
            ui_messages.LOG_FILTER_ALL,
            ui_messages.LOG_FILTER_JS,
            ui_messages.LOG_FILTER_ERRORS,
            ui_messages.LOG_FILTER_TOOL,
        ]
    )
    widgets = LogPanelWidgets(
        log_console=CliTerminalView(),
        log_filter_combo=log_filter_combo,
        log_search_input=QLineEdit(),
        log_search_status_label=QLabel(),
        prev_log_match_button=QPushButton(),
        next_log_match_button=QPushButton(),
        log_search_case_checkbox=QCheckBox(),
        log_search_regex_checkbox=QCheckBox(),
        log_search_matches_only_checkbox=QCheckBox(),
        choose_log_file_button=QPushButton(),
    )
    status_bar = QStatusBar()
    controller = LogPanelController(
        owner=owner_widget,
        widgets=widgets,
        status_bar=status_bar,
        project_root=Path.cwd(),
    )
    controller.render_logs()

    controller.append_log("[JS] first line\nsecond line")
    controller.append_log("[JS] third line\nfourth line")

    text = widgets.log_console.toPlainText()
    assert "[JS] first line\nsecond line\n[JS] third line\nfourth line" in text
    assert "[JS] first line\nsecond line\n\n[JS] third line" not in text
