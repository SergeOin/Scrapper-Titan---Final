import uvicorn
import os
import sys
from pathlib import Path
import asyncio


_LOG_FILE_HANDLE = None


def _ensure_log_streams() -> bool:
    """Ensure stdout/stderr are available even when no console is attached."""
    global _LOG_FILE_HANDLE
    stdout_missing = sys.stdout is None or getattr(sys.stdout, "closed", False)
    stderr_missing = sys.stderr is None or getattr(sys.stderr, "closed", False)

    if stdout_missing or stderr_missing:
        log_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "TitanScraper" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        if _LOG_FILE_HANDLE is None or getattr(_LOG_FILE_HANDLE, "closed", False):
            _LOG_FILE_HANDLE = open(log_dir / "server.log", "a", encoding="utf-8", buffering=1)

        if stdout_missing:
            sys.stdout = _LOG_FILE_HANDLE

        if stderr_missing:
            sys.stderr = _LOG_FILE_HANDLE

    return stdout_missing or stderr_missing

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if __name__ == "__main__":
    # On Windows, use Proactor event loop policy so asyncio.subprocess works (required by Playwright)
    if sys.platform.startswith("win"):
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception:
            pass

    _ensure_log_streams()

    os.environ.setdefault("LOG_LEVEL", "INFO")
    # Allow passing host/port via env
    host = os.environ.get("APP_HOST", "0.0.0.0")
    port_env = os.environ.get("PORT") or os.environ.get("APP_PORT") or "8000"
    try:
        port = int(port_env)
    except Exception:
        port = 8000
    try:
        uvicorn.run("server.main:app", host=host, port=port, log_level=os.environ.get("LOG_LEVEL","info").lower())
    except KeyboardInterrupt:
        print("\n[run_server] Arrêt propre demandé (KeyboardInterrupt)")
