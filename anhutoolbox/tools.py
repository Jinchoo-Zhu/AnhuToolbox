# -*- coding: utf-8 -*-
"""AnhuToolbox 实用工具集: 时间戳转换 / 二维码生成 / JSON美化 / 进制转换"""

import io, os, json, re, shutil, tempfile, zipfile, time
from collections import OrderedDict
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QLayout,
    QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox,
    QGridLayout, QFileDialog, QApplication,
    QGraphicsOpacityEffect,
    QFrame, QStackedWidget, QButtonGroup, QSplitter, QTabWidget,
    QSizePolicy, QTableView, QHeaderView, QAbstractItemView, QCheckBox,
    QScrollBar,
)
from PySide6.QtCore import (
    Qt, QTimer, QRect, QSize, QPropertyAnimation, QAbstractAnimation, Signal,
    QProcess, QAbstractTableModel, QModelIndex,
)
from PySide6.QtGui import (
    QColor, QFont, QIcon, QImage, QKeySequence, QPixmap, QShortcut,
    QTextCharFormat,
)

from . import hardware
from . import toolbox
from .capture import (
    build_dumpcap_capture_args, build_tshark_capture_args,
    capture_resource_dirs, launch_npcap_installer, npcap_installer_path,
    parse_packet_fields, parse_tshark_interfaces,
)
from .dialogs import show_error, show_information, show_success, show_warning
from .log_writer import AUTO_CLEAR_BYTES, AUTO_CLEAR_RECORDS
from .panels import _save_rule_label
from .styles import _find_assets_dir
from .table_actions import apply_data_table_style
from .ui_tokens import (
    COLOR_DANGER, CONTROL_HEIGHT, HTTP_TABLE_STYLE, ICON_SIZE, SPACE_LG,
    SPACE_MD, SPACE_SM, TABLE_ROW_HEIGHT, TOOL_PAGE_STYLE,
)


def _tool_page(widget, title, subtitle):
    """为工具页建立统一的蓝白工作区与页头。"""
    widget.setObjectName("toolPage")
    widget.setStyleSheet(TOOL_PAGE_STYLE)

    root = QVBoxLayout(widget)
    root.setContentsMargins(
        SPACE_LG + 4, SPACE_LG + 2, SPACE_LG + 4, SPACE_LG)
    root.setSpacing(SPACE_MD)

    header = QWidget()
    header.setObjectName("toolPageHeader")
    header_lo = QHBoxLayout(header)
    header_lo.setContentsMargins(0, 0, 0, 0)
    header_lo.setSpacing(10)
    accent = QFrame()
    accent.setObjectName("toolAccent")
    accent.setFixedSize(3, 38)
    header_lo.addWidget(accent)

    texts = QVBoxLayout()
    texts.setSpacing(2)
    title_label = QLabel(title)
    title_label.setObjectName("toolPageTitle")
    texts.addWidget(title_label)
    subtitle_label = QLabel(subtitle)
    subtitle_label.setObjectName("toolPageSubtitle")
    subtitle_label.setWordWrap(False)
    texts.addWidget(subtitle_label)
    header_lo.addLayout(texts)
    header_lo.addStretch()
    root.addWidget(header)

    body = QVBoxLayout()
    body.setContentsMargins(0, 0, 0, 0)
    body.setSpacing(SPACE_MD)
    root.addLayout(body, stretch=1)
    return body


class ToolCard(QFrame):
    """带统一标题和操作区的白色工具卡片。"""

    def __init__(self, title=None, subtitle=None, parent=None):
        super().__init__(parent)
        self.setObjectName("toolCard")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(
            SPACE_MD + 2, SPACE_MD, SPACE_MD + 2, SPACE_MD)
        self._layout.setSpacing(SPACE_SM + 2)
        self.header = QHBoxLayout()
        self.header.setContentsMargins(0, 0, 0, 0)
        self.header.setSpacing(SPACE_SM)
        if title:
            heading = QVBoxLayout()
            heading.setSpacing(1)
            title_label = QLabel(title)
            title_label.setObjectName("toolCardTitle")
            heading.addWidget(title_label)
            if subtitle:
                subtitle_label = QLabel(subtitle)
                subtitle_label.setObjectName("toolCardSubtitle")
                subtitle_label.setWordWrap(False)
                heading.addWidget(subtitle_label)
            self.header.addLayout(heading)
            self.header.addStretch()
            self._layout.addLayout(self.header)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(SPACE_SM)
        self._layout.addLayout(self.body, stretch=1)

    def add_header_widget(self, widget, alignment=None):
        if alignment is None:
            self.header.addWidget(widget)
        else:
            self.header.addWidget(widget, 0, alignment)
        return widget


def _field_label(text):
    label = QLabel(text)
    label.setObjectName("toolFieldLabel")
    return label


def _hint_label(text=""):
    label = QLabel(text)
    label.setObjectName("toolHint")
    label.setWordWrap(True)
    return label


def _badge(text="", tone="default"):
    label = QLabel(text)
    label.setProperty("toolBadge", True)
    label.setProperty("tone", tone)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


def _set_tone(label, tone):
    label.setProperty("tone", tone)
    label.style().unpolish(label)
    label.style().polish(label)
    label.update()


def _set_button_icon(button, filename):
    icon = QIcon(os.path.join(_find_assets_dir(), filename))
    if not icon.isNull():
        button.setIcon(icon)
        button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
    return button


def _primary_button(text):
    button = QPushButton(text)
    button.setProperty("toolPrimary", True)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setMinimumHeight(CONTROL_HEIGHT)
    return _set_button_icon(button, "http_send.svg")


def _secondary_button(text, icon_name=None):
    button = QPushButton(text)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setMinimumHeight(CONTROL_HEIGHT)
    if icon_name:
        _set_button_icon(button, icon_name)
    return button


def _segment_button(text):
    button = QPushButton(text)
    button.setCheckable(True)
    button.setProperty("toolSegment", True)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setMinimumHeight(CONTROL_HEIGHT)
    return button


def _code_editor(editor, readonly=False):
    editor.setReadOnly(bool(readonly))
    editor.setProperty("toolReadonly", bool(readonly))
    editor.setFont(QFont("Consolas", 10))
    editor.setTabStopDistance(28)
    return editor


def _result_field(field, accent=False):
    field.setReadOnly(True)
    field.setProperty(
        "toolAccentResult" if accent else "toolResult", True)
    field.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
    field.setMinimumHeight(CONTROL_HEIGHT)
    return field


def _editor_card(title, editor, badge=None):
    card = ToolCard(title)
    if badge is not None:
        card.add_header_widget(badge)
    card.body.addWidget(editor, stretch=1)
    return card


# ============================================================
#  时间戳转换工具
# ============================================================
class TimestampTool(QWidget):
    def __init__(self):
        super().__init__()
        self._build()

    def _build(self):
        body = _tool_page(
            self,
            "时间戳转换",
            "在日期时间、Unix 秒和毫秒时间戳之间快速转换。",
        )

        now_card = ToolCard("当前时间", "本机时间每秒自动刷新")
        now_card.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        now_card.add_header_widget(_badge("实时", "primary"))
        now_metrics = QHBoxLayout()
        now_metrics.setSpacing(SPACE_SM)

        def add_metric(label, value):
            metric = QFrame()
            metric.setObjectName("toolMetric")
            metric_lo = QVBoxLayout(metric)
            metric_lo.setContentsMargins(12, 9, 12, 10)
            metric_lo.setSpacing(4)
            metric_lo.addWidget(_field_label(label))
            field = QLineEdit(value)
            field.setReadOnly(True)
            field.setFont(QFont("Consolas", 11))
            field.setMinimumHeight(CONTROL_HEIGHT)
            metric_lo.addWidget(field)
            now_metrics.addWidget(metric, stretch=1)
            return field

        self._lbl_now_dt = add_metric("日期时间", "")
        self._lbl_now_ts = add_metric("Unix 秒", "")
        self._lbl_now_ms = add_metric("Unix 毫秒", "")
        now_card.body.addLayout(now_metrics)
        body.addWidget(now_card)

        converters = QHBoxLayout()
        converters.setSpacing(SPACE_MD)

        ts_card = ToolCard(
            "时间戳转日期时间", "自动识别 10 位秒、13 位毫秒和 16 位微秒")
        ts_card.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self._ts_input = QLineEdit()
        self._ts_input.setPlaceholderText("例如 1700000000")
        self._ts_input.textChanged.connect(self._on_ts_input)
        ts_card.body.addWidget(_field_label("时间戳"))
        ts_card.body.addWidget(self._ts_input)
        ts_card.body.addWidget(_field_label("转换结果"))
        self._ts_result = _result_field(QLineEdit(), accent=True)
        ts_card.body.addWidget(self._ts_result)
        ts_card.body.addStretch()
        converters.addWidget(ts_card, stretch=1)

        dt_card = ToolCard(
            "日期时间转时间戳", "支持 2026-08-03 / 2026/08/03 格式")
        dt_card.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self._dt_input = QLineEdit()
        self._dt_input.setPlaceholderText("例如 2026-08-03 14:30:00")
        self._dt_input.textChanged.connect(self._on_dt_input)
        dt_card.body.addWidget(_field_label("日期时间"))
        dt_card.body.addWidget(self._dt_input)

        dt_results = QGridLayout()
        dt_results.setHorizontalSpacing(SPACE_SM)
        dt_results.setVerticalSpacing(4)
        dt_results.addWidget(_field_label("Unix 秒"), 0, 0)
        dt_results.addWidget(_field_label("Unix 毫秒"), 0, 1)
        self._dt_ts = _result_field(QLineEdit(), accent=True)
        self._dt_ms = _result_field(QLineEdit(), accent=True)
        dt_results.addWidget(self._dt_ts, 1, 0)
        dt_results.addWidget(self._dt_ms, 1, 1)
        dt_card.body.addLayout(dt_results)
        dt_card.body.addStretch()
        converters.addWidget(dt_card, stretch=1)
        body.addLayout(converters)
        body.addStretch()

        self._tick_timer = QTimer()
        self._tick_timer.timeout.connect(self._update_now)
        self._tick_timer.start(200)

    def _update_now(self):
        try:
            now = datetime.now()
            self._lbl_now_dt.setText(now.strftime("%Y-%m-%d %H:%M:%S"))
            self._lbl_now_ts.setText(str(int(now.timestamp())))
            self._lbl_now_ms.setText(str(int(now.timestamp() * 1000)))
        except (KeyboardInterrupt, RuntimeError):
            pass
    def _on_ts_input(self):
        s = self._ts_input.text().strip()
        if not s:
            self._ts_result.setText("")
            return
        try:
            ts = int(s)
            # 常见时间戳：10 位秒、13 位毫秒、16 位微秒。
            # 按数量级判断，避免把当前 13 位毫秒时间戳误当作秒。
            magnitude = abs(ts)
            if magnitude >= 100_000_000_000_000:
                ts //= 1_000_000
            elif magnitude >= 100_000_000_000:
                ts //= 1000
            dt = datetime.fromtimestamp(ts)
            self._ts_result.setText(dt.strftime("%Y-%m-%d %H:%M:%S"))
        except Exception:
            self._ts_result.setText("格式错误")

    def _on_dt_input(self):
        s = self._dt_input.text().strip()
        if not s:
            self._dt_ts.setText(""); self._dt_ms.setText("")
            return
        for fmt in ["%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S",
                     "%Y-%m-%d", "%Y/%m/%d"]:
            try:
                dt = datetime.strptime(s, fmt)
                ts = int(dt.timestamp())
                self._dt_ts.setText(str(ts))
                self._dt_ms.setText(str(ts * 1000))
                return
            except ValueError:
                continue
        self._dt_ts.setText("格式错误"); self._dt_ms.setText("格式错误")

    def stop_timer(self):
        self._tick_timer.stop()


# ============================================================
#  二维码批量生成工具
# ============================================================
class FlowLayout(QLayout):
    """简易流式布局：从左到右自动换行"""
    def __init__(self, parent=None, margin=0, spacing=10):
        super().__init__(parent)
        self._items = []
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._doLayout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._doLayout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for item in self._items:
            s = s.expandedTo(item.minimumSize())
        return s

    def _doLayout(self, rect, testOnly):
        x, y = rect.x(), rect.y()
        line_h = 0
        sp = self.spacing()
        right = rect.right()

        for item in self._items:
            sz = item.sizeHint()
            if x + sz.width() > right and line_h > 0:
                x = rect.x()
                y += line_h + sp
                line_h = 0
            if not testOnly:
                item.setGeometry(QRect(x, y, sz.width(), sz.height()))
            x += sz.width() + sp
            line_h = max(line_h, sz.height())
        return y + line_h - rect.y()


class ScaledPixmapLabel(QLabel):
    """在可用宽度内按正方形等比显示图片，供二维码预览自适应缩放。"""

    def __init__(self, pixmap=None, preferred_side=180, parent=None):
        super().__init__(parent)
        self.setObjectName("qrImage")
        self._source_pixmap = None
        self._preferred_side = preferred_side
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumWidth(96)
        self.setFixedHeight(preferred_side)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        if pixmap is not None:
            self.set_source_pixmap(pixmap)

    def set_source_pixmap(self, pixmap):
        self._source_pixmap = pixmap
        self._refresh_pixmap()

    def sizeHint(self):
        return QSize(self._preferred_side, self._preferred_side)

    def minimumSizeHint(self):
        return QSize(96, self._preferred_side)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_pixmap()

    def _refresh_pixmap(self):
        if self._source_pixmap is None or self._source_pixmap.isNull():
            return
        side = max(1, min(self.width(), self._preferred_side))
        self.setPixmap(self._source_pixmap.scaled(
            side, side,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))


class QRCellFrame(QFrame):
    """二维码卡片；有图片时双击可请求放大预览。"""

    double_clicked = Signal()

    def __init__(self, text, pixmap=None, parent=None):
        super().__init__(parent)
        self.setObjectName("qrCell")
        self._text = text
        self._pixmap = pixmap
        if pixmap is not None and not pixmap.isNull():
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip("双击放大二维码")

    def mouseDoubleClickEvent(self, event):
        if (self._pixmap is not None
                and not self._pixmap.isNull()
                and event.button() == Qt.MouseButton.LeftButton):
            self.double_clicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class QRTool(QWidget):
    """二维码批量生成：五列网格，预览数量有上限，批量保存不限量。"""
    ROWS, COLS = 2, 5
    MAX_PREVIEW_ITEMS = 200

    def __init__(self):
        super().__init__()
        self._lines = []
        self._cells = []
        self._build()

    def _build(self):
        body = _tool_page(
            self,
            "二维码生成",
            "每行输入一条内容，批量生成、预览并以 ZIP 保存二维码。",
        )

        input_card = ToolCard(
            "二维码内容", "空行会被忽略；修改内容后点击生成即可刷新预览")
        self._lbl_qr_count = _badge("尚未生成")
        input_card.add_header_widget(self._lbl_qr_count)

        self._qr_input = QPlainTextEdit()
        self._qr_input.setPlaceholderText("每行一个文本，对应一个二维码...")
        _code_editor(self._qr_input)
        self._qr_input.setMinimumHeight(112)
        self._qr_input.setMaximumHeight(150)
        input_card.body.addWidget(self._qr_input)

        btns = QHBoxLayout()
        self._btn_gen = _primary_button("生成预览")
        self._btn_gen.clicked.connect(self._generate)
        btns.addWidget(self._btn_gen)
        self._btn_save = _secondary_button("批量保存", "http_save.svg")
        self._btn_save.clicked.connect(self._batch_save)
        btns.addWidget(self._btn_save)
        btns.addStretch()
        input_card.body.addLayout(btns)
        body.addWidget(input_card)

        # 计算单元格基准尺寸：基于 box_size 估算单格宽度
        # 短文本版本1二维码：21模块, border=2 -> (21+4)*box_size
        self._cell_img_size = 180

        # 网格容器，行数按需动态创建
        self._grid_widget = QWidget()
        self._grid_widget.setObjectName("qrGrid")
        self._grid_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._grid = QGridLayout(self._grid_widget)
        self._grid.setContentsMargins(2, 2, 2, 2)
        self._grid.setSpacing(SPACE_SM)
        # 5 列均分
        for c in range(self.COLS):
            self._grid.setColumnStretch(c, 1)

        # 初始绘制 2 行空格子
        self._rebuild_grid(2)

        self._qr_scroll = QScrollArea()
        self._qr_scroll.setWidget(self._grid_widget)
        self._qr_scroll.setWidgetResizable(True)
        # 始终预留纵向滚动槽，避免第 11 条出现滚动条时重新分配宽度，
        # 导致整组二维码突然向左跳。
        self._qr_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self._qr_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        qr_scrollbar = self._qr_scroll.verticalScrollBar()
        qr_scrollbar.setObjectName("qrPreviewScrollBar")
        qr_scrollbar.rangeChanged.connect(
            self._update_qr_scrollbar_state)
        self._update_qr_scrollbar_state()
        preview_card = ToolCard(
            "二维码预览", "预览按单元格等比缩放，保存的 PNG 保持原始分辨率，双击可放大预览二维码")
        preview_card.body.addWidget(self._qr_scroll, stretch=1)
        body.addWidget(preview_card, stretch=1)

        self._qr_preview_overlay = QFrame(self)
        self._qr_preview_overlay.setObjectName("qrPreviewOverlay")
        self._qr_preview_overlay.setVisible(False)
        overlay_lo = QVBoxLayout(self._qr_preview_overlay)
        overlay_lo.setContentsMargins(24, 24, 24, 24)
        overlay_lo.addStretch()
        overlay_row = QHBoxLayout()
        overlay_row.addStretch()

        enlarged_card = QFrame()
        enlarged_card.setObjectName("qrEnlargedCard")
        enlarged_card.setMinimumWidth(460)
        enlarged_card.setMaximumWidth(700)
        enlarged_card.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        enlarged_lo = QVBoxLayout(enlarged_card)
        enlarged_lo.setContentsMargins(16, 12, 16, 16)
        enlarged_lo.setSpacing(SPACE_SM)

        enlarged_header = QHBoxLayout()
        enlarged_header.setSpacing(SPACE_SM)
        enlarged_header.addStretch()
        self._btn_close_qr_preview = QPushButton()
        self._btn_close_qr_preview.setObjectName("qrPreviewClose")
        self._btn_close_qr_preview.setFixedSize(32, 32)
        self._btn_close_qr_preview.setCursor(
            Qt.CursorShape.PointingHandCursor)
        self._btn_close_qr_preview.setFocusPolicy(
            Qt.FocusPolicy.NoFocus)
        self._btn_close_qr_preview.setToolTip("关闭预览并恢复二维码列表")
        self._btn_close_qr_preview.setAccessibleName("关闭预览")
        _set_button_icon(self._btn_close_qr_preview, "http_close.svg")
        if self._btn_close_qr_preview.icon().isNull():
            self._btn_close_qr_preview.setText("×")
        self._btn_close_qr_preview.clicked.connect(self._hide_qr_preview)
        enlarged_header.addWidget(self._btn_close_qr_preview)
        enlarged_lo.addLayout(enlarged_header)

        self._qr_preview_content = QLabel("")
        self._qr_preview_content.setObjectName("qrPreviewText")
        preview_font = QFont("Microsoft YaHei UI")
        preview_font.setPixelSize(16)
        preview_font.setWeight(QFont.Weight.DemiBold)
        self._qr_preview_content.setFont(preview_font)
        self._qr_preview_content.setAlignment(
            Qt.AlignmentFlag.AlignHCenter)
        self._qr_preview_content.setWordWrap(False)
        self._qr_preview_content.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        enlarged_lo.addWidget(self._qr_preview_content)

        self._qr_preview_image = ScaledPixmapLabel(preferred_side=480)
        enlarged_lo.addWidget(self._qr_preview_image, 0, Qt.AlignCenter)
        overlay_row.addWidget(enlarged_card)
        overlay_row.addStretch()
        overlay_lo.addLayout(overlay_row)
        overlay_lo.addStretch()

        self._esc_close_qr_preview = QShortcut(
            QKeySequence(Qt.Key.Key_Escape), self)
        self._esc_close_qr_preview.setContext(
            Qt.ShortcutContext.WindowShortcut)
        self._esc_close_qr_preview.setAutoRepeat(False)
        self._esc_close_qr_preview.activated.connect(
            self._hide_qr_preview)

    def _update_qr_scrollbar_state(self, *_):
        bar = self._qr_scroll.verticalScrollBar()
        bar.setEnabled(bar.maximum() > bar.minimum())

    def _show_qr_preview(self, text, pixmap):
        if pixmap is None or pixmap.isNull():
            return
        self._qr_preview_image.set_source_pixmap(pixmap)
        compact = " ".join(str(text).split())
        if len(compact) > 72:
            compact = compact[:69] + "..."
        self._qr_preview_content.setText(compact)
        self._qr_preview_content.setToolTip(str(text))
        self._qr_preview_overlay.setGeometry(self.rect())
        self._qr_preview_overlay.raise_()
        self._qr_preview_overlay.show()

    def _hide_qr_preview(self):
        self._qr_preview_overlay.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_qr_preview_overlay"):
            self._qr_preview_overlay.setGeometry(self.rect())

    def hideEvent(self, event):
        if hasattr(self, "_qr_preview_overlay"):
            self._qr_preview_overlay.hide()
        super().hideEvent(event)

    def _rebuild_grid(self, rows):
        """清空网格并按指定行数重建单元格"""
        # 清除旧格子
        old_rows = self._grid.rowCount()
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w:
                w.hide()
                w.deleteLater()
        # QGridLayout 会保留行最小高度；从多行缩回少行时必须清零，
        # 否则旧的末尾行会把可见行强行压缩。
        for row in range(old_rows):
            self._grid.setRowMinimumHeight(row, 0)
            self._grid.setRowStretch(row, 0)
        self._grid.invalidate()
        self._cells = []
        for r in range(rows):
            row_cells = []
            for c in range(self.COLS):
                cell = self._make_empty_cell()
                self._grid.addWidget(cell, r, c)
                row_cells.append(cell)
            self._cells.append(row_cells)
        cell_height = max(
            cell.sizeHint().height() for row in self._cells for cell in row)
        for row in range(rows):
            self._grid.setRowMinimumHeight(row, cell_height)
        self._sync_grid_height(rows, cell_height)

    def _sync_grid_height(self, rows, cell_height):
        """固定每行高度，超出预览区域时由滚动区滚动而不压缩内容。"""
        margins = self._grid.contentsMargins()
        spacing = self._grid.verticalSpacing()
        height = (
            margins.top() + margins.bottom()
            + rows * cell_height
            + max(0, rows - 1) * spacing
        )
        self._grid_widget.setFixedHeight(height)

    def _make_empty_cell(self):
        """空白格子：结构与 QR 格子一致，用同尺寸占位图保证等宽"""
        cell = QFrame()
        cell.setObjectName("qrCell")
        cl = QVBoxLayout(cell)
        cl.setContentsMargins(8, 6, 8, 8)
        cl.setSpacing(4)
        placeholder = QLabel()
        placeholder.setFixedHeight(28)
        cl.addWidget(placeholder)
        spacer = ScaledPixmapLabel(preferred_side=self._cell_img_size)
        cl.addWidget(spacer, 0, Qt.AlignCenter)
        cl.addStretch()
        return cell

    def _make_qr_cell(self, text, pixmap, error=None):
        """带二维码的格子：QR 图自适应缩放居中；生成失败时显示错误原因"""
        cell = QRCellFrame(text, pixmap)
        if pixmap is not None and not pixmap.isNull():
            cell.double_clicked.connect(
                lambda t=text, p=pixmap: self._show_qr_preview(t, p))
        cl = QVBoxLayout(cell)
        cl.setContentsMargins(8, 6, 8, 8)
        cl.setSpacing(4)

        lbl = QLabel(text)
        lbl.setObjectName("qrText")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setWordWrap(True)
        lbl.setFixedHeight(28)
        lbl.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        cl.addWidget(lbl)

        if pixmap:
            # 预览随单元格宽度等比放大/缩小，批量保存的 PNG 仍保持原始分辨率。
            ql = ScaledPixmapLabel(
                pixmap, preferred_side=self._cell_img_size)
            ql.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            cl.addWidget(ql, 0, Qt.AlignCenter)
        elif error:
            el = QLabel("生成失败\n" + error)
            el.setObjectName("qrError")
            el.setAlignment(Qt.AlignCenter)
            el.setWordWrap(True)
            el.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            cl.addWidget(el, 0, Qt.AlignCenter)
        cl.addStretch()

        return cell

    def _generate(self):
        text = self._qr_input.toPlainText().strip()
        self._lines = [l.strip() for l in text.split("\n") if l.strip()]

        n = len(self._lines)
        if n == 0:
            self._rebuild_grid(2)
            self._lbl_qr_count.setText("尚未生成")
            _set_tone(self._lbl_qr_count, "default")
            return

        preview_lines = self._lines[:self.MAX_PREVIEW_ITEMS]
        preview_count = len(preview_lines)
        # 动态行数：至少 2 行，多出的向上取整
        rows = max(2, (preview_count + self.COLS - 1) // self.COLS)
        self._rebuild_grid(rows)

        # 填入二维码
        fail = 0
        for i, line in enumerate(preview_lines):
            pix, err = self._make_qr_pixmap(line)
            if err:
                fail += 1
            cell = self._make_qr_cell(line, pix, err)
            r, c = i // self.COLS, i % self.COLS
            old_w = self._grid.itemAtPosition(r, c)
            if old_w:
                w = old_w.widget()
                self._grid.removeItem(old_w)
                if w:
                    w.hide()
                    w.deleteLater()
            self._grid.addWidget(cell, r, c)

        if n > self.MAX_PREVIEW_ITEMS:
            suffix = (
                "，失败 {} 条".format(fail) if fail else "")
            self._lbl_qr_count.setText(
                "共 {} 条，仅预览前 {} 条{}".format(
                    n, self.MAX_PREVIEW_ITEMS, suffix))
            _set_tone(
                self._lbl_qr_count, "error" if fail else "primary")
        elif fail:
            self._lbl_qr_count.setText(f"共 {n} 条，失败 {fail} 条")
            _set_tone(self._lbl_qr_count, "error")
        else:
            self._lbl_qr_count.setText(f"共 {n} 条")
            _set_tone(self._lbl_qr_count, "success")


    def _make_qr_pixmap(self, text):
        """生成二维码，返回 (QPixmap 或 None, 错误信息或 None)"""
        import qrcode
        try:
            qr = qrcode.QRCode(box_size=12, border=2)
            qr.add_data(text); qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buf = io.BytesIO(); img.save(buf, "PNG"); buf.seek(0)
            qimg = QImage.fromData(buf.read())
            return QPixmap.fromImage(qimg), None
        except Exception as e:
            return None, str(e)

    def _batch_save(self):
        import qrcode
        text = self._qr_input.toPlainText().strip()
        self._lines = [l.strip() for l in text.split("\n") if l.strip()]
        if not self._lines:
            show_information(self, "提示", "请输入二维码内容")
            return
        path_, _ = QFileDialog.getSaveFileName(
            self, "保存二维码 ZIP", "QR码.zip", "ZIP 文件 (*.zip)"
        )
        if not path_:
            return
        count = 0
        fail = 0
        errs = []
        used_names = set()

        def output_name(value, index):
            name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", value)
            name = name.strip().rstrip(". ")
            if not name:
                name = "QR_{:03d}".format(index + 1)
            if re.fullmatch(
                    r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", name):
                name = "_" + name
            name = name[:80].rstrip(". ") or "QR_{:03d}".format(index + 1)
            candidate = name + ".png"
            suffix = 2
            while candidate.casefold() in used_names:
                candidate = "{} ({}).png".format(name, suffix)
                suffix += 1
            used_names.add(candidate.casefold())
            return candidate

        try:
            with zipfile.ZipFile(path_, "w", zipfile.ZIP_DEFLATED) as zf:
                for i, line in enumerate(self._lines):
                    try:
                        qr = qrcode.QRCode(box_size=12, border=2)
                        qr.add_data(line); qr.make(fit=True)
                        img = qr.make_image(fill_color="black", back_color="white")
                        buf = io.BytesIO()
                        img.save(buf, "PNG")
                        fname = output_name(line, i)
                        zf.writestr(fname, buf.getvalue())
                        count += 1
                    except Exception as e:
                        fail += 1
                        errs.append(f"第 {i+1} 条: {e}")
            msg = f"已打包 {count} 张二维码到:\n{path_}"
            if fail:
                msg += f"\n\n{fail} 条生成失败:\n" + "\n".join(errs[:5])
                if fail > 5:
                    msg += f"\n... 共 {fail} 条"
            show_success(self, "完成", msg)
        except Exception as e:
            show_error(self, "错误", f"保存失败: {e}")

class JsonTool(QWidget):
    """JSON 格式化工具"""
    def __init__(self):
        super().__init__()
        self._build()

    def _build(self):
        body = _tool_page(
            self,
            "JSON 格式化",
            "校验、格式化或压缩 JSON 文本，左右对照查看处理结果。",
        )

        toolbar = ToolCard()
        actions = QHBoxLayout()
        actions.setSpacing(SPACE_SM)
        self._btn_format = _primary_button("格式化")
        self._btn_format.clicked.connect(self._format)
        actions.addWidget(self._btn_format)
        self._btn_compress = _secondary_button("压缩", "http_raw.svg")
        self._btn_compress.clicked.connect(self._compress)
        actions.addWidget(self._btn_compress)
        actions.addStretch()
        self._json_status = _badge("等待输入")
        actions.addWidget(self._json_status)
        toolbar.body.addLayout(actions)
        body.addWidget(toolbar)

        workspace = QSplitter(Qt.Orientation.Horizontal)
        workspace.setObjectName("toolSplit")
        workspace.setChildrenCollapsible(False)
        workspace.setHandleWidth(8)

        self._json_input = QPlainTextEdit()
        self._json_input.setPlaceholderText("粘贴 JSON 文本...")
        _code_editor(self._json_input)

        self._json_output = QPlainTextEdit()
        _code_editor(self._json_output, readonly=True)
        self._json_output.setPlaceholderText("格式化结果会显示在这里")
        self._json_output.textChanged.connect(self._update_json_copy_button)
        workspace.addWidget(_editor_card("输入", self._json_input))
        result_card = _editor_card("结果", self._json_output)
        self._btn_copy_output = _secondary_button("复制", "http_copy.svg")
        self._btn_copy_output.setToolTip("复制完整结果")
        self._btn_copy_output.setEnabled(False)
        self._btn_copy_output.clicked.connect(self._copy_json_output)
        result_card.add_header_widget(self._btn_copy_output)
        workspace.addWidget(result_card)
        workspace.setSizes([1, 1])
        body.addWidget(workspace, stretch=1)

    def _update_json_copy_button(self):
        self._btn_copy_output.setEnabled(
            bool(self._json_output.toPlainText()))

    def _copy_json_output(self):
        text = self._json_output.toPlainText()
        if not text:
            return
        QApplication.clipboard().setText(text)
        self._json_status.setText("已复制结果")
        _set_tone(self._json_status, "success")

    def _format(self):
        raw = self._json_input.toPlainText().strip()
        if not raw:
            self._json_status.setText("等待输入")
            _set_tone(self._json_status, "default")
            return
        try:
            obj = json.loads(raw)
            formatted = json.dumps(obj, ensure_ascii=False, indent=2)
            self._json_output.setPlainText(formatted)
            self._json_status.setText("格式化成功")
            _set_tone(self._json_status, "success")
        except json.JSONDecodeError as e:
            self._json_output.setPlainText(f"JSON 解析错误:\n{e}")
            self._json_status.setText("格式错误")
            _set_tone(self._json_status, "error")

    def _compress(self):
        raw = self._json_input.toPlainText().strip()
        if not raw:
            self._json_status.setText("等待输入")
            _set_tone(self._json_status, "default")
            return
        try:
            obj = json.loads(raw)
            compressed = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
            self._json_output.setPlainText(compressed)
            self._json_status.setText("压缩成功")
            _set_tone(self._json_status, "success")
        except json.JSONDecodeError as e:
            self._json_output.setPlainText(f"JSON 解析错误:\n{e}")
            self._json_status.setText("格式错误")
            _set_tone(self._json_status, "error")


# ============================================================
#  进制转换工具
# ============================================================
class BaseTool(QWidget):
    def __init__(self):
        super().__init__()
        self._build()

    def _build(self):
        body = _tool_page(
            self,
            "进制转换",
            "在二进制、八进制、十进制和十六进制之间即时转换。",
        )

        input_card = ToolCard("输入数值", "支持负数；十六进制使用 A-F 表示")
        input_row = QHBoxLayout()
        input_row.setSpacing(SPACE_SM)
        input_row.addWidget(_field_label("输入数值"))
        self._base_input = QLineEdit()
        self._base_input.setPlaceholderText("输入数值...")
        self._base_input.textChanged.connect(self._convert)
        input_row.addWidget(self._base_input, stretch=1)
        input_row.addSpacing(4)
        input_row.addWidget(_field_label("输入进制"))
        self._base_from = QComboBox()
        for b in [2, 8, 10, 16]:
            self._base_from.addItem(str(b), b)
        self._base_from.setCurrentText("10")
        self._base_from.currentIndexChanged.connect(self._convert)
        self._base_from.setFixedWidth(110)
        input_row.addWidget(self._base_from)
        input_card.body.addLayout(input_row)
        input_card.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        body.addWidget(input_card)

        result_card = ToolCard(
            "转换结果", "任一结果均可选中后复制使用")
        result_card.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        result_grid = QGridLayout()
        result_grid.setHorizontalSpacing(SPACE_SM)
        result_grid.setVerticalSpacing(SPACE_SM)
        self._results = {}
        bases = [("BIN (2)", 2), ("OCT (8)", 8), ("DEC (10)", 10), ("HEX (16)", 16)]
        for r, (label, base) in enumerate(bases):
            metric = QFrame()
            metric.setObjectName("toolMetric")
            metric_lo = QVBoxLayout(metric)
            metric_lo.setContentsMargins(12, 9, 12, 10)
            metric_lo.setSpacing(4)
            metric_lo.addWidget(_field_label(label))
            le = _result_field(QLineEdit())
            le.setFont(QFont("Consolas", 12))
            metric_lo.addWidget(le)
            result_grid.addWidget(
                metric, r // 2, r % 2)
            self._results[base] = le
        result_card.body.addLayout(result_grid)
        result_card.body.addStretch()
        body.addWidget(result_card)
        body.addStretch()

    def _convert(self):
        raw = self._base_input.text().strip()
        if not raw:
            for le in self._results.values():
                le.setText("")
            return
        from_base = self._base_from.currentData()
        try:
            val = int(raw, from_base)
        except ValueError:
            for le in self._results.values():
                le.setText("格式错误")
            return
        if 2 in self._results:
            self._results[2].setText(format(val, "b"))
        if 8 in self._results:
            self._results[8].setText(format(val, "o"))
        if 10 in self._results:
            self._results[10].setText(str(val))
        if 16 in self._results:
            self._results[16].setText(format(val, "X"))


# ============================================================
#  正则表达式测试工具
# ============================================================
class RegexTool(QWidget):
    def __init__(self):
        super().__init__()
        self._build()

    def _build(self):
        body = _tool_page(
            self,
            "正则表达式测试",
            "实时检查匹配结果、位置和捕获分组。",
        )

        config = ToolCard("匹配规则", "输入表达式后自动执行，不需要额外提交")
        self._re_input = QLineEdit()
        self._re_input.setPlaceholderText("输入正则表达式，如 \\d+")
        self._re_input.setFont(QFont("Consolas", 12))
        self._re_input.textChanged.connect(self._run_regex)
        config.body.addWidget(_field_label("正则表达式"))
        config.body.addWidget(self._re_input)

        opts_row = QHBoxLayout()
        opts_row.setSpacing(SPACE_SM)
        opts_row.addWidget(_field_label("匹配选项"))
        self._chk_ignorecase = _segment_button("忽略大小写")
        self._chk_ignorecase.clicked.connect(self._run_regex)
        opts_row.addWidget(self._chk_ignorecase)

        self._chk_multiline = _segment_button("多行模式")
        self._chk_multiline.clicked.connect(self._run_regex)
        opts_row.addWidget(self._chk_multiline)

        self._chk_dotall = _segment_button("点匹配换行")
        self._chk_dotall.clicked.connect(self._run_regex)
        opts_row.addWidget(self._chk_dotall)
        opts_row.addStretch()
        config.body.addLayout(opts_row)
        body.addWidget(config)

        workspace = QSplitter(Qt.Orientation.Vertical)
        workspace.setObjectName("toolSplit")
        workspace.setChildrenCollapsible(False)
        workspace.setHandleWidth(8)

        self._text_input = QPlainTextEdit()
        self._text_input.setPlaceholderText("输入要匹配的文本...")
        _code_editor(self._text_input)
        self._text_input.textChanged.connect(self._run_regex)

        self._result_output = QTextEdit()
        _code_editor(self._result_output, readonly=True)
        self._result_output.setPlaceholderText("匹配结果会显示在这里")
        self._regex_count = _badge("尚未匹配")
        workspace.addWidget(_editor_card("测试文本", self._text_input))
        workspace.addWidget(_editor_card(
            "匹配结果", self._result_output, self._regex_count))
        workspace.setSizes([300, 360])
        body.addWidget(workspace, stretch=1)

    def _run_regex(self):
        pattern = self._re_input.text()
        text = self._text_input.toPlainText()
        if not pattern:
            self._result_output.setHtml("")
            self._regex_count.setText("尚未匹配")
            _set_tone(self._regex_count, "default")
            return

        flags = 0
        if self._chk_ignorecase.isChecked():
            flags |= 2  # re.IGNORECASE
        if self._chk_multiline.isChecked():
            flags |= 8  # re.MULTILINE
        if self._chk_dotall.isChecked():
            flags |= 16  # re.DOTALL

        try:
            import re
            regex = re.compile(pattern, flags)
            matches = list(regex.finditer(text))

            if not matches:
                self._regex_count.setText("0 个匹配")
                _set_tone(self._regex_count, "default")
                hint = ""
                if "^" in pattern or "$" in pattern:
                    hint = (
                        "<br><br><span style='color:#888;font-size:11px'>"
                        "提示：正则含 ^ 或 $ 锚点，要求从字符串开头/结尾匹配。"
                        "若想匹配文本中的子串，请移除锚点或勾选「多行模式」。</span>"
                    )
                self._result_output.setHtml(
                    f"<div style='color:#999;padding:4px'>"
                    f"(无匹配){hint}</div>"
                )
                return

            # 构建美观的 HTML 结果
            self._regex_count.setText(f"{len(matches)} 个匹配")
            _set_tone(self._regex_count, "primary")
            parts = []
            parts.append(
                "<div style='font-family:Consolas;font-size:14px'>"
                f"<p style='color:#0078D4;font-weight:600;margin:0 0 8px 0'>"
                f"共找到 {len(matches)} 个匹配</p>"
            )

            for i, m in enumerate(matches):
                # 匹配卡片
                parts.append(
                    "<div style='background:#F8FAFC;border:1px solid #E9EEF3;"
                    "border-radius:4px;padding:6px 10px;margin-bottom:6px'>"
                )
                # 标题行
                parts.append(
                    f"<p style='margin:0 0 4px 0;font-size:13px;color:#666'>"
                    f"匹配 {i+1} &nbsp;|&nbsp; 位置 [{m.start()}, {m.end()}] &nbsp;|&nbsp; 长度 {m.end()-m.start()}"
                    "</p>"
                )
                # 匹配内容高亮
                parts.append(
                    f"<p style='margin:0;font-size:15px;font-weight:600;color:#333'>"
                    f"<span style='background:#EAF4FF;color:#005A9E;"
                    f"padding:2px 5px;border-radius:3px'>"
                    f"{self._escape_html(m.group())}</span>"
                    f"</p>"
                )
                # 分组
                if m.groups() or m.groupdict():
                    parts.append(
                        "<p style='margin:4px 0 0 0;font-size:11px;color:#555'>分组:</p>"
                    )
                    if m.groups():
                        for gi, g in enumerate(m.groups(), 1):
                            if g is not None:
                                parts.append(
                                    f"<span style='background:#EFFAF2;color:#107C10;"
                                    f"padding:2px 5px;border-radius:3px;margin:2px;"
                                    f"font-size:11px'>"
                                    f"{gi}: {self._escape_html(g)}</span> "
                                )
                    if m.groupdict():
                        for k, v in m.groupdict().items():
                            if v is not None:
                                parts.append(
                                    f"<span style='background:#EAF4FF;color:#005A9E;"
                                    f"padding:2px 5px;border-radius:3px;margin:2px;"
                                    f"font-size:11px'>"
                                    f"{k}: {self._escape_html(v)}</span> "
                                )
                    parts.append("<br>")
                parts.append("</div>")

            parts.append("</div>")
            self._result_output.setHtml("".join(parts))

        except Exception as e:
            self._regex_count.setText("表达式错误")
            _set_tone(self._regex_count, "error")
            self._result_output.setHtml(
                f"<div style='color:#E53935;font-family:Consolas;font-size:14px'>"
                f"正则错误: {self._escape_html(str(e))}</div>"
            )

    def _escape_html(self, s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class DiffTool(QWidget):
    def __init__(self):
        super().__init__()
        self._build()

    def _build(self):
        body = _tool_page(
            self,
            "文本对比",
            "逐行比较两份文本，差异会直接在左右编辑器中标记。",
        )

        toolbar = ToolCard()
        actions = QHBoxLayout()
        actions.setSpacing(SPACE_SM)
        self._btn_compare = _primary_button("开始对比")
        self._btn_compare.clicked.connect(self._compare)
        actions.addWidget(self._btn_compare)
        self._btn_clear = _secondary_button("清空", "http_delete.svg")
        self._btn_clear.clicked.connect(self._clear)
        actions.addWidget(self._btn_clear)
        actions.addStretch()
        actions.addWidget(_badge("左侧删除 / 替换", "error"))
        actions.addWidget(_badge("右侧新增 / 替换", "success"))
        toolbar.body.addLayout(actions)
        body.addWidget(toolbar)

        workspace = QSplitter(Qt.Orientation.Horizontal)
        workspace.setObjectName("toolSplit")
        workspace.setChildrenCollapsible(False)
        workspace.setHandleWidth(8)

        self._left_text = QPlainTextEdit()
        self._left_text.setPlaceholderText("粘贴原始文本...")
        _code_editor(self._left_text)
        self._left_text.setLineWrapMode(QPlainTextEdit.NoWrap)

        self._right_text = QPlainTextEdit()
        self._right_text.setPlaceholderText("粘贴对比文本...")
        _code_editor(self._right_text)
        self._right_text.setLineWrapMode(QPlainTextEdit.NoWrap)
        workspace.addWidget(_editor_card("原始文本", self._left_text))
        workspace.addWidget(_editor_card("对比文本", self._right_text))
        workspace.setSizes([1, 1])
        body.addWidget(workspace, stretch=1)

        # 同步滚动
        self._left_text.verticalScrollBar().valueChanged.connect(
            self._right_text.verticalScrollBar().setValue
        )
        self._right_text.verticalScrollBar().valueChanged.connect(
            self._left_text.verticalScrollBar().setValue
        )

    def _compare(self):
        import difflib
        left_lines = self._left_text.toPlainText().splitlines()
        right_lines = self._right_text.toPlainText().splitlines()

        # 清除旧的高亮
        self._left_text.setExtraSelections([])
        self._right_text.setExtraSelections([])

        if left_lines == right_lines:
            return

        sm = difflib.SequenceMatcher(None, left_lines, right_lines)
        opcodes = sm.get_opcodes()

        left_sel = []
        right_sel = []

        left_fmt = QTextCharFormat()
        left_fmt.setBackground(QColor(255, 200, 200))  # 浅红
        right_fmt = QTextCharFormat()
        right_fmt.setBackground(QColor(200, 255, 200))  # 浅绿

        for tag, i1, i2, j1, j2 in opcodes:
            if tag == "equal":
                continue
            if tag in ("delete", "replace"):
                for li in range(i1, i2):
                    cursor = self._left_text.textCursor()
                    cursor.movePosition(cursor.MoveOperation.Start)
                    for _ in range(li):
                        cursor.movePosition(cursor.MoveOperation.Down)
                    cursor.movePosition(cursor.MoveOperation.StartOfLine)
                    cursor.movePosition(cursor.MoveOperation.EndOfLine, cursor.MoveMode.KeepAnchor)
                    sel = QTextEdit.ExtraSelection()
                    sel.cursor = cursor
                    sel.format = left_fmt
                    left_sel.append(sel)
            if tag in ("insert", "replace"):
                for rj in range(j1, j2):
                    cursor = self._right_text.textCursor()
                    cursor.movePosition(cursor.MoveOperation.Start)
                    for _ in range(rj):
                        cursor.movePosition(cursor.MoveOperation.Down)
                    cursor.movePosition(cursor.MoveOperation.StartOfLine)
                    cursor.movePosition(cursor.MoveOperation.EndOfLine, cursor.MoveMode.KeepAnchor)
                    sel = QTextEdit.ExtraSelection()
                    sel.cursor = cursor
                    sel.format = right_fmt
                    right_sel.append(sel)

        self._left_text.setExtraSelections(left_sel)
        self._right_text.setExtraSelections(right_sel)

    def _clear(self):
        self._left_text.clear()
        self._right_text.clear()
        self._left_text.setExtraSelections([])
        self._right_text.setExtraSelections([])


class SortTool(QWidget):
    def __init__(self):
        super().__init__()
        self._build()

    def _build(self):
        body = _tool_page(
            self,
            "文本列表排序",
            "按名称、数值或长度排序，可同时去重和反转结果。",
        )

        options_card = ToolCard("排序选项", "每行一条文本，输入变化时自动处理")
        opts_row = QHBoxLayout()
        opts_row.setSpacing(SPACE_SM)
        opts_row.addWidget(_field_label("排序方式"))

        self._sort_mode = QComboBox()
        self._sort_mode.addItems(["名称", "数值", "长度"])
        self._sort_mode.currentIndexChanged.connect(self._run_sort)
        self._sort_mode.setFixedWidth(120)
        opts_row.addWidget(self._sort_mode)

        opts_row.addSpacing(10)

        self._btn_asc = _segment_button("升序")
        self._btn_asc.setChecked(True)
        self._btn_asc.clicked.connect(self._run_sort)
        opts_row.addWidget(self._btn_asc)

        self._btn_desc = _segment_button("降序")
        self._btn_desc.clicked.connect(self._run_sort)
        opts_row.addWidget(self._btn_desc)

        self._sort_order_group = QButtonGroup(self)
        self._sort_order_group.setExclusive(True)
        self._sort_order_group.addButton(self._btn_asc)
        self._sort_order_group.addButton(self._btn_desc)

        opts_row.addSpacing(14)
        opts_row.addWidget(_field_label("附加处理"))
        self._chk_unique = _segment_button("去重")
        self._chk_unique.clicked.connect(self._run_sort)
        opts_row.addWidget(self._chk_unique)

        self._chk_reverse = _segment_button("反转")
        self._chk_reverse.clicked.connect(self._run_sort)
        opts_row.addWidget(self._chk_reverse)

        opts_row.addStretch()
        options_card.body.addLayout(opts_row)
        body.addWidget(options_card)

        workspace = QSplitter(Qt.Orientation.Horizontal)
        workspace.setObjectName("toolSplit")
        workspace.setChildrenCollapsible(False)
        workspace.setHandleWidth(8)

        self._sort_input = QPlainTextEdit()
        self._sort_input.setPlaceholderText("每行一条文本...")
        _code_editor(self._sort_input)
        self._sort_input.textChanged.connect(self._run_sort)

        self._sort_output = QPlainTextEdit()
        _code_editor(self._sort_output, readonly=True)
        self._sort_output.setPlaceholderText("排序结果会显示在这里")
        workspace.addWidget(_editor_card("输入文本", self._sort_input))
        workspace.addWidget(_editor_card("排序结果", self._sort_output))
        workspace.setSizes([1, 1])
        body.addWidget(workspace, stretch=1)

    def _run_sort(self):
        text = self._sort_input.toPlainText().strip()
        if not text:
            self._sort_output.setPlainText("")
            return

        lines = text.splitlines()
        mode = self._sort_mode.currentText()
        reverse = not self._btn_asc.isChecked()

        if mode == "名称":
            lines.sort(reverse=reverse)
        elif mode == "数值":
            try:
                lines.sort(key=lambda x: float(x.strip()) if x.strip() else 0, reverse=reverse)
            except ValueError:
                lines.sort(reverse=reverse)
        elif mode == "长度":
            lines.sort(key=len, reverse=reverse)

        if self._chk_unique.isChecked():
            seen = set()
            uniq = []
            for l in lines:
                if l not in seen:
                    seen.add(l)
                    uniq.append(l)
            lines = uniq

        if self._chk_reverse.isChecked():
            lines.reverse()

        self._sort_output.setPlainText("\n".join(lines))




# ============================================================
#  编码转换工具
# ============================================================
class EncodeTool(QWidget):
    def __init__(self):
        super().__init__()
        self._build()

    def _build(self):
        body = _tool_page(
            self,
            "编码转换",
            "同时生成 HEX、Base64 和 URL 编码结果，便于对照使用。",
        )

        input_card = ToolCard(
            "输入内容", "可输入普通文本或 HEX 字符串，结果会实时刷新")
        self._enc_input = QPlainTextEdit()
        self._enc_input.setPlaceholderText("输入文本或 HEX 字符串...")
        _code_editor(self._enc_input)
        self._enc_input.setMinimumHeight(96)
        self._enc_input.setMaximumHeight(132)
        self._enc_input.textChanged.connect(self._convert_all)
        input_card.body.addWidget(self._enc_input)
        input_card.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        body.addWidget(input_card)

        # 转换结果网格: 2x3
        import base64, urllib.parse, binascii
        self._base64 = base64
        self._urlparse = urllib.parse
        self._binascii = binascii

        result_card = ToolCard(
            "转换结果", "结果框只读；双击或拖动可选择并复制内容")
        result_card.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        grid = QGridLayout()
        grid.setHorizontalSpacing(SPACE_SM)
        grid.setVerticalSpacing(SPACE_SM)

        items = [
            ("HEX → 字节", 0, 0),
            ("字节 → HEX", 0, 1),
            ("Base64 编码", 0, 2),
            ("Base64 解码", 1, 0),
            ("URL 编码", 1, 1),
            ("URL 解码", 1, 2),
        ]

        self._enc_results = {}
        for label, r, c in items:
            metric = QFrame()
            metric.setObjectName("toolMetric")
            metric_lo = QVBoxLayout(metric)
            metric_lo.setContentsMargins(12, 9, 12, 10)
            metric_lo.setSpacing(4)
            metric_lo.addWidget(_field_label(label))
            le = _result_field(QLineEdit())
            le.setFont(QFont("Consolas", 11))
            le.setPlaceholderText("—")
            metric_lo.addWidget(le)
            grid.addWidget(metric, r, c)
            self._enc_results[label] = le

        for column in range(3):
            grid.setColumnStretch(column, 1)
        result_card.body.addLayout(grid)
        result_card.body.addStretch()
        body.addWidget(result_card)
        body.addStretch()

    def _convert_all(self):
        text = self._enc_input.toPlainText()
        if not text.strip():
            for le in self._enc_results.values():
                le.setText("")
            return

        # HEX → 字节
        try:
            clean = text.replace(" ", "").replace("\n", "").replace("\n", "")
            raw = bytes.fromhex(clean)
            self._enc_results["HEX → 字节"].setText(
                " ".join(f"{b:02X}" for b in raw) + "  |  " +
                "".join(chr(b) if 32 <= b < 127 else "." for b in raw)
            )
        except Exception:
            self._enc_results["HEX → 字节"].setText("格式错误")

        # 字节 → HEX
        try:
            raw = text.encode("utf-8")
            self._enc_results["字节 → HEX"].setText(raw.hex(" ").upper())
        except Exception:
            self._enc_results["字节 → HEX"].setText("转换失败")

        # Base64
        try:
            self._enc_results["Base64 编码"].setText(
                self._base64.b64encode(text.encode("utf-8")).decode()
            )
        except Exception:
            self._enc_results["Base64 编码"].setText("转换失败")

        try:
            self._enc_results["Base64 解码"].setText(
                self._base64.b64decode(text.encode("utf-8")).decode("utf-8", errors="replace")
            )
        except Exception:
            self._enc_results["Base64 解码"].setText("格式错误")

        # URL
        try:
            self._enc_results["URL 编码"].setText(
                self._urlparse.quote(text, safe="")
            )
        except Exception:
            self._enc_results["URL 编码"].setText("转换失败")

        try:
            self._enc_results["URL 解码"].setText(
                self._urlparse.unquote(text)
            )
        except Exception:
            self._enc_results["URL 解码"].setText("格式错误")


# ============================================================
#  金额转换工具
# ============================================================
AMOUNT_DIGITS = "零壹贰叁肆伍陆柒捌玖"
AMOUNT_UNITS = ["", "拾", "佰", "仟"]
AMOUNT_SECTIONS = ["", "万", "亿", "万亿"]
AMOUNT_INPUT_DIGITS = {
    "零": 0, "〇": 0, "壹": 1, "贰": 2, "叁": 3, "肆": 4,
    "伍": 5, "陆": 6, "柒": 7, "捌": 8, "玖": 9,
    "0": 0, "1": 1, "2": 2, "3": 3, "4": 4,
    "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
}


def _convert_chinese_integer(number: int) -> str:
    """按中文四位节和十进制位值读整数，支持万亿级金额。"""
    if number == 0:
        return "零"
    sections = []
    while number:
        sections.append(number % 10000)
        number //= 10000
    if len(sections) > len(AMOUNT_SECTIONS):
        raise ValueError("金额超出支持范围（最多到万亿位）")

    result = ""
    zero_pending = False
    for index in range(len(sections) - 1, -1, -1):
        value = sections[index]
        if value == 0:
            # 亿与万之间只有一个空节时仍要保留“亿零”；最末空节无需再补零。
            if result and index > 0:
                zero_pending = True
            continue
        # 高级节内部不足四位时，节与节之间需要补零（如：壹万零贰拾）。
        if result and value < 1000 and not result.endswith("零"):
            result += "零"
        elif zero_pending and result and not result.endswith("零"):
            result += "零"
        part = ""
        digit_zero = False
        for position in range(3, -1, -1):
            digit = value // (10 ** position) % 10
            if digit:
                if digit_zero:
                    part += "零"
                part += AMOUNT_DIGITS[digit] + AMOUNT_UNITS[position]
                digit_zero = False
            elif part:
                digit_zero = True
        # 输出前补齐高位空节，节名才能稳定对应 万亿 / 亿 / 万 / 空；
        # 否则普通“万”会被错读成“万亿”。
        # 单位属于原数值中的 10^4 级，和节内位置无关。
        result += part + AMOUNT_SECTIONS[index]
        zero_pending = False
    return result


def amount_to_chinese(amount: Decimal) -> str:
    """人民币金额转财务大写，精确到分；0.5 -> 零元伍角整。"""
    if not amount.is_finite():
        raise ValueError("金额必须是有限数值")
    if amount < 0:
        raise ValueError("金额不能为负数")
    amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    fen = int(amount * 100)
    yuan, fraction = divmod(fen, 100)
    jiao, fen_digit = divmod(fraction, 10)

    result = (_convert_chinese_integer(yuan) if yuan else "零") + "元"
    if not fraction:
        return result + "整"
    if jiao:
        result += AMOUNT_DIGITS[jiao] + "角"
    elif yuan:
        result += "零"
    if fen_digit:
        result += AMOUNT_DIGITS[fen_digit] + "分"
    elif not yuan:
        result += "整"
    return result


def parse_amount_text(text: str) -> Decimal:
    """只识别人民币数字金额：允许千位逗号和会计括号负数。"""
    raw = (text or "").strip()
    if raw.startswith("(") and raw.endswith(")"):
        raw = "-" + raw[1:-1]
    raw = "".join(raw.split()).replace(",", "")
    if not raw or not (raw[0].isdigit() or raw[0] in ".+-"):
        raise ValueError("请输入金额，例如 892.88")
    try:
        amount = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError("金额格式错误，例如 892.88") from exc
    if not amount.is_finite():
        raise ValueError("金额必须是有限数值")
    if amount < 0:
        raise ValueError("金额不能为负数")
    if amount > Decimal("9999999999999999.99"):
        raise ValueError("金额超出支持范围（最多到万亿位）")
    return amount


_CHINESE_AMOUNT_PATTERN = re.compile(
    r"^(?:负)?(?:整|[零〇壹贰叁肆伍陆柒捌玖"
    r"拾佰仟万亿元角分整"
    r"0-9\.\s])+$"
)
_CHINESE_DIGIT_VALUE = {key: value for key, value in AMOUNT_INPUT_DIGITS.items() if not key.isdigit()}


def chinese_to_amount(text: str) -> Decimal:
    """反向解析人民币大写金额，支持元、角、分及万亿级别。"""
    raw = "".join((text or "").split())
    if not raw or not _CHINESE_AMOUNT_PATTERN.fullmatch(raw):
        raise ValueError("请输入标准中文大写金额")
    if raw.startswith("负"):
        raise ValueError("金额不能为负数")
    if raw.endswith("元整"):
        raw = raw[:-2] + "元"
    if "元" not in raw:
        raise ValueError("中文金额需要包含“元”")
    yuan_text, fraction_text = raw.split("元", 1)

    def parse_four(value_text):
        section, digit, previous = 0, None, 4
        for char in value_text:
            if char in ("零", "〇"):
                continue
            if char in _CHINESE_DIGIT_VALUE:
                if digit is not None:
                    raise ValueError("连续出现多个数字，请检查中文金额")
                digit = _CHINESE_DIGIT_VALUE[char]
            elif char in AMOUNT_UNITS:
                if digit is None:
                    raise ValueError("中文金额单位顺序错误")
                position = AMOUNT_UNITS.index(char)
                if position >= previous:
                    raise ValueError("万、仟、佰、拾的单位顺序错误")
                section += digit * (10 ** position)
                digit, previous = None, position
            else:
                raise ValueError("中文金额格式错误")
        return section + (digit or 0)

    def parse_yuan(value_text):
        if not value_text:
            return 0
        # 以 4^x 作为基本节权值，“万亿”直接用 10^12。
        # 这样万、亿节之间不依赖汉字数量；每个四位节仍独立校验顺序。
        parts = []
        start = 0
        index = 0
        while index < len(value_text):
            if value_text[index] not in ("万", "亿"):
                index += 1
                continue
            unit_end = index + 1
            if value_text.startswith("万亿", index):
                unit_end = index + 2
                multiplier = 10 ** 12
            elif value_text[index] == "亿":
                multiplier = 10 ** 8
            else:
                multiplier = 10 ** 4
            value = value_text[start:index]
            if not value:
                raise ValueError("万、亿前缺少金额数字")
            parts.append((parse_four(value), multiplier))
            start = index = unit_end
        if start < len(value_text):
            parts.append((parse_four(value_text[start:]), 1))
        elif not parts:
            parts.append((0, 1))

        # 高权节必须大于低权节；不能重复写“亿”。
        for current, following in zip(parts, parts[1:], strict=False):
            if current[1] <= following[1]:
                raise ValueError("万、亿的单位顺序错误")
        return sum(value * multiplier for value, multiplier in parts)

    yuan = parse_yuan(yuan_text)
    if yuan > 9999999999999999:
        raise ValueError("金额超出支持范围（最多到万亿位）")
    fraction = Decimal("0")
    if fraction_text:
        if fraction_text.endswith("整"):
            fraction_text = fraction_text[:-1]
        if "整" in fraction_text:
            raise ValueError("中文金额的“整”只能出现在末尾")
        if fraction_text.startswith("零"):
            fraction_text = fraction_text[1:]
        if "角" in fraction_text:
            jiao, fraction_text = fraction_text.split("角", 1)
            if not jiao or jiao not in _CHINESE_DIGIT_VALUE:
                raise ValueError("角位必须是一位中文数字")
            fraction += Decimal(_CHINESE_DIGIT_VALUE[jiao]) / 10
        if fraction_text:
            if not fraction_text.endswith("分"):
                raise ValueError("分位格式错误")
            fen = fraction_text[:-1]
            if not fen or fen not in _CHINESE_DIGIT_VALUE:
                raise ValueError("分位必须是一位中文数字")
            fraction += Decimal(_CHINESE_DIGIT_VALUE[fen]) / 100
    return Decimal(yuan) + fraction



class AmountTool(QWidget):
    """人民币金额转换：蓝色结果框只读，上下输入框均可转换。"""

    def __init__(self):
        super().__init__()
        self._copy_toast_timer = QTimer(self)
        self._copy_toast_timer.setSingleShot(True)
        self._copy_toast_timer.timeout.connect(self._hide_copy_toast)
        self._copy_toast_token = 0
        self._build()

    def _build(self):
        body = _tool_page(
            self,
            "金额转换",
            "人民币小写金额与财务中文大写双向转换，结果可一键复制。",
        )

        # 应用内 Toast 不占布局，放在页面中上方，隐藏时不挤压下方内容。
        self._copy_toast = QLabel(self)
        self._copy_toast.setObjectName("copy_toast")
        self._copy_toast.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._copy_toast.setTextFormat(Qt.TextFormat.PlainText)
        self._copy_toast.setStyleSheet(
            "QLabel#copy_toast{background:#FFFFFF;color:#166534;"
            "border:1px solid #B7E2C3;border-radius:8px;"
            "padding:8px 18px 8px 30px;font-family:'Microsoft YaHei';font-size:13px;}"
        )
        self._copy_toast.setVisible(False)
        self._copy_toast_tick = None

        cards = QHBoxLayout()
        cards.setSpacing(SPACE_MD)

        lower_card = ToolCard(
            "小写金额转中文大写", "结果按财务规范精确到分并四舍五入")
        lower_card.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        lower_form = QVBoxLayout()
        lower_form.setSpacing(SPACE_SM)
        lower_form.addWidget(_field_label("小写金额"))
        self._amount_input = QLineEdit()
        self._amount_input.setPlaceholderText("例如：10020.05")
        self._amount_input.setFont(QFont("Microsoft YaHei", 13))
        self._amount_input.setMinimumHeight(CONTROL_HEIGHT + 4)
        self._amount_input.textChanged.connect(self._on_amount_changed)
        lower_form.addWidget(self._amount_input)

        lower_form.addWidget(_field_label("中文大写"))
        upper_result_row = QHBoxLayout()
        upper_result_row.setSpacing(SPACE_SM)
        self._upper_output = _result_field(QLineEdit(), accent=True)
        self._upper_output.setMinimumHeight(CONTROL_HEIGHT + 4)
        self._upper_output.setFont(QFont("Microsoft YaHei", 13, QFont.Weight.Bold))
        upper_result_row.addWidget(self._upper_output, stretch=1)
        self._btn_copy_upper = _secondary_button("复制", "http_copy.svg")
        self._btn_copy_upper.setFixedWidth(76)
        self._btn_copy_upper.clicked.connect(self._copy_upper)
        upper_result_row.addWidget(self._btn_copy_upper)
        lower_form.addLayout(upper_result_row)
        self._amount_status = QLabel("")
        self._amount_status.setMinimumHeight(16)
        lower_form.addWidget(self._amount_status)
        lower_card.body.addLayout(lower_form)
        lower_card.body.addStretch()
        cards.addWidget(lower_card, stretch=1)

        upper_card = ToolCard(
            "中文大写转小写金额", "支持元、角、分、整以及万 / 亿级金额")
        upper_card.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        upper_form = QVBoxLayout()
        upper_form.setSpacing(SPACE_SM)
        upper_form.addWidget(_field_label("中文大写"))
        self._upper_input = QLineEdit()
        self._upper_input.setPlaceholderText("例如：壹万零贰拾元零伍分")
        self._upper_input.setFont(QFont("Microsoft YaHei", 13))
        self._upper_input.setMinimumHeight(CONTROL_HEIGHT + 4)
        self._upper_input.textChanged.connect(self._on_upper_changed)
        upper_form.addWidget(self._upper_input)

        upper_form.addWidget(_field_label("小写金额"))
        lower_result_row = QHBoxLayout()
        lower_result_row.setSpacing(SPACE_SM)
        self._lower_output = _result_field(QLineEdit(), accent=True)
        self._lower_output.setMinimumHeight(CONTROL_HEIGHT + 4)
        self._lower_output.setFont(QFont("Consolas", 13, QFont.Weight.Bold))
        lower_result_row.addWidget(self._lower_output, stretch=1)
        self._btn_copy_lower = _secondary_button("复制", "http_copy.svg")
        self._btn_copy_lower.setFixedWidth(76)
        self._btn_copy_lower.clicked.connect(self._copy_lower)
        lower_result_row.addWidget(self._btn_copy_lower)
        upper_form.addLayout(lower_result_row)
        self._reverse_status = QLabel("")
        self._reverse_status.setMinimumHeight(16)
        upper_form.addWidget(self._reverse_status)
        upper_card.body.addLayout(upper_form)
        upper_card.body.addStretch()
        cards.addWidget(upper_card, stretch=1)

        body.addLayout(cards)
        body.addStretch()
        self._on_amount_changed()

    def _on_amount_changed(self):
        if not self._amount_input.text().strip():
            self._upper_output.clear()
            self._set_status(self._amount_status, "")
            return
        try:
            amount = parse_amount_text(self._amount_input.text())
            self._upper_output.setText(amount_to_chinese(amount))
            self._set_status(self._amount_status, "")
        except ValueError as exc:
            self._upper_output.clear()
            self._set_status(self._amount_status, str(exc))

    def _on_upper_changed(self):
        """只转换下方大写，不读取也不改写上方数字及结果。"""
        text = self._upper_input.text().strip()
        if not text:
            self._lower_output.clear()
            self._set_status(self._reverse_status, "")
            return
        try:
            amount = chinese_to_amount(text)
            value = format(amount.quantize(Decimal("0.01")), "f")
            self._lower_output.setText(value)
            self._set_status(self._reverse_status, "")
        except ValueError as exc:
            self._set_status(self._reverse_status, str(exc))
            self._lower_output.clear()

    def _copy_upper(self):
        self._copy_result(self._upper_output, "已复制中文大写")

    def _copy_lower(self):
        self._copy_result(self._lower_output, "已复制小写金额")

    def _copy_result(self, field, message):
        """空结果不覆盖剪贴板中的内容。"""
        if field.text().strip():
            QApplication.clipboard().setText(field.text())
            self._show_copy_toast(message)

    def _show_copy_toast(self, message):
        self._copy_toast_token += 1
        token = self._copy_toast_token
        self._copy_toast.setText(message)
        if self._copy_toast_tick is None:
            self._copy_toast_tick = QWidget(self._copy_toast)
            self._copy_toast_tick.setObjectName("copy_toast_tick")
            self._copy_toast_tick.setFixedSize(8, 8)
            self._copy_toast_tick.setStyleSheet(
                "QWidget#copy_toast_tick{background:#107C10;border-radius:4px;}"
            )
        self._copy_toast_tick.show()
        self._copy_toast.adjustSize()
        self._copy_toast_tick.move(12, (self._copy_toast.height() - 8) // 2)
        self._copy_toast.adjustSize()
        self._copy_toast.raise_()
        self._copy_toast.setGraphicsEffect(QGraphicsOpacityEffect(self._copy_toast))
        self._copy_toast.graphicsEffect().setOpacity(0.0)
        self._copy_toast.setVisible(True)
        self._position_copy_toast()
        fade_in = QPropertyAnimation(self._copy_toast.graphicsEffect(), b"opacity", self)
        fade_in.setDuration(160)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)
        fade_in.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
        self._copy_toast_timer.start(1800)
        self._copy_toast_token = token

    def _position_copy_toast(self):
        if not hasattr(self, "_copy_toast"):
            return
        self._copy_toast.move(
            max(16, (self.width() - self._copy_toast.width()) // 2),
            14,
        )

    def _hide_copy_toast(self):
        if not self._copy_toast.isVisible():
            return
        token = self._copy_toast_token
        fade_out = QPropertyAnimation(self._copy_toast.graphicsEffect(), b"opacity", self)
        fade_out.setDuration(220)
        fade_out.setStartValue(self._copy_toast.graphicsEffect().opacity())
        fade_out.setEndValue(0.0)
        fade_out.finished.connect(
            lambda: self._finish_hide_copy_toast(token)
        )
        fade_out.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def _finish_hide_copy_toast(self, token):
        if token == self._copy_toast_token:
            self._copy_toast.setVisible(False)

    def hideEvent(self, event):
        """切换工具页面时立即结束轻提示，避免回页后残留。"""
        if hasattr(self, "_copy_toast_timer"):
            self._copy_toast_timer.stop()
            self._copy_toast.setVisible(False)
        super().hideEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_copy_toast()

    @staticmethod
    def _set_status(label, message):
        label.setText(message)
        label.setProperty("toolTone", "error" if message else "")
        label.style().unpolish(label)
        label.style().polish(label)
        label.update()


# ============================================================
class ChecksumTool(QWidget):
    def __init__(self):
        super().__init__()
        self._build()

    def _build(self):
        import hashlib
        self._hashlib = hashlib

        body = _tool_page(
            self,
            "校验计算",
            "一次计算 CRC、XOR、累加和以及常用摘要校验值。",
        )

        # 输入模式: 文本 / HEX
        input_card = ToolCard(
            "输入数据", "切换文本 / HEX 模式后会重新计算全部结果")
        mode_row = QHBoxLayout()
        mode_row.setSpacing(SPACE_SM)
        mode_row.addWidget(_field_label("输入模式"))
        self._cs_mode = QComboBox()
        self._cs_mode.addItems(["文本", "HEX"])
        self._cs_mode.currentIndexChanged.connect(self._calc_all)
        self._cs_mode.setFixedWidth(110)
        mode_row.addWidget(self._cs_mode)
        mode_row.addStretch()
        mode_row.addWidget(_hint_label("HEX 示例：01 02 0A FF"))
        input_card.body.addLayout(mode_row)

        # 输入
        self._cs_input = QPlainTextEdit()
        self._cs_input.setPlaceholderText("输入要计算校验值的数据...")
        _code_editor(self._cs_input)
        self._cs_input.setMinimumHeight(116)
        self._cs_input.setMaximumHeight(160)
        self._cs_input.textChanged.connect(self._calc_all)
        input_card.body.addWidget(self._cs_input)
        input_card.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        body.addWidget(input_card)

        # 结果网格
        result_card = ToolCard(
            "校验结果", "结果统一使用大写十六进制；哈希值可横向滚动查看")
        result_card.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        grid = QGridLayout()
        grid.setHorizontalSpacing(SPACE_SM)
        grid.setVerticalSpacing(SPACE_SM)

        checks = [
            ("CRC16 (Modbus)", self._crc16_modbus, 0, 0),
            ("CRC16 (CCITT)", self._crc16_ccitt, 0, 1),
            ("CRC32", self._crc32, 0, 2),
            ("XOR", self._xor8, 1, 0),
            ("累加和 (8bit)", self._sum8, 1, 1),
            ("累加和 (16bit)", self._sum16, 1, 2),
            ("MD5", self._md5, 2, 0),
            ("SHA1", self._sha1, 2, 1),
            ("SHA256", self._sha256, 2, 2),
        ]

        self._cs_results = {}
        for label, _func, r, c in checks:
            metric = QFrame()
            metric.setObjectName("toolMetric")
            metric_lo = QVBoxLayout(metric)
            metric_lo.setContentsMargins(12, 8, 12, 9)
            metric_lo.setSpacing(3)
            metric_lo.addWidget(_field_label(label))
            le = _result_field(QLineEdit())
            le.setFont(QFont("Consolas", 12))
            le.setPlaceholderText("—")
            metric_lo.addWidget(le)
            grid.addWidget(metric, r, c)
            self._cs_results[label] = le

        for column in range(3):
            grid.setColumnStretch(column, 1)
        result_card.body.addLayout(grid)
        result_card.body.addStretch()
        body.addWidget(result_card)
        body.addStretch()

    def _get_bytes(self):
        text = self._cs_input.toPlainText().strip()
        if not text:
            return None
        if self._cs_mode.currentText() == "HEX":
            try:
                return bytes.fromhex(text.replace(" ", "").replace("\n", ""))
            except Exception:
                return None
        else:
            return text.encode("utf-8")

    def _calc_all(self):
        data = self._get_bytes()
        if data is None:
            for le in self._cs_results.values():
                le.setText("" if self._cs_input.toPlainText().strip() else "")
            return

        self._cs_results["CRC16 (Modbus)"].setText(f"{self._crc16_modbus(data):04X}")
        self._cs_results["CRC16 (CCITT)"].setText(f"{self._crc16_ccitt(data):04X}")
        self._cs_results["CRC32"].setText(f"{self._crc32(data):08X}")
        self._cs_results["XOR"].setText(f"{self._xor8(data):02X}")
        self._cs_results["累加和 (8bit)"].setText(f"{self._sum8(data):02X}")
        self._cs_results["累加和 (16bit)"].setText(f"{self._sum16(data):04X}")
        self._cs_results["MD5"].setText(self._md5(data))
        self._cs_results["SHA1"].setText(self._sha1(data))
        self._cs_results["SHA256"].setText(self._sha256(data))

    # ---- CRC / XOR / SUM ----
    def _crc16_modbus(self, data):
        crc = 0xFFFF
        for b in data:
            crc ^= b
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc & 0xFFFF

    def _crc16_ccitt(self, data):
        crc = 0xFFFF
        for b in data:
            crc ^= (b << 8)
            for _ in range(8):
                if crc & 0x8000:
                    crc = ((crc << 1) ^ 0x1021) & 0xFFFF
                else:
                    crc = (crc << 1) & 0xFFFF
        return crc

    def _crc32(self, data):
        crc = 0xFFFFFFFF
        for b in data:
            crc ^= b
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ 0xEDB88320
                else:
                    crc >>= 1
        return crc ^ 0xFFFFFFFF

    def _xor8(self, data):
        result = 0
        for b in data:
            result ^= b
        return result & 0xFF

    def _sum8(self, data):
        return sum(data) & 0xFF

    def _sum16(self, data):
        return sum(data) & 0xFFFF

    # ---- Hash ----
    def _md5(self, data):
        return self._hashlib.md5(data).hexdigest().upper()

    def _sha1(self, data):
        return self._hashlib.sha1(data).hexdigest().upper()

    def _sha256(self, data):
        return self._hashlib.sha256(data).hexdigest().upper()


# ============================================================
#  工具箱 / 硬件信息工具
# ============================================================
class SystemInfoTool(QWidget):
    """工具箱页 -- 左侧分类导航(硬件信息 + 外置工具) + 右侧内嵌内容, 无弹窗"""

    def __init__(
            self, base_dir=None, include_capture=False,
            page_title="网络检测",
            page_subtitle="检查主机连通性、开放端口和局域网内存活设备。"):
        super().__init__()
        self._base_dir = base_dir
        self._tools = []
        if base_dir:
            self._tools = toolbox.load_manifest(os.path.join(base_dir, "tools"))
        self._build()

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 左侧导航栏
        nav = QFrame()
        nav.setFixedWidth(176)
        nav.setStyleSheet(
            "QFrame{background:#F7F8FA;border-right:1px solid #E5E7EB;}"
        )
        nav_lo = QVBoxLayout(nav)
        nav_lo.setContentsMargins(12, 18, 12, 16)
        nav_lo.setSpacing(6)

        title = QLabel("工具箱")
        title.setStyleSheet(
            "color:#111827;font-size:16px;font-weight:700;"
            "background:transparent;padding:0 8px 12px 8px;"
        )
        nav_lo.addWidget(title)

        # 硬件信息固定为第一个分类
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._btn_hw = self._make_nav_btn("硬件信息")
        self._nav_group.addButton(self._btn_hw)
        self._btn_hw.setChecked(True)
        nav_lo.addWidget(self._btn_hw)

        # 外置工具分类 (保持清单出现顺序; 优先使用清单显式声明的分类)
        self._categories = toolbox.load_categories(
            os.path.join(self._base_dir, "tools")) if self._base_dir else None
        if self._categories is None:
            self._categories = []
        for t in self._tools:
            c = toolbox._norm_category(t)
            if c not in self._categories:
                self._categories.append(c)

        self._nav_btns = {"硬件信息": self._btn_hw}
        for c in self._categories:
            btn = self._make_nav_btn(c)
            self._nav_group.addButton(btn)
            nav_lo.addWidget(btn)
            self._nav_btns[c] = btn

        nav_lo.addStretch()
        root.addWidget(nav)

        # 右侧内容区
        self._stack = QStackedWidget()
        self._hw_page = HardwareInfoPage()
        self._stack.addWidget(self._hw_page)

        self._pages = {"硬件信息": self._hw_page}
        tools_dir = os.path.join(self._base_dir, "tools") if self._base_dir else ""
        for c in self._categories:
            page = toolbox.build_category_page(c, self._tools, tools_dir)
            self._stack.addWidget(page)
            self._pages[c] = page
        root.addWidget(self._stack, stretch=1)

        self._btn_hw.clicked.connect(lambda: self._show("硬件信息"))
        for c in self._categories:
            btn = self._nav_btns[c]
            btn.clicked.connect(lambda checked=False, cat=c: self._show(cat))

    def _show(self, cat):
        # 点击当前已选中的分类时保持高亮
        btn = self._nav_btns.get(cat)
        if btn is not None:
            btn.setChecked(True)
        self._stack.setCurrentWidget(self._pages.get(cat, self._hw_page))

    @staticmethod
    def _make_nav_btn(text):
        btn = QPushButton(text)
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            "QPushButton{color:#374151;background:transparent;border:none;"
            "border-radius:6px;padding:9px 10px;font-size:13px;text-align:left;}"
            "QPushButton:hover{background:#EBEEF3;}"
            "QPushButton:checked{background:#0078D4;color:#FFFFFF;}"
        )
        return btn


class HardwareInfoPage(QWidget):
    """右侧硬件信息内容 -- 内嵌展示, 不弹窗

    硬件采集要调 PowerShell (CIM 查询, 约 0.8s), 绝不能放在 GUI 线程里同步跑,
    否则窗口打开后会僵住 2-3 秒。这里沿用 NetworkTool 的做法: 后台线程采集 +
    队列回传, GUI 线程用定时器取结果, 期间界面可正常响应。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue = None
        self._poll = None
        self._build()

    def _build(self):
        body = _tool_page(
            self,
            "硬件信息",
            "查看本机型号、操作系统、运行时间和主要硬件配置。",
        )

        # 顶部三卡片
        cards = QHBoxLayout()
        cards.setSpacing(SPACE_MD)
        self._card_model, self._val_model = self._make_card("🖥️", "型号信息", "正在读取...")
        self._card_os, self._val_os = self._make_card("🪟", "系统信息", "正在读取...")
        self._card_uptime, self._val_uptime = self._make_card("⏱️", "运行时间", "正在读取...")
        cards.addWidget(self._card_model, stretch=1)
        cards.addWidget(self._card_os, stretch=1)
        cards.addWidget(self._card_uptime, stretch=1)
        body.addLayout(cards)

        detail_card = ToolCard(
            "设备详情", "处理器、主板、内存、显卡、磁盘和网络设备")
        self._hardware_state = _badge("读取中", "primary")
        detail_card.add_header_widget(self._hardware_state)

        detail_frame = QFrame()
        self._detail_lo = QVBoxLayout(detail_frame)
        self._detail_lo.setContentsMargins(2, 2, 8, 2)
        self._detail_lo.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(detail_frame)
        detail_card.body.addWidget(scroll, stretch=1)
        body.addWidget(detail_card, stretch=1)

        self._load_timer = QTimer(self)
        self._load_timer.setSingleShot(True)
        self._load_timer.timeout.connect(self._load)
        self._load_timer.start(0)

    def _make_card(self, icon, title, value):
        card = ToolCard()
        lo = card.body
        lo.setSpacing(5)

        head = QHBoxLayout()
        head.setSpacing(7)
        ic = QLabel(icon)
        ic.setFixedWidth(26)
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t = QLabel(title)
        t.setObjectName("toolFieldLabel")
        head.addWidget(ic)
        head.addWidget(t)
        head.addStretch()
        lo.addLayout(head)

        val = QLabel(value)
        val.setWordWrap(True)
        val.setObjectName("toolCardTitle")
        val.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        lo.addWidget(val)
        return card, val

    def _add_detail(self, name, value):
        row_widget = QWidget()
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(8, 9, 8, 9)
        row.setSpacing(SPACE_MD)
        row.setAlignment(Qt.AlignmentFlag.AlignTop)
        n = QLabel(name)
        n.setObjectName("toolFieldLabel")
        n.setFixedWidth(72)
        n.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        row.addWidget(n)

        text = self._join(value)
        v = QLabel(text)
        v.setObjectName("toolCardTitle")
        v.setWordWrap(True)
        v.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        v.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(v, stretch=1)
        self._detail_lo.addWidget(row_widget)
        divider = QFrame()
        divider.setObjectName("toolDivider")
        divider.setFixedHeight(1)
        self._detail_lo.addWidget(divider)

    @staticmethod
    def _join(value):
        if isinstance(value, list):
            items = [str(x) for x in value if x is not None and str(x).strip()]
            return "\n".join(items) if items else "未检测到"
        if value is None or not str(value).strip():
            return "未检测到"
        return str(value)

    def _load(self):
        """后台线程采集, GUI 线程只负责取结果填界面 (采集期间界面不卡)"""
        if self._poll is not None:
            return
        import queue as _queue
        import threading

        self._queue = _queue.Queue()

        def worker():
            try:
                self._queue.put(("ok", hardware.collect_hardware_info()))
            except Exception as e:
                self._queue.put(("err", str(e)))

        # 守护线程: 采集未完成时退出程序也不会阻塞或报错
        threading.Thread(target=worker, daemon=True).start()
        self._poll = QTimer(self)
        self._poll.timeout.connect(self._check_queue)
        self._poll.start(80)

    def _check_queue(self):
        if self._queue is None or self._queue.empty():
            return
        kind, payload = self._queue.get()
        self._poll.stop()
        if kind == "ok":
            self._on_collected(payload)
        else:
            self._on_failed(payload)

    def _on_failed(self, message):
        self._val_model.setText("—")
        self._val_os.setText("—")
        self._val_uptime.setText("—")
        self._hardware_state.setText("读取失败")
        _set_tone(self._hardware_state, "error")
        self._add_detail("错误", message)
        self._detail_lo.addStretch()

    def _on_collected(self, info):
        self._val_model.setText(str(info.get("model") or "未检测到"))
        self._val_os.setText(str(info.get("os") or "未检测到"))
        self._hardware_state.setText("已读取")
        _set_tone(self._hardware_state, "success")

        # 运行时间基于开机时刻实时刷新
        up_secs = info.get("uptime_seconds")
        if up_secs is not None:
            self._boot_epoch = time.time() - float(up_secs)
            self._val_uptime.setText(self._fmt_uptime(up_secs))
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._tick)
            # 用 500ms 刷新: 即使某次 tick 被事件循环延后, 也能在下一个周期内
            # 快速追上, 避免显示出现"卡顿后跳 2 秒"的观感
            self._timer.start(500)
        else:
            self._val_uptime.setText(str(info.get("uptime") or "未检测到"))

        self._add_detail("处理器", info.get("cpu"))
        self._add_detail("主板", info.get("mainboard"))
        self._add_detail("内存", self._format_ram(info))
        self._add_detail("显卡", info.get("gpus"))
        self._add_detail("显示器", info.get("monitors"))
        self._add_detail("磁盘", info.get("disks"))
        self._add_detail("声卡", info.get("sounds"))
        self._add_detail("网卡", info.get("nics"))
        # 注册表部分正常但 CIM 查询失败时, 说明一下原因 (否则只会显示一片"未检测到")
        if info.get("wmi_error"):
            self._add_detail("提示", "部分信息读取失败：" + str(info["wmi_error"]))
        self._detail_lo.addStretch()

    def _tick(self):
        if hasattr(self, "_boot_epoch"):
            self._val_uptime.setText(self._fmt_uptime(time.time() - self._boot_epoch))

    @staticmethod
    def _fmt_uptime(secs):
        secs = max(0, int(round(float(secs))))
        days, rem = divmod(secs, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, seconds = divmod(rem, 60)
        return "{}天{}小时{}分钟{}秒".format(days, hours, minutes, seconds)

    @staticmethod
    def _format_ram(info):
        maker = info.get("ram_maker")
        ram = info.get("ram")
        speed = info.get("ram_speed")
        detail = info.get("ram_detail")
        parts = []
        if maker:
            parts.append(str(maker).strip())
        if ram:
            parts.append(str(ram).strip())
        if speed:
            parts.append("{}MHz".format(speed))
        if detail:
            parts.append("( {} )".format(detail))
        return " ".join(parts) if parts else None

    def cleanup(self):
        """停止硬件采集轮询和运行时间定时器。"""
        self._load_timer.stop()
        if self._poll is not None:
            self._poll.stop()
        if hasattr(self, "_timer"):
            self._timer.stop()


# ============================================================
#  Ping + 端口扫描工具
# ============================================================
_INVALID_MODEL_INDEX = QModelIndex()


class CaptureTableModel(QAbstractTableModel):
    """Compact packet-summary model for high-rate capture display."""

    HEADERS = ["序号", "时间", "源地址", "目标地址", "协议", "长度", "信息"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._packets = []

    def rowCount(self, parent=_INVALID_MODEL_INDEX):
        return 0 if parent.isValid() else len(self._packets)

    def columnCount(self, parent=_INVALID_MODEL_INDEX):
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if (
            role == Qt.ItemDataRole.DisplayRole
            and orientation == Qt.Orientation.Horizontal
            and 0 <= section < len(self.HEADERS)
        ):
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._packets):
            return None
        packet = self._packets[index.row()]
        values = (
            str(packet.get("display_number", packet["number"])),
            self.format_time(packet["time"]),
            packet["source"],
            packet["destination"],
            packet["protocol"],
            str(packet["length"]),
            packet["info"],
        )
        if role == Qt.ItemDataRole.DisplayRole:
            return values[index.column()]
        if role == Qt.ItemDataRole.ToolTipRole and index.column() == 6:
            return values[index.column()]
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if index.column() in (0, 1, 5):
                return int(
                    Qt.AlignmentFlag.AlignCenter)
            return int(
                Qt.AlignmentFlag.AlignLeft
                | Qt.AlignmentFlag.AlignVCenter)
        return None

    @staticmethod
    def format_time(value):
        return "{:.6f}".format(value)

    def max_display_number(self):
        return max(
            (
                int(packet.get("display_number", packet["number"]))
                for packet in self._packets
            ),
            default=0,
        )

    def append_packets(self, packets):
        if not packets:
            return
        first = len(self._packets)
        self.beginInsertRows(
            QModelIndex(), first, first + len(packets) - 1)
        self._packets.extend(packets)
        self.endInsertRows()

    def clear(self):
        if not self._packets:
            return
        self.beginResetModel()
        self._packets.clear()
        self.endResetModel()

    def packet_at(self, row):
        if 0 <= row < len(self._packets):
            return self._packets[row]
        return None


class CapturePacketView(QWidget):
    """Packet table with a vertical scrollbar aligned below the header."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.table = QTableView()
        self.table.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        header = self.table.horizontalHeader()
        header.setFixedHeight(TABLE_ROW_HEIGHT)
        layout.addWidget(self.table, 1)

        scroll_host = QWidget()
        scroll_layout = QVBoxLayout(scroll_host)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(0)
        scroll_layout.addSpacing(TABLE_ROW_HEIGHT)
        self.scrollbar = QScrollBar(Qt.Orientation.Vertical)
        self.scrollbar.setFixedWidth(8)
        self.scrollbar.setStyleSheet(
            "QScrollBar:vertical{background:#F3F4F6;width:8px;"
            "margin:0;border:none;border-radius:4px;}"
            "QScrollBar::handle:vertical{background:#C7CBD1;"
            "min-height:30px;border-radius:4px;}"
            "QScrollBar::handle:vertical:hover{background:#AEB4BC;}"
            "QScrollBar::add-line:vertical,"
            "QScrollBar::sub-line:vertical{height:0;border:none;"
            "background:transparent;}"
            "QScrollBar::add-page:vertical,"
            "QScrollBar::sub-page:vertical{background:transparent;}"
        )
        self.scrollbar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        scroll_layout.addWidget(self.scrollbar, 1)
        layout.addWidget(scroll_host)

        internal = self.table.verticalScrollBar()
        internal.rangeChanged.connect(self._sync_range)
        internal.valueChanged.connect(self.scrollbar.setValue)
        self.scrollbar.valueChanged.connect(internal.setValue)
        self.scrollbar.hide()

    def _sync_range(self, minimum, maximum):
        internal = self.table.verticalScrollBar()
        self.scrollbar.setRange(minimum, maximum)
        self.scrollbar.setPageStep(internal.pageStep())
        self.scrollbar.setSingleStep(internal.singleStep())
        self.scrollbar.setVisible(maximum > minimum)


class NetworkTool(QWidget):
    """Ping / 抓包 / 端口扫描 / 网段扫描工具。"""

    MAX_PAUSED_PACKET_BYTES = 16 * 1024 * 1024
    COMMON_PORTS = [
        21, 22, 23, 25, 53, 80, 110, 135, 139, 143, 443, 445,
        993, 995, 1433, 1521, 3306, 3389, 5432, 5900, 6379,
        8000, 8080, 8443, 8888, 9000, 9200, 27017
    ]

    def __init__(
            self, base_dir=None, include_capture=False,
            page_title="网络检测",
            page_subtitle="检查主机连通性、开放端口和局域网内存活设备。"):
        super().__init__()
        import queue as _queue
        import threading
        self._queue = _queue.Queue()
        self._alive_ips = []
        self._open_ports = []
        self._pending = 0
        self._scan_kind = ""
        self._scan_running = False
        self._scan_run = 0
        self._scan_cancel = threading.Event()
        self._executor = None
        self._ping_proc = None
        self._base_dir = base_dir or os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))
        self._include_capture = bool(include_capture)
        self._page_title = str(page_title)
        self._page_subtitle = str(page_subtitle)
        self._capture_engine_dir, self._capture_npcap_dir = (
            capture_resource_dirs(self._base_dir))
        self._capture_proc = None
        self._capture_file_proc = None
        self._capture_detail_proc = None
        self._capture_interface_proc = None
        self._capture_interface_recheck_after_failure = False
        self._capture_temp_path = ""
        self._capture_save_path = ""
        self._capture_running = False
        self._capture_stopping = False
        self._capture_paused = False
        self._capture_buffer = []
        self._capture_paused_packets = []
        self._capture_paused_bytes = 0
        self._capture_session_frame_base = 0
        self._capture_selected_frame = None
        self._capture_selected_path = ""
        self._capture_detail_cache = OrderedDict()
        self._capture_detail_timed_out_key = None
        self._capture_detail_timeout_timer = QTimer(self)
        self._capture_detail_timeout_timer.setSingleShot(True)
        self._capture_detail_timeout_timer.timeout.connect(
            self._on_capture_detail_timeout)
        self._capture_count = 0
        self._capture_bytes = 0
        self._capture_dropped = 0
        self._capture_display_records = 0
        self._capture_display_bytes = 0
        self._capture_waiting_for_npcap = False
        self._capture_npcap_installer = None
        self._capture_npcap_monitor_timer = QTimer(self)
        self._capture_npcap_monitor_timer.setInterval(250)
        self._capture_npcap_monitor_timer.timeout.connect(
            self._monitor_npcap_installer)
        self._build()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._drain_queue)
        self._timer.start(100)

    def _build(self):
        body = _tool_page(
            self,
            self._page_title,
            self._page_subtitle,
        )

        self._network_tabs = QTabWidget()
        self._network_tabs.setObjectName("toolTabs")
        self._network_tabs.setDocumentMode(True)
        self._network_tabs.addTab(self._build_ping_page(), "Ping")
        if self._include_capture:
            self._network_tabs.addTab(
                self._build_capture_page(), "抓包分析")
        self._network_tabs.addTab(self._build_port_page(), "端口扫描")
        self._network_tabs.addTab(self._build_lan_page(), "网段扫描")
        if self._include_capture:
            self._network_tabs.currentChanged.connect(
                self._on_network_tab_changed)
        body.addWidget(self._network_tabs, stretch=1)

    # ---------- Ping ----------
    def _build_ping_page(self):
        w = QWidget()
        w.setObjectName("toolTabPage")
        lo = QVBoxLayout(w)
        lo.setContentsMargins(SPACE_MD, SPACE_MD, SPACE_MD, SPACE_MD)
        lo.setSpacing(SPACE_MD)

        control = ToolCard(
            "Ping 目标", "持续检测目标连通性；再次点击按钮即可停止")
        row = QHBoxLayout()
        row.setSpacing(SPACE_SM)
        row.addWidget(_field_label("目标主机"))
        self._ping_target = QLineEdit()
        self._ping_target.setPlaceholderText("IP 或域名，如 192.168.1.1 或 baidu.com")
        self._ping_target.returnPressed.connect(self._start_ping)
        row.addWidget(self._ping_target, stretch=1)
        self._btn_ping = _primary_button("Ping")
        self._btn_ping.setFixedWidth(96)
        self._btn_ping.clicked.connect(self._start_ping)
        row.addWidget(self._btn_ping)
        control.body.addLayout(row)
        lo.addWidget(control)

        self._ping_output = QPlainTextEdit()
        _code_editor(self._ping_output, readonly=True)
        self._ping_output.document().setMaximumBlockCount(5000)
        self._ping_output.setPlaceholderText("Ping 输出会实时显示在这里")
        output = ToolCard("实时输出", "输出内容可直接选择复制")
        output.add_header_widget(_badge("持续模式"))
        output.body.addWidget(self._ping_output, stretch=1)
        lo.addWidget(output, stretch=1)
        return w

    def _start_ping(self):
        import threading, subprocess
        # 已在持续 ping 中, 再次点击则停止
        if self._ping_proc is not None:
            self._stop_ping()
            return
        target = self._ping_target.text().strip()
        if not target:
            return
        self._ping_output.appendPlainText(">>> Ping {} ...".format(target))
        self._btn_ping.setText("停止")

        # Windows 下隐藏 ping.exe 的控制台窗口
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        if os.name == "nt":
            cmd = ["ping", "-t", target]
        else:
            cmd = ["ping", target]
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=creationflags,
            )
        except Exception as e:
            self._ping_output.appendPlainText("启动 Ping 失败: {}".format(e))
            self._btn_ping.setText("Ping")
            return
        self._ping_proc = proc

        def reader():
            # 逐行读取, 实时回传 UI; 进程退出后发送结束事件
            try:
                for line in proc.stdout:
                    self._queue.put(("ping_line", line.rstrip("\r\n")))
            except Exception as e:
                self._queue.put(("ping_error", proc, str(e)))
            finally:
                self._queue.put(("ping_end", proc))

        threading.Thread(target=reader, daemon=True).start()

    def _stop_ping(self):
        proc = self._ping_proc
        self._ping_proc = None
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._btn_ping.setText("Ping")
        if proc is not None:
            self._ping_output.appendPlainText(">>> 已停止")

    # ---------- 抓包 ----------
    def _build_capture_page(self):
        w = QWidget()
        w.setObjectName("toolTabPage")
        lo = QVBoxLayout(w)
        lo.setContentsMargins(SPACE_MD, SPACE_MD, SPACE_MD, SPACE_MD)
        lo.setSpacing(SPACE_MD)

        control = ToolCard(
            "抓包参数", "选择网卡并设置 BPF 抓包过滤器")
        form = QGridLayout()
        form.setHorizontalSpacing(SPACE_SM)
        form.setVerticalSpacing(SPACE_SM)
        form.setColumnStretch(1, 1)

        interface_label = _field_label("网卡")
        form.addWidget(interface_label, 0, 0)
        self._capture_interface = QComboBox()
        self._capture_interface.setMinimumWidth(320)
        form.addWidget(self._capture_interface, 0, 1)
        self._btn_capture_refresh = _secondary_button("刷新网卡")
        self._btn_capture_refresh.clicked.connect(
            self._refresh_capture_interfaces)
        form.addWidget(self._btn_capture_refresh, 0, 2)
        self._btn_install_npcap = _secondary_button("安装抓包驱动")
        self._btn_install_npcap.clicked.connect(self._install_npcap)
        self._btn_install_npcap.hide()
        self._capture_driver_hint = QLabel("抓包驱动不可用")
        self._capture_driver_hint.setWordWrap(False)
        self._capture_driver_hint.setStyleSheet(
            "color: {}; font-size: 12px;".format(COLOR_DANGER))
        self._capture_driver_hint.hide()

        filter_label = _field_label("抓包过滤(BPF)")
        form.addWidget(filter_label, 1, 0)
        self._capture_filter = QLineEdit()
        self._capture_filter.setPlaceholderText(
            "可留空，例如 host 192.168.2.188 and tcp port 9090")
        self._capture_filter.setToolTip(
            "BPF 抓包过滤器，决定哪些数据包写入 pcapng 文件")
        self._capture_filter.returnPressed.connect(self._start_capture)
        form.addWidget(self._capture_filter, 1, 1, 1, 2)

        display_label = _field_label("显示过滤")
        form.addWidget(display_label, 2, 0)
        self._capture_display_filter = QLineEdit()
        self._capture_display_filter.setPlaceholderText(
            "可留空，例如 ip.addr == 192.168.2.188 && tcp.port == 9090")
        self._capture_display_filter.setToolTip(
            "Wireshark 显示过滤器，只影响页面中显示的数据包")
        self._capture_display_filter.returnPressed.connect(
            self._start_capture)
        form.addWidget(self._capture_display_filter, 2, 1, 1, 2)
        control.body.addLayout(form)

        button_row = QHBoxLayout()
        button_row.setSpacing(SPACE_SM)
        self._btn_capture_start = _primary_button("开始抓包")
        self._btn_capture_start.setFixedWidth(112)
        self._btn_capture_start.clicked.connect(self._start_capture)
        button_row.addWidget(self._btn_capture_start)
        self._btn_capture_stop = _secondary_button("停止")
        self._btn_capture_stop.setFixedWidth(88)
        self._btn_capture_stop.setEnabled(False)
        self._btn_capture_stop.clicked.connect(self._stop_capture)
        button_row.addWidget(self._btn_capture_stop)
        self._chk_capture_pause = QCheckBox("页面暂停")
        self._chk_capture_pause.toggled.connect(
            self._on_capture_pause)
        button_row.addWidget(self._chk_capture_pause)
        self._chk_capture_save = QCheckBox("保存到文件")
        self._chk_capture_save.toggled.connect(
            self._on_capture_save_toggle)
        button_row.addWidget(self._chk_capture_save)
        self._lbl_capture_save_rule = _save_rule_label()
        self._btn_capture_clear = _secondary_button("清空列表")
        self._btn_capture_clear.clicked.connect(self._clear_capture)
        button_row.addWidget(self._btn_capture_clear)
        self._btn_capture_save = _secondary_button(
            "保存 pcapng", "http_save.svg")
        self._btn_capture_save.clicked.connect(self._save_capture)
        button_row.addWidget(self._btn_capture_save)
        button_row.addStretch()
        button_row.addWidget(
            self._capture_driver_hint, 0,
            Qt.AlignmentFlag.AlignVCenter)
        button_row.addWidget(self._btn_install_npcap)
        self._capture_status = _badge("未开始")
        button_row.addWidget(self._capture_status)
        control.body.addLayout(button_row)
        control.body.addWidget(self._lbl_capture_save_rule)
        lo.addWidget(control)

        self._capture_model = CaptureTableModel(self)
        self._capture_view = CapturePacketView()
        self._capture_table = self._capture_view.table
        self._capture_table.setModel(self._capture_model)
        apply_data_table_style(self._capture_table)
        self._capture_table.setStyleSheet(
            HTTP_TABLE_STYLE.replace("QTableWidget", "QTableView"))
        self._capture_table.setWordWrap(False)
        self._capture_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self._capture_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._capture_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self._capture_table.setAlternatingRowColors(False)
        header = self._capture_table.horizontalHeader()
        header.setMinimumHeight(TABLE_ROW_HEIGHT)
        self._capture_table.verticalHeader().setDefaultSectionSize(
            TABLE_ROW_HEIGHT)
        self._capture_table.verticalHeader().setMinimumSectionSize(
            TABLE_ROW_HEIGHT)
        header.setStretchLastSection(True)
        for column in (4, 5):
            header.setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self._capture_table.setColumnWidth(
            1,
            max(
                96,
                self._capture_table.fontMetrics().horizontalAdvance(
                    "000000.000000") + 28,
            ),
        )
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self._capture_table.setColumnWidth(0, 60)
        for column in (2, 3):
            self._capture_table.setColumnWidth(column, 170)
        self._capture_table.selectionModel().selectionChanged.connect(
            self._on_capture_selection_changed)
        table_card = ToolCard(
            "数据包", "点击数据包查看协议详情和十六进制内容")
        self._btn_capture_detail_toggle = _secondary_button("展开详情")
        self._btn_capture_detail_toggle.setCheckable(True)
        self._btn_capture_detail_toggle.setFixedHeight(28)
        self._btn_capture_detail_toggle.toggled.connect(
            self._set_capture_detail_visible)
        table_card.add_header_widget(self._btn_capture_detail_toggle)
        table_card.body.addWidget(self._capture_view, 1)

        self._capture_detail = QPlainTextEdit()
        _code_editor(self._capture_detail, readonly=True)
        self._capture_detail.setPlaceholderText(
            "选择数据包后显示协议详情")
        detail_card = ToolCard("数据包详情")
        self._capture_detail_card = detail_card
        detail_card.body.addWidget(self._capture_detail, 1)

        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(7)
        splitter.addWidget(table_card)
        splitter.addWidget(detail_card)
        splitter.setSizes([520, 260])
        lo.addWidget(splitter, 1)
        self._capture_splitter = splitter
        self._set_capture_detail_visible(False)
        return w

    def _set_capture_detail_visible(self, visible):
        visible = bool(visible)
        self._capture_detail_card.setVisible(visible)
        self._btn_capture_detail_toggle.blockSignals(True)
        self._btn_capture_detail_toggle.setChecked(visible)
        self._btn_capture_detail_toggle.blockSignals(False)
        self._btn_capture_detail_toggle.setText(
            "收起详情" if visible else "展开详情")
        if visible:
            self._capture_splitter.setSizes([520, 260])

    def _on_network_tab_changed(self, index):
        if index == 1 and self._capture_interface.count() == 0:
            self._refresh_capture_interfaces()

    def _capture_program(self):
        return str(self._capture_engine_dir / "tshark.exe")

    def _capture_engine_ready(self):
        return (
            (self._capture_engine_dir / "tshark.exe").is_file()
            and (self._capture_engine_dir / "dumpcap.exe").is_file()
        )

    def _set_capture_status(self, text, tone="default"):
        self._capture_status.setText(text)
        _set_tone(self._capture_status, tone)
        self._capture_status.show()

    def _show_capture_driver_hint(self, text):
        self._capture_driver_hint.setText(text)
        self._capture_driver_hint.show()
        self._capture_status.hide()

    def _refresh_capture_interfaces(self):
        self._start_capture_interface_refresh()

    def _recheck_capture_driver_after_failure(self):
        self._start_capture_interface_refresh(after_capture_failure=True)

    def _start_capture_interface_refresh(
            self, after_capture_failure=False):
        if (
            self._capture_interface_proc is not None
            and self._capture_interface_proc.state()
            != QProcess.ProcessState.NotRunning
        ):
            return
        self._capture_interface_recheck_after_failure = bool(
            after_capture_failure)
        self._capture_interface.clear()
        self._btn_capture_refresh.setEnabled(False)
        self._btn_capture_start.setEnabled(False)
        if not self._capture_waiting_for_npcap:
            self._btn_install_npcap.hide()
            self._capture_driver_hint.hide()
        if not self._capture_engine_ready():
            self._capture_interface_recheck_after_failure = False
            self._set_capture_status("抓包引擎缺失", "error")
            show_warning(
                self, "抓包引擎缺失",
                "未找到内置的 TShark/Dumpcap 运行文件。")
            return
        if self._capture_waiting_for_npcap:
            self._show_capture_driver_hint("正在检测抓包驱动")
        else:
            self._set_capture_status("正在检测网卡", "primary")
        process = QProcess(self)
        process.setWorkingDirectory(str(self._capture_engine_dir))
        process.setProcessChannelMode(
            QProcess.ProcessChannelMode.SeparateChannels)
        process.finished.connect(
            lambda code, _status: self._on_capture_interfaces_finished(
                process, code))
        process.errorOccurred.connect(
            lambda _error: self._on_capture_interfaces_error(process))
        self._capture_interface_proc = process
        process.start(self._capture_program(), ["-D"])

    def _on_capture_interfaces_finished(self, process, exit_code):
        recheck_after_failure = (
            self._capture_interface_recheck_after_failure)
        self._capture_interface_recheck_after_failure = False
        stdout = bytes(process.readAllStandardOutput()).decode(
            "utf-8", errors="replace")
        stderr = bytes(process.readAllStandardError()).decode(
            "utf-8", errors="replace")
        process.deleteLater()
        if self._capture_interface_proc is process:
            self._capture_interface_proc = None
        interfaces = parse_tshark_interfaces(stdout)
        if exit_code == 0 and interfaces:
            self._capture_waiting_for_npcap = False
            self._capture_driver_hint.hide()
            for interface in interfaces:
                self._capture_interface.addItem(
                    "{}  ({})".format(
                        interface["name"], interface["device"]),
                    interface["device"],
                )
            if recheck_after_failure:
                self._set_capture_status("抓包异常结束", "error")
            else:
                self._set_capture_status(
                    "已发现 {} 个网卡".format(len(interfaces)),
                    "success")
            self._btn_capture_refresh.setEnabled(True)
            self._btn_capture_start.setEnabled(True)
            self._btn_install_npcap.setEnabled(True)
            self._btn_install_npcap.setText("安装抓包驱动")
            self._btn_install_npcap.hide()
            return
        message = stderr.strip() or "未发现可用网卡"
        self._show_capture_driver_hint(
            "抓包驱动已卸载或不可用"
            if recheck_after_failure else "抓包驱动不可用")
        self._capture_detail.setPlainText(message)
        self._btn_capture_refresh.setEnabled(False)
        self._btn_capture_start.setEnabled(False)
        if npcap_installer_path(self._base_dir) is not None:
            self._btn_install_npcap.show()
            self._btn_install_npcap.setEnabled(True)
            self._btn_install_npcap.setText("安装抓包驱动")

    def _on_capture_interfaces_error(self, process):
        recheck_after_failure = (
            self._capture_interface_recheck_after_failure)
        self._capture_interface_recheck_after_failure = False
        if self._capture_interface_proc is process:
            self._capture_interface_proc = None
        process.deleteLater()
        if recheck_after_failure:
            self._show_capture_driver_hint("抓包驱动已卸载或不可用")
        else:
            self._set_capture_status("抓包引擎启动失败", "error")
        self._btn_capture_refresh.setEnabled(False)
        self._btn_capture_start.setEnabled(False)

    def _install_npcap(self):
        installer = launch_npcap_installer(self._base_dir)
        if installer is None:
            show_error(
                self, "无法启动安装程序",
                "未找到 Npcap 安装文件，或以管理员身份启动失败。")
            return
        self._capture_npcap_installer = installer
        self._capture_waiting_for_npcap = True
        self._btn_install_npcap.setEnabled(False)
        self._btn_install_npcap.setText("等待安装驱动")
        self._btn_capture_refresh.setEnabled(False)
        self._btn_capture_start.setEnabled(False)
        self._show_capture_driver_hint(
            "请完成驱动安装，完成后自动检测")
        self._capture_npcap_monitor_timer.start()

    def _monitor_npcap_installer(self):
        installer = self._capture_npcap_installer
        if installer is None:
            self._capture_npcap_monitor_timer.stop()
            return
        if installer.is_running():
            return
        self._capture_npcap_monitor_timer.stop()
        installer.close()
        self._capture_npcap_installer = None
        self._capture_waiting_for_npcap = False
        self._btn_install_npcap.setEnabled(True)
        self._btn_install_npcap.setText("安装抓包驱动")
        self._refresh_capture_interfaces()

    def _start_capture(self):
        if self._capture_running:
            return
        if not self._capture_engine_ready():
            show_warning(
                self, "抓包引擎缺失",
                "未找到内置的 TShark/Dumpcap 运行文件。")
            return
        device = self._capture_interface.currentData()
        if not device:
            self._refresh_capture_interfaces()
            return
        capture_filter = self._capture_filter.text().strip()
        display_filter = self._capture_display_filter.text().strip()
        if self._chk_capture_save.isChecked():
            if not self._capture_save_path:
                show_warning(
                    self, "未选择保存文件",
                    "请先开启“保存到文件”并选择 pcapng 路径。")
                return
            path = self._capture_save_path
        else:
            try:
                fd, path = tempfile.mkstemp(
                    prefix="anhutoolbox_capture_", suffix=".pcapng")
                os.close(fd)
            except OSError as exc:
                show_error(self, "无法创建抓包文件", str(exc))
                return
        self._capture_temp_path = path
        args = build_tshark_capture_args(
            device,
            path,
            capture_filter=capture_filter,
            display_filter=display_filter,
            write_output=not bool(display_filter),
        )
        self._capture_file_proc = None
        if display_filter:
            file_process = QProcess(self)
            file_process.setWorkingDirectory(str(self._capture_engine_dir))
            file_process.setProcessChannelMode(
                QProcess.ProcessChannelMode.SeparateChannels)
            file_process.readyReadStandardError.connect(
                lambda: self._on_capture_file_stderr(file_process))
            file_process.finished.connect(
                lambda code, _status: self._on_capture_file_finished(
                    file_process, code))
            file_process.errorOccurred.connect(
                lambda _error: self._on_capture_file_error(file_process))
            self._capture_file_proc = file_process
            file_process.start(
                str(self._capture_engine_dir / "dumpcap.exe"),
                build_dumpcap_capture_args(
                    device, path, capture_filter),
            )
        process = QProcess(self)
        process.setWorkingDirectory(str(self._capture_engine_dir))
        process.setProcessChannelMode(
            QProcess.ProcessChannelMode.SeparateChannels)
        process.readyReadStandardOutput.connect(
            lambda: self._on_capture_stdout(process))
        process.readyReadStandardError.connect(
            lambda: self._on_capture_stderr(process))
        process.finished.connect(
            lambda code, _status: self._on_capture_finished(
                process, code))
        process.errorOccurred.connect(
            lambda _error: self._on_capture_process_error(process))
        self._capture_proc = process
        self._capture_running = True
        self._capture_stopping = False
        self._capture_session_frame_base = (
            self._capture_model.max_display_number())
        self._capture_stdout_buffer = ""
        self._capture_stderr_buffer = ""
        self._capture_file_stderr_buffer = ""
        self._capture_buffer.clear()
        self._btn_capture_start.setEnabled(False)
        self._btn_capture_stop.setEnabled(True)
        self._btn_capture_clear.setEnabled(False)
        self._btn_capture_refresh.setEnabled(False)
        self._chk_capture_save.setEnabled(False)
        self._set_capture_status("正在抓包", "success")
        process.start(self._capture_program(), args)

    def _on_capture_stdout(self, process):
        if self._capture_proc is not process:
            return
        text = bytes(process.readAllStandardOutput()).decode(
            "utf-8", errors="replace")
        if self._capture_stopping:
            return
        self._capture_stdout_buffer += text
        lines = self._capture_stdout_buffer.splitlines(keepends=True)
        self._capture_stdout_buffer = ""
        for line in lines:
            if line.endswith(("\n", "\r")):
                packet = parse_packet_fields(line)
                if packet:
                    frame = int(packet["number"])
                    packet["frame_number"] = frame
                    packet["display_number"] = (
                        self._capture_session_frame_base + frame)
                    packet["capture_path"] = self._capture_temp_path
                    self._capture_buffer.append(packet)
            else:
                self._capture_stdout_buffer = line

    def _on_capture_stderr(self, process):
        if self._capture_proc is not process:
            return
        text = bytes(process.readAllStandardError()).decode(
            "utf-8", errors="replace")
        self._capture_stderr_buffer += text
        if len(self._capture_stderr_buffer) > 20000:
            self._capture_stderr_buffer = (
                self._capture_stderr_buffer[-20000:])

    def _on_capture_file_stderr(self, process):
        if self._capture_file_proc is not process:
            return
        text = bytes(process.readAllStandardError()).decode(
            "utf-8", errors="replace")
        self._capture_file_stderr_buffer += text
        if len(self._capture_file_stderr_buffer) > 20000:
            self._capture_file_stderr_buffer = (
                self._capture_file_stderr_buffer[-20000:])

    def _on_capture_file_error(self, process):
        if self._capture_file_proc is process:
            self._capture_file_stderr_buffer += process.errorString()
            if process.error() == QProcess.ProcessError.FailedToStart:
                self._capture_file_proc = None
                process.deleteLater()
                self._on_capture_file_failed()

    def _on_capture_file_finished(self, process, exit_code):
        if self._capture_file_proc is not process:
            process.deleteLater()
            return
        self._on_capture_file_stderr(process)
        self._capture_file_proc = None
        process.deleteLater()
        if self._capture_stopping:
            return
        if self._capture_running and exit_code != 0:
            self._on_capture_file_failed()

    def _on_capture_file_failed(self):
        error = self._capture_file_stderr_buffer.strip()
        self._stop_capture()
        self._capture_detail.setPlainText(
            "抓包文件写入失败：\n" + (error or "Dumpcap 已停止"))
        self._set_capture_status("抓包文件写入失败", "error")
        self._recheck_capture_driver_after_failure()

    def _on_capture_process_error(self, process):
        if self._capture_proc is process:
            self._capture_stderr_buffer += process.errorString()
            if process.error() == QProcess.ProcessError.FailedToStart:
                self._capture_proc = None
                self._capture_running = False
                self._btn_capture_start.setEnabled(True)
                self._btn_capture_stop.setEnabled(False)
                self._btn_capture_clear.setEnabled(True)
                self._btn_capture_refresh.setEnabled(True)
                self._chk_capture_save.setEnabled(True)
                self._set_capture_status("抓包引擎启动失败", "error")
                process.deleteLater()
                file_process = self._capture_file_proc
                if (
                    file_process is not None
                    and file_process.state()
                    != QProcess.ProcessState.NotRunning
                ):
                    file_process.kill()
                    file_process.waitForFinished(500)

    def _flush_capture_packets(self):
        if self._capture_stopping:
            self._capture_buffer.clear()
            return
        if not self._capture_buffer:
            return
        packets, self._capture_buffer = self._capture_buffer, []
        visible_packets = []
        for packet in packets:
            if self._capture_paused:
                size = len(str(packet.get("info") or "")) + 256
                if (
                    self._capture_paused_bytes + size
                    > self.MAX_PAUSED_PACKET_BYTES
                ):
                    self._capture_dropped += 1
                else:
                    self._capture_paused_packets.append(packet)
                    self._capture_paused_bytes += size
                continue
            visible_packets.append(packet)
        self._append_capture_packets(visible_packets)

    def _append_capture_packet(self, packet):
        self._append_capture_packets([packet])

    def _append_capture_packets(self, packets):
        if not packets:
            return
        self._capture_model.append_packets(packets)
        digits = max(
            3,
            max(len(str(int(packet["number"]))) for packet in packets),
        )
        required_width = (
            self._capture_table.fontMetrics().horizontalAdvance(
                "9" * digits) + 24
        )
        if self._capture_table.columnWidth(0) < required_width:
            self._capture_table.setColumnWidth(0, required_width)
        required_time_width = (
            max(
                self._capture_table.fontMetrics().horizontalAdvance(
                    self._capture_model.format_time(packet["time"]))
                for packet in packets
            )
            + 28
        )
        if self._capture_table.columnWidth(1) < required_time_width:
            self._capture_table.setColumnWidth(1, required_time_width)
        self._capture_count += len(packets)
        self._capture_bytes += sum(
            int(packet["length"]) for packet in packets)
        self._capture_display_records += len(packets)
        self._capture_display_bytes += sum(
            512 + int(packet["length"]) + len(str(packet["info"]))
            for packet in packets
        )
        if self._capture_model.rowCount() > 0:
            self._capture_table.scrollToBottom()
        self._set_capture_status(
            "抓包中  {} 包 / {}".format(
                self._capture_count,
                self._format_capture_bytes(self._capture_bytes)),
            "success",
        )
        self._clear_capture_if_save_limit_reached()

    @staticmethod
    def _format_capture_bytes(value):
        size = max(0, int(value))
        if size >= 1024 ** 3:
            return "{:.2f} GB".format(size / (1024 ** 3))
        if size >= 1024 ** 2:
            return "{:.2f} MB".format(size / (1024 ** 2))
        if size >= 1024:
            return "{:.1f} KB".format(size / 1024)
        return "{} B".format(size)

    def _on_capture_pause(self, checked):
        self._capture_paused = bool(checked)
        if not checked and self._capture_paused_packets:
            pending, self._capture_paused_packets = (
                self._capture_paused_packets, [])
            self._capture_paused_bytes = 0
            for packet in pending:
                self._append_capture_packet(packet)
            self._set_capture_status(
                "抓包中  {} 包 / {}".format(
                    self._capture_count,
                    self._format_capture_bytes(self._capture_bytes)),
                "success",
            )

    def _on_capture_save_toggle(self, checked):
        if self._capture_running:
            self._chk_capture_save.blockSignals(True)
            self._chk_capture_save.setChecked(
                bool(self._capture_save_path))
            self._chk_capture_save.blockSignals(False)
            show_warning(
                self, "抓包进行中",
                "请先停止抓包，再修改保存设置。")
            return
        if not checked:
            self._capture_save_path = ""
            self._set_capture_status("保存到文件已关闭")
            return
        directory = os.path.join(self._base_dir, "log")
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError:
            directory = os.getcwd()
        default_path = os.path.join(
            directory,
            "AnhuToolbox_capture_{}.pcapng".format(
                time.strftime("%Y%m%d_%H%M%S")),
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "保存抓包文件", default_path,
            "Wireshark 抓包文件 (*.pcapng);;所有文件 (*.*)",
        )
        if not path:
            self._chk_capture_save.blockSignals(True)
            self._chk_capture_save.setChecked(False)
            self._chk_capture_save.blockSignals(False)
            self._capture_save_path = ""
            return
        self._capture_save_path = path
        self._set_capture_status(
            "保存到文件已开启：{}".format(path), "primary")

    def _clear_capture_if_save_limit_reached(self):
        if (
            not self._chk_capture_save.isChecked()
            or not self._capture_save_path
        ):
            return
        if (
            self._capture_display_records < AUTO_CLEAR_RECORDS
            and self._capture_display_bytes < AUTO_CLEAR_BYTES
        ):
            return
        self._capture_model.clear()
        self._capture_detail.clear()
        self._capture_detail_cache.clear()
        self._capture_detail_timed_out_key = None
        self._capture_selected_frame = None
        self._capture_selected_path = ""
        self._capture_display_records = 0
        self._capture_display_bytes = 0
        self._set_capture_status(
            "页面已清空，文件继续保存  {} 包".format(
                self._capture_count),
            "success",
        )

    def _clear_capture(self):
        if self._capture_running:
            return
        self._capture_model.clear()
        self._capture_detail.clear()
        self._capture_detail_cache.clear()
        self._capture_count = 0
        self._capture_bytes = 0
        self._capture_dropped = 0
        self._capture_paused_packets.clear()
        self._capture_paused_bytes = 0
        self._capture_selected_frame = None
        self._capture_selected_path = ""
        self._capture_detail_timed_out_key = None
        self._capture_session_frame_base = 0
        self._capture_display_records = 0
        self._capture_display_bytes = 0
        self._set_capture_status("列表已清空")

    def _save_capture(self):
        if self._capture_running:
            show_warning(
                self, "抓包进行中",
                "请先停止抓包，再保存 pcapng 文件。")
            return
        if not self._capture_temp_path or not os.path.isfile(
                self._capture_temp_path):
            show_warning(self, "没有可保存的数据", "请先开始并抓取数据包。")
            return
        default_path = os.path.join(
            os.getcwd(),
            "AnhuToolbox_capture_{}.pcapng".format(
                time.strftime("%Y%m%d_%H%M%S")),
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "保存抓包文件", default_path,
            "Wireshark 抓包文件 (*.pcapng);;所有文件 (*.*)",
        )
        if not path:
            return
        try:
            shutil.copy2(self._capture_temp_path, path)
        except OSError as exc:
            show_error(self, "保存失败", str(exc))
            return
        show_success(self, "保存成功", "抓包文件已保存到：\n" + path)

    def _on_capture_selection_changed(self, *_args):
        rows = self._capture_table.selectionModel().selectedRows()
        if not rows:
            return
        packet = self._capture_model.packet_at(rows[0].row())
        if packet is None:
            return
        try:
            frame = int(packet.get("frame_number", packet["number"]))
        except (KeyError, TypeError, ValueError):
            return
        path = packet.get("capture_path") or self._capture_temp_path
        if (
            frame == self._capture_selected_frame
            and path == self._capture_selected_path
        ):
            return
        self._capture_selected_frame = frame
        self._capture_selected_path = path
        QTimer.singleShot(
            80, lambda: self._load_capture_detail(frame, path))

    def _load_capture_detail(self, frame, path=None):
        path = path or self._capture_temp_path
        if (
            not frame
            or not path
            or not os.path.isfile(path)
        ):
            return
        detail_key = (path, frame)
        previous = self._capture_detail_proc
        if previous is not None and previous.state() != QProcess.ProcessState.NotRunning:
            previous.kill()
            previous.waitForFinished(300)
        self._capture_detail_timeout_timer.stop()
        self._capture_detail_timed_out_key = None
        cached = self._capture_detail_cache.get(detail_key)
        if cached is not None:
            self._capture_detail_cache.move_to_end(detail_key)
            self._capture_detail.setPlainText(cached)
            return
        process = QProcess(self)
        process.setWorkingDirectory(str(self._capture_engine_dir))
        process.setProcessChannelMode(
            QProcess.ProcessChannelMode.MergedChannels)
        process.finished.connect(
            lambda code, _status: self._on_capture_detail_finished(
                process, frame, path, code))
        process.errorOccurred.connect(
            lambda _error: self._on_capture_detail_error(process))
        self._capture_detail_proc = process
        self._capture_detail.setPlainText("正在加载数据包 #{}...".format(frame))
        self._capture_detail_timeout_timer.start(8000)
        process.start(self._capture_program(), [
            "-r", path,
            "-Y", "frame.number=={}".format(frame),
            "-n", "-V", "-x",
        ])

    def _on_capture_detail_finished(
            self, process, frame, path, exit_code):
        self._capture_detail_timeout_timer.stop()
        output = bytes(process.readAll()).decode(
            "utf-8", errors="replace")
        process.deleteLater()
        if self._capture_detail_proc is process:
            self._capture_detail_proc = None
        detail_key = (path, frame)
        if (
            self._capture_selected_frame != frame
            or self._capture_selected_path != path
        ):
            return
        if self._capture_detail_timed_out_key == detail_key:
            self._capture_detail_timed_out_key = None
            self._capture_detail.setPlainText(
                "数据包详情加载超时。\n"
                "抓包文件较大时，可先停止抓包后再查看详情。")
            return
        if exit_code == 0 and output:
            detail = output[:2 * 1024 * 1024]
            self._capture_detail_cache[detail_key] = detail
            self._capture_detail_cache.move_to_end(detail_key)
            while len(self._capture_detail_cache) > 50:
                self._capture_detail_cache.popitem(last=False)
            self._capture_detail.setPlainText(detail)
        else:
            message = (
                output.strip()
                or "未找到第 {} 个数据包。\n"
                "抓包仍在写入或文件尚未刷新，可停止抓包后重试。".format(
                    frame)
            )
            self._capture_detail.setPlainText(
                "无法读取数据包详情：\n" + message)

    def _on_capture_detail_error(self, process):
        self._capture_detail_timeout_timer.stop()
        if self._capture_detail_proc is process:
            self._capture_detail_proc = None
        process.deleteLater()
        self._capture_detail.setPlainText("抓包详情进程启动失败")

    def _on_capture_detail_timeout(self):
        process = self._capture_detail_proc
        frame = self._capture_selected_frame
        path = self._capture_selected_path
        if process is None or frame is None or not path:
            return
        self._capture_detail_timed_out_key = (path, frame)
        if process.state() != QProcess.ProcessState.NotRunning:
            process.kill()
            process.waitForFinished(300)

    def _stop_capture(self):
        if not self._capture_running and self._capture_proc is None:
            return
        self._capture_stopping = True
        self._btn_capture_stop.setEnabled(False)
        self._set_capture_status("正在停止...", "primary")
        processes = (self._capture_proc, self._capture_file_proc)
        for process in processes:
            if (
                process is not None
                and process.state() != QProcess.ProcessState.NotRunning
            ):
                process.terminate()
        deadline = time.monotonic() + 0.3
        while (
            time.monotonic() < deadline
            and any(
                process is not None
                and process.state() != QProcess.ProcessState.NotRunning
                for process in processes
            )
        ):
            QApplication.processEvents()
            time.sleep(0.01)
        for process in processes:
            if (
                process is not None
                and process.state() != QProcess.ProcessState.NotRunning
            ):
                process.kill()
                process.waitForFinished(150)
        QApplication.processEvents()
        if self._capture_proc is processes[0]:
            self._capture_proc = None
        if self._capture_file_proc is processes[1]:
            self._capture_file_proc = None
        self._capture_running = False
        self._capture_stopping = False
        self._btn_capture_start.setEnabled(True)
        self._btn_capture_stop.setEnabled(False)
        self._btn_capture_clear.setEnabled(True)
        self._btn_capture_refresh.setEnabled(True)
        self._chk_capture_save.setEnabled(True)
        self._set_capture_status(
            "已停止  {} 包".format(self._capture_count), "success")

    def _on_capture_finished(self, process, exit_code):
        if self._capture_proc is not process:
            process.deleteLater()
            return
        user_stopped = self._capture_stopping
        self._on_capture_stdout(process)
        self._on_capture_stderr(process)
        self._capture_proc = None
        file_process = self._capture_file_proc
        if (
            not self._capture_stopping
            and file_process is not None
            and file_process.state() != QProcess.ProcessState.NotRunning
        ):
            self._capture_stopping = True
            file_process.terminate()
            if not file_process.waitForFinished(1200):
                file_process.kill()
                file_process.waitForFinished(500)
            self._capture_stopping = False
        self._capture_running = False
        self._flush_capture_packets()
        self._btn_capture_start.setEnabled(True)
        self._btn_capture_stop.setEnabled(False)
        self._btn_capture_clear.setEnabled(True)
        self._btn_capture_refresh.setEnabled(True)
        self._chk_capture_save.setEnabled(True)
        if user_stopped:
            self._set_capture_status(
                "已停止  {} 包".format(self._capture_count), "success")
        else:
            error = self._capture_stderr_buffer.strip()
            self._set_capture_status("抓包异常结束", "error")
            if error:
                self._capture_detail.setPlainText(error[-20000:])
            self._recheck_capture_driver_after_failure()
        process.deleteLater()

    # ---------- 端口扫描 ----------
    def _build_port_page(self):
        w = QWidget()
        w.setObjectName("toolTabPage")
        lo = QVBoxLayout(w)
        lo.setContentsMargins(SPACE_MD, SPACE_MD, SPACE_MD, SPACE_MD)
        lo.setSpacing(SPACE_MD)

        control = ToolCard(
            "扫描参数", "选择端口预设，或手动指定单个端口 / 端口范围")
        row1 = QHBoxLayout()
        row1.setSpacing(SPACE_SM)
        row1.addWidget(_field_label("目标主机"))
        self._port_host = QLineEdit()
        self._port_host.setPlaceholderText("如 192.168.1.1 或 example.com")
        row1.addWidget(self._port_host, stretch=1)
        control.body.addLayout(row1)

        # 快捷预设 (置于端口设置上方)
        row2 = QHBoxLayout()
        row2.setSpacing(SPACE_SM)
        row2.addWidget(_field_label("快捷预设"))
        self._port_preset = QComboBox()
        self._port_preset.addItems([
            "自定义端口",
            "自定义范围",
            "常用端口 (1-1024)",
            "常见服务 (21/22/80/443/3306/3389...)",
            "全端口 (1-65535)",
        ])
        self._port_preset.currentIndexChanged.connect(self._on_port_preset)
        row2.addWidget(self._port_preset, stretch=1)
        control.body.addLayout(row2)

        # 端口设置 (根据预设动态显示 1 个或 2 个输入框)
        # 用固定高度容器预留空间，避免切换预设时下方按钮/输出框上下跳动
        cfg_box = QWidget()
        cfg_box.setFixedHeight(CONTROL_HEIGHT)
        row3 = QHBoxLayout(cfg_box)
        row3.setContentsMargins(0, 0, 0, 0)
        row3.setSpacing(SPACE_SM)
        self._port_cfg_label = _field_label("端口设置")
        row3.addWidget(self._port_cfg_label)
        self._port_single = QSpinBox()
        self._port_single.setRange(1, 65535)
        self._port_single.setValue(80)
        self._port_single.setFixedWidth(110)
        row3.addWidget(self._port_single)

        self._port_start = QSpinBox()
        self._port_start.setRange(1, 65535)
        self._port_start.setValue(1)
        self._port_start.setFixedWidth(110)
        row3.addWidget(self._port_start)
        self._port_sep = QLabel("~")
        row3.addWidget(self._port_sep)
        self._port_end = QSpinBox()
        self._port_end.setRange(1, 65535)
        self._port_end.setValue(1024)
        self._port_end.setFixedWidth(110)
        row3.addWidget(self._port_end)
        row3.addStretch()
        control.body.addWidget(cfg_box)

        self._btn_scan = _primary_button("开始扫描")
        self._btn_scan.setFixedWidth(110)
        self._btn_scan.clicked.connect(self._start_port_scan)
        btn_row = QHBoxLayout()
        btn_row.addWidget(self._btn_scan)
        btn_row.addStretch()
        control.body.addLayout(btn_row)
        lo.addWidget(control)

        self._port_output = QPlainTextEdit()
        _code_editor(self._port_output, readonly=True)
        self._port_output.setPlaceholderText("扫描进度和开放端口会显示在这里")
        output = ToolCard("扫描结果", "完成后会汇总全部开放端口")
        output.body.addWidget(self._port_output, stretch=1)
        lo.addWidget(output, stretch=1)
        self._on_port_preset(0)
        return w

    def _on_port_preset(self, idx=0):
        # 0=自定义端口(1个输入框) 1=自定义范围(2个输入框) 其余=固定预设(隐藏输入及标签)
        if idx == 0:
            self._port_cfg_label.show()
            self._port_single.show()
            self._port_start.hide()
            self._port_sep.hide()
            self._port_end.hide()
        elif idx == 1:
            self._port_cfg_label.show()
            self._port_single.hide()
            self._port_start.show()
            self._port_sep.show()
            self._port_end.show()
        else:
            self._port_cfg_label.hide()
            self._port_single.hide()
            self._port_start.hide()
            self._port_sep.hide()
            self._port_end.hide()

    def _get_ports(self):
        idx = self._port_preset.currentIndex()
        if idx == 0:
            return [self._port_single.value()]
        if idx == 1:
            start = self._port_start.value()
            end = self._port_end.value()
            if start > end:
                start, end = end, start
            return list(range(start, end + 1))
        if idx == 2:
            return list(range(1, 1025))
        if idx == 3:
            return list(self.COMMON_PORTS)
        if idx == 4:
            return list(range(1, 65536))
        return [80]

    def _start_port_scan(self):
        import socket, threading
        if self._scan_running:
            show_warning(self, "扫描进行中", "请等待当前扫描结束。")
            return
        host = self._port_host.text().strip()
        if not host:
            return
        ports = self._get_ports()
        if not ports:
            return
        self._scan_kind = "port"
        self._scan_running = True
        self._scan_run += 1
        run_id = self._scan_run
        self._scan_cancel = threading.Event()
        cancel_event = self._scan_cancel
        self._btn_scan.setEnabled(False)
        self._btn_lan.setEnabled(False)
        self._open_ports = []
        self._pending = len(ports)
        self._port_output.setPlainText(
            "正在扫描 {} 的 {} 个端口 ...".format(host, len(ports)))

        def scan(p):
            if cancel_event.is_set():
                return
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.5)
                if not cancel_event.is_set() and s.connect_ex((host, p)) == 0:
                    self._queue.put(("port_open", p, run_id))
                s.close()
            except Exception:
                pass
            finally:
                if not cancel_event.is_set():
                    self._queue.put(("task_done", run_id))

        from concurrent.futures import (
            FIRST_COMPLETED, ThreadPoolExecutor, wait,
        )
        # 大范围扫描时提高并发以加速
        workers = 200 if len(ports) <= 1024 else 500
        ex = ThreadPoolExecutor(max_workers=workers)
        self._executor = ex
        iterator = iter(ports)
        max_inflight = workers * 2
        inflight = set()

        def submit_more():
            while len(inflight) < max_inflight and not cancel_event.is_set():
                try:
                    port = next(iterator)
                except StopIteration:
                    return
                try:
                    inflight.add(ex.submit(scan, port))
                except RuntimeError:
                    cancel_event.set()
                    return

        def coordinate():
            try:
                submit_more()
                while inflight and not cancel_event.is_set():
                    done, _pending_futures = wait(
                        inflight,
                        timeout=0.1,
                        return_when=FIRST_COMPLETED,
                    )
                    inflight.difference_update(done)
                    submit_more()
                if cancel_event.is_set():
                    for future in inflight:
                        future.cancel()
            finally:
                ex.shutdown(
                    wait=False,
                    cancel_futures=cancel_event.is_set(),
                )

        threading.Thread(
            target=coordinate,
            name="AnhuPortScanCoordinator",
            daemon=True,
        ).start()

    # ---------- 网段扫描 ----------
    def _build_lan_page(self):
        w = QWidget()
        w.setObjectName("toolTabPage")
        lo = QVBoxLayout(w)
        lo.setContentsMargins(SPACE_MD, SPACE_MD, SPACE_MD, SPACE_MD)
        lo.setSpacing(SPACE_MD)

        control = ToolCard(
            "扫描网段", "使用 CIDR 表示网段，最多一次检测 1024 个主机")
        row = QHBoxLayout()
        row.setSpacing(SPACE_SM)
        row.addWidget(_field_label("网段"))
        self._lan_input = QLineEdit()
        self._lan_input.setPlaceholderText("如 192.168.1.0/24")
        self._lan_input.returnPressed.connect(self._start_lan_scan)
        row.addWidget(self._lan_input, stretch=1)
        self._btn_lan = _primary_button("扫描存活主机")
        self._btn_lan.clicked.connect(self._start_lan_scan)
        row.addWidget(self._btn_lan)
        control.body.addLayout(row)
        lo.addWidget(control)

        self._lan_output = QPlainTextEdit()
        _code_editor(self._lan_output, readonly=True)
        self._lan_output.setPlaceholderText("发现的存活主机会显示在这里")
        output = ToolCard("存活主机", "扫描结束后会显示全部检测结果")
        output.body.addWidget(self._lan_output, stretch=1)
        lo.addWidget(output, stretch=1)
        return w

    def _start_lan_scan(self):
        import ipaddress, threading
        if self._scan_running:
            show_warning(self, "扫描进行中", "请等待当前扫描结束。")
            return
        cidr = self._lan_input.text().strip()
        if not cidr:
            return
        try:
            net = ipaddress.ip_network(cidr, strict=False)
        except ValueError as e:
            self._lan_output.setPlainText("网段格式错误: {}".format(e))
            return
        hosts = list(net.hosts())
        if not hosts:
            hosts = [net.network_address]
        if len(hosts) > 1024:
            self._lan_output.setPlainText(
                "网段过大（{} 个主机），请缩小前缀".format(len(hosts)))
            return
        self._scan_kind = "lan"
        self._scan_running = True
        self._scan_run += 1
        run_id = self._scan_run
        self._scan_cancel = threading.Event()
        cancel_event = self._scan_cancel
        self._btn_lan.setEnabled(False)
        self._btn_scan.setEnabled(False)
        self._alive_ips = []
        self._pending = len(hosts)
        self._lan_output.setPlainText(
            "正在扫描 {}，共 {} 个主机 ...".format(cidr, len(hosts)))

        def check(ip):
            if cancel_event.is_set():
                return
            try:
                if not cancel_event.is_set() and self._ping_once(str(ip)):
                    self._queue.put(("lan_alive", str(ip), run_id))
            finally:
                if not cancel_event.is_set():
                    self._queue.put(("task_done", run_id))

        from concurrent.futures import ThreadPoolExecutor
        ex = ThreadPoolExecutor(max_workers=100)
        self._executor = ex
        for h in hosts:
            ex.submit(check, h)
        ex.shutdown(wait=False, cancel_futures=False)

    def _ping_once(self, ip):
        import subprocess
        try:
            if os.name == "nt":
                cmd = ["ping", "-n", "1", "-w", "300", ip]
            else:
                cmd = ["ping", "-c", "1", "-W", "1", ip]
            r = subprocess.run(
                cmd, capture_output=True, timeout=3,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            return r.returncode == 0
        except Exception:
            return False

    # ---------- 结果回传 ----------
    def _drain_queue(self):
        self._flush_capture_packets()
        try:
            while True:
                msg = self._queue.get_nowait()
                kind = msg[0]
                if kind == "ping_line":
                    self._ping_output.appendPlainText(msg[1])
                    sb = self._ping_output.verticalScrollBar()
                    sb.setValue(sb.maximum())
                elif kind == "ping_end":
                    if msg[1] is self._ping_proc:
                        self._ping_proc = None
                        self._btn_ping.setText("Ping")
                elif kind == "ping_error":
                    if msg[1] is self._ping_proc:
                        self._ping_proc = None
                        self._btn_ping.setText("Ping")
                    self._ping_output.appendPlainText("Ping 出错: {}".format(msg[2]))
                elif kind == "port_open":
                    p = msg[1]
                    if len(msg) < 3 or msg[2] != self._scan_run:
                        continue
                    if p not in self._open_ports:
                        self._open_ports.append(p)
                        self._open_ports.sort()
                    self._port_output.appendPlainText("  开放端口: {}".format(p))
                elif kind == "lan_alive":
                    ip = msg[1]
                    if len(msg) < 3 or msg[2] != self._scan_run:
                        continue
                    if ip not in self._alive_ips:
                        self._alive_ips.append(ip)
                    self._lan_output.appendPlainText("  存活: {}".format(ip))
                elif kind == "task_done":
                    if len(msg) < 2 or msg[1] != self._scan_run:
                        continue
                    self._pending -= 1
                    if self._pending <= 0:
                        self._on_all_done()
        except Exception:
            pass

    def _on_all_done(self):
        self._scan_running = False
        self._executor = None
        if self._scan_kind == "port":
            if self._open_ports:
                self._port_output.appendPlainText(
                    "\n扫描完成，共开放 {} 个端口: {}".format(
                        len(self._open_ports), ", ".join(map(str, self._open_ports))))
            else:
                self._port_output.appendPlainText("\n扫描完成，未发现开放端口")
        elif self._scan_kind == "lan":
            pass
        self._btn_scan.setEnabled(True)
        self._btn_lan.setEnabled(True)

    def stop_tasks(self):
        """停止持续任务、抓包进程和扫描任务。"""
        self._stop_ping()
        if self._include_capture:
            self._capture_npcap_monitor_timer.stop()
            if self._capture_npcap_installer is not None:
                self._capture_npcap_installer.close()
                self._capture_npcap_installer = None
            self._capture_detail_timeout_timer.stop()
            self._stop_capture()
            for process in (
                    self._capture_file_proc,
                    self._capture_detail_proc,
                    self._capture_interface_proc):
                if (
                    process is not None
                    and process.state() != QProcess.ProcessState.NotRunning
                ):
                    process.kill()
                    process.waitForFinished(500)
            self._capture_detail_proc = None
            self._capture_interface_proc = None
            self._capture_file_proc = None
        self._scan_cancel.set()
        self._scan_run += 1
        self._scan_running = False
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None
        self._timer.stop()


class PacketCaptureTool(QWidget):
    """Independent packet-capture workspace backed by the bundled TShark."""

    def __init__(self, base_dir=None):
        super().__init__()
        self.setObjectName("toolPage")
        self.setStyleSheet(TOOL_PAGE_STYLE)
        self._interfaces_initialized = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._capture_tool = NetworkTool(
            base_dir,
            include_capture=True,
            page_title="抓包分析",
            page_subtitle="抓取、过滤、查看并保存网络数据包。",
        )
        tabs = self._capture_tool._network_tabs
        for index in reversed(range(tabs.count())):
            if tabs.tabText(index) != "抓包分析":
                tabs.removeTab(index)
        tabs.setStyleSheet("QTabWidget::pane{border:none;}")
        tabs.tabBar().hide()
        layout.addWidget(self._capture_tool)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._interfaces_initialized:
            self._interfaces_initialized = True
            QTimer.singleShot(
                0, self._capture_tool._refresh_capture_interfaces)

    def stop_tasks(self):
        self._capture_tool.stop_tasks()
