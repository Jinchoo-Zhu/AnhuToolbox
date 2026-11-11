# -*- coding: utf-8 -*-
"""通信调试页中的 MQTT、HTTP、WebSocket 协议工作区。"""

import base64
import json
import time
import urllib.parse
from datetime import datetime

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSpinBox, QSplitter,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from .dialogs import show_error, show_information, show_warning
from .panels import parse_hex_bytes
from .protocol_workers import HTTPRequestWorker
from .table_actions import checked_row_indexes, install_select_all_header


def _new_table(headers):
    headers = list(headers)
    has_checkbox_column = bool(headers and headers[0] == "启用")
    if has_checkbox_column:
        headers[0] = ""
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.setSelectionBehavior(QTableWidget.SelectRows)
    table.setAlternatingRowColors(True)
    if has_checkbox_column:
        install_select_all_header(table)
    table.horizontalHeader().setStretchLastSection(True)
    return table


def _protocol_group(title):
    group = QGroupBox(title)
    group.setStyleSheet(
        "QGroupBox{margin-top:24px;padding:12px 8px 8px 8px;"
        "border:1px solid #D0D0D0;border-radius:6px;background:#FAFAFA;"
        "font-weight:600;color:#1A1A1A;}"
        "QGroupBox::title{subcontrol-origin:margin;left:10px;"
        "top:4px;padding:4px 6px;color:#1A1A1A;font-size:13px;}"
    )
    return group


def _table_add_row(table, values, checked=False):
    row = table.rowCount()
    table.insertRow(row)
    check_column = table.property("checkboxColumn")
    if check_column is not None:
        item = QTableWidgetItem()
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(
            Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        table.setItem(row, check_column, item)
        offset = check_column + 1
    else:
        offset = 0
    for index, value in enumerate(values, offset):
        table.setItem(row, index, QTableWidgetItem(str(value)))
    return row


def _table_pairs(table):
    pairs = []
    check_column = table.property("checkboxColumn")
    for row in range(table.rowCount()):
        if check_column is not None:
            enabled_item = table.item(row, check_column)
            if enabled_item is not None and \
                    enabled_item.checkState() != Qt.CheckState.Checked:
                continue
            offset = check_column + 1
        else:
            offset = 0
        key_item = table.item(row, offset)
        value_item = table.item(row, offset + 1)
        key = key_item.text().strip() if key_item else ""
        value = value_item.text() if value_item else ""
        if key:
            pairs.append((key, value))
    return pairs


class MQTTPage(QWidget):
    subscription_changed = Signal(object)
    publish_requested = Signal(dict)

    def __init__(self):
        super().__init__()
        self._connected = False
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        header = QHBoxLayout()
        self._state = QLabel("未连接")
        self._state.setStyleSheet(
            "color:#D83B01;font-size:13px;font-weight:600;")
        header.addWidget(self._state)
        header.addStretch()
        self._btn_clear = QPushButton("清空消息")
        self._btn_clear.clicked.connect(self.clear_messages)
        header.addWidget(self._btn_clear)
        root.addLayout(header)

        split = QSplitter(Qt.Vertical)

        messages = _protocol_group("消息")
        ml = QVBoxLayout(messages)
        self._messages = _new_table([
            "时间", "方向", "Topic", "QoS", "Retain", "大小", "Payload"])
        self._messages.setColumnWidth(0, 88)
        self._messages.setColumnWidth(1, 52)
        self._messages.setColumnWidth(2, 190)
        self._messages.setColumnWidth(3, 44)
        self._messages.setColumnWidth(4, 54)
        self._messages.setColumnWidth(5, 60)
        ml.addWidget(self._messages)
        split.addWidget(messages)

        subscriptions = _protocol_group("订阅")
        sl = QVBoxLayout(subscriptions)
        row = QHBoxLayout()
        self._sub_topic = QLineEdit()
        self._sub_topic.setPlaceholderText("Topic，例如 device/+/status")
        row.addWidget(self._sub_topic, 1)
        self._sub_qos = QComboBox()
        self._sub_qos.addItems(["QoS 0", "QoS 1", "QoS 2"])
        row.addWidget(self._sub_qos)
        self._btn_subscribe = QPushButton("添加订阅")
        self._btn_subscribe.clicked.connect(self._add_subscription)
        row.addWidget(self._btn_subscribe)
        self._btn_unsubscribe = QPushButton("删除选中")
        self._btn_unsubscribe.clicked.connect(self._remove_subscription)
        row.addWidget(self._btn_unsubscribe)
        sl.addLayout(row)
        self._subscriptions = _new_table(["Topic", "QoS"])
        self._subscriptions.setColumnWidth(0, 360)
        self._subscriptions.setColumnWidth(1, 60)
        sl.addWidget(self._subscriptions)
        split.addWidget(subscriptions)
        split.setSizes([360, 150])
        root.addWidget(split, 1)

        publish = _protocol_group("发布")
        pl = QVBoxLayout(publish)
        prow = QHBoxLayout()
        self._pub_topic = QLineEdit()
        self._pub_topic.setPlaceholderText("发布 Topic")
        prow.addWidget(self._pub_topic, 1)
        self._pub_qos = QComboBox()
        self._pub_qos.addItems(["QoS 0", "QoS 1", "QoS 2"])
        prow.addWidget(self._pub_qos)
        self._pub_retain = QCheckBox("Retain")
        prow.addWidget(self._pub_retain)
        self._pub_format = QComboBox()
        self._pub_format.addItems(["文本", "HEX", "JSON"])
        prow.addWidget(self._pub_format)
        pl.addLayout(prow)
        body_row = QHBoxLayout()
        self._pub_payload = QPlainTextEdit()
        self._pub_payload.setMaximumHeight(72)
        self._pub_payload.setPlaceholderText("消息内容")
        self._pub_payload.setFont(QFont("Consolas", 10))
        body_row.addWidget(self._pub_payload, 1)
        self._btn_publish = QPushButton("发布")
        self._btn_publish.setMinimumSize(80, 60)
        self._btn_publish.clicked.connect(self._publish)
        body_row.addWidget(self._btn_publish)
        pl.addLayout(body_row)
        root.addWidget(publish)
        self.set_connected(False)

    def set_connected(self, connected):
        self._connected = bool(connected)
        self._state.setText("已连接" if connected else "未连接")
        self._state.setStyleSheet(
            "color:{};font-size:13px;font-weight:600;".format(
                "#107C10" if connected else "#D83B01"))
        for widget in (
                self._btn_subscribe, self._btn_unsubscribe,
                self._btn_publish):
            widget.setEnabled(connected)

    def append_message(self, message):
        payload = bytes(message.get("payload") or b"")
        text = message.get("text")
        if text is None:
            preview = payload.hex(" ").upper()
        else:
            preview = str(text).replace("\r", "\\r").replace("\n", "\\n")
        if len(preview) > 180:
            preview = preview[:177] + "..."
        row = self._messages.rowCount()
        self._messages.insertRow(row)
        values = [
            datetime.fromtimestamp(
                float(message.get("timestamp") or time.time())).strftime(
                    "%H:%M:%S.%f")[:-3],
            str(message.get("direction") or "RX").upper(),
            str(message.get("topic") or ""),
            str(message.get("qos", 0)),
            "是" if message.get("retain") else "否",
            str(len(payload)),
            preview,
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if column == 6:
                item.setToolTip(str(text if text is not None
                                    else payload.hex(" ").upper()))
            self._messages.setItem(row, column, item)
        self._messages.scrollToBottom()

    def add_subscription(self, topic, qos=0, notify=False):
        topic = str(topic or "").strip()
        if not topic:
            return False
        for row in range(self._subscriptions.rowCount()):
            if self._subscriptions.item(row, 0).text() == topic:
                return True
        row = self._subscriptions.rowCount()
        self._subscriptions.insertRow(row)
        self._subscriptions.setItem(row, 0, QTableWidgetItem(topic))
        self._subscriptions.setItem(row, 1, QTableWidgetItem(str(int(qos))))
        if notify:
            self.subscription_changed.emit(self.subscriptions())
        return True

    def _add_subscription(self):
        topic = self._sub_topic.text().strip()
        if not topic:
            show_warning(self, "提示", "请输入订阅 Topic。")
            return
        qos = self._sub_qos.currentIndex()
        if self.add_subscription(topic, qos, notify=True):
            self._sub_topic.clear()

    def _remove_subscription(self):
        rows = sorted({
            index.row() for index in self._subscriptions.selectedIndexes()},
            reverse=True)
        for row in rows:
            self._subscriptions.removeRow(row)
        if rows:
            self.subscription_changed.emit(self.subscriptions())

    def subscriptions(self):
        return [
            {
                "topic": self._subscriptions.item(row, 0).text(),
                "qos": int(self._subscriptions.item(row, 1).text()),
            }
            for row in range(self._subscriptions.rowCount())
            if self._subscriptions.item(row, 0)
            and self._subscriptions.item(row, 0).text().strip()
        ]

    def set_subscriptions(self, items):
        self._subscriptions.setRowCount(0)
        for item in items or []:
            if isinstance(item, dict):
                self.add_subscription(
                    item.get("topic", ""), item.get("qos", 0), notify=False)

    def _publish(self):
        topic = self._pub_topic.text().strip()
        raw = self._pub_payload.toPlainText()
        if not topic:
            show_warning(self, "提示", "请输入发布 Topic。")
            return
        try:
            mode = self._pub_format.currentText()
            if mode == "HEX":
                payload = parse_hex_bytes(raw)
            else:
                payload = raw.encode("utf-8")
                if mode == "JSON" and raw.strip():
                    json.loads(raw)
        except (ValueError, json.JSONDecodeError) as exc:
            show_warning(self, "消息格式错误", str(exc))
            return
        self.publish_requested.emit({
            "topic": topic,
            "payload": payload,
            "qos": self._pub_qos.currentIndex(),
            "retain": self._pub_retain.isChecked(),
        })

    def record_publish(self, message):
        self.append_message(message)

    def clear_messages(self):
        self._messages.setRowCount(0)

    def snapshot(self):
        return {
            "subscriptions": self.subscriptions(),
            "publish_topic": self._pub_topic.text(),
            "publish_qos": self._pub_qos.currentIndex(),
            "publish_retain": self._pub_retain.isChecked(),
            "publish_format": self._pub_format.currentText(),
            "publish_payload": self._pub_payload.toPlainText(),
        }

    def apply(self, data):
        data = data if isinstance(data, dict) else {}
        self.set_subscriptions(data.get("subscriptions") or [])
        self._pub_topic.setText(str(data.get("publish_topic") or ""))
        try:
            publish_qos = int(data.get("publish_qos", 0))
        except (TypeError, ValueError):
            publish_qos = 0
        self._pub_qos.setCurrentIndex(max(0, min(2, publish_qos)))
        self._pub_retain.setChecked(bool(data.get("publish_retain", False)))
        self._pub_format.setCurrentText(
            str(data.get("publish_format") or "文本"))
        self._pub_payload.setPlainText(
            str(data.get("publish_payload") or ""))


class WebSocketPage(QWidget):
    send_requested = Signal(dict)
    ping_requested = Signal()
    connect_requested = Signal()
    disconnect_requested = Signal()

    def __init__(self):
        super().__init__()
        self._connected = False
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)
        self.setStyleSheet(
            "QPushButton#wsConnect{background:#0078D4;color:#FFFFFF;"
            "border:1px solid #0078D4;border-radius:4px;padding:6px 14px;"
            "font-weight:600;}"
            "QPushButton#wsConnect:hover{background:#106EBE;}"
            "QPushButton#wsConnect[connected=\"true\"]{"
            "background:#D13438;border-color:#B52A2E;}"
            "QPushButton#wsConnect[connected=\"true\"]:hover{"
            "background:#A80000;border-color:#8A0000;}"
        )

        top = QHBoxLayout()
        self._url = QLineEdit()
        self._url.setPlaceholderText("ws://127.0.0.1:8080/ws")
        self._url.setClearButtonEnabled(True)
        self._url.returnPressed.connect(self._toggle_connection)
        top.addWidget(self._url, 1)
        self._btn_connect = QPushButton("连接 WebSocket")
        self._btn_connect.setObjectName("wsConnect")
        self._btn_connect.setMinimumWidth(136)
        self._btn_connect.clicked.connect(self._toggle_connection)
        top.addWidget(self._btn_connect)
        self._btn_ping = QPushButton("发送 Ping")
        self._btn_ping.clicked.connect(self.ping_requested.emit)
        top.addWidget(self._btn_ping)
        self._btn_clear = QPushButton("清空消息")
        self._btn_clear.clicked.connect(self.clear_messages)
        top.addWidget(self._btn_clear)
        root.addLayout(top)

        headers_group = _protocol_group("连接请求头")
        hl = QVBoxLayout(headers_group)
        hrow = QHBoxLayout()
        self._btn_add_header = QPushButton("+ 添加 Header")
        self._btn_add_header.clicked.connect(
            lambda: _table_add_row(self._headers, ["", ""], True))
        hrow.addWidget(self._btn_add_header)
        self._btn_remove_header = QPushButton("删除选中")
        self._btn_remove_header.clicked.connect(
            lambda: self._remove_checked_rows(self._headers))
        hrow.addWidget(self._btn_remove_header)
        hrow.addStretch()
        hl.addLayout(hrow)
        self._headers = _new_table(["启用", "Header", "值"])
        self._headers.setColumnWidth(0, 48)
        self._headers.setMaximumHeight(120)
        hl.addWidget(self._headers)
        root.addWidget(headers_group)

        self._messages = _new_table([
            "时间", "方向", "类型", "大小", "内容"])
        self._messages.setColumnWidth(0, 90)
        self._messages.setColumnWidth(1, 52)
        self._messages.setColumnWidth(2, 65)
        self._messages.setColumnWidth(3, 60)
        root.addWidget(self._messages, 1)

        composer = _protocol_group("发送消息")
        cl = QVBoxLayout(composer)
        row = QHBoxLayout()
        self._format = QComboBox()
        self._format.addItems(["文本", "JSON", "HEX/二进制"])
        row.addWidget(self._format)
        row.addStretch()
        self._btn_send = QPushButton("发送")
        self._btn_send.clicked.connect(self._send)
        row.addWidget(self._btn_send)
        cl.addLayout(row)
        self._payload = QPlainTextEdit()
        self._payload.setMaximumHeight(72)
        self._payload.setFont(QFont("Consolas", 10))
        self._payload.setPlaceholderText("输入 WebSocket 消息")
        cl.addWidget(self._payload)
        root.addWidget(composer)
        self.set_connected(False)

    def _toggle_connection(self):
        if self._connected:
            self.disconnect_requested.emit()
        else:
            self.connect_requested.emit()

    @staticmethod
    def _remove_checked_rows(table):
        rows = sorted(checked_row_indexes(table), reverse=True)
        if not rows:
            show_information(
                table.window(), "删除选中",
                "请先勾选需要删除的 Header。")
            return
        for row in rows:
            table.removeRow(row)

    def set_connected(self, connected):
        self._connected = bool(connected)
        self._btn_connect.setText(
            "断开 WebSocket" if connected else "连接 WebSocket")
        self._btn_connect.setProperty(
            "connected", "true" if connected else "false")
        self._btn_connect.style().unpolish(self._btn_connect)
        self._btn_connect.style().polish(self._btn_connect)
        self._url.setEnabled(not connected)
        self._btn_send.setEnabled(connected)
        self._btn_ping.setEnabled(connected)

    def append_message(self, message):
        payload = bytes(message.get("payload") or b"")
        binary = bool(message.get("binary"))
        text = message.get("text")
        preview = (
            text if text is not None and not binary
            else payload.hex(" ").upper())
        preview = str(preview).replace("\r", "\\r").replace("\n", "\\n")
        if len(preview) > 220:
            preview = preview[:217] + "..."
        row = self._messages.rowCount()
        self._messages.insertRow(row)
        values = [
            datetime.fromtimestamp(
                float(message.get("timestamp") or time.time())).strftime(
                    "%H:%M:%S.%f")[:-3],
            str(message.get("direction") or "rx").upper(),
            "Binary" if binary else "Text",
            str(len(payload)),
            preview,
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if column == 4:
                item.setToolTip(str(
                    text if text is not None and not binary
                    else payload.hex(" ").upper()))
            self._messages.setItem(row, column, item)
        self._messages.scrollToBottom()

    def _send(self):
        mode = self._format.currentText()
        raw = self._payload.toPlainText()
        try:
            if mode == "HEX/二进制":
                payload = parse_hex_bytes(raw)
                binary = True
            else:
                payload = raw.encode("utf-8")
                binary = False
                if mode == "JSON" and raw.strip():
                    json.loads(raw)
        except (ValueError, json.JSONDecodeError) as exc:
            show_warning(self, "消息格式错误", str(exc))
            return
        self.send_requested.emit({
            "payload": payload,
            "binary": binary,
            "text": None if binary else raw,
        })

    def record_sent(self, message):
        self.append_message(message)

    def url(self):
        return self._url.text().strip()

    def set_url(self, url):
        self._url.setText(str(url or ""))

    def headers(self):
        return _table_pairs(self._headers)

    def set_headers(self, items):
        self._headers.setRowCount(0)
        for item in items or []:
            if isinstance(item, dict):
                _table_add_row(
                    self._headers,
                    [item.get("name", ""), item.get("value", "")],
                    bool(item.get("enabled", True)),
                )

    def clear_messages(self):
        self._messages.setRowCount(0)

    def snapshot(self):
        return {
            "url": self.url(),
            "headers": [
                {"name": key, "value": value, "enabled": True}
                for key, value in self.headers()
            ],
            "send_format": self._format.currentText(),
            "payload": self._payload.toPlainText(),
        }

    def apply(self, data):
        data = data if isinstance(data, dict) else {}
        self.set_url(data.get("url"))
        self.set_headers(data.get("headers") or [])
        self._format.setCurrentText(str(data.get("send_format") or "文本"))
        self._payload.setPlainText(str(data.get("payload") or ""))


class _LegacyHTTPPage(QWidget):
    request_status = Signal(str)

    def __init__(self):
        super().__init__()
        self._worker = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        bar = QHBoxLayout()
        self._method = QComboBox()
        self._method.addItems([
            "GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
        self._method.setMinimumWidth(90)
        bar.addWidget(self._method)
        self._url = QLineEdit()
        self._url.setPlaceholderText("https://api.example.com/path")
        self._url.returnPressed.connect(self._send)
        bar.addWidget(self._url, 1)
        self._btn_send = QPushButton("发送")
        self._btn_send.setMinimumWidth(86)
        self._btn_send.clicked.connect(self._send)
        bar.addWidget(self._btn_send)
        root.addLayout(bar)

        options = QHBoxLayout()
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
        self._status = QLabel("就绪")
        options.addWidget(self._status)
        root.addLayout(options)

        split = QSplitter(Qt.Vertical)
        request = QWidget()
        rl = QVBoxLayout(request)
        rl.setContentsMargins(0, 0, 0, 0)
        self._request_tabs = QTabWidget()
        self._params = self._make_pair_tab(
            self._request_tabs, "Params", ["启用", "参数", "值"])
        self._http_headers = self._make_pair_tab(
            self._request_tabs, "Headers", ["启用", "Header", "值"])
        self._build_body_tab()
        self._build_auth_tab()
        rl.addWidget(self._request_tabs)
        split.addWidget(request)

        response = QWidget()
        el = QVBoxLayout(response)
        el.setContentsMargins(0, 0, 0, 0)
        self._response_tabs = QTabWidget()
        self._response_body = QPlainTextEdit()
        self._response_body.setReadOnly(True)
        self._response_body.setFont(QFont("Consolas", 10))
        self._response_tabs.addTab(self._response_body, "Body")
        self._response_headers = _new_table(["Header", "值"])
        self._response_tabs.addTab(self._response_headers, "Headers")
        self._response_cookies = _new_table(["Cookie", "值"])
        self._response_tabs.addTab(self._response_cookies, "Cookies")
        self._response_history = _new_table(["状态", "URL"])
        self._response_tabs.addTab(self._response_history, "History")
        el.addWidget(self._response_tabs)
        split.addWidget(response)
        split.setSizes([320, 320])
        root.addWidget(split, 1)

    def _make_pair_tab(self, tabs, title, headers):
        page = QWidget()
        lo = QVBoxLayout(page)
        row = QHBoxLayout()
        add = QPushButton("+ 添加")
        row.addWidget(add)
        remove = QPushButton("删除选中")
        row.addWidget(remove)
        row.addStretch()
        lo.addLayout(row)
        table = _new_table(headers)
        lo.addWidget(table)
        add.clicked.connect(
            lambda: _table_add_row(table, ["", ""], True))
        remove.clicked.connect(
            lambda: self._remove_rows(table))
        tabs.addTab(page, title)
        return table

    @staticmethod
    def _remove_rows(table):
        rows = sorted(checked_row_indexes(table), reverse=True)
        if not rows:
            show_information(
                table.window(), "删除选中",
                "请先勾选需要删除的行。")
            return
        for row in rows:
            table.removeRow(row)

    def _build_body_tab(self):
        page = QWidget()
        lo = QVBoxLayout(page)
        row = QHBoxLayout()
        row.addWidget(QLabel("Body 类型"))
        self._body_type = QComboBox()
        self._body_type.addItems(["无", "JSON", "Text", "Form"])
        row.addWidget(self._body_type)
        row.addStretch()
        lo.addLayout(row)
        self._body = QPlainTextEdit()
        self._body.setFont(QFont("Consolas", 10))
        self._body.setPlaceholderText("输入请求 Body")
        lo.addWidget(self._body)
        self._request_tabs.addTab(page, "Body")

    def _build_auth_tab(self):
        page = QWidget()
        lo = QVBoxLayout(page)
        row = QHBoxLayout()
        row.addWidget(QLabel("认证"))
        self._auth_type = QComboBox()
        self._auth_type.addItems(["无", "Bearer", "Basic"])
        row.addWidget(self._auth_type)
        row.addStretch()
        lo.addLayout(row)
        self._auth_user = QLineEdit()
        self._auth_user.setPlaceholderText("Basic 用户名")
        self._auth_password = QLineEdit()
        self._auth_password.setEchoMode(QLineEdit.Password)
        self._auth_password.setPlaceholderText("Basic 密码")
        self._auth_token = QLineEdit()
        self._auth_token.setEchoMode(QLineEdit.Password)
        self._auth_token.setPlaceholderText("Bearer Token")
        lo.addWidget(self._auth_user)
        lo.addWidget(self._auth_password)
        lo.addWidget(self._auth_token)
        lo.addStretch()
        self._request_tabs.addTab(page, "Auth")

    def _send(self):
        if self._worker is not None and self._worker.isRunning():
            return
        url = self._url.text().strip()
        if not url:
            show_warning(self, "提示", "请输入请求 URL。")
            return
        headers = dict(_table_pairs(self._http_headers))
        auth_type = self._auth_type.currentText()
        if auth_type == "Bearer":
            headers["Authorization"] = "Bearer {}".format(
                self._auth_token.text())
        elif auth_type == "Basic":
            token = base64.b64encode(
                "{}:{}".format(
                    self._auth_user.text(),
                    self._auth_password.text()).encode("utf-8")).decode("ascii")
            headers["Authorization"] = "Basic {}".format(token)

        body_type = self._body_type.currentText()
        content = None
        raw = self._body.toPlainText()
        try:
            if body_type == "JSON":
                if raw.strip():
                    json.loads(raw)
                content = raw.encode("utf-8")
                headers.setdefault("Content-Type", "application/json")
            elif body_type == "Text":
                content = raw.encode("utf-8")
                headers.setdefault("Content-Type", "text/plain; charset=utf-8")
            elif body_type == "Form":
                pairs = urllib.parse.parse_qsl(
                    raw, keep_blank_values=True, strict_parsing=False)
                content = urllib.parse.urlencode(pairs).encode("utf-8")
                headers.setdefault(
                    "Content-Type", "application/x-www-form-urlencoded")
        except (ValueError, json.JSONDecodeError) as exc:
            show_warning(self, "请求 Body 格式错误", str(exc))
            return

        request = {
            "method": self._method.currentText(),
            "url": url,
            "params": _table_pairs(self._params),
            "headers": headers,
            "content": content,
            "timeout": self._timeout.value(),
            "follow_redirects": self._follow.isChecked(),
            "verify_tls": self._verify.isChecked(),
        }
        self._btn_send.setEnabled(False)
        self._status.setText("请求中...")
        self.request_status.emit("HTTP 请求中...")
        self._worker = HTTPRequestWorker()
        self._worker.configure(request)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    @Slot(dict)
    def _on_finished(self, result):
        self._btn_send.setEnabled(True)
        self._populate_response(result)
        status = "{} {} | {:.0f} ms".format(
            result["status"], result["reason"], result["elapsed_ms"])
        self._status.setText(status)
        self.request_status.emit("HTTP " + status)

    @Slot(str)
    def _on_failed(self, message):
        self._btn_send.setEnabled(True)
        self._status.setText("请求失败")
        self._response_body.setPlainText(message)
        self.request_status.emit("HTTP 请求失败")
        show_error(self, "HTTP 请求失败", message)

    def _populate_response(self, result):
        self._response_headers.setRowCount(0)
        for item in result.get("headers") or []:
            row = self._response_headers.rowCount()
            self._response_headers.insertRow(row)
            self._response_headers.setItem(
                row, 0, QTableWidgetItem(item["name"]))
            self._response_headers.setItem(
                row, 1, QTableWidgetItem(item["value"]))
        self._response_cookies.setRowCount(0)
        for item in result.get("cookies") or []:
            row = self._response_cookies.rowCount()
            self._response_cookies.insertRow(row)
            self._response_cookies.setItem(
                row, 0, QTableWidgetItem(item["name"]))
            self._response_cookies.setItem(
                row, 1, QTableWidgetItem(item["value"]))
        self._response_history.setRowCount(0)
        for item in result.get("history") or []:
            row = self._response_history.rowCount()
            self._response_history.insertRow(row)
            self._response_history.setItem(
                row, 0, QTableWidgetItem(str(item["status"])))
            self._response_history.setItem(
                row, 1, QTableWidgetItem(item["url"]))

        content = bytes(result.get("content") or b"")
        truncated = len(content) > 2 * 1024 * 1024
        if truncated:
            content = content[:2 * 1024 * 1024]
        text = content.decode("utf-8", errors="replace")
        content_type = ""
        for item in result.get("headers") or []:
            if item["name"].lower() == "content-type":
                content_type = item["value"].lower()
                break
        if "json" in content_type:
            try:
                text = json.dumps(
                    json.loads(text), ensure_ascii=False, indent=2)
            except Exception:
                pass
        if truncated:
            text += "\n\n[响应超过 2 MB，界面仅显示前 2 MB]"
        self._response_body.setPlainText(text)

    def snapshot(self):
        return {
            "method": self._method.currentText(),
            "url": self._url.text(),
            "timeout": self._timeout.value(),
            "follow_redirects": self._follow.isChecked(),
            "verify_tls": self._verify.isChecked(),
            "params": [
                {"name": key, "value": value, "enabled": True}
                for key, value in _table_pairs(self._params)
            ],
            "headers": [
                {"name": key, "value": value, "enabled": True}
                for key, value in _table_pairs(self._http_headers)
            ],
            "body_type": self._body_type.currentText(),
            "body": self._body.toPlainText(),
            "auth_type": self._auth_type.currentText(),
            "auth_user": self._auth_user.text(),
        }

    def apply(self, data):
        data = data if isinstance(data, dict) else {}
        self._method.setCurrentText(str(data.get("method") or "GET"))
        self._url.setText(str(data.get("url") or ""))
        try:
            timeout = int(data.get("timeout", 30))
        except (TypeError, ValueError):
            timeout = 30
        self._timeout.setValue(max(1, min(3600, timeout)))
        self._follow.setChecked(bool(data.get("follow_redirects", True)))
        self._verify.setChecked(bool(data.get("verify_tls", True)))
        self._set_pairs(self._params, data.get("params"))
        self._set_pairs(self._http_headers, data.get("headers"))
        self._body_type.setCurrentText(
            str(data.get("body_type") or "无"))
        self._body.setPlainText(str(data.get("body") or ""))
        self._auth_type.setCurrentText(
            str(data.get("auth_type") or "无"))
        self._auth_user.setText(str(data.get("auth_user") or ""))
        self._auth_password.clear()
        self._auth_token.clear()

    @staticmethod
    def _set_pairs(table, items):
        table.setRowCount(0)
        for item in items or []:
            if isinstance(item, dict):
                _table_add_row(
                    table,
                    [item.get("name", ""), item.get("value", "")],
                    bool(item.get("enabled", True)),
                )

    def cleanup(self):
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.stop()


# 新 HTTP 工作区单独实现，保留协议页面模块的既有导入路径。
from .http_page import HTTPPage  # noqa: E402,F401
