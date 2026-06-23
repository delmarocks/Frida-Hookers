from __future__ import annotations

import json
from dataclasses import dataclass

from PySide6.QtCore import QThread, Qt
from PySide6.QtWidgets import QDialog, QLineEdit, QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget, QComboBox

from core.errors import HookersError, RpcCallError, RpcTargetMissingError, to_ui_error_payload

from .controller_types import (
    BusySetter,
    EnsureCurrentAppReady,
    ErrorPresenter,
    GeneratedHookScriptPayload,
    GuiDepsLike,
    LogAppender,
    RpcResultPayload,
    ScriptRootApplier,
    StatusSetter,
    WorkerAction,
    WorkerSuccessHandler,
)
from .workers.action_worker import ActionWorker
from .ui_thread_dispatcher import UiThreadDispatcher
from . import ui_messages


@dataclass
class RpcToolWidgets:
    hook_target_input: QLineEdit
    inspect_target_input: QLineEdit
    script_combo: QComboBox


class RpcToolController:
    def __init__(
        self,
        owner: QWidget,
        widgets: RpcToolWidgets,
        deps: GuiDepsLike,
        *,
        set_busy: BusySetter,
        set_status_text: StatusSetter,
        append_log: LogAppender,
        show_worker_error: ErrorPresenter,
        ensure_current_app_ready: EnsureCurrentAppReady,
        apply_script_root: ScriptRootApplier,
    ) -> None:
        self.owner = owner
        self.widgets = widgets
        self.deps = deps
        self.set_busy = set_busy
        self.set_status_text = set_status_text
        self.append_log = append_log
        self.show_worker_error = show_worker_error
        self.ensure_current_app_ready = ensure_current_app_ready
        self.apply_script_root = apply_script_root

        self.result_windows: list[QDialog] = []
        self.rpc_action_thread: QThread | None = None
        self.rpc_action_worker: ActionWorker | None = None
        self.ui_dispatcher = UiThreadDispatcher(owner)

    def start_rpc_action(
        self,
        *,
        busy_message: str,
        action: WorkerAction,
        on_success: WorkerSuccessHandler,
    ) -> None:
        if self.rpc_action_thread is not None:
            self.show_worker_error(
                to_ui_error_payload(
                    HookersError(
                        ui_messages.RPC_ACTION_BUSY_BODY,
                        severity="warning",
                        next_step=ui_messages.RPC_ACTION_BUSY_NEXT_STEP,
                    )
                )
            )
            return

        self.set_busy(True, busy_message)
        self.rpc_action_thread = QThread(self.owner)
        self.rpc_action_worker = ActionWorker(action)
        self.rpc_action_worker.moveToThread(self.rpc_action_thread)

        self.rpc_action_thread.started.connect(self.rpc_action_worker.run)
        self.rpc_action_worker.succeeded.connect(
            lambda payload: self.ui_dispatcher.submit(on_success, payload)
        )
        self.rpc_action_worker.failed.connect(
            lambda error: self.ui_dispatcher.submit(self.show_worker_error, error)
        )
        self.rpc_action_worker.finished.connect(self.rpc_action_thread.quit)
        self.rpc_action_worker.finished.connect(self.rpc_action_worker.deleteLater)
        self.rpc_action_thread.finished.connect(self.rpc_action_thread.deleteLater)
        self.rpc_action_thread.finished.connect(self._clear_rpc_action_thread)
        self.rpc_action_thread.start()

    def _clear_rpc_action_thread(self) -> None:
        self.rpc_action_thread = None
        self.rpc_action_worker = None

    def format_result_text(self, result: object) -> str:
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

    def show_result_dialog(self, title: str, content: str) -> None:
        dialog = QDialog(self.owner)
        dialog.setWindowTitle(title)
        dialog.resize(860, 620)
        dialog.setModal(False)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        content_view = QTextEdit(dialog)
        content_view.setReadOnly(True)
        content_view.setPlainText(content)
        layout.addWidget(content_view, 1)

        close_button = QPushButton(ui_messages.RESULT_DIALOG_CLOSE_TEXT)
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)

        self.result_windows.append(dialog)
        dialog.destroyed.connect(lambda _=None, win=dialog: self._forget_result_window(win))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _forget_result_window(self, dialog: QDialog) -> None:
        self.result_windows = [window for window in self.result_windows if window is not dialog]

    def inspect_target(self) -> str:
        target = self.widgets.inspect_target_input.text().strip()
        if not target:
            raise RpcTargetMissingError(ui_messages.INSPECT_TARGET_BODY)
        return target

    def generate_hook_script(self) -> None:
        hook_target = self.widgets.hook_target_input.text().strip()
        if not hook_target:
            self.show_worker_error(
                to_ui_error_payload(RpcTargetMissingError(ui_messages.MISSING_HOOK_TARGET_BODY))
            )
            return

        def action() -> GeneratedHookScriptPayload:
            try:
                package_name = self.ensure_current_app_ready()
                script_path = self.deps.rpc_service.generate_hook_script(hook_target)
                return GeneratedHookScriptPayload(package_name=package_name, script_path=script_path)
            except HookersError:
                raise
            except Exception as exc:
                raise RpcCallError(
                    ui_messages.HOOK_SCRIPT_GENERATE_FAILED_BODY,
                    hint=ui_messages.HOOK_SCRIPT_GENERATE_FAILED_HINT,
                ) from exc

        self.start_rpc_action(
            busy_message=ui_messages.GENERATING_HOOK_SCRIPT,
            action=action,
            on_success=self.on_hook_script_generated,
        )

    def on_hook_script_generated(self, payload: GeneratedHookScriptPayload) -> None:
        package_name = payload.package_name
        script_path = payload.script_path
        self.append_log(
            ui_messages.HOOK_SCRIPT_GENERATED_LOG.format(path=script_path)
        )
        self.apply_script_root(self.deps.workspace_service.script_dir(package_name))

        target_resolved = str(script_path.resolve())
        for index in range(self.widgets.script_combo.count()):
            if self.widgets.script_combo.itemData(index) == target_resolved:
                self.widgets.script_combo.setCurrentIndex(index)
                break

        self.set_busy(False, ui_messages.READY)
        self.set_status_text(
            ui_messages.READY,
            ui_messages.HOOK_SCRIPT_GENERATED_STATUS.format(name=script_path.name),
        )
        QMessageBox.information(
            self.owner,
            ui_messages.GENERATED_TITLE,
            ui_messages.generated_script_body(script_path),
        )

    def show_activities(self) -> None:
        def action() -> RpcResultPayload:
            try:
                package_name = self.ensure_current_app_ready()
                result = self.deps.rpc_service.activitys()
                return RpcResultPayload(package_name=package_name, result=result)
            except HookersError:
                raise
            except Exception as exc:
                raise RpcCallError("加载 Activity 列表失败。") from exc

        self.start_rpc_action(
            busy_message=ui_messages.LOADING_ACTIVITIES,
            action=action,
            on_success=self.on_activities_ready,
        )

    def on_activities_ready(self, payload: RpcResultPayload) -> None:
        package_name = payload.package_name
        self.append_log(
            ui_messages.LOADED_ACTIVITIES_LOG.format(package=package_name)
        )
        self.show_result_dialog(
            ui_messages.ACTIVITY_LIST_TITLE,
            self.format_result_text(payload.result),
        )
        self.set_busy(False, ui_messages.READY)

    def show_services(self) -> None:
        def action() -> RpcResultPayload:
            try:
                package_name = self.ensure_current_app_ready()
                result = self.deps.rpc_service.services()
                return RpcResultPayload(package_name=package_name, result=result)
            except HookersError:
                raise
            except Exception as exc:
                raise RpcCallError("加载 Service 列表失败。") from exc

        self.start_rpc_action(
            busy_message=ui_messages.LOADING_SERVICES,
            action=action,
            on_success=self.on_services_ready,
        )

    def on_services_ready(self, payload: RpcResultPayload) -> None:
        package_name = payload.package_name
        self.append_log(
            ui_messages.LOADED_SERVICES_LOG.format(package=package_name)
        )
        self.show_result_dialog(
            ui_messages.SERVICE_LIST_TITLE,
            self.format_result_text(payload.result),
        )
        self.set_busy(False, ui_messages.READY)

    def show_object_info(self) -> None:
        def action() -> RpcResultPayload:
            try:
                package_name = self.ensure_current_app_ready()
                target = self.inspect_target()
                result = self.deps.rpc_service.object_info(target)
                return RpcResultPayload(package_name=package_name, target=target, result=result)
            except HookersError:
                raise
            except Exception as exc:
                raise RpcCallError("加载对象信息失败。") from exc

        self.start_rpc_action(
            busy_message=ui_messages.LOADING_OBJECT_INFO,
            action=action,
            on_success=self.on_object_info_ready,
        )

    def on_object_info_ready(self, payload: RpcResultPayload) -> None:
        package_name = payload.package_name
        target = payload.target or ""
        self.append_log(
            ui_messages.LOADED_OBJECT_INFO_LOG.format(
                package=package_name,
                target=target,
            )
        )
        self.show_result_dialog(
            ui_messages.object_info_title(target),
            self.format_result_text(payload.result),
        )
        self.set_busy(False, ui_messages.READY)

    def show_object_explain(self) -> None:
        def action() -> RpcResultPayload:
            try:
                package_name = self.ensure_current_app_ready()
                target = self.inspect_target()
                result = self.deps.rpc_service.object_to_explain(target)
                return RpcResultPayload(package_name=package_name, target=target, result=result)
            except HookersError:
                raise
            except Exception as exc:
                raise RpcCallError("解释对象失败。") from exc

        self.start_rpc_action(
            busy_message=ui_messages.EXPLAINING_OBJECT,
            action=action,
            on_success=self.on_object_explain_ready,
        )

    def on_object_explain_ready(self, payload: RpcResultPayload) -> None:
        package_name = payload.package_name
        target = payload.target or ""
        self.append_log(
            ui_messages.EXPLAINED_OBJECT_LOG.format(
                package=package_name,
                target=target,
            )
        )
        self.show_result_dialog(
            ui_messages.object_explain_title(target),
            self.format_result_text(payload.result),
        )
        self.set_busy(False, ui_messages.READY)

    def show_view_info(self) -> None:
        def action() -> RpcResultPayload:
            try:
                package_name = self.ensure_current_app_ready()
                target = self.inspect_target()
                result = self.deps.rpc_service.view_info(target)
                return RpcResultPayload(package_name=package_name, target=target, result=result)
            except HookersError:
                raise
            except Exception as exc:
                raise RpcCallError("加载 View 信息失败。") from exc

        self.start_rpc_action(
            busy_message=ui_messages.LOADING_VIEW_INFO,
            action=action,
            on_success=self.on_view_info_ready,
        )

    def on_view_info_ready(self, payload: RpcResultPayload) -> None:
        package_name = payload.package_name
        target = payload.target or ""
        self.append_log(
            ui_messages.LOADED_VIEW_INFO_LOG.format(
                package=package_name,
                target=target,
            )
        )
        self.show_result_dialog(
            ui_messages.view_info_title(target),
            self.format_result_text(payload.result),
        )
        self.set_busy(False, ui_messages.READY)
