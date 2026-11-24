# -*- coding: utf-8 -*-
"""DPAPI project-secret encryption tests."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from anhutoolbox.projects import ProjectManager
from anhutoolbox.secret_store import decrypt_secrets, encrypt_secrets


@unittest.skipUnless(os.name == "nt", "Windows DPAPI only")
class SecretStoreTests(unittest.TestCase):
    def test_nested_secrets_roundtrip(self):
        source = {
            "mqtt": {"password": "mqtt-secret"},
            "http": {
                "headers": [
                    {"name": "Authorization", "value": "Bearer token"},
                ],
            },
            "users": [
                {"username": "admin", "password": "server-secret"},
            ],
        }
        encrypted = encrypt_secrets(source)
        self.assertNotIn("mqtt-secret", json.dumps(encrypted))
        self.assertNotIn("Bearer token", json.dumps(encrypted))
        self.assertNotIn("server-secret", json.dumps(encrypted))
        self.assertEqual(decrypt_secrets(encrypted), source)

    def test_project_manager_encrypts_disk_and_decrypts_load(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = ProjectManager(temp)
            data = {
                "name": "安全项目",
                "mqtt": {"password": "project-secret"},
                "token": "abc123",
            }
            self.assertTrue(manager.save("安全项目", data))
            path = Path(manager.path_of("安全项目"))
            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("project-secret", raw)
            self.assertNotIn("abc123", raw)
            loaded = manager.load("安全项目")
            self.assertEqual(
                loaded["mqtt"]["password"], "project-secret")
            self.assertEqual(loaded["token"], "abc123")

    def test_export_and_import_keep_secrets_usable_for_same_user(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = ProjectManager(temp)
            manager.save(
                "导出项目",
                {"mqtt": {"password": "export-secret"}},
            )
            export_path = Path(temp) / "portable.json"
            self.assertTrue(
                manager.export_to("导出项目", str(export_path)))
            self.assertNotIn(
                "export-secret",
                export_path.read_text(encoding="utf-8"),
            )
            imported = manager.import_from(str(export_path))
            self.assertTrue(imported)
            loaded = manager.load(imported)
            self.assertEqual(
                loaded["mqtt"]["password"], "export-secret")

    def test_legacy_plaintext_project_is_encrypted_on_next_save(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = ProjectManager(temp)
            path = Path(manager.dir) / "旧项目.json"
            path.write_text(json.dumps({
                "format": 1,
                "name": "旧项目",
                "mqtt": {"password": "dpapi-v1:legacy-secret"},
            }, ensure_ascii=False), encoding="utf-8")
            loaded = manager.load("旧项目")
            self.assertEqual(
                loaded["mqtt"]["password"], "dpapi-v1:legacy-secret")
            self.assertTrue(manager.save("旧项目", loaded))
            encrypted = path.read_text(encoding="utf-8")
            self.assertNotIn("legacy-secret", encrypted)
            self.assertIn("dpapi-v1:", encrypted)
            self.assertEqual(
                manager.load("旧项目")["mqtt"]["password"],
                "dpapi-v1:legacy-secret",
            )

    def test_rename_preserves_dpapi_secret(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = ProjectManager(temp)
            self.assertTrue(manager.save(
                "原项目", {"mqtt": {"password": "rename-secret"}}))
            renamed = manager.rename("原项目", "新项目")
            self.assertEqual(renamed, "新项目")
            self.assertEqual(
                manager.load("新项目")["mqtt"]["password"],
                "rename-secret",
            )

    def test_corrupt_ciphertext_reports_error_without_overwriting(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = ProjectManager(temp)
            self.assertTrue(manager.save(
                "损坏项目", {"mqtt": {"password": "valid-secret"}}))
            path = Path(manager.path_of("损坏项目"))
            data = json.loads(path.read_text(encoding="utf-8"))
            data["mqtt"]["password"] = "dpapi-v1:not-valid-dpapi-data"
            path.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8")
            before = path.read_bytes()
            self.assertIsNone(manager.load("损坏项目"))
            self.assertIn("DPAPI", manager.last_error)
            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
