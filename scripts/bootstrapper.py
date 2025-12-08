#!/usr/bin/env python3
"""
TitanScraper Bootstrapper
Downloads and installs TitanScraper.exe and required browser to %LOCALAPPDATA%\TitanScraper
"""

import os
import sys
import json
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path

# GitHub release URL
GITHUB_REPO = "SergeOin/Scrapper-Titan---Final"
RELEASE_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
FALLBACK_DOWNLOAD_URL = "https://github.com/SergeOin/Scrapper-Titan---Final/releases/latest/download/TitanScraper.exe"

# Installation paths
INSTALL_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / "TitanScraper"
EXE_NAME = "TitanScraper.exe"
BROWSERS_DIR = INSTALL_DIR / "pw-browsers"


def show_message(title: str, message: str, error: bool = False):
    """Show a Windows message box."""
    try:
        import ctypes
        icon = 0x10 if error else 0x40  # MB_ICONERROR or MB_ICONINFORMATION
        ctypes.windll.user32.MessageBoxW(0, message, title, icon)
    except Exception:
        print(f"{title}: {message}")


def show_progress_window():
    """Create a simple progress window using tkinter."""
    try:
        import tkinter as tk
        from tkinter import ttk
        
        root = tk.Tk()
        root.title("TitanScraper - Installation")
        root.geometry("400x150")
        root.resizable(False, False)
        
        # Center window
        root.eval('tk::PlaceWindow . center')
        
        label = tk.Label(root, text="Installation de TitanScraper en cours...", font=("Segoe UI", 11))
        label.pack(pady=20)
        
        progress = ttk.Progressbar(root, mode='indeterminate', length=300)
        progress.pack(pady=10)
        progress.start(10)
        
        status_label = tk.Label(root, text="Préparation...", font=("Segoe UI", 9), fg="gray")
        status_label.pack(pady=5)
        
        return root, status_label, progress
    except Exception:
        return None, None, None


def update_status(status_label, text: str):
    """Update the status label."""
    if status_label:
        try:
            status_label.config(text=text)
            status_label.update()
        except Exception:
            pass
    print(text)


def download_file(url: str, dest: Path, status_label=None) -> bool:
    """Download a file from URL to destination."""
    try:
        update_status(status_label, f"Téléchargement: {dest.name}")
        
        # Create a request with headers to avoid 403
        req = urllib.request.Request(url, headers={
            'User-Agent': 'TitanScraper-Bootstrapper/1.0'
        })
        
        with urllib.request.urlopen(req, timeout=120) as response:
            with open(dest, 'wb') as f:
                shutil.copyfileobj(response, f)
        return True
    except Exception as e:
        print(f"Download error: {e}")
        return False


def get_latest_release_url() -> str:
    """Get the download URL for the latest release."""
    try:
        req = urllib.request.Request(RELEASE_API_URL, headers={
            'User-Agent': 'TitanScraper-Bootstrapper/1.0',
            'Accept': 'application/vnd.github.v3+json'
        })
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode())
            
        # Find the TitanScraper.exe asset
        for asset in data.get("assets", []):
            if asset.get("name") == "TitanScraper.exe":
                return asset.get("browser_download_url")
        
        # Fallback to tag-based URL
        tag = data.get("tag_name", "latest")
        return f"https://github.com/{GITHUB_REPO}/releases/download/{tag}/TitanScraper.exe"
    except Exception as e:
        print(f"Failed to get release info: {e}")
        return FALLBACK_DOWNLOAD_URL


def install_browsers(status_label=None) -> bool:
    """Install Playwright Chromium browser."""
    update_status(status_label, "Installation du navigateur Chromium...")
    
    try:
        # Set environment variable for browser path
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(BROWSERS_DIR)
        
        # Run playwright install chromium
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True,
            text=True,
            timeout=300,
            env={**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(BROWSERS_DIR)}
        )
        
        if result.returncode == 0:
            return True
        else:
            print(f"Browser install failed: {result.stderr}")
            # Try with the exe directly
            exe_path = INSTALL_DIR / EXE_NAME
            if exe_path.exists():
                result = subprocess.run(
                    [str(exe_path), "--install-browsers"],
                    capture_output=True,
                    timeout=300
                )
                return result.returncode == 0
            return False
    except subprocess.TimeoutExpired:
        print("Browser installation timed out")
        return False
    except Exception as e:
        print(f"Browser install error: {e}")
        return False


def create_shortcut(status_label=None):
    """Create a desktop shortcut."""
    update_status(status_label, "Création du raccourci bureau...")
    
    try:
        import winreg
        
        # Get desktop path
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 
                           r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as key:
            desktop = winreg.QueryValueEx(key, "Desktop")[0]
        
        shortcut_path = Path(desktop) / "TitanScraper.lnk"
        target = INSTALL_DIR / EXE_NAME
        
        # Use PowerShell to create shortcut
        ps_script = f'''
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("{shortcut_path}")
$Shortcut.TargetPath = "{target}"
$Shortcut.WorkingDirectory = "{INSTALL_DIR}"
$Shortcut.Description = "TitanScraper - LinkedIn Scraper"
$Shortcut.Save()
'''
        subprocess.run(["powershell", "-Command", ps_script], capture_output=True)
        return True
    except Exception as e:
        print(f"Shortcut creation failed: {e}")
        return False


def main():
    """Main bootstrapper function."""
    root, status_label, progress = show_progress_window()
    
    try:
        # Create installation directory
        update_status(status_label, "Création du dossier d'installation...")
        INSTALL_DIR.mkdir(parents=True, exist_ok=True)
        BROWSERS_DIR.mkdir(parents=True, exist_ok=True)
        
        # Check if already installed
        exe_path = INSTALL_DIR / EXE_NAME
        if exe_path.exists():
            update_status(status_label, "Mise à jour de TitanScraper...")
        else:
            update_status(status_label, "Installation de TitanScraper...")
        
        # Download the exe
        update_status(status_label, "Récupération de la dernière version...")
        download_url = get_latest_release_url()
        
        # Download to temp first
        temp_exe = INSTALL_DIR / "TitanScraper_new.exe"
        if download_file(download_url, temp_exe, status_label):
            # Replace old exe
            if exe_path.exists():
                try:
                    exe_path.unlink()
                except Exception:
                    pass
            temp_exe.rename(exe_path)
            update_status(status_label, "TitanScraper téléchargé ✓")
        else:
            # Try to copy from local dist folder (for local testing)
            local_exe = Path(__file__).parent.parent / "dist" / "TitanScraper.exe"
            if local_exe.exists():
                shutil.copy2(local_exe, exe_path)
                update_status(status_label, "TitanScraper copié depuis local ✓")
            else:
                raise Exception("Impossible de télécharger TitanScraper.exe")
        
        # Check if browsers are installed
        if not any(BROWSERS_DIR.glob("chromium-*")):
            if not install_browsers(status_label):
                update_status(status_label, "⚠️ Navigateur sera installé au premier lancement")
        else:
            update_status(status_label, "Navigateur Chromium déjà installé ✓")
        
        # Create desktop shortcut
        create_shortcut(status_label)
        
        # Launch TitanScraper
        update_status(status_label, "Lancement de TitanScraper...")
        if progress:
            progress.stop()
        
        subprocess.Popen([str(exe_path)], cwd=str(INSTALL_DIR))
        
        if root:
            root.after(1500, root.destroy)
            root.mainloop()
        
    except Exception as e:
        if progress:
            progress.stop()
        error_msg = f"Erreur d'installation: {str(e)}"
        update_status(status_label, error_msg)
        show_message("Erreur", error_msg, error=True)
        if root:
            root.after(3000, root.destroy)
            root.mainloop()
        sys.exit(1)


if __name__ == "__main__":
    main()
