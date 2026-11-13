# -*- coding: utf-8 -*-
"""AnhuToolbox 全局样式表 -- 白色主题"""

import os
import sys


def _find_assets_dir():
    """定位 assets 目录。

    源码运行时是 anhutoolbox/assets;
    打包后 spec 用了 contents_directory='lib', datas 被放到 exe 旁的
    lib/anhutoolbox/assets, 而冻结模块的 __file__ 是
    <exe目录>/anhutoolbox/styles.py, 两者并不一致, 所以必须逐个候选路径探测,
    否则 QSS 里的 url() 会指向不存在的文件, 下拉箭头图标会丢失。
    """
    candidates = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")]
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        meipass = getattr(sys, "_MEIPASS", exe_dir)
        candidates += [
            os.path.join(meipass, "lib", "anhutoolbox", "assets"),
            os.path.join(exe_dir, "lib", "anhutoolbox", "assets"),
            os.path.join(meipass, "anhutoolbox", "assets"),
            os.path.join(exe_dir, "anhutoolbox", "assets"),
        ]
    for path in candidates:
        if os.path.isdir(path):
            return path
    return candidates[0]


# 下拉箭头图标 (PNG, 随包分发)
# 注意: QSS 的 url() 不接受 file:/// 前缀, 必须用正斜杠的本地绝对路径
_ASSETS_DIR = _find_assets_dir()
_DOWN_ARROW = os.path.join(_ASSETS_DIR, "down_arrow.png").replace("\\", "/")
_UP_ARROW = os.path.join(_ASSETS_DIR, "up_arrow.png").replace("\\", "/")
_CHECK_MARK = os.path.join(_ASSETS_DIR, "checkbox_check.svg").replace("\\", "/")
_CHECK_MARK_MUTED = os.path.join(_ASSETS_DIR, "checkbox_check_muted.svg").replace("\\", "/")

BG_MAIN       = "#FFFFFF"
BG_PANEL      = "#FAFAFA"
BG_CARD       = "#F5F5F5"
BG_INPUT      = "#FFFFFF"
BG_HOVER      = "#E8F0FE"
BG_ACTIVE     = "#DEEBF7"
BG_BUTTON     = "#F0F0F0"
BG_BUTTON_HOVER = "#E0E0E0"
BG_PRIMARY    = "#0078D4"
BG_PRIMARY_HOVER = "#106EBE"
BG_DANGER     = "#D13438"
BG_DANGER_HOVER = "#A80000"
BG_SIDEBAR    = "#F5F5F5"
BORDER        = "#D0D0D0"
BORDER_FOCUS  = "#0078D4"
TEXT_PRIMARY  = "#1A1A1A"
TEXT_SECONDARY = "#666666"
TEXT_MUTED    = "#AAAAAA"
TEXT_BRIGHT   = "#FFFFFF"
ACCENT        = "#0078D4"
ACCENT_GREEN  = "#107C10"

FONT_MONO = "Consolas"
FONT_UI   = "Microsoft YaHei"

# 下拉框统一样式: 项目下拉框 / 参数配置下拉框 / 其它下拉框全部用这一份规则.
# 定义为独立常量并显式绑定到每个 QComboBox 上, 同时被 GLOBAL_STYLE 引用,
# 保证"某处下拉框"与"参数配置下拉框"永远不可能长得不一样。
# (Qt 在样式规则不含边框/背景时会退回原生绘制: 直角深色边框且弹出列表不走样式)
COMBO_STYLE = f"""
QComboBox {{
    background-color: {BG_INPUT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 4px 8px;
    min-height: 22px;
    /* 关键: main.py 里调用了 app.setStyle("Fusion"),
       Fusion 的 SH_ComboBox_Popup 为真, 弹出列表会走"菜单式"原生绘制,
       导致 QComboBox QAbstractItemView / ::item 的样式(行高/内边距/高亮色)全部失效,
       表现为弹出列表又矮又挤、选中项只剩一个细边框。
       强制 combobox-popup: 0 后用普通列表弹出, 下面这套弹出列表样式才会生效。 */
    combobox-popup: 0;
}}
QComboBox:hover, QComboBox:on {{
    border-color: {BORDER_FOCUS};
}}
QComboBox:focus {{
    border-color: {BORDER_FOCUS};
}}
QComboBox:disabled {{
    background-color: {BG_CARD};
    color: {TEXT_MUTED};
    border-color: {BORDER};
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 22px;
    border: none;
}}
QComboBox::down-arrow {{
    image: url({_DOWN_ARROW});
    width: 12px;
    height: 8px;
}}
/* 可编辑下拉框内部的编辑框: 去掉它自己的边框与内边距,
   否则文字会比普通下拉框多缩进一截, 两种下拉框看起来就不一致了 */
QComboBox QLineEdit {{
    background: transparent;
    border: none;
    padding: 0;
    margin: 0;
    color: {TEXT_PRIMARY};
}}
QComboBox QAbstractItemView {{
    background-color: {BG_INPUT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 4px;
    outline: 0;
    selection-background-color: {BG_HOVER};
    selection-color: {TEXT_PRIMARY};
}}
QComboBox QAbstractItemView::item {{
    padding: 6px 8px;
    min-height: 26px;
    border: none;
}}
QComboBox QAbstractItemView::item:selected,
QComboBox QAbstractItemView::item:hover {{
    color: {TEXT_PRIMARY};
    background-color: {BG_HOVER};
}}
"""

# 弹出菜单统一样式 (项目齿轮菜单 / 预设右键菜单 ... 全部走这一份).
# 原生 QMenu 在 Fusion 下是直角 + 深色描边 + 通栏蓝底高亮的"系统味",
# 和主界面的白色扁平风不搭, 这里统一成圆角菜单 + 内缩圆角高亮条。
# 注意: 要让 border-radius 真正露出来, 必须配合 prepare_menu() 去掉系统
# 边框并开透明背景, 否则四角会被不透明的窗口背景盖成白色方块。
MENU_STYLE = f"""
QMenu {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px;
}}
QMenu::item {{
    min-width: 132px;
    padding: 6px 18px 6px 14px;
    border-radius: 5px;
    color: {TEXT_PRIMARY};
    font-size: 13px;
}}
QMenu::item:selected {{
    background-color: {BG_HOVER};
    color: {ACCENT};
}}
QMenu::item:disabled {{
    background-color: transparent;
    color: {TEXT_MUTED};
}}
QMenu::separator {{
    height: 1px;
    background-color: #E8E8E8;
    margin: 5px 10px;
}}
"""

# 对话框 (新建/重命名/复制项目弹窗, 各种提示框) 的背景与文字色,
# 否则 Qt 默认的浅灰底和主界面纯白背景看着是两套东西。
DIALOG_STYLE = f"""
QDialog {{
    background-color: {BG_MAIN};
}}
QDialog QLabel {{
    color: {TEXT_PRIMARY};
    font-size: 13px;
}}
QDialog QPushButton {{
    min-width: 72px;
}}
/* 对话框的默认按钮(确定 / 是)给个蓝色强调, 否则和旁边的取消按钮一样是灰的,
   看不出哪个是回车会触发的动作 */
QDialog QPushButton:default {{
    background-color: {BG_PRIMARY};
    border-color: {BG_PRIMARY};
    color: {TEXT_BRIGHT};
    font-weight: 600;
}}
QDialog QPushButton:default:hover {{
    background-color: {BG_PRIMARY_HOVER};
    border-color: {BG_PRIMARY_HOVER};
}}
"""


def prepare_menu(menu):
    """把 QMenu 统一成主界面风格。

    QMenu 是独立的顶层弹窗, 不随父窗口继承样式表, 所以要显式套样式;
    另外 QSS 的圆角只有在窗口自己不画背景时才露得出来, 因此去掉系统
    边框与投影并打开透明背景, 否则圆角四角会顶着四个白色方块。
    """
    from PySide6.QtCore import Qt
    menu.setStyleSheet(MENU_STYLE)
    menu.setWindowFlags(menu.windowFlags()
                        | Qt.WindowType.FramelessWindowHint
                        | Qt.WindowType.NoDropShadowWindowHint)
    menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    return menu


GLOBAL_STYLE = f"""
QMainWindow {{
    background-color: {BG_MAIN};
    color: {TEXT_PRIMARY};
}}

QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    margin-top: 12px;
    padding: 12px 10px 10px 10px;
    background-color: {BG_PANEL};
    font-weight: 600;
    color: {TEXT_PRIMARY};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    color: {TEXT_PRIMARY};
    font-size: 13px;
}}

QLabel {{
    color: {TEXT_SECONDARY};
    background: transparent;
}}

QSpinBox, QLineEdit {{
    background-color: {BG_INPUT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 4px 8px;
    min-height: 22px;
}}
/* 数字框右侧箭头固定为独立宽度，输入内容不会被遮住。 */
QSpinBox {{
    padding-right: 20px;
}}
QSpinBox::up-button, QSpinBox::down-button {{
    subcontrol-origin: padding;
    width: 18px;
    /* 两段箭头无缝相接，总高度固定为控件内高。 */
    height: 12px;
    border: none;
    border-left: 1px solid {BORDER};
    background-color: {BG_CARD};
}}
QSpinBox::up-button {{
    subcontrol-position: top right;
    border-top-right-radius: 3px;
}}
QSpinBox::down-button {{
    subcontrol-position: bottom right;
    border-bottom-right-radius: 3px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
    background-color: {BG_HOVER};
}}
QSpinBox::up-button:pressed, QSpinBox::down-button:pressed {{
    background-color: {BG_ACTIVE};
}}
QSpinBox::up-arrow {{
    image: url({_UP_ARROW});
    width: 10px;
    height: 7px;
}}
QSpinBox::down-arrow {{
    image: url({_DOWN_ARROW});
    width: 10px;
    height: 7px;
}}
QSpinBox:hover, QLineEdit:hover {{
    border-color: {BORDER_FOCUS};
}}
QSpinBox:focus, QLineEdit:focus {{
    border-color: {BORDER_FOCUS};
}}
QSpinBox:disabled,
QLineEdit:disabled {{
    background-color: {BG_CARD};
    color: {TEXT_MUTED};
    border-color: {BORDER};
}}

{COMBO_STYLE}

{MENU_STYLE}

{DIALOG_STYLE}

QTextEdit {{
    background-color: {BG_INPUT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 6px;
    font-family: {FONT_MONO};
    font-size: 13px;
    selection-background-color: #C0E0FF;
}}
QTextEdit:focus {{
    border-color: {BORDER_FOCUS};
}}

QToolTip {{
    background-color: #FFFFFF;
    color: #263238;
    border: 1px solid #B8C3CF;
    border-radius: 6px;
    padding: 8px;
    font-family: "Microsoft YaHei UI";
    font-size: 10pt;
}}

QPushButton {{
    background-color: {BG_BUTTON};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 5px 14px;
    min-height: 26px;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {BG_BUTTON_HOVER};
    border-color: {BORDER_FOCUS};
}}
QPushButton:pressed {{
    background-color: {BG_ACTIVE};
}}
QPushButton:disabled {{
    background-color: {BG_CARD};
    color: {TEXT_MUTED};
    border-color: {BORDER};
}}

QPushButton#btn_connect {{
    background-color: {BG_PRIMARY};
    border-color: {BG_PRIMARY};
    color: {TEXT_BRIGHT};
    font-weight: 600;
    padding: 8px 24px;
    font-size: 14px;
}}
QPushButton#btn_connect:hover {{
    background-color: {BG_PRIMARY_HOVER};
    border-color: {BG_PRIMARY_HOVER};
}}
QPushButton#btn_connect[connected="true"] {{
    background-color: {BG_DANGER};
    border-color: {BG_DANGER};
}}
QPushButton#btn_connect[connected="true"]:hover {{
    background-color: {BG_DANGER_HOVER};
    border-color: {BG_DANGER_HOVER};
}}

QPushButton#btn_send {{
    background-color: {ACCENT};
    border-color: {ACCENT};
    color: #FFFFFF;
    font-weight: 600;
    padding: 8px 28px;
    font-size: 14px;
}}
QPushButton#btn_send:hover {{
    background-color: {BG_PRIMARY_HOVER};
}}

QPushButton.mode_btn {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    text-align: left;
    padding: 8px 12px;
    font-size: 13px;
    font-weight: 500;
    color: {TEXT_SECONDARY};
}}
QPushButton.mode_btn:hover {{
    background-color: {BG_HOVER};
    color: {TEXT_PRIMARY};
}}
QPushButton.mode_btn:checked {{
    background-color: {BG_HOVER};
    border-color: {ACCENT};
    color: {ACCENT};
    font-weight: 600;
}}

QCheckBox {{
    color: {TEXT_SECONDARY};
    spacing: 5px;
    background: transparent;
}}
QCheckBox:hover {{
    color: {TEXT_PRIMARY};
}}
QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    border-radius: 3px;
    border: 1px solid {BORDER};
    background-color: {BG_INPUT};
}}
QCheckBox::indicator:checked {{
    background-color: {BG_INPUT};
    border-color: {ACCENT};
    image: url({_CHECK_MARK});
}}
QCheckBox::indicator:checked:hover {{
    background-color: {BG_HOVER};
}}
QCheckBox::indicator:checked:disabled {{
    background-color: {BG_CARD};
    border-color: {BORDER};
    image: url({_CHECK_MARK_MUTED});
}}
QCheckBox::indicator:hover {{
    border-color: {BORDER_FOCUS};
}}
QCheckBox::indicator:disabled {{
    background-color: {BG_CARD};
    border-color: {BORDER};
}}
/* 放在 hover 之后：禁用控件即使被鼠标悬停也保持灰色。 */
QCheckBox:disabled {{
    color: {TEXT_MUTED};
}}

QFrame#separator {{
    background-color: {BORDER};
    max-height: 1px;
}}

QScrollBar:vertical {{
    background: {BG_CARD};
    width: 8px;
    margin: 0;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    min-height: 30px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical:hover {{
    background: {TEXT_MUTED};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QScrollBar:horizontal {{
    background: {BG_CARD};
    height: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER};
    min-width: 30px;
    border-radius: 4px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {TEXT_MUTED};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
    height: 0;
    border: none;
    background: transparent;
}}

QTableWidget {{
    background-color: {BG_INPUT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 4px;
    gridline-color: {BG_CARD};
    font-family: {FONT_MONO};
    font-size: 12px;
}}
QTableWidget::item {{
    padding: 3px 5px;
    border: none;
    border-bottom: 1px solid #EEF1F4;
}}
QTableWidget::item:selected {{
    background-color: {BG_HOVER};
}}
QTableWidget::indicator {{
    width: 15px;
    height: 15px;
    background-color: #FFFFFF;
    border: 1px solid #BFC5CC;
    border-radius: 0;
}}
QTableWidget::indicator:hover {{
    border-color: {BORDER_FOCUS};
}}
QTableWidget::indicator:checked {{
    background-color: #FFFFFF;
    border-color: #BFC5CC;
    image: url({_CHECK_MARK});
}}
QHeaderView::section {{
    background-color: {BG_PANEL};
    color: {TEXT_SECONDARY};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 4px 5px;
    font-size: 12px;
}}

QSplitter::handle {{
    background-color: {BORDER};
}}
"""

STATUS_BAR_STYLE = f"""
QStatusBar {{
    background-color: {BG_SIDEBAR};
    border-top: 1px solid {BORDER};
    color: {TEXT_SECONDARY};
    padding: 2px 8px;
    font-size: 12px;
}}
"""

SIDEBAR_STYLE = f"""
QWidget#sidebar {{
    background-color: {BG_SIDEBAR};
    border-right: 1px solid {BORDER};
}}
"""


