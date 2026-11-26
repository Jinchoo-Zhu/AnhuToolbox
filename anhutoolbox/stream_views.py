# -*- coding: utf-8 -*-
"""串口与 TCP 各自独立的消息、发送工作区。"""

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
    QWidget,
)

from .panels import LogPanel, SendBar


class StreamPage(QWidget):
    """一套独立日志和发送栏，供串口、TCP 服务端、TCP 客户端复用。"""

    preset_toggled = Signal(bool)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.log_panel = LogPanel()
        self.btn_toggle_preset = QPushButton("≡ 预设")
        self.btn_toggle_preset.setCheckable(True)
        self.btn_toggle_preset.setFixedHeight(24)
        self.btn_toggle_preset.setStyleSheet(
            "QPushButton{padding:2px 10px;font-size:12px;border-radius:4px;"
            "min-height:20px;max-height:24px}"
            "QPushButton:checked{background:#E8F0FE;color:#0078D4;"
            "border-color:#0078D4;font-weight:600}"
        )
        self.btn_toggle_preset.toggled.connect(self.preset_toggled.emit)
        self.log_panel._add_widget(self.btn_toggle_preset)
        layout.addWidget(self.log_panel, stretch=1)

        self.toolbar = self.log_panel.take_toolbar()
        self.toolbar.setParent(None)
        self.toolbar.hide()
        self.send_bar = SendBar()
        self.send_bar.hide()
        self._compact_scale = 1.0

    def set_compact_scale(self, scale):
        scale = max(0.7, min(1.0, float(scale)))
        self._compact_scale = scale
        if scale >= 0.99:
            self.setStyleSheet("")
        else:
            pixel_size = 12 if scale >= 0.86 else 11
            self.setStyleSheet(
                "QWidget{{font-size:{}px;}}".format(pixel_size))
        widgets = [self, *self.findChildren(QWidget)]
        seen = set()
        for widget in widgets:
            if id(widget) in seen:
                continue
            seen.add(id(widget))
            base = getattr(widget, "_anhu_base_font", None)
            if base is None:
                base = QFont(widget.font())
                widget._anhu_base_font = base
            font = QFont(base)
            if font.pointSizeF() > 0:
                font.setPointSizeF(max(6.5, font.pointSizeF() * scale))
            elif font.pixelSize() > 0:
                font.setPixelSize(
                    max(9, int(round(font.pixelSize() * scale))))
            widget.setFont(font)
        if scale >= 0.95:
            mono_size = 10
        elif scale >= 0.86:
            mono_size = 9
        else:
            mono_size = 8
        self.log_panel.text.setFont(QFont("Consolas", mono_size))


class StreamWindowFrame(QFrame):
    """One selectable split-screen pane."""

    selected = Signal(int)

    def __init__(self, index, page, parent=None):
        super().__init__(parent)
        self.index = int(index)
        self.page = page
        self._selected = False
        self._multi_mode = False
        self.setObjectName("streamWindowFrame")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)
        self.header = QWidget()
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(8, 2, 8, 2)
        header_layout.setSpacing(8)
        self.title = QLabel("窗口{}".format(self.index + 1))
        self.title.setStyleSheet(
            "color:#4B5563;font-size:11px;font-weight:600;")
        self.status = QLabel("未连接")
        self.status.setStyleSheet("color:#6B7280;font-size:11px;")
        header_layout.addWidget(self.title)
        header_layout.addWidget(self.status)
        header_layout.addStretch()
        self.header.setFixedHeight(24)
        layout.addWidget(self.header)
        layout.addWidget(page, 1)
        self.header.hide()
        for widget in [self, *self.findChildren(QWidget)]:
            widget.installEventFilter(self)
        self._apply_style()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            self.selected.emit(self.index)
        return False

    def set_selected(self, selected):
        selected = bool(selected)
        if selected == self._selected:
            return
        self._selected = selected
        self._apply_style()

    def set_multi_mode(self, enabled):
        self._multi_mode = bool(enabled)
        self.header.hide()
        self._apply_style()

    def set_status_text(self, text):
        self.status.setText(str(text or "未连接"))

    def set_compact_scale(self, scale):
        font = QFont(self.header.font())
        font.setPointSizeF(max(6.5, 9.0 * float(scale)))
        self.header.setFont(font)
        pixel_size = 11 if scale >= 0.86 else 10
        self.title.setStyleSheet(
            "color:#4B5563;font-size:{}px;font-weight:600;".format(
                pixel_size))
        self.status.setStyleSheet(
            "color:#6B7280;font-size:{}px;".format(pixel_size))

    def _apply_style(self):
        color = (
            "#0078D4"
            if self._multi_mode and self._selected
            else "#D8DEE8"
        )
        self.setStyleSheet(
            "QFrame#streamWindowFrame{{background:#FFFFFF;"
            "border:2px solid {color};border-radius:4px;}}".format(
                color=color))


class StreamModeWorkspace(QWidget):
    """Single/dual/quad workspace for one serial or TCP mode."""

    active_changed = Signal(int)
    preset_toggled = Signal(int, bool)
    page_created = Signal(int, object)

    LAYOUT_COUNTS = {
        "single": 1,
        "dual": 2,
        "quad": 4,
    }

    def __init__(self, mode, log_dir, log_prefix, parent=None):
        super().__init__(parent)
        self.mode = str(mode)
        self._log_dir = str(log_dir)
        self._log_prefix = str(log_prefix)
        self._layout_mode = "single"
        self._active_index = 0
        self._pages = {}
        self._frames = {}
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(2, 2, 2, 2)
        self._root.setSpacing(2)
        self.toolbar_host = QWidget()
        self._toolbar_layout = QVBoxLayout(self.toolbar_host)
        self._toolbar_layout.setContentsMargins(0, 0, 0, 0)
        self._toolbar_layout.setSpacing(0)
        self.grid_host = QWidget()
        self._grid = QGridLayout(self.grid_host)
        self._grid.setContentsMargins(2, 2, 2, 2)
        self._grid.setHorizontalSpacing(6)
        self._grid.setVerticalSpacing(6)
        self.send_host = QWidget()
        self._send_layout = QVBoxLayout(self.send_host)
        self._send_layout.setContentsMargins(0, 0, 0, 0)
        self._send_layout.setSpacing(0)
        self._root.addWidget(self.toolbar_host)
        self._root.addWidget(self.grid_host, 1)
        self._root.addWidget(self.send_host)
        self._shared_toolbar = None
        self._shared_send_bar = None
        self.ensure_window(0)
        self.set_layout("single", emit=False)

    @property
    def layout_mode(self):
        return self._layout_mode

    @property
    def active_index(self):
        return self._active_index

    @property
    def active_page(self):
        return self.page(self._active_index)

    def visible_indices(self):
        return list(range(self.LAYOUT_COUNTS[self._layout_mode]))

    def ensure_window(self, index):
        index = int(index)
        if index not in range(4):
            raise ValueError("stream window index must be 0..3")
        if index in self._pages:
            return self._pages[index]
        page = StreamPage()
        page.log_panel.set_log_directory(
            self._log_dir,
            "{}_window{}".format(self._log_prefix, index + 1),
        )
        page.preset_toggled.connect(
            lambda checked, idx=index:
            self.preset_toggled.emit(idx, checked))
        frame = StreamWindowFrame(index, page, self)
        frame.selected.connect(self.set_active)
        self._pages[index] = page
        self._frames[index] = frame
        self._grid.addWidget(frame)
        self.page_created.emit(index, page)
        return page

    def page(self, index=None):
        index = self._active_index if index is None else int(index)
        return self.ensure_window(index)

    def frame(self, index):
        self.ensure_window(index)
        return self._frames[int(index)]

    def set_layout(self, layout_mode, active=None, emit=False):
        layout_mode = str(layout_mode or "single").lower()
        if layout_mode not in self.LAYOUT_COUNTS:
            layout_mode = "single"
        count = self.LAYOUT_COUNTS[layout_mode]
        for index in range(count):
            self.ensure_window(index)
        for frame in self._frames.values():
            self._grid.removeWidget(frame)
            frame.hide()
        positions = {
            "single": ((0, 0),),
            "dual": ((0, 0), (0, 1)),
            "quad": ((0, 0), (0, 1), (1, 0), (1, 1)),
        }[layout_mode]
        for index, (row, column) in enumerate(positions):
            frame = self._frames[index]
            frame.set_multi_mode(layout_mode != "single")
            self._grid.addWidget(frame, row, column)
            frame.show()
        for row in range(2):
            self._grid.setRowStretch(row, 1 if row < (2 if layout_mode == "quad" else 1) else 0)
        for column in range(2):
            self._grid.setColumnStretch(column, 1 if column < (2 if layout_mode != "single" else 1) else 0)
        scale = {"single": 1.0, "dual": 0.9, "quad": 0.82}[layout_mode]
        for frame in self._frames.values():
            frame.set_compact_scale(scale)
            frame.page.set_compact_scale(scale)
        self._layout_mode = layout_mode
        if active is None:
            active = self._active_index
        active = max(0, min(count - 1, int(active)))
        changed = active != self._active_index
        self._active_index = active
        self._update_selection()
        self._bind_shared_controls(active)
        if emit and changed:
            self.active_changed.emit(active)

    def set_active(self, index, emit=True):
        index = int(index)
        if index not in self.visible_indices():
            return
        changed = index != self._active_index
        self._active_index = index
        self._update_selection()
        self._bind_shared_controls(index)
        if emit:
            self.active_changed.emit(index)
        return changed

    def _bind_shared_controls(self, index):
        page = self.page(index)
        if self._shared_toolbar is not None:
            self._toolbar_layout.removeWidget(self._shared_toolbar)
            self._shared_toolbar.hide()
        if self._shared_send_bar is not None:
            self._send_layout.removeWidget(self._shared_send_bar)
            self._shared_send_bar.hide()
        self._shared_toolbar = page.toolbar
        self._shared_send_bar = page.send_bar
        self._toolbar_layout.addWidget(self._shared_toolbar)
        self._send_layout.addWidget(self._shared_send_bar)
        self._shared_toolbar.show()
        self._shared_send_bar.show()
        page.log_panel._fit_toolbar_width()

    def set_status(self, index, text):
        self.frame(index).set_status_text(text)

    def _update_selection(self):
        for index, frame in self._frames.items():
            frame.set_selected(index == self._active_index)

    def cleanup(self):
        for page in self._pages.values():
            page.send_bar.stop_repeat()
            page.log_panel.cleanup()
            page.toolbar.hide()
            page.toolbar.deleteLater()
            page.send_bar.hide()
            page.send_bar.deleteLater()
