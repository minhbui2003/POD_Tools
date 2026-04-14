"""
POD Tools - App Hợp Nhất
Gồm 2 chức năng chính:
- Crawl Ảnh (từ Gossby/Wanderprints)
- Resize Ảnh (Hàng loạt + DPI 300)
"""
import sys
import os
import tkinter as tk
from tkinter import ttk

# Import các tab
from gui.tab_crawl import CrawlTab
from gui.tab_resize import ResizeTab

# Để hỗ trợ import 'core' từ bất cứ đâu
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

BG_MAIN = "#f5f7fa"
BG_SIDE = "#ffffff"
BG_HOVER = "#e2e8f0"
ACCENT = "#c4a484"
TEXT = "#000000"

class PODToolsApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("POD Software - Tools")
        self.geometry("1000x800")
        self.minsize(900, 700)
        self.configure(bg=BG_MAIN)
        
        self.current_btn = None
        self.current_frame = None
        self.frames = {}
        
        # Load Icons
        self._load_menu_icons()
        self._set_app_icon()
        
        self._build_sidebar()
        self._build_main_area()
        
        # Init Tabs
        self.frames["crawl"] = CrawlTab(self.main_area)
        self.frames["resize"] = ResizeTab(self.main_area)
        
        # Mặc định mở tab đầu tiên
        self._switch_tab("crawl", self.btn_crawl)

    def _load_menu_icons(self):
        try:
            from PIL import Image, ImageTk
            import sys
            
            if getattr(sys, 'frozen', False):
                base_path = sys._MEIPASS
            else:
                base_path = os.path.dirname(os.path.abspath(__file__))
            
            # Helper to load and resize
            def _get_img(name):
                p = os.path.join(base_path, "assets", name)
                if os.path.exists(p):
                    img = Image.open(p).resize((24, 24), Image.LANCZOS)
                    return ImageTk.PhotoImage(img)
                return None

            self.icon_crawl = _get_img("icon_crawl.png")
            self.icon_resize = _get_img("icon_resize.png")
        except Exception:
            self.icon_crawl = None
            self.icon_resize = None

    def _set_app_icon(self):
        try:
            from PIL import Image, ImageTk
            import sys
            
            if getattr(sys, 'frozen', False):
                base_path = sys._MEIPASS
            else:
                base_path = os.path.dirname(os.path.abspath(__file__))
                
            icon_path = os.path.join(base_path, "assets", "Logo_bg.png")
            if os.path.exists(icon_path):
                icon_img = Image.open(icon_path)
                self.iconphoto(False, ImageTk.PhotoImage(icon_img))
        except Exception:
            pass

    def _build_sidebar(self):
        self.sidebar = tk.Frame(self, bg=BG_SIDE, width=220)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # Trống trên đầu 1 chút
        tk.Label(self.sidebar, text="POD TOOLS", font=("Segoe UI", 16, "bold"), 
                 bg=BG_SIDE, fg="#000000").pack(pady=(30, 20))

        # Các Nút Menu
        self.btn_crawl = self._make_menu_btn("Crawl Image", "crawl", self.icon_crawl)
        self.btn_crawl.pack(fill="x", pady=2, padx=10)
        
        self.btn_resize = self._make_menu_btn("Resize Image", "resize", self.icon_resize)
        self.btn_resize.pack(fill="x", pady=2, padx=10)
        
        # Phần dư ở dưới
        tk.Label(self.sidebar, text="By IT POD Software", font=("Segoe UI", 9), 
                 bg=BG_SIDE, fg="#000000").pack(side="bottom", pady=10)

    def _make_menu_btn(self, text, tab_id, icon=None):
        btn = tk.Button(self.sidebar, text=f" {text}", font=("Segoe UI", 11, "bold"),
                        bg=BG_SIDE, fg=TEXT, relief="flat", bd=0, 
                        image=icon, compound="left",
                        anchor="center", padx=10, pady=12, cursor="hand2")
        btn.configure(command=lambda b=btn, tid=tab_id: self._switch_tab(tid, b))
        
        # Hover effect
        btn.bind("<Enter>", lambda e, b=btn: self._on_hover(b))
        btn.bind("<Leave>", lambda e, b=btn: self._on_leave(b))
        
        return btn
        btn.configure(command=lambda b=btn, tid=tab_id: self._switch_tab(tid, b))
        
        # Hover effect
        btn.bind("<Enter>", lambda e, b=btn: self._on_hover(b))
        btn.bind("<Leave>", lambda e, b=btn: self._on_leave(b))
        
        return btn

    def _on_hover(self, btn):
        if btn != self.current_btn:
            btn.configure(bg=BG_HOVER)

    def _on_leave(self, btn):
        if btn != self.current_btn:
            btn.configure(bg=BG_SIDE)

    def _build_main_area(self):
        self.main_area = tk.Frame(self, bg=BG_MAIN)
        self.main_area.pack(side="left", fill="both", expand=True)

    def _switch_tab(self, tab_id, btn):
        # Đổi màu hiển thị của sidebar
        if self.current_btn:
            self.current_btn.configure(bg=BG_SIDE, fg=TEXT)
        self.current_btn = btn
        self.current_btn.configure(bg=ACCENT, fg="#000000")
        
        # Ẩn frame cũ
        if self.current_frame:
            self.current_frame.pack_forget()
            
        # Hiển thị frame mới
        self.current_frame = self.frames[tab_id]
        self.current_frame.pack(fill="both", expand=True)

if __name__ == "__main__":
    app = PODToolsApp()
    app.mainloop()
