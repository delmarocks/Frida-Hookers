from __future__ import annotations

from pathlib import Path

import pytest

from core.errors import FridaServerStopError, HookStartError, HookStopError, RestartAppError
from PySide6.QtWidgets import QComboBox, QLabel, QPushButton

from core.errors import AttachStageError
from core.workspace_service import AdvancedLauncherNamedTemplate, AdvancedLauncherPresetEntry, ScriptMetadata, ScriptSourceInfo, SessionRecord
from ui import ui_messages
import ui.hook_runtime as hook_runtime_module
from ui.hook_runtime import HookRuntimeController, HookRuntimeWidgets
from ui.frida_multi_launcher_dialog import FridaScriptOption
from ui.quick_hook_actions import QUICK_HOOK_ACTIONS
from ui.workers.hook_worker import HookWorker


class _FakeSignal:
    def __init__(self) -> None:
        self._callbacks = []

    def connect(self, callback) -> None:
        self._callbacks.append(callback)

    def emit(self, *args, **kwargs) -> None:
        for callback in list(self._callbacks):
            callback(*args, **kwargs)


class _WorkerTestThread:
    def __init__(self, *_args, **_kwargs) -> None:
        self.started = _FakeSignal()
        self.finished = _FakeSignal()

    def start(self) -> None:
        self.started.emit()

    def quit(self) -> None:
        self.finished.emit()

    def deleteLater(self) -> None:
        return None


class _WorkerTestHookWorker:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.started = _FakeSignal()
        self.succeeded = _FakeSignal()
        self.failed = _FakeSignal()
        self.finished = _FakeSignal()

    def moveToThread(self, _thread):
        return None

    def run(self) -> None:
        result = self.kwargs.get('run_result')
        if isinstance(result, Exception):
            from core.errors import to_ui_error_payload
            self.failed.emit(to_ui_error_payload(result))
        elif result is not None:
            self.succeeded.emit(result)
        self.finished.emit()

    def deleteLater(self) -> None:
        return None


def _capturing_hook_worker(captured: dict):
    class FakeWorker(_WorkerTestHookWorker):
        def __init__(self, **kwargs):
            captured.update(kwargs)
            super().__init__(**kwargs)

    return FakeWorker


def build_controller(owner_widget, dummy_deps):
    busy_calls = []
    status_calls = []
    logs = []
    errors = []
    refresh_calls = []
    applied_payloads = []

    session_status_calls = []
    widgets = HookRuntimeWidgets(
        start_hook_button=QPushButton(),
        stop_hook_button=QPushButton(),
        current_state_label=QLabel(),
        app_combo=QComboBox(),
        set_session_status=lambda phase, mode=None, package=None, script=None, detail=None: session_status_calls.append((phase, mode, package, script, detail)),
    )

    def apply_apps_payload(apps, foreground_package=None):
        applied_payloads.append((apps, foreground_package))
        widgets.app_combo.clear()
        for app in apps:
            widgets.app_combo.addItem(app["name"], app["identifier"])

    controller = HookRuntimeController(
        owner=owner_widget,
        widgets=widgets,
        deps=dummy_deps,
        set_busy=lambda busy, message=None: busy_calls.append((busy, message)),
        set_status_text=lambda message, status=None: status_calls.append((message, status)),
        append_log=logs.append,
        show_worker_error=errors.append,
        selected_package_name=lambda: widgets.app_combo.currentData(),
        selected_script_path=lambda: None,
        ensure_current_app_ready=lambda: "pkg.demo",
        refresh_app_status_panel=lambda package=None: refresh_calls.append(package),
        apply_apps_payload=apply_apps_payload,
    )
    for action in QUICK_HOOK_ACTIONS:
        setattr(owner_widget, action.button_attr, QPushButton())
    return controller, widgets, busy_calls, status_calls, logs, errors, refresh_calls, applied_payloads, session_status_calls


def test_hook_runtime_initializes_session_status_idle(owner_widget, dummy_deps) -> None:
    _, _, _, _, _, _, _, _, session_status_calls = build_controller(owner_widget, dummy_deps)
    assert session_status_calls[-1][0] == ui_messages.SESSION_STATUS_PHASE_IDLE


def test_handle_session_event_updates_detached_state(owner_widget, dummy_deps) -> None:
    controller, widgets, _, status_calls, _, _, refresh_calls, _, session_status_calls = build_controller(owner_widget, dummy_deps)
    widgets.start_hook_button.setDisabled(True)
    widgets.stop_hook_button.setDisabled(False)
    controller.handle_session_event(
        "detached",
        {
            "package_name": "pkg.demo",
            "mode": "spawn",
            "old_pid": 100,
            "new_pid": 200,
        },
    )
    assert status_calls[-1] == (
        ui_messages.SESSION_DETACHED_PID_CHANGED_STATE.format(mode="spawn", old_pid=100, new_pid=200),
        ui_messages.SESSION_DETACHED_PID_CHANGED_STATUS.format(mode="spawn", new_pid=200),
    )
    assert not widgets.start_hook_button.isEnabled() is False
    assert widgets.stop_hook_button.isEnabled() is False
    assert refresh_calls[-1] == "pkg.demo"
    assert session_status_calls[-1][0] == ui_messages.SESSION_STATUS_PHASE_DETACHED


def test_handle_auto_stop_requested_starts_async_stop(owner_widget, dummy_deps) -> None:
    controller, _, busy_calls, _, logs, _, _, _, session_status_calls = build_controller(owner_widget, dummy_deps)
    dummy_deps.context.active_session = type("Session", (), {"mode": "spawn"})()
    captured = {}

    def fake_start_runtime_action(*, busy_message, action, on_success):
        captured["busy_message"] = busy_message
        captured["action"] = action
        captured["on_success"] = on_success

    controller.start_runtime_action = fake_start_runtime_action
    controller.handle_session_event(
        "auto_stop_requested",
        {"message": "网络栈识别观察窗口结束，正在自动停止 Hook。"},
    )

    assert logs[-1] == "[TOOL] 网络栈识别观察窗口结束，正在自动停止 Hook。"
    assert captured["busy_message"] == ui_messages.STOPPING_HOOK
    assert captured["action"] == dummy_deps.session_service.stop_active_session
    assert captured["on_success"] == controller.on_auto_stop_finished
    assert controller._auto_stop_in_progress is True
    assert session_status_calls[-1][0] == ui_messages.SESSION_STATUS_PHASE_AUTO_STOPPING


def test_start_hook_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)
    controller.start_hook(use_spawn=False)
    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY
    assert errors[-1].focus_target == "app_combo"


def test_start_hook_requires_selected_app_does_not_mark_session_failed(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _, session_status_calls = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)
    controller.start_hook(use_spawn=False)
    assert session_status_calls[-1][0] != ui_messages.SESSION_STATUS_PHASE_FAILED


def test_start_hook_requires_selected_script(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)
    controller.start_hook(use_spawn=False)
    assert errors
    assert errors[-1].title == ui_messages.SCRIPT_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.SCRIPT_NOT_SELECTED_BODY
    assert errors[-1].focus_target == "script_combo"


def test_resolve_quick_script_path_prefers_workspace_script(owner_widget, dummy_deps, tmp_path: Path) -> None:
    dummy_deps.context.hookers_js_dir = tmp_path / "hookers" / "js"
    dummy_deps.context.hookers_js_dir.mkdir(parents=True)
    builtin_script = dummy_deps.context.hookers_js_dir / "detect_network_stack.js"
    builtin_script.write_text("// builtin", encoding="utf-8")

    workspace_script_dir = tmp_path / "workspaces" / "pkg.demo" / "js"
    workspace_script_dir.mkdir(parents=True)
    workspace_script = workspace_script_dir / "detect_network_stack.js"
    workspace_script.write_text("// workspace", encoding="utf-8")

    dummy_deps.workspace_service.script_dir = lambda package_name: workspace_script_dir
    controller, _, _, _, _, _, _, _, _ = build_controller(owner_widget, dummy_deps)

    resolved = controller.resolve_quick_script_path("pkg.demo", "detect_network_stack.js")
    assert resolved == workspace_script


def test_resolve_builtin_quick_script_path_uses_builtin_script(owner_widget, dummy_deps, tmp_path: Path) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    builtin_script = builtin_script_dir / "detect_network_stack.js"
    builtin_script.write_text("// builtin", encoding="utf-8")

    workspace_script_dir = tmp_path / "workspaces" / "pkg.demo" / "js"
    workspace_script_dir.mkdir(parents=True)
    workspace_script = workspace_script_dir / "detect_network_stack.js"
    workspace_script.write_text("// workspace", encoding="utf-8")

    dummy_deps.context.hookers_js_dir = builtin_script_dir
    dummy_deps.workspace_service.script_dir = lambda package_name: workspace_script_dir
    controller, _, _, _, _, _, _, _, _ = build_controller(owner_widget, dummy_deps)

    resolved = controller.resolve_builtin_quick_script_path("detect_network_stack.js")
    assert resolved == builtin_script


def test_resolve_quick_script_path_falls_back_to_builtin_script(owner_widget, dummy_deps, tmp_path: Path) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    builtin_script = builtin_script_dir / "detect_network_stack.js"
    builtin_script.write_text("// builtin", encoding="utf-8")

    dummy_deps.context.hookers_js_dir = builtin_script_dir
    dummy_deps.workspace_service.script_dir = lambda package_name: tmp_path / "workspaces" / package_name / "js"
    controller, _, _, _, _, _, _, _, _ = build_controller(owner_widget, dummy_deps)

    resolved = controller.resolve_quick_script_path("pkg.demo", "detect_network_stack.js")
    assert resolved == builtin_script


def test_resolve_quick_script_path_raises_structured_error_when_missing(owner_widget, dummy_deps, tmp_path: Path) -> None:
    dummy_deps.context.hookers_js_dir = tmp_path / "hookers" / "js"
    dummy_deps.workspace_service.script_dir = lambda package_name: tmp_path / "workspaces" / package_name / "js"
    controller, _, _, _, _, _, _, _, _ = build_controller(owner_widget, dummy_deps)

    try:
        controller.resolve_quick_script_path("pkg.demo", "detect_network_stack.js")
        assert False, "expected HookStartError"
    except HookStartError as exc:
        assert "detect_network_stack.js" in exc.message
        assert exc.hint is not None


def test_start_script_command_missing_path_uses_shared_messages(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    controller.start_script_command("missing.js", use_spawn=False)

    assert errors
    assert errors[-1].message == ui_messages.BUILTIN_SCRIPT_NOT_FOUND_BODY.format(value="missing.js")
    assert errors[-1].hint == ui_messages.BUILTIN_SCRIPT_NOT_FOUND_HINT


def test_start_hook_requires_selected_script_does_not_mark_session_failed(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, _, _, _, session_status_calls = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    controller.start_hook(use_spawn=False)

    assert session_status_calls[-1][0] != ui_messages.SESSION_STATUS_PHASE_FAILED


def test_start_hook_active_session_blocks_launch_without_marking_script_used(owner_widget, dummy_deps, monkeypatch) -> None:
    controller, widgets, _, _, _, errors, _, _, session_status_calls = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)
    dummy_deps.context.active_session = type("Session", (), {"mode": "attach"})()
    monkeypatch.setattr(controller, "selected_script_path", lambda: Path(r"C:\demo\alpha.js"))

    controller.start_hook(use_spawn=False)

    assert errors
    assert errors[-1].message == ui_messages.ADVANCED_FRIDA_ACTIVE_SESSION_BODY
    assert errors[-1].next_step == ui_messages.ADVANCED_FRIDA_ACTIVE_SESSION_NEXT_STEP
    assert dummy_deps.workspace_service.mark_script_used_calls == []
    assert session_status_calls[-1][0] != ui_messages.SESSION_STATUS_PHASE_STARTING


def test_start_script_command_empty_input_does_not_mark_session_failed(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, _, _, _, session_status_calls = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    controller.start_script_command("   ", use_spawn=False)

    assert session_status_calls[-1][0] != ui_messages.SESSION_STATUS_PHASE_FAILED


def test_start_script_command_missing_path_does_not_mark_session_failed(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, _, _, _, session_status_calls = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    controller.start_script_command("missing.js", use_spawn=False)

    assert session_status_calls[-1][0] != ui_messages.SESSION_STATUS_PHASE_FAILED


def test_start_script_command_active_session_blocks_launch_without_marking_script_used(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _, session_status_calls = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)
    dummy_deps.context.active_session = type("Session", (), {"mode": "spawn"})()

    controller.start_script_command("alpha.js", use_spawn=False)

    assert errors
    assert errors[-1].message == ui_messages.ADVANCED_FRIDA_ACTIVE_SESSION_BODY
    assert errors[-1].next_step == ui_messages.ADVANCED_FRIDA_ACTIVE_SESSION_NEXT_STEP
    assert dummy_deps.workspace_service.mark_script_used_calls == []
    assert session_status_calls[-1][0] != ui_messages.SESSION_STATUS_PHASE_STARTING



def test_start_detect_network_stack_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)
    controller.start_detect_network_stack(use_spawn=True)
    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY
    assert errors[-1].focus_target == "app_combo"


def test_start_print_okhttp_interceptors_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)
    controller.start_print_okhttp_interceptors(use_spawn=True)
    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY
    assert errors[-1].focus_target == "app_combo"


def test_start_okhttp_capture_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)
    controller.start_okhttp_capture(use_spawn=False)
    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY
    assert errors[-1].focus_target == "app_combo"


def test_start_hook_register_natives_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)
    controller.start_hook_register_natives(use_spawn=True)
    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY
    assert errors[-1].focus_target == "app_combo"


def test_start_find_anti_frida_so_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)
    controller.start_find_anti_frida_so(use_spawn=True)
    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY
    assert errors[-1].focus_target == "app_combo"


def test_start_click_trace_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)
    controller.start_click_trace(use_spawn=False)
    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY
    assert errors[-1].focus_target == "app_combo"


def test_start_edit_text_trace_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)
    controller.start_edit_text_trace(use_spawn=True)
    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY
    assert errors[-1].focus_target == "app_combo"


def test_start_text_view_trace_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)
    controller.start_text_view_trace(use_spawn=False)
    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY
    assert errors[-1].focus_target == "app_combo"


def test_start_url_trace_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)
    controller.start_url_trace(use_spawn=True)
    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY
    assert errors[-1].focus_target == "app_combo"


def test_start_activity_events_trace_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)
    controller.start_activity_events_trace(use_spawn=False)
    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY
    assert errors[-1].focus_target == "app_combo"


def test_start_jni_method_trace_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)
    controller.start_jni_method_trace(use_spawn=True)
    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY
    assert errors[-1].focus_target == "app_combo"


def test_start_hook_encryption_algo_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)
    controller.start_quick_hook("hook_encryption_algo", selected_use_spawn=False)
    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY
    assert errors[-1].focus_target == "app_combo"


def test_start_hook_encryption_algo2_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)
    controller.start_quick_hook("hook_encryption_algo2", selected_use_spawn=True)
    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY
    assert errors[-1].focus_target == "app_combo"


def test_start_bypass_root_detect_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)
    controller.start_quick_hook("bypass_root_detect", selected_use_spawn=False)
    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY
    assert errors[-1].focus_target == "app_combo"


def test_start_bypass_vpn_detect_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)
    controller.start_quick_hook("bypass_vpn_detect", selected_use_spawn=True)
    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY
    assert errors[-1].focus_target == "app_combo"


def test_start_detect_network_stack_logs_and_uses_selected_mode(owner_widget, dummy_deps, tmp_path: Path) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    script_path = builtin_script_dir / "detect_network_stack.js"
    script_path.write_text("// builtin", encoding="utf-8")
    dummy_deps.context.hookers_js_dir = builtin_script_dir

    workspace_script_dir = tmp_path / "workspaces" / "pkg.demo" / "js"
    workspace_script_dir.mkdir(parents=True)
    (workspace_script_dir / "detect_network_stack.js").write_text("// workspace old", encoding="utf-8")
    dummy_deps.workspace_service.script_dir = lambda package_name: workspace_script_dir

    controller, widgets, busy_calls, _, logs, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    captured = {}

    import ui.hook_runtime as hook_runtime_module

    FakeWorker = _capturing_hook_worker(captured)

    original_thread = hook_runtime_module.QThread
    original_worker = hook_runtime_module.HookWorker
    hook_runtime_module.QThread = _WorkerTestThread
    hook_runtime_module.HookWorker = FakeWorker
    try:
        controller.start_detect_network_stack(use_spawn=False)
    finally:
        hook_runtime_module.QThread = original_thread
        hook_runtime_module.HookWorker = original_worker

    assert busy_calls[-1] == (True, ui_messages.DETECTING_NETWORK_STACK)
    assert logs[0] == ui_messages.NETWORK_STACK_ACTION_LOG
    assert logs[1] == ui_messages.NETWORK_STACK_SCRIPT_LOG.format(script_path=script_path)
    assert logs[2] == ui_messages.NETWORK_STACK_MODE_LOG.format(mode="attach")
    assert logs[3] == ui_messages.TARGET_APP_LOG.format(package="pkg.demo")
    assert logs[4] == ui_messages.SELECTED_SCRIPT_LOG.format(script_name="detect_network_stack.js")
    assert captured["package_name"] == "pkg.demo"
    assert captured["script_path"] == script_path
    assert captured["use_spawn"] is False
    assert captured["ensure_workspace"] is False


def test_start_print_okhttp_interceptors_logs_and_uses_selected_mode(owner_widget, dummy_deps, tmp_path: Path) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    script_path = builtin_script_dir / "print_okhttp_interceptors.js"
    script_path.write_text("// builtin", encoding="utf-8")
    dummy_deps.context.hookers_js_dir = builtin_script_dir

    controller, widgets, busy_calls, _, logs, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    captured = {}

    import ui.hook_runtime as hook_runtime_module

    FakeWorker = _capturing_hook_worker(captured)

    original_thread = hook_runtime_module.QThread
    original_worker = hook_runtime_module.HookWorker
    hook_runtime_module.QThread = _WorkerTestThread
    hook_runtime_module.HookWorker = FakeWorker
    try:
        controller.start_print_okhttp_interceptors(use_spawn=False)
    finally:
        hook_runtime_module.QThread = original_thread
        hook_runtime_module.HookWorker = original_worker

    assert busy_calls[-1] == (True, ui_messages.PRINTING_OKHTTP_INTERCEPTORS)
    assert logs[0] == ui_messages.OKHTTP_INTERCEPTORS_ACTION_LOG
    assert logs[1] == ui_messages.OKHTTP_INTERCEPTORS_SCRIPT_LOG.format(script_path=script_path)
    assert logs[2] == ui_messages.OKHTTP_INTERCEPTORS_MODE_LOG.format(mode="attach")
    assert logs[3] == ui_messages.TARGET_APP_LOG.format(package="pkg.demo")
    assert logs[4] == ui_messages.SELECTED_SCRIPT_LOG.format(script_name="print_okhttp_interceptors.js")
    assert captured["script_path"] == script_path
    assert captured["use_spawn"] is False
    assert captured["ensure_workspace"] is False


def test_start_okhttp_capture_logs_and_uses_selected_mode(owner_widget, dummy_deps, tmp_path: Path) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    script_path = builtin_script_dir / "okhttp.js"
    script_path.write_text("// builtin", encoding="utf-8")
    dummy_deps.context.hookers_js_dir = builtin_script_dir

    controller, widgets, busy_calls, _, logs, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    captured = {}

    import ui.hook_runtime as hook_runtime_module

    FakeWorker = _capturing_hook_worker(captured)

    original_thread = hook_runtime_module.QThread
    original_worker = hook_runtime_module.HookWorker
    hook_runtime_module.QThread = _WorkerTestThread
    hook_runtime_module.HookWorker = FakeWorker
    try:
        controller.start_okhttp_capture(use_spawn=True)
    finally:
        hook_runtime_module.QThread = original_thread
        hook_runtime_module.HookWorker = original_worker

    assert busy_calls[-1] == (True, ui_messages.CAPTURING_OKHTTP_TRAFFIC)
    assert logs[0] == ui_messages.OKHTTP_CAPTURE_ACTION_LOG
    assert logs[1] == ui_messages.OKHTTP_CAPTURE_SCRIPT_LOG.format(script_path=script_path)
    assert logs[2] == ui_messages.OKHTTP_CAPTURE_MODE_LOG.format(mode="spawn")
    assert logs[3] == ui_messages.TARGET_APP_LOG.format(package="pkg.demo")
    assert logs[4] == ui_messages.SELECTED_SCRIPT_LOG.format(script_name="okhttp.js")
    assert captured["script_path"] == script_path
    assert captured["use_spawn"] is True
    assert captured["ensure_workspace"] is False


def test_start_hook_register_natives_logs_and_uses_selected_mode(
    owner_widget, dummy_deps, tmp_path: Path
) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    script_path = builtin_script_dir / "hook_register_natives.js"
    script_path.write_text("// builtin", encoding="utf-8")
    dummy_deps.context.hookers_js_dir = builtin_script_dir

    controller, widgets, busy_calls, _, logs, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    captured = {}

    import ui.hook_runtime as hook_runtime_module

    FakeWorker = _capturing_hook_worker(captured)

    original_thread = hook_runtime_module.QThread
    original_worker = hook_runtime_module.HookWorker
    hook_runtime_module.QThread = _WorkerTestThread
    hook_runtime_module.HookWorker = FakeWorker
    try:
        controller.start_hook_register_natives(use_spawn=False)
    finally:
        hook_runtime_module.QThread = original_thread
        hook_runtime_module.HookWorker = original_worker

    assert busy_calls[-1] == (True, ui_messages.HOOKING_REGISTER_NATIVES)
    assert logs[0] == ui_messages.REGISTER_NATIVES_ACTION_LOG
    assert logs[1] == ui_messages.REGISTER_NATIVES_SCRIPT_LOG.format(script_path=script_path)
    assert logs[2] == ui_messages.REGISTER_NATIVES_MODE_LOG.format(mode="attach")
    assert logs[3] == ui_messages.TARGET_APP_LOG.format(package="pkg.demo")
    assert logs[4] == ui_messages.SELECTED_SCRIPT_LOG.format(
        script_name="hook_register_natives.js"
    )
    assert captured["script_path"] == script_path
    assert captured["use_spawn"] is False
    assert captured["ensure_workspace"] is False


def test_start_find_anti_frida_so_logs_and_uses_selected_mode(
    owner_widget, dummy_deps, tmp_path: Path
) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    script_path = builtin_script_dir / "find_anit_frida_so.js"
    script_path.write_text("// builtin", encoding="utf-8")
    dummy_deps.context.hookers_js_dir = builtin_script_dir

    controller, widgets, busy_calls, _, logs, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    captured = {}

    class FakeThread:
        def __init__(self, *_args, **_kwargs):
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def start(self):
            return None

        def quit(self):
            return None

        def deleteLater(self):
            return None

    class FakeWorker:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.failed = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def moveToThread(self, _thread):
            return None

        def deleteLater(self):
            return None

        def run(self):
            return None

    import ui.hook_runtime as hook_runtime_module

    original_thread = hook_runtime_module.QThread
    original_worker = hook_runtime_module.HookWorker
    hook_runtime_module.QThread = FakeThread
    hook_runtime_module.HookWorker = FakeWorker
    try:
        controller.start_find_anti_frida_so(use_spawn=False)
    finally:
        hook_runtime_module.QThread = original_thread
        hook_runtime_module.HookWorker = original_worker

    assert busy_calls[-1] == (True, ui_messages.FINDING_ANTI_FRIDA_SO)
    assert logs[0] == ui_messages.ANTI_FRIDA_SO_ACTION_LOG
    assert logs[1] == ui_messages.ANTI_FRIDA_SO_SCRIPT_LOG.format(script_path=script_path)
    assert logs[2] == ui_messages.ANTI_FRIDA_SO_MODE_LOG.format(mode="attach")
    assert logs[3] == ui_messages.TARGET_APP_LOG.format(package="pkg.demo")
    assert logs[4] == ui_messages.SELECTED_SCRIPT_LOG.format(
        script_name="find_anit_frida_so.js"
    )
    assert captured["script_path"] == script_path
    assert captured["use_spawn"] is False
    assert captured["ensure_workspace"] is False


def test_start_click_trace_logs_and_uses_selected_mode(
    owner_widget, dummy_deps, tmp_path: Path
) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    script_path = builtin_script_dir / "click.js"
    script_path.write_text("// builtin", encoding="utf-8")
    dummy_deps.context.hookers_js_dir = builtin_script_dir

    controller, widgets, busy_calls, _, logs, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    captured = {}

    class FakeThread:
        def __init__(self, *_args, **_kwargs):
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def start(self):
            return None

        def quit(self):
            return None

        def deleteLater(self):
            return None

    class FakeWorker:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.failed = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def moveToThread(self, _thread):
            return None

        def deleteLater(self):
            return None

        def run(self):
            return None

    import ui.hook_runtime as hook_runtime_module

    original_thread = hook_runtime_module.QThread
    original_worker = hook_runtime_module.HookWorker
    hook_runtime_module.QThread = FakeThread
    hook_runtime_module.HookWorker = FakeWorker
    try:
        controller.start_click_trace(use_spawn=False)
    finally:
        hook_runtime_module.QThread = original_thread
        hook_runtime_module.HookWorker = original_worker

    assert busy_calls[-1] == (True, ui_messages.TRACING_CLICK_EVENTS)
    assert logs[0] == ui_messages.CLICK_TRACE_ACTION_LOG
    assert logs[1] == ui_messages.CLICK_TRACE_SCRIPT_LOG.format(script_path=script_path)
    assert logs[2] == ui_messages.CLICK_TRACE_MODE_LOG.format(mode="attach")
    assert logs[3] == ui_messages.TARGET_APP_LOG.format(package="pkg.demo")
    assert logs[4] == ui_messages.SELECTED_SCRIPT_LOG.format(script_name="click.js")
    assert captured["script_path"] == script_path
    assert captured["use_spawn"] is False
    assert captured["ensure_workspace"] is False


def test_start_edit_text_trace_logs_and_uses_selected_mode(
    owner_widget, dummy_deps, tmp_path: Path
) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    script_path = builtin_script_dir / "edit_text.js"
    script_path.write_text("// builtin", encoding="utf-8")
    dummy_deps.context.hookers_js_dir = builtin_script_dir

    controller, widgets, busy_calls, _, logs, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    captured = {}

    class FakeThread:
        def __init__(self, *_args, **_kwargs):
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def start(self):
            return None

        def quit(self):
            return None

        def deleteLater(self):
            return None

    class FakeWorker:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.failed = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def moveToThread(self, _thread):
            return None

        def deleteLater(self):
            return None

        def run(self):
            return None

    import ui.hook_runtime as hook_runtime_module

    original_thread = hook_runtime_module.QThread
    original_worker = hook_runtime_module.HookWorker
    hook_runtime_module.QThread = FakeThread
    hook_runtime_module.HookWorker = FakeWorker
    try:
        controller.start_edit_text_trace(use_spawn=True)
    finally:
        hook_runtime_module.QThread = original_thread
        hook_runtime_module.HookWorker = original_worker

    assert busy_calls[-1] == (True, ui_messages.TRACING_EDIT_TEXT)
    assert logs[0] == ui_messages.EDIT_TEXT_TRACE_ACTION_LOG
    assert logs[1] == ui_messages.EDIT_TEXT_TRACE_SCRIPT_LOG.format(script_path=script_path)
    assert logs[2] == ui_messages.EDIT_TEXT_TRACE_MODE_LOG.format(mode="spawn")
    assert logs[3] == ui_messages.TARGET_APP_LOG.format(package="pkg.demo")
    assert logs[4] == ui_messages.SELECTED_SCRIPT_LOG.format(script_name="edit_text.js")
    assert captured["script_path"] == script_path
    assert captured["use_spawn"] is True
    assert captured["ensure_workspace"] is False


def test_start_text_view_trace_logs_and_uses_selected_mode(
    owner_widget, dummy_deps, tmp_path: Path
) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    script_path = builtin_script_dir / "text_view.js"
    script_path.write_text("// builtin", encoding="utf-8")
    dummy_deps.context.hookers_js_dir = builtin_script_dir

    controller, widgets, busy_calls, _, logs, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    captured = {}

    class FakeThread:
        def __init__(self, *_args, **_kwargs):
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def start(self):
            return None

        def quit(self):
            return None

        def deleteLater(self):
            return None

    class FakeWorker:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.failed = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def moveToThread(self, _thread):
            return None

        def deleteLater(self):
            return None

        def run(self):
            return None

    import ui.hook_runtime as hook_runtime_module

    original_thread = hook_runtime_module.QThread
    original_worker = hook_runtime_module.HookWorker
    hook_runtime_module.QThread = FakeThread
    hook_runtime_module.HookWorker = FakeWorker
    try:
        controller.start_text_view_trace(use_spawn=False)
    finally:
        hook_runtime_module.QThread = original_thread
        hook_runtime_module.HookWorker = original_worker

    assert busy_calls[-1] == (True, ui_messages.TRACING_TEXT_VIEW)
    assert logs[0] == ui_messages.TEXT_VIEW_TRACE_ACTION_LOG
    assert logs[1] == ui_messages.TEXT_VIEW_TRACE_SCRIPT_LOG.format(script_path=script_path)
    assert logs[2] == ui_messages.TEXT_VIEW_TRACE_MODE_LOG.format(mode="attach")
    assert logs[3] == ui_messages.TARGET_APP_LOG.format(package="pkg.demo")
    assert logs[4] == ui_messages.SELECTED_SCRIPT_LOG.format(script_name="text_view.js")
    assert captured["script_path"] == script_path
    assert captured["use_spawn"] is False
    assert captured["ensure_workspace"] is False


def test_start_url_trace_logs_and_uses_selected_mode(
    owner_widget, dummy_deps, tmp_path: Path
) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    script_path = builtin_script_dir / "url.js"
    script_path.write_text("// builtin", encoding="utf-8")
    dummy_deps.context.hookers_js_dir = builtin_script_dir

    controller, widgets, busy_calls, _, logs, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    captured = {}

    class FakeThread:
        def __init__(self, *_args, **_kwargs):
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def start(self):
            return None

        def quit(self):
            return None

        def deleteLater(self):
            return None

    class FakeWorker:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.failed = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def moveToThread(self, _thread):
            return None

        def deleteLater(self):
            return None

        def run(self):
            return None

    import ui.hook_runtime as hook_runtime_module

    original_thread = hook_runtime_module.QThread
    original_worker = hook_runtime_module.HookWorker
    hook_runtime_module.QThread = FakeThread
    hook_runtime_module.HookWorker = FakeWorker
    try:
        controller.start_url_trace(use_spawn=True)
    finally:
        hook_runtime_module.QThread = original_thread
        hook_runtime_module.HookWorker = original_worker

    assert busy_calls[-1] == (True, ui_messages.TRACING_URLS)
    assert logs[0] == ui_messages.URL_TRACE_ACTION_LOG
    assert logs[1] == ui_messages.URL_TRACE_SCRIPT_LOG.format(script_path=script_path)
    assert logs[2] == ui_messages.URL_TRACE_MODE_LOG.format(mode="spawn")
    assert logs[3] == ui_messages.TARGET_APP_LOG.format(package="pkg.demo")
    assert logs[4] == ui_messages.SELECTED_SCRIPT_LOG.format(script_name="url.js")
    assert captured["script_path"] == script_path
    assert captured["use_spawn"] is True
    assert captured["ensure_workspace"] is False


def test_start_activity_events_trace_logs_and_uses_selected_mode(
    owner_widget, dummy_deps, tmp_path: Path
) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    script_path = builtin_script_dir / "activity_events.js"
    script_path.write_text("// builtin", encoding="utf-8")
    dummy_deps.context.hookers_js_dir = builtin_script_dir

    controller, widgets, busy_calls, _, logs, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    captured = {}

    class FakeThread:
        def __init__(self, *_args, **_kwargs):
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def start(self):
            return None

        def quit(self):
            return None

        def deleteLater(self):
            return None

    class FakeWorker:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.failed = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def moveToThread(self, _thread):
            return None

        def deleteLater(self):
            return None

        def run(self):
            return None

    import ui.hook_runtime as hook_runtime_module

    original_thread = hook_runtime_module.QThread
    original_worker = hook_runtime_module.HookWorker
    hook_runtime_module.QThread = FakeThread
    hook_runtime_module.HookWorker = FakeWorker
    try:
        controller.start_activity_events_trace(use_spawn=False)
    finally:
        hook_runtime_module.QThread = original_thread
        hook_runtime_module.HookWorker = original_worker

    assert busy_calls[-1] == (True, ui_messages.TRACING_ACTIVITY_EVENTS)
    assert logs[0] == ui_messages.ACTIVITY_EVENTS_TRACE_ACTION_LOG
    assert logs[1] == ui_messages.ACTIVITY_EVENTS_TRACE_SCRIPT_LOG.format(script_path=script_path)
    assert logs[2] == ui_messages.ACTIVITY_EVENTS_TRACE_MODE_LOG.format(mode="attach")
    assert logs[3] == ui_messages.TARGET_APP_LOG.format(package="pkg.demo")
    assert logs[4] == ui_messages.SELECTED_SCRIPT_LOG.format(
        script_name="activity_events.js"
    )
    assert captured["script_path"] == script_path
    assert captured["use_spawn"] is False
    assert captured["ensure_workspace"] is False


def test_start_jni_method_trace_cancelled_input_does_nothing(
    owner_widget, dummy_deps, monkeypatch
) -> None:
    controller, widgets, busy_calls, _, logs, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)
    monkeypatch.setattr(
        "ui.hook_runtime.QInputDialog.getText",
        lambda *args, **kwargs: ("", False),
    )

    controller.start_jni_method_trace(use_spawn=False)

    assert busy_calls == []
    assert logs == []
    assert errors == []


def test_start_jni_method_trace_requires_non_empty_so(
    owner_widget, dummy_deps, monkeypatch
) -> None:
    controller, widgets, _, _, _, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)
    monkeypatch.setattr(
        "ui.hook_runtime.QInputDialog.getText",
        lambda *args, **kwargs: ("   ", True),
    )

    controller.start_jni_method_trace(use_spawn=False)

    assert errors
    assert errors[-1].title == ui_messages.MISSING_TARGET_TITLE
    assert errors[-1].message == ui_messages.JNI_TARGET_SO_REQUIRED_BODY


def test_start_jni_method_trace_requires_so_suffix(
    owner_widget, dummy_deps, monkeypatch
) -> None:
    controller, widgets, _, _, _, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)
    monkeypatch.setattr(
        "ui.hook_runtime.QInputDialog.getText",
        lambda *args, **kwargs: ("libdemo", True),
    )

    controller.start_jni_method_trace(use_spawn=False)

    assert errors
    assert errors[-1].title == ui_messages.MISSING_TARGET_TITLE
    assert errors[-1].message == ui_messages.JNI_TARGET_SO_INVALID_BODY


def test_start_jni_method_trace_logs_uses_selected_mode_and_remembers_target_so(
    owner_widget, dummy_deps, tmp_path: Path, monkeypatch
) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    script_template = builtin_script_dir / "jni_method_trace.js"
    script_template.write_text(
        'var TARGET_SO = "__HOOKERS_TARGET_SO__";\nconsole.log(TARGET_SO);\n',
        encoding="utf-8",
    )
    dummy_deps.context.hookers_js_dir = builtin_script_dir

    workspace_script_dir = tmp_path / "workspaces" / "pkg.demo" / "js"
    dummy_deps.workspace_service.script_dir = lambda package_name: workspace_script_dir

    controller, widgets, busy_calls, _, logs, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    captured = {"dialog_texts": []}

    def fake_get_text(*args, **kwargs):
        captured["dialog_texts"].append(kwargs.get("text", ""))
        return ("libtarget.so", True)

    class FakeThread:
        def __init__(self, *_args, **_kwargs):
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def start(self):
            return None

        def quit(self):
            return None

        def deleteLater(self):
            return None

    class FakeWorker:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.failed = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def moveToThread(self, _thread):
            return None

        def deleteLater(self):
            return None

        def run(self):
            return None

    monkeypatch.setattr("ui.hook_runtime.QInputDialog.getText", fake_get_text)

    import ui.hook_runtime as hook_runtime_module

    original_thread = hook_runtime_module.QThread
    original_worker = hook_runtime_module.HookWorker
    hook_runtime_module.QThread = FakeThread
    hook_runtime_module.HookWorker = FakeWorker
    try:
        controller.start_jni_method_trace(use_spawn=True)
        controller._clear_hook_thread()
        controller.start_jni_method_trace(use_spawn=False)
    finally:
        hook_runtime_module.QThread = original_thread
        hook_runtime_module.HookWorker = original_worker

    runtime_script_path = workspace_script_dir / "jni_method_trace.runtime.js"
    assert runtime_script_path.is_file()
    runtime_script = runtime_script_path.read_text(encoding="utf-8")
    assert "__HOOKERS_TARGET_SO__" not in runtime_script
    assert "libtarget.so" in runtime_script

    assert busy_calls[-1] == (True, ui_messages.TRACING_JNI_METHODS)
    assert logs[0] == ui_messages.JNI_METHOD_TRACE_ACTION_LOG
    assert logs[1] == ui_messages.JNI_METHOD_TRACE_SCRIPT_LOG.format(
        script_path=runtime_script_path
    )
    assert logs[2] == ui_messages.JNI_METHOD_TRACE_TARGET_SO_LOG.format(
        target_so="libtarget.so"
    )
    assert logs[3] == ui_messages.JNI_METHOD_TRACE_MODE_LOG.format(mode="spawn")
    assert logs[4] == ui_messages.TARGET_APP_LOG.format(package="pkg.demo")
    assert logs[5] == ui_messages.SELECTED_SCRIPT_LOG.format(
        script_name="jni_method_trace.runtime.js"
    )
    assert captured["script_path"] == runtime_script_path
    assert captured["use_spawn"] is False
    assert captured["ensure_workspace"] is False
    assert captured["dialog_texts"][0] == ""
    assert captured["dialog_texts"][1] == "libtarget.so"


def test_start_trace_init_proc_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)
    controller.start_trace_init_proc(use_spawn=True)
    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY
    assert errors[-1].focus_target == "app_combo"


def test_start_analysis_scenario_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)

    controller.start_analysis_scenario("network_baseline", use_spawn=False)

    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY


def test_start_analysis_scenario_materializes_bundle_and_logs_scene(owner_widget, dummy_deps, tmp_path: Path, monkeypatch) -> None:
    package_name = "pkg.demo"
    builtin_dir = tmp_path / "hookers" / "js"
    builtin_dir.mkdir(parents=True, exist_ok=True)
    for name in ("detect_network_stack.js", "print_okhttp_interceptors.js", "url.js"):
        (builtin_dir / name).write_text(f"// {name}", encoding="utf-8")
    dummy_deps.context.hookers_js_dir = builtin_dir

    bundle_path = tmp_path / "workspaces" / package_name / "js" / "frida_multi_bundle.runtime.js"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    def fake_materialize(_package_name, script_paths, *, output_name="frida_multi_bundle.runtime.js"):
        bundle_path.write_text("// bundle", encoding="utf-8")
        return bundle_path
    dummy_deps.workspace_service.materialize_multi_script_bundle = fake_materialize

    controller, widgets, _, _, logs, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", package_name)
    widgets.app_combo.setCurrentIndex(0)

    captured = {}
    monkeypatch.setattr(
        controller,
        "_start_launch_request",
        lambda request: captured.setdefault("request", request),
    )

    controller.start_analysis_scenario("network_baseline", use_spawn=False)

    request = captured["request"]
    assert request.package_name == package_name
    assert request.script_path == bundle_path
    assert request.use_spawn is False
    assert request.action_log == ui_messages.ANALYSIS_SCENARIO_NETWORK_ACTION_LOG
    assert "detect_network_stack.js" in request.order_log_message
    assert "print_okhttp_interceptors.js" in request.order_log_message
    assert "url.js" in request.order_log_message
    assert ui_messages.ANALYSIS_SCENARIO_MODE_LOG.format(mode="attach") in request.note_log_message


def test_open_analysis_scenario_as_template_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)

    controller.open_analysis_scenario_as_template("network_baseline", use_spawn=False)

    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY


def test_open_analysis_scenario_as_template_does_not_start_launch_request(
    owner_widget, dummy_deps, tmp_path: Path, monkeypatch
) -> None:
    package_name = 'pkg.demo'
    controller, widgets, _, _, logs, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem('Demo', package_name)
    widgets.app_combo.setCurrentIndex(0)

    resolved_option = FridaScriptOption(
        label='jni_method_trace.runtime.js',
        path=tmp_path / 'workspaces' / package_name / 'js' / 'jni_method_trace.runtime.js',
        kind='jni_method_trace',
        source_kind='workspace',
        display_name='jni_method_trace.runtime.js',
        summary='libfoo.so',
        runtime_key='jni_method_trace',
    )
    monkeypatch.setattr(
        controller,
        '_resolve_analysis_scenario_options',
        lambda package_name, scenario_key: ([resolved_option], '首轮 JNI / Native 分析：草稿模板'),
    )

    launch_called = {'value': False}
    monkeypatch.setattr(controller, '_start_launch_request', lambda request: launch_called.__setitem__('value', True))

    captured = {}

    class FakeDialog:
        def __init__(self, *_args, **kwargs):
            captured['initial_selected_options'] = kwargs.get('initial_selected_options')

        def exec(self):
            return 0

    monkeypatch.setattr('ui.hook_runtime.FridaMultiLauncherDialog', FakeDialog)

    controller.open_analysis_scenario_as_template('native_baseline', use_spawn=True)

    assert launch_called['value'] is False
    assert logs == []
    assert errors == []
    assert any(getattr(option, 'runtime_key', None) == 'jni_method_trace' for option in captured['initial_selected_options'])


def test_start_analysis_scenario_resolves_parameterized_entry(owner_widget, dummy_deps, tmp_path: Path, monkeypatch) -> None:
    package_name = "pkg.demo"
    builtin_dir = tmp_path / "hookers" / "js"
    builtin_dir.mkdir(parents=True, exist_ok=True)
    (builtin_dir / "hook_register_natives.js").write_text("// register", encoding="utf-8")
    (builtin_dir / "jni_method_trace.js").write_text("// template", encoding="utf-8")
    dummy_deps.context.hookers_js_dir = builtin_dir

    runtime_path = tmp_path / "workspaces" / package_name / "js" / "jni_method_trace.runtime.js"
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text("// runtime", encoding="utf-8")
    monkeypatch.setattr(
        controller := build_controller(owner_widget, dummy_deps)[0],
        "_resolve_advanced_frida_option",
        lambda package_name, option: (
            FridaScriptOption(
                label=option.label,
                path=runtime_path,
                kind=option.kind,
                source_kind=option.source_kind,
                display_name=runtime_path.name,
                summary="libfoo.so",
                template_path=option.path,
                runtime_key="jni_method_trace",
            )
            if option.kind == "jni_method_trace"
            else option
        ),
    )
    widgets = build_controller(owner_widget, dummy_deps)[1]
    # rebuild with patched controller references for remaining state
    controller, widgets, _, _, _, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    monkeypatch.setattr(
        controller,
        "_resolve_advanced_frida_option",
        lambda package_name, option: (
            FridaScriptOption(
                label=option.label,
                path=runtime_path,
                kind=option.kind,
                source_kind=option.source_kind,
                display_name=runtime_path.name,
                summary="libfoo.so",
                template_path=option.path,
                runtime_key="jni_method_trace",
            )
            if option.kind == "jni_method_trace"
            else option
        ),
    )
    widgets.app_combo.addItem("Demo", package_name)
    widgets.app_combo.setCurrentIndex(0)

    resolved = controller._resolve_analysis_scenario_options(package_name, "native_baseline")

    assert resolved is not None
    options, note = resolved
    assert len(options) == 2
    assert any(option.path == runtime_path for option in options)
    assert "首轮 JNI / Native 分析" in note


def test_start_trace_init_proc_cancelled_dialog_does_nothing(
    owner_widget, dummy_deps, monkeypatch
) -> None:
    controller, widgets, busy_calls, _, logs, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    class FakeDialog:
        def __init__(self, *args, **kwargs):
            return None

        def exec(self):
            return 0

    monkeypatch.setattr("ui.hook_runtime.TraceInitProcDialog", FakeDialog)

    controller.start_trace_init_proc(use_spawn=False)

    assert busy_calls == []
    assert logs == []
    assert errors == []


def test_start_trace_init_proc_requires_valid_inputs(
    owner_widget, dummy_deps, monkeypatch
) -> None:
    controller, widgets, _, _, _, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    def run_with(values):
        class FakeDialog:
            def __init__(self, *args, **kwargs):
                return None

            def exec(self):
                return 1

            def values(self):
                return type("Params", (), values)()

        monkeypatch.setattr("ui.hook_runtime.TraceInitProcDialog", FakeDialog)
        controller.start_trace_init_proc(use_spawn=False)
        return errors[-1]

    payload = run_with({"target_so": " ", "start_addr": "0x10", "end_addr": "0x20"})
    assert payload.message == ui_messages.TRACE_INIT_PROC_REQUIRED_SO_BODY

    payload = run_with({"target_so": "libdemo", "start_addr": "0x10", "end_addr": "0x20"})
    assert payload.message == ui_messages.TRACE_INIT_PROC_INVALID_SO_BODY

    payload = run_with({"target_so": "libdemo.so", "start_addr": " ", "end_addr": "0x20"})
    assert payload.message == ui_messages.TRACE_INIT_PROC_REQUIRED_START_BODY

    payload = run_with({"target_so": "libdemo.so", "start_addr": "0x10", "end_addr": " "})
    assert payload.message == ui_messages.TRACE_INIT_PROC_REQUIRED_END_BODY

    payload = run_with({"target_so": "libdemo.so", "start_addr": "xyz", "end_addr": "0x20"})
    assert payload.message == ui_messages.TRACE_INIT_PROC_INVALID_ADDR_BODY

    payload = run_with({"target_so": "libdemo.so", "start_addr": "0x30", "end_addr": "0x20"})
    assert payload.message == ui_messages.TRACE_INIT_PROC_RANGE_BODY


def test_start_trace_init_proc_logs_uses_selected_mode_and_remembers_inputs(
    owner_widget, dummy_deps, tmp_path: Path, monkeypatch
) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    script_template = builtin_script_dir / "trace_init_proc.js"
    script_template.write_text(
        'var startAddr = __HOOKERS_TRACE_START_ADDR__;\n'
        'var endAddr = __HOOKERS_TRACE_END_ADDR__;\n'
        'var somodule = "__HOOKERS_TRACE_SO__";\n',
        encoding="utf-8",
    )
    dummy_deps.context.hookers_js_dir = builtin_script_dir

    workspace_script_dir = tmp_path / "workspaces" / "pkg.demo" / "js"
    dummy_deps.workspace_service.script_dir = lambda package_name: workspace_script_dir

    controller, widgets, busy_calls, _, logs, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    captured = {"dialog_values": []}

    class FakeDialog:
        def __init__(self, *_args, **kwargs):
            captured["dialog_values"].append(
                (
                    kwargs.get("target_so", ""),
                    kwargs.get("start_addr", ""),
                    kwargs.get("end_addr", ""),
                )
            )

        def exec(self):
            return 1

        def values(self):
            return type(
                "Params",
                (),
                {
                    "target_so": "libtarget.so",
                    "start_addr": "1234",
                    "end_addr": "0x2345",
                },
            )()

    class FakeThread:
        def __init__(self, *_args, **_kwargs):
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def start(self):
            return None

        def quit(self):
            return None

        def deleteLater(self):
            return None

    class FakeWorker:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.failed = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def moveToThread(self, _thread):
            return None

        def deleteLater(self):
            return None

        def run(self):
            return None

    monkeypatch.setattr("ui.hook_runtime.TraceInitProcDialog", FakeDialog)

    import ui.hook_runtime as hook_runtime_module

    original_thread = hook_runtime_module.QThread
    original_worker = hook_runtime_module.HookWorker
    hook_runtime_module.QThread = FakeThread
    hook_runtime_module.HookWorker = FakeWorker
    try:
        controller.start_trace_init_proc(use_spawn=True)
        controller._clear_hook_thread()
        controller.start_trace_init_proc(use_spawn=False)
    finally:
        hook_runtime_module.QThread = original_thread
        hook_runtime_module.HookWorker = original_worker

    runtime_script_path = workspace_script_dir / "trace_init_proc.runtime.js"
    assert runtime_script_path.is_file()
    runtime_script = runtime_script_path.read_text(encoding="utf-8")
    assert "__HOOKERS_TRACE_SO__" not in runtime_script
    assert "__HOOKERS_TRACE_START_ADDR__" not in runtime_script
    assert "__HOOKERS_TRACE_END_ADDR__" not in runtime_script
    assert 'var somodule = "libtarget.so";' in runtime_script
    assert "var startAddr = 0x1234;" in runtime_script
    assert "var endAddr = 0x2345;" in runtime_script

    assert busy_calls[-1] == (True, ui_messages.TRACING_INIT_PROC)
    assert logs[0] == ui_messages.TRACE_INIT_PROC_ACTION_LOG
    assert logs[1] == ui_messages.TRACE_INIT_PROC_SCRIPT_LOG.format(script_path=runtime_script_path)
    assert logs[2] == ui_messages.TRACE_INIT_PROC_PARAMS_LOG.format(
        target_so="libtarget.so",
        start_addr="0x1234",
        end_addr="0x2345",
    )
    assert logs[3] == ui_messages.TRACE_INIT_PROC_MODE_LOG.format(mode="spawn")
    assert logs[4] == ui_messages.TARGET_APP_LOG.format(package="pkg.demo")
    assert logs[5] == ui_messages.SELECTED_SCRIPT_LOG.format(
        script_name="trace_init_proc.runtime.js"
    )
    assert captured["script_path"] == runtime_script_path
    assert captured["use_spawn"] is False
    assert captured["ensure_workspace"] is False
    assert captured["dialog_values"][0] == ("", "", "")
    assert captured["dialog_values"][1] == ("libtarget.so", "0x1234", "0x2345")


def test_start_advanced_frida_launcher_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)

    controller.start_advanced_frida_launcher(use_spawn=True)

    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY
    assert errors[-1].focus_target == "app_combo"


def test_start_advanced_frida_launcher_rejects_when_active_session_exists(
    owner_widget, dummy_deps, monkeypatch
) -> None:
    controller, widgets, _, _, _, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)
    dummy_deps.context.active_session = type("Session", (), {"mode": "spawn"})()

    called = {"dialog": False}

    class FakeDialog:
        def __init__(self, *_args, **_kwargs):
            called["dialog"] = True

    monkeypatch.setattr("ui.hook_runtime.FridaMultiLauncherDialog", FakeDialog)

    controller.start_advanced_frida_launcher(use_spawn=True)

    assert errors
    assert errors[-1].message == ui_messages.ADVANCED_FRIDA_ACTIVE_SESSION_BODY
    assert called["dialog"] is False


def test_start_advanced_frida_launcher_logs_and_uses_selected_mode(
    owner_widget, dummy_deps, tmp_path: Path, monkeypatch
) -> None:
    workspace_script_dir = tmp_path / "workspaces" / "pkg.demo" / "js"
    workspace_script_dir.mkdir(parents=True)
    workspace_script = workspace_script_dir / "alpha.js"
    workspace_script.write_text("// alpha", encoding="utf-8")

    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    builtin_script = builtin_script_dir / "beta.js"
    builtin_script.write_text("// beta", encoding="utf-8")
    dummy_deps.context.hookers_js_dir = builtin_script_dir
    dummy_deps.workspace_service.list_scripts = lambda package_name: [workspace_script]

    bundle_path = workspace_script_dir / "frida_multi_bundle.runtime.js"
    captured: dict[str, object] = {}

    def fake_materialize(package_name, script_paths, *, output_name="frida_multi_bundle.runtime.js"):
        captured["bundle_args"] = (package_name, list(script_paths), output_name)
        bundle_path.write_text("// bundle", encoding="utf-8")
        return bundle_path

    dummy_deps.workspace_service.materialize_multi_script_bundle = fake_materialize

    class FakeDialog:
        def __init__(self, *_args, **kwargs):
            captured["dialog_kwargs"] = kwargs

        def exec(self):
            return 1

        def selected_options(self):
            from ui.frida_multi_launcher_dialog import FridaScriptOption

            return [
                FridaScriptOption(label="[工作区] alpha.js", path=workspace_script),
                FridaScriptOption(label="[内置源] beta.js", path=builtin_script),
            ]

    class FakeThread:
        def __init__(self, *_args, **_kwargs):
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def start(self):
            return None

        def quit(self):
            return None

        def deleteLater(self):
            return None

    class FakeWorker:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.failed = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def moveToThread(self, _thread):
            return None

        def deleteLater(self):
            return None

        def run(self):
            return None

    controller, widgets, busy_calls, _, logs, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    monkeypatch.setattr("ui.hook_runtime.FridaMultiLauncherDialog", FakeDialog)

    import ui.hook_runtime as hook_runtime_module

    original_thread = hook_runtime_module.QThread
    original_worker = hook_runtime_module.HookWorker
    hook_runtime_module.QThread = FakeThread
    hook_runtime_module.HookWorker = FakeWorker
    try:
        controller.start_advanced_frida_launcher(use_spawn=True)
    finally:
        hook_runtime_module.QThread = original_thread
        hook_runtime_module.HookWorker = original_worker

    assert captured["dialog_kwargs"]["package_name"] == "pkg.demo"
    assert captured["dialog_kwargs"]["mode"] == "spawn"
    assert busy_calls[-1] == (True, ui_messages.STARTING_ADVANCED_FRIDA)
    assert logs[0] == ui_messages.ADVANCED_FRIDA_ACTION_LOG
    assert logs[1] == ui_messages.ADVANCED_FRIDA_BUNDLE_LOG.format(script_path=bundle_path)
    assert logs[2] == ui_messages.ADVANCED_FRIDA_ORDER_LOG.format(
        scripts="[工作区] alpha.js -> [内置源] beta.js"
    )
    assert logs[3] == ui_messages.TARGET_APP_LOG.format(package="pkg.demo")
    assert logs[4] == ui_messages.SELECTED_SCRIPT_LOG.format(
        script_name="frida_multi_bundle.runtime.js"
    )
    assert captured["bundle_args"] == (
        "pkg.demo",
        [workspace_script, builtin_script],
        "frida_multi_bundle.runtime.js",
    )
    assert captured["script_path"] == bundle_path
    assert captured["use_spawn"] is True


def test_start_advanced_frida_launcher_parameterized_jni_option_materializes_runtime_on_add(
    owner_widget, dummy_deps, tmp_path: Path, monkeypatch
) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    template = builtin_script_dir / "jni_method_trace.js"
    template.write_text('var so = "__HOOKERS_TARGET_SO__";', encoding="utf-8")
    dummy_deps.context.hookers_js_dir = builtin_script_dir

    workspace_script_dir = tmp_path / "workspaces" / "pkg.demo" / "js"
    dummy_deps.workspace_service.script_dir = lambda package_name: workspace_script_dir
    dummy_deps.workspace_service.list_scripts = lambda package_name: []

    bundle_path = workspace_script_dir / "frida_multi_bundle.runtime.js"
    captured: dict[str, object] = {"selected_options": []}

    def fake_materialize(package_name, script_paths, *, output_name="frida_multi_bundle.runtime.js"):
        captured["bundle_args"] = (package_name, list(script_paths), output_name)
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text("// bundle", encoding="utf-8")
        return bundle_path

    dummy_deps.workspace_service.materialize_multi_script_bundle = fake_materialize

    class FakeDialog:
        def __init__(self, *_args, **kwargs):
            options = kwargs["options"]
            resolver = kwargs["add_option_resolver"]
            target = next(option for option in options if option.path.name == "jni_method_trace.js")
            resolved = resolver(target)
            if resolved is not None:
                captured["selected_options"].append(resolved)

        def exec(self):
            return 1

        def selected_options(self):
            return list(captured["selected_options"])

        def had_add_cancelled(self):
            return True

    monkeypatch.setattr("ui.hook_runtime.FridaMultiLauncherDialog", FakeDialog)
    monkeypatch.setattr(
        "ui.hook_runtime.QInputDialog.getText",
        lambda *args, **kwargs: ("libtarget.so", True),
    )

    class FakeThread:
        def __init__(self, *_args, **_kwargs):
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def start(self):
            return None

        def quit(self):
            return None

        def deleteLater(self):
            return None

    class FakeWorker:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.failed = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def moveToThread(self, _thread):
            return None

        def deleteLater(self):
            return None

        def run(self):
            return None

    controller, widgets, _, _, logs, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    import ui.hook_runtime as hook_runtime_module

    original_thread = hook_runtime_module.QThread
    original_worker = hook_runtime_module.HookWorker
    hook_runtime_module.QThread = FakeThread
    hook_runtime_module.HookWorker = FakeWorker
    try:
        controller.start_advanced_frida_launcher(use_spawn=False)
    finally:
        hook_runtime_module.QThread = original_thread
        hook_runtime_module.HookWorker = original_worker

    runtime_script_paths = list(workspace_script_dir.glob("jni_method_trace.*.runtime.js"))
    assert len(runtime_script_paths) == 1
    runtime_script_path = runtime_script_paths[0]
    assert runtime_script_path.read_text(encoding="utf-8") == 'var so = "libtarget.so";'
    assert captured["bundle_args"] == (
        "pkg.demo",
        [runtime_script_path],
        "frida_multi_bundle.runtime.js",
    )
    assert logs[2] == ui_messages.ADVANCED_FRIDA_ORDER_LOG.format(
        scripts="[参数化] [工作区] jni_method_trace.runtime.js (libtarget.so)"
    )


def test_start_advanced_frida_launcher_parameterized_trace_init_option_materializes_runtime_on_add(
    owner_widget, dummy_deps, tmp_path: Path, monkeypatch
) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    template = builtin_script_dir / "trace_init_proc.js"
    template.write_text(
        'var startAddr = __HOOKERS_TRACE_START_ADDR__;\n'
        'var endAddr = __HOOKERS_TRACE_END_ADDR__;\n'
        'var somodule = "__HOOKERS_TRACE_SO__";\n',
        encoding="utf-8",
    )
    dummy_deps.context.hookers_js_dir = builtin_script_dir

    workspace_script_dir = tmp_path / "workspaces" / "pkg.demo" / "js"
    dummy_deps.workspace_service.script_dir = lambda package_name: workspace_script_dir
    dummy_deps.workspace_service.list_scripts = lambda package_name: []

    bundle_path = workspace_script_dir / "frida_multi_bundle.runtime.js"
    captured: dict[str, object] = {"selected_options": []}

    def fake_materialize(package_name, script_paths, *, output_name="frida_multi_bundle.runtime.js"):
        captured["bundle_args"] = (package_name, list(script_paths), output_name)
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text("// bundle", encoding="utf-8")
        return bundle_path

    dummy_deps.workspace_service.materialize_multi_script_bundle = fake_materialize

    class FakeDialog:
        def __init__(self, *_args, **kwargs):
            options = kwargs["options"]
            resolver = kwargs["add_option_resolver"]
            target = next(option for option in options if option.path.name == "trace_init_proc.js")
            resolved = resolver(target)
            if resolved is not None:
                captured["selected_options"].append(resolved)

        def exec(self):
            return 1

        def selected_options(self):
            return list(captured["selected_options"])

    class FakeParamDialog:
        def __init__(self, *args, **kwargs):
            return None

        def exec(self):
            return 1

        def values(self):
            return type(
                "Params",
                (),
                {
                    "target_so": "libtrace.so",
                    "start_addr": "1234",
                    "end_addr": "2345",
                },
            )()

    monkeypatch.setattr("ui.hook_runtime.FridaMultiLauncherDialog", FakeDialog)
    monkeypatch.setattr("ui.hook_runtime.TraceInitProcDialog", FakeParamDialog)

    class FakeThread:
        def __init__(self, *_args, **_kwargs):
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def start(self):
            return None

        def quit(self):
            return None

        def deleteLater(self):
            return None

    class FakeWorker:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.failed = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def moveToThread(self, _thread):
            return None

        def deleteLater(self):
            return None

        def run(self):
            return None

    controller, widgets, _, _, logs, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    import ui.hook_runtime as hook_runtime_module

    original_thread = hook_runtime_module.QThread
    original_worker = hook_runtime_module.HookWorker
    hook_runtime_module.QThread = FakeThread
    hook_runtime_module.HookWorker = FakeWorker
    try:
        controller.start_advanced_frida_launcher(use_spawn=True)
    finally:
        hook_runtime_module.QThread = original_thread
        hook_runtime_module.HookWorker = original_worker

    runtime_script_paths = list(workspace_script_dir.glob("trace_init_proc.*.runtime.js"))
    assert len(runtime_script_paths) == 1
    runtime_script_path = runtime_script_paths[0]
    content = runtime_script_path.read_text(encoding="utf-8")
    assert 'var somodule = "libtrace.so";' in content
    assert "var startAddr = 0x1234;" in content
    assert "var endAddr = 0x2345;" in content
    assert captured["bundle_args"] == (
        "pkg.demo",
        [runtime_script_path],
        "frida_multi_bundle.runtime.js",
    )
    assert logs[2] == ui_messages.ADVANCED_FRIDA_ORDER_LOG.format(
        scripts="[参数化] [工作区] trace_init_proc.runtime.js (libtrace.so, 0x1234-0x2345)"
    )


def test_start_advanced_frida_launcher_parameterized_option_cancelled_does_not_add(
    owner_widget, dummy_deps, tmp_path: Path, monkeypatch
) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    (builtin_script_dir / "jni_method_trace.js").write_text(
        'var so = "__HOOKERS_TARGET_SO__";',
        encoding="utf-8",
    )
    dummy_deps.context.hookers_js_dir = builtin_script_dir
    dummy_deps.workspace_service.list_scripts = lambda package_name: []

    captured: dict[str, object] = {"selected_options": []}

    class FakeDialog:
        def __init__(self, *_args, **kwargs):
            options = kwargs["options"]
            resolver = kwargs["add_option_resolver"]
            target = next(option for option in options if option.path.name == "jni_method_trace.js")
            resolved = resolver(target)
            if resolved is not None:
                captured["selected_options"].append(resolved)

        def exec(self):
            return 1

        def selected_options(self):
            return list(captured["selected_options"])

        def had_add_cancelled(self):
            return True

    monkeypatch.setattr("ui.hook_runtime.FridaMultiLauncherDialog", FakeDialog)
    monkeypatch.setattr(
        "ui.hook_runtime.QInputDialog.getText",
        lambda *args, **kwargs: ("", False),
    )

    controller, widgets, busy_calls, _, logs, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    controller.start_advanced_frida_launcher(use_spawn=True)

    assert captured["selected_options"] == []
    assert busy_calls == []
    assert logs == []


def test_start_advanced_frida_launcher_reconfigure_parameterized_jni_option_updates_runtime(
    owner_widget, dummy_deps, tmp_path: Path, monkeypatch
) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    (builtin_script_dir / "jni_method_trace.js").write_text(
        'var so = "__HOOKERS_TARGET_SO__";',
        encoding="utf-8",
    )
    dummy_deps.context.hookers_js_dir = builtin_script_dir

    workspace_script_dir = tmp_path / "workspaces" / "pkg.demo" / "js"
    dummy_deps.workspace_service.script_dir = lambda package_name: workspace_script_dir
    dummy_deps.workspace_service.list_scripts = lambda package_name: []

    bundle_path = workspace_script_dir / "frida_multi_bundle.runtime.js"
    captured: dict[str, object] = {"selected_options": []}

    def fake_materialize(package_name, script_paths, *, output_name="frida_multi_bundle.runtime.js"):
        captured["bundle_args"] = (package_name, list(script_paths), output_name)
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text("// bundle", encoding="utf-8")
        return bundle_path

    dummy_deps.workspace_service.materialize_multi_script_bundle = fake_materialize

    class FakeDialog:
        def __init__(self, *_args, **kwargs):
            options = kwargs["options"]
            add_resolver = kwargs["add_option_resolver"]
            reconfigure_resolver = kwargs["reconfigure_option_resolver"]
            target = next(option for option in options if option.path.name == "jni_method_trace.js")
            selected = add_resolver(target)
            if selected is None:
                return
            updated = reconfigure_resolver(selected)
            captured["selected_options"].append(updated or selected)

        def exec(self):
            return 1

        def selected_options(self):
            return list(captured["selected_options"])

    answers = iter([("libfirst.so", True), ("libsecond.so", True)])
    monkeypatch.setattr("ui.hook_runtime.FridaMultiLauncherDialog", FakeDialog)
    monkeypatch.setattr(
        "ui.hook_runtime.QInputDialog.getText",
        lambda *args, **kwargs: next(answers),
    )

    class FakeThread:
        def __init__(self, *_args, **_kwargs):
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def start(self):
            return None

        def quit(self):
            return None

        def deleteLater(self):
            return None

    class FakeWorker:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.failed = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def moveToThread(self, _thread):
            return None

        def deleteLater(self):
            return None

        def run(self):
            return None

    controller, widgets, _, _, logs, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    import ui.hook_runtime as hook_runtime_module

    original_thread = hook_runtime_module.QThread
    original_worker = hook_runtime_module.HookWorker
    hook_runtime_module.QThread = FakeThread
    hook_runtime_module.HookWorker = FakeWorker
    try:
        controller.start_advanced_frida_launcher(use_spawn=False)
    finally:
        hook_runtime_module.QThread = original_thread
        hook_runtime_module.HookWorker = original_worker

    runtime_script_paths = list(workspace_script_dir.glob("jni_method_trace.*.runtime.js"))
    assert len(runtime_script_paths) == 1
    runtime_script_path = runtime_script_paths[0]
    assert runtime_script_path.read_text(encoding="utf-8") == 'var so = "libsecond.so";'
    assert captured["bundle_args"] == (
        "pkg.demo",
        [runtime_script_path],
        "frida_multi_bundle.runtime.js",
    )
    assert logs[2] == ui_messages.ADVANCED_FRIDA_ORDER_LOG.format(
        scripts="[参数化] [工作区] jni_method_trace.runtime.js (libsecond.so)"
    )


def test_start_advanced_frida_launcher_reconfigure_parameterized_trace_init_option_updates_runtime(
    owner_widget, dummy_deps, tmp_path: Path, monkeypatch
) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    (builtin_script_dir / "trace_init_proc.js").write_text(
        'var startAddr = __HOOKERS_TRACE_START_ADDR__;\n'
        'var endAddr = __HOOKERS_TRACE_END_ADDR__;\n'
        'var somodule = "__HOOKERS_TRACE_SO__";\n',
        encoding="utf-8",
    )
    dummy_deps.context.hookers_js_dir = builtin_script_dir

    workspace_script_dir = tmp_path / "workspaces" / "pkg.demo" / "js"
    dummy_deps.workspace_service.script_dir = lambda package_name: workspace_script_dir
    dummy_deps.workspace_service.list_scripts = lambda package_name: []

    bundle_path = workspace_script_dir / "frida_multi_bundle.runtime.js"
    captured: dict[str, object] = {"selected_options": [], "dialog_values": []}

    def fake_materialize(package_name, script_paths, *, output_name="frida_multi_bundle.runtime.js"):
        captured["bundle_args"] = (package_name, list(script_paths), output_name)
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text("// bundle", encoding="utf-8")
        return bundle_path

    dummy_deps.workspace_service.materialize_multi_script_bundle = fake_materialize

    class FakeDialog:
        def __init__(self, *_args, **kwargs):
            options = kwargs["options"]
            add_resolver = kwargs["add_option_resolver"]
            reconfigure_resolver = kwargs["reconfigure_option_resolver"]
            target = next(option for option in options if option.path.name == "trace_init_proc.js")
            selected = add_resolver(target)
            if selected is None:
                return
            updated = reconfigure_resolver(selected)
            captured["selected_options"].append(updated or selected)

        def exec(self):
            return 1

        def selected_options(self):
            return list(captured["selected_options"])

    params_values = [
        ("libfirst.so", "1234", "2345"),
        ("libsecond.so", "3456", "4567"),
    ]

    class FakeParamDialog:
        call_index = 0

        def __init__(self, *args, **kwargs):
            captured["dialog_values"].append(
                (
                    kwargs["target_so"],
                    kwargs["start_addr"],
                    kwargs["end_addr"],
                )
            )

        def exec(self):
            return 1

        def values(self):
            values = params_values[FakeParamDialog.call_index]
            FakeParamDialog.call_index += 1
            return type(
                "Params",
                (),
                {
                    "target_so": values[0],
                    "start_addr": values[1],
                    "end_addr": values[2],
                },
            )()

    monkeypatch.setattr("ui.hook_runtime.FridaMultiLauncherDialog", FakeDialog)
    monkeypatch.setattr("ui.hook_runtime.TraceInitProcDialog", FakeParamDialog)

    class FakeThread:
        def __init__(self, *_args, **_kwargs):
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def start(self):
            return None

        def quit(self):
            return None

        def deleteLater(self):
            return None

    class FakeWorker:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.failed = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def moveToThread(self, _thread):
            return None

        def deleteLater(self):
            return None

        def run(self):
            return None

    controller, widgets, _, _, logs, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    import ui.hook_runtime as hook_runtime_module

    original_thread = hook_runtime_module.QThread
    original_worker = hook_runtime_module.HookWorker
    hook_runtime_module.QThread = FakeThread
    hook_runtime_module.HookWorker = FakeWorker
    try:
        controller.start_advanced_frida_launcher(use_spawn=True)
    finally:
        hook_runtime_module.QThread = original_thread
        hook_runtime_module.HookWorker = original_worker

    runtime_script_paths = list(workspace_script_dir.glob("trace_init_proc.*.runtime.js"))
    assert len(runtime_script_paths) == 1
    runtime_script_path = runtime_script_paths[0]
    content = runtime_script_path.read_text(encoding="utf-8")
    assert 'var somodule = "libsecond.so";' in content
    assert "var startAddr = 0x3456;" in content
    assert "var endAddr = 0x4567;" in content
    assert captured["dialog_values"] == [
        ("", "", ""),
        ("libfirst.so", "0x1234", "0x2345"),
    ]
    assert captured["bundle_args"] == (
        "pkg.demo",
        [runtime_script_path],
        "frida_multi_bundle.runtime.js",
    )
    assert logs[2] == ui_messages.ADVANCED_FRIDA_ORDER_LOG.format(
        scripts="[参数化] [工作区] trace_init_proc.runtime.js (libsecond.so, 0x3456-0x4567)"
    )


def test_start_advanced_frida_launcher_reconfigure_cancel_keeps_existing_parameterized_option(
    owner_widget, dummy_deps, tmp_path: Path, monkeypatch
) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    (builtin_script_dir / "jni_method_trace.js").write_text(
        'var so = "__HOOKERS_TARGET_SO__";',
        encoding="utf-8",
    )
    dummy_deps.context.hookers_js_dir = builtin_script_dir

    workspace_script_dir = tmp_path / "workspaces" / "pkg.demo" / "js"
    dummy_deps.workspace_service.script_dir = lambda package_name: workspace_script_dir
    dummy_deps.workspace_service.list_scripts = lambda package_name: []

    bundle_path = workspace_script_dir / "frida_multi_bundle.runtime.js"
    captured: dict[str, object] = {"selected_options": []}

    def fake_materialize(package_name, script_paths, *, output_name="frida_multi_bundle.runtime.js"):
        captured["bundle_args"] = (package_name, list(script_paths), output_name)
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text("// bundle", encoding="utf-8")
        return bundle_path

    dummy_deps.workspace_service.materialize_multi_script_bundle = fake_materialize

    class FakeDialog:
        def __init__(self, *_args, **kwargs):
            options = kwargs["options"]
            add_resolver = kwargs["add_option_resolver"]
            reconfigure_resolver = kwargs["reconfigure_option_resolver"]
            target = next(option for option in options if option.path.name == "jni_method_trace.js")
            selected = add_resolver(target)
            if selected is None:
                return
            updated = reconfigure_resolver(selected)
            captured["selected_options"].append(updated or selected)

        def exec(self):
            return 1

        def selected_options(self):
            return list(captured["selected_options"])

    answers = iter([("libfirst.so", True), ("", False)])
    monkeypatch.setattr("ui.hook_runtime.FridaMultiLauncherDialog", FakeDialog)
    monkeypatch.setattr(
        "ui.hook_runtime.QInputDialog.getText",
        lambda *args, **kwargs: next(answers),
    )

    class FakeThread:
        def __init__(self, *_args, **_kwargs):
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def start(self):
            return None

        def quit(self):
            return None

        def deleteLater(self):
            return None

    class FakeWorker:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.failed = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def moveToThread(self, _thread):
            return None

        def deleteLater(self):
            return None

        def run(self):
            return None

    controller, widgets, _, _, logs, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    import ui.hook_runtime as hook_runtime_module

    original_thread = hook_runtime_module.QThread
    original_worker = hook_runtime_module.HookWorker
    hook_runtime_module.QThread = FakeThread
    hook_runtime_module.HookWorker = FakeWorker
    try:
        controller.start_advanced_frida_launcher(use_spawn=False)
    finally:
        hook_runtime_module.QThread = original_thread
        hook_runtime_module.HookWorker = original_worker

    runtime_script_paths = list(workspace_script_dir.glob("jni_method_trace.*.runtime.js"))
    assert len(runtime_script_paths) == 1
    runtime_script_path = runtime_script_paths[0]
    assert runtime_script_path.read_text(encoding="utf-8") == 'var so = "libfirst.so";'
    assert captured["bundle_args"] == (
        "pkg.demo",
        [runtime_script_path],
        "frida_multi_bundle.runtime.js",
    )
    assert logs[2] == ui_messages.ADVANCED_FRIDA_ORDER_LOG.format(
        scripts="[参数化] [工作区] jni_method_trace.runtime.js (libfirst.so)"
    )


def test_start_advanced_frida_launcher_multiple_parameterized_jni_options_use_distinct_runtime_paths(
    owner_widget, dummy_deps, tmp_path: Path, monkeypatch
) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    (builtin_script_dir / "jni_method_trace.js").write_text(
        'var so = "__HOOKERS_TARGET_SO__";',
        encoding="utf-8",
    )
    dummy_deps.context.hookers_js_dir = builtin_script_dir

    workspace_script_dir = tmp_path / "workspaces" / "pkg.demo" / "js"
    dummy_deps.workspace_service.script_dir = lambda package_name: workspace_script_dir
    dummy_deps.workspace_service.list_scripts = lambda package_name: []

    captured: dict[str, object] = {"selected_options": []}

    def fake_materialize(package_name, script_paths, *, output_name="frida_multi_bundle.runtime.js"):
        captured["bundle_args"] = (package_name, list(script_paths), output_name)
        bundle_path = workspace_script_dir / output_name
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text("// bundle", encoding="utf-8")
        return bundle_path

    dummy_deps.workspace_service.materialize_multi_script_bundle = fake_materialize

    class FakeDialog:
        def __init__(self, *_args, **kwargs):
            options = kwargs["options"]
            resolver = kwargs["add_option_resolver"]
            target = next(option for option in options if option.path.name == "jni_method_trace.js")
            first = resolver(target)
            second = resolver(target)
            captured["selected_options"] = [first, second]

        def exec(self):
            return 1

        def selected_options(self):
            return list(captured["selected_options"])

    answers = iter([("libone.so", True), ("libtwo.so", True)])
    monkeypatch.setattr("ui.hook_runtime.FridaMultiLauncherDialog", FakeDialog)
    monkeypatch.setattr(
        "ui.hook_runtime.QInputDialog.getText",
        lambda *args, **kwargs: next(answers),
    )

    class FakeThread:
        def __init__(self, *_args, **_kwargs):
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def start(self):
            return None

        def quit(self):
            return None

        def deleteLater(self):
            return None

    class FakeWorker:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.failed = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def moveToThread(self, _thread):
            return None

        def deleteLater(self):
            return None

        def run(self):
            return None

    controller, widgets, _, _, logs, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    import ui.hook_runtime as hook_runtime_module

    original_thread = hook_runtime_module.QThread
    original_worker = hook_runtime_module.HookWorker
    hook_runtime_module.QThread = FakeThread
    hook_runtime_module.HookWorker = FakeWorker
    try:
        controller.start_advanced_frida_launcher(use_spawn=False)
    finally:
        hook_runtime_module.QThread = original_thread
        hook_runtime_module.HookWorker = original_worker

    bundle_args = captured["bundle_args"]
    runtime_paths = bundle_args[1]
    assert len(runtime_paths) == 2
    assert runtime_paths[0] != runtime_paths[1]
    assert runtime_paths[0].read_text(encoding="utf-8") == 'var so = "libone.so";'
    assert runtime_paths[1].read_text(encoding="utf-8") == 'var so = "libtwo.so";'
    assert logs[2] == ui_messages.ADVANCED_FRIDA_ORDER_LOG.format(
        scripts="[参数化] [工作区] jni_method_trace.runtime.js (libone.so) -> [参数化] [工作区] jni_method_trace.runtime.js (libtwo.so)"
    )


def test_start_advanced_frida_launcher_reconfigure_one_jni_option_does_not_overwrite_other_instance(
    owner_widget, dummy_deps, tmp_path: Path, monkeypatch
) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    (builtin_script_dir / "jni_method_trace.js").write_text(
        'var so = "__HOOKERS_TARGET_SO__";',
        encoding="utf-8",
    )
    dummy_deps.context.hookers_js_dir = builtin_script_dir

    workspace_script_dir = tmp_path / "workspaces" / "pkg.demo" / "js"
    dummy_deps.workspace_service.script_dir = lambda package_name: workspace_script_dir
    dummy_deps.workspace_service.list_scripts = lambda package_name: []

    captured: dict[str, object] = {"selected_options": []}

    def fake_materialize(package_name, script_paths, *, output_name="frida_multi_bundle.runtime.js"):
        captured["bundle_args"] = (package_name, list(script_paths), output_name)
        bundle_path = workspace_script_dir / output_name
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text("// bundle", encoding="utf-8")
        return bundle_path

    dummy_deps.workspace_service.materialize_multi_script_bundle = fake_materialize

    class FakeDialog:
        def __init__(self, *_args, **kwargs):
            options = kwargs["options"]
            add_resolver = kwargs["add_option_resolver"]
            reconfigure_resolver = kwargs["reconfigure_option_resolver"]
            target = next(option for option in options if option.path.name == "jni_method_trace.js")
            first = add_resolver(target)
            second = add_resolver(target)
            updated_first = reconfigure_resolver(first)
            captured["selected_options"] = [updated_first, second]

        def exec(self):
            return 1

        def selected_options(self):
            return list(captured["selected_options"])

    answers = iter([("libone.so", True), ("libtwo.so", True), ("libthree.so", True)])
    monkeypatch.setattr("ui.hook_runtime.FridaMultiLauncherDialog", FakeDialog)
    monkeypatch.setattr(
        "ui.hook_runtime.QInputDialog.getText",
        lambda *args, **kwargs: next(answers),
    )

    class FakeThread:
        def __init__(self, *_args, **_kwargs):
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def start(self):
            return None

        def quit(self):
            return None

        def deleteLater(self):
            return None

    class FakeWorker:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.failed = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def moveToThread(self, _thread):
            return None

        def deleteLater(self):
            return None

        def run(self):
            return None

    controller, widgets, _, _, _, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    import ui.hook_runtime as hook_runtime_module

    original_thread = hook_runtime_module.QThread
    original_worker = hook_runtime_module.HookWorker
    hook_runtime_module.QThread = FakeThread
    hook_runtime_module.HookWorker = FakeWorker
    try:
        controller.start_advanced_frida_launcher(use_spawn=False)
    finally:
        hook_runtime_module.QThread = original_thread
        hook_runtime_module.HookWorker = original_worker

    runtime_paths = captured["bundle_args"][1]
    assert len(runtime_paths) == 2
    assert runtime_paths[0] != runtime_paths[1]
    assert runtime_paths[0].read_text(encoding="utf-8") == 'var so = "libthree.so";'
    assert runtime_paths[1].read_text(encoding="utf-8") == 'var so = "libtwo.so";'


def test_start_advanced_frida_launcher_multiple_parameterized_trace_init_options_use_distinct_runtime_paths(
    owner_widget, dummy_deps, tmp_path: Path, monkeypatch
) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    (builtin_script_dir / "trace_init_proc.js").write_text(
        'var startAddr = __HOOKERS_TRACE_START_ADDR__;\n'
        'var endAddr = __HOOKERS_TRACE_END_ADDR__;\n'
        'var somodule = "__HOOKERS_TRACE_SO__";\n',
        encoding="utf-8",
    )
    dummy_deps.context.hookers_js_dir = builtin_script_dir

    workspace_script_dir = tmp_path / "workspaces" / "pkg.demo" / "js"
    dummy_deps.workspace_service.script_dir = lambda package_name: workspace_script_dir
    dummy_deps.workspace_service.list_scripts = lambda package_name: []

    captured: dict[str, object] = {"selected_options": []}

    def fake_materialize(package_name, script_paths, *, output_name="frida_multi_bundle.runtime.js"):
        captured["bundle_args"] = (package_name, list(script_paths), output_name)
        bundle_path = workspace_script_dir / output_name
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text("// bundle", encoding="utf-8")
        return bundle_path

    dummy_deps.workspace_service.materialize_multi_script_bundle = fake_materialize

    class FakeDialog:
        def __init__(self, *_args, **kwargs):
            options = kwargs["options"]
            resolver = kwargs["add_option_resolver"]
            target = next(option for option in options if option.path.name == "trace_init_proc.js")
            first = resolver(target)
            second = resolver(target)
            captured["selected_options"] = [first, second]

        def exec(self):
            return 1

        def selected_options(self):
            return list(captured["selected_options"])

    params_values = [
        ("libone.so", "1111", "2222"),
        ("libtwo.so", "3333", "4444"),
    ]

    class FakeParamDialog:
        call_index = 0

        def __init__(self, *args, **kwargs):
            return None

        def exec(self):
            return 1

        def values(self):
            values = params_values[FakeParamDialog.call_index]
            FakeParamDialog.call_index += 1
            return type(
                "Params",
                (),
                {
                    "target_so": values[0],
                    "start_addr": values[1],
                    "end_addr": values[2],
                },
            )()

    monkeypatch.setattr("ui.hook_runtime.FridaMultiLauncherDialog", FakeDialog)
    monkeypatch.setattr("ui.hook_runtime.TraceInitProcDialog", FakeParamDialog)

    class FakeThread:
        def __init__(self, *_args, **_kwargs):
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def start(self):
            return None

        def quit(self):
            return None

        def deleteLater(self):
            return None

    class FakeWorker:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.failed = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def moveToThread(self, _thread):
            return None

        def deleteLater(self):
            return None

        def run(self):
            return None

    controller, widgets, _, _, logs, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    import ui.hook_runtime as hook_runtime_module

    original_thread = hook_runtime_module.QThread
    original_worker = hook_runtime_module.HookWorker
    hook_runtime_module.QThread = FakeThread
    hook_runtime_module.HookWorker = FakeWorker
    try:
        controller.start_advanced_frida_launcher(use_spawn=True)
    finally:
        hook_runtime_module.QThread = original_thread
        hook_runtime_module.HookWorker = original_worker

    runtime_paths = captured["bundle_args"][1]
    assert len(runtime_paths) == 2
    assert runtime_paths[0] != runtime_paths[1]
    assert 'var somodule = "libone.so";' in runtime_paths[0].read_text(encoding="utf-8")
    assert 'var somodule = "libtwo.so";' in runtime_paths[1].read_text(encoding="utf-8")
    assert logs[2] == ui_messages.ADVANCED_FRIDA_ORDER_LOG.format(
        scripts="[参数化] [工作区] trace_init_proc.runtime.js (libone.so, 0x1111-0x2222) -> [参数化] [工作区] trace_init_proc.runtime.js (libtwo.so, 0x3333-0x4444)"
    )


def test_start_hook_encryption_algo_logs_and_uses_selected_mode(
    owner_widget, dummy_deps, tmp_path: Path
) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    script_path = builtin_script_dir / "hook_encryption_algo.js"
    script_path.write_text("// builtin", encoding="utf-8")
    dummy_deps.context.hookers_js_dir = builtin_script_dir

    controller, widgets, busy_calls, _, logs, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    captured = {}

    class FakeThread:
        def __init__(self, *_args, **_kwargs):
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def start(self):
            return None

        def quit(self):
            return None

        def deleteLater(self):
            return None

    class FakeWorker:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.failed = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def moveToThread(self, _thread):
            return None

        def deleteLater(self):
            return None

        def run(self):
            return None

    import ui.hook_runtime as hook_runtime_module

    original_thread = hook_runtime_module.QThread
    original_worker = hook_runtime_module.HookWorker
    hook_runtime_module.QThread = FakeThread
    hook_runtime_module.HookWorker = FakeWorker
    try:
        controller.start_quick_hook("hook_encryption_algo", selected_use_spawn=False)
    finally:
        hook_runtime_module.QThread = original_thread
        hook_runtime_module.HookWorker = original_worker

    assert busy_calls[-1] == (True, ui_messages.TRACING_ENCRYPTION_ALGO)
    assert logs[0] == ui_messages.ENCRYPTION_ALGO_ACTION_LOG
    assert logs[1] == ui_messages.ENCRYPTION_ALGO_SCRIPT_LOG.format(script_path=script_path)
    assert logs[2] == ui_messages.ENCRYPTION_ALGO_MODE_LOG.format(mode="attach")
    assert logs[3] == ui_messages.TARGET_APP_LOG.format(package="pkg.demo")
    assert logs[4] == ui_messages.SELECTED_SCRIPT_LOG.format(
        script_name="hook_encryption_algo.js"
    )
    assert captured["script_path"] == script_path
    assert captured["use_spawn"] is False
    assert captured["ensure_workspace"] is False


def test_start_hook_encryption_algo2_logs_and_uses_selected_mode(
    owner_widget, dummy_deps, tmp_path: Path
) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    script_path = builtin_script_dir / "hook_encryption_algo2.js"
    script_path.write_text("// builtin", encoding="utf-8")
    dummy_deps.context.hookers_js_dir = builtin_script_dir

    controller, widgets, busy_calls, _, logs, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    captured = {}

    class FakeThread:
        def __init__(self, *_args, **_kwargs):
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def start(self):
            return None

        def quit(self):
            return None

        def deleteLater(self):
            return None

    class FakeWorker:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.failed = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def moveToThread(self, _thread):
            return None

        def deleteLater(self):
            return None

        def run(self):
            return None

    import ui.hook_runtime as hook_runtime_module

    original_thread = hook_runtime_module.QThread
    original_worker = hook_runtime_module.HookWorker
    hook_runtime_module.QThread = FakeThread
    hook_runtime_module.HookWorker = FakeWorker
    try:
        controller.start_quick_hook("hook_encryption_algo2", selected_use_spawn=True)
    finally:
        hook_runtime_module.QThread = original_thread
        hook_runtime_module.HookWorker = original_worker

    assert busy_calls[-1] == (True, ui_messages.TRACING_DIGEST_HMAC)
    assert logs[0] == ui_messages.DIGEST_HMAC_ACTION_LOG
    assert logs[1] == ui_messages.DIGEST_HMAC_SCRIPT_LOG.format(script_path=script_path)
    assert logs[2] == ui_messages.DIGEST_HMAC_MODE_LOG.format(mode="spawn")
    assert logs[3] == ui_messages.TARGET_APP_LOG.format(package="pkg.demo")
    assert logs[4] == ui_messages.SELECTED_SCRIPT_LOG.format(
        script_name="hook_encryption_algo2.js"
    )
    assert captured["script_path"] == script_path
    assert captured["use_spawn"] is True
    assert captured["ensure_workspace"] is False


def test_start_bypass_root_detect_logs_and_uses_selected_mode(
    owner_widget, dummy_deps, tmp_path: Path
) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    script_path = builtin_script_dir / "bypass_root_detect.js"
    script_path.write_text("// builtin", encoding="utf-8")
    dummy_deps.context.hookers_js_dir = builtin_script_dir

    controller, widgets, busy_calls, _, logs, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    captured = {}

    class FakeThread:
        def __init__(self, *_args, **_kwargs):
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def start(self):
            return None

        def quit(self):
            return None

        def deleteLater(self):
            return None

    class FakeWorker:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.failed = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def moveToThread(self, _thread):
            return None

        def deleteLater(self):
            return None

        def run(self):
            return None

    import ui.hook_runtime as hook_runtime_module

    original_thread = hook_runtime_module.QThread
    original_worker = hook_runtime_module.HookWorker
    hook_runtime_module.QThread = FakeThread
    hook_runtime_module.HookWorker = FakeWorker
    try:
        controller.start_quick_hook("bypass_root_detect", selected_use_spawn=False)
    finally:
        hook_runtime_module.QThread = original_thread
        hook_runtime_module.HookWorker = original_worker

    assert busy_calls[-1] == (True, ui_messages.BYPASSING_ROOT_DETECT)
    assert logs[0] == ui_messages.BYPASS_ROOT_DETECT_ACTION_LOG
    assert logs[1] == ui_messages.BYPASS_ROOT_DETECT_SCRIPT_LOG.format(script_path=script_path)
    assert logs[2] == ui_messages.BYPASS_ROOT_DETECT_MODE_LOG.format(mode="attach")
    assert logs[3] == ui_messages.TARGET_APP_LOG.format(package="pkg.demo")
    assert logs[4] == ui_messages.SELECTED_SCRIPT_LOG.format(
        script_name="bypass_root_detect.js"
    )
    assert captured["script_path"] == script_path
    assert captured["use_spawn"] is False
    assert captured["ensure_workspace"] is False


def test_start_bypass_vpn_detect_logs_and_uses_selected_mode(
    owner_widget, dummy_deps, tmp_path: Path
) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    script_path = builtin_script_dir / "bypass_vpn_detect.js"
    script_path.write_text("// builtin", encoding="utf-8")
    dummy_deps.context.hookers_js_dir = builtin_script_dir

    controller, widgets, busy_calls, _, logs, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    captured = {}

    class FakeThread:
        def __init__(self, *_args, **_kwargs):
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def start(self):
            return None

        def quit(self):
            return None

        def deleteLater(self):
            return None

    class FakeWorker:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.started = type("Signal", (), {"connect": lambda self, cb: None})()
            self.failed = type("Signal", (), {"connect": lambda self, cb: None})()
            self.finished = type("Signal", (), {"connect": lambda self, cb: None})()

        def moveToThread(self, _thread):
            return None

        def deleteLater(self):
            return None

        def run(self):
            return None

    import ui.hook_runtime as hook_runtime_module

    original_thread = hook_runtime_module.QThread
    original_worker = hook_runtime_module.HookWorker
    hook_runtime_module.QThread = FakeThread
    hook_runtime_module.HookWorker = FakeWorker
    try:
        controller.start_quick_hook("bypass_vpn_detect", selected_use_spawn=True)
    finally:
        hook_runtime_module.QThread = original_thread
        hook_runtime_module.HookWorker = original_worker

    assert busy_calls[-1] == (True, ui_messages.BYPASSING_VPN_DETECT)
    assert logs[0] == ui_messages.BYPASS_VPN_DETECT_ACTION_LOG
    assert logs[1] == ui_messages.BYPASS_VPN_DETECT_SCRIPT_LOG.format(script_path=script_path)
    assert logs[2] == ui_messages.BYPASS_VPN_DETECT_MODE_LOG.format(mode="spawn")
    assert logs[3] == ui_messages.TARGET_APP_LOG.format(package="pkg.demo")
    assert logs[4] == ui_messages.SELECTED_SCRIPT_LOG.format(
        script_name="bypass_vpn_detect.js"
    )
    assert captured["script_path"] == script_path
    assert captured["use_spawn"] is True
    assert captured["ensure_workspace"] is False


def test_on_hook_started_updates_ui_and_logs(owner_widget, dummy_deps) -> None:
    controller, _, busy_calls, status_calls, logs, _, refresh_calls, _, _ = build_controller(owner_widget, dummy_deps)
    controller.on_hook_started("spawn", "pkg.demo", "sig.js")
    assert busy_calls[-1] == (False, ui_messages.HOOK_STARTED_STATUS.format(mode="spawn"))
    assert status_calls[-1] == (
        ui_messages.HOOK_RUNNING_STATE.format(mode="spawn", package="pkg.demo", script_name="sig.js"),
        None,
    )
    assert logs[-1] == ui_messages.HOOK_STARTED_LOG.format(
        mode="spawn",
        package="pkg.demo",
        script_name="sig.js",
    )
    assert refresh_calls[-1] == "pkg.demo"


def test_on_restart_current_app_finished_refreshes_combo(owner_widget, dummy_deps) -> None:
    controller, widgets, busy_calls, _, logs, _, refresh_calls, applied_payloads, session_status_calls = build_controller(owner_widget, dummy_deps)
    payload = type(
        "Payload",
        (),
        {
            "package_name": "pkg.demo",
            "apps": [
                {"name": "Demo", "identifier": "pkg.demo", "pid": 1},
                {"name": "Other", "identifier": "pkg.other", "pid": 2},
            ],
        },
    )()
    controller.on_restart_current_app_finished(payload)
    assert logs[-1] == ui_messages.RESTARTED_APP_LOG.format(package="pkg.demo")
    assert applied_payloads[-1][0] == payload.apps
    assert widgets.app_combo.currentData() == "pkg.demo"
    assert refresh_calls[-1] == "pkg.demo"
    assert busy_calls[-1] == (False, ui_messages.READY)
    assert session_status_calls[-1][0] == ui_messages.SESSION_STATUS_PHASE_STOPPED
    assert session_status_calls[-1][2] == "pkg.demo"


def test_on_auto_stop_finished_resets_ui_and_logs(owner_widget, dummy_deps) -> None:
    controller, widgets, busy_calls, status_calls, logs, _, refresh_calls, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.start_hook_button.setDisabled(True)
    widgets.stop_hook_button.setDisabled(False)
    controller._auto_stop_in_progress = True

    controller.on_auto_stop_finished(None)

    assert status_calls[-1] == (
        ui_messages.HOOK_STOPPED_STATE,
        ui_messages.HOOK_STOPPED_STATUS,
    )
    assert logs[-1] == ui_messages.NETWORK_STACK_AUTO_STOPPED_LOG
    assert widgets.start_hook_button.isEnabled() is True
    assert widgets.stop_hook_button.isEnabled() is False
    assert refresh_calls[-1] is None
    assert busy_calls[-1] == (False, ui_messages.READY)
    assert controller._auto_stop_in_progress is False


def test_hook_worker_preserves_structured_stage_errors(tmp_path: Path) -> None:
    class DeviceService:
        def ensure_app_running(self, package_name: str):
            return type("App", (), {"identifier": package_name})()

    class SessionService:
        def __init__(self) -> None:
            self.stop_calls = 0

        def attach_script(self, script_path: str, use_v8: bool = False) -> None:
            raise AttachStageError("attach 阶段失败", hint="请检查 App 状态。")

        def stop_active_session(self) -> None:
            self.stop_calls += 1

    class WorkspaceService:
        def ensure_workspace(self, app) -> None:
            return None

    worker = HookWorker(
        device_service=DeviceService(),
        session_service=SessionService(),
        workspace_service=WorkspaceService(),
        package_name="pkg.demo",
        script_path=tmp_path / "sig.js",
        use_spawn=False,
        ensure_workspace=False,
    )

    failed_payloads = []
    worker.failed.connect(failed_payloads.append)
    worker.run()

    assert failed_payloads
    payload = failed_payloads[-1]
    assert payload.message == "attach 阶段失败"
    assert payload.hint == "请检查 App 状态。"
    assert payload.category == "hook"


def test_available_frida_script_options_distinguishes_workspace_copy_and_builtin_source(
    owner_widget, dummy_deps, tmp_path: Path
) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    (builtin_script_dir / "okhttp.js").write_text("// builtin", encoding="utf-8")
    dummy_deps.context.hookers_js_dir = builtin_script_dir

    workspace_script_dir = tmp_path / "workspaces" / "pkg.demo" / "js"
    workspace_script_dir.mkdir(parents=True, exist_ok=True)
    (workspace_script_dir / "alpha.js").write_text("// alpha", encoding="utf-8")
    (workspace_script_dir / "内置-okhttp.js").write_text("// workspace copy", encoding="utf-8")

    dummy_deps.workspace_service.script_dir = lambda package_name: workspace_script_dir

    controller, widgets, *_ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    options = controller._available_frida_script_options("pkg.demo")
    labels = [option.label for option in options]

    assert "[工作区] alpha.js" in labels
    assert "[工作区内置副本] 内置-okhttp.js" in labels
    assert "[内置源] okhttp.js" in labels


def test_reconfigure_parameterized_jni_option_updates_summary_label(
    owner_widget, dummy_deps, tmp_path: Path, monkeypatch
) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    (builtin_script_dir / "jni_method_trace.js").write_text(
        'var so = "__HOOKERS_TARGET_SO__";',
        encoding="utf-8",
    )
    dummy_deps.context.hookers_js_dir = builtin_script_dir
    controller, widgets, *_ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    template = next(
        option for option in controller._available_frida_script_options("pkg.demo")
        if option.path.name == "jni_method_trace.js"
    )

    answers = iter([("libfirst.so", True), ("libsecond.so", True)])
    monkeypatch.setattr(
        "ui.hook_runtime.QInputDialog.getText",
        lambda *args, **kwargs: next(answers),
    )

    first = controller._resolve_advanced_frida_option("pkg.demo", template)
    assert first is not None
    second = controller._reconfigure_advanced_frida_option("pkg.demo", first)

    assert second is not None
    assert second.summary == "libsecond.so"
    assert second.label == "[参数化] [工作区] jni_method_trace.runtime.js (libsecond.so)"


def test_frida_multi_launcher_dialog_distinguishes_search_filter_and_selected_empty_states(qapp) -> None:
    from ui.frida_multi_launcher_dialog import FridaMultiLauncherDialog, FridaScriptOption

    option = FridaScriptOption(
        label='[工作区] alpha.js',
        path=Path(r'C:\demo\alpha.js'),
        source_kind='workspace',
        display_name='alpha.js',
    )
    dialog = FridaMultiLauncherDialog(
        None,
        package_name='pkg.demo',
        mode='attach',
        options=[option],
    )

    assert dialog.available_hint_label.text() == ui_messages.ADVANCED_FRIDA_AVAILABLE_HINT
    assert dialog.selected_hint_label.text() == ui_messages.ADVANCED_FRIDA_SELECTED_HINT
    assert dialog.selected_empty_label.isHidden() is False

    dialog.search_input.setText('zzz')
    dialog._rebuild_available_list()
    assert dialog.available_empty_label.text() == ui_messages.ADVANCED_FRIDA_EMPTY_SEARCH

    dialog.search_input.setText('')
    dialog.source_filter_combo.setCurrentText(ui_messages.ADVANCED_FRIDA_FILTER_BUILTIN)
    dialog._rebuild_available_list()
    assert dialog.available_empty_label.text() == ui_messages.ADVANCED_FRIDA_EMPTY_FILTER

    dialog.source_filter_combo.setCurrentText(ui_messages.ADVANCED_FRIDA_FILTER_ALL)
    dialog._rebuild_available_list()
    dialog.available_list.setCurrentRow(0)
    dialog._add_selected_items()
    assert dialog.selected_empty_label.isHidden() is True
    dialog.deleteLater()


def test_frida_multi_launcher_dialog_details_change_action_hint_for_available_vs_selected(qapp) -> None:
    from ui.frida_multi_launcher_dialog import FridaMultiLauncherDialog, FridaScriptOption

    option = FridaScriptOption(
        label='[参数化] [工作区] jni_method_trace.runtime.js (libfoo.so)',
        path=Path(r'C:\demo\jni_method_trace.runtime.js'),
        source_kind='workspace',
        display_name='jni_method_trace.runtime.js',
        kind='jni_method_trace',
        summary='libfoo.so',
        runtime_key='abc',
    )
    dialog = FridaMultiLauncherDialog(
        None,
        package_name='pkg.demo',
        mode='spawn',
        options=[option],
        reconfigure_option_resolver=lambda item: item,
    )

    dialog.available_list.setCurrentRow(0)
    dialog._update_details()
    assert ui_messages.ADVANCED_FRIDA_DETAIL_ACTION_AVAILABLE in dialog.details_label.text()

    dialog._add_selected_items()
    current_item = dialog.selected_list.currentItem()
    assert current_item is not None
    assert 'jni_method_trace.runtime.js' in current_item.text()
    details_text = dialog.details_label.text()
    assert ui_messages.ADVANCED_FRIDA_DETAIL_ACTION_SELECTED in details_text
    assert 'libfoo.so' in details_text
    assert '第 1 项' in details_text
    dialog.deleteLater()




def test_start_jni_method_trace_materialize_failure_does_not_mark_session_failed(
    owner_widget, dummy_deps, tmp_path: Path, monkeypatch
) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    (builtin_script_dir / "jni_method_trace.js").write_text(
        'var so = "__HOOKERS_TARGET_SO__";',
        encoding="utf-8",
    )
    dummy_deps.context.hookers_js_dir = builtin_script_dir

    controller, widgets, _, _, _, errors, _, _, session_status_calls = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    monkeypatch.setattr(
        "ui.hook_runtime.QInputDialog.getText",
        lambda *args, **kwargs: ("libdemo.so", True),
    )
    monkeypatch.setattr(
        controller,
        "_materialize_parameterized_template_runtime",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            hook_runtime_module._ParameterizedRuntimeWriteError("runtime 写入失败", hint="请检查工作区目录。")
        ),
    )

    controller.start_jni_method_trace(use_spawn=False)
    assert errors[-1].hint == "请检查工作区目录。"
    assert session_status_calls[-1][0] != ui_messages.SESSION_STATUS_PHASE_FAILED

def test_start_jni_method_trace_materialize_failure_uses_error_chain_and_skips_launch(
    owner_widget, dummy_deps, tmp_path: Path, monkeypatch
) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    (builtin_script_dir / "jni_method_trace.js").write_text(
        'var so = "__HOOKERS_TARGET_SO__";',
        encoding="utf-8",
    )
    dummy_deps.context.hookers_js_dir = builtin_script_dir

    controller, widgets, busy_calls, _, logs, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    monkeypatch.setattr(
        "ui.hook_runtime.QInputDialog.getText",
        lambda *args, **kwargs: ("libdemo.so", True),
    )
    monkeypatch.setattr(
        controller,
        "_materialize_parameterized_template_runtime",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            hook_runtime_module._ParameterizedRuntimeWriteError("runtime 写入失败", hint="请检查工作区目录。")
        ),
    )

    controller.start_jni_method_trace(use_spawn=False)

    assert busy_calls == []
    assert logs == []
    assert errors
    assert errors[-1].message == "runtime 写入失败"
    assert errors[-1].hint == "请检查工作区目录。"




def test_start_advanced_frida_launcher_active_session_error_does_not_mark_session_failed(
    owner_widget, dummy_deps
) -> None:
    controller, widgets, _, _, _, errors, _, _, session_status_calls = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)
    dummy_deps.context.active_session = type("Session", (), {"mode": "attach"})()

    controller.start_advanced_frida_launcher(use_spawn=False)

    assert errors
    assert session_status_calls[-1][0] != ui_messages.SESSION_STATUS_PHASE_FAILED

def test_advanced_parameterized_option_add_materialize_failure_keeps_selection_empty(
    owner_widget, dummy_deps, tmp_path: Path, monkeypatch
) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    (builtin_script_dir / "jni_method_trace.js").write_text(
        'var so = "__HOOKERS_TARGET_SO__";',
        encoding="utf-8",
    )
    dummy_deps.context.hookers_js_dir = builtin_script_dir

    workspace_script_dir = tmp_path / "workspaces" / "pkg.demo" / "js"
    dummy_deps.workspace_service.script_dir = lambda package_name: workspace_script_dir
    dummy_deps.workspace_service.list_scripts = lambda package_name: []

    captured: dict[str, object] = {"selected_options": []}

    class FakeDialog:
        def __init__(self, *_args, **kwargs):
            options = kwargs["options"]
            add_resolver = kwargs["add_option_resolver"]
            target = next(option for option in options if option.path.name == "jni_method_trace.js")
            captured["resolved"] = add_resolver(target)

        def exec(self):
            return 0

        def selected_options(self):
            return list(captured["selected_options"])

    monkeypatch.setattr("ui.hook_runtime.FridaMultiLauncherDialog", FakeDialog)
    monkeypatch.setattr(
        "ui.hook_runtime.QInputDialog.getText",
        lambda *args, **kwargs: ("libdemo.so", True),
    )
    monkeypatch.setattr(
        HookRuntimeController,
        "_materialize_advanced_jni_method_trace_script",
        lambda self, **kwargs: (_ for _ in ()).throw(
            HookStartError("高级 runtime 生成失败", hint="请检查工作区目录。")
        ),
    )

    controller, widgets, busy_calls, _, logs, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    controller.start_advanced_frida_launcher(use_spawn=False)

    assert captured["resolved"] is None
    assert busy_calls == []
    assert logs == []
    assert errors
    assert errors[-1].message == "高级 runtime 生成失败"




def test_start_advanced_frida_launcher_bundle_materialize_failure_does_not_mark_session_failed(
    owner_widget, dummy_deps, monkeypatch
) -> None:
    class FakeDialog:
        def __init__(self, *_args, **_kwargs):
            return None

        def exec(self):
            return 1

        def selected_options(self):
            from ui.frida_multi_launcher_dialog import FridaScriptOption

            return [
                FridaScriptOption(
                    label='[工作区] alpha.js',
                    path=Path(r'C:\demo\alpha.js'),
                    source_kind='workspace',
                    display_name='alpha.js',
                )
            ]

    monkeypatch.setattr("ui.hook_runtime.FridaMultiLauncherDialog", FakeDialog)
    dummy_deps.workspace_service.materialize_multi_script_bundle = lambda *args, **kwargs: (_ for _ in ()).throw(
        HookStartError("高级启动 bundle 生成失败", hint="请先检查工作区写入权限，再重新点击高级 Frida 启动。")
    )

    controller, widgets, busy_calls, _, logs, errors, _, _, session_status_calls = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    controller.start_advanced_frida_launcher(use_spawn=False)

    assert busy_calls == []
    assert logs == [ui_messages.ADVANCED_FRIDA_ACTION_LOG]
    assert errors
    assert errors[-1].message == "高级启动 bundle 生成失败"
    assert session_status_calls[-1][0] != ui_messages.SESSION_STATUS_PHASE_FAILED


def test_start_advanced_frida_launcher_empty_selection_logs_action_context(
    owner_widget, dummy_deps, monkeypatch
) -> None:
    class FakeDialog:
        def __init__(self, *_args, **_kwargs):
            return None

        def exec(self):
            return 1

        def selected_options(self):
            return []

        def had_add_cancelled(self):
            return False

    monkeypatch.setattr("ui.hook_runtime.FridaMultiLauncherDialog", FakeDialog)

    controller, widgets, busy_calls, _, logs, errors, _, _, session_status_calls = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    controller.start_advanced_frida_launcher(use_spawn=False)

    assert busy_calls == []
    assert logs == [ui_messages.ADVANCED_FRIDA_ACTION_LOG]
    assert errors
    assert errors[-1].message == ui_messages.ADVANCED_FRIDA_NO_SCRIPT_BODY
    assert session_status_calls[-1][0] != ui_messages.SESSION_STATUS_PHASE_FAILED

def test_advanced_parameterized_option_reconfigure_materialize_failure_keeps_existing_runtime(
    owner_widget, dummy_deps, tmp_path: Path, monkeypatch
) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    (builtin_script_dir / "jni_method_trace.js").write_text(
        'var so = "__HOOKERS_TARGET_SO__";',
        encoding="utf-8",
    )
    dummy_deps.context.hookers_js_dir = builtin_script_dir

    workspace_script_dir = tmp_path / "workspaces" / "pkg.demo" / "js"
    dummy_deps.workspace_service.script_dir = lambda package_name: workspace_script_dir
    dummy_deps.workspace_service.list_scripts = lambda package_name: []
    bundle_path = workspace_script_dir / "frida_multi_bundle.runtime.js"

    def fake_materialize(package_name, script_paths, *, output_name="frida_multi_bundle.runtime.js"):
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text("// bundle", encoding="utf-8")
        return bundle_path

    dummy_deps.workspace_service.materialize_multi_script_bundle = fake_materialize

    captured: dict[str, object] = {}

    class FakeDialog:
        def __init__(self, *_args, **kwargs):
            options = kwargs["options"]
            add_resolver = kwargs["add_option_resolver"]
            reconfigure_resolver = kwargs["reconfigure_option_resolver"]
            target = next(option for option in options if option.path.name == "jni_method_trace.js")
            selected = add_resolver(target)
            assert selected is not None
            runtime_path = selected.path
            captured["runtime_path"] = runtime_path
            captured["before"] = runtime_path.read_text(encoding="utf-8")
            updated = reconfigure_resolver(selected)
            captured["after_option"] = updated
            captured["selected_options"] = [updated or selected]

        def exec(self):
            return 1

        def selected_options(self):
            return list(captured["selected_options"])

    answers = iter([("libfirst.so", True), ("libsecond.so", True)])
    monkeypatch.setattr("ui.hook_runtime.FridaMultiLauncherDialog", FakeDialog)
    monkeypatch.setattr(
        "ui.hook_runtime.QInputDialog.getText",
        lambda *args, **kwargs: next(answers),
    )

    original = HookRuntimeController._materialize_advanced_jni_method_trace_script
    state = {"count": 0}

    def failing_materialize(self, **kwargs):
        state["count"] += 1
        if state["count"] == 1:
            return original(self, **kwargs)
        raise HookStartError("重新配置 runtime 生成失败", hint="请检查工作区目录。")

    monkeypatch.setattr(
        HookRuntimeController,
        "_materialize_advanced_jni_method_trace_script",
        failing_materialize,
    )

    controller, widgets, busy_calls, _, logs, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    controller.start_advanced_frida_launcher(use_spawn=False)

    runtime_path = captured["runtime_path"]
    assert captured["after_option"] is None
    assert runtime_path.read_text(encoding="utf-8") == captured["before"]
    assert busy_calls[-1] == (True, ui_messages.STARTING_ADVANCED_FRIDA)
    assert logs
    assert errors
    assert errors[-1].message == "重新配置 runtime 生成失败"


def test_frida_multi_launcher_dialog_search_matches_real_path_and_template_path(qapp) -> None:
    from ui.frida_multi_launcher_dialog import FridaMultiLauncherDialog, FridaScriptOption

    plain = FridaScriptOption(
        label='[工作区] alpha.js',
        path=Path(r'C:\demo\workspace\alpha.js'),
        source_kind='workspace',
        display_name='alpha.js',
    )
    parameterized = FridaScriptOption(
        label='[参数化] [工作区] jni_method_trace.runtime.js (libfoo.so)',
        path=Path(r'C:\demo\workspace\jni_method_trace.runtime.js'),
        source_kind='workspace',
        display_name='jni_method_trace.runtime.js',
        kind='jni_method_trace',
        summary='libfoo.so',
        template_path=Path(r'C:\demo\hookers\js\jni_method_trace.js'),
        runtime_key='abc',
    )
    dialog = FridaMultiLauncherDialog(
        None,
        package_name='pkg.demo',
        mode='attach',
        options=[plain, parameterized],
    )

    dialog.search_input.setText(r'workspace\alpha.js')
    dialog._rebuild_available_list()
    assert dialog.available_list.count() == 1
    assert dialog.available_list.item(0).text() == '[工作区] alpha.js'

    dialog.search_input.setText(r'hookers\js\jni_method_trace.js')
    dialog._rebuild_available_list()
    assert dialog.available_list.count() == 1
    assert 'jni_method_trace.runtime.js' in dialog.available_list.item(0).text()
    dialog.deleteLater()


def test_parameterized_resolution_marks_materialize_failure_as_failed(owner_widget, dummy_deps) -> None:
    from ui.hook_runtime import (
        FridaScriptOption,
        ParameterizedResolutionStatus,
    )

    controller, widgets, _, _, _, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    from ui.hook_runtime import ParameterizedResolutionStatus, ParameterizedTemplateResolution

    controller._collect_parameterized_template_params = lambda spec, initial_payload=None: ParameterizedTemplateResolution(
        status=ParameterizedResolutionStatus.SUCCESS,
        payload="libdemo.so",
    )
    controller._build_parameterized_runtime_option = lambda *args, **kwargs: (_ for _ in ()).throw(
        HookStartError("runtime 构建失败", hint="请检查工作区。")
    )

    result = controller._resolve_parameterized_runtime_option(
        controller._parameterized_template_spec("jni_method_trace"),
        package_name="pkg.demo",
        template_option=FridaScriptOption(label="x", path=Path("jni_method_trace.js"), kind="jni_method_trace"),
    )

    assert result.status is ParameterizedResolutionStatus.FAILED
    assert result.option is None
    assert errors
    assert errors[-1].message == "runtime 构建失败"



def test_parameterized_resolution_materialize_failure_does_not_mark_session_failed(owner_widget, dummy_deps) -> None:
    from ui.hook_runtime import FridaScriptOption

    controller, widgets, _, _, _, _, _, _, session_status_calls = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    from ui.hook_runtime import ParameterizedResolutionStatus, ParameterizedTemplateResolution

    controller._collect_parameterized_template_params = lambda spec, initial_payload=None: ParameterizedTemplateResolution(
        status=ParameterizedResolutionStatus.SUCCESS,
        payload="libdemo.so",
    )
    controller._build_parameterized_runtime_option = lambda *args, **kwargs: (_ for _ in ()).throw(
        HookStartError("runtime 构建失败", hint="请检查工作区。")
    )

    controller._resolve_parameterized_runtime_option(
        controller._parameterized_template_spec("jni_method_trace"),
        package_name="pkg.demo",
        template_option=FridaScriptOption(label="x", path=Path("jni_method_trace.js"), kind="jni_method_trace"),
    )

    assert session_status_calls[-1][0] != ui_messages.SESSION_STATUS_PHASE_FAILED



def test_resolved_parameterized_option_or_none_returns_none_for_cancelled_resolution(owner_widget, dummy_deps) -> None:
    from ui.hook_runtime import FridaScriptOption

    controller, widgets, _, _, _, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    from ui.hook_runtime import ParameterizedResolutionStatus, ParameterizedTemplateResolution

    controller._collect_parameterized_template_params = lambda spec, initial_payload=None: ParameterizedTemplateResolution(
        status=ParameterizedResolutionStatus.CANCELLED
    )

    template = FridaScriptOption(label="x", path=Path("jni_method_trace.js"), kind="jni_method_trace")
    result = controller._resolved_parameterized_option_or_none(
        controller._parameterized_template_spec("jni_method_trace"),
        package_name="pkg.demo",
        template_option=template,
    )

    assert result is None
    assert errors == []


def test_resolved_parameterized_option_or_none_returns_option_for_success(owner_widget, dummy_deps, tmp_path: Path, monkeypatch) -> None:
    from ui.hook_runtime import FridaScriptOption

    controller, widgets, _, _, _, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    (builtin_script_dir / "jni_method_trace.js").write_text('var so = "__HOOKERS_TARGET_SO__";', encoding="utf-8")
    dummy_deps.context.hookers_js_dir = builtin_script_dir
    workspace_script_dir = tmp_path / "workspaces" / "pkg.demo" / "js"
    dummy_deps.workspace_service.script_dir = lambda package_name: workspace_script_dir

    monkeypatch.setattr(
        "ui.hook_runtime.QInputDialog.getText",
        lambda *args, **kwargs: ("libdemo.so", True),
    )

    template = FridaScriptOption(label="x", path=Path("jni_method_trace.js"), kind="jni_method_trace")
    result = controller._resolved_parameterized_option_or_none(
        controller._parameterized_template_spec("jni_method_trace"),
        package_name="pkg.demo",
        template_option=template,
    )

    assert result is not None
    assert result.summary == "libdemo.so"
    assert result.runtime_key
    assert errors == []




def test_advanced_parameterized_option_reconfigure_materialize_failure_does_not_mark_session_failed(
    owner_widget, dummy_deps, tmp_path: Path, monkeypatch
) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    (builtin_script_dir / "jni_method_trace.js").write_text(
        'var so = "__HOOKERS_TARGET_SO__";',
        encoding="utf-8",
    )
    dummy_deps.context.hookers_js_dir = builtin_script_dir

    workspace_script_dir = tmp_path / "workspaces" / "pkg.demo" / "js"
    dummy_deps.workspace_service.script_dir = lambda package_name: workspace_script_dir
    dummy_deps.workspace_service.list_scripts = lambda package_name: []
    bundle_path = workspace_script_dir / "frida_multi_bundle.runtime.js"

    def fake_materialize(package_name, script_paths, *, output_name="frida_multi_bundle.runtime.js"):
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text("// bundle", encoding="utf-8")
        return bundle_path

    dummy_deps.workspace_service.materialize_multi_script_bundle = fake_materialize

    captured: dict[str, object] = {}

    class FakeDialog:
        def __init__(self, *_args, **kwargs):
            options = kwargs["options"]
            add_resolver = kwargs["add_option_resolver"]
            reconfigure_resolver = kwargs["reconfigure_option_resolver"]
            target = next(option for option in options if option.path.name == "jni_method_trace.js")
            selected = add_resolver(target)
            assert selected is not None
            updated = reconfigure_resolver(selected)
            captured["selected_options"] = [updated or selected]

        def exec(self):
            return 1

        def selected_options(self):
            return list(captured["selected_options"])

    answers = iter([("libfirst.so", True), ("libsecond.so", True)])
    monkeypatch.setattr("ui.hook_runtime.FridaMultiLauncherDialog", FakeDialog)
    monkeypatch.setattr(
        "ui.hook_runtime.QInputDialog.getText",
        lambda *args, **kwargs: next(answers),
    )

    original = HookRuntimeController._materialize_advanced_jni_method_trace_script
    state = {"count": 0}

    def failing_materialize(self, **kwargs):
        state["count"] += 1
        if state["count"] == 1:
            return original(self, **kwargs)
        raise HookStartError("重新配置 runtime 生成失败", hint="请检查工作区写入权限。")

    monkeypatch.setattr(
        HookRuntimeController,
        "_materialize_advanced_jni_method_trace_script",
        failing_materialize,
    )

    controller, widgets, _, _, _, _, _, _, session_status_calls = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    controller.start_advanced_frida_launcher(use_spawn=False)

    assert session_status_calls[-1][0] != ui_messages.SESSION_STATUS_PHASE_FAILED
def test_frida_multi_launcher_dialog_reconfigure_failure_keeps_item_tooltip_and_details(qapp) -> None:
    from ui.frida_multi_launcher_dialog import FridaMultiLauncherDialog, FridaScriptOption

    option = FridaScriptOption(
        label='[参数化] [工作区] jni_method_trace.runtime.js (libfoo.so)',
        path=Path(r'C:\demo\jni_method_trace.runtime.js'),
        source_kind='workspace',
        display_name='jni_method_trace.runtime.js',
        kind='jni_method_trace',
        summary='libfoo.so',
        runtime_key='abc',
    )
    dialog = FridaMultiLauncherDialog(
        None,
        package_name='pkg.demo',
        mode='attach',
        options=[option],
        reconfigure_option_resolver=lambda _item: None,
    )

    dialog.available_list.setCurrentRow(0)
    dialog._add_selected_items()
    dialog.selected_list.setCurrentRow(0)
    dialog._update_details()

    selected_item = dialog.selected_list.item(0)
    before_text = selected_item.text()
    before_tooltip = selected_item.toolTip()
    before_details = dialog.details_label.text()

    dialog._reconfigure_selected_item()

    selected_item = dialog.selected_list.item(0)
    assert selected_item.text() == before_text
    assert selected_item.toolTip() == before_tooltip
    assert dialog.details_label.text() == before_details
    assert 'libfoo.so' in dialog.details_label.text()
    dialog.deleteLater()

def test_frida_multi_launcher_dialog_selected_tooltips_refresh_after_reorder(qapp) -> None:
    from ui.frida_multi_launcher_dialog import FridaMultiLauncherDialog, FridaScriptOption

    first = FridaScriptOption(
        label='[工作区] alpha.js',
        path=Path(r'C:\demo\alpha.js'),
        source_kind='workspace',
        display_name='alpha.js',
    )
    second = FridaScriptOption(
        label='[工作区] beta.js',
        path=Path(r'C:\demo\beta.js'),
        source_kind='workspace',
        display_name='beta.js',
    )
    dialog = FridaMultiLauncherDialog(
        None,
        package_name='pkg.demo',
        mode='attach',
        options=[first, second],
    )

    dialog.available_list.setCurrentRow(0)
    dialog._add_selected_items()
    dialog.available_list.setCurrentRow(1)
    dialog._add_selected_items()

    first_selected = dialog.selected_list.item(0)
    second_selected = dialog.selected_list.item(1)
    assert '顺序：第 1 项' in first_selected.toolTip()
    assert '顺序：第 2 项' in second_selected.toolTip()

    dialog.selected_list.setCurrentRow(1)
    dialog._move_selected_item_up()

    moved_first = dialog.selected_list.item(0)
    moved_second = dialog.selected_list.item(1)
    assert 'beta.js' in moved_first.text()
    assert '顺序：第 1 项' in moved_first.toolTip()
    assert 'alpha.js' in moved_second.text()
    assert '顺序：第 2 项' in moved_second.toolTip()
    dialog.deleteLater()




def test_start_jni_method_trace_invalid_input_does_not_mark_session_failed(
    owner_widget, dummy_deps, monkeypatch
) -> None:
    controller, widgets, _, _, _, _, _, _, session_status_calls = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    monkeypatch.setattr(
        "ui.hook_runtime.QInputDialog.getText",
        lambda *args, **kwargs: (" ", True),
    )
    controller.start_jni_method_trace(use_spawn=False)
    assert session_status_calls[-1][0] != ui_messages.SESSION_STATUS_PHASE_FAILED

def test_start_jni_method_trace_invalid_inputs_include_next_step(owner_widget, dummy_deps, monkeypatch) -> None:
    controller, widgets, _, _, _, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    monkeypatch.setattr(
        "ui.hook_runtime.QInputDialog.getText",
        lambda *args, **kwargs: (" ", True),
    )
    controller.start_jni_method_trace(use_spawn=False)
    assert errors[-1].next_step == ui_messages.JNI_TARGET_SO_REQUIRED_NEXT_STEP

    monkeypatch.setattr(
        "ui.hook_runtime.QInputDialog.getText",
        lambda *args, **kwargs: ("libdemo", True),
    )
    controller.start_jni_method_trace(use_spawn=False)
    assert errors[-1].next_step == ui_messages.JNI_TARGET_SO_INVALID_NEXT_STEP


def test_start_trace_init_proc_validation_errors_include_next_step(
    owner_widget, dummy_deps, monkeypatch
) -> None:
    controller, widgets, _, _, _, errors, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    def run_with(values):
        class FakeDialog:
            def __init__(self, *args, **kwargs):
                return None

            def exec(self):
                return 1

            def values(self):
                return type("Params", (), values)()

        monkeypatch.setattr("ui.hook_runtime.TraceInitProcDialog", FakeDialog)
        controller.start_trace_init_proc(use_spawn=False)
        return errors[-1]

    assert run_with({"target_so": " ", "start_addr": "0x10", "end_addr": "0x20"}).next_step == ui_messages.TRACE_INIT_PROC_REQUIRED_SO_NEXT_STEP
    assert run_with({"target_so": "libdemo", "start_addr": "0x10", "end_addr": "0x20"}).next_step == ui_messages.TRACE_INIT_PROC_INVALID_SO_NEXT_STEP
    assert run_with({"target_so": "libdemo.so", "start_addr": " ", "end_addr": "0x20"}).next_step == ui_messages.TRACE_INIT_PROC_REQUIRED_START_NEXT_STEP
    assert run_with({"target_so": "libdemo.so", "start_addr": "0x10", "end_addr": " "}).next_step == ui_messages.TRACE_INIT_PROC_REQUIRED_END_NEXT_STEP
    assert run_with({"target_so": "libdemo.so", "start_addr": "xyz", "end_addr": "0x20"}).next_step == ui_messages.TRACE_INIT_PROC_INVALID_ADDR_NEXT_STEP
    assert run_with({"target_so": "libdemo.so", "start_addr": "0x30", "end_addr": "0x20"}).next_step == ui_messages.TRACE_INIT_PROC_RANGE_NEXT_STEP


def test_start_hook_reports_busy_instead_of_silently_returning(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _, session_status_calls = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)
    controller.hook_thread = object()

    controller.start_hook(use_spawn=False)

    assert errors
    assert errors[-1].message == ui_messages.HOOK_START_BUSY_BODY
    assert errors[-1].next_step == ui_messages.HOOK_START_BUSY_NEXT_STEP
    assert errors[-1].severity == 'warning'
    assert session_status_calls[-1][0] != ui_messages.SESSION_STATUS_PHASE_FAILED


def test_start_builtin_quick_hook_reports_busy_instead_of_silently_returning(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _, session_status_calls = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)
    controller.hook_thread = object()

    controller.start_detect_network_stack(use_spawn=True)

    assert errors
    assert errors[-1].message == ui_messages.HOOK_START_BUSY_BODY
    assert errors[-1].next_step == ui_messages.HOOK_START_BUSY_NEXT_STEP
    assert errors[-1].severity == 'warning'
    assert session_status_calls[-1][0] != ui_messages.SESSION_STATUS_PHASE_FAILED


def test_start_parameterized_quick_hook_reports_busy_instead_of_silently_returning(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _, session_status_calls = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)
    controller.hook_thread = object()

    controller.start_jni_method_trace(use_spawn=False)

    assert errors
    assert errors[-1].message == ui_messages.HOOK_START_BUSY_BODY
    assert errors[-1].next_step == ui_messages.HOOK_START_BUSY_NEXT_STEP
    assert errors[-1].severity == 'warning'
    assert session_status_calls[-1][0] != ui_messages.SESSION_STATUS_PHASE_FAILED


def test_stop_hook_reports_runtime_action_busy_instead_of_silently_returning(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _, session_status_calls = build_controller(owner_widget, dummy_deps)
    widgets.stop_hook_button.setDisabled(False)
    controller.runtime_action_thread = object()

    controller.stop_hook()

    assert errors
    assert errors[-1].message == ui_messages.RUNTIME_ACTION_BUSY_BODY
    assert errors[-1].next_step == ui_messages.RUNTIME_ACTION_BUSY_NEXT_STEP
    assert errors[-1].severity == 'warning'
    assert session_status_calls[-1][0] != ui_messages.SESSION_STATUS_PHASE_FAILED


def test_stop_hook_wraps_stop_failure_with_ui_message_constants(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.stop_hook_button.setDisabled(False)

    def fail_stop() -> None:
        raise RuntimeError("boom")

    dummy_deps.session_service.stop_active_session = fail_stop

    captured: dict[str, object] = {}

    def fake_start_runtime_action(*, busy_message, action, on_success):
        captured["busy_message"] = busy_message
        captured["on_success"] = on_success
        captured["action"] = action

    controller.start_runtime_action = fake_start_runtime_action

    controller.stop_hook()

    assert captured["busy_message"] == ui_messages.STOPPING_HOOK
    with pytest.raises(HookStopError) as exc_info:
        captured["action"]()
    assert exc_info.value.message == ui_messages.STOP_HOOK_FAILED_BODY
    assert exc_info.value.hint == ui_messages.STOP_HOOK_FAILED_HINT


def test_stop_frida_server_wraps_stop_failure_with_ui_message_constants(owner_widget, dummy_deps) -> None:
    controller, _, _, _, _, _, _, _, _ = build_controller(owner_widget, dummy_deps)

    def fail_stop() -> None:
        raise RuntimeError("boom")

    dummy_deps.device_service.stop_frida_server = fail_stop

    captured: dict[str, object] = {}

    def fake_start_runtime_action(*, busy_message, action, on_success):
        captured["busy_message"] = busy_message
        captured["on_success"] = on_success
        captured["action"] = action

    controller.start_runtime_action = fake_start_runtime_action

    controller.stop_frida_server()

    assert captured["busy_message"] == ui_messages.STOPPING_FRIDA_SERVER
    with pytest.raises(FridaServerStopError) as exc_info:
        captured["action"]()
    assert exc_info.value.message == ui_messages.STOP_FRIDA_SERVER_FAILED_BODY
    assert exc_info.value.hint == ui_messages.STOP_FRIDA_SERVER_FAILED_HINT


def test_restart_current_app_wraps_restart_failure_with_ui_message_constants(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    def fail_restart() -> None:
        raise RuntimeError("boom")

    dummy_deps.session_service.restart_current_app = fail_restart

    captured: dict[str, object] = {}

    def fake_start_runtime_action(*, busy_message, action, on_success):
        captured["busy_message"] = busy_message
        captured["on_success"] = on_success
        captured["action"] = action

    controller.start_runtime_action = fake_start_runtime_action

    controller.restart_current_app()

    assert captured["busy_message"] == ui_messages.RESTARTING_APP
    with pytest.raises(RestartAppError) as exc_info:
        captured["action"]()
    assert exc_info.value.message == ui_messages.RESTART_APP_FAILED_BODY
    assert exc_info.value.hint == ui_messages.RESTART_APP_FAILED_HINT


def test_stop_frida_server_reports_runtime_action_busy_instead_of_silently_returning(owner_widget, dummy_deps) -> None:
    controller, _, _, _, _, errors, _, _, session_status_calls = build_controller(owner_widget, dummy_deps)
    controller.runtime_action_thread = object()

    controller.stop_frida_server()

    assert errors
    assert errors[-1].message == ui_messages.RUNTIME_ACTION_BUSY_BODY
    assert errors[-1].next_step == ui_messages.RUNTIME_ACTION_BUSY_NEXT_STEP
    assert errors[-1].severity == 'warning'
    assert session_status_calls[-1][0] != ui_messages.SESSION_STATUS_PHASE_FAILED


def test_restart_current_app_reports_runtime_action_busy_instead_of_silently_returning(owner_widget, dummy_deps) -> None:
    controller, _, _, _, _, errors, _, _, session_status_calls = build_controller(owner_widget, dummy_deps)
    controller.runtime_action_thread = object()

    controller.restart_current_app()

    assert errors
    assert errors[-1].message == ui_messages.RUNTIME_ACTION_BUSY_BODY
    assert errors[-1].next_step == ui_messages.RUNTIME_ACTION_BUSY_NEXT_STEP
    assert errors[-1].severity == 'warning'
    assert session_status_calls[-1][0] != ui_messages.SESSION_STATUS_PHASE_FAILED


def test_frida_multi_launcher_dialog_remove_keeps_stable_selected_item_and_details(qapp) -> None:
    from ui.frida_multi_launcher_dialog import FridaMultiLauncherDialog, FridaScriptOption

    first = FridaScriptOption(
        label='[工作区] alpha.js',
        path=Path(r'C:\demolpha.js'),
        source_kind='workspace',
        display_name='alpha.js',
    )
    second = FridaScriptOption(
        label='[工作区] beta.js',
        path=Path(r'C:\demoeta.js'),
        source_kind='workspace',
        display_name='beta.js',
    )
    dialog = FridaMultiLauncherDialog(
        None,
        package_name='pkg.demo',
        mode='attach',
        options=[first, second],
    )

    dialog.available_list.setCurrentRow(0)
    dialog._add_selected_items()
    dialog.available_list.setCurrentRow(1)
    dialog._add_selected_items()

    dialog.selected_list.setCurrentRow(0)
    dialog._remove_selected_items()

    assert dialog.selected_list.count() == 1
    assert dialog.selected_list.currentRow() == 0
    assert 'beta.js' in dialog.selected_list.item(0).text()
    assert 'beta.js' in dialog.details_label.text()
    assert dialog.start_button.isEnabled() is True
    dialog.deleteLater()


def test_frida_multi_launcher_dialog_remove_last_item_restores_empty_state(qapp) -> None:
    from ui.frida_multi_launcher_dialog import FridaMultiLauncherDialog, FridaScriptOption

    option = FridaScriptOption(
        label='[工作区] alpha.js',
        path=Path(r'C:\demolpha.js'),
        source_kind='workspace',
        display_name='alpha.js',
    )
    dialog = FridaMultiLauncherDialog(
        None,
        package_name='pkg.demo',
        mode='attach',
        options=[option],
    )

    dialog.available_list.setCurrentRow(0)
    dialog._add_selected_items()
    dialog.selected_list.setCurrentRow(0)
    dialog._remove_selected_items()

    assert dialog.selected_list.count() == 0
    assert dialog.selected_list.currentRow() == -1
    assert dialog.selected_empty_label.text() == ui_messages.ADVANCED_FRIDA_SELECTION_EMPTY
    assert dialog.start_button.isEnabled() is False
    dialog.deleteLater()



def test_start_script_command_marks_script_used(owner_widget, dummy_deps, tmp_path: Path) -> None:
    workspace_script_dir = tmp_path / "workspaces" / "pkg.demo" / "js"
    workspace_script_dir.mkdir(parents=True)
    script_path = workspace_script_dir / "alpha.js"
    script_path.write_text("// workspace", encoding="utf-8")
    dummy_deps.workspace_service.script_dir = lambda _package_name: workspace_script_dir
    controller, widgets, _, _, _, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)
    import ui.hook_runtime as hook_runtime_module
    FakeWorker = _capturing_hook_worker({})
    original_thread = hook_runtime_module.QThread
    original_worker = hook_runtime_module.HookWorker
    hook_runtime_module.QThread = _WorkerTestThread
    hook_runtime_module.HookWorker = FakeWorker
    try:
        controller.start_script_command("alpha.js", use_spawn=False)
    finally:
        hook_runtime_module.QThread = original_thread
        hook_runtime_module.HookWorker = original_worker
    assert dummy_deps.workspace_service.mark_script_used_calls[-1]["script_name"] == "alpha.js"
    assert dummy_deps.workspace_service.mark_script_used_calls[-1]["mode"] == "attach"


def test_start_script_command_records_session_launch_request(owner_widget, dummy_deps, tmp_path: Path) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    script_path = builtin_script_dir / "alpha.js"
    script_path.write_text("// builtin", encoding="utf-8")
    dummy_deps.context.hookers_js_dir = builtin_script_dir
    controller, widgets, _, _, _, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)
    import ui.hook_runtime as hook_runtime_module
    FakeWorker = _capturing_hook_worker({})
    original_thread = hook_runtime_module.QThread
    original_worker = hook_runtime_module.HookWorker
    hook_runtime_module.QThread = _WorkerTestThread
    hook_runtime_module.HookWorker = FakeWorker
    try:
        controller.start_script_command("alpha.js", use_spawn=False)
    finally:
        hook_runtime_module.QThread = original_thread
        hook_runtime_module.HookWorker = original_worker
    record = dummy_deps.workspace_service.append_session_record_calls[-1]
    assert record.package_name == "pkg.demo"
    assert record.script_name == "alpha.js"
    assert record.mode == "attach"


def test_start_script_command_does_not_persist_builtin_source_into_script_library_metadata(owner_widget, dummy_deps, tmp_path: Path) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    script_path = builtin_script_dir / "alpha.js"
    script_path.write_text("// builtin", encoding="utf-8")
    dummy_deps.context.hookers_js_dir = builtin_script_dir
    controller, widgets, _, _, _, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)
    import ui.hook_runtime as hook_runtime_module
    FakeWorker = _capturing_hook_worker({})
    original_thread = hook_runtime_module.QThread
    original_worker = hook_runtime_module.HookWorker
    hook_runtime_module.QThread = _WorkerTestThread
    hook_runtime_module.HookWorker = FakeWorker
    try:
        controller.start_script_command("alpha.js", use_spawn=False)
    finally:
        hook_runtime_module.QThread = original_thread
        hook_runtime_module.HookWorker = original_worker
    assert dummy_deps.workspace_service.mark_script_used_calls == []
    record = dummy_deps.workspace_service.append_session_record_calls[-1]
    assert record.script_name == "alpha.js"
    assert record.mode == "attach"


def test_start_script_command_records_session_without_guessing_source_kind_from_same_named_builtin(owner_widget, dummy_deps, tmp_path: Path) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    script_path = builtin_script_dir / "alpha.js"
    script_path.write_text("// builtin", encoding="utf-8")
    dummy_deps.context.hookers_js_dir = builtin_script_dir
    controller, widgets, _, _, _, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)
    dummy_deps.workspace_service.list_script_sources = lambda _package: [
        ScriptSourceInfo(
            name="alpha.js",
            path=Path(r"C:\other\alpha.js"),
            source_kind="workspace",
            is_builtin=False,
            is_parameter_template=False,
            display_label="alpha.js",
            metadata=None,
        )
    ]
    import ui.hook_runtime as hook_runtime_module
    FakeWorker = _capturing_hook_worker({})
    original_thread = hook_runtime_module.QThread
    original_worker = hook_runtime_module.HookWorker
    hook_runtime_module.QThread = _WorkerTestThread
    hook_runtime_module.HookWorker = FakeWorker
    try:
        controller.start_script_command("alpha.js", use_spawn=False)
    finally:
        hook_runtime_module.QThread = original_thread
        hook_runtime_module.HookWorker = original_worker
    record = dummy_deps.workspace_service.append_session_record_calls[-1]
    assert record.source_kind is None


def test_start_script_command_does_not_mark_script_used_on_precheck_failure(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)
    controller.start_script_command("missing.js", use_spawn=False)
    assert dummy_deps.workspace_service.mark_script_used_calls == []


def test_append_session_record_failure_does_not_block_launch(owner_widget, dummy_deps, tmp_path: Path) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    script_path = builtin_script_dir / "alpha.js"
    script_path.write_text("// builtin", encoding="utf-8")
    dummy_deps.context.hookers_js_dir = builtin_script_dir
    controller, widgets, _, _, logs, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)
    def fail_append(*args, **kwargs):
        raise RuntimeError("boom")
    dummy_deps.workspace_service.append_session_record = fail_append
    import ui.hook_runtime as hook_runtime_module
    captured = {}
    FakeWorker = _capturing_hook_worker(captured)
    original_thread = hook_runtime_module.QThread
    original_worker = hook_runtime_module.HookWorker
    hook_runtime_module.QThread = _WorkerTestThread
    hook_runtime_module.HookWorker = FakeWorker
    try:
        controller.start_script_command("alpha.js", use_spawn=False)
    finally:
        hook_runtime_module.QThread = original_thread
        hook_runtime_module.HookWorker = original_worker
    assert any("记录会话启动失败" in message for message in logs)
    assert captured["script_path"] == script_path


def test_mark_script_used_failure_does_not_block_launch(owner_widget, dummy_deps, tmp_path: Path) -> None:
    workspace_script_dir = tmp_path / "workspaces" / "pkg.demo" / "js"
    workspace_script_dir.mkdir(parents=True)
    script_path = workspace_script_dir / "alpha.js"
    script_path.write_text("// workspace", encoding="utf-8")
    dummy_deps.workspace_service.script_dir = lambda _package_name: workspace_script_dir
    controller, widgets, _, _, logs, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)
    def fail_mark(*args, **kwargs):
        raise RuntimeError("boom")
    dummy_deps.workspace_service.mark_script_used = fail_mark
    import ui.hook_runtime as hook_runtime_module
    captured = {}
    FakeWorker = _capturing_hook_worker(captured)
    original_thread = hook_runtime_module.QThread
    original_worker = hook_runtime_module.HookWorker
    hook_runtime_module.QThread = _WorkerTestThread
    hook_runtime_module.HookWorker = FakeWorker
    try:
        controller.start_script_command("alpha.js", use_spawn=False)
    finally:
        hook_runtime_module.QThread = original_thread
        hook_runtime_module.HookWorker = original_worker
    assert any("记录脚本最近使用失败" in message for message in logs)
    assert captured["script_path"] == script_path


def test_summarize_jni_method_trace_params_is_stable(owner_widget, dummy_deps) -> None:
    controller, *_ = build_controller(owner_widget, dummy_deps)
    assert controller._summarize_jni_method_trace_params(" libfoo.so ") == "libfoo.so"


def test_summarize_trace_init_proc_params_includes_address_range(owner_widget, dummy_deps) -> None:
    controller, *_ = build_controller(owner_widget, dummy_deps)
    params = hook_runtime_module.TraceInitProcParams(
        target_so="libbar.so",
        start_addr="1234",
        end_addr="0x5678",
    )
    assert controller._summarize_trace_init_proc_params(params) == "libbar.so, 0x1234-0x5678"


def test_summarize_parameterized_template_falls_back_when_summary_builder_fails(owner_widget, dummy_deps, monkeypatch) -> None:
    controller, *_ = build_controller(owner_widget, dummy_deps)
    spec = controller._parameterized_template_spec("trace_init_proc")

    def fail_summary(_payload):
        raise RuntimeError("boom")

    monkeypatch.setattr(controller, spec.summary_method_name, fail_summary)
    result = controller._summarize_parameterized_template(spec, object())
    assert result == "参数化 init_proc 跟踪 runtime"


def test_script_usage_summary_falls_back_to_runtime_name_when_workspace_listing_fails(owner_widget, dummy_deps) -> None:
    controller, *_ = build_controller(owner_widget, dummy_deps)
    package_name = "pkg.demo"
    runtime_path = Path(r"C:\demo\jni_method_trace.runtime.js")

    controller.widgets.app_combo.addItem("Demo", package_name)
    controller.widgets.app_combo.setCurrentIndex(0)

    def fail_list(_package_name):
        raise RuntimeError("boom")

    dummy_deps.workspace_service.list_script_sources = fail_list

    assert controller._script_usage_summary(runtime_path) == "参数化 JNI 方法跟踪 runtime"


def test_script_usage_summary_reuses_metadata_summary_when_path_only_differs_by_case(owner_widget, dummy_deps) -> None:
    controller, *_ = build_controller(owner_widget, dummy_deps)
    package_name = "pkg.demo"
    controller.widgets.app_combo.addItem("Demo", package_name)
    controller.widgets.app_combo.setCurrentIndex(0)

    info = ScriptSourceInfo(
        name="Alpha.js",
        path=Path(r"C:\Demo\Alpha.js"),
        source_kind="workspace",
        is_builtin=False,
        is_parameter_template=False,
        display_label="Alpha.js",
        metadata=ScriptMetadata(name="Alpha.js", summary="case-aware summary"),
    )
    dummy_deps.workspace_service.list_script_sources = lambda _package_name: [info]

    result = controller._script_usage_summary(Path(r"C:\demo\alpha.js"))

    assert result == "case-aware summary"


def test_script_usage_summary_does_not_reuse_same_named_builtin_summary_when_paths_do_not_match(owner_widget, dummy_deps) -> None:
    controller, *_ = build_controller(owner_widget, dummy_deps)
    package_name = "pkg.demo"
    controller.widgets.app_combo.addItem("Demo", package_name)
    controller.widgets.app_combo.setCurrentIndex(0)

    info = ScriptSourceInfo(
        name="alpha.js",
        path=Path(r"C:\builtin\alpha.js"),
        source_kind="builtin_source",
        is_builtin=True,
        is_parameter_template=False,
        display_label="[内置源] alpha.js",
        metadata=ScriptMetadata(name="alpha.js", summary="builtin summary"),
    )
    dummy_deps.workspace_service.list_script_sources = lambda _package_name: [info]

    result = controller._script_usage_summary(Path(r"C:\workspace\alpha.js"))

    assert result is None


def test_script_usage_summary_falls_back_to_runtime_name_without_selected_package(owner_widget, dummy_deps) -> None:
    controller, *_ = build_controller(owner_widget, dummy_deps)

    assert controller._script_usage_summary(Path(r"C:\demo\trace_init_proc.runtime.js")) == "参数化 init_proc 跟踪 runtime"


def test_script_usage_summary_falls_back_to_multi_bundle_runtime_name_when_workspace_listing_fails(owner_widget, dummy_deps) -> None:
    controller, *_ = build_controller(owner_widget, dummy_deps)
    package_name = "pkg.demo"
    runtime_path = Path(r"C:\demo\frida_multi_bundle.runtime.js")

    controller.widgets.app_combo.addItem("Demo", package_name)
    controller.widgets.app_combo.setCurrentIndex(0)

    def fail_list(_package_name):
        raise RuntimeError("boom")

    dummy_deps.workspace_service.list_script_sources = fail_list

    assert controller._script_usage_summary(runtime_path) == "多脚本组合 runtime"


def test_script_usage_summary_falls_back_to_multi_bundle_runtime_name_without_selected_package(owner_widget, dummy_deps) -> None:
    controller, *_ = build_controller(owner_widget, dummy_deps)

    assert controller._script_usage_summary(Path(r"C:\demo\frida_multi_bundle.runtime.js")) == "多脚本组合 runtime"


def test_start_advanced_frida_launcher_passes_initial_selected_options_from_preset(
    owner_widget, dummy_deps, tmp_path: Path, monkeypatch
) -> None:
    runtime_path = tmp_path / 'workspaces' / 'pkg.demo' / 'js' / 'preset.runtime.js'
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text('// preset', encoding='utf-8')
    dummy_deps.workspace_service.advanced_launcher_preset_entries_by_package['pkg.demo'] = [
        AdvancedLauncherPresetEntry(
            label='[工作区] preset.runtime.js',
            path=str(runtime_path),
            kind='plain',
            source_kind='workspace',
            display_name='preset.runtime.js',
            summary='from preset',
            mode_strategy='spawn',
            auto_stop=True,
        )
    ]
    captured: dict[str, object] = {}

    class FakeDialog:
        def __init__(self, *_args, **kwargs):
            captured['initial_selected_options'] = kwargs.get('initial_selected_options')

        def exec(self):
            return 0

    monkeypatch.setattr('ui.hook_runtime.FridaMultiLauncherDialog', FakeDialog)

    controller, widgets, *_rest = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem('Demo', 'pkg.demo')
    widgets.app_combo.setCurrentIndex(0)

    controller.start_advanced_frida_launcher(use_spawn=False)

    initial_options = captured['initial_selected_options']
    assert isinstance(initial_options, list)
    assert len(initial_options) == 1
    assert initial_options[0].path == runtime_path
    assert initial_options[0].summary == 'from preset'
    assert initial_options[0].mode_strategy == 'spawn'
    assert initial_options[0].auto_stop is True


def test_option_to_preset_entry_preserves_strategy_fields(owner_widget, dummy_deps) -> None:
    controller, *_ = build_controller(owner_widget, dummy_deps)
    option = FridaScriptOption(
        label='[工作区] alpha.js',
        path=Path('C:/demo/alpha.js'),
        mode_strategy='attach',
        auto_stop=True,
    )

    entry = controller._option_to_preset_entry(option)

    assert entry.mode_strategy == 'attach'
    assert entry.auto_stop is True


def test_preset_entry_to_option_preserves_strategy_fields(owner_widget, dummy_deps, tmp_path: Path) -> None:
    controller, *_ = build_controller(owner_widget, dummy_deps)
    package_name = 'pkg.demo'
    runtime_path = tmp_path / 'workspaces' / package_name / 'js' / 'alpha.js'
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text('// alpha', encoding='utf-8')
    entry = AdvancedLauncherPresetEntry(
        label='[工作区] alpha.js',
        path=str(runtime_path),
        source_kind='workspace',
        mode_strategy='spawn',
        auto_stop=True,
    )

    option = controller._preset_entry_to_option(package_name, entry)

    assert option is not None
    assert option.mode_strategy == 'spawn'
    assert option.auto_stop is True


def test_advanced_frida_item_strategy_log_message_formats_selected_options(owner_widget, dummy_deps) -> None:
    controller, *_ = build_controller(owner_widget, dummy_deps)
    selected = [
        FridaScriptOption(
            label='[工作区] alpha.js',
            path=Path('C:/demo/alpha.js'),
            mode_strategy='inherit',
            auto_stop=False,
        ),
        FridaScriptOption(
            label='[工作区] beta.js',
            path=Path('C:/demo/beta.js'),
            mode_strategy='spawn',
            auto_stop=True,
        ),
    ]

    line = controller._advanced_frida_item_strategy_log_message(selected)

    assert line is not None
    assert 'alpha.js' in line
    assert 'mode=inherit auto_stop=no' in line
    assert 'beta.js' in line
    assert 'mode=spawn auto_stop=yes' in line


def test_available_frida_script_options_reuses_builtin_source_metadata_for_launcher_view(
    owner_widget, dummy_deps, tmp_path: Path
) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True, exist_ok=True)
    builtin_script = builtin_script_dir / "okhttp.js"
    builtin_script.write_text("// builtin", encoding="utf-8")
    dummy_deps.context.hookers_js_dir = builtin_script_dir

    controller, widgets, *_rest = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)

    dummy_deps.workspace_service.resolve_script_metadata = lambda package_name, script_name: (
        ScriptMetadata(
            name="okhttp.js",
            pinned=True,
            last_used_at="2026-06-08T10:30:00+08:00",
            summary="抓取 OkHttp 请求与响应",
            tags=("network", "okhttp"),
        )
        if package_name == "pkg.demo" and script_name == "okhttp.js"
        else None
    )
    dummy_deps.workspace_service.list_launcher_candidate_scripts = lambda package_name: [
        ScriptSourceInfo(
            name="okhttp.js",
            path=builtin_script,
            source_kind="builtin_source",
            is_builtin=True,
            is_parameter_template=False,
            display_label="[内置源] okhttp.js",
            metadata=None,
        )
    ]

    options = controller._available_frida_script_options("pkg.demo")

    assert len(options) == 1
    assert options[0].source_kind == "builtin_source"
    assert options[0].is_pinned is True
    assert options[0].last_used_at == "2026-06-08T10:30:00+08:00"
    assert options[0].summary == "抓取 OkHttp 请求与响应"
    assert options[0].tags == ("network", "okhttp")


def test_start_advanced_frida_launcher_saves_selected_options_as_preset(
    owner_widget, dummy_deps, tmp_path: Path, monkeypatch
) -> None:
    workspace_script_dir = tmp_path / 'workspaces' / 'pkg.demo' / 'js'
    workspace_script_dir.mkdir(parents=True, exist_ok=True)
    workspace_script = workspace_script_dir / 'alpha.js'
    workspace_script.write_text('// alpha', encoding='utf-8')
    bundle_path = workspace_script_dir / 'frida_multi_bundle.runtime.js'

    def fake_materialize(package_name, script_paths, *, output_name='frida_multi_bundle.runtime.js'):
        bundle_path.write_text('// bundle', encoding='utf-8')
        return bundle_path

    dummy_deps.workspace_service.materialize_multi_script_bundle = fake_materialize

    class FakeDialog:
        def __init__(self, *_args, **kwargs):
            return None

        def exec(self):
            return 1

        def selected_options(self):
            return [
                FridaScriptOption(
                    label='[工作区] alpha.js',
                    path=workspace_script,
                    source_kind='workspace',
                    display_name='alpha.js',
                    summary='alpha summary',
                )
            ]

    class FakeThread:
        def __init__(self, *_args, **_kwargs):
            self.started = type('Signal', (), {'connect': lambda self, cb: None})()
            self.finished = type('Signal', (), {'connect': lambda self, cb: None})()

        def start(self):
            return None

        def quit(self):
            return None

        def deleteLater(self):
            return None

    class FakeWorker:
        def __init__(self, **_kwargs):
            self.started = type('Signal', (), {'connect': lambda self, cb: None})()
            self.failed = type('Signal', (), {'connect': lambda self, cb: None})()
            self.finished = type('Signal', (), {'connect': lambda self, cb: None})()

        def moveToThread(self, _thread):
            return None

        def deleteLater(self):
            return None

        def run(self):
            return None

    monkeypatch.setattr('ui.hook_runtime.FridaMultiLauncherDialog', FakeDialog)
    import ui.hook_runtime as hook_runtime_module
    original_thread = hook_runtime_module.QThread
    original_worker = hook_runtime_module.HookWorker
    hook_runtime_module.QThread = FakeThread
    hook_runtime_module.HookWorker = FakeWorker
    try:
        controller, widgets, *_rest = build_controller(owner_widget, dummy_deps)
        widgets.app_combo.addItem('Demo', 'pkg.demo')
        widgets.app_combo.setCurrentIndex(0)
        controller.start_advanced_frida_launcher(use_spawn=False)
    finally:
        hook_runtime_module.QThread = original_thread
        hook_runtime_module.HookWorker = original_worker

    saved_entries = dummy_deps.workspace_service.advanced_launcher_preset_entries_by_package['pkg.demo']
    assert len(saved_entries) == 1
    assert saved_entries[0].path == str(workspace_script)
    assert saved_entries[0].summary == 'alpha summary'


def test_start_advanced_frida_launcher_empty_selection_still_saves_empty_preset(
    owner_widget, dummy_deps, monkeypatch
) -> None:
    class FakeDialog:
        def __init__(self, *_args, **_kwargs):
            return None

        def exec(self):
            return 1

        def selected_options(self):
            return []

        def had_add_cancelled(self):
            return False

    monkeypatch.setattr('ui.hook_runtime.FridaMultiLauncherDialog', FakeDialog)

    controller, widgets, *_rest = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem('Demo', 'pkg.demo')
    widgets.app_combo.setCurrentIndex(0)

    controller.start_advanced_frida_launcher(use_spawn=False)

    assert dummy_deps.workspace_service.advanced_launcher_preset_entries_by_package['pkg.demo'] == []


def test_start_advanced_frida_launcher_restored_preset_missing_display_fields_reuses_current_metadata(
    owner_widget, dummy_deps, tmp_path: Path, monkeypatch
) -> None:
    runtime_path = tmp_path / 'workspaces' / 'pkg.demo' / 'js' / 'restored.runtime.js'
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text('// restored', encoding='utf-8')
    dummy_deps.workspace_service.advanced_launcher_preset_entries_by_package['pkg.demo'] = [
        AdvancedLauncherPresetEntry(
            label='[工作区] restored.runtime.js',
            path=str(runtime_path),
            kind='plain',
            source_kind='workspace',
            display_name='restored.runtime.js',
            summary=None,
            is_pinned=False,
            last_used_at=None,
            tags=(),
        )
    ]
    captured: dict[str, object] = {}

    class FakeDialog:
        def __init__(self, *_args, **kwargs):
            captured['initial_selected_options'] = kwargs.get('initial_selected_options')

        def exec(self):
            return 0

    monkeypatch.setattr('ui.hook_runtime.FridaMultiLauncherDialog', FakeDialog)
    monkeypatch.setattr(
        dummy_deps.workspace_service,
        'list_launcher_candidate_scripts',
        lambda _package_name: [
            ScriptSourceInfo(
                name='restored.runtime.js',
                path=runtime_path,
                source_kind='workspace',
                is_builtin=False,
                is_parameter_template=False,
                display_label='[工作区] restored.runtime.js',
                metadata=ScriptMetadata(
                    name='restored.runtime.js',
                    pinned=True,
                    last_used_at='2026-06-08T10:30:00+08:00',
                    summary='restored summary',
                    tags=('network', 'restored'),
                ),
            )
        ],
    )

    controller, widgets, *_ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem('Demo', 'pkg.demo')
    widgets.app_combo.setCurrentIndex(0)

    controller.start_advanced_frida_launcher(use_spawn=False)

    initial_options = captured['initial_selected_options']
    assert isinstance(initial_options, list)
    assert len(initial_options) == 1
    assert initial_options[0].summary == 'restored summary'
    assert initial_options[0].is_pinned is True
    assert initial_options[0].last_used_at == '2026-06-08T10:30:00+08:00'
    assert initial_options[0].tags == ('network', 'restored')


def test_start_advanced_frida_launcher_passes_restored_display_metadata_from_preset(
    owner_widget, dummy_deps, tmp_path: Path, monkeypatch
) -> None:
    runtime_path = tmp_path / 'workspaces' / 'pkg.demo' / 'js' / 'preset.runtime.js'
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text('// preset', encoding='utf-8')
    dummy_deps.workspace_service.advanced_launcher_preset_entries_by_package['pkg.demo'] = [
        AdvancedLauncherPresetEntry(
            label='★ [工作区] preset.runtime.js',
            path=str(runtime_path),
            kind='plain',
            source_kind='workspace',
            display_name='preset.runtime.js',
            summary='from preset',
            is_pinned=True,
            last_used_at='2026-06-08T10:30:00+08:00',
            tags=('network', 'preset'),
        )
    ]
    captured: dict[str, object] = {}

    class FakeDialog:
        def __init__(self, *_args, **kwargs):
            captured['initial_selected_options'] = kwargs.get('initial_selected_options')

        def exec(self):
            return 0

    monkeypatch.setattr('ui.hook_runtime.FridaMultiLauncherDialog', FakeDialog)

    controller, widgets, *_rest = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem('Demo', 'pkg.demo')
    widgets.app_combo.setCurrentIndex(0)

    controller.start_advanced_frida_launcher(use_spawn=False)

    initial_options = captured['initial_selected_options']
    assert isinstance(initial_options, list)
    assert len(initial_options) == 1
    assert initial_options[0].is_pinned is True
    assert initial_options[0].last_used_at == '2026-06-08T10:30:00+08:00'
    assert initial_options[0].tags == ('network', 'preset')


def test_start_script_command_records_session_source_kind_when_path_only_differs_by_case(owner_widget, dummy_deps, tmp_path: Path) -> None:
    controller, widgets, *_ = build_controller(owner_widget, dummy_deps)
    package_name = "pkg.demo"
    widgets.app_combo.addItem("Demo", package_name)
    widgets.app_combo.setCurrentIndex(0)

    real_path = tmp_path / "workspaces" / package_name / "js" / "Alpha.js"
    real_path.parent.mkdir(parents=True, exist_ok=True)
    real_path.write_text("// alpha", encoding="utf-8")
    requested_path = Path(str(real_path).lower())

    dummy_deps.workspace_service.list_script_sources = lambda _package_name: [
        ScriptSourceInfo(
            name="Alpha.js",
            path=real_path,
            source_kind="workspace",
            is_builtin=False,
            is_parameter_template=False,
            display_label="Alpha.js",
            metadata=ScriptMetadata(name="Alpha.js", summary="case summary"),
        )
    ]

    import ui.hook_runtime as hook_runtime_module
    original_thread = hook_runtime_module.QThread
    original_worker = hook_runtime_module.HookWorker
    hook_runtime_module.QThread = _WorkerTestThread
    hook_runtime_module.HookWorker = _WorkerTestHookWorker
    try:
        controller._start_launch_request(
            hook_runtime_module.LaunchRequest(
                package_name=package_name,
                script_path=requested_path,
                use_spawn=False,
                busy_message=ui_messages.STARTING_HOOK,
            )
        )
    finally:
        hook_runtime_module.QThread = original_thread
        hook_runtime_module.HookWorker = original_worker

    record = dummy_deps.workspace_service.append_session_record_calls[-1]
    assert record.source_kind == "workspace"


def test_start_launch_request_does_not_mark_custom_root_script_as_workspace_asset(owner_widget, dummy_deps, tmp_path: Path) -> None:
    controller, widgets, *_ = build_controller(owner_widget, dummy_deps)
    package_name = "pkg.demo"
    widgets.app_combo.addItem("Demo", package_name)
    widgets.app_combo.setCurrentIndex(0)

    custom_script = tmp_path / "custom-js" / "alpha.js"
    custom_script.parent.mkdir(parents=True, exist_ok=True)
    custom_script.write_text("// custom", encoding="utf-8")

    import ui.hook_runtime as hook_runtime_module
    original_thread = hook_runtime_module.QThread
    original_worker = hook_runtime_module.HookWorker
    hook_runtime_module.QThread = _WorkerTestThread
    hook_runtime_module.HookWorker = _WorkerTestHookWorker
    try:
        controller._start_launch_request(
            hook_runtime_module.LaunchRequest(
                package_name=package_name,
                script_path=custom_script,
                use_spawn=False,
                busy_message=ui_messages.STARTING_HOOK,
            )
        )
    finally:
        hook_runtime_module.QThread = original_thread
        hook_runtime_module.HookWorker = original_worker

    assert dummy_deps.workspace_service.mark_script_used_calls == []
    assert dummy_deps.workspace_service.append_session_record_calls[-1].script_path == str(custom_script)


