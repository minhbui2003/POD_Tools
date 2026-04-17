import os
import sys
import json
import glob
import time
import urllib.request
import urllib.error
import threading
import hashlib
import subprocess
import shutil
import ssl

from core import config


def _https_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _urlopen(req, timeout):
    return urllib.request.urlopen(req, timeout=timeout, context=_https_context())

def is_frozen():
    """Kiểm tra xem app đang chạy bằng file exe (đã build) hay đang chạy source code python"""
    return getattr(sys, "frozen", False)

def is_macos():
    """Kiểm tra xem đang chạy trên macOS"""
    return sys.platform == "darwin"

def is_windows():
    """Kiểm tra xem đang chạy trên Windows"""
    return sys.platform == "win32"

def parse_version(v_str):
    """Chuyển đổi version string (1.0.1) thành tuple (1,0,1) để so sánh"""
    try:
        parts = []
        for part in str(v_str).strip().lstrip("vV").split("."):
            digits = []
            for char in part:
                if not char.isdigit():
                    break
                digits.append(char)
            parts.append(int("".join(digits) or 0))

        while len(parts) < 3:
            parts.append(0)

        return tuple(parts[:3])
    except Exception:
        return (0, 0, 0)

def is_valid_sha256(value):
    """Chi chap nhan checksum SHA256 day du de tranh cai dat file chua xac thuc."""
    if not value:
        return False
    value = str(value).strip().lower()
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)

def _get_platform_key():
    """Trả về key platform cho version.json"""
    if is_macos():
        return "macos"
    return "windows"

def _parse_update_data(data):
    """
    Đọc version.json hỗ trợ cả format mới (multi-platform) và cũ (single-platform).
    Trả về (version, download_url, sha256, release_notes) hoặc None nếu không hợp lệ.
    """
    new_version_str = data.get("version", "0.0.0")
    release_notes = data.get("release_notes", "Bản cập nhật mới giúp tăng cường hiệu suất và sửa lỗi.")

    platform_key = _get_platform_key()

    # Format mới: có key "windows" / "macos"
    if platform_key in data and isinstance(data[platform_key], dict):
        platform_data = data[platform_key]
        download_url = platform_data.get("download_url", "")
        sha256 = str(platform_data.get("sha256", "")).strip().lower()
    # Format cũ (backward-compatible): "download_url" và "sha256" ở root
    elif "download_url" in data:
        download_url = data.get("download_url", "")
        sha256 = str(data.get("sha256", "")).strip().lower()
    else:
        return None

    return (new_version_str, download_url, sha256, release_notes)

def check_for_updates(
    root_or_callback,
    on_update_found_callback=None,
    dispatch_callback=None,
    force_check_in_dev=False,
):
    """
    Chạy ngầm kiểm tra cập nhật.
    Hỗ trợ cả Tkinter cũ và UI khác:
    - check_for_updates(root, callback): nếu root có after() thì callback chạy qua root.after.
    - check_for_updates(callback, dispatch_callback=...): dispatch_callback nhận (callback, *args).
    """
    if not is_frozen() and not force_check_in_dev:
        print("Dev Mode: Skip automatic update check.")
        return

    if on_update_found_callback is None:
        callback = root_or_callback
        dispatch = dispatch_callback or (lambda fn, *args: fn(*args))
    else:
        root = root_or_callback
        callback = on_update_found_callback
        if dispatch_callback:
            dispatch = dispatch_callback
        elif hasattr(root, "after"):
            dispatch = lambda fn, *args: root.after(0, fn, *args)
        else:
            dispatch = lambda fn, *args: fn(*args)

    def _check():
        try:
            cache_buster = f"_={int(time.time())}"
            update_url = (
                f"{config.UPDATE_JSON_URL}&{cache_buster}"
                if "?" in config.UPDATE_JSON_URL
                else f"{config.UPDATE_JSON_URL}?{cache_buster}"
            )
            req = urllib.request.Request(
                update_url,
                headers={
                    "User-Agent": "POD-Tools-Updater/1.0",
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                }
            )
            # Timeout 5 giây để không treo luồng ngầm
            with _urlopen(req, timeout=15) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode('utf-8'))

                    result = _parse_update_data(data)
                    if result is None:
                        print(f"Updater: Khong co du lieu cap nhat cho platform '{_get_platform_key()}'.")
                        return

                    new_version_str, download_url, sha256, release_notes = result
                    curr_ver = parse_version(config.CURRENT_VERSION)
                    new_ver = parse_version(new_version_str)
                    
                    if new_ver > curr_ver:
                        if not download_url:
                            print("Updater: Thieu download_url trong file cap nhat.")
                            return

                        if not is_valid_sha256(sha256):
                            print("Updater: Thieu hoac sai dinh dang SHA256 trong file cap nhat.")
                            return

                        # Cần dispatch callback về main/UI thread xử lý UI.
                        dispatch(callback, new_version_str, release_notes, download_url, sha256)
        except urllib.error.URLError:
            print("Updater: Network unavailable or server did not respond.")
        except json.JSONDecodeError:
            print("Updater: Invalid JSON format.")
        except Exception as e:
            print(f"Updater error: {e}")

    thread = threading.Thread(target=_check, daemon=True)
    thread.start()

def download_and_install_update(download_url, expected_sha256, progress_callback, success_callback, error_callback):
    if is_macos():
        error_callback("macOS su dung cap nhat thu cong: tai file zip moi va thay app hien tai.")
        return

    """Luồng tải file và cài đặt. Trả về tiến trình bằng progress_callback(percent)"""
    def _download():
        try:
            exe_path = sys.executable
            exe_dir = os.path.dirname(exe_path)
            exe_name = os.path.basename(exe_path)

            temp_download_path = os.path.join(
                os.environ.get('TEMP', exe_dir) if is_windows() else os.environ.get('TMPDIR', '/tmp'),
                f"{exe_name}.download"
            )
            new_exe_path = os.path.join(exe_dir, f"{exe_name}.new")

            for stale_path in (temp_download_path, new_exe_path):
                if os.path.exists(stale_path):
                    os.remove(stale_path)
            
            # Khởi tạo urllib tải file
            req = urllib.request.Request(
                download_url,
                headers={"User-Agent": "POD-Tools-Updater/1.0"}
            )
            
            with _urlopen(req, timeout=30) as response:
                total_size_header = response.getheader('Content-Length')
                try:
                    total_size = int(total_size_header.strip()) if total_size_header else 0
                except ValueError:
                    total_size = 0
                downloaded_size = 0
                block_size = 8192

                with open(temp_download_path, 'wb') as file:
                    while True:
                        buffer = response.read(block_size)
                        if not buffer:
                            break
                        file.write(buffer)
                        downloaded_size += len(buffer)
                        
                        if total_size > 0:
                            percent = min(100, int(downloaded_size * 100 / total_size))
                            progress_callback(percent)
                        else:
                            progress_callback(0)
                            
            # Checksum file sau khi tải
            if not is_valid_sha256(expected_sha256):
                os.remove(temp_download_path)
                error_callback("Thieu ma SHA256 hop le. Viec cap nhat bi huy de dam bao an toan.")
                return

            if expected_sha256:
                progress_callback(-1) # Trạng thái đang hash file
                sha_hash = hashlib.sha256()
                with open(temp_download_path, "rb") as f:
                    for byte_block in iter(lambda: f.read(4096), b""):
                        sha_hash.update(byte_block)
                file_hash = sha_hash.hexdigest()

                if file_hash.lower() != expected_sha256.lower():
                    os.remove(temp_download_path)
                    error_callback("File tải về bị lỗi (sai Checksum). Việc cập nhật bị huỷ tự động.")
                    return
            
            # Pre-flight Permission Check: Thử copy file tải về vào thư mục chứa app cũ
            try:
                shutil.move(temp_download_path, new_exe_path)
            except PermissionError:
                if os.path.exists(temp_download_path):
                    os.remove(temp_download_path)
                error_callback("Không có quyền ghi file. Vui lòng chạy ứng dụng bằng quyền Administrator (Run as Admin).")
                return
            except Exception as e:
                error_callback(f"Lỗi khi di chuyển file báo cáo: {str(e)}")
                return
            
            # Tạo script cập nhật theo platform
            if is_macos():
                script_path = _create_mac_update_script(exe_dir, exe_path, exe_name, new_exe_path)
            else:
                script_path = _create_windows_update_script(exe_dir, exe_path, exe_name, new_exe_path)

            # Đã tải và chuẩn bị xong, kích hoạt callback để tắt app
            success_callback(script_path)

        except urllib.error.URLError as e:
            error_callback(f"Lỗi kết nối khi tải bản cập nhật: {e.reason}")
        except Exception as e:
            error_callback(f"Có lỗi hệ thống xảy ra: {e}")

    thread = threading.Thread(target=_download, daemon=True)
    thread.start()

def cleanup_update_artifacts():
    """Xoa file tam con sot lai sau khi app da khoi dong lai thanh cong."""
    if not is_frozen():
        return

    exe_path = sys.executable
    exe_dir = os.path.dirname(exe_path)
    exe_name = os.path.basename(exe_path)
    max_age_seconds = 60 * 60
    now = time.time()

    temp_dir = os.environ.get("TEMP", exe_dir) if is_windows() else os.environ.get("TMPDIR", "/tmp")
    stale_paths = [
        os.path.join(exe_dir, f"{exe_name}.bak"),
        os.path.join(exe_dir, f"{exe_name}.new"),
        os.path.join(exe_dir, "updater.bat"),
        os.path.join(exe_dir, "updater.sh"),
        os.path.join(temp_dir, f"{exe_name}.download"),
    ]

    for stale_path in stale_paths:
        try:
            if os.path.exists(stale_path) and now - os.path.getmtime(stale_path) <= max_age_seconds:
                os.remove(stale_path)
        except Exception:
            pass

    safe_suffixes = (".tmp", ".crdownload", ".download")
    safe_prefixes = (exe_name, "updater", "Unconfirmed")

    for folder in {exe_dir, temp_dir}:
        try:
            for file_path in glob.glob(os.path.join(folder, "*")):
                file_name = os.path.basename(file_path)
                lower_name = file_name.lower()
                if lower_name.endswith(safe_suffixes) and file_name.startswith(safe_prefixes):
                    try:
                        if now - os.path.getmtime(file_path) <= max_age_seconds:
                            os.remove(file_path)
                    except Exception:
                        pass
        except Exception:
            pass

def _create_windows_update_script(exe_dir, exe_path, exe_name, new_exe_path):
    """Tạo batch script cập nhật cho Windows"""
    bat_path = os.path.join(exe_dir, "updater.bat")
    pid = os.getpid()
    bak_exe_path = os.path.join(exe_dir, f"{exe_name}.bak")

    bat_content = f"""@echo off
setlocal
echo Chuyen doi phien ban, vui long doi...
:: Doi de process exit
:wait
tasklist /FI "PID eq {pid}" | find "{pid}" >nul 2>&1
if "%ERRORLEVEL%"=="0" (
    timeout /t 1 /nobreak >nul
    goto wait
)

:: Xoa file bak neu có tu lan update truoc
if exist "{bak_exe_path}" del /f /q "{bak_exe_path}"

:: Copy backup de de phong update crash
rename "{exe_path}" "{exe_name}.bak"
if errorlevel 1 (
    echo Loi khi rename file cu. Dung qua trinh.
    exit /b 1
)

:: Dua file new thanh file chính
rename "{new_exe_path}" "{exe_name}"
if errorlevel 1 (
    echo Loi ghi de thu muc. Khoi phuc ban cu...
    rename "{exe_name}.bak" "{exe_name}"
    exit /b 1
)

:: Khoi dong lai app
set PYINSTALLER_RESET_ENVIRONMENT=1
start "" "{exe_path}"

:: Tu xoa script nay
(goto) 2>nul & del "%~f0"
"""
    with open(bat_path, "w") as f:
        f.write(bat_content)

    return bat_path

def _create_mac_update_script(exe_dir, exe_path, exe_name, new_exe_path):
    """Tạo shell script cập nhật cho macOS"""
    sh_path = os.path.join(exe_dir, "updater.sh")
    pid = os.getpid()
    bak_exe_path = os.path.join(exe_dir, f"{exe_name}.bak")

    sh_content = f"""#!/bin/bash
echo "Chuyen doi phien ban, vui long doi..."

# Doi de process exit
while kill -0 {pid} 2>/dev/null; do
    sleep 1
done

# Xoa file bak neu co tu lan update truoc
if [ -f "{bak_exe_path}" ]; then
    rm -f "{bak_exe_path}"
fi

# Backup file cu
mv "{exe_path}" "{bak_exe_path}"
if [ $? -ne 0 ]; then
    echo "Loi khi rename file cu. Dung qua trinh."
    exit 1
fi

# Dua file new thanh file chinh
mv "{new_exe_path}" "{exe_path}"
if [ $? -ne 0 ]; then
    echo "Loi ghi de. Khoi phuc ban cu..."
    mv "{bak_exe_path}" "{exe_path}"
    exit 1
fi

# Cap quyen thuc thi
chmod +x "{exe_path}"

# Xoa quarantine attribute (macOS Gatekeeper) de tranh bi chan
xattr -cr "{exe_path}" 2>/dev/null

# Khoi dong lai app
export PYINSTALLER_RESET_ENVIRONMENT=1
nohup "{exe_path}" >/dev/null 2>&1 &

# Tu xoa script nay
rm -f "$0"
"""
    with open(sh_path, "w") as f:
        f.write(sh_content)

    # Cấp quyền thực thi cho script
    os.chmod(sh_path, 0o755)

    return sh_path

def execute_updater_and_exit(script_path):
    """Khởi chạy file script ngầm và tắt hẳn ứng dụng hiện tại"""
    script_dir = os.path.dirname(script_path)

    if is_macos():
        subprocess.Popen(
            ['bash', script_path],
            cwd=script_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    else:
        subprocess.Popen(
            ['cmd.exe', '/c', script_path],
            creationflags=subprocess.CREATE_NO_WINDOW,
            cwd=script_dir
        )
    sys.exit(0)
