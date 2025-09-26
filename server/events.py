"""Simple in-process event broadcaster for Server-Sent Events (SSE).

Usage:
  from .events import broadcast, EventType
  await broadcast({"type": EventType.JOB_COMPLETE, "last_run": iso})

Dashboard will connect to /stream and receive JSON lines formatted as SSE:
  event: message\n
  data: { ... json ... }\n\n
We keep it intentionally minimal (no persistence). If no listeners -> event is dropped.
"""
from __future__ import annotations

import asyncio
import json
from enum import Enum
from typing import Any, AsyncIterator, Dict, List

class EventType(str, Enum):
    JOB_COMPLETE = "job_complete"
    TOGGLE = "toggle"
    HEALTH = "health"  # reserved for future proactive pings
    QUOTA = "quota"  # daily quota milestone events
    RISK_COOLDOWN = "risk_cooldown"  # anti-ban cooldown triggered

_listeners: List[asyncio.Queue[Dict[str, Any]]] = []
_lock = asyncio.Lock()

async def register_listener() -> asyncio.Queue[Dict[str, Any]]:
    q: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=100)
    async with _lock:
        _listeners.append(q)
    return q

async def unregister_listener(q: asyncio.Queue[Dict[str, Any]]):
    async with _lock:
        try:
            _listeners.remove(q)
        except ValueError:
            pass

async def broadcast(payload: Dict[str, Any]):
    # Fire-and-forget: push to all queues (drop on full to avoid blocking)
    dead: List[asyncio.Queue[Dict[str, Any]]] = []
    for q in list(_listeners):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            dead.append(q)
    if dead:
        async with _lock:
            for dq in dead:
                if dq in _listeners:
                    _listeners.remove(dq)

async def sse_event_iter() -> AsyncIterator[bytes]:
    q = await register_listener()
    try:
        while True:
            item = await q.get()
            # JSON encode
            data = json.dumps(item, ensure_ascii=False)
            # Basic SSE frame
            yield f"event: message\ndata: {data}\n\n".encode("utf-8")
    except asyncio.CancelledError:  # graceful disconnect
        pass
    finally:
        await unregister_listener(q)
