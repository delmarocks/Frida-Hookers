from __future__ import annotations

from pathlib import Path
import threading
import time

import pytest
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QComboBox, QLabel, QLineEdit, QPushButton, QMessageBox

from core.errors import AppNotSelectedError
from ui import ui_messages
from ui.app_workflow import AppWorkflowController, AppWorkflowWidgets


def build_controller(owner_widget, dummy_deps):
    busy_calls = []
    status_calls = []
    logs = []
    errors = []
    applied_roots = []

    widgets = AppWorkflowWidgets(
        app_combo=QComboBox(),
        prepare_workspace_button=QPushButton(),
        workspace_path_input=QLineEdit(),
        left_pid_uid_status_value=QLabel(),
        left_version_mode_status_value=QLabel(),
        current_state_label=QLabel(),
    )
    controller = AppWorkflowController(
        owner=owner_widget,
        widgets=widgets,
        deps=dummy_deps,
        set_busy=lambda busy, message=None: busy_calls.append((busy, message)),
        set_status_text=lambda message, status=None: status_calls.append((message, status)),
        append_log=logs.append,
        show_worker_error=errors.append,
        apply_script_root=applied_roots.append,
    )
    return controller, widgets, busy_calls, status_calls, logs, errors, applied_roots


def _process_until(qapp, predicate, timeout: float = 1.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        qapp.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    qapp.processEvents()
    assert predicate()


def test_selected_package_name_returns_none_when_unselected(owner_widget, dummy_deps) -> None:
    controller, widgets, *_ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)
    assert controller.selected_package_name() is None


def test_apply_apps_payload_auto_selects_foreground(owner_widget, dummy_deps, monkeypatch) -> None:
    controller, widgets, busy_calls, status_calls, logs, _, applied_roots = build_controller(owner_widget, dummy_deps)
    infos = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: infos.append(args))
    apps = [
        {"name": "Boss", "identifier": "com.hpbr.bosszhipin", "pid": 111},
        {"name": "Momo", "identifier": "com.immomo.momo", "pid": 222},
    ]
    dummy_deps.context.last_connected_device_serial = "7a1fe68a"
    dummy_deps.context.last_prepare_frida_server_status = "reused"
    controller.on_apps_ready(apps, "com.hpbr.bosszhipin")
    assert widgets.app_combo.currentData() == "com.hpbr.bosszhipin"
    assert applied_roots[-1] == dummy_deps.workspace_service.script_dir("com.hpbr.bosszhipin")
    assert busy_calls[-1] == (False, ui_messages.SYNCED_APPS.format(count=2))
    assert status_calls[-1][0] == ui_messages.PREPARE_READY_STATE
    assert any("com.hpbr.bosszhipin" in call[2] for call in infos)
    assert logs[0] == ui_messages.PREPARE_DEVICE_CONNECTED_LOG.format(serial="7a1fe68a")
    assert logs[1] == ui_messages.PREPARE_FRIDA_READY_LOG.format(
        status=ui_messages.PREPARE_FRIDA_STATUS_REUSED,
    )
    assert ui_messages.SYNCED_APPS_LOG.format(count=2) in logs
    assert ui_messages.AUTO_SELECTED_FOREGROUND_LOG.format(package="com.hpbr.bosszhipin") in logs
    assert logs[-1] == ui_messages.PREPARE_DONE_LOG


def test_apply_apps_payload_silent_skips_ready_feedback(owner_widget, dummy_deps, monkeypatch) -> None:
    controller, widgets, busy_calls, status_calls, logs, _, applied_roots = build_controller(owner_widget, dummy_deps)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: (_ for _ in ()).throw(AssertionError("should not show info")))
    apps = [{"name": "Boss", "identifier": "com.hpbr.bosszhipin", "pid": 111}]
    controller.apply_apps_payload_silent(apps, foreground_package=None)
    assert widgets.app_combo.count() == 1
    assert applied_roots == []
    assert busy_calls[-1] == (False, ui_messages.SYNCED_APPS.format(count=1))
    assert status_calls == []
    assert logs == [ui_messages.SYNCED_APPS_LOG.format(count=1)]


def test_on_package_changed_switches_default_script_root_to_workspace_script_dir(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, logs, _, applied_roots = build_controller(owner_widget, dummy_deps)
    package_name = "pkg.demo"
    widgets.app_combo.addItem("Demo", package_name)
    widgets.app_combo.setCurrentIndex(0)

    controller.on_package_changed()

    workspace_dir = dummy_deps.workspace_service.workspace_dir(package_name)
    script_dir = dummy_deps.workspace_service.script_dir(package_name)
    assert applied_roots[-1] == script_dir
    assert widgets.workspace_path_input.text() == str(workspace_dir)
    assert ui_messages.WORKSPACE_PATH_LOG.format(workspace_dir=workspace_dir) in logs
    assert ui_messages.WORKSPACE_SCRIPT_DIR_LOG.format(script_dir=script_dir) in logs
    assert ui_messages.WORKSPACE_NOT_INITIALIZED_LOG in logs
    assert len(logs) == 3


def test_on_package_changed_does_not_sync_builtin_scripts_before_workspace_prepare(
    owner_widget,
    dummy_deps,
    tmp_path,
) -> None:
    controller, widgets, _, _, _, _, applied_roots = build_controller(owner_widget, dummy_deps)
    package_name = "pkg.demo"
    workspace_dir = tmp_path / "workspaces" / package_name
    script_dir = workspace_dir / "js"

    dummy_deps.workspace_service.workspace_dir = lambda package: workspace_dir
    dummy_deps.workspace_service.script_dir = lambda package: script_dir

    widgets.app_combo.addItem("Demo", package_name)
    widgets.app_combo.setCurrentIndex(0)

    controller.on_package_changed()

    assert applied_roots[-1] == script_dir
    assert script_dir.exists() is False


def test_prepare_selected_workspace_requires_selected_app(owner_widget, dummy_deps) -> None:
    controller, widgets, _, _, _, errors, _ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)

    controller.prepare_selected_workspace()

    assert errors
    assert errors[-1].title == ui_messages.APP_NOT_SELECTED_TITLE
    assert errors[-1].message == ui_messages.WORKSPACE_APP_NOT_SELECTED_BODY


def test_on_workspace_ready_emits_summary_logs_for_created_workspace(owner_widget, dummy_deps) -> None:
    controller, widgets, busy_calls, _, logs, _, applied_roots = build_controller(owner_widget, dummy_deps)
    package_name = "pkg.demo"
    workspace_dir = str(dummy_deps.workspace_service.workspace_dir(package_name))
    script_dir = str(dummy_deps.workspace_service.script_dir(package_name))
    dummy_deps.context.last_workspace_prepare_mode = "created"
    dummy_deps.context.last_workspace_apk_status = "pulled"

    controller.on_workspace_ready(package_name, workspace_dir, script_dir)

    assert applied_roots[-1] == Path(script_dir)
    assert widgets.workspace_path_input.text() == workspace_dir
    assert busy_calls[-1] == (False, ui_messages.WORKSPACE_READY)
    assert logs == [
        ui_messages.WORKSPACE_PREPARE_MODE_CREATED_LOG,
        ui_messages.WORKSPACE_PREPARE_APK_PULLED_LOG,
        ui_messages.WORKSPACE_PREPARE_SCRIPT_DIR_LOG.format(script_dir=script_dir),
        ui_messages.WORKSPACE_PREPARE_PATH_LOG.format(workspace_dir=workspace_dir),
        ui_messages.WORKSPACE_PREPARE_DONE_LOG,
    ]
    assert ui_messages.WORKSPACE_PATH_LOG.format(workspace_dir=Path(workspace_dir)) not in logs
    assert ui_messages.WORKSPACE_SCRIPT_DIR_LOG.format(script_dir=Path(script_dir)) not in logs
    assert ui_messages.WORKSPACE_NOT_INITIALIZED_LOG not in logs



def test_on_workspace_ready_emits_summary_logs_for_updated_workspace(owner_widget, dummy_deps) -> None:
    controller, widgets, busy_calls, _, logs, _, applied_roots = build_controller(owner_widget, dummy_deps)
    package_name = "pkg.demo"
    workspace_dir = str(dummy_deps.workspace_service.workspace_dir(package_name))
    script_dir = str(dummy_deps.workspace_service.script_dir(package_name))
    dummy_deps.context.last_workspace_prepare_mode = "updated"
    dummy_deps.context.last_workspace_apk_status = "reused"

    controller.on_workspace_ready(package_name, workspace_dir, script_dir)

    assert applied_roots[-1] == Path(script_dir)
    assert widgets.workspace_path_input.text() == workspace_dir
    assert busy_calls[-1] == (False, ui_messages.WORKSPACE_READY)
    assert logs == [
        ui_messages.WORKSPACE_PREPARE_MODE_UPDATED_LOG,
        ui_messages.WORKSPACE_PREPARE_APK_REUSED_LOG,
        ui_messages.WORKSPACE_PREPARE_SCRIPT_DIR_LOG.format(script_dir=script_dir),
        ui_messages.WORKSPACE_PREPARE_PATH_LOG.format(workspace_dir=workspace_dir),
        ui_messages.WORKSPACE_PREPARE_DONE_LOG,
    ]


def test_apply_apps_payload_no_apps_emits_structured_warning(owner_widget, dummy_deps, monkeypatch) -> None:
    controller, widgets, busy_calls, status_calls, logs, errors, _ = build_controller(owner_widget, dummy_deps)
    infos = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: infos.append(args))

    dummy_deps.context.last_connected_device_serial = "7a1fe68a"
    dummy_deps.context.last_prepare_frida_server_status = "started"
    controller.on_apps_ready([], None)

    assert widgets.app_combo.count() == 0
    assert busy_calls[-1] == (False, ui_messages.SYNCED_APPS.format(count=0))
    assert status_calls[-1][0] == ui_messages.PREPARE_NO_APPS_STATE
    assert logs[0] == ui_messages.PREPARE_DEVICE_CONNECTED_LOG.format(serial="7a1fe68a")
    assert logs[1] == ui_messages.PREPARE_FRIDA_READY_LOG.format(
        status=ui_messages.PREPARE_FRIDA_STATUS_STARTED,
    )
    assert logs[-1] == ui_messages.NO_APPS_FOUND_LOG
    assert errors
    assert errors[-1].title == ui_messages.NO_APPS_FOUND_TITLE
    assert errors[-1].message == ui_messages.NO_APPS_FOUND_BODY
    assert infos == []


def test_ensure_current_app_ready_raises_structured_error_when_no_app_selected(owner_widget, dummy_deps) -> None:
    controller, widgets, *_ = build_controller(owner_widget, dummy_deps)
    widgets.app_combo.setCurrentIndex(-1)

    with pytest.raises(AppNotSelectedError):
        controller.ensure_current_app_ready()


def test_refresh_app_status_panel_uses_active_session_mode(owner_widget, dummy_deps) -> None:
    controller, widgets, *_ = build_controller(owner_widget, dummy_deps)
    app = type("App", (), {"name": "Boss", "identifier": "pkg.demo", "pid": 4321, "uid": 10086, "version": "9.1.4"})()
    dummy_deps.context.apps = [app]
    dummy_deps.context.current_app = app
    dummy_deps.context.active_session = type("Session", (), {"mode": "spawn"})()
    widgets.app_combo.addItem("Boss", "pkg.demo")
    widgets.app_combo.setCurrentIndex(0)
    controller.refresh_app_status_panel()
    assert widgets.left_pid_uid_status_value.text() == ui_messages.PID_UID_TEXT.format(pid=4321, uid=10086)
    assert widgets.left_version_mode_status_value.text() == ui_messages.VERSION_MODE_TEXT.format(
        version="9.1.4",
        mode="spawn",
    )


def test_device_prepare_apps_ready_callback_pattern_dispatches_to_main_thread(
    qapp,
    owner_widget,
    dummy_deps,
) -> None:
    controller, _, _, _, _, _, _ = build_controller(owner_widget, dummy_deps)
    main_thread = qapp.thread()
    done = threading.Event()
    observed: dict[str, object] = {}

    def fake_on_apps_ready(apps, foreground_package) -> None:
        observed["apps"] = apps
        observed["foreground_package"] = foreground_package
        observed["thread"] = QThread.currentThread()
        done.set()

    controller.on_apps_ready = fake_on_apps_ready
    callback = lambda apps, foreground_package: controller.ui_dispatcher.submit(
        controller.on_apps_ready,
        apps,
        foreground_package,
    )

    worker = threading.Thread(
        target=lambda: callback(
            [{"name": "Demo", "identifier": "pkg.demo", "pid": 1234}],
            "pkg.demo",
        )
    )
    worker.start()
    worker.join()

    _process_until(qapp, done.is_set)

    assert observed["apps"] == [{"name": "Demo", "identifier": "pkg.demo", "pid": 1234}]
    assert observed["foreground_package"] == "pkg.demo"
    assert observed["thread"] is main_thread


def test_device_prepare_failed_callback_pattern_dispatches_to_main_thread(
    qapp,
    owner_widget,
    dummy_deps,
) -> None:
    controller, _, _, _, _, errors, _ = build_controller(owner_widget, dummy_deps)
    main_thread = qapp.thread()
    done = threading.Event()
    observed: dict[str, object] = {}

    def fake_show_worker_error(payload) -> None:
        errors.append(payload)
        observed["thread"] = QThread.currentThread()
        done.set()

    controller.show_worker_error = fake_show_worker_error
    callback = lambda error: controller.ui_dispatcher.submit(
        controller.show_worker_error,
        error,
    )

    worker = threading.Thread(target=lambda: callback("准备环境失败。"))
    worker.start()
    worker.join()

    _process_until(qapp, done.is_set)

    assert errors
    assert errors[-1] == "准备环境失败。"
    assert observed["thread"] is main_thread
