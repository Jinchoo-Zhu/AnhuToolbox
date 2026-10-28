# -*- coding: utf-8 -*-
"""AnhuToolbox 侧边栏 -- 连接模式选择与参数配置"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox,
    QPushButton, QSpinBox, QStackedWidget, QLineEdit,
    QFrame, QButtonGroup, QSizePolicy, QScrollArea
)
from PySide6.QtGui import QIntValidator
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from .styles import SIDEBAR_STYLE, COMBO_STYLE


# 参数配置滚动区: 只在需要时露出细滚动条, 无边框, 背景与侧边栏一致
SETTINGS_SCROLL_STYLE = (
    "QScrollArea#settingsScroll{background:transparent;border:none;}"
    "QScrollArea#settingsScroll > QWidget > QWidget{background:transparent;}"
    "QScrollArea#settingsScroll > QScrollBar:vertical"
    "{background:transparent;width:8px;margin:0;}"
    "QScrollArea#settingsScroll > QScrollBar::handle:vertical"
    "{background:#C8C8C8;border-radius:4px;min-height:24px;}"
    "QScrollArea#settingsScroll > QScrollBar::handle:vertical:hover"
    "{background:#A6A6A6;}"
    "QScrollArea#settingsScroll > QScrollBar::add-line:vertical,"
    "QScrollArea#settingsScroll > QScrollBar::sub-line:vertical"
    "{height:0;background:transparent;}"
    "QScrollArea#settingsScroll > QScrollBar::add-page:vertical,"
    "QScrollArea#settingsScroll > QScrollBar::sub-page:vertical"
    "{background:transparent;}"
)


class Sidebar(QWidget):
    """左侧侧边栏: 连接模式选择 + 对应设置面板 + 连接按钮"""

    mode_changed = Signal(str)
    connect_clicked = Signal(str)
    disconnect_clicked = Signal(str)
    port_refresh_clicked = Signal()
    library_item_clicked = Signal(str)   # 工具库: 工具 key
    toolbox_item_clicked = Signal(str)   # 工具箱: 分类名
    project_changed = Signal(str)        # 选中了另一个项目
    project_menu_requested = Signal()    # 点击项目菜单按钮

    def __init__(self):
        super().__init__()
        self.setObjectName("sidebar")
        self.setStyleSheet(SIDEBAR_STYLE)
        self.setFixedWidth(260)

        self._current_mode = "serial"
        self._connected = False

        self._build()
        self._mode_group.buttons()[0].setChecked(True)
        self._on_mode_changed(0)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 14, 10, 14)
        layout.setSpacing(8)

        # -- 标题 --
        title = QLabel("Anhu 百宝箱")
        title.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        title.setStyleSheet("color: #1A1A1A; padding: 4px 0 2px 6px;")
        layout.addWidget(title)

        # 作者与版本号：前缀列等宽，使 "Jinchoo" 的 J 与 "V1.0.0" 的 V 左对齐
        info_grid = QGridLayout()
        info_grid.setHorizontalSpacing(0)
        info_grid.setVerticalSpacing(0)
        info_grid.setContentsMargins(6, 0, 0, 0)  # 与标题左缩进 6px 对齐
        info_grid.setColumnStretch(1, 1)

        author_key = QLabel("作者：")
        author_key.setFont(QFont("Microsoft YaHei", 10))
        author_key.setStyleSheet("color: #888; padding: 0 0 2px 0;")
        author_val = QLabel("Jinchoo（朱锦春）")
        author_val.setFont(QFont("Microsoft YaHei", 10))
        author_val.setStyleSheet("color: #888; padding: 0 0 2px 0;")

        version_key = QLabel("版本号：")
        version_key.setFont(QFont("Microsoft YaHei", 10))
        version_key.setStyleSheet("color: #888; padding: 0 0 16px 0;")
        version_val = QLabel("V1.0.0")
        version_val.setFont(QFont("Microsoft YaHei", 10))
        version_val.setStyleSheet("color: #888; padding: 0 0 16px 0;")

        # 前缀列统一取最大宽度，保证值列起点严格对齐
        key_width = max(author_key.sizeHint().width(), version_key.sizeHint().width())
        author_key.setFixedWidth(key_width)
        version_key.setFixedWidth(key_width)

        info_grid.addWidget(author_key, 0, 0)
        info_grid.addWidget(author_val, 0, 1)
        info_grid.addWidget(version_key, 1, 0)
        info_grid.addWidget(version_val, 1, 1)
        layout.addLayout(info_grid)

        # -- 功能控件容器 (串口调试页之外隐藏) --
        self._controls_widget = QWidget()
        ctrl_lo = QVBoxLayout(self._controls_widget)
        ctrl_lo.setContentsMargins(0, 0, 0, 0)
        ctrl_lo.setSpacing(8)

        # -- 项目区块 (一个项目 = 一整套连接/发送/显示/预设配置) --
        proj_head = QHBoxLayout()
        proj_head.setContentsMargins(4, 0, 0, 0)
        proj_label = QLabel("项目")
        proj_label.setStyleSheet("color: #3D3D3D; font-size: 14px; font-weight: 600;")
        proj_head.addWidget(proj_label)
        proj_head.addStretch()
        # "\ufe0e" 是"文本呈现"变体选择符: 不加它时 Windows 会用彩色 emoji 字体
        # 渲染这个齿轮, color 样式直接失效, 按钮里就变成一个突兀的彩色图标。
        self._btn_project_menu = QPushButton("⚙\ufe0e")
        self._btn_project_menu.setFixedSize(26, 24)
        self._btn_project_menu.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_project_menu.setToolTip("新建 / 重命名 / 复制 / 导入 / 导出 / 删除项目")
        self._btn_project_menu.setStyleSheet(
            "QPushButton{background:#E8F0FE;color:#0078D4;border:1px solid #B3D4FC;"
            "border-radius:4px;font-size:15px;padding:0}"
            "QPushButton:hover{background:#D0E4FC}QPushButton:pressed{background:#B3D4FC}"
        )
        self._btn_project_menu.clicked.connect(self.project_menu_requested.emit)
        proj_head.addWidget(self._btn_project_menu)
        ctrl_lo.addLayout(proj_head)

        self._cb_project = QComboBox()
        self._cb_project.setStyleSheet(COMBO_STYLE)   # 与参数配置下拉框同一套样式
        self._cb_project.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._cb_project.setToolTip("切换项目会整套切换连接参数、发送/显示配置和预设命令")
        self._cb_project.currentIndexChanged.connect(self._on_project_selected)
        ctrl_lo.addWidget(self._cb_project)

        # 串口号在本机不存在等异常时的提示行
        self._lbl_project_warn = QLabel("")
        self._lbl_project_warn.setWordWrap(True)
        self._lbl_project_warn.setStyleSheet("color:#D83B01;font-size:11px;padding:0 4px;")
        self._lbl_project_warn.setVisible(False)
        ctrl_lo.addWidget(self._lbl_project_warn)

        proj_sep = QFrame()
        proj_sep.setObjectName("separator")
        ctrl_lo.addWidget(proj_sep)

        # -- 连接模式标签 --
        mode_label = QLabel("连接模式")
        mode_label.setStyleSheet("color: #3D3D3D; font-size: 14px; font-weight: 600; padding: 8px 4px 4px 4px;")
        ctrl_lo.addWidget(mode_label)

        # -- 模式按钮组 --
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)

        modes = [
            ("serial",    "串口 (Serial)"),
            ("tcpserver", "TCP 服务器"),
            ("tcpclient", "TCP 客户端"),
        ]
        for i, (key, label) in enumerate(modes):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setProperty("class", "mode_btn")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._mode_group.addButton(btn, i)
            ctrl_lo.addWidget(btn)

        self._mode_group.idClicked.connect(self._on_mode_changed)

        # -- 分隔线 --
        sep = QFrame()
        sep.setObjectName("separator")
        ctrl_lo.addWidget(sep)

        # -- 设置标题 --
        self._settings_label = QLabel("参数配置")
        self._settings_label.setStyleSheet("color: #3D3D3D; font-size: 14px; font-weight: 600; padding: 8px 4px 4px 4px;")
        ctrl_lo.addWidget(self._settings_label)

        # -- 堆叠设置页 --
        self._settings_stack = QStackedWidget()
        self._settings_stack.addWidget(self._build_serial_page())
        self._settings_stack.addWidget(self._build_tcpserver_page())
        self._settings_stack.addWidget(self._build_tcpclient_page())

        # 窗口不够高时, 参数区应该出现滚动条, 而不是把每一行压扁
        inner = QWidget()
        inner_lo = QVBoxLayout(inner)
        inner_lo.setContentsMargins(0, 0, 0, 0)
        inner_lo.setSpacing(0)
        inner_lo.addWidget(self._settings_stack)
        inner_lo.addStretch(1)

        self._settings_scroll = QScrollArea()
        self._settings_scroll.setObjectName("settingsScroll")
        self._settings_scroll.setWidgetResizable(True)
        self._settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._settings_scroll.setWidget(inner)
        self._settings_scroll.setStyleSheet(SETTINGS_SCROLL_STYLE)
        ctrl_lo.addWidget(self._settings_scroll, stretch=1)

        # -- 刷新按钮 --
        self._btn_refresh = QPushButton("刷新串口列表")
        self._btn_refresh.clicked.connect(self.port_refresh_clicked.emit)
        ctrl_lo.addWidget(self._btn_refresh)

        # -- 连接按钮 (高度与连接模式按钮保持一致) --
        self._btn_connect = QPushButton("打开串口")
        self._btn_connect.setObjectName("btn_connect")
        self._btn_connect.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_connect.clicked.connect(self._on_connect_clicked)
        ctrl_lo.addWidget(self._btn_connect)

        layout.addWidget(self._controls_widget, stretch=1)

        # -- 工具库导航 (工具库 tab: 搜索框 + 分组列表) --
        self._library_nav = self._build_library_nav()
        self._library_nav.setVisible(False)
        layout.addWidget(self._library_nav, stretch=1)

        # -- 工具箱导航 (工具箱 tab: 搜索框 + 分类列表) --
        self._toolbox_nav = self._build_toolbox_nav()
        self._toolbox_nav.setVisible(False)
        layout.addWidget(self._toolbox_nav, stretch=1)

        # 兜底弹簧: 三块导航全部隐藏时(自定义库 tab)吃掉所有剩余高度,
        # 否则标题/作者/版本号这几个 QLabel 会被拉伸并垂直居中, 位置乱跳。
        # stretch 给 0, 这样三块导航可见时(它们 stretch=1)依旧占满剩余空间。
        layout.addStretch()

    def set_nav_mode(self, mode: str):
        """根据当前主 tab 切换左侧导航区。

        serial: 连接/参数面板; library: 工具库分组列表;
        toolbox: 工具箱分类列表; custom: 自定义库(无导航, 三块全隐藏)。
        """
        self._controls_widget.setVisible(mode == "serial")
        self._library_nav.setVisible(mode == "library")
        self._toolbox_nav.setVisible(mode == "toolbox")

    # ------------------------------------------------------------------
    # 项目 (一个项目 = 一整套工作环境: 连接/参数/发送/显示/预设)
    # ------------------------------------------------------------------
    def set_projects(self, names, current):
        """填充项目下拉框并选中 current"""
        self._cb_project.blockSignals(True)
        self._cb_project.clear()
        for n in (names or []):
            self._cb_project.addItem(n)
        self._select_silently(current)
        self._cb_project.blockSignals(False)

    def set_current_project(self, name):
        """仅同步下拉框选中项(不发信号, 避免递归)"""
        self._cb_project.blockSignals(True)
        self._select_silently(name)
        self._cb_project.blockSignals(False)

    def _select_silently(self, name):
        idx = self._cb_project.findText(name) if name else -1
        if idx < 0 and name:
            # 项目名不在下拉框里(如刚导入)时临时补一项
            self._cb_project.addItem(name)
            idx = self._cb_project.count() - 1
        if idx < 0 and self._cb_project.count():
            idx = 0
        if idx >= 0:
            self._cb_project.setCurrentIndex(idx)

    def set_project_warning(self, msg):
        """显示/隐藏项目异常提示(如串口号在本机不存在)"""
        self._lbl_project_warn.setText(msg or "")
        self._lbl_project_warn.setVisible(bool(msg))

    def project_menu_pos(self):
        """项目菜单的弹出位置(菜单按钮正下方)"""
        b = self._btn_project_menu
        return b.mapToGlobal(b.rect().bottomLeft())

    def _on_project_selected(self, idx):
        if idx < 0 or self._cb_project.count() == 0:
            return
        self.project_changed.emit(self._cb_project.itemText(idx))

    @property
    def current_project(self) -> str:
        return self._cb_project.currentText()

    # ------------------------------------------------------------------
    # 工具库导航 (内置工具: 搜索框 + 分组列表)
    # ------------------------------------------------------------------
    def _build_library_nav(self) -> QWidget:
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(8)

        self._library_search = QLineEdit()
        self._library_search.setPlaceholderText("搜索工具...")
        self._library_search.textChanged.connect(self._on_library_search)
        lo.addWidget(self._library_search)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        content = QWidget()
        self._library_list_lo = QVBoxLayout(content)
        self._library_list_lo.setContentsMargins(0, 4, 0, 0)
        self._library_list_lo.setSpacing(2)
        self._library_list_lo.addStretch()
        scroll.setWidget(content)
        lo.addWidget(scroll, stretch=1)

        # 分组结构数据
        self._library_groups_map = {}    # {组名: [key, ...]}
        self._library_labels = {}        # {key: 显示名}
        self._library_group_labels = {}  # {组名: QLabel}
        self._library_tool_buttons = {}  # {key: QPushButton}
        self._library_group = QButtonGroup(self)
        self._library_group.setExclusive(True)
        return w

    def set_library_groups(self, groups):
        """填充工具库分组列表。

        groups: [(组名, [(key, 显示名), ...]), ...]
        """
        # 清空旧项
        for btn in list(self._library_tool_buttons.values()):
            btn.deleteLater()
        for lbl in list(self._library_group_labels.values()):
            lbl.deleteLater()
        self._library_tool_buttons.clear()
        self._library_group_labels.clear()
        self._library_groups_map.clear()
        self._library_labels.clear()

        last = self._library_list_lo.count() - 1  # 末尾是 stretch
        for gname, items in groups:
            head = QLabel(gname)
            head.setStyleSheet(
                "color:#111827;font-size:13px;font-weight:700;"
                "padding:10px 6px 4px 6px;background:transparent;"
            )
            self._library_list_lo.insertWidget(last, head)
            self._library_group_labels[gname] = head
            last += 1

            keys = []
            for key, label in items:
                btn = self._make_library_btn(label)
                btn.clicked.connect(
                    lambda checked=False, k=key: self.library_item_clicked.emit(k)
                )
                self._library_group.addButton(btn)
                self._library_list_lo.insertWidget(last, btn)
                last += 1
                self._library_tool_buttons[key] = btn
                self._library_labels[key] = label
                keys.append(key)
            self._library_groups_map[gname] = keys

        # 默认选中第一个工具
        if groups and groups[0][1]:
            first = self._library_tool_buttons.get(groups[0][1][0][0])
            if first is not None:
                first.setChecked(True)

    @staticmethod
    def _make_library_btn(text):
        btn = QPushButton(text)
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            "QPushButton{color:#374151;background:transparent;border:none;"
            "border-radius:6px;padding:7px 10px 7px 18px;font-size:13px;text-align:left;}"
            "QPushButton:hover{background:#EBEEF3;}"
            "QPushButton:checked{background:#0078D4;color:#FFFFFF;font-weight:600;}"
        )
        return btn

    def _on_library_search(self, text):
        text = (text or "").strip().lower()
        for gname, keys in self._library_groups_map.items():
            any_visible = False
            for k in keys:
                hit = (text == "") or (text in self._library_labels[k].lower())
                self._library_tool_buttons[k].setVisible(hit)
                any_visible = any_visible or hit
            self._library_group_labels[gname].setVisible(any_visible)

    # ------------------------------------------------------------------
    # 工具箱导航 (外置工具: 搜索框 + 分类列表)
    # ------------------------------------------------------------------
    def _build_toolbox_nav(self) -> QWidget:
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(8)

        self._toolbox_search = QLineEdit()
        self._toolbox_search.setPlaceholderText("搜索分类...")
        self._toolbox_search.textChanged.connect(self._on_toolbox_search)
        lo.addWidget(self._toolbox_search)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        content = QWidget()
        self._toolbox_list_lo = QVBoxLayout(content)
        self._toolbox_list_lo.setContentsMargins(0, 4, 0, 0)
        self._toolbox_list_lo.setSpacing(2)
        self._toolbox_list_lo.addStretch()
        scroll.setWidget(content)
        lo.addWidget(scroll, stretch=1)

        self._toolbox_buttons = {}  # {分类名: QPushButton}
        self._toolbox_group = QButtonGroup(self)
        self._toolbox_group.setExclusive(True)
        return w

    def set_toolbox_categories(self, categories):
        """填充工具箱分类列表。categories: [分类名, ...]"""
        for btn in list(self._toolbox_buttons.values()):
            btn.deleteLater()
        self._toolbox_buttons.clear()

        last = self._toolbox_list_lo.count() - 1  # 末尾是 stretch
        for cat in categories:
            btn = self._make_nav_btn(cat)
            btn.clicked.connect(
                lambda checked=False, c=cat: self.toolbox_item_clicked.emit(c)
            )
            self._toolbox_group.addButton(btn)
            self._toolbox_list_lo.insertWidget(last, btn)
            last += 1
            self._toolbox_buttons[cat] = btn

        # 默认选中第一个分类
        if categories:
            first = self._toolbox_buttons.get(categories[0])
            if first is not None:
                first.setChecked(True)

    @staticmethod
    def _make_nav_btn(text):
        btn = QPushButton(text)
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            "QPushButton{color:#374151;background:transparent;border:none;"
            "border-radius:6px;padding:9px 10px;font-size:13px;text-align:left;}"
            "QPushButton:hover{background:#EBEEF3;}"
            "QPushButton:checked{background:#0078D4;color:#FFFFFF;font-weight:600;}"
        )
        return btn

    def _on_toolbox_search(self, text):
        text = (text or "").strip().lower()
        for cat, btn in self._toolbox_buttons.items():
            btn.setVisible(text == "" or text in cat.lower())

    def _build_serial_page(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        # 统一用 QGridLayout: 标签列宽一致, 所有下拉框左对齐
        form = QGridLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(8)
        form.setColumnStretch(1, 1)

        labels = ["串口号", "波特率", "数据位", "停止位", "校验位", "流控"]
        lab_widgets = [QLabel(t) for t in labels]
        lw = max(lab.sizeHint().width() for lab in lab_widgets)
        for lab in lab_widgets:
            lab.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
            lab.setMinimumWidth(lw)

        self._cb_port = QComboBox()
        self._cb_port.setEditable(True)
        self._cb_port.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._cb_baud = QComboBox()
        self._cb_baud.setEditable(True)
        self._cb_baud.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._cb_baud.addItems(["300","1200","2400","4800","9600","14400","19200",
                                "28800","38400","57600","115200","230400","460800","921600"])
        self._cb_baud.setCurrentText("115200")

        self._cb_data = QComboBox()
        self._cb_data.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._cb_data.addItems(["5","6","7","8"])
        self._cb_data.setCurrentText("8")

        self._cb_stop = QComboBox()
        self._cb_stop.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._cb_stop.addItems(["1", "1.5", "2"])

        self._cb_parity = QComboBox()
        self._cb_parity.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._cb_parity.addItems(["None", "Even", "Odd", "Mark", "Space"])

        self._cb_flow = QComboBox()
        self._cb_flow.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._cb_flow.addItems(["None", "RTS/CTS", "XON/XOFF"])

        for i, (lab, combo) in enumerate(zip(lab_widgets, [
                self._cb_port, self._cb_baud, self._cb_data,
                self._cb_stop, self._cb_parity, self._cb_flow])):
            combo.setStyleSheet(COMBO_STYLE)   # 与项目下拉框同一套样式
            form.addWidget(lab, i, 0, Qt.AlignLeft)
            form.addWidget(combo, i, 1)

        outer.addLayout(form)

        return w

    def _build_tcpserver_page(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        # 用网格布局让"监听端口"和"客户端超时(s)"两个输入框的左边对齐.
        # 标签作为 col0, SpinBox 作为 col1, col1 stretch=1 占满.
        form = QGridLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(8)
        form.setColumnStretch(1, 1)

        lab_port = QLabel("监听端口")
        lab_tmo = QLabel("客户端超时(s)")
        # 给两个标签设成等宽, 保证 spinbox 起点严格对齐.
        lw = max(lab_port.sizeHint().width(), lab_tmo.sizeHint().width())
        for lab in (lab_port, lab_tmo):
            lab.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
            lab.setMinimumWidth(lw)

        self._sp_server_port = QSpinBox()
        self._sp_server_port.setRange(1, 65535)
        self._sp_server_port.setValue(8888)

        self._sp_client_timeout = QSpinBox()
        self._sp_client_timeout.setRange(0, 3600)
        self._sp_client_timeout.setValue(30)
        self._sp_client_timeout.setToolTip(
            "客户端连接后超过该时间(s)未收到任何数据则判定为断开\n(适用于拔网线等不发 RST/FIN 的场景)\n0 = 禁用超时检测")

        form.addWidget(lab_port, 0, 0, Qt.AlignLeft)
        form.addWidget(self._sp_server_port, 0, 1)
        form.addWidget(lab_tmo, 1, 0, Qt.AlignLeft)
        form.addWidget(self._sp_client_timeout, 1, 1)

        outer.addLayout(form)
        outer.addStretch()
        return w

    def _build_tcpclient_page(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        # 与 TCP 服务器页一致: 用 QGridLayout 保证三个输入框左对齐
        form = QGridLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(8)
        form.setColumnStretch(1, 1)

        lab_host = QLabel("远端地址")
        lab_port = QLabel("远端端口")
        lab_lport = QLabel("本地端口")
        # 等宽标签: 输入框起点严格一致
        lw = max(lab_host.sizeHint().width(),
                 lab_port.sizeHint().width(),
                 lab_lport.sizeHint().width())
        for lab in (lab_host, lab_port, lab_lport):
            lab.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
            lab.setMinimumWidth(lw)

        self._le_client_host = QLineEdit()
        self._le_client_host.setPlaceholderText("127.0.0.1")
        self._le_client_host.setText("127.0.0.1")

        self._sp_client_port = QSpinBox()
        self._sp_client_port.setRange(1, 65535)
        self._sp_client_port.setValue(8888)

        # QLineEdit: 留空 = 由系统自动分配(随机), 填 1-65535 = 固定本地端口.
        # 用 QIntValidator 限制只能输入 1-65535 的数字 (留空合法).
        self._le_local_port = QLineEdit()
        self._le_local_port.setPlaceholderText("为空则随机使用本地端口")
        self._le_local_port.setValidator(QIntValidator(1, 65535))
        self._le_local_port.setToolTip(
            "客户端连接时使用的本地端口.\n"
            "留空 = 由系统自动分配; 填具体数字(1-65535) = 固定使用该端口")

        form.addWidget(lab_host, 0, 0, Qt.AlignLeft)
        form.addWidget(self._le_client_host, 0, 1)
        form.addWidget(lab_port, 1, 0, Qt.AlignLeft)
        form.addWidget(self._sp_client_port, 1, 1)
        form.addWidget(lab_lport, 2, 0, Qt.AlignLeft)
        form.addWidget(self._le_local_port, 2, 1)

        outer.addLayout(form)
        outer.addStretch()
        return w

    def _on_mode_changed(self, idx: int):
        modes = ["serial", "tcpserver", "tcpclient"]
        self._current_mode = modes[idx]
        self._settings_stack.setCurrentIndex(idx)

        is_serial = (self._current_mode == "serial")
        self._btn_refresh.setVisible(is_serial)

        if self._connected:
            return
        labels = {"serial": "打开串口", "tcpserver": "启动服务器", "tcpclient": "连接服务器"}
        self._btn_connect.setText(labels[self._current_mode])

        self.mode_changed.emit(self._current_mode)

    def _on_connect_clicked(self):
        if self._connected:
            self.disconnect_clicked.emit(self._current_mode)
        else:
            self.connect_clicked.emit(self._current_mode)

    def set_connected(self, connected: bool):
        self._connected = connected
        labels = {"serial": "打开串口", "tcpserver": "启动服务器", "tcpclient": "连接服务器"}
        disc_labels = {"serial": "关闭串口", "tcpserver": "停止服务器", "tcpclient": "断开连接"}

        if connected:
            self._btn_connect.setText(disc_labels[self._current_mode])
            self._btn_connect.setProperty("connected", "true")
        else:
            self._btn_connect.setText(labels[self._current_mode])
            self._btn_connect.setProperty("connected", "false")
        self._btn_connect.style().unpolish(self._btn_connect)
        self._btn_connect.style().polish(self._btn_connect)

    def set_controls_enabled(self, enabled: bool):
        for btn in self._mode_group.buttons():
            btn.setEnabled(enabled)
        widgets = [
            self._cb_port, self._cb_baud, self._cb_data, self._cb_stop,
            self._cb_parity, self._cb_flow, self._sp_server_port,
            self._sp_client_timeout,
            self._le_client_host, self._sp_client_port, self._le_local_port
        ]
        for w in widgets:
            w.setEnabled(enabled)

    @property
    def cb_port(self) -> QComboBox:
        return self._cb_port

    @property
    def cb_baud(self) -> QComboBox:
        return self._cb_baud

    @property
    def cb_data(self) -> QComboBox:
        return self._cb_data

    @property
    def cb_stop(self) -> QComboBox:
        return self._cb_stop

    @property
    def cb_parity(self) -> QComboBox:
        return self._cb_parity

    @property
    def cb_flow(self) -> QComboBox:
        return self._cb_flow

    @property
    def sp_server_port(self) -> QSpinBox:
        return self._sp_server_port

    @property
    def sp_client_timeout(self) -> QSpinBox:
        return self._sp_client_timeout

    @property
    def le_client_host(self) -> QLineEdit:
        return self._le_client_host

    @property
    def sp_client_port(self) -> QSpinBox:
        return self._sp_client_port

    @property
    def le_local_port(self) -> QLineEdit:
        return self._le_local_port

    @property
    def current_mode(self) -> str:
        return self._current_mode

    @property
    def is_connected(self) -> bool:
        return self._connected
