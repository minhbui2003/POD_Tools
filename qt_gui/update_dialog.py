import webbrowser

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
)

from core import updater
from qt_gui.common import make_button


class UpdateDialog(QDialog):
    progress_signal = Signal(int)
    success_signal = Signal(str)
    error_signal = Signal(str)

    def __init__(self, parent, new_version, release_notes, download_url, sha256):
        super().__init__(parent)
        self.download_url = download_url
        self.sha256 = sha256
        self.is_manual_update = updater.is_macos()
        self.setWindowTitle("Phát hiện bản cập nhật mới")
        self.setMinimumWidth(460)
        self._build(new_version, release_notes)
        self.progress_signal.connect(self.on_progress)
        self.success_signal.connect(self.on_success)
        self.error_signal.connect(self.on_error)

    def _build(self, new_version, release_notes):
        root = QVBoxLayout(self)
        root.setSpacing(10)
        title = QLabel(f"Phiên bản mới: v{new_version} đã sẵn sàng!")
        title.setStyleSheet("font-size: 13pt; font-weight: 700;")
        root.addWidget(title)

        self.notes = QPlainTextEdit()
        self.notes.setPlainText(release_notes or "")
        self.notes.setReadOnly(True)
        self.notes.setFixedHeight(120)
        root.addWidget(self.notes)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.hide()
        root.addWidget(self.progress)

        self.status = QLabel("")
        root.addWidget(self.status)

        row = QHBoxLayout()
        self.update_btn = make_button("Tải bản macOS" if self.is_manual_update else "Cập nhật ngay", "primary")
        self.update_btn.clicked.connect(self.start_update)
        self.cancel_btn = make_button("Nhắc tôi sau")
        self.cancel_btn.clicked.connect(self.reject)
        row.addWidget(self.update_btn)
        row.addWidget(self.cancel_btn)
        root.addLayout(row)

    def on_progress(self, percent):
        self.progress.show()
        if percent == -1:
            self.progress.setRange(0, 0)
            self.status.setText("Đang kiểm tra checksum...")
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(percent)
            self.status.setText(f"Đang tải: {percent}%")

    def on_success(self, script_path):
        self.status.setText("Hoàn tất chuẩn bị. Ứng dụng sẽ khởi động lại...")
        updater.execute_updater_and_exit(script_path)

    def on_error(self, message):
        self.progress.hide()
        self.update_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        self.status.setText("")
        QMessageBox.critical(self, "Cập nhật thất bại", message)

    def start_update(self):
        if self.is_manual_update:
            webbrowser.open(self.download_url)
            QMessageBox.information(
                self,
                "Cập nhật macOS",
                "File cập nhật macOS đã mở trong trình duyệt.\n"
                "Hãy tải file zip, thoát app hiện tại, giải nén và thay bằng bản mới.",
            )
            self.accept()
            return

        self.update_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.progress.show()
        self.status.setText("Bắt đầu tải...")
        updater.download_and_install_update(
            self.download_url,
            self.sha256,
            self.progress_signal.emit,
            self.success_signal.emit,
            self.error_signal.emit,
        )

