# Frida-Hookers

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB)
![Platform Windows](https://img.shields.io/badge/Platform-Windows-0078D4)
![Status Experimental](https://img.shields.io/badge/Status-Experimental-orange)

`Frida-Hookers` 是一个面向 Android 动态调试的 GUI 工作台。它的重点不是替代 Frida，而是把“设备准备、目标 App 选择、脚本注入、结果查看”这些高频动作收进一条稳定、重复成本更低的桌面流程里。

如果你经常在这些动作之间来回切换：

- 手动连设备、确认 root、反复起 `frida-server`
- 针对不同 App 重建调试目录和脚本环境
- 一边切 attach / spawn，一边补脚本、看日志、查页面结构
- 默认 `frida-server` 容易被检测时，需要临时换另一套 server

那这个项目的 GUI 就是在解决这组问题。

![Frida-Hookers GUI Overview](docs/images/gui-overview.png)

## Demo

GUI 主界面：

![Frida-Hookers GUI Demo](docs/images/gui-overview.gif)

Hook 注入过程：

![Hook Injection Demo](docs/images/hook-injection.gif)

## 这个项目有什么用

`Frida-Hookers` 适合已经在做 Android Frida 调试，但不想继续把时间花在重复准备动作上的人。它把常见流程收成一个 GUI 工作台，让你能更快进入“针对目标 App 做分析和注入”这一层，而不是一直停留在环境拼装。

在当前版本里，GUI 主要帮你做这些事：

- 连接 ADB 设备并准备 Frida 调试环境
- 在 `正常 Frida sever` 和 `过检测 Florid sever` 之间切换
- 刷新并选择目标 App
- 初始化该 App 的独立工作目录并拉取 APK
- 选择脚本、生成 Hook 脚本、切换 Attach / Spawn 模式
- 发起注入并持续看日志
- 查看 Activity、Service、对象信息和 View 信息

它的定位不是“全能 APK 分析器”，而是更偏向一个围绕单个目标 App 持续调试的桌面工作台。

## 你可以怎么用它

GUI 里的常用链路基本是固定的：

1. 先选择 `Frida sever选择`
2. 点击“准备环境并刷新 App”
3. 选择目标 App
4. 按需点击“初始化工作目录并拉取 APK”
5. 选择已有脚本，或点击“生成 Hook 脚本”
6. 选择 Attach 或 Spawn
7. 点击“开始注入”
8. 在日志区、结果窗口里继续查看运行结果

这条链路的价值在于，它把原本分散在命令行、脚本目录、设备终端里的动作收到了一个界面里。你切目标 App、换脚本、换注入模式时，不需要重新把整套准备流程手搓一遍。

## GUI 快速开始

### 1. 使用前准备

开始前请确认：

- Windows
- Python 3.12 或 3.13
- `adb` 已安装并且可直接执行
- Android 设备已连接
- 目标设备已 root
- `mobile-deploy/` 目录下存在项目运行需要的资源文件

至少要有这些本地资源：

- `mobile-deploy/radar.dex`
- `mobile-deploy/frida-server-16.7.19-android-arm`
- `mobile-deploy/frida-server-16.7.19-android-arm64`
- `mobile-deploy/florida-server-16.7.19`
- `js/` 目录内置脚本

安装依赖：

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 启动 GUI

```powershell
python app_gui.py
```

GUI 启动后不会自动准备设备环境。你进入界面后，第一步就应该是手动点击“准备环境并刷新 App”。

### 3. 第一次使用建议顺序

1. 在 `Frida sever选择` 中确认本次要用的 server
2. 点击“准备环境并刷新 App”
3. 在 App 下拉框里选择目标应用
4. 如果要建立该 App 的独立工作目录，点击“初始化工作目录并拉取 APK”
5. 在脚本区选择现成脚本，或者点击“生成 Hook 脚本”
6. 根据需要选择 Attach 或 Spawn
7. 点击“开始注入”
8. 继续用“查看 Activity”“查看 Service”“对象信息”“对象解释”“View 信息”做分析

## Frida sever选择

GUI 当前支持两种 server 选择：

- `正常 Frida sever`
  - 适合默认调试场景
  - 使用项目内置的标准 `frida-server`
- `过检测 Florid sever`
  - 适合默认 `frida-server` 容易被检测的场景
  - 使用 `mobile-deploy/florida-server-16.7.19`

这个选择只对当前这次 GUI 运行生效，不会写入配置文件。每次你重新点击“准备环境并刷新 App”时，GUI 都会按当前下拉选项准备对应的 server。

## /js 目录能帮你做什么

`/js` 不是单纯的脚本仓库，而是这个项目 GUI 工作流里最实用的一层能力来源。你初始化工作目录后，会围绕这些内置脚本去做注入、验证、分析和补充。

按使用场景来看，当前 `/js` 目录大致可以分成这些能力：

### 通信与证书相关

当你的目标是先把网络链路跑通、看清请求结构、处理常见证书校验时，可以优先从这组脚本开始：

- `just_trust_me.js`
- `okhttp.js`
- `print_okhttp_interceptors.js`

这组脚本更适合做 SSL Pinning 绕过、OkHttp 请求观察、确认拦截器链路这些高频工作。

### 对抗检测相关

当目标 App 会做环境检查、Root 检测、VPN 检测，或者你怀疑它在主动排查 Frida 痕迹时，可以从这组脚本切入：

- `bypass_root_detect.js`
- `bypass_vpn_detect.js`
- `find_anit_frida_so.js`

它们适合拿来快速验证“问题是不是出在环境检测”这一层。

### UI 与页面分析相关

如果你现在的重点是搞清楚页面跳转、Activity 生命周期、控件操作和当前界面结构，这组脚本最直接：

- `activity_events.js`
- `android_ui.js`
- `click.js`
- `edit_text.js`
- `text_view.js`
- `url.js`

这组脚本更偏向界面观察、页面行为跟踪、控件定位和交互辅助。

### 网络栈与运行环境识别

当你还没完全摸清 App 用的是哪套网络栈、设备暴露了哪些信息、当前环境长什么样时，可以用：

- `detect_network_stack.js`
- `get_device_info.js`

它们适合做开局摸底，帮助你先建立对目标运行环境的基本认识。

### 脱壳、提取与安全分析

如果你的目标偏向提取、脱壳、注册信息分析、密钥材料观察，可以关注这组：

- `DumpDex.js`
- `apk_shell_scanner.js`
- `keystore_dump.js`
- `hook_register_natives.js`

这组更适合放在“初步注入已经跑通之后”的分析阶段。

### GUI 联动基础

`rpc.js` 是 GUI 调试工具区的关键基础脚本。你在界面里点击“查看 Activity”“查看 Service”“对象信息”“对象解释”“View 信息”以及“生成 Hook 脚本”时，背后依赖的就是这条能力链路。

另外，`_hook_js_prepare.js`、`_hook_js_enhance.js`、`_hook_js_warp.js` 负责支撑“生成 Hook 脚本”这条路径，让你可以直接从 GUI 里快速起一个新脚本，而不是每次都手写空白模板。

## 工作目录会带来什么

当你点击“初始化工作目录并拉取 APK”后，项目会为当前目标 App 建一个独立工作目录。这样做的好处是：

- 不同 App 的脚本和产物不会混在一起
- 你可以围绕一个包名长期积累自己的脚本
- 拉取下来的 APK、生成出来的 Hook 脚本、后续分析文件都能按 App 分开管理

如果你经常切不同 App 做调试，这一点会比单纯把所有脚本堆在一个目录里好用很多。

## 使用建议

- 想尽早拦截启动逻辑、证书校验或初始化行为时，优先试 `Spawn`
- 只是想连到已经跑起来的 App 上做观察和补充注入时，用 Attach 更直接
- 遇到默认 `frida-server` 容易被检测时，先切到 `过检测 Florid sever` 再重新准备环境
- 先用现成脚本验证方向，再决定是否用“生成 Hook 脚本”补定制逻辑，效率更高

## 注意事项

- 这个项目默认建立在 root + ADB + Frida 可用的前提上
- `frida-server` 必须和目标设备架构匹配
- `过检测 Florid sever` 依赖本地 `mobile-deploy/florida-server-16.7.19`
- GUI 当前是推荐主入口，README 也只覆盖 GUI 使用方式
- `workspaces/` 目录属于运行时工作区，不是框架源码的一部分

## 免责声明

本项目仅用于经过授权的安全测试、学习研究与逆向分析。请在合法、合规和已获得明确授权的场景下使用。

## 参考

- [CreditTone/hooker](https://github.com/CreditTone/hooker)
