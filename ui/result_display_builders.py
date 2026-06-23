from __future__ import annotations

from . import ui_messages


def build_result_action_lines(actions: list[dict[str, str]]) -> list[str]:
    if not actions:
        return [ui_messages.RESULT_SUMMARY_ACTIONS_EMPTY]
    lines = [ui_messages.RESULT_SUMMARY_ACTIONS_TITLE]
    for action in actions:
        lines.extend(build_result_action_detail_lines(action))
    return lines


def build_result_action_detail_lines(action: dict[str, str]) -> list[str]:
    label = str(action.get('label') or action.get('key') or '-').strip()
    description = str(action.get('description') or '').strip()
    command_hint = str(action.get('command_hint') or '').strip()
    source_reason = str(action.get('source_reason') or '').strip()
    expected_value = str(action.get('expected_value') or '').strip()
    risk_or_noise = str(action.get('risk_or_noise') or '').strip()
    preferred_surface = str(action.get('preferred_surface') or '').strip()
    entry_type = str(action.get('entry_type') or '').strip()
    target = str(action.get('target') or '').strip()
    lines = [f"- {label}：{description or '-'}"]
    if source_reason:
        lines.append(f"  来源说明：{source_reason}")
    if expected_value:
        lines.append(f"  预期收益：{expected_value}")
    if risk_or_noise:
        lines.append(f"  风险/噪音：{risk_or_noise}")
    if command_hint:
        lines.append(f"  建议入口：{command_hint}")
    if preferred_surface:
        lines.append(f"  推荐界面：{preferred_surface}")
    entry_label = str(action.get('entry_label') or '').strip()
    entry_source = str(action.get('entry_source') or '').strip()
    entry_description = str(action.get('entry_description') or '').strip()
    if entry_label:
        lines.append(f"  注册入口：{entry_label}")
    if entry_source:
        lines.append(f"  入口来源：{entry_source}")
    if entry_description:
        lines.append(f"  入口说明：{entry_description}")
    if entry_type or target:
        detail = entry_type or '-'
        if target:
            detail = f"{detail} -> {target}"
        lines.append(f"  入口标识：{detail}")
    return lines


def build_result_action_choice_label(action: dict[str, str]) -> str:
    label = str(action.get('label') or action.get('key') or '-').strip()
    key = str(action.get('key') or '-').strip()
    entry_type = str(action.get('entry_type') or '-').strip()
    description = str(action.get('description') or '').strip()
    detail = f"{label} [{key} / {entry_type}]"
    if description:
        detail = f"{detail} - {description}"
    return detail


def build_result_action_list_lines(actions: list[dict[str, str]]) -> list[str]:
    if not actions:
        return [ui_messages.RESULT_SUMMARY_ACTIONS_RUN_LIST_EMPTY]
    lines = [ui_messages.RESULT_SUMMARY_ACTIONS_RUN_LIST_TITLE]
    for action in actions:
        key = str(action.get('key') or '-').strip()
        label = str(action.get('label') or key).strip()
        entry_type = str(action.get('entry_type') or '-').strip()
        lines.append(f"- {key}: {label} [{entry_type}]")
        for detail in build_result_action_detail_lines(action)[1:]:
            lines.append(f"  {detail.strip()}")
    return lines
