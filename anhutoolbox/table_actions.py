# -*- coding: utf-8 -*-
"""带复选框表格的批量操作工具。"""

from PySide6.QtCore import QEvent, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication, QHeaderView, QStyle, QStyledItemDelegate,
    QStyleOptionViewItem,
)


def _draw_checkbox(painter, box, checked):
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QPen(QColor("#BFC5CC"), 1))
    painter.setBrush(QColor("#FFFFFF"))
    painter.drawRect(box)
    if checked:
        x = box.x()
        y = box.y()
        path = QPainterPath(QPointF(x + 3.2, y + 7.7))
        path.lineTo(x + 6.1, y + 10.6)
        path.lineTo(x + 11.9, y + 4.3)
        painter.setPen(QPen(
            QColor("#0078D4"), 2,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        ))
        painter.drawPath(path)
    painter.restore()


class CenteredCheckBoxDelegate(QStyledItemDelegate):
    """将行选择框绘制在单元格中央，并处理点击切换。"""

    def __init__(self, table, check_column):
        super().__init__(table)
        self._check_column = check_column

    @staticmethod
    def _checkbox_rect(rect):
        size = 15
        return QRect(
            rect.center().x() - size // 2,
            rect.center().y() - size // 2,
            size,
            size,
        )

    @staticmethod
    def _is_checked(value):
        return Qt.CheckState(value) == Qt.CheckState.Checked

    def paint(self, painter, option, index):
        if index.column() != self._check_column:
            super().paint(painter, option, index)
            return
        state_option = QStyleOptionViewItem(option)
        self.initStyleOption(state_option, index)
        state_option.text = ""
        state_option.features &= ~(
            QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        )
        style = (
            state_option.widget.style()
            if state_option.widget is not None
            else QApplication.style()
        )
        style.drawControl(
            QStyle.ControlElement.CE_ItemViewItem,
            state_option,
            painter,
            state_option.widget,
        )
        _draw_checkbox(
            painter,
            self._checkbox_rect(option.rect),
            self._is_checked(index.data(Qt.ItemDataRole.CheckStateRole)),
        )

    def editorEvent(self, event, model, option, index):
        if index.column() != self._check_column:
            return super().editorEvent(event, model, option, index)
        toggle = False
        if (
            event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
        ):
            hit = self._checkbox_rect(option.rect).adjusted(-5, -5, 5, 5)
            toggle = hit.contains(event.position().toPoint())
        elif event.type() == QEvent.Type.KeyPress:
            toggle = event.key() in (
                Qt.Key.Key_Space,
                Qt.Key.Key_Select,
            )
        if not toggle:
            return super().editorEvent(event, model, option, index)
        checked = self._is_checked(
            model.data(index, Qt.ItemDataRole.CheckStateRole)
        )
        model.setData(
            index,
            Qt.CheckState.Unchecked if checked else Qt.CheckState.Checked,
            Qt.ItemDataRole.CheckStateRole,
        )
        return True


def checked_row_indexes(table, check_column=None):
    """返回复选框处于选中状态的行号。

    批量操作只能使用这个集合。当前行、高亮行和普通单元格选择都不参与，
    避免用户只是单击查看某一行时误删或误改数据。
    """
    if check_column is None:
        check_column = table.property("checkboxColumn")
    if check_column is None:
        check_column = 0
    rows = []
    for row in range(table.rowCount()):
        item = table.item(row, check_column)
        if item is None:
            continue
        if not item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
            continue
        if item.checkState() == Qt.CheckState.Checked:
            rows.append(row)
    return rows


class SelectAllHeaderView(QHeaderView):
    """在第一列表头绘制全选复选框。"""

    def __init__(self, table, check_column=0):
        super().__init__(Qt.Orientation.Horizontal, table)
        self._table = table
        self._check_column = check_column
        self.setSectionsClickable(True)
        self.setHighlightSections(False)
        self.setMouseTracking(True)

    def _checkbox_rect(self, section_rect):
        size = 15
        column_rect = QRect(
            self._table.columnViewportPosition(self._check_column),
            0,
            self._table.columnWidth(self._check_column),
            1,
        )
        return QRect(
            column_rect.center().x() - size // 2,
            section_rect.center().y() - size // 2,
            size,
            size,
        )

    def _section_rect(self, logical_index):
        left = self.sectionViewportPosition(logical_index)
        return QRect(left, 0, self.sectionSize(logical_index), self.height())

    def _check_state(self):
        checked = 0
        total = 0
        for row in range(self._table.rowCount()):
            item = self._table.item(row, self._check_column)
            if item is None:
                continue
            if not item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                continue
            total += 1
            if item.checkState() == Qt.CheckState.Checked:
                checked += 1
        if total and checked == total:
            return Qt.CheckState.Checked
        return Qt.CheckState.Unchecked

    def paintSection(self, painter, rect, logical_index):
        super().paintSection(painter, rect, logical_index)
        if logical_index != self._check_column:
            return

        box = self._checkbox_rect(rect)
        state = self._check_state()
        _draw_checkbox(
            painter, box, state == Qt.CheckState.Checked)

    def toggle_all(self):
        items = []
        for row in range(self._table.rowCount()):
            item = self._table.item(row, self._check_column)
            if (
                item is not None
                and item.flags() & Qt.ItemFlag.ItemIsUserCheckable
            ):
                items.append(item)
        if not items:
            return
        target = (
            Qt.CheckState.Unchecked
            if all(item.checkState() == Qt.CheckState.Checked for item in items)
            else Qt.CheckState.Checked
        )
        for item in items:
            item.setCheckState(target)
        self.viewport().update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            position = event.position().toPoint()
            logical_index = self.logicalIndexAt(position)
            if logical_index == self._check_column:
                hit = self._checkbox_rect(
                    self._section_rect(logical_index)
                ).adjusted(-5, -5, 5, 5)
                if hit.contains(position):
                    self.toggle_all()
                    event.accept()
                    return
        super().mouseReleaseEvent(event)


def install_select_all_header(table, check_column=0):
    """为表格安装全选表头，并隐藏原来的复选框列标题文字。"""
    table.setProperty("checkboxColumn", check_column)
    header = SelectAllHeaderView(table, check_column)
    table.setHorizontalHeader(header)
    delegate = CenteredCheckBoxDelegate(table, check_column)
    table.setItemDelegateForColumn(check_column, delegate)
    table._checkbox_delegate = delegate

    header_item = table.horizontalHeaderItem(check_column)
    if header_item is not None:
        header_item.setText("")
        header_item.setToolTip("全选或取消全选")

    refresh = lambda *_args: header.viewport().update()
    table.itemChanged.connect(refresh)
    table.model().rowsInserted.connect(refresh)
    table.model().rowsRemoved.connect(refresh)
    table.model().modelReset.connect(refresh)
    return header
