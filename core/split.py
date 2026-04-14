import os
with open("download_images_gui.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

def write_file(name, imports, start_line, end_line):
    # lines are 1-indexed, so start_line 48 means index 47
    content = imports + "".join(lines[start_line-1:end_line])
    with open(name, "w", encoding="utf-8") as f:
        f.write(content)

wp_imports = """import os, requests, base64, re
from datetime import datetime, timezone
from urllib.parse import urlparse
from config import *
from utils import sanitize_wp

"""

gs_imports = """import os, requests, json, re
from urllib.parse import urlparse
from config import *
from utils import gs_sanitize_filename, gs_get_extension, gs_long_path

"""

# 48 to 283
write_file("wanderprints_scraper.py", wp_imports, 48, 283)

# 285 to 713
write_file("gossby_scraper.py", gs_imports, 285, 713)

# 715 to end for GUI
gui_imports = """import sys, os, threading
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
from config import *
from wanderprints_scraper import Downloader
from gossby_scraper import gs_scrape_single_product, gs_scrape_personalized_data

"""
write_file("download_images_gui.py", gui_imports, 715, len(lines))

print("Successfully split the file.")
