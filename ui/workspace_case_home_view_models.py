from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import ui_messages


@dataclass(frozen=True)
class WorkspaceCaseHomeSummaryViewModel:
    package_name: str
    workspace_ready: bool
    script_asset_count: int
    pinned_script_count: int
    recent_script_count: int
    named_template_count: int
    recent_session_count: int
    recent_log_count: int
    recommended_entrypoint_label: str
    case_entry_hint: str
    last_used_template_name: str
    latest_result_summary_excerpt: str
    recommended_result_action_label: str
    recommended_result_action_description: str


def build_workspace_case_home_summary_view_model(
    manifest: dict[str, object],
    *,
    package_fallback: str,
    entrypoint_label_resolver: Callable[[object], str],
) -> WorkspaceCaseHomeSummaryViewModel:
    package_name = str(manifest.get('package_name') or package_fallback or '-').strip() or '-'
    return WorkspaceCaseHomeSummaryViewModel(
        package_name=package_name,
        workspace_ready=bool(manifest.get('workspace_ready')),
        script_asset_count=int(manifest.get('script_asset_count') or 0),
        pinned_script_count=int(manifest.get('pinned_script_count') or 0),
        recent_script_count=int(manifest.get('recent_script_count') or 0),
        named_template_count=int(manifest.get('named_template_count') or 0),
        recent_session_count=int(manifest.get('recent_session_count') or 0),
        recent_log_count=int(manifest.get('recent_log_count') or 0),
        recommended_entrypoint_label=str(entrypoint_label_resolver(manifest.get('recommended_entrypoint')) or '-').strip() or '-',
        case_entry_hint=str(manifest.get('case_entry_hint') or '-').strip() or '-',
        last_used_template_name=str(manifest.get('last_used_template_name') or '-').strip() or '-',
        latest_result_summary_excerpt=str(manifest.get('latest_result_summary_excerpt') or '-').strip() or '-',
        recommended_result_action_label=str(manifest.get('recommended_result_action_label') or '-').strip() or '-',
        recommended_result_action_description=str(manifest.get('recommended_result_action_description') or '-').strip() or '-',
    )


def build_workspace_case_home_summary_lines(view_model: WorkspaceCaseHomeSummaryViewModel) -> list[str]:
    return [
        f'包名：{view_model.package_name}',
        f"工作区已就绪：{ui_messages.YES_TEXT if view_model.workspace_ready else ui_messages.NO_TEXT}",
        f'脚本资产数：{view_model.script_asset_count}',
        f'固定脚本 / 最近脚本：{view_model.pinned_script_count} / {view_model.recent_script_count}',
        f'命名模板数：{view_model.named_template_count}',
        f'最近 session / log：{view_model.recent_session_count} / {view_model.recent_log_count}',
        ui_messages.WORKSPACE_CASE_HOME_PRIORITY_ENTRY.format(value=view_model.recommended_entrypoint_label),
        f'案例建议：{view_model.case_entry_hint}',
        f'最近模板：{view_model.last_used_template_name}',
        f'最近结果：{view_model.latest_result_summary_excerpt}',
        ui_messages.WORKSPACE_CASE_HOME_RECOMMENDED_ACTION.format(value=view_model.recommended_result_action_label),
        ui_messages.WORKSPACE_CASE_HOME_RECOMMENDED_ACTION_DESC.format(value=view_model.recommended_result_action_description),
    ]
