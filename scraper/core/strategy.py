"""Pacing / quota strategy abstraction."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
import random

@dataclass
class QuotaState:
    collected_today: int
    target: int
    soft_target: int
    hour: int

def next_sleep_seconds(state: QuotaState) -> int:
    # Simple heuristic extracted from previous inline logic; can be evolved.
    if state.collected_today >= state.target:
        return random.randint(900, 1500)
    if state.collected_today < state.soft_target:
        return random.randint(120, 300)
    # Moderate pacing
    return random.randint(300, 900)
