from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QScrollArea,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QDialog,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTextEdit,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .workers.device_worker import DeviceWorker
from .workers.hook_worker import HookWorker
from .workers.action_worker import ActionWorker
from .workers.workspace_worker import WorkspaceWorker


@dataclass
class MainWindowDependencies:
    # GUI 依赖注入容器。
    # 这里不直接 new service，而是由外层统一装配后注入进来，
    # 这样后续更容易做测试、替换实现，或者把同一套 service 同时给 CLI/GUI 使用。
    device_service: Any
    session_service: Any
    workspace_service: Any
    rpc_service: Any
    apk_scan_service: Any
    context: Any


@dataclass
class LogRecord:
    # GUI 内部使用的日志记录模型。
    #
    # 这里把“原始文本”“分类”“级别”拆开保存，
    # 后续过滤、着色、导出都围绕这份结构化数据工作。
    message: str
    category: str
    level: str


class MainWindow(QMainWindow):
    # 第一版 PySide6 主窗口。
    #
    # 目标不是一次性覆盖 CLI 的全部能力，而是先把这几个高频流程跑通：
    # 1. 选择脚本目录并显示脚本
    # 2. 准备设备环境并刷新 App 列表
    # 3. 选择目标 App
    # 4. 选择 attach / spawn 模式开始注入
    # 5. 停止当前 Hook
    # 6. 在右侧面板实时查看日志
    log_emitted = Signal(str)
    session_event_emitted = Signal(str, object)
    MAX_LOG_RECORDS = 3000
    def __init__(self, deps: MainWindowDependencies) -> None:
        super().__init__()
        self.deps = deps
        self.log_records: list[LogRecord] = []
        self.log_file_path: Path | None = None
        self.result_windows: list[QDialog] = []
        self.selected_apk_scan_path: Path | None = None
        self.current_log_match_index = -1
        self.last_log_search_signature: tuple[str, bool, bool] | None = None
        self.visible_log_match_positions: list[tuple[int, int]] = []
        self.log_focus_mode = False
        self.saved_splitter_sizes = [340, 420, 920]
        self.last_log_view_signature: tuple[str, str, bool, bool, bool] | None = None
        self.last_rendered_record_count = 0
        self.log_render_timer = QTimer(self)
        self.log_render_timer.setSingleShot(True)
        self.log_render_timer.setInterval(50)
        self.log_render_timer.timeout.connect(self._flush_scheduled_log_render)

        # 这两个线程分别服务于两个耗时场景：
        # 1. device_thread：准备环境、刷新应用列表
        # 2. hook_thread：切换 App、准备工作区、发起注入
        #
        # 线程本身只负责启动动作，不长期持有 Hook 会话。
        self.device_thread: QThread | None = None
        self.device_worker: DeviceWorker | None = None
        self.workspace_thread: QThread | None = None
        self.workspace_worker: WorkspaceWorker | None = None
        self.hook_thread: QThread | None = None
        self.hook_worker: HookWorker | None = None
        self.action_thread: QThread | None = None
        self.action_worker: ActionWorker | None = None

        # GUI 层接管日志出口：所有 service 的日志最终都通过这个信号回到主线程显示。
        self.deps.context.log_handler = self._handle_log_from_worker
        self.deps.context.session_event_handler = self._handle_session_event_from_worker
        self.log_emitted.connect(self.append_log)
        self.session_event_emitted.connect(self.handle_session_event)

        self.script_root = self.deps.context.js_dir

        self.setWindowTitle("Frida-Hookers GUI 工作台")
        self.resize(1500, 920)
        self._build_ui()
        self._apply_styles()
        self.update_script_root_display()
        self.refresh_script_list()
        self.refresh_app_status_panel()

    def _build_ui(self) -> None:
        # 主体布局采用左右三栏：
        # 左：脚本选择
        # 中：App/模式/动作控制
        # 右：实时日志
        root = QWidget(self)
        self.setCentralWidget(root)

        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(8)
        self.splitter.setOpaqueResize(False)
        layout.addWidget(self.splitter)

        self.script_panel = self._build_script_panel()
        self.control_panel = self._build_control_panel()
        self.log_panel = self._build_log_panel()

        self.script_scroll = self._build_scroll_container(self.script_panel)
        self.control_scroll = self._build_scroll_container(self.control_panel)

        self.script_scroll.setMinimumWidth(300)
        self.script_scroll.setMaximumWidth(380)
        self.control_scroll.setMinimumWidth(360)
        self.control_scroll.setMaximumWidth(500)
        self.log_panel.setMinimumWidth(620)

        self.script_scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.control_scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.log_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.splitter.addWidget(self.script_scroll)
        self.splitter.addWidget(self.control_scroll)
        self.splitter.addWidget(self.log_panel)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setStretchFactor(2, 1)
        self.splitter.setSizes(self.saved_splitter_sizes)

        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("GUI 已就绪，先点击“准备环境并刷新 App”")

    def _build_scroll_container(self, widget: QWidget) -> QScrollArea:
        # 左侧和中间区都放进滚动容器里，避免窗口尺寸偏小时内容被遮挡。
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(widget)
        return scroll

    def _with_dropdown_marker(self, combo: QComboBox) -> QWidget:
        # 某些主题下 QComboBox 原生箭头不明显，这里额外补一个稳定可见的下拉标识。
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(combo, 1)

        marker = QLabel("▼")
        marker.setObjectName("comboMarker")
        marker.setAlignment(Qt.AlignCenter)
        marker.setMinimumWidth(18)
        layout.addWidget(marker)
        return container

    def _build_section_divider(self, title: str) -> QWidget:
        # 给中间工具区加轻量分组分隔，让不同功能块更容易扫视。
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 6, 0, 6)
        layout.setSpacing(8)

        left_line = QFrame()
        left_line.setFrameShape(QFrame.HLine)
        left_line.setObjectName("sectionLine")
        layout.addWidget(left_line, 1)

        label = QLabel(title)
        label.setObjectName("sectionCaption")
        layout.addWidget(label)

        right_line = QFrame()
        right_line.setFrameShape(QFrame.HLine)
        right_line.setObjectName("sectionLine")
        layout.addWidget(right_line, 1)
        return container

    def _build_script_panel(self) -> QWidget:
        # 左侧脚本面板。
        # 这里允许用户切换脚本目录，所以 GUI 不强制绑定到项目内置 js/。
        panel = QWidget()
        panel.setObjectName("sidePanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel("脚本库 (.js)")
        title.setObjectName("panelTitle")
        layout.addWidget(title)

        self.script_dir_input = QLineEdit()
        self.script_dir_input.setReadOnly(True)
        layout.addWidget(self.script_dir_input)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self.select_script_dir_button = QPushButton("选择脚本文件夹")
        self.select_script_dir_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.select_script_dir_button.clicked.connect(self.choose_script_directory)
        button_row.addWidget(self.select_script_dir_button)

        self.reload_script_dir_button = QPushButton("刷新脚本")
        self.reload_script_dir_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.reload_script_dir_button.clicked.connect(self.refresh_script_list)
        button_row.addWidget(self.reload_script_dir_button)
        layout.addLayout(button_row)

        self.selected_script_label = QLabel("当前脚本：未选择")
        self.selected_script_label.setWordWrap(True)
        self.selected_script_label.setMinimumHeight(48)
        layout.addWidget(self.selected_script_label)

        script_combo_label = QLabel("脚本文件选择")
        script_combo_label.setObjectName("mutedLabel")
        layout.addWidget(script_combo_label)

        self.script_combo = QComboBox()
        self.script_combo.setEditable(False)
        self.script_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.script_combo.currentIndexChanged.connect(self._update_selected_script_tip)
        layout.addWidget(self._with_dropdown_marker(self.script_combo))

        app_status_title = QLabel("App 状态")
        app_status_title.setObjectName("panelTitle")
        layout.addWidget(app_status_title)

        self.left_pid_uid_status_value = QLabel("PID: - | UID: -")
        self.left_pid_uid_status_value.setWordWrap(True)
        self.left_pid_uid_status_value.setObjectName("statusValue")
        layout.addWidget(self.left_pid_uid_status_value)

        self.left_version_mode_status_value = QLabel("Version: - | 模式: 未启动")
        self.left_version_mode_status_value.setWordWrap(True)
        self.left_version_mode_status_value.setObjectName("statusValue")
        layout.addWidget(self.left_version_mode_status_value)

        frida_tool_title = QLabel("Frida 工具")
        frida_tool_title.setObjectName("panelTitle")
        layout.addWidget(frida_tool_title)

        self.stop_frida_server_button = QPushButton("停止 Frida Server")
        self.stop_frida_server_button.clicked.connect(self.stop_frida_server)
        layout.addWidget(self.stop_frida_server_button)

        apk_scan_title = QLabel("APK扫描")
        apk_scan_title.setObjectName("panelTitle")
        layout.addWidget(apk_scan_title)

        self.apk_scan_path_input = QLineEdit()
        self.apk_scan_path_input.setReadOnly(True)
        self.apk_scan_path_input.setPlaceholderText("选择一个本地 .apk 文件后开始扫描")
        layout.addWidget(self.apk_scan_path_input)

        apk_scan_button_row = QHBoxLayout()
        apk_scan_button_row.setSpacing(8)

        self.select_apk_scan_button = QPushButton("选择 APK")
        self.select_apk_scan_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.select_apk_scan_button.clicked.connect(self.choose_apk_for_scan)
        apk_scan_button_row.addWidget(self.select_apk_scan_button)

        self.start_apk_scan_button = QPushButton("开始扫描")
        self.start_apk_scan_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.start_apk_scan_button.setDisabled(True)
        self.start_apk_scan_button.clicked.connect(self.start_apk_scan)
        apk_scan_button_row.addWidget(self.start_apk_scan_button)

        layout.addLayout(apk_scan_button_row)

        self.apk_scan_status_label = QLabel("当前未选择 APK")
        self.apk_scan_status_label.setWordWrap(True)
        self.apk_scan_status_label.setObjectName("statusValue")
        layout.addWidget(self.apk_scan_status_label)

        layout.addStretch(1)
        return panel

    def _build_control_panel(self) -> QWidget:
        # 中间控制区。
        # 这块主要承载“准备环境 -> 选择 App -> 选择模式 -> 启动/停止”的主操作流。
        panel = QWidget()
        panel.setObjectName("controlPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        title = QLabel("控制台")
        title.setObjectName("panelTitle")
        layout.addWidget(title)

        form = QGridLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(10)
        layout.addLayout(form)

        self.refresh_apps_button = QPushButton("准备环境并刷新 App")
        self.refresh_apps_button.clicked.connect(self.start_device_prepare)
        form.addWidget(self.refresh_apps_button, 0, 0, 1, 2)

        app_label = QLabel("目标 App")
        self.app_combo = QComboBox()
        self.app_combo.setEditable(False)
        self.app_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.app_combo.currentIndexChanged.connect(self.on_package_changed)
        form.addWidget(app_label, 1, 0)
        form.addWidget(self._with_dropdown_marker(self.app_combo), 1, 1)

        workspace_label = QLabel("工作目录")
        self.workspace_path_input = QLineEdit()
        self.workspace_path_input.setReadOnly(True)
        self.workspace_path_input.setPlaceholderText(
            "选择 App 后显示目标工作目录；点击初始化后才会真正创建和补齐文件"
        )
        form.addWidget(workspace_label, 2, 0)
        form.addWidget(self.workspace_path_input, 2, 1)

        self.prepare_workspace_button = QPushButton("初始化工作目录并刷新列表")
        self.prepare_workspace_button.clicked.connect(self.prepare_selected_workspace)
        self.prepare_workspace_button.setDisabled(True)
        form.addWidget(self.prepare_workspace_button, 3, 0, 1, 2)

        mode_label = QLabel("注入模式")
        mode_row = QHBoxLayout()
        mode_row.setSpacing(18)
        self.attach_mode_radio = QRadioButton("Attach 模式")
        self.spawn_mode_radio = QRadioButton("Spawn 模式 (-f)")
        self.attach_mode_radio.setChecked(True)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_group.addButton(self.attach_mode_radio)
        self.mode_group.addButton(self.spawn_mode_radio)
        mode_row.addWidget(self.attach_mode_radio)
        mode_row.addWidget(self.spawn_mode_radio)
        mode_row.addStretch(1)
        form.addWidget(mode_label, 4, 0)
        form.addLayout(mode_row, 4, 1)

        # 调试工具区把 CLI 里已有的高频分析能力接到 GUI。
        debug_title = QLabel("调试工具")
        debug_title.setObjectName("panelTitle")
        layout.addWidget(debug_title)

        self.hook_target_input = QLineEdit()
        self.hook_target_input.setPlaceholderText("输入类名或类名:方法，例如 com.demo.Test:onCreate")

        self.generate_hook_button = QPushButton("生成 Hook 脚本")
        self.generate_hook_button.clicked.connect(self.generate_hook_script)

        self.view_activity_button = QPushButton("查看 Activity")
        self.view_activity_button.clicked.connect(self.show_activities)

        self.view_service_button = QPushButton("查看 Service")
        self.view_service_button.clicked.connect(self.show_services)

        self.restart_app_button = QPushButton("重启 App")
        self.restart_app_button.clicked.connect(self.restart_current_app)

        # 对象分析区承接 object_info / object_to_explain / view_info。
        self.inspect_target_input = QLineEdit()
        self.inspect_target_input.setPlaceholderText("输入对象 ID、类名或 View ID")

        self.object_info_button = QPushButton("对象信息")
        self.object_info_button.clicked.connect(self.show_object_info)

        self.object_explain_button = QPushButton("对象解释")
        self.object_explain_button.clicked.connect(self.show_object_explain)

        self.view_info_button = QPushButton("View 信息")
        self.view_info_button.clicked.connect(self.show_view_info)

        # 重新收编调试工具布局：
        # 1. 需要输入的功能，输入框和按钮上下放在一起
        # 2. 不需要输入的功能，按钮集中成一组
        hook_group = QWidget()
        hook_group_layout = QVBoxLayout(hook_group)
        hook_group_layout.setContentsMargins(0, 0, 0, 0)
        hook_group_layout.setSpacing(8)
        layout.addWidget(hook_group)

        hook_group_layout.addWidget(self._build_section_divider("脚本生成"))
        hook_group_layout.addWidget(self.hook_target_input)
        hook_group_layout.addWidget(self.generate_hook_button)

        inspect_group = QWidget()
        inspect_group_layout = QVBoxLayout(inspect_group)
        inspect_group_layout.setContentsMargins(0, 0, 0, 0)
        inspect_group_layout.setSpacing(8)
        layout.addWidget(inspect_group)

        inspect_group_layout.addWidget(self._build_section_divider("对象分析"))
        inspect_group_layout.addWidget(self.inspect_target_input)

        inspect_button_row = QGridLayout()
        inspect_button_row.setHorizontalSpacing(10)
        inspect_button_row.setVerticalSpacing(10)
        inspect_group_layout.addLayout(inspect_button_row)
        inspect_button_row.addWidget(self.object_info_button, 0, 0)
        inspect_button_row.addWidget(self.object_explain_button, 0, 1)
        inspect_button_row.addWidget(self.view_info_button, 1, 0, 1, 2)

        layout.addWidget(self._build_section_divider("页面查询"))

        no_input_group = QWidget()
        no_input_layout = QGridLayout(no_input_group)
        no_input_layout.setContentsMargins(0, 0, 0, 0)
        no_input_layout.setHorizontalSpacing(10)
        no_input_layout.setVerticalSpacing(10)
        layout.addWidget(no_input_group)
        no_input_layout.addWidget(self.view_activity_button, 0, 0)
        no_input_layout.addWidget(self.view_service_button, 0, 1)
        no_input_layout.addWidget(self.restart_app_button, 1, 0, 1, 2)

        layout.addWidget(self._build_section_divider("应用控制"))

        self.start_hook_button = QPushButton("开始注入")
        self.start_hook_button.setObjectName("primaryButton")
        self.start_hook_button.clicked.connect(self.start_hook)
        layout.addWidget(self.start_hook_button)

        self.stop_hook_button = QPushButton("停止 Hook")
        self.stop_hook_button.setObjectName("dangerButton")
        self.stop_hook_button.clicked.connect(self.stop_hook)
        self.stop_hook_button.setDisabled(True)
        layout.addWidget(self.stop_hook_button)

        self.current_state_label = QLabel("状态：空闲")
        self.current_state_label.setObjectName("stateLabel")
        self.current_state_label.setWordWrap(True)
        self.current_state_label.setMinimumHeight(54)
        layout.addWidget(self.current_state_label)

        layout.addStretch(1)
        return panel

    def _build_log_panel(self) -> QWidget:
        # 右侧日志区。
        # 所有 service 最终都走 context.log_handler -> log_emitted -> append_log
        # 这条链路，把后台工作线程里的文本安全地送回主线程显示。
        panel = QWidget()
        panel.setObjectName("logPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel("运行日志")
        title.setObjectName("panelTitle")
        layout.addWidget(title)

        tools_row = QHBoxLayout()
        self.log_filter_combo = QComboBox()
        self.log_filter_combo.addItems(["全部日志", "只看 [JS]", "只看错误"])
        self.log_filter_combo.addItem("只看调试工具")
        self.log_filter_combo.currentIndexChanged.connect(self.on_log_view_controls_changed)
        tools_row.addWidget(self._with_dropdown_marker(self.log_filter_combo), 1)

        self.choose_log_file_button = QPushButton("日志文件")
        self.choose_log_file_button.setObjectName("compactButton")
        self.choose_log_file_button.setToolTip("未启用日志文件保存")
        self.choose_log_file_button.clicked.connect(self.choose_log_file)
        tools_row.addWidget(self.choose_log_file_button)

        self.clear_log_button = QPushButton("清空")
        self.clear_log_button.setObjectName("compactButton")
        self.clear_log_button.setToolTip("只清空当前 GUI 日志显示，不删除已保存日志文件")
        self.clear_log_button.clicked.connect(self.clear_logs)
        tools_row.addWidget(self.clear_log_button)

        self.toggle_log_focus_button = QPushButton("专注日志")
        self.toggle_log_focus_button.setObjectName("compactButton")
        self.toggle_log_focus_button.setToolTip("一键最大化右侧日志区")
        self.toggle_log_focus_button.clicked.connect(self.toggle_log_focus_mode)
        tools_row.addWidget(self.toggle_log_focus_button)
        layout.addLayout(tools_row)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)

        self.log_search_input = QLineEdit()
        self.log_search_input.setPlaceholderText("搜索终端信息")
        self.log_search_input.textChanged.connect(self.on_log_search_changed)
        self.log_search_input.returnPressed.connect(self.find_next_log_match)
        search_row.addWidget(self.log_search_input, 1)

        self.prev_log_match_button = QPushButton("上一条")
        self.prev_log_match_button.setObjectName("compactButton")
        self.prev_log_match_button.clicked.connect(self.find_previous_log_match)
        self.prev_log_match_button.setDisabled(True)
        search_row.addWidget(self.prev_log_match_button)

        self.next_log_match_button = QPushButton("下一条")
        self.next_log_match_button.setObjectName("compactButton")
        self.next_log_match_button.clicked.connect(self.find_next_log_match)
        self.next_log_match_button.setDisabled(True)
        search_row.addWidget(self.next_log_match_button)

        self.clear_log_search_button = QPushButton("清空搜索")
        self.clear_log_search_button.setObjectName("compactButton")
        self.clear_log_search_button.clicked.connect(self.clear_log_search)
        search_row.addWidget(self.clear_log_search_button)
        layout.addLayout(search_row)

        status_row = QHBoxLayout()
        status_row.setSpacing(12)

        self.log_search_status_label = QLabel("当前范围：全部日志 | 搜索结果：-")
        self.log_search_status_label.setObjectName("statusValue")
        status_row.addWidget(self.log_search_status_label, 1)

        self.log_search_case_checkbox = QCheckBox("区分大小写")
        self.log_search_case_checkbox.toggled.connect(self.on_log_search_changed)
        status_row.addWidget(self.log_search_case_checkbox)

        self.log_search_regex_checkbox = QCheckBox("正则搜索")
        self.log_search_regex_checkbox.toggled.connect(self.on_log_search_changed)
        status_row.addWidget(self.log_search_regex_checkbox)

        self.log_search_matches_only_checkbox = QCheckBox("仅显示匹配项")
        self.log_search_matches_only_checkbox.toggled.connect(self.on_log_search_changed)
        status_row.addWidget(self.log_search_matches_only_checkbox)
        layout.addLayout(status_row)

        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        layout.addWidget(self.log_console, 1)
        return panel

    def _apply_styles(self) -> None:
        # 第一版风格偏“桌面工作台”，不是默认控件堆叠。
        # 左中区域用暖色浅底，右侧日志保持黑底高对比，便于长时间盯日志。
        self.setStyleSheet(
            """
            QWidget {
                background: #f5f4ef;
                color: #2e2a24;
                font-size: 14px;
            }
            QMainWindow {
                background: #f5f4ef;
            }
            QScrollArea {
                border: none;
                background: transparent;
            }
            QWidget#sidePanel, QWidget#controlPanel {
                background: #f8f5ef;
                border: 1px solid #e2d6c5;
                border-radius: 16px;
            }
            QWidget#logPanel {
                background: #f8f5ef;
                border: 1px solid #d7d0c4;
                border-radius: 16px;
            }
            QLabel#panelTitle {
                font-size: 20px;
                font-weight: 700;
                color: #574633;
                padding-bottom: 6px;
            }
            QLabel#mutedLabel {
                color: #8c7a65;
            }
            QLabel#comboMarker {
                color: #8c7a65;
                font-size: 12px;
                font-weight: 700;
                padding-right: 2px;
            }
            QLabel#sectionCaption {
                color: #90785d;
                font-size: 12px;
                font-weight: 600;
                padding: 0 4px;
            }
            QFrame#sectionLine {
                color: #cdb99e;
                background: #cdb99e;
                max-height: 1px;
            }
            QLabel#stateLabel {
                padding: 10px 12px;
                border-radius: 10px;
                background: #efe4d0;
                color: #6a553f;
                border: 1px solid #d9c4a6;
            }
            QLabel#statusValue {
                padding: 6px 8px;
                border-radius: 8px;
                background: #fffdf9;
                border: 1px solid #d8ccb9;
                color: #4e4033;
            }
            QLineEdit, QComboBox, QListWidget, QTextEdit {
                border: 1px solid #d8ccb9;
                border-radius: 10px;
                padding: 10px;
                background: #fffdf9;
                selection-background-color: #d6ead8;
            }
            QListWidget::item {
                padding: 8px 6px;
                border-radius: 6px;
            }
            QListWidget::item:selected {
                background: #d6ead8;
                color: #204c34;
            }
            QPushButton {
                border: 0;
                border-radius: 12px;
                padding: 12px 14px;
                background: #e2d3bf;
                color: #3d3228;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #d8c5ab;
            }
            QPushButton#primaryButton {
                background: #65c466;
                color: white;
                font-size: 16px;
            }
            QPushButton#primaryButton:hover {
                background: #54b657;
            }
            QPushButton#dangerButton {
                background: #e67676;
                color: white;
                font-size: 16px;
            }
            QPushButton#dangerButton:hover {
                background: #d96060;
            }
            QPushButton#compactButton {
                padding: 8px 10px;
                border-radius: 10px;
                font-size: 13px;
            }
            QTextEdit {
                background: #101512;
                color: #3cff70;
                border: 1px solid #253228;
                font-family: Consolas, "Courier New", monospace;
                font-size: 12px;
            }
            QRadioButton {
                spacing: 8px;
                color: #4b3d30;
            }
            QRadioButton::indicator {
                width: 16px;
                height: 16px;
                border-radius: 8px;
                border: 2px solid #b79d7b;
                background: #fffdf9;
            }
            QRadioButton::indicator:checked {
                background: #8a6e4f;
                border: 2px solid #8a6e4f;
            }
            QRadioButton::indicator:unchecked:hover {
                border: 2px solid #9d8465;
            }
            QWidget#logPanel QLabel#panelTitle,
            QWidget#logPanel QLabel#mutedLabel {
                background: transparent;
                color: #574633;
            }
            QCheckBox {
                spacing: 8px;
            }
            """
        )

    def shorten_path(self, path: Path, keep: int = 18) -> str:
        # 左侧区域较窄，路径太长时做中间省略显示，完整路径放在 tooltip 里。
        text = str(path)
        if len(text) <= keep * 2 + 3:
            return text
        return f"{text[:keep]}...{text[-keep:]}"

    def update_script_root_display(self) -> None:
        # 统一刷新“当前脚本库目录”的显示文本和悬浮提示。
        display = self.shorten_path(self.script_root)
        self.script_dir_input.setText(display)
        self.script_dir_input.setToolTip(str(self.script_root))

    def clear_workspace_display(self) -> None:
        # 未选中 App 或重新准备环境时，清掉上一次遗留的工作目录显示。
        self.workspace_path_input.clear()
        self.workspace_path_input.setToolTip("")

    def update_apk_scan_display(self) -> None:
        if self.selected_apk_scan_path is None:
            self.apk_scan_path_input.clear()
            self.apk_scan_path_input.setToolTip("")
            self.apk_scan_status_label.setText("当前未选择 APK")
            self.start_apk_scan_button.setDisabled(True)
            return

        self.apk_scan_path_input.setText(self.shorten_path(self.selected_apk_scan_path))
        self.apk_scan_path_input.setToolTip(str(self.selected_apk_scan_path))
        self.apk_scan_status_label.setText(f"当前扫描目标：{self.selected_apk_scan_path.name}")
        self.start_apk_scan_button.setDisabled(False)

    def _handle_log_from_worker(self, message: str) -> None:
        # 任何线程里的日志都不要直接操作 Qt 控件，
        # 统一转成信号，交回主线程更新界面。
        self.log_emitted.emit(message)

    def _handle_session_event_from_worker(
        self,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        # 会话 detached 等事件可能来自 Frida 后台线程，这里统一切回主线程。
        self.session_event_emitted.emit(event_type, payload)

    def handle_session_event(self, event_type: str, payload: Any) -> None:
        if event_type != "detached":
            return
        if not isinstance(payload, dict):
            payload = {}

        package_name = str(payload.get("package_name") or self.selected_package_name() or "")
        mode = str(payload.get("mode") or "attach")
        reason = str(payload.get("reason") or "unknown")
        old_pid = payload.get("old_pid")
        new_pid = payload.get("new_pid")

        if new_pid is not None and old_pid is not None and new_pid != old_pid:
            self.current_state_label.setText(
                f"状态：{mode} 会话已断开 | PID 变化 {old_pid} -> {new_pid}"
            )
            self.status_bar.showMessage(
                f"{mode} 会话已断开，检测到新 PID：{new_pid}，请重新附加"
            )
        else:
            self.current_state_label.setText(
                f"状态：{mode} 会话已断开 | reason: {reason}"
            )
            self.status_bar.showMessage(f"{mode} 会话已断开，请重新附加")

        self.start_hook_button.setDisabled(False)
        self.stop_hook_button.setDisabled(True)
        self.refresh_app_status_panel(package_name or None)

    def normalize_js_log_message(self, message: str) -> str:
        normalized = message.replace("\r\n", "\n").replace("\r", "\n")
        normalized = "\n".join(line.rstrip() for line in normalized.split("\n"))
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        return normalized.rstrip()

    def is_effectively_empty_js_log(self, message: str) -> bool:
        if message.startswith("[JS:ERROR]"):
            payload = message[len("[JS:ERROR]"):]
        elif message.startswith("[JS:WARN]"):
            payload = message[len("[JS:WARN]"):]
        elif message.startswith("[JS]"):
            payload = message[len("[JS]"):]
        else:
            return False
        return payload.strip() == ""

    def classify_log(self, message: str) -> LogRecord:
        # 根据日志前缀和关键词做粗粒度分类。
        #
        # 第一版不追求复杂的日志协议，只基于现有输出做足够实用的分类：
        # - [JS] / [JS:WARN] / [JS:ERROR]
        # - [!]
        # - 解密结果已保存到真实目录
        # 这样就能先把“过滤”和“着色”做起来。
        category = "general"
        level = "info"

        if message.startswith("[JS:ERROR]"):
            category = "js"
            level = "error"
        elif message.startswith("[JS:WARN]"):
            category = "js"
            level = "warn"
        elif message.startswith("[JS]"):
            category = "js"
            level = "info"
        elif message.startswith("[TOOL]"):
            category = "tool"
            level = "info"
        elif message.startswith("[!]"):
            category = "error"
            level = "error"
        elif "解密结果已保存到真实目录" in message or "日志文件已启用" in message:
            category = "general"
            level = "success"
        elif message.startswith("[+]"):
            category = "general"
            level = "success"

        return LogRecord(message=message, category=category, level=level)

    def log_color(self, record: LogRecord) -> str:
        # 为不同级别的日志分配颜色。
        if record.level == "error":
            return "#ff6b6b"
        if record.level == "warn":
            return "#ffd166"
        if record.category == "tool":
            return "#7ad7ff"
        if record.level == "success":
            return "#65f18c"
        return "#3cff70"

    def should_show_log(self, record: LogRecord) -> bool:
        # 根据当前过滤器判断一条日志是否需要显示。
        filter_name = self.log_filter_combo.currentText()
        if filter_name == "全部日志":
            return True
        if filter_name == "只看 [JS]":
            return record.category == "js"
        if filter_name == "只看错误":
            return record.level == "error"
        if filter_name == "只看调试工具":
            return record.category == "tool"
        return True

    def current_log_filter_scope(self) -> str:
        filter_name = self.log_filter_combo.currentText()
        if filter_name == "全部日志":
            return "全部日志"
        return filter_name

    def toggle_log_focus_mode(self) -> None:
        if not self.log_focus_mode:
            self.saved_splitter_sizes = self.splitter.sizes()
            total_width = max(sum(self.saved_splitter_sizes), self.width())
            self.script_scroll.hide()
            self.control_scroll.hide()
            self.splitter.setHandleWidth(0)
            self.log_panel.show()
            self.splitter.setSizes([0, 0, total_width])
            self.log_focus_mode = True
            self.toggle_log_focus_button.setText("恢复布局")
            self.toggle_log_focus_button.setToolTip("退出专注日志模式并恢复原布局")
            self.status_bar.showMessage("已进入专注日志模式")
            return

        self.script_scroll.show()
        self.control_scroll.show()
        self.splitter.setHandleWidth(8)
        self.log_focus_mode = False
        self.toggle_log_focus_button.setText("专注日志")
        self.toggle_log_focus_button.setToolTip("一键最大化右侧日志区")
        self.splitter.setSizes(self.saved_splitter_sizes)
        self.status_bar.showMessage("已恢复默认布局")

    def log_search_keyword(self) -> str:
        return self.log_search_input.text().strip()

    def log_search_signature(self) -> tuple[str, bool, bool]:
        return (
            self.log_search_keyword(),
            self.log_search_case_checkbox.isChecked(),
            self.log_search_regex_checkbox.isChecked(),
        )

    def current_log_view_signature(self) -> tuple[str, str, bool, bool, bool]:
        return (
            self.log_filter_combo.currentText(),
            self.log_search_keyword(),
            self.log_search_case_checkbox.isChecked(),
            self.log_search_regex_checkbox.isChecked(),
            self.log_search_matches_only_checkbox.isChecked(),
        )

    def on_log_view_controls_changed(self) -> None:
        self.render_logs()

    def on_log_search_changed(self) -> None:
        signature = self.log_search_signature()
        if signature != self.last_log_search_signature:
            self.current_log_match_index = 0 if signature[0] else -1
            self.last_log_search_signature = signature
        self.render_logs()

    def clear_log_search(self) -> None:
        self.log_search_input.clear()

    def compile_log_search_pattern(self) -> tuple[re.Pattern[str] | None, str | None]:
        keyword = self.log_search_keyword()
        if not keyword:
            return None, None

        flags = 0 if self.log_search_case_checkbox.isChecked() else re.IGNORECASE
        pattern_text = keyword if self.log_search_regex_checkbox.isChecked() else re.escape(keyword)
        try:
            return re.compile(pattern_text, flags), None
        except re.error as exc:
            return None, str(exc)

    def find_next_log_match(self) -> None:
        keyword = self.log_search_keyword()
        if not keyword:
            return
        total = getattr(self, "visible_log_match_count", 0)
        if total <= 0:
            return
        if self.current_log_match_index < 0:
            self.current_log_match_index = 0
        else:
            self.current_log_match_index = (self.current_log_match_index + 1) % total
        self.render_logs()

    def find_previous_log_match(self) -> None:
        keyword = self.log_search_keyword()
        if not keyword:
            return
        total = getattr(self, "visible_log_match_count", 0)
        if total <= 0:
            return
        if self.current_log_match_index < 0:
            self.current_log_match_index = total - 1
        else:
            self.current_log_match_index = (self.current_log_match_index - 1) % total
        self.render_logs()

    def highlight_log_text(
        self,
        message: str,
        pattern: re.Pattern[str] | None,
        global_match_start: int,
    ) -> tuple[str, int]:
        if pattern is None:
            return escape(message), 0

        highlighted_parts: list[str] = []
        match_count = 0
        last_end = 0

        for match in pattern.finditer(message):
            start, end = match.span()
            if start == end:
                continue
            highlighted_parts.append(escape(message[last_end:start]))
            color = "#ffd54f"
            if global_match_start + match_count == self.current_log_match_index:
                color = "#ff8a65"
            highlighted_parts.append(
                f'<span style="background-color: {color}; color: #1f1f1f; border-radius: 2px;">'
                f"{escape(match.group(0))}"
                "</span>"
            )
            last_end = end
            match_count += 1

        if match_count == 0:
            return escape(message), 0

        highlighted_parts.append(escape(message[last_end:]))
        return "".join(highlighted_parts), match_count

    def focus_current_log_match(self) -> None:
        if self.current_log_match_index < 0:
            return
        if self.current_log_match_index >= len(self.visible_log_match_positions):
            return

        position, length = self.visible_log_match_positions[self.current_log_match_index]
        cursor = QTextCursor(self.log_console.document())
        cursor.setPosition(position)
        cursor.setPosition(position + max(length, 1), QTextCursor.KeepAnchor)
        self.log_console.setTextCursor(cursor)
        self.log_console.ensureCursorVisible()

    def can_incrementally_append_log(self, record: LogRecord, overflow: int) -> bool:
        if overflow > 0:
            return False
        if self.log_search_keyword():
            return False
        current_signature = self.current_log_view_signature()
        if self.last_log_view_signature != current_signature:
            return False
        return True

    def append_log_record_to_console(self, record: LogRecord) -> None:
        if not self.should_show_log(record):
            return
        cursor = self.log_console.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertHtml(
            f'<span style="color: {self.log_color(record)}; white-space: pre-wrap;">'
            f"{escape(record.message)}"
            "</span><br/>"
        )
        self.log_console.setTextCursor(cursor)
        self.log_console.ensureCursorVisible()

    def schedule_log_render(self) -> None:
        if not self.log_render_timer.isActive():
            self.log_render_timer.start()

    def _flush_scheduled_log_render(self) -> None:
        self.render_logs()

    def render_logs(self) -> None:
        # 重新渲染日志区。
        #
        # 过滤条件切换时直接基于内存中的结构化日志重绘，
        # 而不是去解析 QTextEdit 里的文本。
        if self.log_render_timer.isActive():
            self.log_render_timer.stop()
        keyword = self.log_search_keyword()
        pattern, pattern_error = self.compile_log_search_pattern()
        matches_only = self.log_search_matches_only_checkbox.isChecked() and bool(keyword) and pattern_error is None
        html_lines: list[str] = []
        total_matches = 0
        self.visible_log_match_positions = []
        plain_text_offset = 0
        for record in self.log_records:
            if not self.should_show_log(record):
                continue
            message_html, match_count = self.highlight_log_text(record.message, pattern, total_matches)
            if matches_only and match_count == 0:
                continue
            if pattern is not None:
                for match in pattern.finditer(record.message):
                    start, end = match.span()
                    if start == end:
                        continue
                    self.visible_log_match_positions.append((plain_text_offset + start, end - start))
            html_lines.append(
                f'<span style="color: {self.log_color(record)}; white-space: pre-wrap;">'
                f"{message_html}"
                "</span><br/>"
            )
            total_matches += match_count
            plain_text_offset += len(record.message) + 1

        self.visible_log_match_count = total_matches
        scope_text = self.current_log_filter_scope()
        if matches_only:
            scope_text = f"{scope_text} | 仅显示匹配项"
        if keyword:
            if pattern_error:
                self.current_log_match_index = -1
                self.log_search_status_label.setText(
                    f"当前范围：{scope_text} | 搜索结果：正则无效"
                )
            elif total_matches == 0:
                self.current_log_match_index = -1
                self.log_search_status_label.setText(
                    f"当前范围：{scope_text} | 搜索结果：0 / 0"
                )
            else:
                if self.current_log_match_index < 0:
                    self.current_log_match_index = 0
                elif self.current_log_match_index >= total_matches:
                    self.current_log_match_index = total_matches - 1
                self.log_search_status_label.setText(
                    f"当前范围：{scope_text} | 搜索结果：{self.current_log_match_index + 1} / {total_matches}"
                )
        else:
            self.current_log_match_index = -1
            self.log_search_status_label.setText(f"当前范围：{scope_text} | 搜索结果：-")

        self.log_console.setUpdatesEnabled(False)
        self.log_console.setHtml("".join(html_lines))
        if keyword and total_matches > 0 and self.current_log_match_index >= 0 and not pattern_error:
            self.focus_current_log_match()
        else:
            self.log_console.moveCursor(QTextCursor.End)
        self.log_console.setUpdatesEnabled(True)
        self.prev_log_match_button.setDisabled(total_matches <= 0 or pattern_error is not None)
        self.next_log_match_button.setDisabled(total_matches <= 0 or pattern_error is not None)
        self.last_log_view_signature = self.current_log_view_signature()
        self.last_rendered_record_count = len(self.log_records)

    def persist_log(self, message: str) -> None:
        # 如果用户选择了日志文件，就把原始文本同步落盘。
        if self.log_file_path is None:
            return
        try:
            self.log_file_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_file_path.open("a", encoding="utf-8") as fp:
                fp.write(message.rstrip() + "\n")
        except OSError as exc:
            self.status_bar.showMessage(f"日志写入失败: {exc}")

    def choose_log_file(self) -> None:
        # 选择 GUI 日志落盘文件。
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "选择日志文件",
            str(self.deps.context.project_root / "hookers_gui.log"),
            "Log Files (*.log);;Text Files (*.txt);;All Files (*.*)",
        )
        if not file_path:
            return
        selected_path = Path(file_path)
        try:
            selected_path.parent.mkdir(parents=True, exist_ok=True)
            # 立即创建/校验文件，这样用户选择后就能确认“保存已真正生效”。
            selected_path.touch(exist_ok=True)
            # 把当前缓存中的日志一并补写进去，避免“只能保存之后的新日志”造成误解。
            with selected_path.open("a", encoding="utf-8") as fp:
                if selected_path.stat().st_size == 0 and self.log_records:
                    for record in self.log_records:
                        fp.write(record.message.rstrip() + "\n")
        except OSError as exc:
            QMessageBox.critical(self, "日志文件不可用", f"无法写入日志文件：{exc}")
            self.status_bar.showMessage(f"日志文件不可用: {exc}")
            return

        self.log_file_path = selected_path
        self.choose_log_file_button.setToolTip(str(self.log_file_path))
        self.append_log(f"[*] 日志文件已启用：{self.log_file_path}")

    def clear_logs(self) -> None:
        # 清空界面中的日志缓存和显示。
        #
        # 这里只清空 GUI 内存和面板，不删除已经写入磁盘的日志文件。
        if self.log_render_timer.isActive():
            self.log_render_timer.stop()
        self.log_records.clear()
        self.last_rendered_record_count = 0
        self.render_logs()
        self.status_bar.showMessage("日志显示已清空")

    def append_log(self, message: str) -> None:
        # 追加日志时：
        # 1. 先做结构化分类
        # 2. 控制内存中的最大日志条数
        # 3. 根据当前过滤器刷新右侧面板
        # 4. 如果配置了日志文件，就同步落盘
        normalized_message = message.rstrip()
        record = self.classify_log(normalized_message)
        if record.category == "js":
            normalized_message = self.normalize_js_log_message(normalized_message)
            record = self.classify_log(normalized_message)
            if self.is_effectively_empty_js_log(record.message):
                last_record = self.log_records[-1] if self.log_records else None
                if last_record and self.is_effectively_empty_js_log(last_record.message):
                    return
        self.log_records.append(record)

        # 做一层简单的内存保护，避免高频日志长时间运行后把 GUI 拖慢。
        overflow = 0
        if len(self.log_records) > self.MAX_LOG_RECORDS:
            overflow = len(self.log_records) - self.MAX_LOG_RECORDS
            del self.log_records[:overflow]

        self.persist_log(record.message)
        if self.can_incrementally_append_log(record, overflow):
            self.append_log_record_to_console(record)
            self.last_rendered_record_count = len(self.log_records)
        else:
            self.schedule_log_render()

    def set_busy(self, busy: bool, message: str | None = None) -> None:
        # 统一管理按钮禁用状态，避免多个分支各自写一套启停逻辑。
        self.refresh_apps_button.setDisabled(busy)
        # 活动会话存在时，不允许再次启动注入。
        self.start_hook_button.setDisabled(busy or self.deps.context.active_session is not None)
        self.select_script_dir_button.setDisabled(busy)
        self.reload_script_dir_button.setDisabled(busy)
        self.select_apk_scan_button.setDisabled(busy)
        self.start_apk_scan_button.setDisabled(busy or self.selected_apk_scan_path is None)
        self.stop_frida_server_button.setDisabled(busy)
        self.prepare_workspace_button.setDisabled(busy)
        self.attach_mode_radio.setDisabled(busy)
        self.spawn_mode_radio.setDisabled(busy)
        self.hook_target_input.setDisabled(busy)
        self.inspect_target_input.setDisabled(busy)
        self.generate_hook_button.setDisabled(busy)
        self.view_activity_button.setDisabled(busy)
        self.view_service_button.setDisabled(busy)
        self.restart_app_button.setDisabled(busy)
        self.object_info_button.setDisabled(busy)
        self.object_explain_button.setDisabled(busy)
        self.view_info_button.setDisabled(busy)
        self.app_combo.setDisabled(busy)
        self.stop_hook_button.setDisabled(self.deps.context.active_session is None)
        if message:
            self.current_state_label.setText(f"状态：{message}")
            self.status_bar.showMessage(message)

    def choose_apk_for_scan(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "选择 APK 文件",
            str(self.deps.context.project_root),
            "APK Files (*.apk);;All Files (*.*)",
        )
        if not selected:
            return

        selected_path = Path(selected)
        self.selected_apk_scan_path = selected_path
        self.update_apk_scan_display()
        self.append_log(f"[*] 已选择 APK 扫描目标：{selected_path}")

    def start_apk_scan(self) -> None:
        if self.selected_apk_scan_path is None:
            QMessageBox.warning(self, "未选择 APK", "请先选择一个本地 APK 文件。")
            return

        apk_path = self.selected_apk_scan_path

        def action() -> dict[str, Any]:
            self.deps.context.emit(f"[*] 开始扫描 APK：{apk_path}")
            self.deps.context.emit(
                f"[*] 使用扫描工具：{self.deps.context.local_apk_check_pack_exe}"
            )
            result = self.deps.apk_scan_service.scan_apk(apk_path)
            if result["stdout"]:
                self.deps.context.emit("[TOOL] APK 扫描输出：")
                for line in str(result["stdout"]).splitlines():
                    self.deps.context.emit(f"[TOOL] {line}")
            if result["stderr"]:
                self.deps.context.emit("[TOOL] APK 扫描错误输出：")
                for line in str(result["stderr"]).splitlines():
                    self.deps.context.emit(f"[TOOL] {line}")
            if int(result["returncode"]) != 0:
                raise RuntimeError(
                    f"APK 扫描失败，退出码：{result['returncode']}"
                )
            return result

        self.start_action(
            busy_message="正在扫描 APK",
            action=action,
            on_success=self.on_apk_scan_succeeded,
        )

    def on_apk_scan_succeeded(self, payload: Any) -> None:
        apk_path = str(payload["apk_path"])
        self.append_log(f"[+] APK 扫描完成：{apk_path}")
        self.status_bar.showMessage("APK 扫描完成")
        self.set_busy(False, "APK 扫描完成")

    def choose_script_directory(self) -> None:
        # 允许用户切换到项目外的脚本目录，方便把 GUI 当成一个通用 Frida 工作台。
        selected = QFileDialog.getExistingDirectory(
            self,
            "选择脚本文件夹",
            str(self.script_root),
        )
        if not selected:
            return
        self.script_root = Path(selected)
        self.update_script_root_display()
        self.refresh_script_list()

    def refresh_script_list(self) -> None:
        # 扫描脚本目录下的 .js 文件并刷新左侧下拉框。
        self.script_combo.clear()
        if not self.script_root.exists():
            return

        files = sorted(self.script_root.glob("*.js"), key=lambda path: path.name.lower())
        for path in files:
            self.script_combo.addItem(path.name, str(path.resolve()))

        if self.script_combo.count() > 0:
            self.script_combo.setCurrentIndex(-1)
            self.selected_script_label.setText("当前脚本：未选择")
            self.selected_script_label.setToolTip("")
        else:
            self.selected_script_label.setText("当前脚本：未选择")

    def _update_selected_script_tip(self) -> None:
        # 底部显示当前选中脚本的完整路径，方便确认自己到底注入了哪个文件。
        script_path = self.selected_script_path()
        if script_path is None:
            self.selected_script_label.setText("当前脚本：未选择")
            self.selected_script_label.setToolTip("")
            return
        self.selected_script_label.setText(f"当前脚本：{script_path.name}")
        self.selected_script_label.setToolTip(str(script_path))

    def selected_script_path(self) -> Path | None:
        # 从脚本下拉框中取回当前选中脚本的完整路径。
        value = self.script_combo.currentData()
        if value is None:
            return None
        return Path(str(value))

    def selected_package_name(self) -> str | None:
        # ComboBox 保存的是包名，显示文本只是给人看的 label。
        value = self.app_combo.currentData()
        if value is None:
            return None
        return str(value)

    def find_cached_app(self, package_name: str | None) -> Any:
        # 从最近一次枚举的应用列表里找回当前包名的基础信息。
        if not package_name:
            return None
        for app in self.deps.context.apps:
            if app.identifier == package_name:
                return app
        return None

    def refresh_app_status_panel(self, package_name: str | None = None) -> None:
        # 统一刷新左侧 App 状态摘要。
        # 这里优先展示 current_app 的实时数据，缺失时再回退到应用列表缓存。
        package_name = package_name or self.selected_package_name()
        current_app = self.deps.context.current_app
        if current_app is not None and current_app.identifier != package_name:
            current_app = None

        cached_app = self.find_cached_app(package_name)
        active_session = self.deps.context.active_session

        pid = cached_app.pid if cached_app is not None else None
        uid = None
        version = None
        mode = "未启动"

        if current_app is not None:
            pid = current_app.pid if current_app.pid is not None else pid
            uid = current_app.uid
            version = current_app.version
        if active_session is not None and self.deps.context.current_app is not None:
            if package_name == self.deps.context.current_app.identifier:
                mode = active_session.mode

        self.left_pid_uid_status_value.setText(
            f"PID: {pid if pid is not None else '-'} | UID: {uid if uid is not None else '-'}"
        )
        self.left_version_mode_status_value.setText(
            f"Version: {version or '-'} | 模式: {mode}"
        )

    def on_package_changed(self) -> None:
        # 选中包名时只切换到该包的轻量工作区壳，不再自动触发完整初始化。
        package_name = self.selected_package_name()
        self.deps.rpc_service.invalidate_persistent_session()
        if not package_name:
            self.clear_workspace_display()
            self.prepare_workspace_button.setDisabled(True)
            self.refresh_app_status_panel(None)
            return

        workspace_dir = self.deps.workspace_service.workspace_dir(package_name)
        script_dir = self.deps.workspace_service.script_dir(package_name)
        self.prepare_workspace_button.setDisabled(False)

        self.workspace_path_input.setText(str(workspace_dir))
        self.workspace_path_input.setToolTip(str(workspace_dir))

        self.script_root = script_dir if script_dir.is_dir() else self.deps.context.js_dir
        self.update_script_root_display()
        self.refresh_script_list()
        self.refresh_app_status_panel(package_name)

        self.append_log(f"[*] 当前工作目录：{workspace_dir}")
        if script_dir.is_dir():
            self.append_log(f"[*] 当前脚本目录已切换到：{script_dir}")
        else:
            self.append_log("[*] 当前工作目录尚未初始化，暂时使用项目内置 js 脚本目录。")

    def prepare_selected_workspace(self) -> None:
        # 显式初始化当前选中 App 的完整工作目录，并刷新脚本列表。
        package_name = self.selected_package_name()
        if not package_name:
            QMessageBox.warning(self, "未选择 App", "请先选择一个目标 App。")
            return
        self.start_workspace_prepare(package_name)

    def start_workspace_prepare(self, package_name: str) -> None:
        # 完整初始化工作目录，并刷新脚本列表。
        if self.workspace_thread is not None:
            return

        self.set_busy(True, "正在初始化工作目录并刷新列表")
        self.workspace_thread = QThread(self)
        self.workspace_worker = WorkspaceWorker(
            device_service=self.deps.device_service,
            workspace_service=self.deps.workspace_service,
            package_name=package_name,
        )
        self.workspace_worker.moveToThread(self.workspace_thread)

        self.workspace_thread.started.connect(self.workspace_worker.run)
        self.workspace_worker.ready.connect(self.on_workspace_ready)
        self.workspace_worker.failed.connect(self.on_worker_failed)
        self.workspace_worker.finished.connect(self.workspace_thread.quit)
        self.workspace_worker.finished.connect(self.workspace_worker.deleteLater)
        self.workspace_thread.finished.connect(self.workspace_thread.deleteLater)
        self.workspace_thread.finished.connect(self._clear_workspace_thread)
        self.workspace_thread.start()

    def _clear_workspace_thread(self) -> None:
        self.workspace_thread = None
        self.workspace_worker = None

    def on_workspace_ready(
        self,
        package_name: str,
        workspace_dir: str,
        script_dir: str,
    ) -> None:
        self.workspace_path_input.setText(workspace_dir)
        self.workspace_path_input.setToolTip(workspace_dir)
        self.script_root = Path(script_dir)
        self.update_script_root_display()
        self.refresh_script_list()
        self.refresh_app_status_panel(package_name)
        self.set_busy(False, "工作目录已初始化")
        self.append_log(f"[+] {package_name} 工作目录已完成初始化：{workspace_dir}")

    def start_device_prepare(self) -> None:
        # 启动“准备环境”后台任务。
        #
        # 这里先做一个并发保护：如果线程已经存在，就不重复启动第二个。
        if self.device_thread is not None:
            return

        self.clear_workspace_display()
        self.app_combo.blockSignals(True)
        self.app_combo.setCurrentIndex(-1)
        self.app_combo.blockSignals(False)
        self.prepare_workspace_button.setDisabled(True)
        self.refresh_app_status_panel(None)
        self.script_root = self.deps.context.js_dir
        self.update_script_root_display()
        self.refresh_script_list()
        self.append_log(f"[*] 本次准备环境使用的 Frida Server：{self.deps.context.frida_server_arm64}")
        self.append_log("[*] 开始准备设备环境并刷新 App 列表...")
        self.set_busy(True, "正在准备设备环境")

        self.device_thread = QThread(self)
        self.device_worker = DeviceWorker(device_service=self.deps.device_service)
        self.device_worker.moveToThread(self.device_thread)

        # 线程启动后执行 worker.run()，
        # 结束后由 Qt 自己回收 worker / thread 对象。
        self.device_thread.started.connect(self.device_worker.run)
        self.device_worker.apps_ready.connect(self.on_apps_ready)
        self.device_worker.failed.connect(self.on_worker_failed)
        self.device_worker.finished.connect(self.device_thread.quit)
        self.device_worker.finished.connect(self.device_worker.deleteLater)
        self.device_thread.finished.connect(self.device_thread.deleteLater)
        self.device_thread.finished.connect(self._clear_device_thread)
        self.device_thread.start()

    def _clear_device_thread(self) -> None:
        # 把 Python 层的引用清空，允许后续再次点击“准备环境”。
        self.device_thread = None
        self.device_worker = None

    def on_apps_ready(
        self,
        apps: list[dict[str, Any]],
        foreground_package: Any = None,
    ) -> None:
        # 收到后台线程返回的应用列表后，刷新下拉框。
        self.deps.rpc_service.invalidate_persistent_session()
        self.app_combo.blockSignals(True)
        self.app_combo.clear()
        for app in apps:
            name = app["name"]
            pid = app["pid"]
            identifier = app["identifier"]
            label = f"{name} ({identifier})"
            if pid is not None:
                label = f"[{pid}] {label}"
            self.app_combo.addItem(label, identifier)
        selected_index = -1
        if isinstance(foreground_package, str) and foreground_package:
            selected_index = self.app_combo.findData(foreground_package)
        self.app_combo.setCurrentIndex(selected_index)
        self.app_combo.blockSignals(False)
        if selected_index < 0:
            self.prepare_workspace_button.setDisabled(True)
            self.clear_workspace_display()
        else:
            self.on_package_changed()

        self.set_busy(False, f"已同步设备 {len(apps)} 个应用")
        self.append_log(f"[v] 已同步设备 {len(apps)} 个进程/应用")
        if apps:
            self.current_state_label.setText("状态：环境已就绪，可以开始注入")
            if selected_index >= 0 and isinstance(foreground_package, str):
                self.append_log(f"[*] 已自动选中当前前台 App：{foreground_package}")
                QMessageBox.information(
                    self,
                    "准备已完成",
                    f"准备已完成，已自动选中当前前台 App：{foreground_package}",
                )
            else:
                self.append_log("[*] 准备已完成，请选择目标 APP。")
                QMessageBox.information(self, "准备已完成", "准备已完成，请选择目标 APP。")
        else:
            self.current_state_label.setText("状态：环境已就绪，但没有枚举到应用")
            self.append_log("[!] 准备已完成，但当前没有枚举到可选择的 APK 包名。")
            QMessageBox.warning(self, "未发现应用", "准备已完成，但当前没有枚举到可选择的 APK 包名。")
            self.clear_workspace_display()

        self.refresh_app_status_panel()

    def on_worker_failed(self, message: str) -> None:
        # 统一错误出口：
        # 1. 更新状态
        # 2. 记录日志
        # 3. 弹出错误框
        self.set_busy(False, "发生错误")
        self.append_log(f"[!] {message}")
        QMessageBox.critical(self, "执行失败", message)

    def start_action(
        self,
        *,
        busy_message: str,
        action,
        on_success,
    ) -> None:
        if self.action_thread is not None:
            return

        self.set_busy(True, busy_message)
        self.action_thread = QThread(self)
        self.action_worker = ActionWorker(action)
        self.action_worker.moveToThread(self.action_thread)

        self.action_thread.started.connect(self.action_worker.run)
        self.action_worker.succeeded.connect(on_success)
        self.action_worker.failed.connect(self.on_worker_failed)
        self.action_worker.finished.connect(self.action_thread.quit)
        self.action_worker.finished.connect(self.action_worker.deleteLater)
        self.action_thread.finished.connect(self.action_thread.deleteLater)
        self.action_thread.finished.connect(self._clear_action_thread)
        self.action_thread.start()

    def _clear_action_thread(self) -> None:
        self.action_thread = None
        self.action_worker = None

    def ensure_current_app_ready(self) -> str:
        # GUI 里的分析类动作不一定要求已经开始注入，
        # 但它们都需要一个有效的 current_app 上下文。
        # 这里统一负责把包名校验、校验运行态、回填 current_app 串起来，
        # 不再主动把目标 App 拉到前台。
        package_name = self.selected_package_name()
        if not package_name:
            raise RuntimeError("请先选择一个目标 App")

        current_app = self.deps.context.current_app
        active_session = self.deps.context.active_session
        # 对 GUI 来说，如果当前包名已经有活动会话且 PID 有效，
        # 说明注入链路本身已经跑通，此时不再强制依赖 resumed-activity 检测。
        # 这样可以避免 spawn 后点击 Activity/Service 等按钮时，
        # 因 ROM/时序差异导致“前台未确认”误报。
        if (
            current_app is not None
            and active_session is not None
            and current_app.identifier == package_name
            and current_app.pid is not None
        ):
            workspace_dir = self.deps.workspace_service.workspace_dir(current_app.identifier)
            self.workspace_path_input.setText(str(workspace_dir))
            self.workspace_path_input.setToolTip(str(workspace_dir))
            self.refresh_app_status_panel(current_app.identifier)
            return current_app.identifier

        app = self.deps.device_service.ensure_app_running(package_name)
        workspace_dir = self.deps.workspace_service.workspace_dir(app.identifier)
        self.workspace_path_input.setText(str(workspace_dir))
        self.workspace_path_input.setToolTip(str(workspace_dir))
        self.refresh_app_status_panel(app.identifier)
        return app.identifier

    def format_result_text(self, result: Any) -> str:
        # RPC 返回值类型不固定，这里统一整理成可展示文本。
        if result is None:
            return "无结果"
        if isinstance(result, str):
            return result.strip() or "无结果"
        if isinstance(result, (list, tuple, dict)):
            try:
                return json.dumps(result, ensure_ascii=False, indent=2)
            except TypeError:
                pass
        return str(result)

    def show_result_dialog(self, title: str, content: str) -> None:
        # 结果窗口改成非模态，这样查看 Activity / Service 时，
        # 主窗口仍然可以继续操作，不会被 dialog.exec() 卡住。
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(860, 620)
        dialog.setModal(False)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        content_view = QTextEdit(dialog)
        content_view.setReadOnly(True)
        content_view.setPlainText(content)
        layout.addWidget(content_view, 1)

        close_button = QPushButton("关闭")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)

        self.result_windows.append(dialog)
        dialog.destroyed.connect(lambda _=None, win=dialog: self._forget_result_window(win))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _forget_result_window(self, dialog: QDialog) -> None:
        # 结果窗口关闭后，把引用从缓存里移除，避免长期积累无效对象。
        self.result_windows = [window for window in self.result_windows if window is not dialog]

    def inspect_target(self) -> str:
        # object_info / object_to_explain / view_info 共用一个输入框。
        target = self.inspect_target_input.text().strip()
        if not target:
            raise RuntimeError("请输入对象 ID、类名或 View ID")
        return target

    def start_hook(self) -> None:
        # 启动“开始注入”后台任务。
        # 第一版只支持单会话，所以有 hook_thread 时直接忽略重复点击。
        if self.hook_thread is not None:
            return

        package_name = self.selected_package_name()
        if not package_name:
            QMessageBox.warning(self, "未选择 App", "请先准备环境并选择一个目标 App。")
            return

        script_path = self.selected_script_path()
        if script_path is None:
            QMessageBox.warning(self, "未选择脚本", "请先在左侧选择一个 .js 脚本。")
            return

        self.append_log(f"[i] 目标 App: {package_name}")
        self.append_log(f"[i] 已选中脚本: {script_path.name}")
        self.set_busy(True, "正在启动注入")

        self.hook_thread = QThread(self)
        self.hook_worker = HookWorker(
            device_service=self.deps.device_service,
            session_service=self.deps.session_service,
            workspace_service=self.deps.workspace_service,
            package_name=package_name,
            script_path=script_path,
            use_spawn=self.spawn_mode_radio.isChecked(),
            ensure_workspace=False,
        )
        self.hook_worker.moveToThread(self.hook_thread)

        # 这条链路和设备准备类似，只是这里的 worker 会触发 attach/spawn。
        self.hook_thread.started.connect(self.hook_worker.run)
        self.hook_worker.started.connect(self.on_hook_started)
        self.hook_worker.failed.connect(self.on_worker_failed)
        self.hook_worker.finished.connect(self.hook_thread.quit)
        self.hook_worker.finished.connect(self.hook_worker.deleteLater)
        self.hook_thread.finished.connect(self.hook_thread.deleteLater)
        self.hook_thread.finished.connect(self._clear_hook_thread)
        self.hook_thread.start()

    def _clear_hook_thread(self) -> None:
        # Hook 启动线程结束后，允许再次发起新的注入任务。
        self.hook_thread = None
        self.hook_worker = None

    def on_hook_started(self, mode: str, package_name: str, script_name: str) -> None:
        # 注入成功后，把界面切到“运行中”状态。
        # 由于 active_session 已经保存在 SessionService / context 中，
        # 此时线程虽然结束了，但 Hook 会话本身仍然存活。
        self.set_busy(False, f"{mode} 已启动")
        self.start_hook_button.setDisabled(True)
        self.stop_hook_button.setDisabled(False)
        self.current_state_label.setText(
            f"状态：{mode} 模式运行中 | App: {package_name} | 脚本: {script_name}"
        )
        self.append_log(f"[+] 已启动 {mode} 注入：{package_name} <- {script_name}")

        self.refresh_app_status_panel(package_name)

    def stop_hook(self) -> None:
        if self.action_thread is not None:
            return

        def action() -> None:
            self.deps.session_service.stop_active_session()

        self.start_action(
            busy_message="Stopping hook",
            action=action,
            on_success=self.on_hook_stopped,
        )

    def on_hook_stopped(self, _payload: Any) -> None:
        self.deps.rpc_service.invalidate_persistent_session()
        self.current_state_label.setText("状态：会话已停止")
        self.status_bar.showMessage("当前 Hook 已停止")
        self.append_log("[*] 当前 Hook 已停止")
        self.start_hook_button.setDisabled(False)
        self.stop_hook_button.setDisabled(True)
        self.refresh_app_status_panel()
        self.set_busy(False, "Ready")

    def stop_frida_server(self) -> None:
        if self.action_thread is not None:
            return

        def action() -> None:
            self.deps.rpc_service.invalidate_persistent_session()
            if self.deps.context.active_session is not None:
                self.deps.session_service.stop_active_session()
            self.deps.device_service.stop_frida_server()

        self.start_action(
            busy_message="正在停止 Frida Server",
            action=action,
            on_success=self.on_frida_server_stopped,
        )

    def on_frida_server_stopped(self, _payload: Any) -> None:
        self.current_state_label.setText("状态：Frida Server 已停止")
        self.status_bar.showMessage("Frida Server 已停止")
        self.append_log("[*] Frida Server 已停止")
        self.start_hook_button.setDisabled(False)
        self.stop_hook_button.setDisabled(True)
        self.refresh_app_status_panel()
        self.set_busy(False, "Ready")

    def generate_hook_script(self) -> None:
        hook_target = self.hook_target_input.text().strip()
        if not hook_target:
            QMessageBox.warning(self, "Missing Target", "Enter class or class:method.")
            return

        def action() -> dict[str, Any]:
            package_name = self.ensure_current_app_ready()
            script_path = self.deps.rpc_service.generate_hook_script(hook_target)
            return {"package_name": package_name, "script_path": str(script_path)}

        self.start_action(
            busy_message="Generating hook script",
            action=action,
            on_success=self.on_hook_script_generated,
        )

    def on_hook_script_generated(self, payload: Any) -> None:
        package_name = str(payload["package_name"])
        script_path = Path(str(payload["script_path"]))
        self.append_log(f"[TOOL] Generated hook script: {script_path}")
        self.script_root = self.deps.workspace_service.script_dir(package_name)
        self.update_script_root_display()
        self.refresh_script_list()

        target_resolved = str(script_path.resolve())
        for index in range(self.script_combo.count()):
            if self.script_combo.itemData(index) == target_resolved:
                self.script_combo.setCurrentIndex(index)
                break

        self.set_busy(False, "Ready")
        self.status_bar.showMessage(f"Hook script generated: {script_path.name}")
        QMessageBox.information(self, "Generated", f"Script saved to:\n{script_path}")

    def show_activities(self) -> None:
        def action() -> dict[str, Any]:
            package_name = self.ensure_current_app_ready()
            result = self.deps.rpc_service.activitys()
            return {"package_name": package_name, "result": result}

        self.start_action(
            busy_message="Loading activities",
            action=action,
            on_success=self.on_activities_ready,
        )

    def on_activities_ready(self, payload: Any) -> None:
        package_name = str(payload["package_name"])
        self.append_log(f"[TOOL] Loaded activities for {package_name}")
        self.show_result_dialog("Activity List", self.format_result_text(payload["result"]))
        self.set_busy(False, "Ready")

    def show_services(self) -> None:
        def action() -> dict[str, Any]:
            package_name = self.ensure_current_app_ready()
            result = self.deps.rpc_service.services()
            return {"package_name": package_name, "result": result}

        self.start_action(
            busy_message="Loading services",
            action=action,
            on_success=self.on_services_ready,
        )

    def on_services_ready(self, payload: Any) -> None:
        package_name = str(payload["package_name"])
        self.append_log(f"[TOOL] Loaded services for {package_name}")
        self.show_result_dialog("Service List", self.format_result_text(payload["result"]))
        self.set_busy(False, "Ready")

    def show_object_info(self) -> None:
        def action() -> dict[str, Any]:
            package_name = self.ensure_current_app_ready()
            target = self.inspect_target()
            result = self.deps.rpc_service.object_info(target)
            return {"package_name": package_name, "target": target, "result": result}

        self.start_action(
            busy_message="Loading object info",
            action=action,
            on_success=self.on_object_info_ready,
        )

    def on_object_info_ready(self, payload: Any) -> None:
        package_name = str(payload["package_name"])
        target = str(payload["target"])
        self.append_log(f"[TOOL] Loaded object info for {package_name}: {target}")
        self.show_result_dialog(
            f"Object Info - {target}",
            self.format_result_text(payload["result"]),
        )
        self.set_busy(False, "Ready")

    def show_object_explain(self) -> None:
        def action() -> dict[str, Any]:
            package_name = self.ensure_current_app_ready()
            target = self.inspect_target()
            result = self.deps.rpc_service.object_to_explain(target)
            return {"package_name": package_name, "target": target, "result": result}

        self.start_action(
            busy_message="Explaining object",
            action=action,
            on_success=self.on_object_explain_ready,
        )

    def on_object_explain_ready(self, payload: Any) -> None:
        package_name = str(payload["package_name"])
        target = str(payload["target"])
        self.append_log(f"[TOOL] Explained object for {package_name}: {target}")
        self.show_result_dialog(
            f"Object Explain - {target}",
            self.format_result_text(payload["result"]),
        )
        self.set_busy(False, "Ready")

    def show_view_info(self) -> None:
        def action() -> dict[str, Any]:
            package_name = self.ensure_current_app_ready()
            target = self.inspect_target()
            result = self.deps.rpc_service.view_info(target)
            return {"package_name": package_name, "target": target, "result": result}

        self.start_action(
            busy_message="Loading view info",
            action=action,
            on_success=self.on_view_info_ready,
        )

    def on_view_info_ready(self, payload: Any) -> None:
        package_name = str(payload["package_name"])
        target = str(payload["target"])
        self.append_log(f"[TOOL] Loaded view info for {package_name}: {target}")
        self.show_result_dialog(
            f"View Info - {target}",
            self.format_result_text(payload["result"]),
        )
        self.set_busy(False, "Ready")

    def restart_current_app(self) -> None:
        def action() -> dict[str, Any]:
            package_name = self.ensure_current_app_ready()
            self.deps.rpc_service.invalidate_persistent_session()
            if self.deps.context.active_session is not None:
                self.deps.session_service.stop_active_session()
            self.deps.session_service.restart_current_app()
            apps = self.deps.device_service.refresh_applications()
            return {
                "package_name": package_name,
                "apps": [
                    {"name": app.name, "identifier": app.identifier, "pid": app.pid}
                    for app in apps
                ],
            }

        self.start_action(
            busy_message="Restarting app",
            action=action,
            on_success=self.on_restart_current_app_finished,
        )

    def on_restart_current_app_finished(self, payload: Any) -> None:
        self.deps.rpc_service.invalidate_persistent_session()
        package_name = str(payload["package_name"])
        self.append_log(f"[TOOL] Restarted app: {package_name}")
        self.on_apps_ready(payload["apps"])
        current_index = self.app_combo.findData(package_name)
        if current_index >= 0:
            self.app_combo.setCurrentIndex(current_index)
        self.set_busy(False, "Ready")

    def closeEvent(self, event) -> None:  # noqa: N802
        # 关闭窗口时尽量做一次温和清理：
        # 1. 停止当前 Hook
        # 2. 不再清理设备侧 rusda 文件，避免某些设备因此崩溃/重启
        # 3. 不强杀线程，让 Qt 走正常收尾流程
        try:
            self.deps.rpc_service.invalidate_persistent_session()
        except Exception:
            pass
        try:
            self.deps.session_service.stop_active_session()
        except Exception:
            pass
        super().closeEvent(event)
