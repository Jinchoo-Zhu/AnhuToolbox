# -*- coding: utf-8 -*-
"""MQTT、HTTP、WebSocket 协议扩展回归测试。"""

import json
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import msgpack

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, QTimer, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QDialog, QGroupBox, QLabel, QPushButton,
    QHeaderView, QMessageBox, QSizePolicy, QStyle, QStyleOptionGroupBox,
    QToolButton,
)

from anhutoolbox.main_window import MainWindow
from anhutoolbox.http_environments import (
    EnvironmentManagerDialog, EnvironmentResolver,
)
from anhutoolbox.http_dialogs import UnsavedChangesDialog
from anhutoolbox.http_page import _enabled_pairs
from anhutoolbox.protocol_pages import (
    HTTPPage, MQTTPage, WebSocketPage,
)
from anhutoolbox.protocol_workers import (
    HTTPRequestWorker, MQTTWorker, WebSocketWorker,
)
from anhutoolbox.sidebar import Sidebar
from anhutoolbox.styles import GLOBAL_STYLE

_HARDWARE_TEST_PATCH = mock.patch(
    "anhutoolbox.hardware.collect_hardware_info",
    return_value={},
)
_HARDWARE_TEST_PATCH.start()


APP = QApplication.instance() or QApplication([])


def close_page(page):
    if hasattr(page, "cleanup"):
        page.cleanup()
    page.close()
    page.deleteLater()
    APP.processEvents()


class _HTTPHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        payload = json.dumps({
            "path": self.path,
            "header": self.headers.get("X-Test", ""),
            "cookie": self.headers.get("Cookie", ""),
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Set-Cookie", "session=abc; Path=/; HttpOnly; Secure")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        pass


class ProtocolWorkerTests(unittest.TestCase):
    def test_http_request_worker(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _HTTPHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        worker = HTTPRequestWorker()
        try:
            worker.configure({
                "method": "GET",
                "url": "http://127.0.0.1:{}/api".format(
                    server.server_address[1]),
                "params": [("a", "1")],
                "headers": {"X-Test": "yes"},
                "content": None,
                "timeout": 5,
                "follow_redirects": True,
                "verify_tls": True,
            })
            worker.start()
            self.assertTrue(worker.wait(5000))
            event = worker.pop_event()
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(event[0], "ok")
        result = event[1]
        self.assertEqual(result["status"], 200)
        self.assertEqual(
            json.loads(result["content"])["header"], "yes")

    def test_http_request_worker_auto_version_falls_back(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _HTTPHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        worker = HTTPRequestWorker()
        try:
            worker.configure({
                "method": "GET",
                "url": "http://127.0.0.1:{}/auto".format(
                    server.server_address[1]),
                "http_version": "auto",
                "timeout": 5,
                "follow_redirects": True,
                "verify_tls": True,
            })
            worker.start()
            self.assertTrue(worker.wait(5000))
            event = worker.pop_event()
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(event[0], "ok")
        self.assertEqual(event[1]["status"], 200)

    def test_mqtt_worker_subscription_state(self):
        worker = MQTTWorker()
        worker.set_subscriptions([
            {"topic": "a/+", "qos": 0},
            {"topic": "b/#", "qos": 2},
        ])
        self.assertEqual(len(worker._subscriptions), 2)
        worker.sync_subscriptions([{"topic": "b/#", "qos": 1}])
        self.assertEqual(worker._subscriptions, [{"topic": "b/#", "qos": 1}])

    def test_websocket_worker_configuration(self):
        worker = WebSocketWorker()
        worker.configure({
            "url": "ws://127.0.0.1/test",
            "headers": {"X-Test": "yes"},
            "auto_reconnect": False,
        })
        self.assertEqual(worker._config["url"], "ws://127.0.0.1/test")
        self.assertFalse(worker._config["auto_reconnect"])

    def test_websocket_text_send_uses_text_opcode(self):
        worker = WebSocketWorker()
        app = mock.Mock()
        app.sock.connected = True
        worker._app = app
        self.assertTrue(worker.send(b"hello", binary=False))
        app.send.assert_called_once()
        self.assertEqual(
            app.send.call_args.kwargs["opcode"],
            __import__("websocket").ABNF.OPCODE_TEXT)


class ProtocolPageTests(unittest.TestCase):
    def test_protocol_group_title_has_vertical_clearance(self):
        page = WebSocketPage()
        page.show()
        APP.processEvents()
        group = [
            item for item in page.findChildren(QGroupBox)
            if item.title() == "连接请求头"
        ][0]
        option = QStyleOptionGroupBox()
        group.initStyleOption(option)
        label = group.style().subControlRect(
            QStyle.ComplexControl.CC_GroupBox,
            option, QStyle.SubControl.SC_GroupBoxLabel, group)
        frame = group.style().subControlRect(
            QStyle.ComplexControl.CC_GroupBox,
            option, QStyle.SubControl.SC_GroupBoxFrame, group)
        self.assertGreaterEqual(label.top(), 5)
        self.assertGreater(frame.top() - label.bottom(), 1)
        close_page(page)

    def test_mqtt_page_snapshot_and_hex_payload(self):
        page = MQTTPage()
        page.set_subscriptions([{"topic": "device/+", "qos": 1}])
        page._pub_topic.setText("device/cmd")
        page._pub_format.setCurrentText("HEX")
        page._pub_payload.setPlainText("01 02 FF")
        requests = []
        page.publish_requested.connect(requests.append)
        page.set_connected(True)
        page._publish()
        self.assertEqual(requests[0]["payload"], b"\x01\x02\xff")
        snapshot = page.snapshot()
        self.assertEqual(snapshot["subscriptions"][0]["topic"], "device/+")
        self.assertEqual(snapshot["publish_format"], "HEX")
        self.assertFalse(hasattr(page, "_state"))
        close_page(page)

    def test_mqtt_messages_are_full_width_and_panels_are_side_by_side(self):
        page = MQTTPage()
        page.resize(1200, 720)
        page.show()
        APP.processEvents()
        split = page._mqtt_bottom_split
        self.assertEqual(
            split.orientation(), Qt.Orientation.Horizontal)
        self.assertEqual(split.count(), 2)
        self.assertIs(split.widget(0), page._subscriptions_panel)
        self.assertIs(split.widget(1), page._publish_panel)
        self.assertEqual(
            page._subscriptions_panel.height(),
            page._publish_panel.height(),
        )
        self.assertFalse(
            page._subscriptions.horizontalHeader().stretchLastSection())
        self.assertEqual(
            page._subscriptions.horizontalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )
        subscription_hint = page._subscriptions_panel.findChild(
            QLabel, "protocolHint")
        self.assertIsNotNone(subscription_hint)
        self.assertEqual(
            subscription_hint.text(),
            "勾选即订阅，取消勾选即退订",
        )
        self.assertEqual(
            page._btn_publish.sizePolicy().verticalPolicy(),
            QSizePolicy.Policy.Fixed,
        )
        for button, row in (
            (page._btn_subscribe, page._subscription_input_row),
            (page._btn_unsubscribe, page._subscription_input_row),
            (page._btn_publish, page._publish_input_row),
        ):
            self.assertGreaterEqual(button.height(), 34)
            self.assertLessEqual(
                button.geometry().bottom(), row.height() - 1)
        self.assertGreater(page._pub_payload.maximumHeight(), 10000)
        self.assertGreater(page._pub_payload.height(), 200)
        button_center = page._btn_publish.mapTo(
            page._publish_panel, page._btn_publish.rect().center()).y()
        topic_center = page._pub_topic.mapTo(
            page._publish_panel, page._pub_topic.rect().center()).y()
        self.assertEqual(button_center, topic_center)
        page._pub_topic.setText("ah/emis/equipmentAll/11")
        APP.processEvents()
        self.assertGreater(page._pub_topic.width(), 150)
        self.assertLessEqual(
            page._pub_qos.x()
            - (page._pub_topic.x() + page._pub_topic.width()),
            8,
        )
        self.assertGreater(page._btn_publish.x(), page._pub_format.x())
        self.assertGreaterEqual(
            page._btn_publish.geometry().right(),
            page._publish_input_row.width() - 2,
        )
        payload_bottom = page._pub_payload.mapTo(
            page._publish_panel,
            QPoint(0, page._pub_payload.height()),
        ).y()
        self.assertGreaterEqual(
            payload_bottom, page._publish_panel.height() - 10)
        self.assertIsNot(page._messages_container.parentWidget(), split)
        self.assertGreaterEqual(page._subscriptions_panel.height(), 200)
        self.assertGreaterEqual(page._publish_panel.height(), 200)
        self.assertEqual(
            page._subscriptions_title_label.mapTo(page, QPoint(0, 0)).y(),
            page._publish_title_label.mapTo(page, QPoint(0, 0)).y(),
        )
        self.assertEqual(
            page._sub_topic.mapTo(page, QPoint(0, 0)).y(),
            page._pub_topic.mapTo(page, QPoint(0, 0)).y(),
        )
        self.assertIs(
            page._btn_clear.parentWidget(), page._messages_container)
        self.assertLess(page.chk_pause.x(), page._btn_clear.x())
        self.assertLess(page.chk_pause.x(), page.chk_save_file.x())
        self.assertLess(
            page._messages_title_label.geometry().right(),
            page.chk_pause.x(),
        )
        self.assertLess(
            page.lbl_save_rule.geometry().right(),
            page._btn_clear.x(),
        )
        close_page(page)

    def test_mqtt_message_page_pause_buffers_and_resumes(self):
        page = MQTTPage()
        page.show()
        APP.processEvents()
        page.append_message({
            "timestamp": 1700000000,
            "direction": "RX",
            "topic": "before",
            "payload": b"1",
            "text": "1",
        })
        self.assertEqual(page._messages.rowCount(), 1)

        page.chk_pause.setChecked(True)
        page.append_message({
            "timestamp": 1700000001,
            "direction": "RX",
            "topic": "paused",
            "payload": b"2",
            "text": "2",
        })
        self.assertEqual(page._messages.rowCount(), 1)
        self.assertEqual(len(page._paused_messages), 1)

        page.chk_pause.setChecked(False)
        self.assertEqual(page._messages.rowCount(), 2)
        self.assertEqual(page._messages.item(1, 2).text(), "paused")

        page.chk_pause.setChecked(True)
        page.append_message({
            "timestamp": 1700000002,
            "direction": "RX",
            "topic": "cleared",
            "payload": b"3",
            "text": "3",
        })
        page.clear_messages()
        page.chk_pause.setChecked(False)
        self.assertEqual(page._messages.rowCount(), 0)
        close_page(page)

    def test_websocket_message_page_pause_buffers_and_resumes(self):
        page = WebSocketPage()
        page.show()
        APP.processEvents()
        page.append_message({
            "timestamp": 1700000000,
            "direction": "RX",
            "binary": False,
            "payload": b"before",
            "text": "before",
        })
        self.assertEqual(page._messages.rowCount(), 1)
        self.assertLess(page.chk_pause.x(), page.chk_save_file.x())

        page.chk_pause.setChecked(True)
        page.append_message({
            "timestamp": 1700000001,
            "direction": "RX",
            "binary": False,
            "payload": b"paused",
            "text": "paused",
        })
        self.assertEqual(page._messages.rowCount(), 1)
        self.assertEqual(len(page._paused_messages), 1)

        page.chk_pause.setChecked(False)
        self.assertEqual(page._messages.rowCount(), 2)
        self.assertEqual(page._messages.item(1, 4).text(), "paused")
        close_page(page)

    def test_mqtt_and_websocket_save_while_page_is_paused(self):
        cases = (
            (
                MQTTPage,
                "mqtt",
                {
                    "timestamp": 1700000000,
                    "direction": "RX",
                    "topic": "device/status",
                    "qos": 0,
                    "payload": b"paused",
                    "text": "paused",
                },
            ),
            (
                WebSocketPage,
                "websocket",
                {
                    "timestamp": 1700000000,
                    "direction": "RX",
                    "binary": False,
                    "payload": b"paused",
                    "text": "paused",
                },
            ),
        )
        with tempfile.TemporaryDirectory() as temp:
            for page_type, prefix, message in cases:
                path = os.path.join(temp, prefix + ".log")
                page = page_type()
                page.set_log_directory(temp, prefix)
                with mock.patch(
                        "anhutoolbox.protocol_pages.QFileDialog."
                        "getSaveFileName",
                        return_value=(path, "")):
                    page.chk_save_file.setChecked(True)
                page.chk_pause.setChecked(True)
                page.append_message(message)
                self.assertEqual(page._messages.rowCount(), 0)
                self.assertTrue(page._save_writer.flush())
                self.assertEqual(
                    len(Path(path).read_text(
                        encoding="utf-8").splitlines()),
                    1,
                )
                page.chk_pause.setChecked(False)
                self.assertEqual(page._messages.rowCount(), 1)
                self.assertTrue(page._save_writer.flush())
                self.assertEqual(
                    len(Path(path).read_text(
                        encoding="utf-8").splitlines()),
                    1,
                )
                close_page(page)

    def test_protocol_save_streams_and_clears_page_after_flush(self):
        cases = (
            (
                MQTTPage,
                "mqtt",
                {
                    "timestamp": 1700000000,
                    "direction": "RX",
                    "topic": "device/status",
                    "qos": 0,
                    "payload": b"ok",
                    "text": "ok",
                },
            ),
            (
                WebSocketPage,
                "websocket",
                {
                    "timestamp": 1700000000,
                    "direction": "RX",
                    "binary": False,
                    "payload": b"ok",
                    "text": "ok",
                },
            ),
        )
        with tempfile.TemporaryDirectory() as temp:
            for page_type, prefix, message in cases:
                path = os.path.join(temp, "{}.log".format(prefix))
                page = page_type()
                self.assertIn(
                    "未开启保存不清屏", page.lbl_save_rule.text())
                self.assertNotIn("\n", page.lbl_save_rule.text())
                page.set_log_directory(temp, prefix)
                default_paths = []

                def choose_path(parent, title, default, filters):
                    default_paths.append(default)
                    return path, ""

                with mock.patch(
                        "anhutoolbox.protocol_pages.AUTO_CLEAR_RECORDS",
                        2), \
                        mock.patch(
                            "anhutoolbox.protocol_pages.AUTO_CLEAR_BYTES",
                            1024 * 1024), \
                        mock.patch(
                            "anhutoolbox.protocol_pages.QFileDialog."
                            "getSaveFileName",
                            side_effect=choose_path):
                    page.chk_save_file.setChecked(True)
                    self.assertEqual(
                        Path(default_paths[0]).parent, Path(temp))
                    self.assertTrue(
                        Path(default_paths[0]).name.startswith(
                            prefix + "_"))
                    for index in range(3):
                        item = dict(message)
                        item["timestamp"] = 1700000000 + index
                        page.append_message(item)
                    self.assertEqual(page._messages.rowCount(), 1)
                    self.assertTrue(page.chk_save_file.isChecked())
                    self.assertTrue(page._save_writer.flush())
                records = [
                    json.loads(line)
                    for line in Path(path).read_text(
                        encoding="utf-8").splitlines()
                ]
                self.assertEqual(len(records), 3)
                self.assertEqual(records[0]["payload"], "ok")
                close_page(page)

    def test_mqtt_message_payload_has_full_tooltip_and_is_read_only(self):
        page = MQTTPage()
        full_payload = json.dumps({
            "set": 1,
            "equipment": [
                {"id": index, "value": "x" * 20}
                for index in range(20)
            ],
        }, ensure_ascii=False)
        page.append_message({
            "timestamp": 1700000000,
            "direction": "RX",
            "topic": "ah/emis/status",
            "qos": 0,
            "retain": False,
            "payload": full_payload.encode("utf-8"),
            "text": full_payload,
        })
        payload_item = page._messages.item(0, 6)
        self.assertEqual(page._messages.item(0, 1).text(), "接收")
        tooltip = payload_item.toolTip()
        self.assertIn('width="640"', tooltip)
        self.assertIn("<pre", tooltip)
        self.assertIn("\n  &quot;set&quot;: 1", tooltip)
        self.assertIn("&quot;set&quot;", tooltip)
        self.assertIn("&quot;equipment&quot;", tooltip)
        self.assertFalse(
            payload_item.flags() & Qt.ItemFlag.ItemIsEditable)
        self.assertEqual(
            page._messages.editTriggers(),
            QAbstractItemView.EditTrigger.NoEditTriggers,
        )
        required_time_width = (
            page._messages.fontMetrics().horizontalAdvance(
                "00:00:00.000") + 26
        )
        self.assertEqual(
            page._messages.columnWidth(0), required_time_width)
        self.assertGreaterEqual(page._pub_payload.minimumHeight(), 200)
        close_page(page)

    def test_mqtt_sidebar_uses_server_ip_label_and_default_port(self):
        sidebar = Sidebar()
        self.assertEqual(sidebar.sp_mqtt_port.value(), 1883)
        self.assertEqual(sidebar.sp_mqtt_keepalive.value(), 60)
        sidebar._mode_group.button(3).click()
        self.assertEqual(sidebar._btn_connect.text(), "连接服务端")
        sidebar.set_connected(True)
        self.assertEqual(sidebar._btn_connect.text(), "断开服务端")
        sidebar.set_controls_enabled(False)
        for widget in (
            sidebar.le_mqtt_host,
            sidebar.sp_mqtt_port,
            sidebar.le_mqtt_client_id,
            sidebar.le_mqtt_user,
            sidebar.le_mqtt_password,
            sidebar.sp_mqtt_keepalive,
            sidebar.cb_mqtt_protocol,
            sidebar.chk_mqtt_tls,
            sidebar.chk_mqtt_clean,
            sidebar.chk_mqtt_reconnect,
        ):
            self.assertFalse(widget.isEnabled())
        sidebar.set_controls_enabled(True)
        sidebar.set_connected(False)
        self.assertTrue(any(
            label.text() == "服务端IP"
            for label in sidebar.findChildren(QLabel)
        ))
        self.assertTrue(any(
            label.text() == "心跳间隔(秒)"
            for label in sidebar.findChildren(QLabel)
        ))
        close_page(sidebar)

    def test_mqtt_connection_validates_server_and_credentials(self):
        with tempfile.TemporaryDirectory() as temp:
            window = MainWindow(temp)
            try:
                window.sidebar.le_mqtt_host.setText("192.168.2.115")
                window.sidebar.le_mqtt_client_id.setText("MQTTDESKT")
                window.sidebar.le_mqtt_user.setText("admin")
                window.sidebar.le_mqtt_password.clear()
                with mock.patch(
                        "anhutoolbox.main_window.show_warning") as warning:
                    window._connect_mqtt()
                warning.assert_called_once()
                self.assertEqual(
                    warning.call_args.args[2], "请填写密码。")
                self.assertIsNone(window._active_worker)

                window.sidebar.le_mqtt_user.clear()
                window.sidebar.le_mqtt_password.setText("secret")
                with mock.patch(
                        "anhutoolbox.main_window.show_warning") as warning:
                    window._connect_mqtt()
                self.assertEqual(
                    warning.call_args.args[2], "请填写用户名。")
                self.assertIsNone(window._active_worker)

                window.sidebar.le_mqtt_host.clear()
                window.sidebar.le_mqtt_user.clear()
                window.sidebar.le_mqtt_password.clear()
                with mock.patch(
                        "anhutoolbox.main_window.show_warning") as warning:
                    window._connect_mqtt()
                self.assertEqual(
                    warning.call_args.args[2], "请填写服务端IP。")
                self.assertIsNone(window._active_worker)

                window.sidebar.le_mqtt_host.setText("broker.example")
                error, field = window._validate_mqtt_fields()
                self.assertIsNone(error)
                self.assertIsNone(field)
            finally:
                window.close()
                window.deleteLater()
                APP.processEvents()

    def test_mqtt_subscriptions_have_checkboxes_and_delete_only_checked(self):
        page = MQTTPage()
        page.set_subscriptions([
            {"topic": "a/#", "qos": 0},
            {"topic": "b/#", "qos": 1},
            {"topic": "c/#", "qos": 2},
        ])
        self.assertEqual(page._subscriptions.columnCount(), 3)
        self.assertEqual(
            page._subscriptions.horizontalHeaderItem(0).text(), "")
        self.assertEqual(
            page._subscriptions.selectionMode(),
            QAbstractItemView.SelectionMode.NoSelection,
        )
        self.assertFalse(page._subscriptions.alternatingRowColors())
        self.assertEqual(page._pub_retain.text(), "保留消息")
        changes = []
        page.subscription_changed.connect(changes.append)
        page._subscriptions.item(0, 0).setCheckState(
            Qt.CheckState.Unchecked)
        QTest.qWait(1)
        self.assertEqual(
            [item["topic"] for item in changes[-1]],
            ["b/#", "c/#"],
        )
        page._subscriptions.item(0, 0).setCheckState(
            Qt.CheckState.Checked)
        QTest.qWait(1)
        self.assertEqual(
            [item["topic"] for item in changes[-1]],
            ["a/#", "b/#", "c/#"],
        )
        page._subscriptions.item(0, 0).setCheckState(
            Qt.CheckState.Unchecked)
        page._subscriptions.item(2, 0).setCheckState(
            Qt.CheckState.Unchecked)
        page._remove_subscription()
        self.assertEqual(
            [item["topic"] for item in page.subscriptions()],
            ["a/#", "c/#"],
        )

        with mock.patch(
                "anhutoolbox.protocol_pages.show_information") as info:
            page._remove_subscription()
        info.assert_called_once()
        self.assertEqual(len(page.subscriptions()), 2)
        close_page(page)

    def test_websocket_page_state(self):
        page = WebSocketPage()
        page.set_url("ws://127.0.0.1/ws")
        page.set_headers([
            {"name": "Authorization", "value": "Bearer x", "enabled": True},
        ])
        page._format.setCurrentText("HEX/二进制")
        page._payload.setPlainText("AA 01")
        page.set_connected(True)
        requests = []
        page.send_requested.connect(requests.append)
        page._send()
        self.assertEqual(requests[0]["payload"], b"\xaa\x01")
        self.assertTrue(requests[0]["binary"])
        self.assertEqual(page.headers(), [("Authorization", "Bearer x")])
        self.assertEqual(page.url(), "ws://127.0.0.1/ws")
        page.append_message({
            "timestamp": 1700000000,
            "direction": "TX",
            "binary": False,
            "payload": b"hello",
            "text": "hello",
        })
        self.assertEqual(page._messages.item(0, 1).text(), "发送")
        close_page(page)

    def test_websocket_url_and_connect_button_are_in_workspace(self):
        page = WebSocketPage()
        events = []
        page.connect_requested.connect(lambda: events.append("connect"))
        page.disconnect_requested.connect(lambda: events.append("disconnect"))

        page.set_url("ws://127.0.0.1:8080/ws")
        page._btn_connect.click()
        self.assertEqual(events, ["connect"])
        self.assertEqual(page.snapshot()["url"], "ws://127.0.0.1:8080/ws")

        page.set_connected(True)
        self.assertEqual(page._btn_connect.text(), "断开 WebSocket")
        self.assertFalse(page._url.isEnabled())
        page._btn_connect.click()
        self.assertEqual(events, ["connect", "disconnect"])

        page.set_connected(False)
        self.assertEqual(page._btn_connect.text(), "连接 WebSocket")
        self.assertTrue(page._url.isEnabled())
        close_page(page)

    def test_sidebar_wheel_requires_focus_for_parameter_controls(self):
        sidebar = Sidebar()
        sidebar.resize(260, 360)
        sidebar._mode_group.button(3).click()
        sidebar.show()
        sidebar.activateWindow()
        APP.processEvents()

        spin = sidebar.sp_mqtt_port
        spin_editor = spin.lineEdit()
        sidebar._cb_project.setFocus(Qt.FocusReason.OtherFocusReason)
        APP.processEvents()
        self.assertFalse(spin.hasFocus())
        scrollbar = sidebar._settings_scroll.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        initial_value = spin.value()
        wheel_up = QWheelEvent(
            QPointF(5, 5), QPointF(5, 5),
            QPoint(), QPoint(0, 120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase, False,
        )
        QApplication.sendEvent(spin_editor, wheel_up)
        APP.processEvents()
        self.assertEqual(spin.value(), initial_value)
        self.assertLess(scrollbar.value(), scrollbar.maximum())

        spin.setFocus(Qt.FocusReason.OtherFocusReason)
        APP.processEvents()
        scrollbar.setValue(scrollbar.maximum())
        automatic_focus_wheel = QWheelEvent(
            QPointF(5, 5), QPointF(5, 5),
            QPoint(), QPoint(0, 120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase, False,
        )
        QApplication.sendEvent(spin_editor, automatic_focus_wheel)
        APP.processEvents()
        self.assertEqual(spin.value(), initial_value)
        self.assertLess(scrollbar.value(), scrollbar.maximum())

        sidebar._cb_project.setFocus(Qt.FocusReason.OtherFocusReason)
        APP.processEvents()
        spin.setFocus(Qt.FocusReason.TabFocusReason)
        APP.processEvents()
        self.assertTrue(spin.hasFocus())
        focused_value = spin.value()
        focused_wheel = QWheelEvent(
            QPointF(5, 5), QPointF(5, 5),
            QPoint(), QPoint(0, 120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase, False,
        )
        QApplication.sendEvent(spin_editor, focused_wheel)
        APP.processEvents()
        self.assertEqual(spin.value(), focused_value + 1)

        combo = sidebar.cb_mqtt_protocol
        combo.setCurrentIndex(0)
        scrollbar.setValue(scrollbar.minimum())
        unfocused_combo_wheel = QWheelEvent(
            QPointF(5, 5), QPointF(5, 5),
            QPoint(), QPoint(0, -120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase, False,
        )
        QApplication.sendEvent(combo, unfocused_combo_wheel)
        APP.processEvents()
        self.assertEqual(combo.currentIndex(), 0)
        self.assertGreater(scrollbar.value(), scrollbar.minimum())

        combo.setFocus(Qt.FocusReason.TabFocusReason)
        APP.processEvents()
        self.assertTrue(combo.hasFocus())
        focused_combo_wheel = QWheelEvent(
            QPointF(5, 5), QPointF(5, 5),
            QPoint(), QPoint(0, -120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase, False,
        )
        QApplication.sendEvent(combo, focused_combo_wheel)
        APP.processEvents()
        self.assertEqual(combo.currentIndex(), 1)
        close_page(sidebar)

    def test_mqtt_websocket_sidebar_fills_without_changing_top_modes(self):
        sidebar = Sidebar()
        for index in (3, 4):
            sidebar._mode_group.button(index).click()
            self.assertEqual(
                sidebar._settings_inner_layout.stretch(0), 1)
            self.assertEqual(
                sidebar._settings_inner_layout.stretch(1), 0)
        for index in (0, 1, 2):
            sidebar._mode_group.button(index).click()
            self.assertEqual(
                sidebar._settings_inner_layout.stretch(0), 0)
            self.assertEqual(
                sidebar._settings_inner_layout.stretch(1), 1)
        close_page(sidebar)

    def test_sidebar_short_mode_has_no_scrollbar(self):
        sidebar = Sidebar()
        sidebar.resize(260, 500)
        sidebar.show()
        sidebar._mode_group.button(1).click()
        APP.processEvents()
        self.assertEqual(
            sidebar._settings_scroll.verticalScrollBar().maximum(), 0)
        close_page(sidebar)

    def test_http_transfer_menu_is_only_visible_for_http_mode(self):
        sidebar = Sidebar()
        sidebar._mode_group.button(5).click()
        self.assertFalse(sidebar._btn_http_transfer_menu.isHidden())
        sidebar._mode_group.button(0).click()
        self.assertTrue(sidebar._btn_http_transfer_menu.isHidden())
        close_page(sidebar)

    def test_http_sidebar_transfer_signals_reach_http_page(self):
        with tempfile.TemporaryDirectory() as temp:
            window = MainWindow(temp)
            try:
                window.sidebar._mode_group.button(5).click()
                with mock.patch.object(
                        window._http_page, "import_interfaces") as import_api, \
                        mock.patch.object(
                            window._http_page, "export_interfaces") as export_api:
                    window.sidebar.http_import_requested.emit()
                    window.sidebar.http_export_requested.emit()
                import_api.assert_called_once_with(
                    window._current_project)
                export_api.assert_called_once_with(
                    window._current_project)
            finally:
                window.close()
                window.deleteLater()
                APP.processEvents()

    def test_http_page_snapshot(self):
        page = HTTPPage()
        self.assertEqual(page._document_tabs.count(), 0)
        self.assertEqual(page._active_document, -1)
        page._method.setCurrentText("POST")
        page._url.setText("https://example.com/api")
        page._set_body_type("raw")
        page._raw_format.setCurrentText("JSON")
        page._body.setPlainText('{"a": 1}')
        page._timeout.setValue(12)
        snapshot = page.snapshot()
        self.assertEqual(snapshot["method"], "POST")
        self.assertEqual(snapshot["body"], '{"a": 1}')
        self.assertEqual(snapshot["body_type"], "raw")
        self.assertEqual(snapshot["timeout"], 12)
        self.assertNotIn("auth_token", snapshot)
        restored = HTTPPage()
        restored.apply(snapshot)
        self.assertEqual(restored._document_tabs.count(), 0)
        self.assertEqual(restored._active_document, -1)
        close_page(restored)
        close_page(page)

    def test_http_response_formats_default_to_auto_and_highlight_json(self):
        page = HTTPPage()
        self.assertEqual(
            [page._response_format.itemText(index)
             for index in range(page._response_format.count())],
            ["JSON", "XML", "HTML", "Text", "Auto"],
        )
        self.assertEqual(page._response_format.currentText(), "Auto")
        page._response_body.setPlainText(
            '{"code":"0","ok":true,"count":12,"message":"成功"}')
        page._refresh_response_highlight()
        colors = {
            selection.format.foreground().color().name()
            for selection in page._response_body.extraSelections()
        }
        self.assertIn("#a31515", colors)
        self.assertIn("#0451a5", colors)
        self.assertIn("#098658", colors)
        page._response_format.setCurrentText("Text")
        self.assertEqual(page._response_body.extraSelections(), [])
        page._response_format.setCurrentText("Auto")
        self.assertTrue(page._response_body.extraSelections())
        page._response_body.setPlainText("<root><item /></root>")
        self.assertEqual(page._effective_response_format(), "XML")
        page._response_body.setPlainText("<!DOCTYPE html><html></html>")
        self.assertEqual(page._effective_response_format(), "HTML")
        close_page(page)

    def test_http_transfer_success_shows_top_toast(self):
        page = HTTPPage()
        page.resize(900, 700)
        page.show()
        APP.processEvents()
        try:
            page._show_http_toast("导入成功")
            APP.processEvents()
            self.assertTrue(page._http_toast.isVisible())
            self.assertEqual(page._http_toast.text(), "✓ 导入成功")
            self.assertLess(page._http_toast.y(), 30)
            self.assertAlmostEqual(
                page._http_toast.geometry().center().x(),
                page.rect().center().x(),
                delta=2,
            )

            import_dialog = mock.Mock()
            import_dialog.exec.return_value = QDialog.DialogCode.Accepted
            import_dialog.transfer_result = {
                "folders": [], "interfaces": []}
            import_dialog.as_new_project = False
            import_dialog.source_name = "测试项目"
            import_dialog.conflict_policy = "merge"
            with mock.patch(
                    "anhutoolbox.http_page.ImportTransferDialog",
                    return_value=import_dialog), \
                    mock.patch.object(
                        page, "_apply_transfer",
                        return_value=(1, 0)), \
                    mock.patch.object(
                        page, "_show_http_toast") as import_toast:
                page.import_interfaces()
            import_toast.assert_called_once_with("导入成功")

            with tempfile.TemporaryDirectory() as temp:
                export_dialog = mock.Mock()
                export_dialog.exec.return_value = QDialog.DialogCode.Accepted
                export_dialog.selected_format = "postman"
                path = os.path.join(temp, "export.json")
                with mock.patch(
                        "anhutoolbox.http_page.ExportTransferDialog",
                        return_value=export_dialog), \
                        mock.patch(
                            "anhutoolbox.http_page.QFileDialog."
                            "getSaveFileName",
                            return_value=(path, "")), \
                        mock.patch.object(
                            page, "_transfer_library",
                            return_value={
                                "folders": [],
                                "interfaces": [{"id": "x"}],
                                "environments": [],
                            }), \
                        mock.patch(
                            "anhutoolbox.http_page.build_transfer",
                            return_value={"item": []}), \
                        mock.patch.object(
                            page, "_show_http_toast") as export_toast:
                    page.export_interfaces("测试项目")
                export_toast.assert_called_once_with("导出成功")
        finally:
            close_page(page)

    def test_http_toast_is_centered_on_main_tab_row(self):
        with tempfile.TemporaryDirectory() as temp:
            window = MainWindow(temp)
            try:
                window.resize(1100, 720)
                window.show()
                window.sidebar._mode_group.button(5).click()
                APP.processEvents()
                page = window._http_page
                page._show_http_toast("导出成功")
                APP.processEvents()
                self.assertIs(
                    page._http_toast.parentWidget(), window)
                self.assertAlmostEqual(
                    page._http_toast.geometry().center().x(),
                    window.rect().center().x(),
                    delta=2,
                )
                self.assertEqual(page._http_toast.y(), 4)
            finally:
                window.close()
                window.deleteLater()
                APP.processEvents()

    def test_http_version_selector_is_inside_url_box(self):
        page = HTTPPage()
        page.new_document()
        self.assertEqual(
            [page._http_version.itemText(index)
             for index in range(page._http_version.count())],
            ["Auto", "http/1.1", "http/2"],
        )
        self.assertIs(
            page._url.parentWidget(), page._http_version.parentWidget())
        self.assertEqual(
            page._url.parentWidget().objectName(), "httpUrlShell")
        self.assertEqual(
            page._url.placeholderText(),
            "请输入URL或粘贴cURL文本",
        )
        self.assertTrue(page._url.parentWidget().testAttribute(
            Qt.WidgetAttribute.WA_StyledBackground))
        page._http_version.setCurrentIndex(
            page._http_version.findData("http/2"))
        self.assertEqual(page.snapshot()["http_version"], "http/2")
        page.apply({"http_version": "HTTP/1.1"})
        self.assertEqual(page._http_version.currentData(), "http/1.1")
        page.apply({"http_version": "http/2"})
        self.assertEqual(page._http_version.currentData(), "http/2")
        page.show()
        APP.processEvents()
        expected_margin = max(
            0.0,
            (
                page._url.viewport().height()
                - page._url.fontMetrics().height()
            ) / 2.0,
        )
        self.assertAlmostEqual(
            page._url.document().documentMargin(),
            expected_margin,
            places=1,
        )
        close_page(page)

    def test_http_save_creates_interface_and_clears_unsaved_dot(self):
        page = HTTPPage()
        page.new_document()
        saved = []
        page.save_requested.connect(lambda: saved.append(True))
        self.assertTrue(page._document_tabs.is_tab_dirty(0))

        page._method.setCurrentText("POST")
        page._url.setText("https://example.com/api/users")
        page._save_current_document()
        APP.processEvents()

        interfaces = page.interfaces()
        self.assertEqual(len(interfaces), 1)
        self.assertEqual(interfaces[0]["name"], "users")
        self.assertEqual(
            interfaces[0]["request"]["method"], "POST")
        self.assertEqual(saved, [True])
        self.assertFalse(page._document_tabs.is_tab_dirty(0))
        status_host = page._document_tabs.tabButton(
            0, page._document_tabs.ButtonPosition.RightSide)
        self.assertFalse(status_host.isHidden())
        self.assertEqual(status_host._dirty_label.text(), "")

        page._url.setText("https://example.com/api/users?page=2")
        self.assertTrue(page._document_tabs.is_tab_dirty(0))
        page._url.setText("https://example.com/api/users")
        self.assertFalse(page._document_tabs.is_tab_dirty(0))
        page.new_document()
        page._url.setText("https://example.com/draft")
        page._url.clear()
        self.assertTrue(page._document_tabs.is_tab_dirty(
            page._active_document))
        close_page(page)

    def test_http_interface_can_be_saved_without_a_url(self):
        page = HTTPPage()
        page.new_document()
        page._save_current_document()
        self.assertEqual(len(page.interfaces()), 1)
        interface = page.interfaces()[0]
        self.assertEqual(interface["request"]["url"], "")
        self.assertEqual(interface["name"], "接口 1")
        self.assertFalse(page._document_tabs.is_tab_dirty(0))
        close_page(page)

    def test_http_tabs_preserve_drafts_and_restore_saved_interfaces(self):
        page = HTTPPage()
        page.new_document()
        page._url.setText("https://example.com/api/first")
        page._save_current_document()
        first_id = page.interfaces()[0]["id"]

        page.new_document()
        self.assertEqual(page._document_tabs.count(), 2)
        page._url.setText("https://example.com/api/second")
        page._save_current_document()
        second_id = page.interfaces()[1]["id"]
        self.assertNotEqual(first_id, second_id)

        self.assertTrue(page.open_interface(first_id))
        self.assertEqual(
            page._url.text(), "https://example.com/api/first")
        page._url.setText("https://example.com/api/first/draft")
        page._document_tabs.setCurrentIndex(1)
        self.assertEqual(
            page._url.text(), "https://example.com/api/second")
        page._document_tabs.setCurrentIndex(0)
        self.assertEqual(
            page._url.text(), "https://example.com/api/first/draft")
        self.assertTrue(page._document_tabs.is_tab_dirty(0))

        snapshot = page.snapshot()
        restored = HTTPPage()
        restored.apply(snapshot)
        self.assertEqual(len(restored.interfaces()), 2)
        self.assertEqual(restored._document_tabs.count(), 2)
        self.assertEqual(
            restored._url.text(), "https://example.com/api/first/draft")
        self.assertTrue(restored._document_tabs.is_tab_dirty(0))
        close_page(restored)
        close_page(page)

    def test_sidebar_http_interface_list_filters_and_opens(self):
        sidebar = Sidebar()
        sidebar._mode_group.button(5).click()
        sidebar.set_http_interfaces([
            {
                "id": "api-1", "name": "用户列表", "method": "GET",
                "url": "https://example.com/users",
            },
            {
                "id": "api-2", "name": "创建订单", "method": "POST",
                "url": "https://example.com/orders",
            },
        ])
        selected = []
        created = []
        sidebar.http_interface_selected.connect(selected.append)
        sidebar.http_new_requested.connect(lambda: created.append(True))
        self.assertEqual(
            sidebar._http_interface_tree.topLevelItemCount(), 2)

        sidebar._http_api_search.setText("订单")
        visible_items = [
            sidebar._http_interface_tree.topLevelItem(index)
            for index in range(
                sidebar._http_interface_tree.topLevelItemCount())
            if not sidebar._http_interface_tree.topLevelItem(
                index).isHidden()
        ]
        self.assertEqual(len(visible_items), 1)
        item = visible_items[0]
        sidebar._on_http_interface_clicked(item, 1)
        self.assertEqual(selected, ["api-2"])

        sidebar._btn_http_new.click()
        self.assertEqual(created, [True])
        close_page(sidebar)

    def test_http_documents_show_hover_close_and_can_be_closed(self):
        page = HTTPPage()
        page.show()
        page.activateWindow()
        page.raise_()
        APP.processEvents()
        page.new_document()
        page.new_document()
        APP.processEvents()
        self.assertEqual(page._document_tabs.count(), 2)
        self.assertEqual(
            page._document_tabs.tabText(0), "未命名接口")
        self.assertTrue(page._document_tabs.is_tab_dirty(0))
        self.assertFalse(page._document_tabs.tabIcon(0).isNull())
        self.assertEqual(page._document_tabs.tabToolTip(0), "")
        fixed_tab_width = page._document_tabs.tabRect(0).width()
        self.assertEqual(fixed_tab_width, 220)
        self.assertEqual(
            page._document_tabs.tabRect(1).width(), fixed_tab_width)
        self.assertNotEqual(
            page._document_method_icon("GET").cacheKey(),
            page._document_method_icon("POST").cacheKey(),
        )
        initial_icon_width = page._document_tabs.iconSize().width()
        self.assertGreater(initial_icon_width, 0)
        page._method.setCurrentText("POST")
        APP.processEvents()
        self.assertEqual(
            page._document_tabs.tabRect(1).width(), fixed_tab_width)
        post_icon_width = page._document_tabs.iconSize().width()
        self.assertGreater(post_icon_width, initial_icon_width)
        page._method.setCurrentText("OPTIONS")
        APP.processEvents()
        self.assertEqual(
            page._document_tabs.tabRect(1).width(), fixed_tab_width)
        self.assertGreaterEqual(
            page._document_tabs.iconSize().width(), post_icon_width)
        self.assertFalse(page._document_tabs.usesScrollButtons())
        self.assertIsInstance(page._btn_new_document, QToolButton)
        self.assertEqual(page._btn_new_document.text(), "")
        self.assertFalse(page._btn_new_document.icon().isNull())
        self.assertEqual(page._btn_new_document.size().width(), 30)
        self.assertEqual(page._btn_new_document.size().height(), 30)
        self.assertFalse(any(
            button.objectName() == "httpSave"
            for button in page.findChildren(QPushButton)
        ))
        self.assertTrue((
            Path(__file__).resolve().parents[1]
            / "anhutoolbox" / "assets" / "add_interface.svg"
        ).is_file())
        tab_bar = page._document_tabs
        self.assertLess(
            tab_bar.x() + tab_bar.width(), page._btn_new_document.x())
        self.assertLess(
            page._btn_new_document.x(), page._btn_tab_more.x())
        self.assertLess(page._btn_tab_more.x(), page._btn_tab_prev.x())
        self.assertLess(page._btn_tab_prev.x(), page._btn_tab_next.x())
        self.assertLess(
            page._btn_tab_next.x(), page._btn_environment.x())
        self.assertLess(
            page._btn_environment.x() + page._btn_environment.width(),
            page.width())
        self.assertFalse(hasattr(page, "_btn_tab_dropdown"))
        self.assertFalse(page._btn_tab_more.icon().isNull())
        self.assertFalse(page._btn_tab_prev.icon().isNull())
        self.assertFalse(page._btn_tab_next.icon().isNull())
        self.assertFalse(page._btn_environment.icon().isNull())
        self.assertFalse(page._btn_send.icon().isNull())
        status_host = tab_bar.tabButton(
            1, tab_bar.ButtonPosition.RightSide)
        dirty_label = getattr(status_host, "_dirty_label", None)
        self.assertIsNotNone(dirty_label)
        self.assertTrue(dirty_label.isVisible())
        self.assertEqual(dirty_label.text(), "●")
        dirty_x = dirty_label.x()
        self.assertFalse(status_host._close_button.isVisible())
        QTest.mouseMove(tab_bar, tab_bar.tabRect(1).center())
        APP.processEvents()
        close_button = tab_bar.tabButton(
            1, tab_bar.ButtonPosition.RightSide)
        self.assertIsNotNone(close_button)
        self.assertTrue(close_button.isVisible())
        close_tool = close_button.findChild(QToolButton)
        self.assertIsNotNone(close_tool)
        self.assertEqual(dirty_label.x(), dirty_x)
        self.assertGreaterEqual(
            close_tool.x(), dirty_label.x() + dirty_label.width())
        for index in range(tab_bar.count()):
            if index == 1:
                continue
            other = tab_bar.tabButton(
                index, tab_bar.ButtonPosition.RightSide)
            self.assertTrue(other.isVisible())
            self.assertFalse(other._close_button.isVisible())
        with mock.patch(
                "anhutoolbox.http_page.UnsavedChangesDialog.ask",
                return_value="discard"):
            close_tool.click()
        APP.processEvents()
        self.assertEqual(page._document_tabs.count(), 1)
        close_page(page)

    def test_http_documents_keep_independent_response_state(self):
        page = HTTPPage()
        page.new_document()
        page._status.setText("200 OK")
        page._elapsed.setText("12 ms")
        page._size.setText("2 B")
        page._response_body.setPlainText('{"name":"first"}')
        page._response_format.setCurrentText("XML")
        page._console.setPlainText("first console")
        page._actual_method.setText("POST")
        page._actual_url.setText("https://example.com/first")
        page._request_tabs.setCurrentIndex(3)
        page._set_table_rows(
            page._response_headers,
            [["Content-Type", "application/json"]],
        )
        first_index = page._active_document

        page.new_document()
        self.assertEqual(page._status.text(), "等待请求")
        self.assertEqual(page._response_body.toPlainText(), "")
        page._status.setText("404 Not Found")
        page._response_body.setPlainText("second response")
        page._response_format.setCurrentText("HTML")
        page._request_tabs.setCurrentIndex(1)
        second_index = page._active_document

        page._document_tabs.setCurrentIndex(first_index)
        APP.processEvents()
        self.assertEqual(page._status.text(), "200 OK")
        self.assertEqual(page._elapsed.text(), "12 ms")
        self.assertEqual(page._size.text(), "2 B")
        self.assertEqual(
            page._response_body.toPlainText(), '{"name":"first"}')
        self.assertEqual(
            page._response_headers.item(0, 1).text(),
            "application/json",
        )
        self.assertEqual(page._actual_method.text(), "POST")
        self.assertEqual(
            page._actual_url.text(), "https://example.com/first")
        self.assertEqual(page._response_format.currentText(), "XML")
        self.assertEqual(page._request_tabs.currentIndex(), 3)

        page._document_tabs.setCurrentIndex(second_index)
        APP.processEvents()
        self.assertEqual(page._status.text(), "404 Not Found")
        self.assertEqual(
            page._response_body.toPlainText(), "second response")
        self.assertEqual(page._response_format.currentText(), "HTML")
        self.assertEqual(page._request_tabs.currentIndex(), 1)
        close_page(page)

    def test_http_late_response_is_saved_to_origin_document(self):
        page = HTTPPage()
        page.new_document()
        origin = page._active_doc()
        origin_index = page._active_document
        origin_request = {
            "method": "GET",
            "url": "https://example.com/origin",
            "params": [],
            "path_params": [],
            "headers": {},
            "content": None,
        }
        page._request_document_key = id(origin)
        page._request_document_request = origin_request
        page._last_request = origin_request
        page.new_document()
        current = page._active_doc()
        current_index = page._active_document
        page._response_body.setPlainText("current untouched")

        result = {
            "status": 200,
            "reason": "OK",
            "content": b'{"origin":true}',
            "headers": [{
                "name": "Content-Type", "value": "application/json",
            }],
            "cookies": [],
            "history": [],
            "elapsed_ms": 25,
            "request": {
                "method": "GET",
                "url": "https://example.com/origin",
                "headers": {},
                "content": b"",
            },
        }
        page._apply_request_result(
            "ok", result, id(origin), origin_request)
        APP.processEvents()
        self.assertIs(page._active_doc(), current)
        self.assertEqual(
            page._response_body.toPlainText(), "current untouched")

        page._document_tabs.setCurrentIndex(origin_index)
        APP.processEvents()
        self.assertIn(
            '"origin": true', page._response_body.toPlainText())
        self.assertEqual(page._status.text(), "200 OK")
        self.assertEqual(page._elapsed.text(), "25 ms")
        self.assertIs(page._active_doc(), origin)
        self.assertEqual(current_index, 1)
        close_page(page)

    def test_http_design_assets_and_compact_layout_are_consistent(self):
        root = Path(__file__).resolve().parents[1]
        icon_names = [
            "http_more.svg",
            "http_previous.svg",
            "http_next.svg",
            "http_environment.svg",
            "http_chevron_down.svg",
            "http_send.svg",
            "http_add.svg",
            "http_delete.svg",
            "http_upload.svg",
            "http_format.svg",
            "http_raw.svg",
            "http_copy.svg",
            "http_save.svg",
            "http_example.svg",
            "http_edit.svg",
            "http_close.svg",
        ]
        spec_text = (root / "AnhuToolbox.spec").read_text(encoding="utf-8")
        for icon_name in icon_names:
            self.assertTrue(
                (root / "anhutoolbox" / "assets" / icon_name).is_file())
            self.assertIn(icon_name, spec_text)

        page = HTTPPage()
        page.show()
        chevron = page._btn_environment._chevron
        self.assertFalse(chevron.pixmap().isNull())
        self.assertLessEqual(
            abs(
                chevron.geometry().center().y()
                - page._btn_environment.rect().center().y()
            ),
            1,
        )
        self.assertEqual(
            page._raw_format.font().family(), "Microsoft YaHei UI")
        self.assertEqual(
            page._raw_format.view().font().family(), "Microsoft YaHei UI")
        self.assertFalse(page._raw_format.view().font().bold())
        page.resize(840, 700)
        APP.processEvents()
        self.assertTrue(page._body_hint.isHidden())
        self.assertLessEqual(page._btn_environment.maximumWidth(), 210)
        page.resize(1280, 800)
        APP.processEvents()
        self.assertFalse(page._body_hint.isHidden())
        self.assertLessEqual(page._btn_environment.maximumWidth(), 240)
        self.assertEqual(page._btn_body_pretty.text(), "")
        self.assertEqual(page._btn_load_binary.text(), "")
        close_page(page)

    def test_http_tab_navigation_uses_custom_arrow_buttons(self):
        page = HTTPPage()
        self.assertFalse(page._document_tabs.usesScrollButtons())
        self.assertFalse(page._btn_tab_prev.isEnabled())
        self.assertFalse(page._btn_tab_next.isEnabled())
        while page._document_tabs.count() < 5:
            page.new_document()
        APP.processEvents()
        self.assertEqual(page._document_tabs.count(), 5)
        self.assertFalse(page._document_tabs.usesScrollButtons())
        self.assertTrue(page._btn_tab_prev.isEnabled())
        self.assertTrue(page._btn_tab_next.isEnabled())
        page._btn_tab_next.click()
        APP.processEvents()
        self.assertEqual(page._document_tabs.currentIndex(), 0)
        for index in reversed(range(1, 5)):
            page._close_document(index)
        self.assertEqual(page._document_tabs.count(), 1)
        self.assertFalse(page._btn_tab_prev.isEnabled())
        self.assertFalse(page._btn_tab_next.isEnabled())
        close_page(page)

    def test_http_environment_is_local_persisted_and_resolves_request(self):
        page = HTTPPage()
        page.new_document()
        page._environments = [{
            "id": "test-env",
            "name": "测试环境",
            "variables": [
                {"name": "path_value", "value": "A B", "description": ""},
                {"name": "direct_query", "value": "direct", "description": ""},
                {"name": "query_name", "value": "q", "description": ""},
                {"name": "query_value", "value": "hello", "description": ""},
                {"name": "header_suffix", "value": "Test", "description": ""},
                {"name": "header_value", "value": "yes", "description": ""},
                {"name": "cookie_name", "value": "session", "description": ""},
                {"name": "cookie_value", "value": "abc", "description": ""},
                {"name": "body_value", "value": "anhu", "description": ""},
                {"name": "token", "value": "secret-token", "description": ""},
            ],
        }]
        page._active_environment_id = "test-env"
        page._refresh_environment_button()
        self.assertIn("测试环境", page._btn_environment.text())

        page._url.setText(
            "http://example.com/api/{{id}}?direct={{direct_query}}")
        page._set_entries(page._path_params, [{
            "name": "id", "value": "{{path_value}}", "enabled": True,
        }])
        page._set_entries(page._params, [{
            "name": "{{query_name}}",
            "value": "{{query_value}}",
            "enabled": True,
        }])
        page._set_entries(page._http_headers, [{
            "name": "X-{{header_suffix}}",
            "value": "{{header_value}}",
            "enabled": True,
        }])
        page._set_entries(page._request_cookies, [{
            "name": "{{cookie_name}}",
            "value": "{{cookie_value}}",
            "enabled": True,
        }])
        page._set_body_type("raw")
        page._raw_format.setCurrentText("JSON")
        page._body.setPlainText('{"name":"{{body_value}}"}')
        page._auth_type.setCurrentText("Bearer")
        page._auth_token.setText("{{token}}")

        worker = mock.Mock()
        worker.isRunning.return_value = False
        worker.pop_event.return_value = None
        with mock.patch(
                "anhutoolbox.http_page.HTTPRequestWorker",
                return_value=worker):
            page._send()

        request = page._last_request
        self.assertEqual(
            request["url"],
            "http://example.com/api/A%20B?direct=direct")
        self.assertEqual(request["params"], [("q", "hello")])
        self.assertEqual(request["path_params"], [("id", "A B")])
        self.assertEqual(request["headers"]["X-Test"], "yes")
        self.assertEqual(
            request["headers"]["Cookie"], "session=abc")
        self.assertEqual(
            request["headers"]["Authorization"], "Bearer secret-token")
        self.assertEqual(
            request["content"], b'{"name":"anhu"}')
        self.assertIn("{{id}}", page._url.text())
        self.assertEqual(
            page._params.item(0, 2).text(), "{{query_value}}")

        snapshot = page.snapshot()
        self.assertEqual(
            snapshot["active_environment"], "test-env")
        self.assertEqual(
            snapshot["environments"][0]["variables"][0]["name"],
            "path_value")
        restored = HTTPPage()
        restored.apply(snapshot)
        self.assertEqual(
            restored._active_environment_id, "test-env")
        self.assertIn("测试环境", restored._btn_environment.text())

        dialog = EnvironmentManagerDialog(
            snapshot["environments"], snapshot["active_environment"])
        self.assertEqual(
            [dialog._variables.horizontalHeaderItem(index).text()
             for index in range(dialog._variables.columnCount())],
            ["", "变量名", "本地值", "描述"],
        )
        self.assertIn(
            "不使用云端数据",
            " ".join(label.text() for label in dialog.findChildren(QLabel)))
        dialog.close()
        dialog.deleteLater()
        close_page(restored)
        close_page(page)

    def test_http_url_environment_completion_and_highlight(self):
        page = HTTPPage()
        page._environments = [{
            "id": "test-env",
            "name": "测试环境",
            "variables": [
                {"name": "host", "value": "http://127.0.0.1:5000"},
                {"name": "token", "value": "abc"},
            ],
        }]
        page._active_environment_id = "test-env"
        page.show()
        page._url.setFocus()
        APP.processEvents()

        QTest.keyClicks(page._url, "{{ho")
        APP.processEvents()
        completer = page._url._completer
        self.assertTrue(completer.popup().isVisible())
        self.assertEqual(completer.completionCount(), 1)
        QTest.keyClick(page._url, Qt.Key.Key_Return)
        APP.processEvents()
        self.assertEqual(page._url.text(), "{{host}}")
        self.assertFalse(completer.popup().isVisible())

        page._url.setText("{{host}}/api/status")
        APP.processEvents()
        formats = page._url.document().firstBlock().layout().formats()
        variable_formats = [
            item for item in formats
            if item.format.foreground().color().name() == "#00a6a6"
        ]
        self.assertTrue(variable_formats)
        self.assertEqual(variable_formats[0].start, 0)
        self.assertEqual(variable_formats[0].length, len("{{host}}"))
        close_page(page)

    def test_http_environment_menu_actions_use_aligned_icons(self):
        page = HTTPPage()
        page._environments = [
            {"id": "default", "name": "默认环境", "variables": []},
            {"id": "test", "name": "测试环境", "variables": []},
        ]
        page._active_environment_id = "default"
        menu, environment_actions, new_environment, manage = (
            page._build_environment_menu())
        self.assertEqual(new_environment.text(), "新建环境")
        self.assertFalse(new_environment.icon().isNull())
        self.assertFalse(manage.icon().isNull())
        for action, environment_id in environment_actions.items():
            self.assertTrue(action.icon().isNull())
            self.assertEqual(
                action.isChecked(), environment_id == "default")
        close_page(page)

    def test_http_environment_menu_closes_and_focuses_url_on_click(self):
        page = HTTPPage()
        page.show()
        page.activateWindow()
        page.raise_()
        APP.processEvents()
        QTimer.singleShot(0, page._show_environment_menu)
        QTimer.singleShot(
            50,
            lambda: QTest.mouseClick(
                page._url.viewport(),
                Qt.MouseButton.LeftButton,
                pos=QPoint(100, 10),
            ),
        )
        QTimer.singleShot(
            200,
            lambda: (
                page._environment_menu.close()
                if page._environment_menu is not None else None
            ),
        )
        QTest.qWait(300)
        self.assertIsNone(page._environment_menu)
        click_position = page._url.viewport().mapToGlobal(
            QPoint(100, 10))
        self.assertIs(
            page._url_focus_target_at(click_position), page._url)
        close_page(page)

    def test_http_environment_blocks_undefined_or_cyclic_variables(self):
        page = HTTPPage()
        page.new_document()
        page._environments = [{
            "id": "cycle-env",
            "name": "循环环境",
            "variables": [
                {"name": "first", "value": "{{second}}"},
                {"name": "second", "value": "{{first}}"},
            ],
        }]
        page._active_environment_id = "cycle-env"
        page._url.setText("http://example.com/{{missing}}")
        with mock.patch(
                "anhutoolbox.http_page.show_warning") as warning:
            page._send()
        warning.assert_called_once()
        self.assertEqual(warning.call_args.args[1], "环境变量错误")
        self.assertIn("missing", warning.call_args.args[2])
        self.assertIsNone(page._worker)

        page._url.setText("http://example.com/{{first}}")
        with mock.patch(
                "anhutoolbox.http_page.show_warning") as warning:
            page._send()
        warning.assert_called_once()
        self.assertIn("循环引用", warning.call_args.args[2])
        close_page(page)

    def test_http_environment_resolves_every_body_type(self):
        page = HTTPPage()
        resolver = EnvironmentResolver({
            "variables": [
                {"name": "text", "value": "anhu"},
                {"name": "hex", "value": "01 02 FF"},
            ],
        })

        headers = {}
        page._set_body_type("urlencoded")
        page._body.setPlainText("name={{text}}")
        self.assertEqual(
            page._request_body(headers, resolver), b"name=anhu")

        headers = {}
        page._set_body_type("form-data")
        page._body.setPlainText("name={{text}}")
        self.assertIn(
            b"anhu", page._request_body(headers, resolver))

        headers = {}
        page._set_body_type("binary")
        page._body.setPlainText("{{hex}}")
        self.assertEqual(
            page._request_body(headers, resolver), b"\x01\x02\xff")

        headers = {}
        page._set_body_type("msgpack")
        page._body.setPlainText('{"name":"{{text}}"}')
        self.assertEqual(
            msgpack.unpackb(
                page._request_body(headers, resolver), raw=False),
            {"name": "anhu"},
        )

        headers = {}
        page._set_body_type("raw")
        page._raw_format.setCurrentText("Text")
        page._body.setPlainText("hello {{text}}")
        self.assertEqual(
            page._request_body(headers, resolver), b"hello anhu")
        close_page(page)

    def test_environment_manager_rejects_invalid_or_duplicate_variables(self):
        dialog = EnvironmentManagerDialog([
            {
                "id": "first",
                "name": "环境一",
                "variables": [
                    {"name": "duplicate", "value": "1"},
                    {"name": "duplicate", "value": "2"},
                ],
            },
            {"id": "second", "name": "环境二", "variables": []},
        ], "second")
        self.assertEqual(
            dialog.objectName(), "httpEnvironmentDialog")
        self.assertEqual(
            dialog._environment_list.objectName(),
            "httpEnvironmentList",
        )
        self.assertIn("QListWidget#httpEnvironmentList", dialog.styleSheet())
        self.assertIn("#EAF4FF", dialog._variables.styleSheet())
        button_texts = {
            button.text() for button in dialog.findChildren(QPushButton)
        }
        self.assertIn("新建环境", button_texts)
        self.assertIn("添加变量", button_texts)
        dialog._environments[0]["variables"] = [
            {"name": "duplicate", "value": "1", "description": ""},
            {"name": "duplicate", "value": "2", "description": ""},
        ]
        with mock.patch(
                "anhutoolbox.http_environments.show_warning") as warning:
            dialog._save()
        warning.assert_called_once()
        self.assertEqual(warning.call_args.args[1], "变量名重复")

        dialog._environments[0]["variables"] = []
        dialog._refresh_environment_list("second")
        dialog._name.clear()
        with mock.patch(
                "anhutoolbox.http_environments.show_warning") as warning:
            dialog._save()
        warning.assert_called_once()
        self.assertEqual(warning.call_args.args[1], "环境名称无效")
        dialog.close()
        dialog.deleteLater()

    def test_environment_variable_delete_uses_only_checkboxes(self):
        dialog = EnvironmentManagerDialog([{
            "id": "default",
            "name": "默认环境",
            "variables": [
                {"name": "first", "value": "1", "description": ""},
                {"name": "second", "value": "2", "description": ""},
                {"name": "third", "value": "3", "description": ""},
            ],
        }], "default")
        table = dialog._variables
        self.assertEqual(table.columnCount(), 4)
        self.assertEqual(
            [table.horizontalHeaderItem(index).text()
             for index in range(table.columnCount())],
            ["", "变量名", "本地值", "描述"],
        )
        buttons_by_text = {
            button.text(): button
            for button in dialog.findChildren(QPushButton)
        }
        self.assertTrue(buttons_by_text["保存"].icon().isNull())
        self.assertTrue(buttons_by_text["取消"].icon().isNull())

        table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
        table.item(2, 0).setCheckState(Qt.CheckState.Unchecked)
        table.selectRow(0)
        dialog._remove_variables()
        self.assertEqual(table.rowCount(), 2)
        self.assertEqual(
            [table.item(row, 1).text() for row in range(table.rowCount())],
            ["first", "third"],
        )

        table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
        table.item(1, 0).setCheckState(Qt.CheckState.Unchecked)
        table.selectRow(1)
        with mock.patch(
                "anhutoolbox.http_environments.show_information") as info:
            dialog._remove_variables()
        info.assert_called_once()
        self.assertEqual(table.rowCount(), 2)
        dialog.close()
        dialog.deleteLater()

    def test_http_tab_actions_match_reference_and_support_force_close(self):
        page = HTTPPage()
        page.new_document()
        page._url.setText("https://example.com/api/first")
        page._save_current_document()
        page.new_document()
        page._url.setText("https://example.com/api/second")
        menu, actions = page._build_tab_actions_menu()
        self.assertEqual(
            [action.text() for action in menu.actions() if action.text()],
            [
                "关闭所有标签",
                "强制关闭所有标签",
                "关闭其他标签",
                "强制关闭其他所有标签",
                "保存所有标签",
            ],
        )
        self.assertIn("force_close_all", actions)
        self.assertIn("force_close_others", actions)
        with mock.patch(
                "anhutoolbox.http_page.UnsavedChangesDialog.ask",
                return_value="discard"):
            page._close_other_documents()
        self.assertEqual(page._document_tabs.count(), 1)
        self.assertEqual(
            page._url.text(), "https://example.com/api/second")

        page.new_document()
        page._url.setText("https://example.com/api/third")
        with mock.patch(
                "anhutoolbox.http_page.UnsavedChangesDialog.ask") as ask:
            page._close_all_documents(force=True)
        ask.assert_not_called()
        self.assertEqual(page._document_tabs.count(), 0)
        self.assertEqual(page._url.text(), "")
        close_page(page)

    def test_http_unsaved_tab_close_cancel_discard_and_save(self):
        page = HTTPPage()
        page.new_document()
        page._url.setText("https://example.com/api/current")
        with mock.patch(
                "anhutoolbox.http_page.UnsavedChangesDialog.ask",
                return_value="cancel"):
            page._request_close_document(page._active_document)
        self.assertEqual(page._document_tabs.count(), 1)
        self.assertEqual(
            page._url.text(), "https://example.com/api/current")

        with mock.patch(
                "anhutoolbox.http_page.UnsavedChangesDialog.ask",
                return_value="discard"):
            page._request_close_document(page._active_document)
        self.assertEqual(page._document_tabs.count(), 0)
        self.assertEqual(page._url.text(), "")

        page.new_document()
        page._url.setText("https://example.com/api/saved-on-close")
        with mock.patch(
                "anhutoolbox.http_page.UnsavedChangesDialog.ask",
                return_value="save"):
            page._request_close_document(page._active_document)
        self.assertEqual(page._document_tabs.count(), 0)
        self.assertEqual(page._url.text(), "")
        self.assertEqual(len(page.interfaces()), 1)
        self.assertEqual(
            page.interfaces()[0]["request"]["url"],
            "https://example.com/api/saved-on-close",
        )
        close_page(page)

    def test_http_unsaved_dialog_uses_correct_message_and_actions(self):
        dialog = UnsavedChangesDialog([
            {"name": "未命名接口"},
        ])
        self.assertEqual(dialog.windowTitle(), "提示")
        self.assertEqual(dialog.icon(), QMessageBox.Icon.Warning)
        message = dialog.text()
        self.assertIn("接口「未命名接口」尚未保存", message)
        self.assertIn("未保存的修改将丢失", message)
        self.assertNotIn("确定继续吗", message)
        buttons = dialog.findChildren(QPushButton)
        button_texts = {button.text() for button in buttons}
        self.assertEqual(
            button_texts, {"取消", "不保存", "保存并关闭"})
        self.assertTrue(all(button.icon().isNull() for button in buttons))
        dialog.close()
        dialog.deleteLater()

    def test_http_tab_context_menu_renames_and_saves_interface(self):
        page = HTTPPage()
        page.new_document()
        page._url.setText("https://example.com/api/original")
        self.assertTrue(page._save_shortcut.isEnabled())
        page._save_current_document()
        page._url.setText("https://example.com/api/original?changed=1")
        self.assertTrue(page._document_tabs.is_tab_dirty(0))

        menu, rename, save = page._build_document_tab_menu()
        action_texts = [
            action.text() for action in menu.actions() if action.text()]
        self.assertEqual(action_texts, ["重命名", "保存"])
        self.assertIsNotNone(rename)
        self.assertIsNotNone(save)

        with mock.patch(
                "anhutoolbox.http_page.get_text",
                return_value=("重命名接口", True)):
            page._rename_current_document()
        self.assertEqual(
            page.interfaces()[0]["name"], "重命名接口")
        self.assertIn("重命名接口", page._document_tabs.tabText(0))
        self.assertTrue(page._document_tabs.is_tab_dirty(0))

        page._save_current_document()
        self.assertFalse(page._document_tabs.is_tab_dirty(0))
        self.assertEqual(
            page.interfaces()[0]["name"], "重命名接口")
        close_page(page)

    def test_http_folders_and_interface_names_are_project_scoped(self):
        page = HTTPPage()
        parent = page.create_folder("业务接口")
        child = page.create_folder("订单", parent)
        page.set_current_folder(child)
        page.new_document()
        page._url.setText("https://example.com/api/orders")
        page._save_current_document()
        api_id = page.interfaces()[0]["id"]
        self.assertEqual(page.interfaces()[0]["folder_id"], child)
        self.assertTrue(page.rename_interface(api_id, "创建订单"))
        self.assertTrue(page.rename_folder(child, "订单管理"))

        snapshot = page.snapshot()
        restored = HTTPPage()
        restored.apply(snapshot)
        self.assertEqual(
            {item["name"] for item in restored.folders()},
            {"业务接口", "订单管理"},
        )
        self.assertEqual(
            restored.interfaces()[0]["name"], "创建订单")
        self.assertEqual(
            restored.interfaces()[0]["folder_id"], child)
        archive = page.create_folder("归档", parent)
        self.assertTrue(page.move_interface(api_id, archive))
        self.assertEqual(page.interfaces()[0]["folder_id"], archive)
        self.assertEqual(
            page.snapshot()["documents"][0]["folder_id"], archive)
        self.assertTrue(page.move_interface(api_id, None))
        self.assertIsNone(page.interfaces()[0]["folder_id"])
        close_page(restored)
        close_page(page)

    def test_http_duplicate_delete_and_folder_delete(self):
        page = HTTPPage()
        root = page.create_folder("项目")
        child = page.create_folder("子目录", root)
        page.set_current_folder(child)
        page.new_document()
        page._url.setText("https://example.com/api/first")
        page._save_current_document()
        source_id = page.interfaces()[0]["id"]
        self.assertTrue(page.duplicate_interface(source_id))
        self.assertEqual(len(page.interfaces()), 2)
        self.assertTrue(
            page.interfaces()[1]["name"].startswith("first 副本"))

        self.assertTrue(page.delete_interface(source_id))
        self.assertEqual(len(page.interfaces()), 1)
        duplicate_id = page.interfaces()[0]["id"]
        self.assertTrue(page.delete_folder(root))
        self.assertEqual(page.folders(), [])
        self.assertEqual(page.interfaces(), [])
        self.assertEqual(page._document_tabs.count(), 0)
        self.assertEqual(page.snapshot()["documents"], [])
        self.assertFalse(page.delete_interface(duplicate_id))
        close_page(page)

    def test_sidebar_http_folder_tree_and_rename_actions(self):
        sidebar = Sidebar()
        sidebar._mode_group.button(5).click()
        sidebar.set_http_folders([
            {"id": "folder-1", "name": "业务接口", "parent_id": None},
        ])
        sidebar.set_http_interfaces([
            {
                "id": "api-1", "name": "用户列表", "method": "GET",
                "url": "https://example.com/users",
                "folder_id": "folder-1",
            },
        ])
        folder_item = sidebar._http_interface_tree.topLevelItem(0)
        self.assertEqual(folder_item.text(0), "业务接口")
        self.assertEqual(folder_item.childCount(), 1)
        self.assertEqual(folder_item.child(0).text(0), "用户列表")
        self.assertEqual(
            sidebar._http_interface_tree.indentation(), 22)
        self.assertIn(
            "http_next.svg",
            sidebar._http_interface_tree.styleSheet(),
        )
        self.assertIn(
            "http_chevron_down.svg",
            sidebar._http_interface_tree.styleSheet(),
        )
        self.assertFalse(
            sidebar._http_interface_tree.expandsOnDoubleClick())
        initial_expanded = folder_item.isExpanded()
        sidebar._http_interface_tree.itemDoubleClicked.emit(
            folder_item, 0)
        self.assertNotEqual(folder_item.isExpanded(), initial_expanded)
        sidebar._http_interface_tree.itemDoubleClicked.emit(
            folder_item, 0)
        self.assertEqual(folder_item.isExpanded(), initial_expanded)
        interface_item = folder_item.child(0)
        sidebar._http_interface_tree.itemDoubleClicked.emit(
            interface_item, 0)
        self.assertFalse(
            sidebar._http_interface_tree.isPersistentEditorOpen(
                interface_item, 0))

        renames = []
        folder_events = []
        sidebar.http_rename_requested.connect(
            lambda *values: renames.append(values))
        sidebar.http_folder_selected.connect(folder_events.append)
        self.assertFalse(
            folder_item.flags() & Qt.ItemFlag.ItemIsSelectable)
        self.assertTrue(
            folder_item.child(0).flags()
            & Qt.ItemFlag.ItemIsSelectable)
        folder_item.setText(0, "核心业务")
        APP.processEvents()
        self.assertEqual(
            renames[-1], ("folder", "folder-1", "核心业务"))
        folder_event_count = len(folder_events)
        sidebar._on_http_interface_clicked(folder_item, 1)
        self.assertEqual(len(folder_events), folder_event_count)

        interface_item = folder_item.child(0)
        menu, actions = sidebar._build_http_library_menu(
            interface_item)
        move_action = next(
            action for action in menu.actions()
            if action.text() == "移动至...")
        move_texts = [
            action.text() for action in move_action.menu().actions()
            if action.text()
        ]
        self.assertIn("全部接口（根目录）", move_texts)
        self.assertIn("业务接口", move_texts)
        menu_texts = [action.text() for action in menu.actions()]
        self.assertIn("复制接口", menu_texts)
        self.assertIn("删除接口", menu_texts)
        self.assertIn("全部展开", menu_texts)
        self.assertIn("全部折叠", menu_texts)
        self.assertIsNotNone(actions["duplicate"])
        self.assertIsNotNone(actions["delete"])
        folder_menu, folder_actions = sidebar._build_http_library_menu(
            folder_item)
        self.assertEqual(folder_actions["delete"].text(), "删除文件夹")
        self.assertFalse(folder_actions["duplicate"].isEnabled())
        close_page(sidebar)

    def test_sidebar_http_keeps_expansion_and_scrolls_nested_tree(self):
        self.assertIn(
            "QScrollBar::add-line:horizontal, "
            "QScrollBar::sub-line:horizontal",
            GLOBAL_STYLE,
        )
        sidebar = Sidebar()
        sidebar._mode_group.button(5).click()
        sidebar.set_http_folders([
            {"id": "root", "name": "一级文件夹", "parent_id": None},
            {"id": "child", "name": "二级文件夹", "parent_id": "root"},
        ])
        sidebar.set_http_interfaces([])
        sidebar.resize(260, 700)
        sidebar.show()
        APP.processEvents()
        root = sidebar._http_folder_items["root"]
        child = sidebar._http_folder_items["child"]
        folder_contexts = []
        sidebar.http_folder_selected.connect(folder_contexts.append)
        sidebar._btn_http_new.click()
        self.assertIsNone(folder_contexts[-1])
        root.setExpanded(True)
        child.setExpanded(True)
        APP.processEvents()
        self.assertEqual(folder_contexts[-1], "child")
        sidebar._btn_http_new.click()
        self.assertEqual(folder_contexts[-1], "child")
        child.setExpanded(False)
        APP.processEvents()
        self.assertEqual(folder_contexts[-1], "root")
        root.setExpanded(False)
        APP.processEvents()
        self.assertIsNone(folder_contexts[-1])
        root.setExpanded(True)
        child.setExpanded(True)

        sidebar._http_interface_tree.setCurrentItem(child)
        folder_requests = []
        sidebar.http_new_folder_requested.connect(
            lambda name, parent: folder_requests.append((name, parent)))
        with mock.patch(
                "anhutoolbox.sidebar.get_text",
                return_value=("三级文件夹", True)):
            sidebar._create_http_folder()
        self.assertEqual(folder_requests, [("三级文件夹", "child")])
        sidebar.set_http_folders([
            {"id": "root", "name": "一级文件夹", "parent_id": None},
            {"id": "child", "name": "二级文件夹", "parent_id": "root"},
            {
                "id": "grandchild",
                "name": "三级文件夹名称很长很长很长很长很长",
                "parent_id": "child",
            },
        ])
        sidebar.set_http_interfaces([{
            "id": "draft",
            "name": "未保存接口名称很长很长很长很长很长",
            "method": "POST",
            "url": "https://example.com/long/path",
            "folder_id": "grandchild",
            "dirty": True,
            "draft": True,
        }])
        self.assertTrue(sidebar._http_folder_items["root"].isExpanded())
        self.assertTrue(sidebar._http_folder_items["child"].isExpanded())
        sidebar._http_folder_items["grandchild"].setExpanded(True)
        QTest.qWait(10)
        APP.processEvents()
        tree = sidebar._http_interface_tree
        self.assertGreater(tree.columnWidth(0), tree.viewport().width())
        horizontal = tree.horizontalScrollBar()
        self.assertGreater(horizontal.maximum(), 0)
        self.assertTrue(horizontal.isVisible())
        close_page(sidebar)

    def test_unsaved_http_document_appears_in_library_immediately(self):
        page = HTTPPage()
        sidebar = Sidebar()
        sidebar._mode_group.button(5).click()
        sidebar.show()
        page.interfaces_changed.connect(sidebar.set_http_interfaces)
        page.folders_changed.connect(sidebar.set_http_folders)
        page.active_interface_changed.connect(
            sidebar.select_http_interface)
        folder_id = page.create_folder("草稿目录")
        page.set_current_folder(folder_id)
        page.new_document()
        APP.processEvents()

        draft = page._active_doc()
        self.assertIsNotNone(draft)
        self.assertTrue(draft["dirty"])
        self.assertEqual(page.interfaces(), [])
        self.assertTrue(page._document_tabs.is_tab_dirty(
            page._active_document))
        draft_item = sidebar._http_interface_items.get(draft["api_id"])
        self.assertIsNotNone(draft_item)
        self.assertEqual(
            draft_item.parent().data(0, Qt.ItemDataRole.UserRole),
            folder_id,
        )
        self.assertTrue(
            sidebar._http_folder_items[folder_id].isExpanded())

        page._save_current_document()
        APP.processEvents()
        self.assertEqual(len(page.interfaces()), 1)
        self.assertEqual(
            page.interfaces()[0]["id"], draft["api_id"])
        self.assertIn(
            draft["api_id"], sidebar._http_interface_items)
        close_page(sidebar)
        close_page(page)

    def test_http_library_ellipsis_uses_the_context_menu_entry(self):
        sidebar = Sidebar()
        sidebar._mode_group.button(5).click()
        sidebar.set_http_folders([
            {"id": "folder-1", "name": "业务接口", "parent_id": None},
        ])
        sidebar.set_http_interfaces([{
            "id": "api-1",
            "name": "用户列表",
            "method": "GET",
            "url": "https://example.com/users",
            "folder_id": "folder-1",
        }])
        sidebar.show()
        folder_item = sidebar._http_interface_tree.topLevelItem(0)
        folder_item.setExpanded(True)
        APP.processEvents()
        item = folder_item.child(0)
        sidebar._http_interface_tree.setCurrentItem(item)

        menu_requests = []
        opened_interfaces = []
        tree = sidebar._http_interface_tree
        tree.menu_requested.disconnect()
        tree.menu_requested.connect(menu_requests.append)
        sidebar.http_interface_selected.connect(opened_interfaces.append)
        button_rect = tree.menu_button_rect(item)
        self.assertGreater(button_rect.width(), 0)
        self.assertIn("branch:selected", tree.styleSheet())
        tree._set_hovered_item(item)
        self.assertIs(tree.hovered_item, item)

        QTest.mouseClick(
            tree.viewport(), Qt.MouseButton.LeftButton,
            pos=button_rect.center())
        APP.processEvents()
        self.assertEqual(len(menu_requests), 1)
        self.assertEqual(opened_interfaces, [])
        close_page(sidebar)

    def test_http_library_scroll_reaches_the_last_interface(self):
        sidebar = Sidebar()
        sidebar._mode_group.button(5).click()
        sidebar.set_http_interfaces([{
            "id": "api-{}".format(index),
            "name": "接口 {}".format(index),
            "method": "GET",
            "url": "https://example.com/{}".format(index),
            "folder_id": None,
        } for index in range(30)])
        sidebar.resize(260, 700)
        sidebar.show()
        APP.processEvents()
        tree = sidebar._http_interface_tree
        self.assertEqual(
            sidebar._settings_inner_layout.stretch(0), 1)
        self.assertEqual(
            sidebar._settings_inner_layout.stretch(1), 0)
        self.assertGreater(tree.viewport().height(), 200)
        self.assertEqual(
            tree.verticalScrollMode(),
            QAbstractItemView.ScrollMode.ScrollPerPixel,
        )
        bar = tree.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0)
        bar.setValue(bar.maximum())
        APP.processEvents()
        last_item = sidebar._http_interface_items["api-29"]
        self.assertLessEqual(
            tree.visualItemRect(last_item).bottom(),
            tree.viewport().rect().bottom(),
        )
        self.assertEqual(bar.value(), bar.maximum())
        close_page(sidebar)

    def test_http_body_types_and_tab_list(self):
        page = HTTPPage()
        self.assertEqual(
            [page._request_tabs.tabText(i)
             for i in range(page._request_tabs.count())],
            ["Header", "Query", "Path", "Body", "认证", "Cookie"],
        )

        headers = {}
        page._set_body_type("urlencoded")
        page._body.setPlainText("name=anhu\ncode=1")
        self.assertEqual(
            page._request_body(headers), b"name=anhu&code=1")

        headers = {}
        page._set_body_type("binary")
        page._body.setPlainText("01 02 FF")
        self.assertEqual(page._request_body(headers), b"\x01\x02\xff")

        headers = {}
        page._set_body_type("msgpack")
        page._body.setPlainText('{"code": "0"}')
        packed = page._request_body(headers)
        self.assertEqual(msgpack.unpackb(packed, raw=False), {"code": "0"})

        headers = {}
        page._set_body_type("form-data")
        page._body.setPlainText("name=anhu")
        multipart = page._request_body(headers)
        self.assertIn(b'name="name"', multipart)
        self.assertIn(b"anhu", multipart)
        close_page(page)

    def test_http_body_layout_is_stable_and_ctrl_s_saves_interface(self):
        page = HTTPPage()
        page.new_document()
        page.show()
        page.activateWindow()
        page._request_tabs.setCurrentWidget(page._body.parentWidget())
        APP.processEvents()
        positions = []
        for body_type in ("none", "raw", "binary", "form-data"):
            page._set_body_type(body_type)
            APP.processEvents()
            positions.append((
                page._body_hint.mapTo(page, QPoint(0, 0)).y(),
                page._body.mapTo(page, QPoint(0, 0)).y(),
                page._body.height(),
            ))
        self.assertTrue(all(position == positions[0] for position in positions))
        self.assertEqual(page._body.objectName(), "httpBodyEditor")
        self.assertIn(
            "border: 1px solid #D8E0E8", page.styleSheet())

        page._method.setCurrentText("POST")
        page._url.setText("https://example.com/api/shortcut-save")
        page._url.setFocus()
        APP.processEvents()
        QTest.keyClick(
            page._url, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
        APP.processEvents()
        self.assertEqual(len(page.interfaces()), 1)
        self.assertEqual(
            page.interfaces()[0]["request"]["method"], "POST")
        close_page(page)

    def test_sidebar_empty_http_library_has_no_placeholder(self):
        sidebar = Sidebar()
        sidebar._mode_group.button(5).click()
        sidebar.set_http_interfaces([])
        sidebar.set_http_folders([])
        APP.processEvents()
        search_y = sidebar._http_api_search.mapTo(
            sidebar, QPoint(0, 0)).y()
        button_y = sidebar._btn_http_new.mapTo(
            sidebar, QPoint(0, 0)).y()
        tree_y = sidebar._http_interface_tree.mapTo(
            sidebar, QPoint(0, 0)).y()
        self.assertLess(search_y, button_y)
        self.assertLess(button_y, tree_y)
        self.assertEqual(
            sidebar._http_interface_tree.topLevelItemCount(), 0)
        close_page(sidebar)

    def test_http_lists_start_empty_and_add_button_creates_one_row(self):
        page = HTTPPage()
        request_tables = [
            page._http_headers,
            page._params,
            page._path_params,
            page._request_cookies,
        ]
        for table in request_tables:
            self.assertEqual(table.rowCount(), 0)

        header_page = page._request_tabs.widget(0)
        add_button = next(
            button for button in header_page.findChildren(QPushButton)
            if button.text() == "添加一行"
        )
        add_button.click()
        self.assertEqual(page._http_headers.rowCount(), 1)

        page._set_entries(page._http_headers, [])
        self.assertEqual(page._http_headers.rowCount(), 0)
        close_page(page)

    def test_http_tables_use_sim_mate_list_style(self):
        page = HTTPPage()
        table = page._http_headers
        self.assertEqual(table.verticalHeader().defaultSectionSize(), 38)
        self.assertEqual(table.font().family(), "Microsoft YaHei UI")
        self.assertEqual(table.font().pixelSize(), 13)
        self.assertFalse(table.alternatingRowColors())
        self.assertIn(
            "border-bottom: 1px solid #E9EEF3", table.styleSheet())
        self.assertIn("#EAF4FF", table.styleSheet())
        self.assertIn("#F8FAFC", table.styleSheet())
        self.assertIn("#D8E0E8", table.styleSheet())
        close_page(page)

    def test_mqtt_and_websocket_tables_use_http_list_style(self):
        mqtt = MQTTPage()
        websocket = WebSocketPage()
        for table in (
            mqtt._messages,
            mqtt._subscriptions,
            websocket._headers,
            websocket._messages,
        ):
            self.assertEqual(
                table.verticalHeader().defaultSectionSize(), 38)
            self.assertFalse(table.showGrid())
            self.assertFalse(table.alternatingRowColors())
            self.assertIn(
                "border-bottom: 1px solid #E9EEF3",
                table.styleSheet(),
            )
            self.assertEqual(table.font().family(), "Microsoft YaHei UI")
            self.assertEqual(table.font().pixelSize(), 13)
            self.assertIn("#EAF4FF", table.styleSheet())
            self.assertIn("#F8FAFC", table.styleSheet())
            self.assertIn("#D8E0E8", table.styleSheet())
        close_page(websocket)
        close_page(mqtt)

    def test_mqtt_and_websocket_use_shared_protocol_workspace_style(self):
        mqtt = MQTTPage()
        websocket = WebSocketPage()
        self.assertEqual(mqtt.objectName(), "mqttPage")
        self.assertEqual(websocket.objectName(), "websocketPage")
        for page in (mqtt, websocket):
            self.assertIn("QWidget#protocolCard", page.styleSheet())
            self.assertIn("#F4F7FA", page.styleSheet())
            self.assertIn("#D8E0E8", page.styleSheet())
        self.assertEqual(
            mqtt._messages_container.objectName(), "protocolCard")
        self.assertEqual(
            mqtt._subscriptions_panel.objectName(), "protocolCard")
        self.assertEqual(
            mqtt._publish_panel.objectName(), "protocolCard")
        self.assertTrue(mqtt._btn_publish.property("protocolPrimary"))
        self.assertTrue(websocket._btn_send.property("protocolPrimary"))
        self.assertTrue(websocket._btn_connect.property("protocolPrimary"))
        for button in (
                mqtt._btn_clear, mqtt._btn_subscribe,
                mqtt._btn_unsubscribe, mqtt._btn_publish,
                websocket._btn_add_header, websocket._btn_remove_header,
                websocket._btn_clear, websocket._btn_connect,
                websocket._btn_send):
            self.assertFalse(button.icon().isNull())
        close_page(websocket)
        close_page(mqtt)

    def test_checkbox_headers_select_all_and_hide_enable_label(self):
        page = HTTPPage()
        request_tables = [
            page._http_headers,
            page._params,
            page._path_params,
            page._request_cookies,
        ]
        for table in request_tables:
            self.assertEqual(table.horizontalHeaderItem(0).text(), "")
            self.assertEqual(table.property("checkboxColumn"), 0)

        page._set_entries(page._http_headers, [
            {"name": "A", "value": "1", "enabled": True},
            {"name": "B", "value": "2", "enabled": False},
            {"name": "C", "value": "3", "enabled": True},
        ])
        header = page._http_headers.horizontalHeader()
        self.assertEqual(header._check_state(), Qt.CheckState.Unchecked)
        header.toggle_all()
        self.assertEqual(header._check_state(), Qt.CheckState.Checked)
        self.assertTrue(all(
            page._http_headers.item(row, 0).checkState()
            == Qt.CheckState.Checked
            for row in range(page._http_headers.rowCount())
        ))
        page._http_headers.item(1, 0).setCheckState(
            Qt.CheckState.Unchecked)
        self.assertEqual(header._check_state(), Qt.CheckState.Unchecked)
        header.toggle_all()
        self.assertEqual(header._check_state(), Qt.CheckState.Checked)
        header.toggle_all()
        self.assertEqual(header._check_state(), Qt.CheckState.Unchecked)
        self.assertTrue(all(
            page._http_headers.item(row, 0).checkState()
            == Qt.CheckState.Unchecked
            for row in range(page._http_headers.rowCount())
        ))
        close_page(page)

        page = WebSocketPage()
        self.assertEqual(page._headers.horizontalHeaderItem(0).text(), "")
        page.set_headers([
            {"name": "A", "value": "1", "enabled": True},
            {"name": "B", "value": "2", "enabled": False},
        ])
        page._headers.horizontalHeader().toggle_all()
        self.assertTrue(all(
            page._headers.item(row, 0).checkState()
            == Qt.CheckState.Checked
            for row in range(page._headers.rowCount())
        ))
        close_page(page)

    def test_checkbox_header_clicks_and_row_changes_stay_in_sync(self):
        page = HTTPPage()
        page.show()
        page._set_entries(page._http_headers, [
            {"name": "A", "value": "1", "enabled": False},
            {"name": "B", "value": "2", "enabled": False},
        ])
        APP.processEvents()
        table = page._http_headers
        header = table.horizontalHeader()
        header_hit = header._checkbox_rect(
            header._section_rect(0)).center()

        QTest.mouseClick(
            header.viewport(), Qt.MouseButton.LeftButton, pos=header_hit)
        APP.processEvents()
        self.assertEqual(header._check_state(), Qt.CheckState.Checked)
        self.assertTrue(all(
            table.item(row, 0).checkState() == Qt.CheckState.Checked
            for row in range(table.rowCount())
        ))

        QTest.mouseClick(
            header.viewport(), Qt.MouseButton.LeftButton, pos=header_hit)
        APP.processEvents()
        self.assertEqual(header._check_state(), Qt.CheckState.Unchecked)
        self.assertTrue(all(
            table.item(row, 0).checkState() == Qt.CheckState.Unchecked
            for row in range(table.rowCount())
        ))

        first_row_center = table.visualItemRect(table.item(0, 0)).center()
        QTest.mouseClick(
            table.viewport(), Qt.MouseButton.LeftButton,
            pos=first_row_center,
        )
        APP.processEvents()
        self.assertEqual(
            table.item(0, 0).checkState(), Qt.CheckState.Checked)
        self.assertEqual(header._check_state(), Qt.CheckState.Unchecked)

        second_row_center = table.visualItemRect(table.item(1, 0)).center()
        QTest.mouseClick(
            table.viewport(), Qt.MouseButton.LeftButton,
            pos=second_row_center,
        )
        APP.processEvents()
        self.assertEqual(header._check_state(), Qt.CheckState.Checked)

        page._set_entries(table, [
            {"name": "C", "value": "3", "enabled": True},
            {"name": "D", "value": "4", "enabled": False},
        ])
        APP.processEvents()
        self.assertEqual(header._check_state(), Qt.CheckState.Unchecked)
        close_page(page)

    def test_http_bearer_requires_non_empty_token(self):
        page = HTTPPage()
        page._url.setText("http://127.0.0.1/")
        page._auth_type.setCurrentText("Bearer")
        page._auth_token.clear()
        with mock.patch("anhutoolbox.http_page.show_warning") as warning:
            page._send()
        warning.assert_called_once()
        self.assertIsNone(page._worker)

        page._auth_token.setText("  abc  ")
        self.assertEqual(
            page._build_headers()["Authorization"], "Bearer abc")
        close_page(page)

    def test_http_failure_is_reported_without_a_popup(self):
        page = HTTPPage()
        with mock.patch("anhutoolbox.http_page.show_error") as error:
            page._on_failed("Request URL is invalid")
        error.assert_not_called()
        self.assertEqual(
            page._response_body.toPlainText(), "Request URL is invalid")
        self.assertEqual(page._status.text(), "请求失败")
        self.assertIn(
            "Request URL is invalid", page._console.toPlainText())
        close_page(page)

    def test_http_send_button_does_not_focus_timeout(self):
        page = HTTPPage()
        page.show()
        page._url.setText("http://example.com/api")
        page._url.setFocus()
        APP.processEvents()
        worker = mock.Mock()
        worker.isRunning.return_value = False
        worker.pop_event.return_value = None
        with mock.patch(
                "anhutoolbox.http_page.HTTPRequestWorker",
                return_value=worker):
            QTest.mouseClick(
                page._btn_send, Qt.MouseButton.LeftButton)
        APP.processEvents()
        self.assertFalse(page._timeout.hasFocus())
        self.assertFalse(page._btn_send.hasFocus())
        close_page(page)

    def test_http_checkbox_controls_send_and_row_hover_deletes(self):
        page = HTTPPage()
        page.new_document()
        page._set_entries(page._http_headers, [
            {"name": "A", "value": "1", "enabled": True},
            {"name": "B", "value": "2", "enabled": False},
            {"name": "C", "value": "3", "enabled": True},
        ])
        page._save_current_document()
        self.assertFalse(page._document_tabs.is_tab_dirty(0))
        header_page = page._request_tabs.widget(0)
        self.assertEqual(
            [name for name, _value in _enabled_pairs(page._http_headers)],
            ["A", "C"],
        )
        self.assertFalse(any(
            button.text() == "删除选中"
            for button in header_page.findChildren(QPushButton)
        ))
        self.assertEqual(page._http_headers.columnCount(), 5)

        page.show()
        APP.processEvents()
        table = page._http_headers
        table._set_hovered_row(1)
        APP.processEvents()
        action_host = table.cellWidget(1, 4)
        self.assertIsNotNone(action_host)
        delete_icon = action_host.findChild(QToolButton)
        self.assertIsNotNone(delete_icon)
        self.assertFalse(delete_icon.icon().isNull())
        self.assertFalse(delete_icon.isHidden())
        other_icon = table.cellWidget(0, 4).findChild(QToolButton)
        self.assertTrue(other_icon.isHidden())
        delete_icon.click()
        APP.processEvents()
        self.assertEqual(table.rowCount(), 2)
        self.assertTrue(page._document_tabs.is_tab_dirty(0))
        self.assertEqual(
            [table.item(row, 1).text() for row in range(table.rowCount())],
            ["A", "C"],
        )
        table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
        self.assertEqual(
            [name for name, _value in _enabled_pairs(table)],
            ["C"],
        )
        close_page(page)

    def test_websocket_delete_uses_only_checked_headers(self):
        page = WebSocketPage()
        page.set_headers([
            {"name": "A", "value": "1", "enabled": True},
            {"name": "B", "value": "2", "enabled": False},
            {"name": "C", "value": "3", "enabled": True},
        ])
        page._headers.selectRow(1)
        page._btn_remove_header.click()
        self.assertEqual(page._headers.rowCount(), 1)
        self.assertEqual(page._headers.item(0, 1).text(), "B")

        page._headers.selectRow(0)
        with mock.patch(
                "anhutoolbox.protocol_pages.show_information") as info:
            page._btn_remove_header.click()
        info.assert_called_once()
        self.assertEqual(page._headers.rowCount(), 1)

        page._headers.item(0, 0).setCheckState(Qt.CheckState.Checked)
        page._btn_remove_header.click()
        self.assertEqual(page._headers.rowCount(), 0)
        close_page(page)

    def test_http_page_executes_request(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _HTTPHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        page = HTTPPage()
        page.new_document()
        try:
            page._url.setText(
                "http://127.0.0.1:{}/page".format(server.server_address[1]))
            page._send()
            deadline = time.monotonic() + 5
            while page._worker.isRunning() and time.monotonic() < deadline:
                APP.processEvents()
                time.sleep(0.01)
            APP.processEvents()
            page._poll_request()
            self.assertIn("200", page._status.text())
            self.assertIn('"path": "/page"', page._response_body.toPlainText())
            self.assertEqual(page._response_format.currentText(), "JSON")
        finally:
            close_page(page)
            server.shutdown()
            server.server_close()

    def test_http_page_builds_path_query_header_and_cookie(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _HTTPHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        page = HTTPPage()
        page.new_document()
        try:
            page._url.setText(
                "http://127.0.0.1:{}/item/{{id}}".format(
                    server.server_address[1]))
            page._set_entries(page._path_params, [{
                "name": "id", "value": "42", "enabled": True,
            }])
            page._set_entries(page._params, [{
                "name": "q", "value": "hello", "enabled": True,
            }])
            page._set_entries(page._http_headers, [{
                "name": "X-Test", "value": "yes", "enabled": True,
            }])
            page._set_entries(page._request_cookies, [{
                "name": "session", "value": "abc", "enabled": True,
            }])
            page._send()
            deadline = time.monotonic() + 5
            while page._worker.isRunning() and time.monotonic() < deadline:
                APP.processEvents()
                time.sleep(0.01)
            APP.processEvents()
            page._poll_request()
            result = json.loads(page._response_body.toPlainText())
            self.assertEqual(result["path"], "/item/42?q=hello")
            self.assertEqual(result["header"], "yes")
            self.assertEqual(result["cookie"], "session=abc")
            self.assertEqual(page._actual_method.text(), "GET")
            self.assertIn("/item/42?q=hello", page._actual_url.text())
            self.assertGreater(page._actual_headers.rowCount(), 0)
            response_tabs = [
                page._response_tabs.tabText(i)
                for i in range(page._response_tabs.count())
            ]
            self.assertEqual(response_tabs[0], "实时响应")
            self.assertTrue(response_tabs[1].startswith("响应头("))
            self.assertEqual(response_tabs[2:], [
                "Cookie(1)", "响应示例", "实际请求 ●", "控制台"])
            self.assertEqual(page._response_cookies.columnCount(), 7)
            self.assertGreaterEqual(
                page._response_headers.columnWidth(0), 220)
        finally:
            close_page(page)
            server.shutdown()
            server.server_close()


class ProtocolProjectTests(unittest.TestCase):
    def test_preset_panel_ui_and_splitter_resize(self):
        with tempfile.TemporaryDirectory() as temp:
            window = MainWindow(temp)
            try:
                window.resize(1100, 720)
                window.show()
                APP.processEvents()
                window._btn_toggle_preset.setChecked(True)
                window.preset_panel.load_from_project([{
                    "name": "测试命令",
                    "data": "01 02 FF",
                    "hex_mode": True,
                    "interval": 1000,
                }])
                APP.processEvents()

                splitter = window._preset_splitter
                self.assertEqual(splitter.handleWidth(), 8)
                self.assertFalse(splitter.childrenCollapsible())
                self.assertEqual(window._tab_widget.minimumWidth(), 360)
                panel = window.preset_panel
                header_scroll = panel._header_scroll
                header_content = header_scroll.widget()
                hint = header_content.findChild(QLabel, "presetHint")
                title = header_content.findChild(QLabel, "presetTitle")
                self.assertIsNotNone(hint)
                self.assertIsNotNone(title)
                self.assertTrue(
                    header_scroll.horizontalScrollBar().isVisible())
                narrow_y = (
                    title.mapTo(
                        panel, title.rect().topLeft()).y(),
                    panel.btn_add.mapTo(
                        panel, panel.btn_add.rect().topLeft()).y(),
                    hint.mapTo(
                        panel, hint.rect().topLeft()).y(),
                )

                window.resize(1920, 1080)
                APP.processEvents()
                self.assertFalse(
                    header_scroll.horizontalScrollBar().isVisible())
                self.assertEqual(
                    (
                        title.mapTo(
                            panel, title.rect().topLeft()).y(),
                        panel.btn_add.mapTo(
                            panel, panel.btn_add.rect().topLeft()).y(),
                        hint.mapTo(
                            panel, hint.rect().topLeft()).y(),
                    ),
                    narrow_y,
                )
                window.resize(1100, 720)
                APP.processEvents()
                self.assertTrue(
                    header_scroll.horizontalScrollBar().isVisible())

                table_height = panel.table.height()
                splitter.setSizes([650, 200])
                APP.processEvents()
                self.assertGreater(
                    panel._header_scroll.horizontalScrollBar().maximum(),
                    0,
                )
                self.assertEqual(panel.table.height(), table_height)
                header_viewport = panel._header_scroll.viewport()
                self.assertLessEqual(
                    panel.btn_add.geometry().bottom() + 1,
                    header_viewport.height(),
                )
                self.assertLessEqual(
                    hint.geometry().bottom() + 1,
                    header_viewport.height(),
                )
                before = list(splitter.sizes())
                splitter.moveSplitter(450, 1)
                APP.processEvents()
                self.assertNotEqual(splitter.sizes(), before)

                self.assertEqual(panel.objectName(), "presetPanel")
                self.assertIn(
                    "QWidget#presetPanel", panel.styleSheet())
                self.assertIn(
                    "QTableWidget", panel.table.styleSheet())
                self.assertIn(
                    "QTableWidget::item:selected{background-color:#FFFFFF;",
                    panel.table.styleSheet(),
                )
                self.assertFalse(
                    panel.table.horizontalHeader().highlightSections())
                self.assertEqual(
                    panel.table.horizontalHeader().sectionResizeMode(1),
                    QHeaderView.ResizeMode.Interactive,
                )
                self.assertEqual(
                    panel.table.horizontalHeader().sectionResizeMode(0),
                    QHeaderView.ResizeMode.Interactive,
                )
                window.resize(1920, 1080)
                APP.processEvents()
                panel._fit_preset_table_width()
                header = panel.table.horizontalHeader()
                self.assertEqual(
                    header.sectionSize(0),
                    panel._preset_name_column_width(),
                )
                self.assertEqual(
                    header.length(), panel.table.viewport().width())
                name_before = header.sectionSize(0)
                data_before = header.sectionSize(1)
                header.resizeSection(0, name_before - 40)
                APP.processEvents()
                self.assertLess(header.sectionSize(0), name_before)
                self.assertGreater(header.sectionSize(1), data_before)
                self.assertEqual(
                    header.length(), panel.table.viewport().width())
                name_before = header.sectionSize(0)
                data_before = header.sectionSize(1)
                header.resizeSection(1, data_before - 40)
                APP.processEvents()
                self.assertLess(header.sectionSize(1), data_before)
                self.assertGreater(header.sectionSize(0), name_before)
                self.assertEqual(
                    header.length(), panel.table.viewport().width())
                header.resizeSection(1, data_before + 40)
                APP.processEvents()
                self.assertGreater(
                    header.sectionSize(1), data_before)
                self.assertGreaterEqual(
                    header.length(), panel.table.viewport().width())
                hex_widget = panel.table.cellWidget(0, 2)
                self.assertGreaterEqual(
                    hex_widget.x(), header.sectionPosition(2))
                self.assertLess(
                    hex_widget.x(),
                    header.sectionPosition(2)
                    + header.sectionSize(2),
                )
                expected_widths = {
                    2: 64, 3: 100, 4: 54, 5: 58,
                }
                for column in (2, 3, 4, 5):
                    width = expected_widths[column]
                    header_text = panel.table.horizontalHeaderItem(
                        column).text()
                    required = (
                        panel.table.fontMetrics().horizontalAdvance(
                            header_text) + 20
                    )
                    self.assertGreaterEqual(width, required)
                    self.assertEqual(
                        panel.table.columnWidth(column), width)
                for button in (panel.btn_add, panel.btn_imp, panel.btn_exp):
                    self.assertFalse(button.icon().isNull())
                row_button = panel.table.cellWidget(0, 5)
                self.assertIsNotNone(row_button)
                self.assertFalse(row_button.icon().isNull())
            finally:
                window.close()
                window.deleteLater()
                APP.processEvents()

    def test_http_tabs_keep_navigation_controls_visible_at_minimum_width(
            self):
        with tempfile.TemporaryDirectory() as temp:
            window = MainWindow(temp)
            try:
                window.sidebar._mode_group.button(5).click()
                page = window._http_page
                while page._document_tabs.count() < 5:
                    page.new_document()
                window.resize(1100, 720)
                window.show()
                APP.processEvents()

                surface = page._document_tabs.parentWidget()
                self.assertLessEqual(
                    page._btn_environment.x()
                    + page._btn_environment.width(),
                    surface.width(),
                )
                self.assertLess(
                    page._document_tabs.width(), page.width())
                current_rect = page._document_tabs.tabRect(
                    page._document_tabs.currentIndex())
                self.assertLessEqual(
                    current_rect.right() + 1,
                    page._document_tabs.width(),
                )
                page._btn_tab_next.click()
                APP.processEvents()
                current_rect = page._document_tabs.tabRect(
                    page._document_tabs.currentIndex())
                self.assertLessEqual(
                    current_rect.right() + 1,
                    page._document_tabs.width(),
                )
            finally:
                window.close()
                window.deleteLater()
                APP.processEvents()

    def test_new_modes_switch_pages_and_project_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            window = MainWindow(temp)
            try:
                window.sidebar._mode_group.button(3).click()
                APP.processEvents()
                self.assertIs(window._comm_stack.currentWidget(),
                              window._mqtt_page)
                window.sidebar._mode_group.button(4).click()
                APP.processEvents()
                self.assertIs(window._comm_stack.currentWidget(),
                              window._websocket_page)
                self.assertTrue(window.sidebar._btn_connect.isHidden())
                window.sidebar._mode_group.button(5).click()
                APP.processEvents()
                self.assertIs(window._comm_stack.currentWidget(),
                              window._http_page)

                window.sidebar.le_mqtt_host.setText("broker.local")
                window.sidebar.le_mqtt_password.setText("secret")
                window._mqtt_page.set_subscriptions([
                    {"topic": "test/#", "qos": 2},
                ])
                window._websocket_page.set_url("ws://127.0.0.1/ws")
                window._http_page.new_document()
                window._http_page._url.setText("https://example.com")
                snapshot = window._snapshot_ui()
                self.assertEqual(snapshot["mqtt"]["host"], "broker.local")
                self.assertEqual(
                    snapshot["mqtt"]["password"], "secret")
                self.assertEqual(
                    snapshot["mqtt"]["subscriptions"][0]["topic"], "test/#")
                self.assertEqual(
                    snapshot["websocket"]["url"], "ws://127.0.0.1/ws")
                self.assertEqual(
                    snapshot["http"]["url"], "https://example.com")

                window._apply_profile({
                    "mode": "mqtt",
                    "mqtt": {
                        "host": "mqtt.example",
                        "port": 1884,
                        "username": "admin",
                        "password": "restored-secret",
                        "subscriptions": [
                            {"topic": "restored/+", "qos": 1},
                        ],
                    },
                    "websocket": {"url": "wss://restored.example/ws"},
                    "http": {"method": "DELETE", "url": "https://delete"},
                })
                self.assertEqual(window.sidebar.current_mode, "mqtt")
                self.assertEqual(window.sidebar.le_mqtt_host.text(),
                                 "mqtt.example")
                self.assertEqual(
                    window._mqtt_page.subscriptions()[0]["topic"],
                    "restored/+")
                self.assertEqual(
                    window.sidebar.le_mqtt_password.text(),
                    "restored-secret")
                self.assertEqual(window._http_page._method.currentText(),
                                 "DELETE")
                self.assertEqual(
                    window._websocket_page.url(),
                    "wss://restored.example/ws")
            finally:
                window.close()
                window.deleteLater()
                APP.processEvents()

    def test_projects_keep_all_six_mode_contents_and_active_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            window = MainWindow(temp)
            try:
                first = window._current_project
                window.sidebar._mode_group.button(0).click()
                window.sidebar.cb_baud.setCurrentText("57600")
                window.sidebar.sp_server_port.setValue(41001)
                window.sidebar.le_client_host.setText("a.client.local")
                window.sidebar.le_mqtt_host.setText("a.broker.local")
                window.sidebar.le_mqtt_user.setText("admin")
                window.sidebar.le_mqtt_password.setText("a-secret")
                window._mqtt_page.set_subscriptions([
                    {"topic": "project-a/#", "qos": 1},
                ])
                window._websocket_page.set_url("ws://a.example/ws")
                window._http_page.new_document()
                window._http_page._url.setText("https://a.example/api")
                window._http_page._environments = [{
                    "id": "env-a",
                    "name": "项目A环境",
                    "variables": [{
                        "name": "host", "value": "a.example",
                        "description": "",
                    }],
                }]
                window._http_page._active_environment_id = "env-a"
                window._http_page._refresh_environment_button()
                for key in ("serial", "tcpserver", "tcpclient"):
                    window._stream_pages[key].send_bar.text.setPlainText(
                        "{} draft A".format(key))

                # 模式切换本身也必须立即写回当前项目。
                window.sidebar._mode_group.button(3).click()
                self.assertEqual(window._pm.load(first)["mode"], "mqtt")
                window.sidebar._mode_group.button(0).click()
                self.assertEqual(window._pm.load(first)["mode"], "serial")

                second = window._pm.create(
                    "项目B", window._default_profile())
                window._reload_project_list(second)
                window.sidebar._mode_group.button(3).click()
                window.sidebar.cb_baud.setCurrentText("921600")
                window.sidebar.sp_server_port.setValue(42002)
                window.sidebar.le_client_host.setText("b.client.local")
                window.sidebar.le_mqtt_host.setText("b.broker.local")
                window.sidebar.le_mqtt_user.setText("admin")
                window.sidebar.le_mqtt_password.setText("b-secret")
                window._mqtt_page.set_subscriptions([
                    {"topic": "project-b/#", "qos": 2},
                ])
                window._websocket_page.set_url("wss://b.example/ws")
                window._http_page.new_document()
                window._http_page._url.setText("https://b.example/api")
                window._http_page._environments = [{
                    "id": "env-b",
                    "name": "项目B环境",
                    "variables": [{
                        "name": "host", "value": "b.example",
                        "description": "",
                    }],
                }]
                window._http_page._active_environment_id = "env-b"
                window._http_page._refresh_environment_button()
                for key in ("serial", "tcpserver", "tcpclient"):
                    window._stream_pages[key].send_bar.text.setPlainText(
                        "{} draft B".format(key))

                window._switch_project(first)
                self.assertEqual(window.sidebar.current_mode, "serial")
                self.assertIs(
                    window._comm_stack.currentWidget(),
                    window._stream_pages["serial"])
                self.assertEqual(
                    window.sidebar.cb_baud.currentText(), "57600")
                self.assertEqual(
                    window.sidebar.sp_server_port.value(), 41001)
                self.assertEqual(
                    window.sidebar.le_client_host.text(),
                    "a.client.local")
                self.assertEqual(
                    window.sidebar.le_mqtt_host.text(),
                    "a.broker.local")
                self.assertEqual(
                    window.sidebar.le_mqtt_password.text(),
                    "a-secret")
                self.assertEqual(
                    window._mqtt_page.subscriptions()[0]["topic"],
                    "project-a/#")
                self.assertEqual(
                    window._websocket_page.url(), "ws://a.example/ws")
                self.assertEqual(
                    window._http_page._url.text(),
                    "https://a.example/api")
                self.assertEqual(
                    window._http_page._active_environment_id, "env-a")
                self.assertEqual(
                    window._http_page._active_environment()["name"],
                    "项目A环境")
                for key in ("serial", "tcpserver", "tcpclient"):
                    self.assertEqual(
                        window._stream_pages[key].send_bar.text.toPlainText(),
                        "{} draft A".format(key))

                window._switch_project(second)
                self.assertEqual(window.sidebar.current_mode, "mqtt")
                self.assertIs(
                    window._comm_stack.currentWidget(), window._mqtt_page)
                self.assertEqual(
                    window.sidebar.cb_baud.currentText(), "921600")
                self.assertEqual(
                    window.sidebar.sp_server_port.value(), 42002)
                self.assertEqual(
                    window.sidebar.le_client_host.text(),
                    "b.client.local")
                self.assertEqual(
                    window.sidebar.le_mqtt_host.text(),
                    "b.broker.local")
                self.assertEqual(
                    window.sidebar.le_mqtt_password.text(),
                    "b-secret")
                self.assertEqual(
                    window._mqtt_page.subscriptions()[0]["topic"],
                    "project-b/#")
                self.assertEqual(
                    window._websocket_page.url(), "wss://b.example/ws")
                self.assertEqual(
                    window._http_page._url.text(),
                    "https://b.example/api")
                self.assertEqual(
                    window._http_page._active_environment_id, "env-b")
                self.assertEqual(
                    window._http_page._active_environment()["name"],
                    "项目B环境")
                for key in ("serial", "tcpserver", "tcpclient"):
                    self.assertEqual(
                        window._stream_pages[key].send_bar.text.toPlainText(),
                        "{} draft B".format(key))
            finally:
                window.close()
                window.deleteLater()
                APP.processEvents()

    def test_http_folder_and_interface_rename_work_from_sidebar(self):
        with tempfile.TemporaryDirectory() as temp:
            window = MainWindow(temp)
            try:
                window.sidebar._mode_group.button(5).click()
                APP.processEvents()
                page = window._http_page
                folder_id = page.create_folder("业务接口")
                page.set_current_folder(folder_id)
                page.new_document()
                page._url.setText("https://example.com/api/orders")
                page._save_current_document()
                APP.processEvents()
                api_id = page.interfaces()[0]["id"]

                api_item = window.sidebar._http_interface_items[api_id]
                api_item.setText(0, "创建订单")
                APP.processEvents()
                self.assertEqual(
                    page.interfaces()[0]["name"], "创建订单")

                folder_item = window.sidebar._http_folder_items[folder_id]
                folder_item.setText(0, "核心业务")
                APP.processEvents()
                self.assertEqual(
                    page.folders()[0]["name"], "核心业务")

                with mock.patch(
                        "anhutoolbox.sidebar.get_text",
                        return_value=("归档接口", True)):
                    window.sidebar._btn_http_new_folder.click()
                    APP.processEvents()
                self.assertIn(
                    "归档接口",
                    {item["name"] for item in page.folders()},
                )
            finally:
                window.close()
                window.deleteLater()
                APP.processEvents()

    def test_http_import_as_new_project_uses_file_name(self):
        transfer = {
            "folders": [{"path": ("业务目录",)}],
            "interfaces": [{
                "name": "导入接口",
                "folder_path": ("业务目录",),
                "request": {
                    "method": "POST",
                    "url": "https://example.com/imported",
                },
            }],
            "environments": [],
        }
        with tempfile.TemporaryDirectory() as temp:
            window = MainWindow(temp)
            try:
                window.resize(1100, 720)
                window.show()
                APP.processEvents()
                window._on_http_import_as_new_project(
                    "省疾控", transfer, "merge")
                APP.processEvents()
                self.assertEqual(
                    window._current_project, "省疾控")
                self.assertTrue(window._pm.exists("省疾控"))
                self.assertEqual(
                    window._http_page.interfaces()[0]["name"],
                    "导入接口",
                )
                self.assertEqual(
                    window._http_page.folders()[0]["name"],
                    "业务目录",
                )
                self.assertEqual(
                    window._http_page._http_toast.text(),
                    "✓ 导入成功",
                )
            finally:
                window.close()
                window.deleteLater()
                APP.processEvents()


if __name__ == "__main__":
    unittest.main()
