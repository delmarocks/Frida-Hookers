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
