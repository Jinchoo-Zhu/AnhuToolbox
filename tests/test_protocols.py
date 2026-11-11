# -*- coding: utf-8 -*-
"""MQTT、HTTP、WebSocket 协议扩展回归测试。"""

import json
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import msgpack

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QGroupBox, QLabel, QPushButton,
    QSizePolicy, QStyle, QStyleOptionGroupBox, QToolButton,
)

from anhutoolbox.main_window import MainWindow
from anhutoolbox.protocol_pages import (
    HTTPPage, MQTTPage, WebSocketPage,
)
from anhutoolbox.protocol_workers import (
    HTTPRequestWorker, MQTTWorker, WebSocketWorker,
)
from anhutoolbox.sidebar import Sidebar

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

    def test_sidebar_short_mode_has_no_scrollbar(self):
        sidebar = Sidebar()
        sidebar.resize(260, 500)
        sidebar.show()
        sidebar._mode_group.button(1).click()
        APP.processEvents()
        self.assertEqual(
            sidebar._settings_scroll.verticalScrollBar().maximum(), 0)
        close_page(sidebar)

    def test_http_page_snapshot(self):
        page = HTTPPage()
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
        close_page(page)

    def test_http_save_creates_interface_and_clears_unsaved_dot(self):
        page = HTTPPage()
        saved = []
        page.save_requested.connect(lambda: saved.append(True))
        self.assertIn("●", page._document_tabs.tabText(0))

        page._method.setCurrentText("POST")
        page._url.setText("https://example.com/api/users")
        page._btn_save.click()
        APP.processEvents()

        interfaces = page.interfaces()
        self.assertEqual(len(interfaces), 1)
        self.assertEqual(interfaces[0]["name"], "users")
        self.assertEqual(
            interfaces[0]["request"]["method"], "POST")
        self.assertEqual(saved, [True])
        self.assertNotIn("●", page._document_tabs.tabText(0))

        page._url.setText("https://example.com/api/users?page=2")
        self.assertIn("●", page._document_tabs.tabText(0))
        close_page(page)

    def test_http_tabs_preserve_drafts_and_restore_saved_interfaces(self):
        page = HTTPPage()
        page._url.setText("https://example.com/api/first")
        page._btn_save.click()
        first_id = page.interfaces()[0]["id"]

        page.new_document()
        self.assertEqual(page._document_tabs.count(), 2)
        page._url.setText("https://example.com/api/second")
        page._btn_save.click()
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
        self.assertIn("●", page._document_tabs.tabText(0))

        snapshot = page.snapshot()
        restored = HTTPPage()
        restored.apply(snapshot)
        self.assertEqual(len(restored.interfaces()), 2)
        self.assertEqual(restored._document_tabs.count(), 2)
        self.assertEqual(
            restored._url.text(), "https://example.com/api/first/draft")
        self.assertIn("●", restored._document_tabs.tabText(0))
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
        APP.processEvents()
        page.new_document()
        APP.processEvents()
        self.assertEqual(page._document_tabs.count(), 2)
        tab_bar = page._document_tabs
        QTest.mouseMove(tab_bar, tab_bar.tabRect(1).center())
        APP.processEvents()
        close_button = tab_bar.tabButton(
            1, tab_bar.ButtonPosition.RightSide)
        self.assertIsNotNone(close_button)
        self.assertTrue(close_button.isVisible())
        close_tool = close_button.findChild(QToolButton)
        self.assertIsNotNone(close_tool)
        for index in range(tab_bar.count()):
            if index == 1:
                continue
            other = tab_bar.tabButton(
                index, tab_bar.ButtonPosition.RightSide)
            self.assertFalse(other.isVisible())
        close_tool.click()
        APP.processEvents()
        self.assertEqual(page._document_tabs.count(), 1)
        close_page(page)

    def test_http_folders_and_interface_names_are_project_scoped(self):
        page = HTTPPage()
        parent = page.create_folder("业务接口")
        child = page.create_folder("订单", parent)
        page.set_current_folder(child)
        page._url.setText("https://example.com/api/orders")
        page._btn_save.click()
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

        renames = []
        folder_events = []
        sidebar.http_rename_requested.connect(
            lambda *values: renames.append(values))
        sidebar.http_folder_selected.connect(folder_events.append)
        folder_item.setText(0, "核心业务")
        APP.processEvents()
        self.assertEqual(
            renames[-1], ("folder", "folder-1", "核心业务"))
        sidebar._on_http_interface_clicked(folder_item, 1)
        self.assertEqual(folder_events[-1], "folder-1")

        interface_item = folder_item.child(0)
        menu, _, _, _, _ = sidebar._build_http_library_menu(
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
            if button.text() == "+ 添加一行"
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
        self.assertEqual(table.font().pointSize(), 11)
        self.assertFalse(table.alternatingRowColors())
        self.assertIn("border-bottom:1px solid #EEF1F4", table.styleSheet())
        self.assertIn("#E8F0FE", table.styleSheet())
        self.assertIn("#FAFAFA", table.styleSheet())
        self.assertIn("#C5CBD3", table.styleSheet())
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
                "border-bottom:1px solid #EEF1F4",
                table.styleSheet(),
            )
            self.assertEqual(table.font().family(), "Microsoft YaHei UI")
            self.assertEqual(table.font().pointSize(), 11)
            self.assertIn("#E8F0FE", table.styleSheet())
            self.assertIn("#FAFAFA", table.styleSheet())
            self.assertIn("#C5CBD3", table.styleSheet())
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

    def test_http_delete_uses_only_checked_rows(self):
        page = HTTPPage()
        page._set_entries(page._http_headers, [
            {"name": "A", "value": "1", "enabled": True},
            {"name": "B", "value": "2", "enabled": False},
            {"name": "C", "value": "3", "enabled": True},
        ])
        header_page = page._request_tabs.widget(0)
        delete_button = next(
            button for button in header_page.findChildren(QPushButton)
            if button.text() == "删除选中"
        )
        page._http_headers.selectRow(1)
        delete_button.click()
        self.assertEqual(page._http_headers.rowCount(), 1)
        self.assertEqual(
            page._http_headers.item(0, 1).text(), "B")

        page._http_headers.selectRow(0)
        with mock.patch(
                "anhutoolbox.http_page.show_information") as info:
            delete_button.click()
        info.assert_called_once()
        self.assertEqual(page._http_headers.rowCount(), 1)
        self.assertEqual(
            page._http_headers.item(0, 1).text(), "B")

        page._http_headers.item(0, 0).setCheckState(
            Qt.CheckState.Checked)
        delete_button.click()
        self.assertEqual(page._http_headers.rowCount(), 0)

        delete_buttons = [
            button for button in page.findChildren(QPushButton)
            if button.text() == "删除选中"
        ]
        self.assertTrue(delete_buttons)
        self.assertTrue(all(
            button.objectName() == "httpDeleteRows"
            for button in delete_buttons))
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
        finally:
            close_page(page)
            server.shutdown()
            server.server_close()

    def test_http_page_builds_path_query_header_and_cookie(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _HTTPHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        page = HTTPPage()
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
        finally:
            close_page(page)
            server.shutdown()
            server.server_close()


class ProtocolProjectTests(unittest.TestCase):
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
                window._http_page._url.setText("https://a.example/api")
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
                window._http_page._url.setText("https://b.example/api")
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
                page._url.setText("https://example.com/api/orders")
                page._btn_save.click()
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


if __name__ == "__main__":
    unittest.main()
