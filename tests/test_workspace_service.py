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
from core.workspace_service import WorkspaceService


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
    assert "BEGIN [1] a.js" in content
    assert "console.log('A');" in content
    assert "BEGIN [2] b.js" in content
    assert "console.log('B');" in content
    assert content.index("console.log('A');") < content.index("console.log('B');")


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
    monkeypatch.setattr(service, "remove_workspace_builtin_scripts", lambda script_dir: None)
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
    monkeypatch.setattr(service, "remove_workspace_builtin_scripts", lambda script_dir: None)
    monkeypatch.setattr(service, "ensure_local_apk", lambda app, refresh=False: setattr(workspace_context, "last_workspace_apk_status", "reused") or service.workspace_apk_path(app))

    result = service.initialize_existing_workspace(sample_app_context)

    assert result == package_dir
    assert workspace_context.last_workspace_prepare_mode == "updated"
    assert workspace_context.last_workspace_apk_status == "reused"

def test_ensure_workspace_wraps_initialization_error(workspace_context, sample_app_context, monkeypatch) -> None:
    service = WorkspaceService(workspace_context)

    def fail_initialize(app):
        raise WorkspaceResourceMissingError("缺少内置资源: android_ui.js")

    monkeypatch.setattr(service, "create_initial_workspace", fail_initialize)

    with pytest.raises(WorkspaceInitializationError):
        service.ensure_workspace(sample_app_context)
