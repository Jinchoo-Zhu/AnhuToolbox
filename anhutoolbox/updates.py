# -*- coding: utf-8 -*-
"""自动更新检查、下载和更新器启动。"""

import hashlib
import json
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
    GITHUB_OWNER, GITHUB_REPO, UPDATE_MANIFEST_URL, UPDATE_MANIFEST_URLS,
    UPDATE_SERVER_HOST, UPDATE_SERVER_PORT, __version__,
)

MAX_MANIFEST_BYTES = 64 * 1024
MAX_INSTALLER_BYTES = 2 * 1024 * 1024 * 1024
USER_AGENT = "AnhuToolbox/{}".format(__version__)
_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_TRUSTED_INSTALLER_TARGETS = (
    (
        UPDATE_SERVER_HOST,
        UPDATE_SERVER_PORT,
        "/anhutoolbox/releases/",
    ),
    (
        "github.com",
        443,
        "/{}/{}/releases/download/".format(
            GITHUB_OWNER, GITHUB_REPO).lower(),
    ),
)


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
    installer_urls: tuple = ()

    @property
    def download_urls(self):
        return tuple(dict.fromkeys(
            url for url in (self.installer_url, *self.installer_urls) if url))


def version_tuple(value):
    match = _VERSION_RE.fullmatch(str(value or "").strip())
    if not match:
        raise ValueError("无效版本号：{}".format(value))
    return tuple(int(part) for part in match.groups())


def _is_trusted_installer_url(url):
    try:
        parsed = urllib.parse.urlsplit(str(url or "").strip())
        port = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme.lower() != "https"
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.path.lower().endswith(".exe")
    ):
        return False
    path = urllib.parse.unquote(parsed.path)
    if ".." in path.split("/"):
        return False
    host = (parsed.hostname or "").lower()
    for expected_host, expected_port, prefix in _TRUSTED_INSTALLER_TARGETS:
        effective_port = port or 443
        if (
            host == expected_host
            and effective_port == expected_port
            and path.lower().startswith(prefix)
        ):
            return True
    return False


def parse_manifest(payload, manifest_url=UPDATE_MANIFEST_URL):
    if not isinstance(payload, dict):
        raise ValueError("更新清单必须是 JSON 对象")
    version = str(payload.get("version") or "").strip()
    version_tuple(version)
    legacy_url = ""
    installer_urls = []
    single_url = payload.get("installer_url")
    if single_url not in (None, ""):
        if not isinstance(single_url, str):
            raise ValueError("installer_url 必须是字符串")
        legacy_url = single_url.strip()
        if legacy_url and not _is_trusted_installer_url(legacy_url):
            raise ValueError("installer_url 不是受信任的发布源")
    multiple_urls = payload.get("installer_urls")
    if multiple_urls is not None:
        if not isinstance(multiple_urls, list) or len(multiple_urls) > 5:
            raise ValueError("installer_urls 必须是最多 5 项的数组")
        for url in multiple_urls:
            if not isinstance(url, str):
                raise ValueError("installer_urls 只能包含字符串")
            installer_urls.append(url.strip())
    installer_urls = list(dict.fromkeys(url for url in installer_urls if url))
    if not installer_urls and legacy_url:
        installer_urls = [legacy_url]
    if not installer_urls:
        raise ValueError("更新清单缺少安装包地址")
    if not all(_is_trusted_installer_url(url) for url in installer_urls):
        raise ValueError("安装包地址包含不受信任的发布源")
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
        installer_url=installer_urls[0],
        installer_urls=tuple(installer_urls),
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
    release_found = Signal(object)
    up_to_date = Signal()
    failed = Signal(str)

    def __init__(self, current_version=__version__, parent=None):
        super().__init__(parent)
        self._current_version = current_version

    def run(self):
        releases = []
        errors = []
        for manifest_url in UPDATE_MANIFEST_URLS:
            if self.isInterruptionRequested():
                return
            try:
                raw = _read_manifest(manifest_url)
                payload = json.loads(raw.decode("utf-8"))
                releases.append(parse_manifest(payload, manifest_url))
            except Exception as exc:
                errors.append(str(exc))
        if self.isInterruptionRequested():
            return
        if not releases:
            self.failed.emit(
                "所有更新源均不可用：{}".format(
                    "；".join(errors[-2:]) or "未知错误"))
            return
        release = max(releases, key=lambda item: version_tuple(item.version))
        self.release_found.emit(release)
        if is_newer_version(release.version, self._current_version):
            self.available.emit(release)
        else:
            self.up_to_date.emit()

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
        if os.path.isfile(target):
            try:
                if (
                    os.path.getsize(target) == self._release.size
                    and _hash_file(target).lower() == self._release.sha256
                ):
                    self.progress.emit(
                        self._release.size, self._release.size)
                    self.completed.emit(target)
                    return
                os.remove(target)
            except OSError:
                pass
        client = None
        try:
            client = httpx.Client(
                headers={"User-Agent": USER_AGENT},
                follow_redirects=True,
                timeout=httpx.Timeout(120.0, connect=10.0),
            )
            self._client = client
            errors = []
            for index, url in enumerate(self._release.download_urls, 1):
                if self._cancel.is_set():
                    break
                for attempt in range(2):
                    if self._cancel.is_set():
                        break
                    try:
                        self._download_from(client, url, part)
                    except Exception as exc:
                        try:
                            if os.path.exists(part):
                                os.remove(part)
                        except OSError:
                            pass
                        if self._cancel.is_set():
                            break
                        errors.append(
                            "源{}第{}次：{}".format(
                                index, attempt + 1, exc))
                        if attempt == 0:
                            self.msleep(500)
                            continue
                        break
                    os.replace(part, target)
                    self.completed.emit(target)
                    return
                if self._cancel.is_set():
                    break
            if not self._cancel.is_set():
                self.failed.emit(
                    "所有下载源均失败：{}".format(
                        "；".join(errors) or "没有可用下载地址"))
        except Exception as exc:
            if not self._cancel.is_set():
                self.failed.emit(str(exc))
        finally:
            self._client = None
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass

    def _download_from(self, client, url, part):
        total = 0
        digest = hashlib.sha256()
        with client.stream("GET", url) as response:
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
            raise UpdateError(
                "下载文件大小与清单不一致（收到 {}，应为 {}）".format(
                    total, self._release.size))
        if digest.hexdigest().lower() != self._release.sha256:
            raise UpdateError("安装包 SHA-256 校验失败")


def launch_updater(
        app_dir, app_path, installer_path, release, merge_tasks=""):
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
    if merge_tasks:
        command.extend(["--merge-tasks", merge_tasks])
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.Popen(command, cwd=directory, creationflags=flags)
    return True
