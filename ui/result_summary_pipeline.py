from __future__ import annotations

from dataclasses import dataclass

from core.analysis_recommendations import result_action_payloads, result_next_steps


@dataclass(frozen=True)
class ResultSummarySnapshot:
    sections: dict[str, object]
    overview_labels: tuple[str, ...]
    total_events: int
    total_unique_items: int
    actions: tuple[dict[str, str], ...]
    next_steps: tuple[str, ...]

    @property
    def has_hits(self) -> bool:
        return any(
            isinstance(value, list) and value
            for key, value in self.sections.items()
            if not str(key).endswith('_total_hits')
        )


def build_result_summary_snapshot(
    sections: dict[str, object],
    *,
    category_rules,
) -> ResultSummarySnapshot:
    overview_labels = tuple(
        rule.overview_label
        for rule in category_rules
        if sections.get(rule.section_key)
    )
    total_events = sum(int(sections.get(rule.total_hits_key) or 0) for rule in category_rules)
    total_unique_items = sum(len(sections.get(rule.section_key) or []) for rule in category_rules)
    actions = tuple(result_action_payloads(sections))
    next_steps = tuple(result_next_steps(sections))
    return ResultSummarySnapshot(
        sections=dict(sections),
        overview_labels=overview_labels,
        total_events=total_events,
        total_unique_items=total_unique_items,
        actions=actions,
        next_steps=next_steps,
    )
