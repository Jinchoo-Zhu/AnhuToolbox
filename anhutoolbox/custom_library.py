# -*- coding: utf-8 -*-
"""自定义库 -- 用户自己添加的本地工具 (快捷方式 / exe)。

与官方工具箱彻底分开:
    官方   tools/tools.json      条目 path 相对 tools/ 目录 (随安装包分发)
    自定义 tools/tools.user.json 条目 path 是绝对路径 (用户自己挑的程序)

本页只做增删改查 + 打开, 不提供分类: 用户自己加的工具一般只有几个,
平铺一屏更直观。新增按钮在页面右上角, 重命名/打开位置/移除都在卡片
右键菜单里; 文件已经不存在(被移走/卸载)的条目仍可点击, 点击时由
launch_tool 提示, 用户照常可以右键把它移除。
"""

import os
import subprocess

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QScrollArea, QMenu, QMessageBox, QInputDialog, QFileDialog,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from . import toolbox
from .styles import prepare_menu

# 允许添加的文件类型: 快捷方式 + 常见可执行脚本
ADD_FILE_FILTER = ("快捷方式与程序 (*.exe *.lnk *.bat *.cmd *.com);;所有文件 (*)")

ADD_BTN_STYLE = (
    "QPushButton{background:#E8F0FE;color:#0078D4;border:1px solid #B3D4FC;"
    "border-radius:4px;padding:5px 14px;font-size:13px;font-weight:600;}"
    "QPushButton:hover{background:#D0E4FC;}"
    "QPushButton:pressed{background:#B3D4FC;}"
)

TITLE_STYLE = "color:#111827;font-size:18px;font-weight:700;"
COUNT_STYLE = "color:#6B7280;font-size:12px;padding-left:8px;"
TIP_STYLE = "color:#6B7280;font-size:13px;line-height:1.6;"

# 操作提示: 常驻在「＋ 添加本地工具」按钮左侧, 教用户怎么加、怎么改。
# 限宽换行, 排两行, 不至于把右边的按钮挤走。
HEAD_TIP = ("点右侧「＋ 添加本地工具」选择快捷方式或exe\n"
            "可以右键工具重命名或移除（不会删除文件本身）")
HEAD_TIP_WIDTH = 300


class CustomLibraryPage(QWidget):
    """自定义库: 顶部工具栏 + 工具图标网格 (首位是「添加工具」卡片)。"""

    def __init__(self, tools_dir):
        super().__init__()
        self._tools_dir = tools_dir
        self._tools = []
        self._last_dir = ""       # 记住上次添加的位置, 下次打开对话框直接定位
        self._build()
        self.reload()

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(0)
        title = QLabel("自定义库")
        title.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        title.setStyleSheet(TITLE_STYLE)
        head.addWidget(title)

        self._lbl_count = QLabel("")
        self._lbl_count.setStyleSheet(COUNT_STYLE)
        head.addWidget(self._lbl_count)
        head.addStretch()

        self._lbl_tip = QLabel(HEAD_TIP)
        self._lbl_tip.setStyleSheet(TIP_STYLE)
        self._lbl_tip.setWordWrap(True)
        # 前置 stretch 会把 wordWrap 的 QLabel 压到最小宽度(挤成细长条),
        # 所以这里给一个最小宽度, 它才会稳定地占住按钮左边这块地方。
        self._lbl_tip.setMinimumWidth(HEAD_TIP_WIDTH)
        head.addWidget(self._lbl_tip)
        head.addSpacing(10)

        self._btn_add = QPushButton("＋ 添加本地工具")
        self._btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_add.setToolTip(
            "选择一个本地的快捷方式或 exe 加入自定义库\n"
            "(清单写在 tools\\{}，不改动官方工具箱)".format(
                toolbox.USER_MANIFEST_NAME))
        self._btn_add.setStyleSheet(ADD_BTN_STYLE)
        self._btn_add.clicked.connect(self.add_tool)
        head.addWidget(self._btn_add)
        root.addLayout(head)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        root.addWidget(self._scroll, stretch=1)

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------
    def reload(self):
        """重新读取清单并重建网格 (增/删/改名后调用)。"""
        self._tools = toolbox.load_user_manifest(self._tools_dir)
        self._lbl_count.setText("共 {} 个".format(len(self._tools)))
        # 提示常驻, 不随工具数量变化 (没有工具时更要看这段说明)
        self._lbl_tip.setText(HEAD_TIP)

        content = QWidget()
        content.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        # 空白处右键 = 新增 (卡片上右键则是重命名/打开位置/移除)
        content.customContextMenuRequested.connect(
            lambda pos, w=content: self._show_blank_menu(w, pos))

        lo = QVBoxLayout(content)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(12)

        grid_w = QWidget()
        grid = QGridLayout(grid_w)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        # 每行 4 个工具卡片 (100x100, 与官方工具库卡片同款)
        for i, t in enumerate(self._tools):
            row, col = divmod(i, 4)
            btn = toolbox.make_tool_button(t, "", use_system_icon=True)
            self._bind_card_menu(btn, t)
            grid.addWidget(btn, row, col, Qt.AlignmentFlag.AlignTop)
        grid.setColumnStretch(4, 1)
        lo.addWidget(grid_w)
        lo.addStretch()
        old = self._scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        self._scroll.setWidget(content)

    def _bind_card_menu(self, btn, tool):
        btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        btn.customContextMenuRequested.connect(
            lambda pos, b=btn, t=tool: self._show_card_menu(b, t, pos))

    # ------------------------------------------------------------------
    # 菜单
    # ------------------------------------------------------------------
    def _show_card_menu(self, btn, tool, pos):
        m = prepare_menu(QMenu(self))
        a_new = m.addAction("添加本地工具...")
        a_dir = m.addAction("打开所在文件夹")
        m.addSeparator()
        a_ren = m.addAction("重命名...")
        a_del = m.addAction("移除")
        act = m.exec(btn.mapToGlobal(pos))
        if act is None:
            return
        if act == a_new:
            self.add_tool()
        elif act == a_dir:
            self._open_folder(tool)
        elif act == a_ren:
            self._rename(tool)
        elif act == a_del:
            self._remove(tool)

    def _show_blank_menu(self, widget, pos):
        m = prepare_menu(QMenu(self))
        a_add = m.addAction("添加本地工具...")
        act = m.exec(widget.mapToGlobal(pos))
        if act == a_add:
            self.add_tool()

    # ------------------------------------------------------------------
    # 增 / 改 / 删
    # ------------------------------------------------------------------
    def add_tool(self):
        start = self._last_dir if os.path.isdir(self._last_dir) else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "添加本地工具", start, ADD_FILE_FILTER)
        if not path:
            return
        path = os.path.normpath(path)
        self._last_dir = os.path.dirname(path)

        if not os.path.isfile(path):
            QMessageBox.warning(self, "添加失败", "找不到该文件：\n{}".format(path))
            return

        tools = toolbox.load_user_manifest(self._tools_dir)
        if any(self._same_path(t, path) for t in tools):
            QMessageBox.information(self, "提示", "「{}」已经添加过了。".format(
                os.path.basename(path)))
            return

        default_name = os.path.splitext(os.path.basename(path))[0] or "未命名工具"
        name, ok = QInputDialog.getText(
            self, "添加本地工具", "显示名称：", text=default_name)
        if not ok:
            return
        name = (name or "").strip() or default_name

        tools.append(toolbox.make_user_tool(name, path))
        if not self._save(tools, "添加失败"):
            return
        self.reload()

    def _rename(self, tool):
        old = str(tool.get("name") or "")
        name, ok = QInputDialog.getText(self, "重命名工具", "新名称：", text=old)
        name = (name or "").strip()
        if not ok or not name or name == old:
            return
        path = str(tool.get("path") or "")
        tools = toolbox.load_user_manifest(self._tools_dir)
        for t in tools:
            if self._same_path(t, path):
                t["name"] = name
                break
        if self._save(tools, "重命名失败"):
            self.reload()

    def _remove(self, tool):
        name = str(tool.get("name") or "该工具")
        path = str(tool.get("path") or "")
        r = QMessageBox.question(
            self, "移除工具",
            "确定把「{}」从自定义库移除吗？\n\n{}\n\n"
            "只删掉这条记录，不会删除工具文件本身。".format(name, path),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        tools = [t for t in toolbox.load_user_manifest(self._tools_dir)
                 if not self._same_path(t, path)]
        if self._save(tools, "移除失败"):
            self.reload()

    def _save(self, tools, title):
        """写清单, 失败时提示原因 (装到 Program Files 等只读目录时会发生)。"""
        if toolbox.save_user_manifest(self._tools_dir, tools):
            return True
        QMessageBox.critical(
            self, title,
            "无法写入自定义库清单：\n{}\n\n"
            "若软件安装在 Program Files 等受保护目录，请换到可写目录后重试。".format(
                toolbox.user_manifest_path(self._tools_dir)))
        return False

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    @staticmethod
    def _same_path(tool, path):
        """比较两条记录是否指向同一个文件 (忽略大小写与斜杠差异)。"""
        a = str(tool.get("path") or "")
        if not a:
            return False
        return os.path.normcase(os.path.normpath(a)) == \
            os.path.normcase(os.path.normpath(path))

    def _open_folder(self, tool):
        """打开工具所在文件夹, 并尽量选中该文件。"""
        path = str(tool.get("path") or "")
        folder = os.path.dirname(path)
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self, "提示", "找不到该工具所在文件夹：\n{}".format(
                folder or path))
            return
        try:
            if os.path.exists(path):
                # explorer /select 只会打开窗口并高亮文件, 失败不影响用户
                subprocess.Popen(["explorer", "/select,", path])
            else:
                os.startfile(folder)
        except Exception as e:
            QMessageBox.warning(self, "提示", "无法打开文件夹：\n{}".format(e))
