# -*- coding: utf-8 -*-
"""Bundled packet capture tab and parser tests."""

import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPoint, QProcess, Qt

from anhutoolbox.capture import (
    build_dumpcap_capture_args, build_tshark_capture_args,
    capture_resource_dirs, npcap_installer_path, parse_packet_fields,
    parse_tshark_interfaces,
)
from anhutoolbox.log_writer import AUTO_CLEAR_RECORDS
from anhutoolbox.tools import NetworkTool, PacketCaptureTool


APP = QApplication.instance() or QApplication([])


class CaptureTests(unittest.TestCase):
    def test_parse_tshark_interfaces(self):
        output = (
            '1. \\Device\\NPF_{AAAA} (以太网)\n'
            '2. \\Device\\NPF_Loopback (Adapter for loopback traffic capture)\n'
        )
        interfaces = parse_tshark_interfaces(output)
        self.assertEqual(len(interfaces), 2)
        self.assertEqual(interfaces[0]["device"], "\\Device\\NPF_{AAAA}")
        self.assertEqual(interfaces[0]["name"], "以太网")

    def test_parse_packet_fields(self):
        line = (
            '"7"\t"1.250000"\t"192.168.1.10"\t\t'
            '"192.168.1.20"\t\t"TCP"\t"74"\t"502 -> 55000 [ACK]"\n'
        )
        packet = parse_packet_fields(line)
        self.assertEqual(packet["number"], 7)
        self.assertEqual(packet["source"], "192.168.1.10")
        self.assertEqual(packet["destination"], "192.168.1.20")
        self.assertEqual(packet["protocol"], "TCP")
        self.assertEqual(packet["length"], 74)

    def test_packet_number_and_length_columns_are_centered(self):
        capture = PacketCaptureTool()
        model = capture._capture_tool._capture_model
        try:
            model.append_packets([{
                "number": 1,
                "time": 0.1,
                "source": "192.0.2.1",
                "destination": "192.0.2.2",
                "protocol": "TCP",
                "length": 66,
                "info": "test",
            }])
            for column in (0, 1, 5):
                alignment = model.data(
                    model.index(0, column),
                    Qt.ItemDataRole.TextAlignmentRole,
                )
                self.assertEqual(
                    int(alignment),
                    int(Qt.AlignmentFlag.AlignCenter),
                )
        finally:
            capture.stop_tasks()
            capture.deleteLater()
            APP.processEvents()

    def test_packet_number_column_expands_for_large_numbers(self):
        capture = PacketCaptureTool()
        tool = capture._capture_tool
        try:
            capture.show()
            packet = {
                "number": 123,
                "time": 0.1,
                "source": "192.0.2.1",
                "destination": "192.0.2.2",
                "protocol": "TCP",
                "length": 66,
                "info": "test",
            }
            tool._append_capture_packet(packet)
            APP.processEvents()
            width_123 = tool._capture_table.columnWidth(0)
            self.assertGreaterEqual(
                width_123,
                tool._capture_table.fontMetrics().horizontalAdvance("123") + 20,
            )
            tool._append_capture_packet({**packet, "number": 12345})
            APP.processEvents()
            self.assertGreater(tool._capture_table.columnWidth(0), width_123)
        finally:
            capture.stop_tasks()
            capture.deleteLater()
            APP.processEvents()

    def test_capture_scrollbar_starts_below_table_header(self):
        capture = PacketCaptureTool()
        tool = capture._capture_tool
        try:
            capture.resize(900, 500)
            capture.show()
            packets = [{
                "number": index + 1,
                "time": index / 100.0,
                "source": "192.0.2.1",
                "destination": "192.0.2.2",
                "protocol": "TCP",
                "length": 66,
                "info": "test packet",
            } for index in range(100)]
            tool._capture_model.append_packets(packets)
            APP.processEvents()
            scrollbar = tool._capture_view.scrollbar
            self.assertFalse(scrollbar.isHidden())
            self.assertEqual(scrollbar.width(), 8)
            self.assertIn("QScrollBar:vertical", scrollbar.styleSheet())
            scrollbar_top = scrollbar.mapTo(
                tool._capture_view, QPoint(0, 0)).y()
            header_height = (
                tool._capture_table.horizontalHeader().height())
            self.assertGreaterEqual(scrollbar_top, header_height)
        finally:
            capture.stop_tasks()
            capture.deleteLater()
            APP.processEvents()

    def test_capture_details_are_collapsed_by_default(self):
        capture = PacketCaptureTool()
        tool = capture._capture_tool
        try:
            capture.show()
            APP.processEvents()
            self.assertTrue(tool._capture_detail_card.isHidden())
            self.assertEqual(
                tool._btn_capture_detail_toggle.text(), "展开详情")
            tool._btn_capture_detail_toggle.click()
            APP.processEvents()
            self.assertFalse(tool._capture_detail_card.isHidden())
            self.assertEqual(
                tool._btn_capture_detail_toggle.text(), "收起详情")
            tool._btn_capture_detail_toggle.click()
            APP.processEvents()
            self.assertTrue(tool._capture_detail_card.isHidden())
        finally:
            capture.stop_tasks()
            capture.deleteLater()
            APP.processEvents()

    def test_capture_filter_and_refresh_right_edges_align(self):
        capture = PacketCaptureTool()
        tool = capture._capture_tool
        try:
            capture.resize(1100, 720)
            capture.show()
            tool._btn_install_npcap.show()
            APP.processEvents()
            refresh_right = tool._btn_capture_refresh.mapTo(
                tool, tool._btn_capture_refresh.rect().topRight()).x()
            filter_right = tool._capture_filter.mapTo(
                tool, tool._capture_filter.rect().topRight()).x()
            display_right = tool._capture_display_filter.mapTo(
                tool, tool._capture_display_filter.rect().topRight()).x()
            self.assertEqual(refresh_right, filter_right)
            self.assertEqual(filter_right, display_right)
        finally:
            capture.stop_tasks()
            capture.deleteLater()
            APP.processEvents()

    def test_capture_detail_uses_fast_args_and_cache(self):
        capture = PacketCaptureTool()
        tool = capture._capture_tool
        fake_process = mock.MagicMock()
        fake_process.state.return_value = 0
        try:
            with tempfile.NamedTemporaryFile(
                    suffix=".pcapng", delete=False) as stream:
                path = stream.name
                stream.write(b"test")
            tool._capture_temp_path = path
            with mock.patch(
                    "anhutoolbox.tools.QProcess",
                    return_value=fake_process):
                tool._load_capture_detail(18)
            args = fake_process.start.call_args.args[1]
            self.assertIn("-n", args)
            self.assertNotIn("-c", args)
            tool._capture_detail_timeout_timer.stop()

            tool._capture_detail_cache[(path, 18)] = "cached detail"
            with mock.patch(
                    "anhutoolbox.tools.QProcess",
                    side_effect=AssertionError("cache was not used")):
                tool._load_capture_detail(18)
            self.assertEqual(
                tool._capture_detail.toPlainText(), "cached detail")
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
            capture.stop_tasks()
            capture.deleteLater()
            APP.processEvents()

    def test_capture_time_column_fits_full_timestamp(self):
        capture = PacketCaptureTool()
        tool = capture._capture_tool
        try:
            tool._append_capture_packet({
                "number": 1,
                "time": 123456.123456,
                "source": "192.0.2.1",
                "destination": "192.0.2.2",
                "protocol": "TCP",
                "length": 66,
                "info": "test",
            })
            APP.processEvents()
            expected = tool._capture_table.fontMetrics().horizontalAdvance(
                tool._capture_model.format_time(123456.123456))
            self.assertGreaterEqual(
                tool._capture_table.columnWidth(1), expected + 20)
        finally:
            capture.stop_tasks()
            capture.deleteLater()
            APP.processEvents()

    def test_start_capture_keeps_existing_packets_and_sequence(self):
        capture = PacketCaptureTool()
        tool = capture._capture_tool
        fake_process = mock.MagicMock()
        old_packet = {
            "number": 3,
            "display_number": 12,
            "frame_number": 3,
            "capture_path": "old-capture.pcapng",
            "time": 1.25,
            "source": "192.0.2.1",
            "destination": "192.0.2.2",
            "protocol": "TCP",
            "length": 66,
            "info": "old packet",
        }
        tool._capture_model.append_packets([old_packet])
        tool._capture_count = 1
        tool._capture_bytes = 66
        tool._capture_display_records = 1
        tool._capture_display_bytes = 600
        tool._capture_detail.setPlainText("old detail")
        tool._capture_detail_cache[("old-capture.pcapng", 3)] = "old detail"
        tool._capture_interface.addItem("Ethernet", "device")
        try:
            with (
                mock.patch.object(
                    tool, "_capture_engine_ready", return_value=True),
                mock.patch(
                    "anhutoolbox.tools.tempfile.mkstemp",
                    return_value=(1, "new-capture.pcapng")),
                mock.patch("anhutoolbox.tools.os.close"),
                mock.patch(
                    "anhutoolbox.tools.QProcess",
                    return_value=fake_process),
            ):
                tool._start_capture()

            self.assertEqual(tool._capture_model.rowCount(), 1)
            self.assertEqual(tool._capture_count, 1)
            self.assertEqual(tool._capture_display_records, 1)
            self.assertEqual(
                tool._capture_detail.toPlainText(), "old detail")
            self.assertIn(
                ("old-capture.pcapng", 3), tool._capture_detail_cache)
            self.assertEqual(tool._capture_session_frame_base, 12)

            fake_process.readAllStandardOutput.return_value = (
                b'"1"\t"0.500000"\t"192.0.2.3"\t""\t'
                b'"192.0.2.4"\t""\t"TCP"\t"60"\t"new packet"\n')
            tool._on_capture_stdout(fake_process)
            tool._flush_capture_packets()
            self.assertEqual(tool._capture_model.rowCount(), 2)
            self.assertEqual(
                tool._capture_model.data(
                    tool._capture_model.index(1, 0)),
                "13",
            )
            self.assertEqual(
                tool._capture_model.packet_at(1)["capture_path"],
                "new-capture.pcapng",
            )
        finally:
            tool._capture_running = False
            tool._capture_proc = None
            capture.stop_tasks()
            capture.deleteLater()
            APP.processEvents()

    def test_stop_ignores_late_packets_and_stale_process_signals(self):
        capture = PacketCaptureTool()
        tool = capture._capture_tool
        current = mock.MagicMock()
        stale = mock.MagicMock()
        packet_line = (
            b'"4000"\t"9.000000"\t"192.0.2.1"\t""\t'
            b'"192.0.2.2"\t""\t"TCP"\t"66"\t"late packet"\n')
        tool._capture_proc = current
        tool._capture_running = True
        tool._capture_stopping = True
        tool._capture_stdout_buffer = ""
        tool._capture_buffer.append({
            "number": 3999,
            "display_number": 3999,
            "frame_number": 3999,
            "capture_path": "late.pcapng",
            "time": 8.5,
            "source": "192.0.2.1",
            "destination": "192.0.2.2",
            "protocol": "TCP",
            "length": 66,
            "info": "buffered late packet",
        })
        current.readAllStandardOutput.return_value = packet_line
        try:
            tool._on_capture_stdout(current)
            tool._flush_capture_packets()
            self.assertEqual(tool._capture_model.rowCount(), 0)

            tool._capture_stopping = False
            tool._capture_proc = current
            stale.readAllStandardOutput.return_value = packet_line
            tool._on_capture_stdout(stale)
            self.assertEqual(tool._capture_model.rowCount(), 0)
            tool._on_capture_finished(stale, 0)
            self.assertIs(tool._capture_proc, current)
            self.assertTrue(tool._capture_running)
            stale.deleteLater.assert_called_once_with()
        finally:
            tool._capture_running = False
            tool._capture_proc = None
            capture.stop_tasks()
            capture.deleteLater()
            APP.processEvents()

    def test_stop_clears_capture_process_handles(self):
        capture = PacketCaptureTool()
        tool = capture._capture_tool

        class FakeProcess:
            def __init__(self):
                self.process_state = QProcess.ProcessState.Running

            def state(self):
                return self.process_state

            def terminate(self):
                pass

            def kill(self):
                pass

            def waitForFinished(self, _timeout):
                self.process_state = QProcess.ProcessState.NotRunning
                return True

        main_process = FakeProcess()
        file_process = FakeProcess()
        tool._capture_proc = main_process
        tool._capture_file_proc = file_process
        tool._capture_running = True
        try:
            tool._stop_capture()
            self.assertIsNone(tool._capture_proc)
            self.assertIsNone(tool._capture_file_proc)
            self.assertFalse(tool._capture_running)
        finally:
            capture.stop_tasks()
            capture.deleteLater()
            APP.processEvents()

    def test_bpf_and_display_filters_use_separate_tshark_options(self):
        display = "ip.addr == 192.168.2.188 && tcp.port == 9090"
        args = build_tshark_capture_args(
            "\\Device\\NPF_TEST",
            "capture.pcapng",
            capture_filter="host 192.168.2.188 and tcp port 9090",
            display_filter=display,
            write_output=False,
        )
        self.assertEqual(
            args[args.index("-f") + 1],
            "host 192.168.2.188 and tcp port 9090")
        self.assertEqual(args[args.index("-Y") + 1], display)
        self.assertNotIn("-w", args)
        dump_args = build_dumpcap_capture_args(
            "\\Device\\NPF_TEST",
            "capture.pcapng",
            "host 192.168.2.188 and tcp port 9090",
        )
        self.assertEqual(dump_args[dump_args.index("-w") + 1],
                         "capture.pcapng")

    def test_bundled_capture_resources_exist(self):
        engine, npcap = capture_resource_dirs()
        self.assertTrue((engine / "tshark.exe").is_file())
        self.assertTrue((engine / "dumpcap.exe").is_file())
        installer = npcap_installer_path()
        self.assertIsNotNone(installer)
        self.assertTrue(installer.is_file())
        self.assertTrue(npcap.is_dir())

    def test_network_and_capture_are_separate_pages(self):
        tool = NetworkTool()
        capture = PacketCaptureTool()
        try:
            self.assertEqual(
                [tool._network_tabs.tabText(i) for i in range(3)],
                ["Ping", "端口扫描", "网段扫描"],
            )
            tabs = capture._capture_tool._network_tabs
            self.assertEqual(tabs.count(), 1)
            self.assertEqual(tabs.tabText(0), "抓包分析")
            self.assertEqual(capture._capture_tool._page_title, "抓包分析")
            self.assertTrue(tabs.tabBar().isHidden())
            self.assertTrue(capture._capture_tool._capture_engine_ready())
        finally:
            tool.stop_tasks()
            capture.stop_tasks()
            tool.deleteLater()
            capture.deleteLater()
            APP.processEvents()

    def test_capture_page_clears_display_after_saved_limit(self):
        capture = PacketCaptureTool()
        tool = capture._capture_tool
        try:
            tool._chk_capture_save.blockSignals(True)
            tool._chk_capture_save.setChecked(True)
            tool._chk_capture_save.blockSignals(False)
            tool._capture_save_path = "active-capture.pcapng"
            tool._capture_display_records = AUTO_CLEAR_RECORDS - 1
            tool._capture_display_bytes = 0
            tool._append_capture_packet({
                "number": 10000,
                "time": 1.0,
                "source": "192.0.2.1",
                "destination": "192.0.2.2",
                "protocol": "TCP",
                "length": 64,
                "info": "test packet",
            })
            self.assertEqual(tool._capture_model.rowCount(), 0)
            self.assertEqual(tool._capture_display_records, 0)
            self.assertEqual(tool._capture_display_bytes, 0)
        finally:
            capture.stop_tasks()
            capture.deleteLater()
            APP.processEvents()

    def test_capture_driver_failure_disables_refresh(self):
        capture = PacketCaptureTool()
        tool = capture._capture_tool
        process = mock.MagicMock()
        process.readAllStandardOutput.return_value = b""
        process.readAllStandardError.return_value = (
            b"tshark: Unable to load Npcap (wpcap.dll)")
        tool._capture_interface_proc = process
        try:
            tool._on_capture_interfaces_finished(process, 1)
            self.assertFalse(tool._btn_capture_refresh.isEnabled())
            self.assertFalse(tool._btn_capture_start.isEnabled())
            self.assertFalse(tool._btn_install_npcap.isHidden())
            self.assertFalse(tool._capture_driver_hint.isHidden())
            self.assertEqual(
                tool._capture_driver_hint.text(), "抓包驱动不可用")
            self.assertTrue(tool._capture_status.isHidden())

            capture.resize(1100, 720)
            capture.show()
            APP.processEvents()
            hint_geometry = tool._capture_driver_hint.geometry()
            button_geometry = tool._btn_install_npcap.geometry()
            start_geometry = tool._btn_capture_start.geometry()
            self.assertLessEqual(
                hint_geometry.center().y(), button_geometry.center().y() + 1)
            self.assertGreaterEqual(
                hint_geometry.center().y(), button_geometry.center().y() - 1)
            self.assertLessEqual(
                hint_geometry.right(), button_geometry.left())
            self.assertLessEqual(
                button_geometry.center().y(), start_geometry.center().y() + 1)
            self.assertGreaterEqual(
                button_geometry.center().y(), start_geometry.center().y() - 1)
        finally:
            capture.stop_tasks()
            capture.deleteLater()
            APP.processEvents()

    def test_capture_driver_success_hides_install_controls(self):
        capture = PacketCaptureTool()
        tool = capture._capture_tool
        process = mock.MagicMock()
        process.readAllStandardOutput.return_value = (
            b"1. \\Device\\NPF_TEST (Ethernet)\n")
        process.readAllStandardError.return_value = b""
        tool._capture_interface_proc = process
        tool._capture_waiting_for_npcap = True
        tool._btn_install_npcap.show()
        tool._show_capture_driver_hint("抓包驱动不可用")
        try:
            tool._on_capture_interfaces_finished(process, 0)
            self.assertFalse(tool._capture_waiting_for_npcap)
            self.assertTrue(tool._btn_install_npcap.isHidden())
            self.assertTrue(tool._capture_driver_hint.isHidden())
            self.assertFalse(tool._capture_status.isHidden())
            self.assertEqual(tool._capture_interface.count(), 1)
        finally:
            capture.stop_tasks()
            capture.deleteLater()
            APP.processEvents()

    def test_cancelled_npcap_installer_restores_button(self):
        capture = PacketCaptureTool()
        tool = capture._capture_tool

        class FakeInstaller:
            running = True
            closed = False

            def is_running(self):
                return self.running

            def close(self):
                self.closed = True

        installer = FakeInstaller()
        try:
            with mock.patch(
                    "anhutoolbox.tools.launch_npcap_installer",
                    return_value=installer):
                tool._install_npcap()
            self.assertTrue(tool._capture_waiting_for_npcap)
            self.assertFalse(tool._btn_install_npcap.isEnabled())
            self.assertEqual(
                tool._btn_install_npcap.text(), "等待安装驱动")

            installer.running = False
            with mock.patch.object(
                    tool, "_refresh_capture_interfaces") as refresh:
                tool._monitor_npcap_installer()
            self.assertTrue(installer.closed)
            self.assertFalse(tool._capture_waiting_for_npcap)
            self.assertTrue(tool._btn_install_npcap.isEnabled())
            self.assertEqual(
                tool._btn_install_npcap.text(), "安装抓包驱动")
            refresh.assert_called_once_with()
        finally:
            capture.stop_tasks()
            capture.deleteLater()
            APP.processEvents()

    def test_unexpected_capture_exit_rechecks_driver(self):
        capture = PacketCaptureTool()
        tool = capture._capture_tool
        process = mock.MagicMock()
        process.readAllStandardOutput.return_value = b""
        process.readAllStandardError.return_value = b""
        tool._capture_proc = process
        tool._capture_running = True
        tool._capture_stopping = False
        tool._capture_stdout_buffer = ""
        tool._capture_stderr_buffer = (
            "tshark: The NPF driver isn't running.")
        try:
            with mock.patch.object(
                    tool,
                    "_recheck_capture_driver_after_failure",
                    ) as recheck:
                tool._on_capture_finished(process, 1)
            recheck.assert_called_once_with()
            self.assertEqual(tool._capture_status.text(), "抓包异常结束")
            self.assertIn(
                "NPF driver", tool._capture_detail.toPlainText())
        finally:
            capture.stop_tasks()
            capture.deleteLater()
            APP.processEvents()

    def test_driver_recheck_reports_uninstalled_driver(self):
        capture = PacketCaptureTool()
        tool = capture._capture_tool
        process = mock.MagicMock()
        process.readAllStandardOutput.return_value = b""
        process.readAllStandardError.return_value = (
            b"tshark: The NPF driver isn't running.")
        tool._capture_interface_proc = process
        tool._capture_interface_recheck_after_failure = True
        try:
            tool._on_capture_interfaces_finished(process, 1)
            self.assertEqual(
                tool._capture_driver_hint.text(),
                "抓包驱动已卸载或不可用")
            self.assertFalse(tool._btn_capture_start.isEnabled())
            self.assertFalse(tool._btn_capture_refresh.isEnabled())
            self.assertFalse(tool._btn_install_npcap.isHidden())
        finally:
            capture.stop_tasks()
            capture.deleteLater()
            APP.processEvents()

    def test_driver_recheck_keeps_abnormal_exit_status_when_ready(self):
        capture = PacketCaptureTool()
        tool = capture._capture_tool
        process = mock.MagicMock()
        process.readAllStandardOutput.return_value = (
            b"1. \\Device\\NPF_TEST (Ethernet)\n")
        process.readAllStandardError.return_value = b""
        tool._capture_interface_proc = process
        tool._capture_interface_recheck_after_failure = True
        try:
            tool._on_capture_interfaces_finished(process, 0)
            self.assertEqual(tool._capture_status.text(), "抓包异常结束")
            self.assertTrue(tool._btn_capture_start.isEnabled())
            self.assertTrue(tool._btn_capture_refresh.isEnabled())
        finally:
            capture.stop_tasks()
            capture.deleteLater()
            APP.processEvents()

    def test_capture_file_failure_rechecks_driver(self):
        capture = PacketCaptureTool()
        tool = capture._capture_tool
        tool._capture_running = True
        tool._capture_file_stderr_buffer = (
            "dumpcap: The NPF driver isn't running.")
        try:
            with (
                mock.patch.object(tool, "_stop_capture") as stop_capture,
                mock.patch.object(
                    tool, "_recheck_capture_driver_after_failure"
                    ) as recheck,
            ):
                tool._on_capture_file_failed()
            stop_capture.assert_called_once_with()
            recheck.assert_called_once_with()
            self.assertEqual(
                tool._capture_status.text(), "抓包文件写入失败")
            self.assertIn(
                "NPF driver", tool._capture_detail.toPlainText())
        finally:
            capture.stop_tasks()
            capture.deleteLater()
            APP.processEvents()


if __name__ == "__main__":
    unittest.main()
