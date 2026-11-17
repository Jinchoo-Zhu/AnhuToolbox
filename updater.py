# -*- coding: utf-8 -*-
"""AnhuToolbox 独立更新器。"""

import argparse
import ctypes
import hashlib
import logging
import os
import subprocess
import sys

CREATE_NO_WINDOW = 0x08000000
SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


def wait_for_process(pid, timeout=60):
    if os.name != "nt":
        return True
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [
        ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32,
    ]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32,
    ]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    handle = kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
    if not handle:
        return True
    try:
        return kernel32.WaitForSingleObject(
            handle, int(timeout * 1000)) == WAIT_OBJECT_0
    finally:
        kernel32.CloseHandle(handle)


def start_application(path):
    if not path or not os.path.isfile(path):
        return False
    try:
        subprocess.Popen([path], cwd=os.path.dirname(path))
        return True
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--installer", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--app", required=True)
    parser.add_argument("--log", required=True)
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.log), exist_ok=True)
    logging.basicConfig(
        filename=args.log, level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    logging.info("updater started for pid=%s", args.pid)
    if not wait_for_process(args.pid):
        logging.error("timed out waiting for application exit")
        start_application(args.app)
        return 1
    try:
        actual_hash = sha256_file(args.installer)
        if actual_hash != args.sha256.lower():
            raise RuntimeError("installer SHA-256 mismatch")
        result = subprocess.run(
            [
                args.installer,
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                "/CLOSEAPPLICATIONS",
            ],
            creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        logging.info("installer exit code=%s", result.returncode)
        success = result.returncode in (0, 3010)
    except Exception:
        logging.exception("update installation failed")
        success = False
    if success:
        try:
            os.remove(args.installer)
        except OSError:
            pass
    start_application(args.app)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
