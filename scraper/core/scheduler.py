"""Scheduler / pacing utilities (stub)."""
from __future__ import annotations
from datetime import datetime
from .strategy import QuotaState, next_sleep_seconds

def compute_next_pause(collected_today: int, target: int, soft: int) -> int:
    now = datetime.now()
    st = QuotaState(collected_today=collected_today, target=target, soft_target=soft, hour=now.hour)
    return next_sleep_seconds(st)
