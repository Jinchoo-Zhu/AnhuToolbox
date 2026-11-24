# -*- coding: utf-8 -*-
"""Bundled Mosquitto process management for the MQTT server mode."""

import os
import socket
import subprocess
import sys
import time as os_time
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


def _port_is_available(bind_address, port):
    family = socket.AF_INET6 if ":" in str(bind_address) else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            probe.setsockopt(
                socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        probe.bind((str(bind_address), int(port)))
    return True


def _write_password_file(executable_dir, username, password, target):
    tool = executable_dir / "mosquitto_passwd.exe"
    if not tool.is_file():
        raise MQTTBrokerError("缺少 mosquitto_passwd.exe")
    try:
        target.unlink(missing_ok=True)
    except OSError as exc:
        raise MQTTBrokerError(
            "无法清理旧的 MQTT 密码文件：{}".format(exc)) from exc
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    result = subprocess.run(
        [str(tool), "-b", "-c", str(target), username, password],
        cwd=str(executable_dir),
        capture_output=True,
        timeout=10,
        creationflags=flags,
    )
    if result.returncode != 0 or not target.is_file():
        detail = bytes(result.stderr or b"").decode(
            "utf-8", errors="replace").strip()
        raise MQTTBrokerError(
            "生成 MQTT 密码文件失败：{}".format(
                detail or "mosquitto_passwd 返回错误"))


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
    log_path = runtime_dir / "mosquitto.log"
    allow_anonymous = bool(config.get("allow_anonymous", True))
    username = str(config.get("username") or "").strip()
    password = str(config.get("password") or "")
    if not allow_anonymous:
        if not username:
            raise MQTTBrokerError("关闭匿名连接时必须填写用户名")
        if not password:
            raise MQTTBrokerError("关闭匿名连接时必须填写密码")
        _write_password_file(
            executable_dir, username, password, password_path)
    else:
        try:
            password_path.unlink(missing_ok=True)
        except OSError:
            pass

    lines = [
        "listener {} {}".format(port, bind_address),
        "allow_anonymous {}".format(
            "true" if allow_anonymous else "false"),
        "max_connections {}".format(max_connections),
        "persistence false",
        "connection_messages true",
        "log_dest file {}".format(log_path.as_posix()),
        "log_type all",
        "log_timestamp true",
        "log_timestamp_format %Y-%m-%d %H:%M:%S",
        "sys_interval 10",
    ]
    if not allow_anonymous:
        lines.append(
            "password_file {}".format(password_path.as_posix()))

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
        process.setWorkingDirectory(str(executable.parent))
        process.setProcessChannelMode(
            QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(
            lambda: self._read_output(process))
        process.finished.connect(
            lambda code, _status: self._on_finished(process, code))
        process.errorOccurred.connect(
            lambda _error: self._on_process_error(process))
        self._process = process
        process.start(str(executable), ["-c", str(config_path)])
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
