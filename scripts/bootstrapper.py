#!/usr/bin/env python3
"""
TitanScraper Bootstrapper
Installs TitanScraper.exe and required browser to %LOCALAPPDATA%\TitanScraper
The TitanScraper.exe is bundled with this bootstrapper.
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

# Installation paths
INSTALL_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / "TitanScraper"
EXE_NAME = "TitanScraper.exe"
BROWSERS_DIR = INSTALL_DIR / "pw-browsers"


def get_bundled_exe_path() -> Path:
    """Get the path to the bundled TitanScraper.exe."""
    if getattr(sys, 'frozen', False):
        # Running as compiled exe - look for bundled file
        base_path = Path(sys._MEIPASS)
        bundled = base_path / EXE_NAME
        if bundled.exists():
            return bundled
        # Also check next to the bootstrapper
        bootstrapper_dir = Path(sys.executable).parent
        nearby = bootstrapper_dir / EXE_NAME
        if nearby.exists():
            return nearby
    else:
        # Running as script - look in dist folder
        script_dir = Path(__file__).parent.parent
        dist_exe = script_dir / "dist" / EXE_NAME
        if dist_exe.exists():
            return dist_exe
    return None


def show_message(title: str, message: str, error: bool = False):
    """Show a Windows message box."""
    try:
        import ctypes
        icon = 0x10 if error else 0x40
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
        root.geometry("420x180")
        root.resizable(False, False)
        root.configure(bg='#f0f4f8')
        
        # Center window
        root.eval('tk::PlaceWindow . center')
        
        # Logo/Title
        title_label = tk.Label(root, text="🔍 TitanScraper", font=("Segoe UI", 14, "bold"), 
                               bg='#f0f4f8', fg='#1e3a5f')
        title_label.pack(pady=(20, 5))
        
        label = tk.Label(root, text="Installation en cours...", font=("Segoe UI", 10),
                        bg='#f0f4f8', fg='#334155')
        label.pack(pady=5)
        
        progress = ttk.Progressbar(root, mode='indeterminate', length=320)
        progress.pack(pady=15)
        progress.start(10)
        
        status_label = tk.Label(root, text="Préparation...", font=("Segoe UI", 9), 
                               bg='#f0f4f8', fg='#64748b')
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
$Shortcut.Description = "TitanScraper - LinkedIn Scraper pour Titan Partners"
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
        
        # Find the bundled exe
        update_status(status_label, "Recherche de TitanScraper.exe...")
        bundled_exe = get_bundled_exe_path()
        
        exe_path = INSTALL_DIR / EXE_NAME
        
        if bundled_exe and bundled_exe.exists():
            update_status(status_label, "Installation de TitanScraper...")
            shutil.copy2(bundled_exe, exe_path)
            update_status(status_label, "TitanScraper installé ✓")
        else:
            raise Exception("TitanScraper.exe non trouvé dans le package")
        
        # Create desktop shortcut
        create_shortcut(status_label)
        update_status(status_label, "Raccourci créé ✓")
        
        # Launch TitanScraper
        update_status(status_label, "Lancement de TitanScraper...")
        if progress:
            progress.stop()
        
        # Start the app
        subprocess.Popen([str(exe_path)], cwd=str(INSTALL_DIR))
        
        update_status(status_label, "Installation terminée ! ✓")
        
        if root:
            root.after(2000, root.destroy)
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
