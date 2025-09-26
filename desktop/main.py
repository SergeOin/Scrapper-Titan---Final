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
    if _is_windows():
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception:
            pass


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
        def _chromium_ready(path: Path) -> bool:
            try:
                rev_dir = next((p for p in path.iterdir() if p.is_dir() and p.name.startswith("chromium-")), None)
                if not rev_dir:
                    return False
                exe = rev_dir / "chrome-win" / "chrome.exe" if _is_windows() else rev_dir / "chrome-linux" / "chrome"
                return exe.exists()
            except Exception:
                return False

        if browsers_dir.exists() and _chromium_ready(browsers_dir):
            log.info("playwright_browsers_present skip_install path=%s", browsers_dir)
            return
        # If prebaked browsers shipped inside the bundle (pw-browsers) copy them first.
        try:
            bundle_pw = (Path(sys.executable).parent if getattr(sys, "frozen", False) else _project_root()) / 'pw-browsers'
            if bundle_pw.exists() and not browsers_dir.exists():
                import shutil
                shutil.copytree(bundle_pw, browsers_dir)
                if _chromium_ready(browsers_dir):
                    log.info("playwright_browsers_copied_from_bundle path=%s", browsers_dir)
                    return
        except Exception:
            log.warning("playwright_copy_bundle_failed", exc_info=True)
        # Trigger install only if playwright package importable
        import playwright  # noqa: F401
        from subprocess import run
        log.info("playwright_install_start target=%s", browsers_dir)
        browsers_dir.mkdir(parents=True, exist_ok=True)
        run([sys.executable, "-m", "playwright", "install", "chromium", "--with-deps"], check=False)
        # Post-check
        if _chromium_ready(browsers_dir):
            log.info("playwright_install_complete")
        else:
            log.warning("playwright_install_incomplete path=%s triggering_second_attempt", browsers_dir)
            try:
                from subprocess import run as _run
                _run([sys.executable, "-m", "playwright", "install", "chromium"], check=False)
                if _chromium_ready(browsers_dir):
                    log.info("playwright_second_attempt_success")
                else:
                    log.error("playwright_second_attempt_failed path=%s", browsers_dir)
            except Exception:
                log.exception("playwright_second_attempt_exception")

        # Fallback HTTP downloader (Windows-focused) if still not ready
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
                        pv = "1.46.0"
                    major_minor = ".".join(pv.split(".")[:2])
                    default_map = {"1.46": "1129"}
                    rev = default_map.get(major_minor, "1129")

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

                url = f"https://playwright.azureedge.net/builds/chromium/{rev}/{zip_name}"
                log.info("playwright_http_fallback_download url=%s rev=%s", url, rev)
                target_rev_dir = browsers_dir / f"chromium-{rev}"
                if target_rev_dir.exists():
                    # If incomplete remove to avoid mixing
                    try:
                        shutil.rmtree(target_rev_dir)
                    except Exception:
                        pass
                target_rev_dir.mkdir(parents=True, exist_ok=True)

                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    tmp_path = Path(tmp.name)
                try:
                    with urllib.request.urlopen(url) as resp, open(tmp_path, "wb") as out:
                        shutil.copyfileobj(resp, out)
                    # Extract
                    with zipfile.ZipFile(tmp_path, 'r') as zf:
                        zf.extractall(target_rev_dir)
                    # Normal shape: target_rev_dir/inner_folder/chrome.exe
                    chrome_exe = target_rev_dir / inner_folder / ("chrome.exe" if _is_windows() else "chrome")
                    if chrome_exe.exists():
                        log.info("playwright_http_fallback_success exe=%s", chrome_exe)
                    else:
                        log.error("playwright_http_fallback_missing_exe path=%s", chrome_exe)
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

        def _has_key(root, path):
            try:
                with winreg.OpenKey(root, path) as _:
                    return True
            except Exception:
                return False

        # Per-machine
        if _has_key(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F1B5F0A6-C3B0-4AB5-9D24-BA61A1B3C047}"):
            return True
        # Per-user
        if _has_key(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F1B5F0A6-C3B0-4AB5-9D24-BA61A1B3C047}"):
            return True
    except Exception:
        return False
    return False


def _install_webview2_if_missing(exe_base: Path, user_base: Path) -> None:
    """Install WebView2 runtime (Windows) if absent, with a small progress window and caching.

    Creates a marker file in user data dir after a successful install attempt to avoid spamming
    multiple runs if detection is flaky. We still re-check registry each launch; marker only
    suppresses repeated installer execution within 24h if runtime still missing.
    """
    if not _is_windows():
        return
    if _webview2_runtime_installed():
        return
    log = logging.getLogger("desktop")
    marker = user_base / "webview2_install_marker.json"
    if marker.exists():
        try:
            import json as _json
            data = _json.loads(marker.read_text(encoding="utf-8"))
            ts = float(data.get("ts", 0))
            if time.time() - ts < 24 * 3600:  # less than 24h ago
                log.info("webview2_recent_attempt_skip")
                return
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
            return

        # Progress window (Tkinter) -----------------------------------------------------------
        progress_close: callable | None = None
        progress_root = None  # type: ignore
        progress_var = None   # will hold tk.IntVar
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
                # Pseudo progress: determinate bar increments while polling; switches to full at success
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

        # Run installer in thread
        import subprocess
        import threading as _th

        done_flag = {"done": False}

        def _run_install():
            try:
                subprocess.run([str(setup), "/silent", "/install"], check=False)
            finally:
                done_flag["done"] = True

        t = _th.Thread(target=_run_install, daemon=True)
        t.start()

        # Poll with UI updates up to 90s
        start = time.time()
        tick = 0
        while time.time() - start < 90:
            if _webview2_runtime_installed():
                break
            if done_flag["done"]:
                # If installer finished but runtime still not detected, wait a bit more
                time.sleep(2)
                if _webview2_runtime_installed():
                    break
            # Keep UI responsive
            try:
                if progress_root is not None:
                    tick += 1
                    # Increment progress up to 95% while waiting
                    if progress_var is not None:
                        cur = progress_var.get()
                        if cur < 95:
                            progress_var.set(min(95, cur + 1))
                    progress_root.update()
            except Exception:
                # Window probably closed by user; stop updating
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

        # Record attempt time
        try:
            marker.write_text('{"ts": %f}' % time.time(), encoding="utf-8")
        except Exception:
            pass

        log.info("webview2_install_complete present=%s", _webview2_runtime_installed())
    except Exception:
        log.exception("Failed to install WebView2")


def main():
    user_base = _user_data_dir()
    _ensure_runtime_dirs(user_base)
    _setup_logging(user_base)
    _ensure_event_loop_policy()
    log = logging.getLogger("desktop")

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

    # Desktop defaults (can be overridden by env)
    os.environ.setdefault("APP_HOST", "127.0.0.1")
    # Pick a free port if 8000 busy
    port = _find_free_port(int(os.environ.get("APP_PORT") or os.environ.get("PORT") or 8000))
    os.environ["APP_PORT"] = str(port)
    # Reduce startup noise for a desktop UX
    os.environ.setdefault("LOG_LEVEL", "INFO")
    # Prefer in-process autonomous worker
    os.environ.setdefault("INPROCESS_AUTONOMOUS", "1")
    # Keep dashboard private by default in desktop mode
    os.environ.setdefault("DASHBOARD_PUBLIC", "0")
    # Speed optimizations: disable remote backends by default in packaged desktop (avoid 5s connection timeouts)
    os.environ.setdefault("DISABLE_MONGO", "1")
    os.environ.setdefault("DISABLE_REDIS", "1")
    # Lower Mongo connect timeout further if user re-enables it
    os.environ.setdefault("MONGO_CONNECT_TIMEOUT_MS", "1200")

    # Point runtime artifacts to user-writable locations
    os.environ.setdefault("SCREENSHOT_DIR", str(user_base / "screenshots"))
    os.environ.setdefault("TRACE_DIR", str(user_base / "traces"))
    os.environ.setdefault("CSV_FALLBACK_FILE", str(user_base / "exports" / "fallback_posts.csv"))
    os.environ.setdefault("LOG_FILE", str(user_base / "logs" / "server.log"))
    # Launch Playwright dependency installation in background to avoid blocking UI (perceived faster startup)
    def _bg_playwright():  # pragma: no cover (background helper)
        try:
            _try_playwright_install(user_base)
        except Exception:
            logging.getLogger("desktop").exception("playwright_background_install_failed")
    threading.Thread(target=_bg_playwright, name="playwright-install", daemon=True).start()

    exe_base = Path(sys.executable).parent if getattr(sys, "frozen", False) else _project_root()
    _install_webview2_if_missing(exe_base, user_base)

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
                    window.load_url(base_url + "/")
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
                        window.load_url(base_url + "/")
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
        except Exception:
            logging.getLogger("desktop").exception("Failed to start webview UI; attempting WebView2 install and retry")
            if _is_windows():
                retry_exe_base = Path(sys.executable).parent if getattr(sys, "frozen", False) else _project_root()
                _install_webview2_if_missing(retry_exe_base, user_base)
                time.sleep(3)
                try:
                    if _webview2_runtime_installed():
                        webview.start(_after_start, gui="edgechromium", http_server=False, debug=False)
                        return
                except Exception:
                    logging.getLogger("desktop").warning("Retry after WebView2 install failed; will not open external browser")
                _message_box(
                    APP_DISPLAY_NAME,
                    (
                        "Impossible d'ouvrir la fenêtre intégrée.\n\n"
                        "Veuillez installer (ou réinstaller) 'Microsoft Edge WebView2 Runtime' puis relancer l'application.\n"
                        "L'installateur est inclus et lancé automatiquement au premier démarrage."
                    ),
                )
                return
            else:
                # Non-Windows fallback shouldn't use external browser per requirement; just inform.
                _message_box(
                    APP_DISPLAY_NAME,
                    "Impossible d'ouvrir la fenêtre intégrée. Veuillez relancer l'application.",
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


if __name__ == "__main__":
    main()
