from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ResultActionDescriptor:
    entry_type: str
    executor_label: str
    status_message_builder: Callable[[str, str], str]


RESULT_ACTION_DESCRIPTOR_REGISTRY: dict[str, ResultActionDescriptor] = {}


def register_result_action_descriptor(descriptor: ResultActionDescriptor) -> None:
    RESULT_ACTION_DESCRIPTOR_REGISTRY[descriptor.entry_type.strip().lower()] = descriptor


def resolve_result_action_descriptor(entry_type: str) -> ResultActionDescriptor | None:
    return RESULT_ACTION_DESCRIPTOR_REGISTRY.get(str(entry_type or '').strip().lower())
