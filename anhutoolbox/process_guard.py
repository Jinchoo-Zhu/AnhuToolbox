# -*- coding: utf-8 -*-
"""Windows Job Object helpers for child-process cleanup."""

import ctypes
import os
import threading


_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001


if os.name == "nt":
    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]


    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", ctypes.c_ulong),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_ulong),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.c_ulong),
            ("SchedulingClass", ctypes.c_ulong),
        ]


    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation",
             _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]


class WindowsJob:
    """Own a kill-on-close Windows job for child processes."""

    def __init__(self):
        self._handle = None
        self._lock = threading.Lock()

    def _ensure(self):
        if os.name != "nt":
            return None
        if self._handle:
            return self._handle
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [
            ctypes.c_void_p, ctypes.c_wchar_p]
        kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            return None
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = (
            _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
        kernel32.SetInformationJobObject.argtypes = [
            ctypes.c_void_p, ctypes.c_int,
            ctypes.c_void_p, ctypes.c_ulong,
        ]
        if not kernel32.SetInformationJobObject(
                handle,
                _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(info),
                ctypes.sizeof(info)):
            kernel32.CloseHandle(handle)
            return None
        self._handle = handle
        return handle

    def assign(self, pid):
        pid = int(pid or 0)
        if pid <= 0 or os.name != "nt":
            return False
        with self._lock:
            job = self._ensure()
            if not job:
                return False
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [
                ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            kernel32.OpenProcess.restype = ctypes.c_void_p
            process = kernel32.OpenProcess(
                _PROCESS_SET_QUOTA | _PROCESS_TERMINATE,
                False,
                pid,
            )
            if not process:
                return False
            try:
                kernel32.AssignProcessToJobObject.argtypes = [
                    ctypes.c_void_p, ctypes.c_void_p]
                return bool(kernel32.AssignProcessToJobObject(
                    job, process))
            finally:
                kernel32.CloseHandle(process)

    def close(self):
        with self._lock:
            handle = self._handle
            self._handle = None
            if handle and os.name == "nt":
                ctypes.WinDLL(
                    "kernel32", use_last_error=True).CloseHandle(handle)

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


_APP_JOB = WindowsJob()
_GLOBAL_LOCK = threading.Lock()


def assign_child_process(pid):
    with _GLOBAL_LOCK:
        return _APP_JOB.assign(pid)


def close_child_processes():
    with _GLOBAL_LOCK:
        _APP_JOB.close()
