"""
POD Resize Tool
Yêu cầu: pip install Pillow
Chạy: python POD_Resize.py
"""

import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from datetime import datetime
from core.platform_utils import open_path

try:
    from PIL import Image, ImageTk
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "Pillow"])
    from PIL import Image, ImageTk


# ─────────────────────────────────────────────
#  Màu sắc & font (dark industrial theme)
# ─────────────────────────────────────────────
BG        = "#f5f7fa"
BG2       = "#FFFFFF"
BG3       = "#EAF0F6"
ACCENT    = "#355C8A"
ACCENT2   = "#355C8A"
BUTTON_PRIMARY_BG = "#DCEEFF"
BUTTON_PRIMARY_BORDER = "#9FC3E8"
BUTTON_SECONDARY_BG = "#EAF0F6"
BUTTON_SECONDARY_BORDER = "#C7D0DB"
BUTTON_STOP_BG = "#FDE2E2"
BUTTON_STOP_BORDER = "#E7B3B3"
BUTTON_START_BG = "#DFF4EA"
BUTTON_START_BORDER = "#A9D8BD"
SUCCESS   = "#16a34a"
WARNING   = "#d97706"
ERROR     = "#dc2626"
TEXT      = "#000000"
TEXT2     = "#000000"
BORDER    = "#D6DCE5"

FONT_TITLE  = ("Segoe UI", 14, "bold")
FONT_LABEL  = ("Segoe UI", 10)
FONT_SMALL  = ("Segoe UI", 9)
FONT_LOG    = ("Consolas", 9)


def _button_style(bg, border):
    return {
        "bg": bg,
        "fg": "#000000",
        "disabledforeground": "#000000",
        "activebackground": bg,
        "activeforeground": "#000000",
        "relief": "solid",
        "bd": 1,
        "highlightthickness": 1,
        "highlightbackground": border,
        "highlightcolor": border,
    }


class ResizeTab(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)

        # State
        self.source_folder   = tk.StringVar(value="Chưa chọn nguồn ảnh")
        self.output_folder   = tk.StringVar()
        self.scale_mode      = tk.StringVar(value="preset")   # preset | custom
        self.preset_scale    = tk.StringVar(value="2")
        self.custom_w        = tk.StringVar(value="2400")
        self.custom_h        = tk.StringVar(value="2400")
        self.output_format   = tk.StringVar(value="PNG")
        self.skip_existing   = tk.BooleanVar(value=True)
        self.letterbox       = tk.BooleanVar(value=True)

        self.folder_tree     = {}   # rel_path -> info
        self.image_list      = []   # list of (abs_path, root_folder_or_none)
        self.source_roots    = set() # set of root folders selected
        self.is_running      = False

        self._build_ui()

    # ─────────────────────────────────────────
    #  UI BUILD
    # ─────────────────────────────────────────
    def _build_ui(self):


        # Scrollable main content
        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True, padx=20, pady=10)

        canvas   = tk.Canvas(outer, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        self.scroll_frame = tk.Frame(canvas, bg=BG)

        self.scroll_frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def _on_mousewheel(event):
            if sys.platform == "darwin":
                step = -1 if event.delta > 0 else 1
            else:
                step = -1 * int(event.delta / 120) if event.delta else 0
            if step:
                canvas.yview_scroll(step, "units")

        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        f = self.scroll_frame  # shorthand

        # ── 1. CHỌN THƯ MỤC NGUỒN ──────────────────────
        self._section(f, "01", "CHỌN NGUỒN ẢNH")
        row1 = self._card(f)
        self._path_picker_source(row1, self.source_folder,
                                 "Thư mục hoặc File gốc:")

        # Tree preview
        tree_frame = tk.Frame(row1, bg=BG2)
        tree_frame.pack(fill="x", padx=4, pady=(4, 8))

        self.tree_label = tk.Label(tree_frame, text="→ Chưa chọn thư mục",
                                   font=FONT_SMALL, fg=TEXT2, bg=BG2, anchor="w",
                                   justify="left", wraplength=680)
        self.tree_label.pack(fill="x", padx=10, pady=6)

        # ── 2. THƯ MỤC XUẤT ────────────────────────────
        self._section(f, "02", "THƯ MỤC XUẤT KẾT QUẢ")
        row2 = self._card(f)
        self._path_picker(row2, self.output_folder,
                          "Thư mục lưu ảnh đã scale (để trống = nằm cùng vị trí chứa tool):",
                          self._browse_output)

        # ── 3. KÍCH THƯỚC ──────────────────────────────
        self._section(f, "03", "KÍCH THƯỚC ẢNH")
        row3 = self._card(f)

        mode_frame = tk.Frame(row3, bg=BG2)
        mode_frame.pack(fill="x", padx=4, pady=(4, 0))

        # Radio buttons
        for val, lbl in [("preset", "Nhân theo tỉ lệ (×)"), ("custom", "Nhập kích thước cụ thể"), ("keep", "Giữ nguyên kích thước")]:
            rb = tk.Radiobutton(mode_frame, text=lbl, variable=self.scale_mode, value=val,
                                font=FONT_LABEL, fg=TEXT, bg=BG2,
                                selectcolor=BG3, activebackground=BG2,
                                command=self._toggle_scale_mode)
            rb.pack(side="left", padx=(10, 5), pady=6)

        # Preset row
        self.preset_row = tk.Frame(row3, bg=BG2)
        self.preset_row.pack(fill="x", padx=4, pady=4)

        tk.Label(self.preset_row, text="Chọn tỉ lệ:", font=FONT_LABEL,
                 fg=TEXT2, bg=BG2).pack(side="left", padx=(10, 8))

        presets = ["1", "1.5", "2", "2.5", "3", "4", "5"]
        self.preset_combo = ttk.Combobox(self.preset_row, values=presets, state="readonly", width=5, font=FONT_LABEL)
        self.preset_combo.pack(side="left", padx=4)
        
        def _on_combo_select(e):
            self._select_preset(self.preset_combo.get())
            
        self.preset_combo.bind("<<ComboboxSelected>>", _on_combo_select)

        tk.Label(self.preset_row, text="hoặc nhập số (tối đa x10):", font=FONT_LABEL,
                 fg=TEXT2, bg=BG2).pack(side="left", padx=(20, 8))
        
        self.preset_entry = tk.Entry(self.preset_row, textvariable=self.preset_scale, font=FONT_LABEL,
                                     width=8, bg=BG3, fg=TEXT,
                                     insertbackground=TEXT, relief="flat",
                                     highlightthickness=1, highlightbackground=BORDER,
                                     highlightcolor=ACCENT, justify="center")
        self.preset_entry.pack(side="left", ipady=4)
        
        def _sync_scale(*args):
            val = self.preset_scale.get()
            if val in self.preset_combo["values"]:
                self.preset_combo.set(val)
            else:
                try:
                    self.preset_combo.set("")
                except:
                    pass
                
        self.preset_scale.trace_add("write", _sync_scale)

        # Custom row
        self.custom_row = tk.Frame(row3, bg=BG2)
        # (packed/hidden by toggle)
        tk.Label(self.custom_row, text="Chiều rộng (px):", font=FONT_LABEL,
                 fg=TEXT2, bg=BG2).pack(side="left", padx=(10, 4))
        self._entry(self.custom_row, self.custom_w, width=8)
        tk.Label(self.custom_row, text="×", font=("Consolas", 14, "bold"),
                 fg=ACCENT, bg=BG2).pack(side="left", padx=6)
        tk.Label(self.custom_row, text="Chiều cao (px):", font=FONT_LABEL,
                 fg=TEXT2, bg=BG2).pack(side="left", padx=(0, 4))
        self._entry(self.custom_row, self.custom_h, width=8)

        # Letterbox checkbox row (inside custom_row container)
        self.letterbox_row = tk.Frame(row3, bg=BG2)
        tk.Checkbutton(self.letterbox_row,
                       text="Giữ tỷ lệ gốc — không kéo dãn",
                       variable=self.letterbox,
                       font=FONT_LABEL, fg=ACCENT2, bg=BG2,
                       selectcolor=BG3, activebackground=BG2).pack(side="left", padx=10, pady=(0, 6))

        # Preview label
        self.size_preview = tk.Label(row3, text="",
                                     font=FONT_SMALL, fg=ACCENT, bg=BG2)
        self.size_preview.pack(pady=(0, 8))
        self._select_preset("2")  # gọi sau khi size_preview đã được tạo
        self.source_folder.trace_add("write", lambda *_: self._update_size_preview())
        self.custom_w.trace_add("write", lambda *_: self._update_size_preview())
        self.custom_h.trace_add("write", lambda *_: self._update_size_preview())

        # ── 4. ĐỊNH DẠNG XUẤT ──────────────────────────
        self._section(f, "04", "ĐỊNH DẠNG ẢNH XUẤT")
        row4 = self._card(f)
        fmt_frame = tk.Frame(row4, bg=BG2)
        fmt_frame.pack(fill="x", padx=4, pady=8)

        tk.Label(fmt_frame, text="Xuất tất cả ảnh thành:", font=FONT_LABEL,
                 fg=TEXT2, bg=BG2).pack(side="left", padx=(10, 8))

        # Đã loại bỏ WEBP vì định dạng này không hỗ trợ lưu siêu dữ liệu 300 DPI chuẩn bằng thư viện Pillow.
        formats = ["PNG", "JPG", "BMP", "TIFF"]
        for fmt in formats:
            rb = tk.Radiobutton(fmt_frame, text=fmt, variable=self.output_format, value=fmt,
                                font=FONT_LABEL, fg=TEXT, bg=BG2,
                                selectcolor=BG3, activebackground=BG2)
            rb.pack(side="left", padx=(0, 12))

        # Skip existing
        skip_frame = tk.Frame(row4, bg=BG2)
        skip_frame.pack(fill="x", padx=14, pady=(0, 8))
        tk.Checkbutton(skip_frame, text="Bỏ qua ảnh đã scale (tránh làm lại)",
                       variable=self.skip_existing,
                       font=FONT_SMALL, fg=TEXT2, bg=BG2,
                       selectcolor=BG3, activebackground=BG2).pack(side="left")

        # ── 5. LOG ─────────────────────────────────────
        self._section(f, "05", "NHẬT KÝ TIẾN TRÌNH")
        log_card = self._card(f)

        # Stats bar
        self.stats_bar = tk.Label(log_card, text="Sẵn sàng",
                                  font=FONT_SMALL, fg=ACCENT, bg=BG3,
                                  anchor="w", pady=4, padx=10)
        self.stats_bar.pack(fill="x", padx=4, pady=(4, 2))

        # Progress bar
        self.progress_var = tk.DoubleVar(value=0)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("pod.Horizontal.TProgressbar",
                        troughcolor=BG3, background=ACCENT,
                        bordercolor=BG3, lightcolor=ACCENT, darkcolor=ACCENT2)
        self.progress = ttk.Progressbar(log_card, variable=self.progress_var,
                                        style="pod.Horizontal.TProgressbar",
                                        maximum=100)
        self.progress.pack(fill="x", padx=4, pady=2)

        # Log text box
        log_inner = tk.Frame(log_card, bg=BG3)
        log_inner.pack(fill="both", expand=False, padx=4, pady=4)

        self.log_text = tk.Text(log_inner, height=12, font=FONT_LOG,
                                bg=BG3, fg=TEXT, insertbackground=TEXT,
                                relief="flat", wrap="word",
                                state="disabled")
        log_scroll = ttk.Scrollbar(log_inner, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        log_scroll.pack(side="right", fill="y", pady=6)

        # Tag colours
        self.log_text.tag_config("info",    foreground=TEXT)
        self.log_text.tag_config("ok",      foreground=SUCCESS)
        self.log_text.tag_config("warn",    foreground=WARNING)
        self.log_text.tag_config("err",     foreground=ERROR)
        self.log_text.tag_config("head",    foreground=ACCENT)
        self.log_text.tag_config("skip",    foreground=TEXT2)

        # ── 6. BUTTONS ─────────────────────────────────
        btn_frame = tk.Frame(self.scroll_frame, bg=BG, pady=12)
        btn_frame.pack(fill="x")

        self.btn_start = tk.Button(btn_frame, text="▶  BẮT ĐẦU SCALE",
                                   font=("Segoe UI", 11, "bold"),
                                   padx=24, pady=10, cursor="hand2",
                                   command=self._start,
                                   **_button_style(BUTTON_START_BG, BUTTON_START_BORDER))
        self.btn_start.pack(side="left", padx=(4, 8))

        self.btn_stop = tk.Button(btn_frame, text="■  DỪNG",
                                  font=("Segoe UI", 11, "bold"),
                                  padx=16, pady=10, cursor="hand2",
                                  state="disabled",
                                  command=self._stop,
                                  **_button_style(BUTTON_STOP_BG, BUTTON_STOP_BORDER))
        self.btn_stop.pack(side="left", padx=4)

        tk.Button(btn_frame, text="🗑  XÓA LOG",
                  font=FONT_SMALL,
                  padx=10, pady=10, cursor="hand2",
                  command=self._clear_log,
                  **_button_style(BUTTON_SECONDARY_BG, BUTTON_SECONDARY_BORDER)).pack(side="right", padx=4)

        self._toggle_scale_mode()

    # ─────────────────────────────────────────
    #  UI HELPERS
    # ─────────────────────────────────────────
    def _section(self, parent, num, title):
        f = tk.Frame(parent, bg=BG)
        f.pack(fill="x", pady=(12, 2))
        # Số đề mục to và đậm
        tk.Label(f, text=f"  {num}", font=("Segoe UI", 12, "bold"),
                 fg=ACCENT, bg=BG).pack(side="left")
        # Chữ tiêu đề to bằng số
        tk.Label(f, text=f"  {title}", font=("Segoe UI", 12, "bold"),
                 fg=TEXT, bg=BG).pack(side="left")
        tk.Frame(f, bg=BORDER, height=1).pack(side="left", fill="x", expand=True, padx=(8, 0))

    def _card(self, parent):
        card = tk.Frame(parent, bg=BG2, padx=2, pady=2,
                        highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="x", pady=2)
        return card

    def _path_picker(self, parent, var, label, cmd):
        tk.Label(parent, text=label, font=FONT_SMALL, fg=TEXT2,
                 bg=BG2, anchor="w").pack(fill="x", padx=10, pady=(8, 2))
        row = tk.Frame(parent, bg=BG2)
        row.pack(fill="x", padx=10, pady=(0, 8))
        entry = tk.Entry(row, textvariable=var, font=FONT_SMALL,
                         bg=BG3, fg=TEXT, insertbackground=TEXT,
                         relief="flat", highlightthickness=1,
                         highlightbackground=BORDER,
                         highlightcolor=ACCENT)
        entry.pack(side="left", fill="x", expand=True, ipady=5, padx=(0, 8))
        tk.Button(row, text="Chọn thư mục", font=FONT_SMALL,
                  padx=10, pady=4, cursor="hand2",
                  command=cmd,
                  **_button_style(BUTTON_PRIMARY_BG, BUTTON_PRIMARY_BORDER)).pack(side="right")

    def _path_picker_source(self, parent, var, label):
        tk.Label(parent, text=label, font=FONT_SMALL, fg=TEXT2,
                 bg=BG2, anchor="w").pack(fill="x", padx=10, pady=(8, 2))
        row = tk.Frame(parent, bg=BG2)
        row.pack(fill="x", padx=10, pady=(0, 8))
        entry = tk.Entry(row, textvariable=var, font=FONT_SMALL,
                         bg=BG3, fg=TEXT, insertbackground=TEXT,
                         relief="flat", highlightthickness=1,
                         highlightbackground=BORDER,
                         highlightcolor=ACCENT, state="readonly")
        entry.pack(side="left", fill="x", expand=True, ipady=5, padx=(0, 8))
        
        tk.Button(row, text="📁 Thư mục", font=FONT_SMALL,
                  padx=10, pady=4, cursor="hand2",
                  command=self._browse_source,
                  **_button_style(BUTTON_PRIMARY_BG, BUTTON_PRIMARY_BORDER)).pack(side="right", padx=(4,0))
        tk.Button(row, text="📄 File(s)", font=FONT_SMALL,
                  padx=10, pady=4, cursor="hand2",
                  command=self._browse_source_files,
                  **_button_style(BUTTON_PRIMARY_BG, BUTTON_PRIMARY_BORDER)).pack(side="right", padx=(4,0))
        tk.Button(row, text="🗑 Xóa", font=FONT_SMALL,
                  padx=10, pady=4, cursor="hand2",
                  command=self._clear_selection,
                  **_button_style(BUTTON_SECONDARY_BG, BUTTON_SECONDARY_BORDER)).pack(side="right")

    def _entry(self, parent, var, width=10):
        e = tk.Entry(parent, textvariable=var, font=FONT_LABEL,
                     width=width, bg=BG3, fg=TEXT,
                     insertbackground=TEXT, relief="flat",
                     highlightthickness=1, highlightbackground=BORDER,
                     highlightcolor=ACCENT, justify="center")
        e.pack(side="left", ipady=4)
        return e

    # ─────────────────────────────────────────
    #  ACTIONS
    # ─────────────────────────────────────────
    def _browse_source(self):
        folder = filedialog.askdirectory(parent=self, title="Chọn thư mục nguồn")
        if folder:
            self._scan_folder(folder)

    def _browse_source_files(self):
        files = filedialog.askopenfilenames(parent=self, title="Chọn File Ảnh",
                                            filetypes=[("Image files", "*.png *.jpg *.jpeg *.webp *.bmp *.tiff")])
        if files:
            self._scan_files(files)

    def _clear_selection(self):
        self.image_list = []
        self.source_roots = set()
        self.folder_tree = {}
        self.source_folder.set("Chưa chọn nguồn ảnh")
        self.tree_label.configure(text="→ Danh sách đã được làm sạch", fg=TEXT2)
        self._log("🗑 Đã xóa toàn bộ danh sách nguồn.", "warn")

    def _browse_output(self):
        folder = filedialog.askdirectory(parent=self, title="Chọn thư mục xuất")
        if folder:
            self.output_folder.set(folder)

    def _toggle_scale_mode(self):
        if self.scale_mode.get() == "preset":
            self.preset_row.pack(fill="x", padx=4, pady=4)
            self.custom_row.pack_forget()
            self.letterbox_row.pack_forget()
        elif self.scale_mode.get() == "custom":
            self.custom_row.pack(fill="x", padx=4, pady=8)
            self.letterbox_row.pack(fill="x", padx=4, pady=(0, 4))
            self.preset_row.pack_forget()
        else:
            self.preset_row.pack_forget()
            self.custom_row.pack_forget()
            self.letterbox_row.pack_forget()
        self._update_size_preview()

    def _select_preset(self, val):
        self.preset_scale.set(val)
        self._update_size_preview()

    def _update_size_preview(self, *_):
        if self.scale_mode.get() == "custom":
            try:
                w = int(self.custom_w.get())
                h = int(self.custom_h.get())
                self.size_preview.configure(text=f"→ Xuất ra: {w} × {h} px")
            except ValueError:
                self.size_preview.configure(text="")
        elif self.scale_mode.get() == "keep":
            self.size_preview.configure(text="→ Xuất ra: Giữ nguyên Pixel (chỉ tăng DPI)")
        else:
            self.size_preview.configure(text="")

    # ─────────────────────────────────────────
    #  FOLDER SCAN
    # ─────────────────────────────────────────
    IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif", ".gif"}

    def _scan_folder(self, folder):
        if folder in self.source_roots:
            self._log(f"⚠ Thư mục này đã có trong danh sách: {folder}", "warn")
            return
        
        self.source_roots.add(folder)
        count_here = 0
        for root, dirs, files in os.walk(folder):
            images_here = [f for f in sorted(files)
                           if Path(f).suffix.lower() in self.IMAGE_EXTS]
            for img in images_here:
                self.image_list.append((os.path.join(root, img), folder))
                count_here += 1

        self._update_selection_display()
        self._log(f"➕ Thêm thư mục: {os.path.basename(folder)} ({count_here} ảnh)", "info")

    def _scan_files(self, files):
        count_here = 0
        for f in files:
            # Check if already in list? (optional, but keep it simple)
            self.image_list.append((f, None))
            count_here += 1

        self._update_selection_display()
        self._log(f"➕ Thêm {count_here} file lẻ.", "info")

    def _update_selection_display(self):
        total_imgs = len(self.image_list)
        folder_count = len(self.source_roots)
        file_count = len([x for x in self.image_list if x[1] is None])
        
        summary = f"Đã chọn: {folder_count} thư mục, {file_count} file lẻ (Tổng {total_imgs} ảnh)"
        self.source_folder.set(summary)
        
        # Build tree preview text
        lines = [f"✔ {summary}\n"]
        # Group by root for preview
        roots_shown = 0
        for root in sorted(list(self.source_roots)):
            if roots_shown >= 10: break
            n = len([x for x in self.image_list if x[1] == root])
            lines.append(f"  📁 {os.path.basename(root)} ({n} ảnh)")
            roots_shown += 1
            
        if folder_count > 10:
            lines.append(f"  ... và {folder_count - 10} thư mục khác")
            
        if file_count > 0:
            lines.append(f"  📄 {file_count} ảnh chọn lẻ")

        self.tree_label.configure(text="\n".join(lines), fg=TEXT)
        self._update_size_preview()

    # ─────────────────────────────────────────
    #  SCALE PROCESS
    # ─────────────────────────────────────────
    def _start(self):
        src = self.source_folder.get().strip()
        if not src:
            messagebox.showwarning("Thiếu thông tin", "Vui lòng chọn nguồn ảnh hợp lệ.")
            return

        if not self.image_list:
            messagebox.showwarning("Không tìm thấy ảnh",
                                   "Nguồn không chứa ảnh nào được hỗ trợ.")
            return

        out_base = self.output_folder.get().strip()
        if not out_base:
            messagebox.showwarning("Thiếu thư mục xuất", "Vui lòng chọn thư mục lưu ảnh trước khi bắt đầu.")
            return

        # Determine target size strategy
        if self.scale_mode.get() == "custom":
            try:
                tw = int(self.custom_w.get())
                th = int(self.custom_h.get())
            except ValueError:
                messagebox.showwarning("Lỗi", "Kích thước tuỳ chỉnh không hợp lệ.")
                return
            size_info = ("custom", tw, th)
        elif self.scale_mode.get() == "keep":
            size_info = ("keep", 1, 1)
        else:
            try:
                scale = float(self.preset_scale.get())
                if scale > 10:
                    scale = 10.0
                    self.preset_scale.set("10")
                elif scale <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showwarning("Lỗi", "Tỉ lệ nhân không hợp lệ (phải là số > 0).")
                return
            size_info = ("scale", scale, scale)

        self.is_running = True
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.progress_var.set(0)

        t = threading.Thread(target=self._run_scale,
                             args=(out_base, size_info), daemon=True)
        t.start()

    def _stop(self):
        self.is_running = False
        self._log("⏹ Đã yêu cầu dừng...", "warn")

    def _run_scale(self, out_base, size_info):
        total = len(self.image_list)
        done  = 0
        skipped = 0
        errors  = 0
        fmt   = self.output_format.get()
        ext_map = {"JPG": "jpg", "PNG": "png", "WEBP": "webp",
                   "BMP": "bmp", "TIFF": "tiff"}
        out_ext = ext_map.get(fmt, "png")

        pil_fmt_map = {"jpg": "JPEG", "png": "PNG", "webp": "WEBP",
                       "bmp": "BMP", "tiff": "TIFF"}

        self._log(f"▶ Bắt đầu xử lý {total} ảnh...", "head")
        self._log(f"  Định dạng xuất: {fmt}", "info")

        for img_path, root in self.image_list:
            if not self.is_running:
                break

            if root:
                # Folder source
                rel_path = os.path.relpath(img_path, root)
                rel_dir  = os.path.dirname(rel_path)
                out_folder_name = f"Resized_{os.path.basename(root)}"
                out_dir = os.path.join(out_base, out_folder_name, rel_dir)
            else:
                # Picked files
                rel_path = os.path.basename(img_path)
                out_folder_name = "Resized_Picked_Files"
                out_dir = os.path.join(out_base, out_folder_name)

            new_name = Path(img_path).stem + f".{out_ext}"
            out_path = os.path.join(out_dir, new_name)

            os.makedirs(out_dir, exist_ok=True)

            if self.skip_existing.get() and os.path.exists(out_path):
                self._log(f"  ↷ Bỏ qua (đã tồn tại): {rel_path}", "skip")
                skipped += 1
                done += 1
                self._set_progress(done / total * 100)
                continue

            try:
                img = Image.open(img_path)
                ow, oh = img.size

                if size_info[0] == "scale":
                    nw = int(ow * size_info[1])
                    nh = int(oh * size_info[2])
                elif size_info[0] == "keep":
                    nw, nh = ow, oh
                else:
                    nw, nh = size_info[1], size_info[2]

                if size_info[0] == "keep":
                    img_resized = img.copy()
                elif size_info[0] == "custom" and self.letterbox.get():
                    # Letterbox: giữ tỷ lệ gốc, đặt vào giữa canvas trong suốt
                    canvas_w, canvas_h = nw, nh
                    ratio = min(canvas_w / ow, canvas_h / oh)
                    fit_w = int(ow * ratio)
                    fit_h = int(oh * ratio)
                    img_fitted = img.resize((fit_w, fit_h), Image.LANCZOS)

                    # Tạo canvas trong suốt (RGBA)
                    img_resized = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
                    offset_x = (canvas_w - fit_w) // 2
                    offset_y = (canvas_h - fit_h) // 2
                    # Đảm bảo ảnh source cũng là RGBA để paste đúng
                    if img_fitted.mode != "RGBA":
                        img_fitted = img_fitted.convert("RGBA")
                    img_resized.paste(img_fitted, (offset_x, offset_y))
                    nw, nh = canvas_w, canvas_h
                else:
                    img_resized = img.resize((nw, nh), Image.LANCZOS)

                # Handle format compatibility
                save_fmt = pil_fmt_map[out_ext]
                if save_fmt in ("JPEG", "BMP") and img_resized.mode in ("RGBA", "P"):
                    # JPG/BMP không hỗ trợ trong suốt → đặt nền trắng
                    bg = Image.new("RGB", img_resized.size, (255, 255, 255))
                    if img_resized.mode == "P":
                        img_resized = img_resized.convert("RGBA")
                    bg.paste(img_resized, mask=img_resized.split()[3])
                    img_resized = bg

                # Cài đặt DPI 300
                img_resized.save(out_path, format=save_fmt, quality=95, dpi=(300, 300))

                self._log(f"  ✔ {rel_path}  ({ow}×{oh} → {nw}×{nh})", "ok")

            except Exception as e:
                self._log(f"  ✘ Lỗi: {rel_path} — {e}", "err")
                errors += 1

            done += 1
            self._set_progress(done / total * 100)
            self._set_stats(done, total, skipped, errors)

        # Done
        self.is_running = False
        self.after(0, lambda: self.btn_start.configure(state="normal"))
        self.after(0, lambda: self.btn_stop.configure(state="disabled"))
        self._set_progress(100)

        summary = (f"Hoàn tất: {done}/{total} ảnh  |  "
                   f"Bỏ qua: {skipped}  |  Lỗi: {errors}")
        self._log(f"\n✅ {summary}", "ok")
        self._log(f"   Thư mục xuất lưu tại: {out_base}", "head")

        def _show_msg():
            if done < total:
                msg = f"Đã dừng giữa chừng.\n{summary}\n\nBạn có muốn mở thư mục kết quả không?"
            else:
                msg = f"Đã hoàn thiện tiến trình scale ảnh!\n\n{summary}\n\nThư mục xuất:\n{out_base}\n\nBạn có muốn mở thư mục này không?"
            
            if messagebox.askyesno("✅ Hoàn thành", msg):
                try:
                    open_path(out_base)
                except Exception as e:
                    self._log(f"Lỗi khi mở thư mục: {e}", "err")

        self.after(0, _show_msg)

    # ─────────────────────────────────────────
    #  LOG / PROGRESS
    # ─────────────────────────────────────────
    def _log(self, msg, tag="info"):
        def _do():
            self.log_text.configure(state="normal")
            ts = datetime.now().strftime("%H:%M:%S")
            self.log_text.insert("end", f"[{ts}] {msg}\n", tag)
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.after(0, _do)

    def _set_progress(self, val):
        self.after(0, lambda: self.progress_var.set(val))

    def _set_stats(self, done, total, skipped, errors):
        pct = int(done / total * 100) if total else 0
        txt = f"Đang xử lý: {done}/{total} ảnh ({pct}%)  |  Bỏ qua: {skipped}  |  Lỗi: {errors}"
        self.after(0, lambda: self.stats_bar.configure(text=txt))

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self.progress_var.set(0)
        self.stats_bar.configure(text="Sẵn sàng")


