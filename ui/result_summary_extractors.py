from __future__ import annotations

import re
from typing import Iterable


def normalize_result_summary_url(url: str) -> str:
    return str(url or '').rstrip("\"'.,;:!?)>]}")


def normalize_result_summary_activity(raw: str) -> str:
    return str(raw or '').strip().rstrip('.,;)]}>')


def normalize_result_summary_security_hit(raw: str) -> str:
    return str(raw or '').strip().rstrip('.,;)]}>')


def extract_result_summary_urls(messages: Iterable[str], pattern: re.Pattern[str]) -> tuple[list[str], int]:
    ordered_unique: list[str] = []
    seen: set[str] = set()
    total_hits = 0
    for message in messages:
        for match in pattern.finditer(message):
            normalized = normalize_result_summary_url(match.group(0))
            if not normalized:
                continue
            total_hits += 1
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            ordered_unique.append(normalized)
    return ordered_unique, total_hits


def extract_result_summary_activities(messages: Iterable[str], patterns: tuple[re.Pattern[str], ...]) -> tuple[list[str], int]:
    ordered_unique: list[str] = []
    seen: set[str] = set()
    total_hits = 0
    for message in messages:
        for pattern in patterns:
            for match in pattern.finditer(message):
                normalized = normalize_result_summary_activity(match.group(1))
                if not normalized:
                    continue
                total_hits += 1
                key = normalized.lower()
                if key in seen:
                    continue
                seen.add(key)
                ordered_unique.append(normalized)
    return ordered_unique, total_hits


def extract_result_summary_jni_registrations(messages: Iterable[str], patterns: tuple[re.Pattern[str], ...]) -> tuple[list[str], int]:
    ordered_unique: list[str] = []
    seen: set[str] = set()
    total_hits = 0
    for message in messages:
        for pattern in patterns:
            for match in pattern.finditer(message):
                if len(match.groups()) >= 3:
                    normalized = f"{match.group(1)}::{match.group(2)} {match.group(3)}".strip()
                else:
                    normalized = f"{match.group(1)} ({match.group(2)} methods)".strip()
                if not normalized:
                    continue
                total_hits += 1
                key = normalized.lower()
                if key in seen:
                    continue
                seen.add(key)
                ordered_unique.append(normalized)
    return ordered_unique, total_hits


def extract_result_summary_security_hits(messages: Iterable[str], patterns: tuple[re.Pattern[str], ...]) -> tuple[list[str], int]:
    ordered_unique: list[str] = []
    seen: set[str] = set()
    total_hits = 0
    for message in messages:
        for pattern in patterns:
            for match in pattern.finditer(message):
                normalized = normalize_result_summary_security_hit(match.group(0))
                if not normalized:
                    continue
                total_hits += 1
                key = normalized.lower()
                if key in seen:
                    continue
                seen.add(key)
                ordered_unique.append(normalized)
    return ordered_unique, total_hits
