from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, Signal

from PySide6.QtWidgets import (
    QApplication,
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
    QMainWindow,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QInputDialog,
    QVBoxLayout,
    QWidget,
)

from .composition import build_main_window_controllers, wire_main_window_controller_signals
from .debug_tools_dialog import DebugToolsDialog
from .widgets import NoWheelComboBox
from .controller_types import (
    ApkScanServiceLike,
    ContextLike,
    DeviceServiceLike,
    RpcServiceLike,
    SessionServiceLike,
    WorkspaceServiceLike,
)
from .quick_hook_actions import (
    ANALYSIS_SCENARIO_PROFILES,
    QUICK_HOOK_ACTIONS,
    QUICK_HOOK_ACTIONS_BY_KEY,
    QUICK_HOOK_BUTTON_ATTRS,
    QUICK_HOOK_GROUPS,
)
from . import ui_messages
from .cli_terminal_view import CliTerminalView
from .display_builders import (
    build_analysis_scenario_tooltip_text,
    build_session_status_payload,
    build_script_selection_lines,
    join_lines,
)
from core.workspace_service import ScriptSourceInfo


@dataclass
class MainWindowDependencies:
    # GUI 依赖注入容器。
    # 第七刀后这里不再用松散类型，而是显式描述 GUI 实际依赖的 service/context 边界。
    device_service: DeviceServiceLike
    session_service: SessionServiceLike
    workspace_service: WorkspaceServiceLike
    rpc_service: RpcServiceLike
    apk_scan_service: ApkScanServiceLike
    context: ContextLike

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

    def __init__(self, deps: MainWindowDependencies) -> None:
        super().__init__()
        self.deps = deps
        self.log_focus_mode = False
        self.saved_splitter_sizes = [340, 420, 920]
        self.quick_hook_group_widgets: dict[str, QWidget] = {}
        self.quick_hook_group_titles: list[str] = []
        self.analysis_scenario_buttons: list[QPushButton] = []

        # GUI 层接管日志出口：所有 service 的日志最终都通过这个信号回到主线程显示。
        self.deps.context.log_handler = self._handle_log_from_worker
        self.deps.context.session_event_handler = self._handle_session_event_from_worker

        self.script_root = self.deps.context.hookers_js_dir

        self.setWindowTitle("Frida-Hookers GUI 工作台")
        self.resize(1500, 920)
        self._build_ui()
        self.controllers = build_main_window_controllers(self, self.deps)
        self.log_panel_controller = self.controllers.log_panel
        self.error_presenter = self.controllers.error_presenter
        self.app_workflow_controller = self.controllers.app_workflow
        self.hook_runtime_controller = self.controllers.hook_runtime
        self.rpc_tool_controller = self.controllers.rpc_tools
        self.apk_scan_controller = self.controllers.apk_scan
        self.terminal_console_controller = self.controllers.terminal_console
        wire_main_window_controller_signals(self, self.controllers)
        self._apply_styles()
        self.update_script_root_display()
        self.refresh_script_list()
        self.apk_scan_controller.update_apk_scan_display()
        self.app_workflow_controller.refresh_app_status_panel()

    def _build_ui(self) -> None:
        # 主体布局采用左右三栏：
        # 左：脚本选择
        # 中：App/模式/动作控制
        # 右：实时日志
        root = QWidget(self)
        self.setCentralWidget(root)

        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

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
        self.status_bar.showMessage(ui_messages.GUI_READY_HINT)

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

    def _apply_button_density(self, *buttons: QPushButton) -> None:
        for button in buttons:
            # 下限需不小于 QSS padding(12px 上下) + 字体高度撑出的 sizeHint(约 38px)，
            # 否则在可滚动弹窗等空间受压场景下按钮会被压到下限导致文字上下被裁。
            button.setMinimumHeight(40)

    def _build_section_divider(self, title: str) -> QWidget:
        # 给中间工具区加轻量分组分隔，让不同功能块更容易扫视。
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 4, 0, 4)
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

        self.script_root_source_label = QLabel(ui_messages.SCRIPT_ROOT_SOURCE_LABEL.format(value=ui_messages.SCRIPT_ROOT_SOURCE_BUILTIN))
        self.script_root_source_label.setObjectName("mutedLabel")
        self.script_root_source_label.setWordWrap(True)
        layout.addWidget(self.script_root_source_label)

        self.script_root_hint_label = QLabel(ui_messages.SCRIPT_SELECTION_ROOT_HINT)
        self.script_root_hint_label.setObjectName("mutedLabel")
        self.script_root_hint_label.setWordWrap(True)
        self.script_root_hint_label.hide()
        layout.addWidget(self.script_root_hint_label)

        self.script_dir_input.setToolTip(ui_messages.SCRIPT_SELECTION_ROOT_HINT)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self.select_script_dir_button = QPushButton("选择脚本文件夹")
        self.select_script_dir_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.select_script_dir_button.clicked.connect(self.choose_script_directory)
        self._apply_button_density(self.select_script_dir_button)
        button_row.addWidget(self.select_script_dir_button)

        self.reload_script_dir_button = QPushButton("刷新脚本")
        self.reload_script_dir_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.reload_script_dir_button.clicked.connect(self.refresh_script_list)
        self._apply_button_density(self.reload_script_dir_button)
        button_row.addWidget(self.reload_script_dir_button)
        layout.addLayout(button_row)

        selected_script_title = QLabel(ui_messages.SCRIPT_SELECTION_SUMMARY_TITLE)
        selected_script_title.setObjectName("mutedLabel")
        layout.addWidget(selected_script_title)

        self.selected_script_label = QLabel(ui_messages.SCRIPT_SELECTION_EMPTY)
        self.selected_script_label.setWordWrap(True)
        self.selected_script_label.setMinimumHeight(84)
        self.selected_script_label.setObjectName("stateLabel")
        layout.addWidget(self.selected_script_label)

        script_combo_label = QLabel("脚本文件选择")
        script_combo_label.setObjectName("mutedLabel")
        layout.addWidget(script_combo_label)

        self.script_combo = NoWheelComboBox()
        self.script_combo.setEditable(False)
        self.script_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.script_combo.currentIndexChanged.connect(self._update_selected_script_tip)
        layout.addWidget(self._with_dropdown_marker(self.script_combo))

        script_filter_label = QLabel(ui_messages.SCRIPT_FILTER_LABEL)
        script_filter_label.setObjectName("mutedLabel")
        layout.addWidget(script_filter_label)

        self.script_filter_combo = NoWheelComboBox()
        self.script_filter_combo.addItems(
            [
                ui_messages.SCRIPT_FILTER_ALL,
                ui_messages.SCRIPT_FILTER_RECENT,
            ]
        )
        self.script_filter_combo.currentIndexChanged.connect(self.refresh_script_list)
        layout.addWidget(self._with_dropdown_marker(self.script_filter_combo))

        script_search_label = QLabel(ui_messages.SCRIPT_SEARCH_LABEL)
        script_search_label.setObjectName("mutedLabel")
        layout.addWidget(script_search_label)

        self.script_search_input = QLineEdit()
        self.script_search_input.setPlaceholderText(ui_messages.SCRIPT_SEARCH_PLACEHOLDER)
        self.script_search_input.textChanged.connect(self.refresh_script_list)
        layout.addWidget(self.script_search_input)

        self.script_list_hint_label = QLabel(ui_messages.SCRIPT_LIST_EMPTY_HINT)
        self.script_list_hint_label.setObjectName("mutedLabel")
        self.script_list_hint_label.setWordWrap(True)
        self.script_list_hint_label.hide()
        layout.addWidget(self.script_list_hint_label)

        session_status_title = QLabel(ui_messages.SESSION_STATUS_TITLE)
        session_status_title.setObjectName("panelTitle")
        layout.addWidget(session_status_title)

        session_status_card = QWidget()
        session_status_card.setObjectName("sessionStatusCard")
        session_status_card_layout = QVBoxLayout(session_status_card)
        session_status_card_layout.setContentsMargins(12, 12, 12, 12)
        session_status_card_layout.setSpacing(8)
        layout.addWidget(session_status_card)

        self.session_status_phase_label = QLabel(ui_messages.SESSION_STATUS_PHASE_IDLE)
        self.session_status_phase_label.setObjectName("sessionStatusBadgeIdle")
        self.session_status_phase_label.setAlignment(Qt.AlignCenter)
        session_status_card_layout.addWidget(self.session_status_phase_label)

        self.session_status_summary_label = QLabel(ui_messages.SESSION_STATUS_SUMMARY_TEMPLATE.format(summary=ui_messages.SESSION_STATUS_SUMMARY_IDLE))
        self.session_status_summary_label.setObjectName("sessionStatusSummary")
        self.session_status_summary_label.setWordWrap(True)
        session_status_card_layout.addWidget(self.session_status_summary_label)

        self.session_status_action_label = QLabel(ui_messages.SESSION_STATUS_ACTION_IDLE)
        self.session_status_action_label.setObjectName("sessionStatusAction")
        self.session_status_action_label.setWordWrap(True)
        session_status_card_layout.addWidget(self.session_status_action_label)

        self.session_status_mode_label = QLabel(ui_messages.SESSION_STATUS_MODE_EMPTY)
        self.session_status_target_label = QLabel(ui_messages.SESSION_STATUS_TARGET_EMPTY)
        self.session_status_script_label = QLabel(ui_messages.SESSION_STATUS_SCRIPT_EMPTY)
        self.session_status_detail_label = QLabel(ui_messages.SESSION_STATUS_DETAIL_EMPTY)
        for label in (
            self.session_status_mode_label,
            self.session_status_target_label,
            self.session_status_script_label,
            self.session_status_detail_label,
        ):
            label.setObjectName("statusValue")
            label.setWordWrap(True)
            session_status_card_layout.addWidget(label)

        app_status_title = QLabel("App 状态")
        app_status_title.setObjectName("panelTitle")
        layout.addWidget(app_status_title)

        self.left_pid_uid_status_value = QLabel(
            ui_messages.PID_UID_TEXT.format(pid="-", uid="-")
        )
        self.left_pid_uid_status_value.setWordWrap(True)
        self.left_pid_uid_status_value.setObjectName("statusValue")
        layout.addWidget(self.left_pid_uid_status_value)

        self.left_version_mode_status_value = QLabel(
            ui_messages.VERSION_MODE_TEXT.format(
                version="-",
                mode=ui_messages.MODE_NOT_RUNNING,
            )
        )
        self.left_version_mode_status_value.setWordWrap(True)
        self.left_version_mode_status_value.setObjectName("statusValue")
        layout.addWidget(self.left_version_mode_status_value)

        frida_tool_title = QLabel("Frida 工具")
        frida_tool_title.setObjectName("panelTitle")
        layout.addWidget(frida_tool_title)

        self.stop_frida_server_button = QPushButton("停止 Frida Server")
        self.stop_frida_server_button.setObjectName("compactButton")
        self.stop_frida_server_button.setToolTip("需要手动关闭设备侧 Frida 服务时使用。它不属于默认注入流程。")
        self._apply_button_density(self.stop_frida_server_button)
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
        self._apply_button_density(self.select_apk_scan_button)
        apk_scan_button_row.addWidget(self.select_apk_scan_button)

        self.start_apk_scan_button = QPushButton("开始扫描")
        self.start_apk_scan_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.start_apk_scan_button.setDisabled(True)
        self._apply_button_density(self.start_apk_scan_button)
        apk_scan_button_row.addWidget(self.start_apk_scan_button)

        layout.addLayout(apk_scan_button_row)

        self.apk_scan_status_label = QLabel(ui_messages.APK_SCAN_EMPTY_STATUS)
        self.apk_scan_status_label.setWordWrap(True)
        self.apk_scan_status_label.setObjectName("statusValue")
        layout.addWidget(self.apk_scan_status_label)

        layout.addStretch(1)
        return panel

    def _build_control_panel(self) -> QWidget:
        # 中间控制区。
        # 当前优先把主路径明确为：准备环境 -> 选择 App -> 选择脚本/模式 -> 启动与会话控制。
        panel = QWidget()
        panel.setObjectName("controlPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel("控制台")
        title.setObjectName("panelTitle")
        layout.addWidget(title)

        self.refresh_apps_button = QPushButton("1. 准备环境并刷新 App")
        self.refresh_apps_button.setObjectName("primaryButton")
        self._apply_button_density(self.refresh_apps_button)
        layout.addWidget(self.refresh_apps_button)

        app_step_container = QWidget()
        app_step_layout = QVBoxLayout(app_step_container)
        app_step_layout.setContentsMargins(0, 0, 0, 0)
        app_step_layout.setSpacing(8)
        layout.addWidget(app_step_container)

        app_step_layout.addWidget(self._build_section_divider("2. 选择目标 App"))

        app_form = QGridLayout()
        app_form.setHorizontalSpacing(10)
        app_form.setVerticalSpacing(10)
        app_step_layout.addLayout(app_form)

        app_label = QLabel("目标 App")
        self.app_combo = NoWheelComboBox()
        self.app_combo.setEditable(False)
        self.app_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        app_form.addWidget(app_label, 0, 0)
        app_form.addWidget(self._with_dropdown_marker(self.app_combo), 0, 1)

        workspace_label = QLabel("工作目录")
        self.workspace_path_input = QLineEdit()
        self.workspace_path_input.setReadOnly(True)
        self.workspace_path_input.setPlaceholderText(
            "选择 App 后显示目标工作目录；点击初始化后才会真正创建和补齐文件"
        )
        app_form.addWidget(workspace_label, 1, 0)
        app_form.addWidget(self.workspace_path_input, 1, 1)

        self.prepare_workspace_button = QPushButton("初始化工作目录并刷新列表")
        self.prepare_workspace_button.setToolTip("只有需要工作区脚本、副本或参数化 runtime 时，再初始化工作目录。")
        self.prepare_workspace_button.setObjectName("secondaryButton")
        self.prepare_workspace_button.setDisabled(True)
        self._apply_button_density(self.prepare_workspace_button)
        app_step_layout.addWidget(self.prepare_workspace_button)

        script_step_container = QWidget()
        script_step_layout = QVBoxLayout(script_step_container)
        script_step_layout.setContentsMargins(0, 0, 0, 0)
        script_step_layout.setSpacing(8)
        layout.addWidget(script_step_container)

        script_step_layout.addWidget(self._build_section_divider("3. 选择脚本与模式"))

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
        script_step_layout.addWidget(mode_label)
        script_step_layout.addLayout(mode_row)

        self.mode_badge_label = QLabel(ui_messages.ATTACH_MODE_BADGE)
        self.mode_badge_label.setObjectName("modeBadge")
        self.mode_badge_label.setAlignment(Qt.AlignCenter)
        script_step_layout.addWidget(self.mode_badge_label)
        self.attach_mode_radio.toggled.connect(self._update_mode_badge)
        self.spawn_mode_radio.toggled.connect(self._update_mode_badge)
        self._update_mode_badge()

        self.hook_target_input = QLineEdit()
        self.hook_target_input.setPlaceholderText(ui_messages.HOOK_TARGET_PLACEHOLDER)
        self.generate_hook_button = QPushButton("生成 Hook 脚本")
        self.advanced_frida_launch_button = QPushButton(f"3A. {ui_messages.ADVANCED_FRIDA_BUTTON}")
        self.advanced_frida_launch_button.setObjectName("secondaryButton")

        script_generation_group = QWidget()
        script_generation_layout = QVBoxLayout(script_generation_group)
        script_generation_layout.setContentsMargins(0, 0, 0, 0)
        script_generation_layout.setSpacing(8)
        script_step_layout.addWidget(script_generation_group)
        script_generation_layout.addWidget(self._build_section_divider("脚本生成 / 高级启动"))
        self.generate_hook_button.setToolTip(ui_messages.HOOK_TARGET_FLOW_HINT)
        self.advanced_frida_launch_button.setToolTip(ui_messages.ADVANCED_FRIDA_FLOW_HINT)
        script_generation_layout.addWidget(self.hook_target_input)

        script_button_row = QGridLayout()
        script_button_row.setHorizontalSpacing(10)
        script_button_row.setVerticalSpacing(10)
        script_generation_layout.addLayout(script_button_row)
        self._apply_button_density(self.generate_hook_button, self.advanced_frida_launch_button)
        script_button_row.addWidget(self.generate_hook_button, 0, 0)
        script_button_row.addWidget(self.advanced_frida_launch_button, 0, 1)

        launch_step_container = QWidget()
        launch_step_layout = QVBoxLayout(launch_step_container)
        launch_step_layout.setContentsMargins(0, 0, 0, 0)
        launch_step_layout.setSpacing(8)
        layout.addWidget(launch_step_container)

        launch_step_layout.addWidget(self._build_section_divider("4. 启动与会话控制"))

        launch_actions_row = QHBoxLayout()
        launch_actions_row.setSpacing(10)
        self.start_hook_button = QPushButton("开始注入")
        self.start_hook_button.setObjectName("primaryButton")
        self._apply_button_density(self.start_hook_button)
        launch_actions_row.addWidget(self.start_hook_button, 1)

        self.stop_hook_button = QPushButton("停止 Hook")
        self.stop_hook_button.setObjectName("dangerButton")
        self.stop_hook_button.setDisabled(True)
        self._apply_button_density(self.stop_hook_button)
        launch_actions_row.addWidget(self.stop_hook_button, 1)

        launch_step_layout.addLayout(launch_actions_row)

        self.current_state_label = QLabel(ui_messages.state_text(ui_messages.READY))
        self.current_state_label.setObjectName("stateLabel")
        self.current_state_label.setWordWrap(True)
        self.current_state_label.setMinimumHeight(54)
        launch_step_layout.addWidget(self.current_state_label)
        self.start_hook_button.setToolTip(ui_messages.LAUNCH_STEP_HINT_IDLE)
        self.stop_hook_button.setToolTip(ui_messages.LAUNCH_STEP_HINT_RUNNING)

        self.error_recovery_banner_label = QLabel(ui_messages.ERROR_RECOVERY_EMPTY)
        self.error_recovery_banner_label.setObjectName("errorRecoveryBanner")
        self.error_recovery_banner_label.setWordWrap(True)
        self.error_recovery_banner_label.hide()
        launch_step_layout.addWidget(self.error_recovery_banner_label)

        self.debug_tools_dialog = DebugToolsDialog(self)
        debug_tools_layout = self.debug_tools_dialog.content_layout

        self.debug_tools_button = QPushButton("调试与分析工具")
        self.debug_tools_button.setObjectName("primaryButton")
        self._apply_button_density(self.debug_tools_button)
        self.debug_tools_button.clicked.connect(self._open_debug_tools_dialog)
        layout.addWidget(self.debug_tools_button)

        self.view_activity_button = QPushButton("查看 Activity")
        self.view_service_button = QPushButton("查看 Service")
        self._apply_button_density(self.view_activity_button, self.view_service_button)

        for action in QUICK_HOOK_ACTIONS:
            button = QPushButton(action.button_label)
            if action.tooltip:
                button.setToolTip(action.tooltip)
            self._apply_button_density(button)
            setattr(self, action.button_attr, button)

        self.restart_app_button = QPushButton("重启 App（必要时）")
        self.restart_app_button.setObjectName("compactButton")
        self.restart_app_button.setToolTip("需要重新拉起目标 App 时使用。通常优先停止 Hook 或重新开始注入。")
        self._apply_button_density(self.restart_app_button)

        self.inspect_target_input = QLineEdit()
        self.inspect_target_input.setPlaceholderText("输入对象 ID、类名或 View ID")
        self.object_info_button = QPushButton("对象信息")
        self.object_explain_button = QPushButton("对象解释")
        self.view_info_button = QPushButton("View 信息")
        self._apply_button_density(self.object_info_button, self.object_explain_button, self.view_info_button)

        inspect_group = QWidget()
        inspect_group_layout = QVBoxLayout(inspect_group)
        inspect_group_layout.setContentsMargins(0, 0, 0, 0)
        inspect_group_layout.setSpacing(8)
        debug_tools_layout.addWidget(inspect_group)

        inspect_group_layout.addWidget(self._build_section_divider("对象分析"))
        inspect_group_layout.addWidget(self.inspect_target_input)

        inspect_button_row = QGridLayout()
        inspect_button_row.setHorizontalSpacing(10)
        inspect_button_row.setVerticalSpacing(10)
        inspect_group_layout.addLayout(inspect_button_row)
        inspect_button_row.addWidget(self.object_info_button, 0, 0)
        inspect_button_row.addWidget(self.object_explain_button, 0, 1)
        inspect_button_row.addWidget(self.view_info_button, 1, 0, 1, 2)

        debug_tools_layout.addWidget(self._build_section_divider("页面查询"))
        no_input_group = QWidget()
        no_input_layout = QGridLayout(no_input_group)
        no_input_layout.setContentsMargins(0, 0, 0, 0)
        no_input_layout.setHorizontalSpacing(10)
        no_input_layout.setVerticalSpacing(10)
        debug_tools_layout.addWidget(no_input_group)
        no_input_layout.addWidget(self.view_activity_button, 0, 0)
        no_input_layout.addWidget(self.view_service_button, 0, 1)

        grouped_actions_container = QWidget()
        grouped_actions_layout = QVBoxLayout(grouped_actions_container)
        grouped_actions_layout.setContentsMargins(0, 8, 0, 0)
        grouped_actions_layout.setSpacing(10)
        no_input_layout.addWidget(grouped_actions_container, 1, 0, 1, 2)
        self.quick_hook_group_widgets.clear()
        self.quick_hook_group_titles = [group.title for group in QUICK_HOOK_GROUPS]
        for group in QUICK_HOOK_GROUPS:
            grouped_actions_layout.addWidget(self._build_quick_hook_group(group.key, group.title, group.action_keys))

        grouped_actions_layout.addWidget(self._build_analysis_scenario_group())
        no_input_layout.addWidget(self.restart_app_button, 2, 0, 1, 2)
        debug_tools_layout.addStretch(1)

        layout.addStretch(1)
        return panel

    def _build_quick_hook_group(
        self,
        group_key: str,
        title: str,
        action_keys: tuple[str, ...],
    ) -> QWidget:
        container = QWidget()
        container.setObjectName(f"quickHookGroup_{group_key}")
        self.quick_hook_group_widgets[group_key] = container

        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._build_section_divider(title))

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        layout.addLayout(grid)

        for index, action_key in enumerate(action_keys):
            action = QUICK_HOOK_ACTIONS_BY_KEY[action_key]
            grid.addWidget(getattr(self, action.button_attr), index // 2, index % 2)
        return container

    def _build_analysis_scenario_group(self) -> QWidget:
        container = QWidget()
        container.setObjectName("analysisScenarioGroup")

        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._build_section_divider(ui_messages.ANALYSIS_SCENARIO_GROUP_TITLE))

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        layout.addLayout(grid)

        for index, profile in enumerate(ANALYSIS_SCENARIO_PROFILES):
            button = QPushButton(profile.button_label)
            button.setToolTip(self._analysis_scenario_tooltip(profile))
            button.setObjectName("secondaryButton")
            self._apply_button_density(button)
            setattr(self, profile.button_attr, button)
            self.analysis_scenario_buttons.append(button)
            grid.addWidget(button, index // 2, index % 2)
        return container

    def _build_log_panel(self) -> QWidget:
        # 右侧日志区。
        # 所有 service 最终都走 context.log_handler -> log_emitted -> append_log
        # 这条链路，把后台工作线程里的文本安全地送回主线程显示。
        panel = QWidget()
        panel.setObjectName("logPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)

        title = QLabel("运行日志")
        title.setObjectName("panelTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)

        self.terminal_cli_mode_button = QPushButton(ui_messages.CLI_MODE_ENTER_BUTTON)
        self.terminal_cli_mode_button.setObjectName("compactButton")
        title_row.addWidget(self.terminal_cli_mode_button, 0, Qt.AlignTop)
        layout.addLayout(title_row)

        tools_row = QHBoxLayout()
        self.log_filter_combo = NoWheelComboBox()
        self.log_filter_combo.addItems(
            [
                ui_messages.LOG_FILTER_ALL,
                ui_messages.LOG_FILTER_JS,
                ui_messages.LOG_FILTER_ERRORS,
                ui_messages.LOG_FILTER_TOOL,
            ]
        )
        tools_row.addWidget(self._with_dropdown_marker(self.log_filter_combo), 1)

        self.choose_log_file_button = QPushButton("日志文件")
        self.choose_log_file_button.setObjectName("compactButton")
        self.choose_log_file_button.setToolTip("需要保存 GUI 日志到文件时使用。当前尚未启用日志文件保存。")
        tools_row.addWidget(self.choose_log_file_button)

        self.clear_log_button = QPushButton("清空")
        self.clear_log_button.setObjectName("compactButton")
        self.clear_log_button.setToolTip("需要清空当前界面日志显示时使用。不会删除已保存的日志文件。")
        tools_row.addWidget(self.clear_log_button)

        self.toggle_log_focus_button = QPushButton(ui_messages.FOCUS_LOG_ENABLE_BUTTON)
        self.toggle_log_focus_button.setObjectName("compactButton")
        self.toggle_log_focus_button.setToolTip(ui_messages.FOCUS_LOG_ENABLE_TOOLTIP)
        self.toggle_log_focus_button.clicked.connect(self.toggle_log_focus_mode)
        tools_row.addWidget(self.toggle_log_focus_button)
        layout.addLayout(tools_row)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)

        self.log_search_input = QLineEdit()
        self.log_search_input.setPlaceholderText("搜索终端信息")
        search_row.addWidget(self.log_search_input, 1)

        self.prev_log_match_button = QPushButton("上一条")
        self.prev_log_match_button.setObjectName("compactButton")
        self.prev_log_match_button.setDisabled(True)
        search_row.addWidget(self.prev_log_match_button)

        self.next_log_match_button = QPushButton("下一条")
        self.next_log_match_button.setObjectName("compactButton")
        self.next_log_match_button.setDisabled(True)
        search_row.addWidget(self.next_log_match_button)

        self.clear_log_search_button = QPushButton("清空搜索")
        self.clear_log_search_button.setObjectName("compactButton")
        search_row.addWidget(self.clear_log_search_button)
        layout.addLayout(search_row)

        status_row = QHBoxLayout()
        status_row.setSpacing(12)

        self.log_search_status_label = QLabel(
            ui_messages.LOG_SEARCH_IDLE.format(scope=ui_messages.LOG_FILTER_ALL)
        )
        self.log_search_status_label.setObjectName("statusValue")
        status_row.addWidget(self.log_search_status_label, 1)

        self.log_search_case_checkbox = QCheckBox("区分大小写")
        status_row.addWidget(self.log_search_case_checkbox)

        self.log_search_regex_checkbox = QCheckBox("正则搜索")
        status_row.addWidget(self.log_search_regex_checkbox)

        self.log_search_matches_only_checkbox = QCheckBox("仅显示匹配项")
        status_row.addWidget(self.log_search_matches_only_checkbox)
        layout.addLayout(status_row)

        layout.addWidget(self._build_section_divider(ui_messages.TERMINAL_SECTION_TITLE))

        self.log_console = CliTerminalView()
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
            QWidget#sessionStatusCard {
                border: 1px solid #d8ccb9;
                border-radius: 12px;
                background: #fffaf1;
            }
            QLabel#sessionStatusSummary {
                padding: 8px 10px;
                border-radius: 8px;
                background: #f6efe3;
                color: #5d4c39;
                border: 1px solid #e0d3bf;
                font-weight: 600;
            }
            QLabel#sessionStatusAction {
                padding: 8px 10px;
                border-radius: 8px;
                background: #eef4ff;
                color: #39527d;
                border: 1px solid #c9d8f0;
                font-weight: 600;
            }
            QLabel#errorRecoveryBanner {
                padding: 10px 12px;
                border-radius: 10px;
                background: #fff4da;
                color: #6f4d16;
                border: 1px solid #e2c17b;
                font-weight: 600;
            }
            QLabel#sessionStatusBadgeIdle {
                padding: 8px 12px;
                border-radius: 999px;
                background: #ece7de;
                color: #5b5248;
                border: 1px solid #d2c7b8;
                font-weight: 700;
            }
            QLabel#sessionStatusBadgeStarting {
                padding: 8px 12px;
                border-radius: 999px;
                background: #efe7c8;
                color: #7a5a10;
                border: 1px solid #dac47f;
                font-weight: 700;
            }
            QLabel#sessionStatusBadgeRunning {
                padding: 8px 12px;
                border-radius: 999px;
                background: #e0efe2;
                color: #2f6a39;
                border: 1px solid #b5d6ba;
                font-weight: 700;
            }
            QLabel#sessionStatusBadgeStopping {
                padding: 8px 12px;
                border-radius: 999px;
                background: #f2e4d8;
                color: #8a5624;
                border: 1px solid #ddb58d;
                font-weight: 700;
            }
            QLabel#sessionStatusBadgeStopped {
                padding: 8px 12px;
                border-radius: 999px;
                background: #ece7de;
                color: #5b5248;
                border: 1px solid #d2c7b8;
                font-weight: 700;
            }
            QLabel#sessionStatusBadgeDetached {
                padding: 8px 12px;
                border-radius: 999px;
                background: #e4e9f2;
                color: #36527a;
                border: 1px solid #b7c7e0;
                font-weight: 700;
            }
            QLabel#sessionStatusBadgeFailed {
                padding: 8px 12px;
                border-radius: 999px;
                background: #f4dede;
                color: #8a2f2f;
                border: 1px solid #deb2b2;
                font-weight: 700;
            }
            QLabel#modeBadge {
                padding: 8px 12px;
                border-radius: 999px;
                background: #e7efe0;
                color: #365139;
                border: 1px solid #bfd4b6;
                font-weight: 700;
            }
            QLabel#terminalPrompt {
                padding: 6px 8px;
                border-radius: 8px;
                background: #101512;
                color: #65f18c;
                border: 1px solid #253228;
                font-family: Consolas, "Courier New", monospace;
                font-size: 12px;
                font-weight: 700;
                min-width: 88px;
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
            QPushButton#secondaryButton {
                background: #f2eadb;
                color: #5f503d;
                border: 1px solid #d7c5ab;
                font-weight: 600;
            }
            QPushButton#secondaryButton:hover {
                background: #ebdfca;
            }
            QPushButton#compactButton {
                padding: 8px 10px;
                border-radius: 10px;
                font-size: 13px;
                min-height: 22px;
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
        # 调试工具弹窗是独立顶层窗口，主窗口 QSS 不会自动级联过去；
        # 复制同一份样式，保证弹窗内按钮/标签的内边距与高度和主界面一致，避免文字被裁切。
        self.debug_tools_dialog.setStyleSheet(self.styleSheet())

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
        self.script_dir_input.setToolTip(f"{ui_messages.SCRIPT_SELECTION_ROOT_HINT}\n{str(self.script_root)}")
        self.script_root_source_label.setText(
            ui_messages.SCRIPT_ROOT_SOURCE_LABEL.format(value=self._describe_script_root_source())
        )

    def apply_script_root(self, script_root: Path) -> None:
        self.script_root = script_root
        self.update_script_root_display()
        self.refresh_script_list()

    def _handle_log_from_worker(self, message: str) -> None:
        # 任何线程里的日志都不要直接操作 Qt 控件，
        # 统一转成信号，交回主线程更新界面。
        self.log_emitted.emit(message)

    def _handle_session_event_from_worker(
        self,
        event_type: str,
        payload: object,
    ) -> None:
        # 会话 detached 等事件可能来自 Frida 后台线程，这里统一切回主线程。
        self.session_event_emitted.emit(event_type, payload)

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
            self.toggle_log_focus_button.setText(ui_messages.FOCUS_LOG_DISABLE_BUTTON)
            self.toggle_log_focus_button.setToolTip(ui_messages.FOCUS_LOG_DISABLE_TOOLTIP)
            self.status_bar.showMessage(ui_messages.FOCUS_LOG_ENABLED)
            return

        self.script_scroll.show()
        self.control_scroll.show()
        self.splitter.setHandleWidth(8)
        self.log_focus_mode = False
        self.toggle_log_focus_button.setText(ui_messages.FOCUS_LOG_ENABLE_BUTTON)
        self.toggle_log_focus_button.setToolTip(ui_messages.FOCUS_LOG_ENABLE_TOOLTIP)
        self.splitter.setSizes(self.saved_splitter_sizes)
        self.status_bar.showMessage(ui_messages.FOCUS_LOG_DISABLED)

    def set_status_text(self, message: str, status_message: str | None = None) -> None:
        self.current_state_label.setText(ui_messages.state_text(message))
        self.status_bar.showMessage(status_message or message)

    def update_error_recovery_banner(self, focus_target: str | None, next_step: str | None = None) -> None:
        message = self._recovery_message_for_target(focus_target, next_step)
        if not message:
            self.error_recovery_banner_label.setText(ui_messages.ERROR_RECOVERY_EMPTY)
            self.error_recovery_banner_label.hide()
            return
        self.error_recovery_banner_label.setText(message)
        self.error_recovery_banner_label.show()

    def clear_error_recovery_banner(self) -> None:
        self.error_recovery_banner_label.hide()
        self.error_recovery_banner_label.setText(ui_messages.ERROR_RECOVERY_EMPTY)

    def _recovery_message_for_target(self, focus_target: str | None, next_step: str | None) -> str | None:
        if focus_target == "app_combo":
            return f"{ui_messages.ERROR_RECOVERY_BANNER_PREFIX}{ui_messages.ERROR_RECOVERY_APP}"
        if focus_target == "script_combo":
            return f"{ui_messages.ERROR_RECOVERY_BANNER_PREFIX}{ui_messages.ERROR_RECOVERY_SCRIPT}"
        if focus_target == "hook_target_input":
            return f"{ui_messages.ERROR_RECOVERY_BANNER_PREFIX}{ui_messages.ERROR_RECOVERY_HOOK_TARGET}"
        if focus_target == "inspect_target_input":
            return f"{ui_messages.ERROR_RECOVERY_BANNER_PREFIX}{ui_messages.ERROR_RECOVERY_INSPECT_TARGET}"
        if focus_target == "log_console":
            return f"{ui_messages.ERROR_RECOVERY_BANNER_PREFIX}{ui_messages.ERROR_RECOVERY_TERMINAL}"
        if next_step:
            return f"{ui_messages.ERROR_RECOVERY_BANNER_PREFIX}{next_step}"
        return None

    def set_session_status(
        self,
        *,
        phase: str,
        mode: str | None = None,
        package: str | None = None,
        script: str | None = None,
        detail: str | None = None,
    ) -> None:
        self.session_status_phase_label.setText(phase)
        payload = build_session_status_payload(phase)
        summary = payload['summary']
        action_text = payload['action_text']
        badge_name = payload['badge_name']
        self.session_status_phase_label.setObjectName(badge_name)
        self.session_status_phase_label.style().unpolish(self.session_status_phase_label)
        self.session_status_phase_label.style().polish(self.session_status_phase_label)
        self.session_status_summary_label.setText(
            ui_messages.SESSION_STATUS_SUMMARY_TEMPLATE.format(summary=summary)
        )
        self.session_status_action_label.setText(action_text)
        self.session_status_mode_label.setText(
            ui_messages.SESSION_STATUS_MODE.format(mode=mode)
            if mode
            else ui_messages.SESSION_STATUS_MODE_EMPTY
        )
        self.session_status_target_label.setText(
            ui_messages.SESSION_STATUS_TARGET.format(package=package)
            if package
            else ui_messages.SESSION_STATUS_TARGET_EMPTY
        )
        self.session_status_script_label.setText(
            ui_messages.SESSION_STATUS_SCRIPT.format(script=script)
            if script
            else ui_messages.SESSION_STATUS_SCRIPT_EMPTY
        )
        self.session_status_detail_label.setText(
            ui_messages.SESSION_STATUS_DETAIL.format(detail=detail)
            if detail
            else ui_messages.SESSION_STATUS_DETAIL_EMPTY
        )
        self.start_hook_button.setToolTip(payload['launch_hint'])
        self.stop_hook_button.setToolTip(payload['launch_hint'])

    def _update_mode_badge(self) -> None:
        if self.spawn_mode_radio.isChecked():
            self.mode_badge_label.setText(ui_messages.SPAWN_MODE_BADGE)
            return
        self.mode_badge_label.setText(ui_messages.ATTACH_MODE_BADGE)

    def _park_focus_before_busy(self) -> None:
        # 进入忙碌态前先收回键盘焦点，避免“焦点乱跳”。
        # 原因：set_busy 会禁用大量控件，如果此时焦点正落在某个即将被禁用的控件上
        #（例如刚被鼠标点击的“开始注入”按钮），Qt 会在该控件被禁用时自动把焦点转移到
        # Tab 链下一个控件，而连锁禁用会让焦点在界面上被一路甩动。
        # 因此在禁用前主动把焦点交还给主窗口，从源头切断这种自动转移。
        focused = QApplication.focusWidget()
        if focused is not None and (focused is self or self.isAncestorOf(focused)):
            focused.clearFocus()

    def set_busy(self, busy: bool, message: str | None = None) -> None:
        # 统一管理按钮禁用状态，避免多个分支各自写一套启停逻辑。
        if busy:
            self._park_focus_before_busy()
        self.refresh_apps_button.setDisabled(busy)
        # 活动会话存在时，不允许再次启动注入。
        self.start_hook_button.setDisabled(busy or self.deps.context.active_session is not None)
        self.select_script_dir_button.setDisabled(busy)
        self.reload_script_dir_button.setDisabled(busy)
        self.apk_scan_controller.sync_button_state(busy)
        self.stop_frida_server_button.setDisabled(busy)
        self.prepare_workspace_button.setDisabled(busy)
        self.attach_mode_radio.setDisabled(busy)
        self.spawn_mode_radio.setDisabled(busy)
        self.hook_target_input.setDisabled(busy)
        self.inspect_target_input.setDisabled(busy)
        self.generate_hook_button.setDisabled(busy)
        self.advanced_frida_launch_button.setDisabled(
            busy or self.deps.context.active_session is not None
        )
        self.view_activity_button.setDisabled(busy)
        self.view_service_button.setDisabled(busy)
        quick_hook_disabled = busy or self.deps.context.active_session is not None
        for button_attr in QUICK_HOOK_BUTTON_ATTRS:
            getattr(self, button_attr).setDisabled(quick_hook_disabled)
        self.restart_app_button.setDisabled(busy)
        self.object_info_button.setDisabled(busy)
        self.object_explain_button.setDisabled(busy)
        self.view_info_button.setDisabled(busy)
        self.app_combo.setDisabled(busy)
        self.terminal_cli_mode_button.setDisabled(busy)
        self.log_console.setDisabled(busy and not self.log_console.cli_mode_enabled())
        self.stop_hook_button.setDisabled(self.deps.context.active_session is None)
        if message:
            self.set_status_text(message)

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
        current_path = self.selected_script_path()
        current_path_str = str(current_path.resolve()) if current_path is not None else None
        self.script_combo.clear()
        if not self.script_root.exists():
            self.script_list_hint_label.show()
            self.selected_script_label.setText(ui_messages.SCRIPT_SELECTION_EMPTY)
            self.selected_script_label.setToolTip("")
            return

        script_infos = self._filtered_script_infos_for_current_root()
        restored_index = -1
        for index, info in enumerate(script_infos):
            item_label = self._display_label_for_script_info(info)
            resolved_path = str(info.path.resolve())
            self.script_combo.addItem(item_label, resolved_path)
            if current_path_str and resolved_path == current_path_str:
                restored_index = index

        if self.script_combo.count() > 0:
            target_index = restored_index if restored_index >= 0 else 0
            self.script_combo.setCurrentIndex(target_index)
            self.script_list_hint_label.hide()
            if restored_index < 0:
                self._update_selected_script_tip()
        else:
            self.script_list_hint_label.show()
            self.selected_script_label.setText(ui_messages.SCRIPT_SELECTION_EMPTY)
            self.selected_script_label.setToolTip("")
            return

    def _update_selected_script_tip(self) -> None:
        # 底部显示当前选中脚本的完整路径，方便确认自己到底注入了哪个文件。
        info = self._current_script_source_info()
        if info is None:
            self.selected_script_label.setText(ui_messages.SCRIPT_SELECTION_EMPTY)
            self.selected_script_label.setToolTip("")
            return
        script_path = info.path
        script_type = self._describe_script_info_type(info)
        source_text = self._describe_selected_script_source(script_path)
        metadata = self._script_display_metadata(info)
        recommended_mode = self._format_script_recommended_mode(info)
        summary = metadata.summary if metadata and metadata.summary else "-"
        use_when = metadata.use_when if metadata and metadata.use_when else "-"
        caution = metadata.caution if metadata and metadata.caution else "-"
        tags_value = ", ".join(metadata.tags) if metadata and metadata.tags else "-"
        last_used_at = metadata.last_used_at if metadata and metadata.last_used_at else "-"
        self.selected_script_label.setText(
            join_lines(
                build_script_selection_lines(
                    name=script_path.name,
                    source_text=source_text,
                    script_type=script_type,
                    recommended_mode=recommended_mode,
                    summary=summary,
                    use_when=use_when,
                    caution=caution,
                    tags_value=tags_value,
                    last_used_at=last_used_at,
                    path_value=self.shorten_path(script_path, keep=16),
                )
            )
        )
        self.selected_script_label.setToolTip(
            join_lines(
                build_script_selection_lines(
                    name=script_path.name,
                    source_text=source_text,
                    script_type=script_type,
                    recommended_mode=recommended_mode,
                    summary=summary,
                    use_when=use_when,
                    caution=caution,
                    tags_value=tags_value,
                    last_used_at=last_used_at,
                    path_value=str(script_path),
                    root_path=str(self.script_root),
                )
            )
        )

    def _current_script_filter_view(self) -> str:
        current_text = self.script_filter_combo.currentText()
        if current_text == ui_messages.SCRIPT_FILTER_RECENT:
            return "recent"
        return "all"

    def _current_script_filter_query(self) -> str:
        return self.script_search_input.text().strip()

    def _filtered_script_infos_for_current_root(self) -> list[ScriptSourceInfo]:
        package_name = self.deps.context.current_app.identifier if self.deps.context.current_app else None
        if package_name:
            try:
                current_root = self.script_root.resolve()
                workspace_root = self.deps.workspace_service.script_dir(package_name).resolve()
                if current_root == workspace_root:
                    return self.deps.workspace_service.filter_script_sources(
                        package_name,
                        view=self._current_script_filter_view(),
                        query=self._current_script_filter_query(),
                    )
            except Exception:
                pass
        return self._script_infos_for_current_root()

    def _script_infos_for_current_root(self) -> list[ScriptSourceInfo]:
        package_name = self.deps.context.current_app.identifier if self.deps.context.current_app else None
        if package_name:
            try:
                current_root = self.script_root.resolve()
                workspace_root = self.deps.workspace_service.script_dir(package_name).resolve()
                builtin_root = self.deps.context.hookers_js_dir.resolve()
                if current_root == workspace_root:
                    return self.deps.workspace_service.list_workspace_visible_scripts(package_name)
                if current_root == builtin_root:
                    return [
                        info
                        for info in self.deps.workspace_service.list_script_sources(package_name)
                        if info.source_kind == "builtin_source"
                    ]
            except Exception:
                pass
        infos = [
            ScriptSourceInfo(
                name=path.name,
                path=path,
                source_kind="workspace" if self._is_workspace_script(path) else "builtin_source",
                is_builtin=path.resolve().parent == self.deps.context.hookers_js_dir.resolve() if path.exists() else False,
                is_parameter_template=path.name in {"jni_method_trace.js", "trace_init_proc.js"},
                display_label=path.name,
                metadata=None,
            )
            for path in sorted(self.script_root.glob("*.js"), key=lambda item: item.name.lower())
        ]
        keyword = self._current_script_filter_query().lower()
        if not keyword:
            return infos
        return [info for info in infos if keyword in info.name.lower() or keyword in info.display_label.lower()]

    def _current_script_source_info(self) -> ScriptSourceInfo | None:
        script_path = self.selected_script_path()
        if script_path is None:
            return None
        script_infos = self._filtered_script_infos_for_current_root()
        for info in script_infos:
            try:
                if info.path.resolve() == script_path.resolve():
                    return info
            except Exception:
                continue
        fallback_infos = self._script_infos_for_current_root()
        for info in fallback_infos:
            try:
                if info.path.resolve() == script_path.resolve():
                    return info
            except Exception:
                continue
        return None

    def _script_display_metadata(self, info: ScriptSourceInfo):
        if info.metadata is not None:
            return info.metadata
        current_app = self.deps.context.current_app
        if current_app is None:
            return None
        if info.source_kind == "builtin_source":
            return None
        try:
            return self.deps.workspace_service.resolve_script_metadata(current_app.identifier, info.name)
        except Exception:
            return None

    def _display_label_for_script_info(self, info: ScriptSourceInfo) -> str:
        metadata = self._script_display_metadata(info)
        prefix = ui_messages.PINNED_SCRIPT_PREFIX if metadata and metadata.pinned else ""
        return f"{prefix}{info.display_label}"

    def _format_script_recommended_mode(self, info: ScriptSourceInfo) -> str:
        metadata = self._script_display_metadata(info)
        mode = metadata.recommended_mode if metadata else "either"
        if mode == "attach":
            return ui_messages.SCRIPT_METADATA_MODE_ATTACH
        if mode == "spawn":
            return ui_messages.SCRIPT_METADATA_MODE_SPAWN
        return ui_messages.SCRIPT_METADATA_MODE_EITHER

    def _describe_script_info_type(self, info: ScriptSourceInfo) -> str:
        if info.path.name.endswith('.runtime.js'):
            return ui_messages.SCRIPT_SELECTION_RUNTIME
        if info.is_parameter_template:
            return ui_messages.ADVANCED_FRIDA_DETAIL_TYPE.format(value=ui_messages.SCRIPT_SELECTION_TYPE_PARAMETERIZED)
        if info.source_kind == "workspace_builtin_copy":
            return ui_messages.ADVANCED_FRIDA_DETAIL_TYPE.format(value=ui_messages.SCRIPT_SELECTION_TYPE_BUILTIN_COPY)
        if info.source_kind == "builtin_source":
            return ui_messages.ADVANCED_FRIDA_DETAIL_TYPE.format(value=ui_messages.SCRIPT_SELECTION_TYPE_BUILTIN)
        if self._is_workspace_script(info.path):
            return ui_messages.ADVANCED_FRIDA_DETAIL_TYPE.format(value=ui_messages.SCRIPT_SELECTION_TYPE_WORKSPACE)
        return ui_messages.ADVANCED_FRIDA_DETAIL_TYPE.format(value=ui_messages.SCRIPT_SELECTION_TYPE_CUSTOM)
    def _analysis_scenario_tooltip(self, profile) -> str:
        return build_analysis_scenario_tooltip_text(profile)

    def set_current_script_recommended_mode(self) -> None:
        info = self._current_script_source_info()
        current_app = self.deps.context.current_app
        if info is None or current_app is None:
            return
        options = [
            ui_messages.SCRIPT_METADATA_MODE_ATTACH,
            ui_messages.SCRIPT_METADATA_MODE_SPAWN,
            ui_messages.SCRIPT_METADATA_MODE_EITHER,
        ]
        current_mode = self._format_script_recommended_mode(info)
        try:
            current_index = options.index(current_mode)
        except ValueError:
            current_index = 2
        selected, accepted = QInputDialog.getItem(
            self,
            ui_messages.SCRIPT_MODE_EDIT_TITLE,
            ui_messages.SCRIPT_MODE_EDIT_LABEL,
            options,
            current_index,
            False,
        )
        if not accepted:
            return
        mode_map = {
            ui_messages.SCRIPT_METADATA_MODE_ATTACH: "attach",
            ui_messages.SCRIPT_METADATA_MODE_SPAWN: "spawn",
            ui_messages.SCRIPT_METADATA_MODE_EITHER: "either",
        }
        try:
            self.deps.workspace_service.set_script_recommended_mode(
                current_app.identifier,
                info.name,
                mode_map.get(selected, "either"),
            )
        except Exception as exc:
            self.error_presenter.present(exc)
            return
        self.refresh_script_list()

    def _describe_script_root_source(self) -> str:
        try:
            root = self.script_root.resolve()
            builtin = self.deps.context.hookers_js_dir.resolve()
            if root == builtin:
                return ui_messages.SCRIPT_ROOT_SOURCE_BUILTIN
            workspaces_root = (self.deps.context.project_root / "workspaces").resolve()
            if workspaces_root in root.parents:
                return ui_messages.SCRIPT_ROOT_SOURCE_WORKSPACE
        except Exception:
            pass
        return ui_messages.SCRIPT_ROOT_SOURCE_CUSTOM

    def _describe_selected_script_source(self, script_path: Path) -> str:
        if script_path.name.startswith("内置-"):
            return ui_messages.ADVANCED_FRIDA_WORKSPACE_COPY_SOURCE
        try:
            if script_path.resolve().parent == self.deps.context.hookers_js_dir.resolve():
                return ui_messages.ADVANCED_FRIDA_BUILTIN_SOURCE
        except Exception:
            pass
        return ui_messages.ADVANCED_FRIDA_WORKSPACE_SOURCE if self._is_workspace_script(script_path) else ui_messages.SCRIPT_SELECTION_CUSTOM_SOURCE

    def _describe_script_path_kind(self, script_path: Path) -> str:
        if script_path.name.endswith('.runtime.js'):
            return ui_messages.SCRIPT_SELECTION_RUNTIME
        if script_path.name.startswith('内置-'):
            return ui_messages.SCRIPT_SELECTION_WORKSPACE_BUILTIN
        if self._is_workspace_script(script_path):
            return ui_messages.SCRIPT_SELECTION_WORKSPACE
        try:
            if script_path.resolve().parent == self.deps.context.hookers_js_dir.resolve():
                return ui_messages.SCRIPT_SELECTION_BUILTIN
        except Exception:
            pass
        return ui_messages.SCRIPT_SELECTION_WORKSPACE

    def _is_workspace_script(self, script_path: Path) -> bool:
        try:
            workspace_root = (self.deps.context.project_root / "workspaces").resolve()
            return workspace_root in script_path.resolve().parents
        except Exception:
            return False

    def selected_script_path(self) -> Path | None:
        # 从脚本下拉框中取回当前选中脚本的完整路径。
        value = self.script_combo.currentData()
        if value is None:
            return None
        return Path(str(value))

    def _open_debug_tools_dialog(self) -> None:
        # 调试与分析工具收纳进非模态弹窗，单按钮触发显示。
        self.debug_tools_dialog.show()
        self.debug_tools_dialog.raise_()
        self.debug_tools_dialog.activateWindow()

    def focus_error_target(self, target: str) -> None:
        widget = self._resolve_error_focus_widget(target)
        if widget is None:
            return
        # 对象分析输入框已收进调试工具弹窗，错误恢复聚焦前需先把弹窗显示出来。
        if target == "inspect_target_input" and not self.debug_tools_dialog.isVisible():
            self._open_debug_tools_dialog()
        try:
            widget.setFocus()
        except Exception:
            return

    def _resolve_error_focus_widget(self, target: str):
        if target == "app_combo":
            return self.app_combo
        if target == "script_combo":
            return self.script_combo
        if target == "hook_target_input":
            return self.hook_target_input
        if target == "inspect_target_input":
            return self.inspect_target_input
        if target == "log_console":
            return self.log_console
        return None

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
