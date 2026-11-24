# -*- coding: utf-8 -*-
"""Real Mosquitto integration tests for MQTT security and persistence."""

import os
import socket
import ssl
import tempfile
import threading
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
import paho.mqtt.client as mqtt

from anhutoolbox.mqtt_broker import (
    MQTTBrokerRuntime, mqtt_broker_available,
)
from anhutoolbox.protocol_workers import MQTTWorker


APP = QApplication.instance() or QApplication([])
ROOT = Path(__file__).resolve().parents[1]
TLS_DIR = ROOT / "tests" / "fixtures" / "mqtt_tls"


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _reason_code(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def _tls_handshake(port, ca_file, cert_file=None, key_file=None):
    context = ssl.create_default_context(cafile=str(ca_file))
    if cert_file:
        context.load_cert_chain(
            certfile=str(cert_file), keyfile=str(key_file))
    raw_socket = socket.create_connection(
        ("127.0.0.1", port), timeout=3)
    tls_socket = None
    try:
        tls_socket = context.wrap_socket(
            raw_socket,
            server_hostname="127.0.0.1",
            do_handshake_on_connect=False,
        )
        tls_socket.do_handshake()
    finally:
        if tls_socket is not None:
            tls_socket.close()
        else:
            raw_socket.close()


class MQTTProbe:
    def __init__(
        self,
        client_id,
        username=None,
        password=None,
        clean_session=True,
    ):
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            clean_session=clean_session,
        )
        if username is not None:
            self.client.username_pw_set(username, password or "")
        self.connected = threading.Event()
        self.subscribed = threading.Event()
        self.messages = []
        self.connect_reasons = []
        self.subscribe_reasons = []
        self.client.on_connect = self._on_connect
        self.client.on_subscribe = self._on_subscribe
        self.client.on_message = self._on_message
        self._loop_started = False

    def _on_connect(
            self, _client, _userdata, _flags, reason_code, _properties):
        self.connect_reasons.append(_reason_code(reason_code))
        if _reason_code(reason_code) == 0:
            self.connected.set()

    def _on_subscribe(
            self, _client, _userdata, _mid, reason_codes, _properties):
        self.subscribe_reasons.append(
            [_reason_code(code) for code in reason_codes])
        self.subscribed.set()

    def _on_message(self, _client, _userdata, message):
        self.messages.append({
            "topic": message.topic,
            "payload": bytes(message.payload),
            "retain": bool(message.retain),
        })

    def connect(
            self, port, host="127.0.0.1", tls_config=None,
            wait_timeout=4):
        if tls_config is not None:
            self.client.tls_set(
                ca_certs=tls_config.get("ca_file"),
                certfile=tls_config.get("cert_file"),
                keyfile=tls_config.get("key_file"),
                cert_reqs=ssl.CERT_REQUIRED,
                tls_version=ssl.PROTOCOL_TLS_CLIENT,
            )
        self.client.connect(host, port, keepalive=10)
        self.client.loop_start()
        self._loop_started = True
        return self.connected.wait(wait_timeout)

    def subscribe(self, topic, qos=1):
        result, _mid = self.client.subscribe(topic, qos=qos)
        if result != mqtt.MQTT_ERR_SUCCESS:
            return None
        if not self.subscribed.wait(4):
            return None
        return self.subscribe_reasons[-1]

    def wait_message(self, topic, timeout=4):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for message in list(self.messages):
                if message["topic"] == topic:
                    return message
            time.sleep(0.02)
        return None

    def close(self):
        try:
            self.client.disconnect()
        except Exception:
            pass
        if self._loop_started:
            self.client.loop_stop()
            self._loop_started = False
        socket_object = getattr(self.client, "_sock", None)
        if socket_object is not None:
            try:
                socket_object.close()
            except OSError:
                pass


class MQTTAdvancedIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not mqtt_broker_available(str(ROOT)):
            raise unittest.SkipTest("bundled Mosquitto runtime is unavailable")

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.runtime_dir = Path(self._temp.name) / "MQTT Runtime 中文"
        self.runtime = MQTTBrokerRuntime(str(ROOT))
        self.runtime_errors = []
        self.runtime.failed.connect(self.runtime_errors.append)
        self.probes = []

    def tearDown(self):
        for probe in self.probes:
            probe.close()
        self.runtime.cleanup()
        self.runtime.deleteLater()
        APP.processEvents()
        self._temp.cleanup()

    def _probe(self, *args, **kwargs):
        probe = MQTTProbe(*args, **kwargs)
        self.probes.append(probe)
        return probe

    def _start(self, config):
        self.runtime.start(config, self.runtime_dir)
        deadline = time.monotonic() + 6
        port = int(config["port"])
        while time.monotonic() < deadline:
            APP.processEvents()
            try:
                with socket.create_connection(
                        ("127.0.0.1", port), timeout=0.2):
                    return
            except OSError:
                time.sleep(0.02)
        self.fail(
            "Mosquitto did not start: {}".format(self.runtime_errors))

    def _stop(self):
        self.assertTrue(self.runtime.stop())
        APP.processEvents()
        self.assertFalse(self.runtime.is_running)

    def _users_config(self, port, allow_anonymous=False, persistence=False):
        return {
            "bind_address": "127.0.0.1",
            "port": port,
            "allow_anonymous": allow_anonymous,
            "persistence": persistence,
            "max_connections": 20,
            "users": [
                {
                    "username": "alice",
                    "password": "alice-pass",
                    "enabled": True,
                    "topics": ["alice/#"],
                    "access": "readwrite",
                },
                {
                    "username": "bob",
                    "password": "bob-pass",
                    "enabled": True,
                    "topics": ["bob/#"],
                    "access": "readwrite",
                },
                {
                    "username": "disabled",
                    "password": "disabled-pass",
                    "enabled": False,
                    "topics": ["#"],
                    "access": "readwrite",
                },
            ],
        }

    def test_multiuser_authentication_and_topic_acl(self):
        port = _free_port()
        self._start(self._users_config(port))

        alice = self._probe(
            "alice-client", username="alice", password="alice-pass")
        bob = self._probe(
            "bob-client", username="bob", password="bob-pass")
        wrong = self._probe(
            "wrong-password", username="alice", password="wrong")
        disabled = self._probe(
            "disabled-user", username="disabled", password="disabled-pass")
        anonymous = self._probe("anonymous")

        self.assertTrue(alice.connect(port))
        self.assertTrue(bob.connect(port))
        self.assertFalse(wrong.connect(port, wait_timeout=1))
        self.assertFalse(disabled.connect(port, wait_timeout=1))
        self.assertFalse(anonymous.connect(port, wait_timeout=1))

        # Mosquitto 2.1.4 grants wildcard subscriptions but enforces the ACL
        # when matching messages are delivered, so verify actual isolation.
        self.assertEqual(alice.subscribe("alice/#"), [1])
        self.assertEqual(alice.subscribe("bob/#"), [1])
        self.assertEqual(bob.subscribe("bob/#"), [1])
        self.assertEqual(bob.subscribe("alice/#"), [1])

        info = alice.client.publish(
            "alice/device-1", b"online", qos=1, retain=False)
        self.assertEqual(info.rc, mqtt.MQTT_ERR_SUCCESS)
        info.wait_for_publish(3)
        message = alice.wait_message("alice/device-1")
        self.assertIsNotNone(message)
        self.assertEqual(message["payload"], b"online")
        time.sleep(0.4)
        self.assertIsNone(bob.wait_message("alice/device-1", timeout=0.2))

        secret = bob.client.publish(
            "bob/confidential", b"private", qos=1, retain=False)
        self.assertEqual(secret.rc, mqtt.MQTT_ERR_SUCCESS)
        secret.wait_for_publish(3)
        message = bob.wait_message("bob/confidential")
        self.assertIsNotNone(message)
        self.assertEqual(message["payload"], b"private")
        time.sleep(0.4)
        self.assertIsNone(alice.wait_message(
            "bob/confidential", timeout=0.2))

    def test_anonymous_and_named_users_can_coexist(self):
        port = _free_port()
        self._start(self._users_config(port, allow_anonymous=True))

        anonymous = self._probe("anonymous-allowed")
        named = self._probe(
            "alice-allowed", username="alice", password="alice-pass")
        wrong = self._probe(
            "wrong-not-anonymous", username="alice", password="wrong")
        unknown = self._probe(
            "unknown-not-anonymous",
            username="unknown",
            password="unknown-pass",
        )
        self.assertTrue(anonymous.connect(port))
        self.assertTrue(named.connect(port))
        self.assertFalse(wrong.connect(port, wait_timeout=1))
        self.assertFalse(unknown.connect(port, wait_timeout=1))

    def test_unicode_username_password_and_topic(self):
        port = _free_port()
        self._start({
            "bind_address": "127.0.0.1",
            "port": port,
            "allow_anonymous": False,
            "persistence": False,
            "max_connections": 10,
            "users": [{
                "username": "用户甲",
                "password": "密码123",
                "enabled": True,
                "topics": ["设备/#"],
                "access": "readwrite",
            }],
        })
        probe = self._probe(
            "unicode-client",
            username="用户甲",
            password="密码123",
        )
        self.assertTrue(probe.connect(port))
        self.assertEqual(probe.subscribe("设备/#"), [1])
        published = probe.client.publish(
            "设备/温度", "正常".encode("utf-8"), qos=1)
        published.wait_for_publish(3)
        message = probe.wait_message("设备/温度")
        self.assertIsNotNone(message)
        self.assertEqual(message["payload"], "正常".encode("utf-8"))

    def test_tls_server_and_mutual_tls_with_real_worker(self):
        port = _free_port()
        config = {
            "bind_address": "127.0.0.1",
            "port": port,
            "allow_anonymous": True,
            "persistence": False,
            "max_connections": 20,
            "tls": {
                "enabled": True,
                "ca_file": str(TLS_DIR / "ca.crt"),
                "cert_file": str(TLS_DIR / "server.crt"),
                "key_file": str(TLS_DIR / "server.key"),
                "require_client_cert": False,
            },
        }
        self._start(config)

        trusted = self._probe("trusted")
        self.assertTrue(trusted.connect(port, tls_config={
            "ca_file": str(TLS_DIR / "ca.crt"),
        }))

        with self.assertRaises(ssl.SSLCertVerificationError):
            _tls_handshake(port, TLS_DIR / "untrusted-ca.crt")

        self._stop()
        config["tls"]["require_client_cert"] = True
        self._start(config)

        with self.assertRaises((ssl.SSLError, ConnectionError, OSError)):
            _tls_handshake(port, TLS_DIR / "ca.crt")

        with_certificate = self._probe("with-client-cert")
        self.assertTrue(with_certificate.connect(port, tls_config={
            "ca_file": str(TLS_DIR / "ca.crt"),
            "cert_file": str(TLS_DIR / "client.crt"),
            "key_file": str(TLS_DIR / "client.key"),
        }))

        worker = MQTTWorker()
        worker_connected = []
        worker_errors = []
        worker.connected.connect(lambda: worker_connected.append(True))
        worker.error_occurred.connect(worker_errors.append)
        try:
            worker.configure({
                "host": "127.0.0.1",
                "port": port,
                "client_id": "anhutoolbox-worker-tls",
                "keepalive": 10,
                "auto_reconnect": False,
                "tls": True,
                "tls_config": {
                    "enabled": True,
                    "ca_file": str(TLS_DIR / "ca.crt"),
                    "cert_file": str(TLS_DIR / "client.crt"),
                    "key_file": str(TLS_DIR / "client.key"),
                    "insecure": False,
                },
            })
            worker.start()
            deadline = time.monotonic() + 5
            while not worker_connected and time.monotonic() < deadline:
                APP.processEvents()
                time.sleep(0.02)
            self.assertTrue(worker_connected, worker_errors)
        finally:
            worker.stop()
            worker.wait(1000)
            worker.deleteLater()
            APP.processEvents()

    def test_retained_and_offline_qos1_survive_broker_restart(self):
        port = _free_port()
        config = {
            "bind_address": "127.0.0.1",
            "port": port,
            "allow_anonymous": True,
            "persistence": True,
            "max_connections": 20,
        }
        self._start(config)

        publisher = self._probe("persistence-publisher")
        self.assertTrue(publisher.connect(port))
        retained = publisher.client.publish(
            "persist/retained", b"retained-value", qos=1, retain=True)
        retained.wait_for_publish(3)

        offline = self._probe(
            "persistent-subscriber", clean_session=False)
        self.assertTrue(offline.connect(port))
        self.assertEqual(offline.subscribe("persist/offline", qos=1), [1])
        offline.close()

        queued = publisher.client.publish(
            "persist/offline", b"queued-value", qos=1, retain=False)
        queued.wait_for_publish(3)
        publisher.close()
        time.sleep(1.2)
        APP.processEvents()
        self._stop()
        self.assertTrue(any(
            path.is_file()
            for path in (self.runtime_dir / "persistence").iterdir()
        ))

        config["persistence"] = True
        self._start(config)

        retained_reader = self._probe("retained-reader")
        self.assertTrue(retained_reader.connect(port))
        self.assertEqual(retained_reader.subscribe("persist/retained"), [1])
        message = retained_reader.wait_message("persist/retained")
        self.assertIsNotNone(message)
        self.assertEqual(message["payload"], b"retained-value")
        self.assertTrue(message["retain"])

        resumed = self._probe(
            "persistent-subscriber", clean_session=False)
        self.assertTrue(resumed.connect(port))
        queued_message = resumed.wait_message("persist/offline")
        self.assertIsNotNone(queued_message)
        self.assertEqual(queued_message["payload"], b"queued-value")


if __name__ == "__main__":
    unittest.main()
