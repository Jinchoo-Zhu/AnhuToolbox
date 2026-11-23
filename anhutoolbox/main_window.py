# -*- coding: utf-8 -*-
"""AnhuToolbox 主窗口 -- 带配置持久化 + 预设面板可折叠"""

import os, json, shutil, socket, sys, time
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QTabWidget, QStackedWidget,
    QSplitter, QStatusBar, QLabel, QFrame,
    QMenu, QFileDialog, QPushButton,
)
from PySide6.QtCore import Qt, QTimer, Signal, Slot
import serial, serial.tools.list_ports

from .sidebar import Sidebar
from .panels import PresetPanel
from .workers import SerialReadWorker, TCPServerWorker, TCPClientWorker
from .protocol_workers import MQTTWorker, WebSocketWorker
from .protocol_pages import HTTPPage, MQTTPage, WebSocketPage
from .process_metrics import ProcessMetrics
from .stream_views import StreamPage
from .tools import (
    TimestampTool, QRTool, JsonTool, BaseTool, RegexTool, DiffTool, SortTool,
    EncodeTool, ChecksumTool, AmountTool, HardwareInfoPage, NetworkTool,
    PacketCaptureTool,
)
from .styles import (GLOBAL_STYLE, STATUS_BAR_STYLE, BG_SIDEBAR, BORDER,
                     TEXT_PRIMARY, TEXT_SECONDARY, prepare_menu)
from . import settings as cfg
from . import toolbox
from .custom_library import CustomLibraryPage
from .projects import ProjectManager, DEFAULT_PROJECT_NAME
from .secrets_guard import contains_sensitive_values
from .updates import (
    UpdateCheckWorker, cleanup_update_cache, launch_updater,
)
from .update_ui import UpdateAvailableDialog, UpdateDownloadDialog
from .about_dialog import AboutDialog
from .version import __version__
from .app_paths import choose_data_root
from .dialogs import (
    ask_yes_no, get_text, show_error, show_success, show_warning,
)


# 工具库分组: (组名, [(key, 显示名), ...])，key 对应下方工具页字典
LIBRARY_STANDALONE = [("hardware", "硬件信息")]

LIBRARY_GROUPS = [
    ("转换与计算", [
        ("timestamp", "时间戳转换"),
        ("base", "进制转换"),
        ("encode", "编码转换"),
        ("checksum", "校验计算"),
        ("amount", "金额转换"),
    ]),
    ("文本处理", [
        ("json", "JSON 美化"),
        ("regex", "正则测试"),
        ("diff", "文本对比"),
        ("sort", "列表排序"),
    ]),
    ("生成工具", [
        ("qr", "二维码生成"),
    ]),
    ("网络工具", [
        ("network", "Ping | 端口扫描 | 网段扫描"),
        ("capture", "抓包分析"),
    ]),
]

# 工具库默认展示顺序 (与分组一致)
LIBRARY_ORDER = ["hardware", "timestamp", "base", "encode", "checksum", "amount",
                 "json", "regex", "diff", "sort", "qr", "network", "capture"]

COMM_MODE_INDEX = {
    "serial": 0,
    "tcpserver": 1,
    "tcpclient": 2,
    "mqtt": 3,
    "websocket": 4,
    "http": 5,
}

UPDATE_INITIAL_DELAY_MS = 2500
UPDATE_RECHECK_INTERVAL_MS = 4 * 60 * 60 * 1000


def _profile_int(value, default, minimum=None, maximum=None):
    """把导入项目中的数值字段安全转换为整数，并进行范围约束。"""
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        number = int(default)
    if minimum is not None:
        number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number


def _profile_bool(value, default=False):
    """兼容 JSON 布尔值以及常见字符串写法。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("1", "true", "yes", "on", "是"):
            return True
        if text in ("0", "false", "no", "off", "否", ""):
            return False
    return bool(default)


def _profile_dict(value):
    return value if isinstance(value, dict) else {}


def _profile_list(value):
    return value if isinstance(value, list) else []




class MainWindow(QMainWindow):
    log_message = Signal(str)

    def __init__(self, base_dir=None):
        super().__init__()
        self._base_dir = base_dir or os.path.dirname(os.path.dirname(__file__))
        self._data_root = choose_data_root(self._base_dir)
        self._data_dir = os.path.join(self._data_root, "data")
        self._log_dir = os.path.join(self._data_root, "log")
        try:
            os.makedirs(self._log_dir, exist_ok=True)
        except Exception as e:
            print("[AnhuToolbox] 创建日志目录失败:", e)
        # 数据文件放 EXE 目录 (可写), 而非临时解压目录
        self.setWindowTitle("Anhu 百宝箱")
        self.setMinimumSize(1100, 720)

        cfg.init(os.path.join(self._data_dir, "settings.json"))

        self._serial_worker = SerialReadWorker()
        self._serial_worker.data_received.connect(self._on_rx_data)
        self._serial_worker.error_occurred.connect(self._on_error)
        self._serial_worker.disconnected.connect(self._on_serial_disconnected)

        self._tcp_server = TCPServerWorker()
        self._tcp_server.data_received.connect(self._on_rx_data)
        self._tcp_server.error_occurred.connect(self._on_error)
        self._tcp_server.client_connected.connect(self._on_tcp_server_client_connected)
        self._tcp_server.client_disconnected.connect(self._on_tcp_server_client_disconnected)
        self._tcp_server.started.connect(self._on_tcp_server_started)
        self._tcp_server.start_failed.connect(self._on_tcp_server_start_failed)
        self._tcp_server.log_message.connect(self._log)

        self._tcp_client = TCPClientWorker()
        self._tcp_client.data_received.connect(self._on_rx_data)
        self._tcp_client.error_occurred.connect(self._on_error)
        self._tcp_client.connected.connect(self._on_tcp_connected)
        self._tcp_client.disconnected.connect(self._on_tcp_disconnected)
        self._tcp_client.connect_failed.connect(self._on_tcp_client_connect_failed)
        self._tcp_client.log_message.connect(self._log)

        self._mqtt_worker = MQTTWorker()
        self._mqtt_worker.connected.connect(self._on_mqtt_connected)
        self._mqtt_worker.disconnected.connect(self._on_mqtt_disconnected)
        self._mqtt_worker.message_received.connect(self._on_mqtt_message)
        self._mqtt_worker.error_occurred.connect(self._on_error)
        self._mqtt_worker.log_message.connect(self._log)

        self._websocket_worker = WebSocketWorker()
        self._websocket_worker.connected.connect(self._on_websocket_connected)
        self._websocket_worker.disconnected.connect(
            self._on_websocket_disconnected)
        self._websocket_worker.message_received.connect(
            self._on_websocket_message)
        self._websocket_worker.error_occurred.connect(self._on_error)
        self._websocket_worker.log_message.connect(self._log)

        self._active_worker = None
        self._connection_mode = cfg.get("mode", "serial")
        self._local_addr = ""
        self._remote_addr = ""
        self._mqtt_rx_count = 0
        self._mqtt_tx_count = 0
        self._ws_rx_count = 0
        self._ws_tx_count = 0
        self._mqtt_auto_reconnect = True
        self._websocket_auto_reconnect = True
        self._active_stream_key = "serial"

        # 项目管理: 一个项目 = 一整套连接参数 + 发送/显示配置 + 预设命令
        self._pm = ProjectManager(self._data_root)
        self._current_project = ""
        self._project_load_failed = False
        self._last_project_save_error = ""
        self._applying = False          # 应用项目配置期间抑制自动保存
        self._last_snapshot = None
        self._has_dtr_rts = False       # 当前项目是否记录了 DTR/RTS 状态
        self._extra_tabs_built = False
        self._pending_update = None
        self._downloaded_update = None
        self._downloaded_toolbox = None
        self._download_purpose = None
        self._about_dialog = None

        self._build_ui()
        self._restore_global()
        self._connect_signals()
        self._init_projects()
        self._refresh_ports()

        self._port_timer = QTimer()
        self._port_timer.timeout.connect(self._refresh_ports)
        self._port_timer.start(1500)

        self._process_metrics = ProcessMetrics()
        self._resource_timer = QTimer(self)
        self._resource_timer.timeout.connect(self._update_resource_usage)
        self._resource_timer.start(1000)
        self._update_resource_usage()
        self._update_check_worker = None
        self._update_download_dialog = None
        self._update_check_timer = QTimer(self)
        self._update_check_timer.setInterval(UPDATE_RECHECK_INTERVAL_MS)
        self._update_check_timer.timeout.connect(self._start_update_check)
        self._update_check_timer.start()
        self._update_initial_timer = QTimer(self)
        self._update_initial_timer.setSingleShot(True)
        self._update_initial_timer.timeout.connect(self._start_update_check)
        self._update_initial_timer.start(UPDATE_INITIAL_DELAY_MS)

    def _stream_page(self, mode=None):
        key = mode or self._active_stream_key
        return self._stream_pages.get(key, self._stream_pages["serial"])

    @property
    def log_panel(self):
        return self._stream_page().log_panel

    @property
    def send_bar(self):
        return self._stream_page().send_bar

    @property
    def _btn_toggle_preset(self):
        return self._stream_page().btn_toggle_preset

    def _build_ui(self):
        self.setStyleSheet(GLOBAL_STYLE)
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        body = QHBoxLayout()
        body.setContentsMargins(0,0,0,0); body.setSpacing(0)

        self.sidebar = Sidebar()
        body.addWidget(self.sidebar)

        sep = QFrame(); sep.setObjectName("separator"); sep.setFixedWidth(1)
        body.addWidget(sep)

        # 串口、TCP 服务端、TCP 客户端各自拥有独立日志和发送栏。
        self._stream_pages = {
            "serial": StreamPage(),
            "tcpserver": StreamPage(),
            "tcpclient": StreamPage(),
        }
        self._main_area = self._stream_pages["serial"]

        self._mqtt_page = MQTTPage()
        self._websocket_page = WebSocketPage()
        self._http_page = HTTPPage()
        for key, page in self._stream_pages.items():
            prefix = {
                "serial": "serial",
                "tcpserver": "tcp_server",
                "tcpclient": "tcp_client",
            }[key]
            page.log_panel.set_log_directory(self._log_dir, prefix)
        self._mqtt_page.set_log_directory(self._log_dir, "mqtt")
        self._websocket_page.set_log_directory(
            self._log_dir, "websocket")
        self._comm_stack = QStackedWidget()
        self._comm_stack.addWidget(self._main_area)
        self._comm_stack.addWidget(self._stream_pages["tcpserver"])
        self._comm_stack.addWidget(self._stream_pages["tcpclient"])
        self._comm_stack.addWidget(self._mqtt_page)
        self._comm_stack.addWidget(self._websocket_page)
        self._comm_stack.addWidget(self._http_page)

        # --- Tab 控件: 通信调试 + 工具集 ---
        self._tab_widget = QTabWidget()
        # QTabWidget 的 minimumSizeHint 会取所有子页的最大值，导致预设分隔器
        # 在小窗口中几乎没有可拖动范围。显式设置可收缩宽度，由分屏自行分配。
        self._tab_widget.setMinimumWidth(360)
        self._tab_widget.setStyleSheet(
            "QTabWidget::pane{border:1px solid #D0D0D0;border-top:none}"
            "QTabBar::tab{background:#F5F5F5;color:#666;padding:8px 18px;border:1px solid #D0D0D0;"
            "border-bottom:none;margin-right:2px;font-size:13px}"
            "QTabBar::tab:selected{background:#FFF;color:#0078D4;font-weight:600;border-bottom:2px solid #0078D4}"
            "QTabBar::tab:hover{background:#E8F0FE;color:#0078D4}"
        )
        self._tab_widget.addTab(self._comm_stack, "通信调试")
        self._build_header_actions()
        self._tab_widget.currentChanged.connect(self._on_tab_changed)
        # 其余工具页延迟到事件循环开始后再创建, 加快首屏显示
        self._extra_tabs_timer = QTimer(self)
        self._extra_tabs_timer.setSingleShot(True)
        self._extra_tabs_timer.timeout.connect(self._build_extra_tabs)
        self._extra_tabs_timer.start(0)

        # --- 预设面板 (可拖动, 初始隐藏) ---
        self.preset_panel = PresetPanel()
        # 预设内容改为跟随「项目」保存, 不再写全局 presets.json
        self.preset_panel.set_change_callback(self._on_presets_changed)
        self.preset_panel.send_preset.connect(self._on_send_preset)
        self.preset_panel.setVisible(False)
        self.preset_panel.setMinimumWidth(200)

        self._preset_splitter = QSplitter(Qt.Horizontal)
        self._preset_splitter.setObjectName("presetSplitter")
        self._preset_splitter.setHandleWidth(8)
        self._preset_splitter.setChildrenCollapsible(False)
        self._preset_splitter.setOpaqueResize(True)
        self._preset_splitter.setStyleSheet(
            "QSplitter#presetSplitter::handle{background:#D8E0E8;"
            "border-left:1px solid #C6D0DA;"
            "border-right:1px solid #F4F7FA;}"
            "QSplitter#presetSplitter::handle:hover{background:#9CC7EA;}"
        )
        self._preset_splitter.addWidget(self._tab_widget)
        self._preset_splitter.addWidget(self.preset_panel)
        self._preset_splitter.setStretchFactor(0, 3)
        self._preset_splitter.setStretchFactor(1, 1)
        self._preset_splitter.setSizes([550, 450])

        body.addWidget(self._preset_splitter, stretch=1)

        root.addLayout(body, stretch=1)

        # --- 底部信息栏 ---
        self._info_bar = self._build_info_bar()
        root.addWidget(self._info_bar)

        # --- 状态栏 ---
        self.status_bar = QStatusBar()
        self.status_bar.setStyleSheet(STATUS_BAR_STYLE)
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")

    def _build_header_actions(self):
        actions = QWidget()
        layout = QHBoxLayout(actions)
        layout.setContentsMargins(0, 1, 6, 1)
        layout.setSpacing(2)

        self._btn_about = QPushButton("关于")
        self._btn_about.setObjectName("aboutLinkButton")
        self._btn_about.setCursor(
            Qt.CursorShape.PointingHandCursor)
        self._btn_about.setStyleSheet(
            "QPushButton#aboutLinkButton{"
            "background:transparent;color:#555;border:1px solid #9CC7EA;"
            "border-radius:4px;padding:0 9px;font-size:12px;"
            "min-height:22px;max-height:24px;}"
            "QPushButton#aboutLinkButton:hover{color:#0067B8;"
            "background:#EAF4FF;border-color:#0078D4;}"
        )
        self._btn_about.setFixedHeight(24)
        self._btn_about.setFixedWidth(48)

        self._btn_update_available = QPushButton("发现新版本")
        self._btn_update_available.setObjectName("updateAvailableButton")
        self._btn_update_available.setCursor(
            Qt.CursorShape.PointingHandCursor)
        self._btn_update_available.setToolTip(
            "点击查看更新内容，并选择是否立即更新")
        self._btn_update_available.setStyleSheet(
            "QPushButton#updateAvailableButton{"
            "background:#EAF4FF;color:#0067B8;border:1px solid #B7D9F5;"
            "border-radius:12px;padding:0 11px;font-size:12px;"
            "min-height:22px;max-height:24px;}"
            "QPushButton#updateAvailableButton:hover{"
            "background:#D9ECFF;border-color:#8CC4F0;}"
            "QPushButton#updateAvailableButton:pressed{"
            "background:#CBE4FB;}"
        )
        self._btn_update_available.setFixedHeight(24)
        self._btn_update_available.hide()
        layout.addWidget(
            self._btn_update_available, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(
            self._btn_about, 0, Qt.AlignmentFlag.AlignVCenter)

        self._tab_widget.setCornerWidget(
            actions, Qt.Corner.TopRightCorner)

    def _build_extra_tabs(self):
        """延迟创建工具库、可选工具箱和自定义库 (避免首屏被阻塞)"""
        if self._extra_tabs_built:
            return
        self._extra_tabs_built = True
        # --- 工具库 tab: 左侧分组列表在 sidebar, 右侧是工具页堆叠 ---
        self._library_pages = {
            "hardware": HardwareInfoPage(),
            "timestamp": TimestampTool(),
            "base": BaseTool(),
            "encode": EncodeTool(),
            "checksum": ChecksumTool(),
            "amount": AmountTool(),
            "json": JsonTool(),
            "regex": RegexTool(),
            "diff": DiffTool(),
            "sort": SortTool(),
            "qr": QRTool(),
            "network": NetworkTool(self._base_dir),
            "capture": PacketCaptureTool(self._base_dir),
        }
        self._library_stack = QStackedWidget()
        for key in LIBRARY_ORDER:
            self._library_stack.addWidget(self._library_pages[key])
        # tab 顺序: 通信调试(0) / 工具库(1) / 工具箱(2) / 自定义库(3)
        # 通信调试在 _build_ui 里已占据 0, 这里追加即得 1
        self._tab_widget.addTab(self._library_stack, "工具库")

        # --- 可选工具箱: 只有安装器勾选且工具清单存在时才创建 ---
        tools_dir = os.path.join(self._base_dir, "tools")
        self._toolbox_available = toolbox.is_toolbox_available(tools_dir)
        self._toolbox_tools = []
        cats = []
        if self._toolbox_available:
            self._toolbox_tools = toolbox.load_manifest(tools_dir)
            cats = toolbox.load_categories(tools_dir)
            if cats is None:
                cats = []
            for t in self._toolbox_tools:
                c = toolbox._norm_category(t)
                if c not in cats:
                    cats.append(c)

        self._toolbox_categories = list(cats)
        self._toolbox_pages = {}
        self._toolbox_stack = None
        if self._toolbox_available:
            self._toolbox_stack = QStackedWidget()
            for c in cats:
                page = toolbox.build_category_page(
                    c, self._toolbox_tools, tools_dir)
                self._toolbox_stack.addWidget(page)
                self._toolbox_pages[c] = page
            self._tab_widget.addTab(self._toolbox_stack, "工具箱")

        # --- 自定义库 tab: 用户自己添加的本地工具 (清单 tools\tools.user.json) ---
        manifest_dir = tools_dir
        if os.path.normcase(os.path.abspath(self._data_root)) != \
                os.path.normcase(os.path.abspath(self._base_dir)):
            manifest_dir = self._data_dir
            old_manifest = os.path.join(tools_dir, "tools.user.json")
            new_manifest = os.path.join(manifest_dir, "tools.user.json")
            if os.path.isfile(old_manifest) and not os.path.exists(new_manifest):
                try:
                    os.makedirs(manifest_dir, exist_ok=True)
                    shutil.copy2(old_manifest, new_manifest)
                except Exception as e:
                    print("[AnhuToolbox] 迁移自定义库清单失败:", e)
        self._custom_library = CustomLibraryPage(tools_dir, manifest_dir)
        self._tab_widget.addTab(self._custom_library, "自定义库")

        # 填充左侧导航并连接信号
        self.sidebar.set_library_groups(
            LIBRARY_GROUPS, LIBRARY_STANDALONE)
        self.sidebar.set_toolbox_categories(self._toolbox_categories)
        self.sidebar.library_item_clicked.connect(self._on_library_item)
        self.sidebar.toolbox_item_clicked.connect(self._on_toolbox_item)

        # 默认停在「通信调试」(第一个 tab), 显示上次关闭时使用的项目
        self._tab_widget.setCurrentWidget(self._comm_stack)
        # 当前页本来就是 0 号, setCurrentWidget 不会触发 currentChanged,
        # 这里显式同步一次, 免得左侧边栏/底部信息栏停在未初始化状态
        self._on_tab_changed(self._tab_widget.currentIndex())

    def _build_info_bar(self):
        bar = QWidget()
        bar.setFixedHeight(32)
        bar.setStyleSheet("QWidget#info_bar{{background:{};border-top:1px solid {};}}".format(BG_SIDEBAR, BORDER))
        bar.setObjectName("info_bar")
        lo = QHBoxLayout(bar); lo.setContentsMargins(12,2,12,2); lo.setSpacing(10)
        self._lbl_conn_type = QLabel("串口")
        self._lbl_conn_type.setStyleSheet("color:{};font-weight:600;font-size:12px".format(TEXT_PRIMARY))
        lo.addWidget(self._lbl_conn_type)
        self._lbl_dot = QLabel("●")
        self._lbl_dot.setStyleSheet("color:#AAA;font-size:12px")
        lo.addWidget(self._lbl_dot)
        self._lbl_status_text = QLabel("未连接")
        self._lbl_status_text.setStyleSheet("color:{};font-size:12px".format(TEXT_SECONDARY))
        lo.addWidget(self._lbl_status_text)
        sep1 = QLabel("|"); sep1.setStyleSheet("color:#CCC;font-size:12px")
        lo.addWidget(sep1)
        self._lbl_local = QLabel("")
        lo.addWidget(self._lbl_local)
        self._lbl_arrow = QLabel("")
        self._lbl_arrow.setStyleSheet("color:#0078D4;font-size:13px;font-weight:600")
        lo.addWidget(self._lbl_arrow)
        self._lbl_remote = QLabel("")
        lo.addWidget(self._lbl_remote)
        self._lbl_stats = QLabel("")
        self._lbl_stats.setMinimumWidth(180)
        self._lbl_stats.setStyleSheet("color:{};font-size:12px".format(TEXT_SECONDARY))
        lo.addWidget(self._lbl_stats)
        lo.addStretch()
        self._lbl_resource_usage = QLabel("内存 --  |  CPU --")
        self._lbl_resource_usage.setObjectName("processResourceUsage")
        self._lbl_resource_usage.setMinimumWidth(200)
        self._lbl_resource_usage.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._lbl_resource_usage.setStyleSheet(
            "color:{};font-size:12px".format(TEXT_SECONDARY))
        self._lbl_resource_usage.setToolTip(
            "当前 AnhuToolbox 进程占用的工作集内存和 CPU，按秒刷新")
        lo.addWidget(self._lbl_resource_usage)
        self._comm_info_widgets = [
            self._lbl_conn_type,
            self._lbl_dot,
            self._lbl_status_text,
            sep1,
            self._lbl_local,
            self._lbl_arrow,
            self._lbl_remote,
            self._lbl_stats,
        ]
        self._info_bar = bar
        return bar

    @staticmethod
    def _format_memory_size(size_bytes):
        size = max(0, int(size_bytes))
        if size >= 1024 ** 3:
            return "{:.2f} GB".format(size / (1024 ** 3))
        return "{:.1f} MB".format(size / (1024 ** 2))

    def _update_resource_usage(self):
        try:
            usage = self._process_metrics.sample()
        except Exception:
            self._lbl_resource_usage.setText("内存 --  |  CPU --")
            return
        self._lbl_resource_usage.setText(
            "内存 {}  |  CPU {:.1f}%".format(
                self._format_memory_size(usage.memory_bytes),
                usage.cpu_percent,
            )
        )

    def _on_tab_changed(self, index):
        """切换主 tab 时同步导航、连接状态和全局资源栏。"""
        # 按页面对象判断, 避免依赖 tab 的先后顺序
        page = self._tab_widget.widget(index)
        if page is getattr(self, "_toolbox_stack", None):
            mode = "toolbox"
        elif page is getattr(self, "_library_stack", None):
            mode = "library"
        elif page is getattr(self, "_custom_library", None):
            # 自定义库不占左侧导航 (没有分类), 工具栏按钮在右侧页面顶部
            mode = "custom"
        elif page is getattr(self, "_comm_stack", None):
            mode = "serial"
        else:
            mode = "serial"
        self.sidebar.set_nav_mode(mode)
        is_comm = (mode == "serial")
        self._info_bar.setVisible(True)
        for widget in self._comm_info_widgets:
            widget.setVisible(is_comm)
        if is_comm:
            stream_mode = self.sidebar.current_mode in (
                "serial", "tcpserver", "tcpclient")
            show = self._btn_toggle_preset.isChecked() and stream_mode
            self.preset_panel.setVisible(show)
        else:
            self.preset_panel.setVisible(False)

    @Slot(str)
    def _on_library_item(self, key):
        page = self._library_pages.get(key)
        if page is not None:
            self._library_stack.setCurrentWidget(page)

    @Slot(str)
    def _on_toolbox_item(self, cat):
        page = self._toolbox_pages.get(cat)
        if page is not None:
            self._toolbox_stack.setCurrentWidget(page)

    def _on_toggle_preset(self, checked):
        for page in self._stream_pages.values():
            page.btn_toggle_preset.blockSignals(True)
            page.btn_toggle_preset.setChecked(checked)
            page.btn_toggle_preset.blockSignals(False)
        stream_mode = self.sidebar.current_mode in (
            "serial", "tcpserver", "tcpclient")
        self.preset_panel.setVisible(checked and stream_mode)
        if checked:
            # 展开时给预设面板合理的初始宽度
            tw = self._preset_splitter.width()
            left = tw // 2
            self._preset_splitter.setSizes([left, tw - left])
            if stream_mode:
                # 等分屏布局稳定后再补满数据列，避免展开时留下右侧空白。
                QTimer.singleShot(
                    0, self.preset_panel.fit_data_column_on_expand)
        cfg.set("preset_visible", checked)
        cfg.save()

    def _restore_global(self):
        """恢复与项目无关的全局偏好(项目内容由 _load_project 负责)"""
        show_preset = cfg.get("preset_visible", False)
        self.preset_panel.setVisible(show_preset)
        for page in self._stream_pages.values():
            page.btn_toggle_preset.setChecked(show_preset)
        saved_sizes = cfg.get("preset_splitter", None)
        if (show_preset and isinstance(saved_sizes, list)
                and len(saved_sizes) == 2
                and all(isinstance(v, int) and v > 0 for v in saved_sizes)):
            self._preset_splitter.setSizes(saved_sizes)
        # First launch: show welcome message
        if not os.path.exists(os.path.join(self._data_dir, "settings.json")):
            self._show_welcome()

    def _apply_legacy_settings_to_ui(self):
        """还没有项目时的初始值: 沿用旧版的 settings.json 里的连接/发送/显示参数"""
        idx = COMM_MODE_INDEX.get(cfg.get("mode", "serial"), 0)
        self.sidebar._mode_group.button(idx).setChecked(True)
        self.sidebar._on_mode_changed(idx)

        # Serial settings
        self.sidebar.cb_port.setCurrentText(cfg.get("serial.port", "COM1"))
        self.sidebar.cb_baud.setCurrentText(cfg.get("serial.baud", "115200"))
        self.sidebar.cb_data.setCurrentText(cfg.get("serial.data", "8"))
        self.sidebar.cb_stop.setCurrentText(cfg.get("serial.stop", "1"))
        self.sidebar.cb_parity.setCurrentText(cfg.get("serial.parity", "None"))
        self.sidebar.cb_flow.setCurrentText(cfg.get("serial.flow", "None"))

        # TCP settings
        self.sidebar.sp_server_port.setValue(cfg.get("tcpserver.port", 8888))
        self.sidebar.sp_client_timeout.setValue(cfg.get("tcpserver.client_timeout", 30))
        self.sidebar.le_client_host.setText(cfg.get("tcpclient.host", "127.0.0.1"))
        self.sidebar.sp_client_port.setValue(cfg.get("tcpclient.port", 8888))
        # 本地端口: 配置存字符串; 空/0 表示随机
        _lp = cfg.get("tcpclient.local_port", "")
        self.sidebar.le_local_port.setText(str(_lp) if str(_lp).isdigit() and int(_lp) > 0 else "")

        legacy_send = {
            "crlf": cfg.get("send.crlf", True),
            "hex_send": cfg.get("send.hex_send", False),
            "interval": cfg.get("send.interval", 1000),
            "checksum": cfg.get("send.checksum", "ModbusCRC16"),
            "start_byte": cfg.get("send.start_byte", 1),
            "end_byte_text": cfg.get("send.end_byte_text", "末尾"),
        }
        legacy_log = {
            "hex_display": cfg.get("log.hex_display", True),
            "timestamp": cfg.get("log.timestamp", True),
            "timeout": cfg.get("log.timeout", 0),
        }
        for page in self._stream_pages.values():
            self._apply_stream_config(page, legacy_send, legacy_log)

        # 旧版 data/presets.json 只在第一次建默认项目时读一次, 之后交给项目文件
        self.preset_panel.load_from_project(self._read_legacy_presets())

    def _read_legacy_presets(self):
        """读取旧版全局预设文件(仅用于初始化第一个项目)"""
        try:
            with open(os.path.join(self._data_dir, "presets.json"),
                      "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []


    def _show_welcome(self):
        msg = (
            "\n"
            "\n"
            "+======================================+\n"
            "\n"
            "     欢迎使用Anhu 百宝箱\n"
            "     作者：Jinchoo Zhu | Jerry Lyu\n"
            f"     版本号：V{__version__}\n"
            "\n"
            "+======================================+\n"
        )
        self.log_panel.text.setPlainText(msg)

    @Slot()
    def _show_about(self):
        tools_dir = os.path.join(self._base_dir, "tools")
        dialog = AboutDialog(
            self,
            toolbox_installed=toolbox.is_toolbox_available(tools_dir),
        )
        if self._pending_update is not None:
            dialog.set_update_available(self._pending_update)
        self._about_dialog = dialog
        dialog.check_update_requested.connect(self._manual_check_update)
        dialog.update_requested.connect(self._start_update_from_about)
        dialog.install_toolbox_requested.connect(
            self._request_toolbox_install)
        try:
            dialog.exec()
        finally:
            self._about_dialog = None

    def _start_update_from_about(self, release):
        self._pending_update = release
        if self._about_dialog is not None:
            self._about_dialog.accept()
        QTimer.singleShot(
            0, lambda: self._start_update_download(release))

    def _request_toolbox_install(self):
        if (not getattr(sys, "frozen", False)
                and os.environ.get("ANHUTOOLBOX_FORCE_UPDATE") != "1"):
            if self._about_dialog is not None:
                self._about_dialog.set_toolbox_unavailable(
                    "当前运行方式不能安装工具箱，请使用安装版程序")
            return
        if self._update_download_dialog is not None:
            self._update_download_dialog.showNormal()
            self._update_download_dialog.raise_()
            self._update_download_dialog.activateWindow()
            return
        if (self._update_check_worker is not None
                and self._update_check_worker.isRunning()):
            if self._about_dialog is not None:
                self._about_dialog.set_toolbox_unavailable(
                    "正在检查更新，请稍后再安装工具箱")
            return
        if self._about_dialog is not None:
            self._about_dialog.set_toolbox_preparing()
        cleanup_update_cache()
        worker = UpdateCheckWorker(__version__, self)
        worker.release_found.connect(self._on_toolbox_release_found)
        worker.failed.connect(self._on_toolbox_release_failed)
        worker.finished.connect(self._clear_update_check_worker)
        self._update_check_worker = worker
        worker.start()

    def _on_toolbox_release_found(self, release):
        dialog = self._about_dialog
        if dialog is None:
            return
        size_mb = release.size / (1024 * 1024)
        install = ask_yes_no(
            dialog,
            "安装安护工具箱",
            "安装工具箱需要下载完整安装包（约 {:.1f} MB），"
            "安装期间程序会关闭，完成后自动重新启动。\n"
            "是否继续？".format(size_mb),
        )
        if not install:
            dialog.set_toolbox_ready("已取消安装安护工具箱")
            return
        dialog.accept()
        QTimer.singleShot(
            0, lambda: self._start_update_download(
                release, purpose="toolbox"))

    def _on_toolbox_release_failed(self, _message):
        if self._about_dialog is not None:
            self._about_dialog.set_toolbox_unavailable(
                "获取工具箱安装包失败，请检查网络后重试")

    def _manual_check_update(self):
        self._start_update_check(manual=True)

    def _start_update_check(self, manual=False):
        if manual:
            self.status_bar.showMessage("正在检查更新...", 2500)
            if self._about_dialog is not None:
                self._about_dialog.set_checking()
        if (not getattr(sys, "frozen", False)
                and os.environ.get("ANHUTOOLBOX_FORCE_UPDATE") != "1"):
            if manual:
                self.status_bar.showMessage(
                    "当前运行方式不执行在线更新检查", 4000)
                if self._about_dialog is not None:
                    self._about_dialog.set_result(
                        "当前运行方式不执行在线更新检查")
            return
        if self._update_download_dialog is not None:
            if manual:
                self.status_bar.showMessage("更新包正在下载中...", 3000)
                if self._about_dialog is not None:
                    self._about_dialog.set_result("更新包正在下载中...")
            return
        if self._downloaded_update is not None:
            if manual:
                self.status_bar.showMessage(
                    "更新包已下载，请点击顶部提示安装", 4000)
                if self._about_dialog is not None:
                    self._about_dialog.set_result(
                        "更新包已下载，请点击顶部提示安装")
            return
        if self._downloaded_toolbox is not None:
            if manual:
                self.status_bar.showMessage(
                    "工具箱安装包已下载，请点击顶部提示安装", 4000)
                if self._about_dialog is not None:
                    self._about_dialog.set_result(
                        "工具箱安装包已下载，请点击顶部提示安装")
            return
        if (self._update_check_worker is not None
                and self._update_check_worker.isRunning()):
            if manual:
                self.status_bar.showMessage("正在检查更新，请稍候...", 2500)
                if self._about_dialog is not None:
                    self._about_dialog.set_result(
                        "正在检查更新，请稍候...")
            return
        cleanup_update_cache()
        worker = UpdateCheckWorker(__version__, self)
        worker.available.connect(
            lambda release: self._on_update_available(release, manual))
        worker.up_to_date.connect(
            lambda: self._on_update_up_to_date(manual))
        worker.failed.connect(
            lambda message: self._on_update_check_failed(message, manual))
        worker.finished.connect(self._clear_update_check_worker)
        self._update_check_worker = worker
        worker.start()

    def _clear_update_check_worker(self):
        worker, self._update_check_worker = self._update_check_worker, None
        if worker is not None:
            worker.deleteLater()

    def _on_update_available(self, release, manual=False):
        if self._update_download_dialog is not None:
            return
        if (not manual
                and cfg.get("update_skipped_version", "") == release.version):
            self._clear_update_notice()
            return
        self._pending_update = release
        self._btn_update_available.setText(
            "发现新版本 V{}".format(release.version))
        self._btn_update_available.show()
        if manual:
            if self._about_dialog is not None:
                message = (
                    "发现新版本 V{}，可直接在关于窗口更新".format(
                        release.version))
            else:
                message = (
                    "发现新版本 V{}，请点击顶部提示查看".format(
                        release.version))
            self.status_bar.showMessage(message, 5000)
        if self._about_dialog is not None:
            self._about_dialog.set_update_available(release)

    def _on_update_up_to_date(self, manual=False):
        if (self._pending_update is not None
                and self._update_download_dialog is None):
            self._clear_update_notice()
        if manual:
            self.status_bar.showMessage("当前已是最新版本", 4000)
        if self._about_dialog is not None:
            self._about_dialog.set_result("当前已是最新版本")

    def _on_update_check_failed(self, _message, manual=False):
        if manual:
            self.status_bar.showMessage(
                "检查更新失败，请检查网络连接后重试", 5000)
        if self._about_dialog is not None:
            self._about_dialog.set_result(
                "检查更新失败，请检查网络连接后重试", error=True)

    def _clear_update_notice(self):
        self._pending_update = None
        self._btn_update_available.hide()

    @Slot()
    def _prompt_for_update(self):
        if self._downloaded_toolbox is not None:
            self._prompt_install_downloaded_toolbox()
            return
        if self._downloaded_update is not None:
            self._prompt_install_downloaded_update()
            return
        if self._update_download_dialog is not None:
            dialog = self._update_download_dialog
            dialog.showNormal()
            dialog.raise_()
            dialog.activateWindow()
            return
        release = self._pending_update
        if release is None:
            return
        dialog = UpdateAvailableDialog(release, self)
        dialog.exec()
        if dialog.decision == "skip":
            cfg.set("update_skipped_version", release.version)
            cfg.save()
            self._clear_update_notice()
            return
        if dialog.decision != "update":
            return
        self._start_update_download(release)

    def _start_update_download(self, release, purpose="update"):
        download = UpdateDownloadDialog(
            release, self, purpose=purpose)
        self._update_download_dialog = download
        download.download_purpose = purpose
        if purpose == "toolbox":
            self._btn_update_available.setText("正在下载工具箱")
        else:
            self._btn_update_available.setText(
                "正在下载 V{}".format(release.version))
        self._btn_update_available.show()
        download.background_requested.connect(
            lambda: self._on_update_backgrounded(release, purpose))
        download.accepted.connect(
            lambda: self._on_update_download_ready(download))
        download.rejected.connect(
            lambda: self._on_update_download_cancelled(download))
        download.finished.connect(download.deleteLater)
        download.show()

    def _on_update_backgrounded(self, release, purpose="update"):
        if purpose == "toolbox":
            self._btn_update_available.setText("后台安装工具箱")
        else:
            self._btn_update_available.setText(
                "后台更新 V{}".format(release.version))
        self._btn_update_available.show()
        if purpose == "toolbox":
            self.status_bar.showMessage(
                "工具箱安装包正在后台下载，可点击顶部提示恢复进度", 5000)
        else:
            self.status_bar.showMessage(
                "更新包正在后台下载，可点击顶部提示恢复进度", 5000)

    def _on_update_download_ready(self, dialog):
        if dialog is not self._update_download_dialog:
            return
        self._update_download_dialog = None
        if dialog.download_path:
            if getattr(dialog, "download_purpose", "update") == "toolbox":
                self._downloaded_toolbox = (
                    dialog.release, dialog.download_path)
                self._prompt_install_downloaded_toolbox()
            else:
                self._downloaded_update = (
                    dialog.release, dialog.download_path)
                self._prompt_install_downloaded_update()

    def _prompt_install_downloaded_update(self):
        if self._downloaded_update is None:
            return
        release, installer_path = self._downloaded_update
        if not os.path.isfile(installer_path):
            self._downloaded_update = None
            self._btn_update_available.setText(
                "发现新版本 V{}".format(release.version))
            show_error(
                self, "更新包不存在",
                "已下载的更新包不存在，请重新检查更新。")
            return
        install = ask_yes_no(
            self,
            "安装更新",
            "更新包已下载完成。\n"
            "是否立即安装新版本，并在安装完成后自动重新启动？",
        )
        if not install:
            self._btn_update_available.setText(
                "更新已下载，点击安装")
            self.status_bar.showMessage(
                "已暂缓安装，可点击顶部提示继续安装", 5000)
            return
        self._downloaded_update = None
        self._install_downloaded_update(release, installer_path)

    def _prompt_install_downloaded_toolbox(self):
        if self._downloaded_toolbox is None:
            return
        release, installer_path = self._downloaded_toolbox
        if not os.path.isfile(installer_path):
            self._downloaded_toolbox = None
            self._btn_update_available.hide()
            show_error(
                self, "工具箱安装包不存在",
                "已下载的工具箱安装包不存在，请重新安装工具箱。")
            return
        install = ask_yes_no(
            self,
            "安装安护工具箱",
            "工具箱安装包已下载完成。\n"
            "是否立即安装，并在安装完成后自动重新启动？",
        )
        if not install:
            self._btn_update_available.setText(
                "工具箱已下载，点击安装")
            self.status_bar.showMessage(
                "已暂缓安装工具箱，可点击顶部提示继续安装", 5000)
            return
        self._downloaded_toolbox = None
        self._install_downloaded_toolbox(release, installer_path)

    def _on_update_download_cancelled(self, dialog):
        if dialog is not self._update_download_dialog:
            return
        self._update_download_dialog = None
        if getattr(dialog, "download_purpose", "update") == "toolbox":
            if self._pending_update is not None:
                self._btn_update_available.setText(
                    "发现新版本 V{}".format(
                        self._pending_update.version))
                self._btn_update_available.show()
            else:
                self._btn_update_available.hide()
            return
        if self._pending_update is not None:
            self._btn_update_available.setText(
                "发现新版本 V{}".format(self._pending_update.version))
            self._btn_update_available.show()

    def _install_downloaded_toolbox(self, release, installer_path):
        try:
            launch_updater(
                os.path.dirname(os.path.abspath(sys.executable)),
                os.path.abspath(sys.executable),
                installer_path,
                release,
                merge_tasks="installtoolbox",
            )
        except Exception as exc:
            show_error(
                self, "安装工具箱失败",
                "无法启动工具箱安装程序：\n{}".format(exc))
            self._btn_update_available.setText(
                "工具箱已下载，点击安装")
            self._btn_update_available.show()
            return
        self._save_current_project()
        self._save_global()
        self.close()

    def _install_downloaded_update(self, release, installer_path):
        try:
            launch_updater(
                os.path.dirname(os.path.abspath(sys.executable)),
                os.path.abspath(sys.executable),
                installer_path,
                release,
            )
        except Exception as exc:
            show_error(
                self, "更新失败",
                "无法启动更新程序：\n{}".format(exc))
            if self._pending_update is not None:
                self._btn_update_available.setText(
                    "发现新版本 V{}".format(
                        self._pending_update.version))
                self._btn_update_available.show()
            return
        self._save_current_project()
        self._save_global()
        self.close()

    def _save_global(self):
        """只保存与项目无关的全局偏好; 项目内容由 _save_current_project 负责"""
        # 工具页会临时隐藏预设面板，但用户的开关意图仍保留在按钮上。
        cfg.set("preset_visible", self._btn_toggle_preset.isChecked())
        cfg.set("preset_splitter", list(self._preset_splitter.sizes()))
        cfg.set("last_project", self._current_project or "")
        cfg.save()

    def _connect_signals(self):
        self._btn_about.clicked.connect(self._show_about)
        self._btn_update_available.clicked.connect(self._prompt_for_update)
        self.sidebar.mode_changed.connect(self._on_mode_changed)
        self.sidebar.connect_clicked.connect(self._on_connect)
        self.sidebar.disconnect_clicked.connect(self._on_disconnect)
        self.sidebar.port_refresh_clicked.connect(self._refresh_ports)
        self.sidebar.project_changed.connect(self._on_project_selected)
        self.sidebar.project_menu_requested.connect(self._show_project_menu)
        self._mqtt_page.subscription_changed.connect(
            self._on_mqtt_subscriptions_changed)
        self._mqtt_page.publish_requested.connect(self._on_mqtt_publish)
        self._websocket_page.send_requested.connect(
            self._on_websocket_send)
        self._websocket_page.ping_requested.connect(
            self._on_websocket_ping)
        self._websocket_page.connect_requested.connect(
            lambda: self._on_connect("websocket"))
        self._websocket_page.disconnect_requested.connect(
            lambda: self._on_disconnect("websocket"))
        self._http_page.request_status.connect(self._log)
        self._http_page.save_requested.connect(self._save_current_project)
        self._http_page.interfaces_changed.connect(
            self.sidebar.set_http_interfaces)
        self._http_page.folders_changed.connect(
            self.sidebar.set_http_folders)
        self._http_page.active_interface_changed.connect(
            self.sidebar.select_http_interface)
        self._http_page.new_project_import_requested.connect(
            self._on_http_import_as_new_project)
        self.sidebar.http_interface_selected.connect(
            self._http_page.open_interface)
        self.sidebar.http_new_requested.connect(
            self._http_page.new_document)
        self.sidebar.http_import_requested.connect(
            lambda: self._http_page.import_interfaces(
                self._current_project))
        self.sidebar.http_export_requested.connect(
            lambda: self._http_page.export_interfaces(
                self._current_project))
        self.sidebar.http_folder_selected.connect(
            self._http_page.set_current_folder)
        self.sidebar.http_new_folder_requested.connect(
            self._http_page.create_folder)
        self.sidebar.http_rename_requested.connect(
            self._rename_http_item)
        self.sidebar.http_move_requested.connect(
            self._http_page.move_interface)
        self.sidebar.http_duplicate_requested.connect(
            self._http_page.duplicate_interface)
        self.sidebar.http_delete_interface_requested.connect(
            self._http_page.delete_interface)
        self.sidebar.http_delete_folder_requested.connect(
            self._http_page.delete_folder)
        for page in self._stream_pages.values():
            page.send_bar.send_data.connect(self._on_send_data)
            page.send_bar.repeat_tick.connect(self._on_repeat_tick)
            page.send_bar.chk_dtr.toggled.connect(self._on_dtr_toggled)
            page.send_bar.chk_rts.toggled.connect(self._on_rts_toggled)
            page.log_panel.cleared.connect(self._on_log_cleared)
            page.log_panel.file_error.connect(self._on_error)
            page.preset_toggled.connect(self._on_toggle_preset)
        self._sync_timer = QTimer()
        self._sync_timer.timeout.connect(self._sync_preset_text)
        self._sync_timer.start(500)

    @Slot(str, str, str)
    def _rename_http_item(self, kind, item_id, name):
        if kind == "folder":
            self._http_page.rename_folder(item_id, name)
        elif kind == "interface":
            self._http_page.rename_interface(item_id, name)

    @Slot(str, object, str)
    def _on_http_import_as_new_project(
            self, project_name, transfer_result, conflict_policy):
        base_name = str(project_name or "导入项目").strip()
        actual_name = self._pm.create(
            base_name, self._default_profile())
        if not actual_name:
            show_error(
                self, "导入失败",
                "无法创建导入项目，请检查数据目录权限或磁盘空间。")
            return
        self._reload_project_list(actual_name)
        self.sidebar._mode_group.button(5).click()
        imported, skipped = self._http_page._apply_transfer(
            transfer_result, None, conflict_policy)
        self._save_current_project()
        self._http_page._show_http_toast("导入成功")
        self.status_bar.showMessage(
            "已创建项目「{}」：导入 {} 个接口，跳过 {} 个".format(
                actual_name, imported, skipped),
            8000,
        )

    def _sync_preset_text(self):
        self.preset_panel.set_current_text(
            self.send_bar.chk_hex.isChecked(),
            self.send_bar.text.toPlainText()
        )
        self._autosave_project()

    def _autosave_project(self):
        """配置有变化就写回当前项目(快照比对, 无变化不写盘)"""
        if (self._applying or not self._current_project
                or self._project_load_failed):
            return
        snap = self._snapshot_ui()
        if snap == self._last_snapshot:
            return
        self._persist_project_snapshot(snap)

    def _persist_project_snapshot(self, snap):
        if self._pm.save(self._current_project, snap):
            self._last_snapshot = snap
            self._last_project_save_error = ""
            return True
        message = "项目保存失败，请检查数据目录权限或磁盘空间。"
        if message != self._last_project_save_error:
            self._last_project_save_error = message
            self.status_bar.showMessage(message, 15000)
            self.log_panel.text.appendPlainText("[错误] " + message + "\n")
        return False

    # ==================== 项目管理 ====================
    def _init_projects(self):
        """启动时准备项目: 一个项目都没有就先建一个默认项目"""
        names = self._pm.names()
        if not names:
            self._apply_legacy_settings_to_ui()
            created = self._pm.create(
                DEFAULT_PROJECT_NAME, self._snapshot_ui())
            if not created:
                message = "无法创建默认项目，请检查数据目录权限或磁盘空间。"
                self.status_bar.showMessage(message, 15000)
                self.log_panel.text.appendPlainText("[错误] " + message + "\n")
                return
            names = self._pm.names()
        last = cfg.get("last_project", "")
        name = last if last in names else names[0]
        self.sidebar.set_projects(names, name)
        self._load_project(name)

    def _default_profile(self):
        """生成一份「全新项目」的配置: 等价于第一次启动时的默认状态。

        做法: 临时把空配置应用到界面再取快照, 这样默认值只在 _apply_profile 里定义一次,
        不会在两处硬编码后互相不一致。取完快照立刻还原界面, 期间 _applying 保持 True,
        避免自动保存把这份临时状态写回当前项目。
        """
        backup = self._snapshot_ui()
        self._applying = True
        try:
            self._apply_profile({})       # 空配置 -> 所有项落到默认值, 预设也一并清空
            snap = self._snapshot_ui()
            self._apply_profile(backup)   # 还原成切换前的界面
        finally:
            self._applying = False
        snap.pop("name", None)
        return snap

    @staticmethod
    def _snapshot_stream(page):
        send = page.send_bar
        log = page.log_panel
        return {
            "send": {
                "hex_send": send.chk_hex.isChecked(),
                "crlf": send.chk_crlf.isChecked(),
                "interval": send.sp_interval.value(),
                "checksum": send.cb_checksum.currentText(),
                "start_byte": send.sp_start.value(),
                "end_byte_text": send.cb_end.currentText(),
                "dtr": send.chk_dtr.isChecked(),
                "rts": send.chk_rts.isChecked(),
                "draft": send.text.toPlainText(),
            },
            "log": {
                "hex_display": log.chk_hex.isChecked(),
                "timestamp": log.chk_timestamp.isChecked(),
                "timeout": log.sp_timeout.value(),
            },
        }

    def _snapshot_ui(self):
        """把当前界面状态打包成项目数据"""
        active_stream = self._snapshot_stream(self._stream_page())
        return {
            "format": 1,
            "mode": self.sidebar.current_mode,
            "serial": {
                "port": self.sidebar.cb_port.currentText(),
                "baud": self.sidebar.cb_baud.currentText(),
                "data": self.sidebar.cb_data.currentText(),
                "stop": self.sidebar.cb_stop.currentText(),
                "parity": self.sidebar.cb_parity.currentText(),
                "flow": self.sidebar.cb_flow.currentText(),
            },
            "tcpserver": {
                "port": self.sidebar.sp_server_port.value(),
                "client_timeout": self.sidebar.sp_client_timeout.value(),
            },
            "tcpclient": {
                "host": self.sidebar.le_client_host.text(),
                "port": self.sidebar.sp_client_port.value(),
                "local_port": self.sidebar.le_local_port.text().strip(),
            },
            "mqtt": {
                "host": self.sidebar.le_mqtt_host.text(),
                "port": self.sidebar.sp_mqtt_port.value(),
                "client_id": self.sidebar.le_mqtt_client_id.text(),
                "username": self.sidebar.le_mqtt_user.text(),
                "password": self.sidebar.le_mqtt_password.text(),
                "keepalive": self.sidebar.sp_mqtt_keepalive.value(),
                "protocol": self.sidebar.cb_mqtt_protocol.currentText(),
                "clean_session": self.sidebar.chk_mqtt_clean.isChecked(),
                "auto_reconnect": self.sidebar.chk_mqtt_reconnect.isChecked(),
                "tls": self.sidebar.chk_mqtt_tls.isChecked(),
                **self._mqtt_page.snapshot(),
            },
            "websocket": {
                "origin": self.sidebar.le_ws_origin.text(),
                "subprotocol": self.sidebar.le_ws_protocol.text(),
                "ping_interval": self.sidebar.sp_ws_ping.value(),
                "auto_reconnect": self.sidebar.chk_ws_reconnect.isChecked(),
                "verify_tls": self.sidebar.chk_ws_verify.isChecked(),
                **self._websocket_page.snapshot(),
            },
            "http": self._http_page.snapshot(),
            "streams": {
                key: self._snapshot_stream(page)
                for key, page in self._stream_pages.items()
            },
            # 保留旧字段，兼容已有项目和旧版程序。
            "send": active_stream["send"],
            "log": active_stream["log"],
            "presets": self.preset_panel.dump_presets(),
        }

    def _load_project(self, name):
        """把项目数据应用到界面"""
        profile = self._pm.load(name)
        self._project_load_failed = profile is None
        profile = profile or {}
        self._applying = True
        try:
            self._apply_profile(profile)
        finally:
            self._applying = False
        self._current_project = name
        self.sidebar.set_current_project(name)
        self._last_snapshot = self._snapshot_ui()
        cfg.set("last_project", name)
        cfg.save()
        self._check_port_exists()
        self._update_stats()
        if self._project_load_failed:
            message = (
                "项目「{}」读取失败，原文件已保护；本次修改不会自动保存。"
                .format(name))
            self.status_bar.showMessage(message, 15000)
            self.log_panel.text.appendPlainText("[提示] " + message + "\n")
        else:
            self.status_bar.showMessage("已切换到项目: {}".format(name), 3000)

    def _save_current_project(self):
        """把当前界面状态写回当前项目"""
        if (self._applying or not self._current_project
                or self._project_load_failed):
            return
        snap = self._snapshot_ui()
        self._persist_project_snapshot(snap)

    def _on_presets_changed(self, presets):
        """预设内容变化 -> 立即写回当前项目"""
        if self._applying or not self._current_project:
            return
        snap = self._snapshot_ui()
        self._persist_project_snapshot(snap)

    def _check_port_exists(self):
        """项目里的串口号在本机不存在时给出提示(只提示, 不自动改)"""
        if self.sidebar.current_mode != "serial":
            self.sidebar.set_project_warning("")
            return
        port = self.sidebar.cb_port.currentText().strip().upper()
        if not port:
            self.sidebar.set_project_warning("")
            return
        try:
            avail = {p.device.upper() for p in serial.tools.list_ports.comports()}
        except Exception:
            avail = set()
        if port not in avail:
            self.sidebar.set_project_warning("{} 在本机不存在，请重新选择串口".format(port))
        else:
            self.sidebar.set_project_warning("")

    @staticmethod
    def _apply_stream_config(page, send_data, log_data):
        send = page.send_bar
        log = page.log_panel
        d = _profile_dict(send_data)
        send.chk_crlf.setChecked(_profile_bool(d.get("crlf", True), True))
        send.chk_hex.setChecked(_profile_bool(d.get("hex_send", False), False))
        send.sp_interval.setValue(
            _profile_int(d.get("interval", 1000), 1000, 5, 99999))
        checksum = str(d.get("checksum", "ModbusCRC16") or "ModbusCRC16")
        index = send.cb_checksum.findText(checksum)
        if index >= 0:
            send.cb_checksum.setCurrentIndex(index)
        else:
            send.cb_checksum.setCurrentText("ModbusCRC16")
        send.sp_start.setValue(
            _profile_int(d.get("start_byte", 1), 1, 1, 99999))
        send.cb_end.setCurrentText(str(d.get("end_byte_text", "末尾")))
        send.chk_dtr.setChecked(_profile_bool(d.get("dtr", False), False))
        send.chk_rts.setChecked(_profile_bool(d.get("rts", False), False))
        send.text.setPlainText(str(d.get("draft", "")))

        g = _profile_dict(log_data)
        log.chk_hex.setChecked(
            _profile_bool(g.get("hex_display", True), True))
        log.chk_timestamp.setChecked(
            _profile_bool(g.get("timestamp", True), True))
        log.sp_timeout.setValue(
            _profile_int(g.get("timeout", 0), 0, 0, 9999))

    def _apply_profile(self, p):
        """把项目数据写进各个控件(调用方负责置 _applying 抑制自动保存)"""
        p = _profile_dict(p)
        mode = str(p.get("mode", "serial") or "serial").strip().lower()
        idx = COMM_MODE_INDEX.get(mode, 0)
        self.sidebar._mode_group.button(idx).setChecked(True)
        self.sidebar._on_mode_changed(idx)

        s = _profile_dict(p.get("serial"))
        self.sidebar.cb_port.setCurrentText(str(s.get("port", "COM1")))
        self.sidebar.cb_baud.setCurrentText(str(s.get("baud", "115200")))
        self.sidebar.cb_data.setCurrentText(str(s.get("data", "8")))
        self.sidebar.cb_stop.setCurrentText(str(s.get("stop", "1")))
        self.sidebar.cb_parity.setCurrentText(str(s.get("parity", "None")))
        self.sidebar.cb_flow.setCurrentText(str(s.get("flow", "None")))

        t = _profile_dict(p.get("tcpserver"))
        self.sidebar.sp_server_port.setValue(
            _profile_int(t.get("port", 8888), 8888, 1, 65535))
        self.sidebar.sp_client_timeout.setValue(
            _profile_int(t.get("client_timeout", 30), 30, 0, 3600))
        c = _profile_dict(p.get("tcpclient"))
        host = str(c.get("host", "127.0.0.1") or "127.0.0.1").strip()
        self.sidebar.le_client_host.setText(host)
        self.sidebar.sp_client_port.setValue(
            _profile_int(c.get("port", 8888), 8888, 1, 65535))
        lp = str(c.get("local_port", "") or "")
        local_port = _profile_int(lp, 0, 0, 65535) if lp.isdigit() else 0
        self.sidebar.le_local_port.setText(
            str(local_port) if local_port > 0 else "")

        mq = _profile_dict(p.get("mqtt"))
        self.sidebar.le_mqtt_host.setText(
            str(mq.get("host") or "broker.emqx.io"))
        self.sidebar.sp_mqtt_port.setValue(
            _profile_int(mq.get("port", 1883), 1883, 1, 65535))
        self.sidebar.le_mqtt_client_id.setText(
            str(mq.get("client_id") or ""))
        self.sidebar.le_mqtt_user.setText(str(mq.get("username") or ""))
        self.sidebar.le_mqtt_password.setText(
            str(mq.get("password") or ""))
        self.sidebar.sp_mqtt_keepalive.setValue(
            _profile_int(mq.get("keepalive", 60), 60, 5, 3600))
        self.sidebar.cb_mqtt_protocol.setCurrentText(
            str(mq.get("protocol") or "MQTT 3.1.1"))
        self.sidebar.chk_mqtt_clean.setChecked(
            _profile_bool(mq.get("clean_session", True), True))
        self.sidebar.chk_mqtt_reconnect.setChecked(
            _profile_bool(mq.get("auto_reconnect", True), True))
        self.sidebar.chk_mqtt_tls.setChecked(
            _profile_bool(mq.get("tls", False), False))
        self._mqtt_page.apply(mq)

        ws = _profile_dict(p.get("websocket"))
        self.sidebar.le_ws_origin.setText(str(ws.get("origin") or ""))
        self.sidebar.le_ws_protocol.setText(
            str(ws.get("subprotocol") or ""))
        self.sidebar.sp_ws_ping.setValue(
            _profile_int(ws.get("ping_interval", 30), 30, 0, 3600))
        self.sidebar.chk_ws_reconnect.setChecked(
            _profile_bool(ws.get("auto_reconnect", True), True))
        self.sidebar.chk_ws_verify.setChecked(
            _profile_bool(ws.get("verify_tls", True), True))
        self._websocket_page.apply(ws)

        self._http_page.apply(_profile_dict(p.get("http")))

        legacy_send = _profile_dict(p.get("send"))
        legacy_log = _profile_dict(p.get("log"))
        streams = _profile_dict(p.get("streams"))
        for key, page in self._stream_pages.items():
            stream = _profile_dict(streams.get(key))
            send_data = stream.get("send")
            log_data = stream.get("log")
            if not isinstance(send_data, dict):
                send_data = legacy_send
            if not isinstance(log_data, dict):
                log_data = legacy_log
            self._apply_stream_config(page, send_data, log_data)
        serial_send = _profile_dict(
            _profile_dict(streams.get("serial")).get("send")
            or legacy_send)
        self._has_dtr_rts = (
            "dtr" in serial_send or "rts" in serial_send)

        self.preset_panel.load_from_project(_profile_list(p.get("presets")))

    def _switch_project(self, name, confirm=True):
        """切换项目: 存旧项目 -> 停自动动作 -> 断开 -> 应用新项目"""
        if name == self._current_project:
            return True
        if confirm and self._active_worker:
            if not ask_yes_no(
                self, "切换项目", "切换项目会断开当前连接，是否继续？",
                confirm_text="切换",
            ):
                self.sidebar.set_current_project(self._current_project)
                return False
        self._save_current_project()
        # 停掉所有"会自己动"的东西, 免得老节奏打到新连接上
        for page in self._stream_pages.values():
            if page.send_bar.chk_repeat.isChecked():
                page.send_bar.chk_repeat.setChecked(False)
            page.send_bar.stop_repeat()
            page.log_panel.reset_runtime_state()
        self._mqtt_page.reset_runtime_state()
        self._websocket_page.reset_runtime_state()
        self.preset_panel.stop_loops()
        if self._active_worker:
            self._on_disconnect(self.sidebar.current_mode)
        self._load_project(name)
        return True

    def _on_project_selected(self, name):
        """下拉框选中了另一个项目"""
        self._switch_project(name)

    def _reload_project_list(self, select=None):
        """重建项目下拉框(新建/重命名/删除/导入后调用)"""
        names = self._pm.names()
        if not names:
            created = self._pm.create(
                DEFAULT_PROJECT_NAME, self._default_profile())
            if not created:
                show_error(
                    self, "项目创建失败",
                    "无法创建默认项目，请检查数据目录权限或磁盘空间。")
                names = []
            else:
                names = [created]
        if not names:
            self.sidebar.set_projects([], "")
            return
        target = select or self._current_project or names[0]
        if target not in names:
            target = names[0]
        self.sidebar.set_projects(names, target)
        if target != self._current_project:
            self._switch_project(target)
        else:
            self.sidebar.set_current_project(target)
        self._check_port_exists()

    def _show_project_menu(self):
        """项目下拉框右侧的齿轮菜单"""
        m = prepare_menu(QMenu(self))
        a_new = m.addAction("新建项目...")
        a_ren = m.addAction("重命名当前项目...")
        a_dup = m.addAction("复制当前项目为...")
        m.addSeparator()
        a_imp = m.addAction("从文件导入...")
        a_exp = m.addAction("导出当前项目...")
        a_dir = m.addAction("打开项目文件夹")
        m.addSeparator()
        a_del = m.addAction("删除当前项目")
        has = bool(self._current_project)
        for a in (a_ren, a_dup, a_exp, a_del):
            a.setEnabled(has)
        act = m.exec(self.sidebar.project_menu_pos())
        if act is None:
            return
        if act == a_new:
            self._project_new()
        elif act == a_ren:
            self._project_rename()
        elif act == a_dup:
            self._project_duplicate()
        elif act == a_imp:
            self._project_import()
        elif act == a_exp:
            self._project_export()
        elif act == a_dir:
            self._open_project_dir()
        elif act == a_del:
            self._project_delete()

    def _project_new(self):
        name, ok = get_text(
            self, "新建项目", "请输入新项目的名称",
            text="项目{}".format(len(self._pm.names()) + 1))
        name = (name or "").strip()
        if not ok or not name:
            return
        self._save_current_project()
        # 新项目用默认配置(含空预设), 不继承当前项目的任何设置
        actual_name = self._pm.create(name, self._default_profile())
        if not actual_name:
            show_error(
                self, "新建失败",
                "项目无法保存，请检查数据目录权限或磁盘空间。")
            return
        self._reload_project_list(actual_name)

    def _project_rename(self):
        old = self._current_project
        if not old:
            return
        name, ok = get_text(self, "重命名项目", "请输入新的项目名称", text=old)
        name = (name or "").strip()
        if not ok or not name or name == old:
            return
        self._save_current_project()
        self._current_project = self._pm.rename(old, name)
        self._reload_project_list(self._current_project)

    def _project_duplicate(self):
        old = self._current_project
        if not old:
            return
        name, ok = get_text(self, "复制项目", "请输入副本的项目名称", text=old + " 副本")
        name = (name or "").strip()
        if not ok or not name:
            return
        self._save_current_project()
        data = self._pm.load(old) or self._snapshot_ui()
        actual_name = self._pm.create(name, data)
        if not actual_name:
            show_error(
                self, "复制失败",
                "项目副本无法保存，请检查数据目录权限或磁盘空间。")
            return
        self._reload_project_list(actual_name)

    def _project_delete(self):
        old = self._current_project
        if not old:
            return
        if not ask_yes_no(
            self, "删除项目",
            "确定删除项目「{}」吗？\n该项目下的预设命令和配置会一并删除，且无法恢复。".format(old),
            confirm_text="删除", danger=True,
        ):
            return
        for page in self._stream_pages.values():
            if page.send_bar.chk_repeat.isChecked():
                page.send_bar.chk_repeat.setChecked(False)
            page.send_bar.stop_repeat()
            page.log_panel.reset_runtime_state()
        self._mqtt_page.reset_runtime_state()
        self._websocket_page.reset_runtime_state()
        self.preset_panel.stop_loops()
        if self._active_worker:
            self._on_disconnect(self.sidebar.current_mode)
        self._pm.delete(old)
        self._current_project = None
        self._reload_project_list()

    def _project_import(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入项目", "", "JSON 文件 (*.json)")
        if not path:
            return
        name = self._pm.import_from(path)
        if not name:
            show_error(self, "导入失败", "项目文件格式不正确或无法读取。")
            return
        self._reload_project_list(name)
        show_success(self, "导入成功", "已导入项目「{}」".format(name))

    def _project_export(self):
        old = self._current_project
        if not old:
            return
        self._save_current_project()
        data = self._pm.load(old)
        if data is not None and contains_sensitive_values(data):
            if not ask_yes_no(
                self, "导出包含凭据",
                "项目文件包含明文密码、Token 或其他凭据。\n"
                "导出后请妥善保管，确定继续导出吗？",
                confirm_text="继续导出", danger=True,
            ):
                return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出项目", "{}.json".format(old), "JSON 文件 (*.json)")
        if not path:
            return
        if self._pm.export_to(old, path):
            show_success(self, "导出成功", "已导出到：\n{}".format(path))
        else:
            show_error(self, "导出失败", "无法写入该文件。")

    def _open_project_dir(self):
        try:
            os.startfile(self._pm.dir)
        except Exception as e:
            show_warning(self, "提示", "无法打开项目文件夹：\n{}".format(e))

    @Slot(str)
    def _on_mode_changed(self, mode: str):
        self._connection_mode = mode
        if self._active_worker: self._on_disconnect(mode)
        old_page = self._stream_page()
        if old_page is not None:
            if old_page.send_bar.chk_repeat.isChecked():
                old_page.send_bar.chk_repeat.setChecked(False)
            old_page.send_bar.stop_repeat()
        self.preset_panel.stop_loops()
        if mode in self._stream_pages:
            self._active_stream_key = mode
        pages = {
            "serial": self._stream_pages["serial"],
            "tcpserver": self._stream_pages["tcpserver"],
            "tcpclient": self._stream_pages["tcpclient"],
            "mqtt": self._mqtt_page,
            "websocket": self._websocket_page,
            "http": self._http_page,
        }
        page = pages.get(mode, self._stream_pages["serial"])
        self._comm_stack.setCurrentWidget(page)
        stream_mode = mode in ("serial", "tcpserver", "tcpclient")
        self.preset_panel.setVisible(
            stream_mode and self._stream_page(mode).btn_toggle_preset.isChecked())
        labels = {
            "serial": "串口", "tcpserver": "TCPServer",
            "tcpclient": "TCPClient", "mqtt": "MQTT",
            "websocket": "WebSocket", "http": "HTTP",
        }
        self._lbl_conn_type.setText(labels.get(mode,mode))
        self._lbl_local.setText(""); self._lbl_arrow.setText("")
        self._lbl_remote.setText(""); self._lbl_stats.setText("")
        self._lbl_dot.setStyleSheet("color:#AAA;font-size:12px")
        self._lbl_status_text.setText(
            "就绪" if mode == "http" else "未连接")
        cfg.set("mode", mode); cfg.save()
        self._project_autosave_soon()

    @Slot(str)
    def _on_connect(self, mode: str):
        if mode == "serial": self._connect_serial()
        elif mode == "tcpserver": self._connect_tcp_server()
        elif mode == "tcpclient": self._connect_tcp_client()
        elif mode == "mqtt": self._connect_mqtt()
        elif mode == "websocket": self._connect_websocket()

    def _connect_serial(self):
        port = self.sidebar.cb_port.currentText().strip()
        if not port:
            show_warning(self, "提示", "请选择串口号"); return
        try:
            parity_map = {"None":"N","Even":"E","Odd":"O","Mark":"M","Space":"S"}
            ser = serial.Serial(
                port=port, baudrate=int(self.sidebar.cb_baud.currentText()),
                bytesize=int(self.sidebar.cb_data.currentText()),
                stopbits={"1":serial.STOPBITS_ONE,"1.5":serial.STOPBITS_ONE_POINT_FIVE,"2":serial.STOPBITS_TWO}[self.sidebar.cb_stop.currentText()],
                parity=parity_map[self.sidebar.cb_parity.currentText()],
                timeout=0.1, write_timeout=0.5,
                rtscts=(self.sidebar.cb_flow.currentText()=="RTS/CTS"),
                xonxoff=(self.sidebar.cb_flow.currentText()=="XON/XOFF")
            )
            self._serial_worker.set_serial(ser); self._serial_worker.start()
            self._active_worker = self._serial_worker
            self.sidebar.set_connected(True); self.sidebar.set_controls_enabled(False)
            self.send_bar.chk_dtr.setEnabled(True); self.send_bar.chk_rts.setEnabled(True)
            # DTR/RTS 优先用项目里保存的值; 项目没记录过才回落到硬件初始值
            if self._has_dtr_rts:
                ser.dtr = self.send_bar.chk_dtr.isChecked()
                ser.rts = self.send_bar.chk_rts.isChecked()
            else:
                self.send_bar.chk_dtr.setChecked(ser.dtr)
                self.send_bar.chk_rts.setChecked(ser.rts)
            self._lbl_conn_type.setText("串口")
            self._lbl_dot.setStyleSheet("color:#107C10;font-size:12px")
            self._lbl_status_text.setText("已连接")
            self._lbl_local.setText("{} {}bps,{},{},{}".format(port,self.sidebar.cb_baud.currentText(),self.sidebar.cb_data.currentText(),self.sidebar.cb_parity.currentText(),self.sidebar.cb_stop.currentText()))
            self.status_bar.showMessage("串口已打开: {}".format(port),3000)
        except Exception as e:
            show_error(self, "错误", "无法打开串口:\n{}".format(e))

    def _connect_tcp_server(self):
        port = self.sidebar.sp_server_port.value()
        timeout_s = self.sidebar.sp_client_timeout.value()
        if self._tcp_server.isRunning():
            self._tcp_server.stop()
        self._tcp_server.set_client_timeout(timeout_s)
        self._tcp_server.configure(port); self._tcp_server.start()
        self._active_worker = self._tcp_server
        self.sidebar.set_connected(True); self.sidebar.set_controls_enabled(False)
        lip = self._get_local_ip(); self._local_addr = "{}:{}".format(lip,port)
        self._lbl_conn_type.setText("TCPServer")
        # bind/listen 的结果来自后台线程；成功前不能提前显示“已启动”。
        self._lbl_dot.setStyleSheet("color:#AAA;font-size:12px")
        self._lbl_status_text.setText("启动中...")
        self._lbl_local.setText("本地IP={}".format(self._local_addr))
        self.status_bar.showMessage("正在启动 TCP服务器 {}:{}...".format(lip,port),3000)

    def _connect_tcp_client(self):
        host = self.sidebar.le_client_host.text().strip()
        port = self.sidebar.sp_client_port.value()
        # 本地端口: 留空 = 随机(0); 填数字 = 固定端口
        _lp = self.sidebar.le_local_port.text().strip()
        local_port = int(_lp) if _lp.isdigit() else 0
        if not host: show_warning(self, "提示", "请输入远端地址"); return
        # 若旧连接仍在重试/运行中, 先停止再重新连接 (QThread 不能对运行中的线程重复 start)
        if self._tcp_client.isRunning():
            self._tcp_client.stop()
        self._tcp_client.configure(host, port, local_port); self._tcp_client.start()
        self._active_worker = self._tcp_client
        self.sidebar.set_connected(True); self.sidebar.set_controls_enabled(False)
        self._remote_addr = "{}:{}".format(host,port)
        self._lbl_conn_type.setText("TCPClient")
        self._lbl_dot.setStyleSheet("color:#D83B01;font-size:12px")
        self._lbl_status_text.setText("连接中...")
        self._lbl_remote.setText(self._remote_addr)
        self.status_bar.showMessage("TCP客户端连接中 {}:{}...".format(host,port),3000)

    def _connect_mqtt(self):
        error, field = self._validate_mqtt_fields()
        if error:
            show_warning(self, "无法连接", error)
            if field is not None:
                field.setFocus()
                if hasattr(field, "selectAll"):
                    field.selectAll()
            return
        host = self.sidebar.le_mqtt_host.text().strip()
        if self._mqtt_worker.isRunning():
            self._mqtt_worker.stop()
        config = {
            "host": host,
            "port": self.sidebar.sp_mqtt_port.value(),
            "client_id": self.sidebar.le_mqtt_client_id.text().strip(),
            "username": self.sidebar.le_mqtt_user.text(),
            "password": self.sidebar.le_mqtt_password.text(),
            "keepalive": self.sidebar.sp_mqtt_keepalive.value(),
            "protocol": self.sidebar.cb_mqtt_protocol.currentText(),
            "clean_session": self.sidebar.chk_mqtt_clean.isChecked(),
            "auto_reconnect": self.sidebar.chk_mqtt_reconnect.isChecked(),
            "tls": self.sidebar.chk_mqtt_tls.isChecked(),
        }
        self._mqtt_worker.configure(config)
        self._mqtt_auto_reconnect = bool(config["auto_reconnect"])
        self._mqtt_worker.set_subscriptions(
            self._mqtt_page.enabled_subscriptions())
        self._mqtt_worker.start()
        self._active_worker = self._mqtt_worker
        self.sidebar.set_connected(True)
        self.sidebar.set_controls_enabled(False)
        self._mqtt_page.set_connected(False)
        self._mqtt_rx_count = 0
        self._mqtt_tx_count = 0
        self._lbl_dot.setStyleSheet("color:#AAA;font-size:12px")
        self._lbl_status_text.setText("连接中...")
        self._lbl_local.setText("服务端={}:{}".format(
            host, self.sidebar.sp_mqtt_port.value()))
        self._lbl_remote.setText("")
        self._lbl_stats.setText("Rx:0 | Tx:0")
        self.status_bar.showMessage("正在连接 MQTT 服务端...", 3000)

    def _validate_mqtt_fields(self):
        host = self.sidebar.le_mqtt_host.text().strip()
        if not host:
            return "请填写服务端IP。", self.sidebar.le_mqtt_host
        if self.sidebar.sp_mqtt_port.value() <= 0:
            return "请填写有效端口。", self.sidebar.sp_mqtt_port
        username = self.sidebar.le_mqtt_user.text().strip()
        password = self.sidebar.le_mqtt_password.text().strip()
        if username and not password:
            return (
                "请填写密码。",
                self.sidebar.le_mqtt_password,
            )
        if password and not username:
            return (
                "请填写用户名。",
                self.sidebar.le_mqtt_user,
            )
        return None, None

    def _connect_websocket(self):
        url = self._websocket_page.url()
        if not url:
            show_warning(self, "提示", "请输入 WebSocket URL")
            return
        if self._websocket_worker.isRunning():
            self._websocket_worker.stop()
        headers = {
            key.strip(): value
            for key, value in self._websocket_page.headers()
            if key.strip()
        }
        origin = self.sidebar.le_ws_origin.text().strip()
        protocols = [
            item.strip() for item in
            self.sidebar.le_ws_protocol.text().split(",")
            if item.strip()
        ]
        config = {
            "url": url,
            "headers": headers,
            "origin": origin,
            "subprotocols": protocols or None,
            "ping_interval": self.sidebar.sp_ws_ping.value(),
            "auto_reconnect": self.sidebar.chk_ws_reconnect.isChecked(),
            "verify_tls": self.sidebar.chk_ws_verify.isChecked(),
        }
        self._websocket_worker.configure(config)
        self._websocket_auto_reconnect = bool(config["auto_reconnect"])
        self._websocket_worker.start()
        self._active_worker = self._websocket_worker
        self.sidebar.set_connected(True)
        self.sidebar.set_controls_enabled(False)
        self._websocket_page.set_connected(False)
        self._ws_rx_count = 0
        self._ws_tx_count = 0
        self._lbl_dot.setStyleSheet("color:#AAA;font-size:12px")
        self._lbl_status_text.setText("连接中...")
        self._lbl_local.setText("")
        self._lbl_remote.setText(url)
        self._lbl_stats.setText("Rx:0 | Tx:0")
        self.status_bar.showMessage("正在连接 WebSocket...", 3000)

    @Slot()
    def _on_mqtt_connected(self):
        if self._active_worker is not self._mqtt_worker:
            return
        self._mqtt_page.set_connected(True)
        self._lbl_dot.setStyleSheet("color:#107C10;font-size:12px")
        self._lbl_status_text.setText("已连接")
        self.status_bar.showMessage("MQTT 已连接", 3000)

    @Slot(str)
    def _on_mqtt_disconnected(self, message=""):
        if self._active_worker is not self._mqtt_worker:
            return
        if self._mqtt_auto_reconnect and self._mqtt_worker.isRunning():
            self._mqtt_page.set_connected(False)
            self._lbl_dot.setStyleSheet("color:#D83B01;font-size:12px")
            self._lbl_status_text.setText("重连中...")
            self.status_bar.showMessage(message or "MQTT 正在重连...", 5000)
            return
        self._active_worker = None
        self._mqtt_page.set_connected(False)
        self.sidebar.set_connected(False)
        self.sidebar.set_controls_enabled(True)
        self._lbl_dot.setStyleSheet("color:#D83B01;font-size:12px")
        self._lbl_status_text.setText("已断开")
        self.status_bar.showMessage(message or "MQTT 已断开", 8000)

    @Slot(dict)
    def _on_mqtt_message(self, message):
        if self._active_worker is not self._mqtt_worker:
            return
        message = dict(message)
        message["direction"] = "RX"
        self._mqtt_rx_count += len(bytes(message.get("payload") or b""))
        self._mqtt_page.append_message(message)
        self._lbl_stats.setText("Rx:{} | Tx:{}".format(
            self._mqtt_rx_count, self._mqtt_tx_count))

    @Slot(object)
    def _on_mqtt_subscriptions_changed(self, subscriptions):
        self._project_autosave_soon()
        if self._active_worker is self._mqtt_worker:
            self._mqtt_worker.sync_subscriptions(subscriptions)

    @Slot(dict)
    def _on_mqtt_publish(self, request):
        if self._active_worker is not self._mqtt_worker:
            show_warning(self, "提示", "请先连接 MQTT 服务端")
            return
        if not self._mqtt_worker.publish(
                request["topic"], request["payload"],
                request.get("qos", 0), request.get("retain", False)):
            return
        payload = bytes(request["payload"])
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            text = None
        message = {
            "timestamp": time.time(),
            "direction": "TX",
            "topic": request["topic"],
            "payload": payload,
            "text": text,
            "qos": int(request.get("qos", 0)),
            "retain": bool(request.get("retain", False)),
        }
        self._mqtt_tx_count += len(payload)
        self._mqtt_page.append_message(message)
        self._lbl_stats.setText("Rx:{} | Tx:{}".format(
            self._mqtt_rx_count, self._mqtt_tx_count))
        self._project_autosave_soon()

    @Slot()
    def _on_websocket_connected(self):
        if self._active_worker is not self._websocket_worker:
            return
        self._websocket_page.set_connected(True)
        self._lbl_dot.setStyleSheet("color:#107C10;font-size:12px")
        self._lbl_status_text.setText("已连接")
        self.status_bar.showMessage("WebSocket 已连接", 3000)

    @Slot(str)
    def _on_websocket_disconnected(self, message=""):
        if self._active_worker is not self._websocket_worker:
            return
        if (self._websocket_auto_reconnect
                and self._websocket_worker.isRunning()):
            self._websocket_page.set_connected(False)
            self._lbl_dot.setStyleSheet("color:#D83B01;font-size:12px")
            self._lbl_status_text.setText("重连中...")
            self.status_bar.showMessage(
                message or "WebSocket 正在重连...", 5000)
            return
        self._active_worker = None
        self._websocket_page.set_connected(False)
        self.sidebar.set_connected(False)
        self.sidebar.set_controls_enabled(True)
        self._lbl_dot.setStyleSheet("color:#D83B01;font-size:12px")
        self._lbl_status_text.setText("已断开")
        self.status_bar.showMessage(message or "WebSocket 已断开", 8000)

    @Slot(dict)
    def _on_websocket_message(self, message):
        if self._active_worker is not self._websocket_worker:
            return
        message = dict(message)
        message["direction"] = "RX"
        self._ws_rx_count += len(bytes(message.get("payload") or b""))
        self._websocket_page.append_message(message)
        self._lbl_stats.setText("Rx:{} | Tx:{}".format(
            self._ws_rx_count, self._ws_tx_count))

    @Slot(dict)
    def _on_websocket_send(self, request):
        if self._active_worker is not self._websocket_worker:
            show_warning(self, "提示", "请先连接 WebSocket")
            return
        if not self._websocket_worker.send(
                request["payload"], request.get("binary", False)):
            return
        message = {
            "timestamp": time.time(),
            "direction": "TX",
            "binary": bool(request.get("binary")),
            "payload": bytes(request["payload"]),
            "text": request.get("text"),
        }
        self._ws_tx_count += len(message["payload"])
        self._websocket_page.append_message(message)
        self._lbl_stats.setText("Rx:{} | Tx:{}".format(
            self._ws_rx_count, self._ws_tx_count))
        self._project_autosave_soon()

    @Slot()
    def _on_websocket_ping(self):
        if self._active_worker is self._websocket_worker:
            self._websocket_worker.ping()

    def _project_autosave_soon(self):
        if not self._applying and self._current_project:
            self._save_current_project()

    @Slot(int)
    def _on_tcp_server_started(self, port=0):
        if self._active_worker is not self._tcp_server:
            return
        self._lbl_dot.setStyleSheet("color:#107C10;font-size:12px")
        self._lbl_status_text.setText("已启动 · 待连接")
        self.status_bar.showMessage("TCP服务器监听端口 {}".format(port), 3000)

    @Slot(str)
    def _on_tcp_server_start_failed(self, message=""):
        if self._active_worker is not self._tcp_server:
            return
        self._active_worker = None
        self.sidebar.set_connected(False)
        self.sidebar.set_controls_enabled(True)
        self.send_bar.chk_dtr.setEnabled(False)
        self.send_bar.chk_rts.setEnabled(False)
        self._lbl_dot.setStyleSheet("color:#D83B01;font-size:12px")
        self._lbl_status_text.setText("启动失败")
        self._lbl_local.setText("")
        self._lbl_arrow.setText("")
        self._lbl_remote.setText("")
        self._lbl_stats.setText("")
        self._local_addr = ""
        self._remote_addr = ""
        self.status_bar.showMessage("TCP服务器启动失败: {}".format(message), 8000)

    @Slot(str)
    def _on_tcp_client_connect_failed(self, message=""):
        if self._active_worker is not self._tcp_client:
            return
        self._active_worker = None
        self.sidebar.set_connected(False)
        self.sidebar.set_controls_enabled(True)
        self.send_bar.chk_dtr.setEnabled(False)
        self.send_bar.chk_rts.setEnabled(False)
        self._lbl_dot.setStyleSheet("color:#D83B01;font-size:12px")
        self._lbl_status_text.setText("连接失败")
        self._lbl_local.setText("")
        self._lbl_arrow.setText("")
        self._lbl_remote.setText("")
        self._lbl_stats.setText("")
        self._local_addr = ""
        self._remote_addr = ""
        self.status_bar.showMessage("TCP客户端连接失败: {}".format(message), 8000)

    @Slot(str)
    def _on_serial_disconnected(self, message=""):
        if self._active_worker is not self._serial_worker:
            return
        self.send_bar.chk_repeat.setChecked(False)
        self.send_bar.stop_repeat()
        self.preset_panel.stop_loops()
        ser = self._serial_worker._serial
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass
        self._active_worker = None
        self.sidebar.set_connected(False)
        self.sidebar.set_controls_enabled(True)
        self.send_bar.chk_dtr.setEnabled(False)
        self.send_bar.chk_rts.setEnabled(False)
        self._lbl_dot.setStyleSheet("color:#D83B01;font-size:12px")
        self._lbl_status_text.setText("串口已断开")
        self._lbl_local.setText("")
        self._lbl_arrow.setText("")
        self._lbl_remote.setText("")
        self._lbl_stats.setText("")
        self._local_addr = ""
        self._remote_addr = ""
        self.status_bar.showMessage(
            "串口连接已断开: {}".format(message), 8000)

    def _get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
            s.connect(("8.8.8.8",80)); ip = s.getsockname()[0]; s.close(); return ip
        except: return "127.0.0.1"

    @Slot(str)
    def _on_disconnect(self, mode: str):
        self.send_bar.stop_repeat()
        if self._active_worker:
            if self._active_worker is self._mqtt_worker:
                self._mqtt_page.set_connected(False)
            elif self._active_worker is self._websocket_worker:
                self._websocket_page.set_connected(False)
            self._active_worker.stop()
            if isinstance(self._active_worker, SerialReadWorker):
                if self._active_worker._serial:
                    try: self._active_worker._serial.close()
                    except: pass
            self._active_worker = None
        self.sidebar.set_connected(False); self.sidebar.set_controls_enabled(True)
        self.send_bar.chk_dtr.setEnabled(False); self.send_bar.chk_rts.setEnabled(False)
        self._lbl_dot.setStyleSheet("color:#AAA;font-size:12px")
        self._lbl_status_text.setText("未连接")
        self._lbl_local.setText(""); self._lbl_arrow.setText("")
        self._lbl_remote.setText(""); self._lbl_stats.setText("")
        self._local_addr = ""; self._remote_addr = ""
        self.status_bar.showMessage("已断开",3000)

    @Slot(bytes)
    def _on_rx_data(self, data: bytes):
        self.log_panel.append_data("rx", data); self._update_stats()

    def _can_send(self, notify: bool = True) -> bool:
        """统一检查当前是否真正可发送数据.

        - 无活动连接: 弹窗提示"请先建立连接"
        - TCP 客户端"连接中/重试中"(尚未真正连上): 拒绝发送, 由 worker 兜底限频提示
        notify=False 用于定时/循环等自动触发路径, 避免高频弹窗或刷屏.
        """
        if not self._active_worker:
            if notify:
                show_warning(self, "提示", "请先建立连接")
            return False
        if isinstance(self._active_worker, TCPClientWorker) and not self._tcp_client.is_connected:
            return False
        if (isinstance(self._active_worker, TCPServerWorker)
                and self._tcp_server.client_count == 0):
            if notify:
                show_warning(self, "提示", "当前没有已连接的 TCP 客户端")
            return False
        return True

    @Slot(bytes)
    def _on_send_data(self, data: bytes):
        if not self._can_send(): return
        if self._send_raw(data):
            self._record_tx(data)

    def _send_raw(self, data: bytes):
        try:
            if isinstance(self._active_worker, SerialReadWorker):
                ser = self._active_worker._serial
                if ser and ser.is_open:
                    return ser.write(data) == len(data)
            elif isinstance(self._active_worker, TCPServerWorker):
                return self._active_worker.send(data) > 0
            elif isinstance(self._active_worker, TCPClientWorker):
                return self._active_worker.send(data)
        except Exception as e:
            self._on_error("发送失败: {}".format(e))
        return False

    def _record_tx(self, data: bytes):
        """只在数据真正进入至少一个发送通道后更新发送日志和统计。"""
        self.log_panel.append_data("tx", data)
        self.send_bar._tx_total += len(data)
        self.send_bar.lbl_tx_count.setText("Tx: {}".format(
            self.send_bar._tx_total))
        self._update_stats()

    @Slot()
    def _on_log_cleared(self):
        self.send_bar._tx_total = 0
        self.send_bar.lbl_tx_count.setText("Tx: 0")
        self._update_stats()

    def _update_stats(self):
        self._lbl_stats.setText("Rx:{} | Tx:{}".format(self.log_panel._rx_total, self.log_panel._tx_total))

    @Slot(bytes)
    def _on_send_preset(self, data: bytes):
        # 未连接时直接丢弃, 不记录日志/统计 (预设循环 tick 每 100ms 会走到这里)
        if not self._can_send(notify=False): return
        # Apply current checksum rules from send bar
        data = self.send_bar._build_data_for_preset(data)
        if data and self._send_raw(data):
            self._record_tx(data)

    @Slot()
    def _on_repeat_tick(self):
        if not self._can_send(notify=False): return
        data = self.send_bar._build_data(silent=True)
        if data and self._send_raw(data):
            self._record_tx(data)

    def _on_dtr_toggled(self, checked):
        if isinstance(self._active_worker, SerialReadWorker):
            if self._active_worker._serial: self._active_worker._serial.dtr = checked

    def _on_rts_toggled(self, checked):
        if isinstance(self._active_worker, SerialReadWorker):
            if self._active_worker._serial: self._active_worker._serial.rts = checked

    def _on_tcp_connected(self, host="", port=0):
        if self._active_worker is not self._tcp_client:
            return
        self._lbl_dot.setStyleSheet("color:#107C10;font-size:12px")
        self._lbl_status_text.setText("已连接")
        lip, lport = "127.0.0.1", 0
        if self._tcp_client._sock:
            try:
                lip, lport = self._tcp_client._sock.getsockname()
            except Exception:
                pass
        # 0 表示系统分配; UI 上展示真实端口, 区分于远端端口
        self._local_addr = "{}:{}".format(lip, lport)
        self._lbl_local.setText("本地IP={}".format(self._local_addr))
        self._lbl_arrow.setText("↔")
        self._lbl_remote.setText("远端IP={}".format(self._remote_addr))
        self.status_bar.showMessage("已连接 {}:{}".format(host,port),3000)

    def _on_tcp_server_client_connected(self, host="", port=0):
        if self._active_worker is not self._tcp_server:
            return
        self._lbl_arrow.setText("←")
        self._lbl_remote.setText("客户端={}:{}".format(host,port))
        self._lbl_status_text.setText("已启动 · 已连接")
        self.status_bar.showMessage("客户端连接: {}:{}".format(host,port),3000)

    def _on_tcp_server_client_disconnected(self, host="", port=0):
        if self._active_worker is not self._tcp_server:
            return
        disconnected_host, disconnected_port = host, port
        # 多客户端时优先展示仍在线的一个；全部断开才恢复“待连接”。
        addresses = self._tcp_server.client_addresses
        if addresses:
            host, port = addresses[-1]
            self._lbl_arrow.setText("←")
            self._lbl_remote.setText("客户端={}:{}".format(host, port))
            self._lbl_status_text.setText("已启动 · 已连接")
        else:
            self._lbl_arrow.setText("")
            self._lbl_remote.setText("")
            self._lbl_status_text.setText("已启动 · 待连接")
        self.status_bar.showMessage(
            "客户端断开: {}:{}".format(
                disconnected_host, disconnected_port), 3000)

    def _on_tcp_disconnected(self):
        if self._active_worker is not self._tcp_client:
            return
        # TCP 客户端网络断开: 客户端 Socket 已断, 但本地 UI 应停在"已断开"状态
        # 而不是"未连接" (用户可能想重新连接; 重连前不应清空所有标签)
        self._lbl_dot.setStyleSheet("color:#D83B01;font-size:12px")
        self._lbl_status_text.setText("已断开")
        self._lbl_arrow.setText("")
        self._lbl_remote.setText("")
        self._remote_addr = ""
        self._active_worker = None
        self.sidebar.set_connected(False); self.sidebar.set_controls_enabled(True)
        self.status_bar.showMessage("远端已断开", 3000)

    @Slot(str)
    def _on_error(self, msg: str):
        self.status_bar.showMessage("错误: {}".format(msg), 8000)

    @Slot(str)
    def _log(self, msg: str):
        self.status_bar.showMessage(msg, 5000)

    def _refresh_ports(self):
        try:
            current = self.sidebar.cb_port.currentText()
            self.sidebar.cb_port.blockSignals(True); self.sidebar.cb_port.clear()
            for p in sorted(serial.tools.list_ports.comports()):
                self.sidebar.cb_port.addItem(p.device, p.device)
            if current:
                idx = self.sidebar.cb_port.findText(current)
                if idx >= 0: self.sidebar.cb_port.setCurrentIndex(idx)
                else: self.sidebar.cb_port.setCurrentText(current)
            self.sidebar.cb_port.blockSignals(False)
        except Exception as e:
            # 刷新串口列表失败会表现为端口下拉为空, 记录原因便于排查
            print("[AnhuToolbox] 刷新串口列表失败:", e)
        self._check_port_exists()

    def closeEvent(self, event):
        self._sync_timer.stop(); self._port_timer.stop()
        self._resource_timer.stop()
        self._extra_tabs_timer.stop()
        self._update_check_timer.stop()
        self._update_initial_timer.stop()
        if self._update_download_dialog is not None:
            self._update_download_dialog.reject()
        if (self._update_check_worker is not None
                and self._update_check_worker.isRunning()):
            self._update_check_worker.stop()
        for page in self._stream_pages.values():
            page.send_bar.stop_repeat()
            page.log_panel.cleanup()
        self._mqtt_page.cleanup()
        self._websocket_page.cleanup()
        self.preset_panel.stop_timer()
        if self._active_worker:
            self._on_disconnect(self.sidebar.current_mode)
        if hasattr(self, "_library_pages"):
            network = self._library_pages.get("network")
            if network is not None:
                network.stop_tasks()
            capture = self._library_pages.get("capture")
            if capture is not None:
                capture.stop_tasks()
            timestamp = self._library_pages.get("timestamp")
            if timestamp is not None:
                timestamp.stop_timer()
            hardware = self._library_pages.get("hardware")
            if hardware is not None:
                hardware.cleanup()
        self._http_page.cleanup()
        self._save_current_project()
        self._save_global()
        event.accept()
