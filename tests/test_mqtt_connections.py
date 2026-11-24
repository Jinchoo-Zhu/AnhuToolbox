# -*- coding: utf-8 -*-
"""Tests for Mosquitto connection log parsing."""

import unittest

from anhutoolbox.mqtt_connections import MQTTConnectionRegistry


class MQTTConnectionRegistryTests(unittest.TestCase):
    def test_connect_and_disconnect_session_fields(self):
        registry = MQTTConnectionRegistry()
        self.assertTrue(registry.ingest_line(
            "2026-11-24 09:51:38: New client connected from "
            "127.0.0.1:30017 as device-001 "
            "(p4, c1, k60, u'admin')."))
        connection = registry.records()[0]
        self.assertEqual(connection.client_id, "device-001")
        self.assertEqual(connection.username, "admin")
        self.assertEqual(connection.remote, "127.0.0.1:30017")
        self.assertEqual(connection.protocol, "MQTT 3.1.1")
        self.assertEqual(connection.keepalive, 60)
        self.assertTrue(connection.clean_session)
        self.assertEqual(registry.online_count(), 1)

        self.assertTrue(registry.ingest_line(
            "2026-11-24 09:52:38: Client device-001 "
            "[127.0.0.1:30017] disconnected."))
        self.assertEqual(registry.online_count(), 0)
        self.assertEqual(registry.records(), [])

    def test_anonymous_connection_and_clear_disconnected(self):
        registry = MQTTConnectionRegistry()
        registry.ingest_line(
            "New client connected from 192.0.2.2:1883 as temp-client "
            "(p5, c0, k30).")
        connection = registry.records()[0]
        self.assertEqual(connection.username, "")
        self.assertEqual(connection.protocol, "MQTT 5.0")
        self.assertFalse(connection.clean_session)
        registry.mark_all_offline()
        self.assertEqual(registry.records(), [])

    def test_reconnect_replaces_old_session(self):
        registry = MQTTConnectionRegistry()
        registry.ingest_line(
            "New client connected from 127.0.0.1:1000 as device "
            "(p4, c1, k60).")
        first = registry.records()[0]
        registry.ingest_line(
            "New client connected from 127.0.0.1:1001 as device "
            "(p4, c1, k60).")
        current = registry.records()[0]
        self.assertIsNot(first, current)
        self.assertEqual(current.remote, "127.0.0.1:1001")
        self.assertEqual(len(registry.records()), 1)


if __name__ == "__main__":
    unittest.main()
