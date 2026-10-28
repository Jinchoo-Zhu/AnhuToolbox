#!/usr/bin/env python3
"""验证 tools 附件完整性与打包清单，不依赖项目第三方依赖。"""

import argparse
import hashlib
import json
from pathlib import Path


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_tools(root):
    root = Path(root).resolve()
    tools_dir = root / "tools"
    manifest_path = tools_dir / "tools.gresource"
    if not manifest_path.is_file():
        raise SystemExit("工具清单缺失：{}".format(manifest_path))
    try:
        entries = json.loads(manifest_path.read_text(encoding="utf-8"))["files"]
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit("工具清单格式错误：{}".format(exc)) from exc

    errors = []
    for entry in entries:
        relative_path = entry.get("path", "")
        path = (tools_dir / relative_path).resolve()
        if tools_dir.resolve() not in path.parents:
            errors.append("非法工具路径：{}".format(relative_path))
            continue
        if not path.is_file():
            errors.append("文件缺失：{}".format(relative_path))
            continue
        if path.stat().st_size != entry.get("size"):
            errors.append("文件大小不符：{}".format(relative_path))
            continue
        if sha256_file(path) != entry.get("sha256"):
            errors.append("SHA-256 校验失败：{}".format(relative_path))

    if errors:
        print("工具检查失败：")
        for error in errors[:20]:
            print("  " + error)
        if len(errors) > 20:
            print("  ……其余 {} 项错误".format(len(errors) - 20))
        raise SystemExit(1)
    print("工具检查通过：{} 个文件，{} MB".format(
        len(entries), sum(item["size"] for item in entries) // (1024 * 1024)
    ))


def main():
    parser = argparse.ArgumentParser(description="检查 AnhuToolbox 工具附件")
    parser.add_argument(
        "--root", default=str(Path(__file__).resolve().parent), help="项目根目录"
    )
    args = parser.parse_args()
    verify_tools(args.root)


if __name__ == "__main__":
    main()

