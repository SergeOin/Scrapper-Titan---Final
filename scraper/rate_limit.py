from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Optional

from .bootstrap import SCRAPE_RATE_LIMIT_TOKENS, SCRAPE_RATE_LIMIT_WAIT

@dataclass
class TokenBucket:
    capacity: int
    refill_per_sec: float
    tokens: float
    last_refill: float
    _lock: asyncio.Lock

    @classmethod
    def create(cls, capacity: int, refill_per_sec: float) -> 'TokenBucket':
        now = time.monotonic()
        return cls(capacity=capacity, refill_per_sec=refill_per_sec, tokens=float(capacity), last_refill=now, _lock=asyncio.Lock())

    async def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self.last_refill
        if elapsed <= 0:
            return
        added = elapsed * self.refill_per_sec
        if added > 0:
            self.tokens = min(self.capacity, self.tokens + added)
            self.last_refill = now
            SCRAPE_RATE_LIMIT_TOKENS.set(self.tokens)

    async def consume(self, amount: int = 1) -> float:
        """Consume tokens; returns wait time (seconds) if had to wait, else 0."""
        async with self._lock:
            await self._refill()
            if self.tokens >= amount:
                self.tokens -= amount
                SCRAPE_RATE_LIMIT_TOKENS.set(self.tokens)
                return 0.0
            # Need to wait: compute time until enough tokens accrue.
            deficit = amount - self.tokens
            wait_time = deficit / self.refill_per_sec if self.refill_per_sec > 0 else 1.0
            self.tokens = max(0.0, self.tokens)  # clamp
        if wait_time > 0:
            await asyncio.sleep(wait_time)
            SCRAPE_RATE_LIMIT_WAIT.inc(wait_time)
        async with self._lock:
            await self._refill()
            if self.tokens >= amount:
                self.tokens -= amount
                SCRAPE_RATE_LIMIT_TOKENS.set(self.tokens)
            else:
                # fallback: force grant to avoid infinite wait due to float precision
                self.tokens = max(0.0, self.tokens - amount)
                SCRAPE_RATE_LIMIT_TOKENS.set(self.tokens)
        return wait_time
