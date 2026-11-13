# -*- coding: utf-8 -*-
"""HTTP 项目的本地环境变量管理。"""

import copy
import os
import re
import secrets

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from .dialogs import ask_yes_no, show_information, show_warning
from .styles import _find_assets_dir
from .table_actions import checked_row_indexes, install_select_all_header
from .ui_tokens import (
    FONT_UI, HTTP_ENVIRONMENT_DIALOG_STYLE, HTTP_TABLE_STYLE, ICON_SIZE,
    TABLE_ROW_HEIGHT,
)


DEFAULT_ENVIRONMENT_ID = "default"
_VARIABLE_PATTERN = re.compile(r"\{\{\s*([^{}\r\n]+?)\s*\}\}")


def _icon(filename):
    return QIcon(os.path.join(_find_assets_dir(), filename))


class EnvironmentVariableError(ValueError):
    """当前环境的变量无法完成解析。"""


class EnvironmentResolver:
    """解析 ``{{变量名}}``，同时收集全部缺失和循环引用。"""

    def __init__(self, environment):
        self._values = {}
        for variable in (environment or {}).get("variables") or []:
            if not isinstance(variable, dict):
                continue
            name = str(variable.get("name") or "").strip()
            if name and name not in self._values:
                self._values[name] = str(variable.get("value") or "")
        self.missing = set()
        self.cycles = set()

    def resolve(self, value):
        return self._resolve(str(value or ""), ())

    def _resolve(self, value, stack):
        def replace(match):
            name = match.group(1).strip()
            if name in stack:
                cycle_start = stack.index(name)
                self.cycles.add(
                    " → ".join(stack[cycle_start:] + (name,)))
                return match.group(0)
            if name not in self._values:
                self.missing.add(name)
                return match.group(0)
            return self._resolve(self._values[name], stack + (name,))

        return _VARIABLE_PATTERN.sub(replace, value)

    def raise_if_invalid(self):
        messages = []
        if self.missing:
            messages.append(
                "以下环境变量未定义：{}".format(
                    "、".join(sorted(self.missing))))
        if self.cycles:
            messages.append(
                "环境变量存在循环引用：{}".format(
                    "；".join(sorted(self.cycles))))
        if messages:
            raise EnvironmentVariableError("；".join(messages))


def default_environments():
    return [{
        "id": DEFAULT_ENVIRONMENT_ID,
        "name": "默认环境",
        "variables": [],
    }]


def normalise_environments(items):
    result = []
    used_ids = set()
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        environment_id = str(
            raw.get("id") or secrets.token_hex(8))
        if environment_id in used_ids:
            environment_id = secrets.token_hex(8)
        used_ids.add(environment_id)
        variables = []
        used_names = set()
        for variable in raw.get("variables") or []:
            if not isinstance(variable, dict):
                continue
            name = str(variable.get("name") or "").strip()
            if not name or name in used_names:
                continue
            used_names.add(name)
            variables.append({
                "name": name,
                "value": str(variable.get("value") or ""),
                "description": str(
                    variable.get("description") or ""),
            })
        result.append({
            "id": environment_id,
            "name": str(raw.get("name") or "未命名环境").strip()
            or "未命名环境",
            "variables": variables,
        })
    return result or default_environments()


class EnvironmentManagerDialog(QDialog):
    """编辑当前项目的本地环境及变量。"""

    def __init__(self, environments, active_environment, parent=None):
        super().__init__(parent)
        self.setObjectName("httpEnvironmentDialog")
        self.setWindowTitle("环境管理（本地）")
        self.resize(900, 620)
        self.setStyleSheet(HTTP_ENVIRONMENT_DIALOG_STYLE)
        self._environments = copy.deepcopy(
            normalise_environments(environments))
        self._editing_index = -1
        self.result_environments = []
        self.result_active_environment = active_environment
        self._build()
        self._refresh_environment_list(active_environment)

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(16)

        left = QWidget()
        left.setObjectName("httpEnvironmentPanel")
        left.setFixedWidth(230)
        left_lo = QVBoxLayout(left)
        left_lo.setContentsMargins(12, 12, 12, 12)
        left_lo.setSpacing(8)
        title = QLabel("环境管理")
        title.setObjectName("httpDialogTitle")
        left_lo.addWidget(title)
        self._environment_list = QListWidget()
        self._environment_list.setObjectName("httpEnvironmentList")
        self._environment_list.currentRowChanged.connect(
            self._on_environment_changed)
        left_lo.addWidget(self._environment_list, 1)
        environment_actions = QHBoxLayout()
        environment_actions.setSpacing(6)
        add_environment = QPushButton("新建环境")
        add_environment.setIcon(_icon("http_add.svg"))
        add_environment.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        add_environment.clicked.connect(self._add_environment)
        environment_actions.addWidget(add_environment, 1)
        remove_environment = QPushButton("删除环境")
        remove_environment.setIcon(_icon("http_delete.svg"))
        remove_environment.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        remove_environment.clicked.connect(self._remove_environment)
        environment_actions.addWidget(remove_environment, 1)
        left_lo.addLayout(environment_actions)
        root.addWidget(left)

        right = QWidget()
        right.setObjectName("httpEnvironmentPanel")
        right_lo = QVBoxLayout(right)
        right_lo.setContentsMargins(14, 12, 14, 12)
        right_lo.setSpacing(10)
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name_row.addWidget(QLabel("环境名称"))
        self._name = QLineEdit()
        self._name.setPlaceholderText("请输入环境名称")
        self._name.setFixedHeight(32)
        name_row.addWidget(self._name, 1)
        right_lo.addLayout(name_row)

        hint = QLabel(
            "仅保存本地环境变量，不使用云端数据。请求中可填写 {{变量名}}。")
        hint.setObjectName("httpEnvironmentHint")
        right_lo.addWidget(hint)

        self._variables = QTableWidget(0, 4)
        self._variables.setObjectName("httpVariableTable")
        self._variables.setHorizontalHeaderLabels(
            ["", "变量名", "本地值", "描述"])
        install_select_all_header(self._variables)
        self._variables.verticalHeader().setVisible(False)
        self._variables.verticalHeader().setDefaultSectionSize(
            TABLE_ROW_HEIGHT)
        self._variables.horizontalHeader().setMinimumHeight(
            TABLE_ROW_HEIGHT)
        self._variables.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._variables.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._variables.horizontalHeader().setStretchLastSection(True)
        self._variables.horizontalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignCenter)
        self._variables.setColumnWidth(0, 42)
        self._variables.setColumnWidth(1, 175)
        self._variables.setColumnWidth(2, 235)
        self._variables.setFont(QFont(FONT_UI, 9))
        self._variables.setStyleSheet(HTTP_TABLE_STYLE)
        right_lo.addWidget(self._variables, 1)

        variable_actions = QHBoxLayout()
        variable_actions.setSpacing(6)
        add_variable = QPushButton("添加变量")
        add_variable.setIcon(_icon("http_add.svg"))
        add_variable.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        add_variable.clicked.connect(self._add_variable)
        variable_actions.addWidget(add_variable)
        remove_variable = QPushButton("删除选中变量")
        remove_variable.setIcon(_icon("http_delete.svg"))
        remove_variable.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        remove_variable.clicked.connect(self._remove_variables)
        variable_actions.addWidget(remove_variable)
        variable_actions.addStretch()
        right_lo.addLayout(variable_actions)
        root.addWidget(right, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(
            QDialogButtonBox.StandardButton.Save).setText("保存")
        buttons.button(
            QDialogButtonBox.StandardButton.Save).setObjectName(
                "httpEnvironmentPrimary")
        buttons.button(
            QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        right_lo.addWidget(buttons)

    def _refresh_environment_list(self, selected_id=None):
        selected_id = selected_id or self.result_active_environment
        self._environment_list.blockSignals(True)
        self._environment_list.clear()
        selected_row = 0
        for index, environment in enumerate(self._environments):
            item = QListWidgetItem(
                environment["name"] or "未命名环境")
            item.setData(Qt.ItemDataRole.UserRole, environment["id"])
            self._environment_list.addItem(item)
            if environment["id"] == selected_id:
                selected_row = index
        self._environment_list.setCurrentRow(selected_row)
        self._environment_list.blockSignals(False)
        self._editing_index = -1
        self._load_environment(selected_row)

    def _commit_environment(self):
        index = self._editing_index
        if not 0 <= index < len(self._environments):
            return
        name = self._name.text().strip()
        self._environments[index]["name"] = name
        self._environment_list.item(index).setText(
            name or "未命名环境")
        variables = []
        for row in range(self._variables.rowCount()):
            name_item = self._variables.item(row, 1)
            value_item = self._variables.item(row, 2)
            description_item = self._variables.item(row, 3)
            variable_name = (
                name_item.text().strip() if name_item else "")
            if not variable_name:
                continue
            variables.append({
                "name": variable_name,
                "value": value_item.text() if value_item else "",
                "description": (
                    description_item.text() if description_item else ""),
            })
        self._environments[index]["variables"] = variables

    def _load_environment(self, index):
        if not 0 <= index < len(self._environments):
            self._name.clear()
            self._variables.setRowCount(0)
            self._editing_index = -1
            return
        self._editing_index = index
        environment = self._environments[index]
        self._name.setText(environment["name"])
        variables = environment.get("variables") or []
        self._variables.setRowCount(0)
        for variable in variables:
            row = self._variables.rowCount()
            self._variables.insertRow(row)
            check = QTableWidgetItem()
            check.setFlags(
                check.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            check.setCheckState(Qt.CheckState.Checked)
            check.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._variables.setItem(row, 0, check)
            self._variables.setItem(
                row, 1, QTableWidgetItem(variable.get("name", "")))
            self._variables.setItem(
                row, 2, QTableWidgetItem(variable.get("value", "")))
            self._variables.setItem(
                row, 3, QTableWidgetItem(
                    variable.get("description", "")))

    def _on_environment_changed(self, index):
        if index == self._editing_index:
            return
        self._commit_environment()
        self._load_environment(index)

    def _add_environment(self):
        self._commit_environment()
        environment = {
            "id": secrets.token_hex(8),
            "name": "新建环境",
            "variables": [],
        }
        self._environments.append(environment)
        self._refresh_environment_list(environment["id"])
        self._name.setFocus()
        self._name.selectAll()

    def _remove_environment(self):
        index = self._environment_list.currentRow()
        if not 0 <= index < len(self._environments):
            return
        if len(self._environments) == 1:
            show_warning(self, "无法删除", "至少需要保留一个环境。")
            return
        environment = self._environments[index]
        if not ask_yes_no(
                self, "删除环境",
                "确定删除环境「{}」吗？".format(environment["name"]),
                confirm_text="删除", danger=True):
            return
        del self._environments[index]
        self._refresh_environment_list(
            self._environments[min(index, len(self._environments) - 1)]["id"])

    def _add_variable(self):
        row = self._variables.rowCount()
        self._variables.insertRow(row)
        check = QTableWidgetItem()
        check.setFlags(
            check.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        check.setCheckState(Qt.CheckState.Checked)
        check.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._variables.setItem(row, 0, check)
        self._variables.setItem(row, 1, QTableWidgetItem(""))
        self._variables.setItem(row, 2, QTableWidgetItem(""))
        self._variables.setItem(row, 3, QTableWidgetItem(""))
        self._variables.setCurrentCell(row, 1)
        self._variables.editItem(self._variables.item(row, 1))

    def _remove_variables(self):
        rows = sorted(
            checked_row_indexes(self._variables), reverse=True)
        if not rows:
            show_information(
                self, "删除变量", "请先勾选需要删除的变量。")
            return
        for row in rows:
            self._variables.removeRow(row)

    def _save(self):
        variable_names = set()
        for row in range(self._variables.rowCount()):
            name_item = self._variables.item(row, 1)
            value_item = self._variables.item(row, 2)
            description_item = self._variables.item(row, 3)
            name = name_item.text().strip() if name_item else ""
            has_content = any((
                name,
                value_item.text() if value_item else "",
                description_item.text() if description_item else "",
            ))
            if has_content and not name:
                show_warning(
                    self, "变量名无效",
                    "第 {} 行填写了内容，但变量名为空。".format(row + 1))
                return
            if not name:
                continue
            if "{" in name or "}" in name:
                show_warning(
                    self, "变量名无效",
                    "变量名不能包含大括号：{}".format(name))
                return
            if name in variable_names:
                show_warning(
                    self, "变量名重复",
                    "当前环境中的变量名不能重复：{}".format(name))
                return
            variable_names.add(name)
        self._commit_environment()
        names = set()
        for environment in self._environments:
            name = environment["name"].strip()
            if not name:
                show_warning(self, "环境名称无效", "环境名称不能为空。")
                return
            if name in names:
                show_warning(
                    self, "环境名称重复",
                    "环境名称不能重复：{}".format(name))
                return
            names.add(name)
            variable_names = set()
            for variable in environment.get("variables") or []:
                variable_name = str(variable.get("name") or "").strip()
                if not variable_name:
                    continue
                if "{" in variable_name or "}" in variable_name:
                    show_warning(
                        self, "变量名无效",
                        "环境「{}」中的变量名不能包含大括号：{}".format(
                            name, variable_name))
                    return
                if variable_name in variable_names:
                    show_warning(
                        self, "变量名重复",
                        "环境「{}」中的变量名不能重复：{}".format(
                            name, variable_name))
                    return
                variable_names.add(variable_name)
        current_id = (
            self._environments[self._editing_index]["id"]
            if 0 <= self._editing_index < len(self._environments)
            else self.result_active_environment
        )
        if current_id not in {
                item["id"] for item in self._environments}:
            current_id = self._environments[0]["id"]
        self.result_environments = copy.deepcopy(self._environments)
        self.result_active_environment = current_id
        self.accept()
