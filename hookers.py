from __future__ import annotations

import traceback
import warnings
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import NestedCompleter, WordCompleter
from prompt_toolkit.patch_stdout import patch_stdout
from wcwidth import wcswidth

from core.device_service import DeviceService
from core.models import HookerContext
from core.rpc_service import RpcService
from core.session_service import SessionService
from core.workspace_service import WorkspaceService

warnings.filterwarnings("ignore", category=SyntaxWarning)

ANSI_GREEN = "\033[32m"
ANSI_RED = "\033[31m"
ANSI_RESET = "\033[0m"


def pad_display(text, width: int) -> str:
    # 按“显示宽度”补齐文本，而不是按字符长度补齐。
    # 这样中英文混排时，表格列能尽量对齐。
    text = str(text)
    padding = width - wcswidth(text)
    return text + " " * max(padding, 0)


def format_workspace_status(has_workspace: bool) -> str:
    # 用红绿文字标识当前应用是否已经建立工作目录。
    if has_workspace:
        return f"{ANSI_GREEN}√{ANSI_RESET}"
    return f"{ANSI_RED}×{ANSI_RESET}"


class HookersCli:
    # 这个类是当前命令行版本的总控层。
    #
    # 它本身不直接处理 adb/frida 细节，而是把工作交给四个 service：
    # 1. DeviceService：设备连接、Frida 环境、应用列表、应用前台化
    # 2. WorkspaceService：工作目录、脚本副本、APK、输出文件
    # 3. SessionService：attach/spawn、会话生命周期、脚本消息处理
    # 4. RpcService：rpc.js 调用、hook 脚本生成、对象信息查询
    #
    # CLI 这一层只负责：
    # 1. 组织交互流程
    # 2. 把用户命令分发到对应 service
    # 3. 在控制台里展示结果
    def __init__(self, project_root: Path) -> None:
        # HookerContext 是整套系统的共享状态中心。
        # service 之间不会互相复制状态，而是都围绕同一个 context 工作。
        self.context = HookerContext.from_project_root(project_root)

        # 初始化各层 service。
        self.device_service = DeviceService(self.context)
        self.workspace_service = WorkspaceService(self.context)
        self.session_service = SessionService(
            self.context,
            self.device_service,
            self.workspace_service,
        )
        self.rpc_service = RpcService(
            self.context,
            self.session_service,
            self.workspace_service,
        )

        # PromptSession 负责命令行交互输入。
        self.cmd_session = PromptSession()

    def bootstrap(self) -> None:
        # 启动阶段的初始化入口。
        #
        # 只有真正 run() 时才会去连设备、起 frida-server。
        #
        # 这一步做四件事：
        # 1. 连接 ADB 设备
        # 2. 启动 frida-server
        # 3. 部署 radar.dex
        # 4. 刷新应用列表缓存
        self.device_service.connect()
        self.device_service.start_frida_server()
        self.device_service.deploy_radar_dex()
        self.device_service.refresh_applications()

    def list_apps(self) -> list[str]:
        # 打印当前缓存中的应用列表，并返回包名数组。
        #
        # 这里不重新请求设备，而是读取 self.context.apps。
        # 所以如果想刷新列表，需要先调用 DeviceService.refresh_applications()。
        print(
            f"{pad_display('进程号', 6)}\t"
            f"{pad_display('APP名称', 20)}\t"
            f"{pad_display('包名', 35)}\t"
            "是否有对应工作目录"
        )

        identifiers: list[str] = []
        # 按 PID 从小到大排序；没有 PID 的应用排在最后。
        sorted_apps = sorted(
            self.context.apps,
            key=lambda app: (app.pid is None, app.pid or 0),
        )

        for app in sorted_apps:
            has_workspace = self.workspace_service.workspace_dir(app.identifier).is_dir()
            print(
                f"{pad_display(app.pid, 6)}\t"
                f"{pad_display(app.name, 20)}\t"
                f"{pad_display(app.identifier, 35)}\t"
                f"{format_workspace_status(has_workspace)}"
            )
            identifiers.append(app.identifier)
        return identifiers

    def current_js_files(self) -> list[str]:
        # 读取“当前选中 app”的工作区脚本名。
        #
        # 这个函数主要给自动补全器使用：
        # attach xxx.js / spawn xxx.js 时，候选项来自这里。
        if self.context.current_app is None:
            return []
        return self.workspace_service.script_names(self.context.current_app.identifier)

    def build_debug_mode_completer(self) -> NestedCompleter:
        # 构建调试模式下的二级命令补全器。
        #
        # 固定命令是 help/ls/restart/pid 这些，
        # attach / spawn 的候选参数则动态取自当前工作目录里的 js 文件。
        js_words = {filename: None for filename in self.current_js_files()}
        return NestedCompleter.from_nested_dict(
            {
                "help": None,
                "h": None,
                "activitys": None,
                "a": None,
                "services": None,
                "s": None,
                "object": None,
                "o": None,
                "oe": None,
                "view": None,
                "v": None,
                "gs": None,
                "ls": None,
                "restart": None,
                "pid": None,
                "uid": None,
                "exit": None,
                "exit()": None,
                "quit": None,
                "q": None,
                "attach": js_words,
                "spawn": js_words,
            }
        )

    def print_debug_help(self) -> None:
        # 输出调试模式下的命令帮助。
        #
        # 这里列出来的命令，和 entry_debug_mode() 里的分支一一对应。
        help_msg = [
            ("help / h", "显示帮助信息"),
            ("activitys / a", "显示当前 Activity 信息"),
            ("services / s", "显示当前 Service 信息"),
            ("object / o <id|class>", "查看对象或类实例信息"),
            ("oe <objectId>", "继续展开分析指定对象"),
            ("view / v <id>", "查看 View 详细信息"),
            ("gs <class[:method[(args)]]>", "生成类、方法或精确重载的 hook 脚本"),
            ("ls", "列出当前应用目录下所有 js 脚本"),
            ("attach <script.js>", "attach 模式执行脚本"),
            ("spawn <script.js>", "spawn 模式执行脚本"),
            ("restart", "重启当前 app"),
            ("pid", "显示当前 app 的 PID"),
            ("uid", "显示当前 app 的 UID"),
            ("exit/exit()/quit/q", "退出当前 app 调试模式"),
        ]
        print("可用命令:")
        for cmd, desc in help_msg:
            print(f"  {cmd:<30} {desc}")

    def list_working_dir(self) -> None:
        # 列出当前 app 工作目录里的 js 脚本。
        #
        # 注意这里看的不是全局模板目录 js/，
        # 而是某个包名对应的工作区目录 workspaces/<package>/js/。
        if self.context.current_app is None:
            return

        js_files = self.workspace_service.script_names(self.context.current_app.identifier)
        if not js_files:
            print("当前应用目录下没有可用的 js 脚本")
            return

        print("当前可用脚本:")
        for filename in js_files:
            print(f"  {filename}")

    def execute_script(self, script_file: str, is_spawn: bool = False) -> None:
        # 执行指定脚本，并在前台维持会话直到用户手动停止。
        #
        # 这里自己不处理 Frida 会话细节，而是调用 SessionService。
        # CLI 负责的只是：
        # 1. 根据模式选择 attach 或 spawn
        # 2. 阻塞等待用户按 Ctrl+C
        # 3. 最后统一清理活动会话
        #
        # just_trust_me.js 在原项目里依赖 v8 runtime，这里继续保留这个兼容逻辑。
        use_v8 = "just_trust_me.js" in script_file
        try:
            if is_spawn:
                self.session_service.spawn_script(script_file, use_v8=use_v8)
            else:
                self.session_service.attach_script(script_file, use_v8=use_v8)

            # 只要 active_session 还存在，就说明脚本仍在运行。
            # 这里故意保持一个空 prompt，让用户可以观察日志输出，
            # 并在需要时用 Ctrl+C 停止。
            while self.context.active_session is not None:
                try:
                    with patch_stdout():
                        self.cmd_session.prompt("CTRL + C to stop > ", handle_sigint=True)
                except KeyboardInterrupt:
                    print(f"中断退出... {script_file}")
                    break
                except EOFError:
                    print("错误，退出中...")
                    break
        except Exception:
            # 逆向工具更重视问题暴露，所以这里直接打印完整堆栈。
            print(traceback.format_exc())
        finally:
            self.session_service.stop_active_session()
            print(f"{script_file} 已清理并解除与目标进程的连接")

    def select_app(self, identifier: str) -> None:
        # 选中某个包名后，进入“单应用上下文”。
        #
        # 这一步是从应用列表模式切换到调试模式的关键桥梁：
        # 1. 确保目标 app 在前台并获取 PID/版本/APK 路径等信息
        # 2. 确保本地工作目录存在，脚本副本和 APK 已准备好
        app = self.device_service.ensure_app_in_foreground(identifier)
        self.workspace_service.ensure_workspace(app)

    def entry_debug_mode(self) -> None:
        # 进入单应用调试循环。
        #
        # 进入这里之后，说明当前已经选中了一个 app，
        # 后续命令都默认围绕 self.context.current_app 工作。
        while True:
            try:
                prompt_label = (
                    self.context.current_app.name
                    if self.context.current_app is not None
                    else "hooker"
                )
                hooker_cmd = self.cmd_session.prompt(
                    f"{prompt_label} > ",
                    completer=self.build_debug_mode_completer(),
                ).strip()

                if not hooker_cmd:
                    continue

                if hooker_cmd in ("exit", "quit", "exit()", "q"):
                    # 退出当前 app 的调试上下文，回到顶层应用选择循环。
                    print("退出当前调试模式")
                    break

                if hooker_cmd in ("help", "h"):
                    self.print_debug_help()
                    continue

                if hooker_cmd in ("activitys", "a"):
                    # 这类信息查询都走 RpcService。
                    print(self.rpc_service.activitys())
                    continue

                if hooker_cmd in ("services", "s"):
                    print(self.rpc_service.services())
                    continue

                if hooker_cmd == "ls":
                    self.list_working_dir()
                    continue

                if hooker_cmd == "restart":
                    # 重启 app 后，SessionService 会把新 PID 写回 context。
                    self.session_service.restart_current_app()
                    continue

                if hooker_cmd == "pid":
                    print(self.context.current_app.pid if self.context.current_app else None)
                    continue

                if hooker_cmd == "uid":
                    print(self.context.current_app.uid if self.context.current_app else None)
                    continue

                if hooker_cmd.startswith("object ") or hooker_cmd.startswith("o "):
                    object_id = hooker_cmd.split(maxsplit=1)[1]
                    print(self.rpc_service.object_info(object_id))
                    continue

                if hooker_cmd.startswith("oe "):
                    object_id = hooker_cmd.split(maxsplit=1)[1]
                    print(self.rpc_service.object_to_explain(object_id))
                    continue

                if hooker_cmd.startswith("view ") or hooker_cmd.startswith("v "):
                    view_id = hooker_cmd.split(maxsplit=1)[1]
                    print(self.rpc_service.view_info(view_id))
                    continue

                if hooker_cmd.startswith("gs "):
                    # gs = generate script。
                    # 通过 rpc.js 去设备侧分析类/方法，然后把生成的脚本落到本地工作区。
                    hook_path = self.rpc_service.generate_hook_script(
                        hooker_cmd.split(maxsplit=1)[1].strip()
                    )
                    print(f"frida hook script: {hook_path.name}")
                    continue

                if hooker_cmd.startswith("attach "):
                    # attach 模式：附加到已运行进程。
                    self.execute_script(hooker_cmd.split(maxsplit=1)[1], is_spawn=False)
                    continue

                if hooker_cmd.startswith("spawn "):
                    # spawn 模式：先拉起目标进程，再在更早阶段注入。
                    self.execute_script(hooker_cmd.split(maxsplit=1)[1], is_spawn=True)
                    continue

                print(f"未知命令: {hooker_cmd}，输入 help 查看可用命令")
            except (EOFError, KeyboardInterrupt):
                print("\n退出当前调试模式")
                break
            except Exception:
                print(traceback.format_exc())

    def run(self) -> None:
        # CLI 主循环。
        #
        # 顶层完整执行链路是：
        # main()
        # -> HookersCli(...)
        # -> run()
        # -> bootstrap()
        # -> list_apps()
        # -> select_app()
        # -> entry_debug_mode()
        self.bootstrap()

        while True:
            try:
                print("Frida-Hookers 安卓逆向集成工具 2.0")
                print("-" * 95)

                identifiers = self.list_apps()

                # 顶层输入只支持三类候选：
                # 1. 当前应用列表里的包名
                # 2. exit / quit
                # 3. refresh，用于重新拉取应用列表
                first_level_words = identifiers + ["exit", "quit", "refresh"]
                identifier = self.cmd_session.prompt(
                    "hooker(包名): ",
                    completer=WordCompleter(
                        first_level_words,
                        ignore_case=False,
                        match_middle=True,
                        WORD=True,
                    ),
                ).strip()

                if identifier in ("exit", "quit", "exit()"):
                    print("ByeBye!")
                    return

                if identifier == "refresh":
                    # 只刷新应用缓存，不重启整个 CLI。
                    self.device_service.refresh_applications()
                    continue

                if identifier not in identifiers:
                    print("包名不存在，请重新输入")
                    continue

                # 一旦进入这里，说明用户已经选中了一个有效包名。
                # 接下来切到单应用调试模式。
                self.select_app(identifier)
                self.entry_debug_mode()
            except (EOFError, KeyboardInterrupt):
                return


def main() -> int:
    # 命令行入口保持尽量薄。
    # 它只负责创建 CLI 对象并启动，不在这里堆业务逻辑。
    cli = HookersCli(Path(__file__).resolve().parent)
    cli.run()
    return 0


if __name__ == "__main__":
    # 只有直接运行 hookers.py 时才进入 CLI。
    # 这样将来 GUI 或测试代码 import 这个模块时，不会再触发“导入即执行”。
    raise SystemExit(main())
