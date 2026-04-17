import sys, os, threading, base64, json, time
from urllib.parse import urlparse
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
from core.config import *
from core.wanderprints_scraper import Downloader
from core.gossby_scraper import gs_scrape_single_product, gs_scrape_personalized_data
from core.collection_scraper import fetch_collection, detect_site
from core.platform_utils import get_asset_path, get_default_dialog_dir, get_user_config_dir, open_path

OUTPUT_PLACEHOLDER = "Chọn thư mục lưu ảnh trước khi chạy!"
PANEL_BG = "#FFFFFF"
PANEL_BORDER = "#D6DCE5"
BUTTON_PRIMARY_BG = "#DCEEFF"
BUTTON_PRIMARY_BORDER = "#9FC3E8"
BUTTON_SECONDARY_BG = "#EAF0F6"
BUTTON_SECONDARY_BORDER = "#C7D0DB"
BUTTON_STOP_BG = "#FDE2E2"
BUTTON_STOP_BORDER = "#E7B3B3"
BUTTON_START_BG = "#DFF4EA"
BUTTON_START_BORDER = "#A9D8BD"


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
        "takefocus": 0,
    }


def _check_toggle(parent, text, variable, font=("Segoe UI", 10), state="normal"):
    return tk.Checkbutton(
        parent,
        text=text,
        variable=variable,
        indicatoron=False,
        selectcolor=BUTTON_PRIMARY_BG,
        font=font,
        cursor="hand2",
        padx=8,
        pady=3,
        state=state,
        **_button_style(BUTTON_SECONDARY_BG, BUTTON_SECONDARY_BORDER)
    )


def _radio_toggle(parent, text, variable, value, command=None, font=("Segoe UI", 10)):
    def _select(_event=None):
        variable.set(value)
        if command:
            command()
        return "break"

    widget = tk.Radiobutton(
        parent,
        text=text,
        variable=variable,
        value=value,
        indicatoron=False,
        selectcolor=BUTTON_PRIMARY_BG,
        font=font,
        cursor="hand2",
        padx=8,
        pady=3,
        **_button_style(BUTTON_SECONDARY_BG, BUTTON_SECONDARY_BORDER)
    )
    widget.bind("<Button-1>", _select)
    return widget


def _is_empty_output_folder(value):
    value = value.strip()
    return not value or value == OUTPUT_PLACEHOLDER or "Tool" in value


def _ask_output_folder(parent):
    parent.update_idletasks()
    return filedialog.askdirectory(
        parent=parent,
        title="Chọn thư mục lưu",
        initialdir=get_default_dialog_dir(),
        mustexist=True,
    )

# ─────────────────────────────────────────────
# Encrypt / Decrypt helpers (XOR + base64)
# ─────────────────────────────────────────────
_SECRET_KEY = "P0D-CR4WL-S3CR3T-K3Y-2025"

def _xor_encrypt(text: str, key: str) -> str:
    key_bytes = key.encode('utf-8')
    encrypted = bytes(
        b ^ key_bytes[i % len(key_bytes)]
        for i, b in enumerate(text.encode('utf-8'))
    )
    return base64.b64encode(encrypted).decode('utf-8')

def _xor_decrypt(encoded: str, key: str) -> str:
    try:
        encrypted = base64.b64decode(encoded.encode('utf-8'))
        key_bytes = key.encode('utf-8')
        decrypted = bytes(
            b ^ key_bytes[i % len(key_bytes)]
            for i, b in enumerate(encrypted)
        )
        return decrypted.decode('utf-8')
    except Exception:
        return ""

# ─────────────────────────────────────────────
# GUI — shared log helpers
# ─────────────────────────────────────────────
def _make_log_box(parent):
    """Create a colour-coded ScrolledText log panel."""
    log_box = scrolledtext.ScrolledText(
        parent, bg="#ffffff", fg="#000000", insertbackground="#1e293b",
        font=("Consolas", 9), relief="solid", state="disabled", bd=1, wrap="word"
    )
    log_box.tag_config("ok",   foreground="#16a34a")
    log_box.tag_config("skip", foreground="#9ca3af")
    log_box.tag_config("fail", foreground="#dc2626")
    log_box.tag_config("info", foreground="#1e3a8a")
    log_box.tag_config("head", foreground="#d97706")
    return log_box

def _append_to_log(log_box, msg: str):
    log_box.configure(state="normal")
    if "✓" in msg or "Downloaded" in msg:       tag = "ok"
    elif "[SKIP]" in msg or "SKIP" in msg:       tag = "skip"
    elif "✗" in msg or "FAIL" in msg or "Error" in msg or "Failed" in msg: tag = "fail"
    elif msg.startswith("[") and "]" in msg:     tag = "info"
    elif msg.startswith("---") or msg.startswith("=") or msg.startswith("✅"): tag = "head"
    else:                                         tag = None
    if tag:
        log_box.insert("end", msg + "\n", tag)
    else:
        log_box.insert("end", msg + "\n")
    log_box.see("end")
    log_box.configure(state="disabled")

# ─────────────────────────────────────────────
# TAB 1 — Wanderprints
# ─────────────────────────────────────────────
class WanderprintsTab(tk.Frame):
    def __init__(self, parent, gemini_key_var: tk.StringVar):
        super().__init__(parent, bg="#f5f7fa")
        self.gemini_key_var = gemini_key_var
        self.is_running = False
        self._build_ui()

    def _build_ui(self):
        # Header
        tk.Label(self, text="Wanderprints",
                 bg="#f5f7fa", fg="#000000",
                 font=("Segoe UI", 14, "bold")).pack(fill="x", pady=(10, 6))

        # URL row
        frame_url = tk.Frame(self, bg=PANEL_BG, highlightbackground=PANEL_BORDER, highlightthickness=1)
        frame_url.pack(fill="x", padx=16, pady=(4, 6), ipadx=4, ipady=4)
        tk.Label(frame_url, text="URL sản phẩm:", bg="#ffffff",
                 fg="#000000", font=("Segoe UI", 10)).pack(side="left")
        self.url_var = tk.StringVar()
        self.entry = tk.Entry(frame_url, textvariable=self.url_var,
                              bg="#fff", fg="#000000", insertbackground="#222",
                              relief="solid", font=("Segoe UI", 10), bd=1)
        self.entry.pack(side="left", fill="x", expand=True, padx=(8, 8))
        self.entry.bind("<Return>", lambda e: self._start())
        self.btn = tk.Button(frame_url, text="▶  Tải", command=self._start,
                             font=("Segoe UI", 10, "bold"),
                             padx=14, pady=4, cursor="hand2",
                             **_button_style(BUTTON_START_BG, BUTTON_START_BORDER))
        self.btn.pack(side="left", padx=(0, 8))
        self.btn_stop = tk.Button(frame_url, text="■  Dừng", command=self._stop,
                                  font=("Segoe UI", 10, "bold"),
                                  padx=14, pady=4, cursor="hand2", state="disabled",
                                  **_button_style(BUTTON_STOP_BG, BUTTON_STOP_BORDER))
        self.btn_stop.pack(side="left")

        # Checkboxes — Variant (media) / Layer (swatch)
        chk_frame = tk.Frame(self, bg=PANEL_BG, highlightbackground=PANEL_BORDER, highlightthickness=1)
        chk_frame.pack(fill="x", padx=16, pady=(4, 4), ipadx=4, ipady=4)
        self.var_media = tk.BooleanVar(value=True)
        self.var_swatch = tk.BooleanVar(value=True)
        self.var_desc = tk.BooleanVar(value=False)
        tk.Label(chk_frame, text="Dữ liệu:", bg="#ffffff",
                    fg="#000000", font=("Segoe UI", 10)).pack(side="left", padx=(0, 6))
        _check_toggle(chk_frame, "Variants (ảnh sản phẩm)", self.var_media).pack(side="left", padx=(0, 16))
        _check_toggle(chk_frame, "Layers (ảnh cá nhân hóa)", self.var_swatch).pack(side="left", padx=(0, 16))
        self.chk_desc = _check_toggle(chk_frame, "Mô tả mới cho sản phẩm", self.var_desc, state="disabled")
        self.chk_desc.pack(side="left")

        # Folder row with browse button
        folder_frame = tk.Frame(self, bg=PANEL_BG, highlightbackground=PANEL_BORDER, highlightthickness=1)
        folder_frame.pack(fill="x", padx=16, pady=(4, 4), ipadx=4, ipady=4)
        tk.Label(folder_frame, text="Thư mục lưu:", bg="#ffffff",
                 fg="#000000", font=("Segoe UI", 10)).pack(side="left")
        self.folder_var = tk.StringVar(value=OUTPUT_PLACEHOLDER)
        wp_entry = tk.Entry(folder_frame, textvariable=self.folder_var,
                            bg="#fff", fg="#000000", insertbackground="#222",
                            relief="solid", font=("Segoe UI", 10), bd=1)
        wp_entry.pack(side="left", fill="x", expand=True, padx=(8, 6))
        
        def wp_focus_in(e):
            if self.folder_var.get() == OUTPUT_PLACEHOLDER:
                self.folder_var.set("")
                wp_entry.config(fg="#000000")
                
        def wp_focus_out(e):
            if not self.folder_var.get():
                self.folder_var.set(OUTPUT_PLACEHOLDER)
                wp_entry.config(fg="#000000")
                
        wp_entry.bind("<FocusIn>", wp_focus_in)
        wp_entry.bind("<FocusOut>", wp_focus_out)
        self.folder_entry = wp_entry

        tk.Button(folder_frame, text="Chọn", command=self._browse_folder,
                  font=("Segoe UI", 10), cursor="hand2", padx=6,
                  **_button_style(BUTTON_PRIMARY_BG, BUTTON_PRIMARY_BORDER)).pack(side="left")

        # Status + progress
        self.status_var = tk.StringVar(value="Sẵn sàng")
        tk.Label(self, textvariable=self.status_var, bg="#f5f7fa", fg="#16a34a",
                 font=("Segoe UI", 9)).pack(anchor="w", padx=18)
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("wp.Horizontal.TProgressbar",
                        troughcolor=BUTTON_SECONDARY_BG, background=BUTTON_START_BG, thickness=6)
        self.progress = ttk.Progressbar(self, style="wp.Horizontal.TProgressbar",
                                        mode="determinate", maximum=100)
        self.progress.pack(fill="x", padx=16, pady=(2, 6))

        # Log
        tk.Label(self, text="Log:", bg="#f5f7fa", fg="#000000",
                 font=("Segoe UI", 9)).pack(anchor="w", padx=18)
        self.log_box = _make_log_box(self)
        self.log_box.pack(fill="both", expand=True, padx=16, pady=(0, 4))
        tk.Button(self, text="Xoá log", command=self._clear_log,
                  font=("Segoe UI", 8), cursor="hand2",
                  **_button_style(BUTTON_SECONDARY_BG, BUTTON_SECONDARY_BORDER)).pack(anchor="e", padx=16, pady=(0, 8))


    def _browse_folder(self):
        path = _ask_output_folder(self)
        if path:
            self.folder_var.set(path)
            self.folder_entry.config(fg="#000000")

    def toggle_desc_checkbox(self, has_key: bool):
        if has_key:
            self.chk_desc.config(state="normal")
            self.var_desc.set(True)
        else:
            self.var_desc.set(False)
            self.chk_desc.config(state="disabled")

    def _log(self, msg: str):
        self.after(0, _append_to_log, self.log_box, msg)

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _start(self):
        url = self.url_var.get().strip()
        if not url:
            self._log("[!] Vui lòng nhập URL sản phẩm."); return
        if self.btn["state"] == "disabled": return
        self._clear_log()
        self.btn.configure(state="disabled", **_button_style(BUTTON_START_BG, BUTTON_START_BORDER))
        self.btn_stop.configure(state="normal", **_button_style(BUTTON_STOP_BG, BUTTON_STOP_BORDER))
        self.is_running = True
        self.status_var.set("Đang xử lý...")
        self.progress["value"] = 0
        do_media  = self.var_media.get()
        do_swatch = self.var_swatch.get()
        if not (do_media or do_swatch):
            self._log("[!] Vui lòng chọn ít nhất 1 loại dữ liệu."); return
        do_desc   = self.var_desc.get()
        folder = self.folder_var.get().strip()
        base_dir = folder if folder else None
        if _is_empty_output_folder(folder):
            messagebox.showwarning("Thiếu thư mục lưu", "Vui lòng chọn thư mục lưu trước khi bắt đầu.")
            self.is_running = False
            self.btn.configure(state="normal", **_button_style(BUTTON_START_BG, BUTTON_START_BORDER))
            self.btn_stop.configure(state="disabled", **_button_style(BUTTON_STOP_BG, BUTTON_STOP_BORDER))
            self.status_var.set("San sang")
            return
        threading.Thread(target=self._worker, args=(url, do_media, do_swatch, do_desc, base_dir), daemon=True).start()

    def _stop(self):
        self.is_running = False
        self._log("\n[!] Đang gửi lệnh dừng đến tiến trình tải ảnh...")
        self.status_var.set("Đang dừng...")
        self.progress.stop()
        self.progress.configure(value=0)
        self.btn_stop.configure(state="disabled", **_button_style(BUTTON_STOP_BG, BUTTON_STOP_BORDER))

    def _set_progress(self, current, total):
        pct = int(current / total * 100) if total else 0
        self.after(0, lambda p=pct: self.progress.configure(value=p))

    def _worker(self, url, do_media, do_swatch, do_desc, base_dir=None):
        try:
            # Chỉ dùng API key nếu người dùng tích chọn ô New Description
            _key_to_use = self.gemini_key_var.get().strip() if do_desc else None
            
            dl = Downloader(log_fn=self._log, progress_fn=self._set_progress,
                            gemini_api_key=_key_to_use or None,
                            is_running_check=lambda: getattr(self, "is_running", False),
                            output_root=base_dir)
            _t0 = time.time()
            out_dir = dl.run(url, do_media=do_media, do_swatch=do_swatch)
            _elapsed = time.time() - _t0
            _mm, _ss = divmod(int(_elapsed), 60)
            save_path = base_dir
            self.after(0, self._done, dl.total_ok, dl.total_fail, save_path, _mm, _ss)
        except Exception as e:
            self._log(f"[ERROR] {e}")
            self.after(0, self._done, 0, 1, "", 0, 0)

    def _done(self, ok, fail, save_path="", elapsed_m=0, elapsed_s=0):
        self.progress["value"] = 100
        self.btn.configure(state="normal", **_button_style(BUTTON_START_BG, BUTTON_START_BORDER))
        self.btn_stop.configure(state="disabled", **_button_style(BUTTON_STOP_BG, BUTTON_STOP_BORDER))
        self.is_running = False
        time_str = f"  |⏱ {elapsed_m:02d}:{elapsed_s:02d}" if (elapsed_m or elapsed_s) else ""
        self.status_var.set(f"Xong — thành công: {ok}  |  thất bại: {fail}{time_str}")
        if ok > 0 and save_path:
            res = messagebox.askyesno("Hoàn thành",
                                      f"Đã xong! (⏱ {elapsed_m:02d}:{elapsed_s:02d})\nFile lưu tại:\n{save_path}\n\nMở thư mục?")
            if res:
                open_path(save_path)


# ─────────────────────────────────────────────
# TAB 2 — Gossby
# ─────────────────────────────────────────────
class GossbyTab(tk.Frame):
    def __init__(self, parent, gemini_key_var: tk.StringVar):
        super().__init__(parent, bg="#f5f7fa")
        self.gemini_key_var = gemini_key_var
        self.is_running = False
        self._build_ui()

    def _build_ui(self):
        # Header
        tk.Label(self, text="Gossby",
                 bg="#f5f7fa", fg="#000000",
                 font=("Segoe UI", 14, "bold")).pack(fill="x", pady=(10, 6))

        # URL row — same style as Wanderprints tab
        frame_url = tk.Frame(self, bg=PANEL_BG, highlightbackground=PANEL_BORDER, highlightthickness=1)
        frame_url.pack(fill="x", padx=16, pady=(4, 6), ipadx=4, ipady=4)
        tk.Label(frame_url, text="URL sản phẩm:", bg="#ffffff",
                 fg="#000000", font=("Segoe UI", 10)).pack(side="left")
        self.url_var = tk.StringVar()
        url_entry = tk.Entry(frame_url, textvariable=self.url_var,
                             bg="#fff", fg="#000000", insertbackground="#222",
                             relief="solid", font=("Segoe UI", 10), bd=1)
        url_entry.pack(side="left", fill="x", expand=True, padx=(8, 8))
        url_entry.bind("<Return>", lambda e: self._start())
        self.btn = tk.Button(frame_url, text="▶  Tải", command=self._start,
                             font=("Segoe UI", 10, "bold"),
                             padx=14, pady=4, cursor="hand2",
                             **_button_style(BUTTON_START_BG, BUTTON_START_BORDER))
        self.btn.pack(side="left", padx=(0, 8))
        self.btn_stop = tk.Button(frame_url, text="■  Dừng", command=self._stop,
                                  font=("Segoe UI", 10, "bold"),
                                  padx=14, pady=4, cursor="hand2", state="disabled",
                                  **_button_style(BUTTON_STOP_BG, BUTTON_STOP_BORDER))
        self.btn_stop.pack(side="left")

        # Checkboxes
        chk_frame = tk.Frame(self, bg=PANEL_BG, highlightbackground=PANEL_BORDER, highlightthickness=1)
        chk_frame.pack(fill="x", padx=16, pady=(4, 4), ipadx=4, ipady=4)
        self.var_variants = tk.BooleanVar(value=True)
        self.var_layers   = tk.BooleanVar(value=True)
        self.var_cliparts = tk.BooleanVar(value=True)
        self.var_desc     = tk.BooleanVar(value=False)
        tk.Label(chk_frame, text="Dữ liệu:", bg="#ffffff",
                 fg="#000000", font=("Segoe UI", 10)).pack(side="left", padx=(0, 6))
        _check_toggle(chk_frame, "Variants (ảnh sản phẩm)", self.var_variants).pack(side="left", padx=(0, 16))
        _check_toggle(chk_frame, "Layers (ảnh cá nhân hóa)", self.var_layers).pack(side="left", padx=(0, 16))
        _check_toggle(chk_frame, "Mặc định (Cliparts)", self.var_cliparts).pack(side="left", padx=(0, 16))
        self.chk_desc = _check_toggle(chk_frame, "Mô tả mới cho sản phẩm", self.var_desc, state="disabled")
        self.chk_desc.pack(side="left")

        # Custom folder row with browse button
        folder_frame = tk.Frame(self, bg=PANEL_BG, highlightbackground=PANEL_BORDER, highlightthickness=1)
        folder_frame.pack(fill="x", padx=16, pady=(4, 6), ipadx=4, ipady=4)
        tk.Label(folder_frame, text="Thư mục lưu:", bg="#ffffff",
                 fg="#000000", font=("Segoe UI", 10)).pack(side="left")
        self.folder_var = tk.StringVar(value=OUTPUT_PLACEHOLDER)
        gs_entry = tk.Entry(folder_frame, textvariable=self.folder_var,
                            bg="#fff", fg="#000000", insertbackground="#222",
                            relief="solid", font=("Segoe UI", 10), bd=1)
        gs_entry.pack(side="left", fill="x", expand=True, padx=(8, 6))
        
        def gs_focus_in(e):
            if self.folder_var.get() == OUTPUT_PLACEHOLDER:
                self.folder_var.set("")
                gs_entry.config(fg="#000000")
                
        def gs_focus_out(e):
            if not self.folder_var.get():
                self.folder_var.set(OUTPUT_PLACEHOLDER)
                gs_entry.config(fg="#000000")
                
        gs_entry.bind("<FocusIn>", gs_focus_in)
        gs_entry.bind("<FocusOut>", gs_focus_out)
        self.folder_entry = gs_entry

        tk.Button(folder_frame, text="Chọn", command=self._browse_folder,
                  font=("Segoe UI", 10), cursor="hand2", padx=6,
                  **_button_style(BUTTON_PRIMARY_BG, BUTTON_PRIMARY_BORDER)).pack(side="left")

        # Status
        self.status_var = tk.StringVar(value="Sẵn sàng")
        tk.Label(self, textvariable=self.status_var, bg="#f5f7fa", fg="#16a34a",
                 font=("Segoe UI", 9)).pack(anchor="w", padx=18)
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("gs.Horizontal.TProgressbar",
                        troughcolor=BUTTON_SECONDARY_BG, background=BUTTON_START_BG, thickness=6)
        self.progress = ttk.Progressbar(self, style="gs.Horizontal.TProgressbar",
                                        mode="indeterminate")
        self.progress.pack(fill="x", padx=16, pady=(2, 6))

        # Log
        tk.Label(self, text="Log:", bg="#f5f7fa", fg="#000000",
                 font=("Segoe UI", 9)).pack(anchor="w", padx=18)

        self.log_box = _make_log_box(self)
        self.log_box.pack(fill="both", expand=True, padx=16, pady=(0, 4))
        
        tk.Button(self, text="Xoá log", command=self._clear_log,
                  font=("Segoe UI", 8), cursor="hand2",
                  **_button_style(BUTTON_SECONDARY_BG, BUTTON_SECONDARY_BORDER)).pack(anchor="e", padx=16, pady=(0, 8))


    def _browse_folder(self):
        path = _ask_output_folder(self)
        if path:
            self.folder_var.set(path)
            self.folder_entry.config(fg="#000000")

    def toggle_desc_checkbox(self, has_key: bool):
        if has_key:
            self.chk_desc.config(state="normal")
            self.var_desc.set(True)
        else:
            self.var_desc.set(False)
            self.chk_desc.config(state="disabled")

    def _log(self, msg: str):
        self.after(0, _append_to_log, self.log_box, msg)

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _stop(self):
        self.is_running = False
        self._log("\n[!] Đang gửi lệnh dừng đến tiến trình tải ảnh...")
        self.status_var.set("Đang dừng...")
        self.progress.stop()
        self.progress.configure(value=0)
        self.btn_stop.configure(state="disabled", **_button_style(BUTTON_STOP_BG, BUTTON_STOP_BORDER))


    def _start(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Thiếu URL", "Vui lòng nhập URL sản phẩm!"); return
        if not (self.var_variants.get() or self.var_layers.get()):
            messagebox.showwarning("Lựa chọn", "Chọn ít nhất 1 loại dữ liệu!"); return
        if self.btn["state"] == "disabled": return
        self._clear_log()
        self.btn.configure(state="disabled", **_button_style(BUTTON_START_BG, BUTTON_START_BORDER))
        self.btn_stop.configure(state="normal", **_button_style(BUTTON_STOP_BG, BUTTON_STOP_BORDER))
        self.is_running = True
        self.status_var.set("Đang xử lý...")
        folder = self.folder_var.get().strip()
        base_dir = folder if folder else None
        if _is_empty_output_folder(folder):
            messagebox.showwarning("Thiếu thư mục lưu", "Vui lòng chọn thư mục lưu trước khi bắt đầu.")
            self.is_running = False
            self.btn.configure(state="normal", **_button_style(BUTTON_START_BG, BUTTON_START_BORDER))
            self.btn_stop.configure(state="disabled", **_button_style(BUTTON_STOP_BG, BUTTON_STOP_BORDER))
            self.status_var.set("Sẵn sàng")
            self.progress.stop()
            self.progress.configure(value=0)
            return
        self.progress.configure(value=0)
        self.progress.start(80)
        threading.Thread(target=self._worker,
                         args=(url, self.var_variants.get(), self.var_layers.get(), self.var_cliparts.get(), self.var_desc.get(), base_dir),
                         daemon=True).start()

    def _worker(self, url, do_variants, do_layers, do_cliparts, do_desc, base_dir):
        class StdoutRedirector:
            def __init__(self, log_fn): self.log_fn = log_fn
            def write(self, s):
                s = s.rstrip('\n')
                if s: self.log_fn(s)
            def flush(self): pass

        old_stdout, old_stderr = sys.stdout, sys.stderr
        redirector = StdoutRedirector(self._log)
        sys.stdout = redirector
        sys.stderr = redirector
        _t0 = time.time()
        try:
            self._log("=" * 50)
            if do_variants:
                self._log("\n[--- ĐANG CÀO VARIANTS ---]")
                _key_to_use = self.gemini_key_var.get().strip() if do_desc else None
                gs_scrape_single_product(url, base_dir=base_dir,
                                         gemini_api_key=_key_to_use or None)
            if do_layers:
                self._log("\n[--- ĐANG CÀO PERSONALIZED LAYERS ---]")
                gs_scrape_personalized_data(url, do_cliparts=do_cliparts, base_dir=base_dir, is_running_check=lambda: getattr(self, "is_running", False))
            save_path = base_dir
            _elapsed = time.time() - _t0
            _mm, _ss = divmod(int(_elapsed), 60)
            self._log(f"\n✅ Hoàn tất! File lưu tại: {save_path}")
            self._log(f"⏱ Thời gian: {_mm:02d}:{_ss:02d}")
            self.after(0, self._done, True, save_path, _mm, _ss)
        except Exception as e:
            self._log(f"[ERROR] {e}")
            import traceback; traceback.print_exc()
            self.after(0, self._done, False, "", 0, 0)
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

    def _done(self, success, save_path, elapsed_m=0, elapsed_s=0):
        self.progress.stop()
        self.progress.configure(value=0)
        self.btn.configure(state="normal", **_button_style(BUTTON_START_BG, BUTTON_START_BORDER))
        self.btn_stop.configure(state="disabled", **_button_style(BUTTON_STOP_BG, BUTTON_STOP_BORDER))
        self.is_running = False
        if success:
            time_str = f" (⏱ {elapsed_m:02d}:{elapsed_s:02d})"
            self.status_var.set(f"✅ Hoàn tất!{time_str}")
            res = messagebox.askyesno("Hoàn thành",
                                      f"Đã xong!{time_str}\nFile lưu tại:\n{save_path}\n\nMở thư mục?")
            if res:
                open_path(save_path)
        else:
            self.status_var.set("❌ Có lỗi xảy ra")


# ─────────────────────────────────────────────
# TAB 3 — Collection (Gossby + Wanderprints)
# ─────────────────────────────────────────────
class CollectionTab(tk.Frame):
    def __init__(self, parent, gemini_key_var: tk.StringVar):
        super().__init__(parent, bg="#f5f7fa")
        self.gemini_key_var = gemini_key_var
        self.is_running = False
        self._build_ui()

    def _build_ui(self):
        # Header
        tk.Label(self, text="Collection",
                 bg="#f5f7fa", fg="#000000",
                 font=("Segoe UI", 14, "bold")).pack(fill="x", pady=(10, 6))

        # URL row
        frame_url = tk.Frame(self, bg=PANEL_BG, highlightbackground=PANEL_BORDER, highlightthickness=1)
        frame_url.pack(fill="x", padx=16, pady=(4, 6), ipadx=4, ipady=4)
        tk.Label(frame_url, text="URL Collection:", bg="#ffffff", highlightbackground=PANEL_BORDER, highlightthickness=1,
                 fg="#000000", font=("Segoe UI", 10)).pack(side="left")
        self.url_var = tk.StringVar()
        url_entry = tk.Entry(frame_url, textvariable=self.url_var,
                             bg="#fff", fg="#000000", insertbackground="#222",
                             relief="solid", font=("Segoe UI", 10), bd=1)
        url_entry.pack(side="left", fill="x", expand=True, padx=(8, 8))
        url_entry.bind("<Return>", lambda e: self._start())
        self.btn = tk.Button(frame_url, text="▶  Lấy", command=self._start,
                             font=("Segoe UI", 10, "bold"),
                             padx=14, pady=4, cursor="hand2",
                             **_button_style(BUTTON_START_BG, BUTTON_START_BORDER))
        self.btn.pack(side="left", padx=(0, 8))
        self.btn_stop = tk.Button(frame_url, text="■  Dừng", command=self._stop,
                                  font=("Segoe UI", 10, "bold"),
                                  padx=14, pady=4, cursor="hand2", state="disabled",
                                  **_button_style(BUTTON_STOP_BG, BUTTON_STOP_BORDER))
        self.btn_stop.pack(side="left")

        # Options row
        opt_frame = tk.Frame(self, bg=PANEL_BG, highlightbackground=PANEL_BORDER, highlightthickness=1)
        opt_frame.pack(fill="x", padx=16, pady=(4, 4), ipadx=4, ipady=4)
        tk.Label(opt_frame, text="Số lượng SP:", bg="#ffffff", highlightbackground=PANEL_BORDER, highlightthickness=1,
                 fg="#000000", font=("Segoe UI", 10)).pack(side="left", padx=(0, 6))
        self.limit_var = tk.StringVar(value="10")
        for val, txt in [("10", "10"), ("20", "20"), ("50", "50"), ("0", "Tất cả")]:
            _radio_toggle(opt_frame, txt, self.limit_var, val).pack(side="left", padx=(0, 12))

        # Checkboxes — what to download per product
        chk_frame = tk.Frame(self, bg=PANEL_BG, highlightbackground=PANEL_BORDER, highlightthickness=1)
        chk_frame.pack(fill="x", padx=16, pady=(4, 4), ipadx=4, ipady=4)
        tk.Label(chk_frame, text="Tải:", bg="#ffffff", highlightbackground=PANEL_BORDER, highlightthickness=1,
                 fg="#000000", font=("Segoe UI", 10)).pack(side="left", padx=(0, 6))
        self.var_variants = tk.BooleanVar(value=True)
        self.var_layers = tk.BooleanVar(value=True)
        self.var_cliparts = tk.BooleanVar(value=True)
        self.var_save_json = tk.BooleanVar(value=False)
        _check_toggle(chk_frame, "Variants (ảnh)", self.var_variants).pack(side="left", padx=(0, 12))
        _check_toggle(chk_frame, "Layers (cá nhân hóa)", self.var_layers).pack(side="left", padx=(0, 12))
        _check_toggle(chk_frame, "Cliparts", self.var_cliparts).pack(side="left", padx=(0, 12))
        _check_toggle(chk_frame, "Lưu JSON config", self.var_save_json).pack(side="left")

        # Folder row
        folder_frame = tk.Frame(self, bg=PANEL_BG, highlightbackground=PANEL_BORDER, highlightthickness=1)
        folder_frame.pack(fill="x", padx=16, pady=(4, 4), ipadx=4, ipady=4)
        tk.Label(folder_frame, text="Thư mục lưu:", bg="#ffffff",
                 fg="#000000", font=("Segoe UI", 10)).pack(side="left")
        self.folder_var = tk.StringVar(value=OUTPUT_PLACEHOLDER)
        col_entry = tk.Entry(folder_frame, textvariable=self.folder_var,
                             bg="#fff", fg="#000000", insertbackground="#222",
                             relief="solid", font=("Segoe UI", 10), bd=1)
        col_entry.pack(side="left", fill="x", expand=True, padx=(8, 6))

        def col_focus_in(e):
            if self.folder_var.get() == OUTPUT_PLACEHOLDER:
                self.folder_var.set("")
                col_entry.config(fg="#000000")
        def col_focus_out(e):
            if not self.folder_var.get():
                self.folder_var.set(OUTPUT_PLACEHOLDER)
                col_entry.config(fg="#000000")
        col_entry.bind("<FocusIn>", col_focus_in)
        col_entry.bind("<FocusOut>", col_focus_out)
        self.folder_entry = col_entry

        tk.Button(folder_frame, text="Chọn", command=self._browse_folder,
                  font=("Segoe UI", 10), cursor="hand2", padx=6,
                  **_button_style(BUTTON_PRIMARY_BG, BUTTON_PRIMARY_BORDER)).pack(side="left")

        # Status
        self.status_var = tk.StringVar(value="Sẵn sàng")
        tk.Label(self, textvariable=self.status_var, bg="#f5f7fa", fg="#16a34a",
                 font=("Segoe UI", 9)).pack(anchor="w", padx=18)

        # Log
        tk.Label(self, text="Log:", bg="#f5f7fa", fg="#000000",
                 font=("Segoe UI", 9)).pack(anchor="w", padx=18)
        self.log_box = _make_log_box(self)
        self.log_box.pack(fill="both", expand=True, padx=16, pady=(0, 4))
        tk.Button(self, text="Xoá log", command=self._clear_log,
                  font=("Segoe UI", 8), cursor="hand2",
                  **_button_style(BUTTON_SECONDARY_BG, BUTTON_SECONDARY_BORDER)).pack(anchor="e", padx=16, pady=(0, 8))


    def _browse_folder(self):
        path = _ask_output_folder(self)
        if path:
            self.folder_var.set(path)
            self.folder_entry.config(fg="#000000")

    def _log(self, msg: str):
        self.after(0, _append_to_log, self.log_box, msg)

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _stop(self):
        self.is_running = False
        self._log("\n[!] Đang gửi lệnh dừng đến tiến trình tải ảnh...")
        self.status_var.set("Đang dừng...")
        self.btn_stop.configure(state="disabled", **_button_style(BUTTON_STOP_BG, BUTTON_STOP_BORDER))

    def _start(self):
        url = self.url_var.get().strip()
        if not url:
            self._log("[!] Vui lòng nhập URL collection."); return
        if self.is_running: return
        self._clear_log()
        self.is_running = True
        self.btn.configure(state="disabled", **_button_style(BUTTON_START_BG, BUTTON_START_BORDER))
        self.btn_stop.configure(state="normal", **_button_style(BUTTON_STOP_BG, BUTTON_STOP_BORDER))
        self.status_var.set("Đang lấy danh sách sản phẩm...")
        limit_str = self.limit_var.get()
        limit = int(limit_str)
        folder = self.folder_var.get().strip()
        base_dir = folder if folder else None
        if _is_empty_output_folder(folder):
            messagebox.showwarning("Thiếu thư mục lưu", "Vui lòng chọn thư mục lưu trước khi bắt đầu.")
            self.is_running = False
            self.btn.configure(state="normal", **_button_style(BUTTON_START_BG, BUTTON_START_BORDER))
            self.btn_stop.configure(state="disabled", **_button_style(BUTTON_STOP_BG, BUTTON_STOP_BORDER))
            self.status_var.set("San sang")
            return
        threading.Thread(target=self._worker, args=(url, limit, base_dir), daemon=True).start()

    def _worker(self, collection_url, limit, base_dir):
        _t0 = time.time()
        try:
            site = detect_site(collection_url)
            self._log(f"[INFO] Nhận diện: {site.upper()}")
            self._log(f"[INFO] Giới hạn: {'Tất cả' if limit == 0 else limit} sản phẩm")
            self._log("")
            products = fetch_collection(collection_url, limit=limit, log_fn=self._log, is_running_check=lambda: getattr(self, "is_running", False))
            if not products:
                self._log("\n[!] Không lấy được sản phẩm nào.")
                self.after(0, self._done_collection, False, 0, 0, "", 0, 0)
                return
            self._log(f"\n{'='*50}")
            self._log(f"Tìm thấy {len(products)} sản phẩm — bắt đầu cào...")
            self._log(f"{'='*50}\n")

            do_variants = self.var_variants.get()
            do_layers = self.var_layers.get()
            do_cliparts = self.var_cliparts.get()
            do_desc = False  # Collection mode không hỗ trợ tạo mô tả mới
            total = len(products)
            ok_count = 0
            fail_count = 0

            for idx, p in enumerate(products, 1):
                if not self.is_running:
                    self._log("\n[!] QUÁ TRÌNH CÀO BỊ HỦY BỞI NGƯỜI DÙNG.")
                    break
                p_url = p["url"]
                p_title = p.get("title", p_url)
                self._log(f"\n--- [{idx}/{total}] {p_title} ---")
                self.after(0, self.status_var.set,
                           f"Đang xử lý {idx}/{total}: {p_title[:50]}...")
                try:
                    if site == "gossby":
                        if do_variants:
                            gs_scrape_single_product(p_url, base_dir=base_dir)
                        if do_layers:
                            gs_scrape_personalized_data(p_url, do_cliparts=do_cliparts,
                                                        base_dir=base_dir, is_running_check=lambda: getattr(self, "is_running", False))
                    elif site == "wanderprints":
                        dl = Downloader(log_fn=self._log,
                                        gemini_api_key=None,
                                        is_running_check=lambda: getattr(self, "is_running", False),
                                        output_root=base_dir)
                        dl.run(p_url, do_media=do_variants, do_swatch=do_layers)
                    ok_count += 1
                except Exception as e:
                    self._log(f"  [ERROR] {e}")
                    fail_count += 1

            _elapsed = time.time() - _t0
            _mm, _ss = divmod(int(_elapsed), 60)
            save_path = base_dir
            self._log(f"\n✅ Hoàn tất collection! Thành công: {ok_count} | Thất bại: {fail_count}")
            self._log(f"⏱ Thời gian: {_mm:02d}:{_ss:02d}")
            self.after(0, self._done_collection, True, ok_count, fail_count, save_path, _mm, _ss)
        except Exception as e:
            self._log(f"[ERROR] {e}")
            import traceback; traceback.print_exc()
            self.after(0, self._done_collection, False, 0, 0, "", 0, 0)

    def _done_collection(self, success, ok=0, fail=0, save_path="", mm=0, ss=0):
        self.is_running = False
        self.btn_stop.configure(state="disabled", **_button_style(BUTTON_STOP_BG, BUTTON_STOP_BORDER))
        self.btn.configure(state="normal", **_button_style(BUTTON_START_BG, BUTTON_START_BORDER))
        if success:
            time_str = f" (⏱ {mm:02d}:{ss:02d})"
            self.status_var.set(f"✅ Xong — {ok} thành công | {fail} thất bại{time_str}")
            res = messagebox.askyesno("Hoàn thành",
                                      f"Collection xong!{time_str}\n"
                                      f"Thành công: {ok} | Thất bại: {fail}\n"
                                      f"Lưu tại: {save_path}\n\nMở thư mục?")
            if res:
                open_path(save_path)
        else:
            self.status_var.set("❌ Không lấy được sản phẩm")


# ─────────────────────────────────────────────
# MAIN APP
# ─────────────────────────────────────────────
class CrawlTab(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg="#f5f7fa")
        self._build_ui()

    def _build_ui(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TNotebook", background="#f5f7fa", borderwidth=0)
        style.configure("TNotebook.Tab", background="#ffffff", foreground="#64748b",
                        font=("Segoe UI", 10, "bold"), padding=(14, 5))
        style.map("TNotebook.Tab",
                  background=[("selected", BUTTON_PRIMARY_BG)],
                  foreground=[("selected", "#000000")],
                  font=[("selected", ("Segoe UI", 13, "bold"))],
                  padding=[("selected", (20, 8))])

        # ── Gemini API Key row (dùng chung cho cả 2 tab) ──
        api_container = tk.Frame(self, bg="#f5f7fa")
        api_container.pack(fill="x", padx=12, pady=(8, 4))
        
        api_bar = tk.Frame(api_container, bg="#f5f7fa")
        api_bar.pack(fill="x")
        
        tk.Label(api_bar, text="🔑 Gemini API Key:", bg="#f5f7fa", fg="#000000",
                 font=("Segoe UI", 9, "bold")).pack(side="left")
        # ── Load saved Gemini key ──
        self.gemini_key_var = tk.StringVar()
        _config_file = os.path.join(get_user_config_dir(), "pod_crawl_config.json")
        if os.path.exists(_config_file):
            try:
                with open(_config_file, 'r', encoding='utf-8') as _f:
                    _config_data = json.load(_f)
                _encoded = _config_data.get("gemini_key", "").strip()
                if _encoded:
                    _decrypted = _xor_decrypt(_encoded, _SECRET_KEY)
                    if _decrypted:
                        self.gemini_key_var.set(_decrypted)
            except Exception:
                pass

        gemini_entry = tk.Entry(api_bar, textvariable=self.gemini_key_var,
                                bg="#ffffff", fg="#000000", insertbackground="#1e293b",
                                relief="solid", font=("Consolas", 9), bd=1, show="*")
        gemini_entry.pack(side="left", fill="x", expand=True, padx=(8, 6))

        # ── Auto-save key khi FocusOut ──
        def _save_key(e=None):
            key = self.gemini_key_var.get().strip()
            try:
                _encoded = _xor_encrypt(key, _SECRET_KEY) if key else ""
                _config_data = {}
                if os.path.exists(_config_file):
                    try:
                        with open(_config_file, 'r', encoding='utf-8') as _f:
                            _config_data = json.load(_f)
                    except Exception:
                        pass
                _config_data["gemini_key"] = _encoded
                with open(_config_file, 'w', encoding='utf-8') as _f:
                    json.dump(_config_data, _f, indent=4)
            except Exception:
                pass
        gemini_entry.bind("<FocusOut>", _save_key)

        # Nút toggle hiện/ẩn key
        self._key_visible = False
        def _toggle_visibility():
            self._key_visible = not self._key_visible
            gemini_entry.config(show="" if self._key_visible else "*")
            toggle_btn.config(text="🙈" if self._key_visible else "👁")
        toggle_btn = tk.Button(api_bar, text="👁", command=_toggle_visibility,
                               bg="#ffffff", fg="#000000", relief="flat",
                               font=("Segoe UI", 9), cursor="hand2", padx=4)
        toggle_btn.pack(side="left")
        def _open_guide():
            try:
                pdf_path = get_asset_path("guid_get_gemini_key.pdf")
                
                if os.path.exists(pdf_path):
                    open_path(pdf_path)
                else:
                    messagebox.showerror("Lỗi", "Không tìm thấy file hướng dẫn!")
            except Exception as e:
                messagebox.showerror("Lỗi", f"Không thể mở file hướng dẫn: {e}")

        guide_btn = tk.Button(api_bar, text="📖 Hướng dẫn lấy Gemini API Key", command=_open_guide,
                              font=("Segoe UI", 9, "bold"),
                              cursor="hand2", padx=6,
                              **_button_style(BUTTON_PRIMARY_BG, BUTTON_PRIMARY_BORDER))
        guide_btn.pack(side="left", padx=(4, 0))

        tk.Label(api_container, text="(tùy chọn - bỏ trống Gemini API Key nếu không cần tạo mới Description)",
                 bg="#f5f7fa", fg="#000000",
                 font=("Segoe UI", 8, "italic")).pack(anchor="w", padx=(122, 0), pady=(0, 0))

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=0, pady=0)

        tab1 = WanderprintsTab(notebook, self.gemini_key_var)
        tab2 = GossbyTab(notebook, self.gemini_key_var)
        tab3 = CollectionTab(notebook, self.gemini_key_var)
        notebook.add(tab1, text="Wanderprints")
        notebook.add(tab2, text="Gossby")
        # notebook.add(tab3, text="Collection")  # Ẩn tab Collection tạm thời

        # Trace key variable to toggle New Description checkbox states
        def _on_key_changed(*args):
            has_key = bool(self.gemini_key_var.get().strip())
            tab1.toggle_desc_checkbox(has_key)
            tab2.toggle_desc_checkbox(has_key)
            
        self.gemini_key_var.trace_add("write", _on_key_changed)
        # Khởi tạo trạng thái ban đầu check theo key load được
        _on_key_changed()


if __name__ == "__main__":
    app = App()
    app.mainloop()


