# -*- coding: utf-8 -*-
"""Dialogs for MQTT server users, ACLs, and TLS configuration."""

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from .dialogs import show_warning


def _user_topics(user):
    topics = user.get("topics")
    if isinstance(topics, str):
        topics = topics.splitlines()
    if not isinstance(topics, (list, tuple)):
        return []
    return [
        str(topic).strip()
        for topic in topics
        if str(topic).strip()
    ]


class MQTTUserEditDialog(QDialog):
    def __init__(self, user=None, is_new=True, parent=None):
        super().__init__(parent)
        self._original = dict(user or {})
        self._is_new = bool(is_new)
        self.setWindowTitle("添加 MQTT 用户" if is_new else "编辑 MQTT 用户")
        self.setMinimumWidth(430)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.username = QLineEdit(
            str(self._original.get("username") or ""))
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText(
            "必填" if is_new else "留空则保留原密码")
        self.enabled = QCheckBox("启用此用户")
        self.enabled.setChecked(
            bool(self._original.get("enabled", True)))
        self.topics = QPlainTextEdit(
            "\n".join(_user_topics(self._original) or ["#"]))
        self.topics.setPlaceholderText("每行一个 Topic，例如 device/001/#")
        self.topics.setFixedHeight(100)
        self.access = QComboBox()
        self.access.addItem("只读", "read")
        self.access.addItem("读写", "readwrite")
        access = str(self._original.get("access") or "readwrite")
        index = self.access.findData(access)
        self.access.setCurrentIndex(max(0, index))
        form.addRow("用户名", self.username)
        form.addRow("密码", self.password)
        form.addRow("", self.enabled)
        form.addRow("Topic 权限", self.topics)
        form.addRow("访问方式", self.access)
        root.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _validate(self):
        username = self.username.text().strip()
        password = self.password.text()
        topics = [
            line.strip()
            for line in self.topics.toPlainText().splitlines()
            if line.strip()
        ]
        if not username:
            show_warning(self, "无法保存", "请填写用户名。")
            self.username.setFocus()
            return
        if self._is_new and not password:
            show_warning(self, "无法保存", "请填写密码。")
            self.password.setFocus()
            return
        if not topics:
            show_warning(self, "无法保存", "请至少填写一个 Topic。")
            self.topics.setFocus()
            return
        self.accept()

    def user_data(self):
        password = self.password.text()
        if not password:
            password = str(self._original.get("password") or "")
        return {
            "username": self.username.text().strip(),
            "password": password,
            "enabled": self.enabled.isChecked(),
            "topics": [
                line.strip()
                for line in self.topics.toPlainText().splitlines()
                if line.strip()
            ],
            "access": self.access.currentData(),
        }


class MQTTUsersDialog(QDialog):
    users_changed = Signal()

    def __init__(self, users=None, allow_anonymous=True, parent=None):
        super().__init__(parent)
        self._users = [dict(user) for user in (users or [])]
        self._allow_anonymous = bool(allow_anonymous)
        self._checked_usernames = set()
        self.setWindowTitle("MQTT 用户与权限")
        self.resize(720, 430)
        root = QVBoxLayout(self)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["选择", "用户名", "状态", "Topic 权限", "访问方式"])
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.cellDoubleClicked.connect(
            self._on_cell_double_clicked)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 52)
        self.table.setColumnWidth(1, 140)
        self.table.setColumnWidth(2, 70)
        self.table.setColumnWidth(4, 90)
        root.addWidget(self.table, 1)
        if not self._allow_anonymous:
            hint = QLabel(
                "关闭匿名连接时，请至少保留一个启用用户；"
                "用户修改会立即保存。")
            hint.setStyleSheet("color:#6B7280;font-size:12px;")
            root.addWidget(hint)
        actions = QHBoxLayout()
        add = QPushButton("添加用户")
        add.clicked.connect(self._add_user)
        remove = QPushButton("删除")
        remove.clicked.connect(self._remove_user)
        actions.addWidget(add)
        actions.addWidget(remove)
        actions.addStretch()
        root.addLayout(actions)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._refresh()

    def _refresh(self):
        usernames = {
            str(user.get("username") or "")
            for user in self._users
        }
        self._checked_usernames.intersection_update(usernames)
        self.table.setRowCount(len(self._users))
        for row, user in enumerate(self._users):
            username = str(user.get("username") or "")
            checkbox_holder = QWidget()
            checkbox_layout = QHBoxLayout(checkbox_holder)
            checkbox_layout.setContentsMargins(0, 0, 0, 0)
            checkbox = QCheckBox()
            checkbox.setToolTip("勾选后可通过“删除”按钮删除")
            checkbox.setAccessibleName("选择用户 " + username)
            checkbox.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            checkbox.setChecked(username in self._checked_usernames)
            checkbox.toggled.connect(
                lambda checked, name=username:
                self._set_user_checked(name, checked)
            )
            checkbox_layout.addWidget(
                checkbox, 0, Qt.AlignmentFlag.AlignCenter)
            self.table.setCellWidget(row, 0, checkbox_holder)
            values = (
                username,
                "启用" if bool(user.get("enabled", True)) else "禁用",
                "\n".join(_user_topics(user)),
                "只读" if user.get("access") == "read" else "读写",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignCenter
                    if column in (1, 3)
                    else Qt.AlignmentFlag.AlignLeft
                    | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(row, column + 1, item)

    def _set_user_checked(self, username, checked):
        if checked:
            self._checked_usernames.add(username)
        else:
            self._checked_usernames.discard(username)

    def _checked_rows(self):
        rows = []
        for row in range(self.table.rowCount()):
            holder = self.table.cellWidget(row, 0)
            checkbox = holder.findChild(QCheckBox) if holder else None
            if checkbox is not None and checkbox.isChecked():
                rows.append(row)
        return rows

    def _add_user(self):
        dialog = MQTTUserEditDialog(parent=self, is_new=True)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        user = dialog.user_data()
        if any(
            item.get("username") == user["username"]
            for item in self._users
        ):
            show_warning(self, "无法添加", "用户名已存在。")
            return
        self._users.append(user)
        self._refresh()
        self.users_changed.emit()

    def _on_cell_double_clicked(self, row, column):
        if column > 0:
            self._edit_user(row)

    def _edit_user(self, row):
        if not 0 <= row < len(self._users):
            return
        dialog = MQTTUserEditDialog(
            self._users[row], is_new=False, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        user = dialog.user_data()
        if any(
            index != row
            and item.get("username") == user["username"]
            for index, item in enumerate(self._users)
        ):
            show_warning(self, "无法保存", "用户名已存在。")
            return
        self._users[row] = user
        self._refresh()
        self.users_changed.emit()

    def _remove_user(self):
        rows = self._checked_rows()
        if not rows:
            show_warning(
                self, "删除用户", "请先勾选要删除的用户。")
            return
        for row in reversed(rows):
            self._users.pop(row)
        self._checked_usernames.clear()
        self._refresh()
        self.users_changed.emit()

    def users(self):
        return [dict(user) for user in self._users]


class MQTTTlsDialog(QDialog):
    def __init__(self, config=None, server_mode=False, parent=None):
        super().__init__(parent)
        self._server_mode = bool(server_mode)
        self._config = dict(config or {})
        self.setWindowTitle(
            "MQTT 服务端 TLS" if server_mode else "MQTT 客户端 TLS")
        self.setMinimumWidth(560)
        root = QVBoxLayout(self)
        self.enabled = QCheckBox("启用 TLS")
        self.enabled.setChecked(bool(self._config.get("enabled", False)))
        root.addWidget(self.enabled)
        form = QFormLayout()
        self.ca_file = self._path_row(
            form, "CA 证书", self._config.get("ca_file"))
        self.cert_file = self._path_row(
            form, "证书", self._config.get("cert_file"))
        self.key_file = self._path_row(
            form, "私钥", self._config.get("key_file"))
        self.require_client_cert = QCheckBox("要求客户端证书")
        self.require_client_cert.setChecked(
            bool(self._config.get("require_client_cert", False)))
        self.insecure = QCheckBox("跳过证书主机名校验")
        self.insecure.setChecked(bool(self._config.get("insecure", False)))
        if server_mode:
            form.addRow("", self.require_client_cert)
        else:
            form.addRow("", self.insecure)
        root.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _path_row(self, form, label, value):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        edit = QLineEdit(str(value or ""))
        browse = QPushButton("浏览")
        browse.clicked.connect(
            lambda: self._browse(edit, label))
        layout.addWidget(edit, 1)
        layout.addWidget(browse)
        form.addRow(label, row)
        return edit

    def _browse(self, edit, label):
        file_filter = (
            "私钥 (*.key *.pem);;所有文件 (*.*)"
            if label == "私钥"
            else "PEM 证书 (*.pem *.crt *.cer);;所有文件 (*.*)"
        )
        path, _ = QFileDialog.getOpenFileName(
            self, "选择" + label, "", file_filter)
        if path:
            edit.setText(path)

    def _validate(self):
        if self.enabled.isChecked():
            cert = self.cert_file.text().strip()
            key = self.key_file.text().strip()
            if bool(cert) != bool(key):
                show_warning(
                    self, "TLS 配置不完整",
                    "证书和私钥必须同时填写。")
                return
            if self._server_mode and not cert:
                show_warning(
                    self, "TLS 配置不完整",
                    "服务端 TLS 必须选择证书和私钥。")
                return
            for label, path in (
                ("CA 证书", self.ca_file.text().strip()),
                ("证书", cert),
                ("私钥", key),
            ):
                if path and not os.path.isfile(path):
                    show_warning(
                        self, "文件不存在",
                        "{}文件不存在：\n{}".format(label, path))
                    return
        self.accept()

    def tls_config(self):
        return {
            "enabled": self.enabled.isChecked(),
            "ca_file": self.ca_file.text().strip(),
            "cert_file": self.cert_file.text().strip(),
            "key_file": self.key_file.text().strip(),
            "require_client_cert": (
                self.require_client_cert.isChecked()
                if self._server_mode else False),
            "insecure": (
                self.insecure.isChecked()
                if not self._server_mode else False),
        }
