# -*- coding: utf-8 -*-
"""AnhuToolbox 主窗口 -- 带配置持久化 + 预设面板可折叠"""

import os, json, socket
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QTabWidget, QStackedWidget,
    QSplitter, QStatusBar, QLabel, QFrame, QPushButton,
    QMessageBox, QApplication, QMenu, QInputDialog, QFileDialog
)
from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QFont
import serial, serial.tools.list_ports

from .sidebar import Sidebar
from .panels import LogPanel, SendBar, PresetPanel
from .workers import SerialReadWorker, TCPServerWorker, TCPClientWorker
from .tools import TimestampTool, QRTool, JsonTool, BaseTool, RegexTool, DiffTool, SortTool, EncodeTool, ChecksumTool, AmountTool, HardwareInfoPage, NetworkTool
from .styles import (GLOBAL_STYLE, STATUS_BAR_STYLE, BG_SIDEBAR, BORDER,
                     TEXT_PRIMARY, TEXT_SECONDARY, prepare_menu)
from . import settings as cfg
from . import toolbox
from .custom_library import CustomLibraryPage
from .projects import ProjectManager, DEFAULT_PROJECT_NAME


# 工具库分组: (组名, [(key, 显示名), ...])，key 对应下方工具页字典
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
        ("network", "Ping/端口扫描/网段扫描"),
    ]),
]

# 工具库默认展示顺序 (与分组一致)
LIBRARY_ORDER = ["timestamp", "base", "encode", "checksum", "amount",
                 "json", "regex", "diff", "sort", "qr", "network"]




class MainWindow(QMainWindow):
    log_message = Signal(str)

    def __init__(self, base_dir=None):
        super().__init__()
        self._base_dir = base_dir or os.path.dirname(os.path.dirname(__file__))
        # 数据文件放 EXE 目录 (可写), 而非临时解压目录
        self.setWindowTitle("Anhu 百宝箱")
        self.setMinimumSize(1100, 720)

        cfg.init(os.path.join(self._base_dir, "data", "settings.json"))

        self._serial_worker = SerialReadWorker()
        self._serial_worker.data_received.connect(self._on_rx_data)
        self._serial_worker.error_occurred.connect(self._on_error)

        self._tcp_server = TCPServerWorker()
        self._tcp_server.data_received.connect(self._on_rx_data)
        self._tcp_server.error_occurred.connect(self._on_error)
        self._tcp_server.client_connected.connect(self._on_tcp_server_client_connected)
        self._tcp_server.client_disconnected.connect(self._on_tcp_server_client_disconnected)
        self._tcp_server.log_message.connect(self._log)

        self._tcp_client = TCPClientWorker()
        self._tcp_client.data_received.connect(self._on_rx_data)
        self._tcp_client.error_occurred.connect(self._on_error)
        self._tcp_client.connected.connect(self._on_tcp_connected)
        self._tcp_client.disconnected.connect(self._on_tcp_disconnected)
        self._tcp_client.log_message.connect(self._log)

        self._active_worker = None
        self._connection_mode = cfg.get("mode", "serial")
        self._local_addr = ""
        self._remote_addr = ""

        # 项目管理: 一个项目 = 一整套连接参数 + 发送/显示配置 + 预设命令
        self._pm = ProjectManager(self._base_dir)
        self._current_project = ""
        self._applying = False          # 应用项目配置期间抑制自动保存
        self._last_snapshot = None
        self._has_dtr_rts = False       # 当前项目是否记录了 DTR/RTS 状态

        self._build_ui()
        self._restore_global()
        self._connect_signals()
        self._init_projects()
        self._refresh_ports()

        self._port_timer = QTimer()
        self._port_timer.timeout.connect(self._refresh_ports)
        self._port_timer.start(1500)

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

        # --- 串口调试页 (原主区域: 日志 + 发送) ---
        self._main_area = QWidget()
        main_lo = QVBoxLayout(self._main_area)
        main_lo.setContentsMargins(0,0,0,0); main_lo.setSpacing(0)

        self.log_panel = LogPanel()
        # 在日志工具栏加一个预设面板切换按钮
        self._btn_toggle_preset = QPushButton("≡ 预设")
        self._btn_toggle_preset.setCheckable(True)
        self._btn_toggle_preset.setFixedHeight(24)
        self._btn_toggle_preset.setStyleSheet(
            "QPushButton{padding:2px 10px;font-size:12px;border-radius:4px;min-height:20px;max-height:24px}"
            "QPushButton:checked{background:#E8F0FE;color:#0078D4;border-color:#0078D4;font-weight:600}"
        )
        self._btn_toggle_preset.toggled.connect(self._on_toggle_preset)
        self.log_panel._add_widget(self._btn_toggle_preset)

        main_lo.addWidget(self.log_panel, stretch=1)

        self.send_bar = SendBar()
        self.send_bar.send_data.connect(self._on_send_data)
        self.send_bar.repeat_tick.connect(self._on_repeat_tick)
        main_lo.addWidget(self.send_bar)

        # --- Tab 控件: 串口调试 + 工具集 ---
        self._tab_widget = QTabWidget()
        self._tab_widget.setStyleSheet(
            "QTabWidget::pane{border:1px solid #D0D0D0;border-top:none}"
            "QTabBar::tab{background:#F5F5F5;color:#666;padding:8px 18px;border:1px solid #D0D0D0;"
            "border-bottom:none;margin-right:2px;font-size:13px}"
            "QTabBar::tab:selected{background:#FFF;color:#0078D4;font-weight:600;border-bottom:2px solid #0078D4}"
            "QTabBar::tab:hover{background:#E8F0FE;color:#0078D4}"
        )
        self._tab_widget.addTab(self._main_area, "串口调试")
        self._tab_widget.currentChanged.connect(self._on_tab_changed)
        # 其余工具页延迟到事件循环开始后再创建, 加快首屏显示
        QTimer.singleShot(0, self._build_extra_tabs)

        # --- 预设面板 (可拖动, 初始隐藏) ---
        self.preset_panel = PresetPanel()
        # 预设内容改为跟随「项目」保存, 不再写全局 presets.json
        self.preset_panel.set_change_callback(self._on_presets_changed)
        self.preset_panel.send_preset.connect(self._on_send_preset)
        self.preset_panel.setVisible(False)
        self.preset_panel.setMinimumWidth(200)

        self._preset_splitter = QSplitter(Qt.Horizontal)
        self._preset_splitter.setHandleWidth(2)
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

    def _build_extra_tabs(self):
        """延迟创建工具箱/工具库/自定义库三个主 tab (避免首屏被阻塞)"""
        # --- 工具库 tab: 左侧分组列表在 sidebar, 右侧是工具页堆叠 ---
        self._library_pages = {
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
            "network": NetworkTool(),
        }
        self._library_stack = QStackedWidget()
        for key in LIBRARY_ORDER:
            self._library_stack.addWidget(self._library_pages[key])
        # tab 顺序: 串口调试(0) / 工具库(1) / 工具箱(2) / 自定义库(3)
        # 串口调试在 _build_ui 里已占据 0, 这里追加即得 1
        self._tab_widget.addTab(self._library_stack, "工具库")

        # --- 工具箱 tab: 左侧分类列表在 sidebar, 右侧是内容堆叠 ---
        tools_dir = os.path.join(self._base_dir, "tools")
        self._toolbox_tools = toolbox.load_manifest(tools_dir)
        cats = toolbox.load_categories(tools_dir)
        if cats is None:
            cats = []
        for t in self._toolbox_tools:
            c = toolbox._norm_category(t)
            if c not in cats:
                cats.append(c)

        self._toolbox_categories = ["硬件信息"] + cats
        self._toolbox_pages = {}
        self._toolbox_stack = QStackedWidget()
        hw = HardwareInfoPage()
        self._toolbox_stack.addWidget(hw)
        self._toolbox_pages["硬件信息"] = hw
        for c in cats:
            page = toolbox.build_category_page(c, self._toolbox_tools, tools_dir)
            self._toolbox_stack.addWidget(page)
            self._toolbox_pages[c] = page
        # 追加在工具库之后, 即 工具库(1) / 工具箱(2)
        self._tab_widget.addTab(self._toolbox_stack, "工具箱")

        # --- 自定义库 tab: 用户自己添加的本地工具 (清单 tools\tools.user.json) ---
        self._custom_library = CustomLibraryPage(tools_dir)
        self._tab_widget.addTab(self._custom_library, "自定义库")

        # 填充左侧导航并连接信号
        self.sidebar.set_library_groups(LIBRARY_GROUPS)
        self.sidebar.set_toolbox_categories(self._toolbox_categories)
        self.sidebar.library_item_clicked.connect(self._on_library_item)
        self.sidebar.toolbox_item_clicked.connect(self._on_toolbox_item)

        # 默认停在「串口调试」(第一个 tab), 显示上次关闭时使用的项目
        self._tab_widget.setCurrentWidget(self._main_area)
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
        return bar

    def _on_tab_changed(self, index):
        """切换主 tab 时同步左侧导航区 + 隐藏预设/底部信息栏"""
        # 按页面对象判断, 避免依赖 tab 的先后顺序
        page = self._tab_widget.widget(index)
        if page is getattr(self, "_toolbox_stack", None):
            mode = "toolbox"
        elif page is getattr(self, "_library_stack", None):
            mode = "library"
        elif page is getattr(self, "_custom_library", None):
            # 自定义库不占左侧导航 (没有分类), 工具栏按钮在右侧页面顶部
            mode = "custom"
        else:
            mode = "serial"
        self.sidebar.set_nav_mode(mode)
        is_serial = (mode == "serial")
        self._info_bar.setVisible(is_serial)
        if is_serial:
            show = self._btn_toggle_preset.isChecked()
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
        self.preset_panel.setVisible(checked)
        if checked:
            # 展开时给预设面板合理的初始宽度
            tw = self._preset_splitter.width()
            self._preset_splitter.setSizes([tw * 3 // 5, tw * 2 // 5])
        cfg.set("preset_visible", checked)
        cfg.save()

    def _restore_global(self):
        """恢复与项目无关的全局偏好(项目内容由 _load_project 负责)"""
        show_preset = cfg.get("preset_visible", False)
        self.preset_panel.setVisible(show_preset)
        self._btn_toggle_preset.setChecked(show_preset)
        saved_sizes = cfg.get("preset_splitter", None)
        if show_preset and saved_sizes and len(saved_sizes) == 2:
            self._preset_splitter.setSizes(saved_sizes)
        # First launch: show welcome message
        if not os.path.exists(os.path.join(self._base_dir, "data", "settings.json")):
            self._show_welcome()

    def _apply_legacy_settings_to_ui(self):
        """还没有项目时的初始值: 沿用旧版 settings.json 里的连接/发送/显示参数"""
        mode_map = {"serial": 0, "tcpserver": 1, "tcpclient": 2}
        idx = mode_map.get(cfg.get("mode", "serial"), 0)
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

        # Send settings
        # 先恢复“加回车换行”状态, 再恢复 HEX 开关; HEX 为开时其后会自动禁用并取消该勾选
        self.send_bar.chk_crlf.setChecked(cfg.get("send.crlf", True))
        self.send_bar.chk_hex.setChecked(cfg.get("send.hex_send", False))
        self.send_bar.sp_interval.setValue(cfg.get("send.interval", 1000))
        idx_cs = self.send_bar.cb_checksum.findText(cfg.get("send.checksum", "ModbusCRC16"))
        if idx_cs >= 0: self.send_bar.cb_checksum.setCurrentIndex(idx_cs)
        self.send_bar.sp_start.setValue(cfg.get("send.start_byte", 1))
        self.send_bar.cb_end.setCurrentText(cfg.get("send.end_byte_text", "末尾"))

        # Log settings
        self.log_panel.chk_hex.setChecked(cfg.get("log.hex_display", True))
        self.log_panel.chk_timestamp.setChecked(cfg.get("log.timestamp", True))
        self.log_panel.sp_timeout.setValue(cfg.get("log.timeout", 0))

        # 旧版 data/presets.json 只在第一次建默认项目时读一次, 之后交给项目文件
        self.preset_panel.load_from_project(self._read_legacy_presets())

    def _read_legacy_presets(self):
        """读取旧版全局预设文件(仅用于初始化第一个项目)"""
        try:
            with open(os.path.join(self._base_dir, "data", "presets.json"),
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
            "　　　欢迎使用Anhu 百宝箱\n"
            "　　　版本号：V1.0.0   作者：Jinchoo\n"
            "\n"
            "+======================================+\n"
        )
        self.log_panel.text.setPlainText(msg)
    def _save_global(self):
        """只保存与项目无关的全局偏好; 项目内容由 _save_current_project 负责"""
        cfg.set("preset_visible", self.preset_panel.isVisible())
        cfg.set("preset_splitter", list(self._preset_splitter.sizes()))
        cfg.set("last_project", self._current_project or "")
        cfg.save()

    def _connect_signals(self):
        self.sidebar.mode_changed.connect(self._on_mode_changed)
        self.sidebar.connect_clicked.connect(self._on_connect)
        self.sidebar.disconnect_clicked.connect(self._on_disconnect)
        self.sidebar.port_refresh_clicked.connect(self._refresh_ports)
        self.sidebar.project_changed.connect(self._on_project_selected)
        self.sidebar.project_menu_requested.connect(self._show_project_menu)
        self.send_bar.chk_dtr.toggled.connect(self._on_dtr_toggled)
        self.send_bar.chk_rts.toggled.connect(self._on_rts_toggled)
        self.log_panel.cleared.connect(self._update_stats)
        self._sync_timer = QTimer()
        self._sync_timer.timeout.connect(self._sync_preset_text)
        self._sync_timer.start(500)

    def _sync_preset_text(self):
        self.preset_panel.set_current_text(
            self.send_bar.chk_hex.isChecked(),
            self.send_bar.text.toPlainText()
        )
        self._autosave_project()

    def _autosave_project(self):
        """配置有变化就写回当前项目(快照比对, 无变化不写盘)"""
        if self._applying or not self._current_project:
            return
        snap = self._snapshot_ui()
        if snap == self._last_snapshot:
            return
        self._last_snapshot = snap
        self._pm.save(self._current_project, snap)

    # ==================== 项目管理 ====================
    def _init_projects(self):
        """启动时准备项目: 一个项目都没有就先建一个默认项目"""
        names = self._pm.names()
        if not names:
            self._apply_legacy_settings_to_ui()
            self._pm.create(DEFAULT_PROJECT_NAME, self._snapshot_ui())
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

    def _snapshot_ui(self):
        """把当前界面状态打包成项目数据"""
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
            "send": {
                "hex_send": self.send_bar.chk_hex.isChecked(),
                "crlf": self.send_bar.chk_crlf.isChecked(),
                "interval": self.send_bar.sp_interval.value(),
                "checksum": self.send_bar.cb_checksum.currentText(),
                "start_byte": self.send_bar.sp_start.value(),
                "end_byte_text": self.send_bar.cb_end.currentText(),
                "dtr": self.send_bar.chk_dtr.isChecked(),
                "rts": self.send_bar.chk_rts.isChecked(),
                "draft": self.send_bar.text.toPlainText(),
            },
            "log": {
                "hex_display": self.log_panel.chk_hex.isChecked(),
                "timestamp": self.log_panel.chk_timestamp.isChecked(),
                "timeout": self.log_panel.sp_timeout.value(),
            },
            "presets": self.preset_panel.dump_presets(),
        }

    def _load_project(self, name):
        """把项目数据应用到界面"""
        profile = self._pm.load(name) or {}
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
        self.status_bar.showMessage("已切换到项目: {}".format(name), 3000)

    def _save_current_project(self):
        """把当前界面状态写回当前项目"""
        if self._applying or not self._current_project:
            return
        snap = self._snapshot_ui()
        self._last_snapshot = snap
        self._pm.save(self._current_project, snap)

    def _on_presets_changed(self, presets):
        """预设内容变化 -> 立即写回当前项目"""
        if self._applying or not self._current_project:
            return
        snap = self._snapshot_ui()
        self._last_snapshot = snap
        self._pm.save(self._current_project, snap)

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

    def _apply_profile(self, p):
        """把项目数据写进各个控件(调用方负责置 _applying 抑制自动保存)"""
        mode_map = {"serial": 0, "tcpserver": 1, "tcpclient": 2}
        idx = mode_map.get(p.get("mode", "serial"), 0)
        self.sidebar._mode_group.button(idx).setChecked(True)
        self.sidebar._on_mode_changed(idx)

        s = p.get("serial") or {}
        self.sidebar.cb_port.setCurrentText(str(s.get("port", "COM1")))
        self.sidebar.cb_baud.setCurrentText(str(s.get("baud", "115200")))
        self.sidebar.cb_data.setCurrentText(str(s.get("data", "8")))
        self.sidebar.cb_stop.setCurrentText(str(s.get("stop", "1")))
        self.sidebar.cb_parity.setCurrentText(str(s.get("parity", "None")))
        self.sidebar.cb_flow.setCurrentText(str(s.get("flow", "None")))

        t = p.get("tcpserver") or {}
        self.sidebar.sp_server_port.setValue(int(t.get("port", 8888)))
        self.sidebar.sp_client_timeout.setValue(int(t.get("client_timeout", 30)))
        c = p.get("tcpclient") or {}
        self.sidebar.le_client_host.setText(str(c.get("host", "127.0.0.1")))
        self.sidebar.sp_client_port.setValue(int(c.get("port", 8888)))
        lp = str(c.get("local_port", "") or "")
        self.sidebar.le_local_port.setText(lp if lp.isdigit() and int(lp) > 0 else "")

        d = p.get("send") or {}
        # 顺序: 先 CRLF 后 HEX (HEX 打开时会自动禁用并取消 CRLF)
        self.send_bar.chk_crlf.setChecked(bool(d.get("crlf", True)))
        self.send_bar.chk_hex.setChecked(bool(d.get("hex_send", False)))
        self.send_bar.sp_interval.setValue(int(d.get("interval", 1000)))
        i = self.send_bar.cb_checksum.findText(str(d.get("checksum", "ModbusCRC16")))
        if i >= 0:
            self.send_bar.cb_checksum.setCurrentIndex(i)
        self.send_bar.sp_start.setValue(int(d.get("start_byte", 1)))
        self.send_bar.cb_end.setCurrentText(str(d.get("end_byte_text", "末尾")))
        self.send_bar.chk_dtr.setChecked(bool(d.get("dtr", False)))
        self.send_bar.chk_rts.setChecked(bool(d.get("rts", False)))
        self._has_dtr_rts = ("dtr" in d) or ("rts" in d)
        self.send_bar.text.setPlainText(str(d.get("draft", "")))

        g = p.get("log") or {}
        self.log_panel.chk_hex.setChecked(bool(g.get("hex_display", True)))
        self.log_panel.chk_timestamp.setChecked(bool(g.get("timestamp", True)))
        self.log_panel.sp_timeout.setValue(int(g.get("timeout", 0)))

        self.preset_panel.load_from_project(p.get("presets") or [])

    def _switch_project(self, name, confirm=True):
        """切换项目: 存旧项目 -> 停自动动作 -> 断开 -> 应用新项目"""
        if name == self._current_project:
            return True
        if confirm and self._active_worker:
            r = QMessageBox.question(
                self, "切换项目",
                "切换项目会断开当前连接，是否继续？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                self.sidebar.set_current_project(self._current_project)
                return False
        self._save_current_project()
        # 停掉所有"会自己动"的东西, 免得老节奏打到新连接上
        if self.send_bar.chk_repeat.isChecked():
            self.send_bar.chk_repeat.setChecked(False)
        self.send_bar.stop_repeat()
        self.preset_panel.stop_loops()
        self.log_panel.reset_runtime_state()
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
            names = [self._pm.create(DEFAULT_PROJECT_NAME, self._default_profile())]
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
        name, ok = QInputDialog.getText(
            self, "新建项目", "项目名称：",
            text="项目{}".format(len(self._pm.names()) + 1))
        name = (name or "").strip()
        if not ok or not name:
            return
        self._save_current_project()
        # 新项目用默认配置(含空预设), 不继承当前项目的任何设置
        self._reload_project_list(self._pm.create(name, self._default_profile()))

    def _project_rename(self):
        old = self._current_project
        if not old:
            return
        name, ok = QInputDialog.getText(self, "重命名项目", "新名称：", text=old)
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
        name, ok = QInputDialog.getText(self, "复制项目", "新项目名称：", text=old + " 副本")
        name = (name or "").strip()
        if not ok or not name:
            return
        self._save_current_project()
        data = self._pm.load(old) or self._snapshot_ui()
        self._reload_project_list(self._pm.create(name, data))

    def _project_delete(self):
        old = self._current_project
        if not old:
            return
        r = QMessageBox.question(
            self, "删除项目",
            "确定删除项目「{}」吗？\n该项目下的预设命令和配置会一并删除，且无法恢复。".format(old),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        if self.send_bar.chk_repeat.isChecked():
            self.send_bar.chk_repeat.setChecked(False)
        self.send_bar.stop_repeat()
        self.preset_panel.stop_loops()
        self.log_panel.reset_runtime_state()
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
            QMessageBox.critical(self, "导入失败", "项目文件格式不正确或无法读取。")
            return
        self._reload_project_list(name)
        QMessageBox.information(self, "导入成功", "已导入项目「{}」".format(name))

    def _project_export(self):
        old = self._current_project
        if not old:
            return
        self._save_current_project()
        path, _ = QFileDialog.getSaveFileName(
            self, "导出项目", "{}.json".format(old), "JSON 文件 (*.json)")
        if not path:
            return
        if self._pm.export_to(old, path):
            QMessageBox.information(self, "导出成功", "已导出到：\n{}".format(path))
        else:
            QMessageBox.critical(self, "导出失败", "无法写入该文件。")

    def _open_project_dir(self):
        try:
            os.startfile(self._pm.dir)
        except Exception as e:
            QMessageBox.warning(self, "提示", "无法打开项目文件夹：\n{}".format(e))

    @Slot(str)
    def _on_mode_changed(self, mode: str):
        self._connection_mode = mode
        if self._active_worker: self._on_disconnect(mode)
        labels = {"serial":"串口","tcpserver":"TCPServer","tcpclient":"TCPClient"}
        self._lbl_conn_type.setText(labels.get(mode,mode))
        self._lbl_local.setText(""); self._lbl_arrow.setText("")
        self._lbl_remote.setText(""); self._lbl_stats.setText("")
        cfg.set("mode", mode); cfg.save()

    @Slot(str)
    def _on_connect(self, mode: str):
        if mode == "serial": self._connect_serial()
        elif mode == "tcpserver": self._connect_tcp_server()
        elif mode == "tcpclient": self._connect_tcp_client()

    def _connect_serial(self):
        port = self.sidebar.cb_port.currentText().strip()
        if not port:
            QMessageBox.warning(self,"提示","请选择串口号"); return
        try:
            parity_map = {"None":"N","Even":"E","Odd":"O","Mark":"M","Space":"S"}
            ser = serial.Serial(
                port=port, baudrate=int(self.sidebar.cb_baud.currentText()),
                bytesize=int(self.sidebar.cb_data.currentText()),
                stopbits={"1":serial.STOPBITS_ONE,"1.5":serial.STOPBITS_ONE_POINT_FIVE,"2":serial.STOPBITS_TWO}[self.sidebar.cb_stop.currentText()],
                parity=parity_map[self.sidebar.cb_parity.currentText()], timeout=0.1,
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
            QMessageBox.critical(self,"错误","无法打开串口:\n{}".format(e))

    def _connect_tcp_server(self):
        port = self.sidebar.sp_server_port.value()
        timeout_s = self.sidebar.sp_client_timeout.value()
        self._tcp_server.set_client_timeout(timeout_s)
        self._tcp_server.configure(port); self._tcp_server.start()
        self._active_worker = self._tcp_server
        self.sidebar.set_connected(True); self.sidebar.set_controls_enabled(False)
        lip = self._get_local_ip(); self._local_addr = "{}:{}".format(lip,port)
        self._lbl_conn_type.setText("TCPServer")
        self._lbl_dot.setStyleSheet("color:#107C10;font-size:12px")
        self._lbl_status_text.setText("已启动 · 待连接")
        self._lbl_local.setText("本地IP={}".format(self._local_addr))
        self.status_bar.showMessage("TCP服务器监听 {}:{}".format(lip,port),3000)

    def _connect_tcp_client(self):
        host = self.sidebar.le_client_host.text().strip()
        port = self.sidebar.sp_client_port.value()
        # 本地端口: 留空 = 随机(0); 填数字 = 固定端口
        _lp = self.sidebar.le_local_port.text().strip()
        local_port = int(_lp) if _lp.isdigit() else 0
        if not host: QMessageBox.warning(self,"提示","请输入远端地址"); return
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

    def _get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
            s.connect(("8.8.8.8",80)); ip = s.getsockname()[0]; s.close(); return ip
        except: return "127.0.0.1"

    @Slot(str)
    def _on_disconnect(self, mode: str):
        self.send_bar.stop_repeat()
        if self._active_worker:
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
                QMessageBox.warning(self, "提示", "请先建立连接")
            return False
        if isinstance(self._active_worker, TCPClientWorker) and not self._tcp_client.is_connected:
            return False
        return True

    @Slot(bytes)
    def _on_send_data(self, data: bytes):
        if not self._can_send(): return
        self._send_raw(data); self.log_panel.append_data("tx", data); self._update_stats()

    def _send_raw(self, data: bytes):
        if isinstance(self._active_worker, SerialReadWorker):
            ser = self._active_worker._serial
            if ser and ser.is_open: ser.write(data)
        elif isinstance(self._active_worker, TCPServerWorker): self._active_worker.send(data)
        elif isinstance(self._active_worker, TCPClientWorker): self._active_worker.send(data)

    def _update_stats(self):
        self._lbl_stats.setText("Rx:{} | Tx:{}".format(self.log_panel._rx_total, self.log_panel._tx_total))

    @Slot(bytes)
    def _on_send_preset(self, data: bytes):
        # 未连接时直接丢弃, 不记录日志/统计 (预设循环 tick 每 100ms 会走到这里)
        if not self._can_send(notify=False): return
        # Apply current checksum rules from send bar
        data = self.send_bar._build_data_for_preset(data)
        self._send_raw(data); self.log_panel.append_data("tx", data); self._update_stats()

    @Slot()
    def _on_repeat_tick(self):
        if not self._can_send(notify=False): return
        data = self.send_bar._build_data(silent=True)
        if data:
            self._send_raw(data); self.log_panel.append_data("tx", data)
            self.send_bar._tx_total += len(data)
            self.send_bar.lbl_tx_count.setText("Tx: {}".format(self.send_bar._tx_total))
            self._update_stats()

    def _on_dtr_toggled(self, checked):
        if isinstance(self._active_worker, SerialReadWorker):
            if self._active_worker._serial: self._active_worker._serial.dtr = checked

    def _on_rts_toggled(self, checked):
        if isinstance(self._active_worker, SerialReadWorker):
            if self._active_worker._serial: self._active_worker._serial.rts = checked

    def _on_tcp_connected(self, host="", port=0):
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
        self._lbl_arrow.setText("←")
        self._lbl_remote.setText("客户端={}:{}".format(host,port))
        self._lbl_status_text.setText("已启动 · 已连接")
        self.status_bar.showMessage("客户端连接: {}:{}".format(host,port),3000)

    def _on_tcp_server_client_disconnected(self, host="", port=0):
        # 客户端断开: 清除客户端显示; 若还有客户端连接则保持"已连接", 全部断开才恢复"待连接"
        # 保留本地IP和统计, 因为服务还在运行
        self._lbl_arrow.setText("")
        self._lbl_remote.setText("")
        self._lbl_status_text.setText("已启动 · 待连接" if self._tcp_server.client_count == 0 else "已启动 · 已连接")
        self.status_bar.showMessage("客户端断开: {}:{}".format(host,port),3000)

    def _on_tcp_disconnected(self):
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
        self.send_bar.stop_repeat()
        self.preset_panel.stop_timer()
        if self._active_worker: self._active_worker.stop()
        self.log_panel.cleanup()
        self._save_current_project()
        self._save_global()
        event.accept()
