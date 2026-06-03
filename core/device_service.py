from __future__ import annotations

import re
import subprocess
import time
from typing import Optional

import adbutils
import frida
from adbutils.errors import AdbError

from .errors import (
    AppNotRunningError,
    DeviceError,
    FridaServerStartError,
    FridaServerStopError,
    RootRequiredError,
)
from .models import AppContext, AppRecord, HookerContext


class _DeviceBridge:
    # 负责设备桥接、shell/root 命令执行和远端文件操作。
    def __init__(self, service: "DeviceService") -> None:
        self.service = service

    def adb_shell(self, cmd: str) -> str:
        return self.service.adb_device.shell(cmd).strip()

    def run_root_cmd(self, cmd: str, read_output: bool = True) -> str:
        stream = self.service.adb_device.shell(["su", "-c", cmd], stream=True)
        try:
            if not read_output:
                time.sleep(1)
                return ""
            return stream.read_until_close().strip()
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def remote_file_exists(self, path: str) -> bool:
        result = self.service.adb_shell(f"test -f {path} && echo exists || echo missing")
        return result == "exists"

    def remote_dir_exists(self, path: str) -> bool:
        result = self.service.adb_shell(f"[ -d {path} ] && echo exists || echo missing")
        return result == "exists"

    def push_file_to_remote(self, local_path, remote_path: str) -> None:
        try:
            self.service.adb_device.sync.push(str(local_path), remote_path)
        except AdbError:
            subprocess.run(
                [
                    "adb",
                    "-s",
                    self.service.adb_device.serial,
                    "push",
                    str(local_path),
                    remote_path,
                ],
                check=True,
            )

    def ensure_adb_forward(self, local_port: int, remote_port: int) -> None:
        subprocess.run(
            [
                "adb",
                "-s",
                self.service.adb_device.serial,
                "forward",
                f"tcp:{local_port}",
                f"tcp:{remote_port}",
            ],
            check=True,
            capture_output=True,
            text=True,
        )


class _FridaServerManager:
    # 负责 Frida device 解析、server 生命周期、端口探测和启动日志。
    def __init__(self, context: HookerContext, service: "DeviceService") -> None:
        self.context = context
        self.service = service

    def get_frida_device(self):
        serial = getattr(self.context.adb_device, "serial", None)
        last_error: Optional[Exception] = None
        remote_server_name = self.service.get_remote_frida_server_name()
        candidate_ports = self.service.get_remote_server_ports(remote_server_name)

        if serial:
            try:
                return frida.get_device(serial, timeout=3)
            except Exception as exc:
                last_error = exc
        else:
            try:
                return frida.get_usb_device(timeout=3)
            except Exception as exc:
                last_error = exc

        if not candidate_ports:
            candidate_ports = [27042, 27043]

        for index, port in enumerate(candidate_ports):
            try:
                local_port = 27052 + index
                return self.service._get_forwarded_frida_device(
                    remote_port=port,
                    local_port=local_port,
                )
            except Exception as exc:
                last_error = exc

        if last_error is not None:
            raise last_error
        raise frida.ServerNotRunningError("Unable to find a reachable Frida device")

    def get_forwarded_frida_device(self, remote_port: int, local_port: int):
        if self.context.adb_device is None:
            raise DeviceError(
                "ADB 设备尚未连接。",
                hint="请先连接设备，并点击“准备环境并刷新 App”后重试。",
            )
        self.service._ensure_adb_forward(local_port, remote_port)
        manager = frida.get_device_manager()
        device = manager.add_remote_device(f"127.0.0.1:{local_port}")
        try:
            device.enumerate_processes()
        except Exception:
            try:
                manager.remove_remote_device(device)
            except Exception:
                pass
            raise
        return device

    def is_frida_environment_ready(self, target_package: str = "com.android.systemui") -> bool:
        try:
            self.context.frida_device = self.service._get_frida_device()
            pid = self.context.frida_device.get_process(target_package).pid
            session = self.context.frida_device.attach(pid)
            session.detach()
            return True
        except frida.ServerNotRunningError:
            return False
        except frida.ProcessNotFoundError:
            return True
        except frida.TimedOutError:
            remote_server_name = self.service.get_remote_frida_server_name()
            ports = self.service.get_remote_server_ports(remote_server_name)
            if ports:
                self.context.emit(
                    f"[!] {remote_server_name} 当前监听端口: {', '.join(str(port) for port in ports)}"
                )
            return False
        except Exception as exc:
            self.context.emit(f"Frida 环境检查失败: {exc}")
            return False

    def get_frida_server_label(self) -> str:
        return "rusda-server-16.2.1"

    def get_remote_frida_server_name(self) -> str:
        return self.context.remote_frida_server_name

    def get_all_remote_frida_server_names(self) -> list[str]:
        return [self.context.remote_frida_server_name]

    def get_frida_server_file(self) -> str:
        cpu_arch = self.service.get_cpu_arch()
        if cpu_arch == "arm64":
            return self.context.frida_server_arm64
        raise FridaServerStartError(
            f"当前 rusda-server-16.2.1 仅支持 arm64 设备，当前架构为: {cpu_arch}",
            hint="请确认目标设备为 arm64，或补充与当前设备架构匹配的设备侧 server 后重试。",
        )

    def get_remote_frida_server_path(self) -> str:
        return f"{self.context.remote_frida_dir}/{self.service.get_remote_frida_server_name()}"

    def get_remote_server_pid(self, remote_server_name: str) -> Optional[str]:
        output = self.service.run_root_cmd(
            f"pidof {remote_server_name} 2>/dev/null || true"
        ).strip()
        if not output:
            return None
        return output.split()[0]

    def get_remote_server_ports(self, remote_server_name: str) -> list[int]:
        pid = self.service.get_remote_server_pid(remote_server_name)
        if pid is None:
            return []

        commands = [
            f"ss -ltnp 2>/dev/null | grep '{remote_server_name}' || true",
            f"netstat -ltnp 2>/dev/null | grep '{remote_server_name}' || true",
        ]
        patterns = [
            re.compile(rf":(\d+)\s+.*pid={re.escape(pid)}\b"),
            re.compile(rf":(\d+)\s+.*\b{re.escape(pid)}/{re.escape(remote_server_name)}\b"),
            re.compile(r":(\d+)"),
        ]

        ports: list[int] = []
        seen: set[int] = set()
        for cmd in commands:
            output = self.service.run_root_cmd(cmd)
            for line in output.splitlines():
                if remote_server_name not in line and pid not in line:
                    continue
                for pattern in patterns:
                    match = pattern.search(line)
                    if not match:
                        continue
                    port = int(match.group(1))
                    if port in seen:
                        break
                    seen.add(port)
                    ports.append(port)
                    break
        return ports

    def cleanup_remote_frida_files(self) -> None:
        remote_dir = self.context.remote_frida_dir
        if remote_dir != "/data/local/tmp" and not remote_dir.startswith("/data/local/tmp/"):
            raise DeviceError(
                f"拒绝清理非预期目录: {remote_dir}",
                hint="请将 HookerContext.remote_frida_dir 保持在 /data/local/tmp 或其受管子目录下，避免误清理设备上的非受管目录。",
            )
        if self.context.adb_device is None:
            return
        if not self.service.is_root():
            self.context.emit("设备没有被 root，跳过远端 Frida 清理")
            return
        if not self.service.remote_dir_exists(remote_dir):
            return

        stopped_any = False
        for remote_server_name in self.service.get_all_remote_frida_server_names():
            pid = self.service.get_remote_server_pid(remote_server_name)
            if pid is None:
                continue
            self.context.emit(
                f"检测到远端 {remote_server_name} 进程正在运行 (pid={pid})，准备停止"
            )
            self.service.run_root_cmd(f"kill -9 {pid}")
            stopped_any = True
        if stopped_any:
            time.sleep(0.5)

        self.context.emit(
            f"清理远端 Frida 文件: {remote_dir}/{self.service.get_remote_frida_server_name()}"
        )
        files = " ".join(
            f"{remote_dir}/{name}" for name in self.service.get_all_remote_frida_server_names()
        )
        self.service.run_root_cmd(f"rm -f {files} 2>/dev/null || true")

    def stop_remote_frida_processes(self) -> bool:
        if self.context.adb_device is None:
            return False
        if not self.service.is_root():
            raise FridaServerStopError(
                "设备没有被 root，无法停止 Frida Server 进程。",
                hint="请先确认设备已 root，并在 Magisk 中授予 su 权限后重试。",
            )

        stopped_any = False
        for remote_server_name in self.service.get_all_remote_frida_server_names():
            pid = self.service.get_remote_server_pid(remote_server_name)
            if pid is None:
                continue
            self.context.emit(
                f"检测到远端 {remote_server_name} 进程正在运行 (pid={pid})，准备停止"
            )
            self.service.run_root_cmd(f"kill -9 {pid}")
            stopped_any = True
        if stopped_any:
            time.sleep(0.5)
        return stopped_any

    def stop_frida_server(self) -> None:
        if self.context.adb_device is None:
            raise FridaServerStopError(
                "请先准备环境或连接设备后，再停止 Frida Server。",
                hint="请先点击“准备环境并刷新 App”，确认设备连接正常后再重试。",
            )
        if not self.service.is_root():
            raise FridaServerStopError(
                "设备没有被 root，无法停止 Frida Server。",
                hint="请先确认设备已 root，并在 Magisk 中授予 su 权限后重试。",
            )

        remote_file = self.service.get_remote_frida_server_path()
        remote_server_name = self.service.get_remote_frida_server_name()
        pid = self.service.get_remote_server_pid(remote_server_name)
        file_exists = self.service.remote_file_exists(remote_file)

        self.context.emit(f"[*] 准备停止 Frida Server: {remote_file}")
        self.service.cleanup_remote_frida_files()
        self.context.frida_device = None

        if pid is None and not file_exists:
            self.context.emit("[*] 当前未发现运行中的 Frida Server，也没有残留部署文件。")
        else:
            self.context.emit(f"[+] Frida Server 已停止并清理: {remote_file}")

    def read_remote_start_log(self, max_lines: int = 80) -> str:
        if self.context.adb_device is None:
            return ""
        try:
            return self.service.run_root_cmd(
                f"tail -n {max_lines} /sdcard/f_server.log 2>/dev/null || true"
            ).strip()
        except Exception:
            return ""

    def start_frida_server(self) -> None:
        if not self.service.is_root():
            raise RootRequiredError(
                "设备没有被 root，无法启动 Frida Server。",
                hint="请先确认设备已 root，并在 Magisk 中授予 su 权限后重试。",
            )
        frida_server_file = self.service.get_frida_server_file()
        remote_file = self.service.get_remote_frida_server_path()

        local_frida_server = self.context.mobile_deploy_dir / frida_server_file
        if not local_frida_server.exists():
            raise FridaServerStartError(
                f"缺少本地 rusda-server 文件：{local_frida_server}",
                hint="请检查 mobile-deploy 目录中的 rusda-server-16.2.1-android-arm64 是否存在。",
            )

        remote_server_name = self.service.get_remote_frida_server_name()
        existing_pid = self.service.get_remote_server_pid(remote_server_name)
        remote_file_exists = self.service.remote_file_exists(remote_file)

        if existing_pid is not None and remote_file_exists and self.service.is_frida_environment_ready():
            self.context.last_prepare_frida_server_status = "reused"
            return

        if not self.service.remote_dir_exists(self.context.remote_frida_dir):
            self.service.run_root_cmd(f"mkdir -p {self.context.remote_frida_dir}")

        self.service.stop_remote_frida_processes()

        if remote_file_exists:
            self.service.run_root_cmd(f"chmod 755 {remote_file}")
        else:
            temp_remote = f"/sdcard/{remote_server_name}"
            self.service.push_file_to_remote(local_frida_server, temp_remote)
            self.service.run_root_cmd(f"mv {temp_remote} {remote_file}")
            self.service.run_root_cmd(f"chmod 755 {remote_file}")

        self.service.run_root_cmd(
            f"cd {self.context.remote_frida_dir} && ./{remote_server_name} > /sdcard/f_server.log 2>&1 &",
            read_output=False,
        )

        for _ in range(20):
            if self.service.is_frida_environment_ready():
                self.context.last_prepare_frida_server_status = "started"
                return
            time.sleep(0.5)

        pid = self.service.get_remote_server_pid(remote_server_name)
        ports = self.service.get_remote_server_ports(remote_server_name)
        start_log = self.service.read_remote_start_log()
        if pid is not None:
            self.context.emit(
                f"[!] 检测到 {remote_server_name} 进程仍在运行 (pid={pid})，但 Frida 探活没有通过。"
            )
        if ports:
            self.context.emit(
                f"[!] {remote_server_name} 当前监听端口: {', '.join(str(port) for port in ports)}"
            )
        if start_log:
            self.context.emit("[!] 远端 Frida Server 启动日志：")
            for line in start_log.splitlines():
                self.context.emit(f"[!] {line}")

        detail_parts = [f"Frida Server 启动失败: {remote_file}"]
        if pid is not None:
            detail_parts.append(f"pid={pid}")
        if ports:
            detail_parts.append(f"ports={','.join(str(port) for port in ports)}")
        if start_log:
            summary = start_log.splitlines()[-1].strip()
            if summary:
                detail_parts.append(f"log={summary}")
        if pid is not None and not ports:
            detail_parts.append("进程已启动但未发现监听端口")
        detail_parts.append("请检查权限、监听端口或手动启动。")
        raise FridaServerStartError(
            " | ".join(detail_parts),
            hint="请检查设备权限、监听端口、远端日志和 rusda 部署状态。",
        )


class _AppRuntimeInspector:
    # 负责 App 元数据、进程状态、前台检测、应用列表与 radar.dex 部署。
    def __init__(
        self,
        context: HookerContext,
        service: "DeviceService",
    ) -> None:
        self.context = context
        self.service = service

    def parse_package_apk_path(self, package_name: str) -> tuple[str, str]:
        raw_output = self.service.adb_shell(f"pm path {package_name}")
        candidates = [
            line.replace("package:", "").strip()
            for line in raw_output.splitlines()
            if line.strip().startswith("package:")
        ]
        if not candidates:
            raise DeviceError(
                f"无法解析 {package_name} 的安装路径: {raw_output!r}",
                hint="请确认目标应用已正确安装，并检查 `pm path` 输出是否正常后重试。",
            )

        apk_path = next((path for path in candidates if path.endswith("/base.apk")), None)
        if apk_path is None:
            apk_path = next((path for path in candidates if path.endswith(".apk")), None)
        if apk_path is None:
            raise DeviceError(
                f"无法从 pm path 输出中找到 APK 文件: {raw_output!r}",
                hint="请确认 `pm path` 输出包含可访问的 APK 路径后重试。",
            )

        install_path, install_apk_filename = apk_path.rsplit("/", 1)
        return install_path, install_apk_filename

    def read_app_metadata(self, package_name: str) -> tuple[Optional[int], str, str, str, Optional[str]]:
        shell_result = self.service.adb_shell(f"dumpsys package {package_name}")
        uid = None
        match_uid = re.search(r"(userId|uid|appId)=(\d+)", shell_result)
        if match_uid:
            uid = int(match_uid.group(2))

        install_path, install_apk_filename = self.service._parse_package_apk_path(package_name)
        if hasattr(self.service.adb_device, "app_info"):
            app_info = self.service.adb_device.app_info(package_name)
            version_name = app_info.version_name
        else:
            app_info = self.service.adb_device.package_info(package_name)
            version_name = app_info["version_name"]
        return uid, install_path, install_apk_filename, shell_result, version_name

    def build_app_context(
        self,
        package_name: str,
        *,
        pid: Optional[int],
        name: Optional[str],
        uid: Optional[int],
        version_name: Optional[str],
        install_path: str,
        install_apk_filename: str,
    ) -> AppContext:
        app_context = AppContext(
            identifier=package_name,
            name=name or package_name,
            pid=pid,
            version=version_name,
            install_path=install_path,
            install_apk_filename=install_apk_filename,
            uid=uid,
        )
        self.context.current_app = app_context
        return app_context

    def prepare_app_context(self, package_name: str) -> AppContext:
        uid, install_path, install_apk_filename, _, version_name = self.service._read_app_metadata(
            package_name
        )
        pid, name = self.service._find_running_process(package_name, refresh_apps=True)
        return self.service._build_app_context(
            package_name,
            pid=pid,
            name=name,
            uid=uid,
            version_name=version_name,
            install_path=install_path,
            install_apk_filename=install_apk_filename,
        )

    def ensure_app_running(self, package_name: str) -> AppContext:
        uid, install_path, install_apk_filename, _, version_name = self.service._read_app_metadata(
            package_name
        )
        pid, name = self.service._find_running_process(package_name, refresh_apps=True)
        if pid is None:
            raise AppNotRunningError(
                f"Attach 模式要求目标 App 已经在运行：{package_name}。",
                hint="请先手动启动目标 App，或改用 Spawn 模式后重试。",
            )
        self.context.emit(f"App {package_name} 已在运行，准备直接 attach 到 pid={pid}。")
        return self.service._build_app_context(
            package_name,
            pid=pid,
            name=name,
            uid=uid,
            version_name=version_name,
            install_path=install_path,
            install_apk_filename=install_apk_filename,
        )

    def get_live_pid(self, package_name: str) -> Optional[int]:
        pid, _ = self.service._find_running_process(package_name, refresh_apps=True)
        return pid

    def refresh_current_app_pid(self, package_name: str) -> Optional[int]:
        pid, name = self.service._find_running_process(package_name, refresh_apps=True)
        if self.context.current_app is not None and self.context.current_app.identifier == package_name:
            self.context.current_app.pid = pid
            if name:
                self.context.current_app.name = name
        return pid

    def find_running_pid_via_adb(self, package_name: str) -> Optional[int]:
        try:
            output = self.service.adb_shell(f"pidof {package_name} 2>/dev/null || true")
        except Exception:
            return None
        if not output:
            return None
        for token in output.split():
            try:
                return int(token)
            except ValueError:
                continue
        return None

    def resolve_process_name_by_pid(
        self,
        pid: int,
        package_name: str,
        *,
        refresh_apps: bool = False,
    ) -> Optional[str]:
        if refresh_apps or not self.context.apps:
            try:
                self.service.refresh_applications()
            except Exception:
                pass

        for app in self.context.apps:
            if app.pid == pid and app.identifier == package_name:
                return app.name

        try:
            process = self.service._get_frida_device().get_process(pid)
            return process.name
        except Exception:
            return None

    def find_running_process(
        self,
        package_name: str,
        *,
        refresh_apps: bool = False,
    ) -> tuple[Optional[int], Optional[str]]:
        adb_pid = self.service._find_running_pid_via_adb(package_name)
        if adb_pid is not None:
            return adb_pid, self.service._resolve_process_name_by_pid(
                adb_pid,
                package_name,
                refresh_apps=refresh_apps,
            )

        if refresh_apps or not self.context.apps:
            self.service.refresh_applications()

        for app in self.context.apps:
            if app.identifier == package_name and app.pid:
                return app.pid, app.name

        try:
            frida_device = self.context.frida_device or self.service._get_frida_device()
            process = frida_device.get_process(package_name)
            return process.pid, process.name
        except frida.ProcessNotFoundError:
            return None, None

    def refresh_applications(self) -> list[AppRecord]:
        self.context.frida_device = self.service._get_frida_device()
        raw_apps = self.context.frida_device.enumerate_applications()
        self.context.apps = [
            AppRecord(name=app.name, identifier=app.identifier, pid=app.pid)
            for app in raw_apps
        ]
        return self.context.apps

    def start_app(self, package_name: str) -> tuple[Optional[int], Optional[str]]:
        shell_result = self.service.adb_shell(
            f"dumpsys package {package_name} | grep -A 1 MAIN | grep {package_name}"
        )
        match = re.search(r"\s+([^\s]+)\s+filter", shell_result) if shell_result else None
        if match:
            self.service.adb_shell(f"am start -n {match.group(1)}")
        else:
            self.service.adb_shell(f"monkey -p {package_name} -c android.intent.category.LAUNCHER 1")

        for _ in range(100):
            time.sleep(0.5)
            if self.service._is_app_in_foreground(package_name):
                pid, name = self.service._find_running_process(package_name, refresh_apps=True)
                if pid is not None:
                    return pid, name
        return self.service._find_running_process(package_name, refresh_apps=True)

    def get_foreground_state(self, package_name: str) -> tuple[bool, str]:
        outputs = [
            ("mResumedActivity", self.service.adb_shell("dumpsys activity activities | grep mResumedActivity")),
            ("topResumedActivity", self.service.adb_shell("dumpsys activity activities | grep topResumedActivity")),
            ("mCurrentFocus", self.service.adb_shell("dumpsys window windows | grep mCurrentFocus")),
            ("mFocusedApp", self.service.adb_shell("dumpsys window windows | grep mFocusedApp")),
        ]
        combined = "\n".join(f"{label}: {text}" for label, text in outputs if text)
        return package_name in combined, combined

    def get_foreground_package(self) -> Optional[str]:
        outputs = [
            self.service.adb_shell("dumpsys activity activities | grep mResumedActivity"),
            self.service.adb_shell("dumpsys activity activities | grep topResumedActivity"),
            self.service.adb_shell("dumpsys window windows | grep mCurrentFocus"),
            self.service.adb_shell("dumpsys window windows | grep mFocusedApp"),
        ]
        package_patterns = [
            r"\s([A-Za-z0-9_.$]+?)/",
            r"u\d+\s+([A-Za-z0-9_.$]+)/",
        ]
        for output in outputs:
            if not output:
                continue
            for line in output.splitlines():
                for pattern in package_patterns:
                    match = re.search(pattern, line)
                    if match:
                        package_name = match.group(1)
                        if package_name and "." in package_name:
                            return package_name
        return None

    def is_app_in_foreground(self, package_name: str) -> bool:
        is_foreground, _ = self.service._get_foreground_state(package_name)
        return is_foreground

    def deploy_radar_dex(self) -> None:
        if not self.context.local_radar_dex.exists():
            raise DeviceError(
                f"缺少本地 radar.dex 文件：{self.context.local_radar_dex}",
                hint="请检查项目根目录下的 radar.dex 是否存在后重试。",
            )
        if not self.service.is_root():
            raise RootRequiredError(
                "设备没有被 root，无法部署 radar.dex。",
                hint="请先确认设备已 root，并在 Magisk 中授予 su 权限后重试。",
            )
        if self.service.remote_file_exists(self.context.remote_radar_dex):
            return
        self.service.push_file_to_remote(self.context.local_radar_dex, "/sdcard/")
        self.service.run_root_cmd(
            f"cp /sdcard/{self.context.local_radar_dex.name} {self.context.remote_radar_dex}"
        )
        self.service.run_root_cmd(f"chmod 755 {self.context.remote_radar_dex}")


class DeviceService:
    # 负责设备发现、ADB/Frida 环境准备和应用枚举。
    # 对外仍是唯一 service 入口，内部通过 bridge / frida_server / apps 三个职责组件协作。
    def __init__(self, context: HookerContext) -> None:
        self.context = context
        self.bridge = _DeviceBridge(self)
        self.frida_server = _FridaServerManager(context, self)
        self.apps = _AppRuntimeInspector(context, self)

    @property
    def adb_device(self):
        if self.context.adb_device is None:
            raise DeviceError("ADB 设备尚未连接。", hint="请先连接设备，并点击“准备环境并刷新 App”后重试。")
        return self.context.adb_device

    def connect(self) -> None:
        self.context.adb_device = adbutils.adb.device()
        self.context.last_connected_device_serial = self.context.adb_device.serial

    def adb_shell(self, cmd: str) -> str:
        return self.bridge.adb_shell(cmd)

    def run_root_cmd(self, cmd: str, read_output: bool = True) -> str:
        return self.bridge.run_root_cmd(cmd, read_output=read_output)

    def remote_file_exists(self, path: str) -> bool:
        return self.bridge.remote_file_exists(path)

    def remote_dir_exists(self, path: str) -> bool:
        return self.bridge.remote_dir_exists(path)

    def push_file_to_remote(self, local_path, remote_path: str) -> None:
        self.bridge.push_file_to_remote(local_path, remote_path)

    def _ensure_adb_forward(self, local_port: int, remote_port: int) -> None:
        self.bridge.ensure_adb_forward(local_port, remote_port)

    def is_root(self) -> bool:
        try:
            return "uid=0" in self.run_root_cmd("id")
        except Exception:
            return False

    def is_magisk_root(self) -> bool:
        output = self.run_root_cmd("id")
        if "uid=0" not in output:
            self.context.emit("设备没有被 root")
            return False
        if "context=u:r:magisk:s0" in output:
            return True
        magisk_marker = self.run_root_cmd("ls /data/adb/magisk.db 2>/dev/null")
        return bool(magisk_marker)

    def get_cpu_arch(self) -> str:
        abi = self.adb_shell("getprop ro.product.cpu.abi").strip()
        if "arm64" in abi:
            return "arm64"
        if "armeabi" in abi:
            return "arm"
        if "x86_64" in abi:
            return "x86_64"
        if "x86" in abi:
            return "x86"
        return abi or "unknown"

    def _get_frida_device(self):
        return self.frida_server.get_frida_device()

    def _get_forwarded_frida_device(self, remote_port: int, local_port: int):
        return self.frida_server.get_forwarded_frida_device(remote_port, local_port)

    def is_frida_environment_ready(self, target_package: str = "com.android.systemui") -> bool:
        return self.frida_server.is_frida_environment_ready(target_package)

    def get_frida_server_label(self) -> str:
        return self.frida_server.get_frida_server_label()

    def get_remote_frida_server_name(self) -> str:
        return self.frida_server.get_remote_frida_server_name()

    def get_all_remote_frida_server_names(self) -> list[str]:
        return self.frida_server.get_all_remote_frida_server_names()

    def get_frida_server_file(self) -> str:
        return self.frida_server.get_frida_server_file()

    def get_remote_frida_server_path(self) -> str:
        return self.frida_server.get_remote_frida_server_path()

    def get_remote_server_pid(self, remote_server_name: str) -> Optional[str]:
        return self.frida_server.get_remote_server_pid(remote_server_name)

    def get_remote_server_ports(self, remote_server_name: str) -> list[int]:
        return self.frida_server.get_remote_server_ports(remote_server_name)

    def cleanup_remote_frida_files(self) -> None:
        self.frida_server.cleanup_remote_frida_files()

    def stop_remote_frida_processes(self) -> bool:
        return self.frida_server.stop_remote_frida_processes()

    def stop_frida_server(self) -> None:
        self.frida_server.stop_frida_server()

    def read_remote_start_log(self, max_lines: int = 80) -> str:
        return self.frida_server.read_remote_start_log(max_lines)

    def start_frida_server(self) -> None:
        self.frida_server.start_frida_server()

    def _parse_package_apk_path(self, package_name: str) -> tuple[str, str]:
        return self.apps.parse_package_apk_path(package_name)

    def _read_app_metadata(self, package_name: str) -> tuple[Optional[int], str, str, str, Optional[str]]:
        return self.apps.read_app_metadata(package_name)

    def _build_app_context(
        self,
        package_name: str,
        *,
        pid: Optional[int],
        name: Optional[str],
        uid: Optional[int],
        version_name: Optional[str],
        install_path: str,
        install_apk_filename: str,
    ) -> AppContext:
        return self.apps.build_app_context(
            package_name,
            pid=pid,
            name=name,
            uid=uid,
            version_name=version_name,
            install_path=install_path,
            install_apk_filename=install_apk_filename,
        )

    def prepare_app_context(self, package_name: str) -> AppContext:
        return self.apps.prepare_app_context(package_name)

    def ensure_app_running(self, package_name: str) -> AppContext:
        return self.apps.ensure_app_running(package_name)

    def get_live_pid(self, package_name: str) -> Optional[int]:
        return self.apps.get_live_pid(package_name)

    def refresh_current_app_pid(self, package_name: str) -> Optional[int]:
        return self.apps.refresh_current_app_pid(package_name)

    def _find_running_pid_via_adb(self, package_name: str) -> Optional[int]:
        return self.apps.find_running_pid_via_adb(package_name)

    def _resolve_process_name_by_pid(
        self,
        pid: int,
        package_name: str,
        *,
        refresh_apps: bool = False,
    ) -> Optional[str]:
        return self.apps.resolve_process_name_by_pid(
            pid,
            package_name,
            refresh_apps=refresh_apps,
        )

    def _find_running_process(
        self,
        package_name: str,
        *,
        refresh_apps: bool = False,
    ) -> tuple[Optional[int], Optional[str]]:
        return self.apps.find_running_process(package_name, refresh_apps=refresh_apps)

    def refresh_applications(self) -> list[AppRecord]:
        return self.apps.refresh_applications()

    def start_app(self, package_name: str) -> tuple[Optional[int], Optional[str]]:
        return self.apps.start_app(package_name)

    def _get_foreground_state(self, package_name: str) -> tuple[bool, str]:
        return self.apps.get_foreground_state(package_name)

    def get_foreground_package(self) -> Optional[str]:
        return self.apps.get_foreground_package()

    def _is_app_in_foreground(self, package_name: str) -> bool:
        return self.apps.is_app_in_foreground(package_name)

    def deploy_radar_dex(self) -> None:
        self.apps.deploy_radar_dex()
