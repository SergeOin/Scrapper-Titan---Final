"""Dedicated continuous worker launcher.

Usage:
  python scripts/run_worker.py

Honors autonomous interval settings:
  AUTONOMOUS_WORKER_INTERVAL_SECONDS > 0 => periodic cycles
Otherwise runs a single batch (same as run_once but via worker_loop).
"""
from __future__ import annotations

import asyncio
import os, sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from scraper.worker import worker_loop  # noqa: E402
import time


def _env_int(name: str, default: int) -> int:
  try:
    return int(os.environ.get(name, str(default)))
  except Exception:
    return default


async def _run_forever():
  delay = _env_int("WORKER_RESTART_DELAY_SECONDS", 5)
  while True:
    try:
      await worker_loop()
    except asyncio.CancelledError:
      raise
    except Exception as exc:
      print(f"[worker] Crash détecté: {exc}. Redémarrage dans {delay}s...", flush=True)
      await asyncio.sleep(delay)
    else:
      # worker_loop returned normally (e.g., single-run mode). Sleep then restart.
      await asyncio.sleep(delay)


def main():  # noqa: D401
  asyncio.run(_run_forever())

if __name__ == "__main__":
    main()
