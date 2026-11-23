# -*- coding: utf-8 -*-
"""Wireshark CLI capture engine paths and packet parsing helpers."""

import csv
import ctypes
import os
import re
import sys
from pathlib import Path


_INTERFACE_RE = re.compile(r"^\s*(\d+)\.\s+(\S+)\s+\((.*)\)\s*$")


def capture_resource_dirs(base_dir=None):
    """Return the bundled engine and Npcap resource directories."""
    roots = []
    if base_dir:
        roots.append(Path(base_dir))
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            roots.append(Path(meipass))
    package_root = Path(__file__).resolve().parent.parent
    roots.append(package_root)

    engine_candidates = []
    npcap_candidates = []
    for root in roots:
        engine_candidates.extend((
            root / "lib" / "capture" / "engine",
            root / "capture" / "engine",
        ))
        npcap_candidates.extend((
            root / "lib" / "capture" / "npcap",
            root / "capture" / "npcap",
        ))

    engine = next(
        (path for path in engine_candidates if (path / "tshark.exe").is_file()),
        engine_candidates[0],
    )
    npcap = next(
        (path for path in npcap_candidates if path.is_dir()),
        npcap_candidates[0],
    )
    return engine, npcap


def parse_tshark_interfaces(output):
    """Parse the text emitted by ``tshark -D``."""
    interfaces = []
    for line in str(output or "").splitlines():
        match = _INTERFACE_RE.match(line)
        if match:
            interfaces.append({
                "index": int(match.group(1)),
                "device": match.group(2),
                "name": match.group(3).strip(),
            })
    return interfaces


def parse_packet_fields(line):
    """Parse one quoted tab-separated TShark fields record."""
    text = str(line or "").rstrip("\r\n")
    if not text:
        return None
    try:
        values = next(csv.reader(
            [text], delimiter="\t", quotechar='"', strict=False))
    except (csv.Error, StopIteration):
        return None
    if len(values) < 9:
        return None
    source = values[2] or values[3]
    destination = values[4] or values[5]
    try:
        frame_number = int(values[0])
        elapsed = float(values[1])
        length = int(values[7])
    except (TypeError, ValueError):
        return None
    return {
        "number": frame_number,
        "time": elapsed,
        "source": source,
        "destination": destination,
        "protocol": values[6],
        "length": length,
        "info": values[8],
    }


def build_tshark_capture_args(
        device, output_path, capture_filter="", display_filter="",
        write_output=True):
    """Build capture arguments while keeping BPF and display filters separate."""
    args = ["-i", str(device), "-l", "-n"]
    if write_output:
        args.extend(["-w", str(output_path)])
    capture_filter = str(capture_filter or "").strip()
    if capture_filter:
        args.extend(["-f", capture_filter])
    display_filter = str(display_filter or "").strip()
    if display_filter:
        args.extend(["-Y", display_filter])
    args.extend([
        "-T", "fields",
        "-E", "separator=/t",
        "-E", "quote=d",
        "-E", "occurrence=f",
        "-e", "frame.number",
        "-e", "frame.time_relative",
        "-e", "ip.src",
        "-e", "ipv6.src",
        "-e", "ip.dst",
        "-e", "ipv6.dst",
        "-e", "_ws.col.Protocol",
        "-e", "frame.len",
        "-e", "_ws.col.Info",
    ])
    return args


def build_dumpcap_capture_args(device, output_path, capture_filter=""):
    """Build Dumpcap arguments for capturing without display filtering."""
    args = ["-i", str(device), "-w", str(output_path)]
    capture_filter = str(capture_filter or "").strip()
    if capture_filter:
        args.extend(["-f", capture_filter])
    return args


def npcap_installer_path(base_dir=None):
    _engine, npcap_dir = capture_resource_dirs(base_dir)
    if not npcap_dir.is_dir():
        return None
    installers = sorted(
        npcap_dir.glob("npcap-*.exe"),
        key=lambda path: path.name,
        reverse=True,
    )
    return installers[0] if installers else None


class _ShellExecuteInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("fMask", ctypes.c_ulong),
        ("hwnd", ctypes.c_void_p),
        ("lpVerb", ctypes.c_wchar_p),
        ("lpFile", ctypes.c_wchar_p),
        ("lpParameters", ctypes.c_wchar_p),
        ("lpDirectory", ctypes.c_wchar_p),
        ("nShow", ctypes.c_int),
        ("hInstApp", ctypes.c_void_p),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", ctypes.c_wchar_p),
        ("hkeyClass", ctypes.c_void_p),
        ("dwHotKey", ctypes.c_ulong),
        ("hIcon", ctypes.c_void_p),
        ("hProcess", ctypes.c_void_p),
    ]


class NpcapInstallerSession:
    """Track an elevated Npcap installer process until it exits."""

    def __init__(self, handle):
        self._handle = handle

    def is_running(self):
        if not self._handle or os.name != "nt":
            return False
        kernel32 = ctypes.windll.kernel32
        kernel32.WaitForSingleObject.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong]
        kernel32.WaitForSingleObject.restype = ctypes.c_ulong
        result = kernel32.WaitForSingleObject(self._handle, 0)
        return int(result) == 0x00000102

    def close(self):
        if not self._handle:
            return
        handle = self._handle
        self._handle = None
        if os.name == "nt":
            kernel32 = ctypes.windll.kernel32
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle(handle)

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


def launch_npcap_installer(base_dir=None):
    installer = npcap_installer_path(base_dir)
    if installer is None or not installer.is_file():
        return None
    if os.name != "nt":
        return None
    shell32 = ctypes.windll.shell32
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(_ShellExecuteInfo)]
    shell32.ShellExecuteExW.restype = ctypes.c_bool
    info = _ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = str(installer)
    info.lpDirectory = str(installer.parent)
    info.nShow = 1  # SW_SHOWNORMAL
    if not shell32.ShellExecuteExW(ctypes.byref(info)) or not info.hProcess:
        return None
    return NpcapInstallerSession(info.hProcess)
