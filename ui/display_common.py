from __future__ import annotations

from typing import Iterable

from . import ui_messages


def join_lines(lines: Iterable[str]) -> str:
    return "\n".join(str(line) for line in lines if str(line) != "")


def bool_flag_text(value: object) -> str:
    if value is None:
        return "-"
    return ui_messages.YES_TEXT if bool(value) else ui_messages.NO_TEXT
