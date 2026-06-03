from __future__ import annotations

import importlib
import os
import sys
import types


class _FakeStream:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def reconfigure(self, **kwargs: str) -> None:
        self.calls.append(kwargs)


class _FakeKernel32:
    def __init__(self) -> None:
        self.output_cp: list[int] = []
        self.input_cp: list[int] = []

    def SetConsoleOutputCP(self, value: int) -> None:
        self.output_cp.append(value)

    def SetConsoleCP(self, value: int) -> None:
        self.input_cp.append(value)


def _load_hookers_module(monkeypatch):
    sys.modules.pop("hookers", None)

    prompt_toolkit_module = types.ModuleType("prompt_toolkit")
    prompt_toolkit_module.PromptSession = object
    completion_module = types.ModuleType("prompt_toolkit.completion")
    completion_module.NestedCompleter = object
    completion_module.WordCompleter = object
    patch_stdout_module = types.ModuleType("prompt_toolkit.patch_stdout")
    patch_stdout_module.patch_stdout = lambda: None
    wcwidth_module = types.ModuleType("wcwidth")
    wcwidth_module.wcswidth = len

    rpc_service_module = types.ModuleType("core.rpc_service")
    rpc_service_module.RpcService = object
    session_service_module = types.ModuleType("core.session_service")
    session_service_module.SessionService = object
    workspace_service_module = types.ModuleType("core.workspace_service")
    workspace_service_module.WorkspaceService = object
    device_service_module = types.ModuleType("core.device_service")
    device_service_module.DeviceService = object
    models_module = types.ModuleType("core.models")
    models_module.HookerContext = object

    monkeypatch.setitem(sys.modules, "prompt_toolkit", prompt_toolkit_module)
    monkeypatch.setitem(sys.modules, "prompt_toolkit.completion", completion_module)
    monkeypatch.setitem(sys.modules, "prompt_toolkit.patch_stdout", patch_stdout_module)
    monkeypatch.setitem(sys.modules, "wcwidth", wcwidth_module)
    monkeypatch.setitem(sys.modules, "core.rpc_service", rpc_service_module)
    monkeypatch.setitem(sys.modules, "core.session_service", session_service_module)
    monkeypatch.setitem(sys.modules, "core.workspace_service", workspace_service_module)
    monkeypatch.setitem(sys.modules, "core.device_service", device_service_module)
    monkeypatch.setitem(sys.modules, "core.models", models_module)

    return importlib.import_module("hookers")


def test_configure_windows_console_utf8_is_noop_on_non_windows(monkeypatch) -> None:
    hookers = _load_hookers_module(monkeypatch)
    monkeypatch.setattr(hookers.sys, "platform", "linux")
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    monkeypatch.delenv("PYTHONUTF8", raising=False)

    hookers._configure_windows_console_utf8()

    assert "PYTHONIOENCODING" not in os.environ
    assert "PYTHONUTF8" not in os.environ


def test_configure_windows_console_utf8_sets_env_codepage_and_streams(monkeypatch) -> None:
    hookers = _load_hookers_module(monkeypatch)
    kernel32 = _FakeKernel32()
    stdin = _FakeStream()
    stdout = _FakeStream()
    stderr = _FakeStream()

    monkeypatch.setattr(hookers.sys, "platform", "win32")
    monkeypatch.setattr(hookers.ctypes, "windll", types.SimpleNamespace(kernel32=kernel32))
    monkeypatch.setattr(hookers.sys, "stdin", stdin)
    monkeypatch.setattr(hookers.sys, "stdout", stdout)
    monkeypatch.setattr(hookers.sys, "stderr", stderr)
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    monkeypatch.delenv("PYTHONUTF8", raising=False)

    hookers._configure_windows_console_utf8()

    assert os.environ["PYTHONIOENCODING"] == "utf-8"
    assert os.environ["PYTHONUTF8"] == "1"
    assert kernel32.output_cp == [65001]
    assert kernel32.input_cp == [65001]
    assert stdin.calls == [{"encoding": "utf-8", "errors": "replace"}]
    assert stdout.calls == [{"encoding": "utf-8", "errors": "replace"}]
    assert stderr.calls == [{"encoding": "utf-8", "errors": "replace"}]
