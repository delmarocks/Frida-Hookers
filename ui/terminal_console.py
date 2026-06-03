from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QThread, Qt, QStringListModel, QRect
from PySide6.QtWidgets import QCompleter, QPushButton, QWidget

from core.errors import HookersError, RpcCallError, RpcTargetMissingError, to_ui_error_payload

from .controller_types import (
    AppsPayloadApplier,
    BusySetter,
    EnsureCurrentAppReady,
    ErrorPresenter,
    GuiDepsLike,
    LogAppender,
    ScriptRootApplier,
    SelectedPackageProvider,
    StatusSetter,
)
from .hook_runtime import HookRuntimeController
from .ui_thread_dispatcher import UiThreadDispatcher
from .workers.action_worker import ActionWorker
from . import ui_messages
from .cli_terminal_view import CliTerminalView


@dataclass
class TerminalConsoleWidgets:
    terminal_view: CliTerminalView
    terminal_cli_mode_button: QPushButton
    app_combo: object


@dataclass(frozen=True)
class _CompletionCandidate:
    kind: str
    value: str
    insert_text: str
    display_text: str


class TerminalConsoleController(QObject):
    COMMAND_WORDS = (
        "help",
        "h",
        "ls",
        "pid",
        "uid",
        "activitys",
        "a",
        "services",
        "s",
        "object",
        "o",
        "oe",
        "view",
        "v",
        "gs",
        "attach",
        "spawn",
        "restart",
        "stop",
        "apps",
        "refresh",
        "select",
    )

    def __init__(
        self,
        owner: QWidget,
        widgets: TerminalConsoleWidgets,
        deps: GuiDepsLike,
        *,
        set_busy: BusySetter,
        set_status_text: StatusSetter,
        append_log: LogAppender,
        show_worker_error: ErrorPresenter,
        ensure_current_app_ready: EnsureCurrentAppReady,
        selected_package_name: SelectedPackageProvider,
        apply_apps_payload: AppsPayloadApplier,
        apply_script_root: ScriptRootApplier,
        hook_runtime: HookRuntimeController,
    ) -> None:
        super().__init__(owner)
        self.owner = owner
        self.widgets = widgets
        self.deps = deps
        self.set_busy = set_busy
        self.set_status_text = set_status_text
        self.append_log = append_log
        self.show_worker_error = show_worker_error
        self.ensure_current_app_ready = ensure_current_app_ready
        self.selected_package_name = selected_package_name
        self.apply_apps_payload = apply_apps_payload
        self.apply_script_root = apply_script_root
        self.hook_runtime = hook_runtime

        self.command_thread: QThread | None = None
        self.command_worker: ActionWorker | None = None
        self.terminal_command_busy = False
        self.shell_process: QProcess | None = None
        self.shell_command_busy = False
        self.shell_output_buffer = ""
        self.shell_error_buffer = ""
        self.ui_dispatcher = UiThreadDispatcher(owner)
        self.command_history: list[str] = []
        self.history_index: int | None = None
        self.completer_model = QStringListModel(self)
        self.completer = QCompleter(self.completer_model, self)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.completer.activated.connect(self.apply_completion)
        self.completer.setWidget(self.widgets.terminal_view)
        self.current_completion_candidates: list[_CompletionCandidate] = []
        self.current_completion_map: dict[str, _CompletionCandidate] = {}
        self.cli_mode_enabled = False

        self.widgets.terminal_view.command_submitted.connect(self.submit_command)
        self.widgets.terminal_view.history_previous_requested.connect(self.show_previous_history)
        self.widgets.terminal_view.history_next_requested.connect(self.show_next_history)
        self.widgets.terminal_view.tab_completion_requested.connect(self.complete_current_input)
        self.widgets.terminal_view.input_edited.connect(self.refresh_completions)
        self.update_prompt()
        self.refresh_completions()

    def toggle_cli_mode(self) -> None:
        self.set_cli_mode_enabled(not self.cli_mode_enabled)

    def set_cli_mode_enabled(self, enabled: bool) -> None:
        self.cli_mode_enabled = enabled
        self.widgets.terminal_cli_mode_button.setText(
            ui_messages.CLI_MODE_EXIT_BUTTON if enabled else ui_messages.CLI_MODE_ENTER_BUTTON
        )
        self.widgets.terminal_view.set_cli_mode_enabled(enabled)
        self.update_prompt()
        if enabled:
            self.widgets.terminal_view.focus_input_end()

    def set_terminal_command_busy(self, busy: bool) -> None:
        self.terminal_command_busy = busy

    def current_transcript_prompt(self) -> str:
        package_name = self.selected_package_name()
        if not package_name:
            return ui_messages.TERMINAL_PROMPT_EMPTY
        return ui_messages.TERMINAL_PROMPT_READY.format(package=package_name)

    def update_prompt(self) -> None:
        self.widgets.terminal_view.set_prompt_text(self.current_transcript_prompt())

    def show_previous_history(self) -> None:
        if not self.command_history:
            return
        if self.history_index is None:
            self.history_index = len(self.command_history) - 1
        elif self.history_index > 0:
            self.history_index -= 1
        self.widgets.terminal_view.set_current_input_text(self.command_history[self.history_index])
        self.refresh_completions()

    def show_next_history(self) -> None:
        if not self.command_history:
            return
        if self.history_index is None:
            return
        if self.history_index >= len(self.command_history) - 1:
            self.history_index = None
            self.widgets.terminal_view.set_current_input_text("")
            self.refresh_completions()
            return
        self.history_index += 1
        self.widgets.terminal_view.set_current_input_text(self.command_history[self.history_index])
        self.refresh_completions()

    def refresh_completions(self, text: str | None = None) -> None:
        current_text = self.widgets.terminal_view.current_input_text() if text is None else text
        candidates = self.build_completions(current_text)
        self.current_completion_candidates = candidates
        self.current_completion_map = {
            candidate.display_text: candidate for candidate in candidates
        }
        self.completer_model.setStringList([candidate.display_text for candidate in candidates])
        self.completer.setCompletionPrefix(current_text)
        if text is not None:
            self._update_live_completion_popup(current_text, candidates)

    def build_completions(self, text: str) -> list[_CompletionCandidate]:
        stripped = text.lstrip()
        if not stripped:
            return self._build_command_candidates(self.COMMAND_WORDS)

        verb, separator, raw_args = stripped.partition(" ")
        lowered_verb = verb.lower()
        if not separator:
            return self._build_command_candidates(
                command for command in self.COMMAND_WORDS if command.startswith(lowered_verb)
            )

        arg_prefix = raw_args.strip()
        if lowered_verb == "select":
            package_names = [
                package_name
                for package_name in self.available_package_names()
                if not arg_prefix or package_name.lower().startswith(arg_prefix.lower())
            ]
            return [
                _CompletionCandidate(
                    kind="package",
                    value=package_name,
                    insert_text=f"{lowered_verb} {package_name}",
                    display_text=f"{ui_messages.TERMINAL_COMPLETION_PACKAGE_PREFIX}: {package_name}",
                )
                for package_name in package_names
            ]
        if lowered_verb not in ("attach", "spawn"):
            return []

        script_names = [
            script_name
            for script_name in self.available_script_names()
            if not arg_prefix or script_name.lower().startswith(arg_prefix.lower())
        ]
        return [
            _CompletionCandidate(
                kind="script",
                value=script_name,
                insert_text=f"{lowered_verb} {script_name}",
                display_text=f"{ui_messages.TERMINAL_COMPLETION_SCRIPT_PREFIX}: {script_name}",
            )
            for script_name in script_names
        ]

    def _build_command_candidates(self, commands) -> list[_CompletionCandidate]:
        return [
            _CompletionCandidate(
                kind="command",
                value=command,
                insert_text=command,
                display_text=f"{ui_messages.TERMINAL_COMPLETION_COMMAND_PREFIX}: {command}",
            )
            for command in sorted(set(commands), key=str.lower)
        ]

    def available_script_names(self) -> list[str]:
        names: set[str] = set()
        package_name = self.selected_package_name()
        if package_name:
            try:
                names.update(self.deps.workspace_service.script_names(package_name))
            except Exception:
                pass
        try:
            for path in sorted(self.deps.context.hookers_js_dir.glob("*.js")):
                names.add(path.name)
        except Exception:
            pass
        return sorted(names, key=str.lower)

    def available_package_names(self) -> list[str]:
        names = [app.identifier for app in self.deps.context.apps if app.identifier]
        return sorted(set(names), key=str.lower)

    def complete_current_input(self) -> None:
        popup = self.completer.popup()
        if popup.isVisible():
            current_index = popup.currentIndex()
            if current_index.isValid():
                completion = current_index.data()
                if isinstance(completion, str):
                    self.apply_completion(completion)
                    popup.hide()
                    return
        self.refresh_completions()
        completion_count = len(self.current_completion_candidates)
        if completion_count <= 0:
            return
        if completion_count == 1:
            self.apply_completion(self.current_completion_candidates[0].display_text)
            popup.hide()
            return
        popup.setCurrentIndex(self.completer_model.index(0, 0))
        self.completer.complete(self._completion_popup_rect())

    def _update_live_completion_popup(
        self,
        current_text: str,
        candidates: list[_CompletionCandidate],
    ) -> None:
        popup = self.completer.popup()
        if not self.cli_mode_enabled or not current_text:
            popup.hide()
            return
        if not candidates:
            popup.hide()
            return
        popup.setCurrentIndex(self.completer_model.index(0, 0))
        self.completer.complete(self._completion_popup_rect())

    def _completion_popup_rect(self) -> QRect:
        popup = self.completer.popup()
        popup_width = max(
            self.widgets.terminal_view.viewport().width() // 2,
            popup.sizeHintForColumn(0) + popup.verticalScrollBar().sizeHint().width() + 24,
        )
        rect = QRect(self.widgets.terminal_view.cursorRect())
        rect.translate(0, rect.height() + 6)
        rect.setX(max(0, rect.x() - 8))
        rect.setWidth(popup_width)
        return rect

    def apply_completion(self, completion: str) -> None:
        candidate = self.current_completion_map.get(completion)
        if candidate is None:
            return
        self.widgets.terminal_view.set_current_input_text(candidate.insert_text)
        self.refresh_completions()

    def submit_command(self, raw_command: str | None = None) -> None:
        raw_command = (
            self.widgets.terminal_view.current_input_text().strip()
            if raw_command is None
            else raw_command.strip()
        )
        if not raw_command:
            return

        self.widgets.terminal_view.set_current_input_text("")
        self.append_log(
            ui_messages.TERMINAL_COMMAND_ECHO.format(
                prompt=self.current_transcript_prompt(),
                command=raw_command,
            )
        )
        if not self.command_history or self.command_history[-1] != raw_command:
            self.command_history.append(raw_command)
        self.history_index = None
        self.refresh_completions()

        verb, _, raw_args = raw_command.partition(" ")
        normalized_verb = verb.strip().lower()
        raw_args = raw_args.strip()

        if normalized_verb in ("help", "h"):
            self.append_log(ui_messages.TERMINAL_HELP_LOG.rstrip())
            return

        if normalized_verb == "ls":
            self.run_ls()
            return
        if normalized_verb == "apps":
            self.run_apps()
            return
        if normalized_verb == "pid":
            self.run_pid()
            return
        if normalized_verb == "uid":
            self.run_uid()
            return
        if normalized_verb == "refresh":
            self.run_refresh()
            return
        if normalized_verb == "select":
            if not raw_args:
                self.append_log(
                    ui_messages.TERMINAL_MISSING_ARGUMENT.format(command=normalized_verb)
                )
                return
            self.run_select(raw_args)
            return

        if normalized_verb in ("activitys", "a"):
            self.run_rpc_command("activitys")
            return
        if normalized_verb in ("services", "s"):
            self.run_rpc_command("services")
            return
        if normalized_verb in ("object", "o"):
            if not raw_args:
                self.append_log(
                    ui_messages.TERMINAL_MISSING_ARGUMENT.format(command=normalized_verb)
                )
                return
            self.run_rpc_command("object", raw_args)
            return
        if normalized_verb == "oe":
            if not raw_args:
                self.append_log(
                    ui_messages.TERMINAL_MISSING_ARGUMENT.format(command=normalized_verb)
                )
                return
            self.run_rpc_command("oe", raw_args)
            return
        if normalized_verb in ("view", "v"):
            if not raw_args:
                self.append_log(
                    ui_messages.TERMINAL_MISSING_ARGUMENT.format(command=normalized_verb)
                )
                return
            self.run_rpc_command("view", raw_args)
            return
        if normalized_verb == "gs":
            if not raw_args:
                self.append_log(
                    ui_messages.TERMINAL_MISSING_ARGUMENT.format(command=normalized_verb)
                )
                return
            self.run_rpc_command("gs", raw_args)
            return
        if normalized_verb == "attach":
            if not raw_args:
                self.append_log(
                    ui_messages.TERMINAL_MISSING_ARGUMENT.format(command=normalized_verb)
                )
                return
            self.hook_runtime.start_script_command(raw_args, False)
            return
        if normalized_verb == "spawn":
            if not raw_args:
                self.append_log(
                    ui_messages.TERMINAL_MISSING_ARGUMENT.format(command=normalized_verb)
                )
                return
            self.hook_runtime.start_script_command(raw_args, True)
            return
        if normalized_verb == "restart":
            self.append_log(ui_messages.TERMINAL_RESTART_ACTION_LOG)
            self.hook_runtime.restart_current_app()
            return
        if normalized_verb == "stop":
            if self.deps.context.active_session is None:
                self.append_log(ui_messages.TERMINAL_STOP_NO_SESSION)
                return
            self.append_log(ui_messages.TERMINAL_STOP_ACTION_LOG)
            self.hook_runtime.stop_hook()
            return

        self.handle_external_command(raw_command)

    def run_ls(self) -> None:
        try:
            package_name = self.ensure_current_app_ready()
        except HookersError as exc:
            self.show_worker_error(to_ui_error_payload(exc))
            return

        workspace_script_names = sorted(
            self.deps.workspace_service.script_names(package_name),
            key=str.lower,
        )
        builtin_script_names = sorted(
            (path.name for path in self.deps.context.hookers_js_dir.glob("*.js")),
            key=str.lower,
        )

        workspace_lines = workspace_script_names or [ui_messages.TERMINAL_LS_EMPTY]
        builtin_lines = builtin_script_names or [ui_messages.TERMINAL_LS_EMPTY]
        message = (
            f"{ui_messages.TERMINAL_LS_WORKSPACE_TITLE}\n"
            + "\n".join(f"  {name}" for name in workspace_lines)
            + "\n"
            + f"{ui_messages.TERMINAL_LS_BUILTIN_TITLE}\n"
            + "\n".join(f"  {name}" for name in builtin_lines)
        )
        self.append_log(ui_messages.TERMINAL_RESULT_LOG.format(message=message))

    def run_apps(self) -> None:
        apps = list(self.deps.context.apps)
        if not apps:
            self.append_log(
                ui_messages.TERMINAL_RESULT_LOG.format(
                    message="当前没有缓存的 App 列表，请先执行 refresh。"
                )
            )
            return
        lines = ["当前缓存 App 列表："]
        sorted_apps = sorted(
            apps,
            key=lambda app: (app.pid is None, app.pid or 0, app.identifier),
        )
        for app in sorted_apps:
            has_workspace = self.deps.workspace_service.workspace_dir(app.identifier).is_dir()
            marker = "√" if has_workspace else "×"
            lines.append(
                f"  pid={app.pid if app.pid is not None else '-'} | {app.name} | {app.identifier} | 工作区:{marker}"
            )
        self.append_log(ui_messages.TERMINAL_RESULT_LOG.format(message="\n".join(lines)))

    def run_pid(self) -> None:
        try:
            self.ensure_current_app_ready()
        except HookersError as exc:
            self.show_worker_error(to_ui_error_payload(exc))
            return
        pid = self.deps.context.current_app.pid if self.deps.context.current_app else None
        self.append_log(ui_messages.TERMINAL_RESULT_LOG.format(message=f"PID: {pid}"))

    def run_uid(self) -> None:
        try:
            self.ensure_current_app_ready()
        except HookersError as exc:
            self.show_worker_error(to_ui_error_payload(exc))
            return
        uid = self.deps.context.current_app.uid if self.deps.context.current_app else None
        self.append_log(ui_messages.TERMINAL_RESULT_LOG.format(message=f"UID: {uid}"))

    def run_refresh(self) -> None:
        if self.command_thread is not None:
            return

        current_package = self.selected_package_name()
        self.append_log(ui_messages.TERMINAL_REFRESH_ACTION_LOG)
        self.append_log(ui_messages.TERMINAL_BUSY_LOG)

        def action() -> tuple[list[object], str | None]:
            apps = self.deps.device_service.refresh_applications()
            selected_package = current_package
            if selected_package and not any(app.identifier == selected_package for app in apps):
                selected_package = None
            return apps, selected_package

        self.set_terminal_command_busy(True)
        self.command_thread = QThread(self.owner)
        self.command_worker = ActionWorker(action)
        self.command_worker.moveToThread(self.command_thread)
        self.command_thread.started.connect(self.command_worker.run)
        self.command_worker.succeeded.connect(
            lambda payload: self.ui_dispatcher.submit(self.on_refresh_finished, payload)
        )
        self.command_worker.failed.connect(
            lambda error: self.ui_dispatcher.submit(self.show_worker_error, error)
        )
        self.command_worker.finished.connect(self.command_thread.quit)
        self.command_worker.finished.connect(self.command_worker.deleteLater)
        self.command_thread.finished.connect(self.command_thread.deleteLater)
        self.command_thread.finished.connect(self._clear_command_thread)
        self.command_thread.start()

    def on_refresh_finished(self, payload: object) -> None:
        apps, selected_package = payload
        self.deps.context.apps = list(apps)
        app_items = [
            {"name": app.name, "identifier": app.identifier, "pid": app.pid}
            for app in apps
        ]
        self.apply_apps_payload(app_items, selected_package)
        self.update_prompt()
        self.refresh_completions()
        self.append_log(
            ui_messages.TERMINAL_RESULT_LOG.format(
                message=f"已刷新 App 列表：{len(app_items)} 个"
            )
        )
        self.set_terminal_command_busy(False)

    def run_select(self, package_name: str) -> None:
        normalized_package = package_name.strip()
        if not normalized_package:
            self.append_log(ui_messages.TERMINAL_MISSING_ARGUMENT.format(command="select"))
            return
        combo = self.widgets.app_combo
        target_index = combo.findData(normalized_package)
        if target_index < 0:
            self.append_log(
                ui_messages.TERMINAL_RESULT_LOG.format(
                    message=f"未找到目标包名：{normalized_package}，请先执行 refresh。"
                )
            )
            return
        combo.setCurrentIndex(target_index)
        self.update_prompt()
        self.refresh_completions()
        self.append_log(ui_messages.TERMINAL_SELECT_APP_LOG.format(package=normalized_package))

    def run_rpc_command(self, command: str, argument: str | None = None) -> None:
        if self.command_thread is not None:
            return

        try:
            package_name = self.ensure_current_app_ready()
        except HookersError as exc:
            self.show_worker_error(to_ui_error_payload(exc))
            return

        self.append_log(ui_messages.TERMINAL_RPC_ACTION_LOG.format(command=command))
        self.append_log(ui_messages.TERMINAL_BUSY_LOG)

        def action() -> tuple[str, str | None, object]:
            if command == "activitys":
                result = self.deps.rpc_service.activitys()
            elif command == "services":
                result = self.deps.rpc_service.services()
            elif command == "object":
                if not argument:
                    raise RpcTargetMissingError(ui_messages.INSPECT_TARGET_BODY)
                result = self.deps.rpc_service.object_info(argument)
            elif command == "oe":
                if not argument:
                    raise RpcTargetMissingError(ui_messages.INSPECT_TARGET_BODY)
                result = self.deps.rpc_service.object_to_explain(argument)
            elif command == "view":
                if not argument:
                    raise RpcTargetMissingError(ui_messages.INSPECT_TARGET_BODY)
                result = self.deps.rpc_service.view_info(argument)
            elif command == "gs":
                if not argument:
                    raise RpcTargetMissingError(ui_messages.MISSING_HOOK_TARGET_BODY)
                result = self.deps.rpc_service.generate_hook_script(argument)
            else:
                raise RpcCallError(f"不支持的终端命令：{command}")
            return package_name, argument, result

        self.set_terminal_command_busy(True)
        self.command_thread = QThread(self.owner)
        self.command_worker = ActionWorker(action)
        self.command_worker.moveToThread(self.command_thread)
        self.command_thread.started.connect(self.command_worker.run)
        self.command_worker.succeeded.connect(
            lambda payload: self.ui_dispatcher.submit(
                self.on_rpc_command_finished,
                command,
                payload,
            )
        )
        self.command_worker.failed.connect(
            lambda error: self.ui_dispatcher.submit(self.show_worker_error, error)
        )
        self.command_worker.finished.connect(self.command_thread.quit)
        self.command_worker.finished.connect(self.command_worker.deleteLater)
        self.command_thread.finished.connect(self.command_thread.deleteLater)
        self.command_thread.finished.connect(self._clear_command_thread)
        self.command_thread.start()

    def _clear_command_thread(self) -> None:
        self.command_thread = None
        self.command_worker = None
        self.set_terminal_command_busy(False)

    def on_rpc_command_finished(self, command: str, payload: object) -> None:
        package_name, argument, result = payload
        formatted = self._format_result_text(result)

        if command == "activitys":
            self.append_log(ui_messages.TERMINAL_ACTIVITYS_LOG.format(content=formatted))
        elif command == "services":
            self.append_log(ui_messages.TERMINAL_SERVICES_LOG.format(content=formatted))
        elif command == "object":
            self.append_log(
                ui_messages.TERMINAL_OBJECT_INFO_LOG.format(
                    target=argument or "-", content=formatted
                )
            )
        elif command == "oe":
            self.append_log(
                ui_messages.TERMINAL_OBJECT_EXPLAIN_LOG.format(
                    target=argument or "-", content=formatted
                )
            )
        elif command == "view":
            self.append_log(
                ui_messages.TERMINAL_VIEW_INFO_LOG.format(
                    target=argument or "-", content=formatted
                )
            )
        elif command == "gs":
            script_path = Path(str(result))
            self.apply_script_root(self.deps.workspace_service.script_dir(package_name))
            self.append_log(
                ui_messages.TERMINAL_GENERATE_SCRIPT_LOG.format(script_path=script_path)
            )

        self.set_terminal_command_busy(False)

    def _format_result_text(self, result: object) -> str:
        if result is None:
            return ui_messages.NO_RESULT
        if isinstance(result, str):
            return result.strip() or ui_messages.NO_RESULT
        if isinstance(result, (list, tuple, dict)):
            try:
                return json.dumps(result, ensure_ascii=False, indent=2)
            except TypeError:
                pass
        return str(result)

    def handle_external_command(self, raw_command: str) -> None:
        if "frida" not in raw_command.lower():
            self.append_log(
                ui_messages.TERMINAL_EXTERNAL_COMMAND_BLOCKED.format(command=raw_command)
            )
            return
        self.run_shell_command(raw_command)

    def run_shell_command(self, raw_command: str) -> None:
        if self.shell_command_busy:
            self.append_log(ui_messages.TERMINAL_SHELL_BUSY_LOG)
            return
        self.append_log(ui_messages.TERMINAL_SHELL_FALLBACK_LOG)
        self.append_log(ui_messages.TERMINAL_BUSY_LOG)
        self.shell_command_busy = True
        self.shell_output_buffer = ""
        self.shell_error_buffer = ""
        process = QProcess(self.owner)
        process.setProgram("powershell.exe")
        process.setArguments(
            [
                "-NoLogo",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                raw_command,
            ]
        )
        process.setWorkingDirectory(str(self.deps.context.project_root))
        process.readyReadStandardOutput.connect(self._on_shell_stdout)
        process.readyReadStandardError.connect(self._on_shell_stderr)
        process.finished.connect(self._on_shell_finished)
        process.errorOccurred.connect(self._on_shell_error)
        self.shell_process = process
        process.start()

    def _on_shell_stdout(self) -> None:
        if self.shell_process is None:
            return
        chunk = bytes(self.shell_process.readAllStandardOutput()).decode("utf-8", errors="replace")
        if not chunk:
            return
        self.shell_output_buffer += chunk

    def _on_shell_stderr(self) -> None:
        if self.shell_process is None:
            return
        chunk = bytes(self.shell_process.readAllStandardError()).decode("utf-8", errors="replace")
        if not chunk:
            return
        self.shell_error_buffer += chunk

    def _on_shell_finished(self, _exit_code: int, _exit_status) -> None:
        self._flush_shell_buffers()
        if self.shell_process is not None:
            self.shell_process.deleteLater()
            self.shell_process = None
        self.shell_command_busy = False

    def _on_shell_error(self, _error) -> None:
        self.append_log(ui_messages.TERMINAL_SHELL_START_FAILED_LOG)
        if self.shell_process is not None:
            self.shell_process.deleteLater()
            self.shell_process = None
        self.shell_command_busy = False

    def _flush_shell_output(self, output: str) -> None:
        normalized = output.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
        if normalized:
            self.append_log(normalized)

    def _flush_shell_errors(self) -> None:
        if not self.shell_error_buffer:
            return
        normalized = self.shell_error_buffer.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
        self.shell_error_buffer = ""
        if not normalized:
            return
        prefixed = "\n".join(
            f"{ui_messages.TERMINAL_SHELL_STDERR_PREFIX} {line}" if line else ui_messages.TERMINAL_SHELL_STDERR_PREFIX
            for line in normalized.split("\n")
        )
        self.append_log(prefixed)

    def _flush_shell_buffers(self) -> None:
        if self.shell_output_buffer.strip():
            self._flush_shell_output(self.shell_output_buffer)
        self.shell_output_buffer = ""
        self._flush_shell_errors()
