# -*- coding: utf-8 -*-
"""应用版本与更新源。"""

__version__ = "1.1.2"

GITHUB_OWNER = "Jinchoo-Zhu"
GITHUB_REPO = "AnhuToolbox"

UPDATE_SERVER_HOST = "mcsgzy.online"
UPDATE_SERVER_PORT = 8443
UPDATE_SERVER_BASE_PATH = "/anhutoolbox"
UPDATE_MANIFEST_URL = (
    "https://{host}:{port}{base_path}/updates/latest.json"
).format(
    host=UPDATE_SERVER_HOST,
    port=UPDATE_SERVER_PORT,
    base_path=UPDATE_SERVER_BASE_PATH,
)
GITHUB_MANIFEST_URL = (
    "https://github.com/{}/{}/releases/latest/download/latest.json"
).format(GITHUB_OWNER, GITHUB_REPO)
UPDATE_MANIFEST_URLS = (
    UPDATE_MANIFEST_URL,
    GITHUB_MANIFEST_URL,
)
UPDATE_RELEASE_BASE_URL = (
    "https://{host}:{port}{base_path}/releases"
).format(
    host=UPDATE_SERVER_HOST,
    port=UPDATE_SERVER_PORT,
    base_path=UPDATE_SERVER_BASE_PATH,
)
