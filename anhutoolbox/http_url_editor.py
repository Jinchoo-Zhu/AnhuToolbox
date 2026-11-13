# -*- coding: utf-8 -*-
"""带环境变量高亮和补全的单行 URL 编辑器。"""

import re

from PySide6.QtCore import QStringListModel, Qt, Signal
from PySide6.QtGui import (
    QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextCursor,
)
from PySide6.QtWidgets import QCompleter, QPlainTextEdit

from .ui_tokens import (
    COLOR_PRIMARY_SOFT, COLOR_TEXT, COLOR_VARIABLE, CONTROL_HEIGHT, FONT_UI,
)


_COMPLETION_PREFIX = re.compile(r"\{\{([^{}\s]*)$")
_VARIABLE = re.compile(r"\{\{[^{}\r\n]+\}\}")


class EnvironmentVariableHighlighter(QSyntaxHighlighter):
    """将请求文本中的 ``{{变量名}}`` 绘制为独立颜色。"""

    def __init__(self, document, variable_provider, color=COLOR_VARIABLE):
        super().__init__(document)
        self._variable_provider = variable_provider
        self._normal_format = QTextCharFormat()
        self._normal_format.setForeground(QColor(color))
        self._missing_format = QTextCharFormat()
        self._missing_format.setForeground(QColor("#C42B1C"))
        self._missing_format.setBackground(QColor("#FDE7E9"))
        self._missing_format.setFontStrikeOut(True)
        self._known_variables = set()
        self.refresh_known_variables()

    def refresh_known_variables(self):
        self._known_variables = {
            str(name).strip()
            for name in self._variable_provider() or []
            if str(name).strip()
        }
        self.rehighlight()

    @property
    def missing_format(self):
        return self._missing_format

    def highlightBlock(self, text):
        for match in _VARIABLE.finditer(text):
            name = match.group(0)[2:-2].strip()
            char_format = (
                self._normal_format
                if name in self._known_variables
                else self._missing_format
            )
            self.setFormat(
                match.start(), match.end() - match.start(), char_format)


class EnvironmentUrlEditor(QPlainTextEdit):
    """固定单行外观，同时保留可着色的富文本文档。"""

    returnPressed = Signal()

    def __init__(self, variable_provider, parent=None):
        super().__init__(parent)
        self._variable_provider = variable_provider
        self.setObjectName("httpUrlEditor")
        self.setFixedHeight(CONTROL_HEIGHT)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTabChangesFocus(True)
        self.setFont(QFont(FONT_UI, 9))
        self.document().setDocumentMargin(0)
        self._center_document_vertically()
        self._highlighter = EnvironmentVariableHighlighter(
            self.document(), self._variable_provider)

        self._completion_model = QStringListModel(self)
        self._completer = QCompleter(self._completion_model, self)
        self._completer.setWidget(self)
        self._completer.setCaseSensitivity(
            Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchFlag.MatchStartsWith)
        self._completer.setCompletionMode(
            QCompleter.CompletionMode.PopupCompletion)
        self._completer.setMaxVisibleItems(8)
        self._completer.activated.connect(self._insert_completion)
        popup = self._completer.popup()
        popup.setObjectName("httpVariableCompleter")
        popup.setFont(QFont(FONT_UI, 9))
        popup.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        popup.setStyleSheet(
            "QListView{background:#FFFFFF;color:#1F2937;"
            "border:1px solid #D8E0E8;border-radius:6px;"
            "padding:4px;outline:0;"
            "font-family:'Microsoft YaHei UI';font-size:13px;}"
            "QListView::item{min-height:28px;padding:5px 10px;"
            "border-radius:4px;}"
            "QListView::item:hover{background:#F1F6FB;}"
            "QListView::item:selected{background:%s;color:%s;}"
            % (COLOR_PRIMARY_SOFT, COLOR_TEXT)
        )
        self.textChanged.connect(self._update_completion_popup)

    def refresh_variable_highlight(self):
        self._highlighter.refresh_known_variables()

    def missing_variables(self):
        names = {
            str(name).strip()
            for name in self._variable_provider() or []
            if str(name).strip()
        }
        return {
            match.group(0)[2:-2].strip()
            for match in _VARIABLE.finditer(self.toPlainText())
            if match.group(0)[2:-2].strip() not in names
        }

    def text(self):
        return self.toPlainText()

    def setText(self, value):
        self.setPlainText(str(value or ""))
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.setTextCursor(cursor)

    def insertFromMimeData(self, source):
        text = source.text().replace("\r", " ").replace("\n", " ")
        cursor = self.textCursor()
        cursor.insertText(text)
        self.setTextCursor(cursor)

    def _completion_context(self):
        cursor = self.textCursor()
        if cursor.hasSelection():
            return None
        prefix_text = self.toPlainText()[:cursor.position()]
        match = _COMPLETION_PREFIX.search(prefix_text)
        if match is None:
            return None
        return cursor.position(), match.group(1)

    def _update_completion_popup(self):
        if not self.hasFocus():
            self._completer.popup().hide()
            return
        context = self._completion_context()
        if context is None:
            self._completer.popup().hide()
            return
        names = sorted({
            str(name).strip()
            for name in self._variable_provider() or []
            if str(name).strip()
        }, key=str.casefold)
        if not names:
            self._completer.popup().hide()
            return
        _position, prefix = context
        self._completion_model.setStringList(names)
        self._completer.setCompletionPrefix(prefix)
        if self._completer.completionCount() == 0:
            self._completer.popup().hide()
            return
        popup_rect = self.cursorRect()
        popup_rect.setWidth(max(
            220, min(420, self.width() - popup_rect.left())))
        popup_rect.setHeight(CONTROL_HEIGHT)
        self._completer.complete(popup_rect)
        popup = self._completer.popup()
        if popup.model().rowCount():
            popup.setCurrentIndex(popup.model().index(0, 0))

    def _insert_completion(self, completion):
        completion = str(completion or "")
        context = self._completion_context()
        if not completion or context is None:
            return
        cursor_position, prefix = context
        start = cursor_position - len(prefix) - 2
        suffix = self.toPlainText()[cursor_position:]
        end = cursor_position + (2 if suffix.startswith("}}") else 0)
        cursor = self.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText("{{" + completion + "}}")
        self.setTextCursor(cursor)
        self._completer.popup().hide()

    def keyPressEvent(self, event):
        popup = self._completer.popup()
        if popup.isVisible():
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                index = popup.currentIndex()
                if index.isValid():
                    self._insert_completion(
                        popup.model().data(index))
                else:
                    popup.hide()
                event.accept()
                return
            if event.key() == Qt.Key.Key_Escape:
                popup.hide()
                event.accept()
                return
            if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                count = popup.model().rowCount()
                current = popup.currentIndex().row()
                if current < 0:
                    current = 0 if event.key() == Qt.Key.Key_Down else count - 1
                else:
                    delta = -1 if event.key() == Qt.Key.Key_Up else 1
                    current = max(0, min(count - 1, current + delta))
                popup.setCurrentIndex(
                    popup.model().index(current, 0))
                popup.scrollTo(popup.currentIndex())
                event.accept()
                return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            popup.hide()
            self.returnPressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)
        self._update_completion_popup()

    def focusOutEvent(self, event):
        self._completer.popup().hide()
        super().focusOutEvent(event)

    def resizeEvent(self, event):
        self._completer.popup().hide()
        super().resizeEvent(event)
        self._center_document_vertically()

    def _center_document_vertically(self):
        available = max(0, self.viewport().height())
        line_height = self.fontMetrics().height()
        margin = max(0.0, (available - line_height) / 2.0)
        if abs(self.document().documentMargin() - margin) > 0.1:
            self.document().setDocumentMargin(margin)
