import base64
import json
import os
import time

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.gossby_scraper import gs_scrape_personalized_data, gs_scrape_single_product
from core.platform_utils import get_asset_path, get_default_dialog_dir, get_user_config_dir, open_path
from core.wanderprints_scraper import Downloader
from qt_gui.common import append_log, log_level_from_text, make_button, make_card, redirect_stdout_to, start_qworker


OUTPUT_PLACEHOLDER = "Chọn thư mục lưu ảnh trước khi chạy!"
_SECRET_KEY = "P0D-CR4WL-S3CR3T-K3Y-2025"


def _xor_encrypt(text: str, key: str) -> str:
    key_bytes = key.encode("utf-8")
    encrypted = bytes(b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(text.encode("utf-8")))
    return base64.b64encode(encrypted).decode("utf-8")


def _xor_decrypt(encoded: str, key: str) -> str:
    try:
        encrypted = base64.b64decode(encoded.encode("utf-8"))
        key_bytes = key.encode("utf-8")
        return bytes(b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(encrypted)).decode("utf-8")
    except Exception:
        return ""


class WanderprintsWorker(QObject):
    log = Signal(str, str)
    progress = Signal(int)
    done = Signal(dict)
    finished = Signal()

    def __init__(self, url, output_dir, do_media, do_swatch, do_desc, gemini_key):
        super().__init__()
        self.url = url
        self.output_dir = output_dir
        self.do_media = do_media
        self.do_swatch = do_swatch
        self.do_desc = do_desc
        self.gemini_key = gemini_key
        self.running = True

    def stop(self):
        self.running = False

    @Slot()
    def run(self):
        start = time.time()
        try:
            key = self.gemini_key if self.do_desc else None
            dl = Downloader(
                log_fn=lambda msg: self.log.emit(msg, log_level_from_text(msg)),
                progress_fn=lambda current, total: self.progress.emit(int(current / total * 100) if total else 0),
                gemini_api_key=key or None,
                is_running_check=lambda: self.running,
                output_root=self.output_dir,
            )
            out_dir = dl.run(self.url, do_media=self.do_media, do_swatch=self.do_swatch)
            elapsed = int(time.time() - start)
            self.done.emit({
                "success": True,
                "ok": dl.total_ok,
                "fail": dl.total_fail,
                "path": out_dir or self.output_dir,
                "elapsed": elapsed,
            })
        except Exception as exc:
            self.log.emit(f"[ERROR] {exc}", "error")
            self.done.emit({"success": False, "error": str(exc), "path": "", "elapsed": 0})
        finally:
            self.finished.emit()


class GossbyWorker(QObject):
    log = Signal(str, str)
    done = Signal(dict)
    finished = Signal()

    def __init__(self, url, output_dir, do_variants, do_layers, do_cliparts, do_desc, gemini_key):
        super().__init__()
        self.url = url
        self.output_dir = output_dir
        self.do_variants = do_variants
        self.do_layers = do_layers
        self.do_cliparts = do_cliparts
        self.do_desc = do_desc
        self.gemini_key = gemini_key
        self.running = True

    def stop(self):
        self.running = False

    def _log(self, msg):
        self.log.emit(str(msg), log_level_from_text(msg))

    @Slot()
    def run(self):
        start = time.time()
        save_path = self.output_dir
        try:
            with redirect_stdout_to(self._log):
                key = self.gemini_key if self.do_desc else None
                if self.do_variants and self.running:
                    save_path = gs_scrape_single_product(self.url, base_dir=self.output_dir, gemini_api_key=key or None) or save_path
                if self.do_layers and self.running:
                    save_path = gs_scrape_personalized_data(
                        self.url,
                        do_cliparts=self.do_cliparts,
                        base_dir=self.output_dir,
                        is_running_check=lambda: self.running,
                    ) or save_path
            elapsed = int(time.time() - start)
            self.done.emit({"success": True, "path": save_path, "elapsed": elapsed})
        except Exception as exc:
            self._log(f"[ERROR] {exc}")
            self.done.emit({"success": False, "error": str(exc), "path": "", "elapsed": 0})
        finally:
            self.finished.emit()


class ProductTab(QWidget):
    def __init__(self, title, key_provider, is_gossby=False):
        super().__init__()
        self.key_provider = key_provider
        self.is_gossby = is_gossby
        self.thread = None
        self.worker = None
        self._build(title)

    def _build(self, title):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 10, 16, 10)
        root.setSpacing(8)

        heading = QLabel(title)
        heading.setStyleSheet("font-size: 14pt; font-weight: 700; color: #000000;")
        root.addWidget(heading)

        card, row = make_card()
        line = QHBoxLayout()
        line.addWidget(QLabel("URL sản phẩm:"))
        self.url_entry = QLineEdit()
        self.url_entry.returnPressed.connect(self.start)
        line.addWidget(self.url_entry, 1)
        self.start_btn = make_button("▶  Tải", "start")
        self.start_btn.clicked.connect(self.start)
        line.addWidget(self.start_btn)
        self.stop_btn = make_button("■  Dừng", "stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        line.addWidget(self.stop_btn)
        row.addLayout(line)
        root.addWidget(card)

        card, options = make_card()
        opt = QHBoxLayout()
        opt.addWidget(QLabel("Dữ liệu:"))
        if self.is_gossby:
            self.var_variants = QCheckBox("Variants (ảnh sản phẩm)")
            self.var_layers = QCheckBox("Layers (ảnh cá nhân hóa)")
            self.var_cliparts = QCheckBox("Mặc định (Cliparts)")
            self.var_cliparts.setChecked(True)
            for box in (self.var_variants, self.var_layers):
                box.setChecked(True)
                opt.addWidget(box)
            opt.addWidget(self.var_cliparts)
        else:
            self.var_media = QCheckBox("Variants (ảnh sản phẩm)")
            self.var_swatch = QCheckBox("Layers (ảnh cá nhân hóa)")
            self.var_media.setChecked(True)
            self.var_swatch.setChecked(True)
            opt.addWidget(self.var_media)
            opt.addWidget(self.var_swatch)
        self.var_desc = QCheckBox("Mô tả mới cho sản phẩm")
        self.var_desc.setEnabled(False)
        opt.addWidget(self.var_desc)
        opt.addStretch(1)
        options.addLayout(opt)
        root.addWidget(card)

        card, folder = make_card()
        frow = QHBoxLayout()
        frow.addWidget(QLabel("Thư mục lưu:"))
        self.folder_entry = QLineEdit()
        self.folder_entry.setPlaceholderText(OUTPUT_PLACEHOLDER)
        frow.addWidget(self.folder_entry, 1)
        pick = make_button("Chọn", "primary")
        pick.clicked.connect(self.browse_folder)
        frow.addWidget(pick)
        folder.addLayout(frow)
        root.addWidget(card)

        self.status_label = QLabel("Sẵn sàng")
        self.status_label.setStyleSheet("color: #16a34a;")
        root.addWidget(self.status_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        root.addWidget(self.progress)

        root.addWidget(QLabel("Log:"))
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        root.addWidget(self.log_box, 1)
        clear = make_button("Xoá log")
        clear.clicked.connect(self.log_box.clear)
        root.addWidget(clear, alignment=Qt.AlignmentFlag.AlignRight)

    def set_has_key(self, has_key):
        self.var_desc.setEnabled(has_key)
        self.var_desc.setChecked(bool(has_key))

    def browse_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu", get_default_dialog_dir())
        if path:
            self.folder_entry.setText(path)

    def _log(self, msg, level="info"):
        append_log(self.log_box, msg, level)

    def _set_running(self, running):
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.status_label.setText("Đang xử lý..." if running else "Sẵn sàng")

    def _validate(self):
        url = self.url_entry.text().strip()
        if not url:
            QMessageBox.warning(self, "Thiếu URL", "Vui lòng nhập URL sản phẩm.")
            return None
        output = self.folder_entry.text().strip()
        if not output:
            QMessageBox.warning(self, "Thiếu thư mục lưu", "Vui lòng chọn thư mục lưu trước khi bắt đầu.")
            return None
        if self.is_gossby:
            if not (self.var_variants.isChecked() or self.var_layers.isChecked()):
                QMessageBox.warning(self, "Lựa chọn", "Chọn ít nhất 1 loại dữ liệu.")
                return None
        else:
            if not (self.var_media.isChecked() or self.var_swatch.isChecked()):
                QMessageBox.warning(self, "Lựa chọn", "Chọn ít nhất 1 loại dữ liệu.")
                return None
        return url, output

    def start(self):
        if self.thread:
            return
        values = self._validate()
        if not values:
            return
        url, output = values
        self.log_box.clear()
        self._set_running(True)
        self.progress.setValue(0)
        if self.is_gossby:
            self.progress.setRange(0, 0)
            self.worker = GossbyWorker(
                url, output,
                self.var_variants.isChecked(),
                self.var_layers.isChecked(),
                self.var_cliparts.isChecked(),
                self.var_desc.isChecked(),
                self.key_provider(),
            )
        else:
            self.progress.setRange(0, 100)
            self.worker = WanderprintsWorker(
                url, output,
                self.var_media.isChecked(),
                self.var_swatch.isChecked(),
                self.var_desc.isChecked(),
                self.key_provider(),
            )
            self.worker.progress.connect(self.progress.setValue)

        self.worker.log.connect(self._log)
        self.worker.done.connect(self._done)
        self.thread, self.worker = start_qworker(self, self.worker, self._cleanup_worker)

    def stop(self):
        if self.worker:
            self.worker.stop()
        self.status_label.setText("Đang dừng...")
        self.stop_btn.setEnabled(False)

    def _cleanup_worker(self):
        self.thread = None
        self.worker = None

    def _done(self, result):
        self._set_running(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(100 if result.get("success") else 0)
        if result.get("success"):
            elapsed = result.get("elapsed", 0)
            mm, ss = divmod(int(elapsed), 60)
            path = result.get("path") or self.folder_entry.text().strip()
            self.status_label.setText(f"Hoàn tất! ({mm:02d}:{ss:02d})")
            if QMessageBox.question(self, "Hoàn thành", f"Đã xong!\nLưu tại:\n{path}\n\nMở thư mục?") == QMessageBox.StandardButton.Yes:
                open_path(path)
        else:
            self.status_label.setText("Có lỗi xảy ra")
            QMessageBox.critical(self, "Lỗi", result.get("error", "Không rõ lỗi"))


class CrawlPage(QWidget):
    def __init__(self):
        super().__init__()
        self.config_file = os.path.join(get_user_config_dir(), "pod_crawl_config.json")
        self._build()
        self._load_key()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(8)

        key_row = QHBoxLayout()
        key_row.addWidget(QLabel("🔑 Gemini API Key:"))
        self.key_entry = QLineEdit()
        self.key_entry.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_entry.editingFinished.connect(self._save_key)
        self.key_entry.textChanged.connect(self._sync_key_state)
        key_row.addWidget(self.key_entry, 1)
        show_btn = make_button("👁")
        show_btn.clicked.connect(self._toggle_key)
        key_row.addWidget(show_btn)
        guide = make_button("📖 Hướng dẫn lấy Gemini API Key", "primary")
        guide.clicked.connect(self._open_guide)
        key_row.addWidget(guide)
        root.addLayout(key_row)

        self.tabs = QTabWidget()
        self.wp_tab = ProductTab("Wanderprints", self.current_key, is_gossby=False)
        self.gs_tab = ProductTab("Gossby", self.current_key, is_gossby=True)
        self.tabs.addTab(self.wp_tab, "Wanderprints")
        self.tabs.addTab(self.gs_tab, "Gossby")
        root.addWidget(self.tabs, 1)

    def current_key(self):
        return self.key_entry.text().strip()

    def _sync_key_state(self):
        has_key = bool(self.current_key())
        self.wp_tab.set_has_key(has_key)
        self.gs_tab.set_has_key(has_key)

    def _toggle_key(self):
        self.key_entry.setEchoMode(
            QLineEdit.EchoMode.Normal
            if self.key_entry.echoMode() == QLineEdit.EchoMode.Password
            else QLineEdit.EchoMode.Password
        )

    def _open_guide(self):
        pdf_path = get_asset_path("guid_get_gemini_key.pdf")
        if os.path.exists(pdf_path):
            open_path(pdf_path)
        else:
            QMessageBox.critical(self, "Lỗi", "Không tìm thấy file hướng dẫn.")

    def _load_key(self):
        try:
            with open(self.config_file, "r", encoding="utf-8") as fh:
                encoded = json.load(fh).get("gemini_key", "").strip()
            if encoded:
                self.key_entry.setText(_xor_decrypt(encoded, _SECRET_KEY))
        except Exception:
            pass
        self._sync_key_state()

    def _save_key(self):
        try:
            encoded = _xor_encrypt(self.current_key(), _SECRET_KEY) if self.current_key() else ""
            with open(self.config_file, "w", encoding="utf-8") as fh:
                json.dump({"gemini_key": encoded}, fh, indent=4)
        except Exception:
            pass
