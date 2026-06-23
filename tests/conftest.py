from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget
from core.models import AppContext, HookerContext
from core.errors import HookStartError
from core.workspace_service import AdvancedLauncherPresetEntry, AdvancedLauncherPresetSnapshot, ScriptMetadata, ScriptSourceInfo, SessionRecord, BUILTIN_SCRIPT_DEFAULT_METADATA


@dataclass
class DummyAppInfo:
    name: str
    identifier: str
    pid: int | None = None
    uid: int | None = None
    version: str | None = None


@dataclass
class DummyActiveSession:
    mode: str


@dataclass
class DummyContext:
    project_root: Path = field(default_factory=lambda: Path.cwd())
    js_dir: Path = field(default_factory=lambda: Path.cwd() / "js")
    hookers_js_dir: Path = field(default_factory=lambda: Path.cwd() / "hookers" / "js")
    frida_server_arm64: str = "rusda-server-16.2.1-android-arm64"
    local_apk_check_pack_exe: Path = field(
        default_factory=lambda: Path.cwd() / "mobile-deploy" / "ApkCheckPack.exe"
    )
    last_connected_device_serial: str | None = None
    last_prepare_frida_server_status: str | None = None
    last_workspace_prepare_mode: str | None = None
    last_workspace_apk_status: str | None = None
    apps: list[DummyAppInfo] = field(default_factory=list)
    current_app: DummyAppInfo | None = None
    active_session: DummyActiveSession | None = None
    log_handler: object | None = None
    session_event_handler: object | None = None
    emitted: list[str] = field(default_factory=list)

    def emit(self, message: str) -> None:
        self.emitted.append(message)


def build_dummy_context(project_root: Path) -> DummyContext:
    project_root = Path(project_root)
    return DummyContext(
        project_root=project_root,
        js_dir=project_root / "js",
        hookers_js_dir=project_root / "hookers" / "js",
        local_apk_check_pack_exe=project_root / "mobile-deploy" / "ApkCheckPack.exe",
    )


class DummyDeviceService:
    def __init__(self) -> None:
        self.ensure_result = DummyAppInfo("App", "pkg.default", pid=1234, uid=2000, version="1.0")
        self.refresh_result = [self.ensure_result]
        self.stop_calls = 0

    def ensure_app_running(self, package_name: str) -> DummyAppInfo:
        if self.ensure_result.identifier != package_name:
            self.ensure_result = DummyAppInfo("App", package_name, pid=1234, uid=2000, version="1.0")
        return self.ensure_result

    def refresh_applications(self) -> list[DummyAppInfo]:
        return self.refresh_result

    def stop_frida_server(self) -> None:
        self.stop_calls += 1


class DummySessionService:
    def __init__(self) -> None:
        self.stop_calls = 0
        self.restart_calls = 0
        self.attach_calls: list[tuple[str, bool]] = []
        self.spawn_calls: list[tuple[str, bool]] = []

    def stop_active_session(self) -> None:
        self.stop_calls += 1

    def restart_current_app(self) -> None:
        self.restart_calls += 1

    def attach_script(self, script_name_or_path: str, use_v8: bool = False) -> None:
        self.attach_calls.append((script_name_or_path, use_v8))

    def spawn_script(self, script_name_or_path: str, use_v8: bool = False) -> None:
        self.spawn_calls.append((script_name_or_path, use_v8))


class DummyWorkspaceService:
    def __init__(self) -> None:
        self.names_by_package: dict[str, list[str]] = {}
        self.metadata_by_package: dict[str, dict[str, ScriptMetadata]] = {}
        self.context = None
        self.mark_script_used_calls: list[dict[str, object]] = []
        self.set_script_pinned_calls: list[dict[str, object]] = []
        self.append_session_record_calls: list[SessionRecord] = []
        self.advanced_launcher_preset_entries_by_package: dict[str, list[AdvancedLauncherPresetEntry]] = {}
        self.advanced_launcher_preset_note_by_package: dict[str, str] = {}
        self.advanced_launcher_named_templates_by_package: dict[str, list[object]] = {}

    def workspace_dir(self, package_name: str) -> Path:
        root = self.context.project_root if self.context is not None else Path.cwd()
        return root / "workspaces" / package_name

    def logs_dir(self, package_name: str) -> Path:
        return self.workspace_dir(package_name) / "logs"

    def exports_dir(self, package_name: str) -> Path:
        return self.workspace_dir(package_name) / "exports"

    def notes_dir(self, package_name: str) -> Path:
        return self.workspace_dir(package_name) / "notes"

    def default_note_file_path(self, package_name: str) -> Path:
        return self.notes_dir(package_name) / "analysis_notes.md"

    def default_workspace_note_template(self, package_name: str) -> str:
        return "\n".join([
            f"# {package_name} 分析笔记",
            "",
            "## 目标与背景",
            "- 目标应用：",
            "- 目标问题：",
            "- 当前版本：",
            "",
            "## 当前观察",
            "- 入口点：",
            "- 关键类 / 方法：",
            "- 关键脚本：",
            "",
            "## 已验证结论",
            "- ",
            "",
            "## 待继续验证",
            "- ",
            "",
            "## 产物与路径",
            "- log：",
            "- session：",
            "- 其它：",
            "",
        ])

    def read_workspace_note(self, package_name: str) -> str:
        note_path = self.default_note_file_path(package_name)
        if not note_path.is_file():
            return ""
        content = note_path.read_text(encoding="utf-8")
        return content if content.strip() else self.default_workspace_note_template(package_name)

    def write_workspace_note(self, package_name: str, content: str) -> Path:
        note_path = self.default_note_file_path(package_name)
        note_path.parent.mkdir(parents=True, exist_ok=True)
        normalized_content = str(content)
        if not normalized_content.strip():
            normalized_content = self.default_workspace_note_template(package_name)
        note_path.write_text(normalized_content, encoding="utf-8", newline="")
        return note_path

    def append_workspace_note_section(self, package_name: str, content: str) -> Path:
        note_path = self.default_note_file_path(package_name)
        note_path.parent.mkdir(parents=True, exist_ok=True)
        existing = self.read_workspace_note(package_name)
        base = existing if str(existing).strip() else self.default_workspace_note_template(package_name)
        addition = str(content or '').strip()
        merged = base.rstrip()
        if addition:
            merged = f"{merged}\n\n{addition}\n"
        else:
            merged = merged + "\n"
        note_path.write_text(merged, encoding="utf-8", newline="")
        return note_path

    def write_latest_result_summary(self, package_name: str, content: str) -> Path:
        summary_path = self.workspace_recent_result_summary_path(package_name)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        normalized = str(content or '').strip()
        summary_path.write_text((normalized + "\n") if normalized else "", encoding="utf-8", newline="")
        return summary_path

    def read_latest_result_summary(self, package_name: str) -> str:
        summary_path = self.workspace_recent_result_summary_path(package_name)
        if not summary_path.is_file():
            return ""
        return summary_path.read_text(encoding="utf-8")

    def ensure_workspace_asset_dirs(self, package_name: str) -> dict[str, Path]:
        asset_dirs = {
            "logs": self.logs_dir(package_name),
            "exports": self.exports_dir(package_name),
            "notes": self.notes_dir(package_name),
        }
        for path in asset_dirs.values():
            path.mkdir(parents=True, exist_ok=True)
        return asset_dirs

    def list_recent_session_records(self, package_name: str, limit: int = 5) -> list[dict[str, object]]:
        path = self.sessions_path(package_name)
        if not path.is_file() or limit <= 0:
            return []
        import json
        lines = path.read_text(encoding="utf-8").splitlines()
        records: list[dict[str, object]] = []
        for line in reversed(lines):
            payload = line.strip()
            if not payload:
                continue
            raw = json.loads(payload)
            if not isinstance(raw, dict):
                continue
            records.append(raw)
            if len(records) >= limit:
                break
        return records

    def read_recent_session_record(self, package_name: str) -> dict[str, object] | None:
        records = self.list_recent_session_records(package_name, limit=1)
        return records[0] if records else None

    def read_recent_session_record_for_script(
        self,
        package_name: str,
        *,
        script_name: str | None,
        script_path: Path | None,
    ) -> dict[str, object] | None:
        path = self.sessions_path(package_name)
        if not path.is_file():
            return None
        import json
        lines = path.read_text(encoding="utf-8").splitlines()
        normalized_name = str(script_name or "").strip().lower()
        normalized_path = str(script_path).strip() if script_path is not None else None
        normalized_path_ci = normalized_path.lower() if normalized_path else None
        case_insensitive_path_match: dict[str, object] | None = None
        name_match: dict[str, object] | None = None
        for line in reversed(lines):
            payload = line.strip()
            if not payload:
                continue
            raw = json.loads(payload)
            if not isinstance(raw, dict):
                continue
            raw_path = str(raw.get("script_path") or "").strip()
            raw_name = str(raw.get("script_name") or "").strip().lower()
            if normalized_path and raw_path == normalized_path:
                return raw
            if (
                normalized_path_ci
                and raw_path
                and raw_path.lower() == normalized_path_ci
                and case_insensitive_path_match is None
            ):
                case_insensitive_path_match = raw
            if normalized_name and raw_name == normalized_name and name_match is None:
                name_match = raw
        return case_insensitive_path_match or name_match

    def build_log_export_manifest(
        self,
        package_name: str,
        *,
        script_name: str | None,
        script_path: Path | None,
        log_file: Path,
        summary: str | None,
        recommended_mode: str | None,
    ) -> dict[str, object]:
        session = self.read_recent_session_record_for_script(
            package_name,
            script_name=script_name,
            script_path=script_path,
        )
        return {
            "version": 1,
            "package_name": package_name,
            "script_name": script_name,
            "script_path": str(script_path) if script_path is not None else None,
            "recommended_mode": recommended_mode or "either",
            "summary": summary or "",
            "exported_at": "2026-06-08T10:30:00+08:00",
            "log_file": log_file.name,
            "session_timestamp": session.get("timestamp") if isinstance(session, dict) else None,
            "session_mode": session.get("mode") if isinstance(session, dict) else None,
            "session_script_name": session.get("script_name") if isinstance(session, dict) else None,
            "session_script_path": session.get("script_path") if isinstance(session, dict) else None,
        }

    def write_log_export_manifest(self, log_file: Path, manifest: dict[str, object]) -> Path:
        manifest_path = log_file.with_suffix(log_file.suffix + ".json")
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        import json
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest_path

    def build_workspace_manifest(self, package_name: str) -> dict[str, object]:
        recent_scripts = [
            info
            for info in self.list_recent_scripts(package_name, limit=5)
            if info.source_kind in {"workspace", "workspace_builtin_copy"}
        ]
        pinned_scripts = [
            info
            for info in self.list_pinned_scripts(package_name)
            if info.source_kind in {"workspace", "workspace_builtin_copy"}
        ]
        recent_sessions = self.list_recent_session_records(package_name, limit=5)
        note_state = self.workspace_note_state(package_name)
        last_session = recent_sessions[0] if recent_sessions else None
        recent_logs = []
        logs_dir = self.logs_dir(package_name)
        if logs_dir.is_dir():
            ranked: list[tuple[float, str]] = []
            for path in logs_dir.iterdir():
                try:
                    if not path.is_file() or path.suffix.lower() != ".log":
                        continue
                    ranked.append((path.stat().st_mtime, path.name))
                except OSError:
                    continue
            ranked.sort(key=lambda item: item[0], reverse=True)
            recent_logs = [name for _, name in ranked[:5]]
        latest_result_summary_path = self.workspace_recent_result_summary_path(package_name)
        latest_result_summary = self.read_latest_result_summary(package_name)
        latest_result_summary_excerpt = " ".join(str(latest_result_summary).split())[:160]
        templates = self.load_advanced_launcher_named_templates(package_name)
        last_template = None
        if templates:
            last_template = sorted(
                templates,
                key=lambda item: (
                    str(getattr(item, "last_used_at", "") or ""),
                    str(getattr(item, "updated_at", "") or ""),
                    str(getattr(item, "name", "") or "").lower(),
                ),
                reverse=True,
            )[0]
        return {
            "version": 1,
            "package_name": package_name,
            "updated_at": "2026-06-08T10:30:00+08:00",
            "notes_path": note_state["path"],
            "notes_exists": bool(note_state["exists"]),
            "notes_is_default_template": bool(note_state["is_default_template"]),
            "notes_has_user_content": bool(note_state["has_user_content"]),
            "latest_result_summary_path": str(latest_result_summary_path),
            "latest_result_summary_exists": latest_result_summary_path.is_file(),
            "latest_result_summary_excerpt": latest_result_summary_excerpt,
            "last_used_template_name": getattr(last_template, "name", None) if last_template is not None else None,
            "last_used_template_note": getattr(last_template, "note", "") if last_template is not None else "",
            "last_used_template_last_result_excerpt": getattr(last_template, "last_result_summary_excerpt", "") if last_template is not None else "",
            "last_used_template_last_result_at": getattr(last_template, "last_result_summary_at", None) if last_template is not None else None,
            "pinned_scripts": [info.name for info in pinned_scripts],
            "recent_scripts": [info.name for info in recent_scripts],
            "recent_session_count": len(recent_sessions),
            "recent_log_count": len(recent_logs),
            "recent_logs": list(recent_logs),
            "last_session": {
                "timestamp": last_session.get("timestamp") or None,
                "script_name": last_session.get("script_name") or None,
                "mode": last_session.get("mode") or None,
                "summary": last_session.get("summary") or "",
            } if isinstance(last_session, dict) else None,
        }

    def sessions_path(self, package_name: str) -> Path:
        return self.workspace_dir(package_name) / "sessions.jsonl"

    def workspace_recent_result_summary_path(self, package_name: str) -> Path:
        return self.workspace_dir(package_name) / "result_summary_latest.md"

    def advanced_launcher_presets_path(self, package_name: str) -> Path:
        return self.workspace_dir(package_name) / "advanced_launcher_presets.json"

    def advanced_launcher_templates_path(self, package_name: str) -> Path:
        return self.workspace_dir(package_name) / "advanced_launcher_templates.json"

    def load_advanced_launcher_presets(self, package_name: str) -> list[AdvancedLauncherPresetEntry]:
        return list(self.advanced_launcher_preset_entries_by_package.get(package_name, []))

    def load_advanced_launcher_preset_snapshot(self, package_name: str) -> AdvancedLauncherPresetSnapshot:
        return AdvancedLauncherPresetSnapshot(
            note=self.advanced_launcher_preset_note_by_package.get(package_name, ""),
            entries=tuple(self.advanced_launcher_preset_entries_by_package.get(package_name, [])),
        )

    def save_advanced_launcher_presets(
        self,
        package_name: str,
        entries: list[AdvancedLauncherPresetEntry],
        *,
        note: str = "",
    ) -> Path:
        normalized: list[AdvancedLauncherPresetEntry] = []
        for entry in entries:
            normalized.append(
                AdvancedLauncherPresetEntry(
                    label=entry.label,
                    path=entry.path,
                    kind=entry.kind,
                    source_kind=entry.source_kind,
                    display_name=entry.display_name,
                    summary=entry.summary,
                    template_path=entry.template_path,
                    config_payload=entry.config_payload,
                    runtime_key=entry.runtime_key,
                    is_pinned=entry.is_pinned,
                    last_used_at=entry.last_used_at,
                    tags=self._normalize_tags(entry.tags),
                    note=str(entry.note or "").strip()[:120],
                    mode_strategy=str(getattr(entry, "mode_strategy", "inherit") or "inherit").strip().lower() or "inherit",
                    auto_stop=bool(getattr(entry, "auto_stop", False)),
                )
            )
        self.advanced_launcher_preset_entries_by_package[package_name] = normalized
        self.advanced_launcher_preset_note_by_package[package_name] = str(note or "").strip()[:120]
        path = self.advanced_launcher_presets_path(package_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("preset", encoding="utf-8")
        return path


    def load_advanced_launcher_named_templates(self, package_name: str):
        return list(self.advanced_launcher_named_templates_by_package.get(package_name, []))

    def upsert_advanced_launcher_named_template(self, package_name: str, name: str, entries: list[AdvancedLauncherPresetEntry], *, note: str = ""):
        from core.workspace_service import AdvancedLauncherNamedTemplate
        normalized_entries = [
            AdvancedLauncherPresetEntry(
                label=entry.label,
                path=entry.path,
                kind=entry.kind,
                source_kind=entry.source_kind,
                display_name=entry.display_name,
                summary=entry.summary,
                template_path=entry.template_path,
                config_payload=entry.config_payload,
                runtime_key=entry.runtime_key,
                is_pinned=entry.is_pinned,
                last_used_at=entry.last_used_at,
                tags=self._normalize_tags(entry.tags),
                note=str(entry.note or '').strip()[:120],
                mode_strategy=str(getattr(entry, 'mode_strategy', 'inherit') or 'inherit').strip().lower() or 'inherit',
                auto_stop=bool(getattr(entry, 'auto_stop', False)),
            )
            for entry in entries
        ]
        updated = AdvancedLauncherNamedTemplate(name=str(name).strip()[:80], note=str(note or '').strip()[:120], entries=tuple(normalized_entries))
        items = []
        replaced = False
        for item in self.advanced_launcher_named_templates_by_package.get(package_name, []):
            if getattr(item, 'name', '').lower() == updated.name.lower():
                items.append(updated)
                replaced = True
            else:
                items.append(item)
        if not replaced:
            items.append(updated)
        self.advanced_launcher_named_templates_by_package[package_name] = items
        path = self.advanced_launcher_templates_path(package_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('templates', encoding='utf-8')
        return items

    def delete_advanced_launcher_named_template(self, package_name: str, name: str):
        normalized = str(name or '').strip().lower()
        items = [item for item in self.advanced_launcher_named_templates_by_package.get(package_name, []) if getattr(item, 'name', '').lower() != normalized]
        self.advanced_launcher_named_templates_by_package[package_name] = items
        path = self.advanced_launcher_templates_path(package_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('templates', encoding='utf-8')
        return items

    def update_advanced_launcher_template_result_summary(
        self,
        package_name: str,
        name: str,
        *,
        summary_excerpt: str,
        session_timestamp: str | None = None,
        script_name: str | None = None,
    ):
        from core.workspace_service import AdvancedLauncherNamedTemplate
        normalized = str(name or '').strip().lower()
        items = []
        for item in self.advanced_launcher_named_templates_by_package.get(package_name, []):
            if getattr(item, 'name', '').lower() == normalized:
                items.append(
                    AdvancedLauncherNamedTemplate(
                        name=item.name,
                        updated_at=getattr(item, 'updated_at', None),
                        last_used_at=getattr(item, 'last_used_at', None),
                        note=getattr(item, 'note', ''),
                        last_result_summary_excerpt=str(summary_excerpt or '').strip()[:120],
                        last_result_summary_at='2026-06-08T13:30:00+08:00',
                        last_result_session_timestamp=str(session_timestamp or '').strip() or None,
                        last_result_script_name=str(script_name or '').strip() or None,
                        entries=getattr(item, 'entries', ()),
                    )
                )
            else:
                items.append(item)
        self.advanced_launcher_named_templates_by_package[package_name] = items
        return items

    def append_session_record(self, record: SessionRecord) -> Path:
        path = self.sessions_path(record.package_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        import json
        payload = {
            "timestamp": record.timestamp,
            "package_name": record.package_name,
            "script_name": record.script_name,
            "script_path": record.script_path,
            "mode": record.mode,
            "source_kind": record.source_kind,
            "summary": record.summary,
        }
        with path.open("a", encoding="utf-8", newline="") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.append_session_record_calls.append(record)
        return path

    def script_dir(self, package_name: str) -> Path:
        root = self.context.project_root if self.context is not None else Path.cwd()
        return root / "workspaces" / package_name / "js"

    def list_scripts(self, package_name: str) -> list[Path]:
        return [self.script_dir(package_name) / name for name in self.script_names(package_name)]

    def script_names(self, package_name: str) -> list[str]:
        names = list(self.names_by_package.get(package_name, []))
        script_dir = self.script_dir(package_name)
        if script_dir.is_dir():
            for path in sorted(script_dir.glob("*.js"), key=lambda p: p.name.lower()):
                if path.name not in names:
                    names.append(path.name)
        return names

    def _metadata(self, package_name: str, script_name: str) -> ScriptMetadata | None:
        return self.metadata_by_package.get(package_name, {}).get(script_name)

    def _build_info(self, package_name: str, path: Path, source_kind: str) -> ScriptSourceInfo:
        name = path.name
        source_label = self.script_source_display_label(source_kind)
        is_parameter_template = name in {"jni_method_trace.js", "trace_init_proc.js"}
        parts = (["参数化"] if is_parameter_template else []) + [source_label]
        info = ScriptSourceInfo(
            name=name,
            path=path,
            source_kind=source_kind,
            is_builtin=source_kind in {"workspace_builtin_copy", "builtin_source"},
            is_parameter_template=is_parameter_template,
            display_label=f"[{'] ['.join(parts)}] {name}",
            metadata=None,
        )
        return self.enrich_script_source_info(package_name, info)

    def list_workspace_visible_scripts(self, package_name: str) -> list[ScriptSourceInfo]:
        return [
            item
            for item in self.list_script_sources(package_name)
            if item.source_kind in {"workspace", "workspace_builtin_copy"}
        ]

    @staticmethod
    def _source_kind_priority(source_kind: str) -> int:
        order = {
            "workspace": 0,
            "workspace_builtin_copy": 1,
            "builtin_source": 2,
        }
        return order.get(source_kind, 99)

    @staticmethod
    def _normalize_recommended_mode(value: object) -> str:
        normalized = str(value or "either").strip().lower()
        return normalized if normalized in {"attach", "spawn", "either"} else "either"

    @staticmethod
    def _normalize_summary(value: object) -> str:
        return str(value or "").strip()[:120]

    @staticmethod
    def _normalize_tags(value: object) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            return ()
        tags: list[str] = []
        seen: set[str] = set()
        for item in value:
            tag = str(item or "").strip()
            if not tag:
                continue
            normalized_tag = tag[:32]
            lowered = normalized_tag.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            tags.append(normalized_tag)
        return tuple(tags)

    @staticmethod
    def _metadata_timestamp(metadata: ScriptMetadata | None) -> float:
        if metadata is None or not metadata.last_used_at:
            return 0.0
        from datetime import datetime
        try:
            return datetime.fromisoformat(metadata.last_used_at).timestamp()
        except ValueError:
            return 0.0

    def _sorting_metadata(self, package_name: str, info: ScriptSourceInfo) -> ScriptMetadata | None:
        if info.metadata is not None:
            return info.metadata
        return self.resolve_script_metadata(package_name, info.name)

    def _sorted_script_sources(self, package_name: str, infos: list[ScriptSourceInfo]) -> list[ScriptSourceInfo]:
        return sorted(
            infos,
            key=lambda info: (
                0 if (self._sorting_metadata(package_name, info) and self._sorting_metadata(package_name, info).pinned) else 1,
                -self._metadata_timestamp(self._sorting_metadata(package_name, info)),
                self._source_kind_priority(info.source_kind),
                info.name.lower(),
            ),
        )

    def list_launcher_candidate_scripts(self, package_name: str) -> list[ScriptSourceInfo]:
        return self._sorted_script_sources(package_name, self.list_script_sources(package_name))

    def available_script_names(self, package_name: str) -> list[str]:
        names: list[str] = []
        seen: set[str] = set()
        for item in self.list_launcher_candidate_scripts(package_name):
            if item.source_kind == "workspace_builtin_copy":
                continue
            lowered = item.name.lower()
            if item.source_kind == "builtin_source" and lowered in seen:
                continue
            if lowered in seen:
                continue
            seen.add(lowered)
            names.append(item.name)
        return names

    def resolve_script_path(self, script_name_or_path: str, package_name: str) -> Path:
        script_path = self.script_dir(package_name) / script_name_or_path
        if script_path.is_file():
            return script_path
        builtin_path = (self.context.hookers_js_dir if self.context is not None else Path.cwd() / "hookers" / "js") / script_name_or_path
        if builtin_path.is_file():
            return builtin_path
        raise HookStartError(
            f"快捷脚本不存在：{script_name_or_path}",
            hint="请检查工作区脚本目录或项目内置 js 目录中是否存在该脚本。",
        )

    def script_source_display_label(self, source_kind: str) -> str:
        if source_kind == "workspace":
            return "工作区"
        if source_kind == "workspace_builtin_copy":
            return "工作区内置副本"
        return "内置源"

    def list_script_sources(self, package_name: str) -> list[ScriptSourceInfo]:
        items: list[ScriptSourceInfo] = []
        script_dir = self.script_dir(package_name)
        seen_workspace: set[str] = set()
        for name in self.names_by_package.get(package_name, []):
            path = script_dir / name
            source_kind = "workspace_builtin_copy" if name.startswith("内置-") else "workspace"
            items.append(self._build_info(package_name, path, source_kind))
            seen_workspace.add(name)
        if script_dir.is_dir():
            for path in sorted(script_dir.glob("*.js"), key=lambda p: p.name.lower()):
                if path.name in seen_workspace:
                    continue
                source_kind = "workspace_builtin_copy" if path.name.startswith("内置-") else "workspace"
                items.append(self._build_info(package_name, path, source_kind))
        builtin_root = self.context.hookers_js_dir if self.context is not None else Path.cwd() / "hookers" / "js"
        for path in sorted(builtin_root.glob("*.js"), key=lambda p: p.name.lower()):
            items.append(self._build_info(package_name, path, "builtin_source"))
        return items

    def resolve_script_metadata(self, package_name: str, script_name: str) -> ScriptMetadata | None:
        metadata_map = self.metadata_by_package.get(package_name, {})
        metadata = metadata_map.get(script_name)
        if metadata is not None:
            return metadata
        normalized_name = script_name.lower()
        for key, value in metadata_map.items():
            if key.lower() == normalized_name:
                return value
        raw = BUILTIN_SCRIPT_DEFAULT_METADATA.get(script_name)
        if raw is not None:
            return ScriptMetadata(
                name=script_name,
                recommended_mode=self._normalize_recommended_mode(raw.get("recommended_mode")),
                summary=self._normalize_summary(raw.get("summary")),
                tags=self._normalize_tags(raw.get("tags")),
                use_when=self._normalize_summary(raw.get("use_when")),
                caution=self._normalize_summary(raw.get("caution")),
            )
        return None

    def enrich_script_source_info(self, package_name: str, info: ScriptSourceInfo) -> ScriptSourceInfo:
        metadata = None
        if info.source_kind in {"workspace", "workspace_builtin_copy"}:
            metadata = self.resolve_script_metadata(package_name, info.name)
        return ScriptSourceInfo(
            name=info.name,
            path=info.path,
            source_kind=info.source_kind,
            is_builtin=info.is_builtin,
            is_parameter_template=info.is_parameter_template,
            display_label=info.display_label,
            metadata=metadata,
        )

    def list_recent_scripts(self, package_name: str, limit: int = 5) -> list[ScriptSourceInfo]:
        recent = [
            info
            for info in self.list_script_sources(package_name)
            if (self._sorting_metadata(package_name, info) and self._sorting_metadata(package_name, info).last_used_at)
        ]
        recent.sort(
            key=lambda info: (
                -self._metadata_timestamp(self._sorting_metadata(package_name, info)),
                self._source_kind_priority(info.source_kind),
                info.name.lower(),
            )
        )
        return recent[:limit]

    def set_script_pinned(self, package_name: str, script_name: str, pinned: bool) -> ScriptMetadata:
        updated = self.update_script_metadata(package_name, script_name, pinned=pinned)
        self.set_script_pinned_calls.append(
            {"package_name": package_name, "script_name": script_name, "pinned": pinned}
        )
        return updated

    def update_script_metadata(
        self,
        package_name: str,
        script_name: str,
        *,
        pinned: bool | None = None,
        recommended_mode: str | None = None,
        summary: str | None = None,
        tags: tuple[str, ...] | None = None,
        use_when: str | None = None,
        caution: str | None = None,
    ) -> ScriptMetadata:
        metadata_map = self.metadata_by_package.setdefault(package_name, {})
        existing_key = next((key for key in metadata_map if key.lower() == script_name.lower()), None)
        current = metadata_map.get(existing_key) if existing_key is not None else None
        current = current or ScriptMetadata(name=script_name)
        updated = ScriptMetadata(
            name=script_name,
            pinned=current.pinned if pinned is None else bool(pinned),
            last_used_at=current.last_used_at,
            recommended_mode=(
                current.recommended_mode
                if recommended_mode is None
                else self._normalize_recommended_mode(recommended_mode)
            ),
            summary=current.summary if summary is None else self._normalize_summary(summary),
            tags=current.tags if tags is None else self._normalize_tags(tags),
            use_when=current.use_when if use_when is None else self._normalize_summary(use_when),
            caution=current.caution if caution is None else self._normalize_summary(caution),
        )
        if existing_key is not None and existing_key != script_name:
            metadata_map.pop(existing_key, None)
        metadata_map[script_name] = updated
        return updated

    def set_script_summary(self, package_name: str, script_name: str, summary: str) -> ScriptMetadata:
        return self.update_script_metadata(package_name, script_name, summary=summary)

    def set_script_recommended_mode(self, package_name: str, script_name: str, mode: str) -> ScriptMetadata:
        return self.update_script_metadata(package_name, script_name, recommended_mode=mode)

    def set_script_metadata_fields(
        self,
        package_name: str,
        script_name: str,
        *,
        summary: str | None = None,
        recommended_mode: str | None = None,
        tags: tuple[str, ...] | None = None,
        use_when: str | None = None,
        caution: str | None = None,
    ) -> ScriptMetadata:
        return self.update_script_metadata(
            package_name,
            script_name,
            summary=summary,
            recommended_mode=recommended_mode,
            tags=tags,
            use_when=use_when,
            caution=caution,
        )

    def mark_script_used(self, package_name: str, script_name: str, *, mode: str, summary: str | None = None) -> ScriptMetadata:
        metadata_map = self.metadata_by_package.setdefault(package_name, {})
        existing_key = next((key for key in metadata_map if key.lower() == script_name.lower()), None)
        current = metadata_map.get(existing_key) if existing_key is not None else None
        current = current or ScriptMetadata(name=script_name)
        updated = ScriptMetadata(
            name=script_name,
            pinned=current.pinned,
            last_used_at="2026-06-08T10:30:00+08:00",
            recommended_mode=self._normalize_recommended_mode(current.recommended_mode),
            summary=current.summary or self._normalize_summary(summary),
            tags=current.tags,
            use_when=current.use_when,
            caution=current.caution,
        )
        if existing_key is not None and existing_key != script_name:
            metadata_map.pop(existing_key, None)
        metadata_map[script_name] = updated
        self.mark_script_used_calls.append(
            {
                "package_name": package_name,
                "script_name": script_name,
                "mode": mode,
                "summary": summary,
            }
        )
        return updated

    def list_pinned_scripts(self, package_name: str) -> list[ScriptSourceInfo]:
        return [
            info
            for info in self.list_script_sources(package_name)
            if info.metadata and info.metadata.pinned
        ]

    def list_recent_scripts(self, package_name: str, limit: int = 5) -> list[ScriptSourceInfo]:
        recent = [
            info
            for info in self.list_script_sources(package_name)
            if info.metadata and info.metadata.last_used_at
        ]
        recent.sort(
            key=lambda info: (
                -self._metadata_timestamp(info.metadata),
                self._source_kind_priority(info.source_kind),
                info.name.lower(),
            )
        )
        return recent[:limit]

    def filter_script_sources(
        self,
        package_name: str,
        *,
        view: str = "all",
        query: str = "",
    ) -> list[ScriptSourceInfo]:
        normalized_view = str(view or "all").strip().lower()
        if normalized_view == "recent":
            infos = self.list_recent_scripts(package_name, limit=10_000)
        else:
            infos = self.list_script_sources(package_name)
            if normalized_view == "pinned":
                infos = [info for info in infos if info.metadata and info.metadata.pinned]
        keyword = str(query or "").strip().lower()
        if not keyword:
            return infos
        result: list[ScriptSourceInfo] = []
        for info in infos:
            summary = info.metadata.summary if info.metadata and info.metadata.summary else ""
            tags = " ".join(info.metadata.tags) if info.metadata and info.metadata.tags else ""
            haystack = f"{info.name} {info.display_label} {summary} {tags}".lower()
            if keyword in haystack:
                result.append(info)
        return result

    def materialize_multi_script_bundle(
        self,
        package_name: str,
        script_paths: list[str | Path],
        *,
        output_name: str = "frida_multi_bundle.runtime.js",
    ) -> Path:
        target = self.script_dir(package_name) / output_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(str(path) for path in script_paths), encoding="utf-8")
        return target


class DummyRpcService:
    def __init__(self) -> None:
        self.invalidations = 0

    def invalidate_persistent_session(self) -> None:
        self.invalidations += 1

    def generate_hook_script(self, hook_target: str) -> Path:
        root = self.context.project_root if self.context is not None else Path.cwd()
        return root / "workspaces" / "pkg.default" / "js" / f"{hook_target}.js"

    def activitys(self) -> object:
        return ["A", "B"]

    def services(self) -> object:
        return ["S"]

    def object_info(self, target: str) -> object:
        return {"target": target}

    def object_to_explain(self, target: str) -> object:
        return {"explain": target}

    def view_info(self, target: str) -> object:
        return {"view": target}


class DummyApkScanService:
    def __init__(self) -> None:
        self.result = {"stdout": "ok", "stderr": "", "returncode": 0}

    def scan_apk(self, apk_path: Path) -> dict[str, object]:
        return self.result


@dataclass
class DummyDeps:
    device_service: DummyDeviceService = field(default_factory=DummyDeviceService)
    session_service: DummySessionService = field(default_factory=DummySessionService)
    workspace_service: DummyWorkspaceService = field(default_factory=DummyWorkspaceService)
    rpc_service: DummyRpcService = field(default_factory=DummyRpcService)
    apk_scan_service: DummyApkScanService = field(default_factory=DummyApkScanService)
    context: DummyContext = field(default_factory=DummyContext)


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def owner_widget(qapp: QApplication) -> QWidget:
    widget = QWidget()
    yield widget
    widget.deleteLater()


@pytest.fixture
def dummy_deps(tmp_path: Path) -> DummyDeps:
    context = build_dummy_context(tmp_path)
    deps = DummyDeps(context=context)
    deps.workspace_service.context = deps.context
    return deps


@pytest.fixture
def workspace_context(tmp_path: Path) -> HookerContext:
    context = HookerContext.from_project_root(tmp_path)
    context.js_dir.mkdir(parents=True, exist_ok=True)
    context.hookers_js_dir.mkdir(parents=True, exist_ok=True)
    context.workspaces_dir.mkdir(parents=True, exist_ok=True)
    return context


@pytest.fixture
def sample_app_context() -> AppContext:
    return AppContext(
        identifier="com.example.demo",
        name="Demo App",
        pid=1234,
        version="1.2.3",
        install_path="/data/app/demo",
        install_apk_filename="base.apk",
        uid=10086,
    )
