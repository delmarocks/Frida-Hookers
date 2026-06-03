from __future__ import annotations

import re
from pathlib import Path

import jsbeautifier

from .models import HookerContext
from .session_service import SessionService
from .workspace_service import WorkspaceService


class RpcService:
    # 负责 RPC 调用和 hook 脚本生成。
    # CLI 默认走短连接；GUI 可显式开启持久 RPC 会话复用。
    def __init__(
        self,
        context: HookerContext,
        session_service: SessionService,
        workspace_service: WorkspaceService,
    ) -> None:
        self.context = context
        self.session_service = session_service
        self.workspace_service = workspace_service
        self._persistent_enabled = False
        self._persistent_session = None
        self._persistent_script = None
        self._persistent_package_name: str | None = None
        self._persistent_pid: int | None = None
        self._persistent_use_v8 = False

    def enable_persistent_session(self) -> None:
        # GUI 高频调用时可开启持久 RPC，会复用同一个 attach/script。
        self._persistent_enabled = True

    def disable_persistent_session(self) -> None:
        self._persistent_enabled = False
        self.invalidate_persistent_session()

    def invalidate_persistent_session(self) -> None:
        # 当前包名、PID 或运行时环境变化后，主动丢弃旧 RPC 会话。
        self._cleanup_rpc_resources(self._persistent_session, self._persistent_script)
        self._persistent_session = None
        self._persistent_script = None
        self._persistent_package_name = None
        self._persistent_pid = None
        self._persistent_use_v8 = False

    def _cleanup_rpc_resources(self, session, script) -> None:
        if script is not None:
            try:
                script.exports_sync.cleanup()
            except Exception:
                pass
            try:
                script.unload()
            except Exception:
                pass
        if session is not None:
            try:
                session.detach()
            except Exception:
                pass

    def _create_rpc_resources(self, use_v8: bool = False):
        self.session_service.require_current_app()
        pid = self.session_service.require_current_pid()
        online_session = self.session_service.frida_device.attach(pid)
        rpc_path = self.context.hookers_js_dir / "rpc.js"
        rpc_source = self.workspace_service.get_resource_script("rpc.js")
        resource_rpc = self.session_service._compose_script_code(
            rpc_path,
            rpc_source,
            append_cleanup_warp=False,
        )
        online_script = (
            online_session.create_script(resource_rpc, runtime="v8")
            if use_v8
            else online_session.create_script(resource_rpc)
        )
        online_script.on("message", self.session_service.handle_script_message)
        online_script.load()
        return online_session, online_script

    def _attach_rpc(self, use_v8: bool = False):
        # 默认沿用短连接；GUI 可显式开启持久 RPC 复用模式。
        if not self._persistent_enabled:
            return self._create_rpc_resources(use_v8=use_v8)

        app = self.session_service.require_current_app()
        pid = self.session_service.require_current_pid()
        if (
            self._persistent_session is not None
            and self._persistent_script is not None
            and self._persistent_package_name == app.identifier
            and self._persistent_pid == pid
            and self._persistent_use_v8 == use_v8
        ):
            return self._persistent_session, self._persistent_script

        self.invalidate_persistent_session()
        online_session, online_script = self._create_rpc_resources(use_v8=use_v8)
        self._persistent_session = online_session
        self._persistent_script = online_script
        self._persistent_package_name = app.identifier
        self._persistent_pid = pid
        self._persistent_use_v8 = use_v8
        return online_session, online_script

    def call(self, method_name: str, *args, use_v8: bool = False):
        # 统一 RPC 入口。
        # CLI 默认仍然是短连接；GUI 可开启持久模式减少重复 attach/load。
        online_session = None
        online_script = None
        try:
            online_session, online_script = self._attach_rpc(use_v8=use_v8)
            rpc_method = getattr(online_script.exports_sync, method_name, None)
            if rpc_method is None:
                raise RuntimeError(f"RPC method not found: {method_name}")
            return rpc_method(*args)
        except Exception:
            if self._persistent_enabled:
                self.invalidate_persistent_session()
            raise
        finally:
            if not self._persistent_enabled:
                self._cleanup_rpc_resources(online_session, online_script)

    def generate_hook_script(self, hook_cmd_arg: str, save_path: str | None = None) -> Path:
        # 根据类名/方法选择器生成 hook 脚本并保存到工作目录。
        app = self.session_service._require_current_app()

        package_name = app.identifier
        app_version = app.version or "unknown"
        class_name = hook_cmd_arg
        method_selector = "*"
        file_method_name = "allfunc"
        separator_index = hook_cmd_arg.find(":")
        if separator_index > 0:
            class_name = hook_cmd_arg[:separator_index]
            method_selector = hook_cmd_arg[separator_index + 1 :].strip()
            if method_selector.startswith("<init>"):
                method_selector = method_selector.replace("<init>", "_", 1)
                file_method_name = "_init"
            else:
                method_name_for_file = method_selector.split("(", 1)[0].strip()
                file_method_name = method_name_for_file or "allfunc"
            if "(" in method_selector and ")" in method_selector:
                signature_suffix = method_selector[
                    method_selector.find("(") + 1 : method_selector.rfind(")")
                ]
                signature_suffix = re.sub(
                    r"[^0-9A-Za-z_.$]+", "_", signature_suffix
                ).strip("_")
                if signature_suffix:
                    file_method_name = f"{file_method_name}.{signature_suffix}"

        if not self.call("containsclass", class_name):
            raise RuntimeError(f"Class Not Found {class_name}")

        jscode = self.call("hookjs", class_name, method_selector)
        generation_jscode = f"\n//{hook_cmd_arg}\n{jscode}"
        if save_path is None:
            default_filename = (
                class_name.replace(":", ".").replace("$", ".").replace("__", ".")
                + f".{file_method_name}.js"
            )
            target_path = self.workspace_service.script_dir(package_name) / default_filename
        else:
            target_path = self.workspace_service.script_dir(package_name) / save_path

        prepare = self.workspace_service.get_resource_script("_hook_js_prepare.js")
        enhance = self.workspace_service.get_resource_script("_hook_js_enhance.js")
        full_script = (
            prepare
            + "\n"
            + generation_jscode
            + "\n\n\n\n\n//---------------------may be you need--------------------\n\n"
            + enhance
        )
        # 这里保留原项目生成脚本时附带的元信息，方便后续追溯来源。
        wrapped = f"//cracked by {app.name} {app_version}\n" + f"//{hook_cmd_arg}\n\n" + full_script
        content = jsbeautifier.beautify(wrapped) if jsbeautifier is not None else wrapped
        self.workspace_service.create_working_file(target_path, content)
        return target_path

    def activitys(self):
        # 获取当前 Activity 信息。
        return self.call("activitys")

    def services(self):
        # 获取当前 Service 信息。
        return self.call("services")

    def object_info(self, object_id: str):
        # 获取对象或类的详细信息。
        return self.call("objectinfo", object_id)

    def object_to_explain(self, object_id: str):
        # 对指定对象做进一步解释分析。
        return self.call("objecttoexplain", object_id)

    def view_info(self, view_id: str):
        # 获取 View 详细信息。
        return self.call("viewinfo", view_id)

    def start_web_server(self, dex_file: str, all_class: list[str]) -> str:
        # 启动设备侧 HTTP 服务，并尝试提取返回地址。
        text = self.call("starthttpserver", dex_file, ",".join(all_class))
        match = re.search(r"http:[^s]+:[\d]+", text)
        self.context.webserver_url = match.group(0) if match else None
        return text
