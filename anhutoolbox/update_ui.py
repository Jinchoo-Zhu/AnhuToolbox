# -*- coding: utf-8 -*-
"""应用内更新提示和下载进度窗口。"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar,
    QPushButton, QVBoxLayout,
)

from .updates import UpdateDownloadWorker, update_cache_dir
from .version import __version__


class UpdateAvailableDialog(QDialog):
    def __init__(self, release, parent=None):
        super().__init__(parent)
        self.release = release
        self.decision = "later"
        self.setWindowTitle("发现新版本")
        self.setMinimumWidth(520)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        title = QLabel("发现新版本 {}".format(release.version))
        title.setFont(QFont("Microsoft YaHei UI", 14, QFont.Weight.DemiBold))
        root.addWidget(title)
        root.addWidget(QLabel(
            "当前版本：V{}\n安装包大小：{:.1f} MB".format(
                __version__, release.size / (1024 * 1024))))
        restart_notice = QLabel(
            "更新过程中程序会暂时关闭；安装完成后会自动重新启动新版本。")
        restart_notice.setWordWrap(True)
        restart_notice.setStyleSheet(
            "QLabel{background:#EAF4FF;color:#005A9E;"
            "border:1px solid #B7D9F5;border-radius:5px;padding:8px 10px;}"
        )
        root.addWidget(restart_notice)

        notes = QPlainTextEdit()
        notes.setReadOnly(True)
        notes.setMaximumHeight(220)
        notes.setPlaceholderText("暂无更新说明")
        notes.setPlainText(release.notes or "暂无更新说明")
        root.addWidget(notes)

        buttons = QHBoxLayout()
        buttons.addStretch()
        if not release.mandatory:
            skip = QPushButton("跳过此版本")
            skip.clicked.connect(lambda: self._choose("skip"))
            buttons.addWidget(skip)
        later = QPushButton("暂不更新")
        later.clicked.connect(lambda: self._choose("later"))
        buttons.addWidget(later)
        update = QPushButton("立即更新并重启")
        update.setDefault(True)
        update.setStyleSheet(
            "QPushButton{background:#0078D4;color:white;border:none;"
            "border-radius:4px;padding:7px 18px;font-weight:600;}"
            "QPushButton:hover{background:#106EBE;}"
        )
        update.clicked.connect(lambda: self._choose("update"))
        buttons.addWidget(update)
        root.addLayout(buttons)

    def _choose(self, decision):
        self.decision = decision
        self.accept() if decision == "update" else self.reject()


class UpdateDownloadDialog(QDialog):
    background_requested = Signal()

    def __init__(self, release, parent=None):
        super().__init__(parent)
        self.release = release
        self.download_path = None
        self.setWindowTitle("下载更新")
        self.setMinimumWidth(480)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        self.status = QLabel("正在下载 Anhu 百宝箱 {}...".format(
            release.version))
        root.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        root.addWidget(self.progress)
        self.detail = QLabel("0.0 / {:.1f} MB".format(
            release.size / (1024 * 1024)))
        self.detail.setAlignment(Qt.AlignmentFlag.AlignRight)
        root.addWidget(self.detail)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.background_button = QPushButton("后台更新")
        self.background_button.setToolTip("隐藏下载窗口，继续在后台下载")
        self.background_button.clicked.connect(self._move_to_background)
        buttons.addWidget(self.background_button)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_button)
        root.addLayout(buttons)

        self.worker = UpdateDownloadWorker(
            release, update_cache_dir(), self)
        self.worker.progress.connect(self._on_progress)
        self.worker.completed.connect(self._on_completed)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_progress(self, received, total):
        total = max(1, int(total))
        self.progress.setValue(min(1000, int(received * 1000 / total)))
        self.detail.setText("{:.1f} / {:.1f} MB".format(
            received / (1024 * 1024), total / (1024 * 1024)))

    def _on_completed(self, path):
        self.download_path = path
        self.status.setText("下载完成，请确认是否立即安装并自动重启...")
        self.progress.setValue(1000)
        self.cancel_button.setEnabled(False)
        self.accept()

    def _on_failed(self, message):
        self.status.setText("下载失败：{}".format(message))
        self.status.setStyleSheet("color:#C42B1C")
        self.background_button.hide()
        self.cancel_button.setText("关闭")
        self.cancel_button.setEnabled(True)
        if self.isHidden() or self.isMinimized():
            self.showNormal()
            self.raise_()
            self.activateWindow()

    def _move_to_background(self):
        self.hide()
        self.background_requested.emit()

    def reject(self):
        if self.worker.isRunning():
            self.worker.cancel()
            if not self.worker.wait(5000):
                self.worker.terminate()
                self.worker.wait(1000)
        super().reject()

    def closeEvent(self, event):
        if self.worker.isRunning():
            self.worker.cancel()
            if not self.worker.wait(5000):
                self.worker.terminate()
                self.worker.wait(1000)
        super().closeEvent(event)
