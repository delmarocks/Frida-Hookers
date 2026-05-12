# AGENT.md

## At a Glance

- Project name: `Frida-Hookers`
- What it is:
  - A local Android Frida/ADB workbench for one target app at a time.
  - It combines device preparation, per-app workspace management, Frida attach/spawn, RPC-style inspection tooling, and local APK scanning.
- Primary entrypoint: `app_gui.py`
- Secondary entrypoint: `hookers.py`
- Primary runtime model:
  - shared `HookerContext`
  - service layer in `core/`
  - GUI orchestration in `ui/main_window.py`
- Primary workflow:
  - prepare device
  - choose target app
  - initialize workspace
  - attach or spawn
  - use RPC/inspection tools
- Current product posture:
  - GUI-first
  - CLI still works, but recent user-facing behavior changes are centered on the GUI
- Current user-facing naming:
  - project display name: `Frida-Hookers`
  - GUI window title: `Frida-Hookers GUI 工作台`
  - CLI banner: `Frida-Hookers 安卓逆向集成工具 2.0`

## If You Only Read 5 Files

1. `app_gui.py`
   - Shows how the GUI runtime is assembled.
   - Builds `HookerContext`, wires services, enables persistent RPC reuse.
2. `ui/main_window.py`
   - The main product surface.
   - Best file for understanding real GUI flow, state transitions, and visible controls.
3. `core/models.py`
   - Defines the shared runtime state.
   - Read this to understand what all services mutate and depend on.
4. `core/device_service.py`
   - Owns device bootstrap, server selection, app discovery, and app readiness checks.
   - Most environment-preparation behavior starts here.
5. `core/session_service.py`
   - Owns attach/spawn, script load, session cleanup, and detached-session handling.
   - Read this before changing hook lifecycle behavior.

If you need one more file after those five, read:

- `core/rpc_service.py` for RPC inspection and hook generation
- `core/apk_scan_service.py` for the local `ApkCheckPack.exe` scan flow

## Mental Model

- `HookerContext` is the single shared runtime state.
- Services own behavior; GUI mostly orchestrates and renders state.
- `DeviceService` prepares the Android side.
- `WorkspaceService` materializes per-package local workspaces under `workspaces/<package>/`.
- `SessionService` owns attach/spawn/session lifecycle.
- `RpcService` owns `js/rpc.js`-based inspection and hook generation.
- `ApkScanService` owns local APK scanning through `mobile-deploy/ApkCheckPack.exe`.
- `workspaces/<package>/` is per-target output, not core framework code.
- `js/` contains reusable Frida assets and hook-generation templates.
- `mobile-deploy/` contains device-side binaries/artifacts, not business logic.

## Current Behavioral Truths

- GUI is the primary product surface and the preferred path for understanding current behavior.
- Attach only attaches to an already running PID.
- Attach does not bring the target app to foreground.
- GUI debug-tool actions also avoid forcing foreground.
- After `准备环境并刷新 App`, the GUI tries to detect the current foreground Android app and auto-select it if that package also exists in the refreshed app list.
- If there is no resolvable foreground app, the GUI leaves target-app selection empty.
- Workspace initialization ensures a local APK copy exists under `workspaces/<package>/`.
- Selecting an app in the GUI no longer creates or materializes workspace files by itself.
- Full workspace creation / helper generation / built-in JS copy / local APK preparation only happens after the user clicks `初始化工作目录并刷新列表`.
- The project now uses a single fixed device-side server:
  - local file: `mobile-deploy/rusda-server-16.2.1-android-arm64`
  - remote path: `/data/local/tmp/rusda-16.2.1`
- There is no longer any GUI option for switching between normal/hidden Frida variants.
- During `准备环境并刷新 App`, if the managed rusda server is already alive and passes Frida probe, the project skips remote cleanup and restart.
- If the remote rusda file already exists but the service needs to be restarted, the project now reuses that file instead of deleting and re-uploading it.
- Device preparation may clean/restart the managed server when needed.
- GUI exit no longer cleans the device-side `rusda-16.2.1` file automatically.
- GUI no longer shows a dedicated fixed-server info block in the control panel.
- GUI exposes a left-panel `停止 Frida Server` button for explicitly stopping the managed device-side server.
- GUI uses persistent RPC reuse for high-frequency inspection actions.
- The right-side log panel supports:
  - category filtering
  - keyword / regex search
  - case-sensitive search
  - `仅显示匹配项`
  - previous / next match navigation
  - a `专注日志` mode that temporarily maximizes the log area
- The log panel is optimized to avoid re-rendering the entire log buffer on every new line:
  - bursty logs are batched on a short timer
  - plain streaming logs without active search use incremental append instead of full HTML rebuild
- GUI also exposes a left-panel `APK扫描` tool for manually chosen local `.apk` files.
- APK scanning is independent of `current_app`, workspaces, and attach/spawn session state.
- APK scanning directly calls `mobile-deploy/ApkCheckPack.exe -f <apk>` and writes results to the right-side log panel.
- Detached Frida sessions now emit clearer user-facing diagnostics instead of only raw detach reasons.
- `README.md` is product-facing; when `README.md` and code diverge, treat current code as the source of truth.

## Where To Change What

- Device bootstrap, root checks, server selection, remote deploy/cleanup, app enumeration:
  - `core/device_service.py`
- Workspace creation, JS copying, helper bat generation, workspace script resolution/output persistence:
  - `core/workspace_service.py`
- Attach/spawn semantics, script loading, session cleanup, restart behavior, detached-session handling:
  - `core/session_service.py`
- RPC inspection, hook generation, persistent RPC session behavior:
  - `core/rpc_service.py`
- Local APK scanning through `ApkCheckPack.exe`:
  - `core/apk_scan_service.py`
- GUI controls, worker wiring, visible labels, button flows, terminal/log presentation:
  - `ui/main_window.py`
- Background execution wrappers for GUI actions:
  - `ui/workers/`

## Primary Runtime Flow

### GUI flow

1. Run `python app_gui.py`.
2. Build `HookerContext`.
3. Construct `DeviceService`, `WorkspaceService`, `SessionService`, and `RpcService`.
4. Enable persistent RPC reuse.
5. Click `准备环境并刷新 App`.
6. Select a target app.
7. Optionally initialize the workspace and refresh the script list.
8. Choose a script or generate one.
9. Start attach/spawn injection.
10. Use GUI tools to inspect Activity / Service / Object / View state.

### GUI local APK scan flow

1. Use the left-panel `APK扫描` section.
2. Click `选择 APK`.
3. Pick a local `.apk` file manually.
4. Click `开始扫描`.
5. The GUI runs `mobile-deploy/ApkCheckPack.exe -f <apk>` asynchronously.
6. Output is written to the right-side log panel.

### CLI note

- `hookers.py` still matters for command-driven workflows.
- CLI remains useful for direct attach/spawn and RPC-style commands.
- Do not assume CLI behavior is the same UX target as the GUI.

## Environment Assumptions

- Windows-oriented host environment
- Python 3.12 or 3.13
- `adb` available
- Android device connected over ADB
- Root access available on the target device
- The active Frida server artifact is expected at:
  - `mobile-deploy/rusda-server-16.2.1-android-arm64`
- `mobile-deploy/ApkCheckPack.exe` present for the GUI APK scan feature
- Main Python dependencies include:
  - `frida==16.2.1`
  - `frida-tools==12.3.0`
  - `adbutils`
  - `PySide6`
  - `prompt_toolkit`
  - `jsbeautifier`

- Version note:
  - `frida-tools==13.x` is intentionally avoided here because it upgrades `frida` to `>=16.2.2`, which breaks the repo's version-alignment goal with `rusda-server-16.2.1`.

## Common Misreads To Avoid

- Do not treat per-package directories under `workspaces/` as core source code unless explicitly requested.
- Do not assume old README wording still matches current runtime behavior.
- Do not assume any hidden/phantom Frida mode still exists in current code; the project now uses one fixed `rusda-server-16.2.1` deployment path.
- Do assume workspace initialization ensures a local APK copy exists under `workspaces/<package>/`.
- Do not assume attach means bringing the target app to foreground.
- Do not assume GUI utility actions are allowed to foreground the app.
- Do not assume `APK扫描` depends on the selected target app or workspace; it is a standalone local-file tool.
- Do not infer Linux support from Python/PySide portability alone; the repo is still Windows-oriented in practice.
- Do not start by editing `ui/` if the requested change is actually a device/session/workspace behavior problem.
- Do not treat `mobile-deploy/` binaries as explanatory source code; they are runtime assets.
