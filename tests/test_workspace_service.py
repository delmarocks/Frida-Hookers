from __future__ import annotations

from pathlib import Path

import pytest

from core.errors import (
    WorkspaceApkPullError,
    WorkspaceFileWriteError,
    WorkspaceInitializationError,
    WorkspaceResourceMissingError,
    WorkspaceScriptMissingError,
)
from core.workspace_service import AdvancedLauncherPresetEntry, AdvancedLauncherPresetSnapshot, SessionRecord, WorkspaceService, AdvancedLauncherNamedTemplate
from ui import ui_messages


def test_sanitize_filename_component_replaces_invalid_characters(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    sanitized = service._sanitize_filename_component(" Demo:/App*? ", "fallback")
    assert sanitized == "Demo__App__"


def test_workspace_apk_path_uses_sanitized_name_and_version(workspace_context, sample_app_context) -> None:
    service = WorkspaceService(workspace_context)
    path = service.workspace_apk_path(sample_app_context)
    assert path.name == "Demo App_1.2.3.apk"
    assert path.parent == workspace_context.workspaces_dir / sample_app_context.identifier


def test_resolve_script_path_prefers_workspace_script_copy(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    script_dir = service.script_dir(package_name)
    script_dir.mkdir(parents=True, exist_ok=True)
    target = script_dir / "hook.js"
    target.write_text("// demo", encoding="utf-8")
    resolved = service.resolve_script_path("hook.js", package_name)
    assert resolved == target


def test_resolve_script_path_falls_back_to_hookers_builtin_script(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    target = workspace_context.hookers_js_dir / "detect_network_stack.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("// builtin", encoding="utf-8")

    resolved = service.resolve_script_path("detect_network_stack.js", "com.example.demo")
    assert resolved == target


def test_get_resource_script_raises_structured_error_for_missing_resource(workspace_context) -> None:
    service = WorkspaceService(workspace_context)

    with pytest.raises(WorkspaceResourceMissingError):
        service.get_resource_script("missing.js")


def test_resolve_script_path_returns_absolute_path_when_provided(workspace_context, tmp_path: Path) -> None:
    service = WorkspaceService(workspace_context)
    target = tmp_path / "hook.js"
    target.write_text("// demo", encoding="utf-8")

    resolved = service.resolve_script_path(str(target), "com.example.demo")

    assert resolved == target


def test_resolve_script_path_prefers_explicit_relative_path_before_name_lookup(workspace_context, tmp_path: Path) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    workspace_script = service.script_dir(package_name) / "demo.js"
    workspace_script.parent.mkdir(parents=True, exist_ok=True)
    workspace_script.write_text("// workspace demo", encoding="utf-8")

    relative_dir = tmp_path / "scripts"
    relative_dir.mkdir(parents=True, exist_ok=True)
    explicit_target = relative_dir / "demo.js"
    explicit_target.write_text("// explicit relative demo", encoding="utf-8")

    import os
    original_cwd = Path.cwd()
    try:
        os.chdir(tmp_path)
        resolved = service.resolve_script_path(str(Path("scripts") / "demo.js"), package_name)
        assert resolved.is_file()
        assert resolved.read_text(encoding="utf-8") == "// explicit relative demo"
    finally:
        os.chdir(original_cwd)

    assert resolved.name == explicit_target.name
    assert resolved.read_text(encoding="utf-8") != workspace_script.read_text(encoding="utf-8")


def test_resolve_script_path_raises_structured_error_when_missing(workspace_context) -> None:
    service = WorkspaceService(workspace_context)

    with pytest.raises(WorkspaceScriptMissingError):
        service.resolve_script_path("missing.js", "com.example.demo")


def test_materialize_multi_script_bundle_concatenates_scripts_in_order(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"

    workspace_script = service.script_dir(package_name) / "a.js"
    workspace_script.parent.mkdir(parents=True, exist_ok=True)
    workspace_script.write_text("console.log('A');", encoding="utf-8")

    builtin_script = workspace_context.hookers_js_dir / "b.js"
    builtin_script.parent.mkdir(parents=True, exist_ok=True)
    builtin_script.write_text("console.log('B');", encoding="utf-8")

    bundle_path = service.materialize_multi_script_bundle(
        package_name,
        [workspace_script, builtin_script],
    )

    assert bundle_path == service.script_dir(package_name) / "frida_multi_bundle.runtime.js"
    content = bundle_path.read_text(encoding="utf-8")
    assert "BEGIN [1]" in content
    assert "a.js" in content
    assert "console.log('A');" in content
    assert "BEGIN [2]" in content
    assert "b.js" in content
    assert "console.log('B');" in content
    assert "Display:" in content
    assert "Source:" in content
    assert "Kind:" in content
    assert content.index("console.log('A');") < content.index("console.log('B');")


def test_sync_builtin_scripts_to_workspace_copies_with_builtin_prefix(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    script_dir = service.script_dir(package_name)
    builtin = workspace_context.hookers_js_dir / "detect_network_stack.js"
    builtin.parent.mkdir(parents=True, exist_ok=True)
    builtin.write_text("// builtin", encoding="utf-8")

    synced = service.sync_builtin_scripts_to_workspace(package_name, script_dir)

    target = script_dir / "内置-detect_network_stack.js"
    assert target.exists()
    assert target.read_text(encoding="utf-8") == "// builtin"
    assert target in synced


def test_sync_builtin_scripts_to_workspace_copies_new_builtin_frida_scripts(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    script_dir = service.script_dir(package_name)

    svc_detect = workspace_context.hookers_js_dir / "bypass_frida_svc_detect.js"
    svc_detect.parent.mkdir(parents=True, exist_ok=True)
    svc_detect.write_text("// svc detect", encoding="utf-8")

    replace_dlsym = workspace_context.hookers_js_dir / "replace_dlsym_get_pthread_create.js"
    replace_dlsym.write_text("// replace dlsym", encoding="utf-8")

    synced = service.sync_builtin_scripts_to_workspace(package_name, script_dir)

    svc_target = script_dir / "内置-bypass_frida_svc_detect.js"
    replace_target = script_dir / "内置-replace_dlsym_get_pthread_create.js"
    assert svc_target.exists()
    assert svc_target.read_text(encoding="utf-8") == "// svc detect"
    assert replace_target.exists()
    assert replace_target.read_text(encoding="utf-8") == "// replace dlsym"
    assert svc_target in synced
    assert replace_target in synced


def test_sync_builtin_scripts_to_workspace_skips_existing_prefixed_file(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    script_dir = service.script_dir(package_name)
    script_dir.mkdir(parents=True, exist_ok=True)
    target = script_dir / "内置-detect_network_stack.js"
    target.write_text("// keep me", encoding="utf-8")
    builtin = workspace_context.hookers_js_dir / "detect_network_stack.js"
    builtin.parent.mkdir(parents=True, exist_ok=True)
    builtin.write_text("// builtin", encoding="utf-8")

    synced = service.sync_builtin_scripts_to_workspace(package_name, script_dir)

    assert target.read_text(encoding="utf-8") == "// keep me"
    assert target not in synced


def test_ensure_local_apk_uses_existing_file_without_pull(workspace_context, sample_app_context, monkeypatch) -> None:
    service = WorkspaceService(workspace_context)
    existing = service.workspace_apk_path(sample_app_context)
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_bytes(b"apk")

    called = {"pull": False}

    def fail_pull(app):
        called["pull"] = True
        raise AssertionError("pull should not be called")

    monkeypatch.setattr(service, "pull_current_apk", fail_pull)
    path = service.ensure_local_apk(sample_app_context, refresh=False)
    assert path == existing
    assert workspace_context.current_local_apk_path == existing
    assert workspace_context.last_workspace_apk_status == "reused"
    assert called["pull"] is False


def test_pull_current_apk_raises_structured_error_on_pull_failure(workspace_context, sample_app_context) -> None:
    service = WorkspaceService(workspace_context)

    class Sync:
        def pull(self, remote: str, local: str) -> None:
            raise RuntimeError("pull failed")

    workspace_context.adb_device = type("Adb", (), {"sync": Sync()})()

    with pytest.raises(WorkspaceApkPullError):
        service.pull_current_apk(sample_app_context)


def test_create_working_file_raises_structured_error_on_write_failure(workspace_context, tmp_path: Path, monkeypatch) -> None:
    service = WorkspaceService(workspace_context)

    def fail_write(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", fail_write)

    with pytest.raises(WorkspaceFileWriteError):
        service.create_working_file(tmp_path / "demo.txt", "payload")


def test_save_decrypt_output_raises_structured_error_on_write_failure(workspace_context, monkeypatch) -> None:
    service = WorkspaceService(workspace_context)

    def fail_write(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", fail_write)

    with pytest.raises(WorkspaceFileWriteError):
        service.save_decrypt_output("com.example.demo", "out.txt", "hello")




def test_create_initial_workspace_records_summary_state(workspace_context, sample_app_context, monkeypatch) -> None:
    service = WorkspaceService(workspace_context)
    monkeypatch.setattr(service, "ensure_workspace_helpers", lambda app, package_dir: None)
    monkeypatch.setattr(service, "sync_builtin_scripts_to_workspace", lambda package_name, script_dir: [])
    monkeypatch.setattr(service, "ensure_local_apk", lambda app, refresh=False: setattr(workspace_context, "last_workspace_apk_status", "pulled") or service.workspace_apk_path(app))

    package_dir = service.create_initial_workspace(sample_app_context)

    assert package_dir == service.workspace_dir(sample_app_context.identifier)
    assert workspace_context.last_workspace_prepare_mode == "created"
    assert workspace_context.last_workspace_apk_status == "pulled"



def test_initialize_existing_workspace_records_summary_state(workspace_context, sample_app_context, monkeypatch) -> None:
    service = WorkspaceService(workspace_context)
    package_dir = service.workspace_dir(sample_app_context.identifier)
    package_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(service, "ensure_workspace_helpers", lambda app, package_dir: None)
    monkeypatch.setattr(service, "sync_builtin_scripts_to_workspace", lambda package_name, script_dir: [])
    monkeypatch.setattr(service, "ensure_local_apk", lambda app, refresh=False: setattr(workspace_context, "last_workspace_apk_status", "reused") or service.workspace_apk_path(app))

    result = service.initialize_existing_workspace(sample_app_context)

    assert result == package_dir
    assert workspace_context.last_workspace_prepare_mode == "updated"
    assert workspace_context.last_workspace_apk_status == "reused"


def test_initialize_existing_workspace_preserves_existing_workspace_scripts(
    workspace_context,
    sample_app_context,
    monkeypatch,
) -> None:
    service = WorkspaceService(workspace_context)
    package_dir = service.workspace_dir(sample_app_context.identifier)
    script_dir = service.script_dir(sample_app_context.identifier)
    script_dir.mkdir(parents=True, exist_ok=True)
    existing_builtin_named_script = script_dir / "detect_network_stack.js"
    existing_builtin_named_script.write_text("// keep me", encoding="utf-8")
    custom_script = script_dir / "custom.js"
    custom_script.write_text("// custom", encoding="utf-8")

    monkeypatch.setattr(service, "ensure_local_apk", lambda app, refresh=False: service.workspace_apk_path(app))

    result = service.initialize_existing_workspace(sample_app_context)

    assert result == package_dir
    assert existing_builtin_named_script.read_text(encoding="utf-8") == "// keep me"
    assert custom_script.read_text(encoding="utf-8") == "// custom"

def test_ensure_workspace_wraps_initialization_error(workspace_context, sample_app_context, monkeypatch) -> None:
    service = WorkspaceService(workspace_context)

    def fail_initialize(app):
        raise WorkspaceResourceMissingError("缺少内置资源: android_ui.js")

    monkeypatch.setattr(service, "create_initial_workspace", fail_initialize)

    with pytest.raises(WorkspaceInitializationError):
        service.ensure_workspace(sample_app_context)


def test_list_script_sources_includes_workspace_copy_and_builtin_source(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    script_dir = service.script_dir(package_name)
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / "alpha.js").write_text("// alpha", encoding="utf-8")
    (script_dir / "内置-okhttp.js").write_text("// workspace builtin copy", encoding="utf-8")
    builtin = workspace_context.hookers_js_dir / "okhttp.js"
    builtin.parent.mkdir(parents=True, exist_ok=True)
    builtin.write_text("// builtin source", encoding="utf-8")

    sources = service.list_script_sources(package_name)

    labels = [item.display_label for item in sources]
    assert "[工作区] alpha.js" in labels
    assert "[工作区内置副本] 内置-okhttp.js" in labels
    assert "[内置源] okhttp.js" in labels


def test_available_script_names_deduplicates_case_insensitively(workspace_context) -> None:
    context = workspace_context
    service = WorkspaceService(context)
    package_name = "com.example.demo"
    workspace_script_dir = context.workspaces_dir / package_name / "js"
    workspace_script_dir.mkdir(parents=True, exist_ok=True)
    (workspace_script_dir / "Alpha.js").write_text("// upper", encoding="utf-8")
    (context.hookers_js_dir / "alpha.js").write_text("// builtin", encoding="utf-8")

    names = service.available_script_names(package_name)

    assert names == ["Alpha.js"]


def test_available_script_names_prefers_first_visible_name_without_duplicates(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    script_dir = service.script_dir(package_name)
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / "alpha.js").write_text("// alpha", encoding="utf-8")
    (script_dir / "内置-okhttp.js").write_text("// copy", encoding="utf-8")
    builtin = workspace_context.hookers_js_dir / "okhttp.js"
    builtin.parent.mkdir(parents=True, exist_ok=True)
    builtin.write_text("// builtin", encoding="utf-8")

    names = service.available_script_names(package_name)

    assert names.count("okhttp.js") == 1
    assert "内置-okhttp.js" in names


def test_resolve_script_path_prefers_builtin_source_without_implicit_prefixed_mapping(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    script_dir = service.script_dir(package_name)
    script_dir.mkdir(parents=True, exist_ok=True)
    copy_path = script_dir / "内置-detect_network_stack.js"
    copy_path.write_text("// copy", encoding="utf-8")
    builtin = workspace_context.hookers_js_dir / "detect_network_stack.js"
    builtin.parent.mkdir(parents=True, exist_ok=True)
    builtin.write_text("// builtin", encoding="utf-8")

    resolved = service.resolve_script_path("detect_network_stack.js", package_name)

    assert resolved == builtin


def test_resolve_script_path_resolves_explicit_workspace_builtin_copy_name(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    script_dir = service.script_dir(package_name)
    script_dir.mkdir(parents=True, exist_ok=True)
    copy_path = script_dir / "内置-detect_network_stack.js"
    copy_path.write_text("// copy", encoding="utf-8")

    resolved = service.resolve_script_path("内置-detect_network_stack.js", package_name)

    assert resolved == copy_path


from core.workspace_service import AdvancedLauncherNamedTemplate, ScriptMetadata


def test_load_script_library_returns_empty_when_missing(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    assert service.load_script_library("com.example.demo") == {}


def test_resolve_script_metadata_covers_additional_builtin_knowledge_cards(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    for script_name in (
        'url.js',
        'activity_events.js',
        'text_view.js',
        'just_trust_me.js',
        'find_anit_frida_so.js',
        'anti_debug.js',
        'hook_encryption_algo.js',
        'hook_encryption_algo2.js',
        'keystore_dump.js',
        'get_device_info.js',
        'replace_dlsym_get_pthread_create.js',
    ):
        metadata = service.resolve_script_metadata('com.example.demo', script_name)
        assert metadata is not None, script_name
        assert metadata.summary, script_name
        assert metadata.use_when, script_name
        assert metadata.caution, script_name
        assert metadata.tags, script_name


def test_resolve_script_metadata_falls_back_to_builtin_defaults(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    metadata = service.resolve_script_metadata("com.example.demo", "okhttp.js")
    assert metadata is not None
    assert metadata.recommended_mode == "attach"
    assert metadata.summary
    assert metadata.use_when
    assert metadata.caution


def test_load_script_library_returns_empty_when_json_is_invalid(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    path = service.script_library_path("com.example.demo")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{invalid', encoding='utf-8')
    assert service.load_script_library("com.example.demo") == {}


def test_set_script_pinned_persists_and_can_toggle_back(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    metadata = service.set_script_pinned(package_name, "alpha.js", True)
    assert metadata.pinned is True
    saved = service.load_script_library(package_name)
    assert saved["alpha.js"].pinned is True
    metadata = service.set_script_pinned(package_name, "alpha.js", False)
    assert metadata.pinned is False
    saved = service.load_script_library(package_name)
    assert saved["alpha.js"].pinned is False


def test_mark_script_used_writes_timestamp_and_minimal_metadata(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    metadata = service.mark_script_used(package_name, "alpha.js", mode="spawn", summary="demo")
    assert metadata.last_used_at is not None
    assert metadata.recommended_mode in {"attach", "spawn", "either"}
    assert metadata.summary == "demo"

def test_mark_script_used_keeps_existing_either_recommended_mode_without_auto_learning(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    service.save_script_library(
        package_name,
        {
            "alpha.js": ScriptMetadata(
                name="alpha.js",
                recommended_mode="either",
                summary="demo",
            )
        },
    )

    metadata = service.mark_script_used(package_name, "alpha.js", mode="spawn")

    assert metadata.recommended_mode == "either"
    saved = service.load_script_library(package_name)
    assert saved["alpha.js"].recommended_mode == "either"


def test_resolve_script_metadata_matches_library_entry_case_insensitively(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    service.save_script_library(
        package_name,
        {
            "Alpha.js": ScriptMetadata(name="Alpha.js", pinned=True, summary="case summary"),
        },
    )

    resolved = service.resolve_script_metadata(package_name, "alpha.js")

    assert resolved is not None
    assert resolved.pinned is True
    assert resolved.summary == "case summary"



def test_mark_script_used_reuses_existing_metadata_case_insensitively_without_duplicate_keys(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    service.save_script_library(
        package_name,
        {
            "Alpha.js": ScriptMetadata(
                name="Alpha.js",
                pinned=True,
                summary="case summary",
                tags=("network",),
                recommended_mode="attach",
            ),
        },
    )

    updated = service.mark_script_used(package_name, "alpha.js", mode="spawn")
    saved = service.load_script_library(package_name)

    assert updated.pinned is True
    assert updated.summary == "case summary"
    assert updated.tags == ("network",)
    assert updated.recommended_mode == "attach"
    assert updated.last_used_at is not None
    assert list(saved) == ["alpha.js"]
    assert saved["alpha.js"].summary == "case summary"


def test_mark_script_used_keeps_default_either_mode_without_auto_learning(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"

    updated = service.mark_script_used(package_name, "alpha.js", mode="spawn")

    assert updated.recommended_mode == "either"


def test_mark_script_used_keeps_existing_specific_mode_instead_of_overwriting(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    service.save_script_library(
        package_name,
        {
            "alpha.js": ScriptMetadata(name="alpha.js", recommended_mode="attach"),
        },
    )

    updated = service.mark_script_used(package_name, "alpha.js", mode="spawn")

    assert updated.recommended_mode == "attach"


def test_read_recent_session_record_for_script_prefers_case_insensitive_path_match_over_name_match(workspace_context, tmp_path: Path) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    exact_path = tmp_path / "Scripts" / "Alpha.js"
    exact_path.parent.mkdir(parents=True, exist_ok=True)

    service.append_session_record(
        SessionRecord(
            timestamp="2026-06-08T10:00:00+08:00",
            package_name=package_name,
            script_name="alpha.js",
            script_path=str(Path(r"C:\Other\alpha.js")),
            mode="attach",
            source_kind="workspace",
            summary="name fallback",
        )
    )
    service.append_session_record(
        SessionRecord(
            timestamp="2026-06-08T10:10:00+08:00",
            package_name=package_name,
            script_name="ALPHA.js",
            script_path=str(exact_path).upper(),
            mode="spawn",
            source_kind="builtin_source",
            summary="path case-insensitive",
        )
    )

    record = service.read_recent_session_record_for_script(
        package_name,
        script_name="alpha.js",
        script_path=exact_path,
    )

    assert isinstance(record, dict)
    assert record["summary"] == "path case-insensitive"
    assert record["mode"] == "spawn"


def test_list_launcher_candidate_scripts_prioritizes_pinned_then_recent_then_source_kind(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    script_dir = service.script_dir(package_name)
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / "beta.js").write_text("// beta", encoding="utf-8")
    (script_dir / "内置-okhttp.js").write_text("// copy", encoding="utf-8")
    builtin = workspace_context.hookers_js_dir / "okhttp.js"
    builtin.parent.mkdir(parents=True, exist_ok=True)
    builtin.write_text("// builtin", encoding="utf-8")
    service.save_script_library(
        package_name,
        {
            "okhttp.js": ScriptMetadata(name="okhttp.js", pinned=True, last_used_at="2026-06-08T10:30:00+08:00"),
            "beta.js": ScriptMetadata(name="beta.js", pinned=False, last_used_at="2026-06-08T10:20:00+08:00"),
            "内置-okhttp.js": ScriptMetadata(name="内置-okhttp.js", pinned=False, last_used_at="2026-06-08T10:10:00+08:00"),
        },
    )
    ordered = [info.name for info in service.list_launcher_candidate_scripts(package_name)]
    assert ordered.index("okhttp.js") < ordered.index("beta.js")
    assert ordered.index("beta.js") < ordered.index("内置-okhttp.js")



def test_available_script_names_follows_launcher_candidate_order(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    script_dir = service.script_dir(package_name)
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / "beta.js").write_text("// beta", encoding="utf-8")
    (script_dir / "ДЪЦГ-okhttp.js").write_text("// copy", encoding="utf-8")
    builtin = workspace_context.hookers_js_dir / "okhttp.js"
    builtin.parent.mkdir(parents=True, exist_ok=True)
    builtin.write_text("// builtin", encoding="utf-8")
    service.save_script_library(
        package_name,
        {
            "okhttp.js": ScriptMetadata(name="okhttp.js", pinned=True, last_used_at="2026-06-08T10:30:00+08:00"),
            "beta.js": ScriptMetadata(name="beta.js", pinned=False, last_used_at="2026-06-08T10:20:00+08:00"),
            "ДЪЦГ-okhttp.js": ScriptMetadata(name="ДЪЦГ-okhttp.js", pinned=False, last_used_at="2026-06-08T10:10:00+08:00"),
        },
    )

    launcher_names = [info.name for info in service.list_launcher_candidate_scripts(package_name)]
    available_names = service.available_script_names(package_name)

    assert available_names == launcher_names[:len(available_names)]


def test_update_script_metadata_merges_with_existing_values(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    service.save_script_library(
        package_name,
        {
            "alpha.js": ScriptMetadata(
                name="alpha.js",
                pinned=True,
                last_used_at="2026-06-08T10:00:00+08:00",
                recommended_mode="attach",
                summary="old",
                tags=("network",),
            )
        },
    )
    updated = service.update_script_metadata(package_name, "alpha.js", summary="new")
    assert updated.pinned is True
    assert updated.last_used_at == "2026-06-08T10:00:00+08:00"
    assert updated.recommended_mode == "attach"
    assert updated.summary == "new"
    assert updated.tags == ("network",)


def test_set_script_summary_normalizes_and_truncates(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    summary = " a" + ("b" * 200)
    updated = service.set_script_summary(package_name, "alpha.js", summary)
    assert updated.summary.startswith("a")
    assert len(updated.summary) == 120


def test_set_script_recommended_mode_normalizes_invalid_value(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    updated = service.set_script_recommended_mode(package_name, "alpha.js", "invalid")
    assert updated.recommended_mode == "either"


def test_update_script_metadata_normalizes_and_deduplicates_tags(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"

    updated = service.update_script_metadata(
        package_name,
        "alpha.js",
        tags=("network", "network", "okhttp"),
    )

    assert updated.tags == ("network", "okhttp")


def test_update_script_metadata_deduplicates_tags_case_insensitively_preserving_first_value(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"

    updated = service.update_script_metadata(
        package_name,
        "alpha.js",
        tags=("Network", "network", "OkHttp", "okhttp"),
    )

    assert updated.tags == ("Network", "OkHttp")


def test_filter_script_sources_recent_view_uses_recent_order(workspace_context) -> None:
    context = workspace_context
    service = WorkspaceService(context)
    package_name = "com.example.demo"
    workspace_script_dir = context.workspaces_dir / package_name / "js"
    workspace_script_dir.mkdir(parents=True, exist_ok=True)
    for name in ["alpha.js", "beta.js", "gamma.js"]:
        (workspace_script_dir / name).write_text(f"// {name}", encoding="utf-8")

    service.save_script_library(
        package_name,
        {
            "alpha.js": ScriptMetadata(
                name="alpha.js",
                pinned=True,
                last_used_at="2026-06-08T10:00:00+08:00",
            ),
            "beta.js": ScriptMetadata(
                name="beta.js",
                last_used_at="2026-06-08T11:00:00+08:00",
            ),
            "gamma.js": ScriptMetadata(
                name="gamma.js",
                last_used_at="2026-06-08T09:00:00+08:00",
            ),
        },
    )

    recent = [info.name for info in service.filter_script_sources(package_name, view="recent")]

    assert recent == ["beta.js", "alpha.js", "gamma.js"]


def test_filter_script_sources_supports_pinned_recent_and_query(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    script_dir = service.script_dir(package_name)
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / "alpha.js").write_text("// alpha", encoding="utf-8")
    (script_dir / "beta.js").write_text("// beta", encoding="utf-8")
    service.save_script_library(
        package_name,
        {
            "alpha.js": ScriptMetadata(
                name="alpha.js",
                pinned=True,
                last_used_at="2026-06-08T10:10:00+08:00",
                summary="抓包脚本",
                tags=("network",),
            ),
            "beta.js": ScriptMetadata(
                name="beta.js",
                pinned=False,
                last_used_at="2026-06-08T10:00:00+08:00",
                summary="native trace",
                tags=("jni",),
            ),
        },
    )
    pinned = [info.name for info in service.filter_script_sources(package_name, view="pinned")]
    recent = [info.name for info in service.filter_script_sources(package_name, view="recent")]
    query_summary = [info.name for info in service.filter_script_sources(package_name, query="抓包")]
    query_tags = [info.name for info in service.filter_script_sources(package_name, query="jni")]
    assert pinned == ["alpha.js"]
    assert recent[:2] == ["alpha.js", "beta.js"]
    assert query_summary == ["alpha.js"]
    assert query_tags == ["beta.js"]


def test_ensure_workspace_asset_dirs_creates_expected_directories(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    dirs = service.ensure_workspace_asset_dirs("com.example.demo")
    assert set(dirs) == {"logs", "exports", "notes"}
    assert dirs["logs"].is_dir()
    assert dirs["exports"].is_dir()
    assert dirs["notes"].is_dir()


def test_default_note_file_path_points_to_analysis_notes_markdown(workspace_context) -> None:
    service = WorkspaceService(workspace_context)

    note_path = service.default_note_file_path("com.example.demo")

    assert note_path == service.workspace_dir("com.example.demo") / "notes" / "analysis_notes.md"



def test_read_workspace_note_returns_empty_string_when_missing(workspace_context) -> None:
    service = WorkspaceService(workspace_context)

    content = service.read_workspace_note("com.example.demo")

    assert content == ""



def test_write_workspace_note_persists_content(workspace_context) -> None:
    service = WorkspaceService(workspace_context)

    note_path = service.write_workspace_note("com.example.demo", "# demo\nhello")

    assert note_path.is_file()
    assert note_path.read_text(encoding="utf-8") == "# demo\nhello"



def test_write_workspace_note_then_read_round_trips_content(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    expected = "line1\nline2\n"

    service.write_workspace_note(package_name, expected)
    actual = service.read_workspace_note(package_name)

    assert actual == expected


def test_default_workspace_note_template_is_used_for_blank_file(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    note_path = service.default_note_file_path(package_name)
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text("   \n\n", encoding="utf-8")

    content = service.read_workspace_note(package_name)

    assert content == service.default_workspace_note_template(package_name)


def test_write_workspace_note_uses_template_when_content_blank(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"

    note_path = service.write_workspace_note(package_name, "   ")

    assert note_path.read_text(encoding="utf-8") == service.default_workspace_note_template(package_name)


def test_workspace_note_state_distinguishes_default_template_and_user_content(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"

    default_state = service.workspace_note_state(package_name)
    assert default_state["exists"] is False
    assert default_state["is_default_template"] is True
    assert default_state["has_user_content"] is False

    service.write_workspace_note(package_name, "# demo\nuser notes")
    custom_state = service.workspace_note_state(package_name)
    assert custom_state["exists"] is True
    assert custom_state["is_default_template"] is False
    assert custom_state["has_user_content"] is True


def test_build_log_export_manifest_contains_expected_fields(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    log_file = service.workspace_dir("com.example.demo") / "logs" / "demo.log"
    manifest = service.build_log_export_manifest(
        "com.example.demo",
        script_name="okhttp.js",
        script_path=service.script_dir("com.example.demo") / "okhttp.js",
        log_file=log_file,
        summary="抓取 OkHttp 请求与响应",
        recommended_mode="attach",
    )
    assert manifest["version"] == 1
    assert manifest["package_name"] == "com.example.demo"
    assert manifest["script_name"] == "okhttp.js"
    assert manifest["recommended_mode"] == "attach"
    assert manifest["summary"] == "抓取 OkHttp 请求与响应"
    assert manifest["log_file"] == "demo.log"
    assert manifest["exported_at"]


def test_write_log_export_manifest_persists_json_file(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    asset_dirs = service.ensure_workspace_asset_dirs("com.example.demo")
    log_file = asset_dirs["logs"] / "demo.log"
    log_file.write_text("hello\n", encoding="utf-8")
    manifest_path = service.write_log_export_manifest(log_file, {"version": 1, "package_name": "com.example.demo"})
    assert manifest_path.name == "demo.log.json"
    assert manifest_path.is_file()
    assert '"package_name": "com.example.demo"' in manifest_path.read_text(encoding="utf-8")


def test_list_recent_scripts_sorts_explicitly_by_last_used_at(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    script_dir = service.script_dir(package_name)
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / "alpha.js").write_text("// alpha", encoding="utf-8")
    (script_dir / "beta.js").write_text("// beta", encoding="utf-8")
    service.save_script_library(
        package_name,
        {
            "alpha.js": ScriptMetadata(name="alpha.js", pinned=False, last_used_at="2026-06-08T10:00:00+08:00"),
            "beta.js": ScriptMetadata(name="beta.js", pinned=True, last_used_at="2026-06-08T10:30:00+08:00"),
        },
    )

    recent = [info.name for info in service.list_recent_scripts(package_name)]

    assert recent[:2] == ["beta.js", "alpha.js"]


def test_list_recent_scripts_uses_stable_tiebreakers_when_timestamp_equal(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    script_dir = service.script_dir(package_name)
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / "beta.js").write_text("// beta", encoding="utf-8")
    (script_dir / "内置-okhttp.js").write_text("// copy", encoding="utf-8")
    builtin = workspace_context.hookers_js_dir / "okhttp.js"
    builtin.parent.mkdir(parents=True, exist_ok=True)
    builtin.write_text("// builtin", encoding="utf-8")
    timestamp = "2026-06-08T10:30:00+08:00"
    service.save_script_library(
        package_name,
        {
            "beta.js": ScriptMetadata(name="beta.js", last_used_at=timestamp),
            "内置-okhttp.js": ScriptMetadata(name="内置-okhttp.js", last_used_at=timestamp),
            "okhttp.js": ScriptMetadata(name="okhttp.js", last_used_at=timestamp),
        },
    )

    recent = [info.name for info in service.list_recent_scripts(package_name)]

    assert recent[:3] == ["beta.js", "内置-okhttp.js", "okhttp.js"]


def test_list_pinned_scripts_includes_builtin_source_via_read_only_metadata_aggregation(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    builtin = workspace_context.hookers_js_dir / "okhttp.js"
    builtin.parent.mkdir(parents=True, exist_ok=True)
    builtin.write_text("// builtin", encoding="utf-8")
    service.save_script_library(
        package_name,
        {
            "okhttp.js": ScriptMetadata(name="okhttp.js", pinned=True, summary="builtin pinned"),
        },
    )

    pinned = service.list_pinned_scripts(package_name)

    assert [info.name for info in pinned] == ["okhttp.js"]
    assert pinned[0].source_kind == "builtin_source"
    assert pinned[0].metadata is None


def test_filter_script_sources_pinned_view_includes_builtin_source_via_read_only_metadata_aggregation(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    builtin = workspace_context.hookers_js_dir / "okhttp.js"
    builtin.parent.mkdir(parents=True, exist_ok=True)
    builtin.write_text("// builtin", encoding="utf-8")
    service.save_script_library(
        package_name,
        {
            "okhttp.js": ScriptMetadata(name="okhttp.js", pinned=True, summary="builtin pinned"),
        },
    )

    pinned_infos = service.filter_script_sources(package_name, view="pinned")

    assert [info.name for info in pinned_infos] == ["okhttp.js"]
    assert pinned_infos[0].source_kind == "builtin_source"
    assert pinned_infos[0].metadata is None


def test_append_session_record_writes_jsonl(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    record = SessionRecord(
        timestamp="2026-06-08T10:30:00+08:00",
        package_name="com.example.demo",
        script_name="alpha.js",
        script_path=r"C:\demo\alpha.js",
        mode="attach",
        source_kind="workspace",
        summary="demo summary",
    )

    path = service.append_session_record(record)

    assert path.name == "sessions.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    import json
    payload = json.loads(lines[0])
    assert payload["package_name"] == "com.example.demo"
    assert payload["script_name"] == "alpha.js"
    assert payload["mode"] == "attach"
    assert payload["source_kind"] == "workspace"
    assert payload["summary"] == "demo summary"


def test_list_recent_session_records_returns_newest_first(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    service.append_session_record(
        SessionRecord(
            timestamp="2026-06-08T10:10:00+08:00",
            package_name=package_name,
            script_name="alpha.js",
            script_path=r"C:\demo\alpha.js",
            mode="attach",
            source_kind="workspace",
            summary="alpha",
        )
    )
    service.append_session_record(
        SessionRecord(
            timestamp="2026-06-08T10:20:00+08:00",
            package_name=package_name,
            script_name="beta.js",
            script_path=r"C:\demo\beta.js",
            mode="spawn",
            source_kind="workspace",
            summary="beta",
        )
    )

    records = service.list_recent_session_records(package_name, limit=2)

    assert [record["script_name"] for record in records] == ["beta.js", "alpha.js"]


def test_build_log_export_manifest_includes_recent_session_context(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    target_path = Path(r"C:\demo\okhttp.js")
    service.append_session_record(
        SessionRecord(
            timestamp="2026-06-08T10:10:00+08:00",
            package_name=package_name,
            script_name="alpha.js",
            script_path=r"C:\demo\alpha.js",
            mode="spawn",
            source_kind="workspace",
            summary="other session",
        )
    )
    service.append_session_record(
        SessionRecord(
            timestamp="2026-06-08T10:30:00+08:00",
            package_name=package_name,
            script_name="okhttp.js",
            script_path=str(target_path),
            mode="attach",
            source_kind="workspace",
            summary="target session",
        )
    )

    manifest = service.build_log_export_manifest(
        package_name,
        script_name="okhttp.js",
        script_path=target_path,
        log_file=Path("demo.log"),
        summary="log summary",
        recommended_mode="attach",
    )

    assert manifest["session_timestamp"] == "2026-06-08T10:30:00+08:00"
    assert manifest["session_mode"] == "attach"
    assert manifest["session_script_name"] == "okhttp.js"
    assert manifest["session_script_path"] == str(target_path)


def test_build_log_export_manifest_uses_none_when_no_session_exists(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    manifest = service.build_log_export_manifest(
        "com.example.demo",
        script_name="okhttp.js",
        script_path=Path(r"C:\demo\okhttp.js"),
        log_file=Path("demo.log"),
        summary="log summary",
        recommended_mode="attach",
    )

    assert manifest["session_timestamp"] is None
    assert manifest["session_mode"] is None
    assert manifest["session_script_name"] is None
    assert manifest["session_script_path"] is None


def test_build_log_export_manifest_does_not_bind_unrelated_recent_session(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    service.append_session_record(
        SessionRecord(
            timestamp="2026-06-08T10:30:00+08:00",
            package_name=package_name,
            script_name="alpha.js",
            script_path=r"C:\demo\alpha.js",
            mode="spawn",
            source_kind="workspace",
            summary="other session",
        )
    )

    manifest = service.build_log_export_manifest(
        package_name,
        script_name="okhttp.js",
        script_path=Path(r"C:\demo\okhttp.js"),
        log_file=Path("demo.log"),
        summary="log summary",
        recommended_mode="attach",
    )

    assert manifest["session_timestamp"] is None
    assert manifest["session_mode"] is None
    assert manifest["session_script_name"] is None
    assert manifest["session_script_path"] is None


def test_build_workspace_manifest_returns_expected_empty_defaults(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    manifest = service.build_workspace_manifest("com.example.demo")

    assert manifest["version"] == 1
    assert manifest["package_name"] == "com.example.demo"
    assert manifest["pinned_scripts"] == []
    assert manifest["recent_scripts"] == []
    assert manifest["recent_session_count"] == 0
    assert manifest["recent_log_count"] == 0
    assert manifest["recent_logs"] == []
    assert manifest["last_session"] is None
    assert manifest["notes_path"]
    assert manifest["notes_exists"] is False
    assert manifest["notes_is_default_template"] is True
    assert manifest["notes_has_user_content"] is False
    assert manifest["updated_at"]


def test_build_workspace_manifest_exposes_case_home_fields(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    script_dir = service.script_dir(package_name)
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / "alpha.js").write_text("// alpha", encoding="utf-8")
    service.save_script_library(
        package_name,
        {
            "alpha.js": ScriptMetadata(name="alpha.js", pinned=True, last_used_at="2026-06-08T10:30:00+08:00"),
        },
    )
    summary_path = service.write_latest_result_summary(package_name, "## 本轮结果摘要\n- 发现登录 URL")

    manifest = service.build_workspace_manifest(package_name)

    assert manifest["workspace_ready"] is True
    assert manifest["script_asset_count"] >= 1
    assert manifest["pinned_script_count"] == 1
    assert manifest["recent_script_count"] == 1
    assert manifest["named_template_count"] == 0
    assert manifest["recommended_entrypoint"] in {"review_latest_result_summary", "launch_pinned_script", "reuse_recent_script"}
    assert manifest["case_entry_hint"]
    assert manifest["last_result_summary_at"]
    assert manifest["latest_result_summary_path"] == str(summary_path)


def test_build_workspace_manifest_summarizes_current_workspace_assets(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    script_dir = service.script_dir(package_name)
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / "alpha.js").write_text("// alpha", encoding="utf-8")
    (script_dir / "beta.js").write_text("// beta", encoding="utf-8")
    service.save_script_library(
        package_name,
        {
            "alpha.js": ScriptMetadata(name="alpha.js", pinned=True, last_used_at="2026-06-08T10:30:00+08:00"),
            "beta.js": ScriptMetadata(name="beta.js", last_used_at="2026-06-08T10:20:00+08:00"),
        },
    )
    service.write_workspace_note(package_name, "# demo")
    logs_dir = service.ensure_workspace_asset_dirs(package_name)["logs"]
    (logs_dir / "a.log").write_text("a", encoding="utf-8")
    (logs_dir / "b.log").write_text("b", encoding="utf-8")
    service.append_session_record(
        SessionRecord(
            timestamp="2026-06-08T10:40:00+08:00",
            package_name=package_name,
            script_name="alpha.js",
            script_path=r"C:\demolpha.js",
            mode="attach",
            source_kind="workspace",
            summary="alpha session",
        )
    )

    manifest = service.build_workspace_manifest(package_name)

    assert manifest["pinned_scripts"] == ["alpha.js"]
    assert manifest["recent_scripts"][:2] == ["alpha.js", "beta.js"]
    assert manifest["recent_session_count"] == 1
    assert manifest["recent_log_count"] == 2
    assert set(manifest["recent_logs"]) == {"a.log", "b.log"}
    assert manifest["notes_exists"] is True
    assert manifest["notes_is_default_template"] is False
    assert manifest["notes_has_user_content"] is True
    assert manifest["last_session"]["script_name"] == "alpha.js"
    assert manifest["last_session"]["summary"] == "alpha session"


def test_recent_log_file_names_include_uppercase_log_suffix(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    logs_dir = service.ensure_workspace_asset_dirs(package_name)["logs"]
    (logs_dir / "Demo.LOG").write_text("demo", encoding="utf-8")
    (logs_dir / "alpha.log").write_text("alpha", encoding="utf-8")

    names = service._recent_log_file_names(package_name, limit=10)

    assert "Demo.LOG" in names
    assert "alpha.log" in names


def test_build_workspace_manifest_includes_uppercase_log_suffix_in_recent_logs(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    logs_dir = service.ensure_workspace_asset_dirs(package_name)["logs"]
    (logs_dir / "Demo.LOG").write_text("demo", encoding="utf-8")

    manifest = service.build_workspace_manifest(package_name)

    assert "Demo.LOG" in manifest["recent_logs"]


def test_write_and_read_workspace_manifest_round_trip(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"

    path = service.write_workspace_manifest(package_name)
    payload = service.read_workspace_manifest(package_name)

    assert path.name == "workspace_manifest.json"
    assert isinstance(payload, dict)
    assert payload["package_name"] == package_name


def test_read_workspace_manifest_returns_none_when_json_invalid(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    manifest_path = service.workspace_manifest_path(package_name)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text("{bad json", encoding="utf-8")

    assert service.read_workspace_manifest(package_name) is None


def test_advanced_launcher_presets_roundtrip(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = 'pkg.demo'
    entries = [
        AdvancedLauncherPresetEntry(
            label='[工作区] alpha.js',
            path=str(workspace_context.workspaces_dir / package_name / 'js' / 'alpha.js'),
            kind='plain',
            source_kind='workspace',
            display_name='alpha.js',
            summary='alpha summary',
            config_payload={'k': 'v'},
            mode_strategy='spawn',
            auto_stop=True,
        )
    ]

    path = service.save_advanced_launcher_presets(package_name, entries)
    loaded = service.load_advanced_launcher_presets(package_name)

    assert path == service.advanced_launcher_presets_path(package_name)
    assert len(loaded) == 1
    assert loaded[0].label == '[工作区] alpha.js'
    assert loaded[0].summary == 'alpha summary'
    assert loaded[0].config_payload == {'k': 'v'}
    assert loaded[0].mode_strategy == 'spawn'
    assert loaded[0].auto_stop is True


def test_advanced_launcher_presets_invalid_json_returns_empty(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = 'pkg.demo'
    path = service.advanced_launcher_presets_path(package_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{invalid', encoding='utf-8')

    assert service.load_advanced_launcher_presets(package_name) == []


def test_advanced_launcher_presets_roundtrip_preserves_display_metadata(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = 'pkg.demo'
    entries = [
        AdvancedLauncherPresetEntry(
            label='★ [工作区] alpha.js',
            path=str(workspace_context.workspaces_dir / package_name / 'js' / 'alpha.js'),
            kind='plain',
            source_kind='workspace',
            display_name='alpha.js',
            summary='alpha summary',
            is_pinned=True,
            last_used_at='2026-06-08T10:30:00+08:00',
            tags=('network', 'alpha', 'network'),
        )
    ]

    service.save_advanced_launcher_presets(package_name, entries)
    loaded = service.load_advanced_launcher_presets(package_name)

    assert len(loaded) == 1
    assert loaded[0].is_pinned is True
    assert loaded[0].last_used_at == '2026-06-08T10:30:00+08:00'
    assert loaded[0].tags == ('network', 'alpha')


def test_advanced_launcher_preset_snapshot_roundtrip_preserves_note(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "pkg.demo"
    entries = [
        AdvancedLauncherPresetEntry(
            label="[工作区] alpha.js",
            path=str(workspace_context.workspaces_dir / package_name / "js" / "alpha.js"),
        )
    ]

    service.save_advanced_launcher_presets(package_name, entries, note="首轮网络探测")
    snapshot = service.load_advanced_launcher_preset_snapshot(package_name)

    assert isinstance(snapshot, AdvancedLauncherPresetSnapshot)
    assert snapshot.note == "首轮网络探测"
    assert len(snapshot.entries) == 1


def test_advanced_launcher_preset_snapshot_old_payload_without_note_is_compatible(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "pkg.demo"
    path = service.advanced_launcher_presets_path(package_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """
{
  "version": 1,
  "selected_options": [
    {
      "label": "[工作区] alpha.js",
      "path": "C:/demo/alpha.js"
    }
  ]
}
""".strip() + "\n",
        encoding="utf-8",
    )

    snapshot = service.load_advanced_launcher_preset_snapshot(package_name)

    assert snapshot.note == ""
    assert len(snapshot.entries) == 1


def test_advanced_launcher_preset_snapshot_invalid_note_type_falls_back_to_string(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "pkg.demo"
    path = service.advanced_launcher_presets_path(package_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """
{
  "version": 1,
  "note": 123,
  "selected_options": []
}
""".strip() + "\n",
        encoding="utf-8",
    )

    snapshot = service.load_advanced_launcher_preset_snapshot(package_name)

    assert snapshot.note == "123"


def test_read_workspace_note_preserves_existing_user_content(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    note_path = service.default_note_file_path(package_name)
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text("# demo\nhello", encoding="utf-8")

    content = service.read_workspace_note(package_name)

    assert content == "# demo\nhello"


def test_build_workspace_manifest_recent_scripts_excludes_builtin_source_even_when_recent_view_includes_it(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    script_dir = service.script_dir(package_name)
    script_dir.mkdir(parents=True, exist_ok=True)
    workspace_script = script_dir / "alpha.js"
    workspace_script.write_text("// alpha", encoding="utf-8")
    builtin = workspace_context.hookers_js_dir / "okhttp.js"
    builtin.parent.mkdir(parents=True, exist_ok=True)
    builtin.write_text("// builtin", encoding="utf-8")
    service.save_script_library(
        package_name,
        {
            "alpha.js": ScriptMetadata(name="alpha.js", last_used_at="2026-06-08T10:20:00+08:00"),
            "okhttp.js": ScriptMetadata(name="okhttp.js", last_used_at="2026-06-08T10:30:00+08:00"),
        },
    )

    recent_names = [info.name for info in service.list_recent_scripts(package_name)]
    manifest = service.build_workspace_manifest(package_name)

    assert recent_names[:2] == ["okhttp.js", "alpha.js"]
    assert manifest["recent_scripts"] == ["alpha.js"]



def test_build_workspace_manifest_pinned_scripts_excludes_builtin_source_even_when_pinned_view_includes_it(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"
    builtin = workspace_context.hookers_js_dir / "okhttp.js"
    builtin.parent.mkdir(parents=True, exist_ok=True)
    builtin.write_text("// builtin", encoding="utf-8")
    script_dir = service.script_dir(package_name)
    script_dir.mkdir(parents=True, exist_ok=True)
    workspace_script = script_dir / "alpha.js"
    workspace_script.write_text("// alpha", encoding="utf-8")
    service.save_script_library(
        package_name,
        {
            "alpha.js": ScriptMetadata(name="alpha.js", pinned=True),
            "okhttp.js": ScriptMetadata(name="okhttp.js", pinned=True),
        },
    )

    pinned_names = [info.name for info in service.list_pinned_scripts(package_name)]
    manifest = service.build_workspace_manifest(package_name)

    assert pinned_names == ["alpha.js", "okhttp.js"]
    assert manifest["pinned_scripts"] == ["alpha.js"]



def test_workspace_service_advanced_launcher_presets_roundtrip_item_note(workspace_context) -> None:
    from core.workspace_service import WorkspaceService, AdvancedLauncherPresetEntry

    service = WorkspaceService(workspace_context)

    entry = AdvancedLauncherPresetEntry(
        label='[工作区] alpha.js',
        path='C:/demo/alpha.js',
        source_kind='workspace',
        note='登录页专用',
        mode_strategy='attach',
        auto_stop=True,
    )

    service.save_advanced_launcher_presets('pkg.demo', [entry], note='整体任务说明')
    snapshot = service.load_advanced_launcher_preset_snapshot('pkg.demo')

    assert snapshot.note == '整体任务说明'
    assert len(snapshot.entries) == 1
    assert snapshot.entries[0].note == '登录页专用'
    assert snapshot.entries[0].mode_strategy == 'attach'
    assert snapshot.entries[0].auto_stop is True


def test_advanced_launcher_named_templates_roundtrip(workspace_context) -> None:
    from core.workspace_service import AdvancedLauncherNamedTemplate
    service = WorkspaceService(workspace_context)
    package_name = "pkg.demo"
    entries = [
        AdvancedLauncherPresetEntry(
            label='[工作区] alpha.js',
            path='C:/demo/alpha.js',
            source_kind='workspace',
            summary='alpha summary',
            mode_strategy='spawn',
            auto_stop=True,
        )
    ]
    templates = [
        AdvancedLauncherNamedTemplate(
            name='首轮网络探测',
            note='登录链路',
            entries=tuple(entries),
        )
    ]

    path_value = service.save_advanced_launcher_named_templates(package_name, templates)
    loaded = service.load_advanced_launcher_named_templates(package_name)

    assert path_value == service.advanced_launcher_templates_path(package_name)
    assert len(loaded) == 1
    assert loaded[0].name == '首轮网络探测'
    assert loaded[0].note == '登录链路'
    assert loaded[0].entries[0].summary == 'alpha summary'
    assert loaded[0].entries[0].mode_strategy == 'spawn'
    assert loaded[0].entries[0].auto_stop is True


def test_advanced_launcher_preset_snapshot_old_payload_without_strategy_fields_is_compatible(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "pkg.demo"
    path = service.advanced_launcher_presets_path(package_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """
{
  "version": 1,
  "selected_options": [
    {
      "label": "[工作区] alpha.js",
      "path": "C:/demo/alpha.js",
      "note": "登录阶段"
    }
  ]
}
""".strip() + "\n",
        encoding="utf-8",
    )

    snapshot = service.load_advanced_launcher_preset_snapshot(package_name)

    assert len(snapshot.entries) == 1
    assert snapshot.entries[0].mode_strategy == "inherit"
    assert snapshot.entries[0].auto_stop is False


def test_advanced_launcher_named_template_upsert_and_delete(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = 'pkg.demo'
    entries = [AdvancedLauncherPresetEntry(label='[工作区] alpha.js', path='C:/demo/alpha.js')]

    service.upsert_advanced_launcher_named_template(package_name, '模板A', entries, note='first')
    service.upsert_advanced_launcher_named_template(package_name, '模板A', entries, note='updated')
    loaded = service.load_advanced_launcher_named_templates(package_name)

    assert len(loaded) == 1
    assert loaded[0].note == 'updated'

    service.delete_advanced_launcher_named_template(package_name, '模板A')
    loaded_after_delete = service.load_advanced_launcher_named_templates(package_name)
    assert loaded_after_delete == []


def test_advanced_launcher_named_templates_roundtrip_preserves_last_used_at(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = 'com.example.demo'
    templates = [
        AdvancedLauncherNamedTemplate(
            name='模板A',
            updated_at='2026-06-08T12:00:00+08:00',
            last_used_at='2026-06-08T12:30:00+08:00',
            note='首轮网络',
            entries=(),
        )
    ]

    service.save_advanced_launcher_named_templates(package_name, templates)
    loaded = service.load_advanced_launcher_named_templates(package_name)

    assert len(loaded) == 1
    assert loaded[0].last_used_at == '2026-06-08T12:30:00+08:00'


def test_mark_advanced_launcher_template_used_updates_last_used_at_and_sorts_first(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = 'com.example.demo'
    service.save_advanced_launcher_named_templates(
        package_name,
        [
            AdvancedLauncherNamedTemplate(name='模板A', updated_at='2026-06-08T10:00:00+08:00'),
            AdvancedLauncherNamedTemplate(name='模板B', updated_at='2026-06-08T11:00:00+08:00'),
        ],
    )

    updated = service.mark_advanced_launcher_template_used(package_name, '模板A')

    marked = next(item for item in updated if item.name == '模板A')
    assert marked.last_used_at is not None
    loaded = service.load_advanced_launcher_named_templates(package_name)
    assert next(item for item in loaded if item.name == '模板A').last_used_at is not None


def test_set_script_metadata_fields_updates_multiple_fields(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"

    updated = service.set_script_metadata_fields(
        package_name,
        "alpha.js",
        summary="网络观察",
        recommended_mode="spawn",
        tags=("network", "okhttp", "Network"),
        use_when="首轮抓网络",
        caution="避免冷启动晚 attach",
    )

    assert updated.summary == "网络观察"
    assert updated.recommended_mode == "spawn"
    assert updated.tags == ("network", "okhttp")
    assert updated.use_when == "首轮抓网络"
    assert updated.caution == "避免冷启动晚 attach"


def test_append_workspace_note_section_appends_after_template(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"

    note_path = service.append_workspace_note_section(package_name, "## 本轮结果摘要\n- hit")
    content = note_path.read_text(encoding="utf-8")

    assert "# com.example.demo 分析笔记" in content
    assert "## 本轮结果摘要" in content
    assert "- hit" in content


def test_latest_result_summary_roundtrip_and_manifest_excerpt(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = "com.example.demo"

    summary_path = service.write_latest_result_summary(package_name, "## 本轮结果摘要\n- url")
    loaded = service.read_latest_result_summary(package_name)
    manifest = service.build_workspace_manifest(package_name)

    assert summary_path.is_file()
    assert "## 本轮结果摘要" in loaded
    assert manifest["latest_result_summary_exists"] is True
    assert manifest["latest_result_summary_path"] == str(summary_path)
    assert "本轮结果摘要" in manifest["latest_result_summary_excerpt"]


def test_advanced_launcher_named_templates_roundtrip_preserves_last_result_summary_fields(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = 'com.example.demo'
    service.save_advanced_launcher_named_templates(
        package_name,
        [
            AdvancedLauncherNamedTemplate(
                name='模板A',
                note='首轮网络',
                last_result_summary_excerpt='已命中 URL 与 OkHttp',
                last_result_summary_at='2026-06-08T12:30:00+08:00',
                last_result_session_timestamp='2026-06-08T12:29:00+08:00',
                last_result_script_name='frida_multi_bundle.runtime.js',
            )
        ],
    )

    loaded = service.load_advanced_launcher_named_templates(package_name)

    assert loaded[0].last_result_summary_excerpt == '已命中 URL 与 OkHttp'
    assert loaded[0].last_result_summary_at == '2026-06-08T12:30:00+08:00'
    assert loaded[0].last_result_session_timestamp == '2026-06-08T12:29:00+08:00'
    assert loaded[0].last_result_script_name == 'frida_multi_bundle.runtime.js'


def test_update_advanced_launcher_template_result_summary_updates_existing_template(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = 'com.example.demo'
    service.save_advanced_launcher_named_templates(
        package_name,
        [AdvancedLauncherNamedTemplate(name='模板A', note='首轮网络')],
    )

    updated = service.update_advanced_launcher_template_result_summary(
        package_name,
        '模板A',
        summary_excerpt='已命中 URL 与 OkHttp，请继续抓包',
        session_timestamp='2026-06-08T13:00:00+08:00',
        script_name='frida_multi_bundle.runtime.js',
    )

    target = next(item for item in updated if item.name == '模板A')
    assert target.last_result_summary_excerpt == '已命中 URL 与 OkHttp，请继续抓包'
    assert target.last_result_session_timestamp == '2026-06-08T13:00:00+08:00'
    assert target.last_result_script_name == 'frida_multi_bundle.runtime.js'
    assert target.last_result_summary_at is not None


def test_build_workspace_manifest_includes_last_used_template_summary(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = 'com.example.demo'
    service.save_advanced_launcher_named_templates(
        package_name,
        [
            AdvancedLauncherNamedTemplate(
                name='模板A',
                note='首轮网络',
                last_used_at='2026-06-08T13:05:00+08:00',
                last_result_summary_excerpt='已命中 URL 与 OkHttp',
                last_result_summary_at='2026-06-08T13:06:00+08:00',
            )
        ],
    )

    manifest = service.build_workspace_manifest(package_name)

    assert manifest['last_used_template_name'] == '模板A'
    assert manifest['last_used_template_note'] == '首轮网络'
    assert manifest['last_used_template_last_result_excerpt'] == '已命中 URL 与 OkHttp'
    assert manifest['last_used_template_last_result_at'] == '2026-06-08T13:06:00+08:00'


def test_build_workspace_manifest_includes_recommended_result_action_from_latest_summary(workspace_context) -> None:
    service = WorkspaceService(workspace_context)
    package_name = 'com.example.demo'

    service.write_latest_result_summary(package_name, '## 本轮结果摘要\n- 发现登录 URL 与 token 参数')
    manifest = service.build_workspace_manifest(package_name)

    assert manifest['recommended_result_action_key'] == 'network_review'
    assert manifest['recommended_result_action_label'] == '回看网络链路'
    assert manifest['recommended_result_action_entry_type'] == 'scenario'
    assert 'URL' in (manifest['recommended_result_action_description'] or '')
