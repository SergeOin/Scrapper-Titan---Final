"""Centralised structured error registry for Playwright failures.

Writes JSON lines to a configurable file (env PLAYWRIGHT_FAILURE_LOG, default playwright_failures.log).
Per-process aggregation keeps an in-memory counter to avoid excessive disk writes for identical signatures.
"""
from __future__ import annotations
import os, json, time, threading
from dataclasses import dataclass, asdict
from typing import Dict

_lock = threading.Lock()
_counts: Dict[str, int] = {}

@dataclass
class PlaywrightFailure:
    ts: float
    category: str
    signature: str
    message: str
    occurrences: int

def _log_path() -> str:
    return os.environ.get("PLAYWRIGHT_FAILURE_LOG", "playwright_failures.log")

def log_playwright_failure(category: str, exc: Exception | str) -> None:
    sig = f"{category}:{type(exc).__name__ if not isinstance(exc, str) else 'str'}"
    msg = str(exc)
    with _lock:
        count = _counts.get(sig, 0) + 1
        _counts[sig] = count
        # Only write every first 3 + then every 10th occurrence to reduce volume
        if count > 3 and (count % 10) != 0:
            return
        rec = PlaywrightFailure(ts=time.time(), category=category, signature=sig, message=msg, occurrences=count)
        try:
            with open(_log_path(), "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")
        except Exception:
            pass
