import uvicorn
import os
import sys
from pathlib import Path
import asyncio

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
