from __future__ import annotations

import sys
import types

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

jsbeautifier_module = types.ModuleType("jsbeautifier")
jsbeautifier_module.beautify = lambda text: text
sys.modules.setdefault("jsbeautifier", jsbeautifier_module)

from core.rpc_service import RpcService
from core.session_service import SessionService
from core.workspace_service import WorkspaceService


class _FakeExports:
    def __init__(self, methods: dict[str, object] | None = None, calls: list[str] | None = None) -> None:
        self._methods = methods or {}
        self._calls = calls if calls is not None else []

    def cleanup(self) -> None:
        self._calls.append("cleanup")

    def __getattr__(self, item: str):
        if item in self._methods:
            return self._methods[item]
        raise AttributeError(item)


class _FakeScript:
    def __init__(self, exports_sync: _FakeExports, calls: list[str]) -> None:
        self.exports_sync = exports_sync
        self._calls = calls
        self.loaded = False
        self.message_handlers: list[tuple[str, object]] = []

    def on(self, event: str, handler) -> None:
        self.message_handlers.append((event, handler))

    def load(self) -> None:
        self.loaded = True
        self._calls.append("load")

    def unload(self) -> None:
        self._calls.append("unload")


class _FakeSession:
    def __init__(self, script: _FakeScript, calls: list[str]) -> None:
        self._script = script
        self._calls = calls

    def create_script(self, source: str, runtime: str | None = None):
        self._calls.append(f"create_script:{runtime or 'default'}")
        return self._script

    def detach(self) -> None:
        self._calls.append("detach")


class _FakeFridaDevice:
    def __init__(self, session_factory, calls: list[str]) -> None:
        self._session_factory = session_factory
        self._calls = calls

    def attach(self, pid: int):
        self._calls.append(f"attach:{pid}")
        return self._session_factory()


def _build_service(workspace_context, sample_app_context, *, methods: dict[str, object] | None = None):
    workspace_context.current_app = sample_app_context
    workspace_context.hookers_js_dir.mkdir(parents=True, exist_ok=True)
    (workspace_context.hookers_js_dir / "rpc.js").write_text("// rpc", encoding="utf-8")
    (workspace_context.hookers_js_dir / "_hook_js_warp.js").write_text("// warp", encoding="utf-8")

    calls: list[str] = []
    exports = _FakeExports(methods=methods, calls=calls)
    script = _FakeScript(exports_sync=exports, calls=calls)

    def make_session():
        return _FakeSession(script=script, calls=calls)

    device = _FakeFridaDevice(make_session, calls)
    workspace_context.frida_device = device

    class DummyDeviceService:
        adb_device = types.SimpleNamespace(prop=types.SimpleNamespace(get=lambda key: "14"))

    session_service = SessionService(
        workspace_context,
        DummyDeviceService(),
        WorkspaceService(workspace_context),
    )
    workspace_service = WorkspaceService(workspace_context)
    service = RpcService(workspace_context, session_service, workspace_service)
    return service, calls, script


def test_rpc_call_short_lived_session_cleans_up_on_success(workspace_context, sample_app_context) -> None:
    method_calls = []

    def activitys():
        method_calls.append("activitys")
        return ["A"]

    service, calls, _script = _build_service(
        workspace_context,
        sample_app_context,
        methods={"activitys": activitys},
    )

    result = service.call("activitys")

    assert result == ["A"]
    assert method_calls == ["activitys"]
    assert calls == [
        "attach:1234",
        "create_script:default",
        "load",
        "cleanup",
        "unload",
        "detach",
    ]


def test_rpc_call_short_lived_session_cleans_up_on_method_failure(workspace_context, sample_app_context) -> None:
    def boom():
        raise RuntimeError("rpc boom")

    service, calls, _script = _build_service(
        workspace_context,
        sample_app_context,
        methods={"activitys": boom},
    )

    with pytest.raises(RuntimeError, match="rpc boom"):
        service.call("activitys")

    assert calls == [
        "attach:1234",
        "create_script:default",
        "load",
        "cleanup",
        "unload",
        "detach",
    ]


def test_rpc_persistent_session_reuses_same_resources_for_same_pid_and_runtime(
    workspace_context, sample_app_context
) -> None:
    method_calls = []

    def activitys():
        method_calls.append("activitys")
        return ["A"]

    service, calls, _script = _build_service(
        workspace_context,
        sample_app_context,
        methods={"activitys": activitys},
    )
    service.enable_persistent_session()

    first = service.call("activitys")
    second = service.call("activitys")

    assert first == ["A"]
    assert second == ["A"]
    assert method_calls == ["activitys", "activitys"]
    assert calls == [
        "attach:1234",
        "create_script:default",
        "load",
    ]


def test_rpc_persistent_session_invalidates_and_rebuilds_when_pid_changes(
    workspace_context, sample_app_context
) -> None:
    service, calls, _script = _build_service(
        workspace_context,
        sample_app_context,
        methods={"activitys": lambda: ["A"]},
    )
    service.enable_persistent_session()

    assert service.call("activitys") == ["A"]
    workspace_context.current_app.pid = 4321
    assert service.call("activitys") == ["A"]

    assert calls == [
        "attach:1234",
        "create_script:default",
        "load",
        "cleanup",
        "unload",
        "detach",
        "attach:4321",
        "create_script:default",
        "load",
    ]


def test_rpc_persistent_session_invalidates_when_runtime_changes(workspace_context, sample_app_context) -> None:
    service, calls, _script = _build_service(
        workspace_context,
        sample_app_context,
        methods={"activitys": lambda: ["A"]},
    )
    service.enable_persistent_session()

    assert service.call("activitys", use_v8=False) == ["A"]
    assert service.call("activitys", use_v8=True) == ["A"]

    assert calls == [
        "attach:1234",
        "create_script:default",
        "load",
        "cleanup",
        "unload",
        "detach",
        "attach:1234",
        "create_script:v8",
        "load",
    ]


def test_rpc_persistent_session_failure_invalidates_old_resources(workspace_context, sample_app_context) -> None:
    def boom():
        raise RuntimeError("rpc boom")

    service, calls, _script = _build_service(
        workspace_context,
        sample_app_context,
        methods={"activitys": boom},
    )
    service.enable_persistent_session()

    with pytest.raises(RuntimeError, match="rpc boom"):
        service.call("activitys")

    assert service._persistent_session is None
    assert service._persistent_script is None
    assert calls == [
        "attach:1234",
        "create_script:default",
        "load",
        "cleanup",
        "unload",
        "detach",
    ]
