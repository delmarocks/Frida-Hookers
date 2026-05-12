from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication

from core.apk_scan_service import ApkScanService
from core.device_service import DeviceService
from core.models import HookerContext
from core.rpc_service import RpcService
from core.session_service import SessionService
from core.workspace_service import WorkspaceService
from ui.main_window import MainWindow, MainWindowDependencies


def build_main_window(project_root: Path) -> MainWindow:
    # GUI 入口的装配函数。
    # 这里负责把 context 和各个 service 组装起来，再统一注入主窗口。
    context = HookerContext.from_project_root(project_root)
    device_service = DeviceService(context)
    workspace_service = WorkspaceService(context)
    session_service = SessionService(context, device_service, workspace_service)
    rpc_service = RpcService(context, session_service, workspace_service)
    apk_scan_service = ApkScanService(context)
    rpc_service.enable_persistent_session()

    deps = MainWindowDependencies(
        device_service=device_service,
        session_service=session_service,
        workspace_service=workspace_service,
        rpc_service=rpc_service,
        apk_scan_service=apk_scan_service,
        context=context,
    )
    return MainWindow(deps)


def main() -> int:
    # Qt 程序入口。
    # 如果外部已经创建过 QApplication，就复用它；否则新建一个。
    app = QApplication.instance() or QApplication([])
    window = build_main_window(Path(__file__).resolve().parent)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
