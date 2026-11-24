# -*- coding: utf-8 -*-
"""MQTT server UI and bundled Mosquitto runtime tests."""

import os
import socket
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QDialog, QLineEdit,
    QPushButton,
)
import paho.mqtt.client as mqtt

from anhutoolbox.main_window import MainWindow
from anhutoolbox.mqtt_broker import (
    MQTTBrokerError, MQTTBrokerRuntime, install_mqtt_broker_runtime,
    mqtt_broker_archive, mqtt_broker_available, mqtt_broker_dir,
    prepare_broker_config,
)
from anhutoolbox.mqtt_server_dialogs import (
    MQTTTlsDialog, MQTTUserEditDialog, MQTTUsersDialog,
)
from anhutoolbox.protocol_pages import MQTTPage
from anhutoolbox.sidebar import Sidebar


APP = QApplication.instance() or QApplication([])
ROOT = Path(__file__).resolve().parents[1]


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class MQTTBrokerTests(unittest.TestCase):
    def test_bundled_runtime_exists(self):
        broker = mqtt_broker_dir(str(ROOT))
        self.assertTrue(mqtt_broker_available(str(ROOT)))
        for name in (
            "mosquitto.exe",
            "mosquitto_passwd.exe",
            "mosquitto_common.dll",
            "mosquitto_password_file.dll",
            "NOTICE.md",
            "edl-v10",
            "epl-v20",
        ):
            self.assertTrue((broker / name).is_file(), name)
        self.assertIsNotNone(mqtt_broker_archive(str(ROOT)))

    def test_runtime_archive_installs_to_writable_data_dir(self):
        with tempfile.TemporaryDirectory() as temp:
            target = install_mqtt_broker_runtime(str(ROOT), temp)
            self.assertTrue((target / "mosquitto.exe").is_file())
            self.assertTrue((target / "NOTICE.md").is_file())
            self.assertTrue((target / "epl-v20").is_file())

    def test_prepare_anonymous_broker_config(self):
        with tempfile.TemporaryDirectory() as temp:
            executable, config_path = prepare_broker_config(
                str(ROOT),
                temp,
                {
                    "bind_address": "127.0.0.1",
                    "port": _free_port(),
                    "allow_anonymous": True,
                    "max_connections": 25,
                },
            )
            self.assertTrue(executable.is_file())
            config = config_path.read_text(encoding="utf-8")
            self.assertIn("allow_anonymous true", config)
            self.assertIn("max_connections 25", config)
            self.assertIn("log_timestamp_format", config)
            self.assertNotIn("password_file", config)

    def test_prepare_password_broker_config(self):
        with tempfile.TemporaryDirectory() as temp:
            _executable, config_path = prepare_broker_config(
                str(ROOT),
                temp,
                {
                    "bind_address": "127.0.0.1",
                    "port": _free_port(),
                    "allow_anonymous": False,
                    "username": "tester",
                    "password": "secret",
                    "max_connections": 10,
                },
            )
            config = config_path.read_text(encoding="utf-8")
            password_file = Path(temp) / "passwd"
            self.assertIn("allow_anonymous false", config)
            self.assertIn("password_file", config)
            self.assertNotIn('password_file "', config)
            self.assertTrue(password_file.is_file())
            self.assertIn(
                "$7$", password_file.read_text(encoding="utf-8"))

    def test_prepare_multiuser_acl_tls_and_persistence_config(self):
        tls_dir = ROOT / "tests" / "fixtures" / "mqtt_tls"
        with tempfile.TemporaryDirectory() as temp:
            _executable, config_path = prepare_broker_config(
                str(ROOT),
                temp,
                {
                    "bind_address": "127.0.0.1",
                    "port": _free_port(),
                    "allow_anonymous": False,
                    "max_connections": 10,
                    "persistence": True,
                    "users": [
                        {
                            "username": "alice",
                            "password": "alice-pass",
                            "enabled": True,
                            "topics": ["alice/#"],
                            "access": "readwrite",
                        },
                        {
                            "username": "bob",
                            "password": "bob-pass",
                            "enabled": True,
                            "topics": ["bob/#"],
                            "access": "read",
                        },
                        {
                            "username": "disabled",
                            "password": "disabled-pass",
                            "enabled": False,
                            "topics": ["#"],
                            "access": "readwrite",
                        },
                    ],
                    "tls": {
                        "enabled": True,
                        "ca_file": str(tls_dir / "ca.crt"),
                        "cert_file": str(tls_dir / "server.crt"),
                        "key_file": str(tls_dir / "server.key"),
                        "require_client_cert": True,
                    },
                },
            )
            runtime_dir = config_path.parent
            config = config_path.read_text(encoding="utf-8")
            self.assertIn("persistence true", config)
            self.assertIn("autosave_interval 1", config)
            self.assertIn("require_certificate true", config)
            self.assertIn("password_file", config)
            self.assertIn("acl_file", config)
            self.assertTrue((runtime_dir / "persistence").is_dir())
            password_file = (runtime_dir / "passwd").read_text(
                encoding="utf-8")
            self.assertIn("alice", password_file)
            self.assertIn("bob", password_file)
            self.assertNotIn("disabled", password_file)
            acl_file = (runtime_dir / "acl").read_text(encoding="utf-8")
            self.assertIn("user alice", acl_file)
            self.assertIn("topic readwrite alice/#", acl_file)
            self.assertIn("user bob", acl_file)
            self.assertIn("topic read bob/#", acl_file)
            self.assertNotIn("user disabled", acl_file)

    def test_multiuser_config_requires_an_enabled_user(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(
                    MQTTBrokerError, "至少需要一个启用的用户"):
                prepare_broker_config(
                    str(ROOT),
                    temp,
                    {
                        "bind_address": "127.0.0.1",
                        "port": _free_port(),
                        "allow_anonymous": False,
                        "users": [{
                            "username": "disabled",
                            "password": "secret",
                            "enabled": False,
                            "topics": ["#"],
                            "access": "readwrite",
                        }],
                    },
                )

    def test_broker_starts_listening_and_stops(self):
        port = _free_port()
        runtime = MQTTBrokerRuntime(str(ROOT))
        started = []
        stopped = []
        logs = []
        runtime.started.connect(lambda: started.append(True))
        runtime.stopped.connect(stopped.append)
        runtime.log_message.connect(logs.append)
        try:
            with tempfile.TemporaryDirectory() as temp:
                runtime_dir = Path(temp) / "MQTT Runtime"
                runtime.start(
                    {
                        "bind_address": "127.0.0.1",
                        "port": port,
                        "allow_anonymous": True,
                        "max_connections": 20,
                    },
                    runtime_dir,
                )
                deadline = time.monotonic() + 5
                while not runtime.is_running and time.monotonic() < deadline:
                    APP.processEvents()
                    time.sleep(0.02)
                self.assertTrue(runtime.is_running)
                self.assertTrue(started)
                deadline = time.monotonic() + 2
                while not any(
                        "mosquitto version" in line for line in logs
                ) and time.monotonic() < deadline:
                    APP.processEvents()
                    time.sleep(0.02)
                self.assertTrue(any(
                    "mosquitto version" in line for line in logs))
                with socket.create_connection(
                        ("127.0.0.1", port), timeout=2):
                    pass
                self.assertTrue(runtime.stop())
                APP.processEvents()
                self.assertFalse(runtime.is_running)
                self.assertTrue(stopped)
        finally:
            runtime.cleanup()
            runtime.deleteLater()
            APP.processEvents()

    def test_password_broker_accepts_authenticated_client(self):
        port = _free_port()
        runtime = MQTTBrokerRuntime(str(ROOT))
        errors = []
        runtime.failed.connect(errors.append)
        client = None
        try:
            with tempfile.TemporaryDirectory() as temp:
                runtime_dir = Path(temp) / "MQTT Runtime"
                runtime.start(
                    {
                        "bind_address": "127.0.0.1",
                        "port": port,
                        "allow_anonymous": False,
                        "username": "tester",
                        "password": "secret",
                        "max_connections": 20,
                    },
                    runtime_dir,
                )
                deadline = time.monotonic() + 5
                while not runtime.is_running and time.monotonic() < deadline:
                    APP.processEvents()
                    time.sleep(0.02)
                self.assertTrue(runtime.is_running)
                self.assertFalse(errors)

                connected = []
                client = mqtt.Client(
                    callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                    client_id="mqtt-broker-test",
                )
                client.username_pw_set("tester", "secret")
                client.on_connect = (
                    lambda _client, _userdata, _flags, reason, _properties:
                    connected.append(str(reason)))
                client.connect("127.0.0.1", port, 10)
                client.loop_start()
                deadline = time.monotonic() + 3
                while not connected and time.monotonic() < deadline:
                    APP.processEvents()
                    time.sleep(0.02)
                self.assertEqual(connected, ["Success"])
                client.disconnect()
                client.loop_stop()
                client = None
                self.assertTrue(runtime.stop())
                APP.processEvents()
        finally:
            if client is not None:
                client.disconnect()
                client.loop_stop()
            runtime.cleanup()
            runtime.deleteLater()
            APP.processEvents()


class MQTTBrokerPageTests(unittest.TestCase):
    def test_page_has_client_and_server_modes(self):
        page = MQTTPage()
        try:
            self.assertEqual(page._mode_tabs.count(), 2)
            self.assertEqual(
                page._mode_tabs.tabText(0), "客户端连接")
            self.assertEqual(
                page._mode_tabs.tabText(1), "内置服务端")
            self.assertEqual(
                page._btn_server_connect_local.text(),
                "本地客户端连接",
            )
            page.set_server_runtime_available(False)
            self.assertFalse(page._server_runtime_hint.isHidden())
            page.set_server_runtime_available(False, True)
            self.assertFalse(
                page._btn_server_install_runtime.isHidden())
            self.assertEqual(
                page._btn_server_install_runtime.text(),
                "安装 MQTT 服务端",
            )
            page.set_server_runtime_available(True)
            self.assertTrue(page._server_runtime_hint.isHidden())
            self.assertTrue(
                page._btn_server_install_runtime.isHidden())
            self.assertFalse(hasattr(page, "_btn_server_start"))
            self.assertFalse(hasattr(page, "_btn_server_stop"))
        finally:
            page.cleanup()
            page.deleteLater()
            APP.processEvents()

    def test_server_log_pause_and_resume(self):
        page = MQTTPage()
        try:
            page._chk_server_log_pause.setChecked(True)
            page.append_server_log("first line")
            page.append_server_log("second line")
            self.assertEqual(page._server_log.toPlainText(), "")
            self.assertEqual(len(page._server_log_paused_lines), 2)
            page._chk_server_log_pause.setChecked(False)
            self.assertIn("first line", page._server_log.toPlainText())
            self.assertIn("second line", page._server_log.toPlainText())
        finally:
            page.cleanup()
            page.deleteLater()
            APP.processEvents()

    def test_server_connections_table_tracks_online_state(self):
        page = MQTTPage()
        try:
            page.append_server_log(
                "2026-11-24 09:51:38: New client connected from "
                "127.0.0.1:30017 as device-001 "
                "(p4, c1, k60, u'admin').")
            page._refresh_connections_table()
            self.assertEqual(page._server_connections.rowCount(), 1)
            self.assertEqual(
                page._server_connections.item(0, 1).text(),
                "device-001",
            )
            self.assertEqual(
                page._server_connections.item(0, 7).text(),
                "2026-11-24 09:51:38",
            )
            for column in range(
                    page._server_connections.columnCount()):
                self.assertEqual(
                    int(page._server_connections.item(
                        0, column).textAlignment()),
                    int(Qt.AlignmentFlag.AlignCenter),
                )
            self.assertIn(
                "在线 1",
                page._lbl_server_connections_title.text(),
            )
            page.append_server_log(
                "2026-11-24 09:52:38: Client device-001 "
                "[127.0.0.1:30017] disconnected.")
            page._refresh_connections_table()
            self.assertEqual(page._server_connections.rowCount(), 0)
        finally:
            page.cleanup()
            page.deleteLater()
            APP.processEvents()

    def test_server_log_saves_and_clears_after_limit(self):
        page = MQTTPage()
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / "mqtt-server.log")
            try:
                with mock.patch(
                    "anhutoolbox.protocol_pages.QFileDialog."
                    "getSaveFileName",
                    return_value=(path, "日志文件 (*.log)"),
                ), mock.patch(
                    "anhutoolbox.protocol_pages.AUTO_CLEAR_RECORDS", 2,
                ):
                    page._chk_server_log_save.setChecked(True)
                    page.append_server_log("line one")
                    page.append_server_log("line two")
                    self.assertEqual(page._server_log.toPlainText(), "")
                    self.assertEqual(
                        page._server_log_display_records, 0)
                    page._chk_server_log_save.setChecked(False)
                text = Path(path).read_text(encoding="utf-8")
                self.assertIn("line one", text)
                self.assertIn("line two", text)
            finally:
                page.cleanup()
                page.deleteLater()
                APP.processEvents()

    def test_missing_server_runtime_can_request_install(self):
        page = MQTTPage()
        requested = []
        page.server_runtime_install_requested.connect(
            lambda: requested.append(True))
        try:
            page.set_server_runtime_available(False, True)
            page._btn_server_install_runtime.click()
            self.assertEqual(requested, [True])
            self.assertFalse(
                page._btn_server_install_runtime.isEnabled())
            self.assertEqual(
                page._btn_server_install_runtime.text(),
                "正在安装",
            )
            self.assertIn(
                "正在安装",
                page._server_runtime_hint.text(),
            )
        finally:
            page.cleanup()
            page.deleteLater()
            APP.processEvents()

    def test_main_window_starts_and_stops_server_mode(self):
        port = _free_port()
        with tempfile.TemporaryDirectory() as temp, mock.patch(
                "anhutoolbox.hardware.collect_hardware_info",
                return_value={}):
            window = MainWindow(temp)
            page = window._mqtt_page
            try:
                window.sidebar._mode_group.button(3).click()
                page.show_server_mode()
                window.sidebar._sp_mqtt_server_port.setValue(port)
                self.assertEqual(
                    window.sidebar._btn_connect.text(), "启动服务端")
                page.show_client_mode()
                self.assertEqual(
                    window.sidebar._btn_connect.text(), "连接服务端")
                page.show_server_mode()
                self.assertEqual(
                    window.sidebar._btn_connect.text(), "启动服务端")
                window.sidebar._btn_connect.click()
                deadline = time.monotonic() + 6
                while (
                    not window._mqtt_broker.is_running
                    and time.monotonic() < deadline
                ):
                    APP.processEvents()
                    time.sleep(0.02)
                self.assertTrue(window._mqtt_broker.is_running)
                self.assertEqual(page._server_status.text(), "运行中")
                self.assertEqual(
                    window.sidebar._btn_connect.text(), "停止服务端")
                window.sidebar._btn_connect.click()
                APP.processEvents()
                self.assertFalse(window._mqtt_broker.is_running)
                self.assertEqual(page._server_status.text(), "已停止")
            finally:
                window._mqtt_broker.cleanup()
                window.close()
                window.deleteLater()
                APP.processEvents()

    def test_server_configuration_is_saved_in_snapshot(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch(
                "anhutoolbox.hardware.collect_hardware_info",
                return_value={}):
            window = MainWindow(temp)
            try:
                window.sidebar._mode_group.button(3).click()
                window._mqtt_page.show_server_mode()
                window.sidebar.set_mqtt_server_config({
                    "bind_address": "0.0.0.0",
                    "port": 18884,
                    "allow_anonymous": False,
                    "username": "server-user",
                    "password": "server-pass",
                    "max_connections": 321,
                    "persistence": True,
                    "users": [
                        {
                            "username": "server-user",
                            "password": "server-pass",
                            "enabled": True,
                            "topics": ["server/#"],
                            "access": "readwrite",
                        },
                        {
                            "username": "reader",
                            "password": "reader-pass",
                            "enabled": True,
                            "topics": ["public/#"],
                            "access": "read",
                        },
                        {
                            "username": "disabled",
                            "password": "disabled-pass",
                            "enabled": False,
                            "topics": ["#"],
                            "access": "readwrite",
                        },
                    ],
                    "tls": {
                        "enabled": True,
                        "ca_file": str(
                            ROOT / "tests" / "fixtures"
                            / "mqtt_tls" / "ca.crt"),
                        "cert_file": str(
                            ROOT / "tests" / "fixtures"
                            / "mqtt_tls" / "server.crt"),
                        "key_file": str(
                            ROOT / "tests" / "fixtures"
                            / "mqtt_tls" / "server.key"),
                        "require_client_cert": True,
                    },
                })
                snapshot = window._snapshot_ui()
                self.assertTrue(snapshot["mqtt"]["server_mode"])
                self.assertEqual(
                    snapshot["mqtt"]["server"]["bind_address"], "0.0.0.0")
                self.assertEqual(snapshot["mqtt"]["server"]["port"], 18884)
                self.assertFalse(
                    snapshot["mqtt"]["server"]["allow_anonymous"])
                self.assertEqual(
                    snapshot["mqtt"]["server"]["username"], "server-user")
                self.assertEqual(
                    snapshot["mqtt"]["server"]["password"], "server-pass")
                self.assertEqual(
                    snapshot["mqtt"]["server"]["max_connections"], 321)
                self.assertTrue(
                    snapshot["mqtt"]["server"]["persistence"])
                self.assertEqual(
                    len(snapshot["mqtt"]["server"]["users"]), 3)
                self.assertEqual(
                    snapshot["mqtt"]["server"]["users"][1]["topics"],
                    ["public/#"],
                )
                self.assertTrue(
                    snapshot["mqtt"]["server"]["tls"]["enabled"])
                self.assertTrue(
                    snapshot["mqtt"]["server"]["tls"]
                    ["require_client_cert"])
                self.assertEqual(
                    window.sidebar._btn_mqtt_server_users.text(),
                    "用户与权限  (2)",
                )
                self.assertIs(
                    window.sidebar._settings_stack.currentWidget(),
                    window.sidebar._mqtt_server_settings_page,
                )
                self.assertFalse(window.sidebar._btn_connect.isHidden())
                self.assertEqual(
                    window.sidebar._btn_connect.text(), "启动服务端")
            finally:
                window._mqtt_broker.cleanup()
                window.close()
                window.deleteLater()
                APP.processEvents()

    def test_server_password_visibility_button_toggles_echo_mode(self):
        sidebar = Sidebar()
        try:
            for field, action in (
                (
                    sidebar._le_mqtt_password,
                    sidebar._mqtt_password_toggle_action,
                ),
                (
                    sidebar._le_mqtt_server_password,
                    sidebar._mqtt_server_password_toggle_action,
                ),
            ):
                self.assertEqual(
                    field.echoMode(), QLineEdit.EchoMode.Password)
                action.trigger()
                self.assertEqual(
                    field.echoMode(), QLineEdit.EchoMode.Normal)
                self.assertEqual(action.toolTip(), "隐藏密码")
                action.trigger()
                self.assertEqual(
                    field.echoMode(), QLineEdit.EchoMode.Password)
                self.assertEqual(action.toolTip(), "显示密码")
        finally:
            sidebar.deleteLater()
            APP.processEvents()

    def test_primary_server_user_update_does_not_replace_disabled_user(self):
        sidebar = Sidebar()
        try:
            sidebar.set_mqtt_server_config({
                "allow_anonymous": False,
                "username": "",
                "password": "",
                "users": [
                    {
                        "username": "disabled",
                        "password": "disabled-pass",
                        "enabled": False,
                        "topics": ["#"],
                        "access": "readwrite",
                    },
                    {
                        "username": "active",
                        "password": "active-pass",
                        "enabled": True,
                        "topics": ["active/#"],
                        "access": "readwrite",
                    },
                ],
            })
            sidebar._le_mqtt_server_user.setText("active-renamed")
            users = sidebar.mqtt_server_config()["users"]
            self.assertEqual(users[0]["username"], "disabled")
            self.assertEqual(users[1]["username"], "active-renamed")
            self.assertTrue(users[1]["enabled"])
        finally:
            sidebar.deleteLater()
            APP.processEvents()

    def test_server_user_changes_apply_before_outer_dialog_closes(self):
        sidebar = Sidebar()
        users = [{
            "username": "immediate",
            "password": "secret",
            "enabled": True,
            "topics": ["immediate/#"],
            "access": "readwrite",
        }]
        fake_dialog = mock.MagicMock()
        fake_dialog.users.return_value = users
        fake_dialog.users_changed.connect.side_effect = (
            lambda callback: callback())
        fake_dialog.exec.return_value = QDialog.DialogCode.Rejected
        try:
            with mock.patch(
                    "anhutoolbox.sidebar.MQTTUsersDialog",
                    return_value=fake_dialog):
                sidebar._edit_mqtt_server_users()
            self.assertEqual(
                sidebar._mqtt_server_users[0]["username"], "immediate")
            self.assertEqual(
                sidebar._le_mqtt_server_user.text(), "immediate")
        finally:
            sidebar.deleteLater()
            APP.processEvents()

    def test_local_client_inherits_server_tls_and_requires_client_cert(self):
        tls_dir = ROOT / "tests" / "fixtures" / "mqtt_tls"
        with tempfile.TemporaryDirectory() as temp, mock.patch(
                "anhutoolbox.hardware.collect_hardware_info",
                return_value={}):
            window = MainWindow(temp)
            try:
                window.sidebar.set_mqtt_server_config({
                    "bind_address": "127.0.0.1",
                    "port": 18883,
                    "allow_anonymous": True,
                    "tls": {
                        "enabled": True,
                        "ca_file": str(tls_dir / "ca.crt"),
                        "cert_file": str(tls_dir / "server.crt"),
                        "key_file": str(tls_dir / "server.key"),
                        "require_client_cert": True,
                    },
                })
                with mock.patch.object(
                        window, "_connect_mqtt") as connect, mock.patch(
                        "anhutoolbox.main_window.show_warning"
                ) as warning:
                    window._on_mqtt_connect_local()
                    connect.assert_not_called()
                    warning.assert_called_once()

                window.sidebar.set_mqtt_client_tls_config({
                    "enabled": True,
                    "ca_file": "",
                    "cert_file": str(tls_dir / "client.crt"),
                    "key_file": str(tls_dir / "client.key"),
                    "insecure": False,
                })
                with mock.patch.object(
                        window, "_connect_mqtt") as connect:
                    window._on_mqtt_connect_local()
                    connect.assert_called_once()
                client_tls = window.sidebar.mqtt_client_tls_config()
                self.assertTrue(client_tls["enabled"])
                self.assertEqual(
                    client_tls["ca_file"], str(tls_dir / "ca.crt"))
                self.assertTrue(client_tls["cert_file"])
                self.assertTrue(client_tls["key_file"])
            finally:
                window._mqtt_broker.cleanup()
                window.close()
                window.deleteLater()
                APP.processEvents()

    def test_mqtt_security_dialogs_validate_and_return_configuration(self):
        user_dialog = MQTTUserEditDialog(is_new=True)
        try:
            user_dialog.username.setText("设备用户")
            user_dialog.password.setText("设备密码")
            user_dialog.topics.setPlainText("device/one/#\ndevice/two/#")
            user_dialog.access.setCurrentIndex(
                user_dialog.access.findData("read"))
            user_dialog._validate()
            self.assertEqual(
                user_dialog.result(), QDialog.DialogCode.Accepted)
            user = user_dialog.user_data()
            self.assertEqual(user["username"], "设备用户")
            self.assertEqual(
                user["topics"], ["device/one/#", "device/two/#"])
            self.assertEqual(user["access"], "read")
        finally:
            user_dialog.deleteLater()

        users_dialog = MQTTUsersDialog(
            [user], allow_anonymous=False)
        try:
            self.assertEqual(users_dialog.table.rowCount(), 1)
            self.assertEqual(users_dialog.users()[0]["username"], "设备用户")
            self.assertEqual(
                users_dialog.table.selectionMode(),
                QAbstractItemView.SelectionMode.NoSelection,
            )
            self.assertNotIn(
                "编辑",
                [button.text() for button in users_dialog.findChildren(
                    QPushButton)],
            )
        finally:
            users_dialog.deleteLater()

        delete_dialog = MQTTUsersDialog([
            dict(user, username="user-a"),
            dict(user, username="user-b"),
            dict(user, username="user-c"),
        ])
        try:
            for row in (0, 2):
                checkbox = delete_dialog.table.cellWidget(
                    row, 0).findChild(QCheckBox)
                checkbox.setChecked(True)
            delete_dialog._remove_user()
            self.assertEqual(
                [item["username"] for item in delete_dialog.users()],
                ["user-b"],
            )
            self.assertEqual(delete_dialog.table.rowCount(), 1)
            with mock.patch(
                    "anhutoolbox.mqtt_server_dialogs.show_warning"
            ) as warning:
                delete_dialog._remove_user()
                warning.assert_called_once()
            self.assertEqual(
                [item["username"] for item in delete_dialog.users()],
                ["user-b"],
            )
        finally:
            delete_dialog.deleteLater()

        immediate_dialog = MQTTUsersDialog([user])
        changes = []
        immediate_dialog.users_changed.connect(
            lambda: changes.append(True))
        added_user = dict(user, username="新增用户")
        fake_add = mock.Mock()
        fake_add.exec.return_value = QDialog.DialogCode.Accepted
        fake_add.user_data.return_value = added_user
        with mock.patch(
                "anhutoolbox.mqtt_server_dialogs.MQTTUserEditDialog",
                return_value=fake_add):
            immediate_dialog._add_user()
        self.assertEqual(
            [item["username"] for item in immediate_dialog.users()],
            ["设备用户", "新增用户"],
        )
        self.assertEqual(changes, [True])

        fake_edit = mock.Mock()
        fake_edit.exec.return_value = QDialog.DialogCode.Accepted
        fake_edit.user_data.return_value = dict(
            added_user, username="编辑后的用户")
        with mock.patch(
                "anhutoolbox.mqtt_server_dialogs.MQTTUserEditDialog",
                return_value=fake_edit):
            immediate_dialog._on_cell_double_clicked(1, 1)
        self.assertEqual(
            immediate_dialog.users()[1]["username"], "编辑后的用户")
        self.assertEqual(changes, [True, True])
        immediate_dialog.deleteLater()

        tls_dir = ROOT / "tests" / "fixtures" / "mqtt_tls"
        tls_dialog = MQTTTlsDialog(
            {
                "enabled": True,
                "ca_file": str(tls_dir / "ca.crt"),
                "cert_file": str(tls_dir / "server.crt"),
                "key_file": str(tls_dir / "server.key"),
                "require_client_cert": True,
            },
            server_mode=True,
        )
        try:
            tls_dialog._validate()
            self.assertEqual(
                tls_dialog.result(), QDialog.DialogCode.Accepted)
            config = tls_dialog.tls_config()
            self.assertTrue(config["enabled"])
            self.assertTrue(config["require_client_cert"])
        finally:
            tls_dialog.deleteLater()
        APP.processEvents()


if __name__ == "__main__":
    unittest.main()
