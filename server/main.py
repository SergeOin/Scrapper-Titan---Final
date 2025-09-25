"""FastAPI application entrypoint.

Responsibilities:
- Create the FastAPI app with lifespan context
- Attach middleware: logging, CORS (if needed), security headers basic
- Include API/dashboard routes
- Provide JSON settings & root redirects if necessary

Notes:
- Logging already configured in scraper.bootstrap when context is created.
- We ensure context initialization in lifespan so routes can rely on it.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
import contextlib
from typing import AsyncIterator
import asyncio

from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uuid
import structlog
from structlog import contextvars as struct_contextvars
from fastapi.responses import RedirectResponse

from scraper.bootstrap import get_context, API_RATE_LIMIT_REJECTIONS
import time
import asyncio
from collections import OrderedDict

# Simple in-memory per-IP token buckets (best-effort; for multi-instance deploy use Redis)
class _PerIPBucket:
    def __init__(self, capacity: int, refill_per_min: int):
        self.capacity = capacity
        self.refill_rate = refill_per_min / 60.0  # tokens per second
        self.tokens = float(capacity)
        self.last = time.monotonic()

    def allow(self) -> bool:
        now = time.monotonic()
        elapsed = now - self.last
        if elapsed > 0:
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
            self.last = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False

_ip_buckets: "OrderedDict[str, _PerIPBucket]" = OrderedDict()
_ip_lock = asyncio.Lock()
_MAX_BUCKETS = 512  # LRU size cap
from .routes import router as core_router

# ------------------------------------------------------------
# Lifespan: initialize global context once app starts
# ------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:  # noqa: D401
    ctx = await get_context()
    # Respect quiet startup setting to avoid noisy JSON logs
    if getattr(ctx.settings, "quiet_startup", False):
        ctx.logger.debug("api_startup")
    else:
        ctx.logger.info("api_startup")
    bg_task: asyncio.Task | None = None
    # In-process autonomous worker
    # Behavior:
    #  - If no Redis is configured, we always start the in-process worker so the dashboard alone is sufficient.
    #  - If Redis exists (typical multi-process deploy), we keep opt-in via INPROCESS_AUTONOMOUS to avoid duplicate workers.
    interval = ctx.settings.autonomous_worker_interval_seconds
    want_inprocess = (ctx.redis is None) or (os.environ.get("INPROCESS_AUTONOMOUS", "0").lower() in ("1", "true", "yes"))
    if want_inprocess:
        if interval > 0:
            async def _periodic():
                logger = ctx.logger.bind(component="inprocess_worker")
                logger.info("inprocess_autonomous_started", interval=interval, mode=("no_redis" if ctx.redis is None else "env_opt_in"))
                while True:
                    try:
                        if ctx.settings.scraping_enabled:
                            from scraper.worker import process_job  # local import to avoid cycles
                            await process_job(ctx.settings.keywords, ctx)
                            logger.info("inprocess_cycle_complete")
                        else:
                            logger.debug("scraping_disabled_skip")
                    except Exception as exc:  # pragma: no cover
                        logger.error("inprocess_cycle_failed", error=str(exc))
                    await asyncio.sleep(interval)
            bg_task = asyncio.create_task(_periodic())
        else:
            ctx.logger.info("inprocess_autonomous_disabled_interval_zero")
    try:
        yield
    except asyncio.CancelledError:  # graceful shutdown triggered
        if getattr(ctx.settings, "quiet_startup", False):
            ctx.logger.debug("api_shutdown_cancelled")
        else:
            ctx.logger.info("api_shutdown_cancelled")
        raise
    finally:
        if bg_task:
            bg_task.cancel()
            with contextlib.suppress(Exception):
                await bg_task
        if getattr(ctx.settings, "quiet_startup", False):
            ctx.logger.debug("api_shutdown")
        else:
            ctx.logger.info("api_shutdown")


app = FastAPI(title="LinkedIn Scraper Dashboard", version="0.1.0", lifespan=lifespan)

# Configure CORS if public dashboard
import os
if os.environ.get("DASHBOARD_PUBLIC", "0").lower() in ("1", "true", "yes"):  # permissive for demo
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# ------------------------------------------------------------
# Basic middleware (could be expanded later)
# ------------------------------------------------------------
@app.middleware("http")
async def security_headers(request: Request, call_next):  # noqa: D401
    # Inject request id
    rid = str(uuid.uuid4())
    struct_contextvars.bind_contextvars(request_id=rid)
    # Basic per-IP rate limit (skip metrics & health for noiseless ops)
    path = request.url.path
    def _skip_rate_limit(p: str) -> bool:
        # Allowlist UI-critical paths to keep the dashboard snappy
        if p in ("/metrics", "/health", "/stream", "/toggle", "/api/trash/count"):
            return True
        if p.startswith("/api/posts"):
            return True
        if p.startswith("/export/excel"):
            return True
        return False
    if not _skip_rate_limit(path):
        ctx = await get_context()
        ip = request.client.host if request.client else "unknown"
        async with _ip_lock:
            bucket = _ip_buckets.get(ip)
            if bucket is None:
                bucket = _PerIPBucket(ctx.settings.api_rate_limit_burst, ctx.settings.api_rate_limit_per_min)
                _ip_buckets[ip] = bucket
            else:
                # move to end (recently used)
                _ip_buckets.move_to_end(ip)
            if len(_ip_buckets) > _MAX_BUCKETS:
                # pop oldest
                _ip_buckets.popitem(last=False)
            allowed = bucket.allow()
        if not allowed:
            API_RATE_LIMIT_REJECTIONS.inc()
            return Response(status_code=429, content="Rate limit exceeded")

    response: Response = await call_next(request)
    # Minimal security headers (adjust if behind reverse proxy)
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Request-ID", rid)
    # Clear contextvars to avoid leakage
    struct_contextvars.clear_contextvars()
    return response


# ------------------------------------------------------------
# Include routes
# ------------------------------------------------------------
app.include_router(core_router)


# Optional root redirect (already / is dashboard) kept simple
@app.get("/root")
async def root_redirect():
    return RedirectResponse("/")


# For local dev run: uvicorn server.main:app --reload
