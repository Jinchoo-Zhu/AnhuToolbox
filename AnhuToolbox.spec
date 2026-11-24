# -*- mode: python ; coding: utf-8 -*-

import hashlib
import os


def _verify_external_tools():
    """拒绝缺少第三方工具资源的安装包。"""
    root = os.path.dirname(os.path.abspath(SPEC))
    tools_root = os.path.join(root, "tools")
    marker = os.path.join(tools_root, "tools.gresource")
    if not os.path.isfile(marker):
        raise SystemExit(
            "无法打包：tools 第三方资源清单缺失。"
            "请检查主源码仓库中的 tools 目录和 tools/README.md 说明。"
        )
    with open(marker, "r", encoding="utf-8") as f:
        import json
        manifest = json.load(f)
    for entry in manifest.get("files", []):
        path = os.path.join(tools_root, *entry["path"].split("/"))
        if not os.path.isfile(path):
            raise SystemExit("工具资源不完整：" + path)
        digest = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != entry["sha256"]:
            raise SystemExit("工具资源校验失败：" + path)
    return os.path.dirname(tools_root)


def _verify_capture_runtime():
    root = os.path.dirname(os.path.abspath(SPEC))
    engine = os.path.join(root, "capture", "engine")
    npcap = os.path.join(root, "capture", "npcap")
    required = [
        os.path.join(engine, "tshark.exe"),
        os.path.join(engine, "dumpcap.exe"),
        os.path.join(engine, "libwireshark.dll"),
        os.path.join(engine, "COPYING.txt"),
        os.path.join(npcap, "npcap-1.89.exe"),
    ]
    missing = [path for path in required if not os.path.isfile(path)]
    if missing:
        raise SystemExit("抓包运行时资源不完整：" + "; ".join(missing))


def _verify_mqtt_runtime():
    root = os.path.dirname(os.path.abspath(SPEC))
    broker = os.path.join(root, "mqtt", "broker")
    required = [
        os.path.join(broker, "mosquitto.exe"),
        os.path.join(broker, "mosquitto_passwd.exe"),
        os.path.join(broker, "mosquitto_common.dll"),
        os.path.join(broker, "mosquitto_password_file.dll"),
        os.path.join(broker, "NOTICE.md"),
        os.path.join(broker, "edl-v10"),
        os.path.join(broker, "epl-v20"),
    ]
    missing = [path for path in required if not os.path.isfile(path)]
    if missing:
        raise SystemExit("MQTT 服务端运行时资源不完整：" + "; ".join(missing))


# 构建前仍校验第三方资源完整性，但不再把官方工具打进 exe。
# installer.iss 会根据任务选择把它们复制到安装目录的 tools\。
_verify_external_tools()
_verify_capture_runtime()
_verify_mqtt_runtime()
VERSION_FILE = os.path.join(
    os.path.dirname(os.path.abspath(SPEC)), "version_info.txt")

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('anhutoolbox.ico', '.'),
           ('anhutoolbox/assets/down_arrow.png', 'anhutoolbox/assets'),
           ('anhutoolbox/assets/up_arrow.png', 'anhutoolbox/assets'),
           # 勾选框的蓝色对勾，源码和打包版本共用
           ('anhutoolbox/assets/checkbox_check.svg', 'anhutoolbox/assets'),
           ('anhutoolbox/assets/checkbox_check_muted.svg', 'anhutoolbox/assets'),
           ('anhutoolbox/assets/add_interface.svg', 'anhutoolbox/assets'),
           ('anhutoolbox/assets/http_more.svg', 'anhutoolbox/assets'),
           ('anhutoolbox/assets/http_previous.svg', 'anhutoolbox/assets'),
           ('anhutoolbox/assets/http_next.svg', 'anhutoolbox/assets'),
           ('anhutoolbox/assets/http_environment.svg', 'anhutoolbox/assets'),
           ('anhutoolbox/assets/http_chevron_down.svg', 'anhutoolbox/assets'),
           ('anhutoolbox/assets/http_send.svg', 'anhutoolbox/assets'),
           ('anhutoolbox/assets/http_add.svg', 'anhutoolbox/assets'),
           ('anhutoolbox/assets/http_delete.svg', 'anhutoolbox/assets'),
           ('anhutoolbox/assets/http_upload.svg', 'anhutoolbox/assets'),
           ('anhutoolbox/assets/http_format.svg', 'anhutoolbox/assets'),
           ('anhutoolbox/assets/http_raw.svg', 'anhutoolbox/assets'),
           ('anhutoolbox/assets/http_copy.svg', 'anhutoolbox/assets'),
           ('anhutoolbox/assets/http_save.svg', 'anhutoolbox/assets'),
           ('anhutoolbox/assets/http_example.svg', 'anhutoolbox/assets'),
           ('anhutoolbox/assets/http_edit.svg', 'anhutoolbox/assets'),
           ('anhutoolbox/assets/http_close.svg', 'anhutoolbox/assets'),
           ('anhutoolbox/assets/password_show.svg', 'anhutoolbox/assets'),
           ('anhutoolbox/assets/password_hide.svg', 'anhutoolbox/assets'),
           # 统一弹窗的状态图标，源码和打包版本都使用同一套 PNG
           ('anhutoolbox/assets/dialog_status.png', 'anhutoolbox/assets'),
           ('anhutoolbox/assets/dialog_error.png', 'anhutoolbox/assets'),
           ('anhutoolbox/assets/dialog_success.png', 'anhutoolbox/assets'),
           ('anhutoolbox/assets/dialog_question.png', 'anhutoolbox/assets'),
           # Qt 中文翻译: 让「新建项目」这类内置对话框的按钮显示 确定/取消
           ('anhutoolbox/assets/qtbase_zh_CN.qm', 'anhutoolbox/assets'),
           # 抓包页面使用内置 TShark 引擎；最终位于 lib\capture\engine。
           ('capture/engine', 'capture/engine'),
           # Npcap 安装资源；最终位于 lib\capture\npcap。
           ('capture/npcap', 'capture/npcap')],
    hiddenimports=['h2', 'hpack', 'hyperframe'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Anhu百宝箱',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['anhutoolbox.ico'],
    version=VERSION_FILE,
    contents_directory='lib',  # 依赖(173 个 Qt DLL / Python / qrcode 等)放到 exe 旁的 lib/ 目录
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Anhu百宝箱',
)
