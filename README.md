# Frida-Hookers

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB)
![Platform Windows](https://img.shields.io/badge/Platform-Windows-0078D4)
![Status Experimental](https://img.shields.io/badge/Status-Experimental-orange)


## 你还在为重复输入 Hook 指令而烦吗？

**你还在为每次 Hook 前都要重复打开终端、反复输入相似命令而烦吗？**  
**你还在为切换不同 App 时，总要重新整理脚本、工作目录和调试环境而打断思路吗？**  
**你还在一边手动准备设备，一边在 Attach / Spawn、日志输出、页面分析之间来回切换吗？**

> 现在不用担心这些重复又繁琐的操作了。  
> 只需要点击 GUI 界面，就可以完成设备准备、目标 App 选择、脚本注入、日志查看和结果分析这整套流程。

Frida-Hookers 是一个面向 Android 动态调试的 GUI 工作台。它的重点不是替代 Frida，而是把这些高频动作收进一条更稳定、重复成本更低的桌面流程里。 

它不替代 Frida，而是把日常最常用、最容易反复手动执行的动作整理成一个更顺手的GUI工作台。

如果你经常在这些事情之间来回切换：

- 手动连接设备、确认 root、反复启动设备侧 Frida 服务
- 针对不同 App 重建工作目录、脚本副本和调试环境
- 在 Attach / Spawn、脚本修改、日志观察、页面分析之间频繁切换
- 依赖固定的 frida-server 完成设备侧 Frida 准备

那这个项目就是你最好的选择。

![Frida-Hookers GUI Overview](docs/images/gui-overview.png)


## Demo

GUI 主界面：

![Frida-Hookers GUI Demo](docs/images/gui-overview.gif)

Hook 注入过程演示：

![Hook Injection Demo](docs/images/hook-injection.gif)


## 这个项目有什么用

`Frida-Hookers` 的价值，不是替你发明新的调试能力，而是减少你在 Android 动态调试里重复做的那些准备动作。

它把设备准备、目标 App 选择、工作目录初始化、脚本注入、日志查看和结果分析收进同一个 GUI 工作流，让你可以更快开始分析目标 App，而不是反复停在环境准备、命令输入和工具切换上。

如果你经常：

- 重复连接设备、确认 root、启动设备侧 Frida 服务
- 为不同 App 反复整理工作目录、脚本副本和 APK
- 在 Attach / Spawn、脚本调试、日志查看和页面分析之间来回切换

那这个项目的作用，就是把这套高频动作收拢起来，降低重复成本。


## 你可以怎么用它

GUI 里的常用链路基本是固定的：

1. 点击“准备环境并刷新 App”
2. 如果当前手机前台存在可识别的 App，GUI 会优先自动选中它；否则手动选择目标 App
3. 按需点击“初始化工作目录并刷新列表”
   这一步会补齐工作区脚本、辅助 bat，并确保本地 APK 副本存在
4. 选择已有脚本，或点击“生成 Hook 脚本”
5. 选择 Attach 或 Spawn
6. 点击“开始注入”
7. 在日志区、结果窗口里继续查看运行结果

这条链路的价值在于，它把原本分散在命令行、脚本目录、设备终端里的动作收到了一个界面里。你切目标 App、换脚本、换注入模式时，不需要重新把整套准备流程手搓一遍。


## GUI 快速开始

### 1. 使用前准备

开始前请确认：

- Windows
- Python 3.12 或 3.13
- `adb` 已安装并且可直接执行
- Android 设备已连接
- 目标设备已 root
- 目标设备使用 frida 注入过


安装依赖：

方法一：使用 `venv`

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

方法二：使用 `conda`

```powershell
conda create -n hookers python=3.12 -y
conda activate hookers
pip install -r requirements.txt
```

当前项目建议固定使用这组兼容版本：

- `frida==16.2.1`
- `frida-tools==12.3.0`


### 2. 启动 GUI

请先进入你创建好的 Python 环境，再启动 GUI。

#### 方式一：venv 环境
```powershell
.venv\Scripts\activate
python app_gui.py
```
#### 方式二：conda 环境
```powershell
conda activate hookers
python app_gui.py
```

GUI 启动后不会自动准备设备环境。你进入界面后，第一步就应该是手动点击“准备环境并刷新 App”。


### 3. 第一次使用建议顺序

1. 点击“准备环境并刷新 App”
2. 在 App 下拉框里选择目标应用
3. 点击“初始化工作目录并刷新列表”
   程序会把该 App 的 APK 副本放到对应 `workspaces/<package>/`
4. 在脚本区选择现成脚本，或者点击“生成 Hook 脚本”
5. 根据需要选择 Attach 或 Spawn
6. 点击“开始注入”
7. 继续用“查看 Activity”“查看 Service”“对象信息”“对象解释”“View 信息”做分析

## Frida Server

GUI 当前固定使用一个设备侧 server：

- 本地文件：`mobile-deploy/rusda-server-16.2.1-android-arm64`
- 远端路径：`/data/local/tmp/rusda-16.2.1`
- 当前实现不提供 GUI 内的 Frida 变体切换选项
- 左侧额外提供一个 `停止 Frida Server` 按钮，用于手动停止并清理当前受管 server


## 为什么默认使用 rusda？

`Frida-Hookers` 当前固定使用 `rusda-server-16.2.1` 作为设备侧 Frida 服务。  
相比直接使用原版 `frida-server`，`rusda` 的价值在于：它会对一部分常见 Frida 特征做弱化处理，用来降低高频 Frida 检测命中的概率。

从当前项目实践来看，`rusda` 更适合解决这类问题：

- 原版 `frida-server` 的进程名、线程名容易被直接检测
- 一些常见的 Frida / Gum / GDBus 相关字符串容易被简单内存扫描命中
- 默认 Frida 运行时特征在部分环境检测工具中暴露过于明显

所以我们采用 `rusda`来作为 frida 远程服务
`rusda`更准确的定位是：

- **降低高频、表层 Frida 特征暴露**
- **提高日常动态调试时的可用性**
- **减少部分常见反 Frida 检测的直接命中**

在实际使用中，更适合把它理解成：

> 一个比原版 `frida-server` 更低调、更适合日常 GUI 工作流的设备侧 Frida 服务。

在 `Frida-Hookers` 中，设备准备阶段会围绕 `rusda-server-16.2.1` 完成检查、启动和复用，用户不需要手动反复准备这一层。


## /js 脚本说明

根目录 `js/` 是项目内置模板库；如果某个 App 已初始化工作目录，后续更建议在：

- `workspaces/<package>/js/`

里按目标 App 单独修改和沉淀脚本。

### 页面 / Activity / View

- `activity_events.js`
  - 作用：跟踪 Activity 生命周期，如 `onCreate`、`onResume`
  - 推荐：**Attach 优先**；想抓首页启动链可用 Spawn

- `android_ui.js`
  - 作用：配合 `radar.dex` 查看 UI 结构与界面状态
  - 推荐：**Attach 优先**

- `click.js`
  - 作用：观察或辅助页面点击行为
  - 推荐：**Attach 优先**

- `edit_text.js`
  - 作用：观察输入框内容变化与赋值/读取逻辑
  - 推荐：**Attach 优先**

- `text_view.js`
  - 作用：观察 TextView 文本设置与动态文本渲染
  - 推荐：**Attach 优先**

- `url.js`
  - 作用：观察 URL / URI / 部分 OkHttp Builder 层 URL 构建
  - 推荐：页面交互阶段用 **Attach**；启动早期请求可用 Spawn

### 网络 / 证书 / OkHttp

- `just_trust_me.js`
  - 作用：绕过常见 SSL Pinning / 证书校验
  - 推荐：**Spawn 强烈优先**

- `okhttp.js`
  - 作用：Hook OkHttp 请求/响应链路，打印请求头/体与响应头/体
  - 注意：依赖目标 App 里存在对应 OkHttp 类，不是所有 App 都能直接用
  - 推荐：**Spawn 优先**；页面阶段请求可试 Attach

- `print_okhttp_interceptors.js`
  - 作用：枚举 / 打印 OkHttp 拦截器链
  - 推荐：**Attach / Spawn 都可以**

- `detect_network_stack.js`
  - 作用：检测目标 App 使用的网络栈，适合开局摸底
  - 推荐：**Attach / Spawn 都可以**

### 环境检测 / 反检测

- `bypass_root_detect.js`
  - 作用：绕过常见 Root 检测点
  - 推荐：**Spawn 强烈优先**

- `bypass_vpn_detect.js`
  - 作用：绕过常见 VPN / 代理检测
  - 推荐：**Spawn 优先**

- `find_anit_frida_so.js`
  - 作用：监控 `android_dlopen_ext`，辅助定位反 Frida so
  - 推荐：**Spawn 优先**

### Native / Dex / JNI / 加固

- `DumpDex.js`
  - 作用：监控 Dex 加载、动态 so 加载，辅助脱壳 / 提取
  - 推荐：**Spawn 强烈优先**

- `hook_register_natives.js`
  - 作用：Hook `RegisterNatives`，打印 JNI 动态注册信息
  - 推荐：**Spawn 强烈优先**

- `apk_shell_scanner.js`
  - 作用：辅助识别 APK 常见加固/壳特征
  - 推荐：独立分析或 **Spawn**

- `keystore_dump.js`
  - 作用：观察/提取 keystore 相关信息
  - 推荐：**Attach / Spawn 都可以**

### 设备 / 环境信息

- `get_device_info.js`
  - 作用：收集设备与运行环境基础信息
  - 推荐：**Attach / Spawn 都可以**


## 使用建议

- 想尽早拦截启动逻辑、证书校验或初始化行为时，优先试 `Spawn`
- 只是想连到已经跑起来的 App 上做观察和补充注入时，用 Attach 更直接
- 先用现成脚本验证方向，再决定是否用“生成 Hook 脚本”补定制逻辑，效率更高

## 注意事项

- 这个项目默认建立在 root + ADB + Frida 可用的前提上
- `frida-server` 必须和目标设备架构匹配
- 当前固定依赖本地 `mobile-deploy/rusda-server-16.2.1-android-arm64`
- `workspaces/` 目录属于运行时工作区，不是框架源码的一部分

## 免责声明

本项目仅用于经过授权的安全测试、学习研究与逆向分析。请在合法、合规和已获得明确授权的场景下使用。

## 参考

- [CreditTone/hooker](https://github.com/CreditTone/hooker)
- [taisuii/rusda](https://github.com/taisuii/rusda)
