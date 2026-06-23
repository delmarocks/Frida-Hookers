from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QComboBox, QLineEdit, QMessageBox

from ui import ui_messages
from ui.rpc_tools import RpcToolController, RpcToolWidgets


def build_controller(owner_widget, dummy_deps):
    busy_calls = []
    status_calls = []
    logs = []
    errors = []
    applied_roots = []

    widgets = RpcToolWidgets(
        hook_target_input=QLineEdit(),
        inspect_target_input=QLineEdit(),
        script_combo=QComboBox(),
    )
    controller = RpcToolController(
        owner=owner_widget,
        widgets=widgets,
        deps=dummy_deps,
        set_busy=lambda busy, message=None: busy_calls.append((busy, message)),
        set_status_text=lambda message, status=None: status_calls.append((message, status)),
        append_log=logs.append,
        show_worker_error=errors.append,
        ensure_current_app_ready=lambda: "pkg.demo",
        apply_script_root=applied_roots.append,
    )
    return controller, widgets, busy_calls, status_calls, logs, errors, applied_roots


def test_format_result_text_handles_none_and_structures(owner_widget, dummy_deps) -> None:
    controller, *_ = build_controller(owner_widget, dummy_deps)
    assert controller.format_result_text(None) == ui_messages.NO_RESULT
    assert controller.format_result_text("  ") == ui_messages.NO_RESULT
    assert controller.format_result_text(["a", "b"]).startswith("[")


def test_inspect_target_requires_input(owner_widget, dummy_deps) -> None:
    controller, widgets, *_ = build_controller(owner_widget, dummy_deps)
    widgets.inspect_target_input.setText("   ")
    try:
        controller.inspect_target()
    except Exception as exc:
        assert str(exc) == ui_messages.INSPECT_TARGET_BODY
    else:
        raise AssertionError("expected structured error")


def test_generate_hook_script_requires_target(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _ = build_controller(owner_widget, dummy_deps)
    widgets.hook_target_input.setText("")
    controller.generate_hook_script()
    assert errors
    assert errors[-1].title == ui_messages.MISSING_TARGET_TITLE
    assert errors[-1].message == ui_messages.MISSING_HOOK_TARGET_BODY
    assert errors[-1].focus_target == "hook_target_input"


def test_start_rpc_action_reports_busy_instead_of_silently_returning(owner_widget, dummy_deps) -> None:
    controller, _, _, _, _, errors, _ = build_controller(owner_widget, dummy_deps)
    controller.rpc_action_thread = object()

    started = {"called": False}

    controller.start_rpc_action(
        busy_message=ui_messages.LOADING_ACTIVITIES,
        action=lambda: started.__setitem__("called", True),
        on_success=lambda _payload: None,
    )

    assert started["called"] is False
    assert errors
    assert errors[-1].message == ui_messages.RPC_ACTION_BUSY_BODY
    assert errors[-1].next_step == ui_messages.RPC_ACTION_BUSY_NEXT_STEP
    assert errors[-1].severity == "warning"


def test_on_hook_script_generated_updates_script_selection(owner_widget, dummy_deps, monkeypatch) -> None:
    controller, widgets, busy_calls, status_calls, logs, _, applied_roots = build_controller(owner_widget, dummy_deps)
    infos = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: infos.append(args))
    package_name = "pkg.demo"
    workspace_script_dir = dummy_deps.workspace_service.script_dir(package_name)
    generated_path = workspace_script_dir / "hook_demo.js"
    widgets.script_combo.addItem("other.js", str((workspace_script_dir / "other.js").resolve()))
    widgets.script_combo.addItem("hook_demo.js", str(generated_path.resolve()))
    payload = type(
        "Payload",
        (),
        {"package_name": package_name, "script_path": generated_path},
    )()

    controller.on_hook_script_generated(payload)

    assert logs[-1] == ui_messages.HOOK_SCRIPT_GENERATED_LOG.format(path=generated_path)
    assert applied_roots[-1] == workspace_script_dir
    assert widgets.script_combo.currentData() == str(generated_path.resolve())
    assert busy_calls[-1] == (False, ui_messages.READY)
    assert status_calls[-1] == (
        ui_messages.READY,
        ui_messages.HOOK_SCRIPT_GENERATED_STATUS.format(name="hook_demo.js"),
    )
    assert infos
    assert infos[-1][1] == ui_messages.GENERATED_TITLE


def test_on_activities_ready_logs_and_shows_result(owner_widget, dummy_deps, monkeypatch) -> None:
    controller, _, busy_calls, _, logs, _, _ = build_controller(owner_widget, dummy_deps)
    shown = []
    monkeypatch.setattr(controller, "show_result_dialog", lambda title, content: shown.append((title, content)))
    payload = type("Payload", (), {"package_name": "pkg.demo", "result": ["A1", "A2"]})()
    controller.on_activities_ready(payload)
    assert logs[-1] == ui_messages.LOADED_ACTIVITIES_LOG.format(package="pkg.demo")
    assert shown[-1][0] == ui_messages.ACTIVITY_LIST_TITLE
    assert busy_calls[-1] == (False, ui_messages.READY)


def test_show_result_dialog_tracks_window_until_destroyed(owner_widget, dummy_deps) -> None:
    controller, *_ = build_controller(owner_widget, dummy_deps)

    controller.show_result_dialog("Demo", "content")

    assert len(controller.result_windows) == 1
    dialog = controller.result_windows[0]
    dialog.deleteLater()
    dialog.destroyed.emit()

    assert controller.result_windows == []


def test_on_services_ready_logs_dialog_and_sets_ready(owner_widget, dummy_deps, monkeypatch) -> None:
    controller, _, busy_calls, _, logs, _, _ = build_controller(owner_widget, dummy_deps)
    shown = []
    monkeypatch.setattr(controller, "show_result_dialog", lambda title, content: shown.append((title, content)))
    payload = type("Payload", (), {"package_name": "pkg.demo", "result": ["S1"]})()

    controller.on_services_ready(payload)

    assert logs[-1] == ui_messages.LOADED_SERVICES_LOG.format(package="pkg.demo")
    assert shown[-1] == (ui_messages.SERVICE_LIST_TITLE, '[\n  "S1"\n]')
    assert busy_calls[-1] == (False, ui_messages.READY)


def test_generate_hook_script_missing_target_includes_next_step(owner_widget, dummy_deps) -> None:
    from ui.rpc_tools import RpcToolController, RpcToolWidgets

    errors = []
    widgets = RpcToolWidgets(
        hook_target_input=QLineEdit(''),
        inspect_target_input=QLineEdit(''),
        script_combo=QComboBox(),
    )
    controller = RpcToolController(
        owner_widget,
        widgets,
        dummy_deps,
        set_busy=lambda *args, **kwargs: None,
        set_status_text=lambda *args, **kwargs: None,
        append_log=lambda *args, **kwargs: None,
        show_worker_error=errors.append,
        ensure_current_app_ready=lambda: 'pkg.demo',
        apply_script_root=lambda *args, **kwargs: None,
    )

    controller.generate_hook_script()

    assert errors
    assert errors[-1].next_step == ui_messages.MISSING_HOOK_TARGET_NEXT_STEP


def test_generate_hook_script_preserves_structured_hookers_error(owner_widget, dummy_deps) -> None:
    from core.errors import HookersError, to_ui_error_payload
    from ui.rpc_tools import RpcToolController, RpcToolWidgets

    errors = []
    widgets = RpcToolWidgets(
        hook_target_input=QLineEdit('demo.Target:onCreate'),
        inspect_target_input=QLineEdit(''),
        script_combo=QComboBox(),
    )
    controller = RpcToolController(
        owner_widget,
        widgets,
        dummy_deps,
        set_busy=lambda *args, **kwargs: None,
        set_status_text=lambda *args, **kwargs: None,
        append_log=lambda *args, **kwargs: None,
        show_worker_error=errors.append,
        ensure_current_app_ready=lambda: 'pkg.demo',
        apply_script_root=lambda *args, **kwargs: None,
    )

    structured = HookersError(
        '自定义结构化错误',
        hint='请检查 Hook 目标。',
        next_step='先修正目标后再重试。',
        focus_target='hook_target_input',
        severity='warning',
    )

    controller.start_rpc_action = lambda **kwargs: errors.append(to_ui_error_payload(structured))
    controller.deps.rpc_service.generate_hook_script = lambda _target: (_ for _ in ()).throw(structured)

    controller.generate_hook_script()

    assert errors
    assert errors[-1].message == '自定义结构化错误'
    assert errors[-1].hint == '请检查 Hook 目标。'
    assert errors[-1].next_step == '先修正目标后再重试。'
    assert errors[-1].focus_target == 'hook_target_input'


def test_inspect_target_missing_includes_next_step(owner_widget, dummy_deps) -> None:
    from ui.rpc_tools import RpcToolController, RpcToolWidgets

    widgets = RpcToolWidgets(
        hook_target_input=QLineEdit(''),
        inspect_target_input=QLineEdit(''),
        script_combo=QComboBox(),
    )
    controller = RpcToolController(
        owner_widget,
        widgets,
        dummy_deps,
        set_busy=lambda *args, **kwargs: None,
        set_status_text=lambda *args, **kwargs: None,
        append_log=lambda *args, **kwargs: None,
        show_worker_error=lambda *args, **kwargs: None,
        ensure_current_app_ready=lambda: 'pkg.demo',
        apply_script_root=lambda *args, **kwargs: None,
    )

    try:
        controller.inspect_target()
        assert False, 'expected RpcTargetMissingError'
    except Exception as exc:
        assert getattr(exc, 'next_step', None) == ui_messages.INSPECT_TARGET_NEXT_STEP


def test_show_activities_preserves_structured_hookers_error(owner_widget, dummy_deps, monkeypatch) -> None:
    from core.errors import HookersError

    controller, _, _, _, _, errors, _ = build_controller(owner_widget, dummy_deps)
    structured = HookersError(
        'RPC 结构化错误',
        hint='请检查设备状态。',
        next_step='先重新准备环境，再重试读取 Activity。',
        severity='warning',
    )
    monkeypatch.setattr(controller, 'start_rpc_action', lambda **kwargs: errors.append(kwargs['action']()))
    controller.deps.rpc_service.activitys = lambda: (_ for _ in ()).throw(structured)

    try:
        controller.show_activities()
    except HookersError as exc:
        assert exc is structured
    else:
        raise AssertionError('expected structured HookersError to be preserved')


def test_show_object_info_preserves_structured_hookers_error(owner_widget, dummy_deps, monkeypatch) -> None:
    from core.errors import HookersError

    controller, widgets, _, _, _, errors, _ = build_controller(owner_widget, dummy_deps)
    widgets.inspect_target_input.setText('demo.Target')
    structured = HookersError(
        '对象查询结构化错误',
        hint='请检查对象目标。',
        next_step='先修正 inspect 输入后再重试。',
        focus_target='inspect_target_input',
        severity='warning',
    )
    monkeypatch.setattr(controller, 'start_rpc_action', lambda **kwargs: errors.append(kwargs['action']()))
    controller.deps.rpc_service.object_info = lambda _target: (_ for _ in ()).throw(structured)

    try:
        controller.show_object_info()
    except HookersError as exc:
        assert exc is structured
    else:
        raise AssertionError('expected structured HookersError to be preserved')
