from __future__ import annotations

from typing import Callable

from core.result_action_registry import resolve_result_action_descriptor


def run_result_action_with_registry(
    action: dict[str, str],
    *,
    scenario_runner: Callable[[str], None],
    workspace_note_runner: Callable[[], None],
    unsupported_message_builder: Callable[[str], str],
):
    entry_type = str(action.get('entry_type') or '').strip().lower()
    label = str(action.get('label') or action.get('key') or '').strip()
    target = str(action.get('target') or '').strip()
    descriptor = resolve_result_action_descriptor(entry_type)
    if descriptor is None:
        return False, unsupported_message_builder(label or '-')
    if descriptor.entry_type == 'scenario':
        scenario_key = str(action.get('scenario_key') or target).strip()
        if not scenario_key:
            return False, unsupported_message_builder(label or '-')
        scenario_runner(scenario_key)
        return True, descriptor.status_message_builder(label, scenario_key)
    if descriptor.entry_type == 'workspace_note':
        workspace_note_runner()
        return True, descriptor.status_message_builder(label, target)
    return False, unsupported_message_builder(label or '-')
