from __future__ import annotations

from dataclasses import dataclass

from .display_common import join_lines
from .result_summary_pipeline import ResultSummarySnapshot
from .result_display_builders import build_result_action_lines


@dataclass(frozen=True)
class ResultSummaryViewModel:
    snapshot: ResultSummarySnapshot
    summary_text: str
    actions_text: str
    note_block: str


@dataclass(frozen=True)
class ResultSummaryTextSpec:
    empty_message: str
    title: str
    overview_title: str
    overview_sections_template: str
    overview_total_events_template: str
    overview_unique_items_template: str
    next_step_title: str


def build_result_summary_note_block(*, snapshot, category_rules, empty_title: str, empty_message: str) -> str:
    sections = snapshot.sections
    lines = [empty_title]
    any_hits = False
    for rule in category_rules:
        items = sections.get(rule.section_key) or []
        if not items:
            continue
        any_hits = True
        lines.extend(["", rule.note_section_title])
        lines.extend(f"- {item}" for item in items)
    if not any_hits:
        lines.extend(["", empty_message])
    return "\n".join(lines)


def build_result_summary_actions_text(actions) -> str:
    return join_lines(build_result_action_lines(list(actions)))


def append_result_summary_category_block(lines: list[str], sections: dict[str, object], rule) -> None:
    items = sections.get(rule.section_key) or []
    if not items:
        return
    if len(lines) > 4:
        lines.append("")
    recent_items = list(items)[-rule.limit:]
    total_hits = int(sections.get(rule.total_hits_key) or 0)
    lines.extend([
        rule.total_template.format(count=total_hits),
        rule.unique_total_template.format(count=len(items)),
        rule.recent_title_template.format(count=len(recent_items)),
    ])
    lines.extend(f"  - {item}" for item in recent_items)


def build_result_summary_text(
    *,
    snapshot,
    has_log_records: bool,
    category_rules,
    spec: ResultSummaryTextSpec,
    actions_text: str,
) -> str:
    if not has_log_records or not snapshot.has_hits:
        return spec.empty_message
    sections = snapshot.sections
    overview_sections = list(snapshot.overview_labels)
    total_events = snapshot.total_events
    total_unique_items = snapshot.total_unique_items
    lines = [spec.title]
    lines.extend([
        spec.overview_title,
        spec.overview_sections_template.format(sections=" / ".join(overview_sections)),
        spec.overview_total_events_template.format(count=total_events),
        spec.overview_unique_items_template.format(count=total_unique_items),
    ])
    for rule in category_rules:
        append_result_summary_category_block(lines, sections, rule)
    next_steps = list(snapshot.next_steps)
    if next_steps:
        lines.extend(["", spec.next_step_title, *next_steps])
    if actions_text:
        lines.extend(["", actions_text])
    return "\n".join(lines)
