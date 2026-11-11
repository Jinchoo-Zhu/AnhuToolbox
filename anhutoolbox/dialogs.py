# -*- coding: utf-8 -*-
"""AnhuToolbox 提示框。

普通提示、警告、错误和是否确认使用 Windows 原生消息框，与 AnhuSimMate
的 tkinter.messagebox 行为保持一致。应用图标继续使用 AnhuToolbox 自身图标。
"""

import ctypes
import os

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)


MB_OK = 0x00000000
MB_YESNO = 0x00000004
MB_ICONERROR = 0x00000010
MB_ICONQUESTION = 0x00000020
MB_ICONWARNING = 0x00000030
MB_ICONINFORMATION = 0x00000040
MB_SETFOREGROUND = 0x00010000

IDOK = 1
IDYES = 6
IDNO = 7


def _app_icon():
    icon = QApplication.windowIcon()
    return icon if not icon.isNull() else QIcon()


def _window_handle(parent):
    widget = parent
    if isinstance(parent, QDialog):
        widget = parent
    elif isinstance(parent, QWidget):
        widget = parent.window()
    else:
        widget = QApplication.activeWindow()
    if widget is None:
        return 0
    try:
        return int(widget.winId())
    except Exception:
        return 0


def _native_message(parent, title, message, icon, buttons=MB_OK):
    """显示 Windows 原生消息框；其他平台回退到 Qt 消息框。"""
    text = str(message)
    if os.name == "nt":
        try:
            import ctypes.wintypes as wintypes
            user32 = ctypes.windll.user32
            user32.MessageBoxW.argtypes = [
                wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
                wintypes.UINT,
            ]
            user32.MessageBoxW.restype = ctypes.c_int
            return int(user32.MessageBoxW(
                _window_handle(parent),
                text,
                str(title),
                int(icon | buttons | MB_SETFOREGROUND),
            ))
        except Exception:
            pass
    return _qt_message(parent, title, text, icon, buttons)


def _qt_message(parent, title, message, icon, buttons):
    box = QMessageBox(parent)
    box.setWindowTitle(str(title))
    box.setText(str(message))
    box.setWindowIcon(_app_icon())
    box.setIcon({
        MB_ICONERROR: QMessageBox.Icon.Critical,
        MB_ICONQUESTION: QMessageBox.Icon.Question,
        MB_ICONWARNING: QMessageBox.Icon.Warning,
        MB_ICONINFORMATION: QMessageBox.Icon.Information,
    }.get(icon, QMessageBox.Icon.Information))
    if buttons == MB_YESNO:
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No)
        box.button(QMessageBox.StandardButton.Yes).setText("是")
        box.button(QMessageBox.StandardButton.No).setText("否")
        box.setDefaultButton(QMessageBox.StandardButton.Yes)
    else:
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.button(QMessageBox.StandardButton.Ok).setText("确定")
        box.setDefaultButton(QMessageBox.StandardButton.Ok)
    return int(box.exec())


class AnhuInputDialog(QDialog):
    """与 AnhuSimMate 文本输入框一致的简洁系统窗口。"""

    def __init__(
            self, parent, title, label, text=""):
        super().__init__(parent)
        self.setWindowTitle(str(title))
        self.setWindowIcon(_app_icon())
        self.setModal(True)
        self.setMinimumWidth(470)
        self.setStyleSheet(
            "QDialog{background:#FFFFFF;}"
            "QLabel#inputLabel{color:#1A1A1A;font-family:'Microsoft YaHei UI';"
            "font-size:13px;font-weight:600;}"
            "QLineEdit#inputField{background:#FFFFFF;color:#1A1A1A;"
            "font-family:'Microsoft YaHei UI';font-size:13px;"
            "border:1px solid #B8B8B8;border-radius:3px;padding:7px 8px;}"
            "QLineEdit#inputField:focus{border-color:#0078D4;}"
            "QPushButton{min-width:84px;min-height:32px;padding:4px 14px;"
            "font-family:'Microsoft YaHei UI';font-size:13px;"
            "border-radius:3px;}"
            "QPushButton#saveButton{background:#0078D4;color:#FFFFFF;"
            "border:1px solid #005A9E;font-weight:600;}"
            "QPushButton#saveButton:hover{background:#106EBE;}"
            "QPushButton#cancelButton{background:#F7F7F7;color:#1A1A1A;"
            "border:1px solid #B8B8B8;}"
            "QPushButton#cancelButton:hover{background:#E8E8E8;"
            "border-color:#0078D4;}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(8)

        field_label = QLabel(str(label))
        field_label.setObjectName("inputLabel")
        field_label.setWordWrap(True)
        root.addWidget(field_label)

        self.input = QLineEdit()
        self.input.setObjectName("inputField")
        self.input.setText(str(text))
        self.input.setMinimumWidth(420)
        self.input.returnPressed.connect(self.accept)
        root.addWidget(self.input)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 10, 0, 0)
        buttons.setSpacing(8)
        buttons.addStretch()
        save = QPushButton("保存")
        save.setObjectName("saveButton")
        save.setDefault(True)
        save.clicked.connect(self.accept)
        buttons.addWidget(save)
        cancel = QPushButton("取消")
        cancel.setObjectName("cancelButton")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        root.addLayout(buttons)

        self.input.selectAll()
        self.input.setFocus()
        self.setMinimumHeight(self.sizeHint().height())

    def showEvent(self, event):
        super().showEvent(event)
        parent = self.parentWidget()
        if parent is not None and parent.isVisible():
            center = parent.window().frameGeometry().center()
            frame = self.frameGeometry()
            frame.moveCenter(center)
            self.move(frame.topLeft())


# 兼容旧调用名称。
AnhuDialog = AnhuInputDialog


def show_information(parent, title, message):
    return _native_message(
        parent, title, message, MB_ICONINFORMATION, MB_OK)


def show_success(parent, title, message):
    return _native_message(
        parent, title, message, MB_ICONINFORMATION, MB_OK)


def show_warning(parent, title, message):
    return _native_message(
        parent, title, message, MB_ICONWARNING, MB_OK)


def show_error(parent, title, message):
    return _native_message(
        parent, title, message, MB_ICONERROR, MB_OK)


def ask_yes_no(parent, title, message, confirm_text="确定", danger=False):
    result = _native_message(
        parent, title, message, MB_ICONQUESTION, MB_YESNO)
    return result == IDYES


def get_text(parent, title, label, text=""):
    dialog = AnhuInputDialog(parent, title, label, text)
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    return dialog.input.text(), accepted
