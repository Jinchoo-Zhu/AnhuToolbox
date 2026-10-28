# -*- mode: python ; coding: utf-8 -*-

import hashlib
import os


def _verify_external_tools():
    """拒绝缺少第三方工具资源的安装包。"""
    root = os.path.dirname(os.path.abspath(SPEC))
    tools_root = os.path.abspath(os.environ.get("ANHU_TOOLS_DIR", os.path.join(root, "tools")))
    marker = os.path.join(tools_root, "tools.gresource")
    if not os.path.isfile(marker):
        raise SystemExit(
            "无法打包：tools 第三方资源清单缺失。"
            "请先恢复 AnhuToolbox-tools 仓库，详见 tools/README.md。"
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


TOOLS_ROOT = os.path.join(_verify_external_tools(), "tools")


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('anhutoolbox.ico', '.'),
           ('anhutoolbox/assets/down_arrow.png', 'anhutoolbox/assets'),
           # Qt 中文翻译: 让「新建项目」这类内置对话框的按钮显示 确定/取消
           ('anhutoolbox/assets/qtbase_zh_CN.qm', 'anhutoolbox/assets'),
           # 第三方工具: 安装包会使用这些外置资源，防止未打包工具附件
           (TOOLS_ROOT, 'tools')],
    hiddenimports=[],
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
