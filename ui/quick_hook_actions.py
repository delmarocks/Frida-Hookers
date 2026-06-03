from __future__ import annotations

from dataclasses import dataclass

from . import ui_messages


@dataclass(frozen=True, slots=True)
class QuickHookAction:
    key: str
    button_attr: str
    button_label: str
    script_name: str
    grid_row: int
    grid_col: int
    busy_message: str
    action_log: str
    script_log_template: str
    mode_log_template: str
    tooltip: str = ""


@dataclass(frozen=True, slots=True)
class QuickHookGroup:
    key: str
    title: str
    action_keys: tuple[str, ...]


QUICK_HOOK_ACTIONS: tuple[QuickHookAction, ...] = (
    QuickHookAction(
        key="detect_network_stack",
        button_attr="detect_network_stack_button",
        button_label="探测网络栈",
        script_name="detect_network_stack.js",
        grid_row=1,
        grid_col=0,
        busy_message=ui_messages.DETECTING_NETWORK_STACK,
        action_log=ui_messages.NETWORK_STACK_ACTION_LOG,
        script_log_template=ui_messages.NETWORK_STACK_SCRIPT_LOG,
        mode_log_template=ui_messages.NETWORK_STACK_MODE_LOG,
    ),
    QuickHookAction(
        key="print_okhttp_interceptors",
        button_attr="print_okhttp_interceptors_button",
        button_label="查看 OkHttp 拦截器",
        script_name="print_okhttp_interceptors.js",
        grid_row=1,
        grid_col=1,
        busy_message=ui_messages.PRINTING_OKHTTP_INTERCEPTORS,
        action_log=ui_messages.OKHTTP_INTERCEPTORS_ACTION_LOG,
        script_log_template=ui_messages.OKHTTP_INTERCEPTORS_SCRIPT_LOG,
        mode_log_template=ui_messages.OKHTTP_INTERCEPTORS_MODE_LOG,
    ),
    QuickHookAction(
        key="okhttp_capture",
        button_attr="okhttp_capture_button",
        button_label="抓取 OkHttp 请求",
        script_name="okhttp.js",
        grid_row=2,
        grid_col=0,
        busy_message=ui_messages.CAPTURING_OKHTTP_TRAFFIC,
        action_log=ui_messages.OKHTTP_CAPTURE_ACTION_LOG,
        script_log_template=ui_messages.OKHTTP_CAPTURE_SCRIPT_LOG,
        mode_log_template=ui_messages.OKHTTP_CAPTURE_MODE_LOG,
    ),
    QuickHookAction(
        key="hook_register_natives",
        button_attr="hook_register_natives_button",
        button_label="监控 JNI 注册",
        script_name="hook_register_natives.js",
        grid_row=2,
        grid_col=1,
        busy_message=ui_messages.HOOKING_REGISTER_NATIVES,
        action_log=ui_messages.REGISTER_NATIVES_ACTION_LOG,
        script_log_template=ui_messages.REGISTER_NATIVES_SCRIPT_LOG,
        mode_log_template=ui_messages.REGISTER_NATIVES_MODE_LOG,
    ),
    QuickHookAction(
        key="find_anti_frida_so",
        button_attr="find_anti_frida_so_button",
        button_label="定位反 Frida SO",
        script_name="find_anit_frida_so.js",
        grid_row=3,
        grid_col=0,
        busy_message=ui_messages.FINDING_ANTI_FRIDA_SO,
        action_log=ui_messages.ANTI_FRIDA_SO_ACTION_LOG,
        script_log_template=ui_messages.ANTI_FRIDA_SO_SCRIPT_LOG,
        mode_log_template=ui_messages.ANTI_FRIDA_SO_MODE_LOG,
        tooltip=ui_messages.ANTI_FRIDA_SO_TOOLTIP,
    ),
    QuickHookAction(
        key="click_trace",
        button_attr="click_trace_button",
        button_label="监听点击事件",
        script_name="click.js",
        grid_row=3,
        grid_col=1,
        busy_message=ui_messages.TRACING_CLICK_EVENTS,
        action_log=ui_messages.CLICK_TRACE_ACTION_LOG,
        script_log_template=ui_messages.CLICK_TRACE_SCRIPT_LOG,
        mode_log_template=ui_messages.CLICK_TRACE_MODE_LOG,
    ),
    QuickHookAction(
        key="edit_text_trace",
        button_attr="edit_text_trace_button",
        button_label="监听输入框",
        script_name="edit_text.js",
        grid_row=4,
        grid_col=0,
        busy_message=ui_messages.TRACING_EDIT_TEXT,
        action_log=ui_messages.EDIT_TEXT_TRACE_ACTION_LOG,
        script_log_template=ui_messages.EDIT_TEXT_TRACE_SCRIPT_LOG,
        mode_log_template=ui_messages.EDIT_TEXT_TRACE_MODE_LOG,
    ),
    QuickHookAction(
        key="text_view_trace",
        button_attr="text_view_trace_button",
        button_label="监听文本视图",
        script_name="text_view.js",
        grid_row=4,
        grid_col=1,
        busy_message=ui_messages.TRACING_TEXT_VIEW,
        action_log=ui_messages.TEXT_VIEW_TRACE_ACTION_LOG,
        script_log_template=ui_messages.TEXT_VIEW_TRACE_SCRIPT_LOG,
        mode_log_template=ui_messages.TEXT_VIEW_TRACE_MODE_LOG,
    ),
    QuickHookAction(
        key="url_trace",
        button_attr="url_trace_button",
        button_label="监听 URL",
        script_name="url.js",
        grid_row=5,
        grid_col=0,
        busy_message=ui_messages.TRACING_URLS,
        action_log=ui_messages.URL_TRACE_ACTION_LOG,
        script_log_template=ui_messages.URL_TRACE_SCRIPT_LOG,
        mode_log_template=ui_messages.URL_TRACE_MODE_LOG,
    ),
    QuickHookAction(
        key="activity_events_trace",
        button_attr="activity_events_trace_button",
        button_label="监听页面跳转",
        script_name="activity_events.js",
        grid_row=5,
        grid_col=1,
        busy_message=ui_messages.TRACING_ACTIVITY_EVENTS,
        action_log=ui_messages.ACTIVITY_EVENTS_TRACE_ACTION_LOG,
        script_log_template=ui_messages.ACTIVITY_EVENTS_TRACE_SCRIPT_LOG,
        mode_log_template=ui_messages.ACTIVITY_EVENTS_TRACE_MODE_LOG,
    ),
    QuickHookAction(
        key="hook_encryption_algo",
        button_attr="hook_encryption_algo_button",
        button_label="监听加密调用",
        script_name="hook_encryption_algo.js",
        grid_row=6,
        grid_col=0,
        busy_message=ui_messages.TRACING_ENCRYPTION_ALGO,
        action_log=ui_messages.ENCRYPTION_ALGO_ACTION_LOG,
        script_log_template=ui_messages.ENCRYPTION_ALGO_SCRIPT_LOG,
        mode_log_template=ui_messages.ENCRYPTION_ALGO_MODE_LOG,
    ),
    QuickHookAction(
        key="hook_encryption_algo2",
        button_attr="hook_encryption_algo2_button",
        button_label="监听摘要/HMAC",
        script_name="hook_encryption_algo2.js",
        grid_row=6,
        grid_col=1,
        busy_message=ui_messages.TRACING_DIGEST_HMAC,
        action_log=ui_messages.DIGEST_HMAC_ACTION_LOG,
        script_log_template=ui_messages.DIGEST_HMAC_SCRIPT_LOG,
        mode_log_template=ui_messages.DIGEST_HMAC_MODE_LOG,
    ),
    QuickHookAction(
        key="jni_method_trace",
        button_attr="jni_method_trace_button",
        button_label="跟踪 JNI 调用",
        script_name="jni_method_trace.js",
        grid_row=7,
        grid_col=0,
        busy_message=ui_messages.TRACING_JNI_METHODS,
        action_log=ui_messages.JNI_METHOD_TRACE_ACTION_LOG,
        script_log_template=ui_messages.JNI_METHOD_TRACE_SCRIPT_LOG,
        mode_log_template=ui_messages.JNI_METHOD_TRACE_MODE_LOG,
        tooltip=ui_messages.JNI_METHOD_TRACE_TOOLTIP,
    ),
    QuickHookAction(
        key="trace_init_proc",
        button_attr="trace_init_proc_button",
        button_label="跟踪 init_proc（需地址）",
        script_name="trace_init_proc.js",
        grid_row=7,
        grid_col=1,
        busy_message=ui_messages.TRACING_INIT_PROC,
        action_log=ui_messages.TRACE_INIT_PROC_ACTION_LOG,
        script_log_template=ui_messages.TRACE_INIT_PROC_SCRIPT_LOG,
        mode_log_template=ui_messages.TRACE_INIT_PROC_MODE_LOG,
        tooltip=ui_messages.TRACE_INIT_PROC_TOOLTIP,
    ),
    QuickHookAction(
        key="bypass_root_detect",
        button_attr="bypass_root_detect_button",
        button_label="绕过常见 Root 检测",
        script_name="bypass_root_detect.js",
        grid_row=8,
        grid_col=0,
        busy_message=ui_messages.BYPASSING_ROOT_DETECT,
        action_log=ui_messages.BYPASS_ROOT_DETECT_ACTION_LOG,
        script_log_template=ui_messages.BYPASS_ROOT_DETECT_SCRIPT_LOG,
        mode_log_template=ui_messages.BYPASS_ROOT_DETECT_MODE_LOG,
        tooltip=ui_messages.BYPASS_ROOT_DETECT_TOOLTIP,
    ),
    QuickHookAction(
        key="bypass_vpn_detect",
        button_attr="bypass_vpn_detect_button",
        button_label="绕过常见 VPN 检测",
        script_name="bypass_vpn_detect.js",
        grid_row=8,
        grid_col=1,
        busy_message=ui_messages.BYPASSING_VPN_DETECT,
        action_log=ui_messages.BYPASS_VPN_DETECT_ACTION_LOG,
        script_log_template=ui_messages.BYPASS_VPN_DETECT_SCRIPT_LOG,
        mode_log_template=ui_messages.BYPASS_VPN_DETECT_MODE_LOG,
        tooltip=ui_messages.BYPASS_VPN_DETECT_TOOLTIP,
    ),
)

QUICK_HOOK_GROUPS: tuple[QuickHookGroup, ...] = (
    QuickHookGroup(
        key="network",
        title=ui_messages.QUICK_HOOK_GROUP_NETWORK,
        action_keys=(
            "detect_network_stack",
            "print_okhttp_interceptors",
            "okhttp_capture",
            "bypass_vpn_detect",
        ),
    ),
    QuickHookGroup(
        key="ui",
        title=ui_messages.QUICK_HOOK_GROUP_UI,
        action_keys=(
            "click_trace",
            "edit_text_trace",
            "text_view_trace",
            "url_trace",
            "activity_events_trace",
        ),
    ),
    QuickHookGroup(
        key="native",
        title=ui_messages.QUICK_HOOK_GROUP_NATIVE,
        action_keys=(
            "hook_register_natives",
            "jni_method_trace",
            "trace_init_proc",
        ),
    ),
    QuickHookGroup(
        key="crypto",
        title=ui_messages.QUICK_HOOK_GROUP_CRYPTO,
        action_keys=(
            "hook_encryption_algo",
            "hook_encryption_algo2",
        ),
    ),
    QuickHookGroup(
        key="bypass",
        title=ui_messages.QUICK_HOOK_GROUP_BYPASS,
        action_keys=(
            "find_anti_frida_so",
            "bypass_root_detect",
        ),
    ),
)

QUICK_HOOK_ACTIONS_BY_KEY = {action.key: action for action in QUICK_HOOK_ACTIONS}
QUICK_HOOK_BUTTON_ATTRS = tuple(action.button_attr for action in QUICK_HOOK_ACTIONS)
