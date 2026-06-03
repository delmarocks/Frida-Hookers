from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QComboBox, QLabel, QLineEdit, QMessageBox, QPushButton, QWidget
from core.errors import (
    AppNotSelectedError,
    HookersError,
    NoAppsFoundError,
    WorkspaceAppNotSelectedError,
    to_ui_error_payload,
)

from .controller_types import (
    AppInfoLike,
    AppListItem,
    AppsReadyPayload,
    BusySetter,
    ErrorPresenter,
    GuiDepsLike,
    LogAppender,
    ScriptRootApplier,
    StatusSetter,
)
from .workers.device_worker import DeviceWorker
from .workers.workspace_worker import WorkspaceWorker
from .ui_thread_dispatcher import UiThreadDispatcher
from . import ui_messages


@dataclass
class AppWorkflowWidgets:
    app_combo: QComboBox
    prepare_workspace_button: QPushButton
    workspace_path_input: QLineEdit
    left_pid_uid_status_value: QLabel
    left_version_mode_status_value: QLabel
    current_state_label: QLabel


class AppWorkflowController:
    def __init__(
        self,
        owner: QWidget,
        widgets: AppWorkflowWidgets,
        deps: GuiDepsLike,
        *,
        set_busy: BusySetter,
        set_status_text: StatusSetter,
        append_log: LogAppender,
        show_worker_error: ErrorPresenter,
        apply_script_root: ScriptRootApplier,
    ) -> None:
        self.owner = owner
        self.widgets = widgets
        self.deps = deps
        self.set_busy = set_busy
        self.set_status_text = set_status_text
        self.append_log = append_log
        self.show_worker_error = show_worker_error
        self.apply_script_root = apply_script_root

        self.device_thread: QThread | None = None
        self.device_worker: DeviceWorker | None = None
        self.workspace_thread: QThread | None = None
        self.workspace_worker: WorkspaceWorker | None = None
        self.ui_dispatcher = UiThreadDispatcher(owner)
        self._suppress_package_change_logs = False
        self._workspace_prepare_in_progress = False

    def _present_local_error(self, exc: HookersError) -> None:
        self.show_worker_error(to_ui_error_payload(exc))

    def selected_package_name(self) -> str | None:
        value = self.widgets.app_combo.currentData()
        if value is None:
            return None
        return str(value)

    def find_cached_app(self, package_name: str | None) -> AppInfoLike | None:
        if not package_name:
            return None
        for app in self.deps.context.apps:
            if app.identifier == package_name:
                return app
        return None

    def clear_workspace_display(self) -> None:
        self.widgets.workspace_path_input.clear()
        self.widgets.workspace_path_input.setToolTip("")

    def refresh_app_status_panel(self, package_name: str | None = None) -> None:
        package_name = package_name or self.selected_package_name()
        current_app = self.deps.context.current_app
        if current_app is not None and current_app.identifier != package_name:
            current_app = None

        cached_app = self.find_cached_app(package_name)
        active_session = self.deps.context.active_session

        pid = cached_app.pid if cached_app is not None else None
        uid = None
        version = None
        mode = ui_messages.MODE_NOT_RUNNING

        if current_app is not None:
            pid = current_app.pid if current_app.pid is not None else pid
            uid = current_app.uid
            version = current_app.version
        if active_session is not None and self.deps.context.current_app is not None:
            if package_name == self.deps.context.current_app.identifier:
                mode = active_session.mode

        self.widgets.left_pid_uid_status_value.setText(
            ui_messages.PID_UID_TEXT.format(
                pid=pid if pid is not None else "-",
                uid=uid if uid is not None else "-",
            )
        )
        self.widgets.left_version_mode_status_value.setText(
            ui_messages.VERSION_MODE_TEXT.format(version=version or "-", mode=mode)
        )

    def on_package_changed(self) -> None:
        package_name = self.selected_package_name()
        self.deps.rpc_service.invalidate_persistent_session()
        if not package_name:
            self.clear_workspace_display()
            self.widgets.prepare_workspace_button.setDisabled(True)
            self.refresh_app_status_panel(None)
            return

        workspace_dir = self.deps.workspace_service.workspace_dir(package_name)
        script_dir = self.deps.workspace_service.script_dir(package_name)
        self.widgets.prepare_workspace_button.setDisabled(False)

        self.widgets.workspace_path_input.setText(str(workspace_dir))
        self.widgets.workspace_path_input.setToolTip(str(workspace_dir))

        self.apply_script_root(script_dir)
        self.refresh_app_status_panel(package_name)

        if not self._suppress_package_change_logs:
            self.append_log(ui_messages.WORKSPACE_PATH_LOG.format(workspace_dir=workspace_dir))
            self.append_log(
                ui_messages.WORKSPACE_SCRIPT_DIR_LOG.format(
                    script_dir=script_dir
                )
            )
            if not script_dir.exists():
                self.append_log(ui_messages.WORKSPACE_NOT_INITIALIZED_LOG)

    def prepare_selected_workspace(self) -> None:
        package_name = self.selected_package_name()
        if not package_name:
            self._present_local_error(
                WorkspaceAppNotSelectedError(ui_messages.WORKSPACE_APP_NOT_SELECTED_BODY)
            )
            return
        self.start_workspace_prepare(package_name)

    def start_workspace_prepare(self, package_name: str) -> None:
        if self.workspace_thread is not None:
            return

        self._workspace_prepare_in_progress = True
        self.append_log(ui_messages.WORKSPACE_PREPARE_START_LOG)
        self.set_busy(True, ui_messages.INITIALIZING_WORKSPACE)
        self.workspace_thread = QThread(self.owner)
        self.workspace_worker = WorkspaceWorker(
            device_service=self.deps.device_service,
            workspace_service=self.deps.workspace_service,
            package_name=package_name,
        )
        self.workspace_worker.moveToThread(self.workspace_thread)

        self.workspace_thread.started.connect(self.workspace_worker.run)
        self.workspace_worker.ready.connect(
            lambda package_name, workspace_dir, script_dir: self.ui_dispatcher.submit(
                self.on_workspace_ready,
                package_name,
                workspace_dir,
                script_dir,
            )
        )
        self.workspace_worker.failed.connect(
            lambda error: self.ui_dispatcher.submit(self._on_workspace_prepare_failed, error)
        )
        self.workspace_worker.finished.connect(self.workspace_thread.quit)
        self.workspace_worker.finished.connect(self.workspace_worker.deleteLater)
        self.workspace_thread.finished.connect(self.workspace_thread.deleteLater)
        self.workspace_thread.finished.connect(self._clear_workspace_thread)
        self.workspace_thread.start()

    def _clear_workspace_thread(self) -> None:
        self.workspace_thread = None
        self.workspace_worker = None

    def _on_workspace_prepare_failed(self, error) -> None:
        self._workspace_prepare_in_progress = False
        self.show_worker_error(error)

    def on_workspace_ready(
        self,
        package_name: str,
        workspace_dir: str,
        script_dir: str,
    ) -> None:
        self.widgets.workspace_path_input.setText(workspace_dir)
        self.widgets.workspace_path_input.setToolTip(workspace_dir)
        self._suppress_package_change_logs = True
        try:
            self.apply_script_root(Path(script_dir))
            self.refresh_app_status_panel(package_name)
        finally:
            self._suppress_package_change_logs = False
        self.set_busy(False, ui_messages.WORKSPACE_READY)

        prepare_mode = getattr(self.deps.context, "last_workspace_prepare_mode", None)
        if prepare_mode == "created":
            self.append_log(ui_messages.WORKSPACE_PREPARE_MODE_CREATED_LOG)
        elif prepare_mode == "updated":
            self.append_log(ui_messages.WORKSPACE_PREPARE_MODE_UPDATED_LOG)

        apk_status = getattr(self.deps.context, "last_workspace_apk_status", None)
        if apk_status == "pulled":
            self.append_log(ui_messages.WORKSPACE_PREPARE_APK_PULLED_LOG)
        elif apk_status == "reused":
            self.append_log(ui_messages.WORKSPACE_PREPARE_APK_REUSED_LOG)

        self.append_log(
            ui_messages.WORKSPACE_PREPARE_SCRIPT_DIR_LOG.format(script_dir=script_dir)
        )
        self.append_log(
            ui_messages.WORKSPACE_PREPARE_PATH_LOG.format(workspace_dir=workspace_dir)
        )
        self.append_log(ui_messages.WORKSPACE_PREPARE_DONE_LOG)
        self._workspace_prepare_in_progress = False

    def start_device_prepare(self) -> None:
        if self.device_thread is not None:
            return

        self.clear_workspace_display()
        self.widgets.app_combo.blockSignals(True)
        self.widgets.app_combo.setCurrentIndex(-1)
        self.widgets.app_combo.blockSignals(False)
        self.widgets.prepare_workspace_button.setDisabled(True)
        self.refresh_app_status_panel(None)
        self.apply_script_root(self.deps.context.hookers_js_dir)
        self.append_log(ui_messages.PREPARE_START_LOG)
        self.set_busy(True, ui_messages.PREPARING_DEVICE)

        self.device_thread = QThread(self.owner)
        self.device_worker = DeviceWorker(device_service=self.deps.device_service)
        self.device_worker.moveToThread(self.device_thread)

        self.device_thread.started.connect(self.device_worker.run)
        self.device_worker.apps_ready.connect(
            lambda apps, foreground_package: self.ui_dispatcher.submit(
                self.on_apps_ready,
                apps,
                foreground_package,
            )
        )
        self.device_worker.failed.connect(
            lambda error: self.ui_dispatcher.submit(self.show_worker_error, error)
        )
        self.device_worker.finished.connect(self.device_thread.quit)
        self.device_worker.finished.connect(self.device_worker.deleteLater)
        self.device_thread.finished.connect(self.device_thread.deleteLater)
        self.device_thread.finished.connect(self._clear_device_thread)
        self.device_thread.start()

    def _clear_device_thread(self) -> None:
        self.device_thread = None
        self.device_worker = None

    def on_apps_ready(
        self,
        apps: list[AppListItem],
        foreground_package: object = None,
    ) -> None:
        serial = getattr(self.deps.context, "last_connected_device_serial", None)
        if serial:
            self.append_log(ui_messages.PREPARE_DEVICE_CONNECTED_LOG.format(serial=serial))

        frida_status = getattr(self.deps.context, "last_prepare_frida_server_status", None)
        frida_status_text = ui_messages.PREPARE_FRIDA_STATUS_REUSED
        if frida_status == "started":
            frida_status_text = ui_messages.PREPARE_FRIDA_STATUS_STARTED
        self.append_log(ui_messages.PREPARE_FRIDA_READY_LOG.format(status=frida_status_text))

        payload = AppsReadyPayload(
            apps=apps,
            foreground_package=foreground_package if isinstance(foreground_package, str) else None,
        )
        self.apply_apps_payload(payload, show_ready_feedback=True)

    def apply_apps_payload(
        self,
        payload: AppsReadyPayload,
        *,
        show_ready_feedback: bool,
    ) -> None:
        self.deps.rpc_service.invalidate_persistent_session()
        self.widgets.app_combo.blockSignals(True)
        self.widgets.app_combo.clear()
        for app in payload.apps:
            name = app["name"]
            pid = app["pid"]
            identifier = app["identifier"]
            label = f"{name} ({identifier})"
            if pid is not None:
                label = f"[{pid}] {label}"
            self.widgets.app_combo.addItem(label, identifier)
        selected_index = -1
        if payload.foreground_package:
            selected_index = self.widgets.app_combo.findData(payload.foreground_package)
        self.widgets.app_combo.setCurrentIndex(selected_index)
        self.widgets.app_combo.blockSignals(False)
        if selected_index < 0:
            self.widgets.prepare_workspace_button.setDisabled(True)
            self.clear_workspace_display()
        else:
            self._suppress_package_change_logs = show_ready_feedback
            try:
                self.on_package_changed()
            finally:
                self._suppress_package_change_logs = False

        self.set_busy(False, ui_messages.SYNCED_APPS.format(count=len(payload.apps)))
        self.append_log(ui_messages.SYNCED_APPS_LOG.format(count=len(payload.apps)))
        if not show_ready_feedback:
            self.refresh_app_status_panel()
            return

        if payload.apps:
            self.set_status_text(ui_messages.PREPARE_READY_STATE)
            if selected_index >= 0 and payload.foreground_package:
                self.append_log(
                    ui_messages.AUTO_SELECTED_FOREGROUND_LOG.format(
                        package=payload.foreground_package
                    )
                )
                QMessageBox.information(
                    self.owner,
                    ui_messages.PREPARE_DONE_TITLE,
                    ui_messages.PREPARE_DONE_AUTO_SELECT.format(package=payload.foreground_package),
                )
            else:
                self.append_log(ui_messages.PREPARE_SELECT_APP_LOG)
                QMessageBox.information(
                    self.owner,
                    ui_messages.PREPARE_DONE_TITLE,
                    ui_messages.PREPARE_DONE_SELECT_APP,
                )
            self.append_log(ui_messages.PREPARE_DONE_LOG)
        else:
            self.set_status_text(ui_messages.PREPARE_NO_APPS_STATE)
            self.append_log(ui_messages.NO_APPS_FOUND_LOG)
            self._present_local_error(NoAppsFoundError(ui_messages.NO_APPS_FOUND_BODY))
            self.clear_workspace_display()

        self.refresh_app_status_panel()

    def apply_apps_payload_silent(
        self,
        apps: list[AppListItem],
        foreground_package: str | None = None,
    ) -> None:
        self.apply_apps_payload(
            AppsReadyPayload(apps=apps, foreground_package=foreground_package),
            show_ready_feedback=False,
        )

    def ensure_current_app_ready(self) -> str:
        package_name = self.selected_package_name()
        if not package_name:
            raise AppNotSelectedError(ui_messages.APP_NOT_SELECTED_BODY)

        current_app = self.deps.context.current_app
        active_session = self.deps.context.active_session
        if (
            current_app is not None
            and active_session is not None
            and current_app.identifier == package_name
            and current_app.pid is not None
        ):
            workspace_dir = self.deps.workspace_service.workspace_dir(current_app.identifier)
            self.widgets.workspace_path_input.setText(str(workspace_dir))
            self.widgets.workspace_path_input.setToolTip(str(workspace_dir))
            self.refresh_app_status_panel(current_app.identifier)
            return current_app.identifier

        app = self.deps.device_service.ensure_app_running(package_name)
        workspace_dir = self.deps.workspace_service.workspace_dir(app.identifier)
        self.widgets.workspace_path_input.setText(str(workspace_dir))
        self.widgets.workspace_path_input.setToolTip(str(workspace_dir))
        self.refresh_app_status_panel(app.identifier)
        return app.identifier
