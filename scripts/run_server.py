import uvicorn
import os
import sys
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if __name__ == "__main__":
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
