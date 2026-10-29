# -*- coding: utf-8 -*-
"""AnhuToolbox 实用工具集: 时间戳转换 / 二维码生成 / JSON美化 / 进制转换"""

import io, os, json, re, zipfile, time
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QScrollArea, QLayout,
    QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox,
    QGroupBox, QGridLayout, QFileDialog, QApplication,
    QGraphicsOpacityEffect,
    QFrame, QStackedWidget, QButtonGroup
)
from PySide6.QtCore import (
    Qt, QTimer, QRect, QSize, QPropertyAnimation, QAbstractAnimation
)
from PySide6.QtGui import QFont, QPixmap, QImage, QColor, QTextCharFormat

from . import hardware
from . import toolbox
from .styles import COMBO_STYLE
from .dialogs import show_error, show_information, show_success


# ============================================================
#  时间戳转换工具
# ============================================================
class TimestampTool(QWidget):
    def __init__(self):
        super().__init__()
        self._build()

    def _build(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(16, 16, 16, 16)
        lo.setSpacing(12)

        title = QLabel("时间戳转换工具")
        title.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        lo.addWidget(title)

        # 当前时间
        g1 = QGroupBox("当前时间")
        g1lo = QGridLayout(g1)
        self._lbl_now_dt = QLineEdit(); self._lbl_now_dt.setReadOnly(True)
        self._lbl_now_ts = QLineEdit(); self._lbl_now_ts.setReadOnly(True)
        self._lbl_now_ms = QLineEdit(); self._lbl_now_ms.setReadOnly(True)
        g1lo.addWidget(QLabel("日期时间:"), 0, 0); g1lo.addWidget(self._lbl_now_dt, 0, 1)
        g1lo.addWidget(QLabel("时间戳(秒):"), 1, 0); g1lo.addWidget(self._lbl_now_ts, 1, 1)
        g1lo.addWidget(QLabel("时间戳(毫秒):"), 2, 0); g1lo.addWidget(self._lbl_now_ms, 2, 1)
        lo.addWidget(g1)

        # 时间戳 → 日期
        g2 = QGroupBox("时间戳 → 日期时间")
        g2lo = QGridLayout(g2)
        self._ts_input = QLineEdit()
        self._ts_input.setPlaceholderText("输入时间戳(秒或毫秒)")
        self._ts_input.textChanged.connect(self._on_ts_input)
        self._ts_result = QLineEdit(); self._ts_result.setReadOnly(True)
        g2lo.addWidget(QLabel("时间戳:"), 0, 0); g2lo.addWidget(self._ts_input, 0, 1)
        g2lo.addWidget(QLabel("结果:"), 1, 0); g2lo.addWidget(self._ts_result, 1, 1)
        lo.addWidget(g2)

        # 日期 → 时间戳
        g3 = QGroupBox("日期时间 → 时间戳")
        g3lo = QGridLayout(g3)
        self._dt_input = QLineEdit()
        self._dt_input.setPlaceholderText("例如: 2026-08-03 14:30:00")
        self._dt_input.textChanged.connect(self._on_dt_input)
        self._dt_ts = QLineEdit(); self._dt_ts.setReadOnly(True)
        self._dt_ms = QLineEdit(); self._dt_ms.setReadOnly(True)
        g3lo.addWidget(QLabel("日期时间:"), 0, 0); g3lo.addWidget(self._dt_input, 0, 1)
        g3lo.addWidget(QLabel("时间戳(秒):"), 1, 0); g3lo.addWidget(self._dt_ts, 1, 1)
        g3lo.addWidget(QLabel("时间戳(毫秒):"), 2, 0); g3lo.addWidget(self._dt_ms, 2, 1)
        lo.addWidget(g3)

        lo.addStretch()

        self._tick_timer = QTimer()
        self._tick_timer.timeout.connect(self._update_now)
        self._tick_timer.start(200)

    def _update_now(self):
        try:
            now = datetime.now()
            self._lbl_now_dt.setText(now.strftime("%Y-%m-%d %H:%M:%S"))
            self._lbl_now_ts.setText(str(int(now.timestamp())))
            self._lbl_now_ms.setText(str(int(now.timestamp() * 1000)))
        except (KeyboardInterrupt, RuntimeError):
            pass
    def _on_ts_input(self):
        s = self._ts_input.text().strip()
        if not s:
            self._ts_result.setText("")
            return
        try:
            ts = int(s)
            if ts > 1e15:
                ts = ts // 1000
            dt = datetime.fromtimestamp(ts)
            self._ts_result.setText(dt.strftime("%Y-%m-%d %H:%M:%S"))
        except Exception:
            self._ts_result.setText("格式错误")

    def _on_dt_input(self):
        s = self._dt_input.text().strip()
        if not s:
            self._dt_ts.setText(""); self._dt_ms.setText("")
            return
        for fmt in ["%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S",
                     "%Y-%m-%d", "%Y/%m/%d"]:
            try:
                dt = datetime.strptime(s, fmt)
                ts = int(dt.timestamp())
                self._dt_ts.setText(str(ts))
                self._dt_ms.setText(str(ts * 1000))
                return
            except ValueError:
                yuan_text = yuan_text[yuan_index + 2:]
                break
        self._dt_ts.setText("格式错误"); self._dt_ms.setText("格式错误")

    def stop_timer(self):
        self._tick_timer.stop()


# ============================================================
#  二维码批量生成工具
# ============================================================
class FlowLayout(QLayout):
    """简易流式布局：从左到右自动换行"""
    def __init__(self, parent=None, margin=0, spacing=10):
        super().__init__(parent)
        self._items = []
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._doLayout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._doLayout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for item in self._items:
            s = s.expandedTo(item.minimumSize())
        return s

    def _doLayout(self, rect, testOnly):
        x, y = rect.x(), rect.y()
        line_h = 0
        sp = self.spacing()
        right = rect.right()

        for item in self._items:
            sz = item.sizeHint()
            if x + sz.width() > right and line_h > 0:
                x = rect.x()
                y += line_h + sp
                line_h = 0
            if not testOnly:
                item.setGeometry(QRect(x, y, sz.width(), sz.height()))
            x += sz.width() + sp
            line_h = max(line_h, sz.height())
        return y + line_h - rect.y()


class QRTool(QWidget):
    """二维码批量生成：固定2行6列隐框网格，二维码填入对应格子"""
    ROWS, COLS = 2, 5

    def __init__(self):
        super().__init__()
        self._lines = []
        self._cells = []
        self._build()

    def _build(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        top = QWidget()
        top.setStyleSheet("QWidget{background:#FFF;border-bottom:1px solid #E0E0E0}")
        top_lo = QVBoxLayout(top)
        top_lo.setContentsMargins(20, 16, 20, 12)
        top_lo.setSpacing(8)

        title = QLabel("二维码生成工具")
        title.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        top_lo.addWidget(title)

        self._qr_input = QPlainTextEdit()
        self._qr_input.setPlaceholderText("每行一个文本，对应一个二维码...")
        self._qr_input.setMaximumHeight(70)
        self._qr_input.setStyleSheet(
            "QPlainTextEdit{background:#FFF;border:1px solid #D0D0D0;border-radius:4px;padding:6px}"
        )
        top_lo.addWidget(self._qr_input)

        btns = QHBoxLayout()
        self._btn_gen = QPushButton("生成预览")
        self._btn_gen.clicked.connect(self._generate)
        self._btn_gen.setStyleSheet(
            "QPushButton{background:#0078D4;color:#FFF;border:none;border-radius:4px;"
            "padding:6px 20px;font-weight:600}QPushButton:hover{background:#106EBE}"
        )
        btns.addWidget(self._btn_gen)
        self._btn_save = QPushButton("批量保存")
        self._btn_save.clicked.connect(self._batch_save)
        btns.addWidget(self._btn_save)
        btns.addStretch()
        self._lbl_qr_count = QLabel("")
        self._lbl_qr_count.setStyleSheet("color:#666;font-size:12px")
        btns.addWidget(self._lbl_qr_count)
        top_lo.addLayout(btns)
        lo.addWidget(top)

        # 计算单元格基准尺寸：基于 box_size 估算单格宽度
        # 短文本版本1二维码：21模块, border=2 -> (21+4)*box_size
        self._cell_img_size = (21 + 4) * 12

        # 网格容器，行数按需动态创建
        self._grid_widget = QWidget()
        self._grid_widget.setStyleSheet("QWidget{background:#FFF}")
        self._grid = QGridLayout(self._grid_widget)
        self._grid.setContentsMargins(12, 12, 12, 12)
        self._grid.setSpacing(0)
        # 5 列均分
        for c in range(self.COLS):
            self._grid.setColumnStretch(c, 1)

        # 初始绘制 2 行空格子
        self._rebuild_grid(2)

        # 外层居中包裹
        wrapper = QWidget()
        wrapper.setStyleSheet("QWidget{background:#FFF}")
        wl = QHBoxLayout(wrapper)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.addStretch()
        wl.addWidget(self._grid_widget)
        wl.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(wrapper)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{background:#FFF;border:none}")
        lo.addWidget(scroll, stretch=1)

    def _rebuild_grid(self, rows):
        """清空网格并按指定行数重建单元格"""
        # 清除旧格子
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._cells = []
        for r in range(rows):
            row_cells = []
            for c in range(self.COLS):
                cell = self._make_empty_cell()
                self._grid.addWidget(cell, r, c)
                row_cells.append(cell)
            self._cells.append(row_cells)

    def _make_empty_cell(self):
        """空白格子：结构与 QR 格子一致，用同尺寸占位图保证等宽"""
        cell = QWidget()
        cell.setStyleSheet(
            "QWidget{background:#FFF;border:1px solid #D0D0D0}"
        )
        cl = QVBoxLayout(cell)
        cl.setContentsMargins(6, 4, 6, 6)
        cl.setSpacing(2)
        placeholder = QLabel()
        placeholder.setFixedHeight(34)
        placeholder.setStyleSheet("border:none;background:transparent")
        cl.addWidget(placeholder)
        # 生成与 QR 同尺寸的透明占位图
        dummy = QPixmap(self._cell_img_size, self._cell_img_size)
        dummy.fill(Qt.transparent)
        spacer = QLabel()
        spacer.setPixmap(dummy)
        spacer.setAlignment(Qt.AlignCenter)
        spacer.setStyleSheet("border:none;background:transparent")
        cl.addWidget(spacer, 0, Qt.AlignCenter)
        cl.addStretch()
        return cell

    def _make_qr_cell(self, text, pixmap, error=None):
        """带二维码的格子：QR 图自适应缩放居中；生成失败时显示错误原因"""
        cell = QWidget()
        cell.setStyleSheet(
            "QWidget{background:#FFF;border:1px solid #D0D0D0}"
        )
        cl = QVBoxLayout(cell)
        cl.setContentsMargins(6, 4, 6, 6)
        cl.setSpacing(2)

        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("color:#333;font-size:14px;font-weight:600;border:none;background:transparent")
        lbl.setWordWrap(True)
        lbl.setFixedHeight(34)
        cl.addWidget(lbl)

        if pixmap:
            ql = QLabel()
            ql.setPixmap(pixmap)
            ql.setAlignment(Qt.AlignCenter)
            ql.setStyleSheet("border:none;background:transparent")
            cl.addWidget(ql, 0, Qt.AlignCenter)
        elif error:
            el = QLabel("生成失败\n" + error)
            el.setAlignment(Qt.AlignCenter)
            el.setWordWrap(True)
            el.setStyleSheet("color:#C0392B;font-size:12px;border:none;background:transparent")
            cl.addWidget(el, 0, Qt.AlignCenter)
        cl.addStretch()

        return cell

    def _generate(self):
        text = self._qr_input.toPlainText().strip()
        self._lines = [l.strip() for l in text.split("\n") if l.strip()]

        n = len(self._lines)
        if n == 0:
            self._rebuild_grid(2)
            self._lbl_qr_count.setText("")
            return

        # 动态行数：至少 2 行，多出的向上取整
        rows = max(2, (n + self.COLS - 1) // self.COLS)
        self._rebuild_grid(rows)

        # 填入二维码
        fail = 0
        for i, line in enumerate(self._lines):
            pix, err = self._make_qr_pixmap(line)
            if err:
                fail += 1
            cell = self._make_qr_cell(line, pix, err)
            r, c = i // self.COLS, i % self.COLS
            old_w = self._grid.itemAtPosition(r, c)
            if old_w:
                w = old_w.widget()
                if w:
                    w.deleteLater()
            self._grid.addWidget(cell, r, c)

        if fail:
            self._lbl_qr_count.setText(f"共 {n} 条，失败 {fail} 条")
        else:
            self._lbl_qr_count.setText(f"共 {n} 条")


    def _make_qr_pixmap(self, text):
        """生成二维码，返回 (QPixmap 或 None, 错误信息或 None)"""
        import qrcode
        try:
            qr = qrcode.QRCode(box_size=12, border=2)
            qr.add_data(text); qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buf = io.BytesIO(); img.save(buf, "PNG"); buf.seek(0)
            qimg = QImage.fromData(buf.read())
            return QPixmap.fromImage(qimg), None
        except Exception as e:
            return None, str(e)

    def _batch_save(self):
        import qrcode
        if not self._lines:
            show_information(self, "提示", "请先生成预览")
            return
        path_, _ = QFileDialog.getSaveFileName(
            self, "保存二维码 ZIP", "QR码.zip", "ZIP 文件 (*.zip)"
        )
        if not path_:
            return
        count = 0
        fail = 0
        errs = []
        try:
            with zipfile.ZipFile(path_, "w", zipfile.ZIP_DEFLATED) as zf:
                for i, line in enumerate(self._lines):
                    try:
                        qr = qrcode.QRCode(box_size=12, border=2)
                        qr.add_data(line); qr.make(fit=True)
                        img = qr.make_image(fill_color="black", back_color="white")
                        buf = io.BytesIO()
                        img.save(buf, "PNG")
                        fname = f"QR_{i+1:03d}.png"
                        zf.writestr(fname, buf.getvalue())
                        count += 1
                    except Exception as e:
                        fail += 1
                        errs.append(f"第 {i+1} 条: {e}")
            msg = f"已打包 {count} 张二维码到:\n{path_}"
            if fail:
                msg += f"\n\n{fail} 条生成失败:\n" + "\n".join(errs[:5])
                if fail > 5:
                    msg += f"\n... 共 {fail} 条"
            show_success(self, "完成", msg)
        except Exception as e:
            show_error(self, "错误", f"保存失败: {e}")

class JsonTool(QWidget):
    """JSON 格式化工具"""
    def __init__(self):
        super().__init__()
        self._build()

    def _build(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(16, 16, 16, 16)
        lo.setSpacing(10)

        title = QLabel("JSON 格式化工具")
        title.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        lo.addWidget(title)

        btns = QHBoxLayout()
        self._btn_format = QPushButton("格式化")
        self._btn_format.clicked.connect(self._format)
        btns.addWidget(self._btn_format)
        self._btn_compress = QPushButton("压缩")
        self._btn_compress.clicked.connect(self._compress)
        btns.addWidget(self._btn_compress)
        btns.addStretch()
        self._json_status = QLabel("")
        btns.addWidget(self._json_status)
        lo.addLayout(btns)

        body = QHBoxLayout()
        # 输入
        self._json_input = QPlainTextEdit()
        self._json_input.setPlaceholderText("粘贴 JSON 文本...")
        self._json_input.setFont(QFont("Consolas", 10))
        body.addWidget(self._json_input)
        # 输出
        self._json_output = QPlainTextEdit()
        self._json_output.setReadOnly(True)
        self._json_output.setFont(QFont("Consolas", 10))
        body.addWidget(self._json_output)
        lo.addLayout(body, stretch=1)

    def _format(self):
        raw = self._json_input.toPlainText().strip()
        if not raw:
            return
        try:
            obj = json.loads(raw)
            formatted = json.dumps(obj, ensure_ascii=False, indent=2)
            self._json_output.setPlainText(formatted)
            self._json_status.setText("✓ 格式化成功")
            self._json_status.setStyleSheet("color:#107C10")
        except json.JSONDecodeError as e:
            self._json_output.setPlainText(f"JSON 解析错误:\n{e}")
            self._json_status.setText("✗ 格式错误")
            self._json_status.setStyleSheet("color:#D13438")

    def _compress(self):
        raw = self._json_input.toPlainText().strip()
        if not raw:
            return
        try:
            obj = json.loads(raw)
            compressed = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
            self._json_output.setPlainText(compressed)
            self._json_status.setText("✓ 压缩成功")
            self._json_status.setStyleSheet("color:#107C10")
        except json.JSONDecodeError as e:
            self._json_output.setPlainText(f"JSON 解析错误:\n{e}")
            self._json_status.setText("✗ 格式错误")
            self._json_status.setStyleSheet("color:#D13438")


# ============================================================
#  进制转换工具
# ============================================================
class BaseTool(QWidget):
    def __init__(self):
        super().__init__()
        self._build()

    def _build(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(16, 16, 16, 16)
        lo.setSpacing(12)

        title = QLabel("进制转换工具")
        title.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        lo.addWidget(title)

        # 输入
        inp = QHBoxLayout()
        inp.addWidget(QLabel("输入:"))
        self._base_input = QLineEdit()
        self._base_input.setPlaceholderText("输入数值...")
        self._base_input.textChanged.connect(self._convert)
        inp.addWidget(self._base_input, stretch=1)
        inp.addWidget(QLabel("进制:"))
        self._base_from = QComboBox()
        for b in [2, 8, 10, 16]:
            self._base_from.addItem(str(b), b)
        self._base_from.setCurrentText("10")
        self._base_from.currentIndexChanged.connect(self._convert)
        inp.addWidget(self._base_from)
        lo.addLayout(inp)

        # 结果
        g = QGroupBox("转换结果")
        glo = QGridLayout(g)
        self._results = {}
        bases = [("BIN (2)", 2), ("OCT (8)", 8), ("DEC (10)", 10), ("HEX (16)", 16)]
        for r, (label, base) in enumerate(bases):
            glo.addWidget(QLabel(label + ":"), r, 0)
            le = QLineEdit(); le.setReadOnly(True)
            le.setFont(QFont("Consolas", 11))
            glo.addWidget(le, r, 1)
            self._results[base] = le
        lo.addWidget(g)

        lo.addStretch()

    def _convert(self):
        raw = self._base_input.text().strip()
        if not raw:
            for le in self._results.values():
                le.setText("")
            return
        from_base = self._base_from.currentData()
        try:
            val = int(raw, from_base)
        except ValueError:
            for le in self._results.values():
                le.setText("格式错误")
            return
        if 2 in self._results:
            self._results[2].setText(bin(val)[2:])
        if 8 in self._results:
            self._results[8].setText(oct(val)[2:])
        if 10 in self._results:
            self._results[10].setText(str(val))
        if 16 in self._results:
            self._results[16].setText(hex(val)[2:].upper())


# ============================================================
#  正则表达式测试工具
# ============================================================
class RegexTool(QWidget):
    def __init__(self):
        super().__init__()
        self._build()

    def _build(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(16, 16, 16, 16)
        lo.setSpacing(10)

        title = QLabel("正则表达式测试工具")
        title.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        lo.addWidget(title)

        # 正则输入
        lo.addWidget(QLabel("正则表达式:"))
        self._re_input = QLineEdit()
        self._re_input.setPlaceholderText("输入正则表达式，如 \\d+")
        self._re_input.setFont(QFont("Consolas", 12))
        self._re_input.setStyleSheet("QLineEdit{background:#FFF;border:1px solid #D0D0D0;border-radius:4px;padding:6px}")
        self._re_input.textChanged.connect(self._run_regex)
        lo.addWidget(self._re_input)

        # 选项行
        opts_row = QHBoxLayout()

        btn_style = (
            "QPushButton{background:#FFF;border:1px solid #D0D0D0;border-radius:4px;padding:4px 12px}"
            "QPushButton:checked{background:#0078D4;color:#FFF;border-color:#0078D4}"
        )

        self._chk_ignorecase = QPushButton("忽略大小写")
        self._chk_ignorecase.setCheckable(True)
        self._chk_ignorecase.setStyleSheet(btn_style)
        self._chk_ignorecase.clicked.connect(self._run_regex)
        opts_row.addWidget(self._chk_ignorecase)

        self._chk_multiline = QPushButton("多行模式")
        self._chk_multiline.setCheckable(True)
        self._chk_multiline.setStyleSheet(btn_style)
        self._chk_multiline.clicked.connect(self._run_regex)
        opts_row.addWidget(self._chk_multiline)

        self._chk_dotall = QPushButton("点匹配换行")
        self._chk_dotall.setCheckable(True)
        self._chk_dotall.setStyleSheet(btn_style)
        self._chk_dotall.clicked.connect(self._run_regex)
        opts_row.addWidget(self._chk_dotall)
        opts_row.addStretch()
        lo.addLayout(opts_row)

        # 测试文本
        lo.addWidget(QLabel("测试文本:"))
        self._text_input = QPlainTextEdit()
        self._text_input.setPlaceholderText("输入要匹配的文本...")
        self._text_input.setFont(QFont("Consolas", 11))
        self._text_input.setStyleSheet(
            "QPlainTextEdit{background:#FFF;border:1px solid #D0D0D0;border-radius:4px;padding:6px}"
        )
        self._text_input.textChanged.connect(self._run_regex)
        lo.addWidget(self._text_input, stretch=2)

        # 匹配结果 - 使用 QTextEdit 支持 HTML 美化显示
        lo.addWidget(QLabel("匹配结果:"))
        self._result_output = QTextEdit()
        self._result_output.setReadOnly(True)
        self._result_output.setFont(QFont("Consolas", 11))
        self._result_output.setStyleSheet(
            "QTextEdit{background:#FAFAFA;border:1px solid #D0D0D0;border-radius:4px;padding:6px}"
        )
        lo.addWidget(self._result_output, stretch=2)

    def _run_regex(self):
        pattern = self._re_input.text()
        text = self._text_input.toPlainText()
        if not pattern:
            self._result_output.setHtml("")
            return

        flags = 0
        if self._chk_ignorecase.isChecked():
            flags |= 2  # re.IGNORECASE
        if self._chk_multiline.isChecked():
            flags |= 8  # re.MULTILINE
        if self._chk_dotall.isChecked():
            flags |= 16  # re.DOTALL

        try:
            import re
            regex = re.compile(pattern, flags)
            matches = list(regex.finditer(text))

            if not matches:
                hint = ""
                if "^" in pattern or "$" in pattern:
                    hint = (
                        "<br><br><span style='color:#888;font-size:11px'>"
                        "提示：正则含 ^ 或 $ 锚点，要求从字符串开头/结尾匹配。"
                        "若想匹配文本中的子串，请移除锚点或勾选「多行模式」。</span>"
                    )
                self._result_output.setHtml(
                    f"<div style='color:#999;padding:4px'>"
                    f"(无匹配){hint}</div>"
                )
                return

            # 构建美观的 HTML 结果
            parts = []
            parts.append(
                f"<div style='font-family:Consolas;font-size:14px'>"
                f"<p style='color:#0078D4;font-weight:600;margin:0 0 8px 0'>"
                f"共找到 {len(matches)} 个匹配</p>"
            )

            for i, m in enumerate(matches):
                # 匹配卡片
                parts.append(
                    f"<div style='background:#FFF;border:1px solid #E0E0E0;"
                    f"border-radius:4px;padding:6px 10px;margin-bottom:6px'>"
                )
                # 标题行
                parts.append(
                    f"<p style='margin:0 0 4px 0;font-size:13px;color:#666'>"
                    f"匹配 {i+1} &nbsp;|&nbsp; 位置 [{m.start()}, {m.end()}] &nbsp;|&nbsp; 长度 {m.end()-m.start()}"
                    f"</p>"
                )
                # 匹配内容高亮
                parts.append(
                    f"<p style='margin:0;font-size:15px;font-weight:600;color:#333'>"
                    f"<span style='background:#FFEB3B;padding:1px 4px;border-radius:2px'>"
                    f"{self._escape_html(m.group())}</span>"
                    f"</p>"
                )
                # 分组
                if m.groups() or m.groupdict():
                    parts.append(
                        f"<p style='margin:4px 0 0 0;font-size:11px;color:#555'>分组:</p>"
                    )
                    if m.groups():
                        for gi, g in enumerate(m.groups(), 1):
                            if g is not None:
                                parts.append(
                                    f"<span style='background:#E8F5E9;padding:1px 4px;"
                                    f"border-radius:2px;margin:2px;font-size:11px'>"
                                    f"{gi}: {self._escape_html(g)}</span> "
                                )
                    if m.groupdict():
                        for k, v in m.groupdict().items():
                            if v is not None:
                                parts.append(
                                    f"<span style='background:#E3F2FD;padding:1px 4px;"
                                    f"border-radius:2px;margin:2px;font-size:11px'>"
                                    f"{k}: {self._escape_html(v)}</span> "
                                )
                    parts.append("<br>")
                parts.append("</div>")

            parts.append("</div>")
            self._result_output.setHtml("".join(parts))

        except Exception as e:
            self._result_output.setHtml(
                f"<div style='color:#E53935;font-family:Consolas;font-size:14px'>"
                f"正则错误: {self._escape_html(str(e))}</div>"
            )

    def _escape_html(self, s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class DiffTool(QWidget):
    def __init__(self):
        super().__init__()
        self._build()

    def _build(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(16, 16, 16, 16)
        lo.setSpacing(10)

        title = QLabel("文本对比工具")
        title.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        lo.addWidget(title)

        # 双栏输入
        panels = QHBoxLayout()
        panels.setSpacing(12)

        left_box = QVBoxLayout()
        left_box.addWidget(QLabel("原始文本:"))
        self._left_text = QPlainTextEdit()
        self._left_text.setPlaceholderText("粘贴原始文本...")
        self._left_text.setFont(QFont("Consolas", 11))
        self._left_text.setStyleSheet(
            "QPlainTextEdit{background:#FFF;border:1px solid #D0D0D0;border-radius:4px;padding:6px}"
        )
        self._left_text.setLineWrapMode(QPlainTextEdit.NoWrap)
        left_box.addWidget(self._left_text)
        panels.addLayout(left_box)

        right_box = QVBoxLayout()
        right_box.addWidget(QLabel("对比文本:"))
        self._right_text = QPlainTextEdit()
        self._right_text.setPlaceholderText("粘贴对比文本...")
        self._right_text.setFont(QFont("Consolas", 11))
        self._right_text.setStyleSheet(
            "QPlainTextEdit{background:#FFF;border:1px solid #D0D0D0;border-radius:4px;padding:6px}"
        )
        self._right_text.setLineWrapMode(QPlainTextEdit.NoWrap)
        right_box.addWidget(self._right_text)
        panels.addLayout(right_box)
        lo.addLayout(panels, stretch=1)

        # 同步滚动
        self._left_text.verticalScrollBar().valueChanged.connect(
            self._right_text.verticalScrollBar().setValue
        )
        self._right_text.verticalScrollBar().valueChanged.connect(
            self._left_text.verticalScrollBar().setValue
        )

        # 按钮行
        btn_row = QHBoxLayout()
        self._btn_compare = QPushButton("开始对比")
        self._btn_compare.clicked.connect(self._compare)
        self._btn_compare.setStyleSheet(
            "QPushButton{background:#0078D4;color:#FFF;border:none;border-radius:4px;"
            "padding:6px 20px;font-weight:600}QPushButton:hover{background:#106EBE}"
        )
        btn_row.addWidget(self._btn_compare)
        self._btn_clear = QPushButton("清空")
        self._btn_clear.clicked.connect(self._clear)
        btn_row.addWidget(self._btn_clear)
        btn_row.addStretch()
        lo.addLayout(btn_row)

    def _compare(self):
        import difflib
        left_lines = self._left_text.toPlainText().splitlines()
        right_lines = self._right_text.toPlainText().splitlines()

        # 清除旧的高亮
        self._left_text.setExtraSelections([])
        self._right_text.setExtraSelections([])

        if left_lines == right_lines:
            return

        sm = difflib.SequenceMatcher(None, left_lines, right_lines)
        opcodes = sm.get_opcodes()

        left_sel = []
        right_sel = []

        left_fmt = QTextCharFormat()
        left_fmt.setBackground(QColor(255, 200, 200))  # 浅红
        right_fmt = QTextCharFormat()
        right_fmt.setBackground(QColor(200, 255, 200))  # 浅绿

        for tag, i1, i2, j1, j2 in opcodes:
            if tag == "equal":
                yuan_text = yuan_text[yuan_index + 2:]
                break
            if tag in ("delete", "replace"):
                for li in range(i1, i2):
                    cursor = self._left_text.textCursor()
                    cursor.movePosition(cursor.MoveOperation.Start)
                    for _ in range(li):
                        cursor.movePosition(cursor.MoveOperation.Down)
                    cursor.movePosition(cursor.MoveOperation.StartOfLine)
                    cursor.movePosition(cursor.MoveOperation.EndOfLine, cursor.MoveMode.KeepAnchor)
                    sel = QTextEdit.ExtraSelection()
                    sel.cursor = cursor
                    sel.format = left_fmt
                    left_sel.append(sel)
            if tag in ("insert", "replace"):
                for rj in range(j1, j2):
                    cursor = self._right_text.textCursor()
                    cursor.movePosition(cursor.MoveOperation.Start)
                    for _ in range(rj):
                        cursor.movePosition(cursor.MoveOperation.Down)
                    cursor.movePosition(cursor.MoveOperation.StartOfLine)
                    cursor.movePosition(cursor.MoveOperation.EndOfLine, cursor.MoveMode.KeepAnchor)
                    sel = QTextEdit.ExtraSelection()
                    sel.cursor = cursor
                    sel.format = right_fmt
                    right_sel.append(sel)

        self._left_text.setExtraSelections(left_sel)
        self._right_text.setExtraSelections(right_sel)

    def _clear(self):
        self._left_text.clear()
        self._right_text.clear()
        self._left_text.setExtraSelections([])
        self._right_text.setExtraSelections([])


class SortTool(QWidget):
    def __init__(self):
        super().__init__()
        self._build()

    def _build(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(16, 16, 16, 16)
        lo.setSpacing(10)

        title = QLabel("文本列表排序工具")
        title.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        lo.addWidget(title)

        # 排序选项行
        opts_row = QHBoxLayout()
        opts_row.addWidget(QLabel("排序方式:"))

        self._sort_mode = QComboBox()
        self._sort_mode.addItems(["名称", "数值", "长度"])
        self._sort_mode.setStyleSheet(COMBO_STYLE)   # 与侧边栏下拉框同一套样式
        self._sort_mode.currentIndexChanged.connect(self._run_sort)
        opts_row.addWidget(self._sort_mode)

        opts_row.addSpacing(8)

        self._btn_asc = QPushButton("升序")
        self._btn_asc.setCheckable(True)
        self._btn_asc.setChecked(True)
        self._btn_asc.setStyleSheet(
            "QPushButton{background:#FFF;border:1px solid #D0D0D0;border-radius:4px;padding:4px 12px}"
            "QPushButton:checked{background:#0078D4;color:#FFF;border-color:#0078D4}"
        )
        self._btn_asc.clicked.connect(lambda: (self._btn_desc.setChecked(False), self._run_sort()))
        opts_row.addWidget(self._btn_asc)

        self._btn_desc = QPushButton("降序")
        self._btn_desc.setCheckable(True)
        self._btn_desc.setStyleSheet(
            "QPushButton{background:#FFF;border:1px solid #D0D0D0;border-radius:4px;padding:4px 12px}"
            "QPushButton:checked{background:#0078D4;color:#FFF;border-color:#0078D4}"
        )
        self._btn_desc.clicked.connect(lambda: (self._btn_asc.setChecked(False), self._run_sort()))
        opts_row.addWidget(self._btn_desc)

        opts_row.addSpacing(16)

        self._chk_unique = QPushButton("去重")
        self._chk_unique.setCheckable(True)
        self._chk_unique.setStyleSheet(
            "QPushButton{background:#FFF;border:1px solid #D0D0D0;border-radius:4px;padding:4px 12px}"
            "QPushButton:checked{background:#0078D4;color:#FFF;border-color:#0078D4}"
        )
        self._chk_unique.clicked.connect(self._run_sort)
        opts_row.addWidget(self._chk_unique)

        self._chk_reverse = QPushButton("反转")
        self._chk_reverse.setCheckable(True)
        self._chk_reverse.setStyleSheet(
            "QPushButton{background:#FFF;border:1px solid #D0D0D0;border-radius:4px;padding:4px 12px}"
            "QPushButton:checked{background:#0078D4;color:#FFF;border-color:#0078D4}"
        )
        self._chk_reverse.clicked.connect(self._run_sort)
        opts_row.addWidget(self._chk_reverse)

        opts_row.addStretch()
        lo.addLayout(opts_row)

        # 输入
        lo.addWidget(QLabel("输入文本 (每行一条):"))
        self._sort_input = QPlainTextEdit()
        self._sort_input.setPlaceholderText("每行一条文本...")
        self._sort_input.setFont(QFont("Consolas", 11))
        self._sort_input.setStyleSheet(
            "QPlainTextEdit{background:#FFF;border:1px solid #D0D0D0;border-radius:4px;padding:6px}"
        )
        self._sort_input.textChanged.connect(self._run_sort)
        lo.addWidget(self._sort_input, stretch=2)

        # 结果
        lo.addWidget(QLabel("排序结果:"))
        self._sort_output = QPlainTextEdit()
        self._sort_output.setReadOnly(True)
        self._sort_output.setFont(QFont("Consolas", 11))
        self._sort_output.setStyleSheet(
            "QPlainTextEdit{background:#FAFAFA;border:1px solid #D0D0D0;border-radius:4px;padding:6px}"
        )
        lo.addWidget(self._sort_output, stretch=2)

    def _run_sort(self):
        text = self._sort_input.toPlainText().strip()
        if not text:
            self._sort_output.setPlainText("")
            return

        lines = text.splitlines()
        mode = self._sort_mode.currentText()
        reverse = not self._btn_asc.isChecked()

        if mode == "名称":
            lines.sort(reverse=reverse)
        elif mode == "数值":
            try:
                lines.sort(key=lambda x: float(x.strip()) if x.strip() else 0, reverse=reverse)
            except ValueError:
                lines.sort(reverse=reverse)
        elif mode == "长度":
            lines.sort(key=len, reverse=reverse)

        if self._chk_unique.isChecked():
            seen = set()
            uniq = []
            for l in lines:
                if l not in seen:
                    seen.add(l)
                    uniq.append(l)
            lines = uniq

        if self._chk_reverse.isChecked():
            lines.reverse()

        self._sort_output.setPlainText("\n".join(lines))




# ============================================================
#  编码转换工具
# ============================================================
class EncodeTool(QWidget):
    def __init__(self):
        super().__init__()
        self._build()

    def _build(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(16, 16, 16, 16)
        lo.setSpacing(10)

        title = QLabel("编码转换工具")
        title.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        lo.addWidget(title)

        # 输入区
        lo.addWidget(QLabel("输入:"))
        self._enc_input = QPlainTextEdit()
        self._enc_input.setPlaceholderText("输入文本或 HEX 字符串...")
        self._enc_input.setFont(QFont("Consolas", 11))
        self._enc_input.setStyleSheet(
            "QPlainTextEdit{background:#FFF;border:1px solid #D0D0D0;border-radius:4px;padding:6px}"
        )
        self._enc_input.textChanged.connect(self._convert_all)
        lo.addWidget(self._enc_input, stretch=1)

        # 转换结果网格: 2x3
        import base64, urllib.parse, binascii
        self._base64 = base64
        self._urlparse = urllib.parse
        self._binascii = binascii

        grid = QGridLayout()
        grid.setSpacing(8)

        items = [
            ("HEX → 字节", 0, 0),
            ("字节 → HEX", 0, 1),
            ("Base64 编码", 0, 2),
            ("Base64 解码", 1, 0),
            ("URL 编码", 1, 1),
            ("URL 解码", 1, 2),
        ]

        self._enc_results = {}
        for label, r, c in items:
            gb = QGroupBox(label)
            gbl = QVBoxLayout(gb)
            gbl.setContentsMargins(6, 4, 6, 6)
            le = QLineEdit()
            le.setReadOnly(True)
            le.setFont(QFont("Consolas", 10))
            le.setStyleSheet(
                "QLineEdit{background:#FAFAFA;border:1px solid #D0D0D0;border-radius:3px;padding:4px}"
            )
            le.setPlaceholderText("—")
            gbl.addWidget(le)
            grid.addWidget(gb, r, c)
            self._enc_results[label] = le

        lo.addLayout(grid)
        lo.addStretch()

    def _convert_all(self):
        text = self._enc_input.toPlainText()
        if not text.strip():
            for le in self._enc_results.values():
                le.setText("")
            return

        # HEX → 字节
        try:
            clean = text.replace(" ", "").replace("\n", "").replace("\n", "")
            raw = bytes.fromhex(clean)
            self._enc_results["HEX → 字节"].setText(
                " ".join(f"{b:02X}" for b in raw) + "  |  " +
                "".join(chr(b) if 32 <= b < 127 else "." for b in raw)
            )
        except Exception:
            self._enc_results["HEX → 字节"].setText("格式错误")

        # 字节 → HEX
        try:
            raw = text.encode("utf-8")
            self._enc_results["字节 → HEX"].setText(raw.hex(" ").upper())
        except Exception:
            self._enc_results["字节 → HEX"].setText("转换失败")

        # Base64
        try:
            self._enc_results["Base64 编码"].setText(
                self._base64.b64encode(text.encode("utf-8")).decode()
            )
        except Exception:
            self._enc_results["Base64 编码"].setText("转换失败")

        try:
            self._enc_results["Base64 解码"].setText(
                self._base64.b64decode(text.encode("utf-8")).decode("utf-8", errors="replace")
            )
        except Exception:
            self._enc_results["Base64 解码"].setText("格式错误")

        # URL
        try:
            self._enc_results["URL 编码"].setText(
                self._urlparse.quote(text, safe="")
            )
        except Exception:
            self._enc_results["URL 编码"].setText("转换失败")

        try:
            self._enc_results["URL 解码"].setText(
                self._urlparse.unquote(text)
            )
        except Exception:
            self._enc_results["URL 解码"].setText("格式错误")


# ============================================================
#  金额转换工具
# ============================================================
AMOUNT_DIGITS = "零壹贰叁肆伍陆柒捌玖"
AMOUNT_UNITS = ["", "拾", "佰", "仟"]
AMOUNT_SECTIONS = ["", "万", "亿", "万亿"]
AMOUNT_INPUT_DIGITS = {
    "零": 0, "〇": 0, "壹": 1, "贰": 2, "叁": 3, "肆": 4,
    "伍": 5, "陆": 6, "柒": 7, "捌": 8, "玖": 9,
    "0": 0, "1": 1, "2": 2, "3": 3, "4": 4,
    "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
}


def _convert_chinese_integer(number: int) -> str:
    """按中文四位节和十进制位值读整数，支持万亿级金额。"""
    if number == 0:
        return "零"
    sections = []
    while number:
        sections.append(number % 10000)
        number //= 10000
    if len(sections) > len(AMOUNT_SECTIONS):
        raise ValueError("金额超出支持范围（最多到万亿位）")

    result = ""
    zero_pending = False
    for index in range(len(sections) - 1, -1, -1):
        value = sections[index]
        if value == 0:
            # 亿与万之间只有一个空节时仍要保留“亿零”；最末空节无需再补零。
            if result and index > 0:
                zero_pending = True
            continue
        # 高级节内部不足四位时，节与节之间需要补零（如：壹万零贰拾）。
        if result and value < 1000 and not result.endswith("零"):
            result += "零"
        elif zero_pending and result and not result.endswith("零"):
            result += "零"
        part = ""
        digit_zero = False
        for position in range(3, -1, -1):
            digit = value // (10 ** position) % 10
            if digit:
                if digit_zero:
                    part += "零"
                part += AMOUNT_DIGITS[digit] + AMOUNT_UNITS[position]
                digit_zero = False
            elif part:
                digit_zero = True
        # 输出前补齐高位空节，节名才能稳定对应 万亿 / 亿 / 万 / 空；
        # 否则普通“万”会被错读成“万亿”。
        # 单位属于原数值中的 10^4 级，和节内位置无关。
        result += part + AMOUNT_SECTIONS[index]
        zero_pending = False
    return result


def amount_to_chinese(amount: Decimal) -> str:
    """人民币金额转财务大写，精确到分；0.5 -> 零元伍角整。"""
    if not amount.is_finite():
        raise ValueError("金额必须是有限数值")
    if amount < 0:
        raise ValueError("金额不能为负数")
    amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    fen = int(amount * 100)
    yuan, fraction = divmod(fen, 100)
    jiao, fen_digit = divmod(fraction, 10)

    result = (_convert_chinese_integer(yuan) if yuan else "零") + "元"
    if not fraction:
        return result + "整"
    if jiao:
        result += AMOUNT_DIGITS[jiao] + "角"
    elif yuan:
        result += "零"
    if fen_digit:
        result += AMOUNT_DIGITS[fen_digit] + "分"
    elif not yuan:
        result += "整"
    return result


def parse_amount_text(text: str) -> Decimal:
    """只识别人民币数字金额：允许千位逗号和会计括号负数。"""
    raw = (text or "").strip()
    if raw.startswith("(") and raw.endswith(")"):
        raw = "-" + raw[1:-1]
    raw = "".join(raw.split()).replace(",", "")
    if not raw or not (raw[0].isdigit() or raw[0] in ".+-"):
        raise ValueError("请输入金额，例如 892.88")
    try:
        amount = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError("金额格式错误，例如 892.88") from exc
    if not amount.is_finite():
        raise ValueError("金额必须是有限数值")
    if amount < 0:
        raise ValueError("金额不能为负数")
    if amount > Decimal("9999999999999999.99"):
        raise ValueError("金额超出支持范围（最多到万亿位）")
    return amount


_CHINESE_AMOUNT_PATTERN = re.compile(
    r"^(?:负)?(?:整|[零〇壹贰叁肆伍陆柒捌玖"
    r"拾佰仟万亿元角分整"
    r"0-9\.\s])+$"
)
_CHINESE_DIGIT_VALUE = {key: value for key, value in AMOUNT_INPUT_DIGITS.items() if not key.isdigit()}


def chinese_to_amount(text: str) -> Decimal:
    """反向解析人民币大写金额，支持元、角、分及万亿级别。"""
    raw = "".join((text or "").split())
    if not raw or not _CHINESE_AMOUNT_PATTERN.fullmatch(raw):
        raise ValueError("请输入标准中文大写金额")
    if raw.startswith("负"):
        raise ValueError("金额不能为负数")
    if raw.endswith("元整"):
        raw = raw[:-2] + "元"
    if "元" not in raw:
        raise ValueError("中文金额需要包含“元”")
    yuan_text, fraction_text = raw.split("元", 1)

    def parse_four(value_text):
        section, digit, previous = 0, None, 4
        for char in value_text:
            if char in ("零", "〇"):
                continue
            if char in _CHINESE_DIGIT_VALUE:
                if digit is not None:
                    raise ValueError("连续出现多个数字，请检查中文金额")
                digit = _CHINESE_DIGIT_VALUE[char]
            elif char in AMOUNT_UNITS:
                if digit is None:
                    raise ValueError("中文金额单位顺序错误")
                position = AMOUNT_UNITS.index(char)
                if position >= previous:
                    raise ValueError("万、仟、佰、拾的单位顺序错误")
                section += digit * (10 ** position)
                digit, previous = None, position
            else:
                raise ValueError("中文金额格式错误")
        return section + (digit or 0)

    def parse_yuan(value_text):
        if not value_text:
            return 0
        # 以 4^x 作为基本节权值，“万亿”直接用 10^12。
        # 这样万、亿节之间不依赖汉字数量；每个四位节仍独立校验顺序。
        parts = []
        start = 0
        index = 0
        while index < len(value_text):
            if value_text[index] not in ("万", "亿"):
                index += 1
                continue
            unit_end = index + 1
            if value_text.startswith("万亿", index):
                unit_end = index + 2
                multiplier = 10 ** 12
            elif value_text[index] == "亿":
                multiplier = 10 ** 8
            else:
                multiplier = 10 ** 4
            value = value_text[start:index]
            if not value:
                raise ValueError("万、亿前缺少金额数字")
            parts.append((parse_four(value), multiplier))
            start = index = unit_end
        if start < len(value_text):
            parts.append((parse_four(value_text[start:]), 1))
        elif not parts:
            parts.append((0, 1))

        # 高权节必须大于低权节；不能重复写“亿”。
        for current, following in zip(parts, parts[1:]):
            if current[1] <= following[1]:
                raise ValueError("万、亿的单位顺序错误")
        return sum(value * multiplier for value, multiplier in parts)

    yuan = parse_yuan(yuan_text)
    if yuan > 9999999999999999:
        raise ValueError("金额超出支持范围（最多到万亿位）")
    fraction = Decimal("0")
    if fraction_text:
        if fraction_text.endswith("整"):
            fraction_text = fraction_text[:-1]
        if "整" in fraction_text:
            raise ValueError("中文金额的“整”只能出现在末尾")
        if fraction_text.startswith("零"):
            fraction_text = fraction_text[1:]
        if "角" in fraction_text:
            jiao, fraction_text = fraction_text.split("角", 1)
            if not jiao or jiao not in _CHINESE_DIGIT_VALUE:
                raise ValueError("角位必须是一位中文数字")
            fraction += Decimal(_CHINESE_DIGIT_VALUE[jiao]) / 10
        if fraction_text:
            if not fraction_text.endswith("分"):
                raise ValueError("分位格式错误")
            fen = fraction_text[:-1]
            if not fen or fen not in _CHINESE_DIGIT_VALUE:
                raise ValueError("分位必须是一位中文数字")
            fraction += Decimal(_CHINESE_DIGIT_VALUE[fen]) / 100
    return Decimal(yuan) + fraction



class AmountTool(QWidget):
    """人民币金额转换：蓝色结果框只读，上下输入框均可转换。"""

    def __init__(self):
        super().__init__()
        self._copy_toast_timer = QTimer(self)
        self._copy_toast_timer.setSingleShot(True)
        self._copy_toast_timer.timeout.connect(self._hide_copy_toast)
        self._copy_toast_token = 0
        self._build()

    def _build(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(16, 16, 16, 16)
        lo.setSpacing(12)

        # 应用内 Toast 不占布局，放在页面中上方，隐藏时不挤压下方内容。
        self._copy_toast = QLabel(self)
        self._copy_toast.setObjectName("copy_toast")
        self._copy_toast.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._copy_toast.setTextFormat(Qt.TextFormat.PlainText)
        self._copy_toast.setStyleSheet(
            "QLabel#copy_toast{background:#FFFFFF;color:#166534;"
            "border:1px solid #B7E2C3;border-radius:8px;"
            "padding:8px 18px 8px 30px;font-family:'Microsoft YaHei';font-size:13px;}"
        )
        self._copy_toast.setVisible(False)

        title = QLabel("金额转换")
        title.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        title.setObjectName("heading")
        lo.addWidget(title)

        hint = QLabel("在白色输入框填写，蓝色结果框只用于显示。")
        hint.setObjectName("subtitle")
        lo.addWidget(hint)

        g1 = QGroupBox("小写金额 → 中文大写")
        g1lo = QGridLayout(g1)
        g1lo.setHorizontalSpacing(10)
        g1lo.setVerticalSpacing(8)
        self._amount_input = QLineEdit()
        self._amount_input.setPlaceholderText("例如：10020.05")
        self._amount_input.setFont(QFont("Microsoft YaHei", 13))
        self._amount_input.setMinimumHeight(42)
        self._amount_input.setStyleSheet(
            "QLineEdit{background:#FFFFFF;color:#1A1A1A;border:1px solid #D0D0D0;"
            "border-radius:4px;padding:7px 9px}"
            "QLineEdit:focus{border-color:#0078D4}"
        )
        self._amount_input.textChanged.connect(self._on_amount_changed)
        g1lo.addWidget(QLabel("金额:"), 0, 0)
        g1lo.addWidget(self._amount_input, 0, 1)

        self._upper_output = QLineEdit()
        self._upper_output.setReadOnly(True)
        self._upper_output.setEnabled(False)
        self._upper_output.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._upper_output.setMinimumHeight(42)
        self._upper_output.setFont(QFont("Microsoft YaHei", 13, QFont.Weight.Bold))
        self._upper_output.setStyleSheet(
            "QLineEdit{background:#E8F0FE;color:#005A9E;border:1px solid #B3D4FC;"
            "border-radius:4px;padding:7px 9px}"
        )
        g1lo.addWidget(QLabel("大写:"), 1, 0)
        g1lo.addWidget(self._upper_output, 1, 1)
        self._btn_copy_upper = QPushButton("复制")
        self._btn_copy_upper.setMinimumWidth(58)
        self._btn_copy_upper.clicked.connect(self._copy_upper)
        g1lo.addWidget(self._btn_copy_upper, 1, 2)
        self._amount_status = QLabel("")
        g1lo.addWidget(self._amount_status, 2, 1)
        g1lo.setColumnStretch(1, 1)
        lo.addWidget(g1)

        g2 = QGroupBox("中文大写 → 小写金额")
        g2lo = QGridLayout(g2)
        g2lo.setHorizontalSpacing(10)
        g2lo.setVerticalSpacing(8)
        self._upper_input = QLineEdit()
        self._upper_input.setPlaceholderText("例如：壹万零贰拾元零伍分")
        self._upper_input.setFont(QFont("Microsoft YaHei", 13))
        self._upper_input.setMinimumHeight(42)
        self._upper_input.setStyleSheet(
            "QLineEdit{background:#FFFFFF;color:#1A1A1A;border:1px solid #D0D0D0;"
            "border-radius:4px;padding:7px 9px}"
            "QLineEdit:focus{border-color:#0078D4}"
        )
        self._upper_input.textChanged.connect(self._on_upper_changed)
        self._lower_output = QLineEdit()
        self._lower_output.setReadOnly(True)
        self._lower_output.setEnabled(False)
        self._lower_output.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._lower_output.setMinimumHeight(42)
        self._lower_output.setFont(QFont("Consolas", 13, QFont.Weight.Bold))
        self._lower_output.setStyleSheet(
            "QLineEdit{background:#E8F0FE;color:#005A9E;border:1px solid #B3D4FC;"
            "border-radius:4px;padding:7px 9px}"
        )
        g2lo.addWidget(QLabel("大写:"), 0, 0); g2lo.addWidget(self._upper_input, 0, 1)
        g2lo.addWidget(QLabel("小写:"), 1, 0); g2lo.addWidget(self._lower_output, 1, 1)
        self._btn_copy_lower = QPushButton("复制")
        self._btn_copy_lower.setMinimumWidth(58)
        self._btn_copy_lower.clicked.connect(self._copy_lower)
        g2lo.addWidget(self._btn_copy_lower, 1, 2)
        self._reverse_status = QLabel("")
        g2lo.addWidget(self._reverse_status, 2, 1)
        g2lo.setColumnStretch(1, 1)
        lo.addWidget(g2)

        lo.addStretch()
        self._on_amount_changed()

    def _on_amount_changed(self):
        if not self._amount_input.text().strip():
            self._upper_output.clear()
            self._set_status(self._amount_status, "")
            return
        try:
            amount = parse_amount_text(self._amount_input.text())
            self._upper_output.setText(amount_to_chinese(amount))
            self._set_status(self._amount_status, "")
        except ValueError as exc:
            self._upper_output.clear()
            self._set_status(self._amount_status, str(exc))

    def _on_upper_changed(self):
        """只转换下方大写，不读取也不改写上方数字及结果。"""
        text = self._upper_input.text().strip()
        if not text:
            self._lower_output.clear()
            self._set_status(self._reverse_status, "")
            return
        try:
            amount = chinese_to_amount(text)
            value = format(amount.quantize(Decimal("0.01")), "f")
            self._lower_output.setText(value)
            self._set_status(self._reverse_status, "")
        except ValueError as exc:
            self._set_status(self._reverse_status, str(exc))
            self._lower_output.clear()

    def _copy_upper(self):
        self._copy_result(self._upper_output, "已复制中文大写")

    def _copy_lower(self):
        self._copy_result(self._lower_output, "已复制小写金额")

    def _copy_result(self, field, message):
        """空结果不覆盖剪贴板中的内容。"""
        if field.text().strip():
            QApplication.clipboard().setText(field.text())
            self._show_copy_toast(message)

    def _show_copy_toast(self, message):
        self._copy_toast_token += 1
        token = self._copy_toast_token
        self._copy_toast.setText(message)
        self._copy_toast_tick = QWidget(self._copy_toast)
        self._copy_toast_tick.setObjectName("copy_toast_tick")
        self._copy_toast_tick.setFixedSize(8, 8)
        self._copy_toast_tick.setStyleSheet(
            "QWidget#copy_toast_tick{background:#107C10;border-radius:4px;}"
        )
        self._copy_toast_tick.show()
        self._copy_toast.adjustSize()
        self._copy_toast_tick.move(12, (self._copy_toast.height() - 8) // 2)
        self._copy_toast.adjustSize()
        self._copy_toast.raise_()
        self._copy_toast.setGraphicsEffect(QGraphicsOpacityEffect(self._copy_toast))
        self._copy_toast.graphicsEffect().setOpacity(0.0)
        self._copy_toast.setVisible(True)
        self._position_copy_toast()
        fade_in = QPropertyAnimation(self._copy_toast.graphicsEffect(), b"opacity", self)
        fade_in.setDuration(160)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)
        fade_in.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
        self._copy_toast_timer.start(1800)
        self._copy_toast_token = token

    def _position_copy_toast(self):
        if not hasattr(self, "_copy_toast"):
            return
        self._copy_toast.move(
            max(16, (self.width() - self._copy_toast.width()) // 2),
            14,
        )

    def _hide_copy_toast(self):
        if not self._copy_toast.isVisible():
            return
        token = self._copy_toast_token
        fade_out = QPropertyAnimation(self._copy_toast.graphicsEffect(), b"opacity", self)
        fade_out.setDuration(220)
        fade_out.setStartValue(self._copy_toast.graphicsEffect().opacity())
        fade_out.setEndValue(0.0)
        fade_out.finished.connect(
            lambda: self._finish_hide_copy_toast(token)
        )
        fade_out.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def _finish_hide_copy_toast(self, token):
        if token == self._copy_toast_token:
            self._copy_toast.setVisible(False)

    def hideEvent(self, event):
        """切换工具页面时立即结束轻提示，避免回页后残留。"""
        if hasattr(self, "_copy_toast_timer"):
            self._copy_toast_timer.stop()
            self._copy_toast.setVisible(False)
        super().hideEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_copy_toast()

    @staticmethod
    def _set_status(label, message):
        label.setText(message)
        label.setStyleSheet("color:#D13438;font-size:12px")


# ============================================================
class ChecksumTool(QWidget):
    def __init__(self):
        super().__init__()
        self._build()

    def _build(self):
        import hashlib
        self._hashlib = hashlib

        lo = QVBoxLayout(self)
        lo.setContentsMargins(16, 16, 16, 16)
        lo.setSpacing(10)

        title = QLabel("校验计算器")
        title.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        lo.addWidget(title)

        # 输入模式: 文本 / HEX
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("输入模式:"))
        self._cs_mode = QComboBox()
        self._cs_mode.addItems(["文本", "HEX"])
        self._cs_mode.setStyleSheet(COMBO_STYLE)   # 与侧边栏下拉框同一套样式
        self._cs_mode.currentIndexChanged.connect(self._calc_all)
        mode_row.addWidget(self._cs_mode)
        mode_row.addStretch()
        lo.addLayout(mode_row)

        # 输入
        self._cs_input = QPlainTextEdit()
        self._cs_input.setPlaceholderText("输入要计算校验值的数据...")
        self._cs_input.setFont(QFont("Consolas", 11))
        self._cs_input.setStyleSheet(
            "QPlainTextEdit{background:#FFF;border:1px solid #D0D0D0;border-radius:4px;padding:6px}"
        )
        self._cs_input.textChanged.connect(self._calc_all)
        lo.addWidget(self._cs_input, stretch=1)

        # 结果网格
        grid = QGridLayout()
        grid.setSpacing(8)

        checks = [
            ("CRC16 (Modbus)", self._crc16_modbus, 0, 0),
            ("CRC16 (CCITT)", self._crc16_ccitt, 0, 1),
            ("CRC32", self._crc32, 0, 2),
            ("XOR", self._xor8, 1, 0),
            ("累加和 (8bit)", self._sum8, 1, 1),
            ("累加和 (16bit)", self._sum16, 1, 2),
            ("MD5", self._md5, 2, 0),
            ("SHA1", self._sha1, 2, 1),
            ("SHA256", self._sha256, 2, 2),
        ]

        self._cs_results = {}
        for label, func, r, c in checks:
            gb = QGroupBox(label)
            gbl = QVBoxLayout(gb)
            gbl.setContentsMargins(6, 4, 6, 6)
            le = QLineEdit()
            le.setReadOnly(True)
            le.setFont(QFont("Consolas", 12))
            le.setAlignment(Qt.AlignCenter)
            le.setStyleSheet(
                "QLineEdit{background:#FAFAFA;border:1px solid #D0D0D0;border-radius:3px;padding:4px}"
            )
            le.setPlaceholderText("—")
            gbl.addWidget(le)
            grid.addWidget(gb, r, c)
            self._cs_results[label] = le

        lo.addLayout(grid)
        lo.addStretch()

    def _get_bytes(self):
        text = self._cs_input.toPlainText().strip()
        if not text:
            return None
        if self._cs_mode.currentText() == "HEX":
            try:
                return bytes.fromhex(text.replace(" ", "").replace("\n", ""))
            except Exception:
                return None
        else:
            return text.encode("utf-8")

    def _calc_all(self):
        data = self._get_bytes()
        if data is None:
            for le in self._cs_results.values():
                le.setText("" if self._cs_input.toPlainText().strip() else "")
            return

        self._cs_results["CRC16 (Modbus)"].setText(f"{self._crc16_modbus(data):04X}")
        self._cs_results["CRC16 (CCITT)"].setText(f"{self._crc16_ccitt(data):04X}")
        self._cs_results["CRC32"].setText(f"{self._crc32(data):08X}")
        self._cs_results["XOR"].setText(f"{self._xor8(data):02X}")
        self._cs_results["累加和 (8bit)"].setText(f"{self._sum8(data):02X}")
        self._cs_results["累加和 (16bit)"].setText(f"{self._sum16(data):04X}")
        self._cs_results["MD5"].setText(self._md5(data))
        self._cs_results["SHA1"].setText(self._sha1(data))
        self._cs_results["SHA256"].setText(self._sha256(data))

    # ---- CRC / XOR / SUM ----
    def _crc16_modbus(self, data):
        crc = 0xFFFF
        for b in data:
            crc ^= b
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc & 0xFFFF

    def _crc16_ccitt(self, data):
        crc = 0xFFFF
        for b in data:
            crc ^= (b << 8)
            for _ in range(8):
                if crc & 0x8000:
                    crc = ((crc << 1) ^ 0x1021) & 0xFFFF
                else:
                    crc = (crc << 1) & 0xFFFF
        return crc

    def _crc32(self, data):
        crc = 0xFFFFFFFF
        for b in data:
            crc ^= b
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ 0xEDB88320
                else:
                    crc >>= 1
        return crc ^ 0xFFFFFFFF

    def _xor8(self, data):
        result = 0
        for b in data:
            result ^= b
        return result & 0xFF

    def _sum8(self, data):
        return sum(data) & 0xFF

    def _sum16(self, data):
        return sum(data) & 0xFFFF

    # ---- Hash ----
    def _md5(self, data):
        return self._hashlib.md5(data).hexdigest().upper()

    def _sha1(self, data):
        return self._hashlib.sha1(data).hexdigest().upper()

    def _sha256(self, data):
        return self._hashlib.sha256(data).hexdigest().upper()


# ============================================================
#  工具箱 / 硬件信息工具
# ============================================================
class SystemInfoTool(QWidget):
    """工具箱页 -- 左侧分类导航(硬件信息 + 外置工具) + 右侧内嵌内容, 无弹窗"""

    def __init__(self, base_dir=None):
        super().__init__()
        self._base_dir = base_dir
        self._tools = []
        if base_dir:
            self._tools = toolbox.load_manifest(os.path.join(base_dir, "tools"))
        self._build()

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 左侧导航栏
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

        # 硬件信息固定为第一个分类
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._btn_hw = self._make_nav_btn("硬件信息")
        self._nav_group.addButton(self._btn_hw)
        self._btn_hw.setChecked(True)
        nav_lo.addWidget(self._btn_hw)

        # 外置工具分类 (保持清单出现顺序; 优先使用清单显式声明的分类)
        self._categories = toolbox.load_categories(
            os.path.join(self._base_dir, "tools")) if self._base_dir else None
        if self._categories is None:
            self._categories = []
        for t in self._tools:
            c = toolbox._norm_category(t)
            if c not in self._categories:
                self._categories.append(c)

        self._nav_btns = {"硬件信息": self._btn_hw}
        for c in self._categories:
            btn = self._make_nav_btn(c)
            self._nav_group.addButton(btn)
            nav_lo.addWidget(btn)
            self._nav_btns[c] = btn

        nav_lo.addStretch()
        root.addWidget(nav)

        # 右侧内容区
        self._stack = QStackedWidget()
        self._hw_page = HardwareInfoPage()
        self._stack.addWidget(self._hw_page)

        self._pages = {"硬件信息": self._hw_page}
        tools_dir = os.path.join(self._base_dir, "tools") if self._base_dir else ""
        for c in self._categories:
            page = toolbox.build_category_page(c, self._tools, tools_dir)
            self._stack.addWidget(page)
            self._pages[c] = page
        root.addWidget(self._stack, stretch=1)

        self._btn_hw.clicked.connect(lambda: self._show("硬件信息"))
        for c in self._categories:
            btn = self._nav_btns[c]
            btn.clicked.connect(lambda checked=False, cat=c: self._show(cat))

    def _show(self, cat):
        # 点击当前已选中的分类时保持高亮
        btn = self._nav_btns.get(cat)
        if btn is not None:
            btn.setChecked(True)
        self._stack.setCurrentWidget(self._pages.get(cat, self._hw_page))

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


class HardwareInfoPage(QWidget):
    """右侧硬件信息内容 -- 内嵌展示, 不弹窗

    硬件采集要调 PowerShell (CIM 查询, 约 0.8s), 绝不能放在 GUI 线程里同步跑,
    否则窗口打开后会僵住 2-3 秒。这里沿用 NetworkTool 的做法: 后台线程采集 +
    队列回传, GUI 线程用定时器取结果, 期间界面可正常响应。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue = None
        self._poll = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        # 顶部三卡片
        cards = QHBoxLayout()
        cards.setSpacing(12)
        self._card_model, self._val_model = self._make_card("🖥️", "型号信息", "正在读取...")
        self._card_os, self._val_os = self._make_card("🪟", "系统信息", "正在读取...")
        self._card_uptime, self._val_uptime = self._make_card("⏱️", "运行时间", "正在读取...")
        cards.addWidget(self._card_model, stretch=1)
        cards.addWidget(self._card_os, stretch=1)
        cards.addWidget(self._card_uptime, stretch=1)
        root.addLayout(cards)

        det_title = QLabel("详细信息")
        det_title.setStyleSheet(
            "color:#111827;font-size:18px;font-weight:700;"
            "padding-left:10px;border-left:4px solid #0078D4;"
        )
        root.addWidget(det_title)

        detail_frame = QFrame()
        detail_frame.setStyleSheet(
            "QFrame{background:transparent;border:none;}"
        )
        self._detail_lo = QVBoxLayout(detail_frame)
        self._detail_lo.setContentsMargins(16, 12, 16, 12)
        self._detail_lo.setSpacing(10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(detail_frame)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        root.addWidget(scroll, stretch=1)

        QTimer.singleShot(0, self._load)

    def _make_card(self, icon, title, value):
        card = QFrame()
        card.setStyleSheet(
            "QFrame{background:#F5F7FA;border:none;border-radius:8px;}"
        )
        lo = QVBoxLayout(card)
        lo.setContentsMargins(14, 12, 14, 12)
        lo.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(6)
        ic = QLabel(icon)
        ic.setStyleSheet("font-size:22px;background:transparent;")
        t = QLabel(title)
        t.setStyleSheet("color:#4B5563;font-size:13px;font-weight:600;background:transparent;")
        head.addWidget(ic)
        head.addWidget(t)
        head.addStretch()
        lo.addLayout(head)

        val = QLabel(value)
        val.setWordWrap(True)
        val.setStyleSheet("color:#111827;font-size:14px;font-weight:600;background:transparent;")
        lo.addWidget(val)
        return card, val

    def _add_detail(self, name, value):
        row = QHBoxLayout()
        row.setSpacing(12)
        row.setAlignment(Qt.AlignTop)
        n = QLabel(name + ":")
        n.setFixedWidth(72)
        n.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        n.setStyleSheet("color:#374151;font-size:14px;font-weight:600;background:transparent;")
        row.addWidget(n)

        text = self._join(value)
        v = QLabel(text)
        v.setWordWrap(True)
        v.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        v.setStyleSheet("color:#111827;font-size:15px;background:transparent;")
        row.addWidget(v, stretch=1)
        self._detail_lo.addLayout(row)

    @staticmethod
    def _join(value):
        if isinstance(value, list):
            items = [str(x) for x in value if x is not None and str(x).strip()]
            return "\n".join(items) if items else "未检测到"
        if value is None or not str(value).strip():
            return "未检测到"
        return str(value)

    def _load(self):
        """后台线程采集, GUI 线程只负责取结果填界面 (采集期间界面不卡)"""
        if self._poll is not None:
            return
        import queue as _queue
        import threading

        self._queue = _queue.Queue()

        def worker():
            try:
                self._queue.put(("ok", hardware.collect_hardware_info()))
            except Exception as e:
                self._queue.put(("err", str(e)))

        # 守护线程: 采集未完成时退出程序也不会阻塞或报错
        threading.Thread(target=worker, daemon=True).start()
        self._poll = QTimer(self)
        self._poll.timeout.connect(self._check_queue)
        self._poll.start(80)

    def _check_queue(self):
        if self._queue is None or self._queue.empty():
            return
        kind, payload = self._queue.get()
        self._poll.stop()
        if kind == "ok":
            self._on_collected(payload)
        else:
            self._on_failed(payload)

    def _on_failed(self, message):
        self._val_model.setText("—")
        self._val_os.setText("—")
        self._val_uptime.setText("—")
        self._add_detail("错误", message)
        self._detail_lo.addStretch()

    def _on_collected(self, info):
        self._val_model.setText(str(info.get("model") or "未检测到"))
        self._val_os.setText(str(info.get("os") or "未检测到"))

        # 运行时间基于开机时刻实时刷新
        up_secs = info.get("uptime_seconds")
        if up_secs is not None:
            self._boot_epoch = time.time() - float(up_secs)
            self._val_uptime.setText(self._fmt_uptime(up_secs))
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._tick)
            # 用 500ms 刷新: 即使某次 tick 被事件循环延后, 也能在下一个周期内
            # 快速追上, 避免显示出现"卡顿后跳 2 秒"的观感
            self._timer.start(500)
        else:
            self._val_uptime.setText(str(info.get("uptime") or "未检测到"))

        self._add_detail("处理器", info.get("cpu"))
        self._add_detail("主板", info.get("mainboard"))
        self._add_detail("内存", self._format_ram(info))
        self._add_detail("显卡", info.get("gpus"))
        self._add_detail("显示器", info.get("monitors"))
        self._add_detail("磁盘", info.get("disks"))
        self._add_detail("声卡", info.get("sounds"))
        self._add_detail("网卡", info.get("nics"))
        # 注册表部分正常但 CIM 查询失败时, 说明一下原因 (否则只会显示一片"未检测到")
        if info.get("wmi_error"):
            self._add_detail("提示", "部分信息读取失败：" + str(info["wmi_error"]))
        self._detail_lo.addStretch()

    def _tick(self):
        if hasattr(self, "_boot_epoch"):
            self._val_uptime.setText(self._fmt_uptime(time.time() - self._boot_epoch))

    @staticmethod
    def _fmt_uptime(secs):
        secs = max(0, int(round(float(secs))))
        days, rem = divmod(secs, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, seconds = divmod(rem, 60)
        return "{}天{}小时{}分钟{}秒".format(days, hours, minutes, seconds)

    @staticmethod
    def _format_ram(info):
        maker = info.get("ram_maker")
        ram = info.get("ram")
        speed = info.get("ram_speed")
        detail = info.get("ram_detail")
        parts = []
        if maker:
            parts.append(str(maker).strip())
        if ram:
            parts.append(str(ram).strip())
        if speed:
            parts.append("{}MHz".format(speed))
        if detail:
            parts.append("( {} )".format(detail))
        return " ".join(parts) if parts else None


# ============================================================
#  Ping + 端口扫描工具
# ============================================================
class NetworkTool(QWidget):
    """Ping / 端口扫描 / 网段扫描工具 (后台线程 + 队列, 不阻塞 UI)"""

    COMMON_PORTS = [
        21, 22, 23, 25, 53, 80, 110, 135, 139, 143, 443, 445,
        993, 995, 1433, 1521, 3306, 3389, 5432, 5900, 6379,
        8000, 8080, 8443, 8888, 9000, 9200, 27017
    ]

    def __init__(self):
        super().__init__()
        import queue as _queue
        self._queue = _queue.Queue()
        self._alive_ips = []
        self._open_ports = []
        self._pending = 0
        self._scan_kind = ""
        self._ping_proc = None
        self._build()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._drain_queue)
        self._timer.start(100)

    def _build(self):
        from PySide6.QtWidgets import QTabWidget
        lo = QVBoxLayout(self)
        lo.setContentsMargins(16, 16, 16, 16)
        lo.setSpacing(10)

        title = QLabel("Ping/端口扫描/网段扫描工具")
        title.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        lo.addWidget(title)

        # 标题与标签栏之间的横向贯穿分隔线
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("QFrame{background:#D0D0D0;border:none;}")
        lo.addWidget(sep)

        tabs = QTabWidget()
        # 父级(主窗口)样式表把 QTabWidget::pane 的 border-top 设成了 none,
        # 内层 Tab 会继承该规则而导致缺少上框线; 这里显式补回完整边框,
        # 并用 top:-1px 让上框线与标签栏底边贴合, 形成一条贯通的分隔线
        tabs.setStyleSheet(
            "QTabWidget::pane{border:1px solid #D0D0D0;background:#FFFFFF;top:-1px}"
        )
        tabs.addTab(self._build_ping_page(), "Ping")
        tabs.addTab(self._build_port_page(), "端口扫描")
        tabs.addTab(self._build_lan_page(), "网段扫描")
        lo.addWidget(tabs, stretch=1)

    # ---------- Ping ----------
    def _build_ping_page(self):
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setContentsMargins(8, 8, 8, 8)
        lo.setSpacing(8)

        row = QHBoxLayout()
        row.addWidget(QLabel("目标:"))
        self._ping_target = QLineEdit()
        self._ping_target.setPlaceholderText("IP 或域名，如 192.168.1.1 或 baidu.com")
        self._ping_target.setFont(QFont("Consolas", 11))
        self._ping_target.returnPressed.connect(self._start_ping)
        row.addWidget(self._ping_target, stretch=1)
        self._btn_ping = QPushButton("Ping")
        self._btn_ping.setStyleSheet(
            "QPushButton{background:#0078D4;color:#FFF;border:none;border-radius:4px;"
            "padding:6px 20px;font-weight:600}QPushButton:hover{background:#106EBE}"
            "QPushButton:disabled{background:#CCC;color:#FFF}")
        self._btn_ping.clicked.connect(self._start_ping)
        row.addWidget(self._btn_ping)
        lo.addLayout(row)

        self._ping_output = QPlainTextEdit()
        self._ping_output.setReadOnly(True)
        self._ping_output.setFont(QFont("Consolas", 10))
        self._ping_output.setStyleSheet(
            "QPlainTextEdit{background:#FFF;border:1px solid #D0D0D0;border-radius:4px;padding:6px}")
        lo.addWidget(self._ping_output, stretch=1)
        return w

    def _start_ping(self):
        import threading, subprocess
        # 已在持续 ping 中, 再次点击则停止
        if self._ping_proc is not None:
            self._stop_ping()
            return
        target = self._ping_target.text().strip()
        if not target:
            return
        self._ping_output.appendPlainText(">>> Ping {} ...".format(target))
        self._btn_ping.setText("停止")

        # Windows 下隐藏 ping.exe 的控制台窗口
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        if os.name == "nt":
            cmd = ["ping", "-t", target]
        else:
            cmd = ["ping", target]
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=creationflags,
            )
        except Exception as e:
            self._ping_output.appendPlainText("启动 Ping 失败: {}".format(e))
            self._btn_ping.setText("Ping")
            return
        self._ping_proc = proc

        def reader():
            # 逐行读取, 实时回传 UI; 进程退出后发送结束事件
            try:
                for line in proc.stdout:
                    self._queue.put(("ping_line", line.rstrip("\r\n")))
            except Exception as e:
                self._queue.put(("ping_error", proc, str(e)))
            finally:
                self._queue.put(("ping_end", proc))

        threading.Thread(target=reader, daemon=True).start()

    def _stop_ping(self):
        proc = self._ping_proc
        self._ping_proc = None
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._btn_ping.setText("Ping")
        self._ping_output.appendPlainText(">>> 已停止")

    # ---------- 端口扫描 ----------
    def _build_port_page(self):
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setContentsMargins(8, 8, 8, 8)
        lo.setSpacing(8)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("目标主机:"))
        self._port_host = QLineEdit()
        self._port_host.setPlaceholderText("如 192.168.1.1 或 example.com")
        self._port_host.setFont(QFont("Consolas", 11))
        self._port_host.setMaximumWidth(340)
        row1.addWidget(self._port_host)
        row1.addStretch()
        lo.addLayout(row1)

        # 快捷预设 (置于端口设置上方)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("快捷预设:"))
        self._port_preset = QComboBox()
        self._port_preset.addItems([
            "自定义端口",
            "自定义范围",
            "常用端口 (1-1024)",
            "常见服务 (21/22/80/443/3306/3389...)",
            "全端口 (1-65535)",
        ])
        self._port_preset.setMaximumWidth(340)
        self._port_preset.currentIndexChanged.connect(self._on_port_preset)
        row2.addWidget(self._port_preset)
        row2.addStretch()
        lo.addLayout(row2)

        # 端口设置 (根据预设动态显示 1 个或 2 个输入框)
        # 用固定高度容器预留空间，避免切换预设时下方按钮/输出框上下跳动
        cfg_box = QWidget()
        cfg_box.setFixedHeight(34)
        row3 = QHBoxLayout(cfg_box)
        row3.setContentsMargins(0, 0, 0, 0)
        row3.setSpacing(6)
        self._port_cfg_label = QLabel("端口设置:")
        row3.addWidget(self._port_cfg_label)
        self._port_single = QSpinBox()
        self._port_single.setRange(1, 65535)
        self._port_single.setValue(80)
        self._port_single.setFixedWidth(110)
        row3.addWidget(self._port_single)

        self._port_start = QSpinBox()
        self._port_start.setRange(1, 65535)
        self._port_start.setValue(1)
        self._port_start.setFixedWidth(110)
        row3.addWidget(self._port_start)
        self._port_sep = QLabel("~")
        row3.addWidget(self._port_sep)
        self._port_end = QSpinBox()
        self._port_end.setRange(1, 65535)
        self._port_end.setValue(1024)
        self._port_end.setFixedWidth(110)
        row3.addWidget(self._port_end)
        row3.addStretch()
        lo.addWidget(cfg_box)

        self._btn_scan = QPushButton("开始扫描")
        self._btn_scan.setStyleSheet(
            "QPushButton{background:#0078D4;color:#FFF;border:none;border-radius:4px;"
            "padding:6px 20px;font-weight:600}QPushButton:hover{background:#106EBE}"
            "QPushButton:disabled{background:#CCC;color:#FFF}")
        self._btn_scan.setFixedWidth(110)
        self._btn_scan.clicked.connect(self._start_port_scan)
        btn_row = QHBoxLayout()
        btn_row.addWidget(self._btn_scan)
        btn_row.addStretch()
        lo.addLayout(btn_row)

        self._port_output = QPlainTextEdit()
        self._port_output.setReadOnly(True)
        self._port_output.setFont(QFont("Consolas", 10))
        self._port_output.setStyleSheet(
            "QPlainTextEdit{background:#FFF;border:1px solid #D0D0D0;border-radius:4px;padding:6px}")
        lo.addWidget(self._port_output, stretch=1)
        self._on_port_preset(0)
        return w

    def _on_port_preset(self, idx=0):
        # 0=自定义端口(1个输入框) 1=自定义范围(2个输入框) 其余=固定预设(隐藏输入及标签)
        if idx == 0:
            self._port_cfg_label.show()
            self._port_single.show()
            self._port_start.hide()
            self._port_sep.hide()
            self._port_end.hide()
        elif idx == 1:
            self._port_cfg_label.show()
            self._port_single.hide()
            self._port_start.show()
            self._port_sep.show()
            self._port_end.show()
        else:
            self._port_cfg_label.hide()
            self._port_single.hide()
            self._port_start.hide()
            self._port_sep.hide()
            self._port_end.hide()

    def _get_ports(self):
        idx = self._port_preset.currentIndex()
        if idx == 0:
            return [self._port_single.value()]
        if idx == 1:
            start = self._port_start.value()
            end = self._port_end.value()
            if start > end:
                start, end = end, start
            return list(range(start, end + 1))
        if idx == 2:
            return list(range(1, 1025))
        if idx == 3:
            return list(self.COMMON_PORTS)
        if idx == 4:
            return list(range(1, 65536))
        return [80]

    def _start_port_scan(self):
        import socket
        host = self._port_host.text().strip()
        if not host:
            return
        ports = self._get_ports()
        if not ports:
            return
        self._scan_kind = "port"
        self._btn_scan.setEnabled(False)
        self._open_ports = []
        self._pending = len(ports)
        self._port_output.setPlainText(
            "正在扫描 {} 的 {} 个端口 ...".format(host, len(ports)))

        def scan(p):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.5)
                if s.connect_ex((host, p)) == 0:
                    self._queue.put(("port_open", p))
                s.close()
            except Exception:
                pass
            finally:
                self._queue.put(("task_done", None))

        from concurrent.futures import ThreadPoolExecutor
        # 大范围扫描时提高并发以加速
        workers = 200 if len(ports) <= 1024 else 500
        ex = ThreadPoolExecutor(max_workers=workers)
        for p in ports:
            ex.submit(scan, p)
        ex.shutdown(wait=False)

    # ---------- 网段扫描 ----------
    def _build_lan_page(self):
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setContentsMargins(8, 8, 8, 8)
        lo.setSpacing(8)

        row = QHBoxLayout()
        row.addWidget(QLabel("网段:"))
        self._lan_input = QLineEdit()
        self._lan_input.setPlaceholderText("如 192.168.1.0/24")
        self._lan_input.setFont(QFont("Consolas", 11))
        self._lan_input.returnPressed.connect(self._start_lan_scan)
        row.addWidget(self._lan_input, stretch=1)
        self._btn_lan = QPushButton("扫描存活主机")
        self._btn_lan.setStyleSheet(
            "QPushButton{background:#0078D4;color:#FFF;border:none;border-radius:4px;"
            "padding:6px 20px;font-weight:600}QPushButton:hover{background:#106EBE}"
            "QPushButton:disabled{background:#CCC;color:#FFF}")
        self._btn_lan.clicked.connect(self._start_lan_scan)
        row.addWidget(self._btn_lan)
        lo.addLayout(row)

        self._lan_output = QPlainTextEdit()
        self._lan_output.setReadOnly(True)
        self._lan_output.setFont(QFont("Consolas", 10))
        self._lan_output.setStyleSheet(
            "QPlainTextEdit{background:#FFF;border:1px solid #D0D0D0;border-radius:4px;padding:6px}")
        lo.addWidget(self._lan_output, stretch=1)
        return w

    def _start_lan_scan(self):
        import ipaddress
        cidr = self._lan_input.text().strip()
        if not cidr:
            return
        try:
            net = ipaddress.ip_network(cidr, strict=False)
        except ValueError as e:
            self._lan_output.setPlainText("网段格式错误: {}".format(e))
            return
        hosts = list(net.hosts())
        if not hosts:
            hosts = [net.network_address]
        if len(hosts) > 1024:
            self._lan_output.setPlainText(
                "网段过大（{} 个主机），请缩小前缀".format(len(hosts)))
            return
        self._scan_kind = "lan"
        self._btn_lan.setEnabled(False)
        self._alive_ips = []
        self._pending = len(hosts)
        self._lan_output.setPlainText(
            "正在扫描 {}，共 {} 个主机 ...".format(cidr, len(hosts)))

        def check(ip):
            try:
                if self._ping_once(str(ip)):
                    self._queue.put(("lan_alive", str(ip)))
            finally:
                self._queue.put(("task_done", None))

        from concurrent.futures import ThreadPoolExecutor
        ex = ThreadPoolExecutor(max_workers=100)
        for h in hosts:
            ex.submit(check, h)
        ex.shutdown(wait=False)

    def _ping_once(self, ip):
        import subprocess
        try:
            if os.name == "nt":
                cmd = ["ping", "-n", "1", "-w", "300", ip]
            else:
                cmd = ["ping", "-c", "1", "-W", "1", ip]
            r = subprocess.run(
                cmd, capture_output=True, timeout=3,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            return r.returncode == 0
        except Exception:
            return False

    # ---------- 结果回传 ----------
    def _drain_queue(self):
        try:
            while True:
                msg = self._queue.get_nowait()
                kind = msg[0]
                if kind == "ping_line":
                    self._ping_output.appendPlainText(msg[1])
                    sb = self._ping_output.verticalScrollBar()
                    sb.setValue(sb.maximum())
                elif kind == "ping_end":
                    if msg[1] is self._ping_proc:
                        self._ping_proc = None
                        self._btn_ping.setText("Ping")
                elif kind == "ping_error":
                    if msg[1] is self._ping_proc:
                        self._ping_proc = None
                        self._btn_ping.setText("Ping")
                    self._ping_output.appendPlainText("Ping 出错: {}".format(msg[2]))
                elif kind == "port_open":
                    p = msg[1]
                    if p not in self._open_ports:
                        self._open_ports.append(p)
                        self._open_ports.sort()
                    self._port_output.appendPlainText("  开放端口: {}".format(p))
                elif kind == "lan_alive":
                    ip = msg[1]
                    if ip not in self._alive_ips:
                        self._alive_ips.append(ip)
                    self._lan_output.appendPlainText("  存活: {}".format(ip))
                elif kind == "task_done":
                    self._pending -= 1
                    if self._pending <= 0:
                        self._on_all_done()
        except Exception:
            pass

    def _on_all_done(self):
        if self._scan_kind == "port":
            self._btn_scan.setEnabled(True)
            if self._open_ports:
                self._port_output.appendPlainText(
                    "\n扫描完成，共开放 {} 个端口: {}".format(
                        len(self._open_ports), ", ".join(map(str, self._open_ports))))
            else:
                self._port_output.appendPlainText("\n扫描完成，未发现开放端口")
        elif self._scan_kind == "lan":
            self._btn_lan.setEnabled(True)
