# Hookers

`Hookers` 是一个面向 Android 动态调试场景的本地工作台，核心目标是把：

- 设备准备
- `frida-server` 启动
- `radar.dex` 部署
- 目标 App 工作区初始化
- Frida JS 注入
- Activity / Service / Object / View 查询

收敛到一套统一的 CLI / GUI 工作流里。

它不是一个“通用 APK 分析器”，而是一个围绕**单个目标 App 持续调试**的本地工程化外壳。

当前代码提供两个入口：

- CLI: `hookers.py`
- GUI: `app_gui.py`

---

## 1. 这个项目解决什么问题

如果你平时做 Android Frida 调试，通常会不断重复这些动作：

- 连接 ADB 设备
- 确认设备 root 状态
- 手动启动匹配架构的 `frida-server`
- 部署调试辅助资源
- 拉起目标 App
- 准备脚本目录
- attach / spawn 注入
- 保存目标 App 的专属脚本和 APK

这个项目把上述流程拆成了明确的 service 层，再分别暴露给：

- 命令行交互流程
- PySide6 图形界面

从代码上看，核心职责由这些模块承担：

- [core/device_service.py](C:/Users/mengze/Desktop/hooker-master/core/device_service.py:15)
- [core/workspace_service.py](C:/Users/mengze/Desktop/hooker-master/core/workspace_service.py:31)
- [core/session_service.py](C:/Users/mengze/Desktop/hooker-master/core/session_service.py:57)
- [core/rpc_service.py](C:/Users/mengze/Desktop/hooker-master/core/rpc_service.py:13)

---

## 2. 当前能力

基于当前代码，项目已经支持：

- 连接 ADB 设备
- 检测 root / Magisk
- 根据 CPU 架构选择并启动 `frida-server`
- 部署 `radar.dex`
- 枚举设备上的 App
- 把目标 App 拉到前台，或以 spawn 方式准备注入
- 为目标 App 创建独立本地工作区
- 自动复制内置 Frida JS 模板到工作区
- 拉取目标 APK 到本地工作区
- attach / spawn 注入指定脚本
- 通过 `rpc.js` 查询 Activity / Service / Object / View 信息
- 通过 `gs` / GUI 动作生成 hook 脚本
- 在 GUI 中完成常见调试动作

这些能力分别落在：

- 设备准备：[core/device_service.py](C:/Users/mengze/Desktop/hooker-master/core/device_service.py:27)
- 工作区初始化：[core/workspace_service.py](C:/Users/mengze/Desktop/hooker-master/core/workspace_service.py:109)
- 会话生命周期：[core/session_service.py](C:/Users/mengze/Desktop/hooker-master/core/session_service.py:139)
- RPC 和 hook 生成：[core/rpc_service.py](C:/Users/mengze/Desktop/hooker-master/core/rpc_service.py:73)

---

## 3. 运行前提

这个项目当前是**强依赖真实设备环境**的。

开始前请确认：

- Windows
- Python 3.12 或 3.13
- `adb` 已安装并且在 PATH 中可直接执行
- 已连接 Android 设备
- 目标设备已 root
- `mobile-deploy/` 中存在与你设备架构匹配的 `frida-server`

代码中的关键依赖和假设：

- `hookers.py` 启动时会直接执行 bootstrap 流程  
  见 [hookers.py](C:/Users/mengze/Desktop/hooker-master/hookers.py:75)
- bootstrap 会依次调用：
  - `connect()`
  - `start_frida_server()`
  - `deploy_radar_dex()`
  - `refresh_applications()`  
  见 [hookers.py](C:/Users/mengze/Desktop/hooker-master/hookers.py:85)
- `DeviceService.start_frida_server()` 当前只内建了 `arm` / `arm64` 资源选择逻辑  
  见 [core/device_service.py](C:/Users/mengze/Desktop/hooker-master/core/device_service.py:167)

如果设备没有 root，或 `frida-server` 架构不匹配，核心流程基本无法正常工作。

---

## 4. 安装依赖

使用 `venv`：

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

使用 `uv`：

```powershell
uv venv
.venv\Scripts\activate
uv pip install -r requirements.txt
```

当前 Python 依赖见 [requirements.txt](C:/Users/mengze/Desktop/hooker-master/requirements.txt:1)，主要包括：

- `frida`
- `frida-tools`
- `adbutils`
- `PySide6`
- `prompt_toolkit`
- `jsbeautifier`

---

## 5. 目录结构

```text
hooker-master/
├─ app_gui.py
├─ hookers.py
├─ README.md
├─ AGENT.md
├─ LICENSE
├─ requirements.txt
├─ core/
│  ├─ models.py
│  ├─ device_service.py
│  ├─ workspace_service.py
│  ├─ session_service.py
│  └─ rpc_service.py
├─ ui/
│  ├─ main_window.py
│  └─ workers/
├─ js/
├─ mobile-deploy/
└─ workspaces/
   └─ <package-name>/
```

说明：

- `core/`：核心业务层
- `ui/`：GUI 层
- `js/`：全局 Frida JS 模板
- `mobile-deploy/`：设备部署资源
- `workspaces/<package-name>/`：按目标 App 自动生成的本地工作区

工作区目录不是框架核心源码，而是运行时产物。  
对应逻辑见 [core/workspace_service.py](C:/Users/mengze/Desktop/hooker-master/core/workspace_service.py:36)。

---

## 6. 快速开始

### 6.1 检查本地资源

至少确认以下资源存在：

- `js/`
- `mobile-deploy/radar.dex`
- `mobile-deploy/frida-server-16.7.19-android-arm`
- `mobile-deploy/frida-server-16.7.19-android-arm64`

### 6.2 先跑 CLI

```powershell
python hookers.py
```

推荐第一次先用 CLI，因为它会在启动时直接暴露设备准备阶段是否正常。

CLI 启动后会自动执行：

1. 连接 ADB 设备
2. 启动 `frida-server`
3. 部署 `radar.dex`
4. 刷新 App 列表

这部分行为来自 [HookersCli.bootstrap()](C:/Users/mengze/Desktop/hooker-master/hookers.py:75)。

### 6.3 再跑 GUI

```powershell
python app_gui.py
```

GUI 入口本身只负责组装依赖并创建主窗口：

- 构造 `HookerContext`
- 构造四个 service
- 注入 `MainWindow`

见 [app_gui.py](C:/Users/mengze/Desktop/hooker-master/app_gui.py:15)。

注意：GUI 启动后**不会自动准备设备环境**，你需要手动点击“准备环境并刷新 App”。

---

## 7. CLI 使用方式

CLI 不是一次性命令工具，而是两层交互式工作流。

### 7.1 第一层：App 选择层

启动 `python hookers.py` 后，会先显示当前设备上的 App 列表。

这里支持三类输入：

- 包名，例如 `com.example.demo`
- `refresh`
- `exit` / `quit`

对应逻辑见 [hookers.py](C:/Users/mengze/Desktop/hooker-master/hookers.py:369)。

当你输入一个有效包名后，CLI 会：

1. 确保目标 App 进入前台
2. 收集 PID / UID / 版本 / APK 路径等上下文
3. 初始化该 App 的本地工作区

对应代码：

- [HookersCli.select_app()](C:/Users/mengze/Desktop/hooker-master/hookers.py:232)
- [DeviceService.ensure_app_in_foreground()](C:/Users/mengze/Desktop/hooker-master/core/device_service.py:282)
- [WorkspaceService.ensure_workspace()](C:/Users/mengze/Desktop/hooker-master/core/workspace_service.py:164)

### 7.2 第二层：单 App 调试层

进入单 App 调试模式后，提示符会变成当前 App 名称。  
这时围绕当前 App 可用的命令包括：

- `help` / `h`
- `activitys` / `a`
- `services` / `s`
- `object <id|class>` / `o <id|class>`
- `oe <objectId>`
- `view <id>` / `v <id>`
- `gs <class[:method[(args)]]>`
- `ls`
- `attach <script.js>`
- `spawn <script.js>`
- `restart`
- `pid`
- `uid`
- `exit` / `quit` / `q`

命令表定义见 [HookersCli.print_debug_help()](C:/Users/mengze/Desktop/hooker-master/hookers.py:162)。

### 7.3 attach 和 spawn

- `attach`：附加到已运行进程
- `spawn`：先拉起目标进程，再在更早阶段注入

如果你需要尽早拦截启动逻辑、证书校验或初始化行为，通常应先尝试 `spawn`。

真正的执行入口见：

- [SessionService.attach_script()](C:/Users/mengze/Desktop/hooker-master/core/session_service.py:139)
- [SessionService.spawn_script()](C:/Users/mengze/Desktop/hooker-master/core/session_service.py:159)

### 7.4 脚本如何停止

执行 `attach <script.js>` 或 `spawn <script.js>` 后，CLI 会维持当前会话并持续输出日志。

停止方式：

- 在 CLI 中按 `Ctrl + C`

这部分行为在 [HookersCli.execute_script()](C:/Users/mengze/Desktop/hooker-master/hookers.py:203) 中实现。

### 7.5 一个最小 CLI 示例

```text
python hookers.py
hooker(包名): com.example.demo
com.example.demo > ls
com.example.demo > attach okhttp.js
CTRL + C to stop >
```

---

## 8. GUI 使用方式

GUI 是对同一套 `core/` service 的可视化编排，不是单独的另一套底层逻辑。

推荐操作顺序：

1. 启动 `python app_gui.py`
2. 点击“准备环境并刷新 App”
3. 选择目标 App
4. 如有需要，初始化工作目录并拉取 APK
5. 选择脚本
6. 选择 `Attach` 或 `Spawn`
7. 点击“开始注入”
8. 在右侧日志区观察输出

GUI 中的高频动作包括：

- 准备设备环境
- 刷新 App 列表
- 初始化工作区
- 启动 / 停止 Hook
- 查看 Activity / Service 信息
- 查看 Object / View 信息
- 生成 hook 脚本

相关入口见：

- [app_gui.py](C:/Users/mengze/Desktop/hooker-master/app_gui.py:34)
- [ui/main_window.py](C:/Users/mengze/Desktop/hooker-master/ui/main_window.py:63)

---

## 9. 工作区机制

这个项目的一个核心设计是：**每个包名一个本地工作区**。

当你选中某个 App 并初始化工作区后，项目会在 `workspaces/` 下生成类似：

```text
workspaces/
└─ com.example.demo/
   ├─ attach.bat
   ├─ spawn.bat
   ├─ kill.bat
   ├─ objection.bat
   ├─ hooking.bat
   ├─ SomeApp_1.2.3.apk
   └─ js/
      ├─ okhttp.js
      ├─ url.js
      └─ ...
```

这些内容不是手工维护，而是由 `WorkspaceService` 生成：

- 工作区目录：[core/workspace_service.py](C:/Users/mengze/Desktop/hooker-master/core/workspace_service.py:36)
- 轻量工作区壳：[core/workspace_service.py](C:/Users/mengze/Desktop/hooker-master/core/workspace_service.py:74)
- 首次完整初始化：[core/workspace_service.py](C:/Users/mengze/Desktop/hooker-master/core/workspace_service.py:109)

内置模板脚本来自全局 `js/` 目录，初始化时会复制到 `workspaces/<package>/js/`，并把模板里默认包名替换成当前目标包名。  
对应逻辑见 [core/workspace_service.py](C:/Users/mengze/Desktop/hooker-master/core/workspace_service.py:96)。

---

## 10. 内置脚本与 RPC

`js/` 目录包含全局模板脚本，例如：

- `okhttp.js`
- `url.js`
- `just_trust_me.js`
- `DumpDex.js`
- `bypass_root_detect.js`
- `bypass_vpn_detect.js`
- `keystore_dump.js`
- `rpc.js`

其中几个关键脚本：

- `js/rpc.js`
  - 为 `RpcService` 提供导出方法
- `js/_hook_js_prepare.js`
  - 生成 hook 脚本时的前置模板
- `js/_hook_js_enhance.js`
  - 生成 hook 脚本时追加的辅助逻辑
- `js/_hook_js_warp.js`
  - 注入脚本时统一拼接的包装逻辑

对应生成逻辑见 [RpcService.generate_hook_script()](C:/Users/mengze/Desktop/hooker-master/core/rpc_service.py:73)。

额外说明：

- `just_trust_me.js` 在 CLI / GUI 中会自动切换到 V8 runtime  
  见 [hookers.py](C:/Users/mengze/Desktop/hooker-master/hookers.py:213) 和 [ui/workers/hook_worker.py](C:/Users/mengze/Desktop/hooker-master/ui/workers/hook_worker.py:50)

---

## 11. 架构概览

这个项目已经从“单脚本堆逻辑”拆成了“共享上下文 + service + CLI/GUI 外壳”的结构。

### 11.1 共享状态

[core/models.py](C:/Users/mengze/Desktop/hooker-master/core/models.py:13) 定义了：

- `AppRecord`
- `AppContext`
- `HookSession`
- `HookerContext`

其中 `HookerContext` 是 service 协作的状态中心。

### 11.2 service 层

- [DeviceService](C:/Users/mengze/Desktop/hooker-master/core/device_service.py:15)
  - 设备连接、root 检测、前台切换、`frida-server` 启动、`radar.dex` 部署
- [WorkspaceService](C:/Users/mengze/Desktop/hooker-master/core/workspace_service.py:31)
  - 工作区、脚本复制、APK 拉取、输出保存
- [SessionService](C:/Users/mengze/Desktop/hooker-master/core/session_service.py:57)
  - attach / spawn、脚本加载、会话清理、消息处理
- [RpcService](C:/Users/mengze/Desktop/hooker-master/core/rpc_service.py:13)
  - 临时 RPC 调用、对象查询、hook 生成

### 11.3 GUI 层

GUI 主要由这些文件组成：

- [app_gui.py](C:/Users/mengze/Desktop/hooker-master/app_gui.py:15)
- [ui/main_window.py](C:/Users/mengze/Desktop/hooker-master/ui/main_window.py:63)
- [ui/workers/device_worker.py](C:/Users/mengze/Desktop/hooker-master/ui/workers/device_worker.py:8)
- [ui/workers/workspace_worker.py](C:/Users/mengze/Desktop/hooker-master/ui/workers/workspace_worker.py:8)
- [ui/workers/hook_worker.py](C:/Users/mengze/Desktop/hooker-master/ui/workers/hook_worker.py:9)
- [ui/workers/action_worker.py](C:/Users/mengze/Desktop/hooker-master/ui/workers/action_worker.py:8)

---

## 12. 建议的阅读顺序

如果你准备继续开发，建议按这个顺序阅读：

1. [core/models.py](C:/Users/mengze/Desktop/hooker-master/core/models.py:13)
2. [hookers.py](C:/Users/mengze/Desktop/hooker-master/hookers.py:40)
3. [app_gui.py](C:/Users/mengze/Desktop/hooker-master/app_gui.py:15)
4. [core/device_service.py](C:/Users/mengze/Desktop/hooker-master/core/device_service.py:15)
5. [core/workspace_service.py](C:/Users/mengze/Desktop/hooker-master/core/workspace_service.py:31)
6. [core/session_service.py](C:/Users/mengze/Desktop/hooker-master/core/session_service.py:57)
7. [core/rpc_service.py](C:/Users/mengze/Desktop/hooker-master/core/rpc_service.py:13)
8. [ui/main_window.py](C:/Users/mengze/Desktop/hooker-master/ui/main_window.py:63)

---

## 13. 注意事项

- 项目默认依赖 root 环境和 Frida 调试能力
- `frida-server` 必须与设备架构匹配
- 不同 Android ROM 的 shell 输出可能有差异
- GUI 当前可用，但仍属于持续整理中的第一版
- `workspaces/` 下的包名目录属于运行时工作区，不应与框架源码混淆

如果你是在新对话中快速理解这个项目，默认可以先忽略：

- `.venv/`
- `.uv-cache/`
- `.cache/`
- `__pycache__/`
- `workspaces/` 下的具体目标 App 工作区

---

## 14. 后续可继续完善的方向

当前最值得继续补的发布体验项：

- `run_cli.bat` / `run_gui.bat`
- 环境自检脚本
- GUI 截图
- FAQ
- GitHub Release 形式的部署资源说明

---

## 参考

README 的整体重构顺序参考了你提到的项目：

- [CreditTone/hooker](https://github.com/CreditTone/hooker)

但本文档中的功能说明、流程描述和能力边界，均以当前仓库中的实际代码实现为准。
