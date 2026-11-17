# -*- coding: utf-8 -*-
"""MQTT、HTTP、WebSocket 协议客户端线程。"""

import queue
import threading
import time

import httpx
import paho.mqtt.client as mqtt
import websocket
from PySide6.QtCore import QThread, Signal

# httpx 的证书模块使用延迟导入。必须在 GUI 主线程先初始化，否则在
# PySide6 存在时由 QThread 首次导入可能触发 shiboken 的导入钩子崩溃。
_DEFAULT_VERIFY_CONTEXT = httpx.create_ssl_context()
with httpx.Client(verify=_DEFAULT_VERIFY_CONTEXT) as _warmup_client:
    pass


class MQTTWorker(QThread):
    connected = Signal()
    disconnected = Signal(str)
    message_received = Signal(dict)
    error_occurred = Signal(str)
    log_message = Signal(str)

    def __init__(self):
        super().__init__()
        self._config = {}
        self._subscriptions = []
        self._client = None
        self._running = False
        self._stopping = False
        self._lock = threading.Lock()

    def configure(self, config):
        self._config = dict(config or {})

    def set_subscriptions(self, subscriptions):
        with self._lock:
            self._subscriptions = [
                {
                    "topic": str(item.get("topic") or "").strip(),
                    "qos": max(0, min(2, int(item.get("qos", 0)))),
                }
                for item in (subscriptions or [])
                if isinstance(item, dict) and str(item.get("topic") or "").strip()
            ]

    def _restore_subscriptions(self):
        client = self._client
        if client is None:
            return
        with self._lock:
            subscriptions = list(self._subscriptions)
        for item in subscriptions:
            try:
                client.subscribe(item["topic"], qos=item["qos"])
            except Exception as exc:
                self.error_occurred.emit(
                    "恢复订阅 {} 失败: {}".format(item["topic"], exc))

    def sync_subscriptions(self, subscriptions):
        with self._lock:
            previous = [item["topic"] for item in self._subscriptions]
        self.set_subscriptions(subscriptions)
        client = self._client
        if client is None:
            return
        wanted = {
            item["topic"] for item in (subscriptions or [])
            if isinstance(item, dict) and item.get("topic")
        }
        for topic in previous:
            if topic not in wanted:
                try:
                    client.unsubscribe(topic)
                except Exception:
                    pass
        self._restore_subscriptions()

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        try:
            success = int(reason_code) == 0
        except (TypeError, ValueError):
            success = str(reason_code).lower() in ("success", "0")
        if success:
            self._restore_subscriptions()
            self.connected.emit()
            self.log_message.emit("MQTT 已连接")
        else:
            self.error_occurred.emit("MQTT 连接被拒绝: {}".format(reason_code))

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        if self._stopping:
            return
        text = "MQTT 连接已断开"
        if reason_code not in (None, 0, "Success"):
            text += ": {}".format(reason_code)
        self.disconnected.emit(text)
        self.log_message.emit(text)
        if not self._config.get("auto_reconnect", True):
            self._running = False

    def _on_connect_fail(self, client, userdata):
        if self._stopping:
            return
        self.error_occurred.emit("MQTT 连接失败")
        self.disconnected.emit("MQTT 连接失败，正在重试")
        if not self._config.get("auto_reconnect", True):
            self._running = False

    def _on_message(self, client, userdata, message):
        payload = bytes(message.payload)
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            text = None
        self.message_received.emit({
            "timestamp": time.time(),
            "topic": message.topic,
            "payload": payload,
            "text": text,
            "qos": int(message.qos),
            "retain": bool(message.retain),
            "dup": bool(message.dup),
        })

    def run(self):
        self._running = True
        config = self._config
        try:
            protocol = (
                mqtt.MQTTv5
                if str(config.get("protocol", "MQTT 3.1.1")) == "MQTT 5.0"
                else mqtt.MQTTv311
            )
            client_id = str(config.get("client_id") or "").strip()
            if not client_id:
                client_id = "AnhuToolbox-{:x}".format(int(time.time() * 1000))
            client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=client_id,
                protocol=protocol,
                clean_session=(
                    bool(config.get("clean_session", True))
                    if protocol == mqtt.MQTTv311 else None),
                reconnect_on_failure=bool(
                    config.get("auto_reconnect", True)),
            )
            username = str(config.get("username") or "")
            if username:
                client.username_pw_set(username, str(config.get("password") or ""))

            if config.get("tls"):
                client.tls_set()
                client.tls_insecure_set(bool(config.get("tls_insecure", False)))

            client.on_connect = self._on_connect
            client.on_disconnect = self._on_disconnect
            client.on_connect_fail = self._on_connect_fail
            client.on_message = self._on_message
            client.reconnect_delay_set(
                min_delay=int(config.get("reconnect_min", 1)),
                max_delay=int(config.get("reconnect_max", 30)),
            )
            self._client = client
            client.connect_async(
                str(config.get("host") or "127.0.0.1"),
                int(config.get("port", 1883)),
                keepalive=int(config.get("keepalive", 60)),
            )
            client.loop_start()
            self.log_message.emit("正在连接 MQTT Broker...")
            while self._running:
                self.msleep(100)
        except Exception as exc:
            self.error_occurred.emit("MQTT 连接失败: {}".format(exc))
        finally:
            client = self._client
            if client is not None:
                try:
                    client.disconnect()
                except Exception:
                    pass
                try:
                    client.loop_stop()
                except Exception:
                    pass
            self._client = None
            self._running = False

    def subscribe(self, topic, qos=0):
        client = self._client
        if client is None:
            return False
        try:
            result, _ = client.subscribe(topic, qos=int(qos))
            return result == mqtt.MQTT_ERR_SUCCESS
        except Exception as exc:
            self.error_occurred.emit("MQTT 订阅失败: {}".format(exc))
            return False

    def publish(self, topic, payload, qos=0, retain=False):
        client = self._client
        if client is None:
            return False
        try:
            info = client.publish(
                topic, payload=payload, qos=int(qos), retain=bool(retain))
            return info.rc == mqtt.MQTT_ERR_SUCCESS
        except Exception as exc:
            self.error_occurred.emit("MQTT 发布失败: {}".format(exc))
            return False

    def stop(self):
        self._stopping = True
        self._running = False
        client = self._client
        if client is not None:
            try:
                client.disconnect()
            except Exception:
                pass
            try:
                client.loop_stop()
            except Exception:
                pass
        self.wait(2500)
        self._stopping = False


class WebSocketWorker(QThread):
    connected = Signal()
    disconnected = Signal(str)
    message_received = Signal(dict)
    error_occurred = Signal(str)
    log_message = Signal(str)

    def __init__(self):
        super().__init__()
        self._config = {}
        self._app = None
        self._running = False
        self._stopping = False
        self._close_notified = False

    def configure(self, config):
        self._config = dict(config or {})

    def _on_open(self, ws):
        self.connected.emit()
        self.log_message.emit("WebSocket 已连接")

    def _on_message(self, ws, message):
        binary = isinstance(message, bytes)
        payload = bytes(message) if binary else str(message).encode("utf-8")
        self.message_received.emit({
            "timestamp": time.time(),
            "direction": "rx",
            "binary": binary,
            "payload": payload,
            "text": None if binary else str(message),
        })

    def _on_error(self, ws, error):
        if not self._stopping:
            self.error_occurred.emit("WebSocket 错误: {}".format(error))
            self.disconnected.emit("WebSocket 连接异常: {}".format(error))

    def _on_close(self, ws, code, reason):
        if not self._stopping:
            self._close_notified = True
            text = "WebSocket 已断开"
            if code:
                text += " ({}{})".format(
                    code, ": " + str(reason) if reason else "")
            self.disconnected.emit(text)

    def run(self):
        self._running = True
        cfg = self._config
        url = str(cfg.get("url") or "").strip()
        headers = cfg.get("headers") or {}
        subprotocols = cfg.get("subprotocols") or None
        reconnect = bool(cfg.get("auto_reconnect", True))
        try:
            self._close_notified = False
            while self._running:
                app = websocket.WebSocketApp(
                    url,
                    header=headers,
                    subprotocols=subprotocols,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self._app = app
                app.run_forever(
                    ping_interval=max(0, int(cfg.get("ping_interval", 30))),
                    ping_timeout=max(1, int(cfg.get("ping_timeout", 10))),
                    origin=str(cfg.get("origin") or "") or None,
                    sslopt={
                        "cert_reqs": 2 if cfg.get("verify_tls", True) else 0,
                    },
                )
                self._app = None
                if not self._running or not reconnect:
                    break
                self.log_message.emit("WebSocket 将在 2 秒后重连...")
                end = time.monotonic() + 2.0
                while self._running and time.monotonic() < end:
                    time.sleep(0.05)
        except Exception as exc:
            self._close_notified = True
            self.error_occurred.emit("WebSocket 连接失败: {}".format(exc))
        finally:
            was_running = self._running
            self._running = False
            if not self._stopping and was_running and not self._close_notified:
                self.disconnected.emit("WebSocket 连接已结束")

    def send(self, payload, binary=False):
        app = self._app
        if app is None or not app.sock or not app.sock.connected:
            return False
        try:
            if binary:
                app.send(payload, opcode=websocket.ABNF.OPCODE_BINARY)
            else:
                app.send(payload, opcode=websocket.ABNF.OPCODE_TEXT)
            return True
        except Exception as exc:
            self.error_occurred.emit("WebSocket 发送失败: {}".format(exc))
            return False

    def ping(self):
        app = self._app
        if app is None or not app.sock or not app.sock.connected:
            return False
        try:
            app.send("", opcode=websocket.ABNF.OPCODE_PING)
            return True
        except Exception as exc:
            self.error_occurred.emit("WebSocket Ping 失败: {}".format(exc))
            return False

    def stop(self):
        self._stopping = True
        self._running = False
        app = self._app
        if app is not None:
            try:
                app.close()
            except Exception:
                pass
        self.wait(2500)
        self._stopping = False


class HTTPRequestWorker:
    MAX_RESPONSE_BYTES = 64 * 1024 * 1024
    IDEMPOTENT_METHODS = {
        "GET", "HEAD", "OPTIONS", "TRACE", "PUT", "DELETE",
    }

    def __init__(self):
        self._request = {}
        self._client = None
        self._stopping = False
        self._events = queue.Queue()
        self._thread = None

    def configure(self, request):
        self._request = dict(request or {})

    def run(self):
        req = self._request
        started = time.perf_counter()
        try:
            version = str(
                req.get("http_version") or "http/1.1").lower()
            use_http2 = version in ("auto", "http/2")
            auto_version = version == "auto"
            method = str(req.get("method") or "GET").upper()

            def send_request(http2_enabled):
                client = httpx.Client(
                    timeout=float(req.get("timeout", 30)),
                    follow_redirects=bool(
                        req.get("follow_redirects", True)),
                    verify=(
                        _DEFAULT_VERIFY_CONTEXT
                        if req.get("verify_tls", True) else False),
                    http2=http2_enabled,
                )
                self._client = client
                try:
                    with client.stream(
                        method,
                        str(req.get("url") or ""),
                        params=req.get("params") or None,
                        headers=req.get("headers") or None,
                        content=req.get("content"),
                    ) as response:
                        chunks = []
                        total = 0
                        for chunk in response.iter_bytes():
                            total += len(chunk)
                            if total > self.MAX_RESPONSE_BYTES:
                                raise ValueError(
                                    "响应体超过 {} MiB 限制".format(
                                        self.MAX_RESPONSE_BYTES // (1024 * 1024)))
                            chunks.append(chunk)
                        request = response.request
                        return {
                            "status": response.status_code,
                            "reason": response.reason_phrase,
                            "url": str(response.url),
                            "headers": [
                                {"name": str(name), "value": str(value)}
                                for name, value
                                in response.headers.multi_items()
                            ],
                            "cookies": [
                                {
                                    "name": cookie.name,
                                    "value": cookie.value,
                                }
                                for cookie in response.cookies.jar
                            ],
                            "content": b"".join(chunks),
                            "history": [
                                {
                                    "status": item.status_code,
                                    "url": str(item.url),
                                }
                                for item in response.history
                            ],
                            "request": {
                                "method": request.method,
                                "url": str(request.url),
                                "headers": [
                                    {"name": str(name), "value": str(value)}
                                    for name, value
                                    in request.headers.multi_items()
                                ],
                                "content": bytes(request.content or b""),
                            },
                        }
                finally:
                    self._client = None
                    client.close()

            try:
                response = send_request(use_http2)
            except Exception:
                # httpx 会在 http2=True 时自动协商到 HTTP/1.1。
                # 只有幂等请求才允许对连接级异常做一次显式回退，避免
                # “服务器已处理 POST，但客户端读响应超时”后重复提交。
                if (
                    self._stopping
                    or not (auto_version and use_http2)
                    or method not in self.IDEMPOTENT_METHODS
                ):
                    raise
                response = send_request(False)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            response["elapsed_ms"] = elapsed_ms
            self._events.put(("ok", response))
        except Exception as exc:
            if not self._stopping:
                self._events.put(("error", str(exc)))

    def pop_event(self):
        try:
            return self._events.get_nowait()
        except queue.Empty:
            return None

    def start(self):
        self._thread = threading.Thread(
            target=self.run, name="HTTPRequestWorker", daemon=True)
        self._thread.start()

    def isRunning(self):
        return bool(self._thread and self._thread.is_alive())

    def wait(self, timeout_ms=2500):
        if self._thread is None:
            return True
        self._thread.join(max(0, timeout_ms) / 1000.0)
        return not self._thread.is_alive()

    def stop(self):
        self._stopping = True
        client = self._client
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        self.wait(2500)
