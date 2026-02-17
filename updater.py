"""自动更新模块

检查 GitHub Releases 获取最新版本，支持自动下载和重启更新。
"""
import os
import sys
import subprocess
import tempfile
import urllib.request
import json
import threading
from typing import Optional, Tuple, Callable

try:
    import customtkinter as ctk
    from tkinter import messagebox
except ImportError:
    pass

from version import VERSION, GITHUB_REPO, APP_NAME


class AutoUpdater:
    """自动更新器"""
    
    GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    
    def __init__(self, on_update_available: Optional[Callable] = None):
        self.on_update_available = on_update_available
        self.latest_version: Optional[str] = None
        self.download_url: Optional[str] = None
        self.release_notes: str = ""
    
    def check_for_updates(self, callback: Optional[Callable] = None):
        """在后台线程检查更新"""
        def _check():
            has_update, version, notes = self._fetch_latest_release()
            if callback:
                callback(has_update, version, notes)
        
        thread = threading.Thread(target=_check, daemon=True)
        thread.start()
    
    def _fetch_latest_release(self) -> Tuple[bool, str, str]:
        """获取最新发布版本"""
        try:
            req = urllib.request.Request(
                self.GITHUB_API,
                headers={"Accept": "application/vnd.github.v3+json", "User-Agent": APP_NAME}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
            
            tag_name = data.get("tag_name", "")
            self.latest_version = tag_name.lstrip('v')
            self.release_notes = data.get("body", "")
            
            for asset in data.get("assets", []):
                if asset["name"].endswith(".exe"):
                    self.download_url = asset["browser_download_url"]
                    break
            
            has_update = self._compare_versions(VERSION, self.latest_version)
            return has_update, self.latest_version, self.release_notes
            
        except Exception as e:
            print(f"检查更新失败: {e}")
            return False, VERSION, ""
    
    def _compare_versions(self, current: str, latest: str) -> bool:
        """比较版本号，返回是否有更新"""
        try:
            current_parts = [int(x) for x in current.split('.')]
            latest_parts = [int(x) for x in latest.split('.')]
            
            while len(current_parts) < len(latest_parts):
                current_parts.append(0)
            while len(latest_parts) < len(current_parts):
                latest_parts.append(0)
            
            return latest_parts > current_parts
        except (ValueError, AttributeError):
            return False
    
    def download_and_update(self, progress_callback: Optional[Callable] = None) -> bool:
        """下载更新并重启"""
        if not self.download_url:
            return False
        
        try:
            if getattr(sys, 'frozen', False):
                current_exe = sys.executable
            else:
                messagebox.showinfo("提示", "开发模式下不支持自动更新，请手动下载最新版本。")
                return False
            
            temp_dir = tempfile.gettempdir()
            new_exe = os.path.join(temp_dir, "telegram_sender_update.exe")
            
            def _download():
                try:
                    req = urllib.request.Request(
                        self.download_url,
                        headers={"User-Agent": APP_NAME}
                    )
                    with urllib.request.urlopen(req, timeout=120) as response:
                        total_size = int(response.headers.get('content-length', 0))
                        downloaded = 0
                        chunk_size = 8192
                        
                        with open(new_exe, 'wb') as f:
                            while True:
                                chunk = response.read(chunk_size)
                                if not chunk:
                                    break
                                f.write(chunk)
                                downloaded += len(chunk)
                                if progress_callback and total_size > 0:
                                    progress_callback(downloaded / total_size)
                    
                    self._create_update_script(current_exe, new_exe)
                    return True
                except Exception as e:
                    print(f"下载更新失败: {e}")
                    return False
            
            return _download()
            
        except Exception as e:
            print(f"更新失败: {e}")
            return False
    
    def _create_update_script(self, current_exe: str, new_exe: str):
        """创建更新脚本并执行"""
        batch_path = os.path.join(tempfile.gettempdir(), "update_telegram_sender.bat")
        
        script = f'''@echo off
echo 正在更新 {APP_NAME}...
timeout /t 2 /nobreak >nul
:retry
del "{current_exe}" >nul 2>&1
if exist "{current_exe}" (
    timeout /t 1 /nobreak >nul
    goto retry
)
copy /y "{new_exe}" "{current_exe}"
del "{new_exe}" >nul 2>&1
start "" "{current_exe}"
del "%~f0"
'''
        with open(batch_path, 'w', encoding='gbk') as f:
            f.write(script)
        
        subprocess.Popen(
            ['cmd', '/c', batch_path],
            creationflags=subprocess.CREATE_NO_WINDOW,
            close_fds=True
        )
        sys.exit(0)


class UpdateDialog(ctk.CTkToplevel):
    """更新提示对话框"""
    
    def __init__(self, parent, version: str, notes: str, updater: AutoUpdater):
        super().__init__(parent)
        
        self.updater = updater
        self.result = False
        
        self.title("发现新版本")
        self.geometry("450x320")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - 450) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 320) // 2
        self.geometry(f"+{x}+{y}")
        
        icon_label = ctk.CTkLabel(self, text="NEW", font=ctk.CTkFont(size=48))
        icon_label.pack(pady=(20, 10))
        
        title_label = ctk.CTkLabel(
            self, text=f"发现新版本 v{version}",
            font=ctk.CTkFont(size=20, weight="bold")
        )
        title_label.pack()
        
        current_label = ctk.CTkLabel(
            self, text=f"当前版本: v{VERSION}",
            font=ctk.CTkFont(size=12), text_color="gray"
        )
        current_label.pack(pady=(5, 10))
        
        if notes:
            notes_frame = ctk.CTkFrame(self, fg_color="transparent")
            notes_frame.pack(fill="x", padx=30, pady=10)
            
            notes_label = ctk.CTkLabel(
                notes_frame, text="更新内容:",
                font=ctk.CTkFont(size=12, weight="bold"), anchor="w"
            )
            notes_label.pack(anchor="w")
            
            notes_text = ctk.CTkTextbox(
                notes_frame, height=80,
                font=ctk.CTkFont(size=11), wrap="word"
            )
            notes_text.pack(fill="x", pady=(5, 0))
            notes_text.insert("1.0", notes[:500])
            notes_text.configure(state="disabled")
        
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=30, pady=20)
        
        self.update_btn = ctk.CTkButton(
            btn_frame, text="立即更新",
            font=ctk.CTkFont(size=14),
            fg_color="#3fb950", hover_color="#2ea043",
            width=140, height=38, command=self._on_update
        )
        self.update_btn.pack(side="left", expand=True)
        
        ctk.CTkButton(
            btn_frame, text="稍后提醒",
            font=ctk.CTkFont(size=14),
            fg_color="#30363d", hover_color="#484f58",
            width=140, height=38, command=self._on_cancel
        ).pack(side="right", expand=True)
        
        self.progress = ctk.CTkProgressBar(self, width=390, height=8)
        self.progress_label = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(size=11), text_color="gray"
        )
    
    def _on_update(self):
        """开始更新"""
        self.update_btn.configure(state="disabled", text="下载中...")
        self.progress.pack(padx=30, pady=(0, 5))
        self.progress.set(0)
        self.progress_label.pack()
        self.progress_label.configure(text="正在下载更新...")
        
        def do_update():
            def progress_cb(p):
                self.after(0, lambda: self.progress.set(p))
                self.after(0, lambda: self.progress_label.configure(text=f"下载进度: {int(p*100)}%"))
            
            success = self.updater.download_and_update(progress_cb)
            if not success:
                self.after(0, lambda: messagebox.showerror("错误", "更新失败，请稍后重试或手动下载。"))
                self.after(0, self.destroy)
        
        thread = threading.Thread(target=do_update, daemon=True)
        thread.start()
    
    def _on_cancel(self):
        """取消更新"""
        self.result = False
        self.destroy()


def check_for_updates_on_startup(app):
    """启动时检查更新（在主窗口显示后调用）"""
    updater = AutoUpdater()
    
    def on_check_complete(has_update, version, notes):
        if has_update:
            app.after(500, lambda: UpdateDialog(app, version, notes, updater))
    
    updater.check_for_updates(on_check_complete)
