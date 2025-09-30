"""Dev entrypoint with auto-reload and Windows event loop policy.

Usage:
  python scripts/dev_server.py  (honors PORT or APP_PORT)

Sets INPROCESS_AUTONOMOUS=0 to prevent background worker when using reload.
"""
from __future__ import annotations
import os, sys, asyncio

if sys.platform.startswith("win"):
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

os.environ.setdefault("LOG_LEVEL", "INFO")
# Disable autonomous worker to avoid multiple Playwright launches during reload
os.environ.setdefault("INPROCESS_AUTONOMOUS", "0")

host = os.environ.get("APP_HOST", "0.0.0.0")
port_env = os.environ.get("PORT") or os.environ.get("APP_PORT") or "8000"
try:
    port = int(port_env)
except Exception:
    port = 8000

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server.main:app", host=host, port=port, reload=True, log_level=os.environ.get("LOG_LEVEL","info").lower())