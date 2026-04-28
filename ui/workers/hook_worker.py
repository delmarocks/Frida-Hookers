from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot


class HookWorker(QObject):
    # 负责在后台线程中切换 App、准备工作目录并发起注入。
    #
    # 它的职责非常单一：
    # 1. 确保目标 App 处于可调试状态
    # 2. 如有需要，准备工作目录
    # 3. 发起 attach 或 spawn
    # 真正的 Frida 会话仍然由 SessionService 持有，worker 只是触发启动动作。
    started = Signal(str, str, str)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        device_service: Any,
        session_service: Any,
        workspace_service: Any,
        package_name: str,
        script_path: Path,
        use_spawn: bool,
        ensure_workspace: bool,
    ) -> None:
        super().__init__()
        self.device_service = device_service
        self.session_service = session_service
        self.workspace_service = workspace_service
        self.package_name = package_name
        self.script_path = script_path
        self.use_spawn = use_spawn
        self.ensure_workspace_flag = ensure_workspace

    @Slot()
    def run(self) -> None:
        # 线程入口。
        #
        # 这里不会阻塞等待脚本结束；一旦 attach/spawn 成功，
        # 会话就转交给 SessionService 托管，然后 GUI 主线程仅负责显示状态和日志。
        try:
            if self.use_spawn:
                app = self.device_service.prepare_app_context(self.package_name)
            else:
                app = self.device_service.ensure_app_in_foreground(self.package_name)
            if self.ensure_workspace_flag:
                self.workspace_service.ensure_workspace(app)

            use_v8 = self.script_path.name == "just_trust_me.js"
            if self.use_spawn:
                self.session_service.spawn_script(str(self.script_path), use_v8=use_v8)
                mode = "spawn"
            else:
                self.session_service.attach_script(str(self.script_path), use_v8=use_v8)
                mode = "attach"

            self.started.emit(mode, self.package_name, self.script_path.name)
        except Exception as exc:
            # 如果启动过程中已经部分创建了会话，这里主动清理一下，
            # 避免 GUI 看起来失败了，但底层还挂着一个半残会话。
            try:
                self.session_service.stop_active_session()
            except Exception:
                pass
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()
