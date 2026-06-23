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

from core.device_service import DeviceService
from core.errors import AppNotRunningError, DeviceError, FridaServerStartError, FridaServerStopError
from core.models import AppContext


def test_get_forwarded_frida_device_removes_remote_device_after_probe_failure(
    workspace_context,
) -> None:
    service = DeviceService(workspace_context)
    workspace_context.adb_device = types.SimpleNamespace(serial="device-1")

    forwarded = []
    removed = []

    class FakeRemoteDevice:
        def enumerate_processes(self):
            raise RuntimeError("probe boom")

    fake_manager = types.SimpleNamespace(
        add_remote_device=lambda address: forwarded.append(address) or FakeRemoteDevice(),
        remove_remote_device=lambda device: removed.append(device),
    )
    original_get_manager = frida_module.get_device_manager
    frida_module.get_device_manager = lambda: fake_manager
    service._ensure_adb_forward = lambda local_port, remote_port: forwarded.append(
        f"forward:{local_port}->{remote_port}"
    )

    try:
        with pytest.raises(RuntimeError, match="probe boom"):
            service._get_forwarded_frida_device(remote_port=27042, local_port=27052)
    finally:
        frida_module.get_device_manager = original_get_manager

    assert forwarded == ["forward:27052->27042", "127.0.0.1:27052"]
    assert len(removed) == 1


def test_stop_remote_frida_processes_returns_true_after_killing_running_server(
    workspace_context,
) -> None:
    service = DeviceService(workspace_context)
    workspace_context.adb_device = types.SimpleNamespace(serial="device-1")
    service.is_root = lambda: True
    service.get_remote_server_pid = lambda name: "4321"
    commands = []
    service.run_root_cmd = lambda cmd: commands.append(cmd) or ""

    assert service.stop_remote_frida_processes() is True
    assert commands == ["kill -9 4321"]


def test_cleanup_remote_frida_files_skips_without_root_and_logs_reason(
    workspace_context,
) -> None:
    service = DeviceService(workspace_context)
    workspace_context.adb_device = types.SimpleNamespace(serial="device-1")
    service.is_root = lambda: False
    messages = []
    workspace_context.emit = messages.append

    service.cleanup_remote_frida_files()

    assert messages == ["设备没有被 root，跳过远端 Frida 清理"]


def test_start_frida_server_reuses_existing_ready_server_without_restart(
    workspace_context,
) -> None:
    service = DeviceService(workspace_context)
    workspace_context.mobile_deploy_dir.mkdir(parents=True, exist_ok=True)
    local_binary = workspace_context.mobile_deploy_dir / workspace_context.frida_server_arm64
    local_binary.write_text("server", encoding="utf-8")

    service.is_root = lambda: True
    service.get_cpu_arch = lambda: "arm64"
    service.get_remote_server_pid = lambda name: "4321"
    service.remote_file_exists = lambda path: True
    service.is_frida_environment_ready = lambda: True

    side_effects = []
    service.remote_dir_exists = lambda path: side_effects.append(f"remote_dir:{path}") or True
    service.stop_remote_frida_processes = lambda: side_effects.append("stop")
    service.push_file_to_remote = lambda local_path, remote_path: side_effects.append("push")
    service.run_root_cmd = lambda cmd, read_output=True: side_effects.append(cmd) or ""

    service.start_frida_server()

    assert workspace_context.last_prepare_frida_server_status == "reused"
    assert side_effects == []


def test_start_frida_server_reports_pid_ports_and_log_when_probe_never_recovers(
    workspace_context, monkeypatch
) -> None:
    service = DeviceService(workspace_context)
    workspace_context.mobile_deploy_dir.mkdir(parents=True, exist_ok=True)
    local_binary = workspace_context.mobile_deploy_dir / workspace_context.frida_server_arm64
    local_binary.write_text("server", encoding="utf-8")

    service.is_root = lambda: True
    service.get_cpu_arch = lambda: "arm64"
    service.get_remote_server_pid = lambda name: None
    service.remote_file_exists = lambda path: False if path.endswith("rusda-server-16.2.1") else False
    service.remote_dir_exists = lambda path: True
    service.stop_remote_frida_processes = lambda: False
    service.push_file_to_remote = lambda local_path, remote_path: None
    commands = []
    service.run_root_cmd = lambda cmd, read_output=True: commands.append((cmd, read_output)) or ""

    readiness = iter([False] * 20)
    service.is_frida_environment_ready = lambda: next(readiness)
    service.get_remote_server_pid = lambda name: "4321"
    service.get_remote_server_ports = lambda name: [27042, 27043]
    service.read_remote_start_log = lambda max_lines=80: "line1\nfatal boom"
    messages = []
    workspace_context.emit = messages.append
    monkeypatch.setattr("core.device_service.time.sleep", lambda _seconds: None)

    with pytest.raises(FridaServerStartError) as exc_info:
        service.start_frida_server()

    message = str(exc_info.value)
    assert "pid=4321" in message
    assert "ports=27042,27043" in message
    assert "log=fatal boom" in message
    assert any("远端 Frida Server 启动日志" in line for line in messages)
    assert any("fatal boom" in line for line in messages)


def test_start_app_returns_latest_process_when_foreground_never_matches(
    workspace_context, monkeypatch
) -> None:
    service = DeviceService(workspace_context)
    service.adb_shell = lambda cmd: ""
    service._is_app_in_foreground = lambda package_name: False
    service._find_running_process = lambda package_name, refresh_apps=False: (9876, "Demo App")
    monkeypatch.setattr("core.device_service.time.sleep", lambda _seconds: None)

    pid, name = service.start_app("com.example.demo")

    assert pid == 9876
    assert name == "Demo App"


def test_parse_package_apk_path_prefers_base_apk(workspace_context) -> None:
    service = DeviceService(workspace_context)
    service.adb_shell = lambda cmd: "\n".join(
        [
            "package:/data/app/~~abc/demo-split_config.arm64_v8a.apk",
            "package:/data/app/~~abc/demo-base.apk",
            "package:/data/app/~~abc/base.apk",
        ]
    )

    install_path, apk_name = service._parse_package_apk_path("com.example.demo")

    assert install_path == "/data/app/~~abc"
    assert apk_name == "base.apk"


def test_parse_package_apk_path_falls_back_to_first_apk_candidate(workspace_context) -> None:
    service = DeviceService(workspace_context)
    service.adb_shell = lambda cmd: "package:/data/app/~~abc/demo.apk\npackage:/data/app/~~abc/split_config.en.apk"

    install_path, apk_name = service._parse_package_apk_path("com.example.demo")

    assert install_path == "/data/app/~~abc"
    assert apk_name == "demo.apk"


def test_parse_package_apk_path_raises_structured_error_when_pm_path_is_empty(
    workspace_context,
) -> None:
    service = DeviceService(workspace_context)
    service.adb_shell = lambda cmd: ""

    with pytest.raises(DeviceError):
        service._parse_package_apk_path("com.example.demo")


def test_parse_package_apk_path_raises_structured_error_when_no_apk_found(
    workspace_context,
) -> None:
    service = DeviceService(workspace_context)
    service.adb_shell = lambda cmd: "package:/data/app/~~abc/not-an-apk"

    with pytest.raises(DeviceError):
        service._parse_package_apk_path("com.example.demo")


def test_find_running_pid_via_adb_returns_first_integer_token(workspace_context) -> None:
    service = DeviceService(workspace_context)
    service.adb_shell = lambda cmd: "oops 24567 30001"

    assert service._find_running_pid_via_adb("com.example.demo") == 24567


def test_find_running_pid_via_adb_returns_none_on_failure(workspace_context) -> None:
    service = DeviceService(workspace_context)

    def raise_error(cmd: str) -> str:
        raise RuntimeError("adb unavailable")

    service.adb_shell = raise_error

    assert service._find_running_pid_via_adb("com.example.demo") is None


def test_get_cpu_arch_maps_known_abis_and_returns_unknown_value_verbatim(workspace_context) -> None:
    service = DeviceService(workspace_context)

    cases = {
        "arm64-v8a": "arm64",
        "armeabi-v7a": "arm",
        "x86_64": "x86_64",
        "x86": "x86",
        "mips": "mips",
    }

    for abi, expected in cases.items():
        service.adb_shell = lambda cmd, value=abi: value
        assert service.get_cpu_arch() == expected


def test_get_frida_server_file_raises_structured_error_for_unsupported_arch(
    workspace_context,
) -> None:
    service = DeviceService(workspace_context)
    service.adb_shell = lambda cmd: "x86"

    with pytest.raises(FridaServerStartError):
        service.get_frida_server_file()


def test_get_remote_server_ports_parses_and_deduplicates_ports(workspace_context) -> None:
    service = DeviceService(workspace_context)
    service.get_remote_server_pid = lambda name: "26465"

    outputs = {
        "ss -ltnp 2>/dev/null | grep 'rusda-16.2.1' || true": "\n".join(
            [
                'LISTEN 0 128 127.0.0.1:27042 *:* users:(("rusda-16.2.1",pid=26465,fd=8))',
                'LISTEN 0 128 127.0.0.1:27042 *:* users:(("rusda-16.2.1",pid=26465,fd=9))',
            ]
        ),
        "netstat -ltnp 2>/dev/null | grep 'rusda-16.2.1' || true": (
            "tcp 0 0 0.0.0.0:41272 0.0.0.0:* LISTEN 26465/rusda-16.2.1"
        ),
    }
    service.run_root_cmd = lambda cmd: outputs[cmd]

    assert service.get_remote_server_ports("rusda-16.2.1") == [27042, 41272]


def test_get_remote_server_ports_returns_empty_when_server_not_running(workspace_context) -> None:
    service = DeviceService(workspace_context)
    service.get_remote_server_pid = lambda name: None

    assert service.get_remote_server_ports("rusda-16.2.1") == []


def test_get_foreground_package_reads_first_valid_package(workspace_context) -> None:
    service = DeviceService(workspace_context)
    outputs = iter(
        [
            "mResumedActivity: ActivityRecord{123 u0 com.example.demo/.MainActivity t12}",
            "",
            "",
            "",
        ]
    )
    service.adb_shell = lambda cmd: next(outputs)

    assert service.get_foreground_package() == "com.example.demo"


def test_get_foreground_package_returns_none_when_no_valid_package_found(workspace_context) -> None:
    service = DeviceService(workspace_context)
    outputs = iter(
        [
            "mResumedActivity: ActivityRecord{123 u0 MainActivity/NoDots t12}",
            "topResumedActivity: <none>",
            "mCurrentFocus=Window{abc u0 StatusBar}",
            "mFocusedApp=AppWindowToken{def token=Token{ghi ActivityRecord{jkl u0 Launcher/NoDots}}}",
        ]
    )
    service.adb_shell = lambda cmd: next(outputs)

    assert service.get_foreground_package() is None


def test_remote_file_and_dir_exists_use_public_facade(workspace_context) -> None:
    service = DeviceService(workspace_context)
    outputs = {
        "test -f /tmp/a && echo exists || echo missing": "exists",
        "[ -d /tmp/b ] && echo exists || echo missing": "missing",
    }
    service.adb_shell = lambda cmd: outputs[cmd]

    assert service.remote_file_exists("/tmp/a") is True
    assert service.remote_dir_exists("/tmp/b") is False


def test_prepare_app_context_updates_current_app(workspace_context) -> None:
    service = DeviceService(workspace_context)
    service._read_app_metadata = lambda package_name: (
        10086,
        "/data/app/demo",
        "base.apk",
        "package dump",
        "1.2.3",
    )
    service._find_running_process = lambda package_name, refresh_apps=False: (4321, "Demo App")

    app = service.prepare_app_context("com.example.demo")

    assert isinstance(app, AppContext)
    assert workspace_context.current_app is app
    assert app.identifier == "com.example.demo"
    assert app.pid == 4321
    assert app.name == "Demo App"


def test_refresh_current_app_pid_updates_matching_current_app(workspace_context) -> None:
    service = DeviceService(workspace_context)
    workspace_context.current_app = AppContext(
        identifier="com.example.demo",
        name="Old Name",
        pid=1111,
        version="1.0",
        install_path="/data/app/demo",
        install_apk_filename="base.apk",
        uid=10086,
    )
    service._find_running_process = lambda package_name, refresh_apps=False: (9876, "New Name")

    pid = service.refresh_current_app_pid("com.example.demo")

    assert pid == 9876
    assert workspace_context.current_app.pid == 9876
    assert workspace_context.current_app.name == "New Name"


def test_refresh_applications_writes_context_apps(workspace_context) -> None:
    service = DeviceService(workspace_context)
    fake_apps = [
        types.SimpleNamespace(name="Demo One", identifier="pkg.one", pid=1234),
        types.SimpleNamespace(name="Demo Two", identifier="pkg.two", pid=None),
    ]
    fake_device = types.SimpleNamespace(enumerate_applications=lambda: fake_apps)
    service._get_frida_device = lambda: fake_device

    apps = service.refresh_applications()

    assert workspace_context.frida_device is fake_device
    assert apps is workspace_context.apps
    assert [app.identifier for app in apps] == ["pkg.one", "pkg.two"]


def test_stop_remote_frida_processes_raises_structured_error_without_root(
    workspace_context,
) -> None:
    service = DeviceService(workspace_context)
    workspace_context.adb_device = types.SimpleNamespace(serial="device-1")
    service.is_root = lambda: False

    with pytest.raises(FridaServerStopError):
        service.stop_remote_frida_processes()


def test_cleanup_remote_frida_files_raises_structured_error_for_unexpected_dir(
    workspace_context,
) -> None:
    service = DeviceService(workspace_context)
    workspace_context.remote_frida_dir = "/unexpected"

    with pytest.raises(DeviceError):
        service.cleanup_remote_frida_files()


def test_cleanup_remote_frida_files_allows_managed_subdirectory(
    workspace_context,
) -> None:
    service = DeviceService(workspace_context)
    workspace_context.remote_frida_dir = "/data/local/tmp/hooker"
    workspace_context.adb_device = None

    service.cleanup_remote_frida_files()


def test_ensure_app_running_raises_structured_warning_when_pid_missing(
    workspace_context,
) -> None:
    service = DeviceService(workspace_context)
    service._read_app_metadata = lambda package_name: (
        10086,
        "/data/app/demo",
        "base.apk",
        "package dump",
        "1.2.3",
    )
    service._find_running_process = lambda package_name, refresh_apps=False: (None, "Demo App")

    with pytest.raises(AppNotRunningError):
        service.ensure_app_running("com.example.demo")
