# -*- coding: utf-8 -*-
"""HTTP 接口导入、导出对话框。"""

import json
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QRadioButton,
    QVBoxLayout,
)

from .dialogs import show_error
from .http_transfer import (
    FORMAT_APIPOST, FORMAT_LABELS, FORMAT_POSTMAN, FORMAT_SWAGGER,
    HttpTransferError, detect_format, parse_transfer,
)


TRANSFER_DIALOG_STYLE = """
QDialog {
    background: #F5F7FA;
    font-family: "Microsoft YaHei UI";
    font-size: 13px;
    color: #263238;
}
QLabel#transferTitle {
    color: #1F2937;
    font-size: 18px;
    font-weight: 600;
}
QLabel#transferSection {
    color: #4B5563;
    font-size: 12px;
    font-weight: 600;
}
QFrame#transferCard {
    background: #FFFFFF;
    border: 1px solid #D8DEE6;
    border-radius: 8px;
}
QFrame#transferCard[selected="true"] {
    border: 1px solid #0078D4;
    background: #F3F8FF;
}
QFrame#transferCard:hover {
    border-color: #0078D4;
}
QLineEdit {
    background: #FFFFFF;
    border: 1px solid #D8DEE6;
    border-radius: 5px;
    padding: 6px 8px;
    min-height: 24px;
}
QPushButton {
    background: #FFFFFF;
    border: 1px solid #D8DEE6;
    border-radius: 5px;
    padding: 6px 14px;
    min-height: 24px;
}
QPushButton:hover {
    border-color: #0078D4;
    color: #0078D4;
}
QPushButton#transferPrimary {
    background: #0078D4;
    color: #FFFFFF;
    border-color: #0078D4;
    font-weight: 600;
}
QPushButton#transferPrimary:hover {
    background: #106EBE;
}
QPushButton#transferPrimary:disabled {
    background: #B8C3CF;
    border-color: #B8C3CF;
}
"""


class FormatCard(QFrame):
    def __init__(self, format_name, description, parent=None):
        super().__init__(parent)
        self.setObjectName("transferCard")
        self.format_name = format_name
        self.setProperty("selected", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        self.radio = QRadioButton(FORMAT_LABELS[format_name])
        self.radio.setStyleSheet("QRadioButton{font-weight:600;}")
        layout.addWidget(self.radio)
        hint = QLabel(description)
        hint.setWordWrap(True)
        hint.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        hint.setStyleSheet("color:#7B8490;font-size:11px;")
        layout.addWidget(hint)
        self.radio.toggled.connect(self._sync_style)

    def _sync_style(self, checked):
        self.setProperty("selected", bool(checked))
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.radio.setChecked(True)
            event.accept()
            return
        super().mousePressEvent(event)


class ExportTransferDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("导出项目")
        self.setMinimumWidth(620)
        self.setStyleSheet(TRANSFER_DIALOG_STYLE)
        self.selected_format = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(14)

        title = QLabel("导出项目")
        title.setObjectName("transferTitle")
        layout.addWidget(title)
        note = QLabel(
            "导出当前项目的全部 HTTP 接口，包括当前未保存草稿。"
            "不同格式无法表达的高级功能会给出兼容提示。")
        note.setWordWrap(True)
        note.setStyleSheet(
            "background:#EEF3F8;color:#5C6672;border-radius:5px;"
            "padding:8px 10px;")
        layout.addWidget(note)
        section = QLabel("导出格式")
        section.setObjectName("transferSection")
        layout.addWidget(section)
        cards = QHBoxLayout()
        cards.setSpacing(10)
        self._group = QButtonGroup(self)
        self._cards = []
        for index, (format_name, description) in enumerate((
            (FORMAT_APIPOST, "Apipost 项目 JSON"),
            (FORMAT_SWAGGER, "OpenAPI 3.0 JSON"),
            (FORMAT_POSTMAN, "Postman Collection v2.1"),
        )):
            card = FormatCard(format_name, description)
            self._group.addButton(card.radio, index)
            cards.addWidget(card, 1)
            self._cards.append(card)
        self._cards[0].radio.setChecked(True)
        layout.addLayout(cards)
        buttons = QDialogButtonBox()
        buttons.addButton(
            "取消", QDialogButtonBox.ButtonRole.RejectRole)
        export = buttons.addButton(
            "立即导出", QDialogButtonBox.ButtonRole.AcceptRole)
        export.setObjectName("transferPrimary")
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self._accept)
        layout.addWidget(buttons)

    def _accept(self):
        button = self._group.checkedButton()
        if button is None:
            return
        self.selected_format = self._cards[
            self._group.id(button)].format_name
        self.accept()


class ImportTransferDialog(QDialog):
    MAX_BYTES = 50 * 1024 * 1024

    def __init__(self, current_folder_name="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("导入项目")
        self.setMinimumSize(820, 560)
        self.setStyleSheet(TRANSFER_DIALOG_STYLE)
        self.transfer_result = None
        self.as_new_project = False
        self.source_name = ""
        self.conflict_policy = "merge"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)
        title = QLabel("导入项目")
        title.setObjectName("transferTitle")
        layout.addWidget(title)

        section = QLabel("数据格式")
        section.setObjectName("transferSection")
        layout.addWidget(section)
        cards = QHBoxLayout()
        cards.setSpacing(10)
        self._group = QButtonGroup(self)
        self._cards = []
        for index, (format_name, description) in enumerate((
            (FORMAT_APIPOST, "Apipost 项目 JSON"),
            (FORMAT_SWAGGER, "Swagger 2.0 / OpenAPI 3.x"),
            (FORMAT_POSTMAN, "Postman Collection v2.1"),
        )):
            card = FormatCard(format_name, description)
            self._group.addButton(card.radio, index)
            cards.addWidget(card, 1)
            self._cards.append(card)
        self._cards[0].radio.setChecked(True)
        layout.addLayout(cards)
        self._group.idClicked.connect(lambda _index: self._reparse())

        destination = QHBoxLayout()
        destination.addWidget(self._section_label("导入位置"))
        self._radio_current = QRadioButton("导入当前项目，当前分支")
        self._radio_current.setToolTip(
            "导入到当前展开目录：{}".format(
                current_folder_name or "根目录"))
        self._radio_current.setChecked(True)
        destination.addWidget(self._radio_current)
        self._radio_new_project = QRadioButton("作为新项目")
        self._radio_new_project.setToolTip(
            "使用所选 JSON 文件名作为新项目名称")
        destination.addWidget(self._radio_new_project)
        destination.addStretch()
        destination.addWidget(QLabel("重复接口"))
        self._conflict = QComboBox()
        self._conflict.addItem("保留重复", "merge")
        self._conflict.addItem("跳过重复", "skip")
        destination.addWidget(self._conflict)
        layout.addLayout(destination)

        file_row = QHBoxLayout()
        file_row.addWidget(self._section_label("选择 JSON 文件"))
        self._file_path = QLineEdit()
        self._file_path.setReadOnly(True)
        self._file_path.setPlaceholderText("尚未选择文件")
        file_row.addWidget(self._file_path, 1)
        browse = QPushButton("选择文件")
        browse.clicked.connect(self._choose_file)
        file_row.addWidget(browse)
        layout.addLayout(file_row)

        self._preview = QLabel("选择文件后将在这里显示导入预览")
        self._preview.setWordWrap(True)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._preview.setStyleSheet(
            "background:#FFFFFF;border:1px dashed #C8D1DB;"
            "border-radius:7px;padding:14px;color:#5D6672;"
            "min-height:130px;")
        layout.addWidget(self._preview, 1)

        buttons = QDialogButtonBox()
        buttons.addButton(
            "取消", QDialogButtonBox.ButtonRole.RejectRole)
        self._import_button = buttons.addButton(
            "开始导入", QDialogButtonBox.ButtonRole.AcceptRole)
        self._import_button.setObjectName("transferPrimary")
        self._import_button.setEnabled(False)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self._accept)
        layout.addWidget(buttons)

        self._raw_data = None

    @staticmethod
    def _section_label(text):
        label = QLabel(text)
        label.setObjectName("transferSection")
        return label

    def _selected_format(self):
        button = self._group.checkedButton()
        if button is None:
            return None
        return self._cards[self._group.id(button)].format_name

    def _select_format(self, format_name):
        for index, card in enumerate(self._cards):
            if card.format_name == format_name:
                card.radio.setChecked(True)
                return

    def _choose_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择项目文件", "", "JSON 文件 (*.json);;所有文件 (*.*)")
        if not path:
            return
        try:
            if os.path.getsize(path) > self.MAX_BYTES:
                raise HttpTransferError("文件超过 50 MB 限制")
            with open(path, "r", encoding="utf-8-sig") as stream:
                data = json.load(stream)
        except Exception as exc:
            show_error(self, "导入失败", str(exc))
            return
        self._file_path.setText(path)
        self.source_name = (
            os.path.splitext(os.path.basename(path))[0].strip()
            or "导入项目"
        )
        self._raw_data = data
        try:
            self._select_format(detect_format(data))
        except HttpTransferError:
            pass
        self._reparse()

    def _reparse(self):
        if self._raw_data is None:
            return
        format_name = self._selected_format()
        if format_name is None:
            return
        try:
            result = parse_transfer(self._raw_data, format_name)
        except Exception as exc:
            self.transfer_result = None
            self._import_button.setEnabled(False)
            self._preview.setText("解析失败：{}".format(exc))
            return
        self.transfer_result = result
        warnings = list(result.get("warnings") or [])
        lines = [
            "格式：{}".format(FORMAT_LABELS[format_name]),
            "文件夹：{} 个".format(len(result.get("folders") or [])),
            "接口：{} 个".format(len(result.get("interfaces") or [])),
            "重复处理：{}".format(self._conflict.currentText()),
        ]
        if warnings:
            lines.append("")
            lines.append("兼容提示：")
            lines.extend(warnings[:8])
            if len(warnings) > 8:
                lines.append("…另有 {} 条提示".format(len(warnings) - 8))
        self._preview.setText("\n".join(lines))
        self._import_button.setEnabled(bool(result.get("interfaces")))

    def _accept(self):
        if self.transfer_result is None:
            return
        self.as_new_project = self._radio_new_project.isChecked()
        self.conflict_policy = str(
            self._conflict.currentData() or "merge")
        self.accept()
