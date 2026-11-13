# -*- coding: utf-8 -*-
"""当前进程的内存和 CPU 占用采样。"""

import ctypes
import os
import sys
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessUsage:
    memory_bytes: int
    cpu_percent: float


class _WindowsBackend:
    class _FileTime(ctypes.Structure):
        _fields_ = [
            ("dwLowDateTime", ctypes.c_uint32),
            ("dwHighDateTime", ctypes.c_uint32),
        ]

    class _ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_uint32),
            ("PageFaultCount", ctypes.c_uint32),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    def __init__(self):
        self._kernel32 = ctypes.WinDLL(
            "kernel32", use_last_error=True)
        self._psapi = ctypes.WinDLL(
            "psapi", use_last_error=True)
        self._kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        self._psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(self._ProcessMemoryCounters),
            ctypes.c_uint32,
        ]
        self._psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        self._kernel32.GetProcessTimes.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(self._FileTime),
            ctypes.POINTER(self._FileTime),
            ctypes.POINTER(self._FileTime),
            ctypes.POINTER(self._FileTime),
        ]
        self._kernel32.GetProcessTimes.restype = ctypes.c_int
        self._handle = self._kernel32.GetCurrentProcess()

    def memory_bytes(self):
        counters = self._ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        if not self._psapi.GetProcessMemoryInfo(
                self._handle, ctypes.byref(counters), counters.cb):
            raise OSError("GetProcessMemoryInfo failed")
        return int(counters.WorkingSetSize)

    @staticmethod
    def _filetime_value(value):
        return (
            int(value.dwHighDateTime) << 32
        ) | int(value.dwLowDateTime)

    def cpu_seconds(self):
        creation = self._FileTime()
        exited = self._FileTime()
        kernel = self._FileTime()
        user = self._FileTime()
        if not self._kernel32.GetProcessTimes(
                self._handle,
                ctypes.byref(creation),
                ctypes.byref(exited),
                ctypes.byref(kernel),
                ctypes.byref(user)):
            raise OSError("GetProcessTimes failed")
        total_100ns = (
            self._filetime_value(kernel)
            + self._filetime_value(user)
        )
        return total_100ns / 10_000_000.0


class _ProcBackend:
    def memory_bytes(self):
        with open("/proc/self/statm", "r", encoding="ascii") as stream:
            resident_pages = int(stream.read().split()[1])
        return resident_pages * os.sysconf("SC_PAGE_SIZE")

    def cpu_seconds(self):
        with open("/proc/self/stat", "r", encoding="ascii") as stream:
            stat = stream.read()
        fields = stat.rsplit(")", 1)[1].split()
        ticks = int(fields[11]) + int(fields[12])
        return ticks / os.sysconf("SC_CLK_TCK")


class _ResourceBackend:
    def memory_bytes(self):
        import resource
        usage = resource.getrusage(resource.RUSAGE_SELF)
        scale = 1 if sys.platform == "darwin" else 1024
        return int(usage.ru_maxrss) * scale

    def cpu_seconds(self):
        import resource
        usage = resource.getrusage(resource.RUSAGE_SELF)
        return float(usage.ru_utime + usage.ru_stime)


class ProcessMetrics:
    """采样当前进程；CPU 百分比与任务管理器一致，按整机核心数归一化。"""

    def __init__(self):
        if sys.platform == "win32":
            self._backend = _WindowsBackend()
        elif os.path.exists("/proc/self/stat"):
            self._backend = _ProcBackend()
        else:
            self._backend = _ResourceBackend()
        self._cpu_count = max(1, os.cpu_count() or 1)
        self._last_cpu_seconds = self._backend.cpu_seconds()
        self._last_sample_time = time.perf_counter()

    def sample(self) -> ProcessUsage:
        memory = self._backend.memory_bytes()
        now = time.perf_counter()
        cpu_seconds = self._backend.cpu_seconds()
        elapsed = now - self._last_sample_time
        if elapsed <= 0:
            cpu_percent = 0.0
        else:
            delta = max(
                0.0, cpu_seconds - self._last_cpu_seconds)
            cpu_percent = min(
                100.0, delta / elapsed / self._cpu_count * 100.0)
        self._last_cpu_seconds = cpu_seconds
        self._last_sample_time = now
        return ProcessUsage(
            memory_bytes=max(0, int(memory)),
            cpu_percent=max(0.0, cpu_percent),
        )
