"""Dev entrypoint with auto-reload and Windows event loop policy.

Usage:
  python scripts/dev_server.py  (honors PORT or APP_PORT)

Sets INPROCESS_AUTONOMOUS=0 to prevent background worker when using reload.
"""
from __future__ import annotations
import os, sys, asyncio
from pathlib import Path

# Ensure project root on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# On Windows the Proactor loop can raise NotImplementedError for subprocess
# creation under certain reload scenarios (Playwright launches a Node driver).
# We default to the Selector loop for dev to keep Playwright functional.
if sys.platform.startswith("win"):
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass
    # Expose a toggle if user explicitly wants Proactor (rare): set WIN_LOOP=proactor
    if os.environ.get("WIN_LOOP", "selector").lower().startswith("pro"):
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception:
            pass

os.environ.setdefault("LOG_LEVEL", "INFO")
# Force autonomous worker ON in dev (user requirement) even with reload
os.environ["INPROCESS_AUTONOMOUS"] = "1"
# Disable auto-disable heuristic so scraper stays active
os.environ.setdefault("AUTO_DISABLE_ON_RELOAD", "0")
# Pick loop policy hint for server/main.py (mirrors what we already set here)
os.environ.setdefault("WIN_LOOP", "selector")

host = os.environ.get("APP_HOST", "0.0.0.0")
port_env = os.environ.get("PORT") or os.environ.get("APP_PORT") or "8000"
try:
    port = int(port_env)
except Exception:
    port = 8000

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server.main:app", host=host, port=port, reload=True, log_level=os.environ.get("LOG_LEVEL","info").lower())