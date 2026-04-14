import re
import os
from urllib.parse import urlparse

def sanitize_wp(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()[:80]

def gs_sanitize_filename(name):
    name = str(name).strip()
    return "".join([c for c in name if c.isalnum() or c in (' ', '-', '_')]).strip()

def gs_get_extension(url):
    ext = os.path.splitext(urlparse(url).path)[1]
    return ext if ext else '.png'

def gs_long_path(path):
    path = os.path.abspath(path)
    if os.name == 'nt' and not path.startswith('\\\\?\\'): return f"\\\\?\\{path}"
    return path
