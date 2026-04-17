import os
import sys
from contextlib import contextmanager

from PySide6.QtCore import QObject, QThread, Qt
from PySide6.QtGui import QTextCharFormat, QColor, QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from qt_gui import styles


def make_button(text, kind="secondary"):
    button = QPushButton(text)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if kind == "start":
        button.setProperty("startButton", True)
    elif kind == "primary":
        button.setProperty("primaryButton", True)
    elif kind == "stop":
        button.setProperty("stopButton", True)
    return button


def make_card():
    card = QFrame()
    card.setProperty("card", True)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(8)
    return card, layout


def make_section(parent_layout, number, title):
    header = QWidget()
    row = QHBoxLayout(header)
    row.setContentsMargins(0, 10, 0, 0)
    row.setSpacing(8)

    num = QLabel(number)
    num.setStyleSheet(f"font-weight: 700; color: {styles.ACCENT}; font-size: 12pt;")
    lbl = QLabel(title)
    lbl.setStyleSheet("font-weight: 700; color: #000000; font-size: 12pt;")
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setStyleSheet(f"color: {styles.PANEL_BORDER}; background: {styles.PANEL_BORDER};")
    line.setFixedHeight(1)

    row.addWidget(num)
    row.addWidget(lbl)
    row.addWidget(line, 1)
    parent_layout.addWidget(header)


def append_log(log_widget, message, level="info"):
    colors = {
        "ok": "#16a34a",
        "warn": "#d97706",
        "error": "#dc2626",
        "skip": "#64748b",
        "head": "#355C8A",
        "info": "#000000",
    }
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(colors.get(level, colors["info"])))
    cursor = log_widget.textCursor()
    cursor.movePosition(QTextCursor.End)
    cursor.insertText(str(message) + "\n", fmt)
    log_widget.setTextCursor(cursor)
    log_widget.ensureCursorVisible()


def log_level_from_text(message):
    text = str(message)
    lower = text.lower()
    if "error" in lower or "fail" in lower or "lỗi" in lower or "✗" in text:
        return "error"
    if "skip" in lower or "bỏ qua" in lower:
        return "skip"
    if "warn" in lower or "!" in text:
        return "warn"
    if "downloaded" in lower or "complete" in lower or "hoàn tất" in lower or "✓" in text:
        return "ok"
    if text.startswith("=") or text.startswith("---") or text.startswith("["):
        return "head"
    return "info"


class StreamRedirector:
    def __init__(self, log_fn):
        self.log_fn = log_fn

    def write(self, text):
        for line in str(text).splitlines():
            line = line.rstrip()
            if line:
                self.log_fn(line)

    def flush(self):
        pass


@contextmanager
def redirect_stdout_to(log_fn):
    old_stdout, old_stderr = sys.stdout, sys.stderr
    redirector = StreamRedirector(log_fn)
    sys.stdout = redirector
    sys.stderr = redirector
    try:
        yield
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr


def start_qworker(parent, worker, on_cleanup):
    thread = QThread(parent)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.finished.connect(on_cleanup)
    thread.start()
    return thread, worker


def image_extensions():
    return {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif", ".gif"}


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path
