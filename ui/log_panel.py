from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QTextEdit,
    QWidget,
)

from . import ui_messages
from .display_builders import (
    ResultSummaryTextSpec,
    ResultSummaryViewModel,
    build_result_summary_actions_text,
    build_result_summary_note_block,
    build_result_summary_text,
)
from .result_summary_rules import build_result_summary_category_rules
from .result_summary_pipeline import ResultSummarySnapshot, build_result_summary_snapshot
from .result_summary_extractors import (
    extract_result_summary_activities,
    extract_result_summary_jni_registrations,
    extract_result_summary_security_hits,
    extract_result_summary_urls,
)


@dataclass
class LogRecord:
    # GUI 内部使用的日志记录模型。
    message: str
    category: str
    level: str


@dataclass
class LogPanelWidgets:
    # 日志面板控件集合，集中交给控制器接管。
    log_console: QTextEdit
    log_filter_combo: QComboBox
    log_search_input: QLineEdit
    log_search_status_label: QLabel
    prev_log_match_button: QPushButton
    next_log_match_button: QPushButton
    log_search_case_checkbox: QCheckBox
    log_search_regex_checkbox: QCheckBox
    log_search_matches_only_checkbox: QCheckBox
    choose_log_file_button: QPushButton


class LogPanelController:
    RESULT_SUMMARY_CATEGORY_RULES = build_result_summary_category_rules(ui_messages)
    RESULT_SUMMARY_URL_LIMIT = 8
    RESULT_SUMMARY_URL_PATTERN = re.compile(r'https?://[^\s"<>]+', re.IGNORECASE)
    RESULT_SUMMARY_ACTIVITY_LIMIT = 8
    RESULT_SUMMARY_ACTIVITY_PATTERNS = (
        re.compile(r'Activity\s*[:：]\s*([A-Za-z0-9_.$/]+)', re.IGNORECASE),
        re.compile(r'Activity\s*->\s*([A-Za-z0-9_.$/]+)', re.IGNORECASE),
        re.compile(r'页面跳转\s*[:：]\s*([A-Za-z0-9_.$/]+)', re.IGNORECASE),
        re.compile(r'Activity\s+changed\s+to\s+([A-Za-z0-9_.$/]+)', re.IGNORECASE),
        re.compile(r'onResume\s*[:：]\s*([A-Za-z0-9_.$/]+)', re.IGNORECASE),
    )
    RESULT_SUMMARY_JNI_LIMIT = 8
    RESULT_SUMMARY_JNI_PATTERNS = (
        re.compile(r'\[RegisterNatives\]\s+([A-Za-z0-9_.$/]+)\s*\((\d+)\s+methods?\)', re.IGNORECASE),
        re.compile(r'\[RegisterNatives\]\s+java_class\s*:\s*([A-Za-z0-9_.$/]+)\s+name\s*:\s*([^\s]+)\s+sig\s*:\s*([^\s]+)', re.IGNORECASE),
    )
    RESULT_SUMMARY_ANTI_FRIDA_LIMIT = 8
    RESULT_SUMMARY_ANTI_FRIDA_PATTERNS = (
        re.compile(r'anti[-\s]?frida[^\n]*', re.IGNORECASE),
        re.compile(r'frida\s+detect[^\n]*', re.IGNORECASE),
    )
    RESULT_SUMMARY_ROOT_LIMIT = 8
    RESULT_SUMMARY_ROOT_PATTERNS = (
        re.compile(r'root\s+detect[^\n]*', re.IGNORECASE),
        re.compile(r'检测到\s*root[^\n]*', re.IGNORECASE),
        re.compile(r'绕过[^\n]*root[^\n]*', re.IGNORECASE),
    )
    RESULT_SUMMARY_VPN_LIMIT = 8
    RESULT_SUMMARY_VPN_PATTERNS = (
        re.compile(r'vpn\s+detect[^\n]*', re.IGNORECASE),
        re.compile(r'检测到\s*vpn[^\n]*', re.IGNORECASE),
        re.compile(r'绕过[^\n]*vpn[^\n]*', re.IGNORECASE),
    )

    # 独立日志控制器。
    #
    # 这一层只接管日志状态、搜索、渲染和落盘逻辑，
    # 不负责三栏 splitter 布局切换；“专注日志”仍由 MainWindow 管。
    MAX_LOG_RECORDS = 3000

    def __init__(
        self,
        owner: QWidget,
        widgets: LogPanelWidgets,
        status_bar: QStatusBar,
        project_root: Path,
        selected_package_name=None,
        selected_script_path=None,
    ) -> None:
        self.owner = owner
        self.widgets = widgets
        self.status_bar = status_bar
        self.project_root = project_root
        self.selected_package_name = selected_package_name or (lambda: None)
        self.selected_script_path = selected_script_path or (lambda: None)

        self.log_records: list[LogRecord] = []
        self.log_file_path: Path | None = None
        self.current_log_match_index = -1
        self.last_log_search_signature: tuple[str, bool, bool] | None = None
        self.visible_log_match_positions: list[tuple[int, int]] = []
        self.visible_log_match_count = 0
        self.last_log_view_signature: tuple[str, str, bool, bool, bool] | None = None
        self.last_rendered_record_count = 0

        self.log_render_timer = QTimer(owner)
        self.log_render_timer.setSingleShot(True)
        self.log_render_timer.setInterval(50)
        self.log_render_timer.timeout.connect(self._flush_scheduled_log_render)

    def normalize_js_log_message(self, message: str) -> str:
        normalized = message.replace("\r\n", "\n").replace("\r", "\n")
        normalized = "\n".join(line.rstrip() for line in normalized.split("\n"))
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        return normalized.rstrip()

    def is_effectively_empty_js_log(self, message: str) -> bool:
        if message.startswith("[JS:ERROR]"):
            payload = message[len("[JS:ERROR]"):]
        elif message.startswith("[JS:WARN]"):
            payload = message[len("[JS:WARN]"):]
        elif message.startswith("[JS]"):
            payload = message[len("[JS]"):]
        else:
            return False
        return payload.strip() == ""

    def classify_log(self, message: str) -> LogRecord:
        category = "general"
        level = "info"

        if message.startswith("[JS:ERROR]"):
            category = "js"
            level = "error"
        elif message.startswith("[JS:WARN]"):
            category = "js"
            level = "warn"
        elif message.startswith("[JS]"):
            category = "js"
            level = "info"
        elif message.startswith("[TOOL]"):
            category = "tool"
            level = "info"
        elif message.startswith("[!]"):
            category = "error"
            level = "error"
        elif "解密结果已保存到真实目录" in message or "日志文件已启用" in message:
            category = "general"
            level = "success"
        elif message.startswith("[+]"):
            category = "general"
            level = "success"

        return LogRecord(message=message, category=category, level=level)

    def log_color(self, record: LogRecord) -> str:
        if record.level == "error":
            return "#ff6b6b"
        if record.level == "warn":
            return "#ffd166"
        if record.category == "tool":
            return "#7ad7ff"
        if record.level == "success":
            return "#65f18c"
        return "#3cff70"

    def should_show_log(self, record: LogRecord) -> bool:
        filter_name = self.widgets.log_filter_combo.currentText()
        if filter_name == ui_messages.LOG_FILTER_ALL:
            return True
        if filter_name == ui_messages.LOG_FILTER_JS:
            return record.category == "js"
        if filter_name == ui_messages.LOG_FILTER_ERRORS:
            return record.level == "error"
        if filter_name == ui_messages.LOG_FILTER_TOOL:
            return record.category == "tool"
        return True

    def current_log_filter_scope(self) -> str:
        filter_name = self.widgets.log_filter_combo.currentText()
        if filter_name == ui_messages.LOG_FILTER_ALL:
            return ui_messages.LOG_FILTER_ALL
        return filter_name

    def log_search_keyword(self) -> str:
        return self.widgets.log_search_input.text().strip()

    def log_search_signature(self) -> tuple[str, bool, bool]:
        return (
            self.log_search_keyword(),
            self.widgets.log_search_case_checkbox.isChecked(),
            self.widgets.log_search_regex_checkbox.isChecked(),
        )

    def current_log_view_signature(self) -> tuple[str, str, bool, bool, bool]:
        return (
            self.widgets.log_filter_combo.currentText(),
            self.log_search_keyword(),
            self.widgets.log_search_case_checkbox.isChecked(),
            self.widgets.log_search_regex_checkbox.isChecked(),
            self.widgets.log_search_matches_only_checkbox.isChecked(),
        )

    def on_log_view_controls_changed(self) -> None:
        self.render_logs()

    def on_log_search_changed(self) -> None:
        signature = self.log_search_signature()
        if signature != self.last_log_search_signature:
            self.current_log_match_index = 0 if signature[0] else -1
            self.last_log_search_signature = signature
        self.render_logs()

    def clear_log_search(self) -> None:
        self.widgets.log_search_input.clear()

    def compile_log_search_pattern(self) -> tuple[re.Pattern[str] | None, str | None]:
        keyword = self.log_search_keyword()
        if not keyword:
            return None, None

        flags = 0 if self.widgets.log_search_case_checkbox.isChecked() else re.IGNORECASE
        pattern_text = (
            keyword if self.widgets.log_search_regex_checkbox.isChecked() else re.escape(keyword)
        )
        try:
            return re.compile(pattern_text, flags), None
        except re.error as exc:
            return None, str(exc)

    def find_next_log_match(self) -> None:
        keyword = self.log_search_keyword()
        if not keyword:
            return
        total = self.visible_log_match_count
        if total <= 0:
            return
        if self.current_log_match_index < 0:
            self.current_log_match_index = 0
        else:
            self.current_log_match_index = (self.current_log_match_index + 1) % total
        self.render_logs()

    def find_previous_log_match(self) -> None:
        keyword = self.log_search_keyword()
        if not keyword:
            return
        total = self.visible_log_match_count
        if total <= 0:
            return
        if self.current_log_match_index < 0:
            self.current_log_match_index = total - 1
        else:
            self.current_log_match_index = (self.current_log_match_index - 1) % total
        self.render_logs()

    def highlight_log_text(
        self,
        message: str,
        pattern: re.Pattern[str] | None,
        global_match_start: int,
    ) -> tuple[str, int]:
        if pattern is None:
            return escape(message), 0

        highlighted_parts: list[str] = []
        match_count = 0
        last_end = 0

        for match in pattern.finditer(message):
            start, end = match.span()
            if start == end:
                continue
            highlighted_parts.append(escape(message[last_end:start]))
            color = "#ffd54f"
            if global_match_start + match_count == self.current_log_match_index:
                color = "#ff8a65"
            highlighted_parts.append(
                f'<span style="background-color: {color}; color: #1f1f1f; border-radius: 2px;">'
                f"{escape(match.group(0))}"
                "</span>"
            )
            last_end = end
            match_count += 1

        if match_count == 0:
            return escape(message), 0

        highlighted_parts.append(escape(message[last_end:]))
        return "".join(highlighted_parts), match_count

    def focus_current_log_match(self) -> None:
        if self.current_log_match_index < 0:
            return
        if self.current_log_match_index >= len(self.visible_log_match_positions):
            return

        position, length = self.visible_log_match_positions[self.current_log_match_index]
        cursor = QTextCursor(self.widgets.log_console.document())
        cursor.setPosition(position)
        cursor.setPosition(position + max(length, 1), QTextCursor.KeepAnchor)
        self.widgets.log_console.setTextCursor(cursor)
        self.widgets.log_console.ensureCursorVisible()

    def can_incrementally_append_log(self, record: LogRecord, overflow: int) -> bool:
        if overflow > 0:
            return False
        if self.log_search_keyword():
            return False
        current_signature = self.current_log_view_signature()
        if self.last_log_view_signature != current_signature:
            return False
        return True

    def append_log_record_to_console(self, record: LogRecord) -> None:
        if not self.should_show_log(record):
            return
        html_fragment = (
            f'<span style="color: {self.log_color(record)}; white-space: pre-wrap;">'
            f"{escape(record.message)}"
            "</span><br/>"
        )
        if hasattr(self.widgets.log_console, "append_log_html_preserving_prompt"):
            self.widgets.log_console.append_log_html_preserving_prompt(html_fragment)
            return
        cursor = self.widgets.log_console.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertHtml(html_fragment)
        self.widgets.log_console.setTextCursor(cursor)
        self.widgets.log_console.ensureCursorVisible()

    def schedule_log_render(self) -> None:
        if not self.log_render_timer.isActive():
            self.log_render_timer.start()

    def _flush_scheduled_log_render(self) -> None:
        self.render_logs()

    def render_logs(self) -> None:
        if self.log_render_timer.isActive():
            self.log_render_timer.stop()
        keyword = self.log_search_keyword()
        pattern, pattern_error = self.compile_log_search_pattern()
        matches_only = (
            self.widgets.log_search_matches_only_checkbox.isChecked()
            and bool(keyword)
            and pattern_error is None
        )
        html_lines: list[str] = []
        total_matches = 0
        self.visible_log_match_positions = []
        plain_text_offset = 0
        for record in self.log_records:
            if not self.should_show_log(record):
                continue
            message_html, match_count = self.highlight_log_text(record.message, pattern, total_matches)
            if matches_only and match_count == 0:
                continue
            if pattern is not None:
                for match in pattern.finditer(record.message):
                    start, end = match.span()
                    if start == end:
                        continue
                    self.visible_log_match_positions.append((plain_text_offset + start, end - start))
            html_lines.append(
                f'<span style="color: {self.log_color(record)}; white-space: pre-wrap;">'
                f"{message_html}"
                "</span><br/>"
            )
            total_matches += match_count
            plain_text_offset += len(record.message) + 1

        self.visible_log_match_count = total_matches
        scope_text = self.current_log_filter_scope()
        if matches_only:
            scope_text = ui_messages.LOG_SCOPE_WITH_MATCHES_ONLY.format(scope=scope_text)
        if keyword:
            if pattern_error:
                self.current_log_match_index = -1
                self.widgets.log_search_status_label.setText(
                    ui_messages.LOG_SEARCH_INVALID.format(scope=scope_text)
                )
            elif total_matches == 0:
                self.current_log_match_index = -1
                self.widgets.log_search_status_label.setText(
                    ui_messages.LOG_SEARCH_EMPTY.format(scope=scope_text)
                )
            else:
                if self.current_log_match_index < 0:
                    self.current_log_match_index = 0
                elif self.current_log_match_index >= total_matches:
                    self.current_log_match_index = total_matches - 1
                self.widgets.log_search_status_label.setText(
                    ui_messages.LOG_SEARCH_PROGRESS.format(
                        scope=scope_text,
                        current=self.current_log_match_index + 1,
                        total=total_matches,
                    )
                )
        else:
            self.current_log_match_index = -1
            self.widgets.log_search_status_label.setText(
                ui_messages.LOG_SEARCH_IDLE.format(scope=scope_text)
            )

        self.widgets.log_console.setUpdatesEnabled(False)
        html = "".join(html_lines)
        if hasattr(self.widgets.log_console, "set_log_html_preserving_prompt"):
            self.widgets.log_console.set_log_html_preserving_prompt(html)
        else:
            self.widgets.log_console.setHtml(html)
        if keyword and total_matches > 0 and self.current_log_match_index >= 0 and not pattern_error:
            self.focus_current_log_match()
        else:
            self.widgets.log_console.moveCursor(QTextCursor.End)
        self.widgets.log_console.setUpdatesEnabled(True)
        self.widgets.prev_log_match_button.setDisabled(total_matches <= 0 or pattern_error is not None)
        self.widgets.next_log_match_button.setDisabled(total_matches <= 0 or pattern_error is not None)
        self.last_log_view_signature = self.current_log_view_signature()
        self.last_rendered_record_count = len(self.log_records)

    def persist_log(self, message: str) -> None:
        if self.log_file_path is None:
            return
        try:
            self.log_file_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_file_path.open("a", encoding="utf-8") as fp:
                fp.write(message.rstrip() + "\n")
        except OSError as exc:
            self.status_bar.showMessage(
                ui_messages.LOG_WRITE_FAILED_STATUS.format(error=exc)
            )

    def _result_summary_messages(self):
        for record in self.log_records:
            yield record.message

    def _extract_result_summary_urls(self) -> tuple[list[str], int]:
        return extract_result_summary_urls(self._result_summary_messages(), self.RESULT_SUMMARY_URL_PATTERN)

    def _extract_result_summary_activities(self) -> tuple[list[str], int]:
        return extract_result_summary_activities(self._result_summary_messages(), self.RESULT_SUMMARY_ACTIVITY_PATTERNS)

    def _extract_result_summary_jni_registrations(self) -> tuple[list[str], int]:
        return extract_result_summary_jni_registrations(self._result_summary_messages(), self.RESULT_SUMMARY_JNI_PATTERNS)

    def _extract_result_summary_security_hits(self, patterns: tuple[re.Pattern[str], ...]) -> tuple[list[str], int]:
        return extract_result_summary_security_hits(self._result_summary_messages(), patterns)

    def _extract_result_summary_anti_frida_hits(self) -> tuple[list[str], int]:
        return self._extract_result_summary_security_hits(self.RESULT_SUMMARY_ANTI_FRIDA_PATTERNS)

    def _extract_result_summary_root_hits(self) -> tuple[list[str], int]:
        return self._extract_result_summary_security_hits(self.RESULT_SUMMARY_ROOT_PATTERNS)

    def _extract_result_summary_vpn_hits(self) -> tuple[list[str], int]:
        return self._extract_result_summary_security_hits(self.RESULT_SUMMARY_VPN_PATTERNS)

    def build_result_summary_sections(self) -> dict[str, object]:
        sections: dict[str, object] = {}
        for rule in self.RESULT_SUMMARY_CATEGORY_RULES:
            extractor = getattr(self, rule.extractor_name)
            items, total_hits = extractor()
            sections[rule.section_key] = items
            sections[rule.total_hits_key] = total_hits
        return sections

    def build_result_summary_snapshot(self) -> ResultSummarySnapshot:
        return build_result_summary_snapshot(
            self.build_result_summary_sections(),
            category_rules=self.RESULT_SUMMARY_CATEGORY_RULES,
        )

    def build_result_summary_view_model(self) -> ResultSummaryViewModel:
        snapshot = self.build_result_summary_snapshot()
        note_block = build_result_summary_note_block(
            snapshot=snapshot,
            category_rules=self.RESULT_SUMMARY_CATEGORY_RULES,
            empty_title=ui_messages.RESULT_SUMMARY_NOTE_TITLE,
            empty_message=ui_messages.RESULT_SUMMARY_NOTE_EMPTY,
        )
        actions_text = build_result_summary_actions_text(snapshot.actions)
        summary_text = build_result_summary_text(
            snapshot=snapshot,
            has_log_records=bool(self.log_records),
            category_rules=self.RESULT_SUMMARY_CATEGORY_RULES,
            spec=ResultSummaryTextSpec(
                empty_message=ui_messages.RESULT_SUMMARY_EMPTY,
                title=ui_messages.RESULT_SUMMARY_TITLE,
                overview_title=ui_messages.RESULT_SUMMARY_OVERVIEW_TITLE,
                overview_sections_template=ui_messages.RESULT_SUMMARY_OVERVIEW_SECTIONS,
                overview_total_events_template=ui_messages.RESULT_SUMMARY_OVERVIEW_TOTAL_EVENTS,
                overview_unique_items_template=ui_messages.RESULT_SUMMARY_OVERVIEW_UNIQUE_ITEMS,
                next_step_title=ui_messages.RESULT_SUMMARY_NEXT_STEP_TITLE,
            ),
            actions_text=actions_text,
        )
        return ResultSummaryViewModel(
            snapshot=snapshot,
            summary_text=summary_text,
            actions_text=actions_text,
            note_block=note_block,
        )

    def build_result_summary_actions(self) -> list[dict[str, str]]:
        return list(self.build_result_summary_view_model().snapshot.actions)

    def build_result_summary_actions_text(self) -> str:
        return self.build_result_summary_view_model().actions_text

    def build_result_summary_note_block(self) -> str:
        return self.build_result_summary_view_model().note_block

    def build_result_summary_text(self) -> str:
        return self.build_result_summary_view_model().summary_text

    def append_transient_view_message(self, message: str, *, color: str = "#9ad1ff") -> None:
        if not message.strip():
            return
        html_fragment = (
            f'<span style="color: {color}; white-space: pre-wrap;">'
            f"{escape(message.rstrip())}"
            "</span><br/>"
        )
        if hasattr(self.widgets.log_console, "append_log_html_preserving_prompt"):
            self.widgets.log_console.append_log_html_preserving_prompt(html_fragment)
            return
        cursor = self.widgets.log_console.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertHtml(html_fragment)
        self.widgets.log_console.setTextCursor(cursor)
        self.widgets.log_console.ensureCursorVisible()

    def choose_log_file(self) -> None:
        file_path, _ = QFileDialog.getSaveFileName(
            self.owner,
            "选择日志文件",
            str(self.project_root / "hookers_gui.log"),
            "Log Files (*.log);;Text Files (*.txt);;All Files (*.*)",
        )
        if not file_path:
            return
        selected_path = Path(file_path)
        try:
            selected_path.parent.mkdir(parents=True, exist_ok=True)
            selected_path.touch(exist_ok=True)
            with selected_path.open("a", encoding="utf-8") as fp:
                if selected_path.stat().st_size == 0 and self.log_records:
                    for record in self.log_records:
                        fp.write(record.message.rstrip() + "\n")
        except OSError as exc:
            QMessageBox.critical(
                self.owner,
                ui_messages.LOG_FILE_UNAVAILABLE_TITLE,
                ui_messages.LOG_FILE_UNAVAILABLE_BODY.format(error=exc),
            )
            self.status_bar.showMessage(
                ui_messages.LOG_FILE_UNAVAILABLE_STATUS.format(error=exc)
            )
            return

        self.log_file_path = selected_path
        self.widgets.choose_log_file_button.setToolTip(str(self.log_file_path))
        self.append_log(f"[*] 日志文件已启用：{self.log_file_path}")

    def clear_logs(self) -> None:
        if self.log_render_timer.isActive():
            self.log_render_timer.stop()
        self.log_records.clear()
        self.last_rendered_record_count = 0
        self.render_logs()
        self.status_bar.showMessage(ui_messages.LOG_DISPLAY_CLEARED)

    def append_log(self, message: str) -> None:
        normalized_message = message.rstrip()
        record = self.classify_log(normalized_message)
        if record.category == "js":
            normalized_message = self.normalize_js_log_message(normalized_message)
            record = self.classify_log(normalized_message)
            if self.is_effectively_empty_js_log(record.message):
                last_record = self.log_records[-1] if self.log_records else None
                if last_record and self.is_effectively_empty_js_log(last_record.message):
                    return
        self.log_records.append(record)

        overflow = 0
        if len(self.log_records) > self.MAX_LOG_RECORDS:
            overflow = len(self.log_records) - self.MAX_LOG_RECORDS
            del self.log_records[:overflow]

        self.persist_log(record.message)
        if self.can_incrementally_append_log(record, overflow):
            self.append_log_record_to_console(record)
            self.last_rendered_record_count = len(self.log_records)
        else:
            self.schedule_log_render()
