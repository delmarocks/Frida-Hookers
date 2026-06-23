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
from ui.log_panel import LogPanelController, LogPanelWidgets, LogRecord


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


def test_build_result_summary_text_extracts_urls_and_deduplicates(owner_widget) -> None:
    controller, _ = build_log_controller(owner_widget)
    controller.append_log('[JS] GET https://api.example.com/v1/demo?id=1')
    controller.append_log('[TOOL] mirror https://api.example.com/v1/demo?id=1')
    controller.append_log('[JS] POST http://localhost:8080/test.')

    summary = controller.build_result_summary_text()

    assert ui_messages.RESULT_SUMMARY_TITLE in summary
    assert ui_messages.RESULT_SUMMARY_OVERVIEW_TITLE in summary
    assert ui_messages.RESULT_SUMMARY_OVERVIEW_SECTIONS.format(sections="URL/Network") in summary
    assert ui_messages.RESULT_SUMMARY_URL_TOTAL.format(count=3) in summary
    assert ui_messages.RESULT_SUMMARY_URL_UNIQUE_TOTAL.format(count=2) in summary
    assert 'https://api.example.com/v1/demo?id=1' in summary
    assert 'http://localhost:8080/test' in summary
    assert ui_messages.RESULT_SUMMARY_NEXT_STEP_TITLE in summary
    assert ui_messages.RESULT_SUMMARY_NEXT_STEP_NETWORK in summary


def test_build_result_summary_text_returns_empty_when_no_url_hits(owner_widget) -> None:
    controller, _ = build_log_controller(owner_widget)
    controller.append_log('[TOOL] no network here')

    assert controller.build_result_summary_text() == ui_messages.RESULT_SUMMARY_EMPTY


def test_build_result_summary_text_does_not_mutate_log_records(owner_widget) -> None:
    controller, _ = build_log_controller(owner_widget)
    controller.append_log('[JS] https://example.com/a')
    before = [record.message for record in controller.log_records]

    _ = controller.build_result_summary_text()

    after = [record.message for record in controller.log_records]
    assert after == before


def test_append_transient_view_message_does_not_mutate_log_records(owner_widget) -> None:
    controller, widgets = build_log_controller(owner_widget)
    controller.append_log('[JS] https://example.com/a')
    before = [record.message for record in controller.log_records]

    controller.append_transient_view_message(controller.build_result_summary_text())

    after = [record.message for record in controller.log_records]
    assert after == before
    assert 'https://example.com/a' in widgets.log_console.toPlainText()


def test_build_result_summary_text_ignores_previous_summary_output_pollution(owner_widget) -> None:
    controller, widgets = build_log_controller(owner_widget)
    controller.render_logs()
    controller.append_log('[JS] https://example.com/a')

    first = controller.build_result_summary_text()
    controller.append_transient_view_message(first)
    second = controller.build_result_summary_text()

    assert ui_messages.RESULT_SUMMARY_URL_TOTAL.format(count=1) in first
    assert ui_messages.RESULT_SUMMARY_URL_TOTAL.format(count=1) in second
    assert widgets.log_console.toPlainText().count('https://example.com/a') >= 1


def test_build_result_summary_text_extracts_activities_and_deduplicates(owner_widget) -> None:
    controller, _ = build_log_controller(owner_widget)
    controller.append_log('[JS] Activity: com.demo.MainActivity')
    controller.append_log('[TOOL] 页面跳转: com.demo.MainActivity')
    controller.append_log('[JS] Activity -> com.demo.DetailActivity')

    summary = controller.build_result_summary_text()

    assert ui_messages.RESULT_SUMMARY_TITLE in summary
    assert ui_messages.RESULT_SUMMARY_ACTIVITY_TOTAL.format(count=3) in summary
    assert ui_messages.RESULT_SUMMARY_ACTIVITY_UNIQUE_TOTAL.format(count=2) in summary
    assert 'com.demo.MainActivity' in summary
    assert 'com.demo.DetailActivity' in summary


def test_build_result_summary_text_combines_url_and_activity_sections(owner_widget) -> None:
    controller, _ = build_log_controller(owner_widget)
    controller.append_log('[JS] GET https://api.example.com/demo')
    controller.append_log('[JS] Activity: com.demo.MainActivity')

    summary = controller.build_result_summary_text()

    assert ui_messages.RESULT_SUMMARY_URL_TOTAL.format(count=1) in summary
    assert ui_messages.RESULT_SUMMARY_ACTIVITY_TOTAL.format(count=1) in summary
    assert 'https://api.example.com/demo' in summary
    assert 'com.demo.MainActivity' in summary


def test_build_result_summary_text_returns_activity_summary_without_urls(owner_widget) -> None:
    controller, _ = build_log_controller(owner_widget)
    controller.append_log('[JS] Activity changed to com.demo.MainActivity')

    summary = controller.build_result_summary_text()

    assert summary != ui_messages.RESULT_SUMMARY_EMPTY
    assert ui_messages.RESULT_SUMMARY_ACTIVITY_TOTAL.format(count=1) in summary
    assert 'com.demo.MainActivity' in summary


def test_build_result_summary_text_extracts_jni_registrations_and_deduplicates(owner_widget) -> None:
    controller, _ = build_log_controller(owner_widget)
    controller.append_log('[JS] [RegisterNatives] com.demo.NativeBridge (3 methods)')
    controller.append_log('[JS] [RegisterNatives] java_class: com.demo.NativeBridge name: nativeFoo sig: ()V fnPtr: 0x1234')
    controller.append_log('[JS] [RegisterNatives] java_class: com.demo.NativeBridge name: nativeFoo sig: ()V fnPtr: 0x8888')

    summary = controller.build_result_summary_text()

    assert ui_messages.RESULT_SUMMARY_JNI_TOTAL.format(count=3) in summary
    assert ui_messages.RESULT_SUMMARY_JNI_UNIQUE_TOTAL.format(count=2) in summary
    assert 'com.demo.NativeBridge (3 methods)' in summary
    assert 'com.demo.NativeBridge::nativeFoo ()V' in summary


def test_build_result_summary_text_combines_url_activity_and_jni_sections(owner_widget) -> None:
    controller, _ = build_log_controller(owner_widget)
    controller.append_log('[JS] GET https://api.example.com/demo')
    controller.append_log('[JS] Activity: com.demo.MainActivity')
    controller.append_log('[JS] [RegisterNatives] com.demo.NativeBridge (2 methods)')

    summary = controller.build_result_summary_text()

    assert ui_messages.RESULT_SUMMARY_URL_TOTAL.format(count=1) in summary
    assert ui_messages.RESULT_SUMMARY_ACTIVITY_TOTAL.format(count=1) in summary
    assert ui_messages.RESULT_SUMMARY_JNI_TOTAL.format(count=1) in summary


def test_build_result_summary_text_extracts_anti_frida_hits(owner_widget) -> None:
    controller, _ = build_log_controller(owner_widget)
    controller.append_log('[JS] anti-frida so detected: libalib.so')
    controller.append_log('[TOOL] anti-frida so detected: libalib.so')
    controller.append_log('[JS] frida detect bypass hook installed')

    summary = controller.build_result_summary_text()

    assert ui_messages.RESULT_SUMMARY_ANTI_FRIDA_TOTAL.format(count=3) in summary
    assert ui_messages.RESULT_SUMMARY_ANTI_FRIDA_UNIQUE_TOTAL.format(count=2) in summary
    assert 'anti-frida so detected: libalib.so' in summary
    assert 'frida detect bypass hook installed' in summary


def test_build_result_summary_text_extracts_root_detection_hits(owner_widget) -> None:
    controller, _ = build_log_controller(owner_widget)
    controller.append_log('[JS] root detect hit: su binary')
    controller.append_log('[TOOL] 检测到 root 环境: magisk')
    controller.append_log('[JS] root detect hit: su binary')

    summary = controller.build_result_summary_text()

    assert ui_messages.RESULT_SUMMARY_ROOT_TOTAL.format(count=3) in summary
    assert ui_messages.RESULT_SUMMARY_ROOT_UNIQUE_TOTAL.format(count=2) in summary
    assert 'root detect hit: su binary' in summary
    assert '检测到 root 环境: magisk' in summary


def test_build_result_summary_text_extracts_vpn_detection_hits(owner_widget) -> None:
    controller, _ = build_log_controller(owner_widget)
    controller.append_log('[JS] vpn detect hit: tun0')
    controller.append_log('[TOOL] 绕过 VPN 检测: ConnectivityManager')
    controller.append_log('[JS] vpn detect hit: tun0')

    summary = controller.build_result_summary_text()

    assert ui_messages.RESULT_SUMMARY_VPN_TOTAL.format(count=3) in summary
    assert ui_messages.RESULT_SUMMARY_VPN_UNIQUE_TOTAL.format(count=2) in summary
    assert 'vpn detect hit: tun0' in summary
    assert '绕过 VPN 检测: ConnectivityManager' in summary


def test_build_result_summary_text_combines_security_sections_with_existing_sections(owner_widget) -> None:
    controller, _ = build_log_controller(owner_widget)
    controller.append_log('[JS] GET https://api.example.com/demo')
    controller.append_log('[JS] Activity: com.demo.MainActivity')
    controller.append_log('[JS] [RegisterNatives] com.demo.NativeBridge (2 methods)')
    controller.append_log('[JS] anti-frida so detected: libcheck.so')
    controller.append_log('[JS] root detect hit: test-keys')
    controller.append_log('[JS] vpn detect hit: tun0')

    summary = controller.build_result_summary_text()

    assert ui_messages.RESULT_SUMMARY_URL_TOTAL.format(count=1) in summary
    assert ui_messages.RESULT_SUMMARY_ACTIVITY_TOTAL.format(count=1) in summary
    assert ui_messages.RESULT_SUMMARY_JNI_TOTAL.format(count=1) in summary
    assert ui_messages.RESULT_SUMMARY_ANTI_FRIDA_TOTAL.format(count=1) in summary
    assert ui_messages.RESULT_SUMMARY_ROOT_TOTAL.format(count=1) in summary
    assert ui_messages.RESULT_SUMMARY_VPN_TOTAL.format(count=1) in summary
    assert ui_messages.RESULT_SUMMARY_OVERVIEW_SECTIONS.format(
        sections="URL/Network / Activity / JNI / Anti-Frida / Root / VPN"
    ) in summary
    assert ui_messages.RESULT_SUMMARY_NEXT_STEP_NETWORK in summary
    assert ui_messages.RESULT_SUMMARY_NEXT_STEP_ACTIVITY in summary
    assert ui_messages.RESULT_SUMMARY_NEXT_STEP_JNI in summary
    assert ui_messages.RESULT_SUMMARY_NEXT_STEP_ANTI_FRIDA in summary
    assert ui_messages.RESULT_SUMMARY_NEXT_STEP_ROOT in summary
    assert ui_messages.RESULT_SUMMARY_NEXT_STEP_VPN in summary


def test_build_result_summary_actions_returns_structured_suggestions(owner_widget) -> None:
    controller, _ = build_log_controller(owner_widget)
    controller.append_log('[JS] GET https://api.example.com/demo')
    controller.append_log('[JS] Activity: com.demo.MainActivity')
    controller.append_log('[JS] [RegisterNatives] com.demo.NativeBridge (2 methods)')

    actions = controller.build_result_summary_actions()
    labels = [item['label'] for item in actions]

    assert '回看网络链路' in labels
    assert '复跑页面行为场景' in labels
    assert '转入 JNI/Native 场景' in labels
    assert any(item['command_hint'] for item in actions)
    assert any(item.get('entry_type') == 'scenario' for item in actions)
    assert any(item.get('target') for item in actions)
    assert any(item.get('source_reason') for item in actions)
    assert any(item.get('expected_value') for item in actions)
    assert any(item.get('risk_or_noise') for item in actions)
    assert any(item.get('preferred_surface') for item in actions)
    assert any(item.get('entry_label') == '网络分析场景' for item in actions)
    assert any(item.get('entry_source') == 'analysis_scenario' for item in actions)
    assert any(item.get('entry_description') for item in actions)


def test_build_result_summary_text_appends_action_section(owner_widget) -> None:
    controller, _ = build_log_controller(owner_widget)
    controller.append_log('[JS] GET https://api.example.com/demo')

    summary = controller.build_result_summary_text()

    assert ui_messages.RESULT_SUMMARY_ACTIONS_TITLE in summary
    assert '回看网络链路' in summary
    assert '来源说明：结果摘要已命中 URL / Network 相关线索。' in summary
    assert '预期收益：更快定位请求时机、参数来源与响应处理链。' in summary
    assert '风险/噪音：网络日志可能很多，需注意区分初始化噪音与真实业务请求。' in summary


def test_build_result_summary_note_block_outputs_markdown_sections(owner_widget) -> None:
    controller, _ = build_log_controller(owner_widget)
    controller.log_records = [
        LogRecord(message='https://api.demo.test/v1/login', category='js', level='info'),
        LogRecord(message='Activity: com.demo.LoginActivity', category='js', level='info'),
    ]

    summary = controller.build_result_summary_note_block()

    assert ui_messages.RESULT_SUMMARY_NOTE_TITLE in summary
    assert ui_messages.RESULT_SUMMARY_NOTE_SECTION_URL in summary
    assert '- https://api.demo.test/v1/login' in summary
    assert ui_messages.RESULT_SUMMARY_NOTE_SECTION_ACTIVITY in summary
    assert '- com.demo.LoginActivity' in summary


def test_build_result_summary_note_block_returns_empty_markdown_without_hits(owner_widget) -> None:
    controller, _ = build_log_controller(owner_widget)
    controller.log_records = [LogRecord(message='plain line', category='js', level='info')]

    summary = controller.build_result_summary_note_block()

    assert ui_messages.RESULT_SUMMARY_NOTE_TITLE in summary
    assert ui_messages.RESULT_SUMMARY_NOTE_EMPTY in summary
