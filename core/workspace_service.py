from __future__ import annotations

from pathlib import Path
from typing import Optional

from .errors import (
    WorkspaceApkPullError,
    WorkspaceFileReadError,
    WorkspaceFileWriteError,
    WorkspaceInitializationError,
    WorkspaceResourceMissingError,
    WorkspaceScriptMissingError,
)
from .models import AppContext, HookerContext


BUILTIN_JS_FILES = [
    "android_ui.js",
    "apk_shell_scanner.js",
    "bypass_root_detect.js",
    "bypass_vpn_detect.js",
    "click.js",
    "detect_network_stack.js",
    "DumpDex.js",
    "edit_text.js",
    "find_anit_frida_so.js",
    "get_device_info.js",
    "hook_encryption_algo.js",
    "hook_encryption_algo2.js",
    "hook_register_natives.js",
    "trace_init_proc.js",
    "jni_method_trace.js",
    "just_trust_me.js",
    "keystore_dump.js",
    "okhttp.js",
    "print_okhttp_interceptors.js",
    "text_view.js",
    "url.js",
    "activity_events.js",
]

GUI_RESOURCE_JS_FILES = BUILTIN_JS_FILES + [
    "_hook_js_enhance.js",
    "_hook_js_prepare.js",
    "_hook_js_warp.js",
    "rpc.js",
]

DEFAULT_PACKAGE_PLACEHOLDER = "com.smile.gifmaker"


class WorkspaceService:
    # 负责工作目录、脚本资源和产物文件管理。
    def __init__(self, context: HookerContext) -> None:
        self.context = context

    def workspace_dir(self, package_name: str) -> Path:
        # 返回某个包名对应的工作目录。
        return self.context.workspaces_dir / package_name

    def script_dir(self, package_name: str) -> Path:
        # 返回某个包名对应的脚本目录。
        return self.workspace_dir(package_name) / "js"

    def read_local_file(self, filename) -> Optional[str]:
        # 读取本地文本文件，主要用于 JS 脚本和资源文件。
        path = Path(filename)
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            self.context.emit(f"File {path} not found.")
            return None
        except OSError as exc:
            self.context.emit(f"Error reading file {path}: {exc}")
            return None

    def read_js_resource(self, filename: str) -> Optional[str]:
        # 读取项目内置 js 资源。
        return self.read_local_file(self.context.hookers_js_dir / filename)

    def get_resource_script(self, filename: str) -> str:
        # 读取内置脚本；缺失时直接抛错，避免后续拼接出错。
        content = self.read_js_resource(filename)
        if content is None:
            raise WorkspaceResourceMissingError(
                f"缺少内置资源: {filename}",
                hint="请检查项目根目录下的 js 资源是否完整后重试。",
            )
        return content

    def create_working_file(self, filename, text: str) -> Path:
        # 在工作目录中创建文件，并自动补齐父目录。
        path = Path(filename)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="")
        except OSError as exc:
            raise WorkspaceFileWriteError(
                f"写入工作区文件失败: {path}",
                hint="请检查本地工作目录是否可写，以及磁盘空间和文件权限是否正常。",
            ) from exc
        return path

    def _sanitize_filename_component(self, value: Optional[str], fallback: str) -> str:
        raw = (value or "").strip()
        if not raw:
            raw = fallback
        sanitized = "".join(
            ch if ch.isalnum() or ch in "._-() " else "_"
            for ch in raw
        ).strip()
        sanitized = sanitized.rstrip(". ")
        return sanitized or fallback

    def _render_builtin_script(self, js_file: str, package_name: str) -> Optional[str]:
        src = self.context.hookers_js_dir / js_file
        if not src.exists():
            return None
        text = src.read_text(encoding="utf-8", errors="ignore")
        return text.replace(DEFAULT_PACKAGE_PLACEHOLDER, package_name)

    def remove_workspace_builtin_scripts(self, script_dir: Path) -> None:
        # 工作区不再保存 GUI 内置脚本副本，避免工作区旧脚本覆盖 GUI 固定资源。
        if not script_dir.exists():
            return

        for js_file in BUILTIN_JS_FILES:
            target = script_dir / js_file
            if not target.exists():
                continue
            try:
                target.unlink()
            except OSError as exc:
                raise WorkspaceFileWriteError(
                    f"删除工作区内置脚本失败: {target}",
                    hint="请检查当前工作目录脚本文件是否可写，必要时关闭占用后重新初始化工作目录。",
                ) from exc

        try:
            next(script_dir.iterdir())
        except StopIteration:
            try:
                script_dir.rmdir()
            except OSError:
                pass

    def materialize_builtin_scripts(
        self,
        package_name: str,
        script_dir: Path,
        rewrite_existing: bool = False,
    ) -> None:
        # 把内置脚本物化到工作区，并在需要时修正仍保留默认包名占位值的旧副本。
        script_dir.mkdir(parents=True, exist_ok=True)
        for js_file in BUILTIN_JS_FILES:
            rendered = self._render_builtin_script(js_file, package_name)
            if rendered is None:
                continue

            target = script_dir / js_file
            if not target.exists():
                self.create_working_file(target, rendered)
                continue

            if not rewrite_existing:
                continue

            try:
                existing = target.read_text(encoding="utf-8")
            except OSError as exc:
                raise WorkspaceFileReadError(
                    f"读取工作区脚本副本失败: {target}",
                    hint="请检查当前工作目录脚本副本是否仍然存在且可读，必要时重新初始化工作目录。",
                ) from exc

            if DEFAULT_PACKAGE_PLACEHOLDER not in existing:
                continue

            updated = existing.replace(DEFAULT_PACKAGE_PLACEHOLDER, package_name)
            if updated != existing:
                self.create_working_file(target, updated)

    def workspace_apk_path(self, app: AppContext) -> Path:
        safe_name = self._sanitize_filename_component(app.name, app.identifier)
        safe_version = self._sanitize_filename_component(app.version, "unknown")
        return self.workspace_dir(app.identifier) / f"{safe_name}_{safe_version}.apk"

    def pull_current_apk(self, app: AppContext) -> Path:
        # 把当前应用 APK 拉到本地工作目录。
        local_apk_path = self.workspace_apk_path(app)
        remote_apk = f"{app.install_path}/{app.install_apk_filename}"
        try:
            self.context.adb_device.sync.pull(remote_apk, str(local_apk_path))
        except Exception as exc:
            raise WorkspaceApkPullError(
                f"拉取 APK 失败: {remote_apk}",
                hint="请检查设备连接、包安装路径以及当前 ADB/root 状态后重试。",
            ) from exc
        self.context.current_local_apk_path = local_apk_path
        self.context.last_workspace_apk_status = "pulled"
        return local_apk_path

    def ensure_local_apk(self, app: AppContext, refresh: bool = False) -> Path:
        local_apk_path = self.workspace_apk_path(app)
        if refresh or not local_apk_path.exists():
            return self.pull_current_apk(app)
        self.context.current_local_apk_path = local_apk_path
        self.context.last_workspace_apk_status = "reused"
        return local_apk_path

    def ensure_workspace_helpers(self, app: AppContext, package_dir: Path) -> None:
        log_hooking = (
            "@echo off\r\n"
            + "echo hooking %1 > log.txt\r\n"
            + "echo %date% %time% >> log.txt\r\n"
            + f"frida -U -l %1 -N {app.identifier} >> log.txt 2>&1\r\n"
        )
        attach_shell = "@echo off\r\n" + f"frida -U -l %1 -N {app.identifier}\r\n"
        spawn_shell = (
            "@echo off\r\n" + f"frida -U --runtime=v8 -f {app.identifier} -l %1\r\n"
        )
        kill_shell = "@echo off\r\n" + f"frida-kill -U {app.identifier}\r\n"
        objection_shell = (
            "@echo off\r\n" + f"objection -d -g {app.identifier} explore\r\n"
        )

        self.create_working_file(package_dir / "hooking.bat", log_hooking)
        self.create_working_file(package_dir / "attach.bat", attach_shell)
        self.create_working_file(package_dir / "spawn.bat", spawn_shell)
        self.create_working_file(package_dir / "kill.bat", kill_shell)
        self.create_working_file(package_dir / "objection.bat", objection_shell)

    def create_initial_workspace(self, app: AppContext) -> Path:
        # 首次进入某个应用时，初始化默认脚本和辅助 bat 文件。
        package_dir = self.workspace_dir(app.identifier)
        try:
            self.context.workspaces_dir.mkdir(parents=True, exist_ok=True)
            package_dir.mkdir(parents=True, exist_ok=True)
            self.ensure_workspace_helpers(app, package_dir)
            self.remove_workspace_builtin_scripts(package_dir / "js")
            self.ensure_local_apk(app, refresh=True)
            self.context.last_workspace_prepare_mode = "created"
            return package_dir
        except WorkspaceInitializationError:
            raise
        except Exception as exc:
            raise WorkspaceInitializationError(
                f"首次初始化工作目录失败: {app.identifier} -> {exc}",
                hint="请检查本地工作区是否可写、设备 APK 是否可拉取，以及内置脚本资源是否完整。",
            ) from exc

    def initialize_existing_workspace(self, app: AppContext) -> Path:
        # 已有工作目录时补齐缺失脚本、修正旧占位值，并刷新本地 APK 副本。
        package_dir = self.workspace_dir(app.identifier)
        try:
            self.context.workspaces_dir.mkdir(parents=True, exist_ok=True)
            package_dir.mkdir(parents=True, exist_ok=True)
            self.ensure_workspace_helpers(app, package_dir)
            self.remove_workspace_builtin_scripts(package_dir / "js")
            self.ensure_local_apk(app, refresh=False)
            self.context.last_workspace_prepare_mode = "updated"
            return package_dir
        except WorkspaceInitializationError:
            raise
        except Exception as exc:
            raise WorkspaceInitializationError(
                f"补齐已有工作目录失败: {app.identifier} -> {exc}",
                hint="请检查现有工作目录文件是否可读写、设备 APK 是否可拉取，以及内置脚本资源是否完整。",
            ) from exc

    def ensure_workspace(self, app: AppContext) -> Path:
        # 根据工作目录是否存在，选择初始化或补全。
        try:
            self.context.last_workspace_prepare_mode = None
            self.context.last_workspace_apk_status = None
            self.context.workspaces_dir.mkdir(parents=True, exist_ok=True)
            package_dir = self.workspace_dir(app.identifier)
            if package_dir.exists():
                return self.initialize_existing_workspace(app)
            return self.create_initial_workspace(app)
        except WorkspaceInitializationError:
            raise
        except Exception as exc:
            raise WorkspaceInitializationError(
                f"准备工作目录失败: {app.identifier} -> {exc}",
                hint="请检查工作目录路径、本地磁盘权限以及设备 APK 是否可以正常拉取。",
            ) from exc

    def list_scripts(self, package_name: str) -> list[Path]:
        # 列出某个工作目录下可直接执行的 js 脚本。
        script_dir = self.script_dir(package_name)
        if not script_dir.is_dir():
            return []
        return sorted(
            [
                path
                for path in script_dir.iterdir()
                if path.is_file() and path.suffix == ".js"
            ]
        )

    def script_names(self, package_name: str) -> list[str]:
        # 仅返回脚本文件名，适合给 CLI/GUI 做展示和补全。
        return [path.name for path in self.list_scripts(package_name)]

    def materialize_multi_script_bundle(
        self,
        package_name: str,
        script_paths: list[str | Path],
        *,
        output_name: str = "frida_multi_bundle.runtime.js",
    ) -> Path:
        if not script_paths:
            raise WorkspaceScriptMissingError(
                "未选择任何脚本。",
                hint="请至少选择一个工作区脚本或内置脚本后再启动。",
            )

        bundle_parts = [
            "// Generated by Frida-Hookers multi-script launcher.",
            "",
        ]

        for index, script_ref in enumerate(script_paths, start=1):
            resolved = self.resolve_script_path(str(script_ref), package_name)
            try:
                script_text = resolved.read_text(encoding="utf-8")
            except OSError as exc:
                raise WorkspaceFileReadError(
                    f"读取脚本失败: {resolved}",
                    hint="请检查脚本文件是否存在且可读后重试。",
                ) from exc

            bundle_parts.extend(
                [
                    f"// ===== BEGIN [{index}] {resolved.name} =====",
                    f"// Source: {resolved}",
                    script_text,
                    f"// ===== END [{index}] {resolved.name} =====",
                    "",
                ]
            )

        bundle_path = self.script_dir(package_name) / output_name
        return self.create_working_file(bundle_path, "\n".join(bundle_parts))

    def resolve_script_path(self, script_name_or_path: str, package_name: str) -> Path:
        # 把脚本名解析成实际路径。
        # 优先解析工作目录下的相对路径，便于 CLI 和 GUI 只传入文件名。
        path = Path(script_name_or_path)
        if path.is_absolute():
            return path
        workspace_path = self.script_dir(package_name) / script_name_or_path
        if workspace_path.exists():
            return workspace_path
        builtin_path = self.context.hookers_js_dir / script_name_or_path
        if builtin_path.exists():
            return builtin_path
        if path.exists():
            return path
        raise WorkspaceScriptMissingError(
            f"脚本不存在: {script_name_or_path}",
            hint="请确认当前工作目录脚本副本是否存在，或重新初始化工作目录后再试。",
        )

    def save_decrypt_output(self, package_name: str, filename: str, content: str) -> Path:
        # 保存脚本通过 send 回传的解密结果。
        safe_package = "".join(
            ch if ch.isalnum() or ch in "._-" else "_"
            for ch in (package_name or "unknown_package")
        )
        safe_filename = Path(filename or "decrypt_output.txt").name
        output_dir = self.workspace_dir(safe_package) / "hook_da5_outputs"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / safe_filename
            normalized_content = (
                content.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")
            )
            output_path.write_text(normalized_content, encoding="utf-8")
            self.context.emit(
                f"解密结果已保存到真实目录: {output_path} ({output_path.stat().st_size} bytes)"
            )
            return output_path
        except OSError as exc:
            raise WorkspaceFileWriteError(
                f"保存解密结果失败: {safe_filename}",
                hint="请检查工作目录输出路径是否可写，以及磁盘空间是否充足。",
            ) from exc
