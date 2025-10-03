"""Unified launcher entrypoint for packaged binary.

Behavior:
 - Loads .env if present.
 - Starts FastAPI server + worker concurrently (like scripts/run_all.py) with structured log messages.
 - Respects APP_HOST / APP_PORT.
 - Honors LOG_FILE / LOG_MAX_BYTES / LOG_BACKUP_COUNT via existing bootstrap settings.
 - Test shortcut: set ENTRYPOINT_TEST_MODE=1 to skip launching subsystems (used in unit tests).

Usage (source):
  python entrypoint.py

Packaged: included via PyInstaller spec (update spec to target entrypoint instead of run_all if desired).
"""
from __future__ import annotations
import asyncio, os, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Optional .env loading (light) without adding dependency
def _load_dotenv():
    env_path = PROJECT_ROOT / '.env'
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding='utf-8').splitlines():
        if not line or line.strip().startswith('#'):
            continue
        if '=' not in line:
            continue
        k, v = line.split('=', 1)
        k = k.strip(); v = v.strip()
        os.environ.setdefault(k, v)

_load_dotenv()

# Structured logging / settings
try:
    from scraper.bootstrap import Settings, configure_logging  # type: ignore
except Exception:  # pragma: no cover
    Settings = None  # type: ignore
    def configure_logging(*a, **k):  # type: ignore
        pass

settings = None
try:
    if Settings:
        settings = Settings()
        configure_logging(settings.log_level, settings)
except Exception as e:  # pragma: no cover
    print(f"[entrypoint] Failed to initialize logging via Settings: {e}")

import uvicorn  # type: ignore
from scraper.worker import worker_loop

async def _supervise_worker():
    cooldown = int(os.environ.get('WORKER_RESPAWN_COOLDOWN_SECONDS', '300'))
    while True:
        try:
            await worker_loop()
        except Exception as exc:  # pragma: no cover
            import logging; logging.getLogger(__name__).exception("worker_loop crashed: %s", exc)
        await asyncio.sleep(cooldown)

async def _run_server():
    host = os.environ.get('APP_HOST', '0.0.0.0')
    port = int(os.environ.get('APP_PORT', '8000'))
    log_level = os.environ.get('LOG_LEVEL', 'info')
    config = uvicorn.Config('server.main:app', host=host, port=port, log_level=log_level)
    server = uvicorn.Server(config)
    await server.serve()

async def main():
    # Test shortcut: bail out quickly (used by unit test)
    if os.environ.get('ENTRYPOINT_TEST_MODE') == '1':
        import logging; logging.getLogger(__name__).info("ENTRYPOINT_TEST_MODE active – skipping launch")
        return
    os.environ.setdefault('INPROCESS_AUTONOMOUS', '0')
    import logging; logging.getLogger(__name__).info("Starting server + worker", extra={
        'host': os.environ.get('APP_HOST', '0.0.0.0'),
        'port': os.environ.get('APP_PORT', '8000'),
    })
    server_task = asyncio.create_task(_run_server(), name='uvicorn_server')
    worker_task = asyncio.create_task(_supervise_worker(), name='scraper_worker_supervisor')
    done, pending = await asyncio.wait({server_task, worker_task}, return_when=asyncio.FIRST_COMPLETED)
    for t in pending:
        t.cancel()
        try: await t
        except Exception: pass

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('\n[entrypoint] Interrupted')
