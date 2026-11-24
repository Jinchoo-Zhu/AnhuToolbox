# -*- coding: utf-8 -*-
"""Parse Mosquitto connection logs into a small connection registry."""

import re
from dataclasses import dataclass
from datetime import datetime


_STAMP_RE = re.compile(
    r"^(?P<stamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}):\s*")
_CONNECT_RE = re.compile(
    r"New client connected from (?P<remote>.+?) as (?P<client>.+?) "
    r"\((?P<protocol>p\d+), c(?P<clean>[01]), k(?P<keepalive>\d+)"
    r"(?:, u'(?P<username>.*)')?\)\.?$",
)
_DISCONNECT_RE = re.compile(
    r"Client (?P<client>.+?) \[(?P<remote>[^\]]+)\] disconnected\.?$")


@dataclass
class MQTTConnection:
    client_id: str
    username: str
    remote: str
    protocol: str
    keepalive: int
    clean_session: bool
    connected_at: datetime

    def online_seconds(self, now=None):
        return max(0, int(
            ((now or datetime.now()) - self.connected_at).total_seconds()))


def _log_time(line):
    match = _STAMP_RE.match(str(line or ""))
    if not match:
        return datetime.now()
    try:
        return datetime.strptime(
            match.group("stamp"), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return datetime.now()


def protocol_name(code):
    return {
        "p3": "MQTT 3.1",
        "p4": "MQTT 3.1.1",
        "p5": "MQTT 5.0",
    }.get(str(code or "").lower(), str(code or ""))


class MQTTConnectionRegistry:
    def __init__(self):
        self._connections = {}

    def ingest_line(self, line):
        line = str(line or "").strip()
        if not line:
            return False
        match = _CONNECT_RE.search(line)
        if match:
            client_id = match.group("client").strip()
            if not client_id:
                return False
            self._connections[client_id] = MQTTConnection(
                client_id=client_id,
                username=(match.group("username") or "").strip(),
                remote=match.group("remote").strip(),
                protocol=protocol_name(match.group("protocol")),
                keepalive=int(match.group("keepalive")),
                clean_session=match.group("clean") == "1",
                connected_at=_log_time(line),
            )
            return True
        match = _DISCONNECT_RE.search(line)
        if match:
            client_id = match.group("client").strip()
            return self._connections.pop(client_id, None) is not None
        return False

    def records(self):
        return sorted(
            self._connections.values(),
            key=lambda item: -item.connected_at.timestamp(),
        )

    def online_count(self):
        return len(self._connections)

    def mark_all_offline(self):
        changed = bool(self._connections)
        self._connections.clear()
        return changed

    def clear(self):
        self._connections.clear()
