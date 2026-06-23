from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

adbutils_module = types.ModuleType("adbutils")
adbutils_module.adb = types.SimpleNamespace(device=lambda: None)
errors_module = types.ModuleType("adbutils.errors")
errors_module.AdbError = RuntimeError
sys.modules.setdefault("adbutils", adbutils_module)
sys.modules.setdefault("adbutils.errors", errors_module)

frida_module = types.ModuleType("frida")
frida_module.ServerNotRunningError = RuntimeError
frida_module.ProcessNotFoundError = RuntimeError
frida_module.TimedOutError = RuntimeError
frida_module.get_device = lambda *args, **kwargs: None
frida_module.get_usb_device = lambda *args, **kwargs: None
frida_module.get_device_manager = lambda: types.SimpleNamespace(
    add_remote_device=lambda address: None,
    remove_remote_device=lambda device: None,
)
sys.modules.setdefault("frida", frida_module)

from core.errors import (
    AttachStageError,
    CurrentAppMissingError,
    CurrentPidMissingError,
    FridaDeviceNotReadyError,
    ResumeStageError,
    ScriptFileMissingError,
    ScriptLoadStageError,
    SpawnStageError,
)
from core.session_service import SessionService
from core.workspace_service import WorkspaceService


class DummyDeviceService:
    def __init__(self) -> None:
        self.refreshed_pid: int | None = None
        self.adb_device = types.SimpleNamespace(
            prop=types.SimpleNamespace(get=lambda key: "14"),
        )

    def refresh_current_app_pid(self, package_name: str) -> int | None:
        return self.refreshed_pid


def build_session_service(workspace_context, sample_app_context) -> tuple[SessionService, DummyDeviceService]:
    workspace_context.hookers_js_dir.mkdir(parents=True, exist_ok=True)
    (workspace_context.hookers_js_dir / "_hook_js_warp.js").write_text("// warp", encoding="utf-8")
    workspace_context.current_app = sample_app_context
    device_service = DummyDeviceService()
    service = SessionService(
        workspace_context,
        device_service,
        WorkspaceService(workspace_context),
    )
    return service, device_service


def write_script(tmp_path: Path) -> Path:
    script_path = tmp_path / "sig.js"
    script_path.write_text("console.log('ok');", encoding="utf-8")
    return script_path


def test_frida_device_property_raises_structured_error(workspace_context, sample_app_context) -> None:
    service, _ = build_session_service(workspace_context, sample_app_context)
    workspace_context.frida_device = None

    with pytest.raises(FridaDeviceNotReadyError):
        _ = service.frida_device


def test_require_current_app_raises_structured_error(workspace_context, sample_app_context) -> None:
    service, _ = build_session_service(workspace_context, sample_app_context)
    workspace_context.current_app = None

    with pytest.raises(CurrentAppMissingError):
        service.require_current_app()


def test_require_current_pid_raises_structured_error(workspace_context, sample_app_context) -> None:
    service, _ = build_session_service(workspace_context, sample_app_context)
    workspace_context.current_app = sample_app_context
    workspace_context.current_app.pid = None

    with pytest.raises(CurrentPidMissingError):
        service.require_current_pid()


def test_load_script_code_raises_structured_error_for_missing_file(workspace_context, sample_app_context, tmp_path: Path) -> None:
    service, _ = build_session_service(workspace_context, sample_app_context)

    with pytest.raises(ScriptFileMissingError):
        service._load_script_code(tmp_path / "missing.js")


def test_attach_script_raises_attach_stage_error(workspace_context, sample_app_context, tmp_path: Path) -> None:
    service, device_service = build_session_service(workspace_context, sample_app_context)
    script_path = write_script(tmp_path)
    workspace_context.current_app.pid = 1234

    class FakeFridaDevice:
        def attach(self, pid: int):
            raise RuntimeError("attach boom")

    workspace_context.frida_device = FakeFridaDevice()
    device_service.refreshed_pid = None

    with pytest.raises(AttachStageError):
        service.attach_script(str(script_path))


def test_spawn_script_raises_spawn_stage_error(workspace_context, sample_app_context, tmp_path: Path) -> None:
    service, _ = build_session_service(workspace_context, sample_app_context)
    script_path = write_script(tmp_path)

    class FakeFridaDevice:
        def spawn(self, argv: list[str]) -> int:
            raise RuntimeError("spawn boom")

    workspace_context.frida_device = FakeFridaDevice()

    with pytest.raises(SpawnStageError):
        service.spawn_script(str(script_path))


def test_spawn_script_raises_script_load_stage_error(workspace_context, sample_app_context, tmp_path: Path) -> None:
    service, _ = build_session_service(workspace_context, sample_app_context)
    script_path = write_script(tmp_path)

    class FakeScript:
        def on(self, event: str, handler) -> None:
            return None

        def load(self) -> None:
            raise RuntimeError("load boom")

    class FakeSession:
        def create_script(self, source: str, runtime: str | None = None) -> FakeScript:
            return FakeScript()

        def detach(self) -> None:
            return None

    class FakeFridaDevice:
        def spawn(self, argv: list[str]) -> int:
            return 5678

        def attach(self, pid: int) -> FakeSession:
            return FakeSession()

        def resume(self, target) -> None:
            return None

    workspace_context.frida_device = FakeFridaDevice()

    with pytest.raises(ScriptLoadStageError):
        service.spawn_script(str(script_path))


def test_handle_script_auto_stop_message_emits_session_event(workspace_context, sample_app_context) -> None:
    service, _ = build_session_service(workspace_context, sample_app_context)
    received = []
    workspace_context.session_event_handler = lambda event_type, payload: received.append((event_type, payload))

    service.handle_script_message(
        {
            "type": "send",
            "payload": {
                "type": "auto_stop",
                "reason": "network-stack-window-finished",
                "message": "网络栈识别观察窗口结束，正在自动停止 Hook。",
            },
        },
        None,
    )

    assert received == [
        (
            "auto_stop_requested",
            {
                "reason": "network-stack-window-finished",
                "message": "网络栈识别观察窗口结束，正在自动停止 Hook。",
            },
        )
    ]


def test_handle_script_structured_log_message_formats_details(
    workspace_context, sample_app_context
) -> None:
    service, _ = build_session_service(workspace_context, sample_app_context)
    received = []
    workspace_context.log_handler = received.append

    service.handle_script_message(
        {
            "type": "send",
            "payload": {
                "type": "hookers_log",
                "level": "warn",
                "category": "dependency",
                "message": "radar.dex 未就绪，已跳过当前功能。",
                "details": {
                    "dexPath": "/data/local/tmp/radar.dex",
                    "hint": "请先点击“准备环境并刷新 App”。",
                },
            },
        },
        None,
    )

    assert len(received) == 1
    assert received[0].startswith("[JS:WARN] [dependency] radar.dex 未就绪，已跳过当前功能。")
    assert '"dexPath":"/data/local/tmp/radar.dex"' in received[0]
    assert "请先点击“准备环境并刷新 App”。" in received[0]


def test_handle_script_structured_log_message_keeps_load_error(
    workspace_context, sample_app_context
) -> None:
    service, _ = build_session_service(workspace_context, sample_app_context)
    received = []
    workspace_context.log_handler = received.append

    service.handle_script_message(
        {
            "type": "send",
            "payload": {
                "type": "hookers_log",
                "level": "error",
                "category": "dependency",
                "message": "radar.dex 未就绪，已跳过当前功能。",
                "details": {
                    "dexPath": "/data/local/tmp/radar.dex",
                    "missingClasses": ["gz.radar.AndroidUI"],
                    "loadError": "java.io.FileNotFoundException",
                },
            },
        },
        None,
    )

    assert len(received) == 1
    assert received[0].startswith("[JS:ERROR] [dependency] radar.dex 未就绪，已跳过当前功能。")
    assert '"missingClasses":["gz.radar.AndroidUI"]' in received[0]
    assert '"loadError":"java.io.FileNotFoundException"' in received[0]


def test_handle_script_structured_log_message_supports_string_details(
    workspace_context, sample_app_context
) -> None:
    service, _ = build_session_service(workspace_context, sample_app_context)
    received = []
    workspace_context.log_handler = received.append

    service.handle_script_message(
        {
            "type": "send",
            "payload": {
                "type": "hookers_log",
                "level": "log",
                "category": "url-trace",
                "message": "捕获到 URL",
                "details": "https://example.com/api/v1/demo",
            },
        },
        None,
    )

    assert received == [
        "[JS] [url-trace] 捕获到 URL\nhttps://example.com/api/v1/demo"
    ]


def test_load_script_code_injects_hookers_bridge(workspace_context, sample_app_context, tmp_path: Path) -> None:
    service, _ = build_session_service(workspace_context, sample_app_context)
    script_path = write_script(tmp_path)

    source = service._load_script_code(script_path)

    assert "global.Hookers" in source
    assert 'type: "hookers_log"' in source
    assert 'type: "console"' in source


def test_stop_active_session_prefers_cleanup_then_detach(workspace_context, sample_app_context) -> None:
    service, _ = build_session_service(workspace_context, sample_app_context)
    calls = []

    class FakeExportsSync:
        def cleanup(self) -> None:
            calls.append("cleanup")

    class FakeScript:
        exports_sync = FakeExportsSync()

        def unload(self) -> None:
            calls.append("unload")

    class FakeSession:
        def detach(self) -> None:
            calls.append("detach")

    workspace_context.active_session = types.SimpleNamespace(
        script=FakeScript(),
        session=FakeSession(),
    )

    service.stop_active_session()

    assert workspace_context.active_session is None
    assert calls == ["cleanup", "detach"]


def test_spawn_script_restores_previous_pid_when_resume_stage_fails(
    workspace_context, sample_app_context, tmp_path: Path
) -> None:
    service, device_service = build_session_service(workspace_context, sample_app_context)
    script_path = write_script(tmp_path)
    previous_pid = 4321
    workspace_context.current_app.pid = previous_pid

    class FakeScript:
        def on(self, event: str, handler) -> None:
            return None

        def load(self) -> None:
            return None

    class FakeSession:
        def create_script(self, source: str, runtime: str | None = None) -> FakeScript:
            return FakeScript()

        def detach(self) -> None:
            return None

    class FakeFridaDevice:
        def spawn(self, argv: list[str]) -> int:
            return 5678

        def attach(self, pid: int) -> FakeSession:
            return FakeSession()

        def resume(self, target) -> None:
            raise RuntimeError("resume boom")

    workspace_context.frida_device = FakeFridaDevice()
    device_service.adb_device.prop = {"ro.build.version.release": "13"}

    with pytest.raises(ResumeStageError):
        service.spawn_script(str(script_path))

    assert workspace_context.current_app.pid == previous_pid
