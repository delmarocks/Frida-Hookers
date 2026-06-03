from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Signal, Slot
from core.errors import to_ui_error_payload


class DeviceWorker(QObject):
    # 负责在后台线程中准备设备环境并刷新应用列表。
    #
    # 为什么要把这部分逻辑放进 worker：
    # 1. 连接 ADB 设备可能阻塞
    # 2. 启动 frida-server 可能阻塞
    # 3. 枚举应用列表也可能比较慢
    # 如果直接在主线程执行，GUI 会卡住，窗口会表现成“未响应”。
    apps_ready = Signal(list, object)
    failed = Signal(object)
    finished = Signal()

    def __init__(self, device_service: Any) -> None:
        super().__init__()
        self.device_service = device_service

    @Slot()
    def run(self) -> None:
        # 这个方法会在线程启动后执行。
        #
        # 执行顺序和 CLI 的 bootstrap 基本一致：
        # 1. connect()
        # 2. start_frida_server()
        # 3. deploy_radar_dex()
        # 4. refresh_applications()
        #
        # 最后把结果转成适合 GUI 展示的简单字典列表，通过信号回传给主线程。
        try:
            context = getattr(self.device_service, "context", None)
            if context is not None:
                context.last_connected_device_serial = None
                context.last_prepare_frida_server_status = None
            self.device_service.connect()
            self.device_service.start_frida_server()
            self.device_service.deploy_radar_dex()
            apps = self.device_service.refresh_applications()
            payload = [
                {
                    "name": app.name,
                    "identifier": app.identifier,
                    "pid": app.pid,
                }
                for app in apps
            ]
            foreground_package = self.device_service.get_foreground_package()
            self.apps_ready.emit(payload, foreground_package)
        except Exception as exc:
            self.failed.emit(to_ui_error_payload(exc))
        finally:
            # 无论成功失败，都要通知线程可以收尾。
            self.finished.emit()
