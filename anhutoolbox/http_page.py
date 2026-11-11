# -*- coding: utf-8 -*-
"""APIpost 风格的 HTTP 请求与响应工作区。"""

import base64
import json
import mimetypes
import os
import re
import secrets
import urllib.parse
from http.cookies import SimpleCookie

import msgpack
from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QFileDialog,
    QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QRadioButton, QSpinBox,
    QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout,
    QWidget,
)

from .dialogs import show_error, show_information, show_warning
from .panels import parse_hex_bytes
from .protocol_workers import HTTPRequestWorker
from .table_actions import checked_row_indexes, install_select_all_header


_HEADER_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")


def _table(headers):
    headers = list(headers)
    has_checkbox_column = bool(headers and headers[0] == "启用")
    if has_checkbox_column:
        headers[0] = ""
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.verticalHeader().setVisible(False)
    widget.verticalHeader().setDefaultSectionSize(38)
    widget.verticalHeader().setMinimumSectionSize(38)
    widget.setAlternatingRowColors(True)
    widget.setSelectionBehavior(QTableWidget.SelectRows)
    widget.setShowGrid(False)
    if has_checkbox_column:
        install_select_all_header(widget)
    widget.horizontalHeader().setStretchLastSection(True)
    widget.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
    widget.setFont(QFont("Microsoft YaHei UI", 11))
    widget.horizontalHeader().setFont(
        QFont("Microsoft YaHei UI", 9, QFont.Weight.Bold))
    widget.setStyleSheet(
        "QTableWidget{background:#FFFFFF;alternate-background-color:#FAFAFA;"
        "border:1px solid #C5CBD3;selection-background-color:#E8F0FE;"
        "selection-color:#1A1A1A;font-family:'Microsoft YaHei UI';"
        "font-size:11pt;}"
        "QTableWidget::item{padding:5px 7px;border:none;}"
        "QTableWidget::item:selected{background:#E8F0FE;color:#1A1A1A;}"
        "QHeaderView::section{background:#FAFAFA;color:#666666;"
        "border:1px solid #C5CBD3;padding:5px 7px;"
        "font-family:'Microsoft YaHei UI';font-size:9pt;font-weight:600;}"
        "QHeaderView::section:hover{background:#F0F0F0;color:#1A1A1A;"
        "border-color:#0078D4;}"
    )
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


def _remove_rows(table):
    rows = sorted(checked_row_indexes(table), reverse=True)
    if not rows:
        show_information(
            table.window(), "删除选中",
            "请先勾选需要删除的行。")
        return
    for row in rows:
        table.removeRow(row)


class HTTPPage(QWidget):
    request_status = Signal(str)
    save_requested = Signal()

    def __init__(self):
        super().__init__()
        self._worker = None
        self._last_request = {}
        self._last_result = {}
        self._raw_response = ""
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(20)
        self._poll_timer.timeout.connect(self._poll_request)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)
        self.setStyleSheet(
            "QTabWidget::pane{border:1px solid #D8DCE2;background:#FFFFFF;}"
            "QTabBar::tab{background:transparent;color:#5F6670;border:none;"
            "padding:8px 14px;font-size:13px;font-weight:400;}"
            "QTabBar::tab:selected{color:#0078D4;"
            "border-bottom:2px solid #0078D4;}"
            "QTabBar::tab:hover{color:#0078D4;background:#F3F7FC;}"
            "QPushButton#httpSend{background:#0078D4;color:#FFFFFF;"
            "border:1px solid #0078D4;border-radius:4px;padding:7px 22px;"
            "font-weight:600;}"
            "QPushButton#httpSend:hover{background:#106EBE;}"
            "QPushButton#httpSend:disabled{background:#B7C7D8;"
            "border-color:#B7C7D8;color:#FFFFFF;}"
            "QPushButton#httpSave{background:#FFFFFF;color:#374151;"
            "border:1px solid #CDD3DC;border-radius:4px;padding:7px 17px;}"
            "QPushButton#httpSave:hover{background:#F5F8FC;border-color:#0078D4;}"
            "QPushButton#httpDeleteRows{background:#D13438;color:#FFFFFF;"
            "border:1px solid #B52A2E;border-radius:3px;padding:4px 12px;}"
            "QPushButton#httpDeleteRows:hover{background:#A80000;"
            "border-color:#8A0000;}"
            "QLabel#httpChip{border-radius:10px;padding:3px 9px;"
            "font-size:12px;font-weight:600;}"
        )

        request_bar = QHBoxLayout()
        request_bar.setSpacing(6)
        self._method = QComboBox()
        self._method.addItems([
            "GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
        self._method.setMinimumWidth(100)
        request_bar.addWidget(self._method)

        self._url = QLineEdit()
        self._url.setPlaceholderText("http://127.0.0.1:5000/api/path")
        self._url.returnPressed.connect(self._send)
        request_bar.addWidget(self._url, 1)

        self._http_version = QComboBox()
        self._http_version.addItems(["HTTP/1.1"])
        self._http_version.setMinimumWidth(96)
        request_bar.addWidget(self._http_version)

        self._btn_send = QPushButton("发送")
        self._btn_send.setObjectName("httpSend")
        self._btn_send.setMinimumWidth(86)
        self._btn_send.clicked.connect(self._send)
        request_bar.addWidget(self._btn_send)

        self._btn_save = QPushButton("保存")
        self._btn_save.setObjectName("httpSave")
        self._btn_save.setMinimumWidth(78)
        self._btn_save.clicked.connect(self.save_requested.emit)
        request_bar.addWidget(self._btn_save)
        root.addLayout(request_bar)

        options = QHBoxLayout()
        options.setSpacing(8)
        options.addWidget(QLabel("超时(秒)"))
        self._timeout = QSpinBox()
        self._timeout.setRange(1, 3600)
        self._timeout.setValue(30)
        options.addWidget(self._timeout)
        self._follow = QCheckBox("跟随重定向")
        self._follow.setChecked(True)
        options.addWidget(self._follow)
        self._verify = QCheckBox("校验证书")
        self._verify.setChecked(True)
        options.addWidget(self._verify)
        options.addStretch()
        root.addLayout(options)

        split = QSplitter(Qt.Vertical)
        split.setChildrenCollapsible(False)

        request_page = QWidget()
        request_lo = QVBoxLayout(request_page)
        request_lo.setContentsMargins(0, 0, 0, 0)
        request_lo.setSpacing(4)
        self._request_tabs = QTabWidget()
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
        response_lo = QVBoxLayout(response_page)
        response_lo.setContentsMargins(0, 0, 0, 0)
        response_lo.setSpacing(4)

        response_info = QHBoxLayout()
        response_info.setSpacing(8)
        response_info.addWidget(QLabel("响应"))
        response_info.addStretch()
        self._status = self._chip("等待请求", "#6B7280", "#EEF1F5")
        self._elapsed = self._chip("— ms", "#5F6670", "#F1F3F6")
        self._size = self._chip("— B", "#5F6670", "#F1F3F6")
        response_info.addWidget(self._status)
        response_info.addWidget(self._elapsed)
        response_info.addWidget(self._size)
        response_lo.addLayout(response_info)

        self._response_tabs = QTabWidget()
        self._response_tabs.setDocumentMode(True)
        body_page = QWidget()
        body_lo = QVBoxLayout(body_page)
        body_lo.setContentsMargins(0, 0, 0, 0)
        body_lo.setSpacing(4)

        body_toolbar = QHBoxLayout()
        self._btn_pretty = QPushButton("美化")
        self._btn_pretty.clicked.connect(self._pretty_response)
        self._btn_raw = QPushButton("原始")
        self._btn_raw.clicked.connect(self._show_raw_response)
        body_toolbar.addWidget(self._btn_pretty)
        body_toolbar.addWidget(self._btn_raw)
        self._response_format = QComboBox()
        self._response_format.addItems(["JSON", "Text", "XML"])
        body_toolbar.addWidget(self._response_format)
        self._encoding = QComboBox()
        self._encoding.addItems(["UTF-8", "GBK", "Latin-1"])
        body_toolbar.addWidget(self._encoding)
        body_toolbar.addStretch()
        self._btn_copy = QPushButton("复制")
        self._btn_copy.clicked.connect(self._copy_response)
        body_toolbar.addWidget(self._btn_copy)
        self._btn_save_response = QPushButton("保存响应")
        self._btn_save_response.clicked.connect(self._save_response)
        body_toolbar.addWidget(self._btn_save_response)
        self._btn_save_example = QPushButton("存为示例")
        self._btn_save_example.clicked.connect(self._save_response_example)
        body_toolbar.addWidget(self._btn_save_example)
        body_lo.addLayout(body_toolbar)

        self._response_body = QPlainTextEdit()
        self._response_body.setReadOnly(True)
        self._response_body.setFont(QFont("Consolas", 10))
        self._response_body.setPlaceholderText("响应内容")
        body_lo.addWidget(self._response_body, 1)
        self._response_tabs.addTab(body_page, "实时响应")

        self._response_headers = _table(["响应头", "值"])
        self._response_tabs.addTab(self._response_headers, "响应头")
        self._response_cookies = _table([
            "Name", "Value", "Domain", "Path", "Expires",
            "HttpOnly", "Secure",
        ])
        self._response_tabs.addTab(self._response_cookies, "Cookie")

        self._response_example = QPlainTextEdit()
        self._response_example.setReadOnly(True)
        self._response_example.setFont(QFont("Consolas", 10))
        self._response_example.setPlaceholderText(
            "暂无响应示例。收到响应后可点击“存为示例”。")
        self._response_tabs.addTab(self._response_example, "响应示例")

        self._build_actual_request_tab()
        self._console = QPlainTextEdit()
        self._console.setReadOnly(True)
        self._console.setFont(QFont("Consolas", 10))
        self._console.setPlaceholderText(
            "控制台显示请求准备、完成耗时和错误信息。\n"
            "当前版本不执行请求脚本。")
        self._response_tabs.addTab(self._console, "控制台")

        response_lo.addWidget(self._response_tabs)
        split.addWidget(response_page)
        split.setSizes([340, 330])
        root.addWidget(split, 1)

    def _make_pair_tab(self, title, headers):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        row = QHBoxLayout()
        add = QPushButton("+ 添加一行")
        remove = QPushButton("删除选中")
        remove.setObjectName("httpDeleteRows")
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch()
        layout.addLayout(row)
        table = _table(headers)
        table.setColumnWidth(0, 48)
        table.setColumnWidth(1, 190)
        table.setColumnWidth(2, 260)
        layout.addWidget(table, 1)
        remove.clicked.connect(lambda: _remove_rows(table))
        add.clicked.connect(lambda: _add_pair_row(table))
        self._request_tabs.addTab(page, title)
        return table

    def _build_body_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        toolbar = QHBoxLayout()
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
        self._body_hint.setStyleSheet("color:#7A8490;font-size:12px;")
        toolbar.addWidget(self._body_hint)
        toolbar.addStretch()
        self._btn_body_pretty = QPushButton("格式化 JSON")
        self._btn_body_pretty.clicked.connect(self._pretty_request_body)
        toolbar.addWidget(self._btn_body_pretty)
        self._btn_body_pretty.setVisible(False)
        self._raw_format = QComboBox()
        self._raw_format.addItems(["JSON", "XML", "Text"])
        self._raw_format.setVisible(False)
        toolbar.addWidget(self._raw_format)
        self._btn_load_binary = QPushButton("选择文件")
        self._btn_load_binary.clicked.connect(self._load_binary_file)
        self._btn_load_binary.setVisible(False)
        toolbar.addWidget(self._btn_load_binary)
        layout.addLayout(toolbar)
        self._body = QPlainTextEdit()
        self._body.setFont(QFont("Consolas", 10))
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
        layout.setContentsMargins(8, 8, 8, 8)
        row = QHBoxLayout()
        row.addWidget(QLabel("认证方式"))
        self._auth_type = QComboBox()
        self._auth_type.addItems(["无", "Bearer", "Basic"])
        row.addWidget(self._auth_type)
        row.addStretch()
        layout.addLayout(row)
        self._auth_user = QLineEdit()
        self._auth_user.setPlaceholderText("Basic 用户名")
        self._auth_password = QLineEdit()
        self._auth_password.setEchoMode(QLineEdit.Password)
        self._auth_password.setPlaceholderText("Basic 密码")
        self._auth_token = QLineEdit()
        self._auth_token.setEchoMode(QLineEdit.Password)
        self._auth_token.setPlaceholderText("Bearer Token")
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

    def _request_body(self, content_type):
        body_type = self._body_type()
        raw = self._body.toPlainText()
        if body_type == "none":
            return None
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
        url = self._url.text().strip()
        if not url:
            show_warning(self, "提示", "请输入请求 URL。")
            return
        for name, value in _enabled_pairs(self._path_params):
            url = url.replace(
                "{" + name + "}", urllib.parse.quote(value, safe=""))

        try:
            headers = self._build_headers()
        except ValueError as exc:
            show_warning(self, "请求 Header 错误", str(exc))
            return
        cookie_header = "; ".join(
            "{}={}".format(name, value)
            for name, value in _enabled_pairs(self._request_cookies))
        if cookie_header:
            headers.setdefault("Cookie", cookie_header)

        try:
            content = self._request_body(headers)
            params = _enabled_pairs(self._params)
        except (ValueError, json.JSONDecodeError) as exc:
            show_warning(self, "请求内容错误", str(exc))
            return

        request = {
            "method": self._method.currentText(),
            "url": url,
            "params": params,
            "path_params": _enabled_pairs(self._path_params),
            "headers": headers,
            "content": content,
            "timeout": self._timeout.value(),
            "follow_redirects": self._follow.isChecked(),
            "verify_tls": self._verify.isChecked(),
        }
        self._last_request = request
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
        if kind == "ok":
            self._on_finished(payload)
        else:
            self._on_failed(payload)

    def _build_headers(self):
        headers = {}
        for name, value in _enabled_pairs(self._http_headers):
            name = name.strip()
            value = value.strip()
            if not _HEADER_NAME.fullmatch(name):
                raise ValueError("Header 名称不合法：{}".format(name))
            if any(char in value for char in ("\r", "\n", "\x00")):
                raise ValueError("Header 值不能包含换行或控制字符：{}".format(name))
            headers[name] = value

        auth_type = self._auth_type.currentText()
        if auth_type == "Bearer":
            token = self._auth_token.text().strip()
            if not token:
                self._request_tabs.setCurrentWidget(self._auth_page)
                raise ValueError("已选择 Bearer 认证，请输入 Bearer Token")
            headers["Authorization"] = "Bearer " + token
        elif auth_type == "Basic":
            username = self._auth_user.text().strip()
            password = self._auth_password.text()
            if not username and not password:
                self._request_tabs.setCurrentWidget(self._auth_page)
                raise ValueError("已选择 Basic 认证，请输入用户名和密码")
            token = base64.b64encode(
                "{}:{}".format(username, password).encode("utf-8")
            ).decode("ascii")
            headers["Authorization"] = "Basic " + token
        return headers

    def _build_actual_request_tab(self):
        page = QWidget()
        self._actual_request_page = page
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
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
        url_row.addWidget(self._actual_url, 1)
        layout.addLayout(url_row)
        layout.addWidget(QLabel("请求参数"))
        self._actual_tabs = QTabWidget()
        self._actual_headers = _table(["参数名", "参数值"])
        self._actual_tabs.addTab(self._actual_headers, "Header")
        self._actual_query = _table(["参数名", "参数值"])
        self._actual_tabs.addTab(self._actual_query, "Query")
        self._actual_path = _table(["参数名", "参数值"])
        self._actual_tabs.addTab(self._actual_path, "Path")
        self._actual_body = QPlainTextEdit()
        self._actual_body.setReadOnly(True)
        self._actual_body.setFont(QFont("Consolas", 10))
        self._actual_tabs.addTab(self._actual_body, "Body")
        layout.addWidget(self._actual_tabs, 1)
        self._response_tabs.addTab(page, "实际请求")

    def _format_request(self, request):
        lines = ["{} {} {}".format(
            request["method"], request["url"], "HTTP/1.1")]
        for name, value in request["headers"].items():
            lines.append("{}: {}".format(name, value))
        lines.append("")
        content = request.get("content")
        if content:
            lines.append(bytes(content).decode("utf-8", errors="replace"))
        return "\n".join(lines)

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
        self._status.setText("请求失败")
        self._status.setStyleSheet(
            "QLabel#httpChip{color:#A4262C;background:#FDECEA;"
            "border-radius:10px;padding:3px 9px;font-size:12px;"
            "font-weight:600;}")
        self._response_body.setPlainText(message)
        self._raw_response = message
        self._console.appendPlainText("!!! " + message)
        self.request_status.emit("HTTP 请求失败")
        show_error(self, "HTTP 请求失败", message)

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
            for morsel in jar.values():
                entries.append({
                    "name": morsel.key,
                    "value": morsel.value,
                    "domain": morsel["domain"],
                    "path": morsel["path"],
                    "expires": morsel["expires"],
                    "httponly": bool(morsel["httponly"]),
                    "secure": bool(morsel["secure"]),
                })
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
        if "json" in content_type or text.lstrip().startswith(("{", "[")):
            try:
                text = json.dumps(
                    json.loads(text), ensure_ascii=False, indent=2)
            except Exception:
                pass
        if truncated:
            text += "\n\n[响应超过 2 MB，界面仅显示前 2 MB]"
        self._response_body.setPlainText(text)

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

    def _show_raw_response(self):
        self._response_body.setPlainText(self._raw_response)
        self._response_tabs.setCurrentIndex(0)

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

    def snapshot(self):
        return {
            "method": self._method.currentText(),
            "url": self._url.text(),
            "timeout": self._timeout.value(),
            "follow_redirects": self._follow.isChecked(),
            "verify_tls": self._verify.isChecked(),
            "http_version": self._http_version.currentText(),
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

    def apply(self, data):
        data = data if isinstance(data, dict) else {}
        self._method.setCurrentText(str(data.get("method") or "GET"))
        self._url.setText(str(data.get("url") or ""))
        self._http_version.setCurrentText(
            str(data.get("http_version") or "HTTP/1.1"))
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
        self._auth_password.clear()
        self._auth_token.clear()
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
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.stop()
