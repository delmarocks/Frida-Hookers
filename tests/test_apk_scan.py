from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton

from ui import ui_messages
from ui.apk_scan import ApkScanController, ApkScanWidgets


def build_controller(owner_widget, dummy_deps):
    busy_calls = []
    status_calls = []
    logs = []
    errors = []
    widgets = ApkScanWidgets(
        apk_scan_path_input=QLineEdit(),
        apk_scan_status_label=QLabel(),
        select_apk_scan_button=QPushButton(),
        start_apk_scan_button=QPushButton(),
    )
    controller = ApkScanController(
        owner=owner_widget,
        widgets=widgets,
        deps=dummy_deps,
        set_busy=lambda busy, message=None: busy_calls.append((busy, message)),
        set_status_text=lambda message, status=None: status_calls.append((message, status)),
        append_log=logs.append,
        show_worker_error=errors.append,
        shorten_path=lambda path: f"short::{path.name}",
    )
    return controller, widgets, busy_calls, status_calls, logs, errors


def test_update_apk_scan_display_without_selection(owner_widget, dummy_deps) -> None:
    controller, widgets, *_ = build_controller(owner_widget, dummy_deps)
    controller.update_apk_scan_display()
    assert widgets.apk_scan_status_label.text() == ui_messages.APK_SCAN_EMPTY_STATUS
    assert widgets.start_apk_scan_button.isEnabled() is False


def test_update_apk_scan_display_with_selection(owner_widget, dummy_deps) -> None:
    controller, widgets, *_ = build_controller(owner_widget, dummy_deps)
    controller.selected_apk_scan_path = Path("demo.apk")
    controller.update_apk_scan_display()
    assert widgets.apk_scan_status_label.text() == ui_messages.APK_SCAN_TARGET_STATUS.format(name="demo.apk")
    assert widgets.apk_scan_path_input.text() == "short::demo.apk"
    assert widgets.start_apk_scan_button.isEnabled()


def test_start_apk_scan_requires_selection(owner_widget, dummy_deps) -> None:
    controller, widgets, *_ = build_controller(owner_widget, dummy_deps)
    controller, widgets, _, _, _, errors = build_controller(owner_widget, dummy_deps)
    controller.start_apk_scan()
    assert errors
    assert errors[-1].title == ui_messages.APK_SCAN_TITLE
    assert errors[-1].message == ui_messages.APK_SCAN_BODY


def test_on_apk_scan_succeeded_updates_status(owner_widget, dummy_deps) -> None:
    controller, _, busy_calls, status_calls, logs, _ = build_controller(owner_widget, dummy_deps)
    payload = type("Payload", (), {"apk_path": Path("demo.apk")})()
    controller.on_apk_scan_succeeded(payload)
    assert logs[-1] == ui_messages.APK_SCAN_FINISHED_LOG.format(apk_path=Path("demo.apk"))
    assert status_calls[-1] == (ui_messages.APK_SCAN_COMPLETE, ui_messages.APK_SCAN_COMPLETE)
    assert busy_calls[-1] == (False, ui_messages.APK_SCAN_COMPLETE)
