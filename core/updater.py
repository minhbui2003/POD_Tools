import os
import sys
import json
import urllib.request
import urllib.error
import threading
import hashlib
import subprocess
import shutil

from core import config

def is_frozen():
    """Kiểm tra xem app đang chạy bằng file exe (đã build) hay đang chạy source code python"""
    return getattr(sys, "frozen", False)

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

def check_for_updates(root, on_update_found_callback):
    """
    Chạy ngầm kiểm tra cập nhật.
    root: Đối tượng Tkinter chính để gọi hàm callback về main thread (bằng root.after).
    on_update_found_callback: Hàm nhận (new_version, release_notes, download_url, sha256)
    """
    if not is_frozen():
        print("Dev Mode: Bỏ qua kiểm tra cập nhật tự động.")
        return

    def _check():
        try:
            req = urllib.request.Request(
                config.UPDATE_JSON_URL,
                headers={"User-Agent": "POD-Tools-Updater/1.0"}
            )
            # Timeout 5 giây để không treo luồng ngầm
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode('utf-8'))
                    
                    new_version_str = data.get("version", "0.0.0")
                    curr_ver = parse_version(config.CURRENT_VERSION)
                    new_ver = parse_version(new_version_str)
                    
                    if new_ver > curr_ver:
                        download_url = data.get("download_url")
                        release_notes = data.get("release_notes", "Bản cập nhật mới giúp tăng cường hiệu suất và sửa lỗi.")
                        sha256 = str(data.get("sha256", "")).strip().lower()
                        
                        if not download_url:
                            print("Updater: Thieu download_url trong file cap nhat.")
                            return

                        if not is_valid_sha256(sha256):
                            print("Updater: Thieu hoac sai dinh dang SHA256 trong file cap nhat.")
                            return

                            # Cần gọi callback về main thread xử lý UI
                        root.after(0, on_update_found_callback, new_version_str, release_notes, download_url, sha256)
        except urllib.error.URLError:
            print("Updater: Không có mạng hoặc server không phản hồi.")
        except json.JSONDecodeError:
            print("Updater: File JSON format không hợp lệ.")
        except Exception as e:
            print(f"Updater error: {e}")

    thread = threading.Thread(target=_check, daemon=True)
    thread.start()

def download_and_install_update(download_url, expected_sha256, progress_callback, success_callback, error_callback):
    """Luồng tải file và cài đặt. Trả về tiến trình bằng progress_callback(percent)"""
    def _download():
        try:
            exe_path = sys.executable
            exe_dir = os.path.dirname(exe_path)
            exe_name = os.path.basename(exe_path)
            
            temp_download_path = os.path.join(os.environ.get('TEMP', exe_dir), f"{exe_name}.download")
            new_exe_path = os.path.join(exe_dir, f"{exe_name}.new")

            for stale_path in (temp_download_path, new_exe_path):
                if os.path.exists(stale_path):
                    os.remove(stale_path)
            
            # Khởi tạo urllib tải file
            req = urllib.request.Request(
                download_url,
                headers={"User-Agent": "POD-Tools-Updater/1.0"}
            )
            
            with urllib.request.urlopen(req, timeout=10) as response:
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
                
            # Tạo batch script để rollback
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
start "" "{exe_path}"

:: Tu xoa script nay
(goto) 2>nul & del "%~f0"
"""
            with open(bat_path, "w") as f:
                f.write(bat_content)
                
            # Đã tải và chuẩn bị xong, kích hoạt callback để tắt app
            success_callback(bat_path)

        except urllib.error.URLError as e:
            error_callback(f"Lỗi kết nối khi tải bản cập nhật: {e.reason}")
        except Exception as e:
            error_callback(f"Có lỗi hệ thống xảy ra: {e}")

    thread = threading.Thread(target=_download, daemon=True)
    thread.start()

def execute_updater_and_exit(bat_path):
    """Khởi chạy file batch ngầm và tắt hẳn ứng dụng hiện tại"""
    bat_dir = os.path.dirname(bat_path)
    subprocess.Popen(
        ['cmd.exe', '/c', bat_path],
        creationflags=subprocess.CREATE_NO_WINDOW,
        cwd=bat_dir
    )
    sys.exit(0)
