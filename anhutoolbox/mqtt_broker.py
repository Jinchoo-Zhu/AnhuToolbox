# -*- coding: utf-8 -*-
"""Bundled Mosquitto process management for the MQTT server mode."""

import base64
import hashlib
import os
import shutil
import socket
import sys
import time as os_time
import zipfile
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from .process_guard import assign_child_process


class MQTTBrokerError(RuntimeError):
    pass


def mqtt_broker_dir(base_dir=None):
    roots = []
    if base_dir:
        roots.append(Path(base_dir))
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            roots.append(Path(meipass))
    roots.append(Path(__file__).resolve().parent.parent)
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        roots.append(Path(local_appdata) / "AnhuToolbox")

    candidates = []
    for root in roots:
        candidates.extend((
            root / "lib" / "mqtt" / "broker",
            root / "mqtt" / "broker",
        ))
    return next(
        (path for path in candidates if (path / "mosquitto.exe").is_file()),
        candidates[0],
    )


def mqtt_broker_available(base_dir=None):
    return (mqtt_broker_dir(base_dir) / "mosquitto.exe").is_file()


def mqtt_broker_archive(base_dir=None):
    roots = []
    if base_dir:
        roots.append(Path(base_dir))
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            roots.append(Path(meipass))
    roots.append(Path(__file__).resolve().parent.parent)
    for root in roots:
        for candidate in (
            root / "lib" / "mqtt" / "broker.zip",
            root / "mqtt" / "broker.zip",
        ):
            if candidate.is_file():
                return candidate
    return None


def install_mqtt_broker_runtime(base_dir, data_root):
    archive = mqtt_broker_archive(base_dir)
    if archive is None:
        raise MQTTBrokerError(
            "安装包中缺少 MQTT 服务端运行资源，请重新下载完整安装包。")
    target = Path(data_root) / "mqtt" / "broker"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / ".broker-installing-{}-{}".format(
        os.getpid(), os_time.time_ns())
    try:
        temporary.mkdir()
        with zipfile.ZipFile(archive) as package:
            for info in package.infolist():
                relative = Path(info.filename)
                if relative.is_absolute() or ".." in relative.parts:
                    raise MQTTBrokerError("MQTT 运行组件压缩包路径不安全")
                package.extract(info, temporary)
        required = (
            "mosquitto.exe",
            "mosquitto_passwd.exe",
            "mosquitto_common.dll",
            "mosquitto_password_file.dll",
            "NOTICE.md",
            "edl-v10",
            "epl-v20",
        )
        missing = [
            name for name in required
            if not (temporary / name).is_file()
        ]
        if missing:
            raise MQTTBrokerError(
                "MQTT 运行组件不完整：{}".format("、".join(missing)))
        if target.exists():
            shutil.rmtree(target)
        os.replace(temporary, target)
        return target
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
        raise


def _port_is_available(bind_address, port):
    family = socket.AF_INET6 if ":" in str(bind_address) else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            probe.setsockopt(
                socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        probe.bind((str(bind_address), int(port)))
    return True


def _password_hash(password):
    iterations = 20000
    salt = os.urandom(64)
    digest = hashlib.pbkdf2_hmac(
        "sha512",
        str(password).encode("utf-8"),
        salt,
        iterations,
        dklen=64,
    )
    return "$7${}${}${}".format(
        iterations,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def _write_password_file(users, target):
    try:
        lines = [
            "{}:{}".format(user["username"], _password_hash(
                user["password"]))
            for user in users
        ]
        target.write_text(
            "\n".join(lines) + "\n", encoding="utf-8")
    except OSError as exc:
        raise MQTTBrokerError(
            "无法写入 MQTT 密码文件：{}".format(exc)) from exc


def _normalize_users(config):
    raw_users = config.get("users")
    if not isinstance(raw_users, list):
        raw_users = []
    if not raw_users:
        username = str(config.get("username") or "").strip()
        if username:
            raw_users = [{
                "username": username,
                "password": str(config.get("password") or ""),
                "enabled": True,
                "topics": ["#"],
                "access": "readwrite",
            }]
    users = []
    seen = set()
    for item in raw_users:
        if not isinstance(item, dict):
            continue
        username = str(item.get("username") or "").strip()
        if not username or not bool(item.get("enabled", True)):
            continue
        if any(character in username for character in ("\r", "\n", "\0", ":")):
            raise MQTTBrokerError("MQTT 用户名不能包含换行符或冒号")
        if username in seen:
            raise MQTTBrokerError(
                "MQTT 用户名重复：{}".format(username))
        seen.add(username)
        password = str(item.get("password") or "")
        if not password:
            raise MQTTBrokerError(
                "用户 {} 未填写密码".format(username))
        topics = item.get("topics")
        if isinstance(topics, str):
            topics = topics.splitlines()
        if not isinstance(topics, (list, tuple)):
            topics = []
        topics = [
            str(topic).strip()
            for topic in topics
            if str(topic).strip()
        ]
        if not topics:
            raise MQTTBrokerError(
                "用户 {} 未配置 Topic 权限".format(username))
        if any(
            any(character in topic for character in ("\r", "\n", "\0"))
            for topic in topics
        ):
            raise MQTTBrokerError(
                "用户 {} 的 Topic 不能包含换行符".format(username))
        access = str(item.get("access") or "readwrite").lower()
        if access not in ("read", "readwrite"):
            raise MQTTBrokerError(
                "用户 {} 的访问方式无效".format(username))
        users.append({
            "username": username,
            "password": password,
            "topics": topics,
            "access": access,
        })
    return users


def _write_acl_file(path, users, allow_anonymous):
    lines = []
    if allow_anonymous:
        lines.append("topic readwrite #")
    for user in users:
        lines.append("user {}".format(user["username"]))
        lines.extend(
            "topic {} {}".format(user["access"], topic)
            for topic in user["topics"]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _tls_paths(config):
    tls = config.get("tls")
    if not isinstance(tls, dict) or not bool(tls.get("enabled", False)):
        return None
    ca_file = str(tls.get("ca_file") or "").strip()
    cert_file = str(tls.get("cert_file") or "").strip()
    key_file = str(tls.get("key_file") or "").strip()
    require_client_cert = bool(tls.get("require_client_cert", False))
    if not cert_file or not key_file:
        raise MQTTBrokerError(
            "启用服务端 TLS 时必须选择证书和私钥")
    if require_client_cert and not ca_file:
        raise MQTTBrokerError(
            "要求客户端证书时必须选择 CA 证书")
    paths = {
        "ca_file": Path(ca_file) if ca_file else None,
        "cert_file": Path(cert_file),
        "key_file": Path(key_file),
        "require_client_cert": require_client_cert,
    }
    for label, path in (
        ("CA 证书", paths["ca_file"]),
        ("证书", paths["cert_file"]),
        ("私钥", paths["key_file"]),
    ):
        if path is not None and not path.is_file():
            raise MQTTBrokerError(
                "{}文件不存在：{}".format(label, path))
    return paths


def _copy_tls_runtime_files(tls_paths, runtime_dir):
    targets = {
        "ca_file": runtime_dir / "tls-ca.pem",
        "cert_file": runtime_dir / "tls-cert.pem",
        "key_file": runtime_dir / "tls-key.pem",
    }
    if tls_paths is None:
        for target in targets.values():
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass
        return None

    prepared = {
        "require_client_cert": tls_paths["require_client_cert"],
    }
    for key, target in targets.items():
        source = tls_paths[key]
        if source is None:
            prepared[key] = ""
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass
            continue
        try:
            shutil.copyfile(source, target)
        except OSError as exc:
            raise MQTTBrokerError(
                "无法准备 MQTT TLS 文件：{}".format(exc)) from exc
        prepared[key] = target.name
    return prepared


def prepare_broker_config(base_dir, runtime_dir, config):
    executable_dir = mqtt_broker_dir(base_dir)
    executable = executable_dir / "mosquitto.exe"
    if not executable.is_file():
        raise MQTTBrokerError(
            "未安装 MQTT 服务端运行组件，请重新运行安装程序安装。")

    bind_address = str(
        config.get("bind_address") or "127.0.0.1").strip()
    if not bind_address:
        raise MQTTBrokerError("请填写监听地址")
    try:
        port = int(config.get("port", 1883))
        max_connections = int(config.get("max_connections", 100))
    except (TypeError, ValueError, OverflowError) as exc:
        raise MQTTBrokerError("MQTT 服务端端口或连接数无效") from exc
    if not 1 <= port <= 65535:
        raise MQTTBrokerError("MQTT 服务端端口必须在 1-65535 之间")
    if max_connections < 1:
        raise MQTTBrokerError("最大连接数必须大于 0")
    try:
        port_available = _port_is_available(bind_address, port)
    except OSError as exc:
        raise MQTTBrokerError(
            "监听地址无效或端口不可用：{}".format(exc)) from exc
    if not port_available:
        raise MQTTBrokerError(
            "端口 {}:{} 已被占用".format(bind_address, port))

    runtime_dir = Path(runtime_dir)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    password_path = runtime_dir / "passwd"
    acl_path = runtime_dir / "acl"
    persistence_dir = runtime_dir / "persistence"
    allow_anonymous = bool(config.get("allow_anonymous", True))
    users = _normalize_users(config)
    if not allow_anonymous and not users:
        raise MQTTBrokerError(
            "关闭匿名连接时至少需要一个启用的用户")
    if users:
        _write_password_file(users, password_path)
        _write_acl_file(acl_path, users, allow_anonymous)
    else:
        for stale_path in (password_path, acl_path):
            try:
                stale_path.unlink(missing_ok=True)
            except OSError:
                pass

    tls_paths = _copy_tls_runtime_files(
        _tls_paths(config), runtime_dir)
    persistence_enabled = bool(config.get("persistence", False))
    if persistence_enabled:
        persistence_dir.mkdir(parents=True, exist_ok=True)

    lines = [
        "listener {} {}".format(port, bind_address),
        "allow_anonymous {}".format(
            "true" if allow_anonymous else "false"),
        "max_connections {}".format(max_connections),
        "connection_messages true",
        "log_dest file mosquitto.log",
        "log_type all",
        "log_timestamp true",
        "log_timestamp_format %Y-%m-%d %H:%M:%S",
        "sys_interval 10",
    ]
    if tls_paths is not None:
        if tls_paths["ca_file"]:
            lines.append("cafile {}".format(tls_paths["ca_file"]))
        lines.extend((
            "certfile {}".format(tls_paths["cert_file"]),
            "keyfile {}".format(tls_paths["key_file"]),
            "require_certificate {}".format(
                "true" if tls_paths["require_client_cert"] else "false"),
        ))
    if persistence_enabled:
        lines.extend((
            "persistence true",
            "persistence_location persistence/",
            "autosave_interval 1",
        ))
    else:
        lines.append("persistence false")
    if users:
        lines.extend((
            "password_file passwd",
            "acl_file acl",
        ))

    config_path = runtime_dir / "mosquitto.conf"
    config_path.write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    return executable, config_path


class MQTTBrokerRuntime(QObject):
    started = Signal()
    stopped = Signal(str)
    failed = Signal(str)
    log_message = Signal(str)

    def __init__(self, base_dir=None, parent=None):
        super().__init__(parent)
        self._base_dir = base_dir
        self._process = None
        self._running = False
        self._stopping = False
        self._bind_address = "127.0.0.1"
        self._port = 1883
        self._log_path = None
        self._log_position = 0
        self._ready_timer = QTimer(self)
        self._ready_timer.setSingleShot(True)
        self._ready_timer.setInterval(350)
        self._ready_timer.timeout.connect(self._confirm_started)
        self._log_timer = QTimer(self)
        self._log_timer.setInterval(250)
        self._log_timer.timeout.connect(self._read_log_file)

    @property
    def is_running(self):
        process = self._process
        return bool(
            self._running
            and process is not None
            and process.state() != QProcess.ProcessState.NotRunning
        )

    @property
    def has_active_process(self):
        process = self._process
        return bool(
            process is not None
            and process.state() != QProcess.ProcessState.NotRunning
        )

    def start(self, config, runtime_dir):
        if self.is_running or (
            self._process is not None
            and self._process.state() != QProcess.ProcessState.NotRunning
        ):
            raise MQTTBrokerError("MQTT 服务端已在运行")
        executable, config_path = prepare_broker_config(
            self._base_dir, runtime_dir, config)
        self._bind_address = str(
            config.get("bind_address") or "127.0.0.1").strip()
        self._port = int(config.get("port", 1883))
        self._log_path = config_path.parent / "mosquitto.log"
        self._log_position = 0
        try:
            self._log_path.unlink(missing_ok=True)
        except OSError:
            pass
        self._stopping = False
        self._running = False

        process = QProcess(self)
        process.setWorkingDirectory(str(config_path.parent))
        process.setProcessChannelMode(
            QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(
            lambda: self._read_output(process))
        process.finished.connect(
            lambda code, _status: self._on_finished(process, code))
        process.errorOccurred.connect(
            lambda _error: self._on_process_error(process))
        self._process = process
        process.start(str(executable), ["-c", config_path.name])
        if not process.waitForStarted(3000):
            self._process = None
            process.deleteLater()
            raise MQTTBrokerError("MQTT 服务端进程启动失败")
        assign_child_process(process.processId())
        self._log_timer.start()
        self._ready_timer.start()

    def stop(self):
        process = self._process
        if process is None:
            return True
        self._ready_timer.stop()
        self._stopping = True
        if process.state() != QProcess.ProcessState.NotRunning:
            process.terminate()
            if not process.waitForFinished(1500):
                process.kill()
                process.waitForFinished(500)
        self._read_log_file()
        self._log_timer.stop()
        exited = (
            process.state() == QProcess.ProcessState.NotRunning)
        self._process = None
        self._running = False
        self._stopping = False
        process.deleteLater()
        released = exited and self._wait_port_released()
        if released:
            self.stopped.emit("MQTT 服务端已停止")
        else:
            self.failed.emit(
                "MQTT 服务端进程已结束，但监听端口仍未释放")
        return bool(released)

    def cleanup(self):
        return self.stop()

    def _wait_port_released(self, timeout=2.0):
        deadline = os_time.monotonic() + timeout
        while os_time.monotonic() < deadline:
            try:
                if _port_is_available(self._bind_address, self._port):
                    return True
            except OSError:
                pass
            os_time.sleep(0.05)
        return False

    def _confirm_started(self):
        process = self._process
        if (
            process is None
            or process.state() == QProcess.ProcessState.NotRunning
        ):
            return
        self._running = True
        self.started.emit()

    def _read_output(self, process):
        if process is not self._process:
            return
        text = bytes(process.readAllStandardOutput()).decode(
            "utf-8", errors="replace")
        for line in text.splitlines():
            line = line.strip()
            if line:
                self.log_message.emit(line)

    def _read_log_file(self):
        path = self._log_path
        if path is None or not path.is_file():
            return
        try:
            with path.open("rb") as stream:
                stream.seek(self._log_position)
                data = stream.read()
                self._log_position = stream.tell()
        except OSError:
            return
        for line in data.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if line:
                self.log_message.emit(line)

    def _on_finished(self, process, exit_code):
        if process is not self._process:
            process.deleteLater()
            return
        self._ready_timer.stop()
        self._read_output(process)
        self._read_log_file()
        self._log_timer.stop()
        self._process = None
        was_running = self._running
        self._running = False
        if self._stopping:
            self._stopping = False
            return
        message = "MQTT 服务端异常退出（代码 {}）".format(exit_code)
        process.deleteLater()
        if was_running:
            self.failed.emit(message)
        else:
            self.failed.emit("MQTT 服务端启动失败，请检查端口和日志")

    def _on_process_error(self, process):
        if process is not self._process:
            return
        if process.error() == QProcess.ProcessError.FailedToStart:
            self._ready_timer.stop()
            self._log_timer.stop()
            self._process = None
            self._running = False
            process.deleteLater()
            self.failed.emit("MQTT 服务端进程启动失败")
