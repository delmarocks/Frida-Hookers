from __future__ import annotations

from pathlib import Path


# 通用状态 / 忙碌文案
READY = "空闲"
ERROR_OCCURRED = "发生错误"
GUI_READY_HINT = "GUI 已就绪，先点击“准备环境并刷新 App”"

PREPARING_DEVICE = "正在准备设备环境"
INITIALIZING_WORKSPACE = "正在初始化工作目录并刷新列表"
WORKSPACE_READY = "工作目录已初始化"
SYNCED_APPS = "已同步设备 {count} 个应用"
STARTING_HOOK = "正在启动注入"
DETECTING_NETWORK_STACK = "正在探测网络栈"
PRINTING_OKHTTP_INTERCEPTORS = "正在分析 OkHttp 拦截器"
CAPTURING_OKHTTP_TRAFFIC = "正在启动 OkHttp 抓包"
HOOKING_REGISTER_NATIVES = "正在监控 JNI 注册"
FINDING_ANTI_FRIDA_SO = "正在定位反 Frida SO"
TRACING_CLICK_EVENTS = "正在监听点击事件"
TRACING_EDIT_TEXT = "正在监听输入框"
TRACING_TEXT_VIEW = "正在监听文本视图"
TRACING_URLS = "正在监听 URL"
TRACING_ACTIVITY_EVENTS = "正在监听页面跳转"
TRACING_ENCRYPTION_ALGO = "正在监听加密调用"
TRACING_DIGEST_HMAC = "正在监听摘要/HMAC"
TRACING_JNI_METHODS = "正在跟踪 JNI 调用"
TRACING_INIT_PROC = "正在跟踪 init_proc（需地址）"
BYPASSING_ROOT_DETECT = "正在绕过常见 Root 检测"
BYPASSING_VPN_DETECT = "正在绕过常见 VPN 检测"
STARTING_ADVANCED_FRIDA = "正在启动高级 Frida 启动器"
STOPPING_HOOK = "正在停止 Hook"
STOPPING_FRIDA_SERVER = "正在停止 Frida Server"
RESTARTING_APP = "正在重启 App"
GENERATING_HOOK_SCRIPT = "正在生成 Hook 脚本"
LOADING_ACTIVITIES = "正在加载 Activity"
LOADING_SERVICES = "正在加载 Service"
LOADING_OBJECT_INFO = "正在加载对象信息"
EXPLAINING_OBJECT = "正在解释对象"
LOADING_VIEW_INFO = "正在加载 View 信息"
SCANNING_APK = "正在扫描 APK"
RUNNING_TERMINAL_COMMAND = "正在执行终端命令"


# 对话框标题 / 正文
ERROR_DIALOG_TITLE = "执行失败"
ERROR_LOG_PREFIX = "[!]"
ERROR_HINT_PREFIX = "[!] 建议："

APK_SCAN_COMPLETE = "APK 扫描完成"
APK_SCAN_TITLE = "未选择 APK"
APK_SCAN_BODY = "请先选择一个本地 APK 文件。"

APP_NOT_SELECTED_TITLE = "未选择 App"
APP_NOT_SELECTED_BODY = "请先准备环境并选择一个目标 App。"
WORKSPACE_APP_NOT_SELECTED_BODY = "请先选择一个目标 App。"

SCRIPT_NOT_SELECTED_TITLE = "未选择脚本"
SCRIPT_NOT_SELECTED_BODY = "请先在左侧选择一个 .js 脚本。"

MISSING_TARGET_TITLE = "缺少目标"
MISSING_HOOK_TARGET_BODY = "请输入类名或 类名:方法。"
INSPECT_TARGET_BODY = "请输入对象 ID、类名或 View ID。"

PREPARE_DONE_TITLE = "准备已完成"
PREPARE_DONE_AUTO_SELECT = "准备已完成，已自动选中当前前台 App：{package}"
PREPARE_DONE_SELECT_APP = "准备已完成，请选择目标 App。"
PREPARE_READY_STATE = "环境已就绪，可以开始注入"
PREPARE_NO_APPS_STATE = "环境已就绪，但没有枚举到应用"

NO_APPS_FOUND_TITLE = "未发现应用"
NO_APPS_FOUND_BODY = "准备已完成，但当前没有枚举到可选择的 APK 包名。"

GENERATED_TITLE = "脚本已生成"
GENERATED_BODY = "脚本已保存到：\n{script_path}"
RESULT_DIALOG_CLOSE_TEXT = "关闭"
NO_RESULT = "无结果"

LOG_FILE_UNAVAILABLE_TITLE = "日志文件不可用"
LOG_FILE_UNAVAILABLE_BODY = "无法写入日志文件：{error}"
LOG_FILE_UNAVAILABLE_STATUS = "日志文件不可用: {error}"
LOG_WRITE_FAILED_STATUS = "日志写入失败: {error}"
LOG_DISPLAY_CLEARED = "日志显示已清空"


# 状态标签 / 提示
HOOK_STOPPED_STATUS = "当前 Hook 已停止"
HOOK_STOPPED_STATE = "会话已停止"
FRIDA_SERVER_STOPPED = "Frida Server 已停止"
APK_SCAN_EMPTY_STATUS = "当前未选择 APK"
APK_SCAN_TARGET_STATUS = "当前扫描目标：{name}"
JNI_TARGET_SO_DIALOG_TITLE = "输入目标 SO"
JNI_TARGET_SO_DIALOG_LABEL = "请输入要跟踪的 SO 文件名（例如 libxxx.so）："
JNI_TARGET_SO_REQUIRED_BODY = "请输入要跟踪的 SO 文件名。"
JNI_TARGET_SO_INVALID_BODY = "请输入合法的 SO 文件名，例如 libxxx.so。"
TRACE_INIT_PROC_DIALOG_TITLE = "输入 init_proc 参数"
TRACE_INIT_PROC_SO_LABEL = "SO 文件名"
TRACE_INIT_PROC_START_ADDR_LABEL = "startAddr"
TRACE_INIT_PROC_END_ADDR_LABEL = "endAddr"
TRACE_INIT_PROC_REQUIRED_SO_BODY = "请输入要跟踪的 SO 文件名。"
TRACE_INIT_PROC_INVALID_SO_BODY = "请输入合法的 SO 文件名，例如 libxxx.so。"
TRACE_INIT_PROC_REQUIRED_START_BODY = "请输入 startAddr。"
TRACE_INIT_PROC_REQUIRED_END_BODY = "请输入 endAddr。"
TRACE_INIT_PROC_INVALID_ADDR_BODY = "请输入合法的十六进制地址，例如 0x1234。"
TRACE_INIT_PROC_RANGE_BODY = "endAddr 不能小于 startAddr。"
FOCUS_LOG_ENABLED = "已进入专注日志模式"
FOCUS_LOG_DISABLED = "已恢复默认布局"
FOCUS_LOG_ENABLE_BUTTON = "专注日志"
FOCUS_LOG_DISABLE_BUTTON = "恢复布局"
FOCUS_LOG_ENABLE_TOOLTIP = "一键最大化右侧日志区"
FOCUS_LOG_DISABLE_TOOLTIP = "退出专注日志模式并恢复原布局"
QUICK_HOOK_GROUP_NETWORK = "网络与抓包"
QUICK_HOOK_GROUP_UI = "UI 观察"
QUICK_HOOK_GROUP_NATIVE = "Native / JNI"
QUICK_HOOK_GROUP_CRYPTO = "加密分析"
QUICK_HOOK_GROUP_BYPASS = "对抗与绕过"
ATTACH_MODE_BADGE = "当前模式：Attach"
SPAWN_MODE_BADGE = "当前模式：Spawn"
TERMINAL_SECTION_TITLE = "CLI 终端"
TERMINAL_CONTEXT_EMPTY = "CLI 命令模式（当前 App） | 请先准备环境并选择目标 App"
TERMINAL_CONTEXT_READY = "CLI 命令模式（当前 App） | {package} >"
TERMINAL_CONTEXT_BUSY_EMPTY = "CLI 命令模式（当前 App） | 命令执行中..."
TERMINAL_CONTEXT_BUSY_READY = "CLI 命令模式（当前 App） | {package} | 命令执行中..."
TERMINAL_PROMPT_EMPTY = "hooker >"
TERMINAL_PROMPT_READY = "{package} >"
CLI_MODE_ENTER_BUTTON = "进入 CLI 模式"
CLI_MODE_EXIT_BUTTON = "退出 CLI 模式"
TERMINAL_INPUT_PLACEHOLDER = "输入 help、ls、pid、activitys、object、gs、attach、spawn、restart、stop ..."
TERMINAL_EXECUTE_BUTTON = "执行"
TERMINAL_CLEAR_BUTTON = "清空"
TERMINAL_HELP_LOG = """[CMD:RESULT] 可用命令:
[CMD:RESULT] 基础命令:
[CMD:RESULT]   help / h                       显示帮助信息
[CMD:RESULT]   ls                             列出当前已选 App 的工作区脚本和内置脚本
[CMD:RESULT]   pid                            显示当前 App PID
[CMD:RESULT]   uid                            显示当前 App UID
[CMD:RESULT] 
[CMD:RESULT] App 命令:
[CMD:RESULT]   apps                           显示当前缓存 App 列表
[CMD:RESULT]   refresh                        刷新当前 App 列表
[CMD:RESULT]   select <package>               选中目标 App
[CMD:RESULT] 
[CMD:RESULT] 查询命令:
[CMD:RESULT]   activitys / a                  显示当前 Activity 信息
[CMD:RESULT]   services / s                   显示当前 Service 信息
[CMD:RESULT]   object / o <id|class>          查看对象或类实例信息
[CMD:RESULT]   oe <objectId>                  继续展开分析指定对象
[CMD:RESULT]   view / v <id>                  查看 View 详细信息
[CMD:RESULT]   gs <class[:method[(args)]]>    生成 Hook 脚本
[CMD:RESULT] 
[CMD:RESULT] Hook 命令:
[CMD:RESULT]   attach <script.js>             Attach 模式执行脚本
[CMD:RESULT]   spawn <script.js>              Spawn 模式执行脚本
[CMD:RESULT]   restart                        重启当前 App
[CMD:RESULT]   stop                           停止当前 Hook
[CMD:RESULT] 
[CMD:RESULT] Shell 回退:
[CMD:RESULT]   未命中项目内命令时，将回退到持久 PowerShell 会话执行
[CMD:RESULT]   输入 exit / quit 只会结束 PowerShell 会话，不会关闭 GUI 终端
[CMD:RESULT] 
[CMD:RESULT] 示例:
[CMD:RESULT]   object demo.Target
[CMD:RESULT]   gs com.demo.A:onCreate
[CMD:RESULT]   attach okhttp.js
[CMD:RESULT]   select com.demo.app
"""
TERMINAL_COMMAND_ECHO = "[CMD] {prompt} {command}"
TERMINAL_RESULT_LOG = "[CMD:RESULT] {message}"
TERMINAL_UNKNOWN_COMMAND = "[CMD:RESULT] 未知命令：{command}，输入 help 查看可用命令"
TERMINAL_MISSING_ARGUMENT = "[CMD:RESULT] {command} 缺少参数。"
TERMINAL_STOP_NO_SESSION = "[CMD:RESULT] 当前没有正在运行的 Hook 会话。"
TERMINAL_HISTORY_EMPTY = ""
TERMINAL_SHELL_FALLBACK_LOG = "[TOOL] 未匹配项目命令，回退到 PowerShell"
TERMINAL_SHELL_SESSION_ENDED_LOG = "[TOOL] PowerShell 会话已结束"
TERMINAL_SHELL_START_FAILED_LOG = "[PS:ERR] PowerShell 会话启动失败"
TERMINAL_SHELL_STDERR_PREFIX = "[PS:ERR]"
TERMINAL_SHELL_BUSY_LOG = "[CMD:RESULT] 当前已有 Frida 外部命令正在执行，请稍后再试"
TERMINAL_EXTERNAL_COMMAND_BLOCKED = "[CMD:RESULT] 已阻止外部命令：{command}。当前仅允许包含 frida 的外部命令"
TERMINAL_COMPLETION_COMMAND_PREFIX = "命令"
TERMINAL_COMPLETION_SCRIPT_PREFIX = "脚本"
TERMINAL_COMPLETION_PACKAGE_PREFIX = "包名"
TERMINAL_LS_WORKSPACE_TITLE = "工作区脚本："
TERMINAL_LS_BUILTIN_TITLE = "内置脚本："
TERMINAL_LS_EMPTY = "（无）"
ADVANCED_FRIDA_BUTTON = "高级 Frida 启动"
ADVANCED_FRIDA_DIALOG_TITLE = "高级 Frida 启动"
ADVANCED_FRIDA_TARGET_APP_LABEL = "当前目标 App"
ADVANCED_FRIDA_MODE_LABEL = "当前模式"
ADVANCED_FRIDA_AVAILABLE_SCRIPTS_LABEL = "可选脚本"
ADVANCED_FRIDA_SELECTED_SCRIPTS_LABEL = "启动顺序"
ADVANCED_FRIDA_ADD_BUTTON = "添加 →"
ADVANCED_FRIDA_REMOVE_BUTTON = "移除"
ADVANCED_FRIDA_RECONFIGURE_BUTTON = "重新配置参数"
ADVANCED_FRIDA_MOVE_UP_BUTTON = "上移"
ADVANCED_FRIDA_MOVE_DOWN_BUTTON = "下移"
ADVANCED_FRIDA_START_BUTTON = "启动"
ADVANCED_FRIDA_CANCEL_BUTTON = "取消"
ADVANCED_FRIDA_NO_SCRIPT_BODY = "请至少选择一个要启动的脚本。"
ADVANCED_FRIDA_ACTIVE_SESSION_BODY = "当前已有 Hook 会话，请先停止后再启动新的高级 Frida 启动。"
ADVANCED_FRIDA_ACTION_LOG = "[TOOL] 启动高级 Frida 启动器"
ADVANCED_FRIDA_BUNDLE_LOG = "[TOOL] 多脚本 bundle：{script_path}"
ADVANCED_FRIDA_ORDER_LOG = "[TOOL] 本次合并脚本顺序：{scripts}"
ADVANCED_FRIDA_WORKSPACE_SOURCE = "工作区"
ADVANCED_FRIDA_BUILTIN_SOURCE = "内置"
ADVANCED_FRIDA_PARAM_PREFIX = "参数化"
TERMINAL_ATTACH_ACTION_LOG = "[TOOL] 终端命令启动 Attach：{script_name}"
TERMINAL_SPAWN_ACTION_LOG = "[TOOL] 终端命令启动 Spawn：{script_name}"
TERMINAL_RESTART_ACTION_LOG = "[TOOL] 终端命令：重启当前 App"
TERMINAL_STOP_ACTION_LOG = "[TOOL] 终端命令：停止当前 Hook"
TERMINAL_REFRESH_ACTION_LOG = "[TOOL] 终端命令：刷新 App 列表"
TERMINAL_SELECT_APP_LOG = "[CMD:RESULT] 已选中目标 App：{package}"
TERMINAL_RPC_ACTION_LOG = "[TOOL] 终端命令：{command}"
TERMINAL_BUSY_LOG = "[TOOL] 命令执行中..."
TERMINAL_GENERATE_SCRIPT_LOG = "[CMD:RESULT] 已生成 Hook 脚本：{script_path}"
TERMINAL_ACTIVITYS_LOG = "[CMD:RESULT] Activity 信息：\n{content}"
TERMINAL_SERVICES_LOG = "[CMD:RESULT] Service 信息：\n{content}"
TERMINAL_OBJECT_INFO_LOG = "[CMD:RESULT] 对象信息（{target}）：\n{content}"
TERMINAL_OBJECT_EXPLAIN_LOG = "[CMD:RESULT] 对象解释（{target}）：\n{content}"
TERMINAL_VIEW_INFO_LOG = "[CMD:RESULT] View 信息（{target}）：\n{content}"


# 工作区 / App 状态摘要
PID_UID_TEXT = "PID: {pid} | UID: {uid}"
VERSION_MODE_TEXT = "Version: {version} | 模式: {mode}"
MODE_NOT_RUNNING = "未启动"
WORKSPACE_PATH_LOG = "[*] 当前工作目录：{workspace_dir}"
WORKSPACE_SCRIPT_DIR_LOG = "[*] 当前脚本目录已切换到：{script_dir}"
WORKSPACE_NOT_INITIALIZED_LOG = "[*] 当前工作目录尚未初始化；脚本目录已切换到工作区 js，内置脚本会在初始化时同步进去。"
WORKSPACE_READY_LOG = "[+] {package} 工作目录已完成初始化：{workspace_dir}"
WORKSPACE_PREPARE_START_LOG = "[TOOL] 开始初始化工作目录"
WORKSPACE_PREPARE_MODE_CREATED_LOG = "[TOOL] 工作目录：已创建"
WORKSPACE_PREPARE_MODE_UPDATED_LOG = "[TOOL] 工作目录：已更新"
WORKSPACE_PREPARE_APK_PULLED_LOG = "[TOOL] APK：已拉取本地副本"
WORKSPACE_PREPARE_APK_REUSED_LOG = "[TOOL] APK：复用本地 APK"
WORKSPACE_PREPARE_SCRIPT_DIR_LOG = "[TOOL] 脚本目录：已切换到 {script_dir}"
WORKSPACE_PREPARE_PATH_LOG = "[TOOL] 工作目录：{workspace_dir}"
WORKSPACE_PREPARE_DONE_LOG = "[+] 工作目录已初始化"
PREPARE_START_LOG = "[TOOL] 开始准备设备环境"
SYNCED_APPS_LOG = "[TOOL] 应用列表同步完成：{count} 个"
AUTO_SELECTED_FOREGROUND_LOG = "[TOOL] 前台 App：{package}（已自动选中）"
PREPARE_SELECT_APP_LOG = "[TOOL] 请先选择目标 App"
NO_APPS_FOUND_LOG = "[!] 准备已完成，但当前没有枚举到可选择的 APK 包名。"
PREPARE_DEVICE_CONNECTED_LOG = "[TOOL] 设备已连接：{serial}"
PREPARE_FRIDA_READY_LOG = "[TOOL] Frida Server：已就绪（{status}）"
PREPARE_FRIDA_STATUS_REUSED = "复用现有服务"
PREPARE_FRIDA_STATUS_STARTED = "已启动"
PREPARE_DONE_LOG = "[+] 环境准备完成"


# Hook / Session
TARGET_APP_LOG = "[i] 目标 App: {package}"
SELECTED_SCRIPT_LOG = "[i] 已选中脚本: {script_name}"
NETWORK_STACK_ACTION_LOG = "[TOOL] 启动快捷动作：探测网络栈"
NETWORK_STACK_SCRIPT_LOG = "[TOOL] 探测网络栈使用内置脚本：{script_path}"
NETWORK_STACK_MODE_LOG = "[TOOL] 探测网络栈当前使用模式：{mode}"
NETWORK_STACK_AUTO_STOPPED_LOG = "[TOOL] 网络栈识别已自动结束，本次 Hook 已停止"
OKHTTP_INTERCEPTORS_ACTION_LOG = "[TOOL] 启动快捷动作：查看 OkHttp 拦截器"
OKHTTP_INTERCEPTORS_SCRIPT_LOG = "[TOOL] 查看 OkHttp 拦截器使用内置脚本：{script_path}"
OKHTTP_INTERCEPTORS_MODE_LOG = "[TOOL] 查看 OkHttp 拦截器当前使用模式：{mode}"
OKHTTP_CAPTURE_ACTION_LOG = "[TOOL] 启动快捷动作：抓取 OkHttp 请求"
OKHTTP_CAPTURE_SCRIPT_LOG = "[TOOL] 抓取 OkHttp 请求使用内置脚本：{script_path}"
OKHTTP_CAPTURE_MODE_LOG = "[TOOL] 抓取 OkHttp 请求当前使用模式：{mode}"
REGISTER_NATIVES_ACTION_LOG = "[TOOL] 启动快捷动作：监控 JNI 注册"
REGISTER_NATIVES_SCRIPT_LOG = "[TOOL] 监控 JNI 注册使用内置脚本：{script_path}"
REGISTER_NATIVES_MODE_LOG = "[TOOL] 监控 JNI 注册当前使用模式：{mode}"
ANTI_FRIDA_SO_ACTION_LOG = "[TOOL] 启动快捷动作：定位反 Frida SO"
ANTI_FRIDA_SO_SCRIPT_LOG = "[TOOL] 定位反 Frida SO 使用内置脚本：{script_path}"
ANTI_FRIDA_SO_MODE_LOG = "[TOOL] 定位反 Frida SO 当前使用模式：{mode}"
ANTI_FRIDA_SO_TOOLTIP = "用于定位反 Frida 相关 so；建议先准备环境再用。"
CLICK_TRACE_ACTION_LOG = "[TOOL] 启动快捷动作：监听点击事件"
CLICK_TRACE_SCRIPT_LOG = "[TOOL] 监听点击事件使用内置脚本：{script_path}"
CLICK_TRACE_MODE_LOG = "[TOOL] 监听点击事件当前使用模式：{mode}"
EDIT_TEXT_TRACE_ACTION_LOG = "[TOOL] 启动快捷动作：监听输入框"
EDIT_TEXT_TRACE_SCRIPT_LOG = "[TOOL] 监听输入框使用内置脚本：{script_path}"
EDIT_TEXT_TRACE_MODE_LOG = "[TOOL] 监听输入框当前使用模式：{mode}"
TEXT_VIEW_TRACE_ACTION_LOG = "[TOOL] 启动快捷动作：监听文本视图"
TEXT_VIEW_TRACE_SCRIPT_LOG = "[TOOL] 监听文本视图使用内置脚本：{script_path}"
TEXT_VIEW_TRACE_MODE_LOG = "[TOOL] 监听文本视图当前使用模式：{mode}"
URL_TRACE_ACTION_LOG = "[TOOL] 启动快捷动作：监听 URL"
URL_TRACE_SCRIPT_LOG = "[TOOL] 监听 URL 使用内置脚本：{script_path}"
URL_TRACE_MODE_LOG = "[TOOL] 监听 URL 当前使用模式：{mode}"
ACTIVITY_EVENTS_TRACE_ACTION_LOG = "[TOOL] 启动快捷动作：监听页面跳转"
ACTIVITY_EVENTS_TRACE_SCRIPT_LOG = "[TOOL] 监听页面跳转使用内置脚本：{script_path}"
ACTIVITY_EVENTS_TRACE_MODE_LOG = "[TOOL] 监听页面跳转当前使用模式：{mode}"
ENCRYPTION_ALGO_ACTION_LOG = "[TOOL] 启动快捷动作：监听加密调用"
ENCRYPTION_ALGO_SCRIPT_LOG = "[TOOL] 监听加密调用使用内置脚本：{script_path}"
ENCRYPTION_ALGO_MODE_LOG = "[TOOL] 监听加密调用当前使用模式：{mode}"
DIGEST_HMAC_ACTION_LOG = "[TOOL] 启动快捷动作：监听摘要/HMAC"
DIGEST_HMAC_SCRIPT_LOG = "[TOOL] 监听摘要/HMAC 使用内置脚本：{script_path}"
DIGEST_HMAC_MODE_LOG = "[TOOL] 监听摘要/HMAC 当前使用模式：{mode}"
JNI_METHOD_TRACE_ACTION_LOG = "[TOOL] 启动快捷动作：跟踪 JNI 调用"
JNI_METHOD_TRACE_SCRIPT_LOG = "[TOOL] 跟踪 JNI 调用使用运行时脚本：{script_path}"
JNI_METHOD_TRACE_MODE_LOG = "[TOOL] 跟踪 JNI 调用当前使用模式：{mode}"
JNI_METHOD_TRACE_TARGET_SO_LOG = "[TOOL] 跟踪 JNI 调用目标 SO：{target_so}"
JNI_METHOD_TRACE_TOOLTIP = "需输入目标 SO；更适合 Native/JNI 分析。"
TRACE_INIT_PROC_ACTION_LOG = "[TOOL] 启动快捷动作：跟踪 init_proc（需地址）"
TRACE_INIT_PROC_SCRIPT_LOG = "[TOOL] 跟踪 init_proc（需地址）使用运行时脚本：{script_path}"
TRACE_INIT_PROC_MODE_LOG = "[TOOL] 跟踪 init_proc（需地址）当前使用模式：{mode}"
TRACE_INIT_PROC_PARAMS_LOG = "[TOOL] 跟踪 init_proc（需地址）参数：SO={target_so} | start={start_addr} | end={end_addr}"
TRACE_INIT_PROC_TOOLTIP = "需输入 SO/startAddr/endAddr；适合 init_proc 范围跟踪。"
BYPASS_ROOT_DETECT_ACTION_LOG = "[TOOL] 启动快捷动作：绕过常见 Root 检测"
BYPASS_ROOT_DETECT_SCRIPT_LOG = "[TOOL] 绕过常见 Root 检测使用内置脚本：{script_path}"
BYPASS_ROOT_DETECT_MODE_LOG = "[TOOL] 绕过常见 Root 检测当前使用模式：{mode}"
BYPASS_ROOT_DETECT_TOOLTIP = "绕过常见 Root 检测；属于专项对抗脚本。"
BYPASS_VPN_DETECT_ACTION_LOG = "[TOOL] 启动快捷动作：绕过常见 VPN 检测"
BYPASS_VPN_DETECT_SCRIPT_LOG = "[TOOL] 绕过常见 VPN 检测使用内置脚本：{script_path}"
BYPASS_VPN_DETECT_MODE_LOG = "[TOOL] 绕过常见 VPN 检测当前使用模式：{mode}"
BYPASS_VPN_DETECT_TOOLTIP = "绕过常见 VPN 检测；属于专项对抗脚本。"
HOOK_STARTED_STATUS = "{mode} 已启动"
HOOK_RUNNING_STATE = "{mode} 模式运行中 | App: {package} | 脚本: {script_name}"
HOOK_STARTED_LOG = "[+] 已启动 {mode} 注入：{package} <- {script_name}"
SESSION_DETACHED_PID_CHANGED_STATE = "{mode} 会话已断开 | PID 变化 {old_pid} -> {new_pid}"
SESSION_DETACHED_PID_CHANGED_STATUS = "{mode} 会话已断开，检测到新 PID：{new_pid}，请重新附加"
SESSION_DETACHED_STATE = "{mode} 会话已断开 | reason: {reason}"
SESSION_DETACHED_STATUS = "{mode} 会话已断开，请重新附加"
HOOK_STOPPED_LOG = "[*] 当前 Hook 已停止"
FRIDA_SERVER_STOPPED_LOG = "[*] Frida Server 已停止"
RESTARTED_APP_LOG = "[TOOL] 已重启 App：{package}"


# RPC / 结果窗口
HOOK_SCRIPT_GENERATED_STATUS = "Hook 脚本已生成：{name}"
HOOK_SCRIPT_GENERATED_LOG = "[TOOL] 已生成 Hook 脚本：{path}"
ACTIVITY_LIST_TITLE = "Activity 列表"
SERVICE_LIST_TITLE = "Service 列表"
LOADED_ACTIVITIES_LOG = "[TOOL] 已加载 {package} 的 Activity 列表"
LOADED_SERVICES_LOG = "[TOOL] 已加载 {package} 的 Service 列表"
LOADED_OBJECT_INFO_LOG = "[TOOL] 已加载 {package} 的对象信息：{target}"
EXPLAINED_OBJECT_LOG = "[TOOL] 已解释 {package} 的对象：{target}"
LOADED_VIEW_INFO_LOG = "[TOOL] 已加载 {package} 的 View 信息：{target}"


# APK 扫描
APK_SELECTED_LOG = "[*] 已选择 APK 扫描目标：{path}"
APK_SCAN_START_LOG = "[*] 开始扫描 APK：{path}"
APK_SCAN_TOOL_LOG = "[*] 使用扫描工具：{tool_path}"
APK_SCAN_OUTPUT_HEADER = "[TOOL] APK 扫描输出："
APK_SCAN_ERROR_HEADER = "[TOOL] APK 扫描错误输出："
APK_SCAN_FAILED_BODY = "APK 扫描失败，退出码：{returncode}"
APK_SCAN_FINISHED_LOG = "[+] APK 扫描完成：{apk_path}"


# 日志面板固定文案
LOG_FILTER_ALL = "全部日志"
LOG_FILTER_JS = "只看 [JS]"
LOG_FILTER_ERRORS = "只看错误"
LOG_FILTER_TOOL = "只看调试工具"
LOG_SCOPE_WITH_MATCHES_ONLY = "{scope} | 仅显示匹配项"
LOG_SEARCH_INVALID = "当前范围：{scope} | 搜索结果：正则无效"
LOG_SEARCH_EMPTY = "当前范围：{scope} | 搜索结果：0 / 0"
LOG_SEARCH_PROGRESS = "当前范围：{scope} | 搜索结果：{current} / {total}"
LOG_SEARCH_IDLE = "当前范围：{scope} | 搜索结果：-"


def state_text(message: str) -> str:
    return f"状态：{message}"


def generated_script_body(script_path: Path) -> str:
    return GENERATED_BODY.format(script_path=script_path)


def object_info_title(target: str) -> str:
    return f"对象信息 - {target}"


def object_explain_title(target: str) -> str:
    return f"对象解释 - {target}"


def view_info_title(target: str) -> str:
    return f"View 信息 - {target}"
