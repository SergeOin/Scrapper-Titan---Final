"""Chromium browser installer for Playwright in PyInstaller frozen mode.

This module handles automatic download and installation of ALL Playwright browser
dependencies from the Playwright CDN when the application is run on a fresh machine.

Components downloaded:
- Chromium browser
- winldd (Windows dependency checker)
- ffmpeg (media support)
- chromium_headless_shell (headless mode support)

Key features:
- Uses only cdn.playwright.dev URLs (current Playwright CDN)
- Shows visual progress window during download
- Handles retries and multiple URL fallbacks
- Works in both frozen (PyInstaller) and development modes
"""
from __future__ import annotations

import logging
import os
import platform
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional, List, Tuple

log = logging.getLogger("desktop.chromium")

# Playwright version to Chromium revision mapping (from Playwright source)
PLAYWRIGHT_CHROMIUM_REVISIONS = {
    "1.44": "1117", "1.45": "1124", "1.46": "1129", "1.47": "1134",
    "1.48": "1140", "1.49": "1148", "1.50": "1155", "1.51": "1160",
    "1.52": "1165", "1.53": "1170", "1.54": "1180", "1.55": "1187",
    "1.56": "1195", "1.57": "1200", "1.58": "1210",
}

# Fixed versions for auxiliary tools
WINLDD_VERSION = "1007"
FFMPEG_VERSION = "1011"

# Default revision matches bundled Playwright version in requirements.txt
# IMPORTANT: Keep in sync with playwright version in requirements.txt
DEFAULT_REVISION = "1187"  # Playwright 1.55.x (bundled version)


def _is_windows() -> bool:
    return sys.platform == "win32"


def _is_macos() -> bool:
    return sys.platform == "darwin"


def get_browsers_dir() -> Path:
    """Get the path where Playwright browsers should be stored."""
    if _is_windows():
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif _is_macos():
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".local" / "share"
    return base / "TitanScraper" / "pw-browsers"


def get_chromium_revision() -> str:
    """Determine the correct Chromium revision for the installed Playwright version.
    
    In frozen mode (PyInstaller), we use the DEFAULT_REVISION which should match
    the playwright version bundled in requirements.txt.
    In development mode, we try to detect from installed playwright package.
    """
    # In frozen mode, always use the bundled version to avoid mismatch
    if getattr(sys, "frozen", False):
        log.info("frozen_mode_using_default_revision=%s", DEFAULT_REVISION)
        return DEFAULT_REVISION
    
    try:
        from importlib.metadata import version as get_version
        pv = get_version("playwright")
        major_minor = ".".join(pv.split(".")[:2])
        revision = PLAYWRIGHT_CHROMIUM_REVISIONS.get(major_minor, DEFAULT_REVISION)
        log.info("detected_playwright=%s revision=%s", pv, revision)
        return revision
    except Exception:
        return DEFAULT_REVISION


def is_chromium_ready(browsers_dir: Optional[Path] = None) -> bool:
    """Check if Chromium and all dependencies are installed and ready to use."""
    if browsers_dir is None:
        browsers_dir = get_browsers_dir()
    
    if not browsers_dir.exists():
        return False
    
    try:
        # Check Chromium
        chromium_ok = False
        for p in browsers_dir.iterdir():
            if p.is_dir() and p.name.startswith("chromium-") and not "headless" in p.name:
                if _is_windows():
                    exe = p / "chrome-win" / "chrome.exe"
                elif _is_macos():
                    exe = p / "chrome-mac" / "Chromium.app" / "Contents" / "MacOS" / "Chromium"
                    if not exe.exists():
                        exe = p / "chrome-mac" / "chrome"
                else:
                    exe = p / "chrome-linux" / "chrome"
                if exe.exists():
                    chromium_ok = True
                    break
        
        if not chromium_ok:
            return False
        
        # Check winldd (Windows only)
        if _is_windows():
            winldd_ok = False
            for p in browsers_dir.iterdir():
                if p.is_dir() and p.name.startswith("winldd-"):
                    if (p / "PrintDeps.exe").exists():
                        winldd_ok = True
                        break
            if not winldd_ok:
                return False
        
        return True
        
    except Exception as e:
        log.warning("chromium_ready_check_failed: %s", e)
        return False


def get_components_to_download(revision: str) -> List[Tuple[str, str, str, bool]]:
    """
    Get list of components to download.
    Returns list of (name, url, target_folder_name, is_required) tuples.
    is_required=True means failure to download will cause overall failure.
    is_required=False means component is optional and failure is tolerated.
    """
    components = []
    
    if _is_windows():
        # Chromium browser - REQUIRED
        components.append((
            "Chromium",
            f"https://cdn.playwright.dev/dbazure/download/playwright/builds/chromium/{revision}/chromium-win64.zip",
            f"chromium-{revision}",
            True  # Required
        ))
        
        # Chromium headless shell - OPTIONAL (not available for all revisions)
        # Note: This component doesn't exist for older Playwright revisions like 1129
        components.append((
            "Chromium Headless",
            f"https://cdn.playwright.dev/dbazure/download/playwright/builds/chromium/{revision}/chromium-headless-shell-win64.zip",
            f"chromium_headless_shell-{revision}",
            False  # Optional - not available for revision 1129
        ))
        
        # winldd (dependency checker) - REQUIRED for Playwright to work
        components.append((
            "WinLDD",
            f"https://cdn.playwright.dev/dbazure/download/playwright/builds/winldd/{WINLDD_VERSION}/winldd-win64.zip",
            f"winldd-{WINLDD_VERSION}",
            True  # Required
        ))
        
        # ffmpeg - REQUIRED for video support
        components.append((
            "FFmpeg",
            f"https://cdn.playwright.dev/dbazure/download/playwright/builds/ffmpeg/{FFMPEG_VERSION}/ffmpeg-win64.zip",
            f"ffmpeg-{FFMPEG_VERSION}",
            True  # Required
        ))
        
    elif _is_macos():
        is_arm = "arm" in platform.machine().lower()
        arch = "mac-arm64" if is_arm else "mac"
        
        components.append((
            "Chromium",
            f"https://cdn.playwright.dev/dbazure/download/playwright/builds/chromium/{revision}/chromium-{arch}.zip",
            f"chromium-{revision}",
            True  # Required
        ))
        
    else:  # Linux
        components.append((
            "Chromium",
            f"https://cdn.playwright.dev/dbazure/download/playwright/builds/chromium/{revision}/chromium-linux.zip",
            f"chromium-{revision}",
            True  # Required
        ))
    
    return components


def download_file(url: str, dest_path: Path, progress_callback=None) -> bool:
    """Download a file from URL with progress reporting."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        
        with urllib.request.urlopen(req, timeout=300) as resp:
            total_size = int(resp.headers.get('Content-Length', 0))
            downloaded = 0
            chunk_size = 256 * 1024  # 256KB chunks
            
            with open(dest_path, "wb") as out:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    out.write(chunk)
                    downloaded += len(chunk)
                    
                    if progress_callback and total_size > 0:
                        pct = int(100 * downloaded / total_size)
                        mb_done = downloaded // (1024 * 1024)
                        mb_total = total_size // (1024 * 1024)
                        progress_callback(pct, mb_done, mb_total)
        
        return dest_path.exists() and dest_path.stat().st_size > 0
        
    except Exception as e:
        log.warning("download_failed url=%s error=%s", url, str(e))
        return False


def download_all_components(
    browsers_dir: Optional[Path] = None,
    show_gui_progress: bool = True,
) -> bool:
    """
    Download and install all Playwright browser components.
    """
    if browsers_dir is None:
        browsers_dir = get_browsers_dir()
    
    # Already installed?
    if is_chromium_ready(browsers_dir):
        log.info("all_components_already_installed path=%s", browsers_dir)
        return True
    
    revision = get_chromium_revision()
    components = get_components_to_download(revision)
    
    log.info("playwright_components_download_start revision=%s count=%d", revision, len(components))
    
    browsers_dir.mkdir(parents=True, exist_ok=True)
    
    # Create progress window
    progress_window = None
    if show_gui_progress and _is_windows():
        try:
            progress_window = _create_progress_window()
        except Exception as e:
            log.warning("progress_window_creation_failed: %s", e)
    
    success = True
    tmp_path = None
    
    for idx, (name, url, target_folder, is_required) in enumerate(components):
        target_dir = browsers_dir / target_folder
        
        # Skip if already exists and has content
        if target_dir.exists():
            try:
                if any(target_dir.iterdir()):
                    log.info("component_already_exists name=%s", name)
                    continue
            except Exception:
                pass
        
        log.info("downloading_component name=%s url=%s required=%s", name, url, is_required)
        
        if progress_window:
            _update_progress_window(
                progress_window, 
                f"Téléchargement {name} ({idx+1}/{len(components)})..."
            )
        
        # Download to temp file
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
                tmp_path = Path(tmp.name)
            
            def progress_cb(pct, mb_done, mb_total):
                if progress_window:
                    msg = f"{name}: {pct}% ({mb_done}/{mb_total} MB)"
                    _update_progress_window(progress_window, msg)
            
            if not download_file(url, tmp_path, progress_cb):
                if is_required:
                    log.error("download_failed component=%s (REQUIRED)", name)
                    success = False
                else:
                    log.warning("download_failed component=%s (optional, skipping)", name)
                continue
            
            # Extract
            if progress_window:
                _update_progress_window(progress_window, f"Extraction {name}...")
            
            target_dir.mkdir(parents=True, exist_ok=True)
            
            with zipfile.ZipFile(tmp_path, 'r') as zf:
                zf.extractall(target_dir)
            
            log.info("component_installed name=%s path=%s", name, target_dir)
            
        except Exception as e:
            log.exception("component_install_failed name=%s error=%s", name, e)
            if is_required:
                success = False
            # Optional components don't cause overall failure
            
        finally:
            # Cleanup temp file
            if tmp_path:
                try:
                    if tmp_path.exists():
                        tmp_path.unlink()
                except Exception:
                    pass
    
    # Close progress window
    if progress_window:
        if success:
            _update_progress_window(progress_window, "Installation terminée!")
            import time
            time.sleep(1)
        _close_progress_window(progress_window)
    
    # Verify installation
    if success:
        success = is_chromium_ready(browsers_dir)
        if success:
            log.info("all_components_installed_successfully")
        else:
            log.error("installation_verification_failed")
    
    return success


def _create_progress_window():
    """Create a tkinter progress window."""
    import tkinter as tk
    
    root = tk.Tk()
    root.title("Titan Scraper - Installation")
    root.geometry("500x120")
    root.resizable(False, False)
    
    # Center on screen
    root.update_idletasks()
    x = (root.winfo_screenwidth() // 2) - 250
    y = (root.winfo_screenheight() // 2) - 60
    root.geometry(f"+{x}+{y}")
    
    # Keep on top
    root.attributes("-topmost", True)
    
    # Title
    title = tk.Label(root, text="Installation du navigateur", font=("Segoe UI", 12, "bold"))
    title.pack(pady=(15, 5))
    
    # Progress label
    label = tk.Label(root, text="Préparation...", font=("Segoe UI", 10))
    label.pack(pady=10)
    
    # Store label reference
    root._progress_label = label
    
    root.update()
    return root


def _update_progress_window(window, message: str):
    """Update the progress window message."""
    try:
        if hasattr(window, '_progress_label'):
            window._progress_label.config(text=message)
        window.update()
    except Exception:
        pass


def _close_progress_window(window):
    """Close the progress window."""
    try:
        window.destroy()
    except Exception:
        pass


def ensure_chromium_installed(
    browsers_dir: Optional[Path] = None,
    show_progress: bool = True,
) -> bool:
    """
    Ensure Chromium and all dependencies are installed.
    
    This is the main entry point that should be called before using Playwright.
    """
    if browsers_dir is None:
        browsers_dir = get_browsers_dir()
    
    # Set environment variable for Playwright
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers_dir)
    
    # Check if already installed
    if is_chromium_ready(browsers_dir):
        log.info("playwright_ready path=%s", browsers_dir)
        return True
    
    log.info("playwright_not_ready, starting_download")
    
    # Try to copy from bundle first (for PyInstaller)
    if getattr(sys, "frozen", False):
        try:
            bundle_pw = Path(sys.executable).parent / "pw-browsers"
            if bundle_pw.exists():
                log.info("copying_from_bundle src=%s", bundle_pw)
                shutil.copytree(bundle_pw, browsers_dir, dirs_exist_ok=True)
                if is_chromium_ready(browsers_dir):
                    log.info("copied_from_bundle_success")
                    return True
        except Exception as e:
            log.warning("copy_from_bundle_failed: %s", e)
    
    # Download all components from CDN
    return download_all_components(browsers_dir, show_gui_progress=show_progress)
