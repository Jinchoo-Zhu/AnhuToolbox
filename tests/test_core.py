# -*- coding: utf-8 -*-
"""核心回归测试：不访问真实串口或用户数据。"""

import os
import socket
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import serial
from PySide6.QtWidgets import QTextBrowser, QWidget

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from anhutoolbox.main_window import MainWindow, _profile_bool, _profile_int
from anhutoolbox.app_paths import choose_data_root
from anhutoolbox.dialogs import AnhuDialog
from anhutoolbox.panels import LogPanel, PresetPanel, SendBar, parse_hex_bytes
from anhutoolbox.projects import ProjectManager
from anhutoolbox.tools import (
    AmountTool, BaseTool, DiffTool, NetworkTool, QRTool, TimestampTool,
)
from anhutoolbox.workers import (
    SerialReadWorker, TCPClientWorker, TCPServerWorker,
)


APP = QApplication.instance() or QApplication([])
ROOT = Path(__file__).resolve().parents[1]


def close_window(window):
    window.close()
    window.deleteLater()
    APP.processEvents()


class ToolTests(unittest.TestCase):
    def test_timestamp_seconds_milliseconds_and_formats(self):
        tool = TimestampTool()
        try:
            tool._ts_input.setText("1700000000")
            APP.processEvents()
            self.assertEqual(tool._ts_result.text(), "2023-11-15 06:13:20")

            tool._ts_input.setText("1700000000000")
            APP.processEvents()
            self.assertEqual(tool._ts_result.text(), "2023-11-15 06:13:20")

            tool._dt_input.setText("2026/08/03 14:30:00")
            APP.processEvents()
            self.assertNotEqual(tool._dt_ts.text(), "格式错误")

            tool._dt_input.setText("2026-08-03")
            APP.processEvents()
            self.assertNotEqual(tool._dt_ts.text(), "格式错误")
        finally:
            tool.stop_timer()

    def test_diff_with_equal_lines(self):
        tool = DiffTool()
        tool._left_text.setPlainText("A\nB")
        tool._right_text.setPlainText("A\nC")
        tool._compare()
        self.assertGreaterEqual(len(tool._left_text.extraSelections()), 1)
        self.assertGreaterEqual(len(tool._right_text.extraSelections()), 1)

    def test_base_conversion_supports_negative_numbers(self):
        tool = BaseTool()
        tool._base_input.setText("-1")
        APP.processEvents()
        self.assertEqual(tool._results[2].text(), "-1")
        self.assertEqual(tool._results[8].text(), "-1")
        self.assertEqual(tool._results[16].text(), "-1")

    def test_long_dialog_uses_scrollable_browser(self):
        dialog = AnhuDialog(
            None, "测试", "\n".join("line {}".format(i) for i in range(100)))
        try:
            self.assertIsInstance(dialog.message_label, QTextBrowser)
            dialog.show()
            APP.processEvents()
            self.assertGreater(
                dialog.message_label.verticalScrollBar().maximum(), 0)
            self.assertLessEqual(
                dialog.message_label.geometry().bottom(),
                dialog._content_frame.height())
        finally:
            dialog.close()

    def test_qr_layout_and_batch_save_use_current_input(self):
        tool = QRTool()
        tool._qr_input.setPlainText("001\n002\n005")
        tool._generate()
        self.assertEqual(
            tool._grid.count(), tool._grid.rowCount() * tool.COLS)
        tool._qr_input.setPlainText("003\n002")
        with tempfile.TemporaryDirectory() as temp:
            path = os.path.join(temp, "qr.zip")
            with mock.patch(
                    "anhutoolbox.tools.QFileDialog.getSaveFileName",
                    return_value=(path, "")), \
                    mock.patch("anhutoolbox.tools.show_success"):
                tool._batch_save()
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(
                    archive.namelist(), ["003.png", "002.png"])
        self.assertEqual(tool._lines, ["003", "002"])

    def test_copy_toast_reuses_indicator_widget(self):
        tool = AmountTool()
        tool._amount_input.setText("1.00")
        APP.processEvents()
        for _ in range(3):
            tool._copy_upper()
            APP.processEvents()
        ticks = [
            child for child in tool._copy_toast.findChildren(QWidget)
            if child.objectName() == "copy_toast_tick"
        ]
        self.assertEqual(len(ticks), 1)
        tool.close()

    def test_network_scans_are_mutually_exclusive(self):
        tool = NetworkTool()
        tool._scan_running = True
        tool._port_host.setText("127.0.0.1")
        with mock.patch("anhutoolbox.tools.show_warning") as warning:
            tool._start_port_scan()
        warning.assert_called_once()
        tool.stop_tasks()


class HexTests(unittest.TestCase):
    def test_strict_hex_parser(self):
        self.assertEqual(parse_hex_bytes("12 34"), b"\x12\x34")
        self.assertEqual(parse_hex_bytes("0x12,0x34"), b"\x12\x34")
        with self.assertRaises(ValueError):
            parse_hex_bytes("GG12")
        with self.assertRaises(ValueError):
            parse_hex_bytes("123")

    def test_send_bar_rejects_invalid_hex(self):
        bar = SendBar()
        bar.chk_hex.setChecked(True)
        bar.text.setPlainText("GG12")
        self.assertIsNone(bar._build_data(silent=True))
        bar.text.setPlainText("01 02 03")
        self.assertEqual(
            bar._build_data(silent=True),
            b"\x01\x02\x03\x61\x61")

    def test_repeat_send_includes_checksum(self):
        bar = SendBar()
        bar.chk_hex.setChecked(True)
        bar.text.setPlainText("01 02 03")
        bar.cb_checksum.setCurrentText("ModbusCRC16")
        self.assertEqual(
            bar._build_data(silent=True),
            b"\x01\x02\x03\x61\x61")


class CommunicationTests(unittest.TestCase):
    def test_serial_framing_scales_with_baud(self):
        slow = SimpleNamespace(
            baudrate=9600, bytesize=8, stopbits=1, parity="N")
        fast = SimpleNamespace(
            baudrate=921600, bytesize=8, stopbits=1, parity="N")
        slow_gap, slow_hold = SerialReadWorker._framing_times(slow)
        fast_gap, fast_hold = SerialReadWorker._framing_times(fast)
        self.assertGreater(slow_gap, 0.001)
        self.assertLess(fast_gap, slow_gap)
        self.assertGreater(slow_hold, 0.05)

    def test_tcp_server_bind_failure_resets_worker(self):
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        worker = TCPServerWorker()
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                blocker.setsockopt(
                    socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            blocker.bind(("0.0.0.0", 0))
            blocker.listen(1)
            port = blocker.getsockname()[1]
            worker.configure(port)
            failures = []
            worker.start_failed.connect(failures.append)
            worker.start()
            self.assertTrue(worker.wait(3000))
            APP.processEvents()
            self.assertFalse(worker._running)
            self.assertEqual(len(failures), 1)
        finally:
            if worker.isRunning():
                worker.stop()
            blocker.close()

    def test_tcp_client_local_bind_failure_resets_worker(self):
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        worker = TCPClientWorker()
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                blocker.setsockopt(
                    socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            blocker.bind(("0.0.0.0", 0))
            blocker.listen(1)
            port = blocker.getsockname()[1]
            worker.configure("127.0.0.1", 1, port)
            failures = []
            worker.connect_failed.connect(failures.append)
            worker.start()
            self.assertTrue(worker.wait(3000))
            APP.processEvents()
            self.assertFalse(worker._running)
            self.assertFalse(worker.is_connected)
            self.assertEqual(len(failures), 1)
        finally:
            if worker.isRunning():
                worker.stop()
            blocker.close()

    def test_tcp_client_send_failure_disconnects(self):
        sock = mock.Mock()
        sock.sendall.side_effect = OSError("send failed")
        worker = TCPClientWorker()
        worker._connected = True
        worker._sock = sock
        disconnected = []
        worker.disconnected.connect(lambda: disconnected.append(True))
        self.assertFalse(worker.send(b"x"))
        self.assertFalse(worker.is_connected)
        self.assertEqual(disconnected, [True])

    def test_tcp_server_disconnect_uses_stored_address(self):
        client = mock.Mock()
        client.getpeername.side_effect = OSError("peer gone")
        worker = TCPServerWorker()
        worker._clients = [client]
        worker._client_addrs[id(client)] = ("192.0.2.1", 12345)
        events = []
        worker.client_disconnected.connect(
            lambda host, port: events.append((host, port)))
        worker._remove_client(client)
        self.assertEqual(events, [("192.0.2.1", 12345)])

    def test_failed_send_is_not_recorded_as_tx(self):
        sock = mock.Mock()
        sock.sendall.side_effect = OSError("send failed")
        sock.getsockname.return_value = ("127.0.0.1", 1234)
        with tempfile.TemporaryDirectory() as temp:
            window = MainWindow(temp)
            try:
                window._tcp_client._connected = True
                window._tcp_client._sock = sock
                window._active_worker = window._tcp_client
                window._on_send_data(b"XYZ")
                APP.processEvents()
                self.assertEqual(window.log_panel._tx_total, 0)
                self.assertEqual(window.send_bar._tx_total, 0)
                self.assertIsNone(window._active_worker)
            finally:
                window._active_worker = None
                close_window(window)

    def test_serial_error_resets_main_window_state(self):
        fake_serial = type("FakeSerial", (), {
            "is_open": True,
            "read": lambda self, n: (_ for _ in ()).throw(
                serial.SerialException("device unplugged")),
            "close": lambda self: None,
        })()
        with tempfile.TemporaryDirectory() as temp:
            window = MainWindow(temp)
            try:
                window._serial_worker._serial = fake_serial
                window._active_worker = window._serial_worker
                window.sidebar.set_connected(True)
                window._serial_worker.start()
                self.assertTrue(window._serial_worker.wait(2000))
                APP.processEvents()
                self.assertFalse(window.sidebar.is_connected)
                self.assertIsNone(window._active_worker)
                self.assertEqual(window._lbl_status_text.text(), "串口已断开")
            finally:
                window._active_worker = None
                close_window(window)


class PersistenceTests(unittest.TestCase):
    def test_profile_fields_are_tolerant(self):
        self.assertEqual(_profile_int("bad", 30, 0, 3600), 30)
        self.assertEqual(_profile_int("99999", 30, 0, 3600), 3600)
        self.assertFalse(_profile_bool("false", True))
        self.assertTrue(_profile_bool("true", False))

    def test_main_window_loads_malformed_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            window = MainWindow(temp)
            try:
                window._applying = True
                window._apply_profile({
                    "mode": ["bad"],
                    "tcpserver": {"port": "bad", "client_timeout": "bad"},
                    "tcpclient": {"host": None, "port": "bad", "local_port": "bad"},
                    "send": {"interval": "bad", "start_byte": "bad", "hex_send": "false"},
                    "log": {"timeout": "bad"},
                    "presets": "bad",
                })
                self.assertEqual(window.sidebar.current_mode, "serial")
                self.assertEqual(window.sidebar.sp_server_port.value(), 8888)
                self.assertEqual(window.sidebar.sp_client_timeout.value(), 30)
                self.assertEqual(window.send_bar.sp_interval.value(), 1000)
                self.assertFalse(window.send_bar.chk_hex.isChecked())
                self.assertEqual(window.log_panel.sp_timeout.value(), 0)
            finally:
                window._applying = False
                close_window(window)

    def test_sanitized_project_names_do_not_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = ProjectManager(temp)
            manager.create("a/b", {"value": 1})
            manager.create("a?b", {"value": 2})
            self.assertEqual(manager.load("a/b")["value"], 1)
            self.assertEqual(manager.load("a?b")["value"], 2)
            self.assertEqual(len(manager.names()), 2)

    def test_read_only_install_uses_local_appdata(self):
        with tempfile.TemporaryDirectory() as temp:
            app_dir = os.path.join(temp, "app")
            old_data = os.path.join(app_dir, "data")
            os.makedirs(os.path.join(old_data, "projects"))
            Path(old_data, "settings.json").write_text("{}", encoding="utf-8")
            Path(old_data, "projects", "old.json").write_text(
                '{"name": "old"}', encoding="utf-8")
            local = os.path.join(temp, "local")
            preferred = os.path.normcase(os.path.abspath(old_data))

            def writable(path):
                return os.path.normcase(os.path.abspath(path)) != preferred

            with mock.patch.dict(os.environ, {"LOCALAPPDATA": local}), \
                    mock.patch(
                        "anhutoolbox.app_paths._is_writable_dir",
                        side_effect=writable):
                root = choose_data_root(app_dir)
            self.assertEqual(
                root, os.path.join(local, "AnhuToolbox"))
            self.assertTrue(Path(
                root, "data", "settings.json").is_file())
            self.assertTrue(Path(
                root, "data", "projects", "old.json").is_file())

    def test_malformed_global_settings_fall_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as temp:
            data_dir = Path(temp, "data")
            data_dir.mkdir()
            Path(data_dir, "settings.json").write_text(
                '{"preset_visible": true, "preset_splitter": {"x": 1},'
                ' "serial": "broken"}',
                encoding="utf-8")
            window = MainWindow(temp)
            try:
                self.assertTrue(window.preset_panel.isVisible()
                                or window._btn_toggle_preset.isChecked())
                self.assertEqual(len(window._preset_splitter.sizes()), 2)
                self.assertEqual(window.sidebar.cb_baud.currentText(), "115200")
            finally:
                close_window(window)

    def test_preset_import_is_transactional_and_export_strips_runtime(self):
        panel = PresetPanel()
        with tempfile.TemporaryDirectory() as temp:
            bad_path = os.path.join(temp, "bad.json")
            Path(bad_path).write_text(
                '[{"name": "ok", "data": "31"}, "bad"]',
                encoding="utf-8")
            errors = []
            with mock.patch(
                    "anhutoolbox.panels.QFileDialog.getOpenFileName",
                    return_value=(bad_path, "")), \
                    mock.patch(
                        "anhutoolbox.panels.show_error",
                        side_effect=lambda *args: errors.append(args[-1])):
                panel._import()
            self.assertTrue(errors)
            self.assertEqual(panel._presets, [])

            good_path = os.path.join(temp, "good.json")
            Path(good_path).write_text(
                '[{"name": "loop", "data": "31", "enabled": true}]',
                encoding="utf-8")
            with mock.patch(
                    "anhutoolbox.panels.QFileDialog.getOpenFileName",
                    return_value=(good_path, "")), \
                    mock.patch("anhutoolbox.panels.show_success"):
                panel._import()
            self.assertFalse(panel._presets[0]["enabled"])

            out_path = os.path.join(temp, "out.json")
            panel._presets[0]["enabled"] = True
            with mock.patch(
                    "anhutoolbox.panels.QFileDialog.getSaveFileName",
                    return_value=(out_path, "")), \
                    mock.patch("anhutoolbox.panels.show_success"):
                panel._export()
            exported = __import__("json").loads(
                Path(out_path).read_text(encoding="utf-8"))
            self.assertNotIn("enabled", exported[0])
            panel.stop_timer()

    def test_paused_log_clear_discards_pending_data(self):
        panel = LogPanel()
        panel.chk_pause.setChecked(True)
        panel.append_data("rx", b"ABC")
        panel.clear()
        panel.chk_pause.setChecked(False)
        APP.processEvents()
        self.assertEqual(panel._rx_total, 0)
        self.assertEqual(panel.text.toPlainText(), "")

    def test_log_file_error_disables_saving(self):
        panel = LogPanel()
        bad_file = mock.Mock()
        bad_file.write.side_effect = OSError("disk full")
        panel._save_file = bad_file
        panel.chk_save_file.blockSignals(True)
        panel.chk_save_file.setChecked(True)
        panel.chk_save_file.blockSignals(False)
        errors = []
        panel.file_error.connect(errors.append)
        panel.append_data("rx", b"ABC")
        panel._flush_display()
        self.assertTrue(errors)
        self.assertFalse(panel.chk_save_file.isChecked())

    def test_corrupt_project_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            window = MainWindow(temp)
            try:
                name = window._current_project
                path = window._pm.path_of(name)
                Path(path).write_text("{broken", encoding="utf-8")
                window._load_project(name)
                window.send_bar.text.setPlainText("changed")
                window._autosave_project()
                self.assertEqual(Path(path).read_text(encoding="utf-8"),
                                 "{broken")
                self.assertTrue(window._project_load_failed)
            finally:
                close_window(window)


if __name__ == "__main__":
    unittest.main()
