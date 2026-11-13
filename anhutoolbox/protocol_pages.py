# -*- coding: utf-8 -*-
"""通信调试页中的 MQTT、HTTP、WebSocket 协议工作区。"""

import base64
import html
import json
import os
import textwrap
import time
import urllib.parse
from datetime import datetime

from PySide6.QtCore import QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QSpinBox, QSplitter,
    QAbstractItemView, QTableWidget, QTableWidgetItem, QTabWidget,
    QVBoxLayout, QWidget, QSizePolicy,
)

from .dialogs import show_error, show_information, show_warning
from .log_writer import (
    AUTO_CLEAR_BYTES, AUTO_CLEAR_RECORDS, AsyncLogWriter,
)
from .panels import _save_rule_label, parse_hex_bytes
from .protocol_workers import HTTPRequestWorker
from .styles import _find_assets_dir
from .table_actions import (
    apply_data_table_style, checked_row_indexes, install_select_all_header,
)
from .ui_tokens import (
    FONT_UI, HTTP_TABLE_STYLE, PROTOCOL_WORKSPACE_STYLE, TABLE_ROW_HEIGHT,
)


def _protocol_icon(filename):
    return QIcon(os.path.join(_find_assets_dir(), filename))


def _set_button_icon(button, filename, size=16):
    icon = _protocol_icon(filename)
    if not icon.isNull():
        button.setIcon(icon)
        button.setIconSize(QSize(size, size))


def _wide_tooltip(value):
    text = str(value)
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    else:
        text = json.dumps(parsed, ensure_ascii=False, indent=2)
    lines = []
    for line in text.splitlines() or [""]:
        wrapped = textwrap.wrap(
            line,
            width=96,
            replace_whitespace=False,
            drop_whitespace=False,
            break_long_words=False,
            break_on_hyphens=False,
        )
        lines.extend(wrapped or [""])
    content = html.escape("\n".join(lines))
    return (
        '<table width="640" cellspacing="0" cellpadding="8">'
        '<tr><td style="font-family:Consolas;font-size:10pt;'
        'color:#263238;"><pre style="margin:0;">{}</pre>'
        '</td></tr></table>'.format(content)
    )


def _new_table(headers):
    headers = list(headers)
    has_checkbox_column = bool(headers and headers[0] == "启用")
    if has_checkbox_column:
        headers[0] = ""
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    if has_checkbox_column:
        install_select_all_header(table)
    apply_data_table_style(table)
    table.setFont(QFont(FONT_UI, 9))
    table.horizontalHeader().setFont(
        QFont(FONT_UI, 9, QFont.Weight.DemiBold))
    table.setStyleSheet(HTTP_TABLE_STYLE)
    table.verticalHeader().setDefaultSectionSize(TABLE_ROW_HEIGHT)
    table.verticalHeader().setMinimumSectionSize(TABLE_ROW_HEIGHT)
    table.horizontalHeader().setMinimumHeight(TABLE_ROW_HEIGHT)
    return table


def _protocol_group(title):
    group = QGroupBox(title)
    group.setObjectName("protocolGroupCard")
    return group


def _compact_protocol_panel(title, description=""):
    panel = QWidget()
    panel.setObjectName("protocolCard")
    panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(10, 8, 10, 10)
    layout.setSpacing(8)
    header_widget = QWidget()
    header_widget.setFixedHeight(20)
    header = QHBoxLayout(header_widget)
    header.setContentsMargins(0, 0, 0, 0)
    label = QLabel(title)
    label.setObjectName("protocolSectionTitle")
    header.addWidget(label)
    if description:
        header.addSpacing(8)
        description_label = QLabel(description)
        description_label.setObjectName("protocolHint")
        description_label.setWordWrap(False)
        header.addWidget(description_label)
    header.addStretch()
    layout.addWidget(header_widget)
    return panel, layout, label


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
    MAX_PAUSED_BYTES = 16 * 1024 * 1024

    def __init__(self):
        super().__init__()
        self._connected = False
        self._messages_paused = False
        self._paused_messages = []
        self._paused_bytes = 0
        self._pause_dropped_bytes = 0
        self._save_writer = None
        self._log_directory = os.getcwd()
        self._save_prefix = "mqtt"
        self._display_records = 0
        self._display_bytes = 0
        self._build()

    def _build(self):
        self.setObjectName("mqttPage")
        self.setStyleSheet(PROTOCOL_WORKSPACE_STYLE)
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        messages = QWidget()
        messages.setObjectName("protocolCard")
        messages.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._messages_container = messages
        ml = QVBoxLayout(messages)
        ml.setContentsMargins(10, 8, 10, 10)
        ml.setSpacing(8)
        message_title = QHBoxLayout()
        self._messages_title_label = QLabel("消息")
        self._messages_title_label.setObjectName("protocolSectionTitle")
        message_title.addWidget(self._messages_title_label)
        message_title.addSpacing(12)
        self.chk_pause = QCheckBox("页面暂停")
        self.chk_pause.setToolTip(
            "暂停时不刷新消息列表，继续接收的消息会在恢复后补显示")
        self.chk_pause.toggled.connect(self._on_messages_pause)
        message_title.addWidget(self.chk_pause)
        self.chk_save_file = QCheckBox("保存到文件")
        self.chk_save_file.setToolTip(
            "保存期间持续写盘；页面达到 10000 条或 300 MB 后自动清空")
        self.chk_save_file.toggled.connect(
            self._on_save_file_toggle)
        message_title.addWidget(self.chk_save_file)
        self.lbl_save_rule = _save_rule_label()
        message_title.addWidget(self.lbl_save_rule)
        message_title.addStretch()
        self._btn_clear = QPushButton("清空消息")
        _set_button_icon(self._btn_clear, "http_delete.svg")
        self._btn_clear.setFixedHeight(30)
        self._btn_clear.clicked.connect(self.clear_messages)
        message_title.addWidget(self._btn_clear)
        ml.addLayout(message_title)
        self._messages = _new_table([
            "时间", "方向", "Topic", "QoS", "保留", "大小", "Payload"])
        time_width = max(
            96,
            self._messages.fontMetrics().horizontalAdvance(
                "00:00:00.000") + 26,
        )
        self._messages.setColumnWidth(0, time_width)
        self._messages.setColumnWidth(1, 52)
        self._messages.setColumnWidth(2, 190)
        self._messages.setColumnWidth(3, 44)
        self._messages.setColumnWidth(4, 54)
        self._messages.setColumnWidth(5, 60)
        self._messages.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        ml.addWidget(self._messages)
        messages.setMinimumHeight(180)

        subscriptions, sl, self._subscriptions_title_label = (
            _compact_protocol_panel(
                "订阅", "勾选即订阅，取消勾选即退订"))
        self._subscriptions_panel = subscriptions
        subscription_row = QWidget()
        subscription_row.setFixedHeight(42)
        self._subscription_input_row = subscription_row
        row = QHBoxLayout(subscription_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self._sub_topic = QLineEdit()
        self._sub_topic.setPlaceholderText("Topic，例如 device/+/status")
        self._sub_topic.setFixedHeight(32)
        row.addWidget(self._sub_topic, 1)
        self._sub_qos = QComboBox()
        self._sub_qos.addItems(["QoS 0", "QoS 1", "QoS 2"])
        self._sub_qos.setFixedHeight(32)
        row.addWidget(self._sub_qos)
        self._btn_subscribe = QPushButton("添加订阅")
        self._btn_subscribe.setFixedHeight(34)
        _set_button_icon(self._btn_subscribe, "http_add.svg")
        self._btn_subscribe.clicked.connect(self._add_subscription)
        row.addWidget(self._btn_subscribe)
        self._btn_unsubscribe = QPushButton("删除选中")
        self._btn_unsubscribe.setFixedHeight(34)
        _set_button_icon(self._btn_unsubscribe, "http_delete.svg")
        self._btn_unsubscribe.clicked.connect(self._remove_subscription)
        row.addWidget(self._btn_unsubscribe)
        sl.addWidget(subscription_row)
        self._subscriptions = _new_table(["启用", "Topic", "QoS"])
        self._subscriptions.setColumnWidth(0, 48)
        self._subscriptions.setColumnWidth(2, 60)
        self._subscriptions.horizontalHeader().setStretchLastSection(False)
        self._subscriptions.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Fixed)
        self._subscriptions.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self._subscriptions.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Fixed)
        self._subscriptions.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._subscriptions.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection)
        self._subscriptions.setAlternatingRowColors(False)
        self._subscription_emit_timer = QTimer(self)
        self._subscription_emit_timer.setSingleShot(True)
        self._subscription_emit_timer.timeout.connect(
            self._emit_subscription_change)
        self._subscriptions.itemChanged.connect(
            self._on_subscription_item_changed)
        sl.addWidget(self._subscriptions)
        sl.setStretch(0, 0)
        sl.setStretch(1, 0)
        sl.setStretch(2, 1)
        subscriptions.setMinimumHeight(220)

        publish, pl, self._publish_title_label = (
            _compact_protocol_panel("发布"))
        self._publish_panel = publish
        publish_row = QWidget()
        publish_row.setFixedHeight(42)
        self._publish_input_row = publish_row
        prow = QHBoxLayout(publish_row)
        prow.setContentsMargins(0, 0, 0, 0)
        prow.setSpacing(8)
        self._pub_topic = QLineEdit()
        self._pub_topic.setPlaceholderText("发布 Topic")
        self._pub_topic.setMinimumWidth(60)
        self._pub_topic.setFixedHeight(32)
        self._pub_topic.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        prow.addWidget(self._pub_topic, 1)
        self._pub_qos = QComboBox()
        self._pub_qos.addItems(["QoS 0", "QoS 1", "QoS 2"])
        self._pub_qos.setMaximumWidth(100)
        self._pub_qos.setFixedHeight(32)
        prow.addWidget(self._pub_qos)
        self._pub_retain = QCheckBox("保留消息")
        self._pub_retain.setMaximumWidth(110)
        self._pub_retain.setToolTip(
            "服务端保留最后一条消息，新订阅者连接后可立即收到")
        prow.addWidget(self._pub_retain)
        self._pub_format = QComboBox()
        self._pub_format.addItems(["文本", "HEX", "JSON"])
        self._pub_format.setMaximumWidth(100)
        self._pub_format.setFixedHeight(32)
        prow.addWidget(self._pub_format)
        self._btn_publish = QPushButton("发布")
        self._btn_publish.setFixedSize(84, 34)
        self._btn_publish.setProperty("protocolPrimary", True)
        _set_button_icon(self._btn_publish, "http_send.svg")
        self._btn_publish.clicked.connect(self._publish)
        prow.addWidget(self._btn_publish)
        pl.addWidget(publish_row)
        self._pub_payload = QPlainTextEdit()
        self._pub_payload.setMinimumHeight(200)
        self._pub_payload.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self._pub_payload.setPlaceholderText("消息内容")
        self._pub_payload.setFont(QFont("Consolas", 10))
        pl.addWidget(self._pub_payload, 1)
        pl.setStretch(0, 0)
        pl.setStretch(1, 0)
        pl.setStretch(2, 1)
        publish.setMinimumHeight(220)

        bottom_split = QSplitter(Qt.Horizontal)
        bottom_split.setObjectName("protocolSplit")
        bottom_split.setChildrenCollapsible(False)
        bottom_split.setHandleWidth(8)
        bottom_split.addWidget(subscriptions)
        bottom_split.addWidget(publish)
        bottom_split.setSizes([520, 520])
        self._mqtt_bottom_split = bottom_split
        root.addWidget(messages, 2)
        root.addWidget(bottom_split, 3)
        self.set_connected(False)

    def set_connected(self, connected):
        self._connected = bool(connected)
        for widget in (
                self._btn_subscribe, self._btn_unsubscribe,
                self._btn_publish):
            widget.setEnabled(connected)

    def append_message(self, message):
        if self._save_writer is not None:
            self._write_saved_message(message)
        if self._messages_paused:
            payload_size = len(bytes(message.get("payload") or b""))
            if self._paused_bytes + payload_size > self.MAX_PAUSED_BYTES:
                self._pause_dropped_bytes += payload_size
                return
            self._paused_messages.append(dict(message))
            self._paused_bytes += payload_size
            return
        self._append_message_now(message)

    def _append_message_now(self, message):
        payload = bytes(message.get("payload") or b"")
        text = message.get("text")
        if text is None:
            full_payload = payload.hex(" ").upper()
            preview = full_payload
        else:
            full_payload = str(text)
            preview = str(text).replace("\r", "\\r").replace("\n", "\\n")
        if len(preview) > 180:
            preview = preview[:177] + "..."
        row = self._messages.rowCount()
        self._messages.insertRow(row)
        values = [
            datetime.fromtimestamp(
                float(message.get("timestamp") or time.time())).strftime(
                    "%H:%M:%S.%f")[:-3],
            {
                "RX": "接收",
                "TX": "发送",
            }.get(
                str(message.get("direction") or "RX").upper(),
                str(message.get("direction") or "RX").upper(),
            ),
            str(message.get("topic") or ""),
            str(message.get("qos", 0)),
            "是" if message.get("retain") else "否",
            str(len(payload)),
            preview,
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setFlags(
                item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if column == 6:
                item.setToolTip(_wide_tooltip(full_payload))
            self._messages.setItem(row, column, item)
        self._display_records += 1
        self._display_bytes += 512 + max(
            len(payload),
            len(full_payload.encode("utf-8")),
        )
        self._messages.scrollToBottom()
        self._clear_messages_if_saving_limit_reached()

    def _write_saved_message(self, message):
        writer = self._save_writer
        if writer is None:
            return
        payload = bytes(message.get("payload") or b"")
        text = message.get("text")
        record = {
            "time": datetime.fromtimestamp(
                float(message.get("timestamp") or time.time())).isoformat(
                    timespec="milliseconds"),
            "direction": str(
                message.get("direction") or "RX").upper(),
            "topic": str(message.get("topic") or ""),
            "qos": int(message.get("qos", 0)),
            "retain": bool(message.get("retain")),
            "dup": bool(message.get("dup")),
            "payload_encoding": "text" if text is not None else "hex",
            "payload": str(text) if text is not None else payload.hex(" ").upper(),
        }
        if not writer.write_text(
                json.dumps(record, ensure_ascii=False) + "\n"):
            self._on_save_writer_error(
                "日志写入失败，保存已停止")

    def _on_save_file_toggle(self, checked):
        if checked:
            try:
                os.makedirs(self._log_directory, exist_ok=True)
            except Exception:
                pass
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            default_path = os.path.join(
                self._log_directory,
                "{}_{}.log".format(self._save_prefix, timestamp),
            )
            path, _ = QFileDialog.getSaveFileName(
                self, "保存日志", default_path,
                "日志文件 (*.log);;所有文件 (*.*)",
            )
            if not path:
                self.chk_save_file.blockSignals(True)
                self.chk_save_file.setChecked(False)
                self.chk_save_file.blockSignals(False)
                return
            try:
                self._save_writer = AsyncLogWriter(path, self)
                self._save_writer.error.connect(
                    self._on_save_writer_error)
                for message in self._paused_messages:
                    self._write_saved_message(message)
            except Exception as exc:
                self._close_save_writer()
                show_error(self, "保存失败", str(exc))
        else:
            self._close_save_writer()

    def _close_save_writer(self):
        writer, self._save_writer = self._save_writer, None
        if writer is not None:
            writer.close()
            writer.deleteLater()
        if self.chk_save_file.isChecked():
            self.chk_save_file.blockSignals(True)
            self.chk_save_file.setChecked(False)
            self.chk_save_file.blockSignals(False)

    def _on_save_writer_error(self, message):
        if self._save_writer is None and not self.chk_save_file.isChecked():
            return
        self._close_save_writer()
        show_error(self, "保存失败", message)

    def _clear_messages_if_saving_limit_reached(self):
        if self._save_writer is None:
            return
        if (
            self._display_records < AUTO_CLEAR_RECORDS
            and self._display_bytes < AUTO_CLEAR_BYTES
        ):
            return
        if not self._save_writer.flush():
            self._on_save_writer_error(
                "日志写入未完成，页面未清空，保存已停止")
            return
        self._messages.setRowCount(0)
        self._display_records = 0
        self._display_bytes = 0

    def set_log_directory(self, directory, prefix=None):
        self._log_directory = str(directory or "")
        if prefix:
            self._save_prefix = str(prefix)

    def _on_messages_pause(self, paused):
        self._messages_paused = bool(paused)
        if paused:
            return
        pending = self._paused_messages
        dropped = self._pause_dropped_bytes
        self._paused_messages = []
        self._paused_bytes = 0
        self._pause_dropped_bytes = 0
        for message in pending:
            self._append_message_now(message)
        if dropped:
            self._append_message_now({
                "timestamp": time.time(),
                "direction": "INFO",
                "topic": "页面暂停",
                "qos": 0,
                "retain": False,
                "payload": (
                    "暂停缓存超过限制，已丢弃 {} 字节".format(
                        dropped)).encode("utf-8"),
                "text": "暂停缓存超过限制，已丢弃 {} 字节".format(
                    dropped),
            })

    def add_subscription(self, topic, qos=0, notify=False):
        topic = str(topic or "").strip()
        if not topic:
            return False
        for row in range(self._subscriptions.rowCount()):
            item = self._subscriptions.item(row, 1)
            if item is not None and item.text() == topic:
                check = self._subscriptions.item(row, 0)
                if check is not None and \
                        check.checkState() != Qt.CheckState.Checked:
                    check.setCheckState(Qt.CheckState.Checked)
                    if notify:
                        self._schedule_subscription_change()
                return True
        _table_add_row(
            self._subscriptions,
            [topic, str(int(qos))],
            checked=True,
        )
        if notify:
            self._schedule_subscription_change()
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
        rows = sorted(
            checked_row_indexes(self._subscriptions), reverse=True)
        if not rows:
            show_information(
                self, "删除订阅", "请先勾选需要删除的订阅。")
            return
        for row in rows:
            self._subscriptions.removeRow(row)
        self._schedule_subscription_change()

    def subscriptions(self):
        return [
            {
                "topic": self._subscriptions.item(row, 1).text(),
                "qos": int(self._subscriptions.item(row, 2).text()),
                "enabled": (
                    self._subscriptions.item(row, 0) is not None
                    and self._subscriptions.item(row, 0).checkState()
                    == Qt.CheckState.Checked),
            }
            for row in range(self._subscriptions.rowCount())
            if self._subscriptions.item(row, 1)
            and self._subscriptions.item(row, 1).text().strip()
        ]

    def enabled_subscriptions(self):
        return [
            {"topic": item["topic"], "qos": item["qos"]}
            for item in self.subscriptions() if item["enabled"]
        ]

    def _on_subscription_item_changed(self, _item):
        self._schedule_subscription_change()

    def _schedule_subscription_change(self):
        self._subscription_emit_timer.start(0)

    def _emit_subscription_change(self):
        self.subscription_changed.emit(
            self.enabled_subscriptions())

    def set_subscriptions(self, items):
        self._subscriptions.blockSignals(True)
        self._subscriptions.setRowCount(0)
        try:
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                topic = str(item.get("topic") or "").strip()
                if not topic:
                    continue
                _table_add_row(
                    self._subscriptions,
                    [topic, str(int(item.get("qos", 0)))],
                    checked=bool(item.get("enabled", True)),
                )
        finally:
            self._subscriptions.blockSignals(False)

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
        if (
            self._save_writer is not None
            and not self._save_writer.flush()
        ):
            self._on_save_writer_error(
                "日志写入未完成，页面未清空，保存已停止")
            return
        self._paused_messages.clear()
        self._paused_bytes = 0
        self._pause_dropped_bytes = 0
        self._display_records = 0
        self._display_bytes = 0
        self._messages.setRowCount(0)

    def reset_runtime_state(self):
        if self.chk_pause.isChecked():
            self.chk_pause.setChecked(False)
        else:
            self._paused_messages.clear()
            self._paused_bytes = 0
            self._pause_dropped_bytes = 0
        self._close_save_writer()

    def cleanup(self):
        self._close_save_writer()

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
    MAX_PAUSED_BYTES = 16 * 1024 * 1024

    def __init__(self):
        super().__init__()
        self._connected = False
        self._messages_paused = False
        self._paused_messages = []
        self._paused_bytes = 0
        self._pause_dropped_bytes = 0
        self._save_writer = None
        self._log_directory = os.getcwd()
        self._save_prefix = "websocket"
        self._display_records = 0
        self._display_bytes = 0
        self._build()

    def _build(self):
        self.setObjectName("websocketPage")
        self.setStyleSheet(PROTOCOL_WORKSPACE_STYLE)
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        top_card = QWidget()
        top_card.setObjectName("protocolCard")
        top_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        top_card_layout = QVBoxLayout(top_card)
        top_card_layout.setContentsMargins(10, 9, 10, 9)
        top_card_layout.setSpacing(4)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        self._url = QLineEdit()
        self._url.setPlaceholderText("ws://127.0.0.1:8080/ws")
        self._url.setClearButtonEnabled(True)
        self._url.setFixedHeight(32)
        self._url.returnPressed.connect(self._toggle_connection)
        top.addWidget(self._url, 1)
        self._btn_connect = QPushButton("连接 WebSocket")
        self._btn_connect.setObjectName("wsConnect")
        self._btn_connect.setProperty("protocolPrimary", True)
        self._btn_connect.setProperty("connected", "false")
        _set_button_icon(self._btn_connect, "http_send.svg")
        self._btn_connect.setMinimumWidth(136)
        self._btn_connect.setFixedHeight(34)
        self._btn_connect.clicked.connect(self._toggle_connection)
        top.addWidget(self._btn_connect)
        top_card_layout.addLayout(top)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        self._btn_ping = QPushButton("发送 Ping")
        self._btn_ping.setFixedHeight(30)
        self._btn_ping.clicked.connect(self.ping_requested.emit)
        actions.addWidget(self._btn_ping)
        self.chk_pause = QCheckBox("页面暂停")
        self.chk_pause.setToolTip(
            "暂停时不刷新消息列表，继续接收的消息会在恢复后补显示")
        self.chk_pause.toggled.connect(self._on_messages_pause)
        actions.addWidget(self.chk_pause)
        self.chk_save_file = QCheckBox("保存到文件")
        self.chk_save_file.setToolTip(
            "保存期间持续写盘；页面达到 10000 条或 300 MB 后自动清空")
        self.chk_save_file.toggled.connect(
            self._on_save_file_toggle)
        actions.addWidget(self.chk_save_file)
        self.lbl_save_rule = _save_rule_label()
        actions.addWidget(self.lbl_save_rule)
        actions.addStretch()
        self._btn_clear = QPushButton("清空消息")
        self._btn_clear.setFixedHeight(30)
        _set_button_icon(self._btn_clear, "http_delete.svg")
        self._btn_clear.clicked.connect(self.clear_messages)
        actions.addWidget(self._btn_clear)
        top_card_layout.addLayout(actions)
        root.addWidget(top_card)

        headers_group = _protocol_group("连接请求头")
        hl = QVBoxLayout(headers_group)
        hl.setContentsMargins(10, 22, 10, 10)
        hl.setSpacing(8)
        hrow = QHBoxLayout()
        hrow.setSpacing(8)
        self._btn_add_header = QPushButton("+ 添加 Header")
        self._btn_add_header.setText("添加 Header")
        _set_button_icon(self._btn_add_header, "http_add.svg")
        self._btn_add_header.setFixedHeight(30)
        self._btn_add_header.clicked.connect(
            lambda: _table_add_row(self._headers, ["", ""], True))
        hrow.addWidget(self._btn_add_header)
        self._btn_remove_header = QPushButton("删除选中")
        _set_button_icon(self._btn_remove_header, "http_delete.svg")
        self._btn_remove_header.setFixedHeight(30)
        self._btn_remove_header.clicked.connect(
            lambda: self._remove_checked_rows(self._headers))
        hrow.addWidget(self._btn_remove_header)
        hrow.addStretch()
        hl.addLayout(hrow)
        self._headers = _new_table(["启用", "Header", "值"])
        self._headers.setColumnWidth(0, 48)
        self._headers.setColumnWidth(1, 280)
        self._headers.setMaximumHeight(120)
        hl.addWidget(self._headers)
        root.addWidget(headers_group)

        self._messages = _new_table([
            "时间", "方向", "类型", "大小", "内容"])
        self._messages.setColumnWidth(0, 112)
        self._messages.setColumnWidth(1, 58)
        self._messages.setColumnWidth(2, 65)
        self._messages.setColumnWidth(3, 60)
        self._messages.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        root.addWidget(self._messages, 1)

        composer = _protocol_group("发送消息")
        cl = QVBoxLayout(composer)
        cl.setContentsMargins(10, 22, 10, 10)
        cl.setSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(8)
        self._format = QComboBox()
        self._format.addItems(["文本", "JSON", "HEX/二进制"])
        self._format.setFixedSize(110, 32)
        row.addWidget(self._format)
        row.addStretch()
        self._btn_send = QPushButton("发送")
        self._btn_send.setProperty("protocolPrimary", True)
        _set_button_icon(self._btn_send, "http_send.svg")
        self._btn_send.setFixedHeight(34)
        self._btn_send.clicked.connect(self._send)
        row.addWidget(self._btn_send)
        cl.addLayout(row)
        self._payload = QPlainTextEdit()
        self._payload.setMinimumHeight(72)
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
        _set_button_icon(
            self._btn_connect,
            "http_close.svg" if connected else "http_send.svg",
        )
        self._btn_connect.setProperty(
            "connected", "true" if connected else "false")
        self._btn_connect.style().unpolish(self._btn_connect)
        self._btn_connect.style().polish(self._btn_connect)
        self._url.setEnabled(not connected)
        self._btn_send.setEnabled(connected)
        self._btn_ping.setEnabled(connected)

    def append_message(self, message):
        if self._save_writer is not None:
            self._write_saved_message(message)
        if self._messages_paused:
            payload_size = len(bytes(message.get("payload") or b""))
            if self._paused_bytes + payload_size > self.MAX_PAUSED_BYTES:
                self._pause_dropped_bytes += payload_size
                return
            self._paused_messages.append(dict(message))
            self._paused_bytes += payload_size
            return
        self._append_message_now(message)

    def _append_message_now(self, message):
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
            {
                "RX": "接收",
                "TX": "发送",
            }.get(
                str(message.get("direction") or "rx").upper(),
                str(message.get("direction") or "rx").upper(),
            ),
            "Binary" if binary else "Text",
            str(len(payload)),
            preview,
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setFlags(
                item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if column == 4:
                item.setToolTip(_wide_tooltip(str(
                    text if text is not None and not binary
                    else payload.hex(" ").upper())))
            self._messages.setItem(row, column, item)
        self._display_records += 1
        self._display_bytes += 512 + max(
            len(payload),
            len(preview.encode("utf-8")),
        )
        self._messages.scrollToBottom()
        self._clear_messages_if_saving_limit_reached()

    def _on_messages_pause(self, paused):
        self._messages_paused = bool(paused)
        if paused:
            return
        pending = self._paused_messages
        dropped = self._pause_dropped_bytes
        self._paused_messages = []
        self._paused_bytes = 0
        self._pause_dropped_bytes = 0
        for message in pending:
            self._append_message_now(message)
        if dropped:
            text = "暂停缓存超过限制，已丢弃 {} 字节".format(dropped)
            self._append_message_now({
                "timestamp": time.time(),
                "direction": "INFO",
                "binary": False,
                "payload": text.encode("utf-8"),
                "text": text,
            })

    def _write_saved_message(self, message):
        writer = self._save_writer
        if writer is None:
            return
        payload = bytes(message.get("payload") or b"")
        binary = bool(message.get("binary"))
        text = message.get("text")
        record = {
            "time": datetime.fromtimestamp(
                float(message.get("timestamp") or time.time())).isoformat(
                    timespec="milliseconds"),
            "direction": str(
                message.get("direction") or "rx").upper(),
            "type": "binary" if binary else "text",
            "payload_encoding": "hex" if binary else "text",
            "payload": payload.hex(" ").upper() if binary else str(text or ""),
        }
        if not writer.write_text(
                json.dumps(record, ensure_ascii=False) + "\n"):
            self._on_save_writer_error(
                "日志写入失败，保存已停止")

    def _on_save_file_toggle(self, checked):
        if checked:
            try:
                os.makedirs(self._log_directory, exist_ok=True)
            except Exception:
                pass
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            default_path = os.path.join(
                self._log_directory,
                "{}_{}.log".format(self._save_prefix, timestamp),
            )
            path, _ = QFileDialog.getSaveFileName(
                self, "保存日志", default_path,
                "日志文件 (*.log);;所有文件 (*.*)",
            )
            if not path:
                self.chk_save_file.blockSignals(True)
                self.chk_save_file.setChecked(False)
                self.chk_save_file.blockSignals(False)
                return
            try:
                self._save_writer = AsyncLogWriter(path, self)
                self._save_writer.error.connect(
                    self._on_save_writer_error)
            except Exception as exc:
                self._close_save_writer()
                show_error(self, "保存失败", str(exc))
        else:
            self._close_save_writer()

    def _close_save_writer(self):
        writer, self._save_writer = self._save_writer, None
        if writer is not None:
            writer.close()
            writer.deleteLater()
        if self.chk_save_file.isChecked():
            self.chk_save_file.blockSignals(True)
            self.chk_save_file.setChecked(False)
            self.chk_save_file.blockSignals(False)

    def _on_save_writer_error(self, message):
        if self._save_writer is None and not self.chk_save_file.isChecked():
            return
        self._close_save_writer()
        show_error(self, "保存失败", message)

    def _clear_messages_if_saving_limit_reached(self):
        if self._save_writer is None:
            return
        if (
            self._display_records < AUTO_CLEAR_RECORDS
            and self._display_bytes < AUTO_CLEAR_BYTES
        ):
            return
        if not self._save_writer.flush():
            self._on_save_writer_error(
                "日志写入未完成，页面未清空，保存已停止")
            return
        self._messages.setRowCount(0)
        self._display_records = 0
        self._display_bytes = 0

    def set_log_directory(self, directory, prefix=None):
        self._log_directory = str(directory or "")
        if prefix:
            self._save_prefix = str(prefix)

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
        if (
            self._save_writer is not None
            and not self._save_writer.flush()
        ):
            self._on_save_writer_error(
                "日志写入未完成，页面未清空，保存已停止")
            return
        self._paused_messages.clear()
        self._paused_bytes = 0
        self._pause_dropped_bytes = 0
        self._display_records = 0
        self._display_bytes = 0
        self._messages.setRowCount(0)

    def reset_runtime_state(self):
        if self.chk_pause.isChecked():
            self.chk_pause.setChecked(False)
        else:
            self._paused_messages.clear()
            self._paused_bytes = 0
            self._pause_dropped_bytes = 0
        self._close_save_writer()

    def cleanup(self):
        self._close_save_writer()

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
