from __future__ import annotations

import types

from ui.workers.action_worker import ActionWorker
from ui.workers.device_worker import DeviceWorker
from ui.workers.workspace_worker import WorkspaceWorker


def test_action_worker_emits_success_and_finished() -> None:
    worker = ActionWorker(lambda: {"ok": True})
    succeeded = []
    failed = []
    finished = []
    worker.succeeded.connect(succeeded.append)
    worker.failed.connect(failed.append)
    worker.finished.connect(lambda: finished.append("done"))

    worker.run()

    assert succeeded == [{"ok": True}]
    assert failed == []
    assert finished == ["done"]


def test_action_worker_emits_structured_failure_and_finished() -> None:
    worker = ActionWorker(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    succeeded = []
    failed = []
    finished = []
    worker.succeeded.connect(succeeded.append)
    worker.failed.connect(failed.append)
    worker.finished.connect(lambda: finished.append("done"))

    worker.run()

    assert succeeded == []
    assert len(failed) == 1
    assert failed[0].message == "boom"
    assert finished == ["done"]


def test_device_worker_resets_context_flags_and_emits_apps_payload() -> None:
    context = types.SimpleNamespace(
        last_connected_device_serial="old-serial",
        last_prepare_frida_server_status="old-status",
    )
    calls = []
    apps = [
        types.SimpleNamespace(name="Demo One", identifier="pkg.one", pid=1234),
        types.SimpleNamespace(name="Demo Two", identifier="pkg.two", pid=None),
    ]

    service = types.SimpleNamespace(
        context=context,
        connect=lambda: calls.append("connect"),
        start_frida_server=lambda: calls.append("start_frida_server"),
        deploy_radar_dex=lambda: calls.append("deploy_radar_dex"),
        refresh_applications=lambda: calls.append("refresh_applications") or apps,
        get_foreground_package=lambda: calls.append("get_foreground_package") or "pkg.one",
    )
    worker = DeviceWorker(service)
    ready = []
    failed = []
    finished = []
    worker.apps_ready.connect(lambda payload, foreground: ready.append((payload, foreground)))
    worker.failed.connect(failed.append)
    worker.finished.connect(lambda: finished.append("done"))

    worker.run()

    assert context.last_connected_device_serial is None
    assert context.last_prepare_frida_server_status is None
    assert calls == [
        "connect",
        "start_frida_server",
        "deploy_radar_dex",
        "refresh_applications",
        "get_foreground_package",
    ]
    assert ready == [
        (
            [
                {"name": "Demo One", "identifier": "pkg.one", "pid": 1234},
                {"name": "Demo Two", "identifier": "pkg.two", "pid": None},
            ],
            "pkg.one",
        )
    ]
    assert failed == []
    assert finished == ["done"]


def test_device_worker_emits_failure_and_finished_when_prepare_raises() -> None:
    context = types.SimpleNamespace(
        last_connected_device_serial="old-serial",
        last_prepare_frida_server_status="old-status",
    )

    def boom():
        raise RuntimeError("connect boom")

    service = types.SimpleNamespace(
        context=context,
        connect=boom,
    )
    worker = DeviceWorker(service)
    ready = []
    failed = []
    finished = []
    worker.apps_ready.connect(lambda payload, foreground: ready.append((payload, foreground)))
    worker.failed.connect(failed.append)
    worker.finished.connect(lambda: finished.append("done"))

    worker.run()

    assert ready == []
    assert len(failed) == 1
    assert failed[0].message == "connect boom"
    assert finished == ["done"]


def test_workspace_worker_emits_workspace_and_script_dirs() -> None:
    app = types.SimpleNamespace(identifier="pkg.demo")
    service = types.SimpleNamespace(
        prepare_app_context=lambda package_name: app,
    )
    workspace_service = types.SimpleNamespace(
        ensure_workspace=lambda current_app: "C:/tmp/workspaces/pkg.demo",
        script_dir=lambda package_name: "C:/tmp/workspaces/pkg.demo/js",
    )
    worker = WorkspaceWorker(
        device_service=service,
        workspace_service=workspace_service,
        package_name="pkg.demo",
    )
    ready = []
    failed = []
    finished = []
    worker.ready.connect(lambda package_name, workspace_dir, script_dir: ready.append((package_name, workspace_dir, script_dir)))
    worker.failed.connect(failed.append)
    worker.finished.connect(lambda: finished.append("done"))

    worker.run()

    assert ready == [("pkg.demo", "C:/tmp/workspaces/pkg.demo", "C:/tmp/workspaces/pkg.demo/js")]
    assert failed == []
    assert finished == ["done"]


def test_workspace_worker_emits_failure_and_finished_when_prepare_raises() -> None:
    def boom(package_name: str):
        raise RuntimeError(f"prepare boom: {package_name}")

    worker = WorkspaceWorker(
        device_service=types.SimpleNamespace(prepare_app_context=boom),
        workspace_service=types.SimpleNamespace(),
        package_name="pkg.demo",
    )
    ready = []
    failed = []
    finished = []
    worker.ready.connect(lambda package_name, workspace_dir, script_dir: ready.append((package_name, workspace_dir, script_dir)))
    worker.failed.connect(failed.append)
    worker.finished.connect(lambda: finished.append("done"))

    worker.run()

    assert ready == []
    assert len(failed) == 1
    assert failed[0].message == "prepare boom: pkg.demo"
    assert finished == ["done"]
