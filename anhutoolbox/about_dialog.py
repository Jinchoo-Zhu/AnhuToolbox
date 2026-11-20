# -*- coding: utf-8 -*-
"""AnhuToolbox 关于窗口。"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from .version import __version__


class AboutDialog(QDialog):
    check_update_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("关于 Anhu 百宝箱")
        self.setModal(True)
        self.setFixedWidth(440)
        self.setStyleSheet(
            "QDialog{background:#FFFFFF;}"
            "QLabel{color:#1A1A1A;font-family:'Microsoft YaHei UI';}"
            "QLabel#aboutName{font-size:18px;font-weight:600;}"
            "QLabel#aboutVersion{color:#555;font-size:13px;}"
            "QLabel#aboutMeta{color:#777;font-size:12px;}"
            "QLabel#updateStatus{background:#F5F9FD;color:#555;"
            "border:1px solid #D9E8F5;border-radius:5px;"
            "padding:8px 10px;font-size:12px;}"
            "QPushButton{min-height:30px;padding:3px 14px;"
            "border-radius:4px;font-family:'Microsoft YaHei UI';"
            "font-size:13px;}"
            "QPushButton#checkUpdateButton{background:#0078D4;color:#FFFFFF;"
            "border:1px solid #005A9E;font-weight:600;}"
            "QPushButton#checkUpdateButton:hover{background:#106EBE;}"
            "QPushButton#closeButton{background:#F7F7F7;color:#333;"
            "border:1px solid #C8C8C8;}"
            "QPushButton#closeButton:hover{background:#ECECEC;}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(12)
        icon = QLabel()
        parent_icon = parent.windowIcon() if parent is not None else None
        if parent_icon is not None and not parent_icon.isNull():
            icon.setPixmap(parent_icon.pixmap(48, 48))
        icon.setFixedSize(48, 48)
        header.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)

        names = QVBoxLayout()
        names.setSpacing(2)
        name = QLabel("Anhu 百宝箱")
        name.setObjectName("aboutName")
        names.addWidget(name)
        description = QLabel("网络通信调试与工程工具箱")
        description.setObjectName("aboutMeta")
        names.addWidget(description)
        names.addStretch()
        header.addLayout(names, 1)
        root.addLayout(header)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet("color:#E6E6E6;")
        root.addWidget(divider)

        version = QLabel(f"当前版本：V{__version__}")
        version.setObjectName("aboutVersion")
        root.addWidget(version)
        author = QLabel("作者：Jinchoo Zhu | Jerry Lyu")
        author.setObjectName("aboutMeta")
        root.addWidget(author)

        self.status = QLabel()
        self.status.setObjectName("updateStatus")
        self.status.setWordWrap(True)
        self.status.hide()
        root.addWidget(self.status)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 6, 0, 0)
        buttons.addStretch()
        self.check_button = QPushButton("检查更新")
        self.check_button.setObjectName("checkUpdateButton")
        self.check_button.setDefault(True)
        self.check_button.clicked.connect(self._request_check)
        buttons.addWidget(self.check_button)
        close_button = QPushButton("关闭")
        close_button.setObjectName("closeButton")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(close_button)
        root.addLayout(buttons)

        self.check_button.setFocus()

    def _request_check(self):
        self.set_checking()
        self.check_update_requested.emit()

    def set_checking(self):
        self.status.setStyleSheet("")
        self.status.setText("正在检查更新...")
        self.status.show()
        self.check_button.setEnabled(False)
        self.check_button.setText("正在检查...")

    def set_result(self, message, error=False):
        self.check_button.setEnabled(True)
        self.check_button.setText("检查更新")
        if error:
            self.status.setStyleSheet(
                "QLabel#updateStatus{background:#FFF4F2;color:#C42B1C;"
                "border:1px solid #F1C7C2;border-radius:5px;"
                "padding:8px 10px;font-size:12px;}"
            )
        else:
            self.status.setStyleSheet("")
        self.status.setText(message)
        self.status.show()
