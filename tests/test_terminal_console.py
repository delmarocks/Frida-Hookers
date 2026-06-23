from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent

from ui import ui_messages
from core.workspace_service import ScriptMetadata, ScriptSourceInfo, SessionRecord
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


def test_terminal_command_registry_is_consistent(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    specs = window.terminal_console_controller.command_specs
    names = [spec.name for spec in specs]
    assert len(names) == len(set(names))

    aliases = []
    for spec in specs:
        assert spec.category
        assert spec.usage
        assert spec.help_text
        assert spec.handler_name
        aliases.extend(spec.aliases)
    assert len(aliases) == len(set(aliases))
    assert "help" in window.terminal_console_controller.command_words
    assert "h" in window.terminal_console_controller.command_words
    window.deleteLater()


def test_terminal_local_command_bindings_cover_expected_commands(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    bindings = window.terminal_console_controller.local_command_bindings

    assert set(bindings) == {"help", "ls", "pinned", "recent", "sessions", "sessionmeta", "workspacemeta", "meta", "resultmeta", "resultactions", "runaction", "noteappend", "logs", "logmeta", "pid", "uid", "apps", "refresh", "select"}
    assert bindings["help"].pass_raw_args is False
    assert bindings["select"].pass_raw_args is True
    window.deleteLater()


def test_terminal_help_category_order_is_readable_and_matches_expected_labels(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)

    assert window.terminal_console_controller.HELP_CATEGORY_ORDER == (
        "基础命令",
        "App 命令",
        "查询命令",
        "Hook 命令",
    )
    window.deleteLater()


def test_terminal_help_log_is_generated_from_registry(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    help_log = window.terminal_console_controller.build_help_log()

    assert "基础命令" in help_log
    assert "App 命令" in help_log
    assert "查询命令" in help_log
    assert "Hook 命令" in help_log
    assert ui_messages.TERMINAL_HELP_SHELL_RULE in help_log
    assert "object demo.Target" in help_log
    assert "gs com.demo.A:onCreate" in help_log
    assert "attach okhttp.js" in help_log
    assert "select com.demo.app" in help_log
    window.deleteLater()


def test_terminal_logs_uses_display_builder_output(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    log_dir = dummy_deps.workspace_service.workspace_dir('pkg.default') / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / 'b.log').write_text('b', encoding='utf-8')
    (log_dir / 'a.log').write_text('a', encoding='utf-8')

    window.terminal_console_controller.run_logs()

    output = log_messages(window)[-1]
    assert ui_messages.TERMINAL_LOGS_TITLE in output
    assert 'a.log' in output
    assert 'b.log' in output
    window.deleteLater()


def test_terminal_apps_uses_display_builder_output(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    app_a = type(dummy_deps.device_service.ensure_result)(
        identifier='pkg.a',
        name='App A',
        pid=222,
        uid='u0_a222',
    )
    app_b = type(dummy_deps.device_service.ensure_result)(
        identifier='pkg.b',
        name='App B',
        pid=None,
        uid='u0_a223',
    )
    dummy_deps.context.apps = [app_b, app_a]
    dummy_deps.workspace_service.workspace_dir('pkg.a').mkdir(parents=True, exist_ok=True)

    window.terminal_console_controller.run_apps()

    output = log_messages(window)[-1]
    assert ui_messages.TERMINAL_APPS_TITLE in output
    assert 'pid=222 | App A | pkg.a' in output
    assert '工作区:' in output
    assert 'App B | pkg.b' in output
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

def test_terminal_ls_shows_pinned_mode_and_truncated_summary(qapp, dummy_deps, tmp_path, monkeypatch) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    package_name = "pkg.default"
    workspace_script_dir = tmp_path / "workspaces" / package_name / "js"
    workspace_script_dir.mkdir(parents=True, exist_ok=True)
    alpha = workspace_script_dir / "alpha.js"
    alpha.write_text("// alpha", encoding="utf-8")

    dummy_deps.workspace_service.script_dir = lambda _package_name: workspace_script_dir
    monkeypatch_service = window.terminal_console_controller.deps.workspace_service
    monkeypatch_service.list_script_sources = lambda _package_name: [
        ScriptSourceInfo(
            name="alpha.js",
            path=alpha,
            source_kind="workspace",
            is_builtin=False,
            is_parameter_template=False,
            display_label="alpha.js",
            metadata=ScriptMetadata(
                name="alpha.js",
                pinned=True,
                recommended_mode="attach",
                summary="x" * 50,
            ),
        )
    ]

    window.terminal_console_controller.submit_command("ls")

    output = log_messages(window)[-1]
    assert "★ alpha.js [attach]" in output
    assert ("- " + "x" * 40 + "...") in output
    window.deleteLater()


def test_terminal_build_completions_uses_available_script_name_order(qapp, dummy_deps, monkeypatch) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)

    monkeypatch.setattr(
        window.terminal_console_controller,
        "available_script_names",
        lambda: ["gamma.js", "alpha.js", "beta.js"],
    )

    workspace_service = dummy_deps.workspace_service
    monkeypatch.setattr(
        workspace_service,
        "list_script_sources",
        lambda _package_name: [
            ScriptSourceInfo(
                name="alpha.js",
                path=Path(r"C:\\demo\\alpha.js"),
                source_kind="workspace",
                is_builtin=False,
                is_parameter_template=False,
                display_label="alpha.js",
                metadata=ScriptMetadata(name="alpha.js", pinned=True),
            ),
            ScriptSourceInfo(
                name="beta.js",
                path=Path(r"C:\\demo\\beta.js"),
                source_kind="workspace",
                is_builtin=False,
                is_parameter_template=False,
                display_label="beta.js",
                metadata=ScriptMetadata(name="beta.js"),
            ),
            ScriptSourceInfo(
                name="gamma.js",
                path=Path(r"C:\\demo\\gamma.js"),
                source_kind="workspace",
                is_builtin=False,
                is_parameter_template=False,
                display_label="gamma.js",
                metadata=ScriptMetadata(name="gamma.js"),
            ),
        ],
    )

    candidates = window.terminal_console_controller.build_completions("attach " )
    displays = [candidate.display_text for candidate in candidates]
    assert displays == [
        "脚本: gamma.js",
        "脚本: ★alpha.js",
        "脚本: beta.js",
    ]
    inserts = [candidate.insert_text for candidate in candidates]
    assert inserts == [
        "attach gamma.js",
        "attach alpha.js",
        "attach beta.js",
    ]
    window.deleteLater()


def test_terminal_build_completions_reuses_builtin_source_metadata_for_pinned_prefix(qapp, dummy_deps, monkeypatch, tmp_path) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps, "pkg.demo")

    monkeypatch.setattr(
        window.terminal_console_controller,
        "available_script_names",
        lambda: ["okhttp.js"],
    )

    builtin_script = tmp_path / "hookers" / "js" / "okhttp.js"
    builtin_script.parent.mkdir(parents=True, exist_ok=True)
    builtin_script.write_text("// builtin", encoding="utf-8")

    monkeypatch.setattr(
        dummy_deps.workspace_service,
        "list_script_sources",
        lambda _package_name: [
            ScriptSourceInfo(
                name="okhttp.js",
                path=builtin_script,
                source_kind="builtin_source",
                is_builtin=True,
                is_parameter_template=False,
                display_label="okhttp.js",
                metadata=None,
            )
        ],
    )
    monkeypatch.setattr(
        dummy_deps.workspace_service,
        "resolve_script_metadata",
        lambda package_name, script_name: (
            ScriptMetadata(name="okhttp.js", pinned=True)
            if package_name == "pkg.demo" and script_name == "okhttp.js"
            else None
        ),
    )

    candidates = window.terminal_console_controller.build_completions("attach ")

    assert [candidate.display_text for candidate in candidates] == ["脚本: ★okhttp.js"]
    assert [candidate.insert_text for candidate in candidates] == ["attach okhttp.js"]
    window.deleteLater()


def test_dummy_workspace_service_available_script_names_matches_real_candidate_priority(qapp, dummy_deps, tmp_path) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps, "pkg.demo")
    package_name = "pkg.demo"
    workspace_script_dir = tmp_path / "workspaces" / package_name / "js"
    builtin_script_dir = tmp_path / "hookers" / "js"
    workspace_script_dir.mkdir(parents=True, exist_ok=True)
    builtin_script_dir.mkdir(parents=True, exist_ok=True)
    dummy_deps.context.hookers_js_dir = builtin_script_dir
    dummy_deps.workspace_service.context = dummy_deps.context

    (workspace_script_dir / "beta.js").write_text("// beta", encoding="utf-8")
    (workspace_script_dir / "内置-alpha.js").write_text("// copied alpha", encoding="utf-8")
    (builtin_script_dir / "alpha.js").write_text("// builtin alpha", encoding="utf-8")
    (builtin_script_dir / "gamma.js").write_text("// builtin gamma", encoding="utf-8")

    dummy_deps.workspace_service.mark_script_used(package_name, "gamma.js", mode="attach")
    dummy_deps.workspace_service.set_script_pinned(package_name, "alpha.js", True)

    assert dummy_deps.workspace_service.available_script_names(package_name) == [
        "alpha.js",
        "gamma.js",
        "beta.js",
    ]
    window.deleteLater()


def test_terminal_recent_log_files_skips_entries_with_stat_failure(qapp, dummy_deps, tmp_path, monkeypatch) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    logs_dir = tmp_path / "workspaces" / "pkg.default" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    good = logs_dir / "good.log"
    bad = logs_dir / "bad.log"
    good.write_text("ok", encoding="utf-8")
    bad.write_text("bad", encoding="utf-8")

    dummy_deps.workspace_service.logs_dir = lambda _package_name: logs_dir

    original_stat = Path.stat

    def fake_stat(self, *args, **kwargs):
        if self == bad:
            raise OSError("stat failed")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fake_stat)

    files = window.terminal_console_controller._recent_log_files("pkg.default")

    assert [path.name for path in files] == ["good.log"]
    window.deleteLater()

def test_terminal_logmeta_matches_logfile_case_insensitively(qapp, dummy_deps, tmp_path) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    logs_dir = tmp_path / "workspaces" / "pkg.default" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "Demo.LOG"
    manifest = logs_dir / "Demo.LOG.json"
    log_file.write_text("payload", encoding="utf-8")
    manifest.write_text(
        '{"log_file": "Demo.LOG", "package_name": "pkg.default", "script_name": "alpha.js", "recommended_mode": "attach"}',
        encoding="utf-8",
    )
    dummy_deps.workspace_service.logs_dir = lambda _package_name: logs_dir

    window.terminal_console_controller.submit_command("logmeta demo.log")

    output = log_messages(window)[-1]
    assert "Demo.LOG" in output
    assert "alpha.js" in output
    window.deleteLater()


def test_terminal_ls_shows_empty_sections_when_no_scripts(qapp, dummy_deps, tmp_path) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    dummy_deps.workspace_service.script_dir = lambda _package_name: tmp_path / "empty_workspace_js"
    dummy_deps.context.hookers_js_dir = tmp_path / "empty_builtin_js"
    dummy_deps.context.hookers_js_dir.mkdir(parents=True, exist_ok=True)

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
    assert "工作区:未初始化" in output
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


def test_terminal_attach_and_spawn_block_when_active_session_exists(qapp, dummy_deps, monkeypatch) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    dummy_deps.context.active_session = type("Session", (), {"mode": "attach"})()
    captured: list[tuple[str, bool]] = []
    presented = []
    monkeypatch.setattr(
        window.hook_runtime_controller,
        "start_script_command",
        lambda script_name, use_spawn: captured.append((script_name, use_spawn)),
    )
    monkeypatch.setattr(window.error_presenter, "present", lambda payload: presented.append(payload))
    window.terminal_console_controller.show_worker_error = window.error_presenter.present

    window.terminal_console_controller.submit_command("attach demo.js")
    window.terminal_console_controller.submit_command("spawn demo.js")

    messages = log_messages(window)
    assert ui_messages.TERMINAL_HOOK_ACTIVE_SESSION_BLOCKED.format(command="attach") in messages
    assert ui_messages.TERMINAL_HOOK_ACTIVE_SESSION_BLOCKED.format(command="spawn") in messages
    assert presented[-2].next_step == "先点击“停止 Hook”结束当前会话；状态栏显示已停止后，再重新执行 attach。"
    assert presented[-1].next_step == "先点击“停止 Hook”结束当前会话；状态栏显示已停止后，再重新执行 spawn。"
    assert captured == []
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
        message=ui_messages.TERMINAL_REFRESH_DONE_MESSAGE.format(count=2)
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


def test_terminal_script_completion_falls_back_to_builtin_when_workspace_visible_scripts_fail(qapp, dummy_deps, monkeypatch) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    hookers_js_dir = dummy_deps.context.hookers_js_dir
    hookers_js_dir.mkdir(parents=True, exist_ok=True)
    (hookers_js_dir / "builtin.js").write_text("// builtin", encoding="utf-8")

    monkeypatch.setattr(
        dummy_deps.workspace_service,
        "available_script_names",
        lambda _package: (_ for _ in ()).throw(RuntimeError("workspace list failed")),
    )

    suggestions = window.terminal_console_controller.build_completions("spawn ")

    assert suggestions
    assert all(candidate.kind == "script" for candidate in suggestions)
    assert any(candidate.value == "builtin.js" for candidate in suggestions)
    assert any(
        candidate.display_text == f"{ui_messages.TERMINAL_COMPLETION_SCRIPT_PREFIX}: builtin.js"
        for candidate in suggestions
    )
    window.deleteLater()


def test_terminal_tab_completion_suggests_commands_and_scripts(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    dummy_deps.context.apps = [dummy_deps.device_service.ensure_result]
    script_dir = dummy_deps.workspace_service.script_dir("pkg.default")
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / "alpha.js").write_text("// alpha", encoding="utf-8")
    (script_dir / "beta.js").write_text("// beta", encoding="utf-8")
    (script_dir / "内置-builtin.js").write_text("// workspace builtin copy", encoding="utf-8")
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
    display_texts = [candidate.display_text for candidate in all_script_suggestions]
    assert "脚本: alpha.js" in display_texts
    assert "脚本: builtin.js" in display_texts
    assert "脚本: 内置-builtin.js" not in display_texts

    prefixed_copy_suggestions = window.terminal_console_controller.build_completions("attach 内")
    assert "脚本: 内置-builtin.js" not in [candidate.display_text for candidate in prefixed_copy_suggestions]

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
        try:
            result = self.action()
        except Exception as exc:
            from core.errors import to_ui_error_payload
            self.failed.emit(to_ui_error_payload(exc))
        else:
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
    monkeypatch.setattr("ui.terminal_console.QThread", _FakeThread)
    monkeypatch.setattr("ui.terminal_console.ActionWorker", _FakeWorker)
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)

    window.terminal_console_controller.command_thread = object()
    presented = []
    monkeypatch.setattr(window.error_presenter, "present", lambda payload: presented.append(payload))
    window.terminal_console_controller.show_worker_error = window.error_presenter.present

    window.terminal_console_controller.submit_command("a")

    assert presented[-1].message == ui_messages.TERMINAL_COMMAND_BUSY_BODY
    assert presented[-1].next_step == ui_messages.TERMINAL_COMMAND_BUSY_NEXT_STEP
    window.deleteLater()


def test_terminal_unknown_command_falls_back_to_powershell(qapp, dummy_deps, monkeypatch) -> None:
    monkeypatch.setattr("ui.terminal_console.QProcess", _FakeProcess)
    window = build_main_window(dummy_deps)

    window.terminal_console_controller.submit_command("frida-ps")

    messages = log_messages(window)
    assert ui_messages.TERMINAL_SHELL_FALLBACK_LOG in messages
    assert any("frida-ps" in message for message in messages)
    assert messages[-1] == ui_messages.TERMINAL_SHELL_SESSION_ENDED_LOG
    assert not any("未知命令" in message for message in messages)
    window.deleteLater()


def test_terminal_non_frida_external_command_logs_next_step(qapp, dummy_deps, monkeypatch) -> None:
    monkeypatch.setattr("ui.terminal_console.QProcess", _FakeProcess)
    window = build_main_window(dummy_deps)

    window.terminal_console_controller.submit_command("pwd")

    messages = log_messages(window)
    assert messages[-2] == f"{ui_messages.ERROR_LOG_PREFIX} {ui_messages.TERMINAL_EXTERNAL_COMMAND_BLOCKED.format(command='pwd')}"
    assert messages[-1] == f"{ui_messages.ERROR_NEXT_STEP_PREFIX}请优先输入 help 查看项目内命令；若确需外部命令，只允许输入包含 frida 的命令。"
    window.deleteLater()


def test_terminal_non_frida_external_command_is_blocked(qapp, dummy_deps, monkeypatch) -> None:
    monkeypatch.setattr("ui.terminal_console.QProcess", _FakeProcess)
    window = build_main_window(dummy_deps)

    window.terminal_console_controller.submit_command("pwd")

    messages = log_messages(window)
    assert messages[-2] == f"{ui_messages.ERROR_LOG_PREFIX} {ui_messages.TERMINAL_EXTERNAL_COMMAND_BLOCKED.format(command='pwd')}"
    assert messages[-1] == f"{ui_messages.ERROR_NEXT_STEP_PREFIX}请优先输入 help 查看项目内命令；若确需外部命令，只允许输入包含 frida 的命令。"
    window.deleteLater()


def test_terminal_shell_stderr_is_prefixed(qapp, dummy_deps, monkeypatch) -> None:
    monkeypatch.setattr("ui.terminal_console.QProcess", _FakeProcess)
    window = build_main_window(dummy_deps)

    window.terminal_console_controller.submit_command("frida-error")

    messages = log_messages(window)
    assert f"{ui_messages.TERMINAL_SHELL_STDERR_PREFIX} boom" in messages
    assert messages[-1] == ui_messages.TERMINAL_SHELL_SESSION_ENDED_LOG
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
    assert log_messages(window)[-1] == ui_messages.TERMINAL_SHELL_SESSION_ENDED_LOG
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


def test_terminal_rpc_missing_targets_include_next_step(qapp, dummy_deps, monkeypatch) -> None:
    monkeypatch.setattr("ui.terminal_console.QThread", _FakeThread)
    monkeypatch.setattr("ui.terminal_console.ActionWorker", _FakeWorker)
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    presented = []
    monkeypatch.setattr(window.error_presenter, "present", lambda payload: presented.append(payload))
    window.terminal_console_controller.show_worker_error = window.error_presenter.present

    window.terminal_console_controller.run_rpc_command("object", "")
    assert presented[-1].next_step == ui_messages.INSPECT_TARGET_NEXT_STEP
    assert presented[-1].focus_target == "inspect_target_input"

    window.terminal_console_controller.run_rpc_command("gs", "")
    assert presented[-1].next_step == ui_messages.MISSING_HOOK_TARGET_NEXT_STEP
    assert presented[-1].focus_target == "hook_target_input"
    window.deleteLater()


def test_terminal_refresh_reports_busy_instead_of_silently_returning(qapp, dummy_deps, monkeypatch) -> None:
    monkeypatch.setattr("ui.terminal_console.QThread", _FakeThread)
    monkeypatch.setattr("ui.terminal_console.ActionWorker", _FakeWorker)
    window = build_main_window(dummy_deps)
    presented = []
    monkeypatch.setattr(window.error_presenter, "present", lambda payload: presented.append(payload))
    window.terminal_console_controller.show_worker_error = window.error_presenter.present
    window.terminal_console_controller.command_thread = object()

    window.terminal_console_controller.run_refresh()

    assert presented[-1].message == ui_messages.TERMINAL_COMMAND_BUSY_BODY
    assert presented[-1].next_step == ui_messages.TERMINAL_COMMAND_BUSY_NEXT_STEP
    window.deleteLater()


def test_terminal_rpc_command_reports_busy_instead_of_silently_returning(qapp, dummy_deps, monkeypatch) -> None:
    monkeypatch.setattr("ui.terminal_console.QThread", _FakeThread)
    monkeypatch.setattr("ui.terminal_console.ActionWorker", _FakeWorker)
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    presented = []
    monkeypatch.setattr(window.error_presenter, "present", lambda payload: presented.append(payload))
    window.terminal_console_controller.show_worker_error = window.error_presenter.present
    window.terminal_console_controller.command_thread = object()

    window.terminal_console_controller.run_rpc_command("activitys")

    assert presented[-1].message == ui_messages.TERMINAL_COMMAND_BUSY_BODY
    assert presented[-1].next_step == ui_messages.TERMINAL_COMMAND_BUSY_NEXT_STEP
    window.deleteLater()


from core.workspace_service import ScriptMetadata


def test_terminal_available_script_names_uses_workspace_service_order(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    dummy_deps.workspace_service.names_by_package["pkg.default"] = ["beta.js", "alpha.js"]
    names = window.terminal_console_controller.available_script_names()
    assert names[:2] == ["alpha.js", "beta.js"]
    window.deleteLater()


def test_terminal_build_completions_shows_pinned_prefix_but_inserts_plain_name(qapp, dummy_deps, tmp_path) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    script_dir = dummy_deps.workspace_service.script_dir("pkg.default")
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / "alpha.js").write_text("// alpha", encoding="utf-8")
    dummy_deps.workspace_service.metadata_by_package.setdefault("pkg.default", {})["alpha.js"] = ScriptMetadata(name="alpha.js", pinned=True)
    candidates = window.terminal_console_controller.build_completions("attach ")
    target = next(candidate for candidate in candidates if "alpha.js" in candidate.display_text)
    assert target.display_text.endswith("★alpha.js") or "★" in target.display_text
    assert target.insert_text == "attach alpha.js"
    window.deleteLater()


def test_terminal_ls_output_contains_pinned_mode_and_summary(qapp, dummy_deps, tmp_path) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    script_dir = dummy_deps.workspace_service.script_dir("pkg.default")
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / "alpha.js").write_text("// alpha", encoding="utf-8")
    hookers_js_dir = dummy_deps.context.hookers_js_dir
    hookers_js_dir.mkdir(parents=True, exist_ok=True)
    (hookers_js_dir / "builtin.js").write_text("// builtin", encoding="utf-8")
    dummy_deps.workspace_service.metadata_by_package.setdefault("pkg.default", {})["alpha.js"] = ScriptMetadata(
        name="alpha.js",
        pinned=True,
        recommended_mode="attach",
        summary="抓取网络请求",
    )
    window.terminal_console_controller.submit_command("ls")
    output = log_messages(window)[-1]
    assert f"{ui_messages.TERMINAL_SCRIPT_PINNED_PREFIX} alpha.js [attach]" in output
    assert "抓取网络请求" in output
    window.deleteLater()


def test_terminal_pinned_lists_only_pinned_scripts(qapp, dummy_deps, tmp_path) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    script_dir = dummy_deps.workspace_service.script_dir('pkg.default')
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / 'alpha.js').write_text('// alpha', encoding='utf-8')
    (script_dir / 'beta.js').write_text('// beta', encoding='utf-8')
    meta = dummy_deps.workspace_service.metadata_by_package.setdefault('pkg.default', {})
    meta['alpha.js'] = ScriptMetadata(name='alpha.js', pinned=True, recommended_mode='attach')
    meta['beta.js'] = ScriptMetadata(name='beta.js', pinned=False, recommended_mode='spawn')

    window.terminal_console_controller.submit_command('pinned')

    output = log_messages(window)[-1]
    assert ui_messages.TERMINAL_PINNED_TITLE in output
    assert 'alpha.js' in output
    assert 'beta.js' not in output
    window.deleteLater()


def test_terminal_recent_lists_recent_scripts(qapp, dummy_deps, tmp_path) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    script_dir = dummy_deps.workspace_service.script_dir('pkg.default')
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / 'alpha.js').write_text('// alpha', encoding='utf-8')
    meta = dummy_deps.workspace_service.metadata_by_package.setdefault('pkg.default', {})
    meta['alpha.js'] = ScriptMetadata(name='alpha.js', last_used_at='2026-06-08T10:30:00+08:00', summary='recent summary')

    window.terminal_console_controller.submit_command('recent')

    output = log_messages(window)[-1]
    assert ui_messages.TERMINAL_RECENT_TITLE in output
    assert 'alpha.js' in output
    window.deleteLater()


def test_terminal_recent_reuses_builtin_source_metadata_for_output(qapp, dummy_deps, tmp_path, monkeypatch) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps, "pkg.demo")

    builtin_script = tmp_path / "hookers" / "js" / "okhttp.js"
    builtin_script.parent.mkdir(parents=True, exist_ok=True)
    builtin_script.write_text("// builtin", encoding="utf-8")

    builtin_info = ScriptSourceInfo(
        name="okhttp.js",
        path=builtin_script,
        source_kind="builtin_source",
        is_builtin=True,
        is_parameter_template=False,
        display_label="[内置源] okhttp.js",
        metadata=None,
    )

    monkeypatch.setattr(
        dummy_deps.workspace_service,
        "list_recent_scripts",
        lambda _package_name: [builtin_info],
    )
    monkeypatch.setattr(
        dummy_deps.workspace_service,
        "resolve_script_metadata",
        lambda package_name, script_name: (
            ScriptMetadata(
                name="okhttp.js",
                recommended_mode="attach",
                summary="抓取 OkHttp 请求与响应",
            )
            if package_name == "pkg.demo" and script_name == "okhttp.js"
            else None
        ),
    )

    window.terminal_console_controller.submit_command("recent")

    output = log_messages(window)[-1]
    assert ui_messages.TERMINAL_RECENT_TITLE in output
    assert "okhttp.js [attach] - 抓取 OkHttp 请求与响应" in output
    window.deleteLater()


def test_terminal_pinned_reuses_builtin_source_metadata_for_output(qapp, dummy_deps, tmp_path, monkeypatch) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps, "pkg.demo")

    builtin_script = tmp_path / "hookers" / "js" / "okhttp.js"
    builtin_script.parent.mkdir(parents=True, exist_ok=True)
    builtin_script.write_text("// builtin", encoding="utf-8")

    builtin_info = ScriptSourceInfo(
        name="okhttp.js",
        path=builtin_script,
        source_kind="builtin_source",
        is_builtin=True,
        is_parameter_template=False,
        display_label="[内置源] okhttp.js",
        metadata=None,
    )

    monkeypatch.setattr(
        dummy_deps.workspace_service,
        "list_pinned_scripts",
        lambda _package_name: [builtin_info],
    )
    monkeypatch.setattr(
        dummy_deps.workspace_service,
        "resolve_script_metadata",
        lambda package_name, script_name: (
            ScriptMetadata(
                name="okhttp.js",
                pinned=True,
                recommended_mode="attach",
                summary="抓取 OkHttp 请求与响应",
            )
            if package_name == "pkg.demo" and script_name == "okhttp.js"
            else None
        ),
    )

    window.terminal_console_controller.submit_command("pinned")

    output = log_messages(window)[-1]
    assert ui_messages.TERMINAL_PINNED_TITLE in output
    assert f"{ui_messages.TERMINAL_SCRIPT_PINNED_PREFIX} okhttp.js [attach] - 抓取 OkHttp 请求与响应" in output
    window.deleteLater()


def test_terminal_meta_outputs_script_metadata(qapp, dummy_deps, tmp_path) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    script_dir = dummy_deps.workspace_service.script_dir('pkg.default')
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / 'alpha.js').write_text('// alpha', encoding='utf-8')
    dummy_deps.workspace_service.metadata_by_package.setdefault('pkg.default', {})['alpha.js'] = ScriptMetadata(
        name='alpha.js',
        pinned=True,
        last_used_at='2026-06-08T10:30:00+08:00',
        recommended_mode='attach',
        summary='抓取网络请求',
        tags=('network', 'okhttp'),
    )

    window.terminal_console_controller.submit_command('meta alpha.js')

    output = log_messages(window)[-1]
    assert ui_messages.TERMINAL_META_TITLE.format(script='alpha.js') in output
    assert '来源：工作区脚本' in output
    assert '固定：是' in output
    assert ui_messages.TERMINAL_META_RECOMMENDED_MODE.format(value=ui_messages.SCRIPT_METADATA_MODE_ATTACH) in output
    assert ui_messages.TERMINAL_META_USE_WHEN.format(value='-') in output
    assert ui_messages.TERMINAL_META_CAUTION.format(value='-') in output
    assert '标签：network, okhttp' in output
    window.deleteLater()


def test_terminal_meta_outputs_additional_builtin_knowledge_card(qapp, dummy_deps, tmp_path) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps, 'pkg.demo')
    builtin_dir = tmp_path / 'hookers' / 'js'
    builtin_dir.mkdir(parents=True, exist_ok=True)
    script_path = builtin_dir / 'url.js'
    script_path.write_text('// builtin', encoding='utf-8')
    dummy_deps.context.hookers_js_dir = builtin_dir

    window.terminal_console_controller.submit_command('meta url.js')

    output = log_messages(window)[-1]
    assert '观察常见 URL / WebView / 请求链接输出' in output
    assert '首轮想快速知道 App 正在访问哪些 URL、页面或接口地址时使用。' in output
    assert '它更适合快速观察，不等于完整请求链；拿到 URL 后仍要回到更定向的网络脚本。' in output
    window.deleteLater()


def test_terminal_meta_outputs_builtin_default_use_when_and_caution(qapp, dummy_deps, tmp_path) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    script_dir = dummy_deps.workspace_service.script_dir('pkg.default')
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / 'okhttp.js').write_text('// okhttp', encoding='utf-8')

    window.terminal_console_controller.submit_command('meta okhttp.js')

    output = log_messages(window)[-1]
    assert ui_messages.TERMINAL_META_TITLE.format(script='okhttp.js') in output
    assert '适用时机：确认目标使用 OkHttp' in output
    assert '注意事项：若关键请求发生在冷启动早期' in output
    window.deleteLater()


def test_terminal_meta_matches_script_name_case_insensitively(qapp, dummy_deps, tmp_path) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    script_dir = dummy_deps.workspace_service.script_dir('pkg.default')
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / 'alpha.js').write_text('// alpha', encoding='utf-8')
    dummy_deps.workspace_service.metadata_by_package.setdefault('pkg.default', {})['alpha.js'] = ScriptMetadata(
        name='alpha.js',
        summary='Case variant script',
    )

    window.terminal_console_controller.submit_command('meta ALPHA.js')

    output = log_messages(window)[-1]
    assert ui_messages.TERMINAL_META_TITLE.format(script='alpha.js') in output
    assert 'Case variant script' in output
    window.deleteLater()


def test_terminal_meta_does_not_attach_workspace_metadata_to_custom_root_script(qapp, dummy_deps, tmp_path, monkeypatch) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps, 'pkg.demo')
    custom_script = tmp_path / 'custom_js' / 'alpha.js'
    custom_script.parent.mkdir(parents=True, exist_ok=True)
    custom_script.write_text('// custom alpha', encoding='utf-8')
    dummy_deps.workspace_service.metadata_by_package.setdefault('pkg.demo', {})['alpha.js'] = ScriptMetadata(
        name='alpha.js',
        pinned=True,
        recommended_mode='attach',
        summary='workspace only summary',
        tags=('network',),
    )
    monkeypatch.setattr(
        dummy_deps.workspace_service,
        'list_launcher_candidate_scripts',
        lambda _package_name: [
            ScriptSourceInfo(
                name='alpha.js',
                path=custom_script,
                source_kind='workspace',
                is_builtin=False,
                is_parameter_template=False,
                display_label='alpha.js',
                metadata=None,
            )
        ],
    )
    monkeypatch.setattr(
        dummy_deps.workspace_service,
        'list_script_sources',
        lambda _package_name: [
            ScriptSourceInfo(
                name='alpha.js',
                path=custom_script,
                source_kind='workspace',
                is_builtin=False,
                is_parameter_template=False,
                display_label='alpha.js',
                metadata=None,
            )
        ],
    )

    window.terminal_console_controller.submit_command('meta alpha.js')

    output = log_messages(window)[-1]
    assert ui_messages.TERMINAL_META_TITLE.format(script='alpha.js') in output
    assert ui_messages.TERMINAL_META_PINNED.format(value=ui_messages.NO_TEXT) in output
    assert ui_messages.TERMINAL_META_SUMMARY.format(value='-') in output
    assert ui_messages.TERMINAL_META_TAGS.format(value='-') in output
    window.deleteLater()


def test_terminal_ls_does_not_attach_workspace_metadata_to_custom_root_script(qapp, dummy_deps, tmp_path, monkeypatch) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps, 'pkg.demo')
    custom_script = tmp_path / 'custom_js' / 'alpha.js'
    custom_script.parent.mkdir(parents=True, exist_ok=True)
    custom_script.write_text('// custom alpha', encoding='utf-8')
    dummy_deps.workspace_service.metadata_by_package.setdefault('pkg.demo', {})['alpha.js'] = ScriptMetadata(
        name='alpha.js',
        pinned=True,
        recommended_mode='attach',
        summary='workspace only summary',
    )
    monkeypatch.setattr(
        dummy_deps.workspace_service,
        'list_launcher_candidate_scripts',
        lambda _package_name: [
            ScriptSourceInfo(
                name='alpha.js',
                path=custom_script,
                source_kind='workspace',
                is_builtin=False,
                is_parameter_template=False,
                display_label='alpha.js',
                metadata=None,
            )
        ],
    )

    window.terminal_console_controller.submit_command('ls')

    output = log_messages(window)[-1]
    assert '★ alpha.js [attach]' not in output
    assert 'workspace only summary' not in output
    assert 'alpha.js [either]' in output
    window.deleteLater()


def test_terminal_sessions_outputs_recent_session_records(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    dummy_deps.workspace_service.append_session_record(
        SessionRecord(
            timestamp='2026-06-08T10:30:00+08:00',
            package_name='pkg.default',
            script_name='alpha.js',
            script_path=r'C:\demo\alpha.js',
            mode='attach',
            source_kind='workspace',
            summary='alpha summary',
        )
    )
    dummy_deps.workspace_service.append_session_record(
        SessionRecord(
            timestamp='2026-06-08T10:40:00+08:00',
            package_name='pkg.default',
            script_name='beta.js',
            script_path=r'C:\demo\beta.js',
            mode='spawn',
            source_kind='workspace',
            summary='beta summary',
        )
    )

    window.terminal_console_controller.submit_command('sessions')

    output = log_messages(window)[-1]
    assert ui_messages.TERMINAL_SESSIONS_TITLE in output
    assert 'beta.js' in output
    assert 'alpha.js' in output
    assert ui_messages.SCRIPT_METADATA_MODE_SPAWN in output
    window.deleteLater()


def test_terminal_sessions_reports_empty_state(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)

    window.terminal_console_controller.submit_command('sessions')

    output = log_messages(window)[-1]
    assert ui_messages.TERMINAL_SESSIONS_EMPTY in output
    window.deleteLater()


def test_terminal_sessionmeta_prefers_current_script_match(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    script_dir = dummy_deps.workspace_service.script_dir('pkg.default')
    script_dir.mkdir(parents=True, exist_ok=True)
    alpha = script_dir / 'alpha.js'
    beta = script_dir / 'beta.js'
    alpha.write_text('// alpha', encoding='utf-8')
    beta.write_text('// beta', encoding='utf-8')
    window.script_combo.addItem('alpha.js', str(alpha))
    window.script_combo.addItem('beta.js', str(beta))
    window.script_combo.setCurrentText('alpha.js')
    dummy_deps.workspace_service.append_session_record(
        SessionRecord(
            timestamp='2026-06-08T10:20:00+08:00',
            package_name='pkg.default',
            script_name='beta.js',
            script_path=str(beta),
            mode='spawn',
            source_kind='workspace',
            summary='beta session',
        )
    )
    dummy_deps.workspace_service.append_session_record(
        SessionRecord(
            timestamp='2026-06-08T10:30:00+08:00',
            package_name='pkg.default',
            script_name='alpha.js',
            script_path=str(alpha),
            mode='attach',
            source_kind='workspace',
            summary='alpha session',
        )
    )

    window.terminal_console_controller.submit_command('sessionmeta')

    output = log_messages(window)[-1]
    assert ui_messages.TERMINAL_SESSIONMETA_TITLE.format(script='alpha.js') in output
    assert 'alpha session' in output
    assert str(alpha) in output
    assert 'beta session' not in output
    window.deleteLater()

def test_terminal_sessionmeta_uses_current_script_data_not_display_text(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    script_dir = dummy_deps.workspace_service.script_dir('pkg.default')
    script_dir.mkdir(parents=True, exist_ok=True)
    alpha = script_dir / 'alpha.js'
    beta = script_dir / 'beta.js'
    alpha.write_text('// alpha', encoding='utf-8')
    beta.write_text('// beta', encoding='utf-8')
    window.script_combo.addItem('★ alpha.js', str(alpha))
    window.script_combo.addItem('beta.js', str(beta))
    window.script_combo.setCurrentIndex(0)
    dummy_deps.workspace_service.append_session_record(
        SessionRecord(
            timestamp='2026-06-08T10:20:00+08:00',
            package_name='pkg.default',
            script_name='beta.js',
            script_path=str(beta),
            mode='spawn',
            source_kind='workspace',
            summary='beta session',
        )
    )
    dummy_deps.workspace_service.append_session_record(
        SessionRecord(
            timestamp='2026-06-08T10:30:00+08:00',
            package_name='pkg.default',
            script_name='alpha.js',
            script_path=str(alpha),
            mode='attach',
            source_kind='workspace',
            summary='alpha session',
        )
    )

    window.terminal_console_controller.submit_command('sessionmeta')

    output = log_messages(window)[-1]
    assert ui_messages.TERMINAL_SESSIONMETA_TITLE.format(script='alpha.js') in output
    assert 'alpha session' in output
    assert str(alpha) in output
    assert 'beta session' not in output
    assert '★ alpha.js' not in output
    window.deleteLater()


def test_terminal_sessionmeta_matches_current_script_even_after_pinned_label_refresh(qapp, dummy_deps, tmp_path) -> None:
    window = build_main_window(dummy_deps)
    app = dummy_deps.device_service.ensure_result
    app.identifier = 'pkg.demo'
    dummy_deps.context.current_app = app
    window.app_combo.addItem(app.name, app.identifier)
    window.app_combo.setCurrentIndex(0)
    dummy_deps.context.project_root = tmp_path
    dummy_deps.context.hookers_js_dir = tmp_path / 'hookers' / 'js'
    dummy_deps.context.hookers_js_dir.mkdir(parents=True, exist_ok=True)
    workspace_dir = tmp_path / 'workspaces' / 'pkg.demo' / 'js'
    workspace_dir.mkdir(parents=True, exist_ok=True)
    alpha = workspace_dir / 'alpha.js'
    beta = workspace_dir / 'beta.js'
    alpha.write_text('// alpha', encoding='utf-8')
    beta.write_text('// beta', encoding='utf-8')
    dummy_deps.workspace_service.script_dir = lambda _package_name: workspace_dir

    window.apply_script_root(workspace_dir)
    alpha_index = window.script_combo.findData(str(alpha.resolve()))
    window.script_combo.setCurrentIndex(alpha_index)
    # 用数据层接口制造“固定标签刷新”场景（GUI 固定按钮已移除，固定能力仍在 workspace_service 与 CLI）
    dummy_deps.workspace_service.set_script_pinned('pkg.demo', 'alpha.js', True)
    window.refresh_script_list()

    dummy_deps.workspace_service.append_session_record(
        SessionRecord(
            timestamp='2026-06-08T10:20:00+08:00',
            package_name='pkg.demo',
            script_name='beta.js',
            script_path=str(beta.resolve()),
            mode='spawn',
            source_kind='workspace',
            summary='beta session',
        )
    )
    dummy_deps.workspace_service.append_session_record(
        SessionRecord(
            timestamp='2026-06-08T10:30:00+08:00',
            package_name='pkg.demo',
            script_name='alpha.js',
            script_path=str(alpha.resolve()),
            mode='attach',
            source_kind='workspace',
            summary='alpha session',
        )
    )

    window.terminal_console_controller.submit_command('sessionmeta')

    output = log_messages(window)[-1]
    assert ui_messages.TERMINAL_SESSIONMETA_FALLBACK_TITLE in output
    assert 'alpha session' in output
    assert str(alpha.resolve()) in output
    assert 'beta session' not in output
    assert 'alpha.js' in output
    window.deleteLater()


def test_terminal_sessionmeta_uses_builtin_root_current_script_identity(qapp, dummy_deps, tmp_path) -> None:
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

    window.apply_script_root(builtin_dir)
    idx = window.script_combo.findData(str(builtin_alpha.resolve()))
    window.script_combo.setCurrentIndex(idx)

    dummy_deps.workspace_service.append_session_record(
        SessionRecord(
            timestamp='2026-06-08T10:30:00+08:00',
            package_name='pkg.demo',
            script_name='alpha.js',
            script_path=str(builtin_alpha.resolve()),
            mode='attach',
            source_kind='builtin_source',
            summary='builtin alpha session',
        )
    )

    window.terminal_console_controller.submit_command('sessionmeta')

    output = log_messages(window)[-1]
    assert 'builtin alpha session' in output
    assert str(builtin_alpha.resolve()) in output
    assert 'alpha.js' in output
    window.deleteLater()


def test_terminal_sessionmeta_custom_root_with_raw_filename_falls_back_to_latest_session(qapp, dummy_deps, tmp_path) -> None:
    window = build_main_window(dummy_deps)
    app = dummy_deps.device_service.ensure_result
    app.identifier = 'pkg.demo'
    dummy_deps.context.current_app = app
    window.app_combo.addItem(app.name, app.identifier)
    window.app_combo.setCurrentIndex(0)
    dummy_deps.context.project_root = tmp_path
    dummy_deps.context.hookers_js_dir = tmp_path / 'hookers' / 'js'
    dummy_deps.context.hookers_js_dir.mkdir(parents=True, exist_ok=True)
    custom_dir = tmp_path / 'custom-js'
    custom_dir.mkdir(parents=True, exist_ok=True)
    custom_alpha = custom_dir / 'alpha.js'
    custom_alpha.write_text('// custom alpha', encoding='utf-8')

    window.apply_script_root(custom_dir)
    idx = window.script_combo.findData(str(custom_alpha.resolve()))
    window.script_combo.setCurrentIndex(idx)

    dummy_deps.workspace_service.append_session_record(
        SessionRecord(
            timestamp='2026-06-08T10:20:00+08:00',
            package_name='pkg.demo',
            script_name='beta.js',
            script_path=r'C:\demoeta.js',
            mode='spawn',
            source_kind='workspace',
            summary='latest fallback session',
        )
    )

    window.terminal_console_controller.submit_command('sessionmeta')

    output = log_messages(window)[-1]
    assert ui_messages.TERMINAL_SESSIONMETA_FALLBACK_TITLE in output
    assert 'latest fallback session' in output
    assert 'beta.js' in output
    assert str(custom_alpha.resolve()) not in output
    window.deleteLater()


def test_terminal_sessionmeta_falls_back_to_latest_session_without_selected_script(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    window.script_combo.clear()
    dummy_deps.workspace_service.append_session_record(
        SessionRecord(
            timestamp='2026-06-08T10:40:00+08:00',
            package_name='pkg.default',
            script_name='beta.js',
            script_path=r'C:\demo\beta.js',
            mode='spawn',
            source_kind='workspace',
            summary='latest session',
        )
    )

    window.terminal_console_controller.submit_command('sessionmeta')

    output = log_messages(window)[-1]
    assert ui_messages.TERMINAL_SESSIONMETA_FALLBACK_TITLE in output
    assert 'latest session' in output
    assert 'beta.js' in output
    window.deleteLater()


def test_terminal_sessionmeta_falls_back_to_latest_session_when_current_script_has_no_match(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    script_dir = dummy_deps.workspace_service.script_dir('pkg.default')
    script_dir.mkdir(parents=True, exist_ok=True)
    alpha = script_dir / 'alpha.js'
    alpha.write_text('// alpha', encoding='utf-8')
    window.script_combo.addItem('alpha.js', str(alpha))
    window.script_combo.setCurrentText('alpha.js')
    dummy_deps.workspace_service.append_session_record(
        SessionRecord(
            timestamp='2026-06-08T10:40:00+08:00',
            package_name='pkg.default',
            script_name='beta.js',
            script_path=r'C:\demo\beta.js',
            mode='spawn',
            source_kind='workspace',
            summary='latest fallback session',
        )
    )

    window.terminal_console_controller.submit_command('sessionmeta')

    output = log_messages(window)[-1]
    assert ui_messages.TERMINAL_SESSIONMETA_FALLBACK_TITLE in output
    assert 'latest fallback session' in output
    assert 'beta.js' in output
    assert ui_messages.TERMINAL_SESSIONMETA_TITLE.format(script='alpha.js') not in output
    window.deleteLater()


def test_terminal_logs_lists_recent_exported_logs(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    logs_dir = dummy_deps.workspace_service.logs_dir('pkg.default')
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / '20260608_111500__beta__hook.log').write_text('beta', encoding='utf-8')
    (logs_dir / '20260608_111000__alpha__hook.log').write_text('alpha', encoding='utf-8')

    window.terminal_console_controller.submit_command('logs')

    output = log_messages(window)[-1]
    assert ui_messages.TERMINAL_LOGS_TITLE in output
    assert '20260608_111500__beta__hook.log' in output
    assert '20260608_111000__alpha__hook.log' in output
    window.deleteLater()


def test_terminal_meta_prefers_candidate_order_for_same_named_scripts(qapp, dummy_deps, tmp_path, monkeypatch) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps, "pkg.demo")

    workspace_script = tmp_path / "workspaces" / "pkg.demo" / "js" / "okhttp.js"
    builtin_script = tmp_path / "hookers" / "js" / "okhttp.js"
    workspace_script.parent.mkdir(parents=True, exist_ok=True)
    builtin_script.parent.mkdir(parents=True, exist_ok=True)
    workspace_script.write_text("// workspace", encoding="utf-8")
    builtin_script.write_text("// builtin", encoding="utf-8")

    workspace_info = ScriptSourceInfo(
        name="okhttp.js",
        path=workspace_script,
        source_kind="workspace",
        is_builtin=False,
        is_parameter_template=False,
        display_label="[工作区] okhttp.js",
        metadata=ScriptMetadata(name="okhttp.js", summary="工作区版本"),
    )
    builtin_info = ScriptSourceInfo(
        name="okhttp.js",
        path=builtin_script,
        source_kind="builtin_source",
        is_builtin=True,
        is_parameter_template=False,
        display_label="[内置源] okhttp.js",
        metadata=ScriptMetadata(name="okhttp.js", summary="内置版本"),
    )

    monkeypatch.setattr(
        dummy_deps.workspace_service,
        "list_script_sources",
        lambda _package_name: [builtin_info, workspace_info],
    )
    monkeypatch.setattr(
        dummy_deps.workspace_service,
        "list_launcher_candidate_scripts",
        lambda _package_name: [workspace_info, builtin_info],
    )

    window.terminal_console_controller.submit_command("meta okhttp.js")

    output = log_messages(window)[-1]
    assert f"路径：{workspace_script}" in output
    assert "说明：工作区版本" in output
    assert f"路径：{builtin_script}" not in output
    assert "说明：内置版本" not in output
    window.deleteLater()

def test_terminal_meta_uses_launcher_candidate_priority_even_if_script_source_order_differs(qapp, dummy_deps, tmp_path, monkeypatch) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps, "pkg.demo")

    workspace_script = tmp_path / "workspaces" / "pkg.demo" / "js" / "okhttp.js"
    builtin_script = tmp_path / "hookers" / "js" / "okhttp.js"
    workspace_script.parent.mkdir(parents=True, exist_ok=True)
    builtin_script.parent.mkdir(parents=True, exist_ok=True)
    workspace_script.write_text("// workspace", encoding="utf-8")
    builtin_script.write_text("// builtin", encoding="utf-8")

    workspace_info = ScriptSourceInfo(
        name="okhttp.js",
        path=workspace_script,
        source_kind="workspace",
        is_builtin=False,
        is_parameter_template=False,
        display_label="[工作区] okhttp.js",
        metadata=ScriptMetadata(name="okhttp.js", summary="工作区版本"),
    )
    builtin_info = ScriptSourceInfo(
        name="okhttp.js",
        path=builtin_script,
        source_kind="builtin_source",
        is_builtin=True,
        is_parameter_template=False,
        display_label="[内置源] okhttp.js",
        metadata=ScriptMetadata(name="okhttp.js", summary="内置版本"),
    )

    monkeypatch.setattr(
        dummy_deps.workspace_service,
        "list_script_sources",
        lambda _package_name: [builtin_info, workspace_info],
    )
    monkeypatch.setattr(
        dummy_deps.workspace_service,
        "list_launcher_candidate_scripts",
        lambda _package_name: [workspace_info, builtin_info],
    )

    window.terminal_console_controller.submit_command("meta okhttp.js")

    output = log_messages(window)[-1]
    assert f"路径：{workspace_script}" in output
    assert "说明：工作区版本" in output
    assert f"路径：{builtin_script}" not in output
    assert "说明：内置版本" not in output
    window.deleteLater()


def test_terminal_meta_reuses_builtin_source_metadata_for_display(qapp, dummy_deps, tmp_path, monkeypatch) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps, "pkg.demo")

    builtin_script = tmp_path / "hookers" / "js" / "okhttp.js"
    builtin_script.parent.mkdir(parents=True, exist_ok=True)
    builtin_script.write_text("// builtin", encoding="utf-8")

    builtin_info = ScriptSourceInfo(
        name="okhttp.js",
        path=builtin_script,
        source_kind="builtin_source",
        is_builtin=True,
        is_parameter_template=False,
        display_label="[内置源] okhttp.js",
        metadata=None,
    )

    monkeypatch.setattr(
        dummy_deps.workspace_service,
        "list_launcher_candidate_scripts",
        lambda _package_name: [builtin_info],
    )
    monkeypatch.setattr(
        dummy_deps.workspace_service,
        "resolve_script_metadata",
        lambda package_name, script_name: (
            ScriptMetadata(
                name="okhttp.js",
                pinned=True,
                last_used_at="2026-06-08T10:30:00+08:00",
                recommended_mode="attach",
                summary="抓取 OkHttp 请求与响应",
                tags=("network", "okhttp"),
            )
            if package_name == "pkg.demo" and script_name == "okhttp.js"
            else None
        ),
    )

    window.terminal_console_controller.submit_command("meta okhttp.js")

    output = log_messages(window)[-1]
    assert "来源：内置源" in output
    assert "固定：是" in output
    assert "推荐模式：Attach" in output
    assert "最近使用：2026-06-08T10:30:00+08:00" in output
    assert "说明：抓取 OkHttp 请求与响应" in output
    assert "标签：network, okhttp" in output
    window.deleteLater()


def test_terminal_logmeta_outputs_manifest_summary(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    logs_dir = dummy_deps.workspace_service.logs_dir('pkg.default')
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / '20260608_111000__okhttp__hook.log'
    log_file.write_text('demo', encoding='utf-8')
    manifest_path = log_file.with_suffix(log_file.suffix + '.json')
    manifest_path.write_text("""{
  "version": 1,
  "package_name": "pkg.default",
  "script_name": "okhttp.js",
  "script_path": "C:/demo/okhttp.js",
  "recommended_mode": "attach",
  "summary": "抓取 OkHttp 请求与响应",
  "exported_at": "2026-06-08T11:10:00+08:00",
  "log_file": "20260608_111000__okhttp__hook.log"
}
""", encoding='utf-8')

    window.terminal_console_controller.submit_command('logmeta 20260608_111000__okhttp__hook.log')

    output = log_messages(window)[-1]
    assert ui_messages.TERMINAL_LOGMETA_TITLE.format(logfile='20260608_111000__okhttp__hook.log') in output
    assert '日志文件：20260608_111000__okhttp__hook.log' in output
    assert f'Manifest 路径：{manifest_path}' in output
    assert '脚本：okhttp.js' in output
    assert ui_messages.TERMINAL_LOGMETA_MODE.format(value=ui_messages.SCRIPT_METADATA_MODE_ATTACH) in output
    assert '抓取 OkHttp 请求与响应' in output
    window.deleteLater()


def test_terminal_logmeta_reports_missing_manifest(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)

    window.terminal_console_controller.submit_command('logmeta missing.log')

    output = log_messages(window)[-1]
    assert ui_messages.TERMINAL_LOGMETA_NOT_FOUND.format(logfile='missing.log') in output
    window.deleteLater()


def test_terminal_logmeta_completion_uses_recent_logs(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    logs_dir = dummy_deps.workspace_service.logs_dir('pkg.default')
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / '20260608_111000__alpha__hook.log').write_text('alpha', encoding='utf-8')

    suggestions = window.terminal_console_controller.build_completions('logmeta 2026')

    assert any(candidate.kind == 'logfile' for candidate in suggestions)
    assert any(candidate.insert_text == 'logmeta 20260608_111000__alpha__hook.log' for candidate in suggestions)
    window.deleteLater()



def test_terminal_logs_completion_and_logmeta_include_uppercase_log_suffix(qapp, dummy_deps, tmp_path) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    logs_dir = tmp_path / 'workspaces' / 'pkg.default' / 'logs'
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / 'Demo.LOG'
    manifest = logs_dir / 'Demo.LOG.json'
    log_file.write_text('payload', encoding='utf-8')
    manifest.write_text(
        '{"log_file": "Demo.LOG", "package_name": "pkg.default", "script_name": "alpha.js", "recommended_mode": "attach"}',
        encoding='utf-8',
    )
    dummy_deps.workspace_service.logs_dir = lambda _package_name: logs_dir

    suggestions = window.terminal_console_controller.build_completions('logmeta dem')
    assert any(candidate.insert_text == 'logmeta Demo.LOG' for candidate in suggestions)

    window.terminal_console_controller.submit_command('logs')
    logs_output = log_messages(window)[-1]
    assert 'Demo.LOG' in logs_output

    window.terminal_console_controller.submit_command('logmeta demo.log')
    meta_output = log_messages(window)[-1]
    assert 'Demo.LOG' in meta_output
    assert 'alpha.js' in meta_output
    window.deleteLater()


def test_terminal_workspacemeta_outputs_case_home_fields(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    dummy_deps.workspace_service.build_workspace_manifest = lambda package_name: {
        'package_name': package_name,
        'workspace_ready': True,
        'script_asset_count': 5,
        'pinned_script_count': 2,
        'recent_script_count': 4,
        'named_template_count': 1,
        'recommended_entrypoint': 'resume_named_template',
        'case_entry_hint': '优先从最近模板继续',
        'notes_path': 'notes/analysis_notes.md',
        'notes_has_user_content': True,
        'notes_is_default_template': False,
        'latest_result_summary_path': 'result_summary_latest.md',
        'latest_result_summary_exists': True,
        'last_result_summary_at': '2026-06-08T10:30:00+08:00',
        'latest_result_summary_excerpt': '发现登录 URL',
        'last_used_template_name': '网络首轮',
        'pinned_scripts': ['alpha.js'],
        'recent_scripts': ['alpha.js'],
        'recent_session_count': 1,
        'recent_log_count': 1,
        'recent_logs': ['demo.log'],
        'updated_at': '2026-06-08T10:40:00+08:00',
        'last_session': None,
    }

    window.terminal_console_controller.submit_command('workspacemeta')

    message = window.log_panel_controller.log_records[-1].message
    assert '工作区案例首页：' in message
    assert '脚本资产数：5' in message
    assert '当前优先入口：恢复最近模板' in message
    assert '案例建议：优先从最近模板继续' in message
    assert '当前建议动作：-' in message
    assert '动作说明：-' in message
    window.deleteLater()


def test_terminal_workspacemeta_outputs_workspace_manifest_summary(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    dummy_deps.workspace_service.build_workspace_manifest = lambda package_name: {
        "version": 1,
        "package_name": package_name,
        "updated_at": "2026-06-08T12:00:00+08:00",
        "notes_path": "workspaces/pkg.default/notes/analysis_notes.md",
        "pinned_scripts": ["alpha.js"],
        "recent_scripts": ["alpha.js", "beta.js"],
        "recent_session_count": 2,
        "recent_log_count": 1,
        "recent_logs": ["20260608_115000__alpha__hook.log"],
        "last_session": {
            "timestamp": "2026-06-08T11:50:00+08:00",
            "script_name": "alpha.js",
            "mode": "attach",
            "summary": "alpha session",
        },
    }

    window.terminal_console_controller.submit_command('workspacemeta')

    output = log_messages(window)[-1]
    assert '工作区案例首页：pkg.default' in output
    assert '固定脚本：alpha.js' in output
    assert '最近脚本：alpha.js, beta.js' in output
    assert '最近 session 数：2' in output
    assert '最近 log：20260608_115000__alpha__hook.log' in output
    assert 'alpha session' in output
    window.deleteLater()


def test_terminal_workspacemeta_uses_unknown_marker_for_missing_notes_flags(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    dummy_deps.workspace_service.build_workspace_manifest = lambda package_name: {
        "version": 1,
        "package_name": package_name,
        "updated_at": "2026-06-08T12:00:00+08:00",
        "notes_path": "workspaces/pkg.default/notes/analysis_notes.md",
        "pinned_scripts": [],
        "recent_scripts": [],
        "recent_session_count": 0,
        "recent_log_count": 0,
        "recent_logs": [],
        "last_session": None,
    }

    window.terminal_console_controller.submit_command('workspacemeta')

    output = log_messages(window)[-1]
    assert 'notes 已填写：-' in output
    assert 'notes 默认模板：-' in output
    window.deleteLater()


def test_terminal_logmeta_title_uses_resolved_logfile_identity(qapp, dummy_deps, tmp_path) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    logs_dir = tmp_path / 'workspaces' / 'pkg.default' / 'logs'
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / 'Demo.LOG'
    manifest = logs_dir / 'Demo.LOG.json'
    log_file.write_text('payload', encoding='utf-8')
    manifest.write_text(
        '{"log_file": "Demo.LOG", "package_name": "pkg.default", "script_name": "alpha.js", "recommended_mode": "attach"}',
        encoding='utf-8',
    )
    dummy_deps.workspace_service.logs_dir = lambda _package_name: logs_dir

    window.terminal_console_controller.submit_command('logmeta demo.log')

    output = log_messages(window)[-1]
    assert ui_messages.TERMINAL_LOGMETA_TITLE.format(logfile='Demo.LOG') in output
    assert ui_messages.TERMINAL_LOGMETA_TITLE.format(logfile='demo.log') not in output
    window.deleteLater()


def test_terminal_resultactions_outputs_action_suggestions(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    window.log_panel_controller.append_log('[JS] https://api.example.com/demo')

    window.terminal_console_controller.submit_command('resultactions')

    output = log_messages(window)[-1]
    assert ui_messages.RESULT_SUMMARY_ACTIONS_TITLE in output
    assert '回看网络链路' in output
    assert '来源说明：结果摘要已命中 URL / Network 相关线索。' in output
    assert '预期收益：更快定位请求时机、参数来源与响应处理链。' in output
    assert '推荐界面：scenario' in output
    assert '注册入口：网络分析场景' in output
    assert '入口来源：analysis_scenario' in output
    assert '入口说明：围绕网络请求、URL、参数与响应处理链做首轮组合分析。' in output
    window.deleteLater()


def test_terminal_resultmeta_outputs_log_result_summary(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    window.log_panel_controller.append_log('[JS] https://api.example.com/demo')

    window.terminal_console_controller.submit_command('resultmeta')

    output = log_messages(window)[-1]
    assert ui_messages.RESULT_SUMMARY_TITLE in output
    assert 'https://api.example.com/demo' in output
    window.deleteLater()


def test_terminal_resultmeta_outputs_empty_state_without_url_hits(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    window.log_panel_controller.append_log('[TOOL] no url here')

    window.terminal_console_controller.submit_command('resultmeta')

    output = log_messages(window)[-1]
    assert ui_messages.RESULT_SUMMARY_EMPTY in output
    window.deleteLater()


def test_terminal_resultmeta_does_not_mutate_original_log_records(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    window.log_panel_controller.append_log('[JS] https://example.com/a')
    before = [record.message for record in window.log_panel_controller.log_records]

    window.terminal_console_controller.submit_command('resultmeta')

    after = [record.message for record in window.log_panel_controller.log_records]
    assert after[:-2] == before
    assert ui_messages.RESULT_SUMMARY_TITLE in after[-1]
    window.deleteLater()


def test_terminal_help_includes_resultmeta_command(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)

    help_log = window.terminal_console_controller.build_help_log()

    assert 'resultmeta' in help_log
    assert '查看当前日志结果摘要' in help_log
    window.deleteLater()


def test_terminal_resultmeta_outputs_activity_summary(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    window.log_panel_controller.append_log('[JS] Activity: com.demo.MainActivity')
    window.log_panel_controller.append_log('[JS] 页面跳转: com.demo.DetailActivity')

    window.terminal_console_controller.submit_command('resultmeta')

    output = log_messages(window)[-1]
    assert ui_messages.RESULT_SUMMARY_ACTIVITY_TOTAL.format(count=2) in output
    assert 'com.demo.MainActivity' in output
    assert 'com.demo.DetailActivity' in output
    window.deleteLater()


def test_terminal_resultmeta_outputs_jni_registration_summary(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    window.log_panel_controller.append_log('[JS] [RegisterNatives] com.demo.NativeBridge (3 methods)')
    window.log_panel_controller.append_log('[JS] [RegisterNatives] java_class: com.demo.NativeBridge name: nativeFoo sig: ()V fnPtr: 0x1234')

    window.terminal_console_controller.submit_command('resultmeta')

    output = log_messages(window)[-1]
    assert ui_messages.RESULT_SUMMARY_JNI_TOTAL.format(count=2) in output
    assert 'com.demo.NativeBridge (3 methods)' in output
    assert 'com.demo.NativeBridge::nativeFoo ()V' in output
    window.deleteLater()


def test_terminal_ls_uses_launcher_candidate_order_within_workspace_and_builtin_sections(qapp, dummy_deps, monkeypatch, tmp_path) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps, "pkg.demo")

    workspace_beta = tmp_path / "workspaces" / "pkg.demo" / "js" / "beta.js"
    workspace_alpha = tmp_path / "workspaces" / "pkg.demo" / "js" / "alpha.js"
    builtin_gamma = tmp_path / "hookers" / "js" / "gamma.js"
    builtin_delta = tmp_path / "hookers" / "js" / "delta.js"
    for target in (workspace_beta, workspace_alpha, builtin_gamma, builtin_delta):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("// demo", encoding="utf-8")

    monkeypatch.setattr(
        dummy_deps.workspace_service,
        "list_launcher_candidate_scripts",
        lambda _package_name: [
            ScriptSourceInfo(
                name="beta.js",
                path=workspace_beta,
                source_kind="workspace",
                is_builtin=False,
                is_parameter_template=False,
                display_label="beta.js",
                metadata=ScriptMetadata(name="beta.js", pinned=True, recommended_mode="attach"),
            ),
            ScriptSourceInfo(
                name="alpha.js",
                path=workspace_alpha,
                source_kind="workspace",
                is_builtin=False,
                is_parameter_template=False,
                display_label="alpha.js",
                metadata=ScriptMetadata(name="alpha.js", recommended_mode="spawn"),
            ),
            ScriptSourceInfo(
                name="gamma.js",
                path=builtin_gamma,
                source_kind="builtin_source",
                is_builtin=True,
                is_parameter_template=False,
                display_label="gamma.js",
                metadata=ScriptMetadata(name="gamma.js", pinned=True, recommended_mode="attach"),
            ),
            ScriptSourceInfo(
                name="delta.js",
                path=builtin_delta,
                source_kind="builtin_source",
                is_builtin=True,
                is_parameter_template=False,
                display_label="delta.js",
                metadata=ScriptMetadata(name="delta.js", recommended_mode="either"),
            ),
        ],
    )

    window.terminal_console_controller.submit_command("ls")

    output = log_messages(window)[-1]
    workspace_title_index = output.index(ui_messages.TERMINAL_LS_WORKSPACE_TITLE)
    builtin_title_index = output.index(ui_messages.TERMINAL_LS_BUILTIN_TITLE)
    beta_index = output.index("★ beta.js [attach]")
    alpha_index = output.index("alpha.js [spawn]")
    gamma_index = output.index("★ gamma.js [attach]")
    delta_index = output.index("delta.js [either]")

    assert workspace_title_index < beta_index < alpha_index < builtin_title_index
    assert builtin_title_index < gamma_index < delta_index
    window.deleteLater()


def test_terminal_sessionmeta_prefers_current_data_path_name_over_display_text_when_source_listing_misses(qapp, dummy_deps, tmp_path, monkeypatch) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps, "pkg.demo")

    script_path = tmp_path / "workspaces" / "pkg.demo" / "js" / "alpha.js"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text("// alpha", encoding="utf-8")

    window.script_combo.addItem("★ [工作区] alpha.js", str(script_path))
    window.script_combo.setCurrentIndex(0)

    monkeypatch.setattr(dummy_deps.workspace_service, "list_script_sources", lambda _package_name: [])
    dummy_deps.workspace_service.append_session_record(
        SessionRecord(
            timestamp='2026-06-08T10:30:00+08:00',
            package_name='pkg.demo',
            script_name='alpha.js',
            script_path=str(script_path),
            mode='attach',
            source_kind='workspace',
            summary='alpha session',
        )
    )

    window.terminal_console_controller.submit_command('sessionmeta')

    output = log_messages(window)[-1]
    assert ui_messages.TERMINAL_SESSIONMETA_TITLE.format(script='alpha.js') in output
    assert 'alpha session' in output
    assert '★ [工作区] alpha.js' not in output
    window.deleteLater()


def test_terminal_noteappend_resultmeta_writes_workspace_summary_and_notes(qapp, dummy_deps, tmp_path) -> None:
    window = build_main_window(dummy_deps)
    app = dummy_deps.device_service.ensure_result
    app.identifier = "pkg.default"
    dummy_deps.context.current_app = app
    dummy_deps.context.project_root = tmp_path
    window.app_combo.addItem(app.name, app.identifier)
    window.app_combo.setCurrentIndex(0)
    window.log_panel_controller.log_records = [
        window.log_panel_controller.classify_log('https://api.demo.test/v1/login'),
    ]

    window.terminal_console_controller.submit_command('noteappend resultmeta')

    summary_path = dummy_deps.workspace_service.workspace_recent_result_summary_path("pkg.default")
    note_path = dummy_deps.workspace_service.default_note_file_path("pkg.default")
    assert summary_path.is_file()
    assert note_path.is_file()
    messages = log_messages(window)
    assert ui_messages.RESULT_SUMMARY_SAVE_SUCCESS_LOG.format(path=summary_path) in messages[-1]
    assert '本轮结果摘要' in summary_path.read_text(encoding='utf-8')
    assert 'https://api.demo.test/v1/login' in note_path.read_text(encoding='utf-8')
    window.deleteLater()


def test_terminal_runaction_first_opens_scenario_template(qapp, dummy_deps, monkeypatch) -> None:
    window = build_main_window(dummy_deps)
    monkeypatch.setattr(
        window.log_panel_controller,
        'build_result_summary_actions',
        lambda: [
            {
                'key': 'network_review',
                'label': '回看网络链路',
                'entry_type': 'scenario',
                'target': 'network_baseline',
                'scenario_key': 'network_baseline',
                'description': '已命中 URL/Network，优先回看请求链路。',
                'command_hint': '优先尝试网络分析场景',
                'source_reason': '结果摘要已命中 URL / Network 相关线索。',
                'expected_value': '更快定位请求时机、参数来源与响应处理链。',
                'risk_or_noise': '网络日志可能很多，需注意区分初始化噪音与真实业务请求。',
                'preferred_surface': 'scenario',
            }
        ],
    )
    captured = {}
    monkeypatch.setattr(
        window.terminal_console_controller.hook_runtime,
        'open_analysis_scenario_as_template',
        lambda key, use_spawn: captured.update({'key': key, 'use_spawn': use_spawn}),
    )

    window.terminal_console_controller.submit_command('runaction first')

    assert captured == {'key': 'network_baseline', 'use_spawn': False}
    assert ui_messages.RESULT_SUMMARY_ACTIONS_RUN_STATUS_TEMPLATE.format(label='回看网络链路') in log_messages(window)[-1]
    window.deleteLater()


def test_terminal_runaction_workspace_note_reuses_noteappend(qapp, dummy_deps, monkeypatch) -> None:
    window = build_main_window(dummy_deps)
    monkeypatch.setattr(
        window.log_panel_controller,
        'build_result_summary_actions',
        lambda: [
            {
                'key': 'persist_summary',
                'label': '沉淀当前结果摘要',
                'entry_type': 'workspace_note',
                'target': 'noteappend_resultmeta',
                'scenario_key': '',
            }
        ],
    )
    captured = {'raw': None}
    monkeypatch.setattr(window.terminal_console_controller, 'run_noteappend', lambda raw: captured.__setitem__('raw', raw))

    window.terminal_console_controller.submit_command('runaction persist_summary')

    assert captured['raw'] == 'resultmeta'
    window.deleteLater()


def test_terminal_runaction_list_outputs_available_actions(qapp, dummy_deps, monkeypatch) -> None:
    window = build_main_window(dummy_deps)
    monkeypatch.setattr(
        window.log_panel_controller,
        'build_result_summary_actions',
        lambda: [
            {
                'key': 'network_review',
                'label': '回看网络链路',
                'entry_type': 'scenario',
                'target': 'network_baseline',
                'scenario_key': 'network_baseline',
                'description': '已命中 URL/Network，优先回看请求时机、参数来源和响应处理链。',
                'command_hint': '优先尝试网络分析场景',
                'source_reason': '结果摘要已命中 URL / Network 相关线索。',
                'expected_value': '更快定位请求时机、参数来源与响应处理链。',
                'risk_or_noise': '网络日志可能很多，需注意区分初始化噪音与真实业务请求。',
                'preferred_surface': 'scenario',
            },
            {
                'key': 'persist_summary',
                'label': '沉淀当前结果摘要',
                'entry_type': 'workspace_note',
                'target': 'noteappend_resultmeta',
                'scenario_key': '',
            },
        ],
    )

    window.terminal_console_controller.submit_command('runaction list')

    output = log_messages(window)[-1]
    assert ui_messages.RESULT_SUMMARY_ACTIONS_RUN_LIST_TITLE in output
    assert 'network_review: 回看网络链路 [scenario]' in output
    assert '来源说明：结果摘要已命中 URL / Network 相关线索。' in output
    assert '预期收益：更快定位请求时机、参数来源与响应处理链。' in output
    assert '风险/噪音：网络日志可能很多，需注意区分初始化噪音与真实业务请求。' in output
    assert 'persist_summary: 沉淀当前结果摘要 [workspace_note]' in output
    assert '建议入口：优先尝试网络分析场景' in output
    window.deleteLater()


def test_terminal_runaction_without_args_outputs_usage_and_list(qapp, dummy_deps, monkeypatch) -> None:
    window = build_main_window(dummy_deps)
    monkeypatch.setattr(
        window.log_panel_controller,
        'build_result_summary_actions',
        lambda: [
            {
                'key': 'network_review',
                'label': '回看网络链路',
                'entry_type': 'scenario',
                'target': 'network_baseline',
                'scenario_key': 'network_baseline',
                'description': '已命中 URL/Network，优先回看请求链路。',
                'command_hint': '优先尝试网络分析场景',
                'source_reason': '结果摘要已命中 URL / Network 相关线索。',
                'expected_value': '更快定位请求时机、参数来源与响应处理链。',
                'risk_or_noise': '网络日志可能很多，需注意区分初始化噪音与真实业务请求。',
                'preferred_surface': 'scenario',
            }
        ],
    )

    window.terminal_console_controller.submit_command('runaction')

    output = log_messages(window)[-1]
    assert ui_messages.RESULT_SUMMARY_ACTIONS_RUN_MISSING_ARGUMENT in output
    assert ui_messages.RESULT_SUMMARY_ACTIONS_RUN_USAGE_HINT in output
    assert 'network_review: 回看网络链路 [scenario]' in output
    assert '来源说明：结果摘要已命中 URL / Network 相关线索。' in output
    assert '预期收益：更快定位请求时机、参数来源与响应处理链。' in output
    window.deleteLater()


def test_terminal_workspacemeta_reuses_case_home_explanation_lines(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    dummy_deps.workspace_service.build_workspace_manifest = lambda package_name: {
        'package_name': package_name,
        'workspace_ready': True,
        'script_asset_count': 1,
        'pinned_script_count': 0,
        'recent_script_count': 0,
        'named_template_count': 1,
        'recommended_entrypoint': 'review_latest_result_summary',
        'case_entry_hint': '先查看最近结果摘要，再决定继续补脚本还是沉淀模板。',
        'latest_result_summary_excerpt': '发现登录 URL',
        'recommended_result_action_label': '回看网络链路',
        'recommended_result_action_description': '已命中 URL/Network，优先回看请求链路。',
        'notes_path': 'notes/analysis_notes.md',
        'notes_has_user_content': True,
        'notes_is_default_template': False,
        'pinned_scripts': [],
        'recent_scripts': [],
        'recent_session_count': 0,
        'recent_log_count': 0,
        'recent_logs': [],
        'updated_at': '2026-06-09T09:00:00+08:00',
        'last_session': None,
    }

    window.terminal_console_controller.submit_command('workspacemeta')

    message = window.log_panel_controller.log_records[-1].message
    assert '当前优先入口：先看最近结果摘要' in message
    assert '案例建议：先查看最近结果摘要，再决定继续补脚本还是沉淀模板。' in message
    assert '当前建议动作：回看网络链路' in message
    assert '动作说明：已命中 URL/Network，优先回看请求链路。' in message
    assert '首页可用入口：' in message
    assert '- 执行推荐动作：回看网络链路' in message
    assert '来源：最近结果摘要推导出的推荐动作 回看网络链路' in message
    assert '行为：复用当前结果建议执行链' in message
    assert '最近链路：' in message
    assert '最近结果：发现登录 URL' in message
    assert '最近脚本：-' in message
    window.deleteLater()


def test_terminal_workspacemeta_deduplicates_recent_flow_fields(qapp, dummy_deps) -> None:
    window = build_main_window(dummy_deps)
    prepare_current_app(window, dummy_deps)
    dummy_deps.workspace_service.build_workspace_manifest = lambda package_name: {
        'package_name': package_name,
        'workspace_ready': True,
        'script_asset_count': 2,
        'pinned_script_count': 1,
        'recent_script_count': 1,
        'named_template_count': 1,
        'recommended_entrypoint': 'resume_named_template',
        'case_entry_hint': '优先从最近模板继续',
        'latest_result_summary_excerpt': '发现登录 URL',
        'last_used_template_name': '网络首轮',
        'notes_path': 'notes/analysis_notes.md',
        'notes_has_user_content': True,
        'notes_is_default_template': False,
        'latest_result_summary_path': 'result_summary_latest.md',
        'latest_result_summary_exists': True,
        'pinned_scripts': ['alpha.js'],
        'recent_scripts': ['alpha.js'],
        'recent_session_count': 1,
        'recent_log_count': 1,
        'recent_logs': ['latest.log'],
        'last_session': {
            'timestamp': '2026-06-08T11:50:00+08:00',
            'script_name': 'alpha.js',
            'mode': 'attach',
            'summary': 'alpha session',
        },
    }

    window.terminal_console_controller.submit_command('workspacemeta')
    output = log_messages(window)[-1]
    assert '固定脚本 / 最近脚本：1 / 1' in output
    assert '最近链路：' in output
    assert output.count('最近会话：alpha.js / attach / alpha session') == 1
    assert '最近脚本：alpha.js' in output
    window.deleteLater()


def test_terminal_display_builder_builds_sessionmeta_and_logmeta_lines() -> None:
    from ui.display_builders import build_terminal_logmeta_lines, build_terminal_sessionmeta_lines

    session_lines = build_terminal_sessionmeta_lines(
        title='最近启动档案：alpha.js',
        timestamp='2026-06-08T10:30:00+08:00',
        mode='Attach',
        script='alpha.js',
        path_value='C:/demo/alpha.js',
        summary='alpha session',
    )
    logmeta_lines = build_terminal_logmeta_lines(
        logfile='demo.log',
        log_file_value='demo.log',
        manifest_path='C:/demo/demo.log.json',
        package_name='pkg.demo',
        script_name='alpha.js',
        mode='Attach',
        summary='login trace',
        exported_at='2026-06-08T11:00:00+08:00',
        script_path='C:/demo/alpha.js',
    )

    assert session_lines[0] == '最近启动档案：alpha.js'
    assert '模式：Attach' in session_lines
    assert '说明：alpha session' in session_lines
    assert logmeta_lines[0] == '日志 manifest：demo.log'
    assert '包名：pkg.demo' in logmeta_lines
    assert '说明：login trace' in logmeta_lines


def test_terminal_display_builder_builds_result_action_lines() -> None:
    from ui.display_builders import build_result_action_lines, build_result_action_list_lines

    actions = [{
        'key': 'review_latest_result_summary',
        'label': '回看结果',
        'description': '检查最近结果摘要',
        'entry_type': 'workspace',
        'target': 'summary',
    }]

    detail_lines = build_result_action_lines(actions)
    list_lines = build_result_action_list_lines(actions)

    assert detail_lines[0]
    assert '回看结果' in '\n'.join(detail_lines)
    assert any('review_latest_result_summary' in line for line in list_lines)


def test_terminal_display_builder_builds_help_text(qapp, dummy_deps) -> None:
    from ui.display_builders import build_terminal_help_text

    window = build_main_window(dummy_deps)
    text = build_terminal_help_text(
        header=ui_messages.TERMINAL_HELP_HEADER,
        category_order=window.terminal_console_controller.HELP_CATEGORY_ORDER,
        command_specs=window.terminal_console_controller.command_specs,
    )

    assert ui_messages.TERMINAL_HELP_HEADER in text
    assert '基础命令' in text
    assert 'Hook 命令' in text
    assert ui_messages.TERMINAL_HELP_SHELL_RULE in text
    assert 'attach okhttp.js' in text
    window.deleteLater()
