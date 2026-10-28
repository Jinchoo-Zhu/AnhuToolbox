# -*- coding: utf-8 -*-
"""AnhuToolbox -- Anhu 百宝箱 入口"""

import sys, os, ctypes

if sys.platform == "win32":
    # Set AppUserModelID so taskbar shows our icon, not Python
    # 版本号递增: 换了新 AUMID 后 Windows 会把它当成"新应用",
    # 从而绕过旧版在系统里缓存的"无图标/默认图标"状态
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AnhuToolbox.AnhuToolbox.3.0")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from PySide6.QtCore import QTimer
from anhutoolbox.main_window import MainWindow
from anhutoolbox import toolbox


def _get_base_dir():
    """获取应用根目录: EXE 所在目录 (打包后) 或脚本所在目录 (开发时)"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(__file__)


def _get_resource_dir():
    """获取资源目录: PyInstaller 临时解压目录 或 脚本所在目录"""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(__file__)


def _apply_windows_taskbar_icon(hwnd, ico_path):
    """Windows 下用 Win32 API 强制设置窗口图标(含任务栏大图标)。

    Qt 的 setWindowIcon 在 Windows 上有时不更新任务栏主图标,
    这里显式设置 WM_SETICON 作为兜底, 确保任务栏显示正确图标。
    """
    if sys.platform != "win32" or not hwnd:
        return
    try:
        user32 = ctypes.windll.user32
        user32.LoadImageW.restype = ctypes.c_void_p
        user32.LoadImageW.argtypes = [
            ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint,
            ctypes.c_int, ctypes.c_int, ctypes.c_uint,
        ]
        user32.SendMessageW.argtypes = [
            ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_void_p,
        ]
        IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
        WM_SETICON, ICON_BIG, ICON_SMALL = 0x0080, 1, 0

        hbig = hsmall = None

        # 1) 优先从 exe 自身图标资源提取(系统原生资源, 兼容性最好)
        if getattr(sys, "frozen", False):
            try:
                shell32 = ctypes.windll.shell32
                shell32.ExtractIconExW.restype = ctypes.c_uint
                shell32.ExtractIconExW.argtypes = [
                    ctypes.c_wchar_p, ctypes.c_int,
                    ctypes.POINTER(ctypes.c_void_p),
                    ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint,
                ]
                big = ctypes.c_void_p()
                small = ctypes.c_void_p()
                shell32.ExtractIconExW(sys.executable, 0, ctypes.byref(big), ctypes.byref(small), 1)
                hbig, hsmall = big.value, small.value
            except Exception:
                hbig = hsmall = None

        # 2) 回退到外部 ico 文件
        if not hbig:
            hbig = user32.LoadImageW(None, ico_path, IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
        if not hsmall:
            hsmall = user32.LoadImageW(None, ico_path, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)

        if hbig:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hbig)
        if hsmall:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hsmall)
    except Exception:
        pass


def _install_chinese_translations(app):
    """让 Qt 自带对话框的按钮和提示显示中文(确定 / 取消 / 是 / 否)。

    Qt 内置文案默认是英文, 不加载翻译文件的话「新建项目」弹窗上就是
    OK / Cancel, 在中文界面里很突兀。找不到翻译文件时静默跳过, 不影响功能。
    """
    from PySide6.QtCore import QTranslator, QLibraryInfo
    dirs = []
    try:
        dirs.append(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
    except Exception:
        pass
    dirs += [
        # 自带一份放 assets 里, 打包后一定能找到, 不依赖 PyInstaller 的 Qt hook
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "anhutoolbox", "assets"),
        os.path.join(_get_resource_dir(), "lib", "anhutoolbox", "assets"),
        os.path.join(_get_base_dir(), "lib", "anhutoolbox", "assets"),
        os.path.join(_get_resource_dir(), "anhutoolbox", "assets"),
        os.path.join(_get_resource_dir(), "PySide6", "translations"),
    ]
    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        tr = QTranslator(app)
        if tr.load("qtbase_zh_CN", d):
            app.installTranslator(tr)
            return True
    return False


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    _install_chinese_translations(app)

    base_dir = _get_base_dir()
    resource_dir = _get_resource_dir()

    # 外置 tools 目录: 直接使用 exe 根目录下的 tools/ 文件夹
    # (exe 未内置 tools 时 ensure_tools 不复制, 仅返回该目录)
    toolbox.ensure_tools(base_dir, resource_dir)

    # 图标从资源目录加载 (只读)
    icon_path = os.path.join(resource_dir, "anhutoolbox.ico")
    icon = None
    if os.path.exists(icon_path):
        icon = QIcon(icon_path)
        app.setWindowIcon(icon)
    window = MainWindow(base_dir)
    if icon is not None:
        window.setWindowIcon(icon)
    # Windows 下显式设置窗口图标, 确保任务栏图标正确
    if os.path.exists(icon_path):
        _apply_windows_taskbar_icon(int(window.winId()), icon_path)
    window.showMaximized()
    # show 之后再强制设置一次, 兜底某些 Windows 版本在窗口显示后重置图标
    if os.path.exists(icon_path):
        QTimer.singleShot(0, lambda: _apply_windows_taskbar_icon(int(window.winId()), icon_path))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
