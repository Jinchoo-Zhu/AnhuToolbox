# -*- coding: utf-8 -*-
"""工具箱 -- 外置工具集 (图吧工具箱模式)。

程序从 exe 根目录下的 tools/ 文件夹读取工具清单 tools.json,
点击工具图标即可打开对应工具软件。tools 文件夹与 exe 一同分发
(zip 打包), 不打包进 exe, 以保持 exe 体积小、启动快。

工具登记方式: tools/tools.json 中的 tools 数组, 每条:
    name     工具名称
    category 分类名称
    path     工具可执行文件相对 tools/ 的路径
    icon     图标相对 tools/ 的路径 (可选, 缺省用首字生成图标)
    desc     说明 (可选)
"""

import os, json, time, shutil, subprocess

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QStackedWidget, QToolButton,
    QFileIconProvider,
)
from PySide6.QtCore import Qt, QSize, QFileInfo
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont
from .dialogs import show_warning

MANIFEST_NAME = "tools.json"
# 用户自定义工具清单 (自定义库), 与官方 tools.json 同目录但互不干扰:
# 官方条目 path 相对 tools\, 用户条目 path 是绝对路径。
USER_MANIFEST_NAME = "tools.user.json"


def _manifest_version(path):
    """读取清单 version 字段, 读取失败返回 0。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return int(data.get("version", 0)) if isinstance(data, dict) else 0
    except Exception:
        return 0


def ensure_tools(base_dir, resource_dir):
    """准备 tools 目录 (外置优先)。

    外置模式: 直接使用 exe 根目录下的 tools/ 文件夹, 不复制任何内容。
    若将来 exe 内置了 tools/ (spec 里重新加入), 首次运行或内置版本号
    更高时会自动释放到 exe 根目录。返回 tools 目录路径。
    """
    tools_dir = os.path.join(base_dir, "tools")
    src = os.path.join(resource_dir, "tools")
    os.makedirs(tools_dir, exist_ok=True)
    if not os.path.isdir(src):
        return tools_dir

    src_manifest = os.path.join(src, MANIFEST_NAME)
    dst_manifest = os.path.join(tools_dir, MANIFEST_NAME)
    need = True
    if os.path.exists(dst_manifest):
        need = _manifest_version(src_manifest) > _manifest_version(dst_manifest)

    if need:
        try:
            shutil.copytree(src, tools_dir, dirs_exist_ok=True)
        except Exception as e:
            print("[AnhuToolbox] 释放 tools 目录失败:", e)
    return tools_dir


def load_manifest(tools_dir):
    """读取 tools.json, 返回工具条目列表 (缺省返回空列表)。"""
    path = os.path.join(tools_dir, MANIFEST_NAME)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        tools = data.get("tools", []) if isinstance(data, dict) else []
        return [t for t in tools if isinstance(t, dict)]
    except Exception as e:
        print("[AnhuToolbox] 读取 tools.json 失败:", e)
        return []


def load_categories(tools_dir):
    """读取 tools.json 顶层 categories 字段 (显式声明的分类及顺序)。

    返回去重后的分类列表; 清单未声明 categories 时返回 None,
    由调用方从工具条目的 category 字段推断。
    """
    path = os.path.join(tools_dir, MANIFEST_NAME)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cats = data.get("categories") if isinstance(data, dict) else None
        if isinstance(cats, list):
            result = []
            for c in cats:
                c = str(c).strip()
                if c and c not in result:
                    result.append(c)
            return result
    except Exception:
        pass
    return None


def user_manifest_path(tools_dir):
    """自定义库清单文件的完整路径。"""
    return os.path.join(tools_dir, USER_MANIFEST_NAME)


def load_user_manifest(tools_dir):
    """读取自定义库清单 (tools.user.json), 缺省/损坏时返回空列表。"""
    path = user_manifest_path(tools_dir)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        tools = data.get("tools", []) if isinstance(data, dict) else []
        return [t for t in tools if isinstance(t, dict)]
    except Exception as e:
        print("[AnhuToolbox] 读取 tools.user.json 失败:", e)
        return []


def save_user_manifest(tools_dir, tools):
    """写回自定义库清单, 成功返回 True。

    先写临时文件再原子替换, 避免写到一半崩溃把清单留成半截 JSON
    (那会导致用户之前加的工具全部读不出来)。
    """
    path = user_manifest_path(tools_dir)
    tmp = path + ".tmp"
    try:
        os.makedirs(tools_dir, exist_ok=True)
        data = {"version": 1, "tools": list(tools or [])}
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception as e:
        print("[AnhuToolbox] 写入 tools.user.json 失败:", e)
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return False


def make_user_tool(name, path):
    """构造一条自定义工具记录 (path 存绝对路径)。"""
    return {
        "name": str(name or "未命名工具"),
        "path": os.path.normpath(os.path.abspath(path)),
        "added": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def resolve_tool_path(base_dir, rel):
    """把条目里的 path 解析成实际文件路径。

    官方工具 (base_dir=tools 目录) 存相对路径; 自定义库工具存绝对路径,
    此时 base_dir 传 "" 也能正确拼出原路径。
    """
    rel = str(rel or "")
    if not rel:
        return ""
    if os.path.isabs(rel):
        return rel
    return os.path.join(base_dir, rel) if base_dir else rel


_ICON_PROVIDER = None


def system_icon(path):
    """取文件在资源管理器里显示的图标 (exe/lnk/bat 等), 失败返回 None。

    自定义库的工具散落在用户磁盘各处, 没有我们放好的 png, 所以直接向
    系统要图标 (QFileIconProvider 内部走 shell, .lnk 也能拿到目标图标)。
    """
    global _ICON_PROVIDER
    if not path or not os.path.exists(path):
        return None
    try:
        if _ICON_PROVIDER is None:
            _ICON_PROVIDER = QFileIconProvider()
        icon = _ICON_PROVIDER.icon(QFileInfo(path))
        return icon if icon is not None and not icon.isNull() else None
    except Exception:
        return None


def _run_as_admin(exe_path, cwd):
    """用 ShellExecute(runas) 触发 UAC 提权后启动工具。

    DirectX Repair 等工具的可执行文件清单声明了 requireAdministrator,
    普通权限进程直接 CreateProcess 会失败 (WinError 740)。此时改用
    ShellExecuteW + "runas" 弹出 UAC 提权框, 由用户确认后以管理员运行。
    """
    import ctypes
    try:
        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", exe_path, None, cwd, 1
        )
        # ShellExecuteW 成功时返回值 > 32, 否则为错误码 (如 1223 用户取消)
        return ret > 32
    except Exception:
        return False


def launch_tool(exe_path):
    """打开工具, 以工具自身目录为工作目录 (兼容便携软件)。"""
    if not exe_path:
        show_warning(None, "工具启动失败", "该工具未配置可执行文件路径。")
        return False
    exe_path = os.path.abspath(exe_path)
    if not os.path.exists(exe_path):
        show_warning(None, "工具启动失败", "工具文件不存在：\n{}".format(exe_path))
        return False
    cwd = os.path.dirname(exe_path)
    ext = os.path.splitext(exe_path)[1].lower()
    if ext not in (".exe", ".bat", ".cmd", ".com"):
        # 其余交给系统关联程序打开: 快捷方式(.lnk 由系统解析到目标, 自带工作目录)
        # 与文档类文件 (.chm/.pdf/.html 等) 都走这条路
        try:
            os.startfile(exe_path)
            return True
        except Exception as e:
            show_warning(None, "工具启动失败", "无法打开文档：\n{}\n\n{}".format(exe_path, e))
            return False
    try:
        # 便携工具通常依赖自身目录下的 dll/配置, 必须设置 cwd
        subprocess.Popen([exe_path], cwd=cwd)
        return True
    except OSError as e:
        # WinError 740 (需要提权) / 5 (拒绝访问): 尝试触发 UAC 以管理员身份运行
        if getattr(e, "winerror", None) in (740, 5):
            if _run_as_admin(exe_path, cwd):
                return True
            show_warning(
                None, "工具启动失败",
                "无法以管理员权限启动工具（已取消提权或提权失败）：\n{}".format(exe_path)
            )
            return False
        show_warning(None, "工具启动失败", "无法打开工具：\n{}\n\n{}".format(exe_path, e))
        return False
    except Exception as e:
        show_warning(None, "工具启动失败", "无法打开工具：\n{}\n\n{}".format(exe_path, e))
        return False


def _norm_category(t):
    c = str(t.get("category") or "").strip()
    return c or "其他"


def _norm_group(t):
    """返回工具的一级分组名 (无则返回空字符串)。"""
    return str(t.get("group") or "").strip()


def _norm_subgroup(t):
    """返回工具的二级分组名 (无则返回空字符串)。"""
    return str(t.get("subgroup") or "").strip()


def load_icon(tools_dir, icon_rel):
    """读取工具图标, 缺失返回 None。"""
    if not icon_rel:
        return None
    p = os.path.join(tools_dir, icon_rel)
    if os.path.exists(p):
        return QIcon(p)
    return None


def default_icon(name):
    """用工具名首字生成默认图标。"""
    pm = QPixmap(48, 48)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor("#0078D4"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(0, 0, 48, 48, 8, 8)
    p.setPen(QColor("#FFFFFF"))
    p.setFont(QFont("Microsoft YaHei", 22, QFont.Weight.Bold))
    ch = (name.strip()[:1] or "?")
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, ch)
    p.end()
    return QIcon(pm)


def make_tool_button(tool, tools_dir, use_system_icon=False):
    """构建单个工具图标按钮, 点击打开对应 exe。

    tools_dir 传 "" 且条目 path 为绝对路径时即为自定义库工具;
    use_system_icon=True 时改从系统取图标 (自定义工具的 exe/快捷方式没有 png)。
    注意文件缺失时按钮仍可点击: 点击后由 launch_tool 弹出"文件不存在"提示,
    这样自定义库才能右键移除一个已失效的条目。
    """
    name = str(tool.get("name") or "未命名")

    btn = QToolButton()
    btn.setText(name)
    btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
    btn.setIconSize(QSize(48, 48))
    btn.setFixedSize(100, 100)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)

    exe_path = resolve_tool_path(tools_dir, tool.get("path"))
    icon = system_icon(exe_path) if use_system_icon \
        else load_icon(tools_dir, tool.get("icon"))
    if icon is not None and not icon.isNull():
        btn.setIcon(icon)
    else:
        btn.setIcon(default_icon(name))

    if exe_path and os.path.exists(exe_path):
        btn.setToolTip(str(tool.get("desc") or name))
        btn.setStyleSheet(
            "QToolButton{color:#374151;background:#F5F7FA;border:1px solid #E5E7EB;"
            "border-radius:8px;font-size:12px;}"
            "QToolButton:hover{background:#EBEEF3;border-color:#0078D4;}"
        )
    else:
        btn.setToolTip(name + " (文件缺失)")
        btn.setStyleSheet(
            "QToolButton{color:#9CA3AF;background:#F3F4F6;border:1px dashed #D1D5DB;"
            "border-radius:8px;font-size:12px;}"
            "QToolButton:hover{background:#E5E7EB;border-color:#9CA3AF;}"
        )
    btn.clicked.connect(lambda checked=False, p=exe_path: launch_tool(p))

    return btn


def _make_tool_grid(tools, tools_dir):
    """把一组工具渲染成图标网格 (每行最多 4 个)。"""
    grid_w = QWidget()
    grid = QGridLayout(grid_w)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(12)
    grid.setVerticalSpacing(12)
    for i, t in enumerate(tools):
        row, col = divmod(i, 4)
        grid.addWidget(make_tool_button(t, tools_dir), row, col,
                       Qt.AlignmentFlag.AlignTop)
    grid.setColumnStretch(4, 1)
    return grid_w


def _make_divider():
    """灰色实线分割线, 用于区分同一分类下的不同一级分组。"""
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet("QFrame{background:#C0C4CC;}")
    return line


def build_category_page(category, tools, tools_dir):
    """构建某分类的工具图标网格滚动页, 供统一工具箱复用。

    分类内的工具若带 group 字段, 会按 group 上下分组显示
    (每个分组一个标题); group 内再按 subgroup 二级分组显示。
    无 group 时保持原平铺网格。
    """
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")

    content = QWidget()
    lo = QVBoxLayout(content)
    lo.setContentsMargins(20, 16, 20, 16)
    lo.setSpacing(14)

    cat_tools = [t for t in tools if _norm_category(t) == category]

    if cat_tools:
        # 按 group 分组, 保持 tools.json 出现顺序
        groups = []  # [(group_name, [tool, ...]), ...]
        for t in cat_tools:
            g = _norm_group(t)
            if not groups or groups[-1][0] != g:
                groups.append((g, []))
            groups[-1][1].append(t)

        if len(groups) == 1 and not groups[0][0]:
            # 无一级分组: 保持原来的平铺网格
            lo.addWidget(_make_tool_grid(groups[0][1], tools_dir))
        else:
            for idx, (gname, gtools) in enumerate(groups):
                if idx > 0:
                    lo.addWidget(_make_divider())
                if gname:
                    head = QLabel(gname)
                    head.setStyleSheet("color:#111827;font-size:20px;font-weight:700;")
                    lo.addWidget(head)
                # 组内再按 subgroup 二级分组, 保持出现顺序
                subgroups = []  # [(subgroup_name, [tool, ...]), ...]
                for t in gtools:
                    sg = _norm_subgroup(t)
                    if not subgroups or subgroups[-1][0] != sg:
                        subgroups.append((sg, []))
                    subgroups[-1][1].append(t)

                if len(subgroups) == 1 and not subgroups[0][0]:
                    # 组内无二级分组
                    lo.addWidget(_make_tool_grid(subgroups[0][1], tools_dir))
                else:
                    for sgname, sgtools in subgroups:
                        if sgname:
                            sub = QLabel(sgname)
                            sub.setStyleSheet(
                                "color:#374151;font-size:16px;font-weight:600;"
                                "margin-top:4px;")
                            lo.addWidget(sub)
                        lo.addWidget(_make_tool_grid(sgtools, tools_dir))
    else:
        empty = QLabel("该分类暂无工具")
        empty.setStyleSheet("color:#6B7280;font-size:13px;")
        lo.addWidget(empty)

    lo.addStretch()
    scroll.setWidget(content)
    return scroll


class ToolboxPage(QWidget):
    """工具箱页 -- 左侧分类导航 + 右侧工具图标网格, 点击图标打开工具。"""

    def __init__(self, base_dir):
        super().__init__()
        self._tools_dir = os.path.join(base_dir, "tools")
        self._tools = load_manifest(self._tools_dir)
        self._build()

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 分类去重, 保持清单出现顺序 (优先使用清单显式声明的分类)
        self._categories = load_categories(self._tools_dir)
        if self._categories is None:
            self._categories = []
        for t in self._tools:
            c = _norm_category(t)
            if c not in self._categories:
                self._categories.append(c)

        # 左侧导航
        nav = QFrame()
        nav.setFixedWidth(176)
        nav.setStyleSheet(
            "QFrame{background:#F7F8FA;border-right:1px solid #E5E7EB;}"
        )
        nav_lo = QVBoxLayout(nav)
        nav_lo.setContentsMargins(12, 18, 12, 16)
        nav_lo.setSpacing(6)

        title = QLabel("工具箱")
        title.setStyleSheet(
            "color:#111827;font-size:16px;font-weight:700;"
            "background:transparent;padding:0 8px 12px 8px;"
        )
        nav_lo.addWidget(title)

        self._nav_btns = {}
        for c in self._categories:
            btn = self._make_nav_btn(c)
            nav_lo.addWidget(btn)
            self._nav_btns[c] = btn

        nav_lo.addStretch()
        root.addWidget(nav)

        # 右侧内容区
        self._stack = QStackedWidget()
        self._pages = {}
        for c in self._categories:
            page = self._build_category_page(c)
            self._stack.addWidget(page)
            self._pages[c] = page
        self._empty_page = self._build_empty_page()
        self._stack.addWidget(self._empty_page)
        root.addWidget(self._stack, stretch=1)

        if self._categories:
            for c, btn in self._nav_btns.items():
                btn.clicked.connect(lambda checked=False, cat=c: self._show(cat))
            first = self._categories[0]
            self._nav_btns[first].setChecked(True)
            self._stack.setCurrentWidget(self._pages[first])
        else:
            self._stack.setCurrentWidget(self._empty_page)

    def _show(self, cat):
        btn = self._nav_btns.get(cat)
        if btn is not None:
            btn.setChecked(True)
        self._stack.setCurrentWidget(self._pages.get(cat, self._empty_page))

    @staticmethod
    def _make_nav_btn(text):
        btn = QPushButton(text)
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            "QPushButton{color:#374151;background:transparent;border:none;"
            "border-radius:6px;padding:9px 10px;font-size:13px;text-align:left;}"
            "QPushButton:hover{background:#EBEEF3;}"
            "QPushButton:checked{background:#0078D4;color:#FFFFFF;}"
        )
        return btn

    def _build_category_page(self, cat):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")

        content = QWidget()
        lo = QVBoxLayout(content)
        lo.setContentsMargins(20, 16, 20, 16)
        lo.setSpacing(14)

        head = QLabel(cat)
        head.setStyleSheet("color:#111827;font-size:15px;font-weight:700;")
        lo.addWidget(head)

        tools = [t for t in self._tools if _norm_category(t) == cat]

        grid_w = QWidget()
        grid = QGridLayout(grid_w)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        for i, t in enumerate(tools):
            btn = self._make_tool_btn(t)
            row, col = divmod(i, 4)
            grid.addWidget(btn, row, col, Qt.AlignmentFlag.AlignTop)
        grid.setColumnStretch(4, 1)

        lo.addWidget(grid_w)
        lo.addStretch()

        scroll.setWidget(content)
        return scroll

    def _make_tool_btn(self, t):
        name = str(t.get("name") or "未命名")
        rel = t.get("path")

        btn = QToolButton()
        btn.setText(name)
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        btn.setIconSize(QSize(48, 48))
        btn.setFixedSize(100, 100)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            "QToolButton{color:#374151;background:#F5F7FA;border:1px solid #E5E7EB;"
            "border-radius:8px;font-size:12px;}"
            "QToolButton:hover{background:#EBEEF3;border-color:#0078D4;}"
        )

        icon = self._load_icon(t.get("icon"))
        if icon is not None and not icon.isNull():
            btn.setIcon(icon)
        else:
            btn.setIcon(self._default_icon(name))

        exe_path = resolve_tool_path(self._tools_dir, rel) or None
        if exe_path and os.path.exists(exe_path):
            btn.setToolTip(str(t.get("desc") or name))
            btn.clicked.connect(
                lambda checked=False, p=exe_path: launch_tool(p)
            )
        else:
            btn.setEnabled(False)
            btn.setToolTip(name + " (文件缺失)")

        return btn

    def _load_icon(self, icon_rel):
        if not icon_rel:
            return None
        p = os.path.join(self._tools_dir, icon_rel)
        if os.path.exists(p):
            return QIcon(p)
        return None

    @staticmethod
    def _default_icon(name):
        pm = QPixmap(48, 48)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor("#0078D4"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 0, 48, 48, 8, 8)
        p.setPen(QColor("#FFFFFF"))
        p.setFont(QFont("Microsoft YaHei", 22, QFont.Weight.Bold))
        ch = (name.strip()[:1] or "?")
        p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, ch)
        p.end()
        return QIcon(pm)

    def _build_empty_page(self):
        page = QWidget()
        lo = QVBoxLayout(page)
        lo.setContentsMargins(20, 16, 20, 16)
        lo.addStretch()
        tip = QLabel(
            "暂无工具\n\n"
            "将工具按「分类 / 工具名 / 工具.exe」的结构放入 tools 目录，\n"
            "并在 tools.json 中登记后，即可在此点击图标启动。"
        )
        tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tip.setStyleSheet("color:#6B7280;font-size:13px;line-height:1.6;")
        lo.addWidget(tip)
        lo.addStretch()
        return page
