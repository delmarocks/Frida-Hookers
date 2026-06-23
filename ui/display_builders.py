from __future__ import annotations

from .display_common import bool_flag_text, join_lines
from .result_display_builders import (
    build_result_action_choice_label,
    build_result_action_detail_lines,
    build_result_action_lines,
    build_result_action_list_lines,
)
from .result_summary_view_models import (
    ResultSummaryTextSpec,
    ResultSummaryViewModel,
    append_result_summary_category_block,
    build_result_summary_actions_text,
    build_result_summary_note_block,
    build_result_summary_text,
)
from .script_display_builders import (
    build_analysis_scenario_log_lines,
    build_analysis_scenario_log_text,
    build_analysis_scenario_summary_lines,
    build_analysis_scenario_summary_text,
    build_analysis_scenario_tooltip_lines,
    build_analysis_scenario_tooltip_text,
    build_pinned_quick_launch_tooltip_lines,
    build_pinned_quick_launch_tooltip_text,
    build_script_selection_lines,
)
from .session_display_builders import build_session_status_payload
from .terminal_display_builders import (
    build_terminal_apps_lines,
    build_terminal_help_category_lines,
    build_terminal_help_example_lines,
    build_terminal_help_text,
    build_terminal_logmeta_lines,
    build_terminal_logs_lines,
    build_terminal_script_meta_lines,
    build_terminal_sessionmeta_lines,
)
from .workspace_display_builders import (
    build_workspace_case_home_action_payloads,
    build_workspace_case_home_card_text,
    build_workspace_case_home_explanation_lines,
    build_workspace_case_home_resume_template_payload,
    build_workspace_case_home_run_action_payload,
    build_workspace_case_home_terminal_lines,
    build_workspace_manifest_lines,
    resolve_workspace_case_home_entry_label,
    build_workspace_recent_flow_lines,
)
