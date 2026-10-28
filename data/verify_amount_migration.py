# -*- coding: utf-8 -*-
"""迁移后的金额工具回归；只在独立 QApplication 内检查页面与换算结果。"""
import sys
from decimal import Decimal
from pathlib import Path

from PySide6.QtWidgets import QApplication

ROOT = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(ROOT))

# 主窗口会正常保存关闭状态；先备份本地状态，验证后原样恢复。
project_path = ROOT / "data" / "projects" / "默认项目.json"
project_backup = project_path.read_bytes() if project_path.exists() else None
settings_path = ROOT / "data" / "settings.json"
settings_backup = settings_path.read_bytes() if settings_path.exists() else None

from anhutoolbox.tools import (
    AmountTool, amount_to_chinese, chinese_to_amount, parse_amount_text,
)

CASES = [
    ("892.88", "捌佰玖拾贰元捌角捌分"),
    ("10020.05", "壹万零贰拾元零伍分"),
    ("100000001.00", "壹亿零壹元整"),
    ("0.50", "零元伍角整"),
    ("10020.04", "壹万零贰拾元零肆分"),
    ("100010001.01", "壹亿零壹万零壹元零壹分"),
    ("9999999999999999.99", "玖仟玖佰玖拾玖万亿玖仟玖佰玖拾玖亿玖仟玖佰玖拾玖万玖仟玖佰玖拾玖元玖角玖分"),
]

for number, chinese in CASES:
    actual = amount_to_chinese(parse_amount_text(number))
    assert actual == chinese, (number, actual, chinese)
    reverse = chinese_to_amount(chinese)
    assert reverse == parse_amount_text(number), (chinese, reverse)
    assert chinese_to_amount(chinese) == parse_amount_text(number)

app = QApplication([])
tool = AmountTool()
tool.resize(1040, 720)
tool.show()
app.processEvents()

assert tool._amount_input.text() == ""
assert tool._upper_output.text() == ""
tool._amount_input.setText("892.88")
app.processEvents()
assert tool._upper_output.text() == "捌佰玖拾贰元捌角捌分"
tool._upper_input.setText("壹万零贰拾元零伍分")
app.processEvents()
assert tool._lower_output.text() == "10020.05"
assert tool._upper_output.text() == "捌佰玖拾贰元捌角捌分"
tool._upper_input.setText("壹亿零壹万零壹元零壹分")
app.processEvents()
assert tool._lower_output.text() == "100010001.01"
assert tool._upper_output.text() == "捌佰玖拾贰元捌角捌分"
tool._btn_copy_upper.click()
assert app.clipboard().text() == tool._upper_output.text()
assert tool._copy_toast.isVisible()

screenshot = ROOT / "data" / "amount_migration_preview.png"
tool.grab().save(str(screenshot))
tool.close()

# 不仅打开独立页面，还要确认备份项目的主窗口能加载新页面。
from anhutoolbox.main_window import MainWindow, LIBRARY_GROUPS, LIBRARY_ORDER

try:
    window = MainWindow(str(ROOT))
    window._build_extra_tabs()
    assert window._library_pages["amount"] is not None
    assert window._library_stack.indexOf(window._library_pages["amount"]) >= 0
    categories = dict(LIBRARY_GROUPS)
    keys = [key for key, _ in categories["转换与计算"]]
    assert keys.index("amount") == keys.index("checksum") + 1
    assert set(LIBRARY_ORDER) == set(window._library_pages)
    window.close()
finally:
    if project_backup is not None:
        project_path.write_bytes(project_backup)
    if settings_backup is not None:
        settings_path.write_bytes(settings_backup)

print("AMOUNT_MIGRATION_OK")
