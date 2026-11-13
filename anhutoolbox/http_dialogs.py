# -*- coding: utf-8 -*-
"""HTTP 页面使用的专用确认对话框。"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox


class UnsavedChangesDialog(QMessageBox):
    """使用系统警告窗口样式处理未保存标签。"""

    def __init__(self, documents, parent=None):
        super().__init__(parent)
        self.setWindowTitle("提示")
        self.setIcon(QMessageBox.Icon.Warning)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setText(self._message(documents))
        self.setStandardButtons(QMessageBox.StandardButton.NoButton)
        self.result_action = "cancel"

        self._cancel_button = self.addButton(
            "取消", QMessageBox.ButtonRole.RejectRole)
        self._discard_button = self.addButton(
            "不保存", QMessageBox.ButtonRole.DestructiveRole)
        self._save_button = self.addButton(
            "保存并关闭", QMessageBox.ButtonRole.AcceptRole)
        self.setDefaultButton(self._save_button)
        self.setEscapeButton(self._cancel_button)
        self.buttonClicked.connect(self._on_button_clicked)

    def _on_button_clicked(self, button):
        if button is self._save_button:
            self.result_action = "save"
        elif button is self._discard_button:
            self.result_action = "discard"
        else:
            self.result_action = "cancel"

    @staticmethod
    def _message(documents):
        names = [
            str(document.get("name") or "未命名接口")
            for document in documents
        ]
        if len(names) == 1:
            subject = "接口「{}」尚未保存".format(names[0])
        else:
            shown = "、".join(names[:3])
            if len(names) > 3:
                shown += " 等 {} 个接口".format(len(names))
            subject = "当前有未保存的接口：{}".format(shown)
        return (
            "{}。\n"
            "关闭后，未保存的修改将丢失。请选择如何处理。"
        ).format(subject)

    @classmethod
    def ask(cls, documents, parent=None):
        dialog = cls(documents, parent)
        dialog.exec()
        return dialog.result_action
