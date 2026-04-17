import os
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.platform_utils import open_path
from qt_gui.common import append_log, image_extensions, make_button, make_card, make_section, start_qworker


class ResizeWorker(QObject):
    log = Signal(str, str)
    progress = Signal(int)
    stats = Signal(str)
    done = Signal(dict)
    finished = Signal()

    def __init__(self, image_list, source_roots, out_base, size_info, fmt, skip_existing, letterbox):
        super().__init__()
        self.image_list = list(image_list)
        self.source_roots = set(source_roots)
        self.out_base = out_base
        self.size_info = size_info
        self.fmt = fmt
        self.skip_existing = skip_existing
        self.letterbox = letterbox
        self.running = True

    def stop(self):
        self.running = False

    def _log(self, message, level="info"):
        self.log.emit(str(message), level)

    @Slot()
    def run(self):
        total = len(self.image_list)
        done = skipped = errors = 0
        ext_map = {"JPG": "jpg", "PNG": "png", "BMP": "bmp", "TIFF": "tiff"}
        out_ext = ext_map.get(self.fmt, "png")
        pil_fmt_map = {"jpg": "JPEG", "png": "PNG", "bmp": "BMP", "tiff": "TIFF"}

        self._log(f"▶ Bắt đầu xử lý {total} ảnh...", "head")
        self._log(f"  Định dạng xuất: {self.fmt}", "info")

        for img_path, root in self.image_list:
            if not self.running:
                break

            if root:
                rel_path = os.path.relpath(img_path, root)
                rel_dir = os.path.dirname(rel_path)
                out_folder_name = f"Resized_{os.path.basename(root)}"
                out_dir = os.path.join(self.out_base, out_folder_name, rel_dir)
            else:
                rel_path = os.path.basename(img_path)
                out_dir = os.path.join(self.out_base, "Resized_Picked_Files")

            out_path = os.path.join(out_dir, Path(img_path).stem + f".{out_ext}")
            os.makedirs(out_dir, exist_ok=True)

            if self.skip_existing and os.path.exists(out_path):
                skipped += 1
                done += 1
                self._log(f"  ↷ Bỏ qua: {rel_path}", "skip")
                self._update(done, total, skipped, errors)
                continue

            try:
                with Image.open(img_path) as img:
                    ow, oh = img.size
                    if self.size_info[0] == "scale":
                        nw = int(ow * self.size_info[1])
                        nh = int(oh * self.size_info[2])
                    elif self.size_info[0] == "keep":
                        nw, nh = ow, oh
                    else:
                        nw, nh = self.size_info[1], self.size_info[2]

                    if self.size_info[0] == "keep":
                        img_resized = img.copy()
                    elif self.size_info[0] == "custom" and self.letterbox:
                        ratio = min(nw / ow, nh / oh)
                        fit_w = int(ow * ratio)
                        fit_h = int(oh * ratio)
                        img_fitted = img.resize((fit_w, fit_h), Image.LANCZOS)
                        if img_fitted.mode != "RGBA":
                            img_fitted = img_fitted.convert("RGBA")
                        canvas = Image.new("RGBA", (nw, nh), (0, 0, 0, 0))
                        canvas.paste(img_fitted, ((nw - fit_w) // 2, (nh - fit_h) // 2))
                        img_resized = canvas
                    else:
                        img_resized = img.resize((nw, nh), Image.LANCZOS)

                    save_fmt = pil_fmt_map[out_ext]
                    if save_fmt in ("JPEG", "BMP") and img_resized.mode in ("RGBA", "P"):
                        bg = Image.new("RGB", img_resized.size, (255, 255, 255))
                        if img_resized.mode == "P":
                            img_resized = img_resized.convert("RGBA")
                        bg.paste(img_resized, mask=img_resized.split()[3])
                        img_resized = bg

                    img_resized.save(out_path, format=save_fmt, quality=95, dpi=(300, 300))
                    self._log(f"  ✓ {rel_path} ({ow}×{oh} → {nw}×{nh})", "ok")
            except Exception as exc:
                errors += 1
                self._log(f"  ✗ Lỗi: {rel_path} — {exc}", "error")

            done += 1
            self._update(done, total, skipped, errors)

        summary = f"Hoàn tất: {done}/{total} ảnh | Bỏ qua: {skipped} | Lỗi: {errors}"
        self._log(summary, "ok" if errors == 0 else "warn")
        self.done.emit({"done": done, "total": total, "skipped": skipped, "errors": errors, "summary": summary, "path": self.out_base})
        self.finished.emit()

    def _update(self, done, total, skipped, errors):
        self.progress.emit(int(done / total * 100) if total else 0)
        self.stats.emit(f"Đã xử lý {done}/{total} | Bỏ qua {skipped} | Lỗi {errors}")


class ResizePage(QWidget):
    IMAGE_EXTS = image_extensions()

    def __init__(self):
        super().__init__()
        self.source_roots = set()
        self.image_list = []
        self.thread = None
        self.worker = None
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setContentsMargins(20, 10, 20, 10)
        root.setSpacing(8)

        make_section(root, "01", "CHỌN NGUỒN ẢNH")
        card, layout = make_card()
        row = QHBoxLayout()
        self.source_entry = QLineEdit("Chưa chọn nguồn ảnh")
        self.source_entry.setReadOnly(True)
        row.addWidget(self.source_entry, 1)
        folder_btn = make_button("Thư mục", "primary", icon_name="folder.svg")
        folder_btn.clicked.connect(self.browse_source_folder)
        file_btn = make_button("📄 File(s)", "primary")
        file_btn.clicked.connect(self.browse_source_files)
        clear_btn = make_button("🗑 Xóa")
        clear_btn.clicked.connect(self.clear_selection)
        row.addWidget(folder_btn)
        row.addWidget(file_btn)
        row.addWidget(clear_btn)
        layout.addLayout(row)
        self.tree_label = QLabel("→ Chưa chọn thư mục")
        self.tree_label.setWordWrap(True)
        layout.addWidget(self.tree_label)
        root.addWidget(card)

        make_section(root, "02", "THƯ MỤC XUẤT KẾT QUẢ")
        card, layout = make_card()
        row = QHBoxLayout()
        self.output_entry = QLineEdit()
        row.addWidget(self.output_entry, 1)
        out_btn = make_button("Chọn thư mục", "primary", icon_name="folder.svg")
        out_btn.clicked.connect(self.browse_output)
        row.addWidget(out_btn)
        layout.addLayout(row)
        root.addWidget(card)

        make_section(root, "03", "KÍCH THƯỚC ẢNH")
        card, layout = make_card()
        mode_row = QHBoxLayout()
        self.mode_group = QButtonGroup(self)
        self.mode_buttons = {}
        for value, text in [("preset", "Nhân theo tỉ lệ (×)"), ("custom", "Nhập kích thước cụ thể"), ("keep", "Giữ nguyên kích thước")]:
            btn = QRadioButton(text)
            self.mode_group.addButton(btn)
            self.mode_buttons[value] = btn
            mode_row.addWidget(btn)
        self.mode_buttons["preset"].setChecked(True)
        self.mode_group.buttonClicked.connect(self.toggle_scale_mode)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        self.preset_row = QWidget()
        prow = QHBoxLayout(self.preset_row)
        prow.setContentsMargins(0, 0, 0, 0)
        prow.addWidget(QLabel("Chọn tỉ lệ:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["1", "1.5", "2", "2.5", "3", "4", "5"])
        self.preset_combo.setCurrentText("2")
        self.preset_combo.currentTextChanged.connect(self.select_preset)
        prow.addWidget(self.preset_combo)
        prow.addWidget(QLabel("hoặc nhập số:"))
        self.preset_entry = QLineEdit("2")
        self.preset_entry.setMaximumWidth(90)
        prow.addWidget(self.preset_entry)
        prow.addStretch(1)
        layout.addWidget(self.preset_row)

        self.custom_row = QWidget()
        crow = QHBoxLayout(self.custom_row)
        crow.setContentsMargins(0, 0, 0, 0)
        crow.addWidget(QLabel("Chiều rộng (px):"))
        self.custom_w = QLineEdit("2400")
        self.custom_w.setMaximumWidth(100)
        crow.addWidget(self.custom_w)
        crow.addWidget(QLabel("×"))
        crow.addWidget(QLabel("Chiều cao (px):"))
        self.custom_h = QLineEdit("2400")
        self.custom_h.setMaximumWidth(100)
        crow.addWidget(self.custom_h)
        self.letterbox = QCheckBox("Giữ tỷ lệ gốc — không kéo dãn")
        self.letterbox.setChecked(True)
        crow.addWidget(self.letterbox)
        crow.addStretch(1)
        layout.addWidget(self.custom_row)
        self.size_preview = QLabel("")
        layout.addWidget(self.size_preview)
        root.addWidget(card)

        make_section(root, "04", "ĐỊNH DẠNG ẢNH XUẤT")
        card, layout = make_card()
        fmt_row = QHBoxLayout()
        fmt_row.addWidget(QLabel("Xuất tất cả ảnh thành:"))
        self.format_group = QButtonGroup(self)
        self.format_buttons = {}
        for fmt in ["PNG", "JPG", "BMP", "TIFF"]:
            btn = QRadioButton(fmt)
            self.format_group.addButton(btn)
            self.format_buttons[fmt] = btn
            fmt_row.addWidget(btn)
        self.format_buttons["PNG"].setChecked(True)
        fmt_row.addStretch(1)
        layout.addLayout(fmt_row)
        self.skip_existing = QCheckBox("Bỏ qua ảnh đã scale (tránh làm lại)")
        self.skip_existing.setChecked(True)
        layout.addWidget(self.skip_existing)
        root.addWidget(card)

        make_section(root, "05", "NHẬT KÝ TIẾN TRÌNH")
        card, layout = make_card()
        self.stats_label = QLabel("Sẵn sàng")
        layout.addWidget(self.stats_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        layout.addWidget(self.log_box)
        root.addWidget(card)

        buttons = QHBoxLayout()
        self.start_btn = make_button("▶  BẮT ĐẦU SCALE", "start")
        self.start_btn.clicked.connect(self.start)
        self.stop_btn = make_button("■  DỪNG", "stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        clear_log = make_button("🗑  XÓA LOG")
        clear_log.clicked.connect(self.log_box.clear)
        buttons.addWidget(self.start_btn)
        buttons.addWidget(self.stop_btn)
        buttons.addStretch(1)
        buttons.addWidget(clear_log)
        root.addLayout(buttons)
        root.addStretch(1)
        self.toggle_scale_mode()

    def current_mode(self):
        for key, btn in self.mode_buttons.items():
            if btn.isChecked():
                return key
        return "preset"

    def current_format(self):
        for key, btn in self.format_buttons.items():
            if btn.isChecked():
                return key
        return "PNG"

    def toggle_scale_mode(self, *_):
        mode = self.current_mode()
        self.preset_row.setVisible(mode == "preset")
        self.custom_row.setVisible(mode == "custom")
        if mode == "custom":
            self.size_preview.setText(f"→ Xuất ra: {self.custom_w.text()} × {self.custom_h.text()} px")
        elif mode == "keep":
            self.size_preview.setText("→ Xuất ra: Giữ nguyên Pixel (chỉ tăng DPI)")
        else:
            self.size_preview.setText("")

    def select_preset(self, value):
        self.preset_entry.setText(value)

    def browse_source_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục nguồn")
        if folder:
            self.scan_folder(folder)

    def browse_source_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Chọn File Ảnh", "", "Image files (*.png *.jpg *.jpeg *.webp *.bmp *.tiff *.tif *.gif)")
        if files:
            for file_path in files:
                self.image_list.append((file_path, None))
            self.update_selection_display()
            self._log(f"➕ Thêm {len(files)} file lẻ.", "info")

    def browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục xuất")
        if folder:
            self.output_entry.setText(folder)

    def clear_selection(self):
        self.source_roots.clear()
        self.image_list.clear()
        self.update_selection_display()
        self._log("Đã xoá toàn bộ danh sách nguồn.", "warn")

    def scan_folder(self, folder):
        if folder in self.source_roots:
            self._log(f"Thư mục này đã có trong danh sách: {folder}", "warn")
            return
        self.source_roots.add(folder)
        count = 0
        for root, _dirs, files in os.walk(folder):
            for name in sorted(files):
                if Path(name).suffix.lower() in self.IMAGE_EXTS:
                    self.image_list.append((os.path.join(root, name), folder))
                    count += 1
        self.update_selection_display()
        self._log(f"➕ Thêm thư mục: {os.path.basename(folder)} ({count} ảnh)", "info")

    def update_selection_display(self):
        total = len(self.image_list)
        folder_count = len(self.source_roots)
        file_count = len([item for item in self.image_list if item[1] is None])
        summary = f"Đã chọn: {folder_count} thư mục, {file_count} file lẻ (Tổng {total} ảnh)"
        self.source_entry.setText(summary if total else "Chưa chọn nguồn ảnh")
        lines = [summary] if total else ["→ Chưa chọn thư mục"]
        for root in sorted(self.source_roots)[:10]:
            count = len([item for item in self.image_list if item[1] == root])
            lines.append(f"📁 {os.path.basename(root)} ({count} ảnh)")
        if file_count:
            lines.append(f"📄 {file_count} ảnh chọn lẻ")
        self.tree_label.setText("\n".join(lines))

    def start(self):
        if self.thread:
            return
        if not self.image_list:
            QMessageBox.warning(self, "Không tìm thấy ảnh", "Vui lòng chọn nguồn ảnh hợp lệ.")
            return
        out_base = self.output_entry.text().strip()
        if not out_base:
            QMessageBox.warning(self, "Thiếu thư mục xuất", "Vui lòng chọn thư mục lưu ảnh trước khi bắt đầu.")
            return
        try:
            if self.current_mode() == "custom":
                size_info = ("custom", int(self.custom_w.text()), int(self.custom_h.text()))
            elif self.current_mode() == "keep":
                size_info = ("keep", 1, 1)
            else:
                scale = float(self.preset_entry.text())
                if scale <= 0:
                    raise ValueError
                size_info = ("scale", min(scale, 10), min(scale, 10))
        except ValueError:
            QMessageBox.warning(self, "Lỗi", "Kích thước hoặc tỉ lệ không hợp lệ.")
            return

        self.log_box.clear()
        self.progress.setValue(0)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.worker = ResizeWorker(
            self.image_list,
            self.source_roots,
            out_base,
            size_info,
            self.current_format(),
            self.skip_existing.isChecked(),
            self.letterbox.isChecked(),
        )
        self.worker.log.connect(self._log)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.stats.connect(self.stats_label.setText)
        self.worker.done.connect(self.done)
        self.thread, self.worker = start_qworker(self, self.worker, self.cleanup_worker)

    def stop(self):
        if self.worker:
            self.worker.stop()
        self.stop_btn.setEnabled(False)
        self._log("Đã yêu cầu dừng...", "warn")

    def cleanup_worker(self):
        self.thread = None
        self.worker = None

    def done(self, result):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress.setValue(100)
        self.stats_label.setText(result.get("summary", "Hoàn tất"))
        if QMessageBox.question(self, "Hoàn thành", f"{result.get('summary')}\n\nMở thư mục kết quả?") == QMessageBox.StandardButton.Yes:
            open_path(result.get("path"))

    def _log(self, message, level="info"):
        append_log(self.log_box, message, level)
