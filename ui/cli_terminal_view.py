from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QTextCursor
from PySide6.QtWidgets import QTextEdit


class CliTerminalView(QTextEdit):
    command_submitted = Signal(str)
    history_previous_requested = Signal()
    history_next_requested = Signal()
    tab_completion_requested = Signal()
    input_edited = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cli_mode_enabled = False
        self._prompt_text = "hooker >"
        self.setReadOnly(True)
        self.setAcceptRichText(False)
        self.setUndoRedoEnabled(False)

    def cli_mode_enabled(self) -> bool:
        return self._cli_mode_enabled

    def prompt_prefix(self) -> str:
        return f"{self._prompt_text} "

    def set_prompt_text(self, prompt_text: str) -> None:
        self._prompt_text = prompt_text
        if self._cli_mode_enabled:
            current_input = self.current_input_text()
            self._remove_prompt_line()
            self._append_prompt_line(current_input)

    def set_cli_mode_enabled(self, enabled: bool) -> None:
        if self._cli_mode_enabled == enabled:
            return
        self._cli_mode_enabled = enabled
        if enabled:
            self.setReadOnly(False)
            self._append_prompt_line("")
            self.focus_input_end()
            return
        self._remove_prompt_line()
        self.setReadOnly(True)

    def current_input_text(self) -> str:
        block = self.document().lastBlock()
        text = block.text()
        prefix = self.prompt_prefix()
        if text.startswith(prefix):
            return text[len(prefix):]
        return ""

    def set_current_input_text(self, text: str) -> None:
        if not self._cli_mode_enabled:
            return
        block = self.document().lastBlock()
        prefix = self.prompt_prefix()
        cursor = QTextCursor(block)
        cursor.setPosition(block.position() + len(prefix))
        cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
        cursor.removeSelectedText()
        cursor.insertText(text)
        self.setTextCursor(cursor)
        self.focus_input_end()
        self.input_edited.emit(text)

    def focus_input_end(self) -> None:
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def selectAll(self) -> None:  # noqa: N802
        cursor = self.textCursor()
        cursor.select(QTextCursor.Document)
        self.setTextCursor(cursor)

    def prompt_start_position(self) -> int:
        return self.document().lastBlock().position() + len(self.prompt_prefix())

    def _cursor_touches_protected_region(self, cursor: QTextCursor, prompt_start: int) -> bool:
        if not cursor.hasSelection():
            return cursor.position() < prompt_start
        return min(cursor.selectionStart(), cursor.selectionEnd()) < prompt_start

    def _move_cursor_to_input_end(self) -> None:
        cursor = self.textCursor()
        cursor.clearSelection()
        cursor.movePosition(QTextCursor.End)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def append_log_html_preserving_prompt(self, html_fragment: str) -> None:
        current_input = self.current_input_text() if self._cli_mode_enabled else ""
        if self._cli_mode_enabled:
            self._remove_prompt_line()
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertHtml(html_fragment)
        self.setTextCursor(cursor)
        if self._cli_mode_enabled:
            self._append_prompt_line(current_input)
        else:
            self.ensureCursorVisible()

    def set_log_html_preserving_prompt(self, html: str) -> None:
        current_input = self.current_input_text() if self._cli_mode_enabled else ""
        self.setHtml(html)
        if self._cli_mode_enabled:
            self._append_prompt_line(current_input)
        else:
            self.moveCursor(QTextCursor.End)

    def _append_prompt_line(self, current_input: str) -> None:
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        last_block = self.document().lastBlock()
        if self.document().characterCount() > 1 and last_block.text():
            cursor.insertBlock()
        cursor.insertText(f"{self.prompt_prefix()}{current_input}")
        self.setTextCursor(cursor)
        self.focus_input_end()

    def _remove_prompt_line(self) -> str:
        block = self.document().lastBlock()
        prefix = self.prompt_prefix()
        text = block.text()
        if not text.startswith(prefix):
            return ""
        current_input = text[len(prefix):]
        cursor = QTextCursor(block)
        cursor.select(QTextCursor.BlockUnderCursor)
        cursor.removeSelectedText()
        if cursor.position() > 0:
            cursor.deletePreviousChar()
        self.setTextCursor(cursor)
        return current_input

    def insertPlainText(self, text: str) -> None:  # noqa: N802
        if self._cli_mode_enabled:
            cursor = self.textCursor()
            prompt_start = self.prompt_start_position()
            if self._cursor_touches_protected_region(cursor, prompt_start):
                self._move_cursor_to_input_end()
            text = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
        super().insertPlainText(text)
        if self._cli_mode_enabled:
            self.input_edited.emit(self.current_input_text())

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if not self._cli_mode_enabled:
            super().keyPressEvent(event)
            return

        key = event.key()
        cursor = self.textCursor()
        prompt_start = self.prompt_start_position()

        if event.matches(QKeySequence.Copy):
            selected = self.textCursor().selectedText().replace("\u2029", "\n")
            if selected:
                QGuiApplication.clipboard().setText(selected)
            return
        if event.matches(QKeySequence.SelectAll):
            self.selectAll()
            return

        if key in (Qt.Key_Return, Qt.Key_Enter):
            self.command_submitted.emit(self.current_input_text())
            return
        if key == Qt.Key_Tab:
            self.tab_completion_requested.emit()
            return
        if key == Qt.Key_Up:
            self.history_previous_requested.emit()
            return
        if key == Qt.Key_Down:
            self.history_next_requested.emit()
            return
        if key == Qt.Key_Home:
            cursor.setPosition(prompt_start)
            self.setTextCursor(cursor)
            return
        if key == Qt.Key_Left and cursor.position() <= prompt_start:
            return
        if key == Qt.Key_Backspace and cursor.position() <= prompt_start and not cursor.hasSelection():
            return
        if key == Qt.Key_Delete and cursor.position() < prompt_start and not cursor.hasSelection():
            return
        if key in (Qt.Key_PageUp, Qt.Key_PageDown):
            super().keyPressEvent(event)
            return

        if self._cursor_touches_protected_region(cursor, prompt_start):
            is_navigation = key in (
                Qt.Key_Left,
                Qt.Key_Right,
                Qt.Key_Up,
                Qt.Key_Down,
                Qt.Key_Shift,
                Qt.Key_Control,
                Qt.Key_Alt,
            )
            if not is_navigation:
                self._move_cursor_to_input_end()

        super().keyPressEvent(event)
        self.input_edited.emit(self.current_input_text())
