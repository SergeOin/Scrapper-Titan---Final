import uvicorn
import os
import sys
from pathlib import Path
import asyncio
import traceback

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

def _read_version() -> str:
    try:
        vfile = PROJECT_ROOT / "VERSION"
        if vfile.exists():
            return vfile.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return "0.0.0"

if __name__ == "__main__":
    version = _read_version()
    print(f"[run_server] Starting TitanScraper v{version}")
    # On Windows, use Proactor event loop policy so asyncio.subprocess works (required by Playwright)
    if sys.platform.startswith("win"):
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception:
            pass
    os.environ.setdefault("LOG_LEVEL", "INFO")
    host = os.environ.get("APP_HOST", "0.0.0.0")
    port_env = os.environ.get("PORT") or os.environ.get("APP_PORT") or "8000"
    try:
        port = int(port_env)
    except Exception:
        port = 8000
    # Import server.main explicitly so PyInstaller bundles it (avoids dynamic import failure)
    try:
        import server.main as _server_main  # type: ignore
    except Exception as e:  # pragma: no cover
        print("[run_server] FATAL: cannot import server.main:")
        traceback.print_exc()
        sys.exit(1)
    try:
        uvicorn.run(_server_main.app, host=host, port=port, log_level=os.environ.get("LOG_LEVEL","info").lower())
    except KeyboardInterrupt:
        print("\n[run_server] Arrêt propre demandé (KeyboardInterrupt)")
    except Exception:
        print("[run_server] Unhandled server exception:")
        traceback.print_exc()
        sys.exit(2)
