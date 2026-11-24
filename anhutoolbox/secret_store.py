# -*- coding: utf-8 -*-
"""Windows DPAPI encryption for secrets stored in project JSON."""

import base64
import copy
import ctypes
import os

from .secrets_guard import SENSITIVE_KEYS


_PREFIX = "dpapi-v1:"
_ENTROPY = b"AnhuToolbox-project-v1"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1
_MARKER_KEY = "_anhu_secret_store"
_MARKER_VERSION = "dpapi-v1"


class SecretStorageError(RuntimeError):
    pass


if os.name == "nt":
    class _DataBlob(ctypes.Structure):
        _fields_ = [
            ("cbData", ctypes.c_ulong),
            ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
        ]


def _blob(data):
    buffer = ctypes.create_string_buffer(data)
    return _DataBlob(
        len(data),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
    ), buffer


def _protect(text):
    if os.name != "nt":
        raise SecretStorageError("DPAPI 仅支持 Windows")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    source, source_buffer = _blob(text.encode("utf-8"))
    entropy, entropy_buffer = _blob(_ENTROPY)
    output = _DataBlob()
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob), ctypes.c_wchar_p,
        ctypes.POINTER(_DataBlob), ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_ulong,
        ctypes.POINTER(_DataBlob),
    ]
    if not crypt32.CryptProtectData(
        ctypes.byref(source),
        "AnhuToolbox secret",
        ctypes.byref(entropy),
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output),
    ):
        raise SecretStorageError(
            "Windows DPAPI 加密失败：{}".format(
                ctypes.get_last_error()))
    try:
        raw = ctypes.string_at(output.pbData, output.cbData)
        return _PREFIX + base64.b64encode(raw).decode("ascii")
    finally:
        kernel32.LocalFree(output.pbData)
        del source_buffer, entropy_buffer


def _unprotect(value):
    if os.name != "nt":
        raise SecretStorageError("DPAPI 仅支持 Windows")
    try:
        raw = base64.b64decode(
            str(value)[len(_PREFIX):], validate=True)
    except Exception as exc:
        raise SecretStorageError("DPAPI 密文格式错误") from exc
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    source, source_buffer = _blob(raw)
    entropy, entropy_buffer = _blob(_ENTROPY)
    output = _DataBlob()
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob), ctypes.POINTER(ctypes.c_wchar_p),
        ctypes.POINTER(_DataBlob), ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_ulong,
        ctypes.POINTER(_DataBlob),
    ]
    if not crypt32.CryptUnprotectData(
        ctypes.byref(source),
        None,
        ctypes.byref(entropy),
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output),
    ):
        raise SecretStorageError(
            "Windows DPAPI 解密失败，项目可能由其他 Windows 用户创建")
    try:
        raw_text = ctypes.string_at(output.pbData, output.cbData)
        return raw_text.decode("utf-8")
    finally:
        kernel32.LocalFree(output.pbData)
        del source_buffer, entropy_buffer


def _is_sensitive_name(value):
    return str(value or "").strip().lower() in SENSITIVE_KEYS


def _has_text(value):
    return value is not None and str(value).strip() != ""


def encrypt_secrets(value):
    value = copy.deepcopy(value)

    def visit(node):
        if isinstance(node, dict):
            if (
                _is_sensitive_name(node.get("name"))
                and _has_text(node.get("value"))
            ):
                node["value"] = _protect(str(node["value"]))
            for key, child in list(node.items()):
                if (
                    _is_sensitive_name(key)
                    and isinstance(child, str)
                    and _has_text(child)
                ):
                    node[key] = _protect(child)
                else:
                    visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    if isinstance(value, dict):
        value[_MARKER_KEY] = _MARKER_VERSION
    visit(value)
    return value


def decrypt_secrets(value):
    value = copy.deepcopy(value)
    decrypt_enabled = (
        isinstance(value, dict)
        and value.get(_MARKER_KEY) == _MARKER_VERSION
    )
    if decrypt_enabled:
        value.pop(_MARKER_KEY, None)

    def visit(node):
        if isinstance(node, dict):
            if (
                _is_sensitive_name(node.get("name"))
                and isinstance(node.get("value"), str)
                and node["value"].startswith(_PREFIX)
                and decrypt_enabled
            ):
                node["value"] = _unprotect(node["value"])
            for key, child in list(node.items()):
                if (
                    _is_sensitive_name(key)
                    and isinstance(child, str)
                    and child.startswith(_PREFIX)
                    and decrypt_enabled
                ):
                    node[key] = _unprotect(child)
                else:
                    visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    return value
