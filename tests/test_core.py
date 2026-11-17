# -*- coding: utf-8 -*-
"""核心回归测试：不访问真实串口或用户数据。"""

import json
import os
import socket
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import serial
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QGroupBox, QLabel, QWidget

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from anhutoolbox.main_window import MainWindow, _profile_bool, _profile_int
from anhutoolbox.app_paths import choose_data_root
from anhutoolbox import dialogs, toolbox
from anhutoolbox.dialogs import AnhuInputDialog
from anhutoolbox.panels import LogPanel, PresetPanel, SendBar, parse_hex_bytes
from anhutoolbox.log_writer import AsyncLogWriter
from anhutoolbox.projects import ProjectManager
from anhutoolbox.process_metrics import ProcessMetrics, ProcessUsage
from anhutoolbox.tools import (
    AmountTool, BaseTool, ChecksumTool, DiffTool, EncodeTool, HardwareInfoPage,
    JsonTool, NetworkTool, QRTool, RegexTool, SortTool, TimestampTool,
)
from anhutoolbox.workers import (
    SerialReadWorker, TCPClientWorker, TCPServerWorker,
)

# GUI 回归测试不启动真实 PowerShell/CIM 硬件探测，避免测试结束时
# 仍有后台子进程与 Qt 事件循环交错。
_HARDWARE_TEST_PATCH = mock.patch(
    "anhutoolbox.hardware.collect_hardware_info",
    return_value={},
)
_HARDWARE_TEST_PATCH.start()


APP = QApplication.instance() or QApplication([])
ROOT = Path(__file__).resolve().parents[1]


def close_window(window):
    window.close()
    window.deleteLater()
    APP.processEvents()


class ToolTests(unittest.TestCase):
    def test_process_metrics_report_memory_and_cpu(self):
        usage = ProcessMetrics().sample()
        self.assertGreater(usage.memory_bytes, 0)
        self.assertGreaterEqual(usage.cpu_percent, 0.0)
        self.assertLessEqual(usage.cpu_percent, 100.0)

    def test_async_log_writer_flushes_before_close(self):
        with tempfile.TemporaryDirectory() as temp:
            path = os.path.join(temp, "save.log")
            writer = AsyncLogWriter(path)
            self.assertTrue(writer.write_text("第一条\n"))
            self.assertTrue(writer.write_text("第二条\n"))
            self.assertTrue(writer.flush())
            writer.close()
            self.assertEqual(
                Path(path).read_text(encoding="utf-8"),
                "第一条\n第二条\n",
            )

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

    def test_native_style_message_icons(self):
        with mock.patch(
                "anhutoolbox.dialogs._native_message",
                return_value=dialogs.IDYES) as message_box:
            self.assertTrue(dialogs.ask_yes_no(None, "确认", "继续吗？"))
        message_box.assert_called_once_with(
            None, "确认", "继续吗？", dialogs.MB_ICONQUESTION, dialogs.MB_YESNO)

        with mock.patch(
                "anhutoolbox.dialogs._native_message",
                return_value=dialogs.IDOK) as message_box:
            dialogs.show_error(None, "错误", "发生错误")
        message_box.assert_called_once_with(
            None, "错误", "发生错误", dialogs.MB_ICONERROR, dialogs.MB_OK)

    def test_input_dialog_matches_simulator_simple_layout(self):
        dialog = AnhuInputDialog(
            None, "新建项目", "项目名称", "默认项目")
        try:
            self.assertEqual(dialog.windowTitle(), "新建项目")
            self.assertEqual(dialog.input.text(), "默认项目")
            self.assertFalse(
                dialog.windowFlags() & Qt.WindowType.FramelessWindowHint)
            self.assertGreaterEqual(dialog.minimumWidth(), 470)
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

    def test_all_library_pages_use_the_shared_workspace_layout(self):
        page_classes = (
            HardwareInfoPage, TimestampTool, BaseTool, EncodeTool,
            ChecksumTool, AmountTool, JsonTool, RegexTool, DiffTool,
            SortTool, QRTool, NetworkTool,
        )
        for page_class in page_classes:
            page = page_class()
            try:
                self.assertEqual(page.objectName(), "toolPage")
                self.assertIn("QWidget#toolPage", page.styleSheet())
                self.assertEqual(page.findChildren(QGroupBox), [])
                subtitle = page.findChild(QLabel, "toolPageSubtitle")
                self.assertIsNotNone(subtitle)
                self.assertFalse(subtitle.wordWrap())
                for card_subtitle in page.findChildren(
                        QLabel, "toolCardSubtitle"):
                    self.assertFalse(card_subtitle.wordWrap())
            finally:
                if hasattr(page, "stop_timer"):
                    page.stop_timer()
                if hasattr(page, "stop_tasks"):
                    page.stop_tasks()
                if hasattr(page, "cleanup"):
                    page.cleanup()
                page.close()
                page.deleteLater()
        APP.processEvents()

    def test_qr_preview_fits_minimum_main_window_width(self):
        with tempfile.TemporaryDirectory() as temp:
            window = MainWindow(temp)
            try:
                window._extra_tabs_timer.stop()
                window._build_extra_tabs()
                window.resize(1100, 720)
                window.show()
                window._tab_widget.setCurrentWidget(window._library_stack)
                page = window._library_pages["qr"]
                window._on_library_item("qr")
                page._qr_input.setPlainText("001\n002\n003\n004\n005")
                page._generate()
                APP.processEvents()
                self.assertEqual(
                    page._qr_scroll.horizontalScrollBar().maximum(), 0)
                window.resize(1500, 1080)
                APP.processEvents()
                qr_widths = [
                    label.pixmap().width()
                    for label in page.findChildren(
                        QLabel, "qrImage")
                    if label.pixmap() is not None
                    and not label.pixmap().isNull()
                ]
                self.assertTrue(qr_widths)
                self.assertGreater(max(qr_widths), 120)
            finally:
                close_window(window)

    def test_qr_grid_keeps_fixed_rows_and_scrolls_instead_of_shrinking(self):
        with tempfile.TemporaryDirectory() as temp:
            window = MainWindow(temp)
            try:
                window._extra_tabs_timer.stop()
                window._build_extra_tabs()
                window.resize(1500, 1080)
                window.show()
                window._tab_widget.setCurrentWidget(window._library_stack)
                page = window._library_pages["qr"]
                window._on_library_item("qr")

                page._qr_input.setPlainText(
                    "\n".join(str(index) for index in range(1, 8)))
                top_levels_before = {
                    id(widget) for widget in APP.topLevelWidgets()}
                with mock.patch(
                        "anhutoolbox.tools.show_information") as information, \
                        mock.patch(
                            "anhutoolbox.tools.show_success") as success, \
                        mock.patch(
                            "anhutoolbox.tools.show_error") as error:
                    page._btn_gen.click()
                    APP.processEvents()
                information.assert_not_called()
                success.assert_not_called()
                error.assert_not_called()
                unexpected_windows = [
                    widget for widget in APP.topLevelWidgets()
                    if id(widget) not in top_levels_before
                    and widget.isVisible()
                ]
                self.assertEqual(unexpected_windows, [])

                self.assertEqual(page._grid.rowCount(), 2)
                self.assertEqual(page._grid.count(), 10)
                first_cell = page._grid.itemAtPosition(0, 0).widget()
                second_cell = page._grid.itemAtPosition(1, 0).widget()
                fixed_row_height = first_cell.height()
                self.assertEqual(second_cell.height(), fixed_row_height)

                # 从 11 条缩回 10 条时，旧网格的第三行最小高度不能残留。
                page._qr_input.setPlainText(
                    "\n".join(str(index) for index in range(1, 12)))
                page._generate()
                APP.processEvents()
                page._qr_input.setPlainText(
                    "\n".join(str(index) for index in range(1, 11)))
                page._generate()
                APP.processEvents()
                ten_first_cell = page._grid.itemAtPosition(0, 0).widget()
                ten_geometry = ten_first_cell.geometry()
                self.assertFalse(
                    page._qr_scroll.verticalScrollBar().isEnabled())
                self.assertEqual(page._grid.count(), 10)
                self.assertEqual(
                    page._grid.itemAtPosition(0, 0).widget().height(),
                    fixed_row_height,
                )
                self.assertEqual(
                    page._grid.itemAtPosition(1, 0).widget().height(),
                    fixed_row_height,
                )

                page._qr_input.setPlainText(
                    "\n".join(str(index) for index in range(1, 12)))
                page._generate()
                APP.processEvents()
                eleven_first_cell = page._grid.itemAtPosition(0, 0).widget()
                self.assertEqual(
                    page._qr_scroll.verticalScrollBarPolicy(),
                    Qt.ScrollBarPolicy.ScrollBarAlwaysOn,
                )
                self.assertTrue(
                    page._qr_scroll.verticalScrollBar().isEnabled())
                self.assertEqual(
                    eleven_first_cell.geometry(), ten_geometry)

                page._qr_input.setPlainText(
                    "\n".join(str(index) for index in range(1, 19)))
                page._generate()
                APP.processEvents()
                self.assertEqual(page._grid.rowCount(), 4)
                self.assertEqual(page._grid.count(), 20)
                first_cell = page._grid.itemAtPosition(0, 0).widget()
                second_cell = page._grid.itemAtPosition(1, 0).widget()
                self.assertEqual(first_cell.height(), fixed_row_height)
                self.assertEqual(second_cell.height(), fixed_row_height)
                self.assertGreater(
                    page._qr_scroll.verticalScrollBar().maximum(), 0)
                self.assertEqual(
                    page._qr_scroll.horizontalScrollBar().maximum(), 0)
            finally:
                close_window(window)

    def test_double_click_qr_opens_and_closes_enlarged_preview(self):
        with tempfile.TemporaryDirectory() as temp:
            window = MainWindow(temp)
            try:
                window._extra_tabs_timer.stop()
                window._build_extra_tabs()
                window.resize(1500, 1080)
                window.show()
                window._tab_widget.setCurrentWidget(window._library_stack)
                page = window._library_pages["qr"]
                window._on_library_item("qr")
                page._qr_input.setPlainText("001\n002")
                page._generate()
                APP.processEvents()

                cell = page._grid.itemAtPosition(0, 0).widget()
                QTest.mouseDClick(
                    cell, Qt.MouseButton.LeftButton,
                    pos=cell.rect().center())
                APP.processEvents()
                self.assertTrue(page._qr_preview_overlay.isVisible())
                self.assertEqual(page._qr_preview_content.text(), "001")
                self.assertEqual(
                    page._qr_preview_content.objectName(), "qrPreviewText")
                self.assertGreaterEqual(
                    page._qr_preview_content.font().pixelSize(), 16)
                self.assertTrue(
                    page._qr_preview_content.alignment()
                    & Qt.AlignmentFlag.AlignHCenter)
                self.assertFalse(any(
                    label.text() == "二维码放大预览"
                    for label in page.findChildren(QLabel)
                ))
                self.assertFalse(
                    page._qr_preview_image.pixmap().isNull())
                self.assertEqual(
                    page._btn_close_qr_preview.focusPolicy(),
                    Qt.FocusPolicy.NoFocus,
                )

                QTest.keyClick(window, Qt.Key.Key_Escape)
                APP.processEvents()
                self.assertFalse(page._qr_preview_overlay.isVisible())
                self.assertEqual(page._grid.itemAtPosition(0, 0).widget().findChild(
                    QLabel, "qrText").text(), "001")
            finally:
                close_window(window)

    def test_refactored_library_pages_keep_their_interactions(self):
        json_tool = JsonTool()
        json_tool._json_input.setPlainText('{"b":2,"a":1}')
        json_tool._format()
        self.assertIn('"a": 1', json_tool._json_output.toPlainText())
        self.assertEqual(json_tool._json_status.text(), "格式化成功")
        self.assertTrue(json_tool._json_output.isReadOnly())
        self.assertTrue(json_tool._btn_copy_output.isEnabled())
        QApplication.clipboard().clear()
        json_tool._btn_copy_output.click()
        self.assertEqual(
            QApplication.clipboard().text(),
            json_tool._json_output.toPlainText(),
        )
        self.assertEqual(json_tool._json_status.text(), "已复制结果")

        regex_tool = RegexTool()
        regex_tool._re_input.setText(r"item-(\d+)")
        regex_tool._text_input.setPlainText("item-1 item-2")
        self.assertEqual(regex_tool._regex_count.text(), "2 个匹配")
        self.assertTrue(regex_tool._result_output.isReadOnly())

        sort_tool = SortTool()
        sort_tool._sort_input.setPlainText("2\n10\n1")
        sort_tool._sort_mode.setCurrentText("数值")
        sort_tool._btn_desc.click()
        self.assertEqual(
            sort_tool._sort_output.toPlainText().splitlines(),
            ["10", "2", "1"],
        )
        self.assertTrue(sort_tool._btn_desc.isChecked())
        self.assertFalse(sort_tool._btn_asc.isChecked())

        encode_tool = EncodeTool()
        encode_tool._enc_input.setPlainText("Anhu")
        self.assertEqual(
            encode_tool._enc_results["Base64 编码"].text(),
            "QW5odQ==",
        )

        checksum_tool = ChecksumTool()
        checksum_tool._cs_mode.setCurrentText("文本")
        checksum_tool._cs_input.setPlainText("abc")
        self.assertEqual(
            checksum_tool._cs_results["MD5"].text(),
            "900150983CD24FB0D6963F7D28E17F72",
        )


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

    def test_send_controls_scroll_without_covering_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            window = MainWindow(temp)
            try:
                window.resize(1100, 720)
                window.show()
                APP.processEvents()
                text_height = window.send_bar.text.height()
                text_y = window.send_bar.sp_start.mapTo(
                    window.send_bar,
                    window.send_bar.sp_start.rect().topLeft(),
                ).y()
                switches_y = window.send_bar.chk_hex.mapTo(
                    window.send_bar,
                    window.send_bar.chk_hex.rect().topLeft(),
                ).y()

                # 展开预设后中间通信区变窄，底部在校验值等控件之外
                # 应出现独立横向滚动条，不能压住两行控制控件。
                window._btn_toggle_preset.setChecked(True)
                APP.processEvents()

                bar = window.send_bar
                scroll = bar._controls_scroll
                scrollbar = scroll.horizontalScrollBar()
                controls_layout = bar._controls_content.layout()
                self.assertTrue(scrollbar.isVisible())
                self.assertGreater(scrollbar.maximum(), 0)
                self.assertEqual(scrollbar.height(), 8)
                self.assertGreaterEqual(
                    scroll.viewport().height(),
                    controls_layout.minimumSize().height(),
                )
                self.assertLessEqual(
                    controls_layout.itemAt(1).geometry().bottom() + 1,
                    scroll.viewport().height(),
                )
                self.assertEqual(bar.text.height(), text_height)
                self.assertEqual(
                    bar.sp_start.mapTo(
                        bar, bar.sp_start.rect().topLeft()).y(),
                    text_y,
                )
                self.assertEqual(
                    bar.chk_hex.mapTo(
                        bar, bar.chk_hex.rect().topLeft()).y(),
                    switches_y,
                )
            finally:
                close_window(window)


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

    def test_serial_connection_has_finite_write_timeout(self):
        fake_serial = mock.Mock()
        fake_serial.dtr = False
        fake_serial.rts = False
        with tempfile.TemporaryDirectory() as temp:
            window = MainWindow(temp)
            try:
                window.sidebar.cb_port.addItem("COM4")
                window.sidebar.cb_port.setCurrentText("COM4")
                with mock.patch(
                        "anhutoolbox.main_window.serial.Serial",
                        return_value=fake_serial) as serial_class, \
                        mock.patch.object(
                            window._serial_worker, "start"), \
                        mock.patch.object(
                            window._serial_worker, "set_serial"):
                    window._connect_serial()
                kwargs = serial_class.call_args.kwargs
                self.assertEqual(kwargs["timeout"], 0.1)
                self.assertEqual(kwargs["write_timeout"], 0.5)
            finally:
                window._active_worker = None
                close_window(window)


class StreamWorkspaceTests(unittest.TestCase):
    def test_serial_tcp_server_and_client_keep_independent_content(self):
        with tempfile.TemporaryDirectory() as temp:
            window = MainWindow(temp)
            try:
                window.resize(1360, 720)
                window.show()
                APP.processEvents()
                self.assertEqual(
                    window.sidebar._settings_scroll.verticalScrollBar().maximum(),
                    0)
                pages = window._stream_pages
                pages["serial"].send_bar.text.setPlainText("serial draft")
                pages["tcpserver"].send_bar.text.setPlainText("server draft")
                pages["tcpclient"].send_bar.text.setPlainText("client draft")
                pages["serial"].log_panel.append_data("rx", b"SERIAL")
                pages["tcpserver"].log_panel.append_data("rx", b"SERVER")
                pages["tcpclient"].log_panel.append_data("rx", b"CLIENT")

                window.sidebar._mode_group.button(0).click()
                APP.processEvents()
                self.assertEqual(window.send_bar.text.toPlainText(),
                                 "serial draft")
                self.assertEqual(window.log_panel._rx_total, 6)

                window.sidebar._mode_group.button(1).click()
                APP.processEvents()
                self.assertEqual(window.send_bar.text.toPlainText(),
                                 "server draft")
                self.assertEqual(window.log_panel._rx_total, 6)

                window.sidebar._mode_group.button(2).click()
                APP.processEvents()
                self.assertEqual(window.send_bar.text.toPlainText(),
                                 "client draft")
                self.assertEqual(window.log_panel._rx_total, 6)
                self.assertEqual(
                    pages["serial"].send_bar.text.toPlainText(),
                    "serial draft")

                snapshot = window._snapshot_ui()
                self.assertEqual(
                    snapshot["streams"]["serial"]["send"]["draft"],
                    "serial draft")
                self.assertEqual(
                    snapshot["streams"]["tcpserver"]["send"]["draft"],
                    "server draft")
                self.assertEqual(
                    snapshot["streams"]["tcpclient"]["send"]["draft"],
                    "client draft")

                window._apply_profile({
                    "mode": "serial",
                    "streams": {
                        "serial": {"send": {"draft": "new serial"}},
                        "tcpserver": {"send": {"draft": "new server"}},
                        "tcpclient": {"send": {"draft": "new client"}},
                    },
                })
                self.assertEqual(
                    pages["serial"].send_bar.text.toPlainText(), "new serial")
                self.assertEqual(
                    pages["tcpserver"].send_bar.text.toPlainText(), "new server")
                self.assertEqual(
                    pages["tcpclient"].send_bar.text.toPlainText(), "new client")
            finally:
                close_window(window)


class OptionalToolboxTests(unittest.TestCase):
    @staticmethod
    def _prepare_tools(temp, state=None):
        tools_dir = Path(temp) / "tools"
        tools_dir.mkdir()
        (tools_dir / "tools.json").write_text(
            json.dumps({
                "version": 1,
                "categories": ["测试工具"],
                "tools": [],
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        if state is not None:
            (tools_dir / "toolbox.install-state").write_text(
                state, encoding="ascii")
        return tools_dir

    def test_install_state_prefers_explicit_installer_choice(self):
        with tempfile.TemporaryDirectory() as temp:
            tools_dir = self._prepare_tools(temp)
            self.assertIsNone(toolbox.install_state(str(tools_dir)))
            self.assertTrue(toolbox.is_toolbox_available(str(tools_dir)))

            state_file = tools_dir / "toolbox.install-state"
            state_file.write_text("1\n", encoding="ascii")
            self.assertTrue(toolbox.install_state(str(tools_dir)))

            state_file.write_text("0\n", encoding="ascii")
            self.assertFalse(toolbox.install_state(str(tools_dir)))
            # 即使升级后残留了 tools.json，也必须遵从安装器的“未安装”记录。
            self.assertFalse(toolbox.is_toolbox_available(str(tools_dir)))

    def test_ensure_tools_does_not_restore_uninstalled_toolbox(self):
        with tempfile.TemporaryDirectory() as temp:
            base_dir = Path(temp) / "app"
            resource_dir = Path(temp) / "bundle"
            tools_dir = base_dir / "tools"
            bundled_tools = resource_dir / "tools"
            tools_dir.mkdir(parents=True)
            bundled_tools.mkdir(parents=True)
            (tools_dir / "toolbox.install-state").write_text(
                "0", encoding="ascii")
            (bundled_tools / "tools.json").write_text(
                '{"version": 2, "tools": []}', encoding="utf-8")

            toolbox.ensure_tools(str(base_dir), str(resource_dir))

            self.assertFalse((tools_dir / "tools.json").exists())

    def test_uninstalled_toolbox_tab_is_hidden_and_hardware_cleanup_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            self._prepare_tools(temp, "0")
            window = MainWindow(temp)
            try:
                window._extra_tabs_timer.stop()
                window._build_extra_tabs()
                tab_texts = [
                    window._tab_widget.tabText(index)
                    for index in range(window._tab_widget.count())
                ]
                self.assertEqual(
                    tab_texts, ["通信调试", "工具库", "自定义库"])
                self.assertIsNone(window._toolbox_stack)
                self.assertEqual(window._toolbox_pages, {})
                self.assertEqual(window._toolbox_categories, [])
                self.assertNotIn("工具箱", window.sidebar._toolbox_buttons)

                sidebar = window.sidebar
                hardware = sidebar._library_standalone_buttons["hardware"]
                first_group = next(
                    iter(sidebar._library_group_labels.values()))
                layout = sidebar._library_list_lo
                self.assertEqual(hardware.text(), "硬件信息")
                self.assertLess(
                    layout.indexOf(hardware),
                    layout.indexOf(first_group),
                )
                self.assertIs(
                    window._library_stack.currentWidget(),
                    window._library_pages["hardware"],
                )

                with mock.patch.object(
                        window._library_pages["hardware"],
                        "cleanup") as cleanup:
                    window.close()
                cleanup.assert_called_once_with()
                APP.processEvents()
            finally:
                window.deleteLater()
                APP.processEvents()

    def test_installed_toolbox_tab_is_available(self):
        with tempfile.TemporaryDirectory() as temp:
            self._prepare_tools(temp, "1")
            window = MainWindow(temp)
            try:
                window._extra_tabs_timer.stop()
                window._build_extra_tabs()
                tab_texts = [
                    window._tab_widget.tabText(index)
                    for index in range(window._tab_widget.count())
                ]
                self.assertEqual(
                    tab_texts,
                    ["通信调试", "工具库", "工具箱", "自定义库"],
                )
                self.assertIsNotNone(window._toolbox_stack)
                self.assertEqual(
                    window._toolbox_categories, ["测试工具"])
                self.assertIn(
                    "测试工具", window.sidebar._toolbox_buttons)
            finally:
                close_window(window)

    def test_build_scripts_keep_toolbox_optional(self):
        installer = (ROOT / "installer.iss").read_text(
            encoding="utf-8")
        spec = (ROOT / "AnhuToolbox.spec").read_text(encoding="utf-8")
        self.assertIn(
            'Name: "installtoolbox"; '
            'Description: "安装安护工具箱（可选第三方工具）"',
            installer,
        )
        self.assertGreaterEqual(
            installer.count("Tasks: installtoolbox"), 2)
        self.assertIn("UsePreviousTasks=yes", installer)
        task_line = next(
            line for line in installer.splitlines()
            if line.startswith('Name: "installtoolbox"'))
        self.assertNotIn("checkedonce", task_line)
        self.assertIn("RemoveOfficialToolboxFiles", installer)
        self.assertIn("toolbox.install-state", installer)
        self.assertIn("tools.user.json", installer)
        self.assertIn("_verify_external_tools()", spec)
        self.assertNotIn("(TOOLS_ROOT, 'tools')", spec)


class PersistenceTests(unittest.TestCase):
    def test_welcome_text_lines_share_the_same_indent(self):
        with tempfile.TemporaryDirectory() as temp:
            window = MainWindow(temp)
            try:
                window._show_welcome()
                text_lines = window.log_panel.text.toPlainText().splitlines()
                welcome_lines = [
                    line for line in text_lines
                    if any(keyword in line for keyword in (
                        "欢迎使用", "作者：", "版本号："))
                ]
                self.assertEqual(len(welcome_lines), 3)
                self.assertTrue(all(
                    line.startswith("     ")
                    and not line.startswith("      ")
                    for line in welcome_lines
                ))
            finally:
                close_window(window)

    def test_global_resource_bar_stays_visible_on_all_tabs(self):
        with tempfile.TemporaryDirectory() as temp:
            window = MainWindow(temp)
            try:
                window.resize(1100, 720)
                window.show()
                APP.processEvents()
                window._build_extra_tabs()
                with mock.patch.object(
                        window._process_metrics,
                        "sample",
                        return_value=ProcessUsage(
                            512 * 1024 * 1024, 12.34)):
                    window._update_resource_usage()
                self.assertEqual(
                    window._lbl_resource_usage.text(),
                    "内存 512.0 MB  |  CPU 12.3%",
                )
                self.assertTrue(window._info_bar.isVisible())
                self.assertTrue(
                    window._lbl_resource_usage.isVisible())
                self.assertTrue(window._lbl_conn_type.isVisible())

                window._tab_widget.setCurrentWidget(
                    window._library_stack)
                APP.processEvents()
                self.assertTrue(window._info_bar.isVisible())
                self.assertTrue(
                    window._lbl_resource_usage.isVisible())
                self.assertFalse(window._lbl_conn_type.isVisible())
            finally:
                close_window(window)

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

    def test_log_toolbar_uses_horizontal_scroll_without_shrinking_log(self):
        panel = LogPanel()
        panel.resize(900, 500)
        panel.show()
        APP.processEvents()
        wide_text_height = panel.text.height()
        wide_scroll_height = panel._toolbar_scroll.height()
        wide_timeout_y = panel.sp_timeout.mapTo(
            panel, panel.sp_timeout.rect().topLeft()).y()
        wide_clear_y = panel.btn_clear.mapTo(
            panel, panel.btn_clear.rect().topLeft()).y()
        panel.resize(320, 500)
        APP.processEvents()
        self.assertGreater(
            panel._toolbar_scroll.horizontalScrollBar().maximum(), 0)
        self.assertTrue(
            panel._toolbar_scroll.horizontalScrollBar().isVisible())
        self.assertEqual(panel.text.height(), wide_text_height)
        self.assertEqual(panel._toolbar_scroll.height(), wide_scroll_height)
        self.assertEqual(
            panel.sp_timeout.mapTo(
                panel, panel.sp_timeout.rect().topLeft()).y(),
            wide_timeout_y,
        )
        self.assertEqual(
            panel.btn_clear.mapTo(
                panel, panel.btn_clear.rect().topLeft()).y(),
            wide_clear_y,
        )
        toolbar_viewport = panel._toolbar_scroll.viewport()
        self.assertLessEqual(
            panel.sp_timeout.geometry().bottom() + 1,
            toolbar_viewport.height(),
        )
        self.assertLessEqual(
            panel.btn_clear.geometry().bottom() + 1,
            toolbar_viewport.height(),
        )
        panel.close()
        panel.deleteLater()

    def test_log_file_error_disables_saving(self):
        panel = LogPanel()
        bad_writer = mock.Mock()
        bad_writer.write_text.return_value = False
        panel._save_writer = bad_writer
        panel.chk_save_file.blockSignals(True)
        panel.chk_save_file.setChecked(True)
        panel.chk_save_file.blockSignals(False)
        errors = []
        panel.file_error.connect(errors.append)
        panel.append_data("rx", b"ABC")
        self.assertTrue(errors)
        self.assertFalse(panel.chk_save_file.isChecked())
        bad_writer.close.assert_called()

    def test_stream_save_keeps_writing_while_page_is_paused(self):
        with tempfile.TemporaryDirectory() as temp:
            path = os.path.join(temp, "serial.log")
            panel = LogPanel()
            try:
                panel.set_log_directory(temp, "serial")
                default_paths = []

                def choose_path(parent, title, default, filters):
                    default_paths.append(default)
                    return path, ""

                with mock.patch(
                        "anhutoolbox.panels.QFileDialog.getSaveFileName",
                        side_effect=choose_path):
                    panel.chk_save_file.setChecked(True)
                self.assertEqual(
                    Path(default_paths[0]).parent, Path(temp))
                self.assertTrue(
                    Path(default_paths[0]).name.startswith("serial_"))
                panel.chk_pause.setChecked(True)
                panel.append_data("rx", b"ABC")
                self.assertTrue(panel._save_writer.flush())
                saved = Path(path).read_text(encoding="utf-8")
                self.assertIn("41 42 43", saved)
                self.assertTrue(saved.endswith("\n"))
                self.assertEqual(panel.text.toPlainText(), "")
            finally:
                panel.cleanup()

    def test_stream_page_keeps_all_rows_when_save_is_off(self):
        panel = LogPanel()
        for index in range(40):
            panel.append_data("rx", str(index).encode("ascii"))
        panel._flush_display()
        self.assertEqual(panel.text.maximumBlockCount(), 0)
        self.assertEqual(panel._display_records, 40)
        self.assertIn("0", panel.text.toPlainText())
        self.assertIn("39", panel.text.toPlainText())
        self.assertLess(
            panel.chk_pause.x(), panel.chk_save_file.x())
        self.assertIn("未开启保存不清屏", panel.lbl_save_rule.text())
        self.assertIn("300MB清屏", panel.lbl_save_rule.text())
        self.assertNotIn("\n", panel.lbl_save_rule.text())
        panel.cleanup()

    def test_stream_save_clears_page_after_writer_flushes(self):
        with tempfile.TemporaryDirectory() as temp:
            path = os.path.join(temp, "serial.log")
            panel = LogPanel()
            try:
                panel.set_log_directory(temp, "serial")
                with mock.patch(
                        "anhutoolbox.panels.AUTO_CLEAR_RECORDS", 2), \
                        mock.patch(
                            "anhutoolbox.panels.AUTO_CLEAR_BYTES",
                            1024 * 1024), \
                        mock.patch(
                            "anhutoolbox.panels.QFileDialog."
                            "getSaveFileName",
                            return_value=(path, "")):
                    panel.chk_save_file.setChecked(True)
                    for char in (b"A", b"B", b"C"):
                        panel.append_data("rx", char)
                        panel._flush_display()
                    self.assertTrue(
                        panel.text.toPlainText().strip().endswith("43"))
                    self.assertEqual(panel._display_records, 1)
                    self.assertTrue(panel.chk_save_file.isChecked())
                    self.assertTrue(panel._save_writer.flush())
                lines = Path(path).read_text(
                    encoding="utf-8").splitlines()
                self.assertEqual(len(lines), 3)
                self.assertTrue(all("41" in line or "42" in line
                                    or "43" in line for line in lines))
            finally:
                panel.cleanup()

    def test_main_window_creates_empty_log_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            window = MainWindow(temp)
            try:
                log_dir = Path(temp, "log")
                self.assertTrue(log_dir.is_dir())
                self.assertEqual(list(log_dir.iterdir()), [])
                self.assertEqual(
                    window._stream_pages["serial"]
                    .log_panel._save_directory,
                    str(log_dir),
                )
            finally:
                close_window(window)

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
