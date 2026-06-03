from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget
from core.models import AppContext, HookerContext


@dataclass
class DummyAppInfo:
    name: str
    identifier: str
    pid: int | None = None
    uid: int | None = None
    version: str | None = None


@dataclass
class DummyActiveSession:
    mode: str


@dataclass
class DummyContext:
    project_root: Path = field(default_factory=lambda: Path.cwd())
    js_dir: Path = field(default_factory=lambda: Path.cwd() / "js")
    hookers_js_dir: Path = field(default_factory=lambda: Path.cwd() / "hookers" / "js")
    frida_server_arm64: str = "rusda-server-16.2.1-android-arm64"
    local_apk_check_pack_exe: Path = field(
        default_factory=lambda: Path.cwd() / "mobile-deploy" / "ApkCheckPack.exe"
    )
    last_connected_device_serial: str | None = None
    last_prepare_frida_server_status: str | None = None
    last_workspace_prepare_mode: str | None = None
    last_workspace_apk_status: str | None = None
    apps: list[DummyAppInfo] = field(default_factory=list)
    current_app: DummyAppInfo | None = None
    active_session: DummyActiveSession | None = None
    log_handler: object | None = None
    session_event_handler: object | None = None
    emitted: list[str] = field(default_factory=list)

    def emit(self, message: str) -> None:
        self.emitted.append(message)


class DummyDeviceService:
    def __init__(self) -> None:
        self.ensure_result = DummyAppInfo("App", "pkg.default", pid=1234, uid=2000, version="1.0")
        self.refresh_result = [self.ensure_result]
        self.stop_calls = 0

    def ensure_app_running(self, package_name: str) -> DummyAppInfo:
        if self.ensure_result.identifier != package_name:
            self.ensure_result = DummyAppInfo("App", package_name, pid=1234, uid=2000, version="1.0")
        return self.ensure_result

    def refresh_applications(self) -> list[DummyAppInfo]:
        return self.refresh_result

    def stop_frida_server(self) -> None:
        self.stop_calls += 1


class DummySessionService:
    def __init__(self) -> None:
        self.stop_calls = 0
        self.restart_calls = 0
        self.attach_calls: list[tuple[str, bool]] = []
        self.spawn_calls: list[tuple[str, bool]] = []

    def stop_active_session(self) -> None:
        self.stop_calls += 1

    def restart_current_app(self) -> None:
        self.restart_calls += 1

    def attach_script(self, script_name_or_path: str, use_v8: bool = False) -> None:
        self.attach_calls.append((script_name_or_path, use_v8))

    def spawn_script(self, script_name_or_path: str, use_v8: bool = False) -> None:
        self.spawn_calls.append((script_name_or_path, use_v8))


class DummyWorkspaceService:
    def __init__(self) -> None:
        self.names_by_package: dict[str, list[str]] = {}

    def workspace_dir(self, package_name: str) -> Path:
        return Path.cwd() / "workspaces" / package_name

    def script_dir(self, package_name: str) -> Path:
        return Path.cwd() / "workspaces" / package_name / "js"

    def list_scripts(self, package_name: str) -> list[Path]:
        return [self.script_dir(package_name) / name for name in self.script_names(package_name)]

    def script_names(self, package_name: str) -> list[str]:
        return list(self.names_by_package.get(package_name, []))

    def materialize_multi_script_bundle(
        self,
        package_name: str,
        script_paths: list[str | Path],
        *,
        output_name: str = "frida_multi_bundle.runtime.js",
    ) -> Path:
        target = self.script_dir(package_name) / output_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(str(path) for path in script_paths), encoding="utf-8")
        return target


class DummyRpcService:
    def __init__(self) -> None:
        self.invalidations = 0

    def invalidate_persistent_session(self) -> None:
        self.invalidations += 1

    def generate_hook_script(self, hook_target: str) -> Path:
        return Path.cwd() / "workspaces" / "pkg.default" / "js" / f"{hook_target}.js"

    def activitys(self) -> object:
        return ["A", "B"]

    def services(self) -> object:
        return ["S"]

    def object_info(self, target: str) -> object:
        return {"target": target}

    def object_to_explain(self, target: str) -> object:
        return {"explain": target}

    def view_info(self, target: str) -> object:
        return {"view": target}


class DummyApkScanService:
    def __init__(self) -> None:
        self.result = {"stdout": "ok", "stderr": "", "returncode": 0}

    def scan_apk(self, apk_path: Path) -> dict[str, object]:
        return self.result


@dataclass
class DummyDeps:
    device_service: DummyDeviceService = field(default_factory=DummyDeviceService)
    session_service: DummySessionService = field(default_factory=DummySessionService)
    workspace_service: DummyWorkspaceService = field(default_factory=DummyWorkspaceService)
    rpc_service: DummyRpcService = field(default_factory=DummyRpcService)
    apk_scan_service: DummyApkScanService = field(default_factory=DummyApkScanService)
    context: DummyContext = field(default_factory=DummyContext)


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def owner_widget(qapp: QApplication) -> QWidget:
    widget = QWidget()
    yield widget
    widget.deleteLater()


@pytest.fixture
def dummy_deps() -> DummyDeps:
    return DummyDeps()


@pytest.fixture
def workspace_context(tmp_path: Path) -> HookerContext:
    context = HookerContext.from_project_root(tmp_path)
    context.js_dir.mkdir(parents=True, exist_ok=True)
    context.hookers_js_dir.mkdir(parents=True, exist_ok=True)
    context.workspaces_dir.mkdir(parents=True, exist_ok=True)
    return context


@pytest.fixture
def sample_app_context() -> AppContext:
    return AppContext(
        identifier="com.example.demo",
        name="Demo App",
        pid=1234,
        version="1.2.3",
        install_path="/data/app/demo",
        install_apk_filename="base.apk",
        uid=10086,
    )
