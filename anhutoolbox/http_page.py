# -*- coding: utf-8 -*-
"""APIpost 风格的 HTTP 请求与响应工作区。"""

import base64
import copy
import json
import mimetypes
import os
import re
import secrets
import urllib.parse
from http.cookies import SimpleCookie

import msgpack
from PySide6.QtCore import (
    QEvent, QPoint, QPropertyAnimation, QRect, QSize, Qt, QTimer, Signal, Slot,
)
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QIcon, QKeySequence, QPainter, QPixmap,
    QShortcut, QTextCharFormat, QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog,
    QGraphicsOpacityEffect, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMenu, QPlainTextEdit,
    QPushButton,
    QRadioButton, QSpinBox,
    QSplitter, QTableWidget, QTableWidgetItem, QTabBar, QTabWidget,
    QTextEdit, QToolButton, QVBoxLayout, QWidget, QSizePolicy, QWidgetAction,
)

from .dialogs import (
    ask_yes_no, get_text, show_error, show_warning,
)
from .http_dialogs import UnsavedChangesDialog
from .http_environments import (
    DEFAULT_ENVIRONMENT_ID, EnvironmentManagerDialog, EnvironmentResolver,
    EnvironmentVariableError, default_environments, normalise_environments,
)
from .http_transfer import (
    FORMAT_LABELS, build_transfer, normalise_request,
)
from .http_transfer_dialogs import (
    ExportTransferDialog, ImportTransferDialog,
)
from .http_url_editor import EnvironmentUrlEditor
from .panels import parse_hex_bytes
from .protocol_workers import HTTPRequestWorker
from .secrets_guard import contains_sensitive_values
from .styles import _find_assets_dir, prepare_menu
from .table_actions import (
    apply_data_table_style, install_select_all_header,
)
from .ui_tokens import (
    CONTROL_HEIGHT, DOCUMENT_TAB_WIDTH, FONT_MONO, FONT_UI,
    HTTP_METHOD_COLORS, HTTP_PAGE_STYLE, HTTP_TABLE_STYLE, ICON_SIZE, SPACE_MD,
    SPACE_SM, TABLE_ROW_HEIGHT, TAB_CONTROL_SIZE,
)


_HEADER_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_JSON_TOKEN = re.compile(
    r'"(?:\\.|[^"\\])*"'
    r"|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?"
    r"|\b(?:true|false|null)\b"
)


def _http_icon(filename):
    return QIcon(os.path.join(_find_assets_dir(), filename))


class HoverCloseTabBar(QTabBar):
    """鼠标悬停到标签上时才显示关闭按钮。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setElideMode(Qt.TextElideMode.ElideRight)

    def _new_close_button(self):
        wrapper = QWidget(self)
        wrapper.setObjectName("httpTabCloseHost")
        wrapper.setFixedSize(34, 20)
        dirty = QLabel("", wrapper)
        dirty.setObjectName("httpTabDirty")
        dirty.setFixedSize(12, 15)
        dirty.move(1, 2)
        dirty.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        dirty.setStyleSheet(
            "QLabel#httpTabDirty{color:#0078D4;font-size:12px;"
            "font-weight:700;background:transparent;}")
        button = QToolButton(wrapper)
        button.setObjectName("httpTabClose")
        button.setFixedSize(15, 15)
        button.move(16, 2)
        close_icon = _http_icon("http_close.svg")
        if close_icon.isNull():
            button.setText("×")
        else:
            button.setIcon(close_icon)
            button.setIconSize(QSize(10, 10))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip("关闭")
        button.setStyleSheet(
            "QToolButton#httpTabClose{background:transparent;border:none;"
            "color:#7A8490;font-size:14px;font-weight:600;padding:0;}"
            "QToolButton#httpTabClose:hover{background:#E3E7EC;"
            "border-radius:7px;color:#1A1A1A;}"
        )
        wrapper._dirty_label = dirty
        wrapper._close_button = button
        button.clicked.connect(
            lambda _checked=False, current=wrapper:
            self._close_button_clicked(current))
        button.hide()
        return wrapper

    def set_tab_dirty(self, index, dirty):
        if not 0 <= index < self.count():
            return
        wrapper = self.tabButton(
            index, QTabBar.ButtonPosition.RightSide)
        if wrapper is None:
            return
        label = getattr(wrapper, "_dirty_label", None)
        if label is not None:
            label.setText("●" if dirty else "")
        wrapper.setProperty("dirty", bool(dirty))

    def is_tab_dirty(self, index):
        if not 0 <= index < self.count():
            return False
        wrapper = self.tabButton(
            index, QTabBar.ButtonPosition.RightSide)
        return bool(wrapper is not None and wrapper.property("dirty"))

    def _close_button_clicked(self, wrapper):
        for index in range(self.count()):
            if self.tabButton(
                    index, QTabBar.ButtonPosition.RightSide) is wrapper:
                self.tabCloseRequested.emit(index)
                return

    def tabInserted(self, index):
        super().tabInserted(index)
        button = self._new_close_button()
        self.setTabButton(
            index, QTabBar.ButtonPosition.RightSide, button)
        button.show()

    def tabSizeHint(self, index):
        size = super().tabSizeHint(index)
        size.setWidth(DOCUMENT_TAB_WIDTH)
        return size

    def _show_close_for(self, index):
        for current in range(self.count()):
            wrapper = self.tabButton(
                current, QTabBar.ButtonPosition.RightSide)
            if wrapper is not None:
                close_button = getattr(
                    wrapper, "_close_button", None)
                if close_button is not None:
                    close_button.setVisible(current == index)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        self._show_close_for(self.tabAt(event.position().toPoint()))

    def leaveEvent(self, event):
        self._show_close_for(-1)
        super().leaveEvent(event)


class HttpPairTable(QTableWidget):
    """请求参数表：行尾删除按钮只在悬停当前行时显示。"""

    def __init__(self, rows, columns, parent=None):
        super().__init__(rows, columns, parent)
        self._action_column = columns - 1
        self._action_hosts = {}
        self._hovered_row = -1
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

    def install_row_action(self, row):
        old_host = self.cellWidget(row, self._action_column)
        if old_host is not None:
            self.removeCellWidget(row, self._action_column)
        host = QWidget(self)
        host.setObjectName("httpRowActionHost")
        host.setStyleSheet("background:transparent;")
        layout = QHBoxLayout(host)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)
        layout.addStretch()
        button = QToolButton(host)
        button.setObjectName("httpRowDelete")
        button.setFixedSize(24, 24)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip("删除此行")
        icon = _http_icon("http_delete.svg")
        if not icon.isNull():
            button.setIcon(icon)
            button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        else:
            button.setText("×")
        button.clicked.connect(
            lambda _checked=False, current=button:
            self._delete_action_row(current))
        layout.addWidget(button)
        self.setCellWidget(row, self._action_column, host)
        self._action_hosts[row] = (host, button)
        host.show()
        button.setVisible(row == self._hovered_row)

    def _delete_action_row(self, button):
        for row, (_host, current) in list(self._action_hosts.items()):
            if current is button and 0 <= row < self.rowCount():
                self.removeRow(row)
                self.refresh_row_actions()
                return

    def refresh_row_actions(self):
        for row in range(self.rowCount()):
            if self.cellWidget(row, self._action_column) is not None:
                self.removeCellWidget(row, self._action_column)
        self._action_hosts.clear()
        for row in range(self.rowCount()):
            self.install_row_action(row)

    def _set_hovered_row(self, row):
        if row == self._hovered_row:
            return
        self._hovered_row = row
        for current_row, (_host, button) in self._action_hosts.items():
            button.setVisible(current_row == row)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        self._set_hovered_row(
            self.rowAt(event.position().toPoint().y()))

    def leaveEvent(self, event):
        self._set_hovered_row(-1)
        super().leaveEvent(event)

    def setRowCount(self, count):
        super().setRowCount(count)
        if hasattr(self, "_action_hosts") and count == 0:
            self._action_hosts.clear()
            self._hovered_row = -1


class HttpUrlBar(QWidget):
    """URL 编辑器和协议选择器共用一条外边框。"""

    def __init__(self, editor, version_combo, parent=None):
        super().__init__(parent)
        self.setObjectName("httpUrlShell")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(CONTROL_HEIGHT)
        self.setProperty("focused", False)
        editor.setFixedHeight(CONTROL_HEIGHT - 2)
        version_combo.setFixedHeight(CONTROL_HEIGHT - 2)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(editor, 1)
        layout.addWidget(version_combo)
        for child in (editor, version_combo):
            child.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() in (
                QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            QTimer.singleShot(0, self._refresh_focus_state)
        return super().eventFilter(watched, event)

    def _refresh_focus_state(self):
        focused = any(
            child.hasFocus() for child in (
                self.findChild(QPlainTextEdit, "httpUrlEditor"),
                self.findChild(QComboBox, "httpVersionCombo"),
            )
            if child is not None
        )
        if bool(self.property("focused")) == focused:
            return
        self.setProperty("focused", focused)
        self.style().unpolish(self)
        self.style().polish(self)


class EnvironmentButton(QToolButton):
    """环境按钮：左侧环境图标、文字和右侧下拉箭头严格垂直居中。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("httpEnvironmentButton")
        self.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setIcon(_http_icon("http_environment.svg"))
        self.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.setFixedHeight(CONTROL_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._chevron = QLabel(self)
        self._chevron.setFixedSize(12, 12)
        self._chevron.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        chevron = _http_icon("http_chevron_down.svg").pixmap(12, 12)
        if not chevron.isNull():
            self._chevron.setPixmap(chevron)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        chevron = getattr(self, "_chevron", None)
        if chevron is not None:
            x = max(0, self.width() - chevron.width() - 8)
            y = max(0, (self.height() - chevron.height()) // 2)
            chevron.move(x, y)
            chevron.raise_()


def _table(headers, row_actions=False):
    headers = list(headers)
    has_checkbox_column = bool(headers and headers[0] == "启用")
    if has_checkbox_column:
        headers[0] = ""
    if row_actions:
        widget = HttpPairTable(0, len(headers))
    else:
        widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    if has_checkbox_column:
        install_select_all_header(widget)
    apply_data_table_style(widget)
    widget.setFont(QFont(FONT_UI, 9))
    widget.horizontalHeader().setFont(
        QFont(FONT_UI, 9, QFont.Weight.DemiBold))
    widget.setStyleSheet(HTTP_TABLE_STYLE)
    widget.verticalHeader().setSectionResizeMode(
        QHeaderView.ResizeMode.Fixed)
    widget.verticalHeader().setDefaultSectionSize(TABLE_ROW_HEIGHT)
    widget.verticalHeader().setMinimumSectionSize(TABLE_ROW_HEIGHT)
    widget.horizontalHeader().setMinimumHeight(TABLE_ROW_HEIGHT)
    return widget


def _add_pair_row(table, name="", value="", description="", enabled=True):
    row = table.rowCount()
    table.insertRow(row)
    check = QTableWidgetItem()
    check.setFlags(check.flags() | Qt.ItemFlag.ItemIsUserCheckable)
    check.setCheckState(
        Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
    check.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    table.setItem(row, 0, check)
    table.setItem(row, 1, QTableWidgetItem(str(name or "")))
    table.setItem(row, 2, QTableWidgetItem(str(value or "")))
    table.setItem(row, 3, QTableWidgetItem(str(description or "")))
    if isinstance(table, HttpPairTable):
        table.install_row_action(row)
    return row


def _table_entries(table):
    entries = []
    for row in range(table.rowCount()):
        check = table.item(row, 0)
        name = table.item(row, 1)
        value = table.item(row, 2)
        description = table.item(row, 3)
        entries.append({
            "name": name.text() if name else "",
            "value": value.text() if value else "",
            "description": description.text() if description else "",
            "enabled": (
                check is None
                or check.checkState() == Qt.CheckState.Checked),
        })
    return entries


def _enabled_pairs(table):
    return [
        (item["name"].strip(), item["value"])
        for item in _table_entries(table)
        if item["enabled"] and item["name"].strip()
    ]


class HTTPPage(QWidget):
    request_status = Signal(str)
    save_requested = Signal()
    interfaces_changed = Signal(object)
    active_interface_changed = Signal(object)
    folders_changed = Signal(object)
    new_project_import_requested = Signal(str, object, str)

    def __init__(self):
        super().__init__()
        self.setObjectName("httpPage")
        self._worker = None
        self._last_request = {}
        self._last_result = {}
        self._raw_response = ""
        self._response_content_type = ""
        self._interfaces = []
        self._folders = []
        self._current_folder_id = None
        self._environments = default_environments()
        self._active_environment_id = DEFAULT_ENVIRONMENT_ID
        self._documents = []
        self._active_document = -1
        self._response_states = {}
        self._request_document_key = None
        self._request_document_request = {}
        self._loading_document = False
        self._document_method_icons = {}
        self._environment_menu = None
        self._suppress_environment_click = False
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(20)
        self._poll_timer.timeout.connect(self._poll_request)
        self._build()
        self._toast_token = 0
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._hide_http_toast)
        self._http_toast = QLabel("", self)
        self._http_toast.setObjectName("httpToast")
        self._http_toast.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._http_toast.setTextFormat(Qt.TextFormat.PlainText)
        self._http_toast.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._http_toast.setStyleSheet(
            "QLabel#httpToast{background:#F0FDF4;color:#166534;"
            "border:1px solid #BBF7D0;border-radius:8px;"
            "padding:9px 18px;font-size:13px;font-weight:600;}")
        self._http_toast.hide()
        self._save_shortcut = QShortcut(
            QKeySequence(QKeySequence.StandardKey.Save), self)
        self._save_shortcut.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._save_shortcut.activated.connect(
            self._save_current_document)
        self._connect_document_signals()
        self._documents = []
        self._active_document = -1
        self._response_states.clear()
        self._refresh_document_tabs()
        self._emit_interfaces_changed()
        self._emit_active_interface_changed()

    @staticmethod
    def _make_tab_control(icon_name, tooltip, fallback_text=""):
        button = QToolButton()
        button.setProperty("httpTabControl", True)
        button.setFixedSize(TAB_CONTROL_SIZE, TAB_CONTROL_SIZE)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(tooltip)
        icon = _http_icon(icon_name)
        if icon.isNull():
            button.setText(fallback_text)
        else:
            button.setIcon(icon)
            button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        return button

    @staticmethod
    def _set_button_icon(button, icon_name, icon_size=ICON_SIZE):
        icon = _http_icon(icon_name)
        if not icon.isNull():
            button.setIcon(icon)
            button.setIconSize(QSize(icon_size, icon_size))
        return button

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(
            SPACE_MD, SPACE_MD, SPACE_MD, SPACE_MD)
        root.setSpacing(SPACE_SM)
        self.setStyleSheet(HTTP_PAGE_STYLE)

        document_surface = QWidget()
        document_surface.setObjectName("httpTabSurface")
        document_bar = QHBoxLayout(document_surface)
        document_bar.setContentsMargins(8, 5, 8, 5)
        document_bar.setSpacing(6)
        self._document_tabs = HoverCloseTabBar()
        self._document_tabs.setObjectName("httpDocuments")
        self._document_tabs.setIconSize(QSize(40, 16))
        self._document_tabs.setExpanding(False)
        self._document_tabs.setMovable(False)
        self._document_tabs.setChangeCurrentOnDrag(False)
        self._document_tabs.currentChanged.connect(
            self._on_document_changed)
        self._document_tabs.tabCloseRequested.connect(
            self._request_close_document)
        self._document_tabs.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self._document_tabs.customContextMenuRequested.connect(
            self._show_document_tab_menu)
        self._document_tabs.setSizePolicy(
            QSizePolicy.Policy.Maximum,
            QSizePolicy.Policy.Fixed,
        )
        document_bar.addWidget(self._document_tabs)
        self._btn_new_document = QToolButton()
        self._btn_new_document.setObjectName("httpNewDocument")
        self._btn_new_document.setFixedSize(
            TAB_CONTROL_SIZE, TAB_CONTROL_SIZE)
        self._btn_new_document.setCursor(
            Qt.CursorShape.PointingHandCursor)
        self._btn_new_document.setToolTip("新建接口")
        add_icon = QIcon(
            os.path.join(_find_assets_dir(), "add_interface.svg"))
        if add_icon.isNull():
            self._btn_new_document.setText("+")
        else:
            self._btn_new_document.setIcon(add_icon)
            self._btn_new_document.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self._btn_new_document.clicked.connect(self.new_document)
        document_bar.addWidget(
            self._btn_new_document, 0,
            Qt.AlignmentFlag.AlignVCenter)
        self._btn_tab_more = self._make_tab_control(
            "http_more.svg", "标签操作", "⋯")
        self._btn_tab_more.clicked.connect(
            self._show_tab_actions_menu)
        document_bar.addWidget(
            self._btn_tab_more, 0, Qt.AlignmentFlag.AlignVCenter)
        document_bar.addStretch(1)
        self._btn_tab_prev = self._make_tab_control(
            "http_previous.svg", "上一个标签", "‹")
        self._btn_tab_prev.clicked.connect(
            lambda: self._move_document_selection(-1))
        document_bar.addWidget(
            self._btn_tab_prev, 0, Qt.AlignmentFlag.AlignVCenter)
        self._btn_tab_next = self._make_tab_control(
            "http_next.svg", "下一个标签", "›")
        self._btn_tab_next.clicked.connect(
            lambda: self._move_document_selection(1))
        document_bar.addWidget(
            self._btn_tab_next, 0, Qt.AlignmentFlag.AlignVCenter)
        self._btn_environment = EnvironmentButton()
        self._btn_environment.setMinimumWidth(150)
        self._btn_environment.setMaximumWidth(230)
        self._btn_environment.setToolTip("切换或管理本地环境")
        self._btn_environment.clicked.connect(
            self._show_environment_menu)
        document_bar.addWidget(
            self._btn_environment, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(document_surface)
        self._refresh_environment_button()

        request_bar = QHBoxLayout()
        request_bar.setSpacing(SPACE_SM)
        self._method = QComboBox()
        self._method.addItems([
            "GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
        self._method.setFixedSize(108, CONTROL_HEIGHT)
        request_bar.addWidget(self._method)

        self._url = EnvironmentUrlEditor(
            self._environment_variable_names)
        self._url.setPlaceholderText("请输入URL或粘贴cURL文本")
        self._url.returnPressed.connect(self._send)

        self._http_version = QComboBox()
        self._http_version.setObjectName("httpVersionCombo")
        self._http_version.addItem("Auto", "auto")
        self._http_version.addItem("http/1.1", "http/1.1")
        self._http_version.addItem("http/2", "http/2")
        self._http_version.setItemData(
            0, "HTTP/2 不可用时自动回退到 HTTP/1.1",
            Qt.ItemDataRole.ToolTipRole)
        self._http_version.setItemData(
            2, "使用 HTTP/2；服务端不支持时将请求失败",
            Qt.ItemDataRole.ToolTipRole)
        self._http_version.setCurrentIndex(1)
        self._http_version.setFixedSize(108, CONTROL_HEIGHT)
        url_bar = HttpUrlBar(self._url, self._http_version)
        request_bar.addWidget(url_bar, 1)

        self._btn_send = QPushButton("发送")
        self._btn_send.setObjectName("httpSend")
        self._btn_send.setMinimumWidth(96)
        self._btn_send.setFixedHeight(CONTROL_HEIGHT)
        self._btn_send.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        send_icon = _http_icon("http_send.svg")
        if not send_icon.isNull():
            self._btn_send.setIcon(send_icon)
            self._btn_send.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self._btn_send.clicked.connect(self._send)
        request_bar.addWidget(self._btn_send)

        options = QHBoxLayout()
        options.setSpacing(SPACE_MD)
        options.addWidget(QLabel("超时(秒)"))
        self._timeout = QSpinBox()
        self._timeout.setRange(1, 3600)
        self._timeout.setValue(30)
        self._timeout.setFixedSize(76, CONTROL_HEIGHT)
        options.addWidget(self._timeout)
        self._follow = QCheckBox("跟随重定向")
        self._follow.setChecked(True)
        options.addWidget(self._follow)
        self._verify = QCheckBox("校验证书")
        self._verify.setChecked(True)
        options.addWidget(self._verify)
        options.addStretch()

        split = QSplitter(Qt.Vertical)
        split.setObjectName("httpWorkspace")
        split.setChildrenCollapsible(False)
        split.setHandleWidth(8)

        request_page = QWidget()
        request_page.setObjectName("httpRequestPanel")
        request_lo = QVBoxLayout(request_page)
        request_lo.setContentsMargins(10, 10, 10, 8)
        request_lo.setSpacing(SPACE_SM)
        request_lo.addLayout(request_bar)
        request_lo.addLayout(options)
        self._request_tabs = QTabWidget()
        self._request_tabs.setObjectName("httpRequestTabs")
        self._request_tabs.setDocumentMode(True)
        self._http_headers = self._make_pair_tab(
            "Header", ["启用", "Header", "值", "描述"])
        self._params = self._make_pair_tab(
            "Query", ["启用", "参数名", "参数值", "描述"])
        self._path_params = self._make_pair_tab(
            "Path", ["启用", "参数名", "参数值", "描述"])
        self._build_body_tab()
        self._build_auth_tab()
        self._request_cookies = self._make_pair_tab(
            "Cookie", ["启用", "Cookie", "值", "描述"])
        request_lo.addWidget(self._request_tabs)
        split.addWidget(request_page)

        response_page = QWidget()
        response_page.setObjectName("httpResponsePanel")
        response_lo = QVBoxLayout(response_page)
        response_lo.setContentsMargins(10, 8, 10, 10)
        response_lo.setSpacing(SPACE_SM)

        response_info = QHBoxLayout()
        response_info.setSpacing(SPACE_SM)
        response_title = QLabel("响应")
        response_title.setObjectName("httpSectionTitle")
        response_info.addWidget(response_title)
        response_info.addStretch()
        self._status = self._chip("等待请求", "#6B7280", "#EEF1F5")
        self._elapsed = self._chip("— ms", "#5F6670", "#F1F3F6")
        self._size = self._chip("— B", "#5F6670", "#F1F3F6")
        response_info.addWidget(self._status)
        response_info.addWidget(self._elapsed)
        response_info.addWidget(self._size)
        response_lo.addLayout(response_info)

        self._response_tabs = QTabWidget()
        self._response_tabs.setObjectName("httpResponseTabs")
        self._response_tabs.setDocumentMode(True)
        body_page = QWidget()
        body_lo = QVBoxLayout(body_page)
        body_lo.setContentsMargins(0, 0, 0, 0)
        body_lo.setSpacing(4)

        body_toolbar = QHBoxLayout()
        body_toolbar.setSpacing(6)
        self._btn_pretty = QPushButton("美化")
        self._set_button_icon(self._btn_pretty, "http_format.svg")
        self._btn_pretty.setFixedHeight(30)
        self._btn_pretty.clicked.connect(self._pretty_response)
        self._btn_raw = QPushButton("原始")
        self._set_button_icon(self._btn_raw, "http_raw.svg")
        self._btn_raw.setFixedHeight(30)
        self._btn_raw.clicked.connect(self._show_raw_response)
        body_toolbar.addWidget(self._btn_pretty)
        body_toolbar.addWidget(self._btn_raw)
        self._response_format = QComboBox()
        self._response_format.addItems(
            ["JSON", "XML", "HTML", "Text", "Auto"])
        self._response_format.setFixedHeight(30)
        self._response_format.setCurrentText("Auto")
        self._response_format.currentTextChanged.connect(
            self._refresh_response_highlight)
        body_toolbar.addWidget(self._response_format)
        self._encoding = QComboBox()
        self._encoding.addItems(["UTF-8", "GBK", "Latin-1"])
        self._encoding.setFixedHeight(30)
        body_toolbar.addWidget(self._encoding)
        body_toolbar.addStretch()
        self._btn_copy = QPushButton("复制")
        self._set_button_icon(self._btn_copy, "http_copy.svg")
        self._btn_copy.setFixedHeight(30)
        self._btn_copy.clicked.connect(self._copy_response)
        body_toolbar.addWidget(self._btn_copy)
        self._btn_save_response = QPushButton("保存响应")
        self._set_button_icon(self._btn_save_response, "http_save.svg")
        self._btn_save_response.setFixedHeight(30)
        self._btn_save_response.clicked.connect(self._save_response)
        body_toolbar.addWidget(self._btn_save_response)
        self._btn_save_example = QPushButton("存为示例")
        self._set_button_icon(self._btn_save_example, "http_example.svg")
        self._btn_save_example.setFixedHeight(30)
        self._btn_save_example.clicked.connect(self._save_response_example)
        body_toolbar.addWidget(self._btn_save_example)
        body_lo.addLayout(body_toolbar)

        self._response_body = QPlainTextEdit()
        self._response_body.setObjectName("httpResponseEditor")
        self._response_body.setReadOnly(True)
        self._response_body.setFont(QFont(FONT_MONO, 10))
        self._response_body.setPlaceholderText("响应内容")
        body_lo.addWidget(self._response_body, 1)
        self._response_tabs.addTab(body_page, "实时响应")

        self._response_headers = _table(["响应头", "值"])
        self._response_headers.setColumnWidth(0, 220)
        self._response_tabs.addTab(self._response_headers, "响应头")
        self._response_cookies = _table([
            "Name", "Value", "Domain", "Path", "Expires",
            "HttpOnly", "Secure",
        ])
        self._response_tabs.addTab(self._response_cookies, "Cookie")

        self._response_example = QPlainTextEdit()
        self._response_example.setObjectName("httpResponseExample")
        self._response_example.setReadOnly(True)
        self._response_example.setFont(QFont(FONT_MONO, 10))
        self._response_example.setPlaceholderText(
            "暂无响应示例。收到响应后可点击“存为示例”。")
        self._response_tabs.addTab(self._response_example, "响应示例")

        self._build_actual_request_tab()
        self._console = QPlainTextEdit()
        self._console.document().setMaximumBlockCount(5000)
        self._console.setObjectName("httpConsole")
        self._console.setReadOnly(True)
        self._console.setFont(QFont(FONT_MONO, 10))
        self._console.setPlaceholderText(
            "控制台显示请求准备、完成耗时和错误信息。\n"
            "当前版本不执行请求脚本。")
        self._response_tabs.addTab(self._console, "控制台")

        response_lo.addWidget(self._response_tabs)
        split.addWidget(response_page)
        split.setSizes([430, 360])
        root.addWidget(split, 1)
        for combo in self.findChildren(QComboBox):
            combo_font = QFont(FONT_UI, 9, QFont.Weight.Normal)
            combo.setFont(combo_font)
            combo.view().setFont(combo_font)

    @staticmethod
    def _blank_response_state():
        return {
            "last_request": {},
            "last_result": {},
            "raw_response": "",
            "status": "等待请求",
            "status_style": (
                "QLabel#httpChip{color:#6B7280;background:#EEF1F5;"
                "border-radius:10px;padding:3px 9px;font-size:12px;"
                "font-weight:600;}"),
            "elapsed": "— ms",
            "size": "— B",
            "body": "",
            "response_content_type": "",
            "response_format": "Auto",
            "encoding": "UTF-8",
            "headers": [],
            "cookies": [],
            "console": "",
            "response_tab": 0,
            "response_tab_labels": [
                "实时响应", "响应头", "Cookie", "响应示例",
                "实际请求", "控制台",
            ],
            "actual_headers": [],
            "actual_method": "GET",
            "actual_url": "",
            "actual_query": [],
            "actual_path": [],
            "actual_body": "",
            "actual_tab": 0,
        }

    @staticmethod
    def _table_rows(table):
        return [
            [
                table.item(row, column).text()
                if table.item(row, column) is not None else ""
                for column in range(table.columnCount())
            ]
            for row in range(table.rowCount())
        ]

    @staticmethod
    def _set_table_rows(table, rows):
        table.setRowCount(0)
        for values in rows or []:
            row = table.rowCount()
            table.insertRow(row)
            for column, value in enumerate(values):
                if column < table.columnCount():
                    table.setItem(
                        row, column, QTableWidgetItem(str(value)))

    def _capture_response_state(self):
        return {
            "last_request": copy.deepcopy(self._last_request),
            "last_result": copy.deepcopy(self._last_result),
            "raw_response": self._raw_response,
            "status": self._status.text(),
            "status_style": self._status.styleSheet(),
            "elapsed": self._elapsed.text(),
            "size": self._size.text(),
            "body": self._response_body.toPlainText(),
            "response_content_type": self._response_content_type,
            "response_format": self._response_format.currentText(),
            "encoding": self._encoding.currentText(),
            "headers": self._table_rows(self._response_headers),
            "cookies": self._table_rows(self._response_cookies),
            "console": self._console.toPlainText(),
            "response_tab": self._response_tabs.currentIndex(),
            "response_tab_labels": [
                self._response_tabs.tabText(index)
                for index in range(self._response_tabs.count())
            ],
            "actual_headers": self._table_rows(self._actual_headers),
            "actual_method": self._actual_method.text(),
            "actual_url": self._actual_url.text(),
            "actual_query": self._table_rows(self._actual_query),
            "actual_path": self._table_rows(self._actual_path),
            "actual_body": self._actual_body.toPlainText(),
            "actual_tab": self._actual_tabs.currentIndex(),
        }

    def _apply_response_state(self, state):
        state = state or self._blank_response_state()
        self._last_request = copy.deepcopy(
            state.get("last_request") or {})
        self._last_result = copy.deepcopy(
            state.get("last_result") or {})
        self._raw_response = str(state.get("raw_response") or "")
        self._status.setText(str(state.get("status") or "等待请求"))
        self._status.setStyleSheet(str(state.get("status_style") or ""))
        self._elapsed.setText(str(state.get("elapsed") or "— ms"))
        self._size.setText(str(state.get("size") or "— B"))
        self._response_body.setPlainText(str(state.get("body") or ""))
        self._response_content_type = str(
            state.get("response_content_type") or "")
        self._response_format.setCurrentText(
            str(state.get("response_format") or "Auto"))
        self._encoding.setCurrentText(
            str(state.get("encoding") or "UTF-8"))
        self._refresh_response_highlight()
        self._set_table_rows(
            self._response_headers, state.get("headers"))
        self._set_table_rows(
            self._response_cookies, state.get("cookies"))
        self._console.setPlainText(str(state.get("console") or ""))
        labels = state.get("response_tab_labels") or []
        for index, label in enumerate(labels):
            if index < self._response_tabs.count():
                self._response_tabs.setTabText(index, str(label))
        self._response_tabs.setCurrentIndex(max(
            0, min(
                int(state.get("response_tab") or 0),
                self._response_tabs.count() - 1)))
        self._set_table_rows(
            self._actual_headers, state.get("actual_headers"))
        self._actual_method.setText(
            str(state.get("actual_method") or "GET"))
        self._actual_url.setText(
            str(state.get("actual_url") or ""))
        self._set_table_rows(
            self._actual_query, state.get("actual_query"))
        self._set_table_rows(
            self._actual_path, state.get("actual_path"))
        self._actual_body.setPlainText(
            str(state.get("actual_body") or ""))
        self._actual_tabs.setCurrentIndex(max(
            0, min(
                int(state.get("actual_tab") or 0),
                self._actual_tabs.count() - 1)))

    def _save_active_response_state(self):
        document = self._active_doc()
        if document is not None:
            self._response_states[id(document)] = (
                self._capture_response_state())

    def _restore_document_response_state(self, document):
        state = (
            self._response_states.get(id(document))
            if document is not None else None)
        self._apply_response_state(state)

    @staticmethod
    def _blank_request():
        return {
            "method": "GET",
            "url": "",
            "timeout": 30,
            "follow_redirects": True,
            "verify_tls": True,
            "http_version": "http/1.1",
            "params": [],
            "headers": [],
            "path_params": [],
            "cookies": [],
            "body_type": "none",
            "raw_format": "JSON",
            "body": "",
            "auth_type": "无",
            "auth_user": "",
            "response_example": "",
        }

    def _connect_document_signals(self):
        signals = (
            self._method.currentTextChanged,
            self._url.textChanged,
            self._http_version.currentTextChanged,
            self._timeout.valueChanged,
            self._follow.toggled,
            self._verify.toggled,
            self._body_group.idClicked,
            self._raw_format.currentTextChanged,
            self._body.textChanged,
            self._auth_type.currentTextChanged,
            self._auth_user.textChanged,
            self._auth_password.textChanged,
            self._auth_token.textChanged,
            self._response_example.textChanged,
        )
        for signal in signals:
            signal.connect(self._mark_document_dirty)
        for table in (
            self._http_headers,
            self._params,
            self._path_params,
            self._request_cookies,
        ):
            table.itemChanged.connect(self._mark_document_dirty)
            table.model().rowsRemoved.connect(
                self._mark_document_dirty)

    def _new_document_data(self, request=None, **values):
        folder_id = values.get("folder_id") or self._current_folder_id
        return {
            "api_id": values.get("api_id"),
            "folder_id": str(folder_id) if folder_id else None,
            "name": str(values.get("name") or "未命名接口"),
            "request": copy.deepcopy(
                request if isinstance(request, dict)
                else self._blank_request()),
            "dirty": bool(values.get("dirty", True)),
            "request_tab": max(
                0, int(values.get("request_tab", 0) or 0)),
        }

    def _active_doc(self):
        if 0 <= self._active_document < len(self._documents):
            return self._documents[self._active_document]
        return None

    def _sync_active_document(self):
        document = self._active_doc()
        if document is not None and not self._loading_document:
            document["request"] = self._capture_request()
            document["request_tab"] = self._request_tabs.currentIndex()
        return document

    @staticmethod
    def _document_tab_label(document):
        return str(document.get("name") or "未命名接口")

    @staticmethod
    def _document_method_font():
        font = QFont(FONT_UI)
        font.setPointSizeF(8.0)
        font.setWeight(QFont.Weight.DemiBold)
        return font

    def _document_method_icon_width(self):
        metrics = QFontMetrics(self._document_method_font())
        methods = [
            str((document.get("request") or {}).get("method") or "GET")
            .upper()
            for document in self._documents
        ] or ["GET"]
        return max(
            26,
            max(metrics.horizontalAdvance(method) for method in methods) + 4,
        )

    def _document_method_icon(self, method, width=None):
        method = str(method or "GET").upper()
        width = int(width or self._document_method_icon_width())
        icon = self._document_method_icons.get((method, width))
        if icon is not None:
            return icon
        pixmap = QPixmap(width * 2, 32)
        pixmap.setDevicePixelRatio(2.0)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setFont(self._document_method_font())
        painter.setPen(QColor(
            HTTP_METHOD_COLORS.get(
                method, HTTP_METHOD_COLORS["OPTIONS"])))
        painter.drawText(
            QRect(1, 3, width - 2, 13),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            method,
        )
        painter.end()
        icon = QIcon(pixmap)
        self._document_method_icons[(method, width)] = icon
        return icon

    def _update_document_tab(self, index=None):
        if index is None:
            index = self._active_document
        if 0 <= index < len(self._documents):
            document = self._documents[index]
            method = str(
                (document.get("request") or {}).get("method") or "GET")
            icon_width = self._document_method_icon_width()
            self._document_tabs.setIconSize(QSize(icon_width, 16))
            self._document_tabs.setTabText(
                index, self._document_tab_label(document))
            self._document_tabs.setTabIcon(
                index, self._document_method_icon(method, icon_width))
            self._document_tabs.set_tab_dirty(
                index, bool(document.get("dirty")))
            self._document_tabs.setTabToolTip(index, "")

    def _refresh_document_tabs(self, select=None):
        if select is None:
            select = self._active_document
        was_loading = self._loading_document
        self._loading_document = True
        self._document_tabs.blockSignals(True)
        try:
            self._document_tabs.setUsesScrollButtons(False)
            while self._document_tabs.count():
                self._document_tabs.removeTab(0)
            icon_width = self._document_method_icon_width()
            self._document_tabs.setIconSize(QSize(icon_width, 16))
            for document in self._documents:
                method = str(
                    (document.get("request") or {}).get("method") or "GET")
                index = self._document_tabs.addTab(
                    self._document_method_icon(method, icon_width),
                    self._document_tab_label(document),
                )
                self._document_tabs.set_tab_dirty(
                    index, bool(document.get("dirty")))
                self._document_tabs.setTabToolTip(index, "")
            if self._documents:
                self._active_document = max(
                    0, min(select, len(self._documents) - 1))
                self._document_tabs.setCurrentIndex(
                    self._active_document)
                self._document_tabs.updateGeometry()
                self._document_tabs._show_close_for(-1)
            can_navigate = len(self._documents) > 1
            self._btn_tab_prev.setEnabled(can_navigate)
            self._btn_tab_next.setEnabled(can_navigate)
        finally:
            self._document_tabs.blockSignals(False)
            self._loading_document = was_loading

    def _mark_document_dirty(self, *_args):
        if self._loading_document:
            return
        document = self._active_doc()
        if document is None:
            return
        document["request"] = self._capture_request()
        current_with_secrets = self._capture_request(
            include_secrets=True)
        api_id = str(document.get("api_id") or "")
        saved = next(
            (item for item in self._interfaces
             if str(item.get("id") or "") == api_id),
            None,
        )
        if saved is None:
            document["dirty"] = True
        else:
            document["dirty"] = (
                normalise_request(current_with_secrets)
                != normalise_request(saved.get("request"))
                or str(document.get("name") or "")
                != str(saved.get("name") or "")
                or document.get("folder_id") != saved.get("folder_id")
            )
        self._update_document_tab()

    def _on_document_changed(self, index):
        if (
            self._loading_document
            or index < 0
            or index >= len(self._documents)
            or index == self._active_document
        ):
            return
        old = self._active_doc()
        if old is not None:
            self._response_states[id(old)] = (
                self._capture_response_state())
            old["request"] = self._capture_request()
            old["request_tab"] = self._request_tabs.currentIndex()
        self._active_document = index
        self._loading_document = True
        try:
            self._apply_request(
                self._documents[index].get("request") or {})
            self._request_tabs.setCurrentIndex(max(
                0, int(
                    self._documents[index].get("request_tab", 0) or 0)))
        finally:
            self._loading_document = False
        self._restore_document_response_state(
            self._documents[index])
        self._emit_active_interface_changed()

    def new_document(self):
        self._save_active_response_state()
        self._sync_active_document()
        self._documents.append(self._new_document_data(
            api_id=secrets.token_hex(8),
            dirty=True,
        ))
        self._active_document = len(self._documents) - 1
        self._refresh_document_tabs(select=self._active_document)
        self._loading_document = True
        try:
            self._apply_request(self._blank_request())
            self._request_tabs.setCurrentIndex(0)
        finally:
            self._loading_document = False
        self._restore_document_response_state(
            self._active_doc())
        self._emit_interfaces_changed()
        self._emit_active_interface_changed()

    def _close_document(self, index):
        if (
            self._loading_document
            or index < 0
            or index >= len(self._documents)
        ):
            return
        self._sync_active_document()
        removed_document = self._documents[index]
        if index == self._active_document:
            self._response_states[id(removed_document)] = (
                self._capture_response_state())
        old_active = self._active_document
        del self._documents[index]
        self._response_states.pop(id(removed_document), None)
        if not self._documents:
            self._active_document = -1
            self._refresh_document_tabs()
            self._loading_document = True
            try:
                self._apply_request(self._blank_request())
                self._request_tabs.setCurrentIndex(0)
            finally:
                self._loading_document = False
            self._apply_response_state(None)
            self._emit_interfaces_changed()
            self._emit_active_interface_changed()
            return
        elif index < old_active:
            self._active_document = old_active - 1
        else:
            self._active_document = min(
                old_active, len(self._documents) - 1)
        self._refresh_document_tabs(select=self._active_document)
        self._loading_document = True
        try:
            self._apply_request(
                self._documents[self._active_document].get(
                    "request") or {})
            self._request_tabs.setCurrentIndex(max(
                0, int(
                    self._documents[self._active_document].get(
                        "request_tab", 0) or 0)))
        finally:
            self._loading_document = False
        self._restore_document_response_state(
            self._active_doc())
        self._emit_interfaces_changed()
        self._emit_active_interface_changed()

    def _resolve_unsaved_documents(self, documents):
        dirty_documents = [
            document for document in documents
            if document is not None and document.get("dirty")
        ]
        if not dirty_documents:
            return "discard"
        action = UnsavedChangesDialog.ask(dirty_documents, self)
        if action == "save":
            self._save_documents_for_close(dirty_documents)
            return "save"
        return action

    def _save_documents_for_close(self, documents):
        for document in documents:
            self._save_document_record(document)
        for index in range(len(self._documents)):
            self._update_document_tab(index)
        self._emit_interfaces_changed()
        self._emit_active_interface_changed()
        self.request_status.emit(
            "已保存 {} 个接口".format(len(documents)))
        self.save_requested.emit()

    def _request_close_document(self, index, force=False):
        if not 0 <= index < len(self._documents):
            return
        if self._active_document == index:
            self._sync_active_document()
        document = self._documents[index]
        if not force:
            action = self._resolve_unsaved_documents([document])
            if action == "cancel":
                return
        self._close_document(index)

    def _close_other_documents(self, force=False):
        if len(self._documents) <= 1 or self._loading_document:
            return
        self._save_active_response_state()
        active_document = self._sync_active_document()
        other_documents = [
            document for document in self._documents
            if document is not active_document
        ]
        if not force:
            action = self._resolve_unsaved_documents(other_documents)
            if action == "cancel":
                return
        for document in other_documents:
            self._response_states.pop(id(document), None)
        self._documents = [active_document]
        self._active_document = 0
        self._refresh_document_tabs(select=0)
        self._loading_document = True
        try:
            self._apply_request(active_document.get("request") or {})
            self._request_tabs.setCurrentIndex(max(
                0, int(active_document.get("request_tab", 0) or 0)))
        finally:
            self._loading_document = False
        self._restore_document_response_state(active_document)
        self._emit_interfaces_changed()
        self._emit_active_interface_changed()

    def _close_all_documents(self, force=False):
        if self._loading_document:
            return
        self._sync_active_document()
        if not force:
            action = self._resolve_unsaved_documents(self._documents)
            if action == "cancel":
                return
        self._documents = []
        self._active_document = -1
        self._response_states.clear()
        self._refresh_document_tabs()
        self._loading_document = True
        try:
            self._apply_request(self._blank_request())
            self._request_tabs.setCurrentIndex(0)
        finally:
            self._loading_document = False
        self._apply_response_state(None)
        self._emit_interfaces_changed()
        self._emit_active_interface_changed()

    def _show_document_tab_menu(self, position):
        index = self._document_tabs.tabAt(position)
        if index < 0:
            return
        self._document_tabs.setCurrentIndex(index)
        menu, rename, save = self._build_document_tab_menu()
        action = menu.exec(
            self._document_tabs.mapToGlobal(position))
        if action == rename:
            self._rename_current_document()
        elif action == save:
            self._save_current_document()

    def _build_document_tab_menu(self):
        menu = prepare_menu(QMenu(self))
        rename = menu.addAction("重命名")
        rename.setIcon(_http_icon("http_edit.svg"))
        save = menu.addAction("保存")
        save.setIcon(_http_icon("http_save.svg"))
        return menu, rename, save

    def _show_tab_actions_menu(self):
        menu, actions = self._build_tab_actions_menu()
        selected = menu.exec(self._btn_tab_more.mapToGlobal(
            QPoint(0, self._btn_tab_more.height())))
        if selected == actions["close_all"]:
            self._close_all_documents()
        elif selected == actions["force_close_all"]:
            self._close_all_documents(force=True)
        elif selected == actions["close_others"]:
            self._close_other_documents()
        elif selected == actions["force_close_others"]:
            self._close_other_documents(force=True)
        elif selected == actions["save_all"]:
            self._save_all_documents()

    def _build_tab_actions_menu(self):
        menu = prepare_menu(QMenu(self))
        close_all = menu.addAction("关闭所有标签")
        close_all.setIcon(_http_icon("http_close.svg"))
        force_close_all = menu.addAction("强制关闭所有标签")
        force_close_all.setIcon(_http_icon("http_close.svg"))
        close_others = menu.addAction("关闭其他标签")
        close_others.setIcon(_http_icon("http_close.svg"))
        force_close_others = menu.addAction("强制关闭其他所有标签")
        force_close_others.setIcon(_http_icon("http_close.svg"))
        save_all = menu.addAction("保存所有标签")
        save_all.setIcon(_http_icon("http_save.svg"))
        close_others.setEnabled(len(self._documents) > 1)
        force_close_others.setEnabled(len(self._documents) > 1)
        close_all.setEnabled(bool(self._documents))
        force_close_all.setEnabled(bool(self._documents))
        save_all.setEnabled(bool(self._documents))
        return menu, {
            "close_all": close_all,
            "force_close_all": force_close_all,
            "close_others": close_others,
            "force_close_others": force_close_others,
            "save_all": save_all,
        }

    def _move_document_selection(self, delta):
        count = len(self._documents)
        if count <= 1:
            return
        self._document_tabs.setCurrentIndex(
            (self._active_document + delta) % count)

    def _active_environment(self):
        return next(
            (item for item in self._environments
             if item.get("id") == self._active_environment_id),
            self._environments[0],
        )

    def _environment_variable_names(self):
        return [
            str(variable.get("name") or "").strip()
            for variable in self._active_environment().get("variables") or []
            if str(variable.get("name") or "").strip()
        ]

    def _refresh_environment_button(self):
        if self._btn_environment is None:
            return
        environment = self._active_environment()
        name = environment.get("name") or "默认环境"
        text_width = max(72, self._btn_environment.maximumWidth() - 78)
        shown_name = QFontMetrics(
            self._btn_environment.font()).elidedText(
                name, Qt.TextElideMode.ElideRight, text_width)
        self._btn_environment.setText(shown_name)
        self._btn_environment.setToolTip(
            "当前环境：{}\n点击切换或管理本地环境".format(name))
        if hasattr(self, "_url"):
            self._url.refresh_variable_highlight()

    def _update_responsive_layout(self):
        compact = self.width() < 1060
        if hasattr(self, "_btn_environment"):
            self._btn_environment.setMaximumWidth(
                210 if compact else 240)
            self._refresh_environment_button()
        if hasattr(self, "_document_tabs"):
            reserved_width = (
                TAB_CONTROL_SIZE * 4
                + self._btn_environment.maximumWidth()
                + 5 * 6
                + 2 * 8
                + 2 * SPACE_MD
                + 8
            )
            self._document_tabs.setMaximumWidth(
                max(220, self.width() - reserved_width))
        if hasattr(self, "_body_hint"):
            self._body_hint.setVisible(not compact)

    def _show_http_toast(self, message):
        self._toast_token += 1
        token = self._toast_token
        window = self.window()
        if self._http_toast.parentWidget() is not window:
            self._http_toast.setParent(window)
        self._http_toast.setText("✓ {}".format(message))
        self._http_toast.adjustSize()
        effect = QGraphicsOpacityEffect(self._http_toast)
        effect.setOpacity(0.0)
        self._http_toast.setGraphicsEffect(effect)
        self._http_toast.show()
        self._http_toast.raise_()
        self._position_http_toast()
        fade_in = QPropertyAnimation(effect, b"opacity", self)
        fade_in.setDuration(140)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)
        fade_in.start()
        self._toast_timer.start(1800)
        self._http_toast.setProperty("toastToken", token)

    def _position_http_toast(self):
        toast = getattr(self, "_http_toast", None)
        if toast is None:
            return
        window = self.window()
        if toast.parentWidget() is not window:
            toast.setParent(window)
        toast.move(
            max(12, (window.width() - toast.width()) // 2),
            4,
        )

    def _hide_http_toast(self):
        toast = self._http_toast
        if not toast.isVisible():
            return
        token = self._toast_token
        effect = toast.graphicsEffect()
        if effect is None:
            toast.hide()
            return
        fade_out = QPropertyAnimation(effect, b"opacity", self)
        fade_out.setDuration(180)
        fade_out.setStartValue(effect.opacity())
        fade_out.setEndValue(0.0)
        fade_out.finished.connect(
            lambda current=token: self._finish_hide_http_toast(current))
        fade_out.start()

    def _finish_hide_http_toast(self, token):
        if token == self._toast_token:
            self._http_toast.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_responsive_layout()
        self._position_http_toast()

    def eventFilter(self, watched, event):
        menu = self._environment_menu
        if (
            menu is not None
            and event.type() in (
                QEvent.Type.MouseButtonPress,
                QEvent.Type.MouseButtonDblClick,
            )
        ):
            global_position = event.globalPosition().toPoint()
            if not menu.frameGeometry().contains(global_position):
                if event.button() == Qt.MouseButton.LeftButton:
                    environment_rect = QRect(
                        self._btn_environment.mapToGlobal(QPoint(0, 0)),
                        self._btn_environment.size(),
                    )
                    if environment_rect.contains(global_position):
                        self._suppress_environment_click = True
                        QTimer.singleShot(
                            250, self._clear_environment_click_suppression)
                    else:
                        focus_target = self._url_focus_target_at(
                            global_position)
                        if focus_target is not None:
                            QTimer.singleShot(
                                40,
                                lambda target=focus_target:
                                self._focus_after_environment_menu(target),
                            )
                menu.close()
        return super().eventFilter(watched, event)

    def _url_focus_target_at(self, global_position):
        version_rect = QRect(
            self._http_version.mapToGlobal(QPoint(0, 0)),
            self._http_version.size(),
        )
        if version_rect.contains(global_position):
            return self._http_version
        url_shell = self._url.parentWidget()
        shell_rect = QRect(
            url_shell.mapToGlobal(QPoint(0, 0)),
            url_shell.size(),
        )
        if shell_rect.contains(global_position):
            return self._url
        return None

    @staticmethod
    def _focus_after_environment_menu(target):
        window = target.window()
        if window is not None and not window.isActiveWindow():
            window.activateWindow()
            window.raise_()
        target.setFocus(Qt.FocusReason.MouseFocusReason)

    def _clear_environment_click_suppression(self):
        self._suppress_environment_click = False

    def _set_active_environment(self, environment_id):
        environment_id = str(environment_id or "")
        if not any(
                item.get("id") == environment_id
                for item in self._environments):
            return False
        self._active_environment_id = environment_id
        self._refresh_environment_button()
        self.request_status.emit(
            "当前环境：{}".format(
                self._active_environment().get("name") or ""))
        self.save_requested.emit()
        return True

    def _show_environment_menu(self):
        if self._suppress_environment_click:
            self._suppress_environment_click = False
            return
        menu, environment_actions, new_environment, manage = (
            self._build_environment_menu())
        application = QApplication.instance()
        self._environment_menu = menu
        application.installEventFilter(self)
        try:
            selected = menu.exec(self._btn_environment.mapToGlobal(
                QPoint(0, self._btn_environment.height())))
        finally:
            application.removeEventFilter(self)
            self._environment_menu = None
        if selected in environment_actions:
            self._set_active_environment(environment_actions[selected])
        elif selected == new_environment:
            self._create_environment()
        elif selected == manage:
            self._manage_environments()

    def _build_environment_menu(self):
        menu = prepare_menu(QMenu(self))
        search = QLineEdit()
        search.setPlaceholderText("请输入环境名称")
        search.setClearButtonEnabled(True)
        search_action = QWidgetAction(menu)
        search_action.setDefaultWidget(search)
        menu.addAction(search_action)
        environment_actions = {}
        environment_menu_actions = []
        for environment in self._environments:
            action = menu.addAction(environment.get("name") or "未命名环境")
            action.setCheckable(True)
            action.setChecked(
                environment.get("id") == self._active_environment_id)
            environment_actions[action] = environment.get("id")
            environment_menu_actions.append(
                (action, str(environment.get("name") or "").lower()))
        menu.addSeparator()
        new_environment = menu.addAction("新建环境")
        new_environment.setIcon(_http_icon("http_add.svg"))
        manage = menu.addAction("环境管理…")
        manage.setIcon(_http_icon("http_environment.svg"))

        def filter_actions(text):
            query = text.strip().lower()
            for action, name in environment_menu_actions:
                action.setVisible(not query or query in name)

        search.textChanged.connect(filter_actions)
        return menu, environment_actions, new_environment, manage

    def _create_environment(self):
        name, accepted = get_text(
            self, "新建环境", "请输入环境名称", "新建环境")
        name = (name or "").strip()
        if not accepted or not name:
            return
        if any(item.get("name") == name for item in self._environments):
            show_warning(self, "环境名称重复", "环境名称不能重复。")
            return
        environment = {
            "id": secrets.token_hex(8),
            "name": name,
            "variables": [],
        }
        self._environments.append(environment)
        self._active_environment_id = environment["id"]
        self._refresh_environment_button()
        self.request_status.emit("已新建环境：{}".format(name))
        self.save_requested.emit()

    def _manage_environments(self):
        dialog = EnvironmentManagerDialog(
            self._environments, self._active_environment_id, self)
        if not dialog.exec():
            return
        self._environments = normalise_environments(
            dialog.result_environments)
        available_ids = {
            item["id"] for item in self._environments}
        self._active_environment_id = (
            dialog.result_active_environment
            if dialog.result_active_environment in available_ids
            else self._environments[0]["id"]
        )
        self._refresh_environment_button()
        self.request_status.emit("本地环境设置已更新")
        self.save_requested.emit()

    def _rename_current_document(self):
        document = self._sync_active_document()
        if document is None:
            return
        name, accepted = get_text(
            self, "重命名接口", "请输入接口名称",
            str(document.get("name") or "未命名接口"),
        )
        name = (name or "").strip()
        if not accepted or not name:
            return
        document["name"] = name
        api_id = document.get("api_id")
        if api_id:
            for item in self._interfaces:
                if item.get("id") == api_id:
                    item["name"] = name
                    break
            self._emit_interfaces_changed()
        document["dirty"] = True
        self._update_document_tab()
        self._emit_active_interface_changed()

    def _suggest_interface_name(self, request):
        parsed = urllib.parse.urlparse(str(request.get("url") or "").strip())
        pieces = [
            urllib.parse.unquote(item)
            for item in parsed.path.split("/")
            if item
        ]
        if pieces:
            name = pieces[-1]
            if "." in name:
                name = name.rsplit(".", 1)[0]
            if name:
                return name[:60]
        if parsed.netloc:
            return parsed.netloc[:60]
        return "接口 {}".format(len(self._interfaces) + 1)

    def _save_current_document(self):
        if self._loading_document:
            return
        document = self._sync_active_document()
        if document is None:
            return
        self._save_document_record(document)
        self._update_document_tab()
        self._emit_interfaces_changed()
        self._emit_active_interface_changed()
        self._console.appendPlainText(
            "已保存接口：{}".format(document["name"]))
        self.request_status.emit(
            "HTTP 接口已保存：{}".format(document["name"]))
        self.save_requested.emit()

    def _save_document_record(self, document):
        request = (
            self._capture_request(include_secrets=True)
            if document is self._active_doc()
            else copy.deepcopy(document["request"])
        )
        if not document.get("name") or document["name"] == "未命名接口":
            document["name"] = self._suggest_interface_name(request)
        api_id = str(document.get("api_id") or secrets.token_hex(8))
        document["api_id"] = api_id
        document["dirty"] = False
        document["folder_id"] = (
            self._current_folder_id or document.get("folder_id"))
        record = {
            "id": api_id,
            "name": document["name"],
            "folder_id": document.get("folder_id"),
            "request": request,
        }
        for index, item in enumerate(self._interfaces):
            if item.get("id") == api_id:
                self._interfaces[index] = record
                break
        else:
            self._interfaces.append(record)

    def _save_all_documents(self):
        if self._loading_document:
            return
        self._sync_active_document()
        for document in self._documents:
            self._save_document_record(document)
        for index in range(len(self._documents)):
            self._update_document_tab(index)
        self._emit_interfaces_changed()
        self._emit_active_interface_changed()
        if self._documents:
            message = "已保存 {} 个接口".format(len(self._documents))
            self._console.appendPlainText(message)
            self.request_status.emit(message)
            self.save_requested.emit()

    def _emit_interfaces_changed(self):
        summaries = []
        saved_ids = {
            str(item.get("id"))
            for item in self._interfaces
            if item.get("id")
        }
        for item in self._interfaces:
            request = item.get("request") or {}
            summaries.append({
                "id": item.get("id"),
                "name": item.get("name"),
                "folder_id": item.get("folder_id"),
                "method": request.get("method", "GET"),
                "url": request.get("url", ""),
                "dirty": False,
                "draft": False,
            })
        for document in self._documents:
            api_id = str(document.get("api_id") or "")
            if not api_id or api_id in saved_ids:
                continue
            request = document.get("request") or {}
            summaries.append({
                "id": api_id,
                "name": str(
                    document.get("name") or "未命名接口"),
                "folder_id": document.get("folder_id"),
                "method": request.get("method", "GET"),
                "url": request.get("url", ""),
                "dirty": bool(document.get("dirty", True)),
                "draft": True,
            })
        self.interfaces_changed.emit(summaries)
        self.folders_changed.emit(copy.deepcopy(self._folders))

    def _emit_folders_changed(self):
        self.folders_changed.emit(copy.deepcopy(self._folders))

    def _emit_active_interface_changed(self):
        document = self._active_doc()
        self.active_interface_changed.emit(
            document.get("api_id") if document is not None else None)

    def interfaces(self):
        return copy.deepcopy(self._interfaces)

    def folders(self):
        return copy.deepcopy(self._folders)

    def _transfer_library(self):
        """导出已保存接口，并用未保存文档覆盖/补充当前内容。"""
        self._sync_active_document()
        current_secrets = self._capture_request(include_secrets=True)
        saved_ids = {
            str(item.get("id"))
            for item in self._interfaces if item.get("id")
        }
        documents = {
            str(document.get("api_id")): document
            for document in self._documents
            if document.get("api_id")
        }
        interfaces = []
        for item in self._interfaces:
            record = copy.deepcopy(item)
            document = documents.get(str(item.get("id")))
            if document is not None and document.get("dirty"):
                record["name"] = str(
                    document.get("name") or record.get("name"))
                record["folder_id"] = document.get("folder_id")
                record["request"] = copy.deepcopy(
                    document.get("request") or record.get("request"))
            if document is self._active_doc():
                record["request"] = copy.deepcopy(current_secrets)
            interfaces.append(record)
        for document in self._documents:
            api_id = str(document.get("api_id") or "")
            if not api_id or api_id in saved_ids:
                continue
            interfaces.append({
                "id": api_id,
                "name": str(document.get("name") or "未命名接口"),
                "folder_id": document.get("folder_id"),
                "request": copy.deepcopy(
                    current_secrets
                    if document is self._active_doc()
                    else document.get("request") or self._blank_request()),
            })
        return {
            "folders": copy.deepcopy(self._folders),
            "interfaces": interfaces,
            "environments": copy.deepcopy(self._environments),
            "active_environment": self._active_environment_id,
        }

    def export_interfaces(self, project_name=""):
        library = self._transfer_library()
        if not library["interfaces"]:
            show_warning(self, "导出项目", "当前项目没有可导出的 HTTP 接口。")
            return False
        if contains_sensitive_values(library):
            if not ask_yes_no(
                self, "导出包含凭据",
                "当前 HTTP 项目包含明文密码、Token 或环境变量凭据。\n"
                "导出后请妥善保管，确定继续导出吗？",
                confirm_text="继续导出", danger=True,
            ):
                return False
        dialog = ExportTransferDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        format_name = dialog.selected_format
        safe_name = re.sub(
            r'[\\/:*?"<>|]+', "_", str(project_name or "HTTP接口"))
        default_name = "{}_{}.json".format(
            safe_name, FORMAT_LABELS[format_name].split()[0])
        path, _ = QFileDialog.getSaveFileName(
            self, "导出项目", default_name,
            "JSON 文件 (*.json);;所有文件 (*.*)")
        if not path:
            return False
        try:
            payload = build_transfer(
                library, format_name, project_name)
            with open(path, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
        except Exception as exc:
            show_error(self, "导出失败", str(exc))
            return False
        self._show_http_toast("导出成功")
        self.request_status.emit(
            "已导出 {} 个 HTTP 接口".format(
                len(library["interfaces"])))
        return True

    def _folder_path(self, folder_id, folders=None):
        folder_by_id = {
            str(item.get("id")): item
            for item in (folders if folders is not None else self._folders)
            if item.get("id")
        }
        names = []
        current = str(folder_id or "") or None
        seen = set()
        while current and current in folder_by_id and current not in seen:
            seen.add(current)
            item = folder_by_id[current]
            names.append(str(item.get("name") or "新建目录"))
            current = str(item.get("parent_id") or "") or None
        return tuple(reversed(names))

    def import_interfaces(self, project_name=""):
        current_name = "/".join(
            self._folder_path(self._current_folder_id)) or "根目录"
        dialog = ImportTransferDialog(current_name, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        if dialog.as_new_project:
            self.new_project_import_requested.emit(
                dialog.source_name or "导入项目",
                dialog.transfer_result,
                dialog.conflict_policy,
            )
            return True
        target_folder = self._current_folder_id
        imported, skipped = self._apply_transfer(
            dialog.transfer_result,
            target_folder,
            dialog.conflict_policy,
        )
        self._show_http_toast("导入成功")
        self.request_status.emit(
            "HTTP 接口导入完成：新增 {} 个，跳过 {} 个".format(
                imported, skipped))
        return True

    def _apply_transfer(
            self, transfer_result, target_folder_id=None,
            conflict_policy="merge"):
        result = transfer_result if isinstance(
            transfer_result, dict) else {}
        folders = copy.deepcopy(self._folders)
        interfaces = copy.deepcopy(self._interfaces)
        environments = copy.deepcopy(self._environments)
        environment_by_name = {
            str(item.get("name") or ""): item
            for item in environments
        }
        imported_environment_ids = {}
        for raw_environment in result.get("environments") or []:
            if not isinstance(raw_environment, dict):
                continue
            name = str(
                raw_environment.get("name") or "导入环境").strip()
            environment = environment_by_name.get(name)
            if environment is None:
                environment = {
                    "id": secrets.token_hex(8),
                    "name": name or "导入环境",
                    "variables": [],
                }
                environments.append(environment)
                environment_by_name[environment["name"]] = environment
            existing_names = {
                str(item.get("name") or "")
                for item in environment.get("variables") or []
            }
            for variable in raw_environment.get("variables") or []:
                if not isinstance(variable, dict):
                    continue
                variable_name = str(
                    variable.get("name") or "").strip()
                if not variable_name or variable_name in existing_names:
                    continue
                environment["variables"].append({
                    "name": variable_name,
                    "value": str(variable.get("value") or ""),
                    "description": str(
                        variable.get("description") or ""),
                })
                existing_names.add(variable_name)
            imported_environment_ids[name] = environment["id"]
        folder_by_path = {
            self._folder_path(item.get("id"), folders): str(item.get("id"))
            for item in folders if item.get("id")
        }
        target_path = self._folder_path(target_folder_id, folders)

        def ensure_folder(path):
            full_path = tuple(target_path) + tuple(path)
            current_path = ()
            parent_id = (
                str(target_folder_id)
                if target_folder_id else None)
            for name in full_path:
                current_path += (str(name),)
                existing = folder_by_path.get(current_path)
                if existing:
                    parent_id = existing
                    continue
                folder_id = secrets.token_hex(8)
                folders.append({
                    "id": folder_id,
                    "name": str(name),
                    "parent_id": parent_id,
                })
                folder_by_path[current_path] = folder_id
                parent_id = folder_id
            return parent_id

        for folder in result.get("folders") or []:
            path = folder.get("path") if isinstance(folder, dict) else None
            if path:
                ensure_folder(tuple(path))

        seen = {
            (
                str((item.get("request") or {}).get("method") or "GET").upper(),
                str((item.get("request") or {}).get("url") or "").strip(),
            )
            for item in interfaces
        }
        imported_ids = []
        skipped = 0
        for item in result.get("interfaces") or []:
            if not isinstance(item, dict):
                continue
            request = normalise_request(item.get("request"))
            key = (
                str(request.get("method") or "GET").upper(),
                str(request.get("url") or "").strip(),
            )
            if conflict_policy == "skip" and key in seen:
                skipped += 1
                continue
            folder_id = ensure_folder(item.get("folder_path") or ())
            api_id = secrets.token_hex(8)
            interfaces.append({
                "id": api_id,
                "name": str(item.get("name") or "未命名接口"),
                "folder_id": folder_id,
                "request": request,
            })
            imported_ids.append(api_id)
            seen.add(key)

        self._folders = folders
        self._interfaces = interfaces
        self._environments = normalise_environments(environments)
        imported_active = result.get("active_environment")
        active_name = (
            str(imported_active.get("name") or "")
            if isinstance(imported_active, dict) else "")
        active_id = imported_environment_ids.get(active_name)
        if active_id:
            self._active_environment_id = active_id
        self._refresh_environment_button()
        self._emit_interfaces_changed()
        self.save_requested.emit()
        if imported_ids:
            self.open_interface(imported_ids[0])
        return len(imported_ids), skipped

    def set_current_folder(self, folder_id):
        folder_id = str(folder_id or "") or None
        if folder_id and not any(
                item.get("id") == folder_id for item in self._folders):
            folder_id = None
        self._current_folder_id = folder_id

    def create_folder(self, name, parent_id=None):
        name = str(name or "").strip()
        if not name:
            return None
        parent_id = str(parent_id or "") or None
        if parent_id and not any(
                item.get("id") == parent_id for item in self._folders):
            parent_id = None
        folder = {
            "id": secrets.token_hex(8),
            "name": name,
            "parent_id": parent_id,
        }
        self._folders.append(folder)
        self._emit_folders_changed()
        return folder["id"]

    def rename_folder(self, folder_id, name):
        name = str(name or "").strip()
        if not name:
            return False
        for folder in self._folders:
            if folder.get("id") == str(folder_id):
                folder["name"] = name
                self._emit_folders_changed()
                return True
        return False

    def rename_interface(self, api_id, name):
        name = str(name or "").strip()
        if not name:
            return False
        changed = False
        for item in self._interfaces:
            if item.get("id") == str(api_id):
                item["name"] = name
                changed = True
                break
        for index, document in enumerate(self._documents):
            if document.get("api_id") == str(api_id):
                document["name"] = name
                document["dirty"] = True
                self._update_document_tab(index)
                changed = True
        if not changed:
            return False
        self._emit_interfaces_changed()
        self._emit_active_interface_changed()
        return True

    def move_interface(self, api_id, folder_id=None):
        folder_id = str(folder_id or "") or None
        if folder_id and not any(
                item.get("id") == folder_id for item in self._folders):
            folder_id = None
        changed = False
        for item in self._interfaces:
            if item.get("id") == str(api_id):
                item["folder_id"] = folder_id
                changed = True
                break
        for document in self._documents:
            if document.get("api_id") == str(api_id):
                document["folder_id"] = folder_id
                document["dirty"] = True
                changed = True
        if not changed:
            return False
        self._current_folder_id = folder_id
        self._emit_interfaces_changed()
        self._emit_active_interface_changed()
        return True

    def duplicate_interface(self, api_id):
        source = next(
            (item for item in self._interfaces
             if item.get("id") == str(api_id)),
            None,
        )
        if source is None:
            return False
        same_folder_names = {
            item.get("name") for item in self._interfaces
            if item.get("folder_id") == source.get("folder_id")
        }
        base = "{} 副本".format(source.get("name") or "未命名接口")
        name = base
        index = 2
        while name in same_folder_names:
            name = "{} {}".format(base, index)
            index += 1
        duplicate = {
            "id": secrets.token_hex(8),
            "name": name,
            "folder_id": source.get("folder_id"),
            "request": copy.deepcopy(source.get("request") or {}),
        }
        self._interfaces.append(duplicate)
        self._emit_interfaces_changed()
        self.open_interface(duplicate["id"])
        self.save_requested.emit()
        self.request_status.emit("接口已复制：{}".format(name))
        return True

    def delete_interface(self, api_id):
        api_id = str(api_id or "")
        interface = next(
            (item for item in self._interfaces
             if item.get("id") == api_id),
            None,
        )
        if interface is None:
            draft = next(
                (document for document in self._documents
                 if document.get("api_id") == api_id),
                None,
            )
            if draft is None:
                return False
            name = draft.get("name") or "未命名接口"
        else:
            name = interface.get("name") or "未命名接口"
        self._remove_library_items(interface_ids={api_id})
        self.request_status.emit("接口已删除：{}".format(name))
        return True

    def delete_folder(self, folder_id):
        folder_id = str(folder_id or "")
        if not any(
                item.get("id") == folder_id for item in self._folders):
            return False
        removed_folders = {folder_id}
        changed = True
        while changed:
            changed = False
            for folder in self._folders:
                if (
                    folder.get("parent_id") in removed_folders
                    and folder.get("id") not in removed_folders
                ):
                    removed_folders.add(folder.get("id"))
                    changed = True
        removed_interfaces = {
            item.get("id") for item in self._interfaces
            if item.get("folder_id") in removed_folders
        }
        self._remove_library_items(
            folder_ids=removed_folders,
            interface_ids=removed_interfaces,
        )
        self.request_status.emit("文件夹已删除")
        return True

    def _remove_library_items(self, folder_ids=None, interface_ids=None):
        folder_ids = {
            str(value) for value in (folder_ids or ()) if value}
        interface_ids = {
            str(value) for value in (interface_ids or ()) if value}
        self._folders = [
            item for item in self._folders
            if item.get("id") not in folder_ids
        ]
        self._interfaces = [
            item for item in self._interfaces
            if item.get("id") not in interface_ids
        ]
        current_doc = self._active_doc()
        old_active = self._active_document
        documents = [
            doc for doc in self._documents
            if doc.get("api_id") not in interface_ids
        ]
        if not documents:
            active = -1
        else:
            current_index = next(
                (index for index, doc in enumerate(documents)
                 if doc is current_doc),
                None,
            )
            active = (
                current_index
                if current_index is not None
                else min(old_active, len(documents) - 1)
            )
        self._save_active_response_state()
        remaining_documents = {id(document) for document in documents}
        for document in self._documents:
            if id(document) not in remaining_documents:
                self._response_states.pop(id(document), None)
        self._documents = documents
        self._active_document = active
        if self._current_folder_id in folder_ids:
            self._current_folder_id = None
        self._refresh_document_tabs(select=active)
        if active >= 0:
            self._loading_document = True
            try:
                self._apply_request(
                    self._documents[active].get("request") or {})
                self._request_tabs.setCurrentIndex(max(
                    0, int(
                        self._documents[active].get(
                            "request_tab", 0) or 0)))
            finally:
                self._loading_document = False
        else:
            self._loading_document = True
            try:
                self._apply_request(self._blank_request())
                self._request_tabs.setCurrentIndex(0)
            finally:
                self._loading_document = False
        self._restore_document_response_state(
            self._documents[active] if active >= 0 else None)
        self._emit_interfaces_changed()
        self._emit_active_interface_changed()
        self.save_requested.emit()

    def open_interface(self, api_id):
        api_id = str(api_id or "")
        if not api_id:
            return False
        for index, document in enumerate(self._documents):
            if document.get("api_id") == api_id:
                self._document_tabs.setCurrentIndex(index)
                return True
        interface = next(
            (item for item in self._interfaces
             if str(item.get("id") or "") == api_id),
            None,
        )
        if interface is None:
            return False
        self._save_active_response_state()
        self._sync_active_document()
        self._documents.append(self._new_document_data(
            interface.get("request"),
            api_id=api_id,
            folder_id=interface.get("folder_id"),
            name=interface.get("name"),
            dirty=False,
        ))
        self._active_document = len(self._documents) - 1
        self._refresh_document_tabs(select=self._active_document)
        self._loading_document = True
        try:
            self._apply_request(interface.get("request") or {})
            self._request_tabs.setCurrentIndex(0)
        finally:
            self._loading_document = False
        self._apply_response_state(None)
        self._emit_active_interface_changed()
        return True

    def _make_pair_tab(self, title, headers):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(SPACE_SM)
        row = QHBoxLayout()
        row.setSpacing(6)
        add = QPushButton("添加一行")
        self._set_button_icon(add, "http_add.svg")
        add.setFixedHeight(30)
        row.addWidget(add)
        row.addStretch()
        layout.addLayout(row)
        table = _table(list(headers) + [""], row_actions=True)
        table.setColumnWidth(0, 48)
        table.setColumnWidth(1, 210)
        table.setColumnWidth(2, 300)
        table.horizontalHeader().setStretchLastSection(False)
        table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(4, 36)
        layout.addWidget(table, 1)
        add.clicked.connect(lambda: _add_pair_row(table))
        self._request_tabs.addTab(page, title)
        return table

    def _build_body_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(SPACE_SM)
        body_type_bar = QWidget()
        body_type_bar.setFixedHeight(CONTROL_HEIGHT)
        toolbar = QHBoxLayout(body_type_bar)
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(8)
        toolbar.addWidget(QLabel("Body 类型"))
        self._body_group = QButtonGroup(self)
        for index, label in enumerate([
                "none", "form-data", "urlencoded", "binary", "msgpack", "raw"]):
            radio = QRadioButton(label)
            self._body_group.addButton(radio, index)
            toolbar.addWidget(radio)
            if label == "none":
                radio.setChecked(True)
        self._body_group.idClicked.connect(self._on_body_type_changed)
        toolbar.addSpacing(8)
        self._body_hint = QLabel("不发送 Body")
        self._body_hint.setObjectName("httpHint")
        toolbar.addWidget(self._body_hint)
        toolbar.addStretch()
        self._btn_body_pretty = QPushButton("格式化 JSON")
        self._set_button_icon(self._btn_body_pretty, "http_format.svg")
        self._btn_body_pretty.setText("")
        self._btn_body_pretty.setToolTip("格式化 JSON")
        self._btn_body_pretty.setFixedSize(
            CONTROL_HEIGHT, CONTROL_HEIGHT)
        self._btn_body_pretty.clicked.connect(self._pretty_request_body)
        toolbar.addWidget(self._btn_body_pretty)
        self._btn_body_pretty.setVisible(False)
        self._raw_format = QComboBox()
        self._raw_format.addItems(["JSON", "XML", "Text"])
        self._raw_format.setFixedHeight(30)
        self._raw_format.setVisible(False)
        toolbar.addWidget(self._raw_format)
        self._btn_load_binary = QPushButton("选择文件")
        self._set_button_icon(self._btn_load_binary, "http_upload.svg")
        self._btn_load_binary.setText("")
        self._btn_load_binary.setToolTip("选择二进制文件")
        self._btn_load_binary.setFixedSize(
            CONTROL_HEIGHT, CONTROL_HEIGHT)
        self._btn_load_binary.clicked.connect(self._load_binary_file)
        self._btn_load_binary.setVisible(False)
        toolbar.addWidget(self._btn_load_binary)
        layout.addWidget(body_type_bar)
        self._body = QPlainTextEdit()
        self._body.setObjectName("httpBodyEditor")
        self._body.setFont(QFont(FONT_MONO, 10))
        self._body.setEnabled(False)
        layout.addWidget(self._body, 1)
        self._request_tabs.addTab(page, "Body")
        self._on_body_type_changed(0)

    def _body_type(self):
        button = self._body_group.checkedButton()
        return button.text() if button is not None else "none"

    def _set_body_type(self, label):
        for button in self._body_group.buttons():
            if button.text() == label:
                button.setChecked(True)
                self._on_body_type_changed(button.group().id(button))
                return
        self._set_body_type("none")

    def _on_body_type_changed(self, _index=None):
        body_type = self._body_type()
        placeholders = {
            "none": "",
            "form-data": "每行一个字段：name=value\n文件字段：file=@C:\\path\\to\\file.bin",
            "urlencoded": "每行一个字段：name=value",
            "binary": "输入 HEX，例如：01 02 FF；也可以点击“选择文件”",
            "msgpack": '输入 JSON，例如：{"code":"0","message":"OK"}',
            "raw": "输入原始文本，可选择 JSON/XML/Text 内容类型",
        }
        hints = {
            "none": "不发送 Body",
            "form-data": "multipart/form-data",
            "urlencoded": "application/x-www-form-urlencoded",
            "binary": "原始二进制 / application/octet-stream",
            "msgpack": "application/msgpack",
            "raw": "原始文本",
        }
        self._body.setEnabled(body_type != "none")
        self._body.setPlaceholderText(placeholders[body_type])
        self._body_hint.setText(hints[body_type])
        self._btn_load_binary.setVisible(body_type == "binary")
        self._btn_body_pretty.setVisible(
            body_type in ("msgpack", "raw"))
        self._raw_format.setVisible(body_type == "raw")

    def _load_binary_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择二进制文件", "", "所有文件 (*.*)")
        if not path:
            return
        try:
            with open(path, "rb") as source:
                data = source.read()
        except Exception as exc:
            show_error(self, "读取失败", str(exc))
            return
        self._body.setPlainText(data.hex(" ").upper())
        self._body_hint.setText(
            "{} / {} 字节".format(os.path.basename(path), len(data)))

    def _build_auth_tab(self):
        page = QWidget()
        self._auth_page = page
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(SPACE_SM)
        row = QHBoxLayout()
        row.setSpacing(SPACE_SM)
        row.addWidget(QLabel("认证方式"))
        self._auth_type = QComboBox()
        self._auth_type.addItems(["无", "Bearer", "Basic"])
        self._auth_type.setFixedSize(140, CONTROL_HEIGHT)
        row.addWidget(self._auth_type)
        row.addStretch()
        layout.addLayout(row)
        self._auth_user = QLineEdit()
        self._auth_user.setPlaceholderText("Basic 用户名")
        self._auth_user.setFixedHeight(CONTROL_HEIGHT)
        self._auth_password = QLineEdit()
        self._auth_password.setEchoMode(QLineEdit.Password)
        self._auth_password.setPlaceholderText("Basic 密码")
        self._auth_password.setFixedHeight(CONTROL_HEIGHT)
        self._auth_password.setToolTip(
            "认证信息可能在 HTTP 项目导出时以明文写入，请妥善保管导出文件")
        self._auth_token = QLineEdit()
        self._auth_token.setEchoMode(QLineEdit.Password)
        self._auth_token.setPlaceholderText("Bearer Token")
        self._auth_token.setFixedHeight(CONTROL_HEIGHT)
        self._auth_token.setToolTip(
            "Token 可能在 HTTP 项目导出时以明文写入，请妥善保管导出文件")
        layout.addWidget(self._auth_user)
        layout.addWidget(self._auth_password)
        layout.addWidget(self._auth_token)
        layout.addStretch()
        self._request_tabs.addTab(page, "认证")

    @staticmethod
    def _chip(text, color, background):
        label = QLabel(text)
        label.setObjectName("httpChip")
        label.setStyleSheet(
            "QLabel#httpChip{{color:{};background:{};"
            "border-radius:10px;padding:3px 9px;"
            "font-size:12px;font-weight:600;}}".format(color, background))
        return label

    @staticmethod
    def _resolved_pairs(table, resolver):
        pairs = []
        for configured_name, configured_value in _enabled_pairs(table):
            name = resolver.resolve(configured_name).strip()
            value = resolver.resolve(configured_value)
            if name:
                pairs.append((name, value))
        return pairs

    def _request_body(self, content_type, resolver=None):
        body_type = self._body_type()
        raw = self._body.toPlainText()
        if body_type == "none":
            return None
        if resolver is not None:
            raw = resolver.resolve(raw)
            resolver.raise_if_invalid()
        if body_type == "form-data":
            boundary = "----AnhuToolbox{}".format(secrets.token_hex(12))
            content_type.setdefault(
                "Content-Type",
                "multipart/form-data; boundary={}".format(boundary))
            chunks = []
            for line in raw.splitlines():
                if not line.strip():
                    continue
                name, separator, value = line.partition("=")
                if not separator or not name.strip():
                    raise ValueError("form-data 每行格式必须为 name=value")
                chunks.append(
                    "--{}\r\n".format(boundary).encode("ascii"))
                if value.startswith("@") and os.path.isfile(value[1:]):
                    path = value[1:]
                    filename = os.path.basename(path)
                    mime = mimetypes.guess_type(path)[0] or \
                        "application/octet-stream"
                    chunks.append((
                        'Content-Disposition: form-data; name="{}"; '
                        'filename="{}"\r\n'
                        "Content-Type: {}\r\n\r\n"
                    ).format(name, filename, mime).encode("utf-8"))
                    with open(path, "rb") as source:
                        chunks.append(source.read())
                    chunks.append(b"\r\n")
                else:
                    chunks.append((
                        'Content-Disposition: form-data; name="{}"\r\n\r\n'
                        "{}"
                    ).format(name, value).encode("utf-8"))
                    chunks.append(b"\r\n")
            chunks.append(
                "--{}--\r\n".format(boundary).encode("ascii"))
            return b"".join(chunks)
        if body_type == "urlencoded":
            fields = []
            for line in raw.splitlines():
                if not line.strip():
                    continue
                name, separator, value = line.partition("=")
                if not separator or not name.strip():
                    raise ValueError("urlencoded 每行格式必须为 name=value")
                fields.append((name.strip(), value))
            content_type.setdefault(
                "Content-Type", "application/x-www-form-urlencoded")
            return urllib.parse.urlencode(fields).encode("utf-8")
        if body_type == "binary":
            content_type.setdefault(
                "Content-Type", "application/octet-stream")
            return parse_hex_bytes(raw)
        if body_type == "msgpack":
            if not raw.strip():
                return None
            value = json.loads(raw)
            content_type.setdefault("Content-Type", "application/msgpack")
            return msgpack.packb(value, use_bin_type=True)
        raw_format = self._raw_format.currentText()
        content_type.setdefault("Content-Type", {
            "JSON": "application/json",
            "XML": "application/xml",
            "Text": "text/plain; charset=utf-8",
        }[raw_format])
        if raw_format == "JSON" and raw.strip():
            json.loads(raw)
        return raw.encode("utf-8")

    def _send(self):
        if self._worker is not None and self._worker.isRunning():
            return
        document = self._active_doc()
        if document is None:
            show_warning(self, "提示", "请先点击 + 新建或打开一个接口。")
            return
        self._sync_active_document()
        url = self._url.text().strip()
        if not url:
            show_warning(self, "提示", "请输入请求 URL。")
            return
        resolver = EnvironmentResolver(self._active_environment())

        try:
            path_params = self._resolved_pairs(
                self._path_params, resolver)
            for name, value in path_params:
                encoded = urllib.parse.quote(value, safe="")
                url = url.replace("{{" + name + "}}", encoded)
                url = url.replace("{" + name + "}", encoded)
            url = resolver.resolve(url)
            headers = self._build_headers(resolver)
            cookie_header = "; ".join(
                "{}={}".format(name, value)
                for name, value in self._resolved_pairs(
                    self._request_cookies, resolver))
            if cookie_header:
                headers.setdefault("Cookie", cookie_header)
            params = self._resolved_pairs(self._params, resolver)
            resolver.raise_if_invalid()
        except EnvironmentVariableError as exc:
            show_warning(self, "环境变量错误", str(exc))
            return
        except ValueError as exc:
            show_warning(self, "请求 Header 错误", str(exc))
            return

        try:
            content = self._request_body(headers, resolver)
        except EnvironmentVariableError as exc:
            show_warning(self, "环境变量错误", str(exc))
            return
        except (ValueError, json.JSONDecodeError) as exc:
            show_warning(self, "请求内容错误", str(exc))
            return

        try:
            resolver.raise_if_invalid()
        except EnvironmentVariableError as exc:
            show_warning(self, "环境变量错误", str(exc))
            return

        request = {
            "method": self._method.currentText(),
            "url": url,
            "params": params,
            "path_params": path_params,
            "headers": headers,
            "content": content,
            "timeout": self._timeout.value(),
            "follow_redirects": self._follow.isChecked(),
            "verify_tls": self._verify.isChecked(),
        }
        self._last_request = request
        self._request_document_key = id(document)
        self._request_document_request = copy.deepcopy(request)
        self._update_actual_request(request)
        self._console.appendPlainText(
            ">>> {} {}".format(request["method"], url))
        self._status.setText("请求中...")
        self._status.setStyleSheet(
            "QLabel#httpChip{color:#8A5A00;background:#FFF4CE;"
            "border-radius:10px;padding:3px 9px;font-size:12px;"
            "font-weight:600;}")
        self._elapsed.setText("— ms")
        self._size.setText("— B")
        self._response_tabs.setCurrentIndex(0)
        self._btn_send.setEnabled(False)
        self._response_states[self._request_document_key] = (
            self._capture_response_state())
        self.request_status.emit("HTTP 请求中...")

        self._worker = HTTPRequestWorker()
        self._worker.configure(request)
        self._worker.start()
        self._poll_timer.start()

    def _poll_request(self):
        worker = self._worker
        if worker is None:
            self._poll_timer.stop()
            return
        event = worker.pop_event()
        if event is None:
            return
        self._poll_timer.stop()
        kind, payload = event
        self._apply_request_result(
            kind,
            payload,
            self._request_document_key,
            self._request_document_request,
        )
        self._request_document_key = None
        self._request_document_request = {}

    def _apply_request_result(
            self, kind, payload, origin_key, origin_request):
        current_document = self._active_doc()
        current_key = id(current_document) if current_document else None
        if current_key == origin_key or origin_key is None:
            self._last_request = copy.deepcopy(origin_request or {})
            if kind == "ok":
                self._on_finished(payload)
            else:
                self._on_failed(payload)
            if current_document is not None:
                self._response_states[id(current_document)] = (
                    self._capture_response_state())
            return

        # 请求所属接口已被关闭时不再把结果写到其他接口。
        origin_document = next(
            (document for document in self._documents
             if id(document) == origin_key),
            None,
        )
        if origin_document is None:
            return
        current_state = (
            self._capture_response_state()
            if current_document is not None else None)
        pending_state = (
            self._response_states.get(origin_key)
            or self._blank_response_state())
        self._apply_response_state(pending_state)
        self._last_request = copy.deepcopy(origin_request or {})
        if kind == "ok":
            self._on_finished(payload)
        else:
            self._on_failed(payload)
        self._response_states[origin_key] = self._capture_response_state()
        self._apply_response_state(current_state)

    def _build_headers(self, resolver=None):
        headers = {}
        configured_headers = []
        for item in _table_entries(self._http_headers):
            if not item["enabled"] or not item["name"].strip():
                continue
            name = item["name"].strip()
            value = item["value"].strip()
            if resolver is not None:
                name = resolver.resolve(name)
                value = resolver.resolve(value)
            configured_headers.append((name.strip(), value.strip()))

        auth_type = self._auth_type.currentText()
        auth_user = ""
        auth_password = ""
        auth_token = ""
        if auth_type == "Bearer":
            auth_token = self._auth_token.text().strip()
            if resolver is not None:
                auth_token = resolver.resolve(auth_token).strip()
        elif auth_type == "Basic":
            auth_user = self._auth_user.text().strip()
            auth_password = self._auth_password.text()
            if resolver is not None:
                auth_user = resolver.resolve(auth_user).strip()
                auth_password = resolver.resolve(auth_password)
        if resolver is not None:
            resolver.raise_if_invalid()

        for name, value in configured_headers:
            name = name.strip()
            value = value.strip()
            if not _HEADER_NAME.fullmatch(name):
                raise ValueError("Header 名称不合法：{}".format(name))
            if any(char in value for char in ("\r", "\n", "\x00")):
                raise ValueError("Header 值不能包含换行或控制字符：{}".format(name))
            headers[name] = value

        if auth_type == "Bearer":
            if not auth_token:
                self._request_tabs.setCurrentWidget(self._auth_page)
                raise ValueError("已选择 Bearer 认证，请输入 Bearer Token")
            headers["Authorization"] = "Bearer " + auth_token
        elif auth_type == "Basic":
            if not auth_user and not auth_password:
                self._request_tabs.setCurrentWidget(self._auth_page)
                raise ValueError("已选择 Basic 认证，请输入用户名和密码")
            token = base64.b64encode(
                "{}:{}".format(auth_user, auth_password).encode("utf-8")
            ).decode("ascii")
            headers["Authorization"] = "Basic " + token
        return headers

    def _build_actual_request_tab(self):
        page = QWidget()
        self._actual_request_page = page
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(SPACE_SM)
        layout.addWidget(QLabel("请求 URL"))
        url_row = QHBoxLayout()
        self._actual_method = QLabel("GET")
        self._actual_method.setStyleSheet(
            "color:#8A5A00;background:#FFF0C2;border-radius:4px;"
            "padding:3px 8px;font-weight:600;")
        url_row.addWidget(self._actual_method)
        self._actual_url = QLineEdit()
        self._actual_url.setReadOnly(True)
        self._actual_url.setPlaceholderText("请求发送后显示最终 URL")
        self._actual_url.setFixedHeight(CONTROL_HEIGHT)
        url_row.addWidget(self._actual_url, 1)
        layout.addLayout(url_row)
        layout.addWidget(QLabel("请求参数"))
        self._actual_tabs = QTabWidget()
        self._actual_tabs.setObjectName("httpActualTabs")
        self._actual_tabs.setDocumentMode(True)
        self._actual_headers = _table(["参数名", "参数值"])
        self._actual_tabs.addTab(self._actual_headers, "Header")
        self._actual_query = _table(["参数名", "参数值"])
        self._actual_tabs.addTab(self._actual_query, "Query")
        self._actual_path = _table(["参数名", "参数值"])
        self._actual_tabs.addTab(self._actual_path, "Path")
        self._actual_body = QPlainTextEdit()
        self._actual_body.setObjectName("httpActualBody")
        self._actual_body.setReadOnly(True)
        self._actual_body.setFont(QFont(FONT_MONO, 10))
        self._actual_tabs.addTab(self._actual_body, "Body")
        layout.addWidget(self._actual_tabs, 1)
        self._response_tabs.addTab(page, "实际请求")

    def _update_actual_request(self, request):
        method = str(request.get("method") or "GET")
        url = str(request.get("url") or "")
        self._actual_method.setText(method)
        self._actual_url.setText(url)
        headers = request.get("headers") or []
        if isinstance(headers, dict):
            headers = [
                {"name": name, "value": value}
                for name, value in headers.items()
            ]
        self._fill_two_column_table(self._actual_headers, headers)
        self._fill_pairs(self._actual_query, self._last_request.get(
            "params") or [])
        self._fill_pairs(self._actual_path, self._last_request.get(
            "path_params") or [])
        content = request.get("content") or b""
        try:
            body_text = bytes(content).decode("utf-8")
        except UnicodeDecodeError:
            body_text = bytes(content).hex(" ").upper()
        self._actual_body.setPlainText(body_text)
        self._response_tabs.setTabText(
            self._response_tabs.indexOf(self._actual_request_page),
            "实际请求 ●")

    @Slot(dict)
    def _on_finished(self, result):
        self._btn_send.setEnabled(True)
        self._last_result = result
        self._populate_response(result)
        self._update_actual_request(
            result.get("request") or self._last_request)
        status = "{} {}".format(result["status"], result["reason"]).strip()
        self._status.setText(status)
        color, background = (
            ("#107C10", "#E8F5E9")
            if 200 <= result["status"] < 300
            else ("#A4262C", "#FDECEA"))
        self._status.setStyleSheet(
            "QLabel#httpChip{{color:{};background:{};border-radius:10px;"
            "padding:3px 9px;font-size:12px;font-weight:600;}}".format(
                color, background))
        self._elapsed.setText("{:.0f} ms".format(result["elapsed_ms"]))
        size = len(bytes(result.get("content") or b""))
        self._size.setText(self._format_size(size))
        self._console.appendPlainText(
            "<<< {} {} | {:.0f} ms | {}".format(
                result["status"], result["reason"],
                result["elapsed_ms"], self._format_size(size)))
        self.request_status.emit(
            "HTTP {} | {:.0f} ms".format(result["status"], result["elapsed_ms"]))

    @Slot(str)
    def _on_failed(self, message):
        self._btn_send.setEnabled(True)
        self._last_result = {}
        self._status.setText("请求失败")
        self._status.setStyleSheet(
            "QLabel#httpChip{color:#A4262C;background:#FDECEA;"
            "border-radius:10px;padding:3px 9px;font-size:12px;"
            "font-weight:600;}")
        self._response_body.setPlainText(message)
        self._refresh_response_highlight()
        self._raw_response = message
        self._elapsed.setText("— ms")
        self._size.setText("— B")
        self._console.appendPlainText("!!! " + message)
        self.request_status.emit("HTTP 请求失败")

    def _populate_response(self, result):
        content = bytes(result.get("content") or b"")
        self._raw_response = content.decode("utf-8", errors="replace")
        self._decode_response(content, result)
        self._fill_table(self._response_headers, result.get("headers"))
        self._fill_cookies(result)
        header_count = len(result.get("headers") or [])
        cookie_count = self._response_cookies.rowCount()
        self._response_tabs.setTabText(1, "响应头({})".format(header_count))
        self._response_tabs.setTabText(2, "Cookie({})".format(cookie_count))
        for item in result.get("history") or []:
            self._console.appendPlainText(
                "重定向 {} -> {}".format(item["status"], item["url"]))

    @staticmethod
    def _detect_response_format(text, content_type=""):
        content_type = str(content_type or "").lower()
        stripped = str(text or "").lstrip()
        if "json" in content_type or stripped.startswith(("{", "[")):
            return "JSON"
        if "html" in content_type or stripped.lower().startswith(
                ("<!doctype html", "<html")):
            return "HTML"
        if "xml" in content_type or stripped.startswith("<"):
            return "XML"
        return "Text"

    def _effective_response_format(self):
        selected = self._response_format.currentText()
        if selected != "Auto":
            return selected
        return self._detect_response_format(
            self._response_body.toPlainText(),
            self._response_content_type,
        )

    def _refresh_response_highlight(self, *_args):
        if self._effective_response_format() != "JSON":
            self._response_body.setExtraSelections([])
            return
        text = self._response_body.toPlainText()
        formats = {
            "key": self._json_format("#A31515"),
            "string": self._json_format("#0451A5"),
            "number": self._json_format("#098658"),
            "literal": self._json_format("#7A3E9D"),
        }
        selections = []
        document = self._response_body.document()
        for match in _JSON_TOKEN.finditer(text):
            token = match.group(0)
            if token.startswith('"'):
                tail = text[match.end():]
                kind = (
                    "key" if tail.lstrip().startswith(":") else "string")
            elif token in ("true", "false", "null"):
                kind = "literal"
            else:
                kind = "number"
            cursor = QTextCursor(document)
            cursor.setPosition(match.start())
            cursor.setPosition(
                match.end(), QTextCursor.MoveMode.KeepAnchor)
            selection = QTextEdit.ExtraSelection()
            selection.cursor = cursor
            selection.format = formats[kind]
            selections.append(selection)
        self._response_body.setExtraSelections(selections)

    @staticmethod
    def _json_format(color):
        char_format = QTextCharFormat()
        char_format.setForeground(QColor(color))
        return char_format

    def _fill_cookies(self, result):
        table = self._response_cookies
        table.setRowCount(0)
        entries = []
        for item in result.get("headers") or []:
            if item.get("name", "").lower() != "set-cookie":
                continue
            jar = SimpleCookie()
            try:
                jar.load(item.get("value", ""))
            except Exception:
                continue
            entries.extend({
                    "name": morsel.key,
                    "value": morsel.value,
                    "domain": morsel["domain"],
                    "path": morsel["path"],
                    "expires": morsel["expires"],
                    "httponly": bool(morsel["httponly"]),
                    "secure": bool(morsel["secure"]),
                } for morsel in jar.values())
        if not entries:
            entries = [
                {
                    "name": item.get("name", ""),
                    "value": item.get("value", ""),
                    "domain": "", "path": "", "expires": "",
                    "httponly": False, "secure": False,
                }
                for item in result.get("cookies") or []
            ]
        for item in entries:
            row = table.rowCount()
            table.insertRow(row)
            values = [
                item["name"], item["value"], item["domain"], item["path"],
                item["expires"],
                "是" if item["httponly"] else "否",
                "是" if item["secure"] else "否",
            ]
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(str(value)))

    def _decode_response(self, content, result):
        truncated = len(content) > 2 * 1024 * 1024
        if truncated:
            content = content[:2 * 1024 * 1024]
        text = content.decode("utf-8", errors="replace")
        content_type = ""
        for item in result.get("headers") or []:
            if item["name"].lower() == "content-type":
                content_type = item["value"].lower()
                break
        self._response_content_type = content_type
        detected_format = self._detect_response_format(
            text, content_type)
        selected_format = self._response_format.currentText()
        effective_format = (
            detected_format
            if selected_format == "Auto" else selected_format)
        if selected_format == "Auto":
            self._response_format.setCurrentText(detected_format)
        is_json = effective_format == "JSON"
        if is_json:
            try:
                text = json.dumps(
                    json.loads(text), ensure_ascii=False, indent=2)
            except Exception:
                pass
        if truncated:
            text += "\n\n[响应超过 2 MB，界面仅显示前 2 MB]"
        self._response_body.setPlainText(text)
        self._refresh_response_highlight()

    @staticmethod
    def _fill_table(table, items):
        table.setRowCount(0)
        name_key = "name" if table.columnCount() == 2 else "key"
        for item in items or []:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(
                str(item.get(name_key) or item.get("name") or "")))
            table.setItem(
                row, 1, QTableWidgetItem(str(item.get("value") or "")))

    @staticmethod
    def _fill_two_column_table(table, items):
        table.setRowCount(0)
        for item in items or []:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(
                str(item.get("name") or "")))
            table.setItem(row, 1, QTableWidgetItem(
                str(item.get("value") or "")))

    @staticmethod
    def _fill_pairs(table, pairs):
        table.setRowCount(0)
        for name, value in pairs:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(str(name)))
            table.setItem(row, 1, QTableWidgetItem(str(value)))

    @staticmethod
    def _format_size(size):
        if size < 1024:
            return "{} B".format(size)
        if size < 1024 * 1024:
            return "{:.1f} KB".format(size / 1024)
        return "{:.1f} MB".format(size / (1024 * 1024))

    def _pretty_response(self):
        if not self._raw_response:
            return
        try:
            pretty = json.dumps(
                json.loads(self._raw_response), ensure_ascii=False, indent=2)
        except Exception:
            show_warning(self, "格式化失败", "响应内容不是有效 JSON。")
            return
        self._response_body.setPlainText(pretty)
        self._response_tabs.setCurrentIndex(0)
        self._refresh_response_highlight()

    def _show_raw_response(self):
        self._response_body.setPlainText(self._raw_response)
        self._response_tabs.setCurrentIndex(0)
        self._refresh_response_highlight()

    def _copy_response(self):
        text = self._response_body.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.request_status.emit("响应内容已复制")

    def _save_response(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "保存响应", "response.json",
            "JSON (*.json);;文本文件 (*.txt);;所有文件 (*.*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as target:
                target.write(self._response_body.toPlainText())
            self.request_status.emit("响应已保存")
        except Exception as exc:
            show_error(self, "保存失败", str(exc))

    def _save_response_example(self):
        text = self._response_body.toPlainText()
        if not text:
            show_warning(self, "提示", "当前没有可保存的响应。")
            return
        self._response_example.setPlainText(text)
        self._response_tabs.setCurrentWidget(self._response_example)
        self.request_status.emit("响应已存为示例")

    def _pretty_request_body(self):
        raw = self._body.toPlainText()
        try:
            value = json.loads(raw)
        except Exception:
            show_warning(self, "格式化失败", "请求 Body 不是有效 JSON。")
            return
        self._body.setPlainText(
            json.dumps(value, ensure_ascii=False, indent=2))
        if self._body_type() not in ("msgpack", "raw"):
            self._set_body_type("raw")
        if self._raw_format.isVisible():
            self._raw_format.setCurrentText("JSON")

    def _capture_request(self, include_secrets=False):
        request = {
            "method": self._method.currentText(),
            "url": self._url.text(),
            "timeout": self._timeout.value(),
            "follow_redirects": self._follow.isChecked(),
            "verify_tls": self._verify.isChecked(),
            "http_version": self._http_version.currentData(),
            "params": _table_entries(self._params),
            "headers": _table_entries(self._http_headers),
            "path_params": _table_entries(self._path_params),
            "cookies": _table_entries(self._request_cookies),
            "body_type": self._body_type(),
            "raw_format": self._raw_format.currentText(),
            "body": self._body.toPlainText(),
            "auth_type": self._auth_type.currentText(),
            "auth_user": self._auth_user.text(),
            "response_example": self._response_example.toPlainText(),
        }
        if include_secrets:
            request["auth_password"] = self._auth_password.text()
            request["auth_token"] = self._auth_token.text()
        return request

    def _normalise_request(self, data):
        data = data if isinstance(data, dict) else {}
        request = self._blank_request()
        for key in request:
            if key in data and data[key] is not None:
                request[key] = copy.deepcopy(data[key])
        return request

    def _normalise_folder(self, item):
        if not isinstance(item, dict):
            return None
        return {
            "id": str(item.get("id") or secrets.token_hex(8)),
            "name": str(item.get("name") or "新建目录"),
            "parent_id": (
                str(item.get("parent_id"))
                if item.get("parent_id") else None),
        }

    def _normalise_interface(self, item):
        if not isinstance(item, dict):
            return None
        request = item.get("request")
        if not isinstance(request, dict):
            request = {
                key: value for key, value in item.items()
                if key not in ("id", "name")
            }
        return {
            "id": str(item.get("id") or secrets.token_hex(8)),
            "name": str(item.get("name") or "未命名接口"),
            "folder_id": (
                str(item.get("folder_id"))
                if item.get("folder_id") else None),
            "request": self._normalise_request(request),
        }

    def _normalise_document(self, item):
        if not isinstance(item, dict):
            return None
        request = item.get("request")
        if not isinstance(request, dict):
            request = item
        return self._new_document_data(
            request,
            api_id=str(item.get("api_id") or "") or None,
            folder_id=(
                str(item.get("folder_id"))
                if item.get("folder_id") else None),
            name=str(item.get("name") or "未命名接口"),
            dirty=bool(item.get("dirty", True)),
            request_tab=max(
                0, int(item.get("request_tab", 0) or 0)),
        )

    def snapshot(self):
        self._sync_active_document()
        current = self._capture_request()
        interfaces = copy.deepcopy(self._interfaces)
        for item in interfaces:
            request = item.get("request")
            if isinstance(request, dict):
                request.pop("auth_password", None)
                request.pop("auth_token", None)
        documents = copy.deepcopy(self._documents)
        for document in documents:
            request = document.get("request")
            if isinstance(request, dict):
                request.pop("auth_password", None)
                request.pop("auth_token", None)
        current["interfaces"] = interfaces
        current["folders"] = copy.deepcopy(self._folders)
        current["current_folder"] = self._current_folder_id
        current["documents"] = documents
        current["active_document"] = self._active_document
        current["environments"] = copy.deepcopy(self._environments)
        current["active_environment"] = self._active_environment_id
        return current

    def apply(self, data):
        data = data if isinstance(data, dict) else {}
        self._response_states.clear()
        self._loading_document = True
        try:
            self._environments = normalise_environments(
                data.get("environments"))
            environment_ids = {
                item["id"] for item in self._environments}
            active_environment = str(
                data.get("active_environment") or "")
            self._active_environment_id = (
                active_environment
                if active_environment in environment_ids
                else self._environments[0]["id"]
            )
            self._folders = [
                item for item in (
                    self._normalise_folder(raw)
                    for raw in (data.get("folders") or [])
                )
                if item is not None
            ]
            self._interfaces = [
                item for item in (
                    self._normalise_interface(raw)
                    for raw in (data.get("interfaces") or [])
                )
                if item is not None
            ]
            folder_ids = {item["id"] for item in self._folders}
            for item in self._interfaces:
                if item.get("folder_id") not in folder_ids:
                    item["folder_id"] = None
            self._current_folder_id = str(
                data.get("current_folder") or "") or None
            if self._current_folder_id not in folder_ids:
                self._current_folder_id = None
            raw_documents = data.get("documents")
            documents = [
                item for item in (
                    self._normalise_document(raw)
                    for raw in (raw_documents or [])
                )
                if item is not None
            ]
            if not documents and raw_documents is None:
                legacy_request = self._normalise_request(data)
                has_legacy_request = bool(
                    legacy_request.get("url")
                    or legacy_request.get("body")
                    or legacy_request.get("params")
                    or legacy_request.get("headers")
                    or legacy_request.get("path_params")
                    or legacy_request.get("cookies")
                    or legacy_request.get("response_example")
                    or str(legacy_request.get("http_version") or "")
                    not in ("", "http/1.1", "HTTP/1.1")
                    or str(legacy_request.get("timeout") or 30)
                    not in ("30", "30.0")
                    or not bool(legacy_request.get(
                        "follow_redirects", True))
                    or not bool(legacy_request.get(
                        "verify_tls", True))
                    or str(legacy_request.get("method") or "GET")
                    != "GET"
                )
                if has_legacy_request:
                    documents = [
                        self._new_document_data(
                            legacy_request, dirty=True)
                    ]
            try:
                active = int(data.get("active_document", 0))
            except (TypeError, ValueError):
                active = 0
            self._documents = documents
            self._active_document = (
                max(0, min(active, len(documents) - 1))
                if documents else -1
            )
            self._refresh_document_tabs(select=self._active_document)
            if self._active_document >= 0:
                self._apply_request(
                    self._documents[self._active_document].get(
                        "request") or {})
                self._request_tabs.setCurrentIndex(max(
                    0, int(
                        self._documents[self._active_document].get(
                            "request_tab", 0) or 0)))
            else:
                self._apply_request(self._blank_request())
                self._request_tabs.setCurrentIndex(0)
            self._apply_response_state(None)
        finally:
            self._loading_document = False
        self._refresh_environment_button()
        self._emit_interfaces_changed()
        self._emit_active_interface_changed()

    def _apply_request(self, data):
        data = self._normalise_request(data)
        self._method.setCurrentText(str(data.get("method") or "GET"))
        self._url.setText(str(data.get("url") or ""))
        version = str(data.get("http_version") or "http/1.1").lower()
        if version in ("http/2", "http/2.0"):
            version = "http/2"
        elif version == "auto":
            version = "auto"
        else:
            version = "http/1.1"
        version_index = self._http_version.findData(version)
        self._http_version.setCurrentIndex(
            version_index if version_index >= 0 else 1)
        try:
            timeout = int(data.get("timeout", 30))
        except (TypeError, ValueError):
            timeout = 30
        self._timeout.setValue(max(1, min(3600, timeout)))
        self._follow.setChecked(bool(data.get("follow_redirects", True)))
        self._verify.setChecked(bool(data.get("verify_tls", True)))
        self._set_entries(self._params, data.get("params"))
        self._set_entries(self._http_headers, data.get("headers"))
        self._set_entries(self._path_params, data.get("path_params"))
        self._set_entries(self._request_cookies, data.get("cookies"))
        body_type = str(data.get("body_type") or "none")
        legacy_types = {
            "无": "none",
            "JSON": "raw",
            "Text": "raw",
            "XML": "raw",
            "Form": "urlencoded",
        }
        body_type = legacy_types.get(body_type, body_type)
        self._set_body_type(body_type)
        legacy_raw = str(data.get("body_type") or "")
        self._raw_format.setCurrentText(
            str(data.get("raw_format")
                or ("JSON" if legacy_raw == "JSON"
                    else "XML" if legacy_raw == "XML" else "Text")))
        self._body.setPlainText(str(data.get("body") or ""))
        self._auth_type.setCurrentText(str(data.get("auth_type") or "无"))
        self._auth_user.setText(str(data.get("auth_user") or ""))
        self._auth_password.setText(
            str(data.get("auth_password") or ""))
        self._auth_token.setText(
            str(data.get("auth_token") or ""))
        self._response_example.setPlainText(
            str(data.get("response_example") or ""))

    @staticmethod
    def _set_entries(table, items):
        table.setRowCount(0)
        for item in items or []:
            if isinstance(item, dict):
                _add_pair_row(
                    table,
                    item.get("name", ""),
                    item.get("value", ""),
                    item.get("description", ""),
                    bool(item.get("enabled", True)),
                )

    def cleanup(self):
        self._poll_timer.stop()
        self._toast_timer.stop()
        self._http_toast.hide()
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.stop()
