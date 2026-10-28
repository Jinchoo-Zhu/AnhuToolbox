# -*- coding: utf-8 -*-
"""硬件信息采集 -- 注册表/Win32 API 快速路径 + 一次性 PowerShell CIM 慢速路径

原实现把十几条 CIM/WMI 查询全部交给 PowerShell, 单次采集约 2.1s
(其中 Win32_Processor 一条就占 ~1.1s), 如果在 GUI 线程里同步调用,
窗口打开后会僵住 2-3 秒。

现改为两条路径:
  1) 注册表 + Win32 API (毫秒级): CPU 型号 / 主板型号 / 机型 / 系统运行时间;
  2) 注册表拿不到的内存条、显卡、磁盘、声卡、网卡、显示器,
     仍由一次 PowerShell CIM 查询完成 (约 0.5s)。

整体耗时从 ~2.1s 降到 ~0.6s; 即便如此, 采集仍应在后台线程中调用
(见 tools.HardwareInfoPage), 避免任何可感知的界面停顿。
"""

import base64
import ctypes
import json
import os
import platform
import subprocess
import time

# --- 注册表路径 ---
_KEY_BIOS = r"HARDWARE\DESCRIPTION\System\BIOS"
_KEY_CPU = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
_KEY_WIN = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"

# PowerShell 脚本: 只采集注册表拿不到的部分, 输出 JSON。
# 通过 -EncodedCommand (UTF-16LE) 传入, 避免中文/引号转义问题。
_PS_SCRIPT = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'SilentlyContinue'
$out = [ordered]@{}

# --- 系统名称 (Caption 为本地化文本, 如「Microsoft Windows 11 专业版」) ---
$out.os_caption = (Get-CimInstance Win32_OperatingSystem -Property Caption).Caption

# --- 内存 ---
$mems = @(Get-CimInstance Win32_PhysicalMemory)
if ($mems.Count -gt 0) {
    $total = ($mems | Measure-Object -Property Capacity -Sum).Sum
    $out.ram = "{0}GB" -f [math]::Round($total / 1GB)
    $out.ram_detail = (($mems | ForEach-Object { "{0}GB" -f [math]::Round($_.Capacity / 1GB) }) -join " + ")
    $out.ram_speed = $mems[0].Speed
    $out.ram_maker = $mems[0].Manufacturer
} else {
    $out.ram = ''
    $out.ram_detail = ''
    $out.ram_speed = ''
    $out.ram_maker = ''
}

# --- 显卡 (过滤虚拟显示适配器) ---
$out.gpus = @(Get-CimInstance Win32_VideoController |
    Where-Object { $_.Name -notmatch '(?i)virtual|oray|mumu|idddriver|indirect display|mirage|parsec' } |
    ForEach-Object { $_.Name.Trim() })

# --- 磁盘 ---
$out.disks = @(Get-CimInstance Win32_DiskDrive | ForEach-Object {
    "{0} ( {1}GB )" -f $_.Model.Trim(), [math]::Round($_.Size / 1GB)
})

# --- 声卡 ---
$out.sounds = @(Get-CimInstance Win32_SoundDevice | ForEach-Object { $_.Name.Trim() })

# --- 网卡 (过滤虚拟/蓝牙/环回等虚拟适配器) ---
$out.nics = @(Get-CimInstance Win32_NetworkAdapter |
    Where-Object { $_.PhysicalAdapter -and $_.MACAddress -and $_.Name -notmatch '(?i)vmware|virtual|bluetooth|loopback|tunnel|tap-windows|wintun' } |
    ForEach-Object { $_.Name.Trim() })

# --- 显示器 (从 EDID 读取型号) ---
$mon_list = @()
$mons = @(Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorID -ErrorAction SilentlyContinue)
foreach ($m in $mons) {
    $n = (($m.UserFriendlyName | Where-Object { $_ -ne 0 } | ForEach-Object { [char]$_ }) -join "").Trim()
    if ($n) { $mon_list += $n }
}
$out.monitors = @($mon_list)

$out | ConvertTo-Json -Compress -Depth 4
"""


# ============================================================
#  快速路径: 注册表 + Win32 API
# ============================================================
def _reg(path, name):
    """读取 HKLM 下的一个字符串值, 失败返回空串。"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
            val = winreg.QueryValueEx(k, name)[0]
        return str(val).strip() if val is not None else ""
    except Exception:
        return ""


def _arch_text():
    """架构文本, 与 WMI OSArchitecture 的中文文案保持一致 (如「64 位」)。"""
    m = platform.machine().upper()
    if m in ("AMD64", "X86_64", "ARM64", "IA64"):
        return "64 位"
    if m in ("X86", "I386", "I686"):
        return "32 位"
    return platform.machine()


def _has_battery():
    """本机是否存在系统电池 (用于区分笔记本/台式机)。

    GetSystemPowerStatus 的 BatteryFlag 为 128 表示「无系统电池」。
    比原来的 Win32_Battery 查询快得多 (微秒级)。
    """
    try:
        class _SYSTEM_POWER_STATUS(ctypes.Structure):
            _fields_ = [
                ("ACLineStatus", ctypes.c_ubyte),
                ("BatteryFlag", ctypes.c_ubyte),
                ("BatteryLifePercent", ctypes.c_ubyte),
                ("SystemStatusFlag", ctypes.c_ubyte),
                ("BatteryLifeTime", ctypes.c_ulong),
                ("BatteryFullLifeTime", ctypes.c_ulong),
            ]

        st = _SYSTEM_POWER_STATUS()
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(st)):
            return False
        return not (st.BatteryFlag & 128)
    except Exception:
        return False


def _uptime_seconds():
    """系统已运行秒数。用 GetTickCount64 (毫秒级), 比 WMI LastBootUpTime 更准。"""
    try:
        fn = ctypes.windll.kernel32.GetTickCount64
        fn.restype = ctypes.c_ulonglong  # 默认按 int 返回会溢出 (超过约 24 天)
        return fn() / 1000.0
    except Exception:
        return None


def _collect_local():
    """注册表 / Win32 API 采集 (毫秒级), 返回部分字段。"""
    bb_m = _reg(_KEY_BIOS, "BaseBoardManufacturer")
    bb_p = _reg(_KEY_BIOS, "BaseBoardProduct")
    model = "{} {}".format(bb_m, bb_p).strip()
    if not model:
        # 部分 DIY 主板 SMBIOS 里主板信息为空, 退回到整机厂商/型号
        model = "{} {}".format(
            _reg(_KEY_BIOS, "SystemManufacturer"),
            _reg(_KEY_BIOS, "SystemProductName"),
        ).strip()

    # 有电池=笔记本; 无电池=台式 (比 WMI PCSystemType 更可靠, 不会把 DIY 机误判为笔记本)
    ptype = "笔记本电脑" if _has_battery() else "台式电脑"

    info = {
        "model": "{} {}".format(model, ptype).strip(),
        "mainboard": model,
        "cpu": _reg(_KEY_CPU, "ProcessorNameString"),
        "os_arch": _arch_text(),
        "uptime_seconds": _uptime_seconds(),
    }
    # CPU 型号注册表缺失时 (极少见) 退回 platform 信息
    if not info["cpu"]:
        info["cpu"] = platform.processor().strip()
    return info


def _fmt_uptime(secs):
    secs = max(0, int(round(float(secs))))
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    return "{}天{}小时{}分钟{}秒".format(days, hours, minutes, seconds)


# ============================================================
#  慢速路径: 一次性 PowerShell CIM 查询
# ============================================================
def _collect_wmi(timeout=40):
    """内存条/显卡/磁盘/声卡/网卡/显示器, 一次 PowerShell 查询取回。"""
    encoded = base64.b64encode(_PS_SCRIPT.encode("utf-16-le")).decode("ascii")
    # Windows 下隐藏 PowerShell 控制台黑窗口, 做到无感采集
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True,
        timeout=timeout,
        creationflags=creationflags,
    )

    raw = proc.stdout
    text = None
    for enc in ("utf-8", "gbk"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", errors="replace")
    text = text.strip().lstrip("\ufeff")

    if not text:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(err or "无法获取硬件信息（PowerShell 无输出）")

    start = text.find("{")
    if start < 0:
        raise RuntimeError("硬件信息解析失败：" + text[:200])

    try:
        return json.loads(text[start:])
    except json.JSONDecodeError as e:
        raise RuntimeError("硬件信息 JSON 解析失败：" + str(e))


def collect_hardware_info(timeout=40):
    """采集本机硬件信息, 返回 dict。失败时抛出 RuntimeError。

    耗时约 0.6s, 请在后台线程中调用 (勿在 GUI 线程同步执行)。
    """
    info = _collect_local()

    # 注册表部分成功但 WMI 部分失败时, 仍把已拿到的信息返回给界面
    try:
        info.update(_collect_wmi(timeout=timeout) or {})
    except Exception as e:
        info["wmi_error"] = str(e)

    if not info.get("model") and not info.get("cpu") and "wmi_error" in info:
        raise RuntimeError(info["wmi_error"])

    # 系统名称: WMI 本地化 Caption + 架构, 缺 Caption 时退回注册表 ProductName
    caption = str(info.get("os_caption") or "").strip()
    if not caption:
        caption = _reg(_KEY_WIN, "ProductName")
    info["os"] = "{} {}".format(caption, info.get("os_arch") or "").strip()

    up = info.get("uptime_seconds")
    if up is not None:
        info["uptime"] = _fmt_uptime(up)

    return info


if __name__ == "__main__":  # 手动计时用: python -m anhutoolbox.hardware
    t0 = time.perf_counter()
    data = collect_hardware_info()
    print("collect_hardware_info: {:.2f}s".format(time.perf_counter() - t0))
    for k, v in data.items():
        print("  {} = {}".format(k, v))
