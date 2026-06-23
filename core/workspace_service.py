from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Optional

from .errors import (
    WorkspaceApkPullError,
    WorkspaceFileWriteError,
    WorkspaceInitializationError,
    WorkspaceResourceMissingError,
    WorkspaceScriptMissingError,
    WorkspaceFileReadError,
)
from .analysis_recommendations import infer_result_summary_sections_from_text, preferred_case_entrypoint, result_action_payloads
from .models import AppContext, HookerContext
from ui import ui_messages


BUILTIN_JS_FILES = [
    "android_ui.js",
    "apk_shell_scanner.js",
    "bypass_frida_svc_detect.js",
    "bypass_root_detect.js",
    "bypass_vpn_detect.js",
    "click.js",
    "detect_network_stack.js",
    "DumpDex.js",
    "edit_text.js",
    "find_anit_frida_so.js",
    "get_device_info.js",
    "hook_encryption_algo.js",
    "hook_encryption_algo2.js",
    "hook_register_natives.js",
    "trace_init_proc.js",
    "jni_method_trace.js",
    "just_trust_me.js",
    "keystore_dump.js",
    "okhttp.js",
    "print_okhttp_interceptors.js",
    "replace_dlsym_get_pthread_create.js",
    "text_view.js",
    "url.js",
    "activity_events.js",
]

GUI_RESOURCE_JS_FILES = BUILTIN_JS_FILES + [
    "_hook_js_enhance.js",
    "_hook_js_prepare.js",
    "_hook_js_warp.js",
    "rpc.js",
]

DEFAULT_PACKAGE_PLACEHOLDER = "com.smile.gifmaker"
WORKSPACE_BUILTIN_PREFIX = "内置-"
SCRIPT_LIBRARY_FILENAME = "script_library.json"
SCRIPT_LIBRARY_VERSION = 1
SESSIONS_FILENAME = "sessions.jsonl"
WORKSPACE_MANIFEST_FILENAME = "workspace_manifest.json"
LATEST_RESULT_SUMMARY_FILENAME = "result_summary_latest.md"
ADVANCED_LAUNCHER_PRESETS_FILENAME = "advanced_launcher_presets.json"
ADVANCED_LAUNCHER_TEMPLATES_FILENAME = "advanced_launcher_templates.json"
_ALLOWED_RECOMMENDED_MODES = {"attach", "spawn", "either"}
from .builtin_script_knowledge import BUILTIN_SCRIPT_DEFAULT_METADATA



@dataclass(frozen=True)
class ScriptMetadata:
    name: str
    pinned: bool = False
    last_used_at: str | None = None
    recommended_mode: str = "either"
    summary: str = ""
    tags: tuple[str, ...] = ()
    use_when: str = ""
    caution: str = ""


@dataclass(frozen=True)
class ScriptSourceInfo:
    name: str
    path: Path
    source_kind: str
    is_builtin: bool
    is_parameter_template: bool
    display_label: str
    metadata: ScriptMetadata | None = None

@dataclass(frozen=True)
class SessionRecord:
    timestamp: str
    package_name: str
    script_name: str
    script_path: str
    mode: str
    source_kind: str | None = None
    summary: str = ""


@dataclass(frozen=True)
class AdvancedLauncherPresetEntry:
    label: str
    path: str
    kind: str = "plain"
    source_kind: str = "workspace"
    display_name: str | None = None
    summary: str | None = None
    template_path: str | None = None
    config_payload: object | None = None
    runtime_key: str | None = None
    is_pinned: bool = False
    last_used_at: str | None = None
    tags: tuple[str, ...] = ()
    note: str = ""
    mode_strategy: str = "inherit"
    auto_stop: bool = False


@dataclass(frozen=True)
class AdvancedLauncherPresetSnapshot:
    note: str = ""
    entries: tuple[AdvancedLauncherPresetEntry, ...] = ()


@dataclass(frozen=True)
class AdvancedLauncherNamedTemplate:
    name: str
    updated_at: str | None = None
    last_used_at: str | None = None
    note: str = ""
    last_result_summary_excerpt: str = ""
    last_result_summary_at: str | None = None
    last_result_session_timestamp: str | None = None
    last_result_script_name: str | None = None
    entries: tuple[AdvancedLauncherPresetEntry, ...] = ()


class WorkspaceService:
    # 负责工作目录、脚本资源和产物文件管理。
    def __init__(self, context: HookerContext) -> None:
        self.context = context

    @staticmethod
    def _normalize_recommended_mode(value: object) -> str:
        normalized = str(value or "either").strip().lower()
        return normalized if normalized in _ALLOWED_RECOMMENDED_MODES else "either"

    @staticmethod
    def _normalize_summary(value: object) -> str:
        summary = str(value or "").strip()
        return summary[:120]

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

    def script_library_path(self, package_name: str) -> Path:
        return self.workspace_dir(package_name) / SCRIPT_LIBRARY_FILENAME

    def _metadata_to_json(self, metadata: ScriptMetadata) -> dict[str, object]:
        payload: dict[str, object] = {
            "pinned": metadata.pinned,
            "last_used_at": metadata.last_used_at,
            "recommended_mode": self._normalize_recommended_mode(metadata.recommended_mode),
            "summary": self._normalize_summary(metadata.summary),
            "tags": list(self._normalize_tags(metadata.tags)),
            "use_when": self._normalize_summary(metadata.use_when),
            "caution": self._normalize_summary(metadata.caution),
        }
        return payload

    def _metadata_from_raw(self, script_name: str, raw: object) -> ScriptMetadata | None:
        if not isinstance(raw, dict):
            return None
        return ScriptMetadata(
            name=script_name,
            pinned=bool(raw.get("pinned", False)),
            last_used_at=str(raw.get("last_used_at") or "").strip() or None,
            recommended_mode=self._normalize_recommended_mode(raw.get("recommended_mode")),
            summary=self._normalize_summary(raw.get("summary")),
            tags=self._normalize_tags(raw.get("tags")),
            use_when=self._normalize_summary(raw.get("use_when")),
            caution=self._normalize_summary(raw.get("caution")),
        )

    def load_script_library(self, package_name: str) -> dict[str, ScriptMetadata]:
        path = self.script_library_path(package_name)
        if not path.is_file():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.context.emit(f"[TOOL] 读取脚本资产 metadata 失败：{path} -> {exc}")
            return {}
        if not isinstance(raw, dict):
            return {}
        scripts_raw = raw.get("scripts")
        if not isinstance(scripts_raw, dict):
            return {}
        result: dict[str, ScriptMetadata] = {}
        for script_name, item in scripts_raw.items():
            if not isinstance(script_name, str):
                continue
            metadata = self._metadata_from_raw(script_name, item)
            if metadata is not None:
                result[script_name] = metadata
        return result

    def save_script_library(self, package_name: str, metadata_map: dict[str, ScriptMetadata]) -> Path:
        path = self.script_library_path(package_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": SCRIPT_LIBRARY_VERSION,
            "scripts": {
                name: self._metadata_to_json(metadata)
                for name, metadata in sorted(metadata_map.items(), key=lambda item: item[0].lower())
            },
        }
        temp_path = path.with_suffix(path.suffix + ".tmp")
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        try:
            temp_path.write_text(text, encoding="utf-8", newline="")
            temp_path.replace(path)
        except OSError as exc:
            raise WorkspaceFileWriteError(
                f"写入脚本资产 metadata 失败: {path}",
                hint="请检查当前工作区目录是否可写，以及磁盘空间是否充足。",
            ) from exc
        return path

    def default_script_metadata(self, script_name: str) -> ScriptMetadata | None:
        raw = BUILTIN_SCRIPT_DEFAULT_METADATA.get(script_name)
        if raw is None:
            return None
        return ScriptMetadata(
            name=script_name,
            pinned=bool(raw.get("pinned", False)),
            recommended_mode=self._normalize_recommended_mode(raw.get("recommended_mode")),
            summary=self._normalize_summary(raw.get("summary")),
            tags=self._normalize_tags(raw.get("tags")),
            use_when=self._normalize_summary(raw.get("use_when")),
            caution=self._normalize_summary(raw.get("caution")),
        )

    def _find_metadata_entry(
        self,
        metadata_map: dict[str, ScriptMetadata],
        script_name: str,
    ) -> tuple[str, ScriptMetadata] | None:
        metadata = metadata_map.get(script_name)
        if metadata is not None:
            return script_name, metadata
        normalized_name = script_name.lower()
        for key, value in metadata_map.items():
            if key.lower() == normalized_name:
                return key, value
        return None

    def resolve_script_metadata(self, package_name: str, script_name: str) -> ScriptMetadata | None:
        metadata_map = self.load_script_library(package_name)
        entry = self._find_metadata_entry(metadata_map, script_name)
        if entry is not None:
            return entry[1]
        return self.default_script_metadata(script_name)

    def set_script_pinned(self, package_name: str, script_name: str, pinned: bool) -> ScriptMetadata:
        return self.update_script_metadata(package_name, script_name, pinned=pinned)

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
        metadata_map = self.load_script_library(package_name)
        entry = self._find_metadata_entry(metadata_map, script_name)
        existing_key = entry[0] if entry is not None else None
        current = (
            entry[1]
            if entry is not None
            else self.default_script_metadata(script_name)
            or ScriptMetadata(name=script_name)
        )
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
            updated = ScriptMetadata(
                name=script_name,
                pinned=updated.pinned,
                last_used_at=updated.last_used_at,
                recommended_mode=updated.recommended_mode,
                summary=updated.summary,
                tags=updated.tags,
                use_when=updated.use_when,
                caution=updated.caution,
            )
        metadata_map[script_name] = updated
        self.save_script_library(package_name, metadata_map)
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
        metadata_map = self.load_script_library(package_name)
        entry = self._find_metadata_entry(metadata_map, script_name)
        existing_key = entry[0] if entry is not None else None
        current = entry[1] if entry is not None else self.default_script_metadata(script_name) or ScriptMetadata(name=script_name)
        updated = ScriptMetadata(
            name=script_name,
            pinned=current.pinned,
            last_used_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            recommended_mode=self._normalize_recommended_mode(current.recommended_mode),
            summary=current.summary or self._normalize_summary(summary),
            tags=current.tags,
            use_when=current.use_when,
            caution=current.caution,
        )
        if existing_key is not None and existing_key != script_name:
            metadata_map.pop(existing_key, None)
            updated = ScriptMetadata(
                name=script_name,
                pinned=updated.pinned,
                last_used_at=updated.last_used_at,
                recommended_mode=updated.recommended_mode,
                summary=updated.summary,
                tags=updated.tags,
                use_when=updated.use_when,
                caution=updated.caution,
            )
        metadata_map[script_name] = updated
        self.save_script_library(package_name, metadata_map)
        return updated

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

    def _sorting_metadata(self, package_name: str, info: ScriptSourceInfo) -> ScriptMetadata | None:
        if info.metadata is not None:
            return info.metadata
        return self.resolve_script_metadata(package_name, info.name)

    @staticmethod
    def _source_kind_priority(source_kind: str) -> int:
        order = {
            "workspace": 0,
            "workspace_builtin_copy": 1,
            "builtin_source": 2,
        }
        return order.get(source_kind, 99)

    @staticmethod
    def _metadata_timestamp(metadata: ScriptMetadata | None) -> float:
        if metadata is None or not metadata.last_used_at:
            return 0.0
        try:
            return datetime.fromisoformat(metadata.last_used_at).timestamp()
        except ValueError:
            return 0.0

    def _sorted_script_sources(self, package_name: str, sources: list[ScriptSourceInfo]) -> list[ScriptSourceInfo]:
        return sorted(
            sources,
            key=lambda info: (
                0 if (self._sorting_metadata(package_name, info) and self._sorting_metadata(package_name, info).pinned) else 1,
                -self._metadata_timestamp(self._sorting_metadata(package_name, info)),
                self._source_kind_priority(info.source_kind),
                info.name.lower(),
            ),
        )

    def workspace_dir(self, package_name: str) -> Path:
        # 返回某个包名对应的工作目录。
        return self.context.workspaces_dir / package_name

    def script_dir(self, package_name: str) -> Path:
        # 返回某个包名对应的脚本目录。
        return self.workspace_dir(package_name) / "js"
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
        try:
            content = note_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise WorkspaceFileReadError(
                f"读取工作区分析笔记失败: {note_path}",
                hint="请检查当前工作区 notes 目录及分析笔记文件是否可读后重试。",
            ) from exc
        return content if content.strip() else self.default_workspace_note_template(package_name)

    def write_workspace_note(self, package_name: str, content: str) -> Path:
        note_path = self.default_note_file_path(package_name)
        note_path.parent.mkdir(parents=True, exist_ok=True)
        normalized_content = str(content)
        if not normalized_content.strip():
            normalized_content = self.default_workspace_note_template(package_name)
        try:
            note_path.write_text(normalized_content, encoding="utf-8", newline="")
        except OSError as exc:
            raise WorkspaceFileWriteError(
                f"写入工作区分析笔记失败: {note_path}",
                hint="请检查当前工作区 notes 目录是否可写，以及磁盘空间是否充足。",
            ) from exc
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
        try:
            note_path.write_text(merged, encoding="utf-8", newline="")
        except OSError as exc:
            raise WorkspaceFileWriteError(
                f"追加工作区分析笔记失败: {note_path}",
                hint="请检查当前工作区 notes 目录是否可写，以及磁盘空间是否充足。",
            ) from exc
        return note_path

    def write_latest_result_summary(self, package_name: str, content: str) -> Path:
        summary_path = self.workspace_recent_result_summary_path(package_name)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        normalized = str(content or '').strip()
        try:
            summary_path.write_text((normalized + "\n") if normalized else "", encoding="utf-8", newline="")
        except OSError as exc:
            raise WorkspaceFileWriteError(
                f"写入最近结果摘要失败: {summary_path}",
                hint="请检查当前工作区目录是否可写，以及磁盘空间是否充足。",
            ) from exc
        return summary_path

    def read_latest_result_summary(self, package_name: str) -> str:
        summary_path = self.workspace_recent_result_summary_path(package_name)
        if not summary_path.is_file():
            return ""
        try:
            return summary_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise WorkspaceFileReadError(
                f"读取最近结果摘要失败: {summary_path}",
                hint="请检查当前工作区结果摘要文件是否可读后重试。",
            ) from exc

    def workspace_note_state(self, package_name: str) -> dict[str, object]:
        note_path = self.default_note_file_path(package_name)
        default_template = self.default_workspace_note_template(package_name)
        try:
            if not note_path.is_file():
                content = default_template
                exists = False
            else:
                content = note_path.read_text(encoding="utf-8")
                exists = True
        except OSError as exc:
            raise WorkspaceFileReadError(
                f"读取工作区分析笔记状态失败: {note_path}",
                hint="请检查当前工作区 notes 目录及分析笔记文件是否可读后重试。",
            ) from exc
        normalized_content = content if content.strip() else default_template
        is_default_template = normalized_content == default_template
        return {
            "path": str(note_path),
            "exists": exists,
            "is_default_template": is_default_template,
            "has_user_content": not is_default_template,
        }

    def sessions_path(self, package_name: str) -> Path:
        return self.workspace_dir(package_name) / SESSIONS_FILENAME

    def workspace_manifest_path(self, package_name: str) -> Path:
        return self.workspace_dir(package_name) / WORKSPACE_MANIFEST_FILENAME

    def workspace_recent_result_summary_path(self, package_name: str) -> Path:
        return self.workspace_dir(package_name) / LATEST_RESULT_SUMMARY_FILENAME


    def advanced_launcher_presets_path(self, package_name: str) -> Path:
        return self.workspace_dir(package_name) / ADVANCED_LAUNCHER_PRESETS_FILENAME

    def advanced_launcher_templates_path(self, package_name: str) -> Path:
        return self.workspace_dir(package_name) / ADVANCED_LAUNCHER_TEMPLATES_FILENAME

    @staticmethod
    def _normalize_advanced_launcher_note(value: object) -> str:
        note = str(value or "").strip()
        return note[:120]

    @staticmethod
    def _normalize_advanced_launcher_mode_strategy(value: object) -> str:
        normalized = str(value or "inherit").strip().lower()
        return normalized if normalized in {"inherit", "attach", "spawn"} else "inherit"

    def _preset_entry_to_json(self, entry: AdvancedLauncherPresetEntry) -> dict[str, object]:
        return {
            "label": str(entry.label or "").strip(),
            "path": str(entry.path or "").strip(),
            "kind": str(entry.kind or "plain").strip() or "plain",
            "source_kind": str(entry.source_kind or "workspace").strip() or "workspace",
            "display_name": str(entry.display_name).strip() if entry.display_name is not None and str(entry.display_name).strip() else None,
            "summary": self._normalize_summary(entry.summary) if entry.summary is not None else None,
            "template_path": str(entry.template_path).strip() if entry.template_path is not None and str(entry.template_path).strip() else None,
            "config_payload": entry.config_payload,
            "runtime_key": str(entry.runtime_key).strip() if entry.runtime_key is not None and str(entry.runtime_key).strip() else None,
            "is_pinned": bool(entry.is_pinned),
            "last_used_at": str(entry.last_used_at or "").strip() or None,
            "tags": list(self._normalize_tags(entry.tags)),
            "note": self._normalize_advanced_launcher_note(entry.note),
            "mode_strategy": self._normalize_advanced_launcher_mode_strategy(entry.mode_strategy),
            "auto_stop": bool(entry.auto_stop),
        }

    def _preset_entry_from_raw(self, raw: object) -> AdvancedLauncherPresetEntry | None:
        if not isinstance(raw, dict):
            return None
        label = str(raw.get("label") or "").strip()
        path = str(raw.get("path") or "").strip()
        if not label or not path:
            return None
        display_name = str(raw.get("display_name") or "").strip() or None
        summary_value = raw.get("summary")
        summary = self._normalize_summary(summary_value) if summary_value is not None else None
        template_value = str(raw.get("template_path") or "").strip()
        runtime_value = str(raw.get("runtime_key") or "").strip()
        return AdvancedLauncherPresetEntry(
            label=label,
            path=path,
            kind=str(raw.get("kind") or "plain").strip() or "plain",
            source_kind=str(raw.get("source_kind") or "workspace").strip() or "workspace",
            display_name=display_name,
            summary=summary,
            template_path=template_value or None,
            config_payload=raw.get("config_payload"),
            runtime_key=runtime_value or None,
            is_pinned=bool(raw.get("is_pinned", False)),
            last_used_at=str(raw.get("last_used_at") or "").strip() or None,
            tags=self._normalize_tags(raw.get("tags")),
            note=self._normalize_advanced_launcher_note(raw.get("note")),
            mode_strategy=self._normalize_advanced_launcher_mode_strategy(raw.get("mode_strategy")),
            auto_stop=bool(raw.get("auto_stop", False)),
        )

    def load_advanced_launcher_preset_snapshot(self, package_name: str) -> AdvancedLauncherPresetSnapshot:
        path = self.advanced_launcher_presets_path(package_name)
        if not path.is_file():
            return AdvancedLauncherPresetSnapshot()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.context.emit(f"[TOOL] 读取高级启动器预设失败：{path} -> {exc}")
            return AdvancedLauncherPresetSnapshot()
        if not isinstance(raw, dict):
            return AdvancedLauncherPresetSnapshot()
        note = self._normalize_advanced_launcher_note(raw.get("note"))
        entries_raw = raw.get("selected_options")
        if not isinstance(entries_raw, list):
            return AdvancedLauncherPresetSnapshot(note=note)
        result: list[AdvancedLauncherPresetEntry] = []
        for item in entries_raw:
            entry = self._preset_entry_from_raw(item)
            if entry is not None:
                result.append(entry)
        return AdvancedLauncherPresetSnapshot(note=note, entries=tuple(result))

    def load_advanced_launcher_presets(self, package_name: str) -> list[AdvancedLauncherPresetEntry]:
        return list(self.load_advanced_launcher_preset_snapshot(package_name).entries)

    def _named_template_to_json(self, template: AdvancedLauncherNamedTemplate) -> dict[str, object]:
        return {
            "name": str(template.name or "").strip(),
            "updated_at": str(template.updated_at or "").strip() or None,
            "last_used_at": str(template.last_used_at or "").strip() or None,
            "note": self._normalize_advanced_launcher_note(template.note),
            "last_result_summary_excerpt": self._normalize_summary(template.last_result_summary_excerpt),
            "last_result_summary_at": str(template.last_result_summary_at or "").strip() or None,
            "last_result_session_timestamp": str(template.last_result_session_timestamp or "").strip() or None,
            "last_result_script_name": str(template.last_result_script_name or "").strip()[:120] or None,
            "entries": [self._preset_entry_to_json(entry) for entry in template.entries],
        }

    def _named_template_from_raw(self, raw: object) -> AdvancedLauncherNamedTemplate | None:
        if not isinstance(raw, dict):
            return None
        name = str(raw.get("name") or "").strip()
        if not name:
            return None
        entries_raw = raw.get("entries")
        entries: list[AdvancedLauncherPresetEntry] = []
        if isinstance(entries_raw, list):
            for item in entries_raw:
                entry = self._preset_entry_from_raw(item)
                if entry is not None:
                    entries.append(entry)
        return AdvancedLauncherNamedTemplate(
            name=name[:80],
            updated_at=str(raw.get("updated_at") or "").strip() or None,
            last_used_at=str(raw.get("last_used_at") or "").strip() or None,
            note=self._normalize_advanced_launcher_note(raw.get("note")),
            last_result_summary_excerpt=self._normalize_summary(raw.get("last_result_summary_excerpt")),
            last_result_summary_at=str(raw.get("last_result_summary_at") or "").strip() or None,
            last_result_session_timestamp=str(raw.get("last_result_session_timestamp") or "").strip() or None,
            last_result_script_name=str(raw.get("last_result_script_name") or "").strip()[:120] or None,
            entries=tuple(entries),
        )

    def load_advanced_launcher_named_templates(self, package_name: str) -> list[AdvancedLauncherNamedTemplate]:
        path = self.advanced_launcher_templates_path(package_name)
        if not path.is_file():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.context.emit(f"[TOOL] 读取高级启动器任务模板失败：{path} -> {exc}")
            return []
        if not isinstance(raw, dict):
            return []
        templates_raw = raw.get("templates")
        if not isinstance(templates_raw, list):
            return []
        result: list[AdvancedLauncherNamedTemplate] = []
        for item in templates_raw:
            template = self._named_template_from_raw(item)
            if template is not None:
                result.append(template)
        result.sort(
            key=self._advanced_launcher_template_sort_key,
            reverse=True,
        )
        return result

    @staticmethod
    def _advanced_launcher_template_sort_key(template: AdvancedLauncherNamedTemplate) -> tuple[int, str, int, str, int]:
        last_used_at = str(template.last_used_at or "").strip()
        updated_at = str(template.updated_at or "").strip()
        return (
            0 if last_used_at else 1,
            last_used_at,
            0 if updated_at else 1,
            updated_at,
            template.name.lower(),
        )

    def save_advanced_launcher_named_templates(
        self,
        package_name: str,
        templates: list[AdvancedLauncherNamedTemplate],
    ) -> Path:
        path = self.advanced_launcher_templates_path(package_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "package_name": package_name,
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "templates": [self._named_template_to_json(item) for item in templates],
        }
        temp_path = path.with_suffix(path.suffix + ".tmp")
        text_payload = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        try:
            temp_path.write_text(text_payload, encoding="utf-8", newline="")
            temp_path.replace(path)
        except OSError as exc:
            raise WorkspaceFileWriteError(
                f"写入高级启动器任务模板失败: {path}",
                hint="请检查当前工作区目录是否可写，以及磁盘空间是否充足。",
            ) from exc
        return path

    def upsert_advanced_launcher_named_template(
        self,
        package_name: str,
        name: str,
        entries: list[AdvancedLauncherPresetEntry],
        *,
        note: str = "",
    ) -> list[AdvancedLauncherNamedTemplate]:
        normalized_name = str(name or "").strip()[:80]
        if not normalized_name:
            return self.load_advanced_launcher_named_templates(package_name)
        templates = self.load_advanced_launcher_named_templates(package_name)
        updated_at = datetime.now().astimezone().isoformat(timespec="seconds")
        current_existing = next((item for item in templates if item.name.lower() == normalized_name.lower()), None)
        updated = AdvancedLauncherNamedTemplate(
            name=normalized_name,
            updated_at=updated_at,
            last_used_at=current_existing.last_used_at if current_existing is not None else None,
            note=self._normalize_advanced_launcher_note(note),
            last_result_summary_excerpt=current_existing.last_result_summary_excerpt if current_existing is not None else "",
            last_result_summary_at=current_existing.last_result_summary_at if current_existing is not None else None,
            last_result_session_timestamp=current_existing.last_result_session_timestamp if current_existing is not None else None,
            last_result_script_name=current_existing.last_result_script_name if current_existing is not None else None,
            entries=tuple(entries),
        )
        replaced = False
        result: list[AdvancedLauncherNamedTemplate] = []
        for item in templates:
            if item.name.lower() == normalized_name.lower():
                result.append(updated)
                replaced = True
            else:
                result.append(item)
        if not replaced:
            result.append(updated)
        result.sort(
            key=self._advanced_launcher_template_sort_key,
            reverse=True,
        )
        self.save_advanced_launcher_named_templates(package_name, result)
        return result

    def mark_advanced_launcher_template_used(
        self,
        package_name: str,
        name: str,
    ) -> list[AdvancedLauncherNamedTemplate]:
        normalized_name = str(name or "").strip()
        templates = self.load_advanced_launcher_named_templates(package_name)
        if not normalized_name:
            return templates
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        changed = False
        result: list[AdvancedLauncherNamedTemplate] = []
        for item in templates:
            if item.name.lower() == normalized_name.lower():
                result.append(
                    AdvancedLauncherNamedTemplate(
                        name=item.name,
                        updated_at=item.updated_at,
                        last_used_at=timestamp,
                        note=item.note,
                        last_result_summary_excerpt=item.last_result_summary_excerpt,
                        last_result_summary_at=item.last_result_summary_at,
                        last_result_session_timestamp=item.last_result_session_timestamp,
                        last_result_script_name=item.last_result_script_name,
                        entries=item.entries,
                    )
                )
                changed = True
            else:
                result.append(item)
        if not changed:
            return templates
        result.sort(
            key=self._advanced_launcher_template_sort_key,
            reverse=True,
        )
        self.save_advanced_launcher_named_templates(package_name, result)
        return result

    def update_advanced_launcher_template_result_summary(
        self,
        package_name: str,
        name: str,
        *,
        summary_excerpt: str,
        session_timestamp: str | None = None,
        script_name: str | None = None,
    ) -> list[AdvancedLauncherNamedTemplate]:
        normalized_name = str(name or "").strip()
        templates = self.load_advanced_launcher_named_templates(package_name)
        if not normalized_name:
            return templates
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        excerpt = self._normalize_summary(summary_excerpt)
        changed = False
        result: list[AdvancedLauncherNamedTemplate] = []
        for item in templates:
            if item.name.lower() == normalized_name.lower():
                result.append(
                    AdvancedLauncherNamedTemplate(
                        name=item.name,
                        updated_at=item.updated_at,
                        last_used_at=item.last_used_at,
                        note=item.note,
                        last_result_summary_excerpt=excerpt,
                        last_result_summary_at=timestamp,
                        last_result_session_timestamp=str(session_timestamp or "").strip() or None,
                        last_result_script_name=str(script_name or "").strip()[:120] or None,
                        entries=item.entries,
                    )
                )
                changed = True
            else:
                result.append(item)
        if changed:
            self.save_advanced_launcher_named_templates(package_name, result)
        return result

    def delete_advanced_launcher_named_template(
        self,
        package_name: str,
        name: str,
    ) -> list[AdvancedLauncherNamedTemplate]:
        normalized_name = str(name or "").strip()
        templates = self.load_advanced_launcher_named_templates(package_name)
        if not normalized_name:
            return templates
        result = [item for item in templates if item.name.lower() != normalized_name.lower()]
        self.save_advanced_launcher_named_templates(package_name, result)
        return result

    def save_advanced_launcher_presets(
        self,
        package_name: str,
        entries: list[AdvancedLauncherPresetEntry],
        *,
        note: str = "",
    ) -> Path:
        path = self.advanced_launcher_presets_path(package_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "package_name": package_name,
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "note": self._normalize_advanced_launcher_note(note),
            "selected_options": [self._preset_entry_to_json(entry) for entry in entries],
        }
        temp_path = path.with_suffix(path.suffix + ".tmp")
        text_payload = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        try:
            temp_path.write_text(text_payload, encoding="utf-8", newline="")
            temp_path.replace(path)
        except OSError as exc:
            raise WorkspaceFileWriteError(
                f"写入高级启动器预设失败: {path}",
                hint="请检查当前工作区目录是否可写，以及磁盘空间是否充足。",
            ) from exc
        return path

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
        recent_logs = self._recent_log_file_names(package_name, limit=5)
        note_state = self.workspace_note_state(package_name)
        last_session = recent_sessions[0] if recent_sessions else None
        latest_result_summary_path = self.workspace_recent_result_summary_path(package_name)
        latest_result_summary = self.read_latest_result_summary(package_name)
        latest_result_summary_excerpt = " ".join(str(latest_result_summary).split())[:160]
        last_result_summary_at = None
        if latest_result_summary_path.is_file():
            try:
                last_result_summary_at = datetime.fromtimestamp(
                    latest_result_summary_path.stat().st_mtime,
                    tz=datetime.now().astimezone().tzinfo,
                ).isoformat(timespec="seconds")
            except OSError:
                last_result_summary_at = None
        last_template = None
        templates = self.load_advanced_launcher_named_templates(package_name)
        if templates:
            last_template = sorted(
                templates,
                key=lambda item: (
                    str(item.last_used_at or ""),
                    str(item.updated_at or ""),
                    item.name.lower(),
                ),
                reverse=True,
            )[0]
        script_dir = self.script_dir(package_name)
        script_asset_count = 0
        if script_dir.is_dir():
            try:
                script_asset_count = sum(1 for path in script_dir.iterdir() if path.is_file() and path.suffix.lower() == '.js')
            except OSError:
                script_asset_count = 0
        workspace_ready = self.workspace_dir(package_name).exists() and script_dir.exists()
        recommended_entrypoint, case_entry_hint = preferred_case_entrypoint(
            has_named_template=last_template is not None,
            has_result_summary=bool(latest_result_summary_excerpt),
            has_pinned_scripts=bool(pinned_scripts),
            has_recent_scripts=bool(recent_scripts),
        )
        if last_template is not None and '最近模板' not in case_entry_hint and last_template.name:
            case_entry_hint = f"{case_entry_hint[:-1]}“{last_template.name}”继续，可直接在高级启动器中恢复并编辑。" if case_entry_hint.endswith('。') else f"{case_entry_hint} 最近模板：{last_template.name}"
        recommended_result_action = None
        if latest_result_summary_excerpt:
            summary_sections = infer_result_summary_sections_from_text(latest_result_summary)
            actions = result_action_payloads(summary_sections)
            if actions:
                recommended_result_action = actions[0]
        return {
            "version": 1,
            "package_name": package_name,
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "workspace_ready": bool(workspace_ready),
            "script_asset_count": int(script_asset_count),
            "pinned_script_count": len(pinned_scripts),
            "recent_script_count": len(recent_scripts),
            "named_template_count": len(templates),
            "recommended_entrypoint": recommended_entrypoint,
            "case_entry_hint": case_entry_hint,
            "recommended_result_action_key": (recommended_result_action or {}).get("key") if isinstance(recommended_result_action, dict) else None,
            "recommended_result_action_label": (recommended_result_action or {}).get("label") if isinstance(recommended_result_action, dict) else None,
            "recommended_result_action_entry_type": (recommended_result_action or {}).get("entry_type") if isinstance(recommended_result_action, dict) else None,
            "recommended_result_action_description": (recommended_result_action or {}).get("description") if isinstance(recommended_result_action, dict) else None,
            "notes_path": note_state["path"],
            "notes_exists": bool(note_state["exists"]),
            "notes_is_default_template": bool(note_state["is_default_template"]),
            "notes_has_user_content": bool(note_state["has_user_content"]),
            "latest_result_summary_path": str(latest_result_summary_path),
            "latest_result_summary_exists": bool(latest_result_summary_path.is_file()),
            "latest_result_summary_excerpt": latest_result_summary_excerpt,
            "last_result_summary_at": last_result_summary_at,
            "last_used_template_name": last_template.name if last_template is not None else None,
            "last_used_template_note": last_template.note if last_template is not None else "",
            "last_used_template_last_result_excerpt": (last_template.last_result_summary_excerpt if last_template is not None else ""),
            "last_used_template_last_result_at": (last_template.last_result_summary_at if last_template is not None else None),
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

    def write_workspace_manifest(self, package_name: str) -> Path:
        manifest_path = self.workspace_manifest_path(package_name)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.build_workspace_manifest(package_name)
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        try:
            manifest_path.write_text(text, encoding="utf-8", newline="")
        except OSError as exc:
            raise WorkspaceFileWriteError(
                f"写入工作区档案摘要失败: {manifest_path}",
                hint="请检查当前工作区目录是否可写，以及磁盘空间是否充足。",
            ) from exc
        return manifest_path

    def read_workspace_manifest(self, package_name: str) -> dict[str, object] | None:
        manifest_path = self.workspace_manifest_path(package_name)
        if not manifest_path.is_file():
            return None
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _recent_log_file_names(self, package_name: str, limit: int = 5) -> list[str]:
        logs_dir = self.logs_dir(package_name)
        if not logs_dir.is_dir() or limit <= 0:
            return []
        ranked: list[tuple[float, str]] = []
        try:
            candidates = list(logs_dir.iterdir())
        except OSError:
            return []
        for path in candidates:
            try:
                if not path.is_file() or path.suffix.lower() != ".log":
                    continue
                ranked.append((path.stat().st_mtime, path.name))
            except OSError:
                continue
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [name for _, name in ranked[:limit]]

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
        sessions_path = self.sessions_path(package_name)
        if not sessions_path.is_file() or limit <= 0:
            return []
        try:
            lines = sessions_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        records: list[dict[str, object]] = []
        for line in reversed(lines):
            payload = line.strip()
            if not payload:
                continue
            try:
                raw = json.loads(payload)
            except json.JSONDecodeError:
                continue
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
        sessions_path = self.sessions_path(package_name)
        if not sessions_path.is_file():
            return None
        try:
            lines = sessions_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return None
        normalized_name = str(script_name or "").strip().lower()
        normalized_path = str(script_path).strip() if script_path is not None else None
        normalized_path_ci = normalized_path.lower() if normalized_path else None
        case_insensitive_path_match: dict[str, object] | None = None
        name_match: dict[str, object] | None = None
        for line in reversed(lines):
            payload = line.strip()
            if not payload:
                continue
            try:
                raw = json.loads(payload)
            except json.JSONDecodeError:
                continue
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
            "script_name": script_name or None,
            "script_path": str(script_path) if script_path is not None else None,
            "recommended_mode": self._normalize_recommended_mode(recommended_mode),
            "summary": self._normalize_summary(summary),
            "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "log_file": log_file.name,
            "session_timestamp": session.get("timestamp") if isinstance(session, dict) else None,
            "session_mode": session.get("mode") if isinstance(session, dict) else None,
            "session_script_name": session.get("script_name") if isinstance(session, dict) else None,
            "session_script_path": session.get("script_path") if isinstance(session, dict) else None,
        }

    def write_log_export_manifest(self, log_file: Path, manifest: dict[str, object]) -> Path:
        manifest_path = log_file.with_suffix(log_file.suffix + ".json")
        text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        try:
            manifest_path.write_text(text, encoding="utf-8", newline="")
        except OSError as exc:
            raise WorkspaceFileWriteError(
                f"写入日志导出 manifest 失败: {manifest_path}",
                hint="请检查当前工作区 logs 目录是否可写，以及磁盘空间是否充足。",
            ) from exc
        return manifest_path


    def append_session_record(self, record: SessionRecord) -> Path:
        sessions_path = self.sessions_path(record.package_name)
        sessions_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": record.timestamp,
            "package_name": record.package_name,
            "script_name": record.script_name,
            "script_path": record.script_path,
            "mode": self._normalize_recommended_mode(record.mode),
            "source_kind": record.source_kind,
            "summary": self._normalize_summary(record.summary),
        }
        try:
            with sessions_path.open("a", encoding="utf-8", newline="") as fh:
                fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except OSError as exc:
            raise WorkspaceFileWriteError(
                f"写入会话记录失败: {sessions_path}",
                hint="请检查当前工作区目录是否可写，以及磁盘空间是否充足。",
            ) from exc
        return sessions_path

    def read_local_file(self, filename) -> Optional[str]:
        # 读取本地文本文件，主要用于 JS 脚本和资源文件。
        path = Path(filename)
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            self.context.emit(f"File {path} not found.")
            return None
        except OSError as exc:
            self.context.emit(f"Error reading file {path}: {exc}")
            return None

    def read_js_resource(self, filename: str) -> Optional[str]:
        # 读取项目内置 js 资源。
        return self.read_local_file(self.context.hookers_js_dir / filename)

    def get_resource_script(self, filename: str) -> str:
        # 读取内置脚本；缺失时直接抛错，避免后续拼接出错。
        content = self.read_js_resource(filename)
        if content is None:
            raise WorkspaceResourceMissingError(
                f"缺少内置资源: {filename}",
                hint="请检查项目根目录下的 js 资源是否完整后重试。",
            )
        return content

    def create_working_file(self, filename, text: str) -> Path:
        # 在工作目录中创建文件，并自动补齐父目录。
        path = Path(filename)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="")
        except OSError as exc:
            raise WorkspaceFileWriteError(
                f"写入工作区文件失败: {path}",
                hint="请检查本地工作目录是否可写，以及磁盘空间和文件权限是否正常。",
            ) from exc
        return path

    def _sanitize_filename_component(self, value: Optional[str], fallback: str) -> str:
        raw = (value or "").strip()
        if not raw:
            raw = fallback
        sanitized = "".join(
            ch if ch.isalnum() or ch in "._-() " else "_"
            for ch in raw
        ).strip()
        sanitized = sanitized.rstrip(". ")
        return sanitized or fallback

    def _render_builtin_script(self, js_file: str, package_name: str) -> Optional[str]:
        src = self.context.hookers_js_dir / js_file
        if not src.exists():
            return None
        text = src.read_text(encoding="utf-8", errors="ignore")
        return text.replace(DEFAULT_PACKAGE_PLACEHOLDER, package_name)

    def workspace_builtin_script_name(self, js_file: str) -> str:
        return f"{WORKSPACE_BUILTIN_PREFIX}{js_file}"

    def sync_builtin_scripts_to_workspace(self, package_name: str, script_dir: Path) -> list[Path]:
        # 仅在初始化工作目录时，把当前 GUI 实际使用的内置脚本复制到工作区，
        # 文件名前统一加“内置-”前缀；已有同名文件则保留并跳过。
        script_dir.mkdir(parents=True, exist_ok=True)
        synced_paths: list[Path] = []
        for js_file in BUILTIN_JS_FILES:
            rendered = self._render_builtin_script(js_file, package_name)
            if rendered is None:
                continue
            target = script_dir / self.workspace_builtin_script_name(js_file)
            if target.exists():
                continue
            synced_paths.append(self.create_working_file(target, rendered))
        return synced_paths

    def workspace_apk_path(self, app: AppContext) -> Path:
        safe_name = self._sanitize_filename_component(app.name, app.identifier)
        safe_version = self._sanitize_filename_component(app.version, "unknown")
        return self.workspace_dir(app.identifier) / f"{safe_name}_{safe_version}.apk"

    def pull_current_apk(self, app: AppContext) -> Path:
        # 把当前应用 APK 拉到本地工作目录。
        local_apk_path = self.workspace_apk_path(app)
        remote_apk = f"{app.install_path}/{app.install_apk_filename}"
        try:
            self.context.adb_device.sync.pull(remote_apk, str(local_apk_path))
        except Exception as exc:
            raise WorkspaceApkPullError(
                f"拉取 APK 失败: {remote_apk}",
                hint="请检查设备连接、包安装路径以及当前 ADB/root 状态后重试。",
            ) from exc
        self.context.current_local_apk_path = local_apk_path
        self.context.last_workspace_apk_status = "pulled"
        return local_apk_path

    def ensure_local_apk(self, app: AppContext, refresh: bool = False) -> Path:
        local_apk_path = self.workspace_apk_path(app)
        if refresh or not local_apk_path.exists():
            return self.pull_current_apk(app)
        self.context.current_local_apk_path = local_apk_path
        self.context.last_workspace_apk_status = "reused"
        return local_apk_path

    def ensure_workspace_helpers(self, app: AppContext, package_dir: Path) -> None:
        log_hooking = (
            "@echo off\r\n"
            + "echo hooking %1 > log.txt\r\n"
            + "echo %date% %time% >> log.txt\r\n"
            + f"frida -U -l %1 -N {app.identifier} >> log.txt 2>&1\r\n"
        )
        attach_shell = "@echo off\r\n" + f"frida -U -l %1 -N {app.identifier}\r\n"
        spawn_shell = (
            "@echo off\r\n" + f"frida -U --runtime=v8 -f {app.identifier} -l %1\r\n"
        )
        kill_shell = "@echo off\r\n" + f"frida-kill -U {app.identifier}\r\n"
        objection_shell = (
            "@echo off\r\n" + f"objection -d -g {app.identifier} explore\r\n"
        )

        self.create_working_file(package_dir / "hooking.bat", log_hooking)
        self.create_working_file(package_dir / "attach.bat", attach_shell)
        self.create_working_file(package_dir / "spawn.bat", spawn_shell)
        self.create_working_file(package_dir / "kill.bat", kill_shell)
        self.create_working_file(package_dir / "objection.bat", objection_shell)

    def create_initial_workspace(self, app: AppContext) -> Path:
        # 首次进入某个应用时，初始化默认脚本和辅助 bat 文件。
        package_dir = self.workspace_dir(app.identifier)
        try:
            self.context.workspaces_dir.mkdir(parents=True, exist_ok=True)
            package_dir.mkdir(parents=True, exist_ok=True)
            self.ensure_workspace_helpers(app, package_dir)
            self.sync_builtin_scripts_to_workspace(app.identifier, package_dir / "js")
            self.ensure_local_apk(app, refresh=True)
            self.context.last_workspace_prepare_mode = "created"
            return package_dir
        except WorkspaceInitializationError:
            raise
        except Exception as exc:
            raise WorkspaceInitializationError(
                f"首次初始化工作目录失败: {app.identifier} -> {exc}",
                hint="请检查本地工作区是否可写、设备 APK 是否可拉取，以及内置脚本资源是否完整。",
            ) from exc

    def initialize_existing_workspace(self, app: AppContext) -> Path:
        # 已有工作目录时只补齐辅助资源并刷新本地 APK 副本，
        # 不主动删除或覆盖工作区里已经存在的脚本文件。
        package_dir = self.workspace_dir(app.identifier)
        try:
            self.context.workspaces_dir.mkdir(parents=True, exist_ok=True)
            package_dir.mkdir(parents=True, exist_ok=True)
            self.ensure_workspace_helpers(app, package_dir)
            self.sync_builtin_scripts_to_workspace(app.identifier, package_dir / "js")
            self.ensure_local_apk(app, refresh=False)
            self.context.last_workspace_prepare_mode = "updated"
            return package_dir
        except WorkspaceInitializationError:
            raise
        except Exception as exc:
            raise WorkspaceInitializationError(
                f"补齐已有工作目录失败: {app.identifier} -> {exc}",
                hint="请检查现有工作目录文件是否可读写、设备 APK 是否可拉取，以及内置脚本资源是否完整。",
            ) from exc

    def ensure_workspace(self, app: AppContext) -> Path:
        # 根据工作目录是否存在，选择初始化或补全。
        try:
            self.context.last_workspace_prepare_mode = None
            self.context.last_workspace_apk_status = None
            self.context.workspaces_dir.mkdir(parents=True, exist_ok=True)
            package_dir = self.workspace_dir(app.identifier)
            if package_dir.exists():
                return self.initialize_existing_workspace(app)
            return self.create_initial_workspace(app)
        except WorkspaceInitializationError:
            raise
        except Exception as exc:
            raise WorkspaceInitializationError(
                f"准备工作目录失败: {app.identifier} -> {exc}",
                hint="请检查工作目录路径、本地磁盘权限以及设备 APK 是否可以正常拉取。",
            ) from exc



    def _script_source_kind(self, script_name: str, *, in_workspace: bool) -> str:
        if in_workspace and script_name.startswith(WORKSPACE_BUILTIN_PREFIX):
            return "workspace_builtin_copy"
        if in_workspace:
            return "workspace"
        return "builtin_source"

    def _script_base_name(self, script_name: str, source_kind: str) -> str:
        if source_kind == "workspace_builtin_copy" and script_name.startswith(WORKSPACE_BUILTIN_PREFIX):
            return script_name[len(WORKSPACE_BUILTIN_PREFIX):]
        return script_name

    def is_parameter_template_script(self, script_name: str) -> bool:
        return self._script_base_name(script_name, "builtin_source") in {
            "jni_method_trace.js",
            "trace_init_proc.js",
        }

    def script_source_display_label(self, source_kind: str) -> str:
        if source_kind == "workspace":
            return "工作区"
        if source_kind == "workspace_builtin_copy":
            return "工作区内置副本"
        if source_kind == "builtin_source":
            return "内置源"
        return "自定义"

    def build_script_source_info(self, path: Path, *, source_kind: str) -> ScriptSourceInfo:
        script_name = path.name
        base_name = self._script_base_name(script_name, source_kind)
        is_builtin = source_kind in {"workspace_builtin_copy", "builtin_source"}
        is_parameter_template = self.is_parameter_template_script(base_name)
        parts: list[str] = []
        if is_parameter_template:
            parts.append("参数化")
        parts.append(self.script_source_display_label(source_kind))
        prefix = "] [".join(parts)
        return ScriptSourceInfo(
            name=script_name,
            path=path,
            source_kind=source_kind,
            is_builtin=is_builtin,
            is_parameter_template=is_parameter_template,
            display_label=f"[{prefix}] {script_name}",
            metadata=None,
        )

    def list_script_sources(self, package_name: str) -> list[ScriptSourceInfo]:
        sources: list[ScriptSourceInfo] = []
        script_dir = self.script_dir(package_name)
        if script_dir.is_dir():
            workspace_paths = sorted(
                [path for path in script_dir.iterdir() if path.is_file() and path.suffix == ".js"],
                key=lambda path: path.name.lower(),
            )
            for path in workspace_paths:
                sources.append(
                    self.build_script_source_info(
                        path,
                        source_kind=self._script_source_kind(path.name, in_workspace=True),
                    )
                )

        builtin_paths = sorted(
            [path for path in self.context.hookers_js_dir.glob("*.js") if path.is_file()],
            key=lambda path: path.name.lower(),
        )
        for path in builtin_paths:
            sources.append(self.build_script_source_info(path, source_kind="builtin_source"))
        enriched = [self.enrich_script_source_info(package_name, info) for info in sources]
        return self._sorted_script_sources(package_name, enriched)

    def list_scripts(self, package_name: str) -> list[Path]:
        # 列出某个工作目录下可直接执行的 js 脚本。
        script_dir = self.script_dir(package_name)
        if not script_dir.is_dir():
            return []
        return sorted(
            [
                path
                for path in script_dir.iterdir()
                if path.is_file() and path.suffix == ".js"
            ]
        )

    def script_names(self, package_name: str) -> list[str]:
        # 仅返回脚本文件名，适合给 CLI/GUI 做展示和补全。
        return [path.name for path in self.list_scripts(package_name)]

    def list_workspace_visible_scripts(self, package_name: str) -> list[ScriptSourceInfo]:
        return [
            info
            for info in self.list_script_sources(package_name)
            if info.source_kind in {"workspace", "workspace_builtin_copy"}
        ]

    def list_launcher_candidate_scripts(self, package_name: str) -> list[ScriptSourceInfo]:
        return self._sorted_script_sources(package_name, self.list_script_sources(package_name))

    def list_pinned_scripts(self, package_name: str) -> list[ScriptSourceInfo]:
        return [
            info
            for info in self.list_script_sources(package_name)
            if (self._sorting_metadata(package_name, info) and self._sorting_metadata(package_name, info).pinned)
        ]

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
                infos = [
                    info
                    for info in infos
                    if (self._sorting_metadata(package_name, info) and self._sorting_metadata(package_name, info).pinned)
                ]

        keyword = str(query or "").strip().lower()
        if not keyword:
            return infos

        def matches(info: ScriptSourceInfo) -> bool:
            summary = info.metadata.summary if info.metadata and info.metadata.summary else ""
            tags = " ".join(info.metadata.tags) if info.metadata and info.metadata.tags else ""
            haystack = " ".join(
                [
                    info.name.lower(),
                    info.display_label.lower(),
                    info.source_kind.lower(),
                    summary.lower(),
                    tags.lower(),
                ]
            )
            return keyword in haystack

        return [info for info in infos if matches(info)]

    def available_script_names(self, package_name: str) -> list[str]:
        names: list[str] = []
        seen: set[str] = set()
        for info in self.list_launcher_candidate_scripts(package_name):
            candidate_name = info.name
            lowered = candidate_name.lower()
            if info.source_kind == "builtin_source" and lowered in seen:
                continue
            if lowered in seen:
                continue
            seen.add(lowered)
            names.append(candidate_name)
        return names

    def materialize_multi_script_bundle(
        self,
        package_name: str,
        script_paths: list[str | Path],
        *,
        output_name: str = "frida_multi_bundle.runtime.js",
    ) -> Path:
        if not script_paths:
            raise WorkspaceScriptMissingError(
                "未选择任何脚本。",
                hint="请至少选择一个工作区脚本或内置脚本后再启动。",
            )

        bundle_parts = [
            "// Generated by Frida-Hookers multi-script launcher.",
            "",
        ]

        for index, script_ref in enumerate(script_paths, start=1):
            resolved = self.resolve_script_path(str(script_ref), package_name)
            source_kind = "builtin_source"
            try:
                if resolved.parent == self.script_dir(package_name):
                    source_kind = self._script_source_kind(resolved.name, in_workspace=True)
                elif resolved.parent == self.context.hookers_js_dir:
                    source_kind = "builtin_source"
                script_info = self.build_script_source_info(resolved, source_kind=source_kind)
                script_text = resolved.read_text(encoding="utf-8")
            except OSError as exc:
                raise WorkspaceFileReadError(
                    f"读取脚本失败: {resolved}",
                    hint="请检查脚本文件是否存在且可读后重试。",
                ) from exc

            bundle_parts.extend(
                [
                    f"// ===== BEGIN [{index}] {script_info.display_label} =====",
                    f"// Display: {script_info.display_label}",
                    f"// Source: {resolved.resolve()}",
                    f"// Kind: {script_info.source_kind}",
                    script_text,
                    f"// ===== END [{index}] {script_info.display_label} =====",
                    "",
                ]
            )

        bundle_path = self.script_dir(package_name) / output_name
        return self.create_working_file(bundle_path, "\n".join(bundle_parts))

    def resolve_script_path(self, script_name_or_path: str, package_name: str) -> Path:
        # 把脚本名解析成实际路径。
        # 规则：
        # 1. 绝对路径 / 显式相对路径：按用户给出的路径直接解析；
        # 2. 纯脚本名：工作区真实文件 -> 内置源；
        # 3. 不再把 xxx.js 隐式映射成 内置-xxx.js；只有显式输入内置副本名时才解析到该文件。
        path = Path(script_name_or_path)
        if path.is_absolute():
            return path

        is_explicit_relative_path = path.parent != Path('.') or script_name_or_path.startswith(('.', '..'))
        if is_explicit_relative_path:
            if path.is_file():
                return path.resolve()
            raise WorkspaceScriptMissingError(
                ui_messages.SCRIPT_NOT_FOUND_BODY.format(value=script_name_or_path),
                hint=ui_messages.SCRIPT_NOT_FOUND_HINT,
            )

        workspace_script = self.script_dir(package_name) / script_name_or_path
        if workspace_script.is_file():
            return workspace_script

        builtin_path = self.context.hookers_js_dir / script_name_or_path
        if builtin_path.is_file():
            return builtin_path
        if path.is_file():
            return path
        raise WorkspaceScriptMissingError(
            ui_messages.SCRIPT_NOT_FOUND_BODY.format(value=script_name_or_path),
            hint=ui_messages.SCRIPT_NOT_FOUND_HINT,
        )

    def save_decrypt_output(self, package_name: str, filename: str, content: str) -> Path:
        # 保存脚本通过 send 回传的解密结果。
        safe_package = "".join(
            ch if ch.isalnum() or ch in "._-" else "_"
            for ch in (package_name or "unknown_package")
        )
        safe_filename = Path(filename or "decrypt_output.txt").name
        output_dir = self.workspace_dir(safe_package) / "hook_da5_outputs"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / safe_filename
            normalized_content = (
                content.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")
            )
            output_path.write_text(normalized_content, encoding="utf-8")
            self.context.emit(
                f"解密结果已保存到真实目录: {output_path} ({output_path.stat().st_size} bytes)"
            )
            return output_path
        except OSError as exc:
            raise WorkspaceFileWriteError(
                f"保存解密结果失败: {safe_filename}",
                hint="请检查工作目录输出路径是否可写，以及磁盘空间是否充足。",
            ) from exc
