# -*- coding: utf-8 -*-
"""项目(Project)管理 -- 一个项目 = 一份完整的串口调试工作环境

一个项目保存: 连接模式 + 串口/TCP 参数 + 发送配置 + 显示配置 + 预设命令。
存储: data/projects/<项目名>.json (一个项目一个文件, 便于导出/导入/删除)
"""

import os
import re
import json

PROJECT_SUBDIR = "projects"
PROJECT_EXT = ".json"
DEFAULT_PROJECT_NAME = "默认项目"
FORMAT_VERSION = 1

_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def sanitize_name(name: str) -> str:
    """把项目名转成安全文件名(不含扩展名)"""
    name = _ILLEGAL.sub("_", str(name or "")).strip().rstrip(". ")
    if not name:
        name = DEFAULT_PROJECT_NAME
    if len(name) > 60:
        name = name[:60].rstrip(". ")
    return name


class ProjectManager:
    """项目的增删改查 -- 只负责文件读写, 不碰 UI"""

    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.dir = os.path.join(base_dir, "data", PROJECT_SUBDIR)
        try:
            os.makedirs(self.dir, exist_ok=True)
        except Exception as e:
            print("[AnhuToolbox] 创建项目目录失败:", e)

    # ---------------- 查询 ----------------
    def _files(self):
        try:
            return [f for f in os.listdir(self.dir)
                    if f.lower().endswith(PROJECT_EXT) and not f.endswith(".tmp")]
        except Exception:
            return []

    def _display_name(self, fname: str) -> str:
        """优先读文件内的 name 字段作为显示名, 读不到就用文件名"""
        try:
            with open(os.path.join(self.dir, fname), "r", encoding="utf-8") as f:
                n = str(json.load(f).get("name") or "").strip()
            if n:
                return n
        except Exception:
            pass
        return os.path.splitext(fname)[0]

    def names(self):
        """所有项目名(按名称排序)"""
        names = [self._display_name(f) for f in self._files()]
        names = [n for n in names if n]
        names.sort(key=lambda s: s.lower())
        return names

    def path_of(self, name: str):
        """按项目名找文件路径, 找不到返回 None"""
        exact = os.path.join(self.dir, sanitize_name(name) + PROJECT_EXT)
        if os.path.exists(exact) and self._display_name(os.path.basename(exact)) == name:
            return exact
        # 文件名被去重/转义过时按内部 name 反查。不能只看“清理后文件名
        # 是否存在”，否则 a/b 与 a?b 都会落到 a_b.json 并互相覆盖。
        for f in self._files():
            if self._display_name(f) == name:
                return os.path.join(self.dir, f)
        return None

    def exists(self, name: str) -> bool:
        return self.path_of(name) is not None

    def load(self, name: str):
        path = self.path_of(name)
        if not path:
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return None
            data.setdefault("format", FORMAT_VERSION)
            data.setdefault("name", name)
            return data
        except Exception as e:
            print("[AnhuToolbox] 读取项目失败:", name, e)
            return None

    # ---------------- 写入 ----------------
    def _write(self, path: str, data: dict) -> bool:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)        # 原子替换, 避免写一半损坏
            return True
        except Exception as e:
            print("[AnhuToolbox] 保存项目失败:", path, e)
            return False

    def save(self, name: str, data: dict) -> bool:
        """保存到已有项目; 文件不存在则新建"""
        data = dict(data)
        data["name"] = name
        path = self.path_of(name)
        if not path:
            path = os.path.join(
                self.dir, self._unique(sanitize_name(name)) + PROJECT_EXT)
        return self._write(path, data)

    def _unique(self, stem: str) -> str:
        """同名文件已存在时追加 (2)/(3)... 后缀"""
        if not os.path.exists(os.path.join(self.dir, stem + PROJECT_EXT)):
            return stem
        i = 2
        while os.path.exists(os.path.join(self.dir, "{} ({}){}".format(stem, i, PROJECT_EXT))):
            i += 1
        return "{} ({})".format(stem, i)

    def create(self, name: str, data: dict) -> str:
        """新建项目, 返回实际使用的项目名(可能因重名而调整)"""
        name = str(name or "").strip() or DEFAULT_PROJECT_NAME
        base = name
        i = 2
        while self.exists(name):
            name = "{} ({})".format(base, i)
            i += 1
        self.save(name, data)
        return name

    def rename(self, old: str, new: str) -> str:
        """重命名项目; 返回新名字(重名时会加后缀), 失败返回原名"""
        new = str(new or "").strip()
        if not new or new == old:
            return old
        path = self.path_of(old)
        if not path:
            return old
        base = new
        i = 2
        while self.exists(new) and self.path_of(new) != path:
            new = "{} ({})".format(base, i)
            i += 1
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["name"] = new
            new_stem = sanitize_name(new)
            new_path = os.path.join(self.dir, new_stem + PROJECT_EXT)
            if (os.path.normcase(os.path.abspath(new_path)) !=
                    os.path.normcase(os.path.abspath(path)) and
                    os.path.exists(new_path)):
                new_stem = self._unique(new_stem)
                new_path = os.path.join(self.dir, new_stem + PROJECT_EXT)
            if (os.path.normcase(os.path.abspath(new_path)) !=
                    os.path.normcase(os.path.abspath(path))):
                os.replace(path, new_path)   # 先改文件名
            with open(new_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return new
        except Exception as e:
            print("[AnhuToolbox] 重命名项目失败:", e)
            return old

    def delete(self, name: str) -> bool:
        path = self.path_of(name)
        if not path:
            return False
        try:
            os.remove(path)
            return True
        except Exception as e:
            print("[AnhuToolbox] 删除项目失败:", e)
            return False

    def export_to(self, name: str, dest: str) -> bool:
        data = self.load(name)
        if data is None:
            return False
        return self._write(dest, data)

    def import_from(self, src: str):
        """从 json 文件导入项目; 返回新项目名, 失败返回 None"""
        try:
            with open(src, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return None
            name = str(data.get("name") or "").strip()
            if not name:
                name = os.path.splitext(os.path.basename(src))[0]
            if self.exists(name):
                name = "{} (导入)".format(name)
            return self.create(name, data)
        except Exception as e:
            print("[AnhuToolbox] 导入项目失败:", e)
            return None
