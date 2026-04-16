import os
import subprocess
import sys


APP_DIR_NAME = "POD_Tools"


def is_windows():
    return sys.platform == "win32"


def is_macos():
    return sys.platform == "darwin"


def get_user_config_dir():
    if is_windows():
        root = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif is_macos():
        root = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        root = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")

    config_dir = os.path.join(root, APP_DIR_NAME)
    os.makedirs(config_dir, exist_ok=True)
    return config_dir


def get_default_dialog_dir():
    documents = os.path.join(os.path.expanduser("~"), "Documents")
    return documents if os.path.isdir(documents) else os.path.expanduser("~")


def get_asset_path(name):
    candidates = []

    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidates.extend([
            os.path.join(sys._MEIPASS, "assets", name),
            os.path.join(sys._MEIPASS, name),
        ])

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates.append(os.path.join(repo_root, "assets", name))

    for path in candidates:
        if os.path.exists(path):
            return path

    return candidates[0] if candidates else name


def open_path(path):
    abs_path = os.path.abspath(path)
    if is_windows():
        os.startfile(abs_path)
    elif is_macos():
        subprocess.Popen(["open", abs_path])
    else:
        subprocess.Popen(["xdg-open", abs_path])
