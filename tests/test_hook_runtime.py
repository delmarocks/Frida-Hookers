from __future__ import annotations

from pathlib import Path

from core.errors import HookStartError
from PySide6.QtWidgets import QComboBox, QLabel, QPushButton

from core.errors import AttachStageError
from ui import ui_messages
from ui.hook_runtime import HookRuntimeController, HookRuntimeWidgets
from ui.quick_hook_actions import QUICK_HOOK_ACTIONS
from ui.workers.hook_worker import HookWorker


def build_controller(owner_widget, dummy_deps):
    busy_calls = []
    status_calls = []
    logs = []
    errors = []
    refresh_calls = []
    applied_payloads = []

    widgets = HookRuntimeWidgets(
        start_hook_button=QPushButton(),
        stop_hook_button=QPushButton(),
        current_state_label=QLabel(),
        app_combo=QComboBox(),
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
    return controller, widgets, busy_calls, status_calls, logs, errors, refresh_calls, applied_payloads


def test_handle_session_event_updates_detached_state(owner_widget, dummy_deps) -> None:
    controller, widgets, _, status_calls, _, _, refresh_calls, _ = build_controller(owner_widget, dummy_deps)
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


def test_handle_auto_stop_requested_starts_async_stop(owner_widget, dummy_deps) -> None:
    controller, _, busy_calls, _, logs, _, _, _ = build_controller(owner_widget, dummy_deps)
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


def test_start_hook_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)
    controller.start_hook(use_spawn=False)
    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY


def test_start_hook_requires_selected_script(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.addItem("Demo", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)
    controller.start_hook(use_spawn=False)
    assert errors
    assert errors[-1].title == ui_messages.SCRIPT_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.SCRIPT_NOT_SELECTED_BODY


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
    controller, _, _, _, _, _, _, _ = build_controller(owner_widget, dummy_deps)

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
    controller, _, _, _, _, _, _, _ = build_controller(owner_widget, dummy_deps)

    resolved = controller.resolve_builtin_quick_script_path("detect_network_stack.js")
    assert resolved == builtin_script


def test_resolve_quick_script_path_falls_back_to_builtin_script(owner_widget, dummy_deps, tmp_path: Path) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    builtin_script = builtin_script_dir / "detect_network_stack.js"
    builtin_script.write_text("// builtin", encoding="utf-8")

    dummy_deps.context.hookers_js_dir = builtin_script_dir
    dummy_deps.workspace_service.script_dir = lambda package_name: tmp_path / "workspaces" / package_name / "js"
    controller, _, _, _, _, _, _, _ = build_controller(owner_widget, dummy_deps)

    resolved = controller.resolve_quick_script_path("pkg.demo", "detect_network_stack.js")
    assert resolved == builtin_script


def test_resolve_quick_script_path_raises_structured_error_when_missing(owner_widget, dummy_deps, tmp_path: Path) -> None:
    dummy_deps.context.hookers_js_dir = tmp_path / "hookers" / "js"
    dummy_deps.workspace_service.script_dir = lambda package_name: tmp_path / "workspaces" / package_name / "js"
    controller, _, _, _, _, _, _, _ = build_controller(owner_widget, dummy_deps)

    try:
        controller.resolve_quick_script_path("pkg.demo", "detect_network_stack.js")
        assert False, "expected HookStartError"
    except HookStartError as exc:
        assert "detect_network_stack.js" in exc.message
        assert exc.hint is not None


def test_start_detect_network_stack_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)
    controller.start_detect_network_stack(use_spawn=True)
    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY


def test_start_print_okhttp_interceptors_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)
    controller.start_print_okhttp_interceptors(use_spawn=True)
    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY


def test_start_okhttp_capture_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)
    controller.start_okhttp_capture(use_spawn=False)
    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY


def test_start_hook_register_natives_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)
    controller.start_hook_register_natives(use_spawn=True)
    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY


def test_start_find_anti_frida_so_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)
    controller.start_find_anti_frida_so(use_spawn=True)
    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY


def test_start_click_trace_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)
    controller.start_click_trace(use_spawn=False)
    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY


def test_start_edit_text_trace_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)
    controller.start_edit_text_trace(use_spawn=True)
    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY


def test_start_text_view_trace_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)
    controller.start_text_view_trace(use_spawn=False)
    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY


def test_start_url_trace_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)
    controller.start_url_trace(use_spawn=True)
    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY


def test_start_activity_events_trace_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)
    controller.start_activity_events_trace(use_spawn=False)
    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY


def test_start_jni_method_trace_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)
    controller.start_jni_method_trace(use_spawn=True)
    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY


def test_start_hook_encryption_algo_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)
    controller.start_quick_hook("hook_encryption_algo", selected_use_spawn=False)
    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY


def test_start_hook_encryption_algo2_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)
    controller.start_quick_hook("hook_encryption_algo2", selected_use_spawn=True)
    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY


def test_start_bypass_root_detect_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)
    controller.start_quick_hook("bypass_root_detect", selected_use_spawn=False)
    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY


def test_start_bypass_vpn_detect_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)
    controller.start_quick_hook("bypass_vpn_detect", selected_use_spawn=True)
    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY


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

    controller, widgets, busy_calls, _, logs, _, _, _ = build_controller(owner_widget, dummy_deps)
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

    controller, widgets, busy_calls, _, logs, _, _, _ = build_controller(owner_widget, dummy_deps)
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

    controller, widgets, busy_calls, _, logs, _, _, _ = build_controller(owner_widget, dummy_deps)
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

    controller, widgets, busy_calls, _, logs, _, _, _ = build_controller(owner_widget, dummy_deps)
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

    controller, widgets, busy_calls, _, logs, _, _, _ = build_controller(owner_widget, dummy_deps)
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

    controller, widgets, busy_calls, _, logs, _, _, _ = build_controller(owner_widget, dummy_deps)
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

    controller, widgets, busy_calls, _, logs, _, _, _ = build_controller(owner_widget, dummy_deps)
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

    controller, widgets, busy_calls, _, logs, _, _, _ = build_controller(owner_widget, dummy_deps)
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

    controller, widgets, busy_calls, _, logs, _, _, _ = build_controller(owner_widget, dummy_deps)
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

    controller, widgets, busy_calls, _, logs, _, _, _ = build_controller(owner_widget, dummy_deps)
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
    controller, widgets, busy_calls, _, logs, errors, _, _ = build_controller(owner_widget, dummy_deps)
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
    controller, widgets, _, _, _, errors, _, _ = build_controller(owner_widget, dummy_deps)
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
    controller, widgets, _, _, _, errors, _, _ = build_controller(owner_widget, dummy_deps)
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

    controller, widgets, busy_calls, _, logs, _, _, _ = build_controller(owner_widget, dummy_deps)
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
    controller, widgets, _, _, _, errors, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)
    controller.start_trace_init_proc(use_spawn=True)
    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY


def test_start_trace_init_proc_cancelled_dialog_does_nothing(
    owner_widget, dummy_deps, monkeypatch
) -> None:
    controller, widgets, busy_calls, _, logs, errors, _, _ = build_controller(owner_widget, dummy_deps)
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
    controller, widgets, _, _, _, errors, _, _ = build_controller(owner_widget, dummy_deps)
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

    controller, widgets, busy_calls, _, logs, _, _, _ = build_controller(owner_widget, dummy_deps)
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
    controller, widgets, _, _, _, errors, _, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)

    controller.start_advanced_frida_launcher(use_spawn=True)

    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.APP_NOT_SELECTED_BODY


def test_start_advanced_frida_launcher_rejects_when_active_session_exists(
    owner_widget, dummy_deps, monkeypatch
) -> None:
    controller, widgets, _, _, _, errors, _, _ = build_controller(owner_widget, dummy_deps)
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
                FridaScriptOption(label="[内置] beta.js", path=builtin_script),
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

    controller, widgets, busy_calls, _, logs, _, _, _ = build_controller(owner_widget, dummy_deps)
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
        scripts="[工作区] alpha.js -> [内置] beta.js"
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

    controller, widgets, _, _, logs, _, _, _ = build_controller(owner_widget, dummy_deps)
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
        scripts="[参数化] jni_method_trace.runtime.js"
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

    controller, widgets, _, _, logs, _, _, _ = build_controller(owner_widget, dummy_deps)
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
        scripts="[参数化] trace_init_proc.runtime.js"
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

    monkeypatch.setattr("ui.hook_runtime.FridaMultiLauncherDialog", FakeDialog)
    monkeypatch.setattr(
        "ui.hook_runtime.QInputDialog.getText",
        lambda *args, **kwargs: ("", False),
    )

    controller, widgets, busy_calls, _, logs, _, _, _ = build_controller(owner_widget, dummy_deps)
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

    controller, widgets, _, _, logs, _, _, _ = build_controller(owner_widget, dummy_deps)
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
        scripts="[参数化] jni_method_trace.runtime.js"
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

    controller, widgets, _, _, logs, _, _, _ = build_controller(owner_widget, dummy_deps)
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
        scripts="[参数化] trace_init_proc.runtime.js"
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

    controller, widgets, _, _, logs, _, _, _ = build_controller(owner_widget, dummy_deps)
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
        scripts="[参数化] jni_method_trace.runtime.js"
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

    controller, widgets, _, _, logs, _, _, _ = build_controller(owner_widget, dummy_deps)
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
        scripts="[参数化] jni_method_trace.runtime.js -> [参数化] jni_method_trace.runtime.js"
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

    controller, widgets, _, _, _, _, _, _ = build_controller(owner_widget, dummy_deps)
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

    controller, widgets, _, _, logs, _, _, _ = build_controller(owner_widget, dummy_deps)
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
        scripts="[参数化] trace_init_proc.runtime.js -> [参数化] trace_init_proc.runtime.js"
    )


def test_start_hook_encryption_algo_logs_and_uses_selected_mode(
    owner_widget, dummy_deps, tmp_path: Path
) -> None:
    builtin_script_dir = tmp_path / "hookers" / "js"
    builtin_script_dir.mkdir(parents=True)
    script_path = builtin_script_dir / "hook_encryption_algo.js"
    script_path.write_text("// builtin", encoding="utf-8")
    dummy_deps.context.hookers_js_dir = builtin_script_dir

    controller, widgets, busy_calls, _, logs, _, _, _ = build_controller(owner_widget, dummy_deps)
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

    controller, widgets, busy_calls, _, logs, _, _, _ = build_controller(owner_widget, dummy_deps)
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

    controller, widgets, busy_calls, _, logs, _, _, _ = build_controller(owner_widget, dummy_deps)
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

    controller, widgets, busy_calls, _, logs, _, _, _ = build_controller(owner_widget, dummy_deps)
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
    controller, _, busy_calls, status_calls, logs, _, refresh_calls, _ = build_controller(owner_widget, dummy_deps)
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
    controller, widgets, busy_calls, _, logs, _, refresh_calls, applied_payloads = build_controller(owner_widget, dummy_deps)
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


def test_on_auto_stop_finished_resets_ui_and_logs(owner_widget, dummy_deps) -> None:
    controller, widgets, busy_calls, status_calls, logs, _, refresh_calls, _ = build_controller(owner_widget, dummy_deps)
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
