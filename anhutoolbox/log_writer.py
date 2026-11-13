# -*- coding: utf-8 -*-
"""后台日志文件写入器。"""

import os
import queue
import threading
import time

from PySide6.QtCore import QObject, Signal


AUTO_CLEAR_RECORDS = 10000
AUTO_CLEAR_BYTES = 300 * 1024 * 1024


class AsyncLogWriter(QObject):
    """把文本交给后台线程写入，并在需要清页时提供同步 flush 屏障。"""

    error = Signal(str)
    MAX_QUEUE_ITEMS = 20000
    FLUSH_INTERVAL_S = 0.5

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self._path = path
        self._queue = queue.Queue(maxsize=self.MAX_QUEUE_ITEMS)
        self._stop_event = threading.Event()
        self._failed = False
        self._active = True
        self._file = open(
            path, "w", encoding="utf-8", newline="\n")
        self._thread = threading.Thread(
            target=self._run,
            name="AnhuLogWriter",
            daemon=True,
        )
        self._thread.start()

    @property
    def path(self):
        return self._path

    @property
    def is_active(self):
        return self._active and not self._failed

    def write_text(self, text):
        if not self.is_active:
            return False
        try:
            self._queue.put_nowait(("write", str(text)))
        except queue.Full:
            self._fail("日志写入队列已满，正在停止保存")
            return False
        return True

    def flush(self, timeout=10.0):
        if not self.is_active or not self._thread.is_alive():
            return False
        result = {"ok": False}
        event = threading.Event()
        try:
            self._queue.put(
                ("flush", (event, result)), timeout=timeout)
        except queue.Full:
            return False
        return bool(event.wait(timeout) and result["ok"])

    def close(self, timeout=10.0):
        if not self._active:
            self._stop_event.set()
            if self._thread.is_alive():
                self._thread.join(timeout)
            return
        self.flush(timeout)
        self._active = False
        self._stop_event.set()
        try:
            self._queue.put_nowait(("stop", None))
        except queue.Full:
            pass
        self._thread.join(timeout)

    def _fail(self, message):
        if self._failed:
            return
        self._failed = True
        self._active = False
        self._stop_event.set()
        self.error.emit(message)

    def _close_file(self):
        file_obj, self._file = self._file, None
        if file_obj is not None:
            try:
                file_obj.flush()
            except Exception:
                pass
            try:
                file_obj.close()
            except Exception:
                pass

    def _run(self):
        dirty = False
        last_flush = time.monotonic()
        try:
            while True:
                try:
                    kind, payload = self._queue.get(timeout=0.1)
                except queue.Empty:
                    if dirty and (
                            time.monotonic() - last_flush
                            >= self.FLUSH_INTERVAL_S):
                        self._file.flush()
                        dirty = False
                        last_flush = time.monotonic()
                    if self._stop_event.is_set():
                        break
                    continue

                if kind == "write":
                    self._file.write(payload)
                    dirty = True
                elif kind == "flush":
                    event, result = payload
                    self._file.flush()
                    os.fsync(self._file.fileno())
                    dirty = False
                    last_flush = time.monotonic()
                    result["ok"] = True
                    event.set()
                elif kind == "stop":
                    break
        except Exception as exc:
            self._fail("日志文件写入失败: {}".format(exc))
        finally:
            self._close_file()
            self._active = False

            while True:
                try:
                    kind, payload = self._queue.get_nowait()
                except queue.Empty:
                    break
                if kind == "flush":
                    event, result = payload
                    result["ok"] = False
                    event.set()
