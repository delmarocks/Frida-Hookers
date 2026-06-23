from __future__ import annotations

from core.entrypoints import resolve_entrypoint_descriptor

from . import ui_messages
from .display_common import bool_flag_text, join_lines
from .workspace_case_home_view_models import (
    build_workspace_case_home_summary_lines,
    build_workspace_case_home_summary_view_model,
)


def _append_unique_lines(lines: list[str], extra_lines: list[str]) -> None:
    for line in extra_lines:
        if line not in lines:
            lines.append(line)


def _append_workspace_manifest_optional_lines(
    lines: list[str],
    manifest: dict[str, object],
    *,
    include_template_info: bool,
    include_result_summary: bool,
    case_home_mode: bool,
) -> None:
    if include_template_info:
        lines.append(f"最近模板：{manifest.get('last_used_template_name') or '-'}")
    if include_result_summary:
        if case_home_mode:
            lines.append(f"最近结果：{manifest.get('latest_result_summary_excerpt') or '-'}")
        else:
            lines.extend([
                f"最近结果摘要：{manifest.get('latest_result_summary_path') or '-'}",
                f"最近结果摘要已存在：{bool_flag_text(manifest.get('latest_result_summary_exists'))}",
                f"最近结果摘要时间：{manifest.get('last_result_summary_at') or '-'}",
                f"最近结果摘要摘录：{manifest.get('latest_result_summary_excerpt') or '-'}",
            ])


def build_workspace_recent_flow_lines(manifest: dict[str, object]) -> list[str]:
    last_session = manifest.get('last_session') if isinstance(manifest.get('last_session'), dict) else None
    recent_scripts = ', '.join(manifest.get('recent_scripts') or []) or '-'
    recent_logs = ', '.join((manifest.get('recent_logs') or [])[:2]) or '-'
    lines = [
        ui_messages.WORKSPACE_RECENT_FLOW_TITLE,
        ui_messages.WORKSPACE_RECENT_FLOW_TEMPLATE.format(value=manifest.get('last_used_template_name') or '-'),
        ui_messages.WORKSPACE_RECENT_FLOW_RESULT.format(value=manifest.get('latest_result_summary_excerpt') or '-'),
        ui_messages.WORKSPACE_RECENT_FLOW_SCRIPTS.format(value=recent_scripts),
        ui_messages.WORKSPACE_RECENT_FLOW_LOGS.format(value=recent_logs),
    ]
    if last_session:
        lines.append(
            ui_messages.WORKSPACE_RECENT_FLOW_SESSION.format(
                script=last_session.get('script_name') or '-',
                mode=last_session.get('mode') or '-',
                summary=last_session.get('summary') or '-',
            )
        )
    else:
        lines.append(ui_messages.WORKSPACE_RECENT_FLOW_SESSION_EMPTY)
    return lines


def build_workspace_case_home_card_text(manifest: dict[str, object], *, package_fallback: str) -> str:
    view_model = build_workspace_case_home_summary_view_model(
        manifest,
        package_fallback=package_fallback,
        entrypoint_label_resolver=resolve_workspace_case_home_entry_label,
    )
    lines = build_workspace_case_home_summary_lines(view_model)
    _append_unique_lines(lines, build_workspace_case_home_explanation_lines(manifest))
    _append_unique_lines(lines, build_workspace_recent_flow_lines(manifest))
    return join_lines(lines)


def resolve_workspace_case_home_entry_label(entry_key: object) -> str:
    descriptor = resolve_entrypoint_descriptor(str(entry_key or '').strip())
    if descriptor is not None:
        return descriptor.label
    mapping = {
        'resume_named_template': ui_messages.WORKSPACE_CASE_HOME_ENTRY_RESUME_TEMPLATE,
        'review_latest_result_summary': ui_messages.WORKSPACE_CASE_HOME_ENTRY_RESULT_SUMMARY,
        'launch_pinned_script': ui_messages.WORKSPACE_CASE_HOME_ENTRY_PINNED_SCRIPT,
        'reuse_recent_script': ui_messages.WORKSPACE_CASE_HOME_ENTRY_RECENT_SCRIPT,
        'prepare_workspace': ui_messages.WORKSPACE_CASE_HOME_ENTRY_PREPARE_WORKSPACE,
    }
    return mapping.get(str(entry_key or '').strip(), '-')


def build_workspace_manifest_lines(
    manifest: dict[str, object],
    *,
    title: str | None = None,
    include_case_home: bool = True,
    package_fallback: str = "-",
    include_result_summary: bool = False,
    include_template_info: bool = False,
) -> list[str]:
    last_session = manifest.get("last_session") if isinstance(manifest.get("last_session"), dict) else None
    lines: list[str] = []
    if title:
        lines.append(title)
    package_name = manifest.get("package_name") or package_fallback
    if include_case_home:
        lines.extend([
            f"包名：{package_name}",
            f"工作区已就绪：{ui_messages.YES_TEXT if manifest.get('workspace_ready') else ui_messages.NO_TEXT}",
            f"脚本资产数：{manifest.get('script_asset_count') or 0}",
            f"固定脚本 / 最近脚本：{manifest.get('pinned_script_count') or 0} / {manifest.get('recent_script_count') or 0}",
            f"命名模板数：{manifest.get('named_template_count') or 0}",
            ui_messages.WORKSPACE_CASE_HOME_PRIORITY_ENTRY.format(value=resolve_workspace_case_home_entry_label(manifest.get('recommended_entrypoint'))),
            f"案例建议：{manifest.get('case_entry_hint') or '-'}",
        ])
        _append_workspace_manifest_optional_lines(
            lines,
            manifest,
            include_template_info=include_template_info,
            include_result_summary=include_result_summary,
            case_home_mode=True,
        )
        recommended_action_label = manifest.get('recommended_result_action_label') or '-'
        recommended_action_desc = manifest.get('recommended_result_action_description') or '-'
        lines.append(ui_messages.WORKSPACE_CASE_HOME_RECOMMENDED_ACTION.format(value=recommended_action_label))
        lines.append(ui_messages.WORKSPACE_CASE_HOME_RECOMMENDED_ACTION_DESC.format(value=recommended_action_desc))
    else:
        lines.extend([
            f"包名：{package_name}",
            f"notes：{manifest.get('notes_path') or '-'}",
            f"notes 已填写：{bool_flag_text(manifest.get('notes_has_user_content'))}",
            f"notes 默认模板：{bool_flag_text(manifest.get('notes_is_default_template'))}",
            f"固定脚本：{', '.join(manifest.get('pinned_scripts') or []) or '-'}",
            f"最近脚本：{', '.join(manifest.get('recent_scripts') or []) or '-'}",
            f"最近 session 数：{manifest.get('recent_session_count') or 0}",
            f"最近 log 数：{manifest.get('recent_log_count') or 0}",
            f"最近 log：{', '.join(manifest.get('recent_logs') or []) or '-'}",
        ])
        _append_workspace_manifest_optional_lines(
            lines,
            manifest,
            include_template_info=include_template_info,
            include_result_summary=include_result_summary,
            case_home_mode=False,
        )
        lines.append(f"最近更新时间：{manifest.get('updated_at') or '-'}")
    if last_session:
        lines.extend([
            "最近会话：",
            f"  时间：{last_session.get('timestamp') or '-'}",
            f"  脚本：{last_session.get('script_name') or '-'}",
            f"  模式：{last_session.get('mode') or '-'}",
            f"  摘要：{last_session.get('summary') or '-'}",
        ])
    return lines




def build_workspace_case_home_terminal_lines(
    manifest: dict[str, object],
    *,
    package_fallback: str,
    notes_flag_text_resolver,
    mode_label_resolver,
    sessions_summary_empty: str,
) -> list[str]:
    view_model = build_workspace_case_home_summary_view_model(
        manifest,
        package_fallback=package_fallback,
        entrypoint_label_resolver=resolve_workspace_case_home_entry_label,
    )
    lines = [f"工作区案例首页：{view_model.package_name}"]
    lines.extend(build_workspace_case_home_summary_lines(view_model))
    lines.extend([
        f"notes：{manifest.get('notes_path') or '-'}",
        f"notes 已填写：{notes_flag_text_resolver(manifest, 'notes_has_user_content')}",
        f"notes 默认模板：{notes_flag_text_resolver(manifest, 'notes_is_default_template')}",
        f"最近结果摘要：{manifest.get('latest_result_summary_path') or '-'}",
        f"最近结果摘要已存在：{notes_flag_text_resolver(manifest, 'latest_result_summary_exists')}",
        f"固定脚本：{', '.join(manifest.get('pinned_scripts') or []) or '-'}",
        f"最近脚本：{', '.join(manifest.get('recent_scripts') or []) or '-'}",
        f"最近 session 数：{manifest.get('recent_session_count') or 0}",
        f"最近 log 数：{manifest.get('recent_log_count') or 0}",
        f"最近 log：{', '.join(manifest.get('recent_logs') or []) or '-'}",
    ])
    _append_unique_lines(lines, build_workspace_case_home_explanation_lines(manifest))
    _append_unique_lines(lines, build_workspace_recent_flow_lines(manifest))
    last_session = manifest.get("last_session") if isinstance(manifest.get("last_session"), dict) else None
    if last_session:
        lines.extend([
            "最近会话：",
            f"  时间：{last_session.get('timestamp') or '-'}",
            f"  脚本：{last_session.get('script_name') or '-'}",
            f"  模式：{mode_label_resolver(last_session.get('mode') or 'either')}",
            f"  摘要：{last_session.get('summary') or sessions_summary_empty}",
        ])
    return lines

def build_workspace_case_home_resume_template_payload(manifest: dict[str, object] | None) -> dict[str, object]:
    manifest = manifest or {}
    template_name = str(manifest.get('last_used_template_name') or '').strip()
    entrypoint = str(manifest.get('recommended_entrypoint') or '').strip()
    is_priority = bool(template_name) and entrypoint == 'resume_named_template'
    if not template_name:
        return {
            'enabled': False,
            'text': ui_messages.WORKSPACE_CASE_HOME_RESUME_TEMPLATE_BUTTON,
            'tooltip': ui_messages.WORKSPACE_CASE_HOME_RESUME_TEMPLATE_TOOLTIP_EMPTY,
            'style_name': 'secondaryButton',
            'status_message': ui_messages.WORKSPACE_CASE_HOME_RESUME_TEMPLATE_EMPTY_STATUS,
            'log_message': '',
            'source_label': '-',
            'behavior_label': '-',
            'template_name': '',
            'is_priority': False,
            'explanation_lines': [],
        }
    source_label = f'最近模板 {template_name}'
    behavior_label = '打开高级启动器，并优先恢复该模板'
    tooltip = ui_messages.WORKSPACE_CASE_HOME_RESUME_TEMPLATE_TOOLTIP.format(name=template_name)
    if is_priority:
        tooltip += ui_messages.WORKSPACE_CASE_HOME_PRIORITY_TOOLTIP_SUFFIX
    payload = {
        'enabled': True,
        'text': ui_messages.WORKSPACE_CASE_HOME_RESUME_TEMPLATE_BUTTON_TEMPLATE.format(name=template_name),
        'tooltip': tooltip,
        'style_name': 'primaryButton' if is_priority else 'secondaryButton',
        'status_message': ui_messages.WORKSPACE_CASE_HOME_RESUME_TEMPLATE_STATUS_TEMPLATE.format(name=template_name),
        'log_message': ui_messages.WORKSPACE_CASE_HOME_RESUME_TEMPLATE_LOG_TEMPLATE.format(
            priority=ui_messages.WORKSPACE_CASE_HOME_PRIORITY_PREFIX if is_priority else '',
            name=template_name,
        ),
        'source_label': source_label,
        'behavior_label': behavior_label,
        'template_name': template_name,
        'is_priority': is_priority,
    }
    payload['explanation_lines'] = [
        f"- {payload['text']}",
        f"  来源：{source_label}",
        f"  行为：{behavior_label}",
        f"  状态提示：{payload['status_message']}",
    ]
    return payload


def build_workspace_case_home_run_action_payload(manifest: dict[str, object] | None) -> dict[str, object]:
    manifest = manifest or {}
    action_label = str(manifest.get('recommended_result_action_label') or manifest.get('recommended_result_action_key') or '').strip()
    entrypoint = str(manifest.get('recommended_entrypoint') or '').strip()
    is_priority = bool(action_label) and entrypoint in {'review_latest_result_summary', 'launch_pinned_script', 'reuse_recent_script'}
    if not action_label:
        return {
            'enabled': False,
            'text': ui_messages.WORKSPACE_CASE_HOME_RUN_ACTION_BUTTON,
            'tooltip': ui_messages.WORKSPACE_CASE_HOME_RUN_ACTION_TOOLTIP_EMPTY,
            'style_name': 'secondaryButton',
            'status_message': ui_messages.WORKSPACE_CASE_HOME_RUN_ACTION_EMPTY_STATUS,
            'log_message': '',
            'source_label': '-',
            'behavior_label': '-',
            'action_label': '',
            'is_priority': False,
            'explanation_lines': [],
        }
    source_label = f'最近结果摘要推导出的推荐动作 {action_label}'
    behavior_label = '复用当前结果建议执行链'
    tooltip = ui_messages.WORKSPACE_CASE_HOME_RUN_ACTION_TOOLTIP.format(label=action_label)
    if is_priority:
        tooltip += ui_messages.WORKSPACE_CASE_HOME_PRIORITY_TOOLTIP_SUFFIX
    payload = {
        'enabled': True,
        'text': ui_messages.WORKSPACE_CASE_HOME_RUN_ACTION_BUTTON_TEMPLATE.format(label=action_label),
        'tooltip': tooltip,
        'style_name': 'primaryButton' if is_priority else 'secondaryButton',
        'status_message': ui_messages.WORKSPACE_CASE_HOME_RUN_ACTION_STATUS_TEMPLATE.format(label=action_label),
        'log_message': ui_messages.WORKSPACE_CASE_HOME_RUN_ACTION_LOG_TEMPLATE.format(
            priority=ui_messages.WORKSPACE_CASE_HOME_PRIORITY_PREFIX if is_priority else '',
            label=action_label,
        ),
        'source_label': source_label,
        'behavior_label': behavior_label,
        'action_label': action_label,
        'is_priority': is_priority,
    }
    payload['explanation_lines'] = [
        f"- {payload['text']}",
        f"  来源：{source_label}",
        f"  行为：{behavior_label}",
        f"  状态提示：{payload['status_message']}",
    ]
    return payload


def build_workspace_case_home_action_payloads(manifest: dict[str, object] | None) -> dict[str, dict[str, object]]:
    return {
        'resume_template': build_workspace_case_home_resume_template_payload(manifest),
        'run_action': build_workspace_case_home_run_action_payload(manifest),
    }


def build_workspace_case_home_explanation_lines(manifest: dict[str, object]) -> list[str]:
    lines = [
        ui_messages.WORKSPACE_CASE_HOME_PRIORITY_ENTRY.format(value=resolve_workspace_case_home_entry_label(manifest.get('recommended_entrypoint'))),
        f"案例建议：{manifest.get('case_entry_hint') or '-'}",
        ui_messages.WORKSPACE_CASE_HOME_RECOMMENDED_ACTION.format(
            value=manifest.get('recommended_result_action_label') or '-'
        ),
        ui_messages.WORKSPACE_CASE_HOME_RECOMMENDED_ACTION_DESC.format(
            value=manifest.get('recommended_result_action_description') or '-'
        ),
    ]
    payloads = build_workspace_case_home_action_payloads(manifest)
    action_lines: list[str] = []
    for payload in payloads.values():
        if bool(payload.get('enabled')):
            action_lines.extend(str(line) for line in payload.get('explanation_lines') or [] if str(line).strip())
    if action_lines:
        lines.append('首页可用入口：')
        lines.extend(action_lines)
    return lines
