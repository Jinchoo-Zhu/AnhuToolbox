# -*- coding: utf-8 -*-
"""串口与 TCP 各自独立的消息、发送工作区。"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

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

        self.send_bar = SendBar()
        layout.addWidget(self.send_bar)
