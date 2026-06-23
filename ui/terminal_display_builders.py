from __future__ import annotations

from . import ui_messages
from .display_common import join_lines


def build_terminal_help_category_lines(category: str, command_specs) -> list[str]:
    lines = [ui_messages.TERMINAL_HELP_CATEGORY_TEMPLATE.format(category=category)]
    for spec in command_specs:
        if spec.category != category:
            continue
        lines.append(
            ui_messages.TERMINAL_HELP_COMMAND_TEMPLATE.format(
                usage=spec.usage,
                description=spec.help_text,
            )
        )
    lines.append(ui_messages.TERMINAL_RESULT_LOG.format(message=""))
    return lines


def build_terminal_help_example_lines(command_specs) -> list[str]:
    lines = [ui_messages.TERMINAL_HELP_EXAMPLES_TITLE]
    for spec in command_specs:
        if spec.example:
            lines.append(ui_messages.TERMINAL_HELP_EXAMPLE_TEMPLATE.format(example=spec.example))
    return lines


def build_terminal_help_text(*, header: str, category_order, command_specs) -> str:
    lines = [header]
    for category in category_order:
        lines.extend(build_terminal_help_category_lines(category, command_specs))
    lines.append(ui_messages.TERMINAL_HELP_CATEGORY_TEMPLATE.format(category=ui_messages.TERMINAL_HELP_SHELL_TITLE))
    lines.append(ui_messages.TERMINAL_HELP_SHELL_TEMPLATE.format(rule=ui_messages.TERMINAL_HELP_SHELL_RULE))
    lines.append(ui_messages.TERMINAL_RESULT_LOG.format(message=""))
    lines.extend(build_terminal_help_example_lines(command_specs))
    return join_lines(lines).rstrip()


def build_terminal_sessionmeta_lines(*, title: str, timestamp: str, mode: str, script: str, path_value: str, summary: str) -> list[str]:
    return [
        title,
        ui_messages.TERMINAL_SESSIONMETA_TIMESTAMP.format(value=timestamp),
        ui_messages.TERMINAL_SESSIONMETA_MODE.format(value=mode),
        ui_messages.TERMINAL_SESSIONMETA_SCRIPT.format(value=script),
        ui_messages.TERMINAL_SESSIONMETA_PATH.format(value=path_value),
        ui_messages.TERMINAL_SESSIONMETA_SUMMARY.format(value=summary),
    ]


def build_terminal_logmeta_lines(*, logfile: str, log_file_value: str, manifest_path: str, package_name: str, script_name: str, mode: str, summary: str, exported_at: str, script_path: str) -> list[str]:
    return [
        ui_messages.TERMINAL_LOGMETA_TITLE.format(logfile=logfile),
        ui_messages.TERMINAL_LOGMETA_LOG_FILE.format(value=log_file_value),
        ui_messages.TERMINAL_LOGMETA_MANIFEST_PATH.format(value=manifest_path),
        ui_messages.TERMINAL_LOGMETA_PACKAGE.format(value=package_name),
        ui_messages.TERMINAL_LOGMETA_SCRIPT.format(value=script_name),
        ui_messages.TERMINAL_LOGMETA_MODE.format(value=mode),
        ui_messages.TERMINAL_LOGMETA_SUMMARY.format(value=summary),
        ui_messages.TERMINAL_LOGMETA_EXPORTED_AT.format(value=exported_at),
        ui_messages.TERMINAL_LOGMETA_PATH.format(value=script_path),
    ]


def build_terminal_logs_lines(files: list[str]) -> list[str]:
    if not files:
        return [ui_messages.TERMINAL_LOGS_EMPTY]
    return [
        ui_messages.TERMINAL_LOGS_TITLE,
        *(f"  {name}" for name in files),
    ]


def build_terminal_apps_lines(app_rows: list[dict[str, str]]) -> list[str]:
    if not app_rows:
        return [ui_messages.TERMINAL_APPS_EMPTY_MESSAGE]
    lines = [ui_messages.TERMINAL_APPS_TITLE]
    for row in app_rows:
        lines.append(
            f"  pid={row.get('pid') or '-'} | {row.get('name') or '-'} | {row.get('identifier') or '-'} | 工作区:{row.get('workspace_state') or '-'}"
        )
    return lines


def build_terminal_script_meta_lines(*, script_name: str, path_value: str, source_text: str, pinned_text: str, recommended_mode: str, last_used_at: str, summary: str, use_when: str, caution: str, tags_value: str) -> list[str]:
    return [
        ui_messages.TERMINAL_META_TITLE.format(script=script_name),
        ui_messages.TERMINAL_META_PATH.format(path=path_value),
        ui_messages.TERMINAL_META_SOURCE.format(source=source_text),
        ui_messages.TERMINAL_META_PINNED.format(value=pinned_text),
        ui_messages.TERMINAL_META_RECOMMENDED_MODE.format(value=recommended_mode),
        ui_messages.TERMINAL_META_LAST_USED_AT.format(value=last_used_at),
        ui_messages.TERMINAL_META_SUMMARY.format(value=summary),
        ui_messages.TERMINAL_META_USE_WHEN.format(value=use_when),
        ui_messages.TERMINAL_META_CAUTION.format(value=caution),
        ui_messages.TERMINAL_META_TAGS.format(value=tags_value),
    ]
