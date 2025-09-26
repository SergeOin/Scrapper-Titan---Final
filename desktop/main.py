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


def _acquire_windows_mutex(name: str = "Local\\TitanScraperMutex_v2"):
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


def _user_data_dir(app_name: str = "TitanScraper") -> Path:
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


def _try_playwright_install():
    """Best-effort ensure Chromium is available for Playwright.

    This runs quickly if already installed (checks cache). Safe to skip on CI.
    """
    try:
        # Do a very fast smoke import; if playwright is missing, packaging is wrong.
        import playwright  # noqa: F401
        from subprocess import run

        # Use module invocation to install Chromium only. Quiet output.
        run([sys.executable, "-m", "playwright", "install", "chromium", "--with-deps"], check=False)
    except Exception:
        # Non-fatal for starting the app; the login flow will fail until installed.
        logging.getLogger("desktop").warning("Playwright install check failed or skipped", exc_info=True)


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


def _install_webview2_if_missing(base: Path) -> None:
    if not _is_windows():
        return
    if _webview2_runtime_installed():
        return
    try:
        # Try multiple locations depending on PyInstaller layout
        candidates: list[Path] = []
        exe_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else _project_root()
        meipass = Path(getattr(sys, "_MEIPASS", exe_dir))  # type: ignore[attr-defined]
        # PyInstaller one-folder puts datas under _internal
        candidates.append(exe_dir / "_internal" / "MicrosoftEdgeWebView2Setup.exe")
        # Some layouts may place it next to the exe
        candidates.append(exe_dir / "MicrosoftEdgeWebView2Setup.exe")
        # Direct MEIPASS
        candidates.append(meipass / "MicrosoftEdgeWebView2Setup.exe")
        # Dev build path
        candidates.append(_project_root() / "build" / "MicrosoftEdgeWebView2Setup.exe")
        setup = next((p for p in candidates if p.exists()), None)
        if setup and setup.exists():
            _message_box(
                "Titan Scraper",
                "Installation du composant Microsoft Edge WebView2 requise. Une installation va démarrer."
            )
            # Silent install; bootstrapper handles per-machine/per-user detection
            import subprocess
            subprocess.run([str(setup), "/silent", "/install"], check=False)
            # Small backoff to let installation complete
            time.sleep(2)
        else:
            _message_box(
                "Titan Scraper",
                (
                    "Composant Microsoft Edge WebView2 manquant et installateur introuvable.\n"
                    "Veuillez installer manuellement 'Microsoft Edge WebView2 Runtime' puis relancer l'application."
                ),
            )
    except Exception:
        logging.getLogger("desktop").exception("Failed to install WebView2")


def main():
    user_base = _user_data_dir()
    _ensure_runtime_dirs(user_base)
    _setup_logging(user_base)
    _ensure_event_loop_policy()
    log = logging.getLogger("desktop")

    # Hard single-instance guard using a Windows named mutex (prevents burst multi-launch)
    _mutex_handle = _acquire_windows_mutex()
    if _mutex_handle is None and _is_windows():
        # Don't exit immediately; rely on TCP port lock + health probe to avoid false positives
        log.warning("win_named_mutex_denied_continue_with_port_lock")

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

    # Point runtime artifacts to user-writable locations
    os.environ.setdefault("SCREENSHOT_DIR", str(user_base / "screenshots"))
    os.environ.setdefault("TRACE_DIR", str(user_base / "traces"))
    os.environ.setdefault("CSV_FALLBACK_FILE", str(user_base / "exports" / "fallback_posts.csv"))
    os.environ.setdefault("LOG_FILE", str(user_base / "logs" / "server.log"))

    _try_playwright_install()
    _install_webview2_if_missing(Path(sys.executable).parent if getattr(sys, "frozen", False) else _project_root())

    # Preflight import of the FastAPI app. If a heavy dependency (numpy/pandas) fails, we still try to start;
    # the export route will handle missing pandas gracefully.
    try:
        from server.main import app as _check_app  # noqa: F401
    except Exception as e:
        msg = str(e)
        log.error("preflight_import_server_main_failed: %s\nSYS_PATH=%s\nROOT=%s", msg, sys.path, ROOT)
        if ("numpy" in msg.lower()) or ("pandas" in msg.lower()):
            _message_box(
                "Titan Scraper",
                (
                    "Alerte: numpy/pandas introuvable. L'application démarre, mais l'export Excel peut être indisponible."
                ),
            )
        else:
            _message_box(
                "Titan Scraper",
                (
                    "Erreur au chargement du module 'server.main'.\n"
                    "Veuillez consulter le journal dans %LOCALAPPDATA%/TitanScraper/logs/desktop.log et réinstaller si besoin."
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
            log.info(f"single_instance_reuse_existing host={h} port={lp}")
            _message_box(
                "Titan Scraper",
                "L'application est déjà ouverte. Si la fenêtre n'est pas visible, vérifiez la barre des tâches.",
            )
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
                log.info(f"single_instance_existing_ok host={h} port={lp}")
                _message_box(
                    "Titan Scraper",
                    "L'application est déjà ouverte. Si la fenêtre n'est pas visible, vérifiez la barre des tâches.",
                )
                return
        # 2) Probe common ports
        for p in [8000, 8001, 8002, 8003, 8004]:
            if _probe_health(host, p, timeout=0.4):
                log.info(f"single_instance_probe_success host={host} port={p}")
                _message_box(
                    "Titan Scraper",
                    "L'application est déjà ouverte. Si la fenêtre n'est pas visible, vérifiez la barre des tâches.",
                )
                return
        # 3) As a last resort, inform the user and exit
        log.error("single_instance_not_found_but_lock_busy")
        _message_box(
            "Titan Scraper",
            (
                "Une autre instance de TitanScraper semble déjà être en cours d'exécution.\n\n"
                "La fenêtre/le navigateur devrait déjà être ouvert. Si besoin, fermez l'ancienne instance via le Gestionnaire des tâches."
            ),
        )
        return

    base_url = f"http://{host}:{port}"

    # Start server in a background thread
    srv = _start_server_thread(host, port)
    log.info("single_instance_lock_acquired port_lock=True")
    _write_last_server_info(user_base, host, port)

    # Wait up to a few seconds for readiness before showing the window
    if not _wait_for_server(base_url, timeout=30.0):
        logging.getLogger("desktop").warning("Server did not report ready within timeout; continuing")

    # Create the desktop window pointing to the dashboard
    title = "Titan Scraper"

    # We rely on the finally block below to request a graceful shutdown when the window closes.

    try:
        import webview  # type: ignore
        window = webview.create_window(title, url=base_url + "/", width=1200, height=800, resizable=True)
        try:
            # Prefer Edge WebView2 on Windows, fall back to MSHTML if unavailable
            if _is_windows():
                try:
                    webview.start(gui="edgechromium", http_server=False, debug=False)
                except Exception as e1:
                    logging.getLogger("desktop").warning("WebView2 backend failed, trying MSHTML: %s", e1)
                    webview.start(gui="mshtml", http_server=False, debug=False)
            else:
                webview.start(gui=None, http_server=False, debug=False)
        except Exception:
            logging.getLogger("desktop").exception("Failed to start webview UI; attempting WebView2 install and retry")
            if _is_windows():
                _install_webview2_if_missing(Path(sys.executable).parent if getattr(sys, "frozen", False) else _project_root())
                # Retry once after short backoff
                time.sleep(5)
                try:
                    if _webview2_runtime_installed():
                        webview.start(gui="edgechromium", http_server=False, debug=False)
                        return
                except Exception:
                    logging.getLogger("desktop").warning("Retry after WebView2 install failed; will not open external browser")
                _message_box(
                    "Titan Scraper",
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
                    "Titan Scraper",
                    "Impossible d'ouvrir la fenêtre intégrée. Veuillez relancer l'application.",
                )
                return
    except Exception:
        logging.getLogger("desktop").exception("Unexpected failure creating the UI window")
    finally:
        # Graceful shutdown on process exit (e.g., if UI closed)
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
