# -*- coding: utf-8 -*-
"""GitHub Release 更新检查、下载和更新器启动。"""

import hashlib
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
from dataclasses import dataclass

import httpx
from PySide6.QtCore import QThread, Signal

from .version import (
    GITHUB_OWNER, GITHUB_REPO, UPDATE_MANIFEST_URL, __version__,
)

MAX_MANIFEST_BYTES = 64 * 1024
MAX_INSTALLER_BYTES = 2 * 1024 * 1024 * 1024
USER_AGENT = "AnhuToolbox/{}".format(__version__)
_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class UpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    installer_url: str
    sha256: str
    size: int
    notes: str = ""
    mandatory: bool = False
    manifest_url: str = UPDATE_MANIFEST_URL


def version_tuple(value):
    match = _VERSION_RE.fullmatch(str(value or "").strip())
    if not match:
        raise ValueError("无效版本号：{}".format(value))
    return tuple(int(part) for part in match.groups())


def parse_manifest(payload, manifest_url=UPDATE_MANIFEST_URL):
    if not isinstance(payload, dict):
        raise ValueError("更新清单必须是 JSON 对象")
    version = str(payload.get("version") or "").strip()
    version_tuple(version)
    installer_url = str(payload.get("installer_url") or "").strip()
    parsed = urllib.parse.urlsplit(installer_url)
    expected_prefix = "/{}/{}/releases/download/".format(
        GITHUB_OWNER, GITHUB_REPO).lower()
    if (
        parsed.scheme.lower() != "https"
        or parsed.netloc.lower() != "github.com"
        or not parsed.path.lower().startswith(expected_prefix)
        or not parsed.path.lower().endswith(".exe")
    ):
        raise ValueError("安装包地址不是受信任的 GitHub Release")
    sha256 = str(payload.get("sha256") or "").strip().lower()
    if not _SHA256_RE.fullmatch(sha256):
        raise ValueError("更新清单 SHA-256 格式错误")
    try:
        size = int(payload.get("size"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("更新清单文件大小错误") from exc
    if size <= 0 or size > MAX_INSTALLER_BYTES:
        raise ValueError("安装包大小超出允许范围")
    notes = str(payload.get("notes") or "")[:10000]
    mandatory = payload.get("mandatory", False)
    if not isinstance(mandatory, bool):
        raise ValueError("mandatory 必须是布尔值")
    return ReleaseInfo(
        version=version.lstrip("vV"),
        installer_url=installer_url,
        sha256=sha256,
        size=size,
        notes=notes,
        mandatory=mandatory,
        manifest_url=manifest_url,
    )


def is_newer_version(candidate, current=__version__):
    return version_tuple(candidate) > version_tuple(current)


def update_cache_dir():
    root = os.environ.get("LOCALAPPDATA") or os.path.expanduser(
        os.path.join("~", "AppData", "Local"))
    return os.path.join(root, "AnhuToolbox", "updates")


def cleanup_update_cache():
    directory = update_cache_dir()
    if not os.path.isdir(directory):
        return
    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        try:
            if (os.path.isfile(path)
                    and time.time() - os.path.getmtime(path) > 10 * 60):
                os.remove(path)
        except OSError:
            # 正在运行的旧更新器或杀毒软件短暂占用时忽略。
            pass


def _read_manifest(url):
    chunks = []
    total = 0
    with httpx.stream(
        "GET", url, headers={"User-Agent": USER_AGENT},
        follow_redirects=True, timeout=httpx.Timeout(10.0, connect=5.0),
    ) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > MAX_MANIFEST_BYTES:
                raise UpdateError("更新清单过大")
            chunks.append(chunk)
    return b"".join(chunks)


class UpdateCheckWorker(QThread):
    available = Signal(object)
    up_to_date = Signal()
    failed = Signal(str)

    def __init__(self, current_version=__version__, parent=None):
        super().__init__(parent)
        self._current_version = current_version

    def run(self):
        try:
            import json
            raw = _read_manifest(UPDATE_MANIFEST_URL)
            release = parse_manifest(json.loads(raw.decode("utf-8")))
            if is_newer_version(release.version, self._current_version):
                self.available.emit(release)
            else:
                self.up_to_date.emit()
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.failed.emit(str(exc))

    def stop(self):
        self.requestInterruption()
        if self.isRunning():
            self.terminate()
            self.wait(1000)


def _hash_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class UpdateDownloadWorker(QThread):
    progress = Signal("qlonglong", "qlonglong")
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, release, directory=None, parent=None):
        super().__init__(parent)
        self._release = release
        self._directory = directory or update_cache_dir()
        self._cancel = threading.Event()
        self._client = None

    def cancel(self):
        self._cancel.set()
        client = self._client
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    def run(self):
        os.makedirs(self._directory, exist_ok=True)
        name = "AnhuToolbox_Setup_{}.exe".format(
            re.sub(r"[^0-9A-Za-z._-]", "_", self._release.version))
        target = os.path.join(self._directory, name)
        part = target + ".part"
        total = 0
        digest = hashlib.sha256()
        client = None
        try:
            client = httpx.Client(
                headers={"User-Agent": USER_AGENT},
                follow_redirects=True,
                timeout=httpx.Timeout(120.0, connect=10.0),
            )
            self._client = client
            with client.stream(
                    "GET", self._release.installer_url) as response:
                response.raise_for_status()
                with open(part, "wb") as output:
                    for chunk in response.iter_bytes(256 * 1024):
                        if self._cancel.is_set():
                            raise UpdateError("更新下载已取消")
                        total += len(chunk)
                        if total > self._release.size:
                            raise UpdateError("下载文件超过清单声明大小")
                        output.write(chunk)
                        digest.update(chunk)
                        self.progress.emit(total, self._release.size)
            if total != self._release.size:
                raise UpdateError("下载文件大小与清单不一致")
            if digest.hexdigest().lower() != self._release.sha256:
                raise UpdateError("安装包 SHA-256 校验失败")
            os.replace(part, target)
            self.completed.emit(target)
        except Exception as exc:
            try:
                if os.path.exists(part):
                    os.remove(part)
            except OSError:
                pass
            if not self._cancel.is_set():
                self.failed.emit(str(exc))
        finally:
            self._client = None
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass


def launch_updater(app_dir, app_path, installer_path, release):
    helper = os.path.join(app_dir, "AnhuUpdater.exe")
    if not os.path.isfile(helper):
        raise UpdateError("缺少更新器 AnhuUpdater.exe")
    if not os.path.isfile(installer_path):
        raise UpdateError("下载的安装包不存在")
    if _hash_file(installer_path).lower() != release.sha256:
        raise UpdateError("安装包 SHA-256 校验失败")
    directory = update_cache_dir()
    os.makedirs(directory, exist_ok=True)
    temp_helper = os.path.join(
        directory, "AnhuUpdater-{}.exe".format(os.getpid()))
    shutil.copy2(helper, temp_helper)
    command = [
        temp_helper,
        "--pid", str(os.getpid()),
        "--installer", installer_path,
        "--sha256", release.sha256,
        "--app", app_path,
        "--log", os.path.join(directory, "updater.log"),
    ]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.Popen(command, cwd=directory, creationflags=flags)
    return True
