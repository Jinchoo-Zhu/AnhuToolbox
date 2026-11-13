# -*- coding: utf-8 -*-
"""HTTP 接口导入导出格式测试。"""

import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from anhutoolbox.http_page import HTTPPage
from anhutoolbox.http_transfer_dialogs import (
    ExportTransferDialog, ImportTransferDialog,
)
from anhutoolbox.http_transfer import (
    FORMAT_APIPOST, FORMAT_POSTMAN, FORMAT_SWAGGER,
    build_transfer, detect_format, parse_transfer,
)


APP = QApplication.instance() or QApplication([])


def _library():
    return {
        "folders": [
            {"id": "folder-1", "name": "业务接口", "parent_id": None},
            {"id": "folder-2", "name": "订单", "parent_id": "folder-1"},
        ],
        "interfaces": [{
            "id": "api-1",
            "name": "创建订单",
            "folder_id": "folder-2",
            "request": {
                "method": "POST",
                "url": "https://api.example.com/orders?id=1",
                "timeout": 15,
                "follow_redirects": False,
                "verify_tls": True,
                "http_version": "http/1.1",
                "params": [{
                    "name": "id", "value": "1",
                    "description": "", "enabled": True,
                }],
                "headers": [{
                    "name": "X-Test", "value": "yes",
                    "description": "", "enabled": True,
                }],
                "path_params": [],
                "cookies": [],
                "body_type": "raw",
                "raw_format": "JSON",
                "body": '{"name":"demo"}',
                "auth_type": "Bearer",
                "auth_user": "",
                "auth_password": "",
                "auth_token": "token",
                "response_example": '{"ok":true}',
            },
        }],
        "environments": [{
            "id": "env-1",
            "name": "测试环境",
            "variables": [{
                "name": "host",
                "value": "api.example.com",
                "description": "",
            }],
        }],
        "active_environment": "env-1",
    }


class HttpTransferTests(unittest.TestCase):
    def test_postman_round_trip_preserves_folder_and_request(self):
        data = build_transfer(
            _library(), FORMAT_POSTMAN, "测试项目")
        self.assertEqual(detect_format(data), FORMAT_POSTMAN)
        result = parse_transfer(data)
        self.assertEqual(len(result["interfaces"]), 1)
        interface = result["interfaces"][0]
        self.assertEqual(interface["name"], "创建订单")
        self.assertEqual(
            interface["folder_path"], ("业务接口", "订单"))
        self.assertEqual(interface["request"]["method"], "POST")
        self.assertIn("/orders", interface["request"]["url"])
        self.assertEqual(
            interface["request"]["headers"][0]["name"], "X-Test")
        self.assertEqual(
            interface["request"]["auth_token"], "token")
        self.assertEqual(
            result["environments"][0]["variables"][0]["name"], "host")

    def test_swagger_round_trip_preserves_request_body(self):
        data = build_transfer(
            _library(), FORMAT_SWAGGER, "测试项目")
        self.assertEqual(detect_format(data), FORMAT_SWAGGER)
        result = parse_transfer(data)
        interface = result["interfaces"][0]
        self.assertEqual(
            interface["folder_path"], ("业务接口", "订单"))
        self.assertEqual(interface["request"]["method"], "POST")
        self.assertEqual(interface["request"]["body_type"], "raw")
        self.assertIn("demo", interface["request"]["body"])

    def test_apipost_export_can_be_parsed_back(self):
        data = build_transfer(
            _library(), FORMAT_APIPOST, "测试项目")
        self.assertEqual(detect_format(data), FORMAT_APIPOST)
        result = parse_transfer(data)
        interface = result["interfaces"][0]
        self.assertEqual(interface["name"], "创建订单")
        self.assertEqual(
            interface["folder_path"], ("业务接口", "订单"))
        self.assertEqual(interface["request"]["method"], "POST")
        self.assertIn("/orders", interface["request"]["url"])
        self.assertEqual(
            interface["request"]["auth_token"], "token")
        self.assertEqual(
            interface["request"]["response_example"], '{"ok":true}')
        self.assertEqual(
            result["environments"][0]["variables"][0]["name"], "host")

    def test_import_dialog_loads_and_previews_postman_file(self):
        data = build_transfer(_library(), FORMAT_POSTMAN, "测试项目")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp, "postman.json")
            path.write_text(
                json.dumps(data, ensure_ascii=False),
                encoding="utf-8",
            )
            dialog = ImportTransferDialog()
            try:
                self.assertEqual(
                    dialog._radio_current.text(),
                    "导入当前项目，当前分支",
                )
                self.assertEqual(
                    dialog._radio_new_project.text(), "作为新项目")
                self.assertFalse(dialog._radio_new_project.isChecked())
                with mock.patch(
                        "anhutoolbox.http_transfer_dialogs."
                        "QFileDialog.getOpenFileName",
                        return_value=(str(path), "")):
                    dialog._choose_file()
                self.assertIsNotNone(dialog.transfer_result)
                self.assertEqual(
                    len(dialog.transfer_result["interfaces"]), 1)
                self.assertIn("接口：1 个", dialog._preview.text())
                self.assertTrue(dialog._import_button.isEnabled())
                self.assertEqual(dialog.source_name, "postman")
            finally:
                dialog.close()
                dialog.deleteLater()
                APP.processEvents()

    def test_transfer_format_card_is_clickable_as_a_whole(self):
        dialog = ExportTransferDialog()
        try:
            dialog.show()
            APP.processEvents()
            card = dialog._cards[1]
            QTest.mouseClick(
                card, Qt.MouseButton.LeftButton,
                pos=card.rect().center())
            self.assertTrue(card.radio.isChecked())
            self.assertTrue(card.property("selected"))
        finally:
            dialog.close()
            dialog.deleteLater()
            APP.processEvents()

    def test_http_import_into_current_folder_and_skip_duplicates(self):
        page = HTTPPage()
        try:
            target = page.create_folder("导入目标")
            transfer = parse_transfer(
                build_transfer(_library(), FORMAT_POSTMAN))
            imported, skipped = page._apply_transfer(
                transfer, target, "skip")
            self.assertEqual((imported, skipped), (1, 0))
            record = page.interfaces()[0]
            self.assertEqual(
                page._folder_path(record["folder_id"]),
                ("导入目标", "业务接口", "订单"),
            )
            imported_again, skipped_again = page._apply_transfer(
                transfer, target, "skip")
            self.assertEqual((imported_again, skipped_again), (0, 1))
        finally:
            page.cleanup()
            page.deleteLater()
            APP.processEvents()

    def test_export_library_includes_unsaved_current_document(self):
        page = HTTPPage()
        try:
            page.create_folder("草稿目录")
            page.new_document()
            page._url.setText("https://example.com/draft")
            library = page._transfer_library()
            self.assertEqual(len(library["interfaces"]), 1)
            self.assertEqual(
                library["interfaces"][0]["name"], "未命名接口")
            self.assertEqual(
                library["interfaces"][0]["request"]["url"],
                "https://example.com/draft")
        finally:
            page.cleanup()
            page.deleteLater()
            APP.processEvents()


if __name__ == "__main__":
    unittest.main()
