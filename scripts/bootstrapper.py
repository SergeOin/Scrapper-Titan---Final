#!/usr/bin/env python3
"""
TitanScraper Bootstrapper
Installs TitanScraper.exe and required browser to %LOCALAPPDATA%\\TitanScraper
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

# Terms and Conditions text
TERMS_TEXT = """
CONDITIONS GÉNÉRALES D'UTILISATION - TitanScraper

1. OBJET
TitanScraper est un outil de veille LinkedIn destiné à un usage interne 
professionnel. Il permet de collecter des posts LinkedIn publics pour 
identifier des opportunités commerciales.

2. CONDITIONS D'UTILISATION
En utilisant TitanScraper, vous acceptez de :
• Utiliser l'outil uniquement à des fins professionnelles internes
• Respecter les Conditions Générales d'Utilisation de LinkedIn
• Ne pas utiliser l'outil de manière massive ou automatisée excessive
• Respecter le RGPD et les réglementations sur les données personnelles
• Ne pas revendre ou redistribuer les données collectées

3. RESPONSABILITÉ
L'utilisateur est seul responsable de l'utilisation qu'il fait de l'outil
et des données collectées. Titan Partners décline toute responsabilité
en cas d'utilisation non conforme aux présentes conditions.

4. DONNÉES COLLECTÉES
L'outil collecte uniquement des données publiquement accessibles sur 
LinkedIn (posts, noms d'auteurs, entreprises). Aucune donnée privée 
n'est collectée.

5. DÉSINSTALLATION
Vous pouvez désinstaller TitanScraper à tout moment en supprimant le 
dossier %LOCALAPPDATA%\\TitanScraper

6. MODIFICATIONS
Ces conditions peuvent être modifiées à tout moment. L'utilisation 
continue de l'outil vaut acceptation des nouvelles conditions.

© 2025 Titan Partners - Tous droits réservés
"""


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
        dist_exe = script_dir / "dist" / "TitanScraper" / EXE_NAME
        if dist_exe.exists():
            return dist_exe
    return None


def get_bundled_internal_path() -> Path:
    """Get the path to the bundled _internal folder."""
    if getattr(sys, 'frozen', False):
        base_path = Path(sys._MEIPASS)
        bundled = base_path / "_internal"
        if bundled.exists():
            return bundled
        bootstrapper_dir = Path(sys.executable).parent
        nearby = bootstrapper_dir / "_internal"
        if nearby.exists():
            return nearby
    else:
        script_dir = Path(__file__).parent.parent
        dist_internal = script_dir / "dist" / "TitanScraper" / "_internal"
        if dist_internal.exists():
            return dist_internal
    return None


def show_message(title: str, message: str, error: bool = False):
    """Show a Windows message box."""
    try:
        import ctypes
        icon = 0x10 if error else 0x40
        ctypes.windll.user32.MessageBoxW(0, message, title, icon)
    except Exception:
        print(f"{title}: {message}")


def show_terms_window() -> bool:
    """Show terms and conditions window. Returns True if accepted."""
    try:
        import tkinter as tk
        from tkinter import ttk, scrolledtext
        
        accepted = [False]  # Use list to allow modification in nested function
        
        root = tk.Tk()
        root.title("TitanScraper - Conditions d'utilisation")
        root.geometry("600x520")
        root.resizable(False, False)
        root.configure(bg='#f0f4f8')
        
        # Center window
        root.eval('tk::PlaceWindow . center')
        
        # Logo/Title
        title_label = tk.Label(root, text="🔍 TitanScraper", font=("Segoe UI", 16, "bold"), 
                               bg='#f0f4f8', fg='#1e3a5f')
        title_label.pack(pady=(20, 5))
        
        subtitle = tk.Label(root, text="Veuillez lire et accepter les conditions d'utilisation", 
                           font=("Segoe UI", 10), bg='#f0f4f8', fg='#334155')
        subtitle.pack(pady=(0, 15))
        
        # Terms text area
        text_frame = tk.Frame(root, bg='#f0f4f8')
        text_frame.pack(padx=30, pady=5, fill='both', expand=True)
        
        text_area = scrolledtext.ScrolledText(text_frame, wrap=tk.WORD, width=65, height=18,
                                              font=("Consolas", 9), bg='white', fg='#1e293b')
        text_area.pack(fill='both', expand=True)
        text_area.insert(tk.END, TERMS_TEXT)
        text_area.config(state='disabled')
        
        # Checkbox
        check_var = tk.BooleanVar(value=False)
        check_frame = tk.Frame(root, bg='#f0f4f8')
        check_frame.pack(pady=10)
        
        checkbox = tk.Checkbutton(check_frame, 
                                  text="J'ai lu et j'accepte les conditions d'utilisation",
                                  variable=check_var, font=("Segoe UI", 10),
                                  bg='#f0f4f8', fg='#334155', 
                                  activebackground='#f0f4f8')
        checkbox.pack()
        
        # Buttons frame
        btn_frame = tk.Frame(root, bg='#f0f4f8')
        btn_frame.pack(pady=15)
        
        def on_accept():
            if check_var.get():
                accepted[0] = True
                root.destroy()
            else:
                show_message("Attention", 
                           "Vous devez cocher la case pour accepter les conditions d'utilisation.",
                           error=False)
        
        def on_cancel():
            accepted[0] = False
            root.destroy()
        
        cancel_btn = ttk.Button(btn_frame, text="Annuler", command=on_cancel, width=15)
        cancel_btn.pack(side='left', padx=10)
        
        accept_btn = ttk.Button(btn_frame, text="Accepter et installer", command=on_accept, width=20)
        accept_btn.pack(side='left', padx=10)
        
        # Handle window close
        root.protocol("WM_DELETE_WINDOW", on_cancel)
        
        root.mainloop()
        return accepted[0]
        
    except Exception as e:
        print(f"Error showing terms window: {e}")
        # Fallback to message box
        import ctypes
        result = ctypes.windll.user32.MessageBoxW(
            0, 
            "Acceptez-vous les conditions d'utilisation de TitanScraper?\n\n" +
            "L'outil est destiné à un usage interne professionnel uniquement.\n" +
            "Vous vous engagez à respecter les CGU de LinkedIn.",
            "TitanScraper - Conditions d'utilisation",
            0x04 | 0x20  # MB_YESNO | MB_ICONQUESTION
        )
        return result == 6  # IDYES


def show_progress_window():
    """Create a progress window using tkinter."""
    try:
        import tkinter as tk
        from tkinter import ttk
        
        root = tk.Tk()
        root.title("TitanScraper - Installation")
        root.geometry("500x220")
        root.resizable(False, False)
        root.configure(bg='#f0f4f8')
        
        # Center window
        root.eval('tk::PlaceWindow . center')
        
        # Logo/Title
        title_label = tk.Label(root, text="🔍 TitanScraper", font=("Segoe UI", 16, "bold"), 
                               bg='#f0f4f8', fg='#1e3a5f')
        title_label.pack(pady=(20, 5))
        
        label = tk.Label(root, text="Installation en cours...", font=("Segoe UI", 11),
                        bg='#f0f4f8', fg='#334155')
        label.pack(pady=5)
        
        # Progress bar
        progress_frame = tk.Frame(root, bg='#f0f4f8')
        progress_frame.pack(pady=15, padx=40, fill='x')
        
        progress = ttk.Progressbar(progress_frame, mode='determinate', length=420, maximum=100)
        progress.pack(fill='x')
        
        progress_label = tk.Label(root, text="0%", font=("Segoe UI", 9, "bold"),
                                 bg='#f0f4f8', fg='#1e3a5f')
        progress_label.pack()
        
        status_label = tk.Label(root, text="Préparation...", font=("Segoe UI", 9), 
                               bg='#f0f4f8', fg='#64748b')
        status_label.pack(pady=10)
        
        return root, status_label, progress, progress_label
    except Exception:
        return None, None, None, None


def update_status(status_label, text: str):
    """Update the status label."""
    if status_label:
        try:
            status_label.config(text=text)
            status_label.update()
        except Exception:
            pass
    print(text)


def update_progress(progress, progress_label, value: int):
    """Update the progress bar."""
    if progress and progress_label:
        try:
            progress['value'] = value
            progress_label.config(text=f"{value}%")
            progress.update()
            progress_label.update()
        except Exception:
            pass


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


def install_browsers(status_label=None, progress=None, progress_label=None):
    """Install Playwright Chromium browser."""
    update_status(status_label, "Téléchargement du navigateur Chromium...")
    update_progress(progress, progress_label, 30)
    
    try:
        # Set environment variable for browser installation path
        env = os.environ.copy()
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(BROWSERS_DIR)
        
        update_status(status_label, "Installation de Chromium (cela peut prendre quelques minutes)...")
        update_progress(progress, progress_label, 40)
        
        # Try to install using playwright CLI with system Python
        python_exe = sys.executable
        
        # First try direct playwright install
        result = subprocess.run(
            [python_exe, "-m", "playwright", "install", "chromium"],
            env=env,
            capture_output=True,
            text=True,
            timeout=600  # 10 minutes timeout
        )
        
        if result.returncode == 0:
            update_status(status_label, "Navigateur Chromium installé ✓")
            update_progress(progress, progress_label, 70)
            return True
        
        # Alternative: try with pip install playwright first
        update_status(status_label, "Installation de Playwright...")
        update_progress(progress, progress_label, 50)
        
        subprocess.run([python_exe, "-m", "pip", "install", "playwright"], 
                      capture_output=True, timeout=120)
        
        result2 = subprocess.run(
            [python_exe, "-m", "playwright", "install", "chromium"],
            env=env,
            capture_output=True,
            text=True,
            timeout=600
        )
        
        if result2.returncode == 0:
            update_status(status_label, "Navigateur Chromium installé ✓")
            update_progress(progress, progress_label, 70)
            return True
        
        # If all fails, log but don't fail completely
        print(f"Playwright install failed: {result2.stdout}\n{result2.stderr}")
        update_status(status_label, "⚠ Navigateur: sera téléchargé au premier lancement")
        update_progress(progress, progress_label, 70)
        return False
        
    except subprocess.TimeoutExpired:
        update_status(status_label, "⚠ Timeout - Le navigateur sera téléchargé plus tard")
        update_progress(progress, progress_label, 70)
        return False
    except Exception as e:
        print(f"Browser installation error: {e}")
        update_status(status_label, "⚠ Le navigateur sera téléchargé au premier lancement")
        update_progress(progress, progress_label, 70)
        return False


def main():
    """Main bootstrapper function."""
    
    # Step 1: Show terms and conditions
    if not show_terms_window():
        show_message("Installation annulée", 
                    "Vous devez accepter les conditions d'utilisation pour installer TitanScraper.",
                    error=False)
        sys.exit(0)
    
    # Step 2: Show progress window
    root, status_label, progress, progress_label = show_progress_window()
    
    try:
        # Create installation directory
        update_status(status_label, "Création du dossier d'installation...")
        update_progress(progress, progress_label, 5)
        INSTALL_DIR.mkdir(parents=True, exist_ok=True)
        BROWSERS_DIR.mkdir(parents=True, exist_ok=True)
        
        # Find the bundled exe
        update_status(status_label, "Recherche de TitanScraper.exe...")
        update_progress(progress, progress_label, 10)
        bundled_exe = get_bundled_exe_path()
        
        exe_path = INSTALL_DIR / EXE_NAME
        internal_path = INSTALL_DIR / "_internal"

        if bundled_exe and bundled_exe.exists():
            update_status(status_label, "Installation de TitanScraper...")
            update_progress(progress, progress_label, 15)
            shutil.copy2(bundled_exe, exe_path)
            
            # Copy _internal folder
            bundled_internal = get_bundled_internal_path()
            if bundled_internal and bundled_internal.exists():
                update_status(status_label, "Copie des fichiers internes...")
                update_progress(progress, progress_label, 20)
                if internal_path.exists():
                    shutil.rmtree(internal_path)
                shutil.copytree(bundled_internal, internal_path)
                update_status(status_label, "TitanScraper installé ✓")
            else:
                raise Exception("Dossier _internal non trouvé dans le package")
        else:
            raise Exception("TitanScraper.exe non trouvé dans le package")
        
        # Install Playwright browsers
        browser_ok = install_browsers(status_label, progress, progress_label)
        
        # Create desktop shortcut
        update_progress(progress, progress_label, 80)
        create_shortcut(status_label)
        update_status(status_label, "Raccourci bureau créé ✓")
        
        # Set environment variable for browsers path
        update_progress(progress, progress_label, 90)
        update_status(status_label, "Configuration de l'environnement...")
        
        # Create a config file with browsers path
        config_file = INSTALL_DIR / "config.env"
        config_file.write_text(f"PLAYWRIGHT_BROWSERS_PATH={BROWSERS_DIR}\n", encoding="utf-8")
        
        update_progress(progress, progress_label, 100)
        
        if browser_ok:
            update_status(status_label, "✓ Installation terminée avec succès !")
        else:
            update_status(status_label, "✓ Installation terminée !")
        
        # Wait a moment then launch
        if root:
            root.update()
            import time
            time.sleep(2)
        
        # Launch TitanScraper
        update_status(status_label, "Lancement de TitanScraper...")
        
        # Start the app with environment
        env = os.environ.copy()
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(BROWSERS_DIR)
        subprocess.Popen([str(exe_path)], cwd=str(INSTALL_DIR), env=env)
        
        if root:
            root.after(1500, root.destroy)
            root.mainloop()
        
    except Exception as e:
        error_msg = f"Erreur d'installation: {str(e)}"
        update_status(status_label, error_msg)
        show_message("Erreur", error_msg, error=True)
        if root:
            root.after(3000, root.destroy)
            root.mainloop()
        sys.exit(1)


if __name__ == "__main__":
    main()
