# -*- coding: utf-8 -*-
"""Regression tests for independent serial and TCP stream windows."""

import os
import socket
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt

from anhutoolbox.main_window import MainWindow


APP = QApplication.instance() or QApplication([])


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _wait(predicate, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        APP.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return bool(predicate())


class StreamWindowTests(unittest.TestCase):
    def _window(self, temp):
        window = MainWindow(temp)
        window.resize(1500, 900)
        window.show()
        APP.processEvents()
        return window

    def _close(self, window):
        window._stop_all_stream_workers()
        window.close()
        window.deleteLater()
        APP.processEvents()

    def test_dual_and_quad_layouts_keep_independent_page_state(self):
        with tempfile.TemporaryDirectory() as temp:
            window = self._window(temp)
            try:
                workspace = window._stream_workspaces["serial"]
                layout = window.sidebar._stream_layout_combos["serial"]
                selector = window.sidebar._stream_window_combos["serial"]
                self.assertEqual(
                    layout.currentData(), "single")
                self.assertEqual(
                    [layout.itemText(index) for index in range(3)],
                    ["单窗口", "双窗口", "四窗口"],
                )
                self.assertFalse(selector.isVisible())

                layout.setCurrentIndex(layout.findData("dual"))
                APP.processEvents()
                self.assertEqual(workspace.layout_mode, "dual")
                self.assertTrue(selector.isVisible())
                self.assertEqual(selector.count(), 2)

                first = workspace.page(0)
                second = workspace.page(1)
                first.send_bar.text.setPlainText("window one")
                first.log_panel.chk_hex.setChecked(False)
                first.log_panel.chk_timestamp.setChecked(False)
                first.log_panel.sp_timeout.setValue(125)
                first.send_bar.chk_hex.setChecked(True)
                first.send_bar.chk_crlf.setChecked(False)
                window.preset_panel.load_from_project([{
                    "name": "window-one",
                    "data": "31",
                    "hex_mode": True,
                    "interval": 1000,
                    "enabled": False,
                }])
                window.sidebar.cb_port.setCurrentText("COM11")

                selector.setCurrentIndex(1)
                APP.processEvents()
                self.assertEqual(workspace.active_index, 1)
                self.assertEqual(
                    window.sidebar.cb_port.currentText(), "COM1")
                second.send_bar.text.setPlainText("window two")
                second.log_panel.chk_hex.setChecked(True)
                second.log_panel.chk_timestamp.setChecked(True)
                second.log_panel.sp_timeout.setValue(250)
                second.send_bar.chk_hex.setChecked(False)
                second.send_bar.chk_crlf.setChecked(True)
                window.sidebar.cb_port.setCurrentText("COM22")

                selector.setCurrentIndex(0)
                APP.processEvents()
                self.assertEqual(window.send_bar.text.toPlainText(),
                                 "window one")
                self.assertEqual(
                    window.sidebar.cb_port.currentText(), "COM11")
                self.assertFalse(window.log_panel.chk_hex.isChecked())
                self.assertFalse(window.log_panel.chk_timestamp.isChecked())
                self.assertEqual(window.log_panel.sp_timeout.value(), 125)
                self.assertTrue(window.send_bar.chk_hex.isChecked())
                self.assertFalse(window.send_bar.chk_crlf.isChecked())
                self.assertEqual(
                    window.preset_panel.dump_presets()[0]["name"],
                    "window-one",
                )
                self.assertIn(
                    "#0078D4", workspace.frame(0).styleSheet())
                self.assertNotIn(
                    "#0078D4", workspace.frame(1).styleSheet())

                workspace.set_active(1)
                APP.processEvents()
                self.assertEqual(selector.currentIndex(), 1)
                self.assertEqual(window.send_bar.text.toPlainText(),
                                 "window two")
                self.assertEqual(
                    window.sidebar.cb_port.currentText(), "COM22")
                self.assertTrue(window.log_panel.chk_hex.isChecked())
                self.assertTrue(window.log_panel.chk_timestamp.isChecked())
                self.assertEqual(window.log_panel.sp_timeout.value(), 250)
                self.assertFalse(window.send_bar.chk_hex.isChecked())
                self.assertTrue(window.send_bar.chk_crlf.isChecked())
                self.assertEqual(
                    window.preset_panel.dump_presets()[0]["name"],
                    "window-one",
                )

                QTest.mouseClick(
                    workspace.page(1).log_panel.chk_hex,
                    Qt.MouseButton.LeftButton,
                )
                APP.processEvents()
                self.assertEqual(workspace.active_index, 1)
                self.assertFalse(
                    workspace.page(1).log_panel.chk_hex.isChecked())

                selector.setCurrentIndex(0)
                APP.processEvents()
                QTest.mouseClick(
                    workspace.page(0).log_panel.text,
                    Qt.MouseButton.LeftButton,
                )
                APP.processEvents()
                self.assertEqual(workspace.active_index, 0)
                self.assertEqual(selector.currentIndex(), 0)

                single_font_height = (
                    first.log_panel.text.fontMetrics().height())
                layout.setCurrentIndex(layout.findData("quad"))
                APP.processEvents()
                self.assertEqual(workspace.layout_mode, "quad")
                self.assertEqual(selector.count(), 4)
                selector.setCurrentIndex(2)
                APP.processEvents()
                self.assertEqual(workspace.active_index, 2)
                self.assertEqual(
                    window.sidebar.stream_active_window("serial"), 3)
                self.assertTrue(all(
                    workspace.frame(index).isVisible()
                    for index in range(4)
                ))
                self.assertLess(
                    workspace.page(0).log_panel.text.fontMetrics().height(),
                    single_font_height,
                )
                self.assertEqual(
                    workspace.page(0).log_panel.text.font().pixelSize(),
                    11,
                )
                self.assertEqual(
                    workspace.page(0).send_bar.text.font().pixelSize(),
                    11,
                )
                for index in range(4):
                    self.assertEqual(
                        workspace.page(index).layout().count(), 1)
                self.assertIs(
                    workspace._shared_send_bar,
                    workspace.page(2).send_bar,
                )
                self.assertIs(
                    workspace._shared_toolbar,
                    workspace.page(2).toolbar,
                )
                workspace.set_active(1)
                APP.processEvents()
                self.assertIs(
                    workspace._shared_send_bar,
                    workspace.page(1).send_bar,
                )
                self.assertIs(
                    workspace._shared_toolbar,
                    workspace.page(1).toolbar,
                )
                layout.setCurrentIndex(layout.findData("single"))
                APP.processEvents()
                self.assertEqual(workspace.active_index, 0)
                self.assertNotIn(
                    "#0078D4", workspace.frame(0).styleSheet())
                self.assertGreaterEqual(
                    workspace.page(0).log_panel.text.fontMetrics().height(),
                    single_font_height,
                )
            finally:
                self._close(window)

    def test_each_mode_keeps_its_own_layout_and_current_window(self):
        with tempfile.TemporaryDirectory() as temp:
            window = self._window(temp)
            try:
                serial_layout = (
                    window.sidebar._stream_layout_combos["serial"])
                serial_layout.setCurrentIndex(
                    serial_layout.findData("dual"))
                serial_selector = (
                    window.sidebar._stream_window_combos["serial"])
                serial_selector.setCurrentIndex(1)
                window.sidebar.cb_port.setCurrentText("COM42")
                window.preset_panel.load_from_project([{
                    "name": "project-shared",
                    "data": "31",
                    "hex_mode": True,
                    "interval": 1000,
                    "enabled": False,
                }])
                APP.processEvents()

                window.sidebar._mode_group.button(1).click()
                APP.processEvents()
                server_layout = (
                    window.sidebar._stream_layout_combos["tcpserver"])
                server_layout.setCurrentIndex(
                    server_layout.findData("quad"))
                server_selector = (
                    window.sidebar._stream_window_combos["tcpserver"])
                server_selector.setCurrentIndex(2)
                window.sidebar.sp_server_port.setValue(19001)
                APP.processEvents()

                window.sidebar._mode_group.button(2).click()
                APP.processEvents()
                self.assertEqual(
                    window.sidebar.stream_layout("tcpclient"),
                    "single",
                )
                window.sidebar.le_client_host.setText("10.0.0.5")

                window.sidebar._mode_group.button(3).click()
                APP.processEvents()
                self.assertIs(
                    window._comm_stack.currentWidget(),
                    window._mqtt_page,
                )

                window.sidebar._mode_group.button(0).click()
                APP.processEvents()
                self.assertEqual(
                    window.sidebar.stream_layout("serial"), "dual")
                self.assertEqual(
                    window.sidebar.stream_active_window("serial"), 2)
                self.assertEqual(
                    window.sidebar.cb_port.currentText(), "COM42")

                window.sidebar._mode_group.button(1).click()
                APP.processEvents()
                self.assertEqual(
                    window.sidebar.stream_layout("tcpserver"), "quad")
                self.assertEqual(
                    window.sidebar.stream_active_window("tcpserver"), 3)
                self.assertEqual(
                    window.sidebar.sp_server_port.value(), 19001)
                self.assertEqual(
                    window.preset_panel.dump_presets()[0]["name"],
                    "project-shared",
                )

                window.preset_panel.load_from_project([{
                    "name": "project-shared-edited",
                    "data": "32",
                    "hex_mode": True,
                    "interval": 1000,
                    "enabled": False,
                }])
                window.sidebar._mode_group.button(0).click()
                APP.processEvents()
                self.assertEqual(
                    window.preset_panel.dump_presets()[0]["name"],
                    "project-shared-edited",
                )

                snapshot = window._snapshot_ui()
                self.assertEqual(snapshot["format"], 2)
                self.assertEqual(
                    snapshot["stream_workspaces"]["serial"]["layout"],
                    "dual",
                )
                self.assertEqual(
                    snapshot["stream_workspaces"]["tcpserver"]
                    ["active_window"],
                    3,
                )
                self.assertEqual(
                    snapshot["presets"][0]["name"],
                    "project-shared-edited",
                )
            finally:
                self._close(window)

    def test_each_quad_pane_can_be_selected_by_clicking_content(self):
        with tempfile.TemporaryDirectory() as temp:
            window = self._window(temp)
            try:
                layout = window.sidebar._stream_layout_combos["serial"]
                layout.setCurrentIndex(layout.findData("quad"))
                APP.processEvents()
                workspace = window._stream_workspaces["serial"]
                selector = (
                    window.sidebar._stream_window_combos["serial"])
                for index in range(4):
                    QTest.mouseClick(
                        workspace.page(index).log_panel.text,
                        Qt.MouseButton.LeftButton,
                    )
                    APP.processEvents()
                    self.assertEqual(workspace.active_index, index)
                    self.assertEqual(selector.currentIndex(), index)
            finally:
                self._close(window)

    def test_preset_panel_visibility_is_shared_across_windows(self):
        with tempfile.TemporaryDirectory() as temp:
            window = self._window(temp)
            try:
                layout = window.sidebar._stream_layout_combos["serial"]
                layout.setCurrentIndex(layout.findData("quad"))
                APP.processEvents()
                workspace = window._stream_workspaces["serial"]
                selector = (
                    window.sidebar._stream_window_combos["serial"])

                workspace.page(0).btn_toggle_preset.setChecked(True)
                APP.processEvents()
                self.assertTrue(window.preset_panel.isVisible())

                selector.setCurrentIndex(2)
                APP.processEvents()
                self.assertEqual(workspace.active_index, 2)
                self.assertTrue(window.preset_panel.isVisible())
                self.assertTrue(
                    workspace.page(2).btn_toggle_preset.isChecked())

                workspace.page(2).btn_toggle_preset.setChecked(False)
                APP.processEvents()
                self.assertFalse(window.preset_panel.isVisible())
                selector.setCurrentIndex(0)
                APP.processEvents()
                self.assertFalse(window.preset_panel.isVisible())
                self.assertFalse(
                    workspace.page(0).btn_toggle_preset.isChecked())
            finally:
                self._close(window)

    def test_two_tcp_server_windows_run_and_survive_mode_switch(self):
        with tempfile.TemporaryDirectory() as temp:
            window = self._window(temp)
            first_port = _free_port()
            second_port = _free_port()
            try:
                window.sidebar._mode_group.button(1).click()
                APP.processEvents()
                layout = window.sidebar._stream_layout_combos["tcpserver"]
                layout.setCurrentIndex(layout.findData("dual"))
                selector = window.sidebar._stream_window_combos["tcpserver"]
                workers = window._stream_workers["tcpserver"]

                window.sidebar.sp_server_port.setValue(first_port)
                window._on_connect("tcpserver")
                self.assertTrue(_wait(lambda: workers[0].isRunning()))

                selector.setCurrentIndex(1)
                APP.processEvents()
                window.sidebar.sp_server_port.setValue(second_port)
                window._on_connect("tcpserver")
                self.assertTrue(_wait(lambda: workers[1].isRunning()))

                self.assertTrue(workers[0].isRunning())
                self.assertTrue(workers[1].isRunning())
                self.assertIs(window._active_worker, workers[1])

                first_client = socket.create_connection(
                    ("127.0.0.1", first_port), timeout=2)
                second_client = socket.create_connection(
                    ("127.0.0.1", second_port), timeout=2)
                try:
                    first_client.sendall(b"FIRST")
                    second_client.sendall(b"SECOND")
                    self.assertTrue(_wait(
                        lambda: window._stream_page_for(
                            "tcpserver", 0
                        ).log_panel._rx_total == 5
                        and window._stream_page_for(
                            "tcpserver", 1
                        ).log_panel._rx_total == 6
                    ))
                finally:
                    first_client.close()
                    second_client.close()

                window.sidebar._mode_group.button(3).click()
                APP.processEvents()
                self.assertTrue(workers[0].isRunning())
                self.assertTrue(workers[1].isRunning())

                window.sidebar._mode_group.button(1).click()
                APP.processEvents()
                self.assertEqual(
                    window.sidebar.stream_active_window("tcpserver"), 2)
                self.assertEqual(
                    window.sidebar.sp_server_port.value(), second_port)
                self.assertIs(window._active_worker, workers[1])
            finally:
                self._close(window)

    def test_two_tcp_client_windows_connect_independently(self):
        listeners = []
        try:
            for _ in range(2):
                listener = socket.socket(
                    socket.AF_INET, socket.SOCK_STREAM)
                listener.bind(("127.0.0.1", 0))
                listener.listen(2)
                listeners.append(listener)
            ports = [item.getsockname()[1] for item in listeners]
            with tempfile.TemporaryDirectory() as temp:
                window = self._window(temp)
                try:
                    window.sidebar._mode_group.button(2).click()
                    APP.processEvents()
                    layout = (
                        window.sidebar._stream_layout_combos["tcpclient"])
                    layout.setCurrentIndex(layout.findData("dual"))
                    selector = (
                        window.sidebar._stream_window_combos["tcpclient"])
                    workers = window._stream_workers["tcpclient"]

                    window.sidebar.le_client_host.setText("127.0.0.1")
                    window.sidebar.sp_client_port.setValue(ports[0])
                    window._on_connect("tcpclient")
                    self.assertTrue(_wait(
                        lambda: workers[0].is_connected))

                    selector.setCurrentIndex(1)
                    APP.processEvents()
                    window.sidebar.sp_client_port.setValue(ports[1])
                    window._on_connect("tcpclient")
                    self.assertTrue(_wait(
                        lambda: workers[1].is_connected))

                    self.assertTrue(workers[0].is_connected)
                    self.assertTrue(workers[1].is_connected)
                    self.assertIs(window._active_worker, workers[1])
                finally:
                    self._close(window)
        finally:
            for listener in listeners:
                listener.close()

    def test_shrinking_layout_stops_hidden_running_window(self):
        with tempfile.TemporaryDirectory() as temp:
            window = self._window(temp)
            try:
                window.sidebar._mode_group.button(1).click()
                APP.processEvents()
                layout = window.sidebar._stream_layout_combos["tcpserver"]
                layout.setCurrentIndex(layout.findData("dual"))
                selector = window.sidebar._stream_window_combos["tcpserver"]
                workers = window._stream_workers["tcpserver"]

                window.sidebar.sp_server_port.setValue(_free_port())
                window._on_connect("tcpserver")
                self.assertTrue(_wait(lambda: workers[0].isRunning()))
                selector.setCurrentIndex(1)
                APP.processEvents()
                window.sidebar.sp_server_port.setValue(_free_port())
                window._on_connect("tcpserver")
                self.assertTrue(_wait(lambda: workers[1].isRunning()))

                with mock.patch(
                        "anhutoolbox.main_window.ask_yes_no",
                        return_value=True,
                ):
                    layout.setCurrentIndex(layout.findData("single"))
                    APP.processEvents()
                self.assertTrue(workers[0].isRunning())
                self.assertFalse(workers[1].isRunning())
                self.assertEqual(
                    window.sidebar.stream_active_window("tcpserver"), 1)
            finally:
                self._close(window)

    def test_two_serial_windows_use_independent_workers(self):
        class FakeSerial:
            def __init__(self, port):
                self.port = port
                self.is_open = True
                self.in_waiting = 0
                self.dtr = False
                self.rts = False
                self.baudrate = 115200
                self.bytesize = 8
                self.stopbits = 1
                self.parity = "N"

            def read(self, _size):
                time.sleep(0.01)
                return b""

            def write(self, data):
                return len(data)

            def close(self):
                self.is_open = False

        first = FakeSerial("COM11")
        second = FakeSerial("COM22")
        with tempfile.TemporaryDirectory() as temp, mock.patch(
                "anhutoolbox.main_window.serial.Serial",
                side_effect=[first, second]):
            window = self._window(temp)
            try:
                window.sidebar.cb_port.setCurrentText("COM11")
                window._on_connect("serial")
                workers = window._stream_workers["serial"]
                self.assertTrue(_wait(lambda: workers[0].isRunning()))

                layout = window.sidebar._stream_layout_combos["serial"]
                layout.setCurrentIndex(layout.findData("dual"))
                selector = (
                    window.sidebar._stream_window_combos["serial"])
                selector.setCurrentIndex(1)
                APP.processEvents()
                window.sidebar.cb_port.setCurrentText("COM22")
                window._on_connect("serial")
                self.assertTrue(_wait(lambda: workers[1].isRunning()))

                self.assertTrue(workers[0].isRunning())
                self.assertTrue(workers[1].isRunning())
                self.assertIs(window._active_worker, workers[1])
                workers[0].data_received.emit(b"ONE")
                workers[1].data_received.emit(b"TWO")
                APP.processEvents()
                self.assertEqual(
                    window._stream_page_for(
                        "serial", 0).log_panel._rx_total, 3)
                self.assertEqual(
                    window._stream_page_for(
                        "serial", 1).log_panel._rx_total, 3)
                self.assertTrue(window._stop_all_stream_workers() == [])
            finally:
                self._close(window)

    def test_stream_workspace_state_round_trips_through_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            window = self._window(temp)
            try:
                serial_layout = (
                    window.sidebar._stream_layout_combos["serial"])
                serial_layout.setCurrentIndex(
                    serial_layout.findData("dual"))
                serial_selector = (
                    window.sidebar._stream_window_combos["serial"])
                serial_selector.setCurrentIndex(1)
                window.sidebar.cb_port.setCurrentText("COM77")
                window._stream_workspaces["serial"].page(
                    1).send_bar.text.setPlainText("saved second window")
                APP.processEvents()

                window.sidebar._mode_group.button(1).click()
                APP.processEvents()
                server_layout = (
                    window.sidebar._stream_layout_combos["tcpserver"])
                server_layout.setCurrentIndex(
                    server_layout.findData("quad"))
                server_selector = (
                    window.sidebar._stream_window_combos["tcpserver"])
                server_selector.setCurrentIndex(2)
                window.sidebar.sp_server_port.setValue(19123)
                APP.processEvents()

                snapshot = window._snapshot_ui()
                window.sidebar._mode_group.button(0).click()
                serial_layout.setCurrentIndex(
                    serial_layout.findData("single"))
                window.sidebar.cb_port.setCurrentText("COM1")
                APP.processEvents()

                window._applying = True
                try:
                    window._apply_profile(snapshot)
                finally:
                    window._applying = False
                APP.processEvents()

                self.assertEqual(window.sidebar.current_mode, "tcpserver")
                self.assertEqual(
                    window.sidebar.stream_layout("tcpserver"), "quad")
                self.assertEqual(
                    window.sidebar.stream_active_window("tcpserver"), 3)
                self.assertEqual(
                    window.sidebar.sp_server_port.value(), 19123)

                window.sidebar._mode_group.button(0).click()
                APP.processEvents()
                self.assertEqual(
                    window.sidebar.stream_layout("serial"), "dual")
                self.assertEqual(
                    window.sidebar.stream_active_window("serial"), 2)
                self.assertEqual(
                    window.sidebar.cb_port.currentText(), "COM77")
                self.assertEqual(
                    window.send_bar.text.toPlainText(),
                    "saved second window",
                )
            finally:
                self._close(window)

    def test_default_profile_does_not_inherit_hidden_stream_windows(self):
        with tempfile.TemporaryDirectory() as temp:
            window = self._window(temp)
            try:
                layout = window.sidebar._stream_layout_combos["serial"]
                layout.setCurrentIndex(layout.findData("quad"))
                APP.processEvents()
                for index in range(4):
                    window._stream_workspaces["serial"].page(
                        index).send_bar.text.setPlainText(
                            "old window {}".format(index + 1))
                profile = window._default_profile()
                for item in (
                    profile["stream_workspaces"]["serial"]["windows"]
                ):
                    self.assertEqual(
                        item["stream"].get("send", {}).get("draft", ""),
                        "",
                    )
            finally:
                self._close(window)


if __name__ == "__main__":
    unittest.main()
