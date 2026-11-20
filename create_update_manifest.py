# -*- coding: utf-8 -*-
"""生成自建更新服务器的 latest.json 并检查版本一致性。"""

import argparse
import hashlib
import json
import re
import urllib.parse
from pathlib import Path

from anhutoolbox.version import (
    GITHUB_OWNER, GITHUB_REPO, UPDATE_RELEASE_BASE_URL, __version__,
)


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


def _check_versions(root, version):
    if version != __version__:
        raise ValueError(
            "版本与 anhutoolbox/version.py 不一致：{} != {}".format(
                version, __version__))
    info = (Path(root) / "version_info.txt").read_text(encoding="utf-8")
    expected = r"\s*,\s*".join(
        re.escape(part) for part in version.split("."))
    if not re.search(
            r"filevers\s*=\s*\(\s*{}\s*(?:,\s*0\s*)?\)".format(expected),
            info):
        raise ValueError("version_info.txt 版本不一致")
    for field in ("FileVersion", "ProductVersion"):
        if "StringStruct(u'{}', u'{}')".format(field, version) not in info:
            raise ValueError(
                "version_info.txt {} 不一致".format(field))
    installer = (Path(root) / "installer.iss").read_text(encoding="utf-8")
    if '#define MyAppVersion "{}"'.format(version) not in installer:
        raise ValueError("installer.iss 版本不一致")


def build_manifest(root, installer_path, version, notes="", mandatory=False):
    root = Path(root).resolve()
    installer_path = Path(installer_path).resolve()
    _check_versions(root, version)
    if not installer_path.is_file():
        raise FileNotFoundError(installer_path)
    tag = "v{}".format(version)
    filename = urllib.parse.quote(installer_path.name)
    server_url = "{}/{}/{}".format(
        UPDATE_RELEASE_BASE_URL, tag, filename)
    github_url = (
        "https://github.com/{}/{}/releases/download/{}/{}"
    ).format(GITHUB_OWNER, GITHUB_REPO, tag, filename)
    return {
        "version": version,
        # 1.0.3 只接受 GitHub Release 地址；保留旧字段供其升级。
        "installer_url": github_url,
        # 1.0.4 起优先使用自建服务器，并回退到 GitHub。
        "installer_urls": [server_url, github_url],
        "sha256": _sha256(installer_path),
        "size": installer_path.stat().st_size,
        "notes": str(notes or ""),
        "mandatory": bool(mandatory),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--installer", required=True)
    parser.add_argument("--version", default=__version__)
    parser.add_argument("--notes", default="")
    parser.add_argument("--notes-file")
    parser.add_argument("--mandatory", action="store_true")
    parser.add_argument("--output", default="installer/latest.json")
    args = parser.parse_args()
    notes = args.notes
    if args.notes_file:
        notes = Path(args.notes_file).read_text(encoding="utf-8")
    manifest = build_manifest(
        Path(__file__).resolve().parent,
        args.installer,
        args.version,
        notes,
        args.mandatory,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(output.resolve())


if __name__ == "__main__":
    main()
