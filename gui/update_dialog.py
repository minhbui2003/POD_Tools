import tkinter as tk
from tkinter import ttk, messagebox
import webbrowser

from core import updater

BUTTON_PRIMARY_BG = "#DCEEFF"
BUTTON_PRIMARY_BORDER = "#9FC3E8"
BUTTON_SECONDARY_BG = "#EAF0F6"
BUTTON_SECONDARY_BORDER = "#C7D0DB"


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

class UpdateDialog(tk.Toplevel):
    def __init__(self, parent, new_version, release_notes, download_url, sha256):
        super().__init__(parent)
        
        self.parent = parent
        self.new_version = new_version
        self.release_notes = release_notes
        self.download_url = download_url
        self.sha256 = sha256
        self.is_manual_update = updater.is_macos()
        
        self.title("Phát hiện bản cập nhật mới")
        self.geometry("450x300")
        self.resizable(False, False)
        
        # Center to parent
        self.transient(parent)
        self.grab_set()
        
        # Thiết kế giao diện
        BG_COLOR = "#ffffff"
        self.configure(bg=BG_COLOR)
        
        title_lbl = tk.Label(self, text=f"Phiên bản mới: v{new_version} đã sẵn sàng!", 
                             font=("Segoe UI", 13, "bold"), bg=BG_COLOR, fg="#2c3e50")
        title_lbl.pack(pady=(20, 10))
        
        notes_frame = tk.Frame(self, bg=BG_COLOR)
        notes_frame.pack(fill="both", expand=True, padx=20, pady=5)
        
        # Hiển thị release notes
        self.notes_text = tk.Text(notes_frame, wrap="word", height=6, font=("Segoe UI", 10),
                                  bg="#f8f9fa", relief="flat", padx=10, pady=10)
        self.notes_text.insert("1.0", self.release_notes)
        self.notes_text.config(state="disabled") # Không cho sửa
        self.notes_text.pack(fill="both", expand=True)
        
        # Thanh tiến trình
        self.progress_var = tk.IntVar()
        self.progress_bar = ttk.Progressbar(self, orient="horizontal", length=350, 
                                            mode="determinate", variable=self.progress_var)
        self.progress_bar.pack(pady=10)
        self.progress_bar.pack_forget() # Ban đầu giấu đi
        
        self.status_lbl = tk.Label(self, text="", font=("Segoe UI", 9, "italic"), bg=BG_COLOR, fg="#7f8c8d")
        self.status_lbl.pack(pady=0)
        
        # Frame nút bấm
        self.btn_frame = tk.Frame(self, bg=BG_COLOR)
        self.btn_frame.pack(side="bottom", fill="x", pady=20)
        
        update_text = "Tai ban macOS" if self.is_manual_update else "Cập nhật ngay"
        self.btn_update = tk.Button(self.btn_frame, text=update_text, font=("Segoe UI", 10, "bold"),
                                   padx=15, pady=5, cursor="hand2",
                                   command=self.start_update,
                                   **_button_style(BUTTON_PRIMARY_BG, BUTTON_PRIMARY_BORDER))
        self.btn_update.pack(side="left", expand=True)
        
        self.btn_cancel = tk.Button(self.btn_frame, text="Nhắc tôi sau", font=("Segoe UI", 10),
                                   padx=15, pady=5, cursor="hand2",
                                   command=self.destroy,
                                   **_button_style(BUTTON_SECONDARY_BG, BUTTON_SECONDARY_BORDER))
        self.btn_cancel.pack(side="right", expand=True)
        
        self._center_window()

    def _center_window(self):
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry('{}x{}+{}+{}'.format(width, height, x, y))

    def on_progress(self, percent):
        """Callback tiến trình, gọi từ luồng tải bằng after"""
        def update_ui():
            if percent == -1:
                self.progress_bar.config(mode="indeterminate")
                self.progress_bar.start(10)
                self.status_lbl.config(text="Đang kiểm tra tính vẹn toàn (Checksum)...")
            else:
                self.progress_bar.config(mode="determinate")
                self.progress_bar.stop()
                self.progress_var.set(percent)
                self.status_lbl.config(text=f"Đang tải dữ liệu: {percent}%")
                
        self.after(0, update_ui)

    def on_success(self, bat_path):
        """Khởi động tiến trình bat và tắt app"""
        def run_bat():
            self.status_lbl.config(text="Hoàn thiện chuẩn bị. Ứng dụng sẽ khởi động lại...")
            # Dùng after để cập nhật status trước khi tắt
            self.after(500, lambda: updater.execute_updater_and_exit(bat_path))
        self.after(0, run_bat)

    def on_error(self, message):
        """Hủy cài đặt báo lỗi"""
        def show_error():
            self.progress_bar.pack_forget()
            self.status_lbl.config(text="")
            self.btn_update.config(state="normal", text="Thử lại")
            self.btn_cancel.config(state="normal")
            messagebox.showerror("Cập nhật thất bại", message, parent=self)
        self.after(0, show_error)

    def start_update(self):
        if self.is_manual_update:
            webbrowser.open(self.download_url)
            messagebox.showinfo(
                "Cap nhat macOS",
                "File cap nhat macOS da duoc mo trong trinh duyet.\n"
                "Hay tai file zip, thoat app hien tai, giai nen va thay bang ban moi.",
                parent=self
            )
            self.destroy()
            return

        """Người dùng bấm nút cập nhật"""
        self.btn_update.config(state="disabled", text="Đang tải...")
        self.btn_cancel.config(state="disabled")
        
        self.progress_bar.pack(pady=10)
        self.status_lbl.config(text="Bắt đầu tải...")
        self.progress_var.set(0)
        
        # Bắt đầu luồng tải
        updater.download_and_install_update(
            download_url=self.download_url,
            expected_sha256=self.sha256,
            progress_callback=self.on_progress,
            success_callback=self.on_success,
            error_callback=self.on_error
        )
