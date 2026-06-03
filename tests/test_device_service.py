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
