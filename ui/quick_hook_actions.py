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


@dataclass(frozen=True, slots=True)
class ScenarioEntry:
    action_key: str
    required: bool = True


@dataclass(frozen=True, slots=True)
class AnalysisScenarioProfile:
    key: str
    button_attr: str
    button_label: str
    title: str
    description: str
    mode_hint: str
    action_log: str
    busy_message: str
    entries: tuple[ScenarioEntry, ...]
    expected_findings: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()


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

ANALYSIS_SCENARIO_PROFILES: tuple[AnalysisScenarioProfile, ...] = (
    AnalysisScenarioProfile(
        key="network_baseline",
        button_attr="network_baseline_scene_button",
        button_label="首轮网络分析",
        title="首轮网络分析",
        description="先探测网络栈，再观察 URL 与 OkHttp 拦截器，适合第一次摸清请求链路。",
        mode_hint=ui_messages.ANALYSIS_SCENARIO_MODE_HINT_ATTACH_OR_SPAWN,
        action_log=ui_messages.ANALYSIS_SCENARIO_NETWORK_ACTION_LOG,
        busy_message=ui_messages.STARTING_ANALYSIS_SCENARIO,
        entries=(
            ScenarioEntry("detect_network_stack"),
            ScenarioEntry("print_okhttp_interceptors"),
            ScenarioEntry("url_trace"),
        ),
        expected_findings=(
            "识别当前 App 使用的网络栈/客户端实现",
            "确认是否存在 OkHttp 拦截器与典型 URL 输出",
            "为后续请求参数、响应链路定位建立入口",
        ),
        next_steps=(
            "若确认存在 OkHttp，请继续抓请求/响应或补 SSL Pinning 相关脚本。",
            "若只看到 URL 未见请求体，请继续补点击链路或加密调用观察。",
        ),
    ),
    AnalysisScenarioProfile(
        key="ui_baseline",
        button_attr="ui_baseline_scene_button",
        button_label="首轮页面行为分析",
        title="首轮页面行为分析",
        description="优先观察页面跳转、点击与文本变化，适合快速摸清当前界面交互。",
        mode_hint=ui_messages.ANALYSIS_SCENARIO_MODE_HINT_ATTACH_PREFERRED,
        action_log=ui_messages.ANALYSIS_SCENARIO_UI_ACTION_LOG,
        busy_message=ui_messages.STARTING_ANALYSIS_SCENARIO,
        entries=(
            ScenarioEntry("activity_events_trace"),
            ScenarioEntry("click_trace"),
            ScenarioEntry("text_view_trace"),
        ),
        expected_findings=(
            "确认关键页面跳转顺序与生命周期节奏",
            "识别核心按钮点击与文本展示变化",
            "定位后续更精细 Hook 的界面入口",
        ),
        next_steps=(
            "若已定位关键页面，请结合 URL / 加密 / RPC 继续缩小分析范围。",
            "若页面变化太快，可切回 Attach 并只保留页面相关脚本复跑。",
        ),
    ),
    AnalysisScenarioProfile(
        key="native_baseline",
        button_attr="native_baseline_scene_button",
        button_label="首轮 JNI / Native 分析",
        title="首轮 JNI / Native 分析",
        description="先看 RegisterNatives，再进入参数化 JNI 跟踪，适合 Native 入口摸底。",
        mode_hint=ui_messages.ANALYSIS_SCENARIO_MODE_HINT_SPAWN_PREFERRED,
        action_log=ui_messages.ANALYSIS_SCENARIO_NATIVE_ACTION_LOG,
        busy_message=ui_messages.STARTING_ANALYSIS_SCENARIO,
        entries=(
            ScenarioEntry("hook_register_natives"),
            ScenarioEntry("jni_method_trace"),
        ),
        expected_findings=(
            "观察 RegisterNatives 注册行为与目标 so",
            "进入参数化 JNI runtime 跟踪具体 native 入口",
            "为后续导符号、trace init_proc 或静态分析提供证据",
        ),
        next_steps=(
            "若已命中目标 so，请优先围绕该 so 做 trace 或导出符号分析。",
            "若尚未命中，请改用 Spawn 或补 init_proc 范围跟踪。",
        ),
    ),
    AnalysisScenarioProfile(
        key="anti_detection_baseline",
        button_attr="anti_detection_baseline_scene_button",
        button_label="首轮反检测验证",
        title="首轮反检测验证",
        description="优先观察 anti-Frida 命中，并一起验证 Root / VPN 绕过脚本。",
        mode_hint=ui_messages.ANALYSIS_SCENARIO_MODE_HINT_SPAWN_PREFERRED,
        action_log=ui_messages.ANALYSIS_SCENARIO_BYPASS_ACTION_LOG,
        busy_message=ui_messages.STARTING_ANALYSIS_SCENARIO,
        entries=(
            ScenarioEntry("find_anti_frida_so"),
            ScenarioEntry("bypass_root_detect"),
            ScenarioEntry("bypass_vpn_detect"),
        ),
        expected_findings=(
            "确认是否存在 Anti-Frida 命中与相关 so 线索",
            "验证 Root / VPN 检测是否影响目标流程",
            "为后续定点绕过与稳定注入准备最小证据链",
        ),
        next_steps=(
            "若命中 Anti-Frida，请先确认是否影响注入稳定性，再决定是否补 bypass。",
            "若 Root/VPN 仍拦截核心流程，请继续改成专项脚本单独验证。",
        ),
    ),
)

ANALYSIS_SCENARIO_PROFILES_BY_KEY = {
    profile.key: profile for profile in ANALYSIS_SCENARIO_PROFILES
}
ANALYSIS_SCENARIO_BUTTON_ATTRS = tuple(profile.button_attr for profile in ANALYSIS_SCENARIO_PROFILES)
