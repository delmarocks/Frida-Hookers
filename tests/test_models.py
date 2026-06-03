from __future__ import annotations

from pathlib import Path

from core.models import HookerContext


def test_hooker_context_from_project_root_builds_default_paths(tmp_path: Path) -> None:
    context = HookerContext.from_project_root(tmp_path)
    assert context.project_root == tmp_path.resolve()
    assert context.mobile_deploy_dir == tmp_path.resolve() / "mobile-deploy"
    assert context.js_dir == tmp_path.resolve() / "js"
    assert context.hookers_js_dir == tmp_path.resolve() / "hookers" / "js"
    assert context.workspaces_dir == tmp_path.resolve() / "workspaces"


def test_hooker_context_emit_uses_log_handler(tmp_path: Path) -> None:
    messages: list[str] = []
    context = HookerContext.from_project_root(tmp_path, log_handler=messages.append)
    context.emit("hello")
    assert messages == ["hello"]


def test_hooker_context_emit_session_event_uses_handler(tmp_path: Path) -> None:
    received: list[tuple[str, dict[str, object]]] = []
    context = HookerContext.from_project_root(tmp_path)
    context.session_event_handler = lambda event_type, payload: received.append((event_type, payload))
    payload = {"reason": "process-terminated"}
    context.emit_session_event("detached", payload)
    assert received == [("detached", payload)]


def test_hooker_context_local_resource_properties(tmp_path: Path) -> None:
    context = HookerContext.from_project_root(tmp_path)
    assert context.local_radar_dex == tmp_path.resolve() / "mobile-deploy" / "radar.dex"
    assert context.local_apk_check_pack_exe == tmp_path.resolve() / "mobile-deploy" / "ApkCheckPack.exe"
