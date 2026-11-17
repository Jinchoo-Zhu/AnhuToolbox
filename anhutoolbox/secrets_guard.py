# -*- coding: utf-8 -*-
"""检测待导出配置中的明文凭据，供导出前提示。"""

SENSITIVE_KEYS = {
    "password",
    "auth_password",
    "auth_token",
    "authorization",
    "proxy-authorization",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "apikey",
    "x-api-key",
    "client_secret",
    "secret",
}


def _has_value(value):
    return value is not None and str(value).strip() != ""


def contains_sensitive_values(value):
    if isinstance(value, dict):
        name = str(value.get("name") or "").strip().lower()
        if (name in SENSITIVE_KEYS
                and _has_value(value.get("value"))):
            return True
        for key, child in value.items():
            key_text = str(key).strip().lower()
            if key_text in SENSITIVE_KEYS and _has_value(child):
                return True
            if contains_sensitive_values(child):
                return True
    elif isinstance(value, (list, tuple)):
        return any(contains_sensitive_values(item) for item in value)
    return False
