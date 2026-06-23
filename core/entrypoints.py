from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EntryPointDescriptor:
    key: str
    entry_type: str
    target: str
    label: str
    source: str
    description: str


ENTRYPOINT_REGISTRY: dict[str, EntryPointDescriptor] = {
    'resume_named_template': EntryPointDescriptor(
        key='resume_named_template',
        entry_type='case_home',
        target='advanced_launcher_recent_template',
        label='恢复最近模板',
        source='workspace_case_home',
        description='从工作区首页恢复最近使用的命名模板。',
    ),
    'review_latest_result_summary': EntryPointDescriptor(
        key='review_latest_result_summary',
        entry_type='case_home',
        target='result_summary_latest',
        label='先看最近结果摘要',
        source='workspace_case_home',
        description='从工作区首页先回看最近结果摘要，再决定下一步。',
    ),
    'launch_pinned_script': EntryPointDescriptor(
        key='launch_pinned_script',
        entry_type='case_home',
        target='pinned_script_quick_launch',
        label='先从固定脚本继续',
        source='workspace_case_home',
        description='从工作区首页优先进入固定脚本快速复现链路。',
    ),
    'reuse_recent_script': EntryPointDescriptor(
        key='reuse_recent_script',
        entry_type='case_home',
        target='recent_script_replay',
        label='先复跑最近脚本',
        source='workspace_case_home',
        description='从工作区首页优先复跑最近使用脚本。',
    ),
    'prepare_workspace': EntryPointDescriptor(
        key='prepare_workspace',
        entry_type='case_home',
        target='workspace_prepare',
        label='先准备工作区',
        source='workspace_case_home',
        description='当前工作区较空，先初始化并准备脚本资产。',
    ),
    'network_baseline': EntryPointDescriptor(
        key='network_baseline',
        entry_type='scenario',
        target='network_baseline',
        label='网络分析场景',
        source='analysis_scenario',
        description='围绕网络请求、URL、参数与响应处理链做首轮组合分析。',
    ),
    'ui_baseline': EntryPointDescriptor(
        key='ui_baseline',
        entry_type='scenario',
        target='ui_baseline',
        label='页面行为场景',
        source='analysis_scenario',
        description='围绕 Activity、页面跳转、生命周期与 UI 行为做首轮分析。',
    ),
    'native_baseline': EntryPointDescriptor(
        key='native_baseline',
        entry_type='scenario',
        target='native_baseline',
        label='JNI/Native 场景',
        source='analysis_scenario',
        description='围绕 JNI 注册、native 调用与 so 线索做首轮分析。',
    ),
    'anti_detection_baseline': EntryPointDescriptor(
        key='anti_detection_baseline',
        entry_type='scenario',
        target='anti_detection_baseline',
        label='反检测验证场景',
        source='analysis_scenario',
        description='围绕 Anti-Frida / Root / VPN 相关检测点做验证与绕过准备。',
    ),
    'noteappend_resultmeta': EntryPointDescriptor(
        key='noteappend_resultmeta',
        entry_type='workspace_note',
        target='noteappend_resultmeta',
        label='沉淀当前结果摘要',
        source='result_action',
        description='把当前结果摘要写回工作区，供首页、模板与案例继续消费。',
    ),
}


def resolve_entrypoint_descriptor(key: str | None = None, *, entry_type: str | None = None, target: str | None = None) -> EntryPointDescriptor | None:
    normalized_key = str(key or '').strip()
    if normalized_key:
        descriptor = ENTRYPOINT_REGISTRY.get(normalized_key)
        if descriptor is not None:
            return descriptor
    normalized_entry_type = str(entry_type or '').strip().lower()
    normalized_target = str(target or '').strip()
    if normalized_entry_type or normalized_target:
        for descriptor in ENTRYPOINT_REGISTRY.values():
            if normalized_entry_type and descriptor.entry_type.lower() != normalized_entry_type:
                continue
            if normalized_target and descriptor.target != normalized_target:
                continue
            return descriptor
    return None
