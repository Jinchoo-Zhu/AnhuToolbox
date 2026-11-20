# -*- coding: utf-8 -*-
"""AnhuToolbox 关于窗口。"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from .version import __version__


class AboutDialog(QDialog):
    check_update_requested = Signal()
    update_requested = Signal(object)
    install_toolbox_requested = Signal()

    def __init__(self, parent=None, toolbox_installed=False):
        super().__init__(parent)
        self.setWindowTitle("关于 Anhu 百宝箱")
        self.setModal(True)
        self.setFixedWidth(440)
        self._available_release = None
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
            "QPushButton#installToolboxButton{background:#FFFFFF;color:#0067B8;"
            "border:1px solid #9CC7EA;font-weight:600;}"
            "QPushButton#installToolboxButton:hover{background:#EAF4FF;"
            "border-color:#0078D4;}"
            "QPushButton#installToolboxButton:disabled{background:#F3F4F6;"
            "color:#9AA0A6;border-color:#D8DCE1;font-weight:400;}"
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

        component = QHBoxLayout()
        component.setContentsMargins(0, 3, 0, 3)
        component.setSpacing(10)
        component_text = QVBoxLayout()
        component_text.setSpacing(1)
        component_name = QLabel("安护工具箱")
        component_name.setObjectName("aboutVersion")
        component_text.addWidget(component_name)
        component_hint = QLabel("可选第三方工具组件")
        component_hint.setObjectName("aboutMeta")
        component_text.addWidget(component_hint)
        component.addLayout(component_text, 1)
        self.toolbox_button = QPushButton(
            "已安装工具箱" if toolbox_installed else "安装工具箱")
        self.toolbox_button.setObjectName("installToolboxButton")
        self.toolbox_button.setEnabled(not toolbox_installed)
        self.toolbox_button.clicked.connect(
            lambda: self.install_toolbox_requested.emit())
        component.addWidget(self.toolbox_button)
        root.addLayout(component)

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
        self.check_button.clicked.connect(self._handle_check_button)
        buttons.addWidget(self.check_button)
        close_button = QPushButton("关闭")
        close_button.setObjectName("closeButton")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(close_button)
        root.addLayout(buttons)

        self.check_button.setFocus()

    def _handle_check_button(self):
        if self._available_release is not None:
            release = self._available_release
            self._available_release = None
            self.check_button.setEnabled(False)
            self.check_button.setText("正在准备...")
            self.update_requested.emit(release)
            return
        self.set_checking()
        self.check_update_requested.emit()

    def set_toolbox_preparing(self):
        self.toolbox_button.setEnabled(False)
        self.toolbox_button.setText("正在准备...")
        self.status.setStyleSheet("")
        self.status.setText("正在获取工具箱安装包信息...")
        self.status.show()

    def set_toolbox_unavailable(self, message):
        self.toolbox_button.setEnabled(True)
        self.toolbox_button.setText("安装工具箱")
        self.status.setStyleSheet(
            "QLabel#updateStatus{background:#FFF4F2;color:#C42B1C;"
            "border:1px solid #F1C7C2;border-radius:5px;"
            "padding:8px 10px;font-size:12px;}"
        )
        self.status.setText(message)
        self.status.show()

    def set_toolbox_ready(self, message):
        self.toolbox_button.setEnabled(True)
        self.toolbox_button.setText("安装工具箱")
        self.set_result(message)

    def set_checking(self):
        self._available_release = None
        self.status.setStyleSheet("")
        self.status.setText("正在检查更新...")
        self.status.show()
        self.check_button.setEnabled(False)
        self.check_button.setText("正在检查...")

    def set_update_available(self, release):
        self._available_release = release
        self.check_button.setEnabled(True)
        self.check_button.setText(
            "更新到 V{}".format(release.version))
        self.status.setStyleSheet("")
        self.status.setText(
            "发现新版本 V{}，可直接在此处更新".format(release.version))
        self.status.show()

    def set_result(self, message, error=False):
        self.check_button.setEnabled(True)
        if self._available_release is None:
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
