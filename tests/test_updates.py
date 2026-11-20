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

from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from anhutoolbox.about_dialog import AboutDialog
from anhutoolbox.main_window import (
    MainWindow, UPDATE_RECHECK_INTERVAL_MS,
)
from anhutoolbox.update_ui import (
    UpdateAvailableDialog, UpdateDownloadDialog,
)
from anhutoolbox.updates import (
    ReleaseInfo, UpdateCheckWorker, UpdateDownloadWorker,
    is_newer_version, parse_manifest, version_tuple,
)
from anhutoolbox.version import (
    UPDATE_MANIFEST_URL, UPDATE_MANIFEST_URLS, __version__,
)
from create_update_manifest import build_manifest
import updater


APP = QApplication.instance() or QApplication([])
ROOT = Path(__file__).resolve().parents[1]


class _DownloadHandler(BaseHTTPRequestHandler):
    payload = b"installer-bytes"

    def do_GET(self):
        if self.path.startswith("/missing"):
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers()
        self.wfile.write(self.payload)

    def log_message(self, format, *args):
        pass


class UpdateTests(unittest.TestCase):
    def test_about_dialog_contains_version_and_manual_check(self):
        dialog = AboutDialog()
        try:
            labels = [
                label.text() for label in dialog.findChildren(QLabel)
            ]
            self.assertTrue(any(
                f"当前版本：V{__version__}" == text for text in labels))
            self.assertTrue(dialog.status.isHidden())
            checked = []
            dialog.check_update_requested.connect(lambda: checked.append(1))
            dialog.check_button.click()
            self.assertEqual(checked, [1])
            self.assertEqual(dialog.status.text(), "正在检查更新...")
            self.assertFalse(dialog.status.isHidden())
        finally:
            dialog.close()
            dialog.deleteLater()
            APP.processEvents()

    def test_update_prompt_explains_automatic_restart(self):
        release = ReleaseInfo(
            version="1.0.3",
            installer_url=(
                "https://github.com/Jinchoo-Zhu/AnhuToolbox/"
                "releases/download/v1.0.3/AnhuToolbox_Setup_1.0.3.exe"
            ),
            sha256="d" * 64,
            size=1024,
        )
        dialog = UpdateAvailableDialog(release)
        try:
            labels = [
                label.text() for label in dialog.findChildren(QLabel)
            ]
            buttons = [
                button.text() for button in dialog.findChildren(QPushButton)
            ]
            self.assertTrue(any(
                "安装完成后会自动重新启动" in text for text in labels))
            self.assertIn("暂不更新", buttons)
            self.assertIn("跳过此版本", buttons)
            self.assertIn("立即更新并重启", buttons)
        finally:
            dialog.close()
            dialog.deleteLater()
            APP.processEvents()

    def test_download_dialog_can_continue_in_background(self):
        release = ReleaseInfo(
            version="1.0.3",
            installer_url=(
                "https://github.com/Jinchoo-Zhu/AnhuToolbox/"
                "releases/download/v1.0.3/AnhuToolbox_Setup_1.0.3.exe"
            ),
            sha256="f" * 64,
            size=1024,
        )
        worker = mock.MagicMock()
        worker.isRunning.return_value = False
        with mock.patch(
                "anhutoolbox.update_ui.UpdateDownloadWorker",
                return_value=worker):
            dialog = UpdateDownloadDialog(release)
        backgrounded = []
        dialog.background_requested.connect(lambda: backgrounded.append(1))
        try:
            self.assertEqual(dialog.background_button.text(), "后台更新")
            dialog.show()
            APP.processEvents()
            dialog.background_button.click()
            APP.processEvents()
            self.assertTrue(dialog.isHidden())
            self.assertEqual(backgrounded, [1])
        finally:
            dialog.reject()
            dialog.deleteLater()
            APP.processEvents()

    def test_main_window_keeps_modeless_download_and_restores_it(self):
        release = ReleaseInfo(
            version="9.9.9",
            installer_url=(
                "https://github.com/Jinchoo-Zhu/AnhuToolbox/"
                "releases/download/v9.9.9/AnhuToolbox_Setup_9.9.9.exe"
            ),
            sha256="a" * 64,
            size=100,
        )
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch(
                    "anhutoolbox.hardware.collect_hardware_info",
                    return_value={}):
                window = MainWindow(temp)
            try:
                window._on_update_available(release, manual=True)
                prompt = mock.MagicMock()
                prompt.decision = "update"
                download = mock.MagicMock()
                download.release = release
                installer_path = str(Path(temp) / "update.exe")
                Path(installer_path).write_bytes(b"installer")
                download.download_path = installer_path
                with mock.patch(
                        "anhutoolbox.main_window.UpdateAvailableDialog",
                        return_value=prompt), mock.patch(
                        "anhutoolbox.main_window.UpdateDownloadDialog",
                        return_value=download):
                    window._prompt_for_update()
                self.assertIs(window._update_download_dialog, download)
                download.show.assert_called_once()
                window._on_update_backgrounded(release)
                self.assertEqual(
                    window._btn_update_available.text(),
                    "后台更新 V9.9.9")
                window._prompt_for_update()
                download.showNormal.assert_called_once()
                with mock.patch.object(
                        window, "_install_downloaded_update") as install:
                    with mock.patch(
                            "anhutoolbox.main_window.ask_yes_no",
                            return_value=True):
                        window._on_update_download_ready(download)
                install.assert_called_once_with(
                    release, installer_path)
                self.assertIsNone(window._update_download_dialog)
            finally:
                window.close()
                window.deleteLater()
                APP.processEvents()

    def test_downloaded_update_waits_for_user_install_confirmation(self):
        release = ReleaseInfo(
            version="9.9.9",
            installer_url=(
                "https://github.com/Jinchoo-Zhu/AnhuToolbox/"
                "releases/download/v9.9.9/AnhuToolbox_Setup_9.9.9.exe"
            ),
            sha256="a" * 64,
            size=100,
        )
        with tempfile.TemporaryDirectory() as temp:
            installer_path = str(Path(temp) / "update.exe")
            Path(installer_path).write_bytes(b"installer")
            with mock.patch(
                    "anhutoolbox.hardware.collect_hardware_info",
                    return_value={}):
                window = MainWindow(temp)
            try:
                window._on_update_available(release, manual=True)
                download = mock.MagicMock()
                download.release = release
                download.download_path = installer_path
                window._update_download_dialog = download
                with mock.patch.object(
                        window, "_install_downloaded_update") as install, \
                        mock.patch(
                            "anhutoolbox.main_window.ask_yes_no",
                            return_value=False):
                    window._on_update_download_ready(download)
                install.assert_not_called()
                self.assertEqual(
                    window._downloaded_update,
                    (release, installer_path))
                self.assertEqual(
                    window._btn_update_available.text(),
                    "更新已下载，点击安装")
                with mock.patch.object(
                        window, "_install_downloaded_update") as install, \
                        mock.patch(
                            "anhutoolbox.main_window.ask_yes_no",
                            return_value=True):
                    window._prompt_for_update()
                install.assert_called_once_with(release, installer_path)
                self.assertIsNone(window._downloaded_update)
            finally:
                window.close()
                window.deleteLater()
                APP.processEvents()

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
        server_release = parse_manifest({
            **payload,
            "installer_url": (
                "https://mcsgzy.online:8443/anhutoolbox/"
                "releases/v1.0.1/AnhuToolbox_Setup_1.0.1.exe"
            ),
            "installer_urls": [
                (
                    "https://mcsgzy.online:8443/anhutoolbox/"
                    "releases/v1.0.1/AnhuToolbox_Setup_1.0.1.exe"
                ),
                (
                    "https://github.com/Jinchoo-Zhu/AnhuToolbox/"
                    "releases/download/v1.0.1/"
                    "AnhuToolbox_Setup_1.0.1.exe"
                ),
            ],
        })
        self.assertEqual(
            server_release.installer_url,
            "https://mcsgzy.online:8443/anhutoolbox/"
            "releases/v1.0.1/AnhuToolbox_Setup_1.0.1.exe",
        )
        self.assertEqual(len(server_release.download_urls), 2)
        with self.assertRaises(ValueError):
            parse_manifest({
                **payload,
                "installer_urls": [
                    (
                        "https://mcsgzy.online:8443/anhutoolbox/"
                        "releases/v1.0.1/"
                        "AnhuToolbox_Setup_1.0.1.exe"
                    ),
                    (
                        "https://gy.example/"
                        "releases/v1.0.1/"
                        "AnhuToolbox_Setup_1.0.1.exe"
                    ),
                ],
            })
        with self.assertRaises(ValueError):
            parse_manifest({**payload, "installer_url": "http://evil.test/x.exe"})
        with self.assertRaises(ValueError):
            parse_manifest({
                **payload,
                "installer_url": (
                    "https://mcsgzy.online:443/anhutoolbox/"
                    "releases/v1.0.1/AnhuToolbox_Setup_1.0.1.exe"
                ),
            })
        with self.assertRaises(ValueError):
            parse_manifest({
                **payload,
                "installer_url": (
                    "https://mcsgzy.online:8443/anhutoolbox/"
                    "releases/../private.exe"
                ),
            })
        with self.assertRaises(ValueError):
            parse_manifest({**payload, "mandatory": "false"})

    def test_update_check_worker_uses_release_manifest(self):
        self.assertEqual(
            UPDATE_MANIFEST_URL,
            "https://mcsgzy.online:8443/anhutoolbox/updates/latest.json",
        )
        self.assertEqual(len(UPDATE_MANIFEST_URLS), 2)
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

    def test_update_check_worker_uses_highest_available_source(self):
        def manifest(version, filename):
            return json.dumps({
                "version": version,
                "installer_url": (
                    "https://mcsgzy.online:8443/anhutoolbox/"
                    f"releases/v{version}/{filename}"
                ),
                "sha256": "b" * 64,
                "size": 456,
            }).encode("utf-8")

        def read_manifest(url):
            if url == UPDATE_MANIFEST_URLS[0]:
                raise RuntimeError("server unavailable")
            if url == UPDATE_MANIFEST_URLS[1]:
                return manifest("1.0.4", "AnhuToolbox_Setup_1.0.4.exe")
            return manifest("1.0.3", "AnhuToolbox_Setup_1.0.3.exe")

        worker = UpdateCheckWorker("1.0.3")
        found = []
        worker.available.connect(found.append)
        with mock.patch(
                "anhutoolbox.updates._read_manifest",
                side_effect=read_manifest):
            worker.run()
        self.assertEqual(found[0].version, "1.0.4")

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

    def test_download_worker_falls_back_to_secondary_source(self):
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0), _DownloadHandler)
        thread = threading.Thread(
            target=server.serve_forever, daemon=True)
        thread.start()
        try:
            payload = _DownloadHandler.payload
            release = ReleaseInfo(
                version="1.0.4",
                installer_url="http://127.0.0.1:{}/missing".format(
                    server.server_address[1]),
                installer_urls=(
                    "http://127.0.0.1:{}/setup.exe".format(
                        server.server_address[1]),
                ),
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
            self.assertEqual(
                manifest["installer_url"],
                "https://mcsgzy.online:8443/anhutoolbox/"
                f"releases/v{__version__}/"
                f"AnhuToolbox_Setup_{__version__}.exe",
            )
            self.assertEqual(len(manifest["installer_urls"]), 2)
            self.assertIn(
                "https://github.com/Jinchoo-Zhu/AnhuToolbox/",
                manifest["installer_urls"][1],
            )

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
                window._on_update_available(release)
                self.assertFalse(window._btn_update_available.isHidden())
                self.assertEqual(
                    window._btn_update_available.text(),
                    "发现新版本 V9.9.9")
                dialog = mock.MagicMock()
                dialog.decision = "skip"
                with mock.patch(
                        "anhutoolbox.main_window.UpdateAvailableDialog",
                        return_value=dialog):
                    window._btn_update_available.click()
                settings = json.loads(
                    (Path(temp) / "data" / "settings.json").read_text(
                        encoding="utf-8"))
                self.assertEqual(
                    settings["update_skipped_version"], "9.9.9")
                self.assertTrue(window._btn_update_available.isHidden())
            finally:
                window.close()
                window.deleteLater()
                APP.processEvents()

    def test_update_runs_after_launch_and_periodically_while_open(self):
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch(
                    "anhutoolbox.hardware.collect_hardware_info",
                    return_value={}):
                window = MainWindow(temp)
            try:
                self.assertTrue(window._update_initial_timer.isActive())
                self.assertTrue(window._update_check_timer.isActive())
                self.assertEqual(
                    window._update_check_timer.interval(),
                    UPDATE_RECHECK_INTERVAL_MS)
                self.assertFalse(window._update_check_timer.isSingleShot())
            finally:
                window.close()
                window.deleteLater()
                APP.processEvents()

    def test_manual_update_check_bypasses_skipped_version(self):
        release = ReleaseInfo(
            version="9.9.9",
            installer_url=(
                "https://github.com/Jinchoo-Zhu/AnhuToolbox/"
                "releases/download/v9.9.9/AnhuToolbox_Setup_9.9.9.exe"
            ),
            sha256="e" * 64,
            size=100,
        )
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch(
                    "anhutoolbox.hardware.collect_hardware_info",
                    return_value={}):
                window = MainWindow(temp)
            try:
                with mock.patch(
                        "anhutoolbox.main_window.cfg.get",
                        return_value="9.9.9"):
                    window._on_update_available(release)
                self.assertTrue(window._btn_update_available.isHidden())
                window._on_update_available(release, manual=True)
                self.assertFalse(window._btn_update_available.isHidden())
                self.assertIn(
                    "请点击顶部提示查看",
                    window.status_bar.currentMessage(),
                )
                self.assertFalse(
                    window._info_bar.isAncestorOf(
                        window._btn_update_available))
            finally:
                window.close()
                window.deleteLater()
                APP.processEvents()

    def test_manual_check_reports_latest_and_failed_states(self):
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch(
                    "anhutoolbox.hardware.collect_hardware_info",
                    return_value={}):
                window = MainWindow(temp)
            try:
                with mock.patch.object(
                        window, "_start_update_check") as start_check:
                    window._manual_check_update()
                start_check.assert_called_once_with(manual=True)
                window._on_update_up_to_date(manual=True)
                self.assertEqual(
                    window.status_bar.currentMessage(),
                    "当前已是最新版本",
                )
                window._on_update_check_failed("network", manual=True)
                self.assertIn(
                    "检查更新失败",
                    window.status_bar.currentMessage(),
                )
            finally:
                window.close()
                window.deleteLater()
                APP.processEvents()


if __name__ == "__main__":
    unittest.main()
