# -*- coding: utf-8 -*-
"""运行期可写数据目录解析与便携数据迁移。"""

import os
import shutil
import tempfile

APP_DATA_DIR = "AnhuToolbox"


def _is_writable_dir(path):
    try:
        os.makedirs(path, exist_ok=True)
        with tempfile.NamedTemporaryFile(
                mode="wb", prefix=".anhu_write_", dir=path,
                delete=False) as probe:
            probe_name = probe.name
        os.remove(probe_name)
        return True
    except Exception:
        return False


def _copy_missing(source, destination):
    if not os.path.exists(source) or os.path.exists(destination):
        return
    try:
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copy2(source, destination)
    except Exception as e:
        print("[AnhuToolbox] 迁移旧数据失败:", source, e)


def choose_data_root(base_dir):
    """返回包含 ``data`` 子目录的可写根目录。

    便携版优先继续使用程序目录，保持原有行为。安装在 Program Files 等只读
    位置时，自动切换到 ``%LOCALAPPDATA%\\AnhuToolbox``，并复制旧配置和项目。
    """
    base_dir = os.path.abspath(base_dir)
    preferred = os.path.join(base_dir, "data")
    if _is_writable_dir(preferred):
        return base_dir

    local_appdata = os.environ.get("LOCALAPPDATA") or os.path.join(
        os.path.expanduser("~"), "AppData", "Local")
    fallback_root = os.path.join(local_appdata, APP_DATA_DIR)
    fallback_data = os.path.join(fallback_root, "data")
    if not _is_writable_dir(fallback_data):
        raise RuntimeError("无法创建可写数据目录：{}".format(fallback_data))

    for name in ("settings.json", "presets.json"):
        _copy_missing(
            os.path.join(preferred, name),
            os.path.join(fallback_data, name),
        )
    source_projects = os.path.join(preferred, "projects")
    target_projects = os.path.join(fallback_data, "projects")
    if os.path.isdir(source_projects) and not os.path.isdir(target_projects):
        try:
            shutil.copytree(source_projects, target_projects)
        except Exception as e:
            print("[AnhuToolbox] 迁移项目目录失败:", e)
    return fallback_root
