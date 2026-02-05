"""Desktop launcher for the Titan Scraper app.

Responsibilities:
- Ensure Playwright Chromium is available (best-effort auto-install once).
- Start the FastAPI/Uvicorn server in-process on a local port.
- Open a native WebView window (pywebview) pointing to the dashboard.
- Gracefully stop the server when the window closes.

Notes:
- This does not modify server behavior or file structure.
- Runs fine from source (python desktop/main.py) and when packaged with PyInstaller.
"""
from __future__ import annotations

# Force PyInstaller to include scrape_subprocess module (hidden import)
import scraper.scrape_subprocess as _scrape_subprocess_module  # noqa: F401
# Force PyInstaller to include worker module (hidden import for store_posts)
import scraper.worker as _worker_module  # noqa: F401

import os
import sys
import time
import socket
import threading
from dataclasses import dataclass
import logging
import ctypes
import ctypes.wintypes as wintypes  # type: ignore[attr-defined]
from pathlib import Path
import json
import threading as _threading

import asyncio
from typing import Any
import base64
import secrets

# =============================================================================
# CRITICAL: Set PLAYWRIGHT_BROWSERS_PATH BEFORE any playwright import happens.
# This must be done at module load time, before scraper/session.py imports playwright.
# =============================================================================
def _early_playwright_path_setup() -> None:
    """Configure Playwright browser path before any playwright import."""
    if sys.platform == "win32":
        user_base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "TitanScraper"
    elif sys.platform == "darwin":
        user_base = Path.home() / "Library" / "Application Support" / "TitanScraper"
    else:
        user_base = Path.home() / ".local" / "share" / "TitanScraper"
    browsers_dir = user_base / "pw-browsers"
    # Force set (not setdefault) to ensure it's always correct
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers_dir)

_early_playwright_path_setup()
# =============================================================================

try:
    import ctypes
    import ctypes.wintypes as _wt
except Exception:
    pass

# -----------------------
# Secure-ish credential storage helpers (Windows DPAPI)
# -----------------------
def _dpapi_protect(raw: bytes) -> bytes:
    """Protect bytes using Windows DPAPI (Current User scope). Fallback: return raw."""
    if not _is_windows():
        return raw
    try:
        class DATA_BLOB(ctypes.Structure):  # type: ignore
            _fields_ = [("cbData", _wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
        CryptProtectData = ctypes.windll.crypt32.CryptProtectData  # type: ignore[attr-defined]
        CryptProtectData.argtypes = [ctypes.POINTER(DATA_BLOB), _wt.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, _wt.DWORD, ctypes.POINTER(DATA_BLOB)]
        inp = DATA_BLOB(len(raw), ctypes.cast(ctypes.create_string_buffer(raw, len(raw)), ctypes.POINTER(ctypes.c_char)))
        out = DATA_BLOB()
        if CryptProtectData(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
            try:
                buf = ctypes.string_at(out.pbData, out.cbData)
                ctypes.windll.kernel32.LocalFree(out.pbData)  # type: ignore[attr-defined]
                return buf
            except Exception:
                return raw
        return raw
    except Exception:
        return raw

def _dpapi_unprotect(enc: bytes) -> bytes:
    if not _is_windows():
        return enc
    try:
        class DATA_BLOB(ctypes.Structure):  # type: ignore
            _fields_ = [("cbData", _wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
        CryptUnprotectData = ctypes.windll.crypt32.CryptUnprotectData  # type: ignore[attr-defined]
        CryptUnprotectData.argtypes = [ctypes.POINTER(DATA_BLOB), ctypes.POINTER(_wt.LPWSTR), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, _wt.DWORD, ctypes.POINTER(DATA_BLOB)]
        inp = DATA_BLOB(len(enc), ctypes.cast(ctypes.create_string_buffer(enc, len(enc)), ctypes.POINTER(ctypes.c_char)))
        out = DATA_BLOB()
        if CryptUnprotectData(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
            try:
                buf = ctypes.string_at(out.pbData, out.cbData)
                ctypes.windll.kernel32.LocalFree(out.pbData)  # type: ignore[attr-defined]
                return buf
            except Exception:
                return enc
        return enc
    except Exception:
        return enc

def _credentials_file(base_dir: Path) -> Path:
    return base_dir / "credentials.json"

def _load_saved_credentials(base_dir: Path) -> dict | None:
    p = _credentials_file(base_dir)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        if not data.get("auto_login"):
            return None
        email = data.get("email")
        pw_prot = data.get("password_protected")
        if not email or not pw_prot:
            return None
        try:
            raw = base64.b64decode(pw_prot)
        except Exception:
            return None
        pwd = _dpapi_unprotect(raw).decode("utf-8", errors="ignore")
        if not pwd:
            return None
        return {"email": email, "password": pwd, "version": data.get("version", 1)}
    except Exception:
        logging.getLogger("desktop").warning("credentials_load_failed", exc_info=True)
        return None

def _attempt_auto_login_if_configured(base_url: str, user_base: Path) -> bool:
    """Attempt a silent login using saved credentials if the current session is invalid.

    Returns True if login succeeded (session became valid), else False.
    """
    log = logging.getLogger("desktop")
    creds = _load_saved_credentials(user_base)
    if not creds:
        return False
    try:
        import requests
        # Re-check status quickly (avoid re-login if already valid)
        r = requests.get(f"{base_url}/api/session/status", timeout=3)
        if r.status_code == 200 and r.json().get("valid"):
            return True
        payload = {"email": creds["email"], "password": creds["password"]}
        resp = requests.post(f"{base_url}/api/session/login", data=payload, timeout=45)
        if resp.status_code == 200:
            # Confirm now valid
            st = requests.get(f"{base_url}/api/session/status", timeout=5)
            if st.status_code == 200 and st.json().get("valid"):
                log.info("auto_login_success email=%s", creds["email"])
                return True
        log.warning("auto_login_failed status=%s", resp.status_code if 'resp' in locals() else 'n/a')
    except Exception as exc:
        log.warning("auto_login_exception error=%s", exc)
    return False
import base64

try:
    import win32crypt  # type: ignore
except Exception:  # pragma: no cover
    win32crypt = None  # type: ignore


def _is_windows() -> bool:
    return sys.platform.startswith("win")


def _is_macos() -> bool:
    return sys.platform == "darwin"


def _project_root() -> Path:
    """Return the project root path to use for Python imports.

    Important: In a PyInstaller one-folder install, our Python packages (e.g. 'server', 'scraper')
    are located next to the executable (Path(sys.executable).parent), while PyInstaller runtime
    libraries live under the _MEIPASS/_internal directory. For imports like 'server.main', we must
    prioritize the executable directory rather than _MEIPASS.
    """
    if getattr(sys, "frozen", False):  # bundled
        try:
            return Path(sys.executable).parent
        except Exception:
            # Fallback to MEIPASS if available
            return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[1]


APP_INTERNAL_NAME = "TitanScraper"  # stable internal identifier for dirs / files
APP_DISPLAY_NAME = "Titan Scraper"  # user-facing name
APP_MUTEX_NAME = "Local\\TitanScraperMutex_v2"


def _acquire_windows_mutex(name: str = APP_MUTEX_NAME):
    """Acquire a named OS mutex on Windows to enforce single instance early.

    Returns a handle if acquired, or None if another instance holds it.
    """
    if not _is_windows():
        return None
    try:
        # Declare signatures
        CreateMutexW = ctypes.windll.kernel32.CreateMutexW  # type: ignore[attr-defined]
        CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        CreateMutexW.restype = wintypes.HANDLE
        GetLastError = ctypes.windll.kernel32.GetLastError  # type: ignore[attr-defined]
        # Create or open existing mutex
        handle = CreateMutexW(None, False, name)
        if not handle:
            return None
        # ERROR_ALREADY_EXISTS = 183
        if GetLastError() == 183:
            # Someone else holds it
            # Close our handle to avoid leak
            try:
                ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
            except Exception:
                pass
            return None
        return handle
    except Exception:
        return None


def _user_data_dir(app_name: str = APP_INTERNAL_NAME) -> Path:
    """Return a per-user writable data directory for runtime artifacts.

    - Windows: %LOCALAPPDATA%/TitanScraper
    - macOS: ~/Library/Application Support/TitanScraper
    - Linux/Other: ~/.local/share/TitanScraper
    """
    if _is_windows():
        base = os.getenv("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
        return Path(base) / app_name
    if _is_macos():
        return Path.home() / "Library" / "Application Support" / app_name
    return Path.home() / ".local" / "share" / app_name


def _ensure_macos_desktop_alias(app_name: str = APP_DISPLAY_NAME) -> None:
    """On macOS, create a Desktop alias to the .app bundle on first run (best-effort).

    This complements the DMG drag-to-Applications flow by ensuring a desktop shortcut
    is present after first launch. No-ops on non-macOS platforms.
    """
    if not _is_macos():
        return
    try:
        app_path = Path(sys.executable).resolve()
        # In a bundled app, sys.executable is .../TitanScraper.app/Contents/MacOS/TitanScraper
        app_bundle = app_path.parents[2] if app_path.name != "python" else None
        if not app_bundle or app_bundle.suffix != ".app":
            return
        desktop = Path.home() / "Desktop"
        if not desktop.exists():
            return
        alias = desktop / f"{app_name}.app"
        if alias.exists():
            return
        # Create a Finder alias via AppleScript for nicer UX than a plain symlink
        try:
            import subprocess
            osa = (
                "tell application \"Finder\" to make alias file to POSIX file \"%s\" at POSIX file \"%s\""
                % (str(app_bundle), str(desktop))
            )
            subprocess.run(["osascript", "-e", osa], check=False)
        except Exception:
            # Fallback: create a symbolic link
            try:
                alias.symlink_to(app_bundle)
            except Exception:
                pass
    except Exception:
        pass


# Ensure project root on sys.path so imports like server.main work in dev and packaged one-dir
ROOT = _project_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# Also include PyInstaller temp/runtime dir if present (helps locate bundled libs/resources)
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    _rt = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    if str(_rt) not in sys.path:
        sys.path.append(str(_rt))
    # Ensure current working directory is the executable directory so relative paths (e.g. server/templates)
    # continue to function even if the process was launched with a different CWD (common for MSI shortcuts).
    try:
        os.chdir(Path(sys.executable).parent)
    except Exception:
        pass
else:
    # In dev mode, also normalize CWD to project root if run from elsewhere
    try:
        if Path.cwd() != ROOT:
            os.chdir(ROOT)
    except Exception:
        pass

def _ensure_event_loop_policy():
    """Set a robust event loop policy.

    Playwright (and asyncio subprocess usage in general) requires a Proactor based loop on
    modern Windows Python versions. The previous implementation allowed selecting a selector
    loop via WIN_LOOP env which led to NotImplementedError in packaged mode when spawning
    subprocesses (observed in server.log). We now force Proactor on Windows. On non-Windows
    platforms default loop is retained.
    """
    if _is_windows():
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception:
            logging.getLogger("desktop").exception("event_loop_policy_set_failed")

# Ensure correct event loop policy early (after definition so symbol exists)
_ensure_event_loop_policy()


def _find_free_port(preferred: int = 8000, max_tries: int = 20) -> int:
    # Try preferred, otherwise grab an OS-assigned free port
    for port in [preferred] + [0] * (max_tries - 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    return preferred


def _acquire_single_instance_lock(port: int = 47654):
    """Try to acquire a simple single-instance lock by binding a localhost TCP port.

    Returns a bound socket to keep open for the process lifetime, or None if already in use.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", port))
        s.listen(1)
        return s
    except Exception:
        try:
            s.close()  # type: ignore
        except Exception:
            pass
        return None


def _read_last_server_info(base: Path) -> dict | None:
    p = base / "last_server.json"
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def _write_last_server_info(base: Path, host: str, port: int) -> None:
    try:
        (base).mkdir(parents=True, exist_ok=True)
        (base / "last_server.json").write_text(
            json.dumps({"host": host, "port": port, "pid": os.getpid()}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def _try_playwright_install(user_base: Path):
    """Best-effort ensure Chromium is available for Playwright.

    We direct Playwright to install browsers into a user-writable persistent folder inside
    the desktop data directory so that PyInstaller's ephemeral _MEIPASS path isn't used.
    Avoids re-download on every launch.
    """
    log = logging.getLogger("desktop")
    try:
        import importlib
        # Ensure env path stable & writable
        browsers_dir = user_base / "pw-browsers"
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(browsers_dir))
        
        is_frozen = getattr(sys, "frozen", False)  # True when running as PyInstaller bundle
        
        def _chromium_ready(path: Path) -> bool:
            """Check if Chromium browser is ready to use."""
            try:
                rev_dir = next((p for p in path.iterdir() if p.is_dir() and p.name.startswith("chromium-")), None)
                if not rev_dir:
                    return False
                # Check for chrome executable based on OS
                if _is_windows():
                    exe = rev_dir / "chrome-win" / "chrome.exe"
                elif _is_macos():
                    # macOS can have chrome-mac or Chromium.app structure
                    exe = rev_dir / "chrome-mac" / "Chromium.app" / "Contents" / "MacOS" / "Chromium"
                    if not exe.exists():
                        exe = rev_dir / "chrome-mac" / "chrome"
                else:
                    exe = rev_dir / "chrome-linux" / "chrome"
                return exe.exists()
            except Exception:
                return False

        if browsers_dir.exists() and _chromium_ready(browsers_dir):
            log.info("playwright_browsers_present skip_install path=%s", browsers_dir)
            return
        # If prebaked browsers shipped inside the bundle (pw-browsers) copy them first.
        try:
            bundle_pw = (Path(sys.executable).parent if is_frozen else _project_root()) / 'pw-browsers'
            if bundle_pw.exists() and not browsers_dir.exists():
                import shutil
                shutil.copytree(bundle_pw, browsers_dir)
                if _chromium_ready(browsers_dir):
                    log.info("playwright_browsers_copied_from_bundle path=%s", browsers_dir)
                    return
        except Exception:
            log.warning("playwright_copy_bundle_failed", exc_info=True)
        
        # In PyInstaller frozen mode, sys.executable is the bundled app, not Python.
        # Skip subprocess playwright install and go directly to HTTP fallback.
        if not is_frozen:
            # Trigger install only if playwright package importable and we have real Python
            try:
                import playwright  # noqa: F401
                from subprocess import run
                log.info("playwright_install_start target=%s", browsers_dir)
                browsers_dir.mkdir(parents=True, exist_ok=True)
                run([sys.executable, "-m", "playwright", "install", "chromium", "--with-deps"], check=False)
                # Post-check
                if _chromium_ready(browsers_dir):
                    log.info("playwright_install_complete")
                    return
                else:
                    log.warning("playwright_install_incomplete path=%s triggering_second_attempt", browsers_dir)
                    try:
                        from subprocess import run as _run
                        _run([sys.executable, "-m", "playwright", "install", "chromium"], check=False)
                        if _chromium_ready(browsers_dir):
                            log.info("playwright_second_attempt_success")
                            return
                        else:
                            log.error("playwright_second_attempt_failed path=%s", browsers_dir)
                    except Exception:
                        log.exception("playwright_second_attempt_exception")
            except Exception:
                log.warning("playwright_subprocess_install_failed", exc_info=True)
        else:
            log.info("playwright_frozen_mode detected, using HTTP fallback directly")

        # HTTP downloader fallback - always used in frozen mode, fallback otherwise
        if not _chromium_ready(browsers_dir):
            try:
                log.warning("playwright_http_fallback_start path=%s", browsers_dir)
                import re, zipfile, tempfile, urllib.request, shutil

                # Derive revision: existing incomplete dir name OR mapping by playwright version
                rev = None
                try:
                    existing = [p for p in browsers_dir.iterdir() if p.is_dir() and p.name.startswith("chromium-")]
                    if existing:
                        # pick the first; expect format chromium-1129
                        m = re.match(r"chromium-(\d+)", existing[0].name)
                        if m:
                            rev = m.group(1)
                except Exception:
                    pass
                if not rev:
                    # Fallback mapping for known Playwright versions (best-effort)
                    from importlib.metadata import version as _ver
                    try:
                        pv = _ver("playwright")
                    except Exception:
                        pv = "1.46.0"  # Match requirements.txt default
                    major_minor = ".".join(pv.split(".")[:2])
                    default_map = {
                        "1.44": "1117",
                        "1.45": "1124",
                        "1.46": "1129",
                        "1.47": "1134",
                        "1.48": "1140",
                        "1.49": "1148",
                        "1.50": "1155",
                        "1.51": "1160",
                        "1.52": "1165",
                        "1.53": "1170",
                        "1.54": "1180",
                        "1.55": "1187",
                        "1.56": "1195",
                    }
                    rev = default_map.get(major_minor, "1129")  # Default to 1.46.x (requirements.txt)

                if _is_windows():
                    zip_name = "chromium-win64.zip"
                    inner_folder = "chrome-win"  # expected inside zip
                elif _is_macos():
                    # Not fully tested; choose x64 vs arm64 simple heuristic
                    is_arm = ("arm" in platform.machine().lower())  # type: ignore
                    zip_name = "chromium-mac-arm64.zip" if is_arm else "chromium-mac.zip"
                    inner_folder = "chrome-mac"
                else:
                    zip_name = "chromium-linux.zip"
                    inner_folder = "chrome-linux"

                # Try multiple CDN URLs - Playwright changed their CDN structure
                urls_to_try = [
                    f"https://cdn.playwright.dev/dbazure/download/playwright/builds/chromium/{rev}/{zip_name}",
                    f"https://playwright.azureedge.net/builds/chromium/{rev}/{zip_name}",
                ]
                url = urls_to_try[0]  # Primary URL
                log.info("playwright_http_fallback_download url=%s rev=%s", url, rev)
                target_rev_dir = browsers_dir / f"chromium-{rev}"
                browsers_dir.mkdir(parents=True, exist_ok=True)
                if target_rev_dir.exists():
                    # If incomplete remove to avoid mixing
                    try:
                        shutil.rmtree(target_rev_dir)
                    except Exception:
                        pass
                target_rev_dir.mkdir(parents=True, exist_ok=True)

                with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
                    tmp_path = Path(tmp.name)
                try:
                    log.info("playwright_http_downloading to=%s", tmp_path)
                    
                    # Try multiple URLs in case one fails
                    download_success = False
                    for try_url in urls_to_try:
                        try:
                            log.info("playwright_trying_url url=%s", try_url)
                            req = urllib.request.Request(try_url, headers={"User-Agent": "Mozilla/5.0"})
                            with urllib.request.urlopen(req, timeout=180) as resp, open(tmp_path, "wb") as out:
                                total_size = int(resp.headers.get('Content-Length', 0))
                                downloaded = 0
                                chunk_size = 1024 * 1024  # 1MB chunks
                                while True:
                                    chunk = resp.read(chunk_size)
                                    if not chunk:
                                        break
                                    out.write(chunk)
                                    downloaded += len(chunk)
                                    if total_size > 0:
                                        pct = int(100 * downloaded / total_size)
                                        log.info("playwright_download_progress %d%% (%d/%d MB)", pct, downloaded // (1024*1024), total_size // (1024*1024))
                            if tmp_path.stat().st_size > 10_000_000:  # At least 10MB
                                download_success = True
                                log.info("playwright_http_download_complete size=%d url=%s", tmp_path.stat().st_size, try_url)
                                break
                        except Exception as e:
                            log.warning("playwright_url_failed url=%s error=%s", try_url, str(e))
                            continue
                    
                    if not download_success:
                        log.error("playwright_all_urls_failed")
                        raise RuntimeError("All download URLs failed")
                    
                    # Extract
                    with zipfile.ZipFile(tmp_path, 'r') as zf:
                        zf.extractall(target_rev_dir)
                    # Verify extraction - check for chrome executable based on OS
                    if _is_windows():
                        chrome_exe = target_rev_dir / inner_folder / "chrome.exe"
                    elif _is_macos():
                        # macOS Chromium structure
                        chrome_exe = target_rev_dir / inner_folder / "Chromium.app" / "Contents" / "MacOS" / "Chromium"
                        if not chrome_exe.exists():
                            chrome_exe = target_rev_dir / inner_folder / "chrome"
                    else:
                        chrome_exe = target_rev_dir / inner_folder / "chrome"
                    
                    if chrome_exe.exists():
                        log.info("playwright_http_fallback_success exe=%s", chrome_exe)
                        # On Unix, ensure executable permissions
                        if not _is_windows():
                            try:
                                chrome_exe.chmod(0o755)
                            except Exception:
                                pass
                    else:
                        log.error("playwright_http_fallback_missing_exe expected=%s", chrome_exe)
                        # List what was extracted for debugging
                        try:
                            extracted = list(target_rev_dir.rglob("*"))[:20]
                            log.error("playwright_extracted_files sample=%s", [str(f) for f in extracted])
                        except Exception:
                            pass
                finally:
                    try:
                        if tmp_path.exists():
                            tmp_path.unlink()
                    except Exception:
                        pass
            except Exception:
                log.exception("playwright_http_fallback_failed")
    except Exception:
        log.warning("playwright_install_failed", exc_info=True)


@dataclass
class ServerHandle:
    server: Any  # uvicorn.Server, but avoid importing just for typing here
    thread: threading.Thread


def _start_server_thread(host: str, port: int) -> ServerHandle:
    import uvicorn
    # Import the FastAPI app directly to avoid dynamic re-import issues in frozen builds
    from server.main import app as fastapi_app

    config = uvicorn.Config(
        fastapi_app,
        host=host,
        port=port,
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
        # Avoid Uvicorn default logging config which may access sys.stderr.isatty in GUI mode
        log_config=None,
        access_log=False,
        # No reload in packaged app
        reload=False,
        workers=1,
    )
    server = uvicorn.Server(config)

    def _run():
        try:
            _ensure_event_loop_policy()
            # Blocks until should_exit is true
            asyncio.run(server.serve())
        except Exception:
            logging.getLogger("desktop").exception("Uvicorn server crashed")

    t = threading.Thread(target=_run, name="uvicorn-thread", daemon=True)
    t.start()
    return ServerHandle(server=server, thread=t)


def _wait_for_server(url: str, timeout: float = 20.0) -> bool:
    import requests

    t0 = time.perf_counter()
    last_err = None
    health = url.rstrip("/") + "/health"
    while time.perf_counter() - t0 < timeout:
        try:
            r = requests.get(health, timeout=1.5)
            if r.status_code == 200:
                return True
        except Exception as e:  # noqa: F841
            last_err = e
        time.sleep(0.25)
    return False


def _probe_health(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        import requests

        r = requests.get(f"http://{host}:{port}/health", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def _determine_initial_view(base_url: str, *, timeout: float = 4.0) -> str:
    """Decide which route the desktop window should open first.

    Returns ``"/"`` when the LinkedIn session looks valid, otherwise returns the login route with
    a reason query parameter. Any network errors fall back to the dashboard to avoid blocking the
    UI on transient issues.
    """
    log = logging.getLogger("desktop")
    # Fast local heuristic: if storage_state.json missing => login
    storage_state = os.environ.get("STORAGE_STATE")
    if storage_state and not Path(storage_state).exists():
        log.info("initial_view_no_storage_state redirect_login path=%s", storage_state)
        return "/login?reason=session_required"
    try:
        import requests
        resp = requests.get(f"{base_url}/api/session/status", timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("valid"):
                log.info(
                    "session_status_valid cookies=%s has_li_at=%s has_jsessionid=%s",
                    data.get("cookies_count"),
                    data.get("has_li_at"),
                    data.get("has_jsessionid"),
                )
                return "/"
            # Decide more precise reason
            reason = "session_required"
            if data.get("li_at_expired"):
                reason = "session_expired"
            log.info(
                "session_status_invalid_redirect cookies=%s has_li_at=%s reason=%s",
                data.get("cookies_count"), data.get("has_li_at"), reason
            )
            return f"/login?reason={reason}"
        log.warning("session_status_unexpected_status status=%s", resp.status_code)
        return "/login?reason=probe_http_%s" % resp.status_code
    except Exception as exc:
        # Force login instead of silently allowing dashboard
        log.warning("session_status_probe_failed forcing_login error=%s", exc)
        return "/login?reason=probe_error"
    # Should not reach; safe fallback is login
    return "/login?reason=unknown"


# ----------------------------
# Credentials (desktop auto-login)
# ----------------------------
def _dpapi_protect(raw: bytes) -> str:
    """Protect bytes using Windows DPAPI; returns base64 string. Fallback: base64(clear)."""
    if win32crypt is None or not _is_windows():  # pragma: no cover - non Windows path
        return base64.b64encode(raw).decode("utf-8")
    try:  # type: ignore[attr-defined]
        import win32crypt as _w
        blob = _w.CryptProtectData(raw, None, None, None, None, 0)
        return base64.b64encode(blob[1]).decode("utf-8")
    except Exception:
        return base64.b64encode(raw).decode("utf-8")


def _dpapi_unprotect(token: str) -> bytes | None:
    if not token:
        return None
    data = base64.b64decode(token)
    if win32crypt is None or not _is_windows():  # pragma: no cover
        return data
    try:  # type: ignore[attr-defined]
        import win32crypt as _w
        blob = _w.CryptUnprotectData(data, None, None, None, 0)
        return blob[1]
    except Exception:
        return data


def _credentials_file(user_base: Path) -> Path:
    return user_base / "credentials.json"


def _load_saved_credentials(user_base: Path) -> dict | None:
    p = _credentials_file(user_base)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        if not data.get("auto_login"):
            return None
        email = data.get("email")
        pwd_token = data.get("password_protected")
        if not email or not pwd_token:
            return None
        dec = _dpapi_unprotect(pwd_token)
        if not dec:
            return None
        password = dec.decode("utf-8", errors="ignore")
        return {"email": email, "password": password}
    except Exception:
        return None


def _attempt_auto_login_if_configured(user_base: Path, base_url: str, timeout: float = 25.0) -> bool:
    """If credentials.json exists with auto_login=true, try a one-shot login.

    Returns True if session became valid afterwards, else False. Silent on all exceptions.
    """
    creds = _load_saved_credentials(user_base)
    log = logging.getLogger("desktop")
    if not creds:
        return False
    try:
        import requests
        log.info("auto_login_attempt_start email=%s", creds.get("email"))
        resp = requests.post(
            f"{base_url}/api/session/login",
            data={"email": creds["email"], "password": creds["password"]},
            timeout=timeout,
        )
        if resp.status_code != 200:
            log.warning("auto_login_failed status=%s", resp.status_code)
            return False
        # Re-check session validity
        check = requests.get(f"{base_url}/api/session/status", timeout=6)
        if check.status_code == 200 and check.json().get("valid"):
            log.info("auto_login_success")
            return True
        log.warning("auto_login_post_check_invalid")
    except Exception as exc:  # pragma: no cover - best effort
        log.warning("auto_login_exception error=%s", exc)
    return False


def _ensure_runtime_dirs(base: Path):
    # Create runtime artifact folders (user-writable)
    for p in [base / "exports", base / "screenshots", base / "traces", base / "logs"]:
        try:
            p.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass


def _setup_logging(base: Path) -> None:
    log_dir = base / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    log_file = log_dir / "desktop.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )
    frozen = bool(getattr(sys, "frozen", False))
    exe_dir = Path(sys.executable).parent if frozen else "n/a"
    logging.getLogger("desktop").info(
        "Desktop launcher starting... ROOT=%s EXE_DIR=%s FROZEN=%s",
        ROOT,
        exe_dir,
        frozen,
    )


def _message_box(title: str, text: str) -> None:
    if _is_windows():
        try:
            ctypes.windll.user32.MessageBoxW(0, text, title, 0x00000040)  # MB_ICONINFORMATION
        except Exception:
            pass


def _webview2_runtime_installed() -> bool:
    """Detect presence of Edge WebView2 runtime on Windows via registry.

    Checks per-machine and per-user keys.
    """
    if not _is_windows():
        return True
    try:
        import winreg

        guid = r"{F1B5F0A6-C3B0-4AB5-9D24-BA61A1B3C047}"
        reg_checks: list[tuple[int, str, int]] = [
            (winreg.HKEY_CURRENT_USER, fr"SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\{guid}", winreg.KEY_READ),
            (winreg.HKEY_LOCAL_MACHINE, fr"SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\{guid}", winreg.KEY_READ),
        ]

        # Include alternate registry views (32/64-bit) commonly used by the WebView2 installer
        if hasattr(winreg, "KEY_WOW64_32KEY"):
            reg_checks.append(
                (
                    winreg.HKEY_LOCAL_MACHINE,
                    fr"SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\{guid}",
                    winreg.KEY_READ | winreg.KEY_WOW64_32KEY,
                )
            )
        if hasattr(winreg, "KEY_WOW64_64KEY"):
            reg_checks.append(
                (
                    winreg.HKEY_LOCAL_MACHINE,
                    fr"SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\{guid}",
                    winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
                )
            )
            reg_checks.append(
                (
                    winreg.HKEY_LOCAL_MACHINE,
                    fr"SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients\\{guid}",
                    winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
                )
            )

        for root, path, access in reg_checks:
            try:
                with winreg.OpenKey(root, path, 0, access):
                    return True
            except FileNotFoundError:
                continue
            except OSError:
                continue

    except ImportError:
        return False
    except Exception:
        logging.getLogger("desktop").warning("webview2_registry_probe_failed", exc_info=True)

    # Fallback: detect the runtime files on disk
    candidates: list[Path] = []
    for env_var in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        base = os.environ.get(env_var)
        if not base:
            continue
        candidates.append(Path(base) / "Microsoft" / "EdgeWebView" / "Application")
        candidates.append(Path(base) / "Microsoft" / "EdgeWebView" / "EBWebView")

    for base in candidates:
        try:
            if not base.exists():
                continue
            for child in base.iterdir():
                if not child.is_dir():
                    continue
                exe = child / "msedgewebview2.exe"
                if exe.exists():
                    return True
        except FileNotFoundError:
            continue
        except PermissionError:
            continue
        except Exception:
            logging.getLogger("desktop").debug("webview2_filesystem_probe_error base=%s", base, exc_info=True)

    return False


def _install_webview2_if_missing(exe_base: Path, user_base: Path) -> bool:
    """Install WebView2 runtime (Windows) if absent.

    Returns ``True`` when the runtime is detected at the end of the routine (including when it
    was already installed). Returns ``False`` if we were unable to detect WebView2 after the
    attempted installation. Always returns ``True`` on non-Windows platforms.
    """
    if not _is_windows():
        return True
    if _webview2_runtime_installed():
        return True
    log = logging.getLogger("desktop")
    marker = user_base / "webview2_install_marker.json"
    if marker.exists():
        try:
            import json as _json

            data = _json.loads(marker.read_text(encoding="utf-8"))
            ts = float(data.get("ts", 0))
            if time.time() - ts < 24 * 3600 and _webview2_runtime_installed():
                log.info("webview2_recent_attempt_skip")
                return True
        except Exception:
            pass

    try:
        candidates: list[Path] = []
        meipass = Path(getattr(sys, "_MEIPASS", exe_base))  # type: ignore[attr-defined]
        candidates.append(exe_base / "_internal" / "MicrosoftEdgeWebView2Setup.exe")
        candidates.append(exe_base / "MicrosoftEdgeWebView2Setup.exe")
        candidates.append(meipass / "MicrosoftEdgeWebView2Setup.exe")
        candidates.append(_project_root() / "build" / "MicrosoftEdgeWebView2Setup.exe")
        setup = next((p for p in candidates if p.exists()), None)
        if not setup:
            _message_box(
                APP_DISPLAY_NAME,
                (
                    "Composant Microsoft Edge WebView2 manquant et installateur introuvable.\n"
                    "Veuillez installer manuellement 'Microsoft Edge WebView2 Runtime' puis relancer l'application."
                ),
            )
            return False

        progress_close: callable | None = None
        progress_root = None  # type: ignore
        progress_var = None
        try:
            import tkinter as tk
            from tkinter import ttk

            def _open_progress():  # pragma: no cover (UI helper)
                root = tk.Tk()
                root.title(f"{APP_DISPLAY_NAME} - WebView2")
                root.geometry("420x140")
                root.resizable(False, False)
                lbl = ttk.Label(root, text="Installation de WebView2 en cours...", anchor="center", wraplength=400)
                lbl.pack(pady=12)
                local_var = tk.IntVar(value=0)
                pb = ttk.Progressbar(root, mode="determinate", maximum=100, variable=local_var)
                pb.pack(fill="x", padx=16, pady=8)
                note = ttk.Label(root, text="Une seule fois. Merci de patienter.", foreground="#555")
                note.pack(pady=(0, 8))
                root.update_idletasks()
                return root, local_var

            _progress_root, progress_var = _open_progress()
            progress_root = _progress_root

            def _close():
                try:
                    _progress_root.destroy()
                except Exception:
                    pass

            progress_close = _close
        except Exception:
            progress_close = None  # fallback to no progress window

        import subprocess
        import threading as _th

        done_flag = {"done": False, "returncode": None, "error": None}

        def _run_install():
            try:
                result = subprocess.run([str(setup), "/silent", "/install"], check=False)
                done_flag["returncode"] = getattr(result, "returncode", None)
            except Exception as exc:
                done_flag["error"] = str(exc)
            finally:
                done_flag["done"] = True

        t = _th.Thread(target=_run_install, daemon=True)
        t.start()

        start = time.time()
        tick = 0
        while time.time() - start < 90:
            if _webview2_runtime_installed():
                break
            if done_flag["done"]:
                time.sleep(2)
                if _webview2_runtime_installed():
                    break
            try:
                if progress_root is not None:
                    tick += 1
                    if progress_var is not None:
                        cur = progress_var.get()
                        if cur < 95:
                            progress_var.set(min(95, cur + 1))
                    progress_root.update()
            except Exception:
                progress_root = None
            time.sleep(0.4)

        if progress_close:
            try:
                if progress_var is not None and progress_root is not None:
                    progress_var.set(100)
                    progress_root.update()
                progress_close()
            except Exception:
                pass

        try:
            marker.write_text('{"ts": %f}' % time.time(), encoding="utf-8")
        except Exception:
            pass

        installed = _webview2_runtime_installed()
        if not installed:
            if progress_close:
                try:
                    progress_close()
                except Exception:
                    pass
            log.warning(
                "webview2_silent_install_failed returncode=%s error=%s",
                done_flag.get("returncode"),
                done_flag.get("error"),
            )
            _message_box(
                APP_DISPLAY_NAME,
                (
                    "L'installation automatique de WebView2 n'a pas abouti. "
                    "Une fenêtre officielle Microsoft va s'ouvrir pour terminer l'installation."
                ),
            )
            try:
                subprocess.run([str(setup), "/install"], check=False)
            except Exception:
                log.exception("webview2_manual_install_failed_to_launch")
            # Grace period for interactive install to finish
            for _ in range(30):
                if _webview2_runtime_installed():
                    installed = True
                    break
                time.sleep(1.0)
            if not installed:
                try:
                    import webbrowser

                    webbrowser.open("https://go.microsoft.com/fwlink/p/?LinkId=2124703")
                except Exception:
                    log.warning("webview2_manual_download_open_failed", exc_info=True)

        log.info("webview2_install_complete present=%s", installed)
        return installed
    except Exception:
        log.exception("Failed to install WebView2")
        return _webview2_runtime_installed()


def main():
    user_base = _user_data_dir()
    _ensure_runtime_dirs(user_base)
    _setup_logging(user_base)
    _ensure_event_loop_policy()
    log = logging.getLogger("desktop")
    # Best-effort desktop alias on macOS for convenience
    try:
        _ensure_macos_desktop_alias()
    except Exception:
        pass

    # Diagnostic: log PID & PPID early
    try:
        ppid = os.getppid()
    except Exception:
        ppid = -1
    log.info("process_start pid=%s ppid=%s", os.getpid(), ppid)

    # Launch storm guard: prevent runaway spawning (e.g. if a shortcut triggers loops)
    try:
        storm_file = user_base / "launch_storm.json"
        now = time.time()
        launches = []
        if storm_file.exists():
            try:
                launches = json.loads(storm_file.read_text(encoding="utf-8"))
            except Exception:
                launches = []
        # Keep only last 30s
        launches = [t for t in launches if (now - float(t)) <= 30.0]
        launches.append(now)
        storm_file.write_text(json.dumps(launches), encoding="utf-8")
        if len(launches) > 8:  # >8 launches inside 30s -> abort to stop explosion
            log.error("launch_storm_abort count=%s window=30s", len(launches))
            _message_box(
                APP_DISPLAY_NAME,
                "Trop de tentatives de lancement en moins de 30 secondes (boucle détectée). L'application s'arrête pour protection.",
            )
            return
    except Exception:
        log.warning("launch_storm_guard_failed", exc_info=True)

    # Hard single-instance guard using a Windows named mutex (prevents burst multi-launch)
    _mutex_handle = _acquire_windows_mutex()
    if _mutex_handle is None and _is_windows():
        # Silent exit: another instance already holds the mutex.
        log.warning("win_named_mutex_denied_exit pid=%s silent_exit", os.getpid())
        return

    # Ensure Playwright uses a stable, user-writable browser cache directory from the very beginning
    # (must be set before any Playwright import occurs; avoids defaulting to the ephemeral _MEIPASS path)
    browsers_dir = user_base / "pw-browsers"
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(browsers_dir))

    # Desktop defaults (can be overridden by env)
    os.environ.setdefault("DESKTOP_APP", "1")
    # Per-launch secret used to protect localhost endpoints against CSRF / drive-by POSTs.
    # Sent by the embedded dashboard (same process) via X-Desktop-Trigger.
    if not os.environ.get("DESKTOP_TRIGGER_KEY"):
        os.environ["DESKTOP_TRIGGER_KEY"] = secrets.token_urlsafe(32)
    os.environ.setdefault("APP_HOST", "127.0.0.1")
    # Pick a free port if 8000 busy
    port = _find_free_port(int(os.environ.get("APP_PORT") or os.environ.get("PORT") or 8000))
    os.environ["APP_PORT"] = str(port)
    # Reduce startup noise for a desktop UX
    os.environ.setdefault("LOG_LEVEL", "INFO")
    # Prefer in-process autonomous worker
    os.environ.setdefault("INPROCESS_AUTONOMOUS", "1")
    # Enable the in-process autonomous worker by providing a sensible default interval
    # Without this, AUTONOMOUS_WORKER_INTERVAL_SECONDS=0 disables any background scraping
    # leading to "scraper actif" UI state but no cycles executed.
    os.environ.setdefault("AUTONOMOUS_WORKER_INTERVAL_SECONDS", "60")  # run a cycle every 60s by default
    # Keep dashboard private by default in desktop mode
    os.environ.setdefault("DASHBOARD_PUBLIC", "0")
    # Speed optimizations: disable remote backends by default in packaged desktop (avoid connection timeouts)
    os.environ.setdefault("DISABLE_REDIS", "1")

    # Point runtime artifacts to user-writable locations
    os.environ.setdefault("SCREENSHOT_DIR", str(user_base / "screenshots"))
    os.environ.setdefault("TRACE_DIR", str(user_base / "traces"))
    os.environ.setdefault("CSV_FALLBACK_FILE", str(user_base / "exports" / "fallback_posts.csv"))
    os.environ.setdefault("LOG_FILE", str(user_base / "logs" / "server.log"))
    # Ensure SQLite database lives in the user-writable data dir (avoids permission issues and improves persistence)
    os.environ.setdefault("SQLITE_PATH", str(user_base / "fallback.sqlite3"))
    # Persist browser session & lightweight session store in user-writable data dir (avoid read-only install dir)
    os.environ.setdefault("STORAGE_STATE", str(user_base / "storage_state.json"))
    os.environ.setdefault("SESSION_STORE_PATH", str(user_base / "session_store.json"))
    # Give a small manual login window on first navigation if session is invalid (improves first-run UX)
    os.environ.setdefault("LOGIN_INITIAL_WAIT_SECONDS", "30")
    # Early diagnostics: record the resolved template search root candidates and storage state existence.
    try:
        tmpl_candidates = []
        exe_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else ROOT
        tmpl_candidates.append(exe_dir / "server" / "templates")
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            tmpl_candidates.append(Path(getattr(sys, "_MEIPASS")) / "server" / "templates")  # type: ignore[attr-defined]
        tmpl_candidates.append(Path.cwd() / "server" / "templates")
        existing = [str(p) for p in tmpl_candidates if p.exists()]
        missing = [str(p) for p in tmpl_candidates if not p.exists()]
        storage_state_path = os.environ.get("STORAGE_STATE")
        session_store_path = os.environ.get("SESSION_STORE_PATH")
        # NOTE: Avoid passing keyword args like structlog; standard logging.Logger.info does not
        # accept arbitrary kwargs and this previously raised a TypeError in packaged (windowed)
        # mode, aborting early before the UI window appeared.
        log.info(
            "startup_paths templates_existing=%s templates_missing=%s storage_state=%s storage_state_exists=%s "
            "session_store=%s session_store_exists=%s cwd=%s",
            existing,
            missing,
            storage_state_path,
            bool(storage_state_path and Path(storage_state_path).exists()),
            session_store_path,
            bool(session_store_path and Path(session_store_path).exists()),
            str(Path.cwd()),
        )
    except Exception:
        pass
    
    # =========================================================================
    # CRITICAL: Install Chromium BEFORE starting server (synchronous)
    # This ensures the browser is ready when scraping starts
    # =========================================================================
    log.info("chromium_check_start")
    try:
        from desktop.chromium_installer import ensure_chromium_installed, is_chromium_ready, get_browsers_dir
        browsers_dir = get_browsers_dir()
        
        if not is_chromium_ready(browsers_dir):
            log.info("chromium_not_ready, starting_installation")
            # Show progress window and download synchronously
            if not ensure_chromium_installed(browsers_dir, show_progress=True):
                log.error("chromium_installation_failed")
                _message_box(
                    APP_DISPLAY_NAME,
                    (
                        "Impossible de télécharger le navigateur Chromium.\n"
                        "Vérifiez votre connexion internet et réessayez.\n\n"
                        "Si le problème persiste, exécutez manuellement:\n"
                        "playwright install chromium"
                    ),
                )
                return
        log.info("chromium_ready path=%s", browsers_dir)
    except Exception as e:
        log.exception("chromium_check_failed: %s", e)
        # Continue anyway - the error will appear later if Chromium is really missing

    # Proactive: verify pywebview import early so we can log a clear diagnostic if packaging missed it
    try:  # pragma: no cover - diagnostic only
        import webview  # type: ignore
        log.info("pywebview_import_ok version=%s", getattr(webview, '__version__', 'unknown'))
    except Exception as e:  # noqa: F841
        log.error("pywebview_import_failed early_diagnostic error=%s", e)

    # 1. WebView2 prerequisite check BEFORE starting server/UI logic
    exe_base = Path(sys.executable).parent if getattr(sys, "frozen", False) else _project_root()
    log.info("prereq_check_webview2 start")
    if not _install_webview2_if_missing(exe_base, user_base):
        log.error("webview2_missing_after_attempt_abort")
        _message_box(
            APP_DISPLAY_NAME,
            (
                "Microsoft Edge WebView2 Runtime est requis pour lancer Titan Scraper.\n"
                "L'installation automatique n'a pas abouti ou le runtime reste introuvable.\n"
                "Installez WebView2 puis relancez l'application."
            ),
        )
        return
    log.info("prereq_check_webview2 ok")

    # Preflight import of the FastAPI app. If a heavy dependency (numpy/pandas) fails, we still try to start;
    # the export route will handle missing pandas gracefully.
    try:
        from server.main import app as _check_app  # noqa: F401
    except Exception as e:
        msg = str(e)
        log.error("preflight_import_server_main_failed: %s\nSYS_PATH=%s\nROOT=%s", msg, sys.path, ROOT)
        if ("numpy" in msg.lower()) or ("pandas" in msg.lower()):
            _message_box(
                APP_DISPLAY_NAME,
                (
                    "Alerte: numpy/pandas introuvable. L'application démarre, mais l'export Excel peut être indisponible."
                ),
            )
        else:
            _message_box(
                APP_DISPLAY_NAME,
                (
                    "Erreur au chargement du module 'server.main'.\n"
                    f"Veuillez consulter le journal dans %LOCALAPPDATA%/{APP_INTERNAL_NAME}/logs/desktop.log et réinstaller si besoin."
                ),
            )
            return

    host = os.environ["APP_HOST"]

    # Single-instance guard: if another instance is healthy, reuse it and exit.
    last = _read_last_server_info(user_base)
    if last and isinstance(last, dict):
        h = str(last.get("host") or host)
        try:
            lp = int(last.get("port"))
        except Exception:
            lp = None  # type: ignore
        if lp and _probe_health(h, lp, timeout=0.8):
            log.info(f"single_instance_reuse_existing host={h} port={lp} silent_exit")
            return

    _lock_sock = _acquire_single_instance_lock()
    if _lock_sock is None:
        log.warning("single_instance_lock_denied")
        # Another instance likely running; try a few strategies to connect user to it and exit.
        # 1) Use last_server.json if healthy
        if last and isinstance(last, dict):
            h = str(last.get("host") or host)
            try:
                lp = int(last.get("port"))
            except Exception:
                lp = None  # type: ignore
            if lp and _probe_health(h, lp, timeout=0.8):
                log.info(f"single_instance_existing_ok host={h} port={lp} silent_exit")
                return
        # 2) Probe common ports
        for p in [8000, 8001, 8002, 8003, 8004]:
            if _probe_health(host, p, timeout=0.4):
                log.info(f"single_instance_probe_success host={host} port={p} silent_exit")
                return
        # 3) As a last resort, inform the user and exit
        log.error("single_instance_not_found_but_lock_busy silent_exit")
        return

    base_url = f"http://{host}:{port}"

    # Start server in a background thread (non-blocking for UI)
    srv = _start_server_thread(host, port)
    log.info("single_instance_lock_acquired port_lock=True fast_start_mode=True")
    _write_last_server_info(user_base, host, port)

    # After server thread start: attempt to hit new debug endpoint for template verification (non-blocking)
    try:  # pragma: no cover - best effort
        import requests
        def _check_templates():
            for _ in range(30):  # up to ~7.5s
                try:
                    r = requests.get(f"http://{host}:{port}/debug/templates", timeout=0.6)
                    if r.status_code == 200:
                        j = r.json()
                        log.info(
                            "templates_debug_probe",
                            template_dir=j.get("template_dir"),
                            dir_exists=j.get("dir_exists"),
                            files=j.get("files"),
                        )
                        return
                except Exception:
                    pass
                time.sleep(0.25)
        threading.Thread(target=_check_templates, name="tmpl-probe", daemon=True).start()
    except Exception:
        pass

    # Prepare immediate window with lightweight loading HTML; will switch to real dashboard when ready.
    title = APP_DISPLAY_NAME
    LOADING_HTML = (
        """
        <html lang='fr'>
        <head><meta charset='utf-8'><title>Titan Scraper</title>
        <style>
            body { font-family: system-ui,-apple-system,Segoe UI,Roboto,sans-serif; display:flex; flex-direction:column; align-items:center; justify-content:center; height:100vh; margin:0; background:#0f1115; color:#eee; }
            h1 { font-size:1.5rem; margin:0 0 1rem; }
            .spinner { width:54px; height:54px; border:6px solid #2e3238; border-top-color:#4fa3ff; border-radius:50%; animation:spin 0.9s linear infinite; margin-bottom:18px; }
            p { margin:0.2rem 0; font-size:0.9rem; opacity:0.85; }
            @keyframes spin { to { transform:rotate(360deg);} }
            .sub { font-size:0.75rem; opacity:0.55; margin-top:1rem; }
        </style></head>
        <body>
          <div class='spinner'></div>
          <h1>Démarrage...</h1>
          <p>Initialisation du serveur local</p>
          <p id='phase'>Préparation des composants</p>
          <script>
            let dots=0; setInterval(()=>{dots=(dots+1)%4;document.getElementById('phase').textContent='Préparation des composants'+'.'.repeat(dots);},450);
          </script>
          <div class='sub'>Titan Scraper</div>
        </body>
        </html>
        """
    )

    # Health watchdog: if /health stops responding for a sustained period, inform user & exit gracefully.
    _watchdog_stop = _threading.Event()

    def _health_watchdog():  # pragma: no cover (runtime behavior)
        consecutive = 0
        while not _watchdog_stop.is_set():
            ok = _probe_health(host, port, timeout=1.5)
            if ok:
                consecutive = 0
            else:
                consecutive += 1
                if consecutive >= 20:  # ~20 * 3s sleep ~= 60s degraded
                    logging.getLogger("desktop").error("health_watchdog_triggered")
                    _message_box(
                        APP_DISPLAY_NAME,
                        (
                            "Le serveur interne ne répond plus depuis ~1 minute.\n"
                            "L'application va se fermer. Relancez-la."
                        ),
                    )
                    os._exit(1)  # Hard exit to avoid zombie window
            time.sleep(3)

    _threading.Thread(target=_health_watchdog, name="health-watchdog", daemon=True).start()

    try:
        import webview  # type: ignore
        window = webview.create_window(title, html=LOADING_HTML, width=1200, height=800, resizable=True, minimized=False)

        def _after_start():  # pragma: no cover (GUI callback)
            # Wait for server readiness then load real dashboard
            try:
                ok = _wait_for_server(base_url, timeout=25.0)
                if ok:
                    target_path = _determine_initial_view(base_url)
                    # If login required, attempt background auto-login (desktop credentials.json)
                    if target_path.startswith("/login"):
                        try:
                            # Note: _attempt_auto_login_if_configured signature is (user_base, base_url, timeout)
                            # Ensure we pass arguments in this order to avoid TypeError on Path operations
                            if _attempt_auto_login_if_configured(user_base, base_url):
                                target_path = "/"  # session now valid
                        except Exception:  # pragma: no cover
                            logging.getLogger("desktop").warning("auto_login_wrapper_failed", exc_info=True)
                    window.load_url(base_url + target_path)
                    try:
                        window.restore()
                        window.show()
                        window.focus()
                    except Exception:
                        pass
                else:
                    # Show a simple retry message inside the loading window
                    window.load_html("<h2 style='font-family:system-ui'>Serveur lent à démarrer – nouvelle tentative...</h2>")
                    again = _wait_for_server(base_url, timeout=15.0)
                    if again:
                        target_path = _determine_initial_view(base_url)
                        window.load_url(base_url + target_path)
            except Exception:
                logging.getLogger("desktop").exception("post_start_load_failed")

        try:
            if _is_windows():
                try:
                    webview.start(_after_start, gui="edgechromium", http_server=False, debug=False)
                except Exception as e1:
                    logging.getLogger("desktop").warning("WebView2 backend failed, trying MSHTML: %s", e1)
                    webview.start(_after_start, gui="mshtml", http_server=False, debug=False)
            else:
                webview.start(_after_start, gui=None, http_server=False, debug=False)
        except ModuleNotFoundError:
            # pywebview non présent: ouvrir le dashboard dans le navigateur par défaut comme repli.
            logging.getLogger("desktop").warning("pywebview introuvable – ouverture du navigateur externe")
            try:
                import webbrowser
                if _wait_for_server(base_url, timeout=15.0):
                    webbrowser.open(base_url + "/")
                else:
                    webbrowser.open(base_url + "/health")
            except Exception:
                logging.getLogger("desktop").exception("external_browser_open_failed")
            return
        except Exception:
            logging.getLogger("desktop").exception("Failed to start webview UI; attempting WebView2 install and retry")
            if _is_windows():
                retry_exe_base = Path(sys.executable).parent if getattr(sys, "frozen", False) else _project_root()
                _install_webview2_if_missing(retry_exe_base, user_base)
                time.sleep(3)
                try:
                    if _webview2_runtime_installed():
                        import webview  # type: ignore
                        webview.start(_after_start, gui="edgechromium", http_server=False, debug=False)
                        return
                except Exception:
                    logging.getLogger("desktop").warning("Retry after WebView2 install failed; falling back to external browser")
                try:
                    import webbrowser
                    if _wait_for_server(base_url, timeout=10.0):
                        webbrowser.open(base_url + "/")
                except Exception:
                    pass
                _message_box(
                    APP_DISPLAY_NAME,
                    (
                        "Impossible d'ouvrir la fenêtre intégrée. Un navigateur externe a été tenté.\n\n"
                        "Si rien ne s'est ouvert, installez (ou réinstallez) 'Microsoft Edge WebView2 Runtime' puis relancez l'application."
                    ),
                )
                return
            else:
                try:
                    import webbrowser
                    if _wait_for_server(base_url, timeout=10.0):
                        webbrowser.open(base_url + "/")
                except Exception:
                    pass
                _message_box(
                    APP_DISPLAY_NAME,
                    "Impossible d'ouvrir la fenêtre intégrée. Un navigateur externe a été tenté.",
                )
                return
    except Exception:
        logging.getLogger("desktop").exception("Unexpected failure creating the UI window")
    finally:
        # Graceful shutdown on process exit (e.g., if UI closed)
        try:
            _watchdog_stop.set()
        except Exception:
            pass
        try:
            srv.server.should_exit = True
        except Exception:
            pass
        try:
            # Give server thread a moment to wind down
            for _ in range(30):
                if not srv.thread.is_alive():
                    break
                time.sleep(0.1)
        except Exception:
            pass
        try:
            if '_lock_sock' in locals() and _lock_sock:
                _lock_sock.close()
        except Exception:
            pass
        # Release Windows mutex if held
        try:
            if '_mutex_handle' in locals() and _mutex_handle and _is_windows():
                ctypes.windll.kernel32.CloseHandle(_mutex_handle)  # type: ignore[attr-defined]
        except Exception:
            pass


def _run_scraper_subprocess_mode():
    """Run in subprocess mode for isolated Playwright scraping.
    
    Called when the exe is invoked with --scraper-subprocess flag.
    Uses file-based I/O (--input-file and --output-file args).
    """
    import json as _json
    import traceback as _tb
    
    # Debug: Write to a known location to confirm we got here
    debug_log_path = Path(os.environ.get("LOCALAPPDATA", ".")) / "TitanScraper" / "subprocess_debug.txt"
    try:
        with open(debug_log_path, 'a', encoding='utf-8') as df:
            df.write(f"subprocess_mode_entered args={sys.argv}\n")
    except Exception:
        pass
    
    # Find output file from args so we can write errors there
    output_file = None
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--output-file" and i < len(sys.argv) - 1:
            output_file = sys.argv[i + 1]
            break
    
    def write_error(msg: str, tb: str = ""):
        """Write error to output file if available."""
        error_data = {"success": False, "error": msg, "posts": [], "traceback": tb}
        if output_file:
            try:
                with open(output_file, 'w', encoding='utf-8') as f:
                    _json.dump(error_data, f)
            except Exception:
                pass
        # Also write to debug log
        try:
            with open(debug_log_path, 'a', encoding='utf-8') as df:
                df.write(f"write_error: {msg}\n{tb}\n")
        except Exception:
            pass
    
    try:
        try:
            with open(debug_log_path, 'a', encoding='utf-8') as df:
                df.write("attempting_import_scraper_main\n")
        except Exception:
            pass
        from scraper.scrape_subprocess import main as scraper_main
        try:
            with open(debug_log_path, 'a', encoding='utf-8') as df:
                df.write(f"import_success, about_to_call_scraper_main, type={type(scraper_main)}\n")
        except Exception:
            pass
        scraper_main()
        try:
            with open(debug_log_path, 'a', encoding='utf-8') as df:
                df.write("scraper_main_returned_normally\n")
        except Exception:
            pass
    except SystemExit as se:
        # Capture sys.exit() calls from scraper_main
        try:
            with open(debug_log_path, 'a', encoding='utf-8') as df:
                df.write(f"scraper_main_called_sys_exit code={se.code}\n")
        except Exception:
            pass
        raise  # Re-raise to exit properly
    except Exception as e:
        write_error(str(e), _tb.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    # Very early debug logging
    import os as _early_os
    from pathlib import Path as _early_Path
    _early_debug = _early_Path(_early_os.environ.get("LOCALAPPDATA", ".")) / "TitanScraper" / "startup_debug.txt"
    try:
        with open(_early_debug, 'a', encoding='utf-8') as _df:
            _df.write(f"main_block_entered argv={sys.argv}\n")
    except Exception:
        pass
    
    # Check for subprocess mode (can be first arg or after other args)
    is_subprocess_mode = "--scraper-subprocess" in sys.argv
    
    try:
        with open(_early_debug, 'a', encoding='utf-8') as _df:
            _df.write(f"is_subprocess_mode={is_subprocess_mode}\n")
    except Exception:
        pass
    
    if is_subprocess_mode:
        _run_scraper_subprocess_mode()
    else:
        main()
