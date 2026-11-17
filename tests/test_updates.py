# -*- coding: utf-8 -*-
"""自动更新检查、下载和发布脚本测试。"""

import hashlib
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from anhutoolbox.main_window import MainWindow
from anhutoolbox.updates import (
    ReleaseInfo, UpdateCheckWorker, UpdateDownloadWorker,
    is_newer_version, parse_manifest, version_tuple,
)
from anhutoolbox.version import __version__
from create_update_manifest import build_manifest
import updater


APP = QApplication.instance() or QApplication([])
ROOT = Path(__file__).resolve().parents[1]


class _DownloadHandler(BaseHTTPRequestHandler):
    payload = b"installer-bytes"

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers()
        self.wfile.write(self.payload)

    def log_message(self, format, *args):
        pass


class UpdateTests(unittest.TestCase):
    def test_version_comparison_and_manifest_validation(self):
        self.assertEqual(version_tuple("v1.2.3"), (1, 2, 3))
        self.assertTrue(is_newer_version("1.0.1", "1.0.0"))
        self.assertFalse(is_newer_version("1.0.0", "1.0.0"))
        payload = {
            "version": "1.0.1",
            "installer_url": (
                "https://github.com/Jinchoo-Zhu/AnhuToolbox/"
                "releases/download/v1.0.1/AnhuToolbox_Setup_1.0.1.exe"
            ),
            "sha256": "a" * 64,
            "size": 123,
            "notes": "fixes",
        }
        release = parse_manifest(payload)
        self.assertEqual(release.version, "1.0.1")
        with self.assertRaises(ValueError):
            parse_manifest({**payload, "installer_url": "http://evil.test/x.exe"})
        with self.assertRaises(ValueError):
            parse_manifest({**payload, "mandatory": "false"})

    def test_update_check_worker_uses_release_manifest(self):
        payload = json.dumps({
            "version": "1.0.1",
            "installer_url": (
                "https://github.com/Jinchoo-Zhu/AnhuToolbox/"
                "releases/download/v1.0.1/AnhuToolbox_Setup_1.0.1.exe"
            ),
            "sha256": "b" * 64,
            "size": 456,
        }).encode("utf-8")
        worker = UpdateCheckWorker("1.0.0")
        found = []
        worker.available.connect(found.append)
        with mock.patch(
                "anhutoolbox.updates._read_manifest", return_value=payload):
            worker.run()
        self.assertEqual(found[0].version, "1.0.1")

    def test_download_worker_verifies_hash_and_size(self):
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0), _DownloadHandler)
        thread = threading.Thread(
            target=server.serve_forever, daemon=True)
        thread.start()
        try:
            payload = _DownloadHandler.payload
            release = ReleaseInfo(
                version="1.0.1",
                installer_url="http://127.0.0.1:{}/setup.exe".format(
                    server.server_address[1]),
                sha256=hashlib.sha256(payload).hexdigest(),
                size=len(payload),
            )
            with tempfile.TemporaryDirectory() as temp:
                worker = UpdateDownloadWorker(release, temp)
                completed = []
                failed = []
                worker.completed.connect(completed.append)
                worker.failed.connect(failed.append)
                worker.start()
                self.assertTrue(worker.wait(5000))
                APP.processEvents()
                self.assertFalse(failed)
                self.assertTrue(completed)
                self.assertEqual(Path(completed[0]).read_bytes(), payload)
        finally:
            server.shutdown()
            server.server_close()

    def test_release_manifest_builder_and_updater_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            installer = (
                Path(temp) / f"AnhuToolbox_Setup_{__version__}.exe")
            installer.write_bytes(b"signed-installer-placeholder")
            manifest = build_manifest(
                ROOT, installer, __version__, "release notes")
            self.assertEqual(manifest["size"], installer.stat().st_size)
            self.assertEqual(
                updater.sha256_file(installer), manifest["sha256"])
            self.assertIn(
                f"/releases/download/v{__version__}/",
                manifest["installer_url"])

    def test_updater_restarts_application_after_install(self):
        with tempfile.TemporaryDirectory() as temp:
            installer = Path(temp) / "update.exe"
            installer.write_bytes(b"installer")
            app_path = str(Path(temp) / "Anhu百宝箱.exe")
            log_path = str(Path(temp) / "updater.log")
            argv = [
                "AnhuUpdater.exe",
                "--pid", "123",
                "--installer", str(installer),
                "--sha256", "a" * 64,
                "--app", app_path,
                "--log", log_path,
            ]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                    updater, "wait_for_process", return_value=True), \
                    mock.patch.object(
                        updater, "sha256_file", return_value="a" * 64), \
                    mock.patch.object(
                        updater.logging, "basicConfig"), \
                    mock.patch.object(
                        updater.subprocess, "run") as run_installer, \
                    mock.patch.object(
                        updater, "start_application",
                        return_value=True) as start_application:
                run_installer.return_value.returncode = 0
                self.assertEqual(updater.main(), 0)
            start_application.assert_called_once_with(app_path)

    def test_packaging_contains_updater_and_close_applications(self):
        updater_spec = (ROOT / "AnhuUpdater.spec").read_text(encoding="utf-8")
        installer = (ROOT / "installer.iss").read_text(encoding="utf-8")
        self.assertIn("name='AnhuUpdater'", updater_spec)
        self.assertIn("AnhuUpdater.exe", installer)
        self.assertIn("CloseApplications=yes", installer)
        self.assertIn("AnhuToolbox_Setup_{#MyAppVersion}", installer)

    def test_skip_version_is_persisted(self):
        release = ReleaseInfo(
            version="9.9.9",
            installer_url=(
                "https://github.com/Jinchoo-Zhu/AnhuToolbox/"
                "releases/download/v9.9.9/AnhuToolbox_Setup_9.9.9.exe"
            ),
            sha256="c" * 64,
            size=100,
        )
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch(
                    "anhutoolbox.hardware.collect_hardware_info",
                    return_value={}):
                window = MainWindow(temp)
            try:
                window._extra_tabs_timer.stop()
                dialog = mock.MagicMock()
                dialog.decision = "skip"
                with mock.patch(
                        "anhutoolbox.main_window.UpdateAvailableDialog",
                        return_value=dialog):
                    window._on_update_available(release)
                settings = json.loads(
                    (Path(temp) / "data" / "settings.json").read_text(
                        encoding="utf-8"))
                self.assertEqual(
                    settings["update_skipped_version"], "9.9.9")
            finally:
                window.close()
                window.deleteLater()
                APP.processEvents()


if __name__ == "__main__":
    unittest.main()
