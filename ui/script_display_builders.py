from __future__ import annotations

from . import ui_messages
from .display_common import join_lines


def build_analysis_scenario_summary_lines(profile) -> list[str]:
    lines = [
        profile.title,
        ui_messages.ANALYSIS_SCENARIO_SUMMARY_DESCRIPTION.format(value=profile.description),
        ui_messages.ANALYSIS_SCENARIO_SUMMARY_MODE.format(value=profile.mode_hint.replace("ÍÆ¼öÄ£Ê½£º", "")),
    ]
    script_labels: list[str] = []
    for entry in getattr(profile, 'entries', ()):
        action_key = getattr(entry, 'action_key', '')
        script_labels.append(str(action_key or '-'))
    if script_labels:
        lines.append(ui_messages.ANALYSIS_SCENARIO_SUMMARY_SCRIPTS.format(value=' -> '.join(script_labels)))
    if profile.expected_findings:
        lines.append(ui_messages.ANALYSIS_SCENARIO_SUMMARY_EXPECTED_TITLE)
        lines.extend(f"- {item}" for item in profile.expected_findings)
    if profile.next_steps:
        lines.append(ui_messages.ANALYSIS_SCENARIO_SUMMARY_NEXT_STEPS_TITLE)
        lines.extend(f"- {item}" for item in profile.next_steps)
    return lines


def build_analysis_scenario_tooltip_lines(profile) -> list[str]:
    lines = [profile.description, profile.mode_hint]
    if profile.expected_findings:
        lines.append(ui_messages.ANALYSIS_SCENARIO_SUMMARY_EXPECTED_TITLE)
        lines.extend(f"- {item}" for item in profile.expected_findings[:2])
    return lines


def build_analysis_scenario_tooltip_text(profile) -> str:
    return join_lines(build_analysis_scenario_tooltip_lines(profile))


def build_analysis_scenario_summary_text(profile) -> str:
    return join_lines(build_analysis_scenario_summary_lines(profile))


def build_analysis_scenario_log_lines(profile) -> list[str]:
    return [
        ui_messages.ANALYSIS_SCENARIO_SUMMARY_LOG_TITLE,
        *build_analysis_scenario_summary_lines(profile),
    ]


def build_analysis_scenario_log_text(profile) -> str:
    return join_lines(build_analysis_scenario_log_lines(profile))


def build_script_selection_lines(*, name: str, source_text: str, script_type: str, recommended_mode: str, summary: str, use_when: str, caution: str, tags_value: str, last_used_at: str, path_value: str, root_path: str | None = None) -> list[str]:
    lines = [
        ui_messages.SCRIPT_SELECTION_NAME.format(value=name),
        ui_messages.SCRIPT_SELECTION_SOURCE.format(value=source_text),
        script_type,
        ui_messages.SCRIPT_SELECTION_RECOMMENDED_MODE.format(value=recommended_mode),
        ui_messages.SCRIPT_SELECTION_SUMMARY.format(value=summary),
        ui_messages.SCRIPT_SELECTION_USE_WHEN.format(value=use_when),
        ui_messages.SCRIPT_SELECTION_CAUTION.format(value=caution),
        ui_messages.SCRIPT_SELECTION_TAGS.format(value=tags_value),
        ui_messages.SCRIPT_LAST_USED_AT.format(value=last_used_at),
        ui_messages.SCRIPT_SELECTION_PATH.format(value=path_value),
    ]
    if root_path is not None:
        lines.append(ui_messages.SCRIPT_SELECTION_ROOT_PATH.format(value=root_path))
    return lines


def build_pinned_quick_launch_tooltip_lines(*, source_text: str, recommended_mode: str, summary: str, path_value: str) -> list[str]:
    return [
        ui_messages.SCRIPT_SELECTION_SOURCE.format(value=source_text),
        ui_messages.SCRIPT_SELECTION_RECOMMENDED_MODE.format(value=recommended_mode),
        ui_messages.SCRIPT_SELECTION_SUMMARY.format(value=summary),
        ui_messages.SCRIPT_SELECTION_PATH.format(value=path_value),
    ]


def build_pinned_quick_launch_tooltip_text(*, source_text: str, recommended_mode: str, summary: str, path_value: str) -> str:
    return join_lines(
        build_pinned_quick_launch_tooltip_lines(
            source_text=source_text,
            recommended_mode=recommended_mode,
            summary=summary,
            path_value=path_value,
        )
    )
