from __future__ import annotations
import json
from dataclasses import dataclass
from typing import Callable
from pathlib import Path
from PySide6.QtCore import QObject, QProcess, QThread, Qt, QStringListModel, QRect
from PySide6.QtWidgets import QCompleter, QPushButton, QWidget
from core.errors import HookersError, RpcCallError, RpcTargetMissingError, to_ui_error_payload
from core.workspace_service import ScriptSourceInfo
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
from .display_builders import (
    build_result_action_list_lines,
    build_terminal_help_category_lines,
    build_terminal_help_example_lines,
    build_terminal_logs_lines,
    build_terminal_apps_lines,
    build_terminal_script_meta_lines,
    build_workspace_case_home_terminal_lines,
    join_lines,
)
from .result_action_runtime import run_result_action_with_registry
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
@dataclass(frozen=True)
class _CommandSpec:
    name: str
    aliases: tuple[str, ...]
    category: str
    usage: str
    help_text: str
    example: str | None
    requires_current_app: bool
    argument_mode: str
    completion_source: str
    handler_name: str


@dataclass(frozen=True)
class _LocalCommandBinding:
    handler: Callable[..., None]
    pass_raw_args: bool = False
class TerminalConsoleController(QObject):
    HELP_CATEGORY_ORDER = (
        ui_messages.TERMINAL_HELP_CATEGORY_BASIC,
        ui_messages.TERMINAL_HELP_CATEGORY_APP,
        ui_messages.TERMINAL_HELP_CATEGORY_QUERY,
        ui_messages.TERMINAL_HELP_CATEGORY_HOOK,
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
        self.command_specs = self._build_command_specs()
        self.command_map = self._build_command_map(self.command_specs)
        self.command_words = self._build_command_words(self.command_specs)
        self.local_command_bindings = self._build_local_command_bindings()
        self.widgets.terminal_view.command_submitted.connect(self.submit_command)
        self.widgets.terminal_view.history_previous_requested.connect(self.show_previous_history)
        self.widgets.terminal_view.history_next_requested.connect(self.show_next_history)
        self.widgets.terminal_view.tab_completion_requested.connect(self.complete_current_input)
        self.widgets.terminal_view.input_edited.connect(self.refresh_completions)
        self.update_prompt()
        self.refresh_completions()

    @staticmethod
    def _build_command_specs() -> tuple[_CommandSpec, ...]:
        categories = {
            "basic": ui_messages.TERMINAL_HELP_CATEGORY_BASIC,
            "app": ui_messages.TERMINAL_HELP_CATEGORY_APP,
            "query": ui_messages.TERMINAL_HELP_CATEGORY_QUERY,
            "hook": ui_messages.TERMINAL_HELP_CATEGORY_HOOK,
        }
        descriptions = {
            "help": "显示帮助信息",
            "ls": "列出当前已选 App 的工作区脚本和内置脚本",
            "pinned": "列出当前已固定脚本",
            "recent": "列出最近使用脚本",
            "sessions": "列出当前工作区最近启动档案",
            "sessionmeta": "查看当前脚本或最近一次启动档案摘要",
            "workspacemeta": "查看当前工作区档案摘要",
            "meta": "查看脚本 metadata",
            "resultmeta": "查看当前日志结果摘要",
            "resultactions": "查看当前结果摘要的推荐下一步",
            "runaction": "执行当前结果摘要的一条建议动作",
            "logs": "列出当前工作区最近导出的日志",
            "logmeta": "查看指定日志的 manifest 摘要",
            "pid": "显示当前 App PID",
            "uid": "显示当前 App UID",
            "apps": "显示当前缓存 App 列表",
            "refresh": "刷新当前 App 列表",
            "select": "选中目标 App",
            "activitys": "显示当前 Activity 信息",
            "services": "显示当前 Service 信息",
            "object": "查看对象或类实例信息",
            "oe": "继续展开分析指定对象",
            "view": "查看 View 详细信息",
            "gs": "生成 Hook 脚本",
            "attach": "Attach 模式执行脚本",
            "spawn": "Spawn 模式执行脚本",
            "restart": "重启当前 App",
            "stop": "停止当前 Hook",
        }
        return (
            _CommandSpec("help", ("h",), categories["basic"], "help / h", descriptions["help"], None, False, "none", "command", "command_help"),
            _CommandSpec("ls", (), categories["basic"], "ls", descriptions["ls"], None, True, "none", "none", "command_ls"),
            _CommandSpec("pinned", (), categories["basic"], "pinned", descriptions["pinned"], None, True, "none", "none", "command_pinned"),
            _CommandSpec("recent", (), categories["basic"], "recent", descriptions["recent"], None, True, "none", "none", "command_recent"),
            _CommandSpec("sessions", (), categories["basic"], "sessions", descriptions["sessions"], None, True, "none", "none", "command_sessions"),
            _CommandSpec("sessionmeta", (), categories["basic"], "sessionmeta", descriptions["sessionmeta"], None, True, "none", "none", "command_sessionmeta"),
            _CommandSpec("workspacemeta", (), categories["basic"], "workspacemeta", descriptions["workspacemeta"], None, True, "none", "none", "command_workspacemeta"),
            _CommandSpec("meta", (), categories["basic"], "meta <script.js>", descriptions["meta"], "meta okhttp.js", True, "required", "script", "command_meta"),
            _CommandSpec("resultmeta", (), categories["basic"], "resultmeta", descriptions["resultmeta"], None, False, "none", "none", "command_resultmeta"),
            _CommandSpec("resultactions", (), categories["basic"], "resultactions", descriptions["resultactions"], None, False, "none", "none", "command_resultactions"),
            _CommandSpec("runaction", (), categories["basic"], "runaction <action_key|first|list>", descriptions["runaction"], "runaction first", False, "optional", "none", "command_runaction"),
            _CommandSpec("noteappend", (), categories["basic"], "noteappend resultmeta", "将当前结果摘要追加到工作区 notes", None, True, "required", "none", "command_noteappend"),
            _CommandSpec("logs", (), categories["basic"], "logs", descriptions["logs"], None, True, "none", "none", "command_logs"),
            _CommandSpec("logmeta", (), categories["basic"], "logmeta <logfile>", descriptions["logmeta"], "logmeta 20260608_111000__okhttp__hook.log", True, "required", "logfile", "command_logmeta"),
            _CommandSpec("pid", (), categories["basic"], "pid", descriptions["pid"], None, True, "none", "none", "command_pid"),
            _CommandSpec("uid", (), categories["basic"], "uid", descriptions["uid"], None, True, "none", "none", "command_uid"),
            _CommandSpec("apps", (), categories["app"], "apps", descriptions["apps"], None, False, "none", "none", "command_apps"),
            _CommandSpec("refresh", (), categories["app"], "refresh", descriptions["refresh"], None, False, "none", "none", "command_refresh"),
            _CommandSpec("select", (), categories["app"], "select <package>", descriptions["select"], "select com.demo.app", False, "required", "package", "command_select"),
            _CommandSpec("activitys", ("a",), categories["query"], "activitys / a", descriptions["activitys"], None, True, "none", "none", "command_activitys"),
            _CommandSpec("services", ("s",), categories["query"], "services / s", descriptions["services"], None, True, "none", "none", "command_services"),
            _CommandSpec("object", ("o",), categories["query"], "object / o <id|class>", descriptions["object"], "object demo.Target", True, "required", "none", "command_object"),
            _CommandSpec("oe", (), categories["query"], "oe <objectId>", descriptions["oe"], None, True, "required", "none", "command_oe"),
            _CommandSpec("view", ("v",), categories["query"], "view / v <id>", descriptions["view"], None, True, "required", "none", "command_view"),
            _CommandSpec("gs", (), categories["query"], "gs <class[:method[(args)]]>", descriptions["gs"], "gs com.demo.A:onCreate", True, "required", "none", "command_gs"),
            _CommandSpec("attach", (), categories["hook"], "attach <script.js>", descriptions["attach"], "attach okhttp.js", True, "required", "script", "command_attach"),
            _CommandSpec("spawn", (), categories["hook"], "spawn <script.js>", descriptions["spawn"], None, True, "required", "script", "command_spawn"),
            _CommandSpec("restart", (), categories["hook"], "restart", descriptions["restart"], None, True, "none", "none", "command_restart"),
            _CommandSpec("stop", (), categories["hook"], "stop", descriptions["stop"], None, True, "none", "none", "command_stop"),
        )

    @staticmethod
    def _build_command_map(specs: tuple[_CommandSpec, ...]) -> dict[str, _CommandSpec]:
        command_map: dict[str, _CommandSpec] = {}
        for spec in specs:
            for word in (spec.name, *spec.aliases):
                command_map[word] = spec
        return command_map

    @staticmethod
    def _build_command_words(specs: tuple[_CommandSpec, ...]) -> tuple[str, ...]:
        words: list[str] = []
        for spec in specs:
            words.append(spec.name)
            words.extend(spec.aliases)
        return tuple(words)

    def _build_local_command_bindings(self) -> dict[str, _LocalCommandBinding]:
        return {
            "help": _LocalCommandBinding(self._run_help_command),
            "ls": _LocalCommandBinding(self.run_ls),
            "pinned": _LocalCommandBinding(self.run_pinned),
            "recent": _LocalCommandBinding(self.run_recent),
            "sessions": _LocalCommandBinding(self.run_sessions),
            "sessionmeta": _LocalCommandBinding(self.run_sessionmeta),
            "workspacemeta": _LocalCommandBinding(self.run_workspacemeta),
            "meta": _LocalCommandBinding(self.run_meta, pass_raw_args=True),
            "resultmeta": _LocalCommandBinding(self.run_resultmeta),
            "resultactions": _LocalCommandBinding(self.run_resultactions),
            "runaction": _LocalCommandBinding(self.run_action, pass_raw_args=True),
            "noteappend": _LocalCommandBinding(self.run_noteappend, pass_raw_args=True),
            "logs": _LocalCommandBinding(self.run_logs),
            "logmeta": _LocalCommandBinding(self.run_logmeta, pass_raw_args=True),
            "pid": _LocalCommandBinding(self.run_pid),
            "uid": _LocalCommandBinding(self.run_uid),
            "apps": _LocalCommandBinding(self.run_apps),
            "refresh": _LocalCommandBinding(self.run_refresh),
            "select": _LocalCommandBinding(self.run_select, pass_raw_args=True),
        }

    def _help_lines_for_category(self, category: str) -> list[str]:
        return build_terminal_help_category_lines(category, self.command_specs)

    def _help_example_lines(self) -> list[str]:
        return build_terminal_help_example_lines(self.command_specs)

    def build_help_log(self) -> str:
        lines = [ui_messages.TERMINAL_HELP_HEADER]
        for category in self.HELP_CATEGORY_ORDER:
            lines.extend(self._help_lines_for_category(category))
        lines.append(ui_messages.TERMINAL_HELP_CATEGORY_TEMPLATE.format(category=ui_messages.TERMINAL_HELP_SHELL_TITLE))
        lines.append(ui_messages.TERMINAL_HELP_SHELL_TEMPLATE.format(rule=ui_messages.TERMINAL_HELP_SHELL_RULE))
        lines.append(ui_messages.TERMINAL_RESULT_LOG.format(message=""))
        lines.extend(self._help_example_lines())
        return "\n".join(lines).rstrip()

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

    def _build_prefixed_completion_candidates(
        self,
        *,
        kind: str,
        prefix_label: str,
        values: list[str],
        insert_text_builder,
    ) -> list[_CompletionCandidate]:
        return [
            _CompletionCandidate(
                kind=kind,
                value=value,
                insert_text=insert_text_builder(value),
                display_text=f"{prefix_label}: {value}",
            )
            for value in values
        ]

    def _build_command_candidates(self, commands) -> list[_CompletionCandidate]:
        values = sorted(set(commands), key=str.lower)
        return self._build_prefixed_completion_candidates(
            kind="command",
            prefix_label=ui_messages.TERMINAL_COMPLETION_COMMAND_PREFIX,
            values=values,
            insert_text_builder=lambda value: value,
        )

    def _build_package_candidates(self, verb: str, arg_prefix: str) -> list[_CompletionCandidate]:
        package_names = [
            package_name
            for package_name in self.available_package_names()
            if not arg_prefix or package_name.lower().startswith(arg_prefix.lower())
        ]
        return self._build_prefixed_completion_candidates(
            kind="package",
            prefix_label=ui_messages.TERMINAL_COMPLETION_PACKAGE_PREFIX,
            values=package_names,
            insert_text_builder=lambda value: f"{verb} {value}",
        )

    def _build_script_candidates(self, verb: str, arg_prefix: str) -> list[_CompletionCandidate]:
        package_name = self.selected_package_name()
        infos_by_name: dict[str, object] = {}
        if package_name:
            try:
                for info in self.deps.workspace_service.list_script_sources(package_name):
                    if info.source_kind == "workspace_builtin_copy":
                        continue
                    infos_by_name.setdefault(info.name.lower(), info)
            except Exception:
                infos_by_name = {}
        script_names = [
            script_name
            for script_name in self.available_script_names()
            if not arg_prefix or script_name.lower().startswith(arg_prefix.lower())
        ]
        candidates: list[_CompletionCandidate] = []
        for script_name in script_names:
            info = infos_by_name.get(script_name.lower())
            metadata = self._readonly_display_metadata(package_name, info) if info is not None and package_name else None
            prefix = ui_messages.TERMINAL_SCRIPT_PINNED_PREFIX if metadata and metadata.pinned else ""
            candidates.append(
                _CompletionCandidate(
                    kind="script",
                    value=script_name,
                    insert_text=f"{verb} {script_name}",
                    display_text=f"{ui_messages.TERMINAL_COMPLETION_SCRIPT_PREFIX}: {prefix}{script_name}",
                )
            )
        return candidates

    @staticmethod
    def _is_log_file(path: Path) -> bool:
        try:
            return path.is_file() and path.suffix.lower() == ".log"
        except OSError:
            return False

    def _recent_log_files(self, package_name: str, limit: int = 10) -> list[Path]:
        try:
            logs_dir = self.deps.workspace_service.logs_dir(package_name)
        except Exception:
            return []
        if not logs_dir.is_dir():
            return []
        ranked_files: list[tuple[float, Path]] = []
        try:
            candidates = list(logs_dir.iterdir())
        except OSError:
            return []
        for path in candidates:
            try:
                if not self._is_log_file(path):
                    continue
                ranked_files.append((path.stat().st_mtime, path))
            except OSError:
                continue
        ranked_files.sort(key=lambda item: item[0], reverse=True)
        return [path for _, path in ranked_files[:limit]]

    def _build_logfile_candidates(self, verb: str, arg_prefix: str) -> list[_CompletionCandidate]:
        package_name = self.selected_package_name()
        if not package_name:
            return []
        values = [
            path.name
            for path in self._recent_log_files(package_name)
            if not arg_prefix or path.name.lower().startswith(arg_prefix.lower())
        ]
        return self._build_prefixed_completion_candidates(
            kind="logfile",
            prefix_label="日志",
            values=values,
            insert_text_builder=lambda value: f"{verb} {value}",
        )


    def _resolve_log_file_path(self, package_name: str, logfile: str) -> Path | None:
        normalized_name = str(logfile or "").strip()
        if not normalized_name:
            return None
        normalized_lookup = normalized_name.lower()
        case_insensitive_match: Path | None = None
        for path in self._recent_log_files(package_name, limit=10_000):
            if path.name == normalized_name:
                return path
            if case_insensitive_match is None and path.name.lower() == normalized_lookup:
                case_insensitive_match = path
        return case_insensitive_match

    def build_completions(self, text: str) -> list[_CompletionCandidate]:
        stripped = text.lstrip()
        if not stripped:
            return self._build_command_candidates(self.command_words)
        verb, separator, raw_args = stripped.partition(" ")
        lowered_verb = verb.lower()
        spec = self.command_map.get(lowered_verb)
        if not separator:
            return self._build_command_candidates(
                command for command in self.command_words if command.startswith(lowered_verb)
            )
        if spec is None:
            return []
        arg_prefix = raw_args.strip()
        if spec.completion_source == "package":
            return self._build_package_candidates(lowered_verb, arg_prefix)
        if spec.completion_source == "script":
            return self._build_script_candidates(lowered_verb, arg_prefix)
        if spec.completion_source == "logfile":
            return self._build_logfile_candidates(lowered_verb, arg_prefix)
        return []
    def _builtin_script_names(self) -> list[str]:
        try:
            return sorted(
                (path.name for path in self.deps.context.hookers_js_dir.glob("*.js")),
                key=str.lower,
            )
        except Exception:
            return []

    def available_script_names(self) -> list[str]:
        package_name = self.selected_package_name()
        if package_name:
            try:
                return self.deps.workspace_service.available_script_names(package_name)
            except Exception:
                return self._builtin_script_names()
        return self._builtin_script_names()
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
    def _resolve_registered_command(
        self,
        raw_command: str,
    ) -> tuple[_CommandSpec | None, str, str]:
        verb, _, raw_args = raw_command.partition(" ")
        normalized_verb = verb.strip().lower()
        return self.command_map.get(normalized_verb), normalized_verb, raw_args.strip()

    def _ensure_command_arguments(self, spec: _CommandSpec, normalized_verb: str, raw_args: str) -> bool:
        if spec.argument_mode == "required" and not raw_args:
            self.append_log(
                ui_messages.TERMINAL_MISSING_ARGUMENT.format(command=normalized_verb)
            )
            return False
        return True

    def _ensure_command_current_app_ready(self, spec: _CommandSpec) -> bool:
        if not spec.requires_current_app:
            return True
        try:
            self.ensure_current_app_ready()
        except HookersError as exc:
            self.show_worker_error(to_ui_error_payload(exc))
            return False
        return True

    def _dispatch_registered_command(self, spec: _CommandSpec, raw_args: str) -> None:
        if self._dispatch_local_command(spec, raw_args):
            return
        if self._dispatch_rpc_command(spec, raw_args):
            return
        if self._dispatch_hook_script_command(spec, raw_args):
            return
        if self._dispatch_hook_control_command(spec):
            return
        handler = getattr(self, spec.handler_name)
        if spec.argument_mode == "required":
            handler(raw_args)
        else:
            handler()

    def _dispatch_local_command(self, spec: _CommandSpec, raw_args: str) -> bool:
        binding = self.local_command_bindings.get(spec.name)
        if binding is None:
            return False
        if binding.pass_raw_args:
            binding.handler(raw_args)
        else:
            binding.handler()
        return True

    def _dispatch_rpc_command(self, spec: _CommandSpec, raw_args: str) -> bool:
        rpc_commands = {
            "activitys": None,
            "services": None,
            "object": raw_args,
            "oe": raw_args,
            "view": raw_args,
            "gs": raw_args,
        }
        if spec.name not in rpc_commands:
            return False
        self.run_rpc_command(spec.name, rpc_commands[spec.name])
        return True

    def _dispatch_hook_script_command(self, spec: _CommandSpec, raw_args: str) -> bool:
        if spec.name not in {"attach", "spawn"}:
            return False
        if self.deps.context.active_session is not None:
            self.append_log(
                ui_messages.TERMINAL_HOOK_ACTIVE_SESSION_BLOCKED.format(command=spec.name)
            )
            self.show_worker_error(
                to_ui_error_payload(
                    HookersError(
                        ui_messages.TERMINAL_HOOK_ACTIVE_SESSION_BLOCKED.format(command=spec.name),
                        severity="warning",
                        next_step=ui_messages.TERMINAL_HOOK_ACTIVE_SESSION_BLOCKED_NEXT_STEP.format(command=spec.name),
                        user_visible=False,
                    )
                )
            )
            return True
        self.hook_runtime.start_script_command(raw_args, spec.name == "spawn")
        return True

    def _dispatch_hook_control_command(self, spec: _CommandSpec) -> bool:
        if spec.name == "restart":
            self.append_log(ui_messages.TERMINAL_RESTART_ACTION_LOG)
            self.hook_runtime.restart_current_app()
            return True
        if spec.name == "stop":
            if self.deps.context.active_session is None:
                self.append_log(ui_messages.TERMINAL_STOP_NO_SESSION)
                return True
            self.append_log(ui_messages.TERMINAL_STOP_ACTION_LOG)
            self.hook_runtime.stop_hook()
            return True
        return False

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
        spec, normalized_verb, raw_args = self._resolve_registered_command(raw_command)
        if spec is None:
            self.handle_external_command(raw_command)
            return
        if not self._ensure_command_arguments(spec, normalized_verb, raw_args):
            return
        if not self._ensure_command_current_app_ready(spec):
            return
        self._dispatch_registered_command(spec, raw_args)
    def command_help(self) -> None:
        self._run_help_command()

    def _run_help_command(self) -> None:
        self.append_log(self.build_help_log())
    def run_ls(self) -> None:
        package_name = self.selected_package_name() or ""
        workspace_infos = []
        builtin_infos = []
        try:
            candidate_infos = self.deps.workspace_service.list_launcher_candidate_scripts(package_name)
            workspace_infos = [info for info in candidate_infos if info.source_kind in {"workspace", "workspace_builtin_copy"}]
            builtin_infos = [info for info in candidate_infos if info.source_kind == "builtin_source"]
        except Exception:
            workspace_infos = []
            builtin_infos = []

        workspace_lines = [self._format_script_metadata_line(package_name, info) for info in workspace_infos] or [ui_messages.TERMINAL_LS_EMPTY]
        builtin_lines = [self._format_script_metadata_line(package_name, info) for info in builtin_infos] or [ui_messages.TERMINAL_LS_EMPTY]
        message = (
            f"{ui_messages.TERMINAL_LS_WORKSPACE_TITLE}\n"
            + "\n".join(workspace_lines)
            + "\n"
            + f"{ui_messages.TERMINAL_LS_BUILTIN_TITLE}\n"
            + "\n".join(builtin_lines)
        )
        self.append_log(ui_messages.TERMINAL_RESULT_LOG.format(message=message))
    def _format_recommended_mode_label(self, mode: str | None) -> str:
        normalized = str(mode or "either").strip().lower()
        if normalized == "attach":
            return ui_messages.SCRIPT_METADATA_MODE_ATTACH
        if normalized == "spawn":
            return ui_messages.SCRIPT_METADATA_MODE_SPAWN
        return ui_messages.SCRIPT_METADATA_MODE_EITHER

    def _readonly_display_metadata(self, package_name: str, info: ScriptSourceInfo | None):
        if info is None:
            return None
        metadata = getattr(info, "metadata", None)
        if metadata is not None:
            return metadata
        if getattr(info, "source_kind", None) != "builtin_source":
            return None
        try:
            return self.deps.workspace_service.resolve_script_metadata(package_name, info.name)
        except Exception:
            return None

    def _script_line_metadata(self, package_name: str, info: ScriptSourceInfo):
        return self._readonly_display_metadata(package_name, info)

    def _format_script_metadata_line(self, package_name: str, info) -> str:
        metadata = self._script_line_metadata(package_name, info)
        prefix = f"{ui_messages.TERMINAL_SCRIPT_PINNED_PREFIX} " if metadata and metadata.pinned else ""
        mode = str(metadata.recommended_mode if metadata else "either").strip().lower() or "either"
        mode_text = f"[{mode}]"
        summary = ""
        if metadata and metadata.summary:
            short = metadata.summary[:40]
            if len(metadata.summary) > 40:
                short += "..."
            summary = f" - {short}"
        return f"  {prefix}{info.name} {mode_text}{summary}"

    def run_pinned(self) -> None:
        package_name = self.selected_package_name() or ""
        try:
            infos = self.deps.workspace_service.list_pinned_scripts(package_name)
        except Exception:
            infos = []
        if not infos:
            message = ui_messages.TERMINAL_PINNED_EMPTY
        else:
            lines = [ui_messages.TERMINAL_PINNED_TITLE]
            lines.extend(self._format_script_metadata_line(package_name, info) for info in infos)
            message = "\n".join(lines)
        self.append_log(ui_messages.TERMINAL_RESULT_LOG.format(message=message))

    def run_recent(self) -> None:
        package_name = self.selected_package_name() or ""
        try:
            infos = self.deps.workspace_service.list_recent_scripts(package_name)
        except Exception:
            infos = []
        if not infos:
            message = ui_messages.TERMINAL_RECENT_EMPTY
        else:
            lines = [ui_messages.TERMINAL_RECENT_TITLE]
            lines.extend(self._format_script_metadata_line(package_name, info) for info in infos)
            message = "\n".join(lines)
        self.append_log(ui_messages.TERMINAL_RESULT_LOG.format(message=message))

    @staticmethod
    def _short_session_summary(summary: str | None, *, limit: int = 48) -> str:
        text = str(summary or "").strip()
        if not text:
            return ui_messages.TERMINAL_SESSIONS_SUMMARY_EMPTY
        return text if len(text) <= limit else text[:limit] + "..."

    def run_sessions(self) -> None:
        package_name = self.selected_package_name() or ""
        try:
            records = self.deps.workspace_service.list_recent_session_records(package_name)
        except Exception:
            records = []
        if not records:
            message = ui_messages.TERMINAL_SESSIONS_EMPTY
        else:
            lines = [ui_messages.TERMINAL_SESSIONS_TITLE]
            for record in records:
                lines.append(
                    ui_messages.TERMINAL_SESSIONS_LINE.format(
                        timestamp=record.get("timestamp") or "-",
                        mode=self._format_recommended_mode_label(record.get("mode") or "either"),
                        script=record.get("script_name") or "-",
                        summary=self._short_session_summary(record.get("summary")),
                    )
                )
            message = "\n".join(lines)
        self.append_log(ui_messages.TERMINAL_RESULT_LOG.format(message=message))

    def _current_selected_script_identity(self) -> tuple[str | None, Path | None]:
        raw_text = self.owner.script_combo.currentText().strip()
        raw_path = self.owner.script_combo.currentData()
        script_path = None
        if raw_path:
            try:
                script_path = Path(str(raw_path))
            except Exception:
                script_path = None
        package_name = self.selected_package_name() or ""
        if package_name and script_path is not None:
            try:
                resolved_target = script_path.resolve()
                for info in self.deps.workspace_service.list_script_sources(package_name):
                    try:
                        if info.path.resolve() == resolved_target:
                            return info.name, script_path
                    except Exception:
                        continue
            except Exception:
                pass
            return script_path.name, script_path
        return (raw_text or None), script_path

    @staticmethod
    def _workspace_manifest_notes_flag_text(manifest: dict[str, object], key: str) -> str:
        value = manifest.get(key)
        if value is None:
            return "-"
        return "是" if bool(value) else "否"

    def run_workspacemeta(self) -> None:
        package_name = self.selected_package_name() or ""
        try:
            manifest = self.deps.workspace_service.build_workspace_manifest(package_name)
        except Exception:
            manifest = None
        if not isinstance(manifest, dict):
            self.append_log(ui_messages.TERMINAL_RESULT_LOG.format(message="工作区档案摘要不可用"))
            return
        lines = build_workspace_case_home_terminal_lines(
            manifest,
            package_fallback=package_name,
            notes_flag_text_resolver=self._workspace_manifest_notes_flag_text,
            mode_label_resolver=self._format_recommended_mode_label,
            sessions_summary_empty=ui_messages.TERMINAL_SESSIONS_SUMMARY_EMPTY,
        )
        self.append_log(ui_messages.TERMINAL_RESULT_LOG.format(message=join_lines(lines)))

    def run_sessionmeta(self) -> None:
        package_name = self.selected_package_name() or ""
        current_script = None
        current_script_path = None
        matched_current_script = False
        if self.deps.context.current_app is not None:
            current_script, current_script_path = self._current_selected_script_identity()
        try:
            if current_script:
                record = self.deps.workspace_service.read_recent_session_record_for_script(
                    package_name,
                    script_name=current_script,
                    script_path=current_script_path,
                )
                matched_current_script = isinstance(record, dict)
                if not matched_current_script:
                    record = self.deps.workspace_service.read_recent_session_record(package_name)
            else:
                record = self.deps.workspace_service.read_recent_session_record(package_name)
        except Exception:
            record = None
        if not isinstance(record, dict):
            self.append_log(ui_messages.TERMINAL_RESULT_LOG.format(message=ui_messages.TERMINAL_SESSIONMETA_EMPTY))
            return
        title = (
            ui_messages.TERMINAL_SESSIONMETA_TITLE.format(script=record.get("script_name") or "-")
            if matched_current_script
            else ui_messages.TERMINAL_SESSIONMETA_FALLBACK_TITLE
        )
        lines = [
            title,
            ui_messages.TERMINAL_SESSIONMETA_TIMESTAMP.format(value=record.get("timestamp") or "-"),
            ui_messages.TERMINAL_SESSIONMETA_MODE.format(value=self._format_recommended_mode_label(record.get("mode") or "either")),
            ui_messages.TERMINAL_SESSIONMETA_SCRIPT.format(value=record.get("script_name") or "-"),
            ui_messages.TERMINAL_SESSIONMETA_PATH.format(value=record.get("script_path") or "-"),
            ui_messages.TERMINAL_SESSIONMETA_SUMMARY.format(value=record.get("summary") or ui_messages.TERMINAL_SESSIONS_SUMMARY_EMPTY),
        ]
        self.append_log(ui_messages.TERMINAL_RESULT_LOG.format(message="\n".join(lines)))

    def _describe_script_source_kind(self, source_kind: str) -> str:
        mapping = {
            "workspace": ui_messages.TERMINAL_META_SOURCE_WORKSPACE,
            "workspace_builtin_copy": ui_messages.TERMINAL_META_SOURCE_WORKSPACE_BUILTIN,
            "builtin_source": ui_messages.TERMINAL_META_SOURCE_BUILTIN,
        }
        return mapping.get(source_kind, source_kind)

    def _resolve_meta_target_info(self, package_name: str, normalized_lookup: str):
        try:
            ordered_infos = self.deps.workspace_service.list_launcher_candidate_scripts(package_name)
        except Exception:
            ordered_infos = []
        if ordered_infos:
            for info in ordered_infos:
                if info.name.lower() == normalized_lookup:
                    return info
        try:
            infos = self.deps.workspace_service.list_script_sources(package_name)
        except Exception:
            infos = []
        return next((info for info in infos if info.name.lower() == normalized_lookup), None)

    def _meta_display_metadata(self, package_name: str, target: ScriptSourceInfo):
        return self._readonly_display_metadata(package_name, target)

    def run_meta(self, script_name: str) -> None:
        normalized_name = script_name.strip()
        if not normalized_name:
            self.append_log(ui_messages.TERMINAL_MISSING_ARGUMENT.format(command="meta"))
            return
        normalized_lookup = normalized_name.lower()
        package_name = self.selected_package_name() or ""
        target = self._resolve_meta_target_info(package_name, normalized_lookup)
        if target is None:
            self.append_log(
                ui_messages.TERMINAL_RESULT_LOG.format(
                    message=ui_messages.TERMINAL_META_NOT_FOUND.format(script=normalized_name)
                )
            )
            return
        metadata = self._meta_display_metadata(package_name, target)
        lines = build_terminal_script_meta_lines(
            script_name=target.name,
            path_value=str(target.path),
            source_text=self._describe_script_source_kind(target.source_kind),
            pinned_text=ui_messages.YES_TEXT if metadata and metadata.pinned else ui_messages.NO_TEXT,
            recommended_mode=self._format_recommended_mode_label(metadata.recommended_mode if metadata else "either"),
            last_used_at=metadata.last_used_at if metadata and metadata.last_used_at else "-",
            summary=metadata.summary if metadata and metadata.summary else "-",
            use_when=metadata.use_when if metadata and metadata.use_when else "-",
            caution=metadata.caution if metadata and metadata.caution else "-",
            tags_value=", ".join(metadata.tags) if metadata and metadata.tags else "-",
        )
        self.append_log(ui_messages.TERMINAL_RESULT_LOG.format(message=join_lines(lines)))

    def run_resultmeta(self) -> None:
        summary = self.owner.log_panel_controller.build_result_summary_text()
        self.append_log(ui_messages.TERMINAL_RESULT_LOG.format(message=summary))

    def run_resultactions(self) -> None:
        actions_text = self.owner.log_panel_controller.build_result_summary_actions_text()
        self.append_log(ui_messages.TERMINAL_RESULT_LOG.format(message=actions_text))

    def _current_result_actions(self) -> list[dict[str, str]]:
        return self.owner.log_panel_controller.build_result_summary_actions()

    def _result_action_list_lines(self, actions: list[dict[str, str]]) -> list[str]:
        return build_result_action_list_lines(actions)

    def _execute_result_action(self, action: dict[str, str]) -> str:
        ok, status_value = run_result_action_with_registry(
            action,
            scenario_runner=lambda scenario_key: self.hook_runtime.open_analysis_scenario_as_template(
                scenario_key,
                use_spawn=False,
            ),
            workspace_note_runner=lambda: self.run_noteappend('resultmeta'),
            unsupported_message_builder=lambda label: ui_messages.RESULT_SUMMARY_ACTIONS_RUN_UNSUPPORTED_STATUS.format(label=label),
        )
        if not ok:
            return status_value
        entry_type = str(action.get('entry_type') or '').strip().lower()
        if entry_type == 'workspace_note':
            return ''
        return ui_messages.RESULT_SUMMARY_ACTIONS_RUN_STATUS_TEMPLATE.format(label=status_value)

    def run_action(self, raw_args: str) -> None:
        normalized = str(raw_args or '').strip()
        actions = self._current_result_actions()
        if not normalized:
            hint = "\n".join([ui_messages.RESULT_SUMMARY_ACTIONS_RUN_MISSING_ARGUMENT, ui_messages.RESULT_SUMMARY_ACTIONS_RUN_USAGE_HINT, *self._result_action_list_lines(actions)])
            self.append_log(ui_messages.TERMINAL_RESULT_LOG.format(message=hint))
            return
        if not actions:
            self.append_log(ui_messages.TERMINAL_RESULT_LOG.format(message=ui_messages.RESULT_SUMMARY_ACTIONS_RUN_EMPTY_STATUS))
            return
        target = normalized.lower()
        if target == ui_messages.RESULT_SUMMARY_ACTIONS_RUN_LIST_ARGUMENT:
            self.append_log(ui_messages.TERMINAL_RESULT_LOG.format(message="\n".join(self._result_action_list_lines(actions))))
            return
        action = None
        if target == ui_messages.RESULT_SUMMARY_ACTIONS_RUN_FIRST_ARGUMENT:
            action = actions[0]
        else:
            for candidate in actions:
                if str(candidate.get('key') or '').strip().lower() == target:
                    action = candidate
                    break
        if action is None:
            message = "\n".join([
                ui_messages.RESULT_SUMMARY_ACTIONS_RUN_NOT_FOUND.format(value=normalized),
                *self._result_action_list_lines(actions),
            ])
            self.append_log(ui_messages.TERMINAL_RESULT_LOG.format(message=message))
            return
        message = self._execute_result_action(action)
        if message:
            self.append_log(ui_messages.TERMINAL_RESULT_LOG.format(message=message))

    def run_noteappend(self, raw_args: str) -> None:
        normalized = str(raw_args or '').strip().lower()
        if normalized != 'resultmeta':
            self.append_log(ui_messages.TERMINAL_MISSING_ARGUMENT.format(command='noteappend resultmeta'))
            return
        package_name = self.selected_package_name() or ''
        note_block = self.owner.log_panel_controller.build_result_summary_note_block()
        if ui_messages.RESULT_SUMMARY_NOTE_EMPTY in note_block:
            self.append_log(ui_messages.TERMINAL_RESULT_LOG.format(message=ui_messages.RESULT_SUMMARY_SAVE_EMPTY_STATUS))
            return
        try:
            summary_path = self.deps.workspace_service.write_latest_result_summary(package_name, note_block)
            self.deps.workspace_service.append_workspace_note_section(package_name, note_block)
        except Exception as exc:
            self.append_log(ui_messages.TERMINAL_RESULT_LOG.format(message=str(exc)))
            return
        self.append_log(ui_messages.TERMINAL_RESULT_LOG.format(message=ui_messages.RESULT_SUMMARY_SAVE_SUCCESS_LOG.format(path=summary_path)))

    def run_logs(self) -> None:
        package_name = self.selected_package_name() or ""
        files = self._recent_log_files(package_name)
        lines = build_terminal_logs_lines([path.name for path in files])
        self.append_log(ui_messages.TERMINAL_RESULT_LOG.format(message=join_lines(lines)))

    def run_logmeta(self, logfile: str) -> None:
        normalized_name = logfile.strip()
        if not normalized_name:
            self.append_log(ui_messages.TERMINAL_MISSING_ARGUMENT.format(command="logmeta"))
            return
        package_name = self.selected_package_name() or ""
        log_file_path = self._resolve_log_file_path(package_name, normalized_name)
        if log_file_path is None:
            self.append_log(
                ui_messages.TERMINAL_RESULT_LOG.format(
                    message=ui_messages.TERMINAL_LOGMETA_NOT_FOUND.format(logfile=normalized_name)
                )
            )
            return
        manifest_path = log_file_path.with_suffix(log_file_path.suffix + ".json")
        if not manifest_path.is_file():
            self.append_log(
                ui_messages.TERMINAL_RESULT_LOG.format(
                    message=ui_messages.TERMINAL_LOGMETA_NOT_FOUND.format(logfile=normalized_name)
                )
            )
            return
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            self.append_log(
                ui_messages.TERMINAL_RESULT_LOG.format(
                    message=ui_messages.TERMINAL_LOGMETA_READ_FAILED.format(error=exc)
                )
            )
            return
        resolved_logfile_name = log_file_path.name
        lines = [
            ui_messages.TERMINAL_LOGMETA_TITLE.format(logfile=resolved_logfile_name),
            ui_messages.TERMINAL_LOGMETA_LOG_FILE.format(value=data.get("log_file") or log_file_path.name),
            ui_messages.TERMINAL_LOGMETA_MANIFEST_PATH.format(value=str(manifest_path)),
            ui_messages.TERMINAL_LOGMETA_PACKAGE.format(value=data.get("package_name") or "-"),
            ui_messages.TERMINAL_LOGMETA_SCRIPT.format(value=data.get("script_name") or "-"),
            ui_messages.TERMINAL_LOGMETA_MODE.format(value=self._format_recommended_mode_label(data.get("recommended_mode") or "either")),
            ui_messages.TERMINAL_LOGMETA_SUMMARY.format(value=data.get("summary") or "-"),
            ui_messages.TERMINAL_LOGMETA_EXPORTED_AT.format(value=data.get("exported_at") or "-"),
            ui_messages.TERMINAL_LOGMETA_PATH.format(value=data.get("script_path") or "-"),
        ]
        self.append_log(ui_messages.TERMINAL_RESULT_LOG.format(message="\n".join(lines)))

    def run_apps(self) -> None:
        apps = list(self.deps.context.apps)
        sorted_apps = sorted(
            apps,
            key=lambda app: (app.pid is None, app.pid or 0, app.identifier),
        )
        app_rows = []
        for app in sorted_apps:
            has_workspace = self.deps.workspace_service.workspace_dir(app.identifier).is_dir()
            workspace_state = (
                ui_messages.TERMINAL_APP_WORKSPACE_READY
                if has_workspace
                else ui_messages.TERMINAL_APP_WORKSPACE_MISSING
            )
            app_rows.append({
                'pid': str(app.pid) if app.pid is not None else '-',
                'name': app.name,
                'identifier': app.identifier,
                'workspace_state': workspace_state,
            })
        lines = build_terminal_apps_lines(app_rows)
        self.append_log(ui_messages.TERMINAL_RESULT_LOG.format(message=join_lines(lines)))
    def run_pid(self) -> None:
        pid = self.deps.context.current_app.pid if self.deps.context.current_app else None
        self.append_log(ui_messages.TERMINAL_RESULT_LOG.format(message=ui_messages.TERMINAL_PID_MESSAGE.format(pid=pid)))
    def run_uid(self) -> None:
        uid = self.deps.context.current_app.uid if self.deps.context.current_app else None
        self.append_log(ui_messages.TERMINAL_RESULT_LOG.format(message=ui_messages.TERMINAL_UID_MESSAGE.format(uid=uid)))
    def run_refresh(self) -> None:
        if self.command_thread is not None:
            self.show_worker_error(
                to_ui_error_payload(
                    HookersError(
                        ui_messages.TERMINAL_COMMAND_BUSY_BODY,
                        next_step=ui_messages.TERMINAL_COMMAND_BUSY_NEXT_STEP,
                    )
                )
            )
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
                message=ui_messages.TERMINAL_REFRESH_DONE_MESSAGE.format(count=len(app_items))
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
                    message=ui_messages.TERMINAL_SELECT_APP_NOT_FOUND.format(package=normalized_package)
                )
            )
            return
        combo.setCurrentIndex(target_index)
        self.update_prompt()
        self.refresh_completions()
        self.append_log(ui_messages.TERMINAL_SELECT_APP_LOG.format(package=normalized_package))
    def run_rpc_command(self, command: str, argument: str | None = None) -> None:
        if self.command_thread is not None:
            self.show_worker_error(
                to_ui_error_payload(
                    HookersError(
                        ui_messages.TERMINAL_COMMAND_BUSY_BODY,
                        next_step=ui_messages.TERMINAL_COMMAND_BUSY_NEXT_STEP,
                    )
                )
            )
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
            self.show_worker_error(
                to_ui_error_payload(
                    HookersError(
                        ui_messages.TERMINAL_EXTERNAL_COMMAND_BLOCKED.format(command=raw_command),
                        severity="warning",
                        next_step=ui_messages.TERMINAL_EXTERNAL_COMMAND_BLOCKED_NEXT_STEP,
                        user_visible=False,
                    )
                )
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
        self.append_log(ui_messages.TERMINAL_SHELL_SESSION_ENDED_LOG)
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
