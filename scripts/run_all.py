"""Convenience launcher: start FastAPI server and background worker in one process.

Usage (PowerShell):
  python scripts/run_all.py

Environment overrides:
  APP_HOST / APP_PORT control server bind
  SHUTDOWN_TOKEN enables protected POST /shutdown

Notes:
- For production deploy it's recommended to run server & worker as separate processes/containers.
- This helper is for quick local demos or small internal setups.
"""
from __future__ import annotations

import asyncio
import os, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import uvicorn  # type: ignore
from scraper.worker import worker_loop


async def _supervise_worker():
    """Keep a worker alive even if it returns after a one-shot run.

    In non-autonomous mode without Redis, worker_loop returns immediately after
    one batch. This supervisor restarts it after a configurable cool-down so the
    server process does not terminate prematurely.
    """
    cooldown = int(os.environ.get("WORKER_RESPAWN_COOLDOWN_SECONDS", "300"))  # 5 min default
    while True:
        try:
            await worker_loop()
        except Exception as exc:  # pragma: no cover
            print(f"[run_all] worker_loop crashed: {exc}")
        # If autonomous interval enabled inside worker, it will not return unless fatal
        # If it returned normally (single pass mode), sleep then restart
        await asyncio.sleep(cooldown)

async def _run_server():
    host = os.environ.get("APP_HOST", "0.0.0.0")
    port = int(os.environ.get("APP_PORT", "8000"))
    config = uvicorn.Config("server.main:app", host=host, port=port, log_level=os.environ.get("LOG_LEVEL","info"))
    server = uvicorn.Server(config)
    await server.serve()

async def main():
    # Ensure the API does NOT spawn its own in-process autonomous worker; we supervise separately here.
    os.environ.setdefault("INPROCESS_AUTONOMOUS", "0")
    # Run server and worker concurrently.
    server_task = asyncio.create_task(_run_server(), name="uvicorn_server")
    worker_task = asyncio.create_task(_supervise_worker(), name="scraper_worker_supervisor")
    done, pending = await asyncio.wait({server_task, worker_task}, return_when=asyncio.FIRST_COMPLETED)
    # If one finishes (e.g., shutdown), cancel the other.
    for t in pending:
        t.cancel()
    for t in pending:
        try:
            await t
        except Exception:
            pass

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[run_all] Interruption utilisateur -> arrêt en cours")
