# -*- coding: utf-8 -*-
"""AnhuToolbox 侧边栏 -- 连接模式选择与参数配置"""

import os

from PySide6.QtWidgets import (
    QAbstractItemView, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox,
    QPushButton, QSpinBox, QStackedWidget, QLineEdit, QCheckBox,
    QFrame, QButtonGroup, QSizePolicy, QScrollArea, QApplication,
    QTreeWidget, QTreeWidgetItem, QStyle, QStyledItemDelegate,
    QMenu, QHeaderView,
)
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QIntValidator
from PySide6.QtCore import QEvent, QRect, QTimer, Qt, Signal
from PySide6.QtGui import QFont

from .styles import _find_assets_dir, SIDEBAR_STYLE, COMBO_STYLE, prepare_menu
from .dialogs import ask_yes_no, get_text
from .ui_tokens import HTTP_METHOD_COLORS, PROTOCOL_SETTINGS_STYLE
from .version import __version__


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


_HTTP_KIND_ROLE = Qt.ItemDataRole.UserRole + 1
_HTTP_ID_ROLE = Qt.ItemDataRole.UserRole
_HTTP_METHOD_ROLE = Qt.ItemDataRole.UserRole + 2
_HTTP_NAME_ROLE = Qt.ItemDataRole.UserRole + 3
_HTTP_URL_ROLE = Qt.ItemDataRole.UserRole + 4
_HTTP_FOLDER_ROLE = Qt.ItemDataRole.UserRole + 5
_HTTP_COUNT_ROLE = Qt.ItemDataRole.UserRole + 6
_HTTP_DIRTY_ROLE = Qt.ItemDataRole.UserRole + 7
_HTTP_DRAFT_ROLE = Qt.ItemDataRole.UserRole + 8
_HTTP_MENU_WIDTH = 26
_BRANCH_RIGHT_ICON = os.path.join(
    _find_assets_dir(), "http_next.svg").replace("\\", "/")
_BRANCH_DOWN_ICON = os.path.join(
    _find_assets_dir(), "http_chevron_down.svg").replace("\\", "/")


def _http_menu_button_rect(row_rect):
    return QRect(
        row_rect.right() - _HTTP_MENU_WIDTH - 4,
        row_rect.top(),
        _HTTP_MENU_WIDTH,
        row_rect.height(),
    )


class HttpLibraryDelegate(QStyledItemDelegate):
    """接口树单列绘制：彩色方法名、文件夹图标和计数。"""

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(32)
        return size

    def paint(self, painter, option, index):
        painter.save()
        rect = option.rect.adjusted(1, 1, -1, -1)
        tree = option.widget
        hovered_item = (
            tree.hovered_item
            if isinstance(tree, HttpLibraryTree) else None
        )
        index_item = (
            tree.itemFromIndex(index)
            if isinstance(tree, HttpLibraryTree) else None
        )
        is_hovered = (
            index_item is not None and index_item is hovered_item
        )
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(rect, QColor("#E8EEF5"))
        elif is_hovered:
            painter.fillRect(rect, QColor("#F1F4F7"))

        kind = index.data(_HTTP_KIND_ROLE)
        name = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        text_rect = rect.adjusted(6, 0, -6, 0)
        text_rect.setTop(rect.top() + 6)
        text_rect.setBottom(rect.bottom() - 6)
        metrics = QFontMetrics(option.font)
        if kind == "folder":
            icon = option.widget.style().standardIcon(
                QStyle.StandardPixmap.SP_DirIcon)
            icon.paint(
                painter,
                text_rect.adjusted(0, 2, 0, -2),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            )
            count = int(index.data(_HTTP_COUNT_ROLE) or 0)
            display = "{}  ({})".format(name, count)
            painter.setPen(QColor("#3D4652"))
            painter.drawText(
                text_rect.adjusted(24, 0, 0, 0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                metrics.elidedText(
                    display, Qt.TextElideMode.ElideRight,
                    max(0, text_rect.width() - 24)),
            )
        else:
            method = str(index.data(_HTTP_METHOD_ROLE) or "GET").upper()
            dirty = bool(index.data(_HTTP_DIRTY_ROLE))
            display_name = "{} ●".format(name) if dirty else name
            show_menu = is_hovered
            menu_width = _HTTP_MENU_WIDTH if show_menu else 0
            painter.setPen(
                QColor(HTTP_METHOD_COLORS.get(method, "#5B6470")))
            method_width = 48
            painter.drawText(
                text_rect.adjusted(0, 0, -text_rect.width() + method_width, 0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                method,
            )
            painter.setPen(QColor("#30343B"))
            painter.drawText(
                text_rect.adjusted(52, 0, 0, 0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                metrics.elidedText(
                    display_name, Qt.TextElideMode.ElideRight,
                    max(0, text_rect.width() - 52 - menu_width)),
            )
            if show_menu:
                painter.setPen(QColor("#68727D"))
                painter.drawText(
                    _http_menu_button_rect(rect),
                    Qt.AlignmentFlag.AlignCenter,
                    "···",
                )
        painter.restore()


class HttpLibraryTree(QTreeWidget):
    """在悬停接口行显示与右键一致的菜单入口。"""

    menu_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self._hovered_item = None

    @property
    def hovered_item(self):
        return self._hovered_item

    def _set_hovered_item(self, item):
        if item is self._hovered_item:
            return
        previous = self._hovered_item
        self._hovered_item = item
        if previous is not None:
            self.viewport().update(self.visualItemRect(previous))
        if item is not None:
            self.viewport().update(self.visualItemRect(item))

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        self._set_hovered_item(
            self.itemAt(event.position().toPoint()))

    def leaveEvent(self, event):
        self._set_hovered_item(None)
        super().leaveEvent(event)

    def menu_button_rect(self, item):
        return _http_menu_button_rect(self.visualItemRect(item))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            position = event.position().toPoint()
            item = self.itemAt(position)
            if (
                item is not None
                and item.data(0, _HTTP_KIND_ROLE) == "interface"
                and self.menu_button_rect(item).contains(position)
            ):
                self.menu_requested.emit(position)
                event.accept()
                return
        super().mouseReleaseEvent(event)


class CurrentPageStackedWidget(QStackedWidget):
    """滚动区只按当前模式页面的真实高度计算尺寸。"""

    def sizeHint(self):
        current = self.currentWidget()
        return current.sizeHint() if current is not None else super().sizeHint()

    def minimumSizeHint(self):
        current = self.currentWidget()
        return (
            current.minimumSizeHint()
            if current is not None else super().minimumSizeHint()
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
    http_interface_selected = Signal(str)
    http_new_requested = Signal()
    http_import_requested = Signal()
    http_export_requested = Signal()
    http_folder_selected = Signal(object)
    http_new_folder_requested = Signal(str, object)
    http_rename_requested = Signal(str, str, str)
    http_move_requested = Signal(str, object)
    http_duplicate_requested = Signal(str)
    http_delete_interface_requested = Signal(str)
    http_delete_folder_requested = Signal(str)
    mqtt_server_settings_changed = Signal()
    mqtt_server_start_requested = Signal()
    mqtt_server_stop_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("sidebar")
        self.setStyleSheet(SIDEBAR_STYLE)
        self.setFixedWidth(260)

        self._current_mode = "serial"
        self._connected = False
        self._mqtt_server_mode = False
        self._mqtt_server_running = False
        self._mqtt_server_available = True
        self._wheel_active_control = None
        self._http_pending_expand_ids = set()
        self._http_expanded_target_folder_id = None

        self._build()
        self._install_focus_wheel_filters()
        self._mode_group.buttons()[0].setChecked(True)
        self._on_mode_changed(0)

    def _install_focus_wheel_filters(self):
        """参数控件只有获得焦点后才允许滚轮改值。"""
        for widget in (
            self.findChildren(QSpinBox) + self.findChildren(QComboBox)
        ):
            widget.installEventFilter(self)
            editor = widget.lineEdit()
            if editor is not None:
                editor.installEventFilter(self)
        self._settings_scroll.viewport().installEventFilter(self)

    @staticmethod
    def _wheel_control(widget):
        if isinstance(widget, (QSpinBox, QComboBox)):
            return widget
        parent = widget.parentWidget()
        while parent is not None:
            if isinstance(parent, (QSpinBox, QComboBox)):
                return parent
            parent = parent.parentWidget()
        return None

    def _wheel_control_is_active(self, widget):
        return (
            widget is self._wheel_active_control
            and widget.hasFocus()
        )

    def eventFilter(self, watched, event):
        if (
            event.type() == QEvent.Type.Resize
            and hasattr(self, "_http_interface_tree")
            and watched is self._http_interface_tree.viewport()
        ):
            QTimer.singleShot(0, self._update_http_tree_width)
            return super().eventFilter(watched, event)
        control = self._wheel_control(watched)
        if event.type() == QEvent.Type.FocusIn and control is not None:
            if event.reason() in (
                    Qt.FocusReason.MouseFocusReason,
                    Qt.FocusReason.TabFocusReason):
                self._wheel_active_control = control
            return super().eventFilter(watched, event)
        if event.type() == QEvent.Type.FocusOut and control is not None:
            if self._wheel_active_control is control:
                self._wheel_active_control = None
            return super().eventFilter(watched, event)
        if (
            event.type() == QEvent.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.LeftButton
        ):
            if control is not None:
                self._wheel_active_control = control
            elif watched is self._settings_scroll.viewport():
                self._wheel_active_control = None
        if event.type() == QEvent.Type.Wheel and control is not None:
            if not self._wheel_control_is_active(control):
                bar = self._settings_scroll.verticalScrollBar()
                delta = event.angleDelta().y()
                if delta:
                    lines = QApplication.wheelScrollLines()
                    if lines < 0:
                        amount = bar.pageStep()
                    else:
                        amount = bar.singleStep() * max(1, lines)
                    bar.setValue(
                        bar.value() - int(round(delta / 120.0 * amount)))
                else:
                    pixel_delta = event.pixelDelta().y()
                    if pixel_delta:
                        bar.setValue(bar.value() - pixel_delta)
                event.accept()
                return True
            if watched is not control:
                control.wheelEvent(event)
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 12, 10, 8)
        layout.setSpacing(6)

        # -- 标题 --
        title = QLabel("Anhu 百宝箱")
        title.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        title.setStyleSheet("color: #1A1A1A; padding: 4px 0 2px 6px;")
        layout.addWidget(title)

        # 作者与版本号：前缀列等宽，保证两行值列左对齐
        info_grid = QGridLayout()
        info_grid.setHorizontalSpacing(0)
        info_grid.setVerticalSpacing(0)
        info_grid.setContentsMargins(6, 0, 0, 0)  # 与标题左缩进 6px 对齐
        info_grid.setColumnStretch(1, 1)

        author_key = QLabel("作者：")
        author_key.setFont(QFont("Microsoft YaHei", 10))
        author_key.setStyleSheet("color: #888; padding: 0 0 2px 0;")
        author_val = QLabel("Jinchoo Zhu | Jerry Lyu")
        author_val.setFont(QFont("Microsoft YaHei", 10))
        author_val.setStyleSheet("color: #888; padding: 0 0 2px 0;")

        version_key = QLabel("版本号：")
        version_key.setFont(QFont("Microsoft YaHei", 10))
        version_key.setStyleSheet("color: #888; padding: 0 0 8px 0;")
        version_val = QLabel(f"V{__version__}")
        version_val.setFont(QFont("Microsoft YaHei", 10))
        version_val.setStyleSheet("color: #888; padding: 0 0 8px 0;")

        # 前缀列统一取最大宽度，保证值列起点严格对齐
        key_width = max(author_key.sizeHint().width(), version_key.sizeHint().width())
        author_key.setFixedWidth(key_width)
        version_key.setFixedWidth(key_width)

        info_grid.addWidget(author_key, 0, 0)
        info_grid.addWidget(author_val, 0, 1)
        info_grid.addWidget(version_key, 1, 0)
        info_grid.addWidget(version_val, 1, 1)
        layout.addLayout(info_grid)

        # -- 功能控件容器 (通信调试页之外隐藏) --
        self._controls_widget = QWidget()
        ctrl_lo = QVBoxLayout(self._controls_widget)
        ctrl_lo.setContentsMargins(0, 0, 0, 0)
        ctrl_lo.setSpacing(6)

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
        self._cb_project.setToolTip(
            "每个项目独立保存六种通信模式的参数、编辑内容、当前模式和预设命令")
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
        mode_label.setStyleSheet("color: #3D3D3D; font-size: 14px; font-weight: 600; padding: 4px 4px 2px 4px;")
        ctrl_lo.addWidget(mode_label)

        # -- 模式按钮组 --
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)

        modes = [
            ("serial",    "串口", "串口 (Serial)"),
            ("tcpserver", "TCP 服务端", "TCP 服务器"),
            ("tcpclient", "TCP 客户端", "TCP 客户端"),
            ("mqtt",      "MQTT", "MQTT 客户端"),
            ("websocket", "WebSocket", "WebSocket 客户端"),
            ("http",      "HTTP", "HTTP 请求"),
        ]
        mode_grid = QGridLayout()
        mode_grid.setHorizontalSpacing(6)
        mode_grid.setVerticalSpacing(6)
        mode_grid.setContentsMargins(0, 0, 0, 0)
        mode_grid.setColumnStretch(0, 1)
        mode_grid.setColumnStretch(1, 1)
        mode_grid.setColumnStretch(2, 1)
        for i, (_key, label, tooltip) in enumerate(modes):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setToolTip(tooltip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            # 三列等宽，按钮文字按 13px 字号排列；水平方向忽略 sizeHint，
            # 避免 WebSocket 的长英文名称把另外两列挤成不同宽度。
            btn.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            btn.setFixedHeight(30)
            btn.setStyleSheet(
                "QPushButton{background:transparent;border:1px solid transparent;"
                "border-radius:5px;padding:4px 2px;font-size:13px;"
                "font-weight:500;color:#666;text-align:center;}"
                "QPushButton:hover{background:#E8F0FE;color:#1A1A1A;}"
                "QPushButton:checked{background:#E8F0FE;border-color:#0078D4;"
                "color:#0078D4;font-weight:500;}"
            )
            self._mode_group.addButton(btn, i)
            mode_grid.addWidget(btn, i // 3, i % 3)

        self._mode_group.idClicked.connect(self._on_mode_changed)
        ctrl_lo.addLayout(mode_grid)

        # -- 分隔线 --
        sep = QFrame()
        sep.setObjectName("separator")
        ctrl_lo.addWidget(sep)

        # -- 设置标题 --
        self._settings_label = QLabel("参数配置")
        self._settings_label.setStyleSheet("color: #3D3D3D; font-size: 14px; font-weight: 600; padding: 4px 4px 2px 4px;")
        settings_head = QHBoxLayout()
        settings_head.setContentsMargins(0, 0, 0, 0)
        settings_head.addWidget(self._settings_label)
        settings_head.addStretch()
        self._btn_http_transfer_menu = QPushButton("···")
        self._btn_http_transfer_menu.setFixedSize(30, 26)
        self._btn_http_transfer_menu.setCursor(
            Qt.CursorShape.PointingHandCursor)
        self._btn_http_transfer_menu.setToolTip("导入导出")
        self._btn_http_transfer_menu.setStyleSheet(
            "QPushButton{background:transparent;color:#5F6873;"
            "border:none;border-radius:5px;font-size:17px;padding:0;}"
            "QPushButton:hover{background:#E8EEF5;color:#0078D4;}")
        self._btn_http_transfer_menu.clicked.connect(
            self._show_http_transfer_menu)
        settings_head.addWidget(self._btn_http_transfer_menu)
        ctrl_lo.addLayout(settings_head)

        # -- 堆叠设置页 --
        self._settings_stack = CurrentPageStackedWidget()
        self._settings_stack.addWidget(self._build_serial_page())
        self._settings_stack.addWidget(self._build_tcpserver_page())
        self._settings_stack.addWidget(self._build_tcpclient_page())
        self._mqtt_client_settings_page = self._build_mqtt_page()
        self._settings_stack.addWidget(self._mqtt_client_settings_page)
        self._settings_stack.addWidget(self._build_websocket_page())
        self._settings_stack.addWidget(self._build_http_page())
        self._mqtt_server_settings_page = self._build_mqtt_server_page()
        self._settings_stack.addWidget(self._mqtt_server_settings_page)

        # 窗口不够高时, 参数区应该出现滚动条, 而不是把每一行压扁
        inner = QWidget()
        inner_lo = QVBoxLayout(inner)
        inner_lo.setContentsMargins(0, 0, 0, 0)
        inner_lo.setSpacing(0)
        inner_lo.addWidget(self._settings_stack)
        inner_lo.addStretch(1)
        self._settings_inner_layout = inner_lo

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
        self._library_standalone_buttons = {}
        self._library_standalone_separator = None
        self._library_group = QButtonGroup(self)
        self._library_group.setExclusive(True)
        return w

    def set_library_groups(self, groups, standalone_items=None):
        """填充工具库分组列表。

        groups: [(组名, [(key, 显示名), ...]), ...]
        standalone_items: [(key, 显示名), ...]，显示在所有分组之前
        """
        standalone_items = list(standalone_items or [])
        # 清空旧项
        for btn in list(self._library_tool_buttons.values()):
            btn.deleteLater()
        for btn in list(self._library_standalone_buttons.values()):
            btn.deleteLater()
        for lbl in list(self._library_group_labels.values()):
            lbl.deleteLater()
        if self._library_standalone_separator is not None:
            self._library_standalone_separator.deleteLater()
            self._library_standalone_separator = None
        self._library_tool_buttons.clear()
        self._library_standalone_buttons.clear()
        self._library_group_labels.clear()
        self._library_groups_map.clear()
        self._library_labels.clear()

        last = self._library_list_lo.count() - 1  # 末尾是 stretch
        for key, label in standalone_items:
            btn = self._make_library_btn(label)
            btn.clicked.connect(
                lambda checked=False, k=key:
                self.library_item_clicked.emit(k))
            self._library_group.addButton(btn)
            self._library_list_lo.insertWidget(last, btn)
            last += 1
            self._library_tool_buttons[key] = btn
            self._library_standalone_buttons[key] = btn
            self._library_labels[key] = label
        if standalone_items and groups:
            separator = QFrame()
            separator.setObjectName("separator")
            separator.setFixedHeight(1)
            self._library_list_lo.insertWidget(last, separator)
            self._library_standalone_separator = separator
            last += 1

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
        first_key = None
        if standalone_items:
            first_key = standalone_items[0][0]
        elif groups and groups[0][1]:
            first_key = groups[0][1][0][0]
        if first_key is not None:
            first = self._library_tool_buttons.get(first_key)
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
        standalone_visible = False
        for key, btn in self._library_standalone_buttons.items():
            hit = (text == "") or (
                text in self._library_labels[key].lower())
            btn.setVisible(hit)
            standalone_visible = standalone_visible or hit
        if self._library_standalone_separator is not None:
            self._library_standalone_separator.setVisible(
                standalone_visible)
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
        form.setVerticalSpacing(5)
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
                self._cb_stop, self._cb_parity, self._cb_flow],
                strict=False)):
            combo.setStyleSheet(COMBO_STYLE)   # 与项目下拉框同一套样式
            form.addWidget(lab, i, 0, Qt.AlignLeft)
            form.addWidget(combo, i, 1)

        outer.addLayout(form)
        outer.addStretch(1)

        return w

    def _build_tcpserver_page(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        # 用网格布局让"监听端口"和"超时(s)"两个输入框的左边对齐.
        # 标签作为 col0, SpinBox 作为 col1, col1 stretch=1 占满.
        form = QGridLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(5)
        form.setColumnStretch(1, 1)

        lab_port = QLabel("监听端口")
        lab_tmo = QLabel("超时(s)")
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
        form.setVerticalSpacing(5)
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

    @staticmethod
    def _form_label(labels):
        widths = [label.sizeHint().width() for label in labels]
        if widths:
            width = max(widths)
            for label in labels:
                label.setMinimumWidth(width)
        return labels

    def _build_mqtt_page(self) -> QWidget:
        w = QWidget()
        w.setObjectName("mqttSettingsPage")
        w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        w.setStyleSheet(PROTOCOL_SETTINGS_STYLE)
        outer = QVBoxLayout(w)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)
        form = QGridLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(8)
        form.setColumnStretch(1, 1)

        labels = self._form_label([
            QLabel("服务端IP"), QLabel("端口"), QLabel("客户端 ID"),
            QLabel("用户名"), QLabel("密码"), QLabel("心跳间隔(秒)"),
            QLabel("协议"),
        ])
        self._le_mqtt_host = QLineEdit()
        self._le_mqtt_host.setPlaceholderText("例如：127.0.0.1")
        self._sp_mqtt_port = QSpinBox()
        self._sp_mqtt_port.setRange(1, 65535)
        self._sp_mqtt_port.setValue(1883)
        self._le_mqtt_client_id = QLineEdit()
        self._le_mqtt_client_id.setPlaceholderText("留空自动生成")
        self._le_mqtt_user = QLineEdit()
        self._le_mqtt_password = QLineEdit()
        self._le_mqtt_password.setEchoMode(QLineEdit.Password)
        self._le_mqtt_password.setToolTip(
            "密码会随当前项目保存在本地 JSON 中，请勿直接分享项目文件")
        self._mqtt_password_toggle_action = \
            self._le_mqtt_password.addAction(
                QIcon(os.path.join(
                    _find_assets_dir(), "password_show.svg")),
                QLineEdit.ActionPosition.TrailingPosition,
            )
        self._mqtt_password_toggle_action.setToolTip("显示密码")
        self._mqtt_password_toggle_action.triggered.connect(
            lambda _checked=False: self._toggle_password_visibility(
                self._le_mqtt_password,
                self._mqtt_password_toggle_action,
            )
        )
        self._sp_mqtt_keepalive = QSpinBox()
        self._sp_mqtt_keepalive.setRange(5, 3600)
        self._sp_mqtt_keepalive.setValue(60)
        self._cb_mqtt_protocol = QComboBox()
        self._cb_mqtt_protocol.addItems(["MQTT 3.1.1", "MQTT 5.0"])
        for widget in (
                self._le_mqtt_host, self._sp_mqtt_port,
                self._le_mqtt_client_id, self._le_mqtt_user,
                self._le_mqtt_password, self._sp_mqtt_keepalive,
                self._cb_mqtt_protocol):
            widget.setFixedHeight(32)

        widgets = [
            self._le_mqtt_host, self._sp_mqtt_port,
            self._le_mqtt_client_id, self._le_mqtt_user,
            self._le_mqtt_password, self._sp_mqtt_keepalive,
            self._cb_mqtt_protocol,
        ]
        for row, (label, widget) in enumerate(
                zip(labels, widgets, strict=False)):
            form.addWidget(label, row, 0, Qt.AlignLeft)
            form.addWidget(widget, row, 1)

        self._chk_mqtt_tls = QCheckBox("启用 TLS")
        self._chk_mqtt_clean = QCheckBox("清理会话")
        self._chk_mqtt_clean.setChecked(True)
        self._chk_mqtt_reconnect = QCheckBox("自动重连")
        self._chk_mqtt_reconnect.setChecked(True)
        form.addWidget(self._chk_mqtt_tls, 7, 0, 1, 2)
        form.addWidget(self._chk_mqtt_clean, 8, 0, 1, 2)
        form.addWidget(self._chk_mqtt_reconnect, 9, 0, 1, 2)
        outer.addLayout(form)
        outer.addStretch()
        return w

    def _build_mqtt_server_page(self) -> QWidget:
        w = QWidget()
        w.setObjectName("mqttServerSettingsPage")
        w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        w.setStyleSheet(PROTOCOL_SETTINGS_STYLE)
        outer = QVBoxLayout(w)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)
        form = QGridLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(8)
        form.setColumnStretch(1, 1)

        labels = self._form_label([
            QLabel("监听地址"), QLabel("端口"),
            QLabel("最大连接"), QLabel("用户名"), QLabel("密码"),
        ])
        self._le_mqtt_server_bind = QLineEdit("127.0.0.1")
        self._le_mqtt_server_bind.setPlaceholderText("127.0.0.1 或 0.0.0.0")
        self._le_mqtt_server_bind.setToolTip(
            "127.0.0.1 仅本机可连接；0.0.0.0 允许局域网连接")
        self._sp_mqtt_server_port = QSpinBox()
        self._sp_mqtt_server_port.setRange(1, 65535)
        self._sp_mqtt_server_port.setValue(1883)
        self._sp_mqtt_server_max_connections = QSpinBox()
        self._sp_mqtt_server_max_connections.setRange(1, 100000)
        self._sp_mqtt_server_max_connections.setValue(100)
        self._le_mqtt_server_user = QLineEdit()
        self._le_mqtt_server_user.setPlaceholderText("关闭匿名连接时必填")
        self._le_mqtt_server_user.setEnabled(False)
        self._le_mqtt_server_password = QLineEdit()
        self._le_mqtt_server_password.setEchoMode(QLineEdit.Password)
        self._le_mqtt_server_password.setPlaceholderText(
            "关闭匿名连接时必填")
        self._le_mqtt_server_password.setEnabled(False)
        self._mqtt_server_password_toggle_action = \
            self._le_mqtt_server_password.addAction(
                QIcon(os.path.join(
                    _find_assets_dir(), "password_show.svg")),
                QLineEdit.ActionPosition.TrailingPosition,
            )
        self._mqtt_server_password_toggle_action.setToolTip("显示密码")
        self._mqtt_server_password_toggle_action.triggered.connect(
            lambda _checked=False: self._toggle_password_visibility(
                self._le_mqtt_server_password,
                self._mqtt_server_password_toggle_action,
            )
        )
        for widget in (
            self._le_mqtt_server_bind,
            self._sp_mqtt_server_port,
            self._sp_mqtt_server_max_connections,
            self._le_mqtt_server_user,
            self._le_mqtt_server_password,
        ):
            widget.setFixedHeight(32)
        widgets = [
            self._le_mqtt_server_bind,
            self._sp_mqtt_server_port,
            self._sp_mqtt_server_max_connections,
            self._le_mqtt_server_user,
            self._le_mqtt_server_password,
        ]
        for row, (label, widget) in enumerate(
                zip(labels, widgets, strict=False)):
            form.addWidget(label, row, 0, Qt.AlignLeft)
            form.addWidget(widget, row, 1)

        self._chk_mqtt_server_anonymous = QCheckBox("允许匿名连接")
        self._chk_mqtt_server_anonymous.setChecked(True)
        form.addWidget(self._chk_mqtt_server_anonymous, 5, 0, 1, 2)
        outer.addLayout(form)
        outer.addStretch()

        self._chk_mqtt_server_anonymous.toggled.connect(
            self._on_mqtt_server_anonymous_toggled)
        for field in (
            self._le_mqtt_server_bind,
            self._le_mqtt_server_user,
            self._le_mqtt_server_password,
        ):
            field.editingFinished.connect(
                lambda: self.mqtt_server_settings_changed.emit())
        for spin in (
            self._sp_mqtt_server_port,
            self._sp_mqtt_server_max_connections,
        ):
            spin.valueChanged.connect(
                lambda _value: self.mqtt_server_settings_changed.emit())
        self._chk_mqtt_server_anonymous.toggled.connect(
            lambda _checked: self.mqtt_server_settings_changed.emit())
        return w

    def _build_websocket_page(self) -> QWidget:
        w = QWidget()
        w.setObjectName("websocketSettingsPage")
        w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        w.setStyleSheet(PROTOCOL_SETTINGS_STYLE)
        outer = QVBoxLayout(w)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)
        form = QGridLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(8)
        form.setColumnStretch(1, 1)

        labels = self._form_label([
            QLabel("Origin"), QLabel("子协议"), QLabel("Ping(s)"),
        ])
        self._le_ws_origin = QLineEdit()
        self._le_ws_protocol = QLineEdit()
        self._le_ws_protocol.setPlaceholderText("可选，逗号分隔")
        self._sp_ws_ping = QSpinBox()
        self._sp_ws_ping.setRange(0, 3600)
        self._sp_ws_ping.setValue(30)
        self._le_ws_origin.setFixedHeight(32)
        self._le_ws_protocol.setFixedHeight(32)
        self._sp_ws_ping.setFixedHeight(32)
        for row, (label, widget) in enumerate(zip(labels, [
                self._le_ws_origin, self._le_ws_protocol,
                self._sp_ws_ping], strict=False)):
            form.addWidget(label, row, 0, Qt.AlignLeft)
            form.addWidget(widget, row, 1)
        self._chk_ws_reconnect = QCheckBox("自动重连")
        self._chk_ws_reconnect.setChecked(True)
        self._chk_ws_verify = QCheckBox("校验证书")
        self._chk_ws_verify.setChecked(True)
        form.addWidget(self._chk_ws_reconnect, 3, 0, 1, 2)
        form.addWidget(self._chk_ws_verify, 4, 0, 1, 2)
        outer.addLayout(form)
        outer.addStretch()
        return w

    def _build_http_page(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        self._http_api_search = QLineEdit()
        self._http_api_search.setPlaceholderText("搜索接口名称或 URL")
        self._http_api_search.setFixedHeight(32)
        self._http_api_search.setStyleSheet(
            "QLineEdit{background:#FFFFFF;color:#30343B;"
            "border:1px solid #D8DDE3;border-radius:6px;"
            "padding:4px 9px;font-size:12px;}"
            "QLineEdit:focus{border-color:#0078D4;}"
        )
        self._http_api_search.textChanged.connect(
            self._refresh_http_interfaces)
        outer.addWidget(self._http_api_search)

        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        action_button_style = (
            "QPushButton{background:#F7F8FA;color:#4B5563;"
            "border:1px solid #DDE2E8;border-radius:5px;"
            "font-size:13px;font-weight:500;padding:6px 8px;}"
            "QPushButton:hover{background:#EEF2F6;color:#1A1A1A;"
            "border-color:#0078D4;}"
        )
        self._btn_http_new = QPushButton("+ 新建接口")
        self._btn_http_new.setFixedHeight(36)
        self._btn_http_new.setStyleSheet(action_button_style)
        self._btn_http_new.clicked.connect(
            self._create_http_interface)
        action_row.addWidget(self._btn_http_new, 1)
        self._btn_http_new_folder = QPushButton("+ 新建目录")
        self._btn_http_new_folder.setFixedHeight(36)
        self._btn_http_new_folder.setStyleSheet(action_button_style)
        self._btn_http_new_folder.clicked.connect(
            self._create_http_folder)
        action_row.addWidget(self._btn_http_new_folder, 1)
        outer.addLayout(action_row)

        self._http_interfaces = []
        self._http_folders = []
        self._http_interface_tree = HttpLibraryTree()
        self._http_interface_tree.setHeaderHidden(True)
        self._http_interface_tree.setColumnCount(1)
        self._http_interface_tree.setRootIsDecorated(True)
        self._http_interface_tree.setIndentation(22)
        self._http_interface_tree.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._http_interface_tree.header().setStretchLastSection(False)
        self._http_interface_tree.header().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Fixed)
        self._http_interface_tree.setExpandsOnDoubleClick(False)
        self._http_interface_tree.setEditTriggers(
            QTreeWidget.EditTrigger.NoEditTriggers)
        self._http_interface_tree.setUniformRowHeights(True)
        self._http_interface_tree.setAlternatingRowColors(False)
        self._http_interface_tree.setMouseTracking(True)
        self._http_interface_tree.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._http_interface_tree.setFrameShape(QFrame.Shape.NoFrame)
        self._http_interface_tree.setToolTip(
            "单击接口在标签页打开；双击文件夹展开或折叠；右键可重命名")
        self._http_interface_tree.setItemDelegate(
            HttpLibraryDelegate(self._http_interface_tree))
        self._http_interface_tree.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        tree_style = (
            "QTreeWidget{background:transparent;border:none;"
            "outline:0;font-size:12px;selection-background-color:transparent;"
            "selection-color:#30343B;}"
            "QTreeWidget::branch{background:transparent;}"
            "QTreeWidget::branch:has-children:!has-siblings:closed,"
            "QTreeWidget::branch:closed:has-children:has-siblings"
            "{image:url(__BRANCH_RIGHT__);}"
            "QTreeWidget::branch:has-children:!has-siblings:open,"
            "QTreeWidget::branch:open:has-children:has-siblings"
            "{image:url(__BRANCH_DOWN__);}"
            "QTreeWidget::branch:!has-children{image:none;}"
            "QTreeWidget::branch:selected,"
            "QTreeWidget::branch:selected:active{background:transparent;}"
            "QTreeWidget::item{border:none;padding:0;}"
        ).replace(
            "__BRANCH_RIGHT__", _BRANCH_RIGHT_ICON
        ).replace(
            "__BRANCH_DOWN__", _BRANCH_DOWN_ICON
        )
        self._http_interface_tree.setStyleSheet(tree_style)
        self._http_interface_tree.itemClicked.connect(
            self._on_http_interface_clicked)
        self._http_interface_tree.itemActivated.connect(
            self._on_http_interface_clicked)
        self._http_interface_tree.itemDoubleClicked.connect(
            self._on_http_item_double_clicked)
        self._http_interface_tree.itemChanged.connect(
            self._on_http_item_changed)
        self._http_interface_tree.itemExpanded.connect(
            self._on_http_folder_expanded)
        self._http_interface_tree.itemCollapsed.connect(
            self._on_http_folder_collapsed)
        self._http_interface_tree.customContextMenuRequested.connect(
            self._show_http_library_menu)
        self._http_interface_tree.menu_requested.connect(
            self._show_http_library_menu)
        self._http_interface_tree.viewport().installEventFilter(self)
        outer.addWidget(self._http_interface_tree, 1)
        self._refresh_http_interfaces()
        return w

    def set_http_interfaces(self, interfaces):
        self._http_interfaces = [
            dict(item) for item in (interfaces or [])
            if isinstance(item, dict)
        ]
        self._refresh_http_interfaces()

    def set_http_folders(self, folders):
        self._http_folders = [
            dict(item) for item in (folders or [])
            if isinstance(item, dict)
        ]
        self._refresh_http_interfaces()

    def _http_current_folder_id(self):
        folder_id = str(
            self._http_expanded_target_folder_id or "") or None
        if folder_id and any(
                str(item.get("id")) == folder_id
                for item in self._http_folders):
            return folder_id
        return None

    def _http_folder_ancestors(self, folder_id):
        parents = {
            str(item.get("id")): item.get("parent_id")
            for item in self._http_folders
            if item.get("id")
        }
        expanded = set()
        current = str(folder_id or "") or None
        while current and current not in expanded:
            expanded.add(current)
            current = parents.get(current)
            current = str(current) if current else None
        return expanded

    def _create_http_interface_in(self, parent_id):
        parent_id = str(parent_id or "") or None
        self._http_pending_expand_ids.update(
            self._http_folder_ancestors(parent_id))
        self.http_folder_selected.emit(parent_id)
        self.http_new_requested.emit()

    def _create_http_interface(self):
        self._create_http_interface_in(
            self._http_current_folder_id())

    def _create_http_folder_in(self, parent_id):
        parent_id = str(parent_id or "") or None
        name, ok = get_text(
            self, "新建目录", "请输入目录名称", "新建目录")
        name = (name or "").strip()
        if ok and name:
            self._http_pending_expand_ids.update(
                self._http_folder_ancestors(parent_id))
            self.http_folder_selected.emit(parent_id)
            self.http_new_folder_requested.emit(name, parent_id)

    def _create_http_folder(self):
        self._create_http_folder_in(
            self._http_current_folder_id())

    def _on_http_folder_expanded(self, item):
        if item.data(0, _HTTP_KIND_ROLE) != "folder":
            return
        folder_id = str(item.data(0, _HTTP_ID_ROLE) or "") or None
        self._http_expanded_target_folder_id = folder_id
        self.http_folder_selected.emit(folder_id)
        QTimer.singleShot(0, self._update_http_tree_width)

    def _on_http_folder_collapsed(self, item):
        if item.data(0, _HTTP_KIND_ROLE) != "folder":
            return
        folder_id = str(item.data(0, _HTTP_ID_ROLE) or "") or None
        if self._http_expanded_target_folder_id == folder_id:
            parent = item.parent()
            self._http_expanded_target_folder_id = (
                str(parent.data(0, _HTTP_ID_ROLE) or "") or None
                if parent is not None and parent.isExpanded() else None
            )
            self.http_folder_selected.emit(
                self._http_expanded_target_folder_id)
        QTimer.singleShot(0, self._update_http_tree_width)

    def _start_http_item_edit(self, item, _column=0):
        if item is not None and item.flags() & Qt.ItemFlag.ItemIsEditable:
            self._http_interface_tree.editItem(item, 0)

    def _on_http_item_double_clicked(self, item, _column=0):
        kind = item.data(0, _HTTP_KIND_ROLE)
        if kind == "folder":
            item.setExpanded(not item.isExpanded())

    def _begin_http_rename(self):
        self._start_http_item_edit(
            self._http_interface_tree.currentItem())

    def _show_http_library_menu(self, position):
        item = self._http_interface_tree.itemAt(position)
        context_folder_id = None
        if item is not None:
            kind = item.data(0, _HTTP_KIND_ROLE)
            context_folder_id = (
                item.data(0, _HTTP_ID_ROLE)
                if kind == "folder"
                else item.data(0, _HTTP_FOLDER_ROLE)
            )
            if kind == "interface":
                self._http_interface_tree.setCurrentItem(item)
                self.http_folder_selected.emit(context_folder_id)
        menu, actions = self._build_http_library_menu(item)
        action = menu.exec(
            self._http_interface_tree.viewport().mapToGlobal(position))
        if action == actions["new_api"]:
            self._create_http_interface_in(context_folder_id)
        elif action == actions["new_folder"]:
            self._create_http_folder_in(context_folder_id)
        elif action in actions["move_targets"] and item is not None:
            self.http_move_requested.emit(
                str(item.data(0, _HTTP_ID_ROLE)),
                actions["move_targets"][action],
            )
        elif action == actions["rename"]:
            self._start_http_item_edit(item)
        elif action == actions["duplicate"] and item is not None:
            self.http_duplicate_requested.emit(
                str(item.data(0, _HTTP_ID_ROLE)))
        elif action == actions["expand_all"]:
            self._http_interface_tree.expandAll()
        elif action == actions["collapse_all"]:
            self._http_interface_tree.collapseAll()
        elif action == actions["delete"] and item is not None:
            self._delete_http_item(item)

    def _build_http_library_menu(self, item):
        kind = (
            item.data(0, _HTTP_KIND_ROLE)
            if item is not None else None
        )
        current_folder = (
            item.data(0, _HTTP_FOLDER_ROLE)
            if item is not None and kind == "interface" else None
        )
        menu = prepare_menu(QMenu(self))
        new_api = menu.addAction("新建接口")
        new_folder = menu.addAction("新建目录")
        menu.addSeparator()
        rename = menu.addAction("重命名")
        rename.setEnabled(item is not None)
        duplicate = menu.addAction("复制接口")
        duplicate.setEnabled(
            kind == "interface"
            and not bool(item.data(0, _HTTP_DRAFT_ROLE)))
        move_targets = {}
        move_menu = menu.addMenu("移动至...")
        move_menu.setEnabled(kind == "interface")
        root_action = move_menu.addAction("全部接口（根目录）")
        root_action.setCheckable(True)
        root_action.setChecked(not current_folder)
        move_targets[root_action] = None
        if self._http_folders:
            move_menu.addSeparator()
        folder_by_id = {
            str(item.get("id")): item for item in self._http_folders
            if item.get("id")
        }

        def folder_label(folder):
            names = []
            current = folder
            seen = set()
            while current is not None and current.get("id") not in seen:
                seen.add(current.get("id"))
                names.append(str(current.get("name") or "新建目录"))
                parent_id = str(current.get("parent_id") or "")
                current = folder_by_id.get(parent_id)
            return " / ".join(reversed(names))

        for folder in sorted(
                self._http_folders,
                key=lambda value: folder_label(value).lower()):
            folder_id = str(folder.get("id") or "")
            action = move_menu.addAction(folder_label(folder))
            action.setCheckable(True)
            action.setChecked(folder_id == str(current_folder or ""))
            move_targets[action] = folder_id
        menu.addSeparator()
        expand_all = menu.addAction("全部展开")
        collapse_all = menu.addAction("全部折叠")
        menu.addSeparator()
        delete = menu.addAction(
            "删除接口" if kind == "interface"
            else "删除文件夹" if kind == "folder"
            else "删除")
        delete.setEnabled(item is not None)
        return menu, {
            "new_api": new_api,
            "new_folder": new_folder,
            "rename": rename,
            "duplicate": duplicate,
            "move_targets": move_targets,
            "expand_all": expand_all,
            "collapse_all": collapse_all,
            "delete": delete,
        }

    @staticmethod
    def _http_interface_count(item):
        if item.data(0, _HTTP_KIND_ROLE) == "interface":
            return 1
        return sum(
            Sidebar._http_interface_count(item.child(index))
            for index in range(item.childCount())
        )

    def _delete_http_item(self, item):
        kind = item.data(0, _HTTP_KIND_ROLE)
        item_id = str(item.data(0, _HTTP_ID_ROLE) or "")
        name = item.text(0)
        if not item_id:
            return
        if kind == "interface":
            confirmed = ask_yes_no(
                self, "删除接口",
                "确定删除接口「{}」吗？\n删除后无法恢复。".format(name),
                confirm_text="删除", danger=True,
            )
            if confirmed:
                self.http_delete_interface_requested.emit(item_id)
        elif kind == "folder":
            count = self._http_interface_count(item)
            confirmed = ask_yes_no(
                self, "删除文件夹",
                "确定删除文件夹「{}」及其中的 {} 个接口吗？\n"
                "子文件夹也会一并删除，且无法恢复。".format(name, count),
                confirm_text="删除", danger=True,
            )
            if confirmed:
                self.http_delete_folder_requested.emit(item_id)

    def _on_http_item_changed(self, item, column):
        if column != 0:
            return
        kind = item.data(0, _HTTP_KIND_ROLE)
        item_id = item.data(0, _HTTP_ID_ROLE)
        original = str(item.data(0, _HTTP_NAME_ROLE) or "")
        name = item.text(0).strip()
        if not name:
            self._http_interface_tree.blockSignals(True)
            item.setText(0, original)
            self._http_interface_tree.blockSignals(False)
            return
        if kind and item_id and name != original:
            QTimer.singleShot(
                0,
                lambda current_kind=str(kind),
                current_id=str(item_id),
                current_name=name:
                self.http_rename_requested.emit(
                    current_kind, current_id, current_name),
            )

    def _refresh_http_interfaces(self, *_args):
        if not hasattr(self, "_http_interface_tree"):
            return
        expanded_ids = {
            folder_id for folder_id, item
            in getattr(self, "_http_folder_items", {}).items()
            if item.isExpanded()
        }
        current = self._http_interface_tree.currentItem()
        current_id = (
            str(current.data(0, _HTTP_ID_ROLE) or "")
            if current is not None else "")
        current_kind = (
            current.data(0, _HTTP_KIND_ROLE)
            if current is not None else None)
        if current_kind != "interface":
            current_id = ""
        vertical_scroll = (
            self._http_interface_tree.verticalScrollBar().value())
        query = self._http_api_search.text().strip().lower()
        self._http_interface_tree.blockSignals(True)
        self._http_interface_tree.clear()
        self._http_interface_items = {}
        self._http_folder_items = {}
        folders_by_parent = {}
        valid_folder_ids = {
            str(item.get("id")) for item in self._http_folders
            if item.get("id")
        }
        for folder in self._http_folders:
            parent_id = str(folder.get("parent_id") or "") or None
            if parent_id not in valid_folder_ids:
                parent_id = None
            folders_by_parent.setdefault(parent_id, []).append(folder)
        interfaces_by_folder = {}
        for interface in self._http_interfaces:
            folder_id = str(interface.get("folder_id") or "") or None
            if folder_id not in valid_folder_ids:
                folder_id = None
            interfaces_by_folder.setdefault(folder_id, []).append(interface)

        def add_interface(parent, item):
            method = str(item.get("method") or "GET").upper()
            name = str(item.get("name") or "未命名接口")
            url = str(item.get("url") or "")
            row = QTreeWidgetItem([name])
            row.setData(0, _HTTP_ID_ROLE, item.get("id"))
            row.setData(0, _HTTP_KIND_ROLE, "interface")
            row.setData(0, _HTTP_METHOD_ROLE, method)
            row.setData(0, _HTTP_NAME_ROLE, name)
            row.setData(0, _HTTP_FOLDER_ROLE, item.get("folder_id"))
            row.setData(0, _HTTP_URL_ROLE, url)
            row.setData(
                0, _HTTP_DIRTY_ROLE, bool(item.get("dirty")))
            row.setData(
                0, _HTTP_DRAFT_ROLE, bool(item.get("draft")))
            row.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsEditable)
            row.setToolTip(0, "{}\n{}".format(method, url))
            if parent is None:
                self._http_interface_tree.addTopLevelItem(row)
            else:
                parent.addChild(row)
            self._http_interface_items[str(item.get("id"))] = row

        def add_folder(parent, folder, visited):
            folder_id = str(folder.get("id") or "")
            if not folder_id or folder_id in visited:
                return
            visited = set(visited)
            visited.add(folder_id)
            name = str(folder.get("name") or "新建目录")
            row = QTreeWidgetItem([name])
            row.setData(0, _HTTP_ID_ROLE, folder_id)
            row.setData(0, _HTTP_KIND_ROLE, "folder")
            row.setData(0, _HTTP_NAME_ROLE, name)
            row.setData(
                0, _HTTP_COUNT_ROLE,
                count_folder_interfaces(folder_id, set()))
            row.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsEditable)
            if parent is None:
                self._http_interface_tree.addTopLevelItem(row)
            else:
                parent.addChild(row)
            self._http_folder_items[folder_id] = row
            for interface in interfaces_by_folder.get(folder_id, []):
                add_interface(row, interface)
            for child in folders_by_parent.get(folder_id, []):
                add_folder(row, child, visited)

        def count_folder_interfaces(folder_id, visited):
            if folder_id in visited:
                return 0
            visited = set(visited)
            visited.add(folder_id)
            total = len(interfaces_by_folder.get(folder_id, []))
            for child in folders_by_parent.get(folder_id, []):
                total += count_folder_interfaces(
                    str(child.get("id") or ""), visited)
            return total

        for folder in folders_by_parent.get(None, []):
            add_folder(None, folder, set())
        for item in interfaces_by_folder.get(None, []):
            add_interface(None, item)

        def filter_item(item):
            kind = item.data(0, _HTTP_KIND_ROLE)
            name = item.text(0).lower()
            url = str(
                item.data(0, _HTTP_URL_ROLE) or "").lower()
            own_match = query in name or query in url
            child_match = False
            for index in range(item.childCount()):
                child_match = filter_item(item.child(index)) or child_match
            visible = not query or own_match or child_match
            item.setHidden(not visible)
            if kind == "folder" and query and own_match:
                def show_children(parent):
                    for index in range(parent.childCount()):
                        child = parent.child(index)
                        child.setHidden(False)
                        show_children(child)
                show_children(item)
                visible = True
            return visible

        for index in range(self._http_interface_tree.topLevelItemCount()):
            filter_item(self._http_interface_tree.topLevelItem(index))

        expand_ids = expanded_ids | self._http_pending_expand_ids
        for folder_id, item in self._http_folder_items.items():
            if folder_id in expand_ids:
                item.setExpanded(True)
        self._http_pending_expand_ids.clear()

        target_id = self._http_expanded_target_folder_id
        target_item = (
            self._http_folder_items.get(target_id)
            if target_id else None)
        if target_item is not None and target_item.isExpanded():
            self._http_expanded_target_folder_id = target_id
        else:
            self._http_expanded_target_folder_id = None
            self.http_folder_selected.emit(None)

        if current_id:
            restored = (
                self._http_folder_items.get(current_id)
                if current_kind == "folder"
                else self._http_interface_items.get(current_id)
            )
            if restored is not None:
                self._http_interface_tree.setCurrentItem(restored)
                self._expand_http_item_parents(restored)
        QTimer.singleShot(
            0,
            lambda value=vertical_scroll:
            self._http_interface_tree.verticalScrollBar().setValue(value),
        )
        QTimer.singleShot(0, self._update_http_tree_width)
        self._http_interface_tree.blockSignals(False)

    def _expand_http_item_parents(self, item):
        parent = item.parent() if item is not None else None
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()

    def _update_http_tree_width(self):
        if not hasattr(self, "_http_interface_tree"):
            return
        tree = self._http_interface_tree
        content_width = tree.sizeHintForColumn(0) + 72
        viewport_width = tree.viewport().width()
        tree.setColumnWidth(0, max(viewport_width, content_width))
        tree.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn
            if content_width > viewport_width
            else Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )

    def _on_http_interface_clicked(self, item, _column):
        kind = item.data(0, _HTTP_KIND_ROLE)
        api_id = item.data(0, _HTTP_ID_ROLE)
        if kind == "interface" and api_id:
            self.http_folder_selected.emit(
                item.data(0, _HTTP_FOLDER_ROLE))
            self.http_interface_selected.emit(str(api_id))

    def select_http_interface(self, api_id):
        api_id = str(api_id or "")
        item = self._http_interface_items.get(api_id)
        if item is not None:
            self._expand_http_item_parents(item)
            self._http_interface_tree.setCurrentItem(item)
            return
        self._http_interface_tree.clearSelection()

    def _show_http_transfer_menu(self):
        menu = prepare_menu(QMenu(self))
        import_action = menu.addAction("导入项目...")
        export_action = menu.addAction("导出项目...")
        selected = menu.exec(
            self._btn_http_transfer_menu.mapToGlobal(
                self._btn_http_transfer_menu.rect().bottomLeft()))
        if selected == import_action:
            self.http_import_requested.emit()
        elif selected == export_action:
            self.http_export_requested.emit()

    @staticmethod
    def _toggle_password_visibility(field, action):
        visible = field.echoMode() == QLineEdit.EchoMode.Normal
        if visible:
            field.setEchoMode(QLineEdit.EchoMode.Password)
            action.setIcon(QIcon(os.path.join(
                _find_assets_dir(), "password_show.svg")))
            action.setToolTip("显示密码")
        else:
            field.setEchoMode(QLineEdit.EchoMode.Normal)
            action.setIcon(QIcon(os.path.join(
                _find_assets_dir(), "password_hide.svg")))
            action.setToolTip("隐藏密码")

    def _on_mqtt_server_anonymous_toggled(self, allow_anonymous):
        credentials_enabled = not bool(allow_anonymous)
        self._le_mqtt_server_user.setEnabled(credentials_enabled)
        self._le_mqtt_server_password.setEnabled(credentials_enabled)

    def mqtt_server_config(self):
        return {
            "bind_address": self._le_mqtt_server_bind.text().strip(),
            "port": self._sp_mqtt_server_port.value(),
            "allow_anonymous": (
                self._chk_mqtt_server_anonymous.isChecked()),
            "username": self._le_mqtt_server_user.text(),
            "password": self._le_mqtt_server_password.text(),
            "max_connections": (
                self._sp_mqtt_server_max_connections.value()),
        }

    def set_mqtt_server_config(self, data):
        data = data if isinstance(data, dict) else {}
        self._le_mqtt_server_bind.setText(
            str(data.get("bind_address") or "127.0.0.1"))
        try:
            port = int(data.get("port", 1883))
        except (TypeError, ValueError, OverflowError):
            port = 1883
        self._sp_mqtt_server_port.setValue(max(1, min(65535, port)))
        try:
            max_connections = int(data.get("max_connections", 100))
        except (TypeError, ValueError, OverflowError):
            max_connections = 100
        self._sp_mqtt_server_max_connections.setValue(
            max(1, min(100000, max_connections)))
        allow_anonymous = bool(data.get("allow_anonymous", True))
        self._chk_mqtt_server_anonymous.setChecked(allow_anonymous)
        self._le_mqtt_server_user.setText(
            str(data.get("username") or ""))
        self._le_mqtt_server_password.setText(
            str(data.get("password") or ""))
        self._on_mqtt_server_anonymous_toggled(allow_anonymous)

    def set_mqtt_server_mode(self, enabled):
        self._mqtt_server_mode = bool(enabled)
        if self._current_mode != "mqtt":
            return
        self._settings_stack.setCurrentWidget(
            self._mqtt_server_settings_page
            if self._mqtt_server_mode
            else self._mqtt_client_settings_page)
        self._settings_label.setText(
            "服务端配置" if self._mqtt_server_mode else "参数配置")
        if self._mqtt_server_mode:
            self._refresh_mqtt_server_button()
        else:
            self.set_connected(self._connected)

    def set_mqtt_server_running(self, running):
        self._mqtt_server_running = bool(running)
        self._refresh_mqtt_server_button()

    def set_mqtt_server_available(self, available):
        self._mqtt_server_available = bool(available)
        self._refresh_mqtt_server_button()

    def _refresh_mqtt_server_button(self):
        if self._current_mode != "mqtt" or not self._mqtt_server_mode:
            return
        if not self._mqtt_server_available:
            text = "服务端组件未安装"
        elif self._mqtt_server_running:
            text = "停止服务端"
        else:
            text = "启动服务端"
        self._btn_connect.setText(text)
        self._btn_connect.setEnabled(self._mqtt_server_available)
        for widget in (
            self._le_mqtt_server_bind, self._sp_mqtt_server_port,
            self._sp_mqtt_server_max_connections,
            self._le_mqtt_server_user,
            self._le_mqtt_server_password,
            self._chk_mqtt_server_anonymous,
        ):
            widget.setEnabled(
                self._mqtt_server_available
                and not self._mqtt_server_running
                and (
                    widget is not self._le_mqtt_server_user
                    and widget is not self._le_mqtt_server_password
                    or not self._chk_mqtt_server_anonymous.isChecked()
                )
            )
        self._btn_connect.setProperty(
            "connected", "true" if self._mqtt_server_running else "false")
        self._btn_connect.style().unpolish(self._btn_connect)
        self._btn_connect.style().polish(self._btn_connect)

    def _on_mode_changed(self, idx: int):
        modes = [
            "serial", "tcpserver", "tcpclient",
            "mqtt", "websocket", "http",
        ]
        self._current_mode = modes[idx]
        if self._current_mode == "mqtt" and self._mqtt_server_mode:
            self._settings_stack.setCurrentWidget(
                self._mqtt_server_settings_page)
        else:
            self._settings_stack.setCurrentIndex(idx)
        fill_settings = self._current_mode in (
            "mqtt", "websocket", "http")
        self._settings_inner_layout.setStretch(
            0, 1 if fill_settings else 0)
        self._settings_inner_layout.setStretch(
            1, 0 if fill_settings else 1)
        self._settings_stack.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            (
                QSizePolicy.Policy.Expanding
                if fill_settings else QSizePolicy.Policy.Preferred
            ),
        )
        self._settings_stack.updateGeometry()
        self._settings_scroll.widget().updateGeometry()
        self._wheel_active_control = None
        self._settings_label.setText(
            "全部接口"
            if self._current_mode == "http"
            else (
                "服务端配置"
                if self._current_mode == "mqtt" and self._mqtt_server_mode
                else "参数配置"
            )
        )
        self._btn_http_transfer_menu.setVisible(
            self._current_mode == "http")

        is_serial = (self._current_mode == "serial")
        self._btn_refresh.setVisible(is_serial)
        self._btn_connect.setVisible(
            self._current_mode not in ("http", "websocket")
        )

        if self._current_mode == "mqtt" and self._mqtt_server_mode:
            self._refresh_mqtt_server_button()
        else:
            self.set_connected(self._connected)

        self.mode_changed.emit(self._current_mode)

    def _on_connect_clicked(self):
        if self._current_mode == "mqtt" and self._mqtt_server_mode:
            if self._mqtt_server_running:
                self.mqtt_server_stop_requested.emit()
            elif self._mqtt_server_available:
                self.mqtt_server_start_requested.emit()
            return
        if self._connected:
            self.disconnect_clicked.emit(self._current_mode)
        else:
            self.connect_clicked.emit(self._current_mode)

    def set_connected(self, connected: bool):
        self._connected = connected
        if self._current_mode == "mqtt" and self._mqtt_server_mode:
            return
        if self._current_mode == "mqtt":
            self._set_mqtt_client_fields_enabled(not connected)
        labels = {
            "serial": "打开串口", "tcpserver": "启动服务器",
            "tcpclient": "连接服务器", "mqtt": "连接服务端",
            "websocket": "连接 WebSocket", "http": "HTTP 请求",
        }
        disc_labels = {
            "serial": "关闭串口", "tcpserver": "停止服务器",
            "tcpclient": "断开连接", "mqtt": "断开服务端",
            "websocket": "断开 WebSocket", "http": "HTTP 请求",
        }

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
            self._le_client_host, self._sp_client_port, self._le_local_port,
            self._le_mqtt_host, self._sp_mqtt_port,
            self._le_mqtt_client_id, self._le_mqtt_user,
            self._le_mqtt_password, self._sp_mqtt_keepalive,
            self._cb_mqtt_protocol, self._chk_mqtt_tls,
            self._chk_mqtt_clean, self._chk_mqtt_reconnect,
            self._le_mqtt_server_bind, self._sp_mqtt_server_port,
            self._sp_mqtt_server_max_connections,
            self._le_mqtt_server_user,
            self._le_mqtt_server_password,
            self._chk_mqtt_server_anonymous,
            self._le_ws_origin, self._le_ws_protocol,
            self._sp_ws_ping,
            self._chk_ws_reconnect, self._chk_ws_verify,
        ]
        for w in widgets:
            w.setEnabled(enabled)
        if (
            enabled
            and self._connected
            and self._current_mode == "mqtt"
            and not self._mqtt_server_mode
        ):
            self._set_mqtt_client_fields_enabled(False)

    def _set_mqtt_client_fields_enabled(self, enabled):
        for widget in (
            self._le_mqtt_host,
            self._sp_mqtt_port,
            self._le_mqtt_client_id,
            self._le_mqtt_user,
            self._le_mqtt_password,
            self._sp_mqtt_keepalive,
            self._cb_mqtt_protocol,
            self._chk_mqtt_tls,
            self._chk_mqtt_clean,
            self._chk_mqtt_reconnect,
        ):
            widget.setEnabled(enabled)

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
    def le_mqtt_host(self) -> QLineEdit:
        return self._le_mqtt_host

    @property
    def sp_mqtt_port(self) -> QSpinBox:
        return self._sp_mqtt_port

    @property
    def le_mqtt_client_id(self) -> QLineEdit:
        return self._le_mqtt_client_id

    @property
    def le_mqtt_user(self) -> QLineEdit:
        return self._le_mqtt_user

    @property
    def le_mqtt_password(self) -> QLineEdit:
        return self._le_mqtt_password

    @property
    def sp_mqtt_keepalive(self) -> QSpinBox:
        return self._sp_mqtt_keepalive

    @property
    def cb_mqtt_protocol(self) -> QComboBox:
        return self._cb_mqtt_protocol

    @property
    def chk_mqtt_tls(self) -> QCheckBox:
        return self._chk_mqtt_tls

    @property
    def chk_mqtt_clean(self) -> QCheckBox:
        return self._chk_mqtt_clean

    @property
    def chk_mqtt_reconnect(self) -> QCheckBox:
        return self._chk_mqtt_reconnect

    @property
    def le_ws_origin(self) -> QLineEdit:
        return self._le_ws_origin

    @property
    def le_ws_protocol(self) -> QLineEdit:
        return self._le_ws_protocol

    @property
    def sp_ws_ping(self) -> QSpinBox:
        return self._sp_ws_ping

    @property
    def chk_ws_reconnect(self) -> QCheckBox:
        return self._chk_ws_reconnect

    @property
    def chk_ws_verify(self) -> QCheckBox:
        return self._chk_ws_verify

    @property
    def current_mode(self) -> str:
        return self._current_mode

    @property
    def is_connected(self) -> bool:
        return self._connected
