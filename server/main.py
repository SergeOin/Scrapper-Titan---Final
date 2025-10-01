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
import sys
import logging

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
    # Diagnostic: log effective event loop policy class (helps validate Playwright NotImplementedError root cause fix)
    try:
        loop_policy_cls = asyncio.get_event_loop_policy().__class__.__name__  # type: ignore[attr-defined]
        ctx.logger.info("loop_policy_detected", policy=loop_policy_cls)
        # Subprocess probe: if a trivial subprocess creation already raises NotImplementedError we know it's global.
        async def _probe_subprocess():
            try:
                proc = await asyncio.create_subprocess_exec("cmd","/c","echo","probe", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                out, err = await proc.communicate()
                ctx.logger.info("subprocess_probe_ok", rc=proc.returncode, out=out.decode(errors='ignore').strip())
            except NotImplementedError:
                ctx.logger.error("subprocess_probe_not_implemented")
            except Exception as e:  # pragma: no cover
                ctx.logger.error("subprocess_probe_failed", error=str(e))
        try:
            await _probe_subprocess()
        except Exception:
            pass
    except Exception:
        logging.getLogger("server").warning("loop_policy_introspection_failed", exc_info=True)
    bg_task: asyncio.Task | None = None
    norm_task: asyncio.Task | None = None
    # In-process autonomous worker
    # Behavior:
    #  - If no Redis is configured, we always start the in-process worker so the dashboard alone is sufficient.
    #  - If Redis exists (typical multi-process deploy), we keep opt-in via INPROCESS_AUTONOMOUS to avoid duplicate workers.
    interval = ctx.settings.autonomous_worker_interval_seconds
    # Defensive: if desktop launcher injected env default (60) but settings still read 0 (e.g. early import ordering), re-read env.
    if interval == 0:
        try:
            env_val = int(os.environ.get("AUTONOMOUS_WORKER_INTERVAL_SECONDS", "0"))
            if env_val > 0:
                interval = env_val
        except Exception:
            pass
    # Decide whether to launch an in-process autonomous worker.
    # Previous behavior: always enabled when Redis was absent, causing duplication when an external
    # supervisor (e.g. scripts/run_all.py) also launched a worker. We now allow explicit disabling
    # by setting INPROCESS_AUTONOMOUS=0 even if Redis is None.
    flag = os.environ.get("INPROCESS_AUTONOMOUS")
    if ctx.redis is None:
        # Default ON unless explicitly disabled
        want_inprocess = flag is None or flag.lower() not in ("0", "false", "no")
    else:
        # With Redis present it's opt-in only
        want_inprocess = flag is not None and flag.lower() in ("1", "true", "yes")

    if want_inprocess:
        if interval > 0:
            async def _periodic():
                logger = ctx.logger.bind(component="inprocess_worker")
                logger.info("inprocess_autonomous_started", interval=interval, mode=("no_redis" if ctx.redis is None else "env_opt_in"))
                try:
                    setattr(ctx, "_autonomous_worker_active", True)
                except Exception:
                    pass
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
    # Periodic company normalization (SQLite only, opt-in via COMPANY_NORM_INTERVAL_SECONDS)
    norm_interval = getattr(ctx.settings, "company_norm_interval_seconds", 0)
    if norm_interval and norm_interval > 0 and ctx.settings.sqlite_path:
        async def _company_norm_loop():
            logger = ctx.logger.bind(component="company_norm")
            logger.info("company_norm_started", interval=norm_interval)
            import sqlite3, json, re
            from pathlib import Path
            CAPITAL_RE = re.compile(r"(?:(?:[A-Z][A-Za-z&\-]{1,}\s){0,3}[A-Z][A-Za-z&\-]{1,})")
            EXCLUDE = {"freelance","consultant","independant","indépendant","recruteur"}
            def derive(author: str, company: str|None, profile: str|None, text: str|None):
                try:
                    if company and company.strip() and company.strip().lower() != author.strip().lower():
                        return company
                    cand_blocks = []
                    if profile and profile.strip().startswith('{'):
                        try:
                            pobj = json.loads(profile)
                            for k in ("company","organization","org","headline","subtitle","occupation","title"):
                                v = pobj.get(k)
                                if isinstance(v,str): cand_blocks.append(v)
                        except Exception: pass
                    if text: cand_blocks.append(text[:240])
                    out_candidates = []
                    for raw in cand_blocks:
                        if not raw: continue
                        low = raw.lower()
                        for marker in ["chez "," at "," @"]:
                            if marker in low:
                                seg = raw[low.find(marker)+len(marker):]
                                out_candidates.append(seg)
                        for part in re.split(r"\s[|·•-]\s|,", raw):
                            out_candidates.append(part)
                        # Regex capital patterns
                        for m in CAPITAL_RE.findall(raw):
                            out_candidates.append(m)
                    cleaned = []
                    for c in out_candidates:
                        c2 = c.strip().strip('-–|·•').strip()
                        if not c2 or len(c2)<2: continue
                        if c2.lower()==author.lower(): continue
                        if c2.lower() in EXCLUDE: continue
                        if not any(ch.isalpha() for ch in c2): continue
                        if author.lower() in c2.lower(): continue
                        cleaned.append(c2)
                    for c3 in cleaned:
                        return c3[:120]
                except Exception:
                    return company
                return company
            async def _loop():
                while True:
                    try:
                        sp = ctx.settings.sqlite_path
                        if sp and Path(sp).exists():
                            conn = sqlite3.connect(sp)
                            conn.row_factory = sqlite3.Row
                            with conn:
                                try: conn.execute("ALTER TABLE posts ADD COLUMN company_norm TEXT")
                                except Exception: pass
                                cur = conn.execute("SELECT id, author, company, company_norm, author_profile, text FROM posts")
                                upd = 0; scanned = 0
                                # Ensure index on company_norm (idempotent)
                                try:
                                    conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_company_norm ON posts(company_norm)")
                                except Exception:
                                    pass
                                for r in cur.fetchall():
                                    scanned += 1
                                    author = r["author"] or ""
                                    if not author: continue
                                    comp = r["company"]
                                    comp_norm = r["company_norm"]
                                    prof = r["author_profile"]
                                    txt = r["text"]
                                    if comp_norm and comp_norm.strip():
                                        continue
                                    derived = derive(author, comp, prof, txt)
                                    if derived and (not comp or comp.strip().lower()==author.strip().lower() or derived!=comp):
                                        conn.execute("UPDATE posts SET company_norm=? WHERE id=?", (derived, r["id"]))
                                        upd += 1
                            logger.info("company_norm_cycle", updated=upd, scanned=scanned)
                    except Exception as exc:  # pragma: no cover
                        logger.error("company_norm_error", error=str(exc))
                    await asyncio.sleep(norm_interval)
            norm_task = asyncio.create_task(_loop())
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
            try:
                setattr(ctx, "_autonomous_worker_active", False)
            except Exception:
                pass
        if norm_task:
            norm_task.cancel()
            with contextlib.suppress(Exception):
                await norm_task
        if getattr(ctx.settings, "quiet_startup", False):
            ctx.logger.debug("api_shutdown")
        else:
            ctx.logger.info("api_shutdown")


app = FastAPI(title="LinkedIn Scraper Dashboard", version="0.1.0", lifespan=lifespan)

# On Windows allow selecting loop implementation; Selector loop tends to be more
# stable for Playwright subprocess spawning under reload. Use WIN_LOOP env var
# to override (values: 'selector' (default), 'proactor').
if sys.platform.startswith("win"):
    import os as _os
    desired = _os.environ.get("WIN_LOOP", "selector").lower()
    try:
        if desired.startswith("pro"):
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        else:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

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
        # Allowlist only essential low-cost endpoints (keep '/' subject to rate-limit for tests)
        if p in ("/metrics", "/health", "/stream", "/api/trash/count"):
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
                # If settings changed since bucket creation, refresh it to respect new test overrides
                if bucket.capacity != ctx.settings.api_rate_limit_burst or bucket.refill_rate != ctx.settings.api_rate_limit_per_min / 60.0:
                    bucket = _PerIPBucket(ctx.settings.api_rate_limit_burst, ctx.settings.api_rate_limit_per_min)
                    _ip_buckets[ip] = bucket
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
