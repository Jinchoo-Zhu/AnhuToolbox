# -*- coding: utf-8 -*-
"""AnhuToolbox 面板组件 -- 校验函数库 + 统一日志面板"""

import json, re, time
import os
from datetime import datetime
from typing import Optional
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QCheckBox, QSpinBox, QPlainTextEdit, QFileDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QMenu, QComboBox, QScrollArea,
)
from PySide6.QtCore import QEvent, QSize, Qt, Signal, Slot, QTimer
from PySide6.QtGui import QFont, QFontMetrics, QIcon, QTextCursor

from .styles import _find_assets_dir, prepare_menu
from .dialogs import show_error, show_success, show_warning
from .log_writer import (
    AUTO_CLEAR_BYTES, AUTO_CLEAR_RECORDS, AsyncLogWriter,
)
from .ui_tokens import (
    FONT_UI, HTTP_TABLE_STYLE, ICON_SIZE, PRESET_PANEL_STYLE,
    TABLE_ROW_HEIGHT,
)


CHECKSUM_TYPES = ["None","ModbusCRC16","CCITT-CRC16","CRC32","OADD8","ADD8","XOR8","ADD16"]


_HEX_SEPARATORS = re.compile(r"[\s,;:_-]+")
_HEX_PREFIX = re.compile(r"(?i)0x")
SCROLLBAR_SLOT_HEIGHT = 8
SAVE_RULE_TEXT = (
    "未开启保存不清屏，"
    "开启保存后页面数据达到1万条/页面数据内存达到300MB清屏"
)
SAVE_RULE_TIP = (
    "未开启“保存到文件”时，页面不会自动清空。\n"
    "开启后数据持续写入所选文件；页面达到 1 万条或"
    "页面数据估算达到 300 MB 时，等待当前数据写入完成后"
    "自动清空页面。\n"
    "300 MB 指当前页面保留的数据，不是整个程序进程内存。"
)


def _save_rule_label():
    label = QLabel(SAVE_RULE_TEXT)
    label.setObjectName("saveRuleHint")
    label.setStyleSheet("color:#7A8088;font-size:11px")
    label.setToolTip(SAVE_RULE_TIP)
    return label


def _preset_icon(filename):
    return QIcon(os.path.join(_find_assets_dir(), filename))


def _set_preset_icon(button, filename):
    icon = _preset_icon(filename)
    if not icon.isNull():
        button.setIcon(icon)
        button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))


def parse_hex_bytes(text: str) -> bytes:
    """严格解析 HEX 文本，只忽略空白和常见分隔符。

    旧实现会删除所有非十六进制字符，``GG12`` 因此会被静默发送成 ``12``。
    这里保留空白、逗号、分号、冒号、下划线和连字符作为分隔符，并兼容
    ``0x12`` 形式；其余字符一律报错。
    """
    raw = str(text or "").strip()
    if not raw:
        return b""
    cleaned = _HEX_SEPARATORS.sub("", _HEX_PREFIX.sub("", raw))
    invalid = sorted({ch for ch in cleaned if ch not in "0123456789abcdefABCDEF"})
    if invalid:
        raise ValueError(
            "HEX 模式下包含非法字符：{}".format(" ".join(invalid))
        )
    if len(cleaned) % 2:
        raise ValueError("HEX 模式下十六进制字符数必须为偶数")
    return bytes.fromhex(cleaned)


def _modbus_crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc & 0xFFFF

_CCITT_TABLE = [0x0000,0x1021,0x2042,0x3063,0x4084,0x50A5,0x60C6,0x70E7,0x8108,0x9129,0xA14A,0xB16B,0xC18C,0xD1AD,0xE1CE,0xF1EF,0x1231,0x0210,0x3273,0x2252,0x52B5,0x4294,0x72F7,0x62D6,0x9339,0x8318,0xB37B,0xA35A,0xD3BD,0xC39C,0xF3FF,0xE3DE,0x2462,0x3443,0x0420,0x1401,0x64E6,0x74C7,0x44A4,0x5485,0xA56A,0xB54B,0x8528,0x9509,0xE5EE,0xF5CF,0xC5AC,0xD58D,0x3653,0x2672,0x1611,0x0630,0x76D7,0x66F6,0x5695,0x46B4,0xB75B,0xA77A,0x9719,0x8738,0xF7DF,0xE7FE,0xD79D,0xC7BC,0x48C4,0x58E5,0x6886,0x78A7,0x0840,0x1861,0x2802,0x3823,0xC9CC,0xD9ED,0xE98E,0xF9AF,0x8948,0x9969,0xA90A,0xB92B,0x5AF5,0x4AD4,0x7AB7,0x6A96,0x1A71,0x0A50,0x3A33,0x2A12,0xDBFD,0xCBDC,0xFBBF,0xEB9E,0x9B79,0x8B58,0xBB3B,0xAB1A,0x6CA6,0x7C87,0x4CE4,0x5CC5,0x2C22,0x3C03,0x0C60,0x1C41,0xEDAE,0xFD8F,0xCDEC,0xDDCD,0xAD2A,0xBD0B,0x8D68,0x9D49,0x7E97,0x6EB6,0x5ED5,0x4EF4,0x3E13,0x2E32,0x1E51,0x0E70,0xFF9F,0xEFBE,0xDFDD,0xCFFC,0xBF1B,0xAF3A,0x9F59,0x8F78,0x9188,0x81A9,0xB1CA,0xA1EB,0xD10C,0xC12D,0xF14E,0xE16F,0x1080,0x00A1,0x30C2,0x20E3,0x5004,0x4025,0x7046,0x6067,0x83B9,0x9398,0xA3FB,0xB3DA,0xC33D,0xD31C,0xE37F,0xF35E,0x02B1,0x1290,0x22F3,0x32D2,0x4235,0x5214,0x6277,0x7256,0xB5EA,0xA5CB,0x95A8,0x8589,0xF56E,0xE54F,0xD52C,0xC50D,0x34E2,0x24C3,0x14A0,0x0481,0x7466,0x6447,0x5424,0x4405,0xA7DB,0xB7FA,0x8799,0x97B8,0xE75F,0xF77E,0xC71D,0xD73C,0x26D3,0x36F2,0x0691,0x16B0,0x6657,0x7676,0x4615,0x5634,0xD94C,0xC96D,0xF90E,0xE92F,0x99C8,0x89E9,0xB98A,0xA9AB,0x5844,0x4865,0x7806,0x6827,0x18C0,0x08E1,0x3882,0x28A3,0xCB7D,0xDB5C,0xEB3F,0xFB1E,0x8BF9,0x9BD8,0xABBB,0xBB9A,0x4A75,0x5A54,0x6A37,0x7A16,0x0AF1,0x1AD0,0x2AB3,0x3A92,0xFD2E,0xED0F,0xDD6C,0xCD4D,0xBDAA,0xAD8B,0x9DE8,0x8DC9,0x7C26,0x6C07,0x5C64,0x4C45,0x3CA2,0x2C83,0x1CE0,0x0CC1,0xEF1F,0xFF3E,0xCF5D,0xDF7C,0xAF9B,0xBFBA,0x8FD9,0x9FF8,0x6E17,0x7E36,0x4E55,0x5E74,0x2E93,0x3EB2,0x0ED1,0x1EF0]

def _ccitt_crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc = (crc << 8) ^ _CCITT_TABLE[((crc >> 8) ^ b) & 0xFF]
        crc &= 0xFFFF
    return crc

_CRC32_TABLE = []
for _i in range(256):
    _val = _i
    for _j in range(8):
        _val = (_val >> 1) ^ 0xEDB88320 if _val & 1 else _val >> 1
    _CRC32_TABLE.append(_val)

def _crc32(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for b in data:
        crc = _CRC32_TABLE[(crc ^ b) & 0xFF] ^ (crc >> 8)
    return crc ^ 0xFFFFFFFF

def _oadd8(data: bytes) -> int:
    total = sum(data)
    return (total & 0xFF) ^ 0xFF

def _add8(data: bytes) -> int:
    return sum(data) & 0xFF

def _xor8(data: bytes) -> int:
    r = 0
    for b in data:
        r ^= b
    return r

def _add16(data: bytes) -> int:
    return sum(data) & 0xFFFF

_CHECKSUM_FUNCS = {"None":None,"ModbusCRC16":_modbus_crc16,"CCITT-CRC16":_ccitt_crc16,"CRC32":_crc32,"OADD8":_oadd8,"ADD8":_add8,"XOR8":_xor8,"ADD16":_add16}

def compute_checksum(ctype: str, data: bytes, start: int = 0, end: int = -1) -> Optional[int]:
    func = _CHECKSUM_FUNCS.get(ctype)
    if func is None:
        return None
    if end < 0:
        end = len(data)
    chunk = data[start:end]
    if not chunk:
        return None
    return func(chunk)

def format_checksum(ctype: str, value: int) -> str:
    # Display bytes in stream order (little-endian where applicable)
    if ctype in ("ModbusCRC16","CCITT-CRC16","ADD16"):
        lo = value & 0xFF
        hi = (value >> 8) & 0xFF
        return "{:02X} {:02X}".format(lo, hi)
    elif ctype == "CRC32":
        b = value.to_bytes(4, "little")
        return " ".join("{:02X}".format(x) for x in b)
    elif ctype in ("OADD8","ADD8","XOR8"):
        return "{:02X}".format(value & 0xFF)
    return hex(value)

def checksum_to_bytes(ctype: str, value: int) -> bytes:
    if ctype in ("ModbusCRC16","CCITT-CRC16","ADD16"):
        return value.to_bytes(2, "little")
    elif ctype == "CRC32":
        return value.to_bytes(4, "little")
    elif ctype in ("OADD8","ADD8","XOR8"):
        return value.to_bytes(1, "little")
    return b""


class LogPanel(QWidget):
    cleared = Signal()      # 清空日志后通知外部刷新统计
    file_error = Signal(str)
    MAX_PAUSED_BYTES = 16 * 1024 * 1024

    def __init__(self):
        super().__init__()
        self._paused = False
        self._pending_data = []
        self._pending_bytes = 0
        self._pause_dropped_bytes = 0
        self._rx_total = 0
        self._tx_total = 0
        self._save_writer = None
        self._save_path = None
        self._save_directory = os.getcwd()
        self._save_prefix = "serial"
        self._display_records = 0
        self._display_bytes = 0
        self._packet_buf = b""
        self._last_packet_ts = 0.0
        self._packet_start_dt = None
        self._packet_timer = QTimer()
        self._packet_timer.setSingleShot(True)
        self._packet_timer.timeout.connect(self._flush_packet)
        self._packet_timeout = 0
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6,6,6,2)
        layout.setSpacing(3)
        self._toolbar_content = QWidget()
        tb = QHBoxLayout(self._toolbar_content)
        tb.setContentsMargins(0, 0, 0, 0)
        tb.setSpacing(4)
        self.chk_hex = QCheckBox("HEX显示")
        self.chk_hex.setChecked(True)
        tb.addWidget(self.chk_hex)
        tb.addSpacing(10)
        self.chk_timestamp = QCheckBox("时间戳和分包显示")
        self.chk_timestamp.setChecked(True)
        self.chk_timestamp.toggled.connect(self._on_timestamp_toggled)
        tb.addWidget(self.chk_timestamp)
        tb.addSpacing(10)
        self.lbl_timeout = QLabel("超时(ms):")
        tb.addWidget(self.lbl_timeout)
        self.sp_timeout = QSpinBox()
        self.sp_timeout.setRange(0,9999)
        self.sp_timeout.setValue(0)
        self.sp_timeout.setFixedWidth(62)
        self.sp_timeout.setToolTip("接收合并超时时间：\n0 = 不合并，收到数据直接显示（不粘包）\n>0 = 两次接收间隔小于该值(ms)时合并为一帧")
        self.sp_timeout.valueChanged.connect(self._on_timeout_changed)
        tb.addWidget(self.sp_timeout)
        tb.addSpacing(12)
        self.chk_pause = QCheckBox("页面暂停")
        self.chk_pause.toggled.connect(self._on_pause)
        tb.addWidget(self.chk_pause)
        tb.addSpacing(10)
        self.chk_save_file = QCheckBox("保存到文件")
        self.chk_save_file.toggled.connect(self._on_save_file_toggle)
        tb.addWidget(self.chk_save_file)
        self.lbl_save_rule = _save_rule_label()
        tb.addWidget(self.lbl_save_rule)
        tb.addStretch()
        self.btn_clear = QPushButton("清空")
        self.btn_clear.setFixedHeight(24)
        self.btn_clear.setStyleSheet("QPushButton{padding:2px 10px;font-size:12px;border-radius:4px;min-height:20px;max-height:24px}")
        self.btn_clear.clicked.connect(self.clear)
        tb.addWidget(self.btn_clear)
        self._toolbar_layout = tb
        self._toolbar_scroll = QScrollArea()
        self._toolbar_scroll.setObjectName("logToolbarScroll")
        self._toolbar_scroll.setWidgetResizable(True)
        self._toolbar_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._toolbar_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._toolbar_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._toolbar_scroll.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._toolbar_scroll.horizontalScrollBar().setFixedHeight(
            SCROLLBAR_SLOT_HEIGHT)
        self._toolbar_scroll.setStyleSheet(
            "QScrollArea#logToolbarScroll{background:transparent;border:none;}"
            "QScrollArea#logToolbarScroll>QWidget>QWidget"
            "{background:transparent;}"
        )
        self._toolbar_scroll.setWidget(self._toolbar_content)
        self._fit_toolbar_width()
        layout.addWidget(self._toolbar_scroll)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setFont(QFont("Consolas",10))
        self.text.setStyleSheet("QPlainTextEdit{background-color:#FFF;color:#1A1A1A;border:1px solid #D0D0D0;border-radius:4px;padding:8px}")
        self._pending_lines = []
        self._display_timer = QTimer()
        self._display_timer.setSingleShot(True)
        self._display_timer.timeout.connect(self._flush_display)
        layout.addWidget(self.text, stretch=1)

    def _fit_toolbar_width(self):
        self._toolbar_layout.activate()
        content_height = max(
            24, self._toolbar_layout.minimumSize().height())
        self._toolbar_content.setMinimumWidth(
            self._toolbar_layout.sizeHint().width())
        self._toolbar_content.setFixedHeight(content_height)
        scrollbar_height = max(
            SCROLLBAR_SLOT_HEIGHT,
            self._toolbar_scroll.horizontalScrollBar().sizeHint().height(),
        )
        self._toolbar_scroll.setFixedHeight(
            content_height + scrollbar_height)

    def showEvent(self, event):
        # 全局样式生效后重新测量，内容区始终固定在滚动条上方。
        super().showEvent(event)
        QTimer.singleShot(0, self._fit_toolbar_width)

    def _on_timestamp_toggled(self, checked):
        """勾选“时间戳和分包显示”后, 超时时间才可修改; 否则标签与输入框置灰禁用"""
        self.lbl_timeout.setEnabled(checked)
        self.sp_timeout.setEnabled(checked)
        if not checked:
            # 关闭“分包显示”时, 立即刷出缓冲中的残余数据
            self._flush_packet()

    def _on_timeout_changed(self, val):
        self._packet_timeout = val
        if val <= 0:
            self._flush_packet()

    def _flush_packet(self):
        if self._packet_buf:
            data = self._packet_buf
            self._packet_buf = b""
            start_dt = self._packet_start_dt
            self._packet_start_dt = None
            self._append_raw("rx", data, start_dt)

    def _flush_display(self):
        """批量刷新显示: 将多条日志一次性写入, 减少 UI 重绘次数"""
        if not self._pending_lines:
            return
        text = "".join(self._pending_lines)
        self._pending_lines.clear()
        cursor = self.text.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(text)
        sb = self.text.verticalScrollBar()
        sb.setValue(sb.maximum())
        self._clear_display_if_saving_limit_reached()

    def _on_pause(self, checked):
        self._paused = checked
        if not checked and (self._pending_data or self._pause_dropped_bytes):
            pending = self._pending_data
            self._pending_data = []
            for d, dat in pending:
                # 暂停期间的数据补计数 + 补写文件
                if d == "rx":
                    self._rx_total += len(dat)
                else:
                    self._tx_total += len(dat)
                self._append_raw(d, dat)
            if self._pause_dropped_bytes:
                self._pending_lines.append(
                    "[提示] 暂停缓存超过 {} MB，已丢弃 {} 字节。\n".format(
                        self.MAX_PAUSED_BYTES // (1024 * 1024),
                        self._pause_dropped_bytes))
            self._pending_bytes = 0
            self._pause_dropped_bytes = 0
            self._display_timer.stop()
            self._flush_display()

    def _on_save_file_toggle(self, checked):
        if checked:
            self._flush_display()
            try:
                os.makedirs(self._save_directory, exist_ok=True)
            except Exception:
                pass
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            default_name = os.path.join(
                self._save_directory,
                "{}_{}.log".format(self._save_prefix, ts),
            )
            path, _ = QFileDialog.getSaveFileName(
                self, "保存日志", default_name,
                "日志文件 (*.log);;文本文件 (*.txt);;所有文件 (*.*)"
            )
            if path:
                self._save_path = path
                try:
                    self._save_writer = AsyncLogWriter(path, self)
                    self._save_writer.error.connect(
                        self._on_save_writer_error)
                    current = self.text.toPlainText()
                    if current:
                        self._save_writer.write_text(current)
                    for direction, data in self._pending_data:
                        self._save_writer.write_text(
                            self._format_raw_line(direction, data))
                    if self._packet_buf:
                        self._save_writer.write_text(
                            self._format_raw_line(
                                "rx",
                                self._packet_buf,
                                self._packet_start_dt,
                            )
                        )
                except Exception as e:
                    self._close_save_file()
                    show_error(self, "保存失败", str(e))
            else:
                self.chk_save_file.setChecked(False)
        else:
            self._close_save_file()

    def _close_save_file(self):
        writer, self._save_writer = self._save_writer, None
        if writer is not None:
            try:
                writer.close()
            except Exception:
                pass
            writer.deleteLater()
        if self.chk_save_file.isChecked():
            self.chk_save_file.blockSignals(True)
            self.chk_save_file.setChecked(False)
            self.chk_save_file.blockSignals(False)

    def _on_save_writer_error(self, message):
        if self._save_writer is None and not self.chk_save_file.isChecked():
            return
        self._close_save_file()
        self.file_error.emit(message)

    def set_log_directory(self, directory, prefix=None):
        self._save_directory = str(directory or "")
        if prefix:
            self._save_prefix = str(prefix)

    @Slot(str, bytes)
    def append_data(self, direction: str, data: bytes):
        """统一入口: 计数 + 写文件 + 路由(分包缓冲 或 直接显示)"""
        if self._save_writer is not None:
            self._write_saved_data(direction, data)
        if self._paused:
            if self._pending_bytes + len(data) > self.MAX_PAUSED_BYTES:
                self._pause_dropped_bytes += len(data)
                if direction == "rx":
                    self._rx_total += len(data)
                else:
                    self._tx_total += len(data)
                return
            self._pending_data.append((direction, data))
            self._pending_bytes += len(data)
            return
        # 计数
        if direction == "rx":
            self._rx_total += len(data)
        else:
            self._tx_total += len(data)
        # 路由: 勾选“时间戳和分包显示”且超时 >0 时按超时合包, 否则直接显示
        if direction == "rx" and self.chk_timestamp.isChecked() and self._packet_timeout > 0:
            self._feed_packet(data)
            return
        self._append_raw(direction, data)

    def _feed_packet(self, data: bytes):
        """分包缓冲: 按接收间隔拆帧, 低延迟显示。

        - 距上一帧数据超过超时时间 -> 视为新的一帧, 先把缓冲输出
        - 定时器只启动一次, 不被每次数据到达重置, 保证数据流结束后能及时刷新
        - 超过 8KB 强制刷新, 防止持续数据流无限累积
        """
        now = time.monotonic()
        if self._packet_buf and (now - self._last_packet_ts) * 1000 >= self._packet_timeout:
            self._flush_packet()
        if not self._packet_buf:
            # 记录本帧第一个字节到达的时刻(墙钟), flush 时用它打时间戳
            self._packet_start_dt = datetime.now()
        self._packet_buf += data
        self._last_packet_ts = now
        if len(self._packet_buf) > 8192:
            self._flush_packet()
        elif not self._packet_timer.isActive():
            self._packet_timer.start(self._packet_timeout)

    def _append_raw(self, direction: str, data: bytes, ts_dt=None):
        """纯显示格式化 -- 不碰计数器, 文件在数据入口单独写入

        ts_dt: 时间戳对应的时刻; 分包模式下传入"包首字节到达时刻",
               未传入(未分包)时取当前时刻。每条数据独立成行。
        """
        line = self._format_raw_line(direction, data, ts_dt)
        self._display_records += 1
        self._display_bytes += len(line.encode("utf-8"))
        self._pending_lines.append(line)
        if not self._display_timer.isActive():
            self._display_timer.start(5)

    def _format_raw_line(self, direction: str, data: bytes, ts_dt=None):
        ts = ""
        if self.chk_timestamp.isChecked():
            ts = "[{}] ".format((ts_dt or datetime.now()).strftime("%H:%M:%S.%f")[:-3])
        arrow = "收←◆ " if direction == "rx" else "发→◆ "
        if self.chk_hex.isChecked():
            # HEX 串本身不含换行符, 末尾补 "\n" 让每条数据独立成行, 便于阅读
            line = ts + arrow + data.hex(" ").upper() + "\n"
        else:
            try:
                txt = data.decode("utf-8", errors="replace")
            except:
                txt = data.decode("latin-1", errors="replace")
            # 每条数据独立成行; 若勾选“加回车换行”则数据自带 \r\n, 显示上会多出一个空行
            line = ts + arrow + txt + "\n"
        return line

    def _write_saved_data(self, direction, data):
        writer = self._save_writer
        if writer is None:
            return
        if not writer.write_text(
                self._format_raw_line(direction, data)):
            self._on_save_writer_error(
                "日志写入失败，保存已停止")

    def _clear_display_if_saving_limit_reached(self):
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
        self._pending_lines.clear()
        self._display_timer.stop()
        self.text.clear()
        self._display_records = 0
        self._display_bytes = 0

    def _add_widget(self, widget):
        """供外部在工具栏末尾插入控件"""
        self._toolbar_layout.addWidget(widget)
        self._fit_toolbar_width()

    def clear(self):
        if (
            self._save_writer is not None
            and not self._save_writer.flush()
        ):
            self._on_save_writer_error(
                "日志写入未完成，页面未清空，保存已停止")
            return
        self._pending_lines.clear()
        self._display_timer.stop()
        # 丢弃未输出的残包, 避免清空后缓冲又被刷出来
        self._packet_timer.stop()
        self._packet_buf = b""
        self._packet_start_dt = None
        self._pending_data.clear()
        self._pending_bytes = 0
        self._pause_dropped_bytes = 0
        self._display_records = 0
        self._display_bytes = 0
        self.text.clear()
        self._rx_total = 0
        self._tx_total = 0
        self.cleared.emit()

    def stop_save_file(self):
        """强制关闭“保存到文件”(切换项目时调用)"""
        self._close_save_file()

    def reset_runtime_state(self):
        """切换项目时复位运行时状态: 取消暂停 + 强制停止保存文件"""
        if self.chk_pause.isChecked():
            self.chk_pause.setChecked(False)
        self.stop_save_file()

    def cleanup(self):
        self._close_save_file()


# 定时发送/循环发送的间隔下限(ms) -- 界面与数据两侧共用同一个值,
# 避免"界面填不进 5ms 以下, 但配置文件里塞了 1 就真按 1ms 跑"的不一致。
# (5ms 是实测能稳定成帧的下限: 再小会被 Qt 定时器分辨率 + 串口线时吃掉)
MIN_INTERVAL_MS = 5

# 定时器"提前量容忍"(ms): Qt 的单次定时器偶尔会早零点几毫秒醒来, 只差这一点点
# 就当成到点直接发, 免得白醒一次再补一次定时(每次白醒要多吃约 1ms 的误差)。
DUE_TOL_MS = 0.75


def _advance_due(due_ms, iv_ms, now_ms):
    """把"下一轮该发的绝对时刻"往前推一整轮, 返回新的到期时刻(monotonic 毫秒)。

    这是"间隔填 5ms、实测却 6.8ms"的根因: QTimer.start(iv) 的语义是
    "本轮处理完再睡 iv", 而每轮发送本身要花时间(建帧 + 写串口 + 写日志 +
    刷状态栏, 约 0.5~2ms), 这截耗时会被原封不动叠进周期; 更糟的是每轮都拿
    "上一轮实际发出去的时刻"当基准重新起算, 于是误差一路累加, 越跑越慢。

    改成以"计划时刻 + 间隔"推进到期时刻: 实际耗时不进周期, 平均间隔就等于
    用户填的 ms; 只有真正被卡住(落后超过一整个周期, 如拖窗口/串口阻塞)时,
    才以当前时刻重新对齐, 不做突发补发。
    """
    if due_ms is None or due_ms <= now_ms - iv_ms:
        return now_ms + iv_ms
    return due_ms + iv_ms


def _warn_interval_too_small(parent, minimum):
    """间隔小于下限时的统一提示文案(输入框与预设表格两处共用, 免得文案跑偏)"""
    show_warning(
        parent, "间隔过小",
        "发送间隔不能小于 {}ms。\n已自动改为 {}ms。".format(minimum, minimum))


def _parse_interval(text):
    """把用户填的间隔文本转成整数, 转不了(空/非数字)返回 None"""
    t = (text or "").strip().replace(",", "").replace(" ", "")
    try:
        return int(t)
    except ValueError:
        return None


def _preset_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("1", "true", "yes", "on"):
            return True
        if text in ("0", "false", "no", "off", ""):
            return False
    return default


def _normalize_preset(preset, index=0):
    """把外部导入的预设规范成内部稳定结构。"""
    if not isinstance(preset, dict):
        raise ValueError("第 {} 条预设不是对象".format(index + 1))
    data = preset.get("data", "")
    name = preset.get("name", "")
    interval_value = _parse_interval(str(preset.get("interval", 1000)))
    if interval_value is None:
        interval_value = 1000
    return {
        "name": str(name if name is not None else "命令{}".format(index + 1)),
        "data": "" if data is None else str(data),
        "hex_mode": _preset_bool(preset.get("hex_mode", False), False),
        "interval": max(LOOP_MIN_INTERVAL, interval_value),
        "enabled": _preset_bool(preset.get("enabled", False), False),
    }


class IntervalSpinBox(QSpinBox):
    """间隔(ms)输入框: 填得比下限小时明确提示, 而不是静默还原。

    QSpinBox 对"小于下限"的手输内容既不接受也不解释 —— 提交时直接把内容
    还原成旧值(填 3 会悄悄变回 1000), 用户以为填进去了, 排查间隔不准时很难发现。
    这里在提交(回车/失焦)时检查用户手输的原文, 提示并把值钉在下限。

    手输原文只从 lineEdit 的 textEdited 里取: 该信号只在用户编辑时发出,
    Qt 自己回写文本(更新显示)不会触发它, 所以原文不会被覆盖。
    (注意不能拿 valueChanged 当"输入已生效"的信号: 提交越界输入时 Qt 会先把
    文本还原、并补发一次 valueChanged, 正好在这时把原文冲掉。)
    """

    def __init__(self, minimum, maximum, parent=None):
        super().__init__(parent)
        self._min = minimum
        self._raw = ""     # 用户上一次手输的原文
        self.setRange(minimum, maximum)
        self.lineEdit().textEdited.connect(self._on_edited)
        self.editingFinished.connect(self._check_below_min)

    def _on_edited(self, text):
        self._raw = text

    def stepBy(self, steps):
        # 上下箭头取整 = 用户自己选定了值, 之前手输的原文作废
        self._raw = ""
        super().stepBy(steps)

    def _check_below_min(self):
        raw, self._raw = self._raw, ""
        n = _parse_interval(raw)
        if n is None or n >= self._min:
            return
        self.setValue(self._min)       # 低于下限的输入钉在下限
        _warn_interval_too_small(self, self._min)


class SendBar(QWidget):
    send_data = Signal(bytes)
    repeat_tick = Signal()

    def __init__(self):
        super().__init__()
        self._tx_total = 0
        self._build_error = ""
        # 「定时发送」用单次定时器 + "计划时刻"重新排期:
        #   QTimer.start(iv) 是"本轮结束后再等 iv", 实际间隔 = iv + 本轮耗时,
        #   跑久了会一直往后漂; 这里由 _advance_due() 推进计划时刻, 每轮只补
        #   差值, 平均速率与用户填的 ms 一致。PreciseTimer 让 5ms 级间隔也能守住。
        self._repeat_due = None      # 下一次计划发送时刻(monotonic 毫秒); None = 未起算
        self._repeat_timer = QTimer()
        self._repeat_timer.setSingleShot(True)
        self._repeat_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._repeat_timer.timeout.connect(self._on_repeat_timeout)
        self._build()

    def _make_icon_btn(self, text, tip):
        btn = QPushButton(text)
        btn.setToolTip(tip)
        btn.setFixedSize(26, 24)
        btn.setStyleSheet("QPushButton{background:#E8F0FE;color:#0078D4;border:1px solid #B3D4FC;border-radius:3px;font-size:13px;font-weight:700;padding:0}QPushButton:hover{background:#D0E4FC}QPushButton:pressed{background:#B3D4FC}")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return btn

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6,2,6,6)
        layout.setSpacing(4)

        # Row 1: input + send button
        r1 = QHBoxLayout(); r1.setSpacing(8)
        self.text = QPlainTextEdit()
        self.text.setFont(QFont("Consolas",10))
        self.text.setMaximumHeight(64)
        self.text.setPlaceholderText("在此输入要发送的数据...")
        self.text.setStyleSheet("QPlainTextEdit{background:#FFF;color:#1A1A1A;border:1px solid #D0D0D0;border-radius:4px;padding:6px}")
        r1.addWidget(self.text, stretch=1)
        self.btn_send = QPushButton("发送")
        self.btn_send.setObjectName("btn_send")
        self.btn_send.setMinimumHeight(50); self.btn_send.setMinimumWidth(80)
        self.btn_send.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_send.clicked.connect(self._do_send)
        r1.addWidget(self.btn_send)
        layout.addLayout(r1)

        # Rows 2/3 share one horizontal scroll region so wide checksum and
        # timing controls never get compressed or cover the input above.
        self._controls_content = QWidget()
        controls_layout = QVBoxLayout(self._controls_content)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(4)

        # Row 2: checksum controls + icon buttons
        r2 = QHBoxLayout(); r2.setSpacing(5)
        r2.addWidget(QLabel("第"))
        self.sp_start = QSpinBox()
        self.sp_start.setRange(1,99999); self.sp_start.setValue(1)
        self.sp_start.setFixedWidth(58)
        r2.addWidget(self.sp_start)
        r2.addWidget(QLabel("字节至第"))
        self.cb_end = QComboBox()
        end_width = self.cb_end.fontMetrics().horizontalAdvance("-1(帧尾前)")
        self.cb_end.setFixedWidth(max(120, end_width + 44))
        self.cb_end.setEditable(True)
        self.cb_end.addItem("末尾",-1)
        self.cb_end.addItem("-1(帧尾前)",-1)
        self.cb_end.addItem("-2",-2); self.cb_end.addItem("-3",-3); self.cb_end.addItem("-4",-4); self.cb_end.addItem("-5",-5)
        self.cb_end.setCurrentText("末尾")
        r2.addWidget(self.cb_end)
        r2.addWidget(QLabel("字节加校验"))
        self.cb_checksum = QComboBox()
        self.cb_checksum.setMinimumWidth(115)
        self.cb_checksum.addItems(CHECKSUM_TYPES)
        self.cb_checksum.setCurrentText("ModbusCRC16")
        self.cb_checksum.currentTextChanged.connect(self._calc_checksum)
        r2.addWidget(self.cb_checksum)
        # Checksum value as styled label (like SSCOM yellow box)
        self.lbl_crc_val = QLabel("")
        self.lbl_crc_val.setMinimumWidth(75)
        self.lbl_crc_val.setAlignment(Qt.AlignCenter)
        self.lbl_crc_val.setStyleSheet("color:#0078D4;font-weight:700;font-family:Consolas;font-size:15px;padding:3px 8px;background:#E8F0FE;border-radius:4px;border:1px solid #B3D4FC")
        r2.addWidget(self.lbl_crc_val)
        r2.addStretch()
        controls_layout.addLayout(r2)

        # Row 3: switches
        r3 = QHBoxLayout(); r3.setSpacing(10)
        self.chk_hex = QCheckBox("HEX发送")
        r3.addWidget(self.chk_hex)
        self.chk_crlf = QCheckBox("加回车换行")
        self.chk_crlf.setChecked(True)
        self.chk_crlf.setStyleSheet("QCheckBox:disabled{color:#A0A0A0;}")
        r3.addWidget(self.chk_crlf)
        self.chk_repeat = QCheckBox("定时发送")
        self.chk_repeat.toggled.connect(self._on_repeat)
        r3.addWidget(self.chk_repeat)
        r3.addWidget(QLabel("间隔(ms):"))
        self.sp_interval = IntervalSpinBox(MIN_INTERVAL_MS, 99999)
        self.sp_interval.setValue(1000)
        self.sp_interval.setSingleStep(MIN_INTERVAL_MS)
        self.sp_interval.setToolTip(
            "定时发送的间隔(ms), 最小 {}ms\n".format(MIN_INTERVAL_MS) +
            "填得比 {}ms 小会提示并自动改回 {}ms\n".format(MIN_INTERVAL_MS, MIN_INTERVAL_MS) +
            "实际能跑多快还取决于串口波特率和从机响应速度")
        self.sp_interval.setEnabled(False); self.sp_interval.setFixedWidth(70)
        # 运行中改间隔立刻生效; 以前改完要重新勾一次「定时发送」才起作用
        self.sp_interval.valueChanged.connect(self.update_interval)
        r3.addWidget(self.sp_interval)
        r3.addSpacing(16)
        self.chk_dtr = QCheckBox("DTR")
        self.chk_dtr.setEnabled(False)
        self.chk_dtr.setToolTip("串口连接后可控制 DTR")
        r3.addWidget(self.chk_dtr)
        self.chk_rts = QCheckBox("RTS")
        self.chk_rts.setEnabled(False)
        self.chk_rts.setToolTip("串口连接后可控制 RTS")
        r3.addWidget(self.chk_rts)
        r3.addStretch()
        self.btn_send_file = QPushButton("发送文件")
        self.btn_send_file.clicked.connect(self._do_send_file)
        r3.addWidget(self.btn_send_file)
        self.lbl_tx_count = QLabel("Tx: 0")
        self.lbl_tx_count.setStyleSheet("color:#666;font-size:12px")
        r3.addWidget(self.lbl_tx_count)
        controls_layout.addLayout(r3)
        controls_layout.activate()
        controls_width = max(
            r2.sizeHint().width(), r3.sizeHint().width())
        controls_height = controls_layout.sizeHint().height()
        self._controls_content.setMinimumSize(
            controls_width, controls_height)

        self._controls_scroll = QScrollArea()
        self._controls_scroll.setObjectName("sendControlsScroll")
        self._controls_scroll.setWidgetResizable(True)
        self._controls_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._controls_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._controls_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._controls_scroll.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._controls_scroll.horizontalScrollBar().setFixedHeight(
            SCROLLBAR_SLOT_HEIGHT)
        self._controls_scroll.setStyleSheet(
            "QScrollArea#sendControlsScroll{background:transparent;"
            "border:none;}"
            "QScrollArea#sendControlsScroll>QWidget>QWidget"
            "{background:transparent;}"
        )
        self._controls_scroll.setWidget(self._controls_content)
        self._fit_controls_scroll()
        layout.addWidget(self._controls_scroll)

        self.text.textChanged.connect(self._calc_checksum)
        self.sp_start.valueChanged.connect(self._calc_checksum)
        self.cb_end.editTextChanged.connect(self._calc_checksum)
        self.cb_end.currentIndexChanged.connect(self._calc_checksum)
        self.chk_hex.toggled.connect(self._calc_checksum)
        self.chk_hex.toggled.connect(self._on_hex_toggled)

    def _fit_controls_scroll(self):
        """按控件真实最小高度预留横向滚动条槽位，避免底部被裁切。"""
        controls_layout = self._controls_content.layout()
        if controls_layout is None:
            return
        controls_layout.activate()
        controls_height = max(
            1, controls_layout.minimumSize().height())
        self._controls_content.setMinimumWidth(
            controls_layout.minimumSize().width())
        self._controls_content.setFixedHeight(controls_height)
        scrollbar_height = max(
            SCROLLBAR_SLOT_HEIGHT,
            self._controls_scroll.horizontalScrollBar().sizeHint().height(),
        )
        self._controls_scroll.setFixedHeight(
            controls_height + scrollbar_height)

    def showEvent(self, event):
        # 主窗口会在 SendBar 创建后应用全局样式，控件高度此时才最终确定。
        super().showEvent(event)
        QTimer.singleShot(0, self._fit_controls_scroll)

    def _parse_end_byte(self, data_len):
        t = self.cb_end.currentText().strip()
        if t in ("", "末尾"):
            return data_len
        try:
            v = int(t)
            return data_len + v if v < 0 else v
        except:
            idx = self.cb_end.findText(t)
            if idx >= 0:
                v = self.cb_end.itemData(idx)
                if v is not None:
                    return data_len + v if v < 0 else v
            return None


    def _build_raw(self):
        raw = self.text.toPlainText()
        if not raw:
            return None
        try:
            if self.chk_hex.isChecked():
                self._build_error = ""
                return parse_hex_bytes(raw)
            self._build_error = ""
            return raw.encode("utf-8")
        except (UnicodeError, ValueError) as exc:
            self._build_error = str(exc)
            return None

    def _append_newline(self, data: Optional[bytes]) -> Optional[bytes]:
        """文本模式下勾选“加回车换行”时, 在发送数据末尾附加回车换行(0x0D 0x0A);
        HEX 模式下严格按十六进制字节原样发送, 不附加任何结尾符."""
        if data and not self.chk_hex.isChecked() and self.chk_crlf.isChecked():
            return data + b"\r\n"
        return data

    def _on_hex_toggled(self, checked):
        """HEX发送模式下禁用“加回车换行”并自动取消勾选, 切回文本模式恢复可用"""
        if checked:
            self.chk_crlf.setChecked(False)
            self.chk_crlf.setCursor(Qt.CursorShape.ForbiddenCursor)
        else:
            self.chk_crlf.unsetCursor()
        self.chk_crlf.setEnabled(not checked)

    def _build_data_with_checksum(self):
        """Build data and auto-insert checksum per current rules"""
        d = self._build_raw()
        if d is None:
            return None
        ct = self.cb_checksum.currentText()
        if ct != "None":
            s = self.sp_start.value() - 1
            e = self._parse_end_byte(len(d))
            if e is None or e < s or e < 0:
                self._build_error = "校验结束位置无效，请检查字节区间"
                return None
            v = compute_checksum(ct, d, s, e)
            if v is None:
                self._build_error = "校验范围内没有可计算的数据"
                return None
            crc_b = checksum_to_bytes(ct, v)
            d = d[:e] + crc_b + d[e:]
        return self._append_newline(d)

    def _build_data_for_preset(self, raw_data: bytes):
        """Apply current checksum rules to preset data"""
        ct = self.cb_checksum.currentText()
        if ct != "None":
            s = self.sp_start.value() - 1
            e = self._parse_end_byte(len(raw_data))
            if e is None or e < s or e < 0:
                return None
            v = compute_checksum(ct, raw_data, s, e)
            if v is None:
                return None
            crc_b = checksum_to_bytes(ct, v)
            raw_data = raw_data[:e] + crc_b + raw_data[e:]
        return raw_data

    def _calc_checksum(self):
        ct = self.cb_checksum.currentText()
        if ct == "None":
            self.lbl_crc_val.setText("")
            return
        d = self._build_raw()
        if d is None:
            self.lbl_crc_val.setText("")
            return
        s = self.sp_start.value() - 1
        e = self._parse_end_byte(len(d))
        if e is None:
            self.lbl_crc_val.setText("")
            return
        v = compute_checksum(ct, d, s, e)
        self.lbl_crc_val.setText(format_checksum(ct, v) if v is not None else "")

    def _insert_checksum(self):
        ct = self.cb_checksum.currentText()
        if ct == "None":
            return
        # 构建原始数据(不含回车换行)，校验应基于原始帧
        d = self._build_raw()
        if d is None:
            return
        s = self.sp_start.value() - 1
        e = self._parse_end_byte(len(d))
        if e is None:
            return
        v = compute_checksum(ct, d, s, e)
        if v is None:
            return
        crc_b = checksum_to_bytes(ct, v)
        nd = d[:e] + crc_b + d[e:]
        if self.chk_hex.isChecked():
            self.text.setPlainText(nd.hex(" ").upper())
        else:
            self.text.setPlainText(nd.decode("utf-8", errors="replace"))

    def _echo_to_log(self):
        d = self._build_raw()
        if d:
            self.send_data.emit(d)

    def _do_send(self):
        d = self._build_data_with_checksum()
        if d:
            self.send_data.emit(d)
        elif self.text.toPlainText().strip():
            # 有内容但构建失败时显示具体原因，避免静默丢字符或误报长度问题。
            show_warning(
                self, "提示",
                "发送内容构建失败：\n{}".format(
                    self._build_error or "无法解析发送内容"))

    def _do_send_file(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择文件", "", "所有文件 (*.*);;文本文件 (*.txt)")
        if not p:
            return
        try:
            with open(p, "rb") as f:
                data = f.read()
            if self.chk_hex.isChecked():
                try:
                    t = data.decode("ascii")
                except UnicodeError:
                    show_warning(self, "提示", "HEX模式下文件无法解析")
                    return
                try:
                    data = parse_hex_bytes(t)
                except ValueError as exc:
                    show_warning(self, "提示", str(exc))
                    return
            self.send_data.emit(data)
        except Exception as e:
            show_error(self, "错误", str(e))

    def _build_data(self, silent=False):
        """构建定时发送数据；必须与手工发送使用相同的校验规则。"""
        data = self._build_data_with_checksum()
        if data is None and not silent and self.text.toPlainText().strip():
            show_warning(
                self, "提示",
                self._build_error or "发送内容构建失败")
        return data

    def _on_repeat(self, checked):
        self.sp_interval.setEnabled(checked)
        if checked:
            self._repeat_due = None     # 重新起算, 第一次仍在 1 个间隔后发
            self._arm_repeat()
        else:
            self._repeat_timer.stop()

    def _arm_repeat(self):
        """把下一次定时发送排到"计划时刻"上(计划时刻由 _advance_due 推进)。

        不是"本轮处理完再睡 iv" -- 那样每轮发送/写日志的耗时都会叠进周期里
        (实测填 5ms 会跑成 6.8ms)。这里只补差值, 平均间隔就等于输入框的 ms;
        被卡住(串口阻塞、拖窗口)超过一整个周期时重新对齐, 免得一下补发一串。
        """
        iv = max(MIN_INTERVAL_MS, self.sp_interval.value())
        now_ms = time.monotonic() * 1000.0
        self._repeat_due = _advance_due(self._repeat_due, iv, now_ms)
        self._repeat_timer.start(max(0, int(round(self._repeat_due - now_ms))))

    def _on_repeat_timeout(self):
        self.repeat_tick.emit()
        if self.chk_repeat.isChecked():
            self._arm_repeat()

    def update_interval(self):
        """间隔被改动后立刻按新值重新排期(运行中改也马上生效)。"""
        if self.chk_repeat.isChecked():
            self._repeat_due = None
            self._arm_repeat()

    def send_preset(self, data: bytes):
        self.send_data.emit(data)

    def stop_repeat(self):
        self._repeat_timer.stop()

    @property
    def tx_total(self):
        return self._tx_total


# 循环发送: 没有任何指令参与循环时的空转轮询周期(ms)。
# 有指令参与时不用轮询 -- 定时器按各自的间隔精确排期。
LOOP_IDLE_MS = 200
# 循环间隔下限(ms): 与界面(定时发送输入框)共用同一个下限, 见 MIN_INTERVAL_MS。
# 单元格填 0/负数/乱填时按这个值兜底, 不会静默漏发。
LOOP_MIN_INTERVAL = MIN_INTERVAL_MS


class PresetPanel(QWidget):
    """命令预设面板 -- 类SSCOM风格: 直接编辑, 数据列自动拉伸"""
    send_preset = Signal(bytes)

    def __init__(self):
        super().__init__()
        self._cur_hex = False
        self._cur_text = ""
        self._presets = []
        # 预设内容由「项目」持有: 外部通过回调写盘, 面板自己不再落文件
        self._on_change = None
        self._suspend_save = False
        self._resizing_preset_columns = False
        self._st = QTimer()
        self._st.setSingleShot(True)
        self._st.setTimerType(Qt.TimerType.PreciseTimer)
        self._st.timeout.connect(self._tick)
        # 循环队列状态: 已勾选"循环"的指令按表格顺序串行循环
        self._loop_pos = 0      # 当前队列中轮到第几条
        self._loop_last = None  # 上一次实际发送时间(仅用于排查, 不参与排期)
        self._loop_due = None   # 下一轮计划发送时刻(monotonic 毫秒), 循环排期的基准
        self._build()
        self._arm_loop()

    def _build(self):
        self.setObjectName("presetPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(PRESET_PANEL_STYLE)
        lo = QVBoxLayout(self)
        lo.setContentsMargins(10, 9, 10, 8)
        lo.setSpacing(8)

        header_content = QWidget()
        header_content_lo = QVBoxLayout(header_content)
        header_content_lo.setContentsMargins(0, 0, 0, 0)
        header_content_lo.setSpacing(6)
        tb = QHBoxLayout()
        tb.setSpacing(6)
        title = QLabel("命令预设")
        title.setObjectName("presetTitle")
        tb.addWidget(title)
        tb.addStretch()
        self.btn_add = QPushButton("添加")
        _set_preset_icon(self.btn_add, "http_add.svg")
        self.btn_add.setFixedHeight(30)
        self.btn_add.clicked.connect(self._add)
        tb.addWidget(self.btn_add)
        self.btn_imp = QPushButton("导入")
        _set_preset_icon(self.btn_imp, "http_upload.svg")
        self.btn_imp.setFixedHeight(30)
        self.btn_imp.clicked.connect(self._import)
        tb.addWidget(self.btn_imp)
        self.btn_exp = QPushButton("导出")
        _set_preset_icon(self.btn_exp, "http_save.svg")
        self.btn_exp.setFixedHeight(30)
        self.btn_exp.clicked.connect(self._export)
        tb.addWidget(self.btn_exp)
        header_content_lo.addLayout(tb)

        hint = QLabel(
            "勾选“循环”参与循环发送；勾选多条时按列表顺序发送，拖动序号可调整顺序。")
        hint.setObjectName("presetHint")
        hint.setWordWrap(False)
        hint.setToolTip(
            "勾选“循环”即参与循环发送。\n"
            "勾选多条时，按当前列表顺序逐条循环；拖动左侧序号可调整顺序。")
        header_content_lo.addWidget(hint)
        header_content_lo.activate()
        content_width = max(
            tb.sizeHint().width(), hint.sizeHint().width())
        content_height = max(
            1, header_content_lo.minimumSize().height())
        header_content.setMinimumWidth(content_width)
        header_content.setFixedHeight(content_height)

        self._header_scroll = QScrollArea()
        self._header_scroll.setObjectName("presetHeaderScroll")
        self._header_scroll.setWidgetResizable(True)
        self._header_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._header_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._header_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._header_scroll.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._header_scroll.horizontalScrollBar().setFixedHeight(
            SCROLLBAR_SLOT_HEIGHT)
        self._header_scroll.setStyleSheet(
            "QScrollArea#presetHeaderScroll{background:transparent;"
            "border:none;}"
            "QScrollArea#presetHeaderScroll>QWidget>QWidget"
            "{background:transparent;}"
        )
        self._header_scroll.setWidget(header_content)
        scrollbar_height = max(
            SCROLLBAR_SLOT_HEIGHT,
            self._header_scroll.horizontalScrollBar().sizeHint().height(),
        )
        self._header_scroll.setFixedHeight(
            content_height + scrollbar_height)
        lo.addWidget(self._header_scroll)

        # 列顺序: 名称 | 数据(自动拉伸) | HEX | 间隔(ms) | 循环 | 发送
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "名称", "数据", "HEX", "间隔(ms)", "循环", "发送"
        ])
        self.table.horizontalHeaderItem(3).setToolTip(
            "循环发送的间隔(ms), 最小 {}ms\n".format(LOOP_MIN_INTERVAL) +
            "填得比 {}ms 小会提示并自动改回 {}ms".format(
                LOOP_MIN_INTERVAL, LOOP_MIN_INTERVAL))
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Fixed)
        self.table.setColumnWidth(1, 200)
        self.table.setColumnWidth(2, 64)
        self.table.setColumnWidth(3, 100)
        self.table.setColumnWidth(4, 54)
        self.table.setColumnWidth(5, 58)
        self.table.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.horizontalHeader().setMinimumSectionSize(40)
        self.table.horizontalHeader().sectionResized.connect(
            self._on_preset_column_resized)
        self.table.viewport().installEventFilter(self)
        QTimer.singleShot(0, self._fit_preset_table_width)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(False)
        self.table.setFont(QFont(FONT_UI, 9))
        self.table.horizontalHeader().setFont(
            QFont(FONT_UI, 9, QFont.Weight.DemiBold))
        self.table.setStyleSheet(
            HTTP_TABLE_STYLE
            + "QTableWidget::item:selected{background-color:#FFFFFF;"
            "color:#1F2937;}"
            "QTableWidget::item:focus{border:none;background-color:#FFFFFF;}"
        )
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.setColumnWidth(0, self._preset_name_column_width())
        self.table.verticalHeader().setDefaultSectionSize(TABLE_ROW_HEIGHT)
        self.table.verticalHeader().setMinimumSectionSize(
            TABLE_ROW_HEIGHT)
        self.table.horizontalHeader().setMinimumHeight(TABLE_ROW_HEIGHT)
        # 允许直接点击编辑 (双击/按任意键/F2)
        self.table.setEditTriggers(
            QAbstractItemView.DoubleClicked |
            QAbstractItemView.EditKeyPressed |
            QAbstractItemView.AnyKeyPressed
        )
        self.table.cellChanged.connect(self._on_cell_changed)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._ctx)
        lo.addWidget(self.table, stretch=1)

        # 序号列 (vertical header) 可拖动重排. 拖动完成后 _on_section_moved
        # 会按新的 visual 顺序重排 _presets 并保存, 下次启动仍按这个顺序加载.
        vh = self.table.verticalHeader()
        vh.setSectionsMovable(True)
        vh.setSectionsClickable(True)
        vh.setHighlightSections(True)
        vh.setDefaultAlignment(Qt.AlignCenter)
        vh.setToolTip("按住序号拖动可以重新排序")
        vh.sectionMoved.connect(self._on_section_moved)

    def _preset_name_column_width(self):
        """名称列默认宽度：完整容纳 12 个中文字符及单元格内边距。"""
        font = QFont(FONT_UI)
        font.setPixelSize(13)
        text_width = QFontMetrics(font).horizontalAdvance("中" * 12)
        return text_width + 28

    def eventFilter(self, watched, event):
        if (
            watched is self.table.viewport()
            and event.type() == QEvent.Type.Resize
        ):
            QTimer.singleShot(0, self._fit_preset_table_width)
        return super().eventFilter(watched, event)

    def _on_preset_column_resized(
            self, logical_index, _old_size, new_size):
        if self._resizing_preset_columns or logical_index not in (0, 1):
            return
        if logical_index == 0:
            QTimer.singleShot(
                0,
                lambda width=new_size:
                self._fit_preset_table_width(
                    preferred_name_width=width),
            )
        else:
            QTimer.singleShot(
                0,
                lambda width=new_size:
                self._fit_preset_table_width(
                    preferred_data_width=width),
            )

    def _fit_preset_table_width(
            self, preferred_data_width=None, preferred_name_width=None):
        if self._resizing_preset_columns:
            return
        available = self.table.viewport().width()
        if available <= 0:
            return
        header = self.table.horizontalHeader()
        fixed_width = sum(header.sectionSize(column) for column in range(2, 6))
        capacity = available - fixed_width
        min_name = 40
        min_data = 60

        self._resizing_preset_columns = True
        try:
            if preferred_name_width is not None:
                name_width = max(min_name, int(preferred_name_width))
                data_width = capacity - name_width
                if data_width < min_data:
                    data_width = min_data
            elif preferred_data_width is not None:
                data_width = max(
                    min_data, int(preferred_data_width))
                name_width = capacity - data_width
                if name_width < min_name:
                    name_width = min_name
            else:
                name_width = max(
                    min_name, header.sectionSize(0))
                data_width = capacity - name_width
                if data_width < min_data:
                    data_width = min_data
            header.resizeSection(0, name_width)
            header.resizeSection(1, data_width)
        finally:
            self._resizing_preset_columns = False
        self.table.scheduleDelayedItemsLayout()
        self.table.viewport().update()

    def set_current_text(self, hm, txt):
        self._cur_hex = hm
        self._cur_text = txt

    # ---------------- 项目模式接口 ----------------
    def set_change_callback(self, cb):
        """内容变化时回调 cb(presets), 由主窗口写入当前项目"""
        self._on_change = cb

    def load_from_project(self, presets):
        """由项目注入预设(切换项目时调用) -- 循环勾选一律复位"""
        self._suspend_save = True
        normalized = []
        for index, p in enumerate(presets or []):
            if isinstance(p, dict):
                item = _normalize_preset(p, index)
                item["enabled"] = False
                normalized.append(item)
        self._presets = normalized
        self._loop_pos = 0
        self._loop_last = None
        self._loop_due = None
        self._refresh()
        self._suspend_save = False
        self._arm_loop()

    def dump_presets(self):
        """导出预设(剔除运行时字段)"""
        return [{k: v for k, v in p.items() if k not in ("_last", "enabled")}
                for p in self._presets]

    def stop_loops(self):
        """取消全部“循环”勾选(切换项目时调用, 防止误发)"""
        if any(p.get("enabled") for p in self._presets):
            for p in self._presets:
                p["enabled"] = False
            self._refresh()
        self._loop_pos = 0
        self._loop_last = None
        self._loop_due = None
        self._arm_loop()

    def _add(self):
        """直接新增一行空白, 用户自行填写"""
        idx = len(self._presets)
        self._presets.append({
            "name": "命令{}".format(idx + 1),
            "data": self._cur_text.strip() if self._cur_text.strip() else "",
            "hex_mode": self._cur_hex,
            "interval": 1000,
            "enabled": False
        })
        self._refresh()
        self._save()
        # 自动进入名称编辑模式
        self.table.editItem(self.table.item(idx, 0))

    def _refresh(self):
        """重建表格 -- 阻断信号防止 cellChanged 误触发"""
        self._presets = [
            _normalize_preset(p, i)
            for i, p in enumerate(self._presets) if isinstance(p, dict)
        ]
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for i, p in enumerate(self._presets):
            self.table.insertRow(i)
            # Col 0: 名称
            item_name = QTableWidgetItem(p.get("name", "命令{}".format(i + 1)))
            item_name.setToolTip(p.get("name", ""))
            self.table.setItem(i, 0, item_name)
            # Col 1: 数据 (长文本, 自动拉伸)
            item_data = QTableWidgetItem(p.get("data", ""))
            item_data.setToolTip(p.get("data", ""))
            self.table.setItem(i, 1, item_data)
            # Col 2: HEX 勾选框
            cb_hex = QCheckBox()
            cb_hex.setChecked(p.get("hex_mode", False))
            cb_hex.toggled.connect(lambda c, idx=i: self._toggle_hex(idx, c))
            cw_hex = QWidget()
            cw_hex.setStyleSheet("background:transparent;")
            cl_hex = QHBoxLayout(cw_hex)
            cl_hex.addWidget(cb_hex)
            cl_hex.setAlignment(Qt.AlignCenter)
            cl_hex.setContentsMargins(0, 0, 0, 0)
            self.table.setCellWidget(i, 2, cw_hex)
            # Col 3: 间隔(ms)
            item_iv = QTableWidgetItem(str(p.get("interval", 1000)))
            self.table.setItem(i, 3, item_iv)
            # Col 4: 循环 (勾选后按间隔自动发送)
            cb_loop = QCheckBox()
            cb_loop.setChecked(p.get("enabled", False))
            cb_loop.toggled.connect(lambda c, idx=i: self._toggle_loop(idx, c))
            cw_loop = QWidget()
            cw_loop.setStyleSheet("background:transparent;")
            cl_loop = QHBoxLayout(cw_loop)
            cl_loop.addWidget(cb_loop)
            cl_loop.setAlignment(Qt.AlignCenter)
            cl_loop.setContentsMargins(0, 0, 0, 0)
            self.table.setCellWidget(i, 4, cw_loop)
            # Col 5: 发送按钮
            btn = QPushButton()
            btn.setObjectName("presetRowSend")
            btn.setToolTip("发送这条预设")
            _set_preset_icon(btn, "http_send.svg")
            btn.setFixedSize(40, 28)
            btn.clicked.connect(lambda c, idx=i: self._send_one(idx))
            self.table.setCellWidget(i, 5, btn)
        self.table.blockSignals(False)

    # ---- 回调 ----
    def _toggle_loop(self, idx, checked):
        if idx < len(self._presets):
            self._presets[idx]["enabled"] = checked
            self._save()
            self._arm_loop()   # 立刻按新的队列重新排期, 不用等下一次空转

    def _toggle_hex(self, idx, checked):
        if idx < len(self._presets):
            self._presets[idx]["hex_mode"] = checked
            self._save()

    def _on_section_moved(self, logical_index, old_visual_index, new_visual_index):
        """用户拖动序号列重排行后, 按当前 visual 顺序重排 _presets 并保存.

        - logical_index    被移动 section 的逻辑索引 (数据上的序号)
        - old_visual_index 拖动前的可视位置
        - new_visual_index 拖动后的可视位置
        """
        n = self.table.rowCount()
        if n <= 1 or n != len(self._presets):
            return
        # 按当前 visual 顺序重构 _presets 列表 (visual 上看到的顺序即为新顺序)
        new_presets = [None] * n
        for logical in range(n):
            visual = self.table.verticalHeader().visualIndex(logical)
            if 0 <= visual < n:
                new_presets[visual] = self._presets[logical]
        if any(p is None for p in new_presets):
            return
        self._presets = new_presets
        # 重建表格, 让 checkbox/lambda 的 idx 重新绑定到新位置
        self._refresh()
        self._save()
        self._arm_loop()   # 顺序变了, 循环队列跟着改

    def _on_cell_changed(self, row, col):
        """单元格直接编辑后自动保存"""
        if row >= len(self._presets):
            return
        item = self.table.item(row, col)
        if item is None:
            return
        val = item.text().strip()
        if col == 0:   # 名称
            self._presets[row]["name"] = val
        elif col == 1: # 数据
            self._presets[row]["data"] = val
        elif col == 3: # 间隔(ms): 下限 LOOP_MIN_INTERVAL, 填小了会提示
            raw_iv = _parse_interval(val)
            if raw_iv is None:
                # 非数字: 保留原值, 但把单元格还原成真正生效的值,
                # 免得界面显示 "abc" 而实际按 1000ms 跑
                self._set_cell_text(row, col,
                                    str(self._presets[row].get("interval", LOOP_MIN_INTERVAL)))
            else:
                iv = max(LOOP_MIN_INTERVAL, raw_iv)
                self._presets[row]["interval"] = iv
                if raw_iv < LOOP_MIN_INTERVAL:
                    # 填得比下限小: 明确提示, 不静默夹值(否则用户以为按自己填的跑)
                    _warn_interval_too_small(self, LOOP_MIN_INTERVAL)
                if str(iv) != val:
                    self._set_cell_text(row, col, str(iv))
                self._arm_loop()   # 运行中改间隔立刻生效
        self._save()

    def _set_cell_text(self, row, col, text):
        """回写单元格文本(改文本会再触发一次 cellChanged, 所以这里阻断信号)"""
        item = self.table.item(row, col)
        if item is None or item.text() == text:
            return
        self.table.blockSignals(True)
        item.setText(text)
        self.table.blockSignals(False)

    def _send_one(self, idx):
        if idx >= len(self._presets):
            return
        p = self._presets[idx]
        d = _build_preset(p)
        if d:
            self.send_preset.emit(d)
        elif p.get("data", "").strip():
            self._warn_build_fail()

    def _warn_build_fail(self):
        show_warning(
            self, "提示",
            "发送内容构建失败：\nHEX 模式下只能包含十六进制字符和常规分隔符，"
            "且字符数必须为偶数。")

    def _tick(self):
        """定时器到期: 已勾选"循环"的指令按表格顺序串行循环发送.

        - 只勾选 1 条 = 单条按自己的间隔重复发送
        - 勾选多条 = 按表格顺序逐条发送, 发完当前条等待它自己的间隔后发下一条,
          发完最后一条回到第一条, 形成循环

        排期基准是 _loop_due(计划时刻), 不是"上一轮实际发出去的时刻":
        每轮的发送/写日志耗时不进周期, 平均间隔就等于用户填的 ms
        (旧版拿实际发送时刻当基准, 误差会一路累加, 填 5ms 实测 6.8ms)。
        """
        try:
            # 参与循环的队列 = 勾选了"循环"的指令, 按表格顺序
            # (间隔填 0/非法值按下限兜底, 见 _loop_interval, 不会静默漏发)
            items = [p for p in self._presets if p.get("enabled", False)]
            if not items:
                self._loop_pos = 0
                self._loop_last = None
                self._loop_due = None
                return
            if self._loop_pos >= len(items):
                self._loop_pos = 0
            # 时刻要在发送之前取: 下面按它推进计划时刻, 本轮发送耗时不算进周期
            now_ms = time.monotonic() * 1000.0
            if self._loop_due is not None and now_ms < self._loop_due - DUE_TOL_MS:
                return      # 定时器提前醒来, 还没到点: 由 _arm_loop 补一小觉
            cur = items[self._loop_pos]
            d = _build_preset(cur)
            if d:
                self.send_preset.emit(d)
            elif cur.get("data", "").strip():
                # 构建失败(HEX 长度奇数)：提示并自动取消该条循环，避免反复弹窗
                self._warn_build_fail()
                cur["enabled"] = False
                self._save()
                self._refresh()
            self._loop_last = datetime.now()
            self._loop_pos = (self._loop_pos + 1) % len(items)
            self._loop_due = _advance_due(
                self._loop_due, _loop_interval(items[self._loop_pos]), now_ms)
        except Exception:
            pass
        finally:
            self._arm_loop()

    def _arm_loop(self):
        """按"下一轮循环该发的计划时刻"(_loop_due)重定一次唤醒时间.

        没有勾选任何循环指令时低频空转(200ms 检查一次, 很轻),
        这样用户后来勾上一条也能很快开始发送。
        """
        items = [p for p in self._presets if p.get("enabled", False)]
        if not items:
            self._loop_due = None
            self._st.start(LOOP_IDLE_MS)
            return
        if self._loop_pos >= len(items):
            self._loop_pos = 0
        now_ms = time.monotonic() * 1000.0
        if self._loop_due is None:
            # 刚开始(或刚从空转恢复): 从现在起算一整轮, 第一次不抢发
            self._loop_due = now_ms + _loop_interval(items[self._loop_pos])
        rem = self._loop_due - now_ms
        # 已经是该发的时刻(或定时器提前醒来): 立刻再醒一次, 由 _tick 决定发不发
        self._st.start(int(round(rem)) if rem > 0 else 0)

    def _ctx(self, pos):
        """右键菜单: 仅保留删除"""
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        m = prepare_menu(QMenu(self))
        da = m.addAction("删除")
        act = m.exec(self.table.viewport().mapToGlobal(pos))
        if act == da:
            self.table.blockSignals(True)
            self._presets.pop(row)
            self._refresh()
            self.table.blockSignals(False)
            self._save()
            self._arm_loop()   # 少了一条, 循环队列要重新排期

    def stop_timer(self):
        self._st.stop()

    def _save(self):
        if self._suspend_save:
            return
        if self._on_change is not None:
            self._on_change(self.dump_presets())
            return
    def _import(self):
        p, _ = QFileDialog.getOpenFileName(self, "导入", "", "JSON (*.json)")
        if not p:
            return
        try:
            with open(p, "r", encoding="utf-8") as f:
                imp = json.load(f)
            if not isinstance(imp, list):
                raise ValueError("预设文件顶层必须是 JSON 数组")
            imported = [_normalize_preset(item, i) for i, item in enumerate(imp)]
            for item in imported:
                item["enabled"] = False
            self._presets.extend(imported)
            self._refresh()
            self._save()
            self._arm_loop()
            show_success(self, "导入成功", "已导入{} 条".format(len(imported)))
        except Exception as e:
            show_error(self, "导入失败", str(e))

    def _export(self):
        p, _ = QFileDialog.getSaveFileName(self, "导出", "presets.json", "JSON (*.json)")
        if not p:
            return
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(self.dump_presets(), f, ensure_ascii=False, indent=2)
            show_success(self, "导出成功", "已导出{} 条".format(len(self._presets)))
        except Exception as e:
            show_error(self, "导出失败", str(e))

def _loop_interval(preset):
    """取循环指令的间隔(ms): 非法值/小于下限的值兜底为 LOOP_MIN_INTERVAL, 不会静默漏发。"""
    try:
        iv = int(preset.get("interval", 0))
    except (TypeError, ValueError):
        iv = 0
    return iv if iv >= LOOP_MIN_INTERVAL else LOOP_MIN_INTERVAL


def _build_preset(preset):
    raw = preset.get("data","")
    if not raw:
        return None
    try:
        if preset.get("hex_mode",False):
            return parse_hex_bytes(raw)
        return raw.encode("utf-8")
    except (UnicodeError, ValueError):
        return None
