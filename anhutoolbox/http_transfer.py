# -*- coding: utf-8 -*-
"""HTTP 接口库与 Postman、OpenAPI、Apipost 之间的转换。"""

import copy
import json
import secrets
from urllib.parse import urlsplit


FORMAT_APIPOST = "apipost"
FORMAT_SWAGGER = "swagger"
FORMAT_POSTMAN = "postman"

FORMAT_LABELS = {
    FORMAT_APIPOST: "Apipost",
    FORMAT_SWAGGER: "Swagger / OpenAPI",
    FORMAT_POSTMAN: "Postman 2.1",
}


class HttpTransferError(ValueError):
    pass


def _entry(name="", value="", description="", enabled=True):
    return {
        "name": str(name or ""),
        "value": str(value if value is not None else ""),
        "description": str(description or ""),
        "enabled": bool(enabled),
    }


def _blank_request():
    return {
        "method": "GET",
        "url": "",
        "timeout": 30,
        "follow_redirects": True,
        "verify_tls": True,
        "http_version": "http/1.1",
        "params": [],
        "headers": [],
        "path_params": [],
        "cookies": [],
        "body_type": "none",
        "raw_format": "JSON",
        "body": "",
        "auth_type": "无",
        "auth_user": "",
        "auth_password": "",
        "auth_token": "",
        "response_example": "",
    }


def normalise_request(data):
    data = data if isinstance(data, dict) else {}
    request = _blank_request()
    for key in request:
        if key in data and data[key] is not None:
            request[key] = copy.deepcopy(data[key])
    legacy = {
        "无": "none",
        "JSON": "raw",
        "Text": "raw",
        "XML": "raw",
        "Form": "urlencoded",
    }
    request["body_type"] = legacy.get(
        str(request.get("body_type") or ""),
        str(request.get("body_type") or "none"),
    )
    return request


def detect_format(data):
    if not isinstance(data, dict):
        raise HttpTransferError("文件根节点必须是 JSON 对象")
    if isinstance(data.get("apis"), list) and "project_id" in data:
        return FORMAT_APIPOST
    info = data.get("info")
    schema = str(info.get("schema") or "") if isinstance(info, dict) else ""
    if schema.startswith("https://schema.getpostman.com/json/collection/"):
        return FORMAT_POSTMAN
    if str(data.get("swagger") or "").startswith("2."):
        return FORMAT_SWAGGER
    if str(data.get("openapi") or "").startswith("3."):
        return FORMAT_SWAGGER
    if isinstance(data.get("item"), list):
        return FORMAT_POSTMAN
    if isinstance(data.get("paths"), dict):
        return FORMAT_SWAGGER
    raise HttpTransferError("无法识别文件格式")


def _folder_paths(folders):
    by_id = {
        str(item.get("id")): item for item in (folders or [])
        if item.get("id")
    }

    def path(folder_id):
        names = []
        current = str(folder_id or "") or None
        seen = set()
        while current and current in by_id and current not in seen:
            seen.add(current)
            item = by_id[current]
            names.append(str(item.get("name") or "新建目录"))
            current = str(item.get("parent_id") or "") or None
        return tuple(reversed(names))

    return path


def _library_items(library):
    folders = [
        dict(item) for item in (library.get("folders") or [])
        if isinstance(item, dict)
    ]
    interfaces = [
        dict(item) for item in (library.get("interfaces") or [])
        if isinstance(item, dict)
    ]
    return folders, interfaces


def _add_unique_folder(folders, seen, path):
    path = tuple(str(part).strip() for part in path if str(part).strip())
    for index in range(1, len(path) + 1):
        current = path[:index]
        if current not in seen:
            seen.add(current)
            folders.append({"path": current})


def _parse_enabled(value, default=True):
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in ("0", "false", "no", "off", "-1")
    return bool(value) and value != -1


def _parse_postman_entry(item):
    item = item if isinstance(item, dict) else {}
    return _entry(
        item.get("key", item.get("name", "")),
        item.get("value", ""),
        item.get("description", ""),
        not bool(item.get("disabled", False))
        and _parse_enabled(item.get("enabled"), True),
    )


def _postman_url(value):
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ""
    raw = str(value.get("raw") or "")
    if raw:
        return raw
    protocol = str(value.get("protocol") or "https")
    host = value.get("host") or []
    if isinstance(host, list):
        host = ".".join(str(part) for part in host)
    path = value.get("path") or []
    if isinstance(path, list):
        path = "/".join(str(part) for part in path)
    port = str(value.get("port") or "")
    netloc = str(host)
    if port:
        netloc += ":" + port
    return "{}://{}/{}".format(
        protocol, netloc, str(path).lstrip("/"))


def _body_from_mode(mode, body):
    request = _blank_request()
    body = body if isinstance(body, dict) else {}
    mode = str(mode or "none").lower()
    if mode in ("none", ""):
        request["body_type"] = "none"
    elif mode in ("form-data", "formdata", "multipart"):
        request["body_type"] = "form-data"
        request["body"] = "\n".join(
            "{}={}".format(item.get("name", ""), item.get("value", ""))
            for item in _parse_postman_entries(body.get("formdata"))
        )
    elif mode in ("urlencoded", "x-www-form-urlencoded"):
        request["body_type"] = "urlencoded"
        request["body"] = "\n".join(
            "{}={}".format(item.get("name", ""), item.get("value", ""))
            for item in _parse_postman_entries(body.get("urlencoded"))
        )
    elif mode in ("binary", "file"):
        request["body_type"] = "binary"
        request["body"] = str(body.get("binary") or body.get("file") or "")
    elif mode in ("msgpack",):
        request["body_type"] = "msgpack"
        request["body"] = str(body.get("raw") or "")
    else:
        request["body_type"] = "raw"
        raw = body.get("raw")
        if raw is None:
            raw = body.get("text", "")
        request["body"] = str(raw or "")
        language = str(
            ((body.get("options") or {}).get("raw") or {}).get(
                "language") or mode
        ).lower()
        request["raw_format"] = (
            "JSON" if mode == "json" or language == "json"
            else "XML" if mode in ("xml",) or language == "xml"
            else "Text"
        )
    return request


def _parse_postman_entries(items):
    return [
        _parse_postman_entry(raw)
        for raw in (items or []) if isinstance(raw, dict)
    ]


def _parse_postman_auth(auth):
    request = _blank_request()
    auth = auth if isinstance(auth, dict) else {}
    auth_type = str(auth.get("type") or "").lower()
    values = {
        item.get("key"): item.get("value", "")
        for item in (auth.get(auth_type) or [])
        if isinstance(item, dict)
    }
    if auth_type == "bearer":
        request["auth_type"] = "Bearer"
        request["auth_token"] = str(values.get("token") or "")
    elif auth_type == "basic":
        request["auth_type"] = "Basic"
        request["auth_user"] = str(values.get("username") or "")
        request["auth_password"] = str(values.get("password") or "")
    return request


def _parse_postman(data):
    result = {
        "folders": [], "interfaces": [], "warnings": [],
        "environments": [], "active_environment": None,
    }
    variables = []
    for item in data.get("variable") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("key") or "").strip()
        if name:
            variables.append({
                "name": name,
                "value": str(item.get("value") or ""),
                "description": str(item.get("description") or ""),
            })
    if variables:
        info = data.get("info") or {}
        result["environments"].append({
            "name": "{} 变量".format(
                info.get("name") or "Postman"),
            "variables": variables,
        })
        result["active_environment"] = result["environments"][0]
    folder_seen = set()

    def walk(items, path):
        for raw in items or []:
            if not isinstance(raw, dict):
                continue
            if isinstance(raw.get("item"), list):
                current = tuple(path) + (
                    str(raw.get("name") or "未命名文件夹"),)
                _add_unique_folder(
                    result["folders"], folder_seen, current)
                walk(raw.get("item"), current)
                continue
            request_data = raw.get("request")
            if not isinstance(request_data, dict):
                request_data = {}
            request = _blank_request()
            request["method"] = str(
                request_data.get("method") or "GET").upper()
            request["url"] = _postman_url(request_data.get("url"))
            request["headers"] = _parse_postman_entries(
                request_data.get("header"))
            url_obj = request_data.get("url")
            if isinstance(url_obj, dict):
                request["params"] = _parse_postman_entries(
                    url_obj.get("query"))
                request["path_params"] = [
                    _entry(item.get("key"), item.get("value"))
                    for item in (url_obj.get("variable") or [])
                    if isinstance(item, dict)
                ]
            body_request = _body_from_mode(
                (request_data.get("body") or {}).get("mode"),
                request_data.get("body") or {},
            )
            for key in (
                    "body_type", "raw_format", "body"):
                request[key] = body_request[key]
            auth_request = _parse_postman_auth(
                request_data.get("auth"))
            for key in (
                    "auth_type", "auth_user",
                    "auth_password", "auth_token"):
                request[key] = auth_request[key]
            responses = raw.get("response") or []
            if responses and isinstance(responses[0], dict):
                request["response_example"] = str(
                    responses[0].get("body") or "")
            result["interfaces"].append({
                "name": str(raw.get("name") or "未命名接口"),
                "folder_path": tuple(path),
                "request": request,
            })
            if request_data.get("event") or raw.get("event"):
                result["warnings"].append(
                    "{}：Postman 脚本未导入".format(
                        raw.get("name") or "未命名接口"))

    walk(data.get("item"), ())
    return result


def _apipost_enabled(item):
    if "is_checked" in item:
        return _parse_enabled(item.get("is_checked"))
    return _parse_enabled(item.get("enabled"), True)


def _parse_apipost_parameters(items):
    return [
        _entry(
            item.get("key", item.get("name", "")),
            item.get("value", ""),
            item.get("description", ""),
            _apipost_enabled(item),
        )
        for item in (items or []) if isinstance(item, dict)
    ]


def _parse_apipost(data):
    apis = data.get("apis") or []
    by_id = {
        str(item.get("target_id") or ""): item
        for item in apis
        if isinstance(item, dict) and item.get("target_id")
    }
    folder_ids = {}

    def folder_path(parent_id):
        ids = []
        current = str(parent_id or "") or None
        seen = set()
        while current and current not in ("0", "root") and current in by_id:
            if current in seen:
                break
            seen.add(current)
            item = by_id[current]
            if str(item.get("target_type") or "").lower() in (
                    "api", "request"):
                break
            ids.append(current)
            current = str(item.get("parent_id") or "") or None
        return tuple(
            str(by_id[item_id].get("name") or "未命名文件夹")
            for item_id in reversed(ids)
        )

    result = {
        "folders": [], "interfaces": [], "warnings": [],
        "environments": [], "active_environment": None,
    }
    for environment in (
            (data.get("global") or {}).get("envs") or []):
        if not isinstance(environment, dict):
            continue
        variables = []
        raw_variables = environment.get("env_var_list") or {}
        if isinstance(raw_variables, dict):
            raw_variables = [
                dict(value, name=name)
                for name, value in raw_variables.items()
                if isinstance(value, dict)
            ]
        for variable in raw_variables if isinstance(raw_variables, list) else []:
            if not isinstance(variable, dict):
                continue
            name = str(variable.get("name") or "").strip()
            if not name:
                continue
            variables.append({
                "name": name,
                "value": str(
                    variable.get("current_value",
                                 variable.get("value", "")) or ""),
                "description": str(variable.get("description") or ""),
            })
        result["environments"].append({
            "name": str(environment.get("name") or "Apipost 环境"),
            "variables": variables,
        })
    if result["environments"]:
        result["active_environment"] = next(
            (environment for environment in result["environments"]
             if environment.get("variables")),
            result["environments"][0],
        )
    folder_seen = set()
    for folder_id, item in by_id.items():
        if str(item.get("target_type") or "").lower() in ("api", "request"):
            continue
        path = folder_path(folder_id) + (
            str(item.get("name") or "未命名文件夹"),)
        folder_ids[folder_id] = path
        _add_unique_folder(result["folders"], folder_seen, path)

    for item in apis:
        if not isinstance(item, dict):
            continue
        if str(item.get("target_type") or "").lower() not in (
                "", "api", "request"):
            continue
        req = item.get("request") or {}
        request = _blank_request()
        request["method"] = str(item.get("method") or "GET").upper()
        request["url"] = str(item.get("url") or "")
        request["http_version"] = str(
            item.get("protocol") or "http/1.1").lower()
        request["headers"] = _parse_apipost_parameters(
            (req.get("header") or {}).get("parameter"))
        request["params"] = _parse_apipost_parameters(
            (req.get("query") or {}).get("parameter"))
        request["cookies"] = _parse_apipost_parameters(
            (req.get("cookie") or {}).get("parameter"))
        request["path_params"] = _parse_apipost_parameters(
            (req.get("restful") or {}).get("parameter"))
        body = req.get("body") or {}
        mode = str(body.get("mode") or "none").lower()
        if mode in ("json", "raw", "text", "xml"):
            request["body_type"] = "raw"
            request["raw_format"] = (
                "JSON" if mode == "json"
                else "XML" if mode == "xml" else "Text")
            request["body"] = str(body.get("raw") or "")
        elif mode in ("form-data", "formdata", "multipart"):
            request["body_type"] = "form-data"
            request["body"] = "\n".join(
                "{}={}".format(item.get("key", ""), item.get("value", ""))
                for item in (body.get("parameter") or [])
                if isinstance(item, dict)
            )
        elif mode in ("urlencoded", "x-www-form-urlencoded"):
            request["body_type"] = "urlencoded"
            request["body"] = "\n".join(
                "{}={}".format(item.get("key", ""), item.get("value", ""))
                for item in (body.get("parameter") or [])
                if isinstance(item, dict)
            )
        elif mode in ("binary", "file"):
            request["body_type"] = "binary"
            request["body"] = str(body.get("binary") or "")
        elif mode == "msgpack":
            request["body_type"] = "msgpack"
            request["body"] = str(body.get("raw") or "")
        auth = req.get("auth") or {}
        auth_type = str(auth.get("type") or "inherit").lower()
        if auth_type == "bearer":
            request["auth_type"] = "Bearer"
            request["auth_token"] = str(
                (auth.get("bearer") or {}).get("key") or "")
        elif auth_type == "basic":
            request["auth_type"] = "Basic"
            request["auth_user"] = str(
                (auth.get("basic") or {}).get("username") or "")
            request["auth_password"] = str(
                (auth.get("basic") or {}).get("password") or "")
        examples = (item.get("response") or {}).get("example") or []
        if examples and isinstance(examples[0], dict):
            request["response_example"] = str(
                examples[0].get("raw") or "")
        path = folder_path(item.get("parent_id"))
        result["interfaces"].append({
            "name": str(item.get("name") or "未命名接口"),
            "folder_path": path,
            "request": request,
        })
        if req.get("pre_tasks") or req.get("post_tasks"):
            result["warnings"].append(
                "{}：Apipost 前/后置脚本未导入".format(
                    item.get("name") or "未命名接口"))
    return result


def _swagger_base(data):
    if str(data.get("openapi") or "").startswith("3."):
        servers = data.get("servers") or []
        if servers and isinstance(servers[0], dict):
            return str(servers[0].get("url") or "").rstrip("/")
        return ""
    scheme = (data.get("schemes") or ["https"])[0]
    host = str(data.get("host") or "")
    base = str(data.get("basePath") or "")
    return "{}://{}{}".format(scheme, host, base).rstrip("/") if host else base


def _parse_swagger_parameter(item):
    schema = item.get("schema") or {}
    value = item.get("example", item.get("default", ""))
    if value == "" and schema.get("type") == "array":
        value = schema.get("default", "")
    return _entry(
        item.get("name", ""),
        value,
        item.get("description", ""),
        _parse_enabled(item.get("enabled"), True),
    )


def _parse_swagger(data):
    result = {"folders": [], "interfaces": [], "warnings": []}
    folder_seen = set()
    base = _swagger_base(data)
    for path, path_item in (data.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        shared = path_item.get("parameters") or []
        for method, operation in path_item.items():
            if method.lower() not in (
                    "get", "post", "put", "patch", "delete",
                    "head", "options", "trace"):
                continue
            if not isinstance(operation, dict):
                operation = {}
            request = _blank_request()
            request["method"] = method.upper()
            servers = operation.get("servers") or data.get("servers") or []
            operation_base = base
            if servers and isinstance(servers[0], dict):
                operation_base = str(servers[0].get("url") or base).rstrip("/")
            request["url"] = str(
                operation.get("x-anhu-url")
                or operation_base + str(path))
            request["timeout"] = operation.get(
                "x-anhu-timeout", request["timeout"])
            request["follow_redirects"] = operation.get(
                "x-anhu-follow-redirects", request["follow_redirects"])
            request["verify_tls"] = operation.get(
                "x-anhu-verify-tls", request["verify_tls"])
            request["http_version"] = operation.get(
                "x-anhu-http-version", request["http_version"])
            request["response_example"] = str(
                operation.get("x-anhu-response-example") or "")
            stored_auth = str(
                operation.get("x-anhu-auth-type") or "")
            if stored_auth in ("Bearer", "Basic"):
                request["auth_type"] = stored_auth
                request["auth_user"] = str(
                    operation.get("x-anhu-auth-user") or "")
            parameters = list(shared) + list(
                operation.get("parameters") or [])
            for raw in parameters:
                if not isinstance(raw, dict):
                    continue
                location = str(raw.get("in") or "").lower()
                if location == "query":
                    request["params"].append(
                        _parse_swagger_parameter(raw))
                elif location == "path":
                    request["path_params"].append(
                        _parse_swagger_parameter(raw))
                elif location == "header":
                    request["headers"].append(
                        _parse_swagger_parameter(raw))
                elif location == "cookie":
                    request["cookies"].append(
                        _parse_swagger_parameter(raw))
                elif location == "body":
                    request["body_type"] = "raw"
                    request["body"] = json.dumps(
                        raw.get("schema") or {}, ensure_ascii=False)
            request_body = operation.get("requestBody") or {}
            if isinstance(request_body, dict) and request_body:
                content = request_body.get("content") or {}
                media_type, media = next(
                    iter(content.items()), ("application/json", {}))
                if media_type.startswith("multipart/"):
                    request["body_type"] = "form-data"
                elif media_type == "application/x-www-form-urlencoded":
                    request["body_type"] = "urlencoded"
                elif media_type == "application/octet-stream":
                    request["body_type"] = "binary"
                else:
                    request["body_type"] = "raw"
                    request["raw_format"] = (
                        "JSON" if "json" in media_type
                        else "XML" if "xml" in media_type else "Text")
                    request["body"] = json.dumps(
                        (media or {}).get("example")
                        or (media or {}).get("schema") or {},
                        ensure_ascii=False,
                    )
            name = str(
                operation.get("summary")
                or operation.get("operationId")
                or path)
            tags = operation.get("tags") or []
            folder_path = ()
            stored_folder = str(
                operation.get("x-anhu-folder-path") or "")
            if stored_folder:
                folder_path = tuple(
                    part.strip()
                    for part in stored_folder.split("/")
                    if part.strip() and part.strip() != "默认"
                )
            elif tags:
                folder_path = tuple(
                    part.strip()
                    for part in str(tags[0]).split("/")
                    if part.strip()
                )
            _add_unique_folder(
                result["folders"], folder_seen, folder_path)
            responses = operation.get("responses") or {}
            for response in responses.values():
                if not isinstance(response, dict):
                    continue
                examples = response.get("examples") or {}
                if examples:
                    first = next(iter(examples.values()))
                    request["response_example"] = json.dumps(
                        first, ensure_ascii=False)
                    break
                content = response.get("content") or {}
                if content:
                    first = next(iter(content.values()), {})
                    example = (first or {}).get("example")
                    if example is not None:
                        request["response_example"] = json.dumps(
                            example, ensure_ascii=False)
                        break
            result["interfaces"].append({
                "name": name,
                "folder_path": folder_path,
                "request": request,
            })
    return result


def parse_transfer(data, format_name=None):
    format_name = format_name or detect_format(data)
    if format_name == FORMAT_POSTMAN:
        return _parse_postman(data)
    if format_name == FORMAT_APIPOST:
        return _parse_apipost(data)
    if format_name == FORMAT_SWAGGER:
        return _parse_swagger(data)
    raise HttpTransferError("不支持的导入格式")


def _postman_query(url):
    parsed = urlsplit(url)
    return [
        {
            "key": name,
            "value": value,
            "description": "",
            "disabled": False,
        }
        for name, value in (
            part.split("=", 1) if "=" in part else (part, "")
            for part in parsed.query.split("&") if part
        )
    ]


def _postman_body(request):
    body_type = str(request.get("body_type") or "none")
    text = str(request.get("body") or "")
    if body_type == "none":
        return {"mode": "none"}
    if body_type == "form-data":
        return {
            "mode": "formdata",
            "formdata": [
                {"key": line.split("=", 1)[0],
                 "value": line.split("=", 1)[1]
                 if "=" in line else "",
                 "type": "text"}
                for line in text.splitlines() if line
            ],
        }
    if body_type == "urlencoded":
        return {
            "mode": "urlencoded",
            "urlencoded": [
                {"key": line.split("=", 1)[0],
                 "value": line.split("=", 1)[1]
                 if "=" in line else ""}
                for line in text.splitlines() if line
            ],
        }
    if body_type in ("binary", "msgpack"):
        return {"mode": body_type, "raw": text}
    language = str(request.get("raw_format") or "Text").lower()
    return {
        "mode": "raw",
        "raw": text,
        "options": {"raw": {"language": language}},
    }


def _auth_for_postman(request):
    auth_type = str(request.get("auth_type") or "无")
    if auth_type == "Bearer":
        return {
            "type": "bearer",
            "bearer": [{
                "key": "token",
                "value": str(request.get("auth_token") or ""),
                "type": "string",
            }],
        }
    if auth_type == "Basic":
        return {
            "type": "basic",
            "basic": [
                {"key": "username", "value": str(request.get("auth_user") or "")},
                {"key": "password", "value": str(request.get("auth_password") or "")},
            ],
        }
    return None


def _build_postman(library, project_name):
    folders, interfaces = _library_items(library)
    path_of = _folder_paths(folders)
    tree = {}
    folder_nodes = {}

    def node_for(path):
        children = tree
        key_path = []
        for name in path:
            key_path.append(name)
            key = tuple(key_path)
            if key not in folder_nodes:
                item = {"name": name, "item": []}
                children.setdefault("_items", []).append(item)
                folder_nodes[key] = item
            children = folder_nodes[key]
            children.setdefault("item", [])
            children.setdefault("_items", [])
        return children

    for item in interfaces:
        request = normalise_request(item.get("request"))
        url = str(request.get("url") or "")
        body = _postman_body(request)
        raw = {
            "name": str(item.get("name") or "未命名接口"),
            "request": {
                "method": str(request.get("method") or "GET").upper(),
                "header": [
                    {
                        "key": entry.get("name", ""),
                        "value": entry.get("value", ""),
                        "description": entry.get("description", ""),
                        "disabled": not entry.get("enabled", True),
                    }
                    for entry in request.get("headers") or []
                ],
                "url": {
                    "raw": url,
                    "query": [
                        {
                            "key": entry.get("name", ""),
                            "value": entry.get("value", ""),
                            "disabled": not entry.get("enabled", True),
                        }
                        for entry in request.get("params") or []
                    ],
                },
                "body": body,
            },
            "response": ([{
                "name": "示例响应",
                "body": str(request.get("response_example") or ""),
            }] if request.get("response_example") else []),
        }
        auth = _auth_for_postman(request)
        if auth:
            raw["request"]["auth"] = auth
        parent = node_for(path_of(item.get("folder_id")))
        parent["_items"].append(raw)

    def strip_internal(node):
        items = []
        for child in node.get("_items", node.get("item", [])):
            if isinstance(child, dict) and "item" in child:
                child["item"] = strip_internal(child)
            else:
                child.pop("_items", None)
            items.append(child)
        return items

    environments = library.get("environments") or []
    active_id = str(library.get("active_environment") or "")
    active_environment = next(
        (item for item in environments
         if str(item.get("id")) == active_id),
        environments[0] if environments else {},
    )
    return {
        "info": {
            "name": project_name or "AnhuToolbox HTTP",
            "schema": (
                "https://schema.getpostman.com/json/collection/"
                "v2.1.0/collection.json"),
        },
        "variable": [
            {
                "key": str(item.get("name") or ""),
                "value": str(item.get("value") or ""),
                "type": "string",
            }
            for item in (active_environment.get("variables") or [])
            if item.get("name")
        ],
        "item": strip_internal({"item": tree.get("_items", [])}),
    }


def _swagger_parameters(request):
    result = []
    for location, key in (
            ("query", "params"),
            ("path", "path_params"),
            ("header", "headers"),
            ("cookie", "cookies")):
        for item in request.get(key) or []:
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            parameter = {
                "name": name,
                "in": location,
                "required": bool(item.get("enabled", True)),
                "schema": {"type": "string"},
                "example": str(item.get("value") or ""),
                "description": str(item.get("description") or ""),
            }
            result.append(parameter)
    return result


def _swagger_request_body(request):
    body_type = str(request.get("body_type") or "none")
    text = str(request.get("body") or "")
    if body_type == "none":
        return None
    if body_type == "form-data":
        properties = {}
        for line in text.splitlines():
            name, _, value = line.partition("=")
            if name:
                properties[name] = {"type": "string", "example": value}
        return {
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object", "properties": properties,
                    }
                }
            }
        }
    if body_type == "urlencoded":
        properties = {}
        for line in text.splitlines():
            name, _, value = line.partition("=")
            if name:
                properties[name] = {"type": "string", "example": value}
        return {
            "content": {
                "application/x-www-form-urlencoded": {
                    "schema": {
                        "type": "object", "properties": properties,
                    }
                }
            }
        }
    raw_format = str(request.get("raw_format") or "Text").lower()
    media_type = (
        "application/json" if raw_format == "json"
        else "application/xml" if raw_format == "xml"
        else "application/octet-stream" if body_type == "binary"
        else "text/plain")
    content = {"schema": {"type": "string"}, "example": text}
    if media_type == "application/json":
        try:
            content["example"] = json.loads(text)
        except Exception:
            pass
    return {"content": {media_type: content}}


def _swagger_folder_tag(folder_path):
    return "/".join(folder_path) if folder_path else "默认"


def _build_swagger(library, project_name):
    folders, interfaces = _library_items(library)
    path_of = _folder_paths(folders)
    base_candidates = []
    for item in interfaces:
        request = normalise_request(item.get("request"))
        url = str(request.get("url") or "")
        parsed = urlsplit(url)
        origin = (
            "{}://{}".format(parsed.scheme, parsed.netloc)
            if parsed.scheme and parsed.netloc else "")
        if origin and origin not in base_candidates:
            base_candidates.append(origin)
    base = base_candidates[0] if base_candidates else "http://localhost"
    paths = {}
    security_schemes = {}
    for item in interfaces:
        request = normalise_request(item.get("request"))
        url = str(request.get("url") or "")
        parsed = urlsplit(url)
        origin = (
            "{}://{}".format(parsed.scheme, parsed.netloc)
            if parsed.scheme and parsed.netloc else base)
        path = parsed.path or "/"
        method = str(request.get("method") or "GET").lower()
        operation = {
            "summary": str(item.get("name") or "未命名接口"),
            "operationId": "anhu_{}".format(secrets.token_hex(4)),
            "tags": [_swagger_folder_tag(path_of(item.get("folder_id")))],
            "parameters": _swagger_parameters(request),
            "responses": {
                "200": {
                    "description": "成功",
                    "content": {
                        "application/json": {
                            "example": request.get("response_example") or {}
                        }
                    },
                }
            },
            "x-anhu-url": url,
            "x-anhu-timeout": request.get("timeout"),
            "x-anhu-follow-redirects": request.get("follow_redirects"),
            "x-anhu-verify-tls": request.get("verify_tls"),
            "x-anhu-http-version": request.get("http_version"),
            "x-anhu-response-example": request.get("response_example"),
            "x-anhu-auth-type": request.get("auth_type"),
            "x-anhu-auth-user": request.get("auth_user"),
            "x-anhu-folder-path": _swagger_folder_tag(
                path_of(item.get("folder_id"))),
        }
        auth_type = str(request.get("auth_type") or "")
        if auth_type == "Bearer":
            security_schemes["anhu_bearer"] = {
                "type": "http", "scheme": "bearer",
            }
            operation["security"] = [{"anhu_bearer": []}]
        elif auth_type == "Basic":
            security_schemes["anhu_basic"] = {
                "type": "http", "scheme": "basic",
            }
            operation["security"] = [{"anhu_basic": []}]
        if origin != base:
            operation["servers"] = [{"url": origin}]
        body = _swagger_request_body(request)
        if body:
            operation["requestBody"] = body
        paths.setdefault(path, {})[method] = operation
    return {
        "openapi": "3.0.3",
        "info": {
            "title": project_name or "AnhuToolbox HTTP",
            "version": "1.0.0",
        },
        "servers": [{"url": base}],
        "components": {
            "securitySchemes": security_schemes,
        },
        "tags": [
            {"name": folder.get("path")[-1]}
            for folder in folders if folder.get("path")
        ],
        "paths": paths,
    }


def _apipost_auth(request):
    auth_type = str(request.get("auth_type") or "无").lower()
    auth = {
        "type": "inherit",
        "kv": {"key": "", "value": "", "in": "header"},
        "bearer": {"key": ""},
        "basic": {"username": "", "password": ""},
        "digest": {
            "username": "", "password": "", "realm": "", "nonce": "",
            "algorithm": "", "qop": "", "nc": "", "cnonce": "", "opaque": "",
        },
        "hawk": {
            "authId": "", "authKey": "", "algorithm": "", "user": "",
            "nonce": "", "extraData": "", "default": "", "delegation": "",
            "timestamp": "", "includePayloadHash": False,
        },
        "awsv4": {
            "accessKey": "", "secretKey": "", "region": "", "service": "",
            "sessionToken": "", "addAuthDataToQuery": False,
        },
        "ntlm": {
            "username": "", "password": "", "entity": "",
            "workstation": "", "disableRetryRequest": False,
        },
        "edgegrid": {
            "accessToken": "", "clientToken": "", "clientSecret": "",
            "nonce": "", "timestamp": "", "baseURi": "", "headersToSign": "",
        },
        "oauth1": {
            "consumerKey": "", "consumerSecret": "", "signatureMethod": "HMAC-SHA1",
            "addEmptyParamsToSign": True, "includeBodyHash": True,
            "addParamsToHeader": False, "disableHeaderEncoding": False,
            "realm": "", "version": "1.0", "nonce": "", "timestamp": "",
            "verifier": "", "callback": "", "tokenSecret": "", "token": "",
        },
        "jwt": {
            "addTokenTo": "header", "algorithm": "HS256", "secret": "",
            "isSecretBase64Encoded": False, "payload": "", "headerPrefix": "Bearer",
            "queryParamKey": "", "header": "",
        },
        "asap": {
            "alg": "HS256", "iss": "", "aud": "", "kid": "", "privateKey": "",
            "sub": "", "claims": "", "exp": "",
        },
    }
    if auth_type == "bearer":
        auth["type"] = "bearer"
        auth["bearer"]["key"] = str(request.get("auth_token") or "")
    elif auth_type == "basic":
        auth["type"] = "basic"
        auth["basic"]["username"] = str(request.get("auth_user") or "")
        auth["basic"]["password"] = str(request.get("auth_password") or "")
    return auth


def _apipost_body(request):
    body_type = str(request.get("body_type") or "none")
    text = str(request.get("body") or "")
    raw_format = str(request.get("raw_format") or "Text").lower()
    mode = (
        "json" if body_type == "raw" and raw_format == "json"
        else "xml" if body_type == "raw" and raw_format == "xml"
        else body_type)
    result = {
        "mode": mode,
        "parameter": [],
        "raw": text if body_type in ("raw", "msgpack") else "",
        "raw_parameter": [],
        "raw_schema": {"type": "object" if mode == "json" else "string"},
        "binary": {},
    }
    if body_type in ("form-data", "urlencoded"):
        for line in text.splitlines():
            name, _, value = line.partition("=")
            if name:
                result["parameter"].append({
                    "param_id": secrets.token_hex(7),
                    "description": "",
                    "field_type": "string",
                    "is_checked": 1,
                    "key": name,
                    "value": value,
                    "schema": {"type": "string"},
                })
    elif body_type == "binary":
        result["binary"] = {"raw": text}
    return result


def _build_apipost(library, project_name):
    folders, interfaces = _library_items(library)
    path_of = _folder_paths(folders)
    project_id = secrets.token_hex(7)
    folder_ids = {}
    apis = []
    sort = 1000
    paths = {
        path_of(folder.get("id"))
        for folder in folders
        if folder.get("id")
    }
    paths.discard(())
    for path in sorted(paths, key=lambda value: (len(value), value)):
        parent = folder_ids.get(path[:-1], "0")
        target_id = secrets.token_hex(7)
        folder_ids[path] = target_id
        apis.append({
            "target_id": target_id,
            "project_id": project_id,
            "parent_id": parent,
            "target_type": "folder",
            "name": path[-1],
            "version": 1,
            "sort": sort,
        })
        sort += 1000
    folder_lookup = dict(folder_ids)
    for item in interfaces:
        request = normalise_request(item.get("request"))
        path = path_of(item.get("folder_id"))
        parent = folder_lookup.get(tuple(path), "0")
        body = _apipost_body(request)
        parameters = lambda entries: {
            "parameter": [
                {
                    "param_id": secrets.token_hex(7),
                    "description": entry.get("description", ""),
                    "field_type": "string",
                    "is_checked": 1 if entry.get("enabled", True) else -1,
                    "key": entry.get("name", ""),
                    "value": entry.get("value", ""),
                    "schema": {"type": "string"},
                }
                for entry in entries or []
            ]
        }
        response_example = str(request.get("response_example") or "")
        apis.append({
            "target_id": secrets.token_hex(7),
            "project_id": project_id,
            "parent_id": parent,
            "target_type": "api",
            "name": str(item.get("name") or "未命名接口"),
            "version": 1,
            "sort": sort,
            "method": str(request.get("method") or "GET").upper(),
            "url": str(request.get("url") or ""),
            "protocol": str(request.get("http_version") or "http/1.1"),
            "mark_id": "1",
            "description": "",
            "request": {
                "auth": _apipost_auth(request),
                "body": body,
                "pre_tasks": [],
                "post_tasks": [],
                "header": parameters(request.get("headers")),
                "query": {
                    "query_add_equal": 1,
                    "parameter": parameters(request.get("params"))["parameter"],
                },
                "cookie": {
                    "cookie_encode": 1,
                    "parameter": parameters(request.get("cookies"))["parameter"],
                },
                "restful": parameters(request.get("path_params")),
            },
            "response": {
                "example": ([{
                    "example_id": "1",
                    "raw": response_example,
                    "raw_parameter": [],
                    "headers": [],
                    "expect": {
                        "code": "200", "content_type": "json",
                        "is_default": 1, "mock": "", "name": "成功",
                        "schema": {"type": "object", "properties": {}},
                        "verify_type": "schema", "sleep": 0,
                    },
                }] if response_example else []),
                "is_check_result": 1,
            },
            "ai_expect": {
                "list": [], "none_math_expect_id": "1",
                "none_math_example": None,
            },
            "mock_server_enable": 1,
            "mock_ip_white_list_enable": -1,
            "mock_ip_white_list": "",
            "mock_show_target_id": 0,
            "attribute_info": {},
            "tags": [],
        })
        sort += 1000
    environment_records = []
    for index, environment in enumerate(
            library.get("environments") or []):
        variables = {}
        for variable in environment.get("variables") or []:
            name = str(variable.get("name") or "").strip()
            if not name:
                continue
            value = str(variable.get("value") or "")
            variables[name] = {
                "value": value,
                "current_value": value,
                "description": str(
                    variable.get("description") or ""),
            }
        environment_records.append({
            "env_id": str(
                environment.get("id") or secrets.token_hex(7)),
            "name": str(environment.get("name") or "默认环境"),
            "is_private": 0,
            "sort": (index + 1) * 1000,
            "server_list": [],
            "env_var_list": variables,
        })
    return {
        "project_id": project_id,
        "name": project_name or "AnhuToolbox HTTP",
        "intro": "",
        "global": {
            "envs": environment_records,
            "servers": [],
            "global_vars": {},
            "global_param": {
                "header": {"parameter": []},
                "query": {"parameter": []},
                "body": {"parameter": []},
                "cookie": {"parameter": []},
                "auth": _apipost_auth(_blank_request()),
                "pre_tasks": [],
                "post_tasks": [],
            },
            "codes": [],
            "marks": [],
            "attributes": [],
            "mock_custom_rules": [],
            "db_link": [],
            "describe_library": [],
            "custom_func": [],
        },
        "apis": apis,
        "models": [],
        "samples": [],
        "automated_testings": [],
    }


def build_transfer(library, format_name, project_name=""):
    if format_name == FORMAT_POSTMAN:
        return _build_postman(library, project_name)
    if format_name == FORMAT_SWAGGER:
        return _build_swagger(library, project_name)
    if format_name == FORMAT_APIPOST:
        return _build_apipost(library, project_name)
    raise HttpTransferError("不支持的导出格式")
