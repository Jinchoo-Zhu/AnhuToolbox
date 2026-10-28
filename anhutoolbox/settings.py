# -*- coding: utf-8 -*-
"""AnhuToolbox 配置持久化 -- 保存/恢复用户设置"""
import os, json, copy

SETTINGS_FILE = None

# 前 3 项是与项目无关的全局偏好; 其余是旧版遗留项, 现在由「项目文件」保存,
# 只在本机还没有任何项目时作为默认项目的初始值。
DEFAULTS = {
    "last_project": "",
    "preset_visible": False,
    "preset_splitter": None,
    "mode": "serial",
    "serial": {
        "port": "COM1", "baud": "115200", "data": "8",
        "stop": "1", "parity": "None", "flow": "None"
    },
    "tcpserver": {"port": 8888, "client_timeout": 30},
    "tcpclient": {"host": "127.0.0.1", "port": 8888, "local_port": ""},
    "send": {
        "hex_send": False, "crlf": True, "repeat": False,
        "interval": 1000, "checksum": "ModbusCRC16",
        "start_byte": 1, "end_byte_text": "末尾"
    },
    "log": {"hex_display": True, "timestamp": True, "timeout": 0}
}

_settings = None

def init(filepath):
    global SETTINGS_FILE, _settings
    SETTINGS_FILE = filepath
    _settings = copy.deepcopy(DEFAULTS)
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                saved = json.load(f)
            _deep_update(_settings, saved)
        except Exception as e:
            # 配置损坏时回退默认值，但记录原因便于排查
            print("[AnhuToolbox] 读取配置失败，已使用默认值:", e)

def _deep_update(d, u):
    for k, v in u.items():
        if isinstance(v, dict) and k in d and isinstance(d[k], dict):
            _deep_update(d[k], v)
        else:
            d[k] = v

def _prune(d, ref):
    """按默认值结构裁剪 -- 写盘时顺手清掉历史遗留的无用字段"""
    out = {}
    for k, v in (d or {}).items():
        if k not in ref:
            continue
        r = ref[k]
        out[k] = _prune(v, r) if isinstance(v, dict) and isinstance(r, dict) else v
    return out

def save():
    global SETTINGS_FILE, _settings
    if SETTINGS_FILE and _settings:
        try:
            os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(_prune(_settings, DEFAULTS), f, ensure_ascii=False, indent=2)
        except Exception as e:
            # 保存失败静默会让用户以为设置已保存，记录原因便于排查
            print("[AnhuToolbox] 保存配置失败:", e)

def get(path, default=None):
    keys = path.split(".")
    val = _settings or {}
    for k in keys:
        if isinstance(val, dict):
            val = val.get(k, default)
        else:
            return default
    return val

def set(path, value):
    keys = path.split(".")
    d = _settings or {}
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value
