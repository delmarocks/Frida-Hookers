from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent

from ui import ui_messages
from ui.main_window import MainWindow, MainWindowDependencies


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


def log_messages(window) -> list[str]:
    return [record.message for record in window.log_panel_controller.log_records]


def prepare_current_app(window, dummy_deps, package_name: str = "pkg.default") -> None:
    app = dummy_deps.device_service.ensure_result
    app.identifier = package_name
    dummy_deps.context.current_app = app
    window.app_combo.addItem(app.name, app.identifier)
    window.app_combo.setCurrentIndex(0)
    window.terminal_console_controller.update_prompt()


def test_terminal_help_logs_available_commands(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    window.terminal_console_controller.submit_command("help")

    messages = log_messages(window)
    assert messages[-2] == ui_messages.TERMINAL_COMMAND_ECHO.format(
        prompt=ui_messages.TERMINAL_PROMPT_EMPTY,
        command="help",
    )
    assert "基础命令" in messages[-1]
    assert "查询命令" in messages[-1]
    assert "attach okhttp.js" in messages[-1]
    window.deleteLater()


def test_terminal_command_echo_uses_selected_app_prompt(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps, "pkg.demo")

    window.terminal_console_controller.submit_command("help")

    assert log_messages(window)[-2] == ui_messages.TERMINAL_COMMAND_ECHO.format(
        prompt=ui_messages.TERMINAL_PROMPT_READY.format(package="pkg.demo"),
        command="help",
    )
    window.deleteLater()


def test_terminal_embedded_repl_keeps_new_command_on_new_line(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    window.terminal_console_controller.set_cli_mode_enabled(True)

    window.terminal_console_controller.submit_command("help")
    window.terminal_console_controller.submit_command("apps")
    window.log_panel_controller.render_logs()

    transcript = window.log_console.toPlainText()
    assert "[CMD] hooker > help\n" in transcript
    assert "\n[CMD] hooker > apps\n" in transcript
    assert "select com.demo.app[CMD] hooker > apps" not in transcript
    window.deleteLater()


def test_terminal_updates_prompt_for_selected_app(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps, "pkg.demo")
    assert window.terminal_console_controller.current_transcript_prompt() == (
        ui_messages.TERMINAL_PROMPT_READY.format(package="pkg.demo")
    )
    window.deleteLater()


def test_terminal_ls_outputs_workspace_script_names(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    dummy_deps.workspace_service.names_by_package["pkg.default"] = ["a.js", "b.js"]
    hookers_js_dir = dummy_deps.context.hookers_js_dir
    hookers_js_dir.mkdir(parents=True, exist_ok=True)
    (hookers_js_dir / "builtin.js").write_text("// builtin", encoding="utf-8")

    window.terminal_console_controller.submit_command("ls")

    output = log_messages(window)[-1]
    assert ui_messages.TERMINAL_LS_WORKSPACE_TITLE in output
    assert "a.js" in output
    assert "b.js" in output
    assert ui_messages.TERMINAL_LS_BUILTIN_TITLE in output
    assert "builtin.js" in output
    window.deleteLater()


def test_terminal_ls_shows_empty_sections_when_no_scripts(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)

    window.terminal_console_controller.submit_command("ls")

    output = log_messages(window)[-1]
    assert ui_messages.TERMINAL_LS_WORKSPACE_TITLE in output
    assert ui_messages.TERMINAL_LS_BUILTIN_TITLE in output
    assert output.count(ui_messages.TERMINAL_LS_EMPTY) >= 1
    window.deleteLater()


def test_terminal_ls_shows_empty_builtin_section_when_builtin_dir_is_empty(qapp, dummy_deps, tmp_path) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    dummy_deps.context.hookers_js_dir = tmp_path / "empty_builtin_js"
    dummy_deps.context.hookers_js_dir.mkdir(parents=True, exist_ok=True)

    window.terminal_console_controller.submit_command("ls")

    output = log_messages(window)[-1]
    assert ui_messages.TERMINAL_LS_BUILTIN_TITLE in output
    assert output.count(ui_messages.TERMINAL_LS_EMPTY) >= 1
    window.deleteLater()


def test_terminal_apps_lists_cached_apps_without_selected_app(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    dummy_deps.context.apps = [
        dummy_deps.device_service.ensure_result,
        type("App", (), {"name": "Other", "identifier": "pkg.other", "pid": None})(),
    ]

    window.terminal_console_controller.submit_command("apps")

    output = log_messages(window)[-1]
    assert "pkg.default" in output
    assert "pkg.other" in output
    window.deleteLater()


def test_terminal_attach_and_spawn_dispatch_to_hook_runtime(qapp, dummy_deps, monkeypatch) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    captured: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        window.hook_runtime_controller,
        "start_script_command",
        lambda script_name, use_spawn: captured.append((script_name, use_spawn)),
    )

    window.terminal_console_controller.submit_command("attach demo.js")
    window.terminal_console_controller.submit_command("spawn demo.js")

    assert captured == [("demo.js", False), ("demo.js", True)]
    window.deleteLater()


def test_terminal_restart_and_stop_dispatch_to_hook_runtime(qapp, dummy_deps, monkeypatch) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    calls: list[str] = []
    monkeypatch.setattr(window.hook_runtime_controller, "restart_current_app", lambda: calls.append("restart"))
    monkeypatch.setattr(window.hook_runtime_controller, "stop_hook", lambda: calls.append("stop"))

    window.terminal_console_controller.submit_command("restart")
    assert calls == ["restart"]

    window.terminal_console_controller.submit_command("stop")
    assert ui_messages.TERMINAL_STOP_NO_SESSION in log_messages(window)[-1]

    dummy_deps.context.active_session = type("Session", (), {"mode": "attach"})()
    window.terminal_console_controller.submit_command("stop")
    assert calls == ["restart", "stop"]
    window.deleteLater()


def test_terminal_unknown_and_missing_argument_commands_log_clear_messages(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    assert ui_messages.TERMINAL_UNKNOWN_COMMAND not in log_messages(window)

    window.terminal_console_controller.submit_command("object")
    assert log_messages(window)[-1] == ui_messages.TERMINAL_MISSING_ARGUMENT.format(
        command="object"
    )
    window.deleteLater()


def test_terminal_select_switches_current_package(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    app = dummy_deps.device_service.ensure_result
    dummy_deps.context.apps = [
        app,
        type("App", (), {"name": "Other", "identifier": "pkg.other", "pid": 99})(),
    ]
    window.app_combo.addItem("App", "pkg.default")
    window.app_combo.addItem("Other", "pkg.other")
    window.app_combo.setCurrentIndex(0)

    window.terminal_console_controller.submit_command("select pkg.other")

    assert window.app_combo.currentData() == "pkg.other"
    assert log_messages(window)[-1] == ui_messages.TERMINAL_SELECT_APP_LOG.format(
        package="pkg.other"
    )
    window.deleteLater()


def test_terminal_refresh_updates_app_list(qapp, dummy_deps, monkeypatch) -> None:
    monkeypatch.setattr("ui.terminal_console.QThread", _FakeThread)
    monkeypatch.setattr("ui.terminal_console.ActionWorker", _FakeWorker)
    window = build_main_window(dummy_deps)
    dummy_deps.device_service.refresh_result = [
        type("App", (), {"name": "A", "identifier": "pkg.a", "pid": 11})(),
        type("App", (), {"name": "B", "identifier": "pkg.b", "pid": None})(),
    ]

    window.terminal_console_controller.submit_command("refresh")

    assert window.app_combo.count() == 2
    assert log_messages(window)[-1] == ui_messages.TERMINAL_RESULT_LOG.format(
        message="已刷新 App 列表：2 个"
    )
    window.deleteLater()


def test_terminal_refresh_marks_context_busy_until_worker_finishes(qapp, dummy_deps, monkeypatch) -> None:
    class _BlockingFakeThread(_FakeThread):
        def start(self) -> None:
            return None

    monkeypatch.setattr("ui.terminal_console.QThread", _BlockingFakeThread)
    monkeypatch.setattr("ui.terminal_console.ActionWorker", _FakeWorker)
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps, "pkg.demo")

    window.terminal_console_controller.submit_command("refresh")
    assert window.terminal_console_controller.terminal_command_busy is True
    assert ui_messages.TERMINAL_BUSY_LOG in log_messages(window)
    window.deleteLater()


def test_terminal_sync_commands_do_not_mark_context_busy(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps, "pkg.demo")

    window.terminal_console_controller.submit_command("help")
    assert window.terminal_console_controller.terminal_command_busy is False
    window.deleteLater()


def test_terminal_tab_completion_suggests_commands_and_scripts(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    dummy_deps.workspace_service.names_by_package["pkg.default"] = ["alpha.js", "beta.js"]
    dummy_deps.context.apps = [dummy_deps.device_service.ensure_result]
    hookers_js_dir = dummy_deps.context.hookers_js_dir
    hookers_js_dir.mkdir(parents=True, exist_ok=True)
    (hookers_js_dir / "builtin.js").write_text("// builtin", encoding="utf-8")

    command_suggestions = window.terminal_console_controller.build_completions("he")
    assert [candidate.display_text for candidate in command_suggestions] == ["命令: help"]

    apps_suggestions = window.terminal_console_controller.build_completions("ap")
    assert [candidate.display_text for candidate in apps_suggestions] == ["命令: apps"]

    script_suggestions = window.terminal_console_controller.build_completions("attach a")
    assert "脚本: alpha.js" in [candidate.display_text for candidate in script_suggestions]
    assert "脚本: builtin.js" not in [candidate.display_text for candidate in script_suggestions]

    all_script_suggestions = window.terminal_console_controller.build_completions("spawn ")
    assert "脚本: alpha.js" in [candidate.display_text for candidate in all_script_suggestions]
    assert "脚本: builtin.js" in [candidate.display_text for candidate in all_script_suggestions]
    select_suggestions = window.terminal_console_controller.build_completions("select pkg")
    assert "包名: pkg.default" in [candidate.display_text for candidate in select_suggestions]
    window.deleteLater()


def test_terminal_live_completion_popup_appears_while_typing(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    window.terminal_console_controller.set_cli_mode_enabled(True)

    window.log_console.set_current_input_text("he")
    qapp.processEvents()

    assert window.terminal_console_controller.completer_model.stringList() == ["命令: help"]
    assert window.terminal_console_controller.completer.popup().isVisible()
    window.deleteLater()


def test_terminal_tab_key_applies_current_popup_completion(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    window.terminal_console_controller.set_cli_mode_enabled(True)

    window.log_console.set_current_input_text("he")
    qapp.processEvents()
    assert window.terminal_console_controller.completer.popup().isVisible()

    window.terminal_console_controller.complete_current_input()
    assert window.log_console.current_input_text() == "help"
    assert not window.terminal_console_controller.completer.popup().isVisible()
    window.deleteLater()


def test_terminal_completion_popup_rect_is_positioned_below_current_input_line(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    window.terminal_console_controller.set_cli_mode_enabled(True)
    window.log_console.set_current_input_text("he")
    qapp.processEvents()

    cursor_rect = window.log_console.cursorRect()
    popup_rect = window.terminal_console_controller._completion_popup_rect()
    assert popup_rect.y() > cursor_rect.y()
    assert popup_rect.width() >= window.log_console.viewport().width() // 2
    window.deleteLater()


def test_terminal_tab_completion_opens_popup_for_single_match_and_applies_on_selection(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    dummy_deps.workspace_service.names_by_package["pkg.default"] = ["only.js"]
    window.terminal_console_controller.set_cli_mode_enabled(True)

    window.log_console.set_current_input_text("att")
    assert window.terminal_console_controller.completer_model.stringList() == ["命令: attach"]
    assert window.log_console.current_input_text() == "att"
    window.terminal_console_controller.complete_current_input()
    assert window.log_console.current_input_text() == "attach"

    window.log_console.set_current_input_text("attach on")
    assert window.terminal_console_controller.completer_model.stringList() == ["脚本: only.js"]
    assert window.log_console.current_input_text() == "attach on"
    window.terminal_console_controller.complete_current_input()
    assert window.log_console.current_input_text() == "attach only.js"
    window.deleteLater()


def test_terminal_tab_completion_opens_popup_for_single_package_match_and_applies_on_selection(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    dummy_deps.context.apps = [dummy_deps.device_service.ensure_result]
    window.terminal_console_controller.set_cli_mode_enabled(True)

    window.log_console.set_current_input_text("select pkg")
    assert window.terminal_console_controller.completer_model.stringList() == ["包名: pkg.default"]
    assert window.log_console.current_input_text() == "select pkg"
    window.terminal_console_controller.complete_current_input()
    assert window.log_console.current_input_text() == "select pkg.default"
    window.deleteLater()


def test_terminal_completion_does_not_mix_categories(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    dummy_deps.workspace_service.names_by_package["pkg.default"] = ["alpha.js", "beta.js"]
    dummy_deps.context.apps = [dummy_deps.device_service.ensure_result]

    command_candidates = window.terminal_console_controller.build_completions("sp")
    assert all(candidate.display_text.startswith("命令: ") for candidate in command_candidates)

    script_candidates = window.terminal_console_controller.build_completions("spawn ")
    assert all(candidate.display_text.startswith("脚本: ") for candidate in script_candidates)

    package_candidates = window.terminal_console_controller.build_completions("select pkg")
    assert all(candidate.display_text.startswith("包名: ") for candidate in package_candidates)
    window.deleteLater()


class _FakeSignal:
    def __init__(self) -> None:
        self.callbacks = []

    def connect(self, callback) -> None:
        self.callbacks.append(callback)

    def emit(self, *args, **kwargs) -> None:
        for callback in list(self.callbacks):
            callback(*args, **kwargs)


class _FakeThread:
    def __init__(self, _owner=None) -> None:
        self.started = _FakeSignal()
        self.finished = _FakeSignal()

    def start(self) -> None:
        self.started.emit()

    def quit(self) -> None:
        self.finished.emit()

    def deleteLater(self) -> None:
        return None


class _FakeWorker:
    def __init__(self, action) -> None:
        self.action = action
        self.succeeded = _FakeSignal()
        self.failed = _FakeSignal()
        self.finished = _FakeSignal()

    def moveToThread(self, _thread) -> None:
        return None

    def run(self) -> None:
        result = self.action()
        self.succeeded.emit(result)
        self.finished.emit()

    def deleteLater(self) -> None:
        return None


class _FakeProcess:
    def __init__(self, _owner=None) -> None:
        self.readyReadStandardOutput = _FakeSignal()
        self.readyReadStandardError = _FakeSignal()
        self.finished = _FakeSignal()
        self.errorOccurred = _FakeSignal()
        self.program = ""
        self.arguments = []
        self.cwd = str(Path.cwd())
        self._stdout = b""
        self._stderr = b""

    def setProgram(self, program: str) -> None:
        self.program = program

    def setArguments(self, arguments) -> None:
        self.arguments = list(arguments)

    def setWorkingDirectory(self, cwd: str) -> None:
        self.cwd = cwd

    def start(self) -> None:
        command = self.arguments[-1]
        output, error = self._simulate(command)
        self._stderr = error.encode("utf-8")
        if self._stderr:
            self.readyReadStandardError.emit()
        self._stdout = output.encode("utf-8")
        self.readyReadStandardOutput.emit()
        self.finished.emit(0, 0)

    def _simulate(self, command: str) -> tuple[str, str]:
        lowered = command.lower()
        if command == "frida-ps":
            return "frida-ps\r\n", ""
        if command == "frida version":
            return "16.2.1\r\n", ""
        if command == "frida-error":
            return "", "boom\r\n"
        if command == "Write-Output hello":
            return "hello\r\n", ""
        return f"{command}\r\n", ""

    def readAllStandardOutput(self) -> bytes:
        data = self._stdout
        self._stdout = b""
        return data

    def readAllStandardError(self) -> bytes:
        data = self._stderr
        self._stderr = b""
        return data

    def deleteLater(self) -> None:
        return None


def test_terminal_rpc_commands_log_results_and_generate_script(qapp, dummy_deps, monkeypatch) -> None:
    monkeypatch.setattr("ui.terminal_console.QThread", _FakeThread)
    monkeypatch.setattr("ui.terminal_console.ActionWorker", _FakeWorker)
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)

    window.terminal_console_controller.submit_command("a")
    assert "Activity 信息" in log_messages(window)[-1]

    window.terminal_console_controller.submit_command("object demo.Target")
    assert "demo.Target" in log_messages(window)[-1]

    generated_path = Path.cwd() / "workspaces" / "pkg.default" / "js" / "demo.js"
    dummy_deps.rpc_service.generate_hook_script = lambda hook_target: generated_path
    window.terminal_console_controller.submit_command("gs demo")
    assert log_messages(window)[-1] == ui_messages.TERMINAL_GENERATE_SCRIPT_LOG.format(
        script_path=generated_path
    )
    window.deleteLater()


def test_terminal_rpc_command_ignores_reentry_while_worker_is_running(qapp, dummy_deps, monkeypatch) -> None:
    class _BlockingFakeThread(_FakeThread):
        def start(self) -> None:
            return None

    monkeypatch.setattr("ui.terminal_console.QThread", _BlockingFakeThread)
    monkeypatch.setattr("ui.terminal_console.ActionWorker", _FakeWorker)
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)

    window.terminal_console_controller.submit_command("a")
    first_thread = window.terminal_console_controller.command_thread
    window.terminal_console_controller.submit_command("a")

    assert window.terminal_console_controller.command_thread is first_thread
    window.deleteLater()


def test_terminal_unknown_command_falls_back_to_powershell(qapp, dummy_deps, monkeypatch) -> None:
    monkeypatch.setattr("ui.terminal_console.QProcess", _FakeProcess)
    window = build_main_window(dummy_deps)

    window.terminal_console_controller.submit_command("frida-ps")

    messages = log_messages(window)
    assert ui_messages.TERMINAL_SHELL_FALLBACK_LOG in messages
    assert "frida-ps" in messages[-1]
    assert not any("未知命令" in message for message in messages)
    window.deleteLater()


def test_terminal_non_frida_external_command_is_blocked(qapp, dummy_deps, monkeypatch) -> None:
    monkeypatch.setattr("ui.terminal_console.QProcess", _FakeProcess)
    window = build_main_window(dummy_deps)

    window.terminal_console_controller.submit_command("pwd")

    assert log_messages(window)[-1] == ui_messages.TERMINAL_EXTERNAL_COMMAND_BLOCKED.format(
        command="pwd"
    )
    window.deleteLater()


def test_terminal_shell_stderr_is_prefixed(qapp, dummy_deps, monkeypatch) -> None:
    monkeypatch.setattr("ui.terminal_console.QProcess", _FakeProcess)
    window = build_main_window(dummy_deps)

    window.terminal_console_controller.submit_command("frida-error")

    assert log_messages(window)[-1] == f"{ui_messages.TERMINAL_SHELL_STDERR_PREFIX} boom"
    window.deleteLater()


def test_terminal_shell_commands_queue_while_process_is_busy(qapp, dummy_deps, monkeypatch) -> None:
    class _QueuedFakeProcess(_FakeProcess):
        finish_immediately = False

        def start(self) -> None:
            command = self.arguments[-1]
            output, error = self._simulate(command)
            self._stderr = error.encode("utf-8")
            if self._stderr:
                self.readyReadStandardError.emit()
            self._stdout = output.encode("utf-8")
            self.readyReadStandardOutput.emit()

    monkeypatch.setattr("ui.terminal_console.QProcess", _QueuedFakeProcess)
    window = build_main_window(dummy_deps)

    window.terminal_console_controller.submit_command("frida-ps")
    process = window.terminal_console_controller.shell_process
    assert process is not None
    window.terminal_console_controller.submit_command("frida version")
    assert log_messages(window)[-1] == ui_messages.TERMINAL_SHELL_BUSY_LOG
    process.finished.emit(0, 0)
    assert window.terminal_console_controller.shell_process is None
    window.deleteLater()


def test_terminal_cli_mode_allows_copy_of_output(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    window.terminal_console_controller.set_cli_mode_enabled(True)
    window.terminal_console_controller.submit_command("help")
    window.log_panel_controller.render_logs()
    window.log_console.selectAll()

    event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_C, Qt.ControlModifier)
    window.log_console.keyPressEvent(event)

    assert "可用命令" in qapp.clipboard().text()
    window.deleteLater()
