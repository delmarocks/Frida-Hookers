from __future__ import annotations

from dataclasses import dataclass

from .entrypoints import resolve_entrypoint_descriptor
from .result_action_registry import (
    ResultActionDescriptor,
    register_result_action_descriptor,
    resolve_result_action_descriptor,
)


@dataclass(frozen=True, slots=True)
class ResultSignalRule:
    key: str
    section_keys: tuple[str, ...]
    scenario_key: str
    action_key: str
    entry_type: str
    target: str
    next_step_text: str
    action_label: str
    action_description: str
    command_hint: str
    source_reason: str
    expected_value: str
    risk_or_noise: str
    preferred_surface: str


RESULT_SIGNAL_RULES: tuple[ResultSignalRule, ...] = (
    ResultSignalRule(
        key="network",
        section_keys=("urls",),
        scenario_key="network_baseline",
        action_key="network_review",
        entry_type="scenario",
        target="network_baseline",
        next_step_text="- 已看到网络请求/URL：优先回头查看请求时机、参数来源和响应处理链。",
        action_label="回看网络链路",
        action_description="已命中 URL/Network，优先回看请求时机、参数来源和响应处理链。",
        command_hint="查看当前日志结果摘要 / 保存当前结果摘要到工作区 / 优先尝试网络分析场景",
        source_reason="结果摘要已命中 URL / Network 相关线索。",
        expected_value="更快定位请求时机、参数来源与响应处理链。",
        risk_or_noise="网络日志可能很多，需注意区分初始化噪音与真实业务请求。",
        preferred_surface="scenario",
    ),
    ResultSignalRule(
        key="ui",
        section_keys=("activities",),
        scenario_key="ui_baseline",
        action_key="ui_replay",
        entry_type="scenario",
        target="ui_baseline",
        next_step_text="- 已看到 Activity / 页面跳转：优先定位关键页面进入点，再补点击/文本/生命周期观察。",
        action_label="复跑页面行为场景",
        action_description="已命中 Activity / 页面跳转，适合复跑页面行为分析并补生命周期观察。",
        command_hint="优先尝试页面行为分析场景",
        source_reason="结果摘要已命中 Activity / 页面跳转。",
        expected_value="更快锁定关键页面进入点与生命周期观察窗口。",
        risk_or_noise="页面切换日志可能包含启动页或壳层跳转，需过滤无关页面。",
        preferred_surface="scenario",
    ),
    ResultSignalRule(
        key="jni",
        section_keys=("jni_items",),
        scenario_key="native_baseline",
        action_key="jni_trace",
        entry_type="scenario",
        target="native_baseline",
        next_step_text="- 已看到 JNI 注册：优先围绕命中的 so / native 方法补 trace 或导出符号分析。",
        action_label="转入 JNI/Native 场景",
        action_description="已命中 JNI 注册，适合继续做 JNI / Native 方向 trace。",
        command_hint="优先尝试 JNI / Native 分析场景 或 jni_method_trace",
        source_reason="结果摘要已命中 JNI 注册信息。",
        expected_value="更快收敛到命中的 so、native 方法与 trace 入口。",
        risk_or_noise="JNI 注册可能只是基础初始化，需结合实际调用链再决定是否深挖。",
        preferred_surface="scenario",
    ),
    ResultSignalRule(
        key="anti_detection",
        section_keys=("anti_frida_items", "root_items", "vpn_items"),
        scenario_key="anti_detection_baseline",
        action_key="bypass_validate",
        entry_type="scenario",
        target="anti_detection_baseline",
        next_step_text="- 已看到 Anti-Frida 命中：优先验证检测点是否影响注入稳定性，再决定是否补 bypass。",
        action_label="转入反检测验证",
        action_description="已命中 Anti-Frida / Root / VPN 相关结果，建议优先验证检测点与绕过路径。",
        command_hint="优先尝试反检测验证场景",
        source_reason="结果摘要已命中 Anti-Frida / Root / VPN 相关线索。",
        expected_value="先验证检测点是否真的影响注入稳定性或核心流程。",
        risk_or_noise="安全检测日志可能存在误报，建议先验证影响再做 bypass。",
        preferred_surface="scenario",
    ),
    ResultSignalRule(
        key="root",
        section_keys=("root_items",),
        scenario_key="anti_detection_baseline",
        action_key="bypass_validate",
        entry_type="scenario",
        target="anti_detection_baseline",
        next_step_text="- 已看到 Root 检测命中：优先确认检测点是否影响登录/核心流程，再补定点绕过。",
        action_label="转入反检测验证",
        action_description="已命中 Anti-Frida / Root / VPN 相关结果，建议优先验证检测点与绕过路径。",
        command_hint="优先尝试反检测验证场景",
        source_reason="结果摘要已命中 Anti-Frida / Root / VPN 相关线索。",
        expected_value="先验证检测点是否真的影响注入稳定性或核心流程。",
        risk_or_noise="安全检测日志可能存在误报，建议先验证影响再做 bypass。",
        preferred_surface="scenario",
    ),
    ResultSignalRule(
        key="vpn",
        section_keys=("vpn_items",),
        scenario_key="anti_detection_baseline",
        action_key="bypass_validate",
        entry_type="scenario",
        target="anti_detection_baseline",
        next_step_text="- 已看到 VPN 检测命中：优先确认是否影响抓包/网络路径，再验证绕过是否生效。",
        action_label="转入反检测验证",
        action_description="已命中 Anti-Frida / Root / VPN 相关结果，建议优先验证检测点与绕过路径。",
        command_hint="优先尝试反检测验证场景",
        source_reason="结果摘要已命中 Anti-Frida / Root / VPN 相关线索。",
        expected_value="先验证检测点是否真的影响注入稳定性或核心流程。",
        risk_or_noise="安全检测日志可能存在误报，建议先验证影响再做 bypass。",
        preferred_surface="scenario",
    ),
)


def _result_action_status_message(label: str, target: str) -> str:
    return label or target or '-'


for _entry_type, _executor_label in (
    ('scenario', 'open_analysis_scenario_as_template'),
    ('workspace_note', 'append_workspace_result_summary'),
):
    if resolve_result_action_descriptor(_entry_type) is None:
        register_result_action_descriptor(
            ResultActionDescriptor(
                entry_type=_entry_type,
                executor_label=_executor_label,
                status_message_builder=_result_action_status_message,
            )
        )


SCENARIO_PRIORITY = (
    "network_baseline",
    "ui_baseline",
    "native_baseline",
    "anti_detection_baseline",
)


def matched_result_rules(sections: dict[str, object]) -> list[ResultSignalRule]:
    matched: list[ResultSignalRule] = []
    for rule in RESULT_SIGNAL_RULES:
        for key in rule.section_keys:
            value = sections.get(key)
            if isinstance(value, (list, tuple)) and value:
                matched.append(rule)
                break
    return matched


def result_next_steps(sections: dict[str, object]) -> list[str]:
    return [rule.next_step_text for rule in matched_result_rules(sections)]


def result_action_payloads(sections: dict[str, object]) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    seen_action_keys: set[str] = set()
    for rule in matched_result_rules(sections):
        if rule.action_key in seen_action_keys:
            continue
        seen_action_keys.add(rule.action_key)
        descriptor = resolve_entrypoint_descriptor(rule.scenario_key, entry_type=rule.entry_type, target=rule.target)
        actions.append(
            {
                "key": rule.action_key,
                "label": rule.action_label,
                "description": rule.action_description,
                "command_hint": rule.command_hint,
                "entry_type": rule.entry_type,
                "target": rule.target,
                "scenario_key": rule.scenario_key,
                "source_reason": rule.source_reason,
                "expected_value": rule.expected_value,
                "risk_or_noise": rule.risk_or_noise,
                "preferred_surface": rule.preferred_surface,
                "entry_label": descriptor.label if descriptor is not None else '',
                "entry_source": descriptor.source if descriptor is not None else '',
                "entry_description": descriptor.description if descriptor is not None else '',
            }
        )
    if actions:
        descriptor = resolve_entrypoint_descriptor('noteappend_resultmeta', entry_type='workspace_note', target='noteappend_resultmeta')
        actions.append(
            {
                "key": "persist_summary",
                "label": "沉淀当前结果摘要",
                "description": "把当前结果摘要写回工作区，方便后续案例首页与模板联动继续消费。",
                "command_hint": "保存当前结果摘要到工作区 / noteappend resultmeta",
                "entry_type": "workspace_note",
                "target": "noteappend_resultmeta",
                "scenario_key": "",
                "source_reason": "当前结果摘要已经形成可沉淀内容。",
                "expected_value": "把本轮发现回写到工作区，方便首页、模板和后续案例继续复用。",
                "risk_or_noise": "若当前摘要仍较粗糙，过早沉淀可能把噪音一并写入工作区。",
                "preferred_surface": "workspace",
                "entry_label": descriptor.label if descriptor is not None else '',
                "entry_source": descriptor.source if descriptor is not None else '',
                "entry_description": descriptor.description if descriptor is not None else '',
            }
        )
    return actions


def preferred_scenario_key_for_script_name(script_name: str, scenario_to_script_names: dict[str, tuple[str, ...]]) -> str | None:
    normalized = str(script_name or "").strip().lower()
    if not normalized:
        return None
    for scenario_key in SCENARIO_PRIORITY:
        for candidate in scenario_to_script_names.get(scenario_key, ()):
            if candidate.lower() == normalized:
                return scenario_key
    for scenario_key, names in scenario_to_script_names.items():
        for candidate in names:
            if candidate.lower() == normalized:
                return scenario_key
    return None


def preferred_case_entrypoint(
    *,
    has_named_template: bool,
    has_result_summary: bool,
    has_pinned_scripts: bool,
    has_recent_scripts: bool,
) -> tuple[str, str]:
    if has_named_template:
        return "resume_named_template", "优先从最近模板继续，可直接在高级启动器中恢复并编辑。"
    if has_result_summary:
        return "review_latest_result_summary", "先查看最近结果摘要，再决定继续补脚本还是沉淀模板。"
    if has_pinned_scripts:
        return "launch_pinned_script", "当前已有固定脚本，适合先从高频固定脚本开始复现关键链路。"
    if has_recent_scripts:
        return "reuse_recent_script", "当前已有最近使用脚本，建议先复跑最近链路并补观察。"
    return "prepare_workspace", "当前工作区仍较空，建议先初始化/补脚本，再开始首轮场景分析。"


def infer_result_summary_sections_from_text(summary_text: str) -> dict[str, object]:
    text = str(summary_text or '')
    lowered = text.lower()

    def _has_any(*tokens: str) -> bool:
        return any(token in lowered for token in tokens if token)

    return {
        'urls': ['summary-hit'] if _has_any('url', 'network', 'http', 'https') else [],
        'activities': ['summary-hit'] if _has_any('activity', '页面') else [],
        'jni_items': ['summary-hit'] if _has_any('jni', 'registernatives', 'native') else [],
        'anti_frida_items': ['summary-hit'] if _has_any('anti-frida', 'anti frida', 'frida') else [],
        'root_items': ['summary-hit'] if _has_any('root') else [],
        'vpn_items': ['summary-hit'] if _has_any('vpn') else [],
    }
