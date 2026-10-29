# -*- coding: utf-8 -*-
"""AnhuToolbox 统一弹窗 -- 提示、确认与文本输入。"""

from pathlib import Path

from PySide6.QtCore import Qt, QRectF, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QRegion
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout, QWidget,
)

DIALOG_WIDTH = 420
HEADER_HEIGHT = 48
RADIUS = 10
EDGE = 2
# 输入区外缘到分隔线、按钮区的视觉留白固定为 30px。
INPUT_CONTENT_GAP = 28
# 输入区在窗口中的固定预留：分隔线→内容→底栏。
INPUT_CONTENT_RESERVED = 107
STATUS_ICON = Path(__file__).resolve().parent / "assets" / "dialog_status.png"
STATUS_ICON_SIZE = 72
STATUS_ICON_FILES = {
    "warning": "dialog_status.png",
    "error": "dialog_error.png",
    "information": "dialog_status.png",
    "question": "dialog_question.png",
    "input": "dialog_question.png",
    "success": "dialog_success.png",
}

DIALOG_STYLE = """
QDialog#anhuDialog { background: transparent; }
QFrame#dialogCard { background: transparent; border: none; }
QFrame#dialogHeader { background: transparent; border: none; }
QLabel#dialogTitle {
    color: #354052; font-family: "Microsoft YaHei"; font-size: 21px;
    font-weight: 500; background: transparent; border: none;
}
QPushButton#dialogClose {
    min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px;
    padding: 0; border: none; border-radius: 4px; background: transparent;
    color: #66758A; font-family: "Segoe UI";
    font-size: 24px; font-weight: 300;
}
QPushButton#dialogClose:hover { background-color: #F1F3F6; color: #182230; }
QPushButton#dialogClose:pressed { background-color: #E7EBF0; }
QLabel#dialogMessage {
    color: #5C6573; font-family: "Microsoft YaHei"; font-size: 16px;
    background: transparent; border: none;
}
QLabel#dialogFieldLabel {
    color: #566276; font-family: "Microsoft YaHei"; font-size: 17px;
    background: transparent; border: none;
}
QLabel#dialogBadge {
    background-color: #FFFFFF; border: none;
}
QWidget#dialogFooter {
    background: transparent; border: none;
}
QWidget#dialogScroll { background: transparent; border: none; }
QWidget#dialogContentView { background: transparent; }
QLineEdit#dialogInput {
    background-color: #FFFFFF; color: #182230;
    font-family: "Microsoft YaHei"; font-size: 15px;
    border: 1px solid #CDD3DC; border-radius: 5px; padding: 7px 9px;
    min-height: 24px; selection-background-color: #CFE4FA;
}
QLineEdit#dialogInput:hover { border-color: #AEB9C7; }
QLineEdit#dialogInput:focus { border: 1px solid #0078D4; }
QPushButton#dialogPrimary {
    min-width: 86px; min-height: 32px; padding: 4px 17px;
    font-family: "Microsoft YaHei"; font-size: 15px; font-weight: 600;
    color: #FFFFFF; background-color: #0078D4; border: 1px solid #0078D4;
    border-radius: 5px;
}
QPushButton#dialogPrimary:hover {
    background-color: #106EBE; border-color: #106EBE;
}
QPushButton#dialogPrimary:pressed {
    background-color: #005A9E; border-color: #005A9E;
}
QPushButton#dialogPrimary:focus { border: 1px solid #005A9E; }
QPushButton#dialogPrimary:default {
    color: #FFFFFF; background-color: #0078D4; border: 1px solid #0078D4;
}
QPushButton#dialogSecondary {
    min-width: 86px; min-height: 32px; padding: 4px 17px;
    font-family: "Microsoft YaHei"; font-size: 15px;
    color: #354052; background-color: #FFFFFF;
    border: 1px solid #CDD3DC; border-radius: 5px;
}
QPushButton#dialogSecondary:hover {
    color: #182230; background-color: #F7F9FB; border-color: #AEB9C7;
}
QPushButton#dialogSecondary:pressed { background-color: #EEF1F5; }
QWidget#dialogFooter {
    background-color: #FFFFFF; border: none;
}
QPushButton#dialogSecondary:default {
    color: #354052; background-color: #FFFFFF; border: 1px solid #CDD3DC;
}
QPushButton#dialogDanger {
    min-width: 86px; min-height: 32px; padding: 4px 17px;
    font-family: "Microsoft YaHei"; font-size: 15px; font-weight: 600;
    color: #FFFFFF; background-color: #C42B1C; border: 1px solid #C42B1C;
    border-radius: 5px;
}
QPushButton#dialogDanger:hover {
    background-color: #A4262C; border-color: #A4262C;
}
QPushButton#dialogDanger:default {
    color: #FFFFFF; background-color: #C42B1C; border: 1px solid #C42B1C;
}
QScrollBar:vertical {
    background: #F5F7F9; width: 7px; border-radius: 3px;
}
QScrollBar::handle:vertical {
    background: #CDD3DC; min-height: 24px; border-radius: 3px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


def _app_icon():
    icon = QApplication.windowIcon()
    return icon if not icon.isNull() else QIcon()


def _badge(kind):
    """读取用户提供的状态 PNG；图片本身保持原样，不做符号重绘。"""
    filename = STATUS_ICON_FILES.get(kind, "dialog_information.png")
    pixmap = QPixmap(str(STATUS_ICON.parent / filename))
    if pixmap.isNull() and STATUS_ICON.is_file():
        pixmap = QPixmap(str(STATUS_ICON))
    if pixmap.isNull():
        # 在用户放入新图片前保留可用的兜底图片，避免弹窗不显示图标。
        pixmap = _app_icon().pixmap(256, 256)
    return pixmap


class AnhuDialog(QDialog):
    """统一弹窗；拖动顶部留白时可移动。"""

    def __init__(self, parent, title, message, kind="information",
                 input_text=None, buttons=None, default_button="primary"):
        super().__init__(parent)
        self.setObjectName("anhuDialog")
        self.setWindowTitle(title)
        self.setWindowIcon(_app_icon())
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        # 固定布局尺寸，窗口管理器和字体变化不能重新分配正文与按钮空间。
        self.setSizeGripEnabled(False)
        # 窗口背景保持透明，由卡片和窗口区域共同形成真正的圆角。
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setModal(True)
        self._drag_offset = None

        self._card = QFrame(self)
        self._card.setObjectName("dialogCard")
        self._card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._card.setAutoFillBackground(True)
        self._card.setStyleSheet(DIALOG_STYLE)
        # 卡片只承载标题与窗口背景，正文和底栏不能进入布局后重排。
        self._card.setAttribute(Qt.WidgetAttribute.WA_LayoutUsesWidgetRect, True)
        card_lo = QVBoxLayout(self._card)
        card_lo.setContentsMargins(0, 0, 0, 0)
        card_lo.setSpacing(0)
        header = QFrame()
        header.setObjectName("dialogHeader")
        header.setFixedHeight(HEADER_HEIGHT - 2)
        header_lo = QHBoxLayout(header)
        header_lo.setContentsMargins(18, 6, 14, 6)
        header_lo.setSpacing(6)
        app_mark = QLabel()
        app_mark.setFixedSize(32, 32)
        app_mark.setPixmap(_app_icon().pixmap(32, 32))
        app_mark.setStyleSheet("background:transparent;border:none;")
        header_lo.addWidget(app_mark)
        title_label = QLabel(title)
        title_label.setObjectName("dialogTitle")
        # 标题独立定位，按整个弹窗宽度居中，不受左侧应用图标影响。
        title_label.setParent(header)
        title_label.setGeometry(0, 1, DIALOG_WIDTH - 2 * EDGE,
                                HEADER_HEIGHT - 4)
        title_label.setAlignment(Qt.AlignmentFlag.AlignHCenter
                                 | Qt.AlignmentFlag.AlignVCenter)
        header_lo.addStretch(1)
        title_label.installEventFilter(self)
        close = QPushButton("×")
        self.close_button = close
        # 关闭按钮不参与默认焦点；Enter 仍交给下面的主操作。
        close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close.setObjectName("dialogClose")
        close.setToolTip("关闭")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.reject)
        header_lo.addWidget(close, 0, Qt.AlignmentFlag.AlignVCenter)
        # 标题按整条标题栏居中，不随左侧应用图标宽度偏移。
        header.installEventFilter(self)
        title_label.installEventFilter(self)
        card_lo.addWidget(header, 0, Qt.AlignmentFlag.AlignTop)
        self._header = header
        self._title_label = title_label

        # 提示正文是固定尺寸的单页；直接用普通 QWidget 承载，避免
        # 滚动视口在卡片刷新时裁掉圆形图片的底部。
        content = QWidget()
        content.setParent(self)
        content.setObjectName("dialogScroll")
        content.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # 正文控件只由下面的固定几何定位，绝不参与布局重排，
        # 否则图片会在最后一轮 show/polish 时被父控件裁掉。
        content_view = QWidget(content)
        content_view.setObjectName("dialogContentView")
        content_view.setGeometry(0, 0, DIALOG_WIDTH - 4 * EDGE, 67)
        content_view.setFixedSize(DIALOG_WIDTH - 4 * EDGE, 67)
        # 内容采用固定坐标，这样每轮刷新都不会在已计算的图标、
        # 文字位置上再次叠加内边距。
        badge = QLabel()
        badge.setObjectName("dialogBadge")
        badge.setStyleSheet("background:transparent; border:none;")
        badge.setFixedSize(STATUS_ICON_SIZE, STATUS_ICON_SIZE)
        badge.setScaledContents(True)
        # 不在这里加子级样式，避免覆盖弹窗的白底和边框规则。
        badge_frame = QFrame()
        # 图标仅作为内容容器内固定尺寸的控件。
        badge.setParent(badge_frame)
        self._badge_frame_size = STATUS_ICON_SIZE
        badge_frame.setFixedSize(self._badge_frame_size, self._badge_frame_size)
        badge_frame.setStyleSheet("background:transparent;border:none;")
        badge_frame.setParent(content_view)
        self._kind = kind
        self._badge = badge
        self._badge_frame = badge_frame
        self._set_badge()
        # 所有控件都由布局一次性给出固定尺寸；滚动区内部不自行重排。

        # 说明文字与输入框保持紧凑间距，定位在固定坐标中完成。
        self.input = None
        if input_text is not None:
            self.message_label = QLabel(message)
            self.message_label.setObjectName("dialogFieldLabel")
            self.message_label.setWordWrap(True)
            # 表单字段只在控件内部固定宽度；正文容器自适应弹窗，避免
            # QSS 的内边距叠加后挤压标签和输入框。
            self.message_label.setFixedSize(DIALOG_WIDTH - 145, 20)
            self.input = QLineEdit()
            self.input.setObjectName("dialogInput")
            self.input.setText(input_text)
            self.input.setFixedWidth(self.message_label.width())
            # 输入框边框与说明文字对齐；内容仍有正常缩进，不贴住边框。
            self.input.setStyleSheet(
                "QLineEdit#dialogInput { padding-left: 19px; }"
            )
            # 不沿用系统输入框的紧凑边距；文字区需独占独立高度。
            self.input.setFixedHeight(max(40, self.input.sizeHint().height()))
            self.input.returnPressed.connect(self.accept)
        else:
            self.message_label = QLabel()
            self.message_label.setObjectName("dialogMessage")
            self.message_label.setTextFormat(Qt.TextFormat.PlainText)
            self.message_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
            self.message_label.setWordWrap(True)
            # 像素字号不会随 Windows 的字号比例取整成 14px；
            # 中英文换行宽度与各电脑上的实际字号保持一致。
            message_font = self.message_label.font()
            message_font.setFamily("Microsoft YaHei")
            message_font.setPixelSize(16)
            self.message_label.setFont(message_font)
            # 固定换行宽度，较长的路径或异常文本不会撑宽整个弹窗。
            self.message_label.setFixedSize(DIALOG_WIDTH - 145, 36)
            self.message_label.setText(message)
            self.message_label.setMinimumHeight(0)
        self.message_label.setParent(content_view)
        if self.input is not None:
            self.input.setParent(content_view)
        self._content = content
        self._content_frame = content_view

        footer = QWidget()
        footer.setParent(self)
        footer.setFixedHeight(64)
        footer.setObjectName("dialogFooter")
        self._footer = footer
        footer_lo = QHBoxLayout(footer)
        # 底边保留足够留白，右下方按钮不会被控件刷新裁切。
        # 底部按钮完整着色需要可控的内部高度，避免 Qt 把默认按钮压出填充区域。
        footer_lo.setContentsMargins(22, 11, 22, 11)
        footer_lo.setSpacing(9)
        # 参考图中的按钮组相对正文左侧缩进约 50px。
        footer_lo.addSpacing(48)
        footer_lo.addStretch(1)
        self._buttons = []
        for text, role, result in buttons or [("确定", "primary", QDialog.DialogCode.Accepted)]:
            button = QPushButton(text)
            button.setFixedSize(122, 42)
            # 具体按钮样式直接绑定，避免不同 Windows / Fusion 样式刷新时吞掉 QSS 填充。
            button.setStyleSheet({
                "primary": "QPushButton{background-color:#0078D4;color:#FFFFFF;"
                           "border:1px solid #0078D4;border-radius:5px;font-size:15px;"
                           "font-weight:600;min-width:86px;min-height:32px;padding:4px 17px;}"
                           "QPushButton:hover{background-color:#106EBE;}"
                           "QPushButton:pressed{background-color:#005A9E;}",
                "danger": "QPushButton{background-color:#C42B1C;color:#FFFFFF;"
                          "border:1px solid #C42B1C;border-radius:5px;font-size:15px;"
                          "font-weight:600;min-width:86px;min-height:32px;padding:4px 17px;}"
                          "QPushButton:hover{background-color:#A4262C;}"
                          "QPushButton:pressed{background-color:#8A1A18;}",
                "secondary": "QPushButton{background-color:#FFFFFF;color:#354052;"
                             "border:1px solid #CDD3DC;border-radius:5px;font-size:15px;"
                             "min-width:86px;min-height:32px;padding:4px 17px;}"
                             "QPushButton:hover{background-color:#F7F9FB;border-color:#AEB9C7;}",
            }.get(role, "QPushButton{background:#FFFFFF;color:#354052;}"))
            button.setObjectName({
                "primary": "dialogPrimary", "danger": "dialogDanger",
            }.get(role, "dialogSecondary"))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, value=result: self.done(value))
            footer_lo.addWidget(button)
            self._buttons.append(button)
            if role == default_button:
                button.setDefault(True)
                button.setAutoDefault(True)
                button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            else:
                button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._adjust_size()
        self._center_on_parent()
        self.setFocus()

    def _adjust_size(self):
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        self.message_label.ensurePolished()
        available = max(120, self.message_label.width() - 4)
        text_height = self.message_label.heightForWidth(available)
        self.message_label.setFixedHeight(max(20 if self.input is not None else 24, text_height))
        self.message_label.adjustSize()
        text_height = self.message_label.height()
        if self.input is not None:
            body_height = INPUT_CONTENT_RESERVED
        else:
            # 提示按图标外缘和文字显示范围计算。标准提示高度保持不变；
            # 多行正文需要向下扩展时，在固定几何中完成。
            body_height = min(max(132, text_height + 32), 300)
        target_height = HEADER_HEIGHT + body_height + 68
        # 避免按钮被挤出可见屏幕；常见错误提示均能完整显示。
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            target_height = min(target_height, 480, screen.availableGeometry().height() - 40)
        self.setFixedSize(DIALOG_WIDTH, target_height)
        self._card.setGeometry(EDGE, EDGE, DIALOG_WIDTH - 2 * EDGE,
                               target_height - 2 * EDGE)
        # 正文和底栏直接固定到窗口网格，QHBoxLayout/QVBoxLayout 不再
        # 在 show() 后的最后一轮 polish 中移动图标。
        self._footer.setGeometry(2, target_height - 70,
                                 DIALOG_WIDTH - 4, 68)
        self._content.setGeometry(EDGE, HEADER_HEIGHT + EDGE,
                                  DIALOG_WIDTH - 4 * EDGE,
                                  target_height - HEADER_HEIGHT - EDGE - 68)
        self._footer_layout_top = target_height - 70 + 11
        self._footer_y = target_height - 70
        self._content_y = HEADER_HEIGHT + EDGE
        self._footer_visible_top = target_height - 70
        self._separator_y = HEADER_HEIGHT + EDGE
        if self.input is not None:
            self._content.setFixedHeight(67)
            self._content_frame.setFixedHeight(67)
        else:
            self._content.setMinimumHeight(0)
            self._content.setMaximumHeight(16777215)
        self._header.raise_()
        self._content.raise_()
        self._footer.raise_()
        if self.input is None:
            # 图标按实际可见边界居中，图片本身的外沿空隙不计入留白。
            self._notice_top = 10
            content_height = min(max(STATUS_ICON_SIZE + 20,
                                     text_height + 20), 300)
            self._content.setGeometry(EDGE, self._content_y,
                                      DIALOG_WIDTH - 4 * EDGE, content_height)
            self._notice_frame_height = content_height
            self._notice_bottom = self._content.y() + self._content.height()
            self._content.setFixedHeight(content_height)
            self._content_frame.setGeometry(0, 0, DIALOG_WIDTH - 4 * EDGE,
                                            content_height)
            self._content_frame.setFixedSize(DIALOG_WIDTH - 4 * EDGE,
                                             content_height)
        else:
            # 输入框只在分隔线和按钮之间排布。
            self._notice_top = 28
            content_height = (67 if self.input is not None
                              else target_height - INPUT_CONTENT_RESERVED)
            self._content.setGeometry(2, 50, DIALOG_WIDTH - 4 * EDGE,
                                      target_height - 2 - 50 - 68)
            self._content_frame.setGeometry(0, 0, DIALOG_WIDTH - 4 * EDGE,
                                            content_height)
            self._notice_frame_height = self._content.height()
            self._notice_bottom = self._content.y() + self._content.height()
        # 图标和文字使用固定几何，避免布局管理器再次覆盖居中位置。
        self._complete_badge_geometry()
        self._title_label.setGeometry(0, 1, DIALOG_WIDTH - 2 * EDGE,
                                      HEADER_HEIGHT - 4)
        self._header.setGeometry(0, 0, DIALOG_WIDTH - 2 * EDGE,
                                 HEADER_HEIGHT - 2 * EDGE)


    def _center_on_parent(self):
        screen = self.screen() or QApplication.primaryScreen()
        parent = self.parentWidget()
        if parent is not None and parent.isVisible():
            center = parent.window().frameGeometry().center()
        elif screen is not None:
            center = screen.availableGeometry().center()
        else:
            return
        frame = self.frameGeometry()
        frame.moveCenter(center)
        self.move(frame.topLeft())

    def _set_badge(self):
        """重新生成徽标图像，避免窗口重建把它当成空图标。"""
        self._badge.clear()
        self._badge.setPixmap(_badge(self._kind).scaled(
            STATUS_ICON_SIZE, STATUS_ICON_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))

    def eventFilter(self, watched, event):
        if event.type() == event.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            return True
        if event.type() == event.Type.MouseMove and self._drag_offset is not None:
            if event.buttons() & Qt.MouseButton.LeftButton:
                self.move(event.globalPosition().toPoint() - self._drag_offset)
            return True
        if event.type() == event.Type.MouseButtonRelease:
            self._drag_offset = None
            return True
        return super().eventFilter(watched, event)

    def showEvent(self, event):
        super().showEvent(event)
        self._center_on_parent()
        # 无边框窗口显示前可能尚未建立系统焦点，等事件循环启动后聚焦。
        QTimer.singleShot(0, self._finalize_badge_geometry)
        QTimer.singleShot(0, self._focus_default)

    def _finalize_badge_geometry(self):
        """窗口建立后按最终宽高重排一次，防止布局管理器覆盖中线位置。"""
        self._complete_badge_geometry()

    def _focus_default(self):
        if self.input is not None:
            self.input.selectAll()
            self.input.setFocus()
        else:
            for button in self._buttons:
                if button.isDefault():
                    button.setFocus()
                    break

    def keyPressEvent(self, event):
        # 文本选择框可能吞掉 Esc，无边框弹窗必须自己保证可关闭。
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event):
        # 圆角和卡片由窗口统一绘制；图标和文字的位置由固定网格计算。
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#FFFFFF"))
        outline = QPainterPath()
        outline.addRoundedRect(
            QRectF(self.rect()).adjusted(1, 1, -1, -1), RADIUS, RADIUS
        )
        painter.fillPath(outline, QColor("#FFFFFF"))
        # 标题区域浅灰，与参考图一致；圆角仍由整张卡片的路径统一裁切。
        header_fill = QPainterPath()
        header_fill.addRect(QRectF(EDGE, EDGE, self.width() - 2 * EDGE, HEADER_HEIGHT))
        painter.fillPath(header_fill.intersected(outline), QColor("#F7F8FA"))
        painter.setPen(QPen(QColor("#BEC7D3"), 1.2))
        painter.drawPath(outline)
        painter.setPen(QColor("#E2E6EC"))
        y = HEADER_HEIGHT + EDGE
        painter.drawLine(10, y, self.width() - 10, y)
        painter.end()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 窗口本身也裁成圆角，避免窗口合成在透明边角填充黑色的矩形底。
        shape = QPainterPath()
        shape.addRoundedRect(QRectF(self.rect()), RADIUS + EDGE, RADIUS + EDGE)
        self.setMask(QRegion(shape.toFillPolygon().toPolygon()))
        self._card.setGeometry(EDGE, EDGE, self.width() - 2 * EDGE,
                               self.height() - 2 * EDGE)
        # 无边框窗口重建后重新套用完整样式，避免关闭按钮和徽标退回系统绘制。
        # 焦点状态也明确设置文字颜色，避免父级 QSS 重绘后输入文字与
        # 选框背景同色，看起来像内容被压缩或消失。
        self._card.setStyleSheet(DIALOG_STYLE.replace(
            "QLineEdit#dialogInput:focus { border: 1px solid #0078D4; }",
            "QLineEdit#dialogInput:focus {"
            " color: #182230; background-color: #FFFFFF;"
            " border: 1px solid #0078D4;"
            " selection-color: #182230; selection-background-color: #CFE4FA; }",
        ))
        # 尺寸变化后重新生成清晰徽标。
        self._set_badge()
        QTimer.singleShot(0, self._complete_badge_geometry)

    def _align_layout_badge(self, content_width, content_height):
        """在固定网格内放置图标和内容，保证中线及两行文字的间距不变。"""
        self._content_layout_size = (content_width, content_height)
        self._complete_badge_geometry()

    def _complete_badge_geometry(self):
        """分别排列输入版与纯提示版，修改其中一种不会影响另一种。"""
        if self.input is not None:
            self._layout_input_geometry()
        else:
            self._layout_notice_geometry()

    def _layout_input_geometry(self):
        """输入版：图标与说明、输入框在正文区内等距排列。"""
        if self._badge_frame.width() != STATUS_ICON_SIZE:
            self._badge_frame.setFixedSize(STATUS_ICON_SIZE, STATUS_ICON_SIZE)
        self._content_frame.setGeometry(0, 0, DIALOG_WIDTH - 4 * EDGE, 67)
        self.message_label.setParent(self)
        self.input.setParent(self)
        self._badge_frame.setParent(self)
        self._badge.setParent(self._badge_frame)
        icon_left = 18
        label_left = icon_left + STATUS_ICON_SIZE + 12
        sep_y = self._separator_y
        button_top = self._footer_layout_top
        icon_top = sep_y + INPUT_CONTENT_GAP + 1
        input_bottom = button_top - INPUT_CONTENT_GAP - 1
        input_top = input_bottom - self.input.height() + 1
        label_height = self.message_label.fontMetrics().height()
        label_top = input_top - 4 - label_height
        self._badge.setGeometry(0, 0, STATUS_ICON_SIZE, STATUS_ICON_SIZE)
        self._badge_frame.setGeometry(
            icon_left, icon_top, STATUS_ICON_SIZE, STATUS_ICON_SIZE
        )
        self.message_label.setGeometry(
            label_left, label_top, self.message_label.width(), label_height
        )
        self.input.setGeometry(
            label_left, input_top, self.input.width(), self.input.height()
        )
        self._badge.show()
        self._badge.raise_()

    def _layout_notice_geometry(self):
        """纯提示版：图标中心严格跟随文字块的对齐行。"""
        if self._badge_frame.width() != STATUS_ICON_SIZE:
            self._badge_frame.setFixedSize(STATUS_ICON_SIZE, STATUS_ICON_SIZE)
        content_width = DIALOG_WIDTH - 4 * EDGE
        content_height = self._notice_frame_height
        self._content_frame.setGeometry(0, 0, content_width, content_height)
        self.message_label.setParent(self._content_frame)
        self._badge_frame.setParent(self._content_frame)
        self._badge.setParent(self._badge_frame)
        icon_left = 18
        label_left = icon_left + STATUS_ICON_SIZE + 12
        label_height = self.message_label.fontMetrics().height()
        line_count = max(1, round(self.message_label.height() / label_height))
        # QLabel 的文字基线略低于控件坐标，按最终字号校正中线。
        if line_count == 1:
            line_center = INPUT_CONTENT_GAP + STATUS_ICON_SIZE / 2 - 2
            label_top = round(line_center - label_height / 2)
        elif line_count == 2:
            label_top = round(INPUT_CONTENT_GAP + STATUS_ICON_SIZE / 2
                              - label_height / 2 - 1)
            line_center = label_top + label_height - 1
        else:
            # 图标与第二行的文字中心线对齐。
            label_top = round(INPUT_CONTENT_GAP + STATUS_ICON_SIZE / 2
                              - label_height - 2)
            line_center = label_top + label_height * 1.5 - 2
        # 无输入框弹窗与输入框弹窗使用相同的 28px 外缘留白：
        # 分隔线 → 图标顶部，以及图标底部 → 按钮顶部。
        icon_top = INPUT_CONTENT_GAP
        icon_bottom = icon_top + STATUS_ICON_SIZE
        # 分离的两版布局仍共用卡片底栏；多行正文会向下延展内容区域，
        # 避免正文或状态图片被 132px 的正文帧截断。
        required_height = max(icon_bottom + INPUT_CONTENT_GAP,
                              icon_top - 4 + self.message_label.height() + 10)
        if required_height > content_height:
            self._notice_frame_height = required_height
            content_height = required_height
            self._content.setFixedHeight(content_height)
            self._content_frame.setFixedSize(content_width, content_height)
            self._footer.setGeometry(
                EDGE, HEADER_HEIGHT + EDGE + content_height,
                DIALOG_WIDTH - 4 * EDGE, 68,
            )
            self._footer_layout_top = (
                HEADER_HEIGHT + EDGE + content_height + 11
            )
        label_bottom = label_top + self.message_label.height()
        if label_bottom > content_height - 10:
            label_top = max(16, label_top - (label_bottom - content_height + 10))
        self._badge.setGeometry(0, 0, STATUS_ICON_SIZE, STATUS_ICON_SIZE)
        self._badge_frame.setGeometry(
            icon_left, icon_top, STATUS_ICON_SIZE, STATUS_ICON_SIZE
        )
        self.message_label.setGeometry(
            label_left, label_top, content_width - label_left - 22,
            self.message_label.height()
        )
        self._badge.show()
        self._badge.raise_()
        self._text_block_geometry = (
            label_left, label_top, content_width - label_left - 22
        )

    def show(self):
        """先完成布局再显示，避免系统第一帧跳动。"""
        self._complete_badge_geometry()
        return super().show()


def _show(parent, title, message, kind, buttons=None, default_button="primary"):
    text = str(message).rstrip()
    # 提示正文统一使用中文感叹号；重复打开也不会叠加中文标点。
    if text:
        # 错误详情中即使已有换行，也只在最末尾补一个中文标点。
        text = text.rstrip("!！") + "！"
    dialog = AnhuDialog(parent, title, text, kind, buttons=buttons,
                        default_button=default_button)
    return dialog.exec()


def show_information(parent, title, message):
    return _show(parent, title, message, "information")


def show_success(parent, title, message):
    return _show(parent, title, message, "success")


def show_warning(parent, title, message):
    return _show(parent, title, message, "warning")


def show_error(parent, title, message):
    return _show(parent, title, message, "error")


def ask_yes_no(parent, title, message, confirm_text="确定", danger=False):
    """确认框使用动作名称，关闭/取消都明确返回 False。"""
    result = _show(
        parent, title, message, "question",
        buttons=[("取消", "secondary", QDialog.DialogCode.Rejected),
                 (confirm_text, "danger" if danger else "primary",
                  QDialog.DialogCode.Accepted)],
    )
    return result == QDialog.DialogCode.Accepted


def get_text(parent, title, label, text=""):
    """文本输入框；返回 (text, ok)，兼容 QInputDialog.getText。"""
    label = str(label).rstrip().rstrip("!！") + "！"
    dialog = AnhuDialog(
        parent, title, label, "input", input_text=text,
        buttons=[("取消", "secondary", QDialog.DialogCode.Rejected),
                 ("确定", "primary", QDialog.DialogCode.Accepted)],
    )
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    return dialog.input.text(), accepted
