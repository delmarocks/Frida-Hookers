from __future__ import annotations

from pathlib import Path

from .device_service import DeviceService
from .models import HookSession, HookerContext
from .workspace_service import WorkspaceService

CONSOLE_BRIDGE_JS = r"""
(function () {
    function toText(args) {
        try {
            return Array.prototype.slice.call(args).map(function (item) {
                if (typeof item === "string") {
                    return item;
                }
                try {
                    return JSON.stringify(item);
                } catch (_) {
                    return String(item);
                }
            }).join(" ");
        } catch (_) {
            return "[console bridge serialize failed]";
        }
    }

    function bridge(level, originalFn) {
        return function () {
            var text = toText(arguments);
            try {
                send({
                    type: "console",
                    level: level,
                    message: text
                });
            } catch (_) {
            }
            if (typeof originalFn === "function") {
                try {
                    originalFn.apply(console, arguments);
                } catch (_) {
                }
            }
        };
    }

    if (typeof console !== "undefined") {
        console.log = bridge("log", console.log);
        console.warn = bridge("warn", console.warn);
        console.error = bridge("error", console.error);
    }
})();
"""


class SessionService:
    # 负责 Frida attach/spawn 会话的创建、维护和清理。
    def __init__(
        self,
        context: HookerContext,
        device_service: DeviceService,
        workspace_service: WorkspaceService,
    ) -> None:
        self.context = context
        self.device_service = device_service
        self.workspace_service = workspace_service

    @property
    def frida_device(self):
        # 懒校验 Frida 设备对象。
        if self.context.frida_device is None:
            raise RuntimeError("Frida device is not ready")
        return self.context.frida_device

    def _on_message(self, message, data) -> None:
        # 统一处理脚本消息，后续 GUI 也可以复用这条日志链路。
        msg_type = message.get("type")
        if msg_type == "send":
            payload = message.get("payload")
            if isinstance(payload, dict) and payload.get("type") == "console":
                level = payload.get("level", "log")
                text = payload.get("message", "")
                prefix = "[JS]"
                if level == "warn":
                    prefix = "[JS:WARN]"
                elif level == "error":
                    prefix = "[JS:ERROR]"
                self.context.emit(f"{prefix} {text}")
                return
            if isinstance(payload, dict) and payload.get("type") == "save_decrypt_output":
                package_name = payload.get("package")
                if not package_name and self.context.current_app is not None:
                    package_name = self.context.current_app.identifier
                self.workspace_service.save_decrypt_output(
                    package_name or "unknown_package",
                    payload.get("filename") or "decrypt_output.txt",
                    payload.get("content") or "",
                )
                return
            self.context.emit(f"[*] {payload}")
            return
        if msg_type == "error":
            error_text = (
                message.get("stack") or message.get("description") or str(message)
            )
            self.context.emit(f"[!] {error_text}")
            hint = self._script_runtime_hint(error_text)
            if hint:
                self.context.emit(f"[!] {hint}")
            return
        self.context.emit(str(message))

    def handle_script_message(self, message, data) -> None:
        # 对外公开的脚本消息处理入口，避免其他服务依赖私有实现。
        self._on_message(message, data)

    def _load_script_code(self, script_path: Path) -> str:
        # 读取脚本，并在尾部拼接项目内置清理脚本。
        source = self.workspace_service.read_local_file(script_path)
        if source is None:
            raise FileNotFoundError(f"脚本不存在: {script_path}")
        return self._compose_script_code(script_path, source)

    def _compose_script_code(
        self,
        script_path: Path,
        source: str,
        *,
        append_cleanup_warp: bool = True,
    ) -> str:
        warp = self.workspace_service.get_resource_script("_hook_js_warp.js")
        # 先注入 console bridge，再加载业务脚本和清理 warp，
        # 这样 hook.js 中大量 console.log(...) 也会被宿主捕获到。
        return (
            CONSOLE_BRIDGE_JS + "\n\n" + source + ("\n\n\n" + warp if append_cleanup_warp else "")
        )

    def _build_session(
        self,
        session,
        script,
        script_path: Path,
        mode: str,
        *,
        use_v8: bool = False,
        auto_follow_attempted: bool = False,
        auto_follow_count: int = 0,
    ) -> HookSession:
        # 把底层 Frida 对象包装成统一会话模型并写回上下文。
        hook_session = HookSession(
            session=session,
            script=script,
            script_path=script_path,
            mode=mode,
            use_v8=use_v8,
            auto_follow_attempted=auto_follow_attempted,
            auto_follow_count=auto_follow_count,
        )
        self.context.active_session = hook_session
        return hook_session

    def _script_runtime_hint(self, error_text: str) -> str | None:
        normalized = (error_text or "").lower()
        if "referenceerror: 'java' is not defined" in normalized or 'referenceerror: "java" is not defined' in normalized:
            return (
                "当前脚本依赖 Java bridge。"
                "在 Frida 16.2.1 下这里继续报 Java 未定义时，通常意味着目标进程还没进入 Java 运行时，"
                "或脚本注入时机过早。"
            )
        if "typeerror: not a function" in normalized and "hook_native_anti_debug" in normalized:
            return (
                "当前脚本里的 native 反调试代码疑似仍在调用旧版 Frida 全局 API。"
                "请优先检查 Module.* / Process.* 相关写法。"
            )
        return None

    def _cleanup_transient_session(self, session, script) -> None:
        # attach/spawn 启动过程中如果在登记 active_session 之前失败，
        # 这里负责兜底释放临时创建出来的 Frida 资源，避免留下半残会话。
        if script is not None:
            try:
                script.unload()
            except Exception:
                pass
        if session is not None:
            try:
                session.detach()
            except Exception:
                pass

    def _require_current_app(self):
        # 返回当前应用上下文，并在缺失时立即报错。
        if self.context.current_app is None:
            raise RuntimeError("当前未选择应用")
        return self.context.current_app

    def require_current_app(self):
        # 对外公开的当前应用获取入口。
        return self._require_current_app()

    def _require_current_pid(self) -> int:
        # attach/RPC 前强制校验 PID，避免向 Frida 传入空值。
        app = self._require_current_app()
        if app.pid is None:
            raise RuntimeError("当前应用没有可用 PID，请先启动或刷新应用")
        return app.pid

    def require_current_pid(self) -> int:
        # 对外公开的 PID 获取入口。
        return self._require_current_pid()

    def attach_script(self, script_name_or_path: str, use_v8: bool = False) -> HookSession:
        app = self._require_current_app()
        script_path = self.workspace_service.resolve_script_path(
            script_name_or_path, app.identifier
        )
        script_jscode = self._load_script_code(script_path)
        session = None
        script = None
        try:
            pid = self._require_current_pid()
            try:
                session = self.frida_device.attach(pid)
            except Exception as exc:
                refreshed_pid = self.device_service.refresh_current_app_pid(app.identifier)
                if refreshed_pid is None or refreshed_pid == pid:
                    raise RuntimeError(
                        f"attach stage failed for {app.identifier} (pid {pid}): {exc}"
                    ) from exc
                self.context.emit(
                    f"[*] 检测到 attach 目标 PID 已变化，重试 attach: {pid} -> {refreshed_pid}"
                )
                session = self.frida_device.attach(refreshed_pid)
            script = (
                session.create_script(script_jscode, runtime="v8")
                if use_v8
                else session.create_script(script_jscode)
            )
            script.on("message", self._on_message)
            script.load()
            return self._build_session(session, script, script_path, "attach", use_v8=use_v8)
        except Exception:
            self._cleanup_transient_session(session, script)
            raise

    def spawn_script(self, script_name_or_path: str, use_v8: bool = False) -> HookSession:
        app = self._require_current_app()
        script_path = self.workspace_service.resolve_script_path(
            script_name_or_path, app.identifier
        )
        script_jscode = self._load_script_code(script_path)
        pid = None
        session = None
        script = None
        previous_pid = app.pid
        try:
            try:
                pid = self.frida_device.spawn([app.identifier])
            except Exception as exc:
                raise RuntimeError(
                    f"spawn stage failed for {app.identifier}: {exc}"
                ) from exc
            app.pid = pid
            try:
                session = self.frida_device.attach(pid)
            except Exception as exc:
                raise RuntimeError(
                    f"attach stage failed for {app.identifier} (pid {pid}): {exc}"
                ) from exc
            try:
                script = (
                    session.create_script(script_jscode, runtime="v8")
                    if use_v8
                    else session.create_script(script_jscode)
                )
                script.on("message", self._on_message)
                script.load()
            except Exception as exc:
                raise RuntimeError(
                    f"script load stage failed for {script_path.name}: {exc}"
                ) from exc

            try:
                release_version = int(
                    self.device_service.adb_device.prop.get(
                        "ro.build.version.release"
                    ).split(".", 1)[0]
                )
                if release_version >= 12:
                    self.frida_device.resume(pid)
                else:
                    self.frida_device.resume(app.identifier)
            except Exception as exc:
                raise RuntimeError(
                    f"resume stage failed for {app.identifier} (pid {pid}): {exc}"
                ) from exc
            return self._build_session(session, script, script_path, "spawn", use_v8=use_v8)
        except Exception:
            app.pid = previous_pid
            self._cleanup_transient_session(session, script)
            if pid is not None:
                try:
                    self.frida_device.resume(pid)
                except Exception:
                    pass
            raise

    def stop_active_session(self) -> None:
        # 停止当前活动脚本并释放 Frida 资源。
        hook_session = self.context.active_session
        if hook_session is None:
            return
        # 先从共享上下文中摘掉当前会话，避免停止过程中 UI 仍然把它当成活跃会话。
        self.context.active_session = None

        if hook_session.script is not None:
            try:
                hook_session.script.unload()
            except Exception as exc:
                self.context.emit(f"脚本卸载异常: {exc}")
        if hook_session.session is not None:
            try:
                hook_session.session.detach()
            except Exception as exc:
                self.context.emit(f"会话清理异常: {exc}")

    def restart_current_app(self) -> None:
        # 重启当前应用，并把新的 PID 回写到上下文。
        app = self._require_current_app()
        self.context.emit(f"正在重启 {app.name}，请稍候...")
        self.device_service.adb_device.app_stop(app.identifier)
        pid, name = self.device_service.start_app(app.identifier)
        app.pid = pid
        if name:
            app.name = name
