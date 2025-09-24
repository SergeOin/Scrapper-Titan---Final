"""Bootstrap module for the scraping subsystem.

Central responsibilities:
- Load and validate settings from environment (.env loaded externally or by Settings class)
- Configure structured logging (structlog + rotating handlers)
- Initialize asynchronous clients: Mongo (Motor) and Redis
- Provide a shared context object for the worker logic
- Expose Prometheus metric instruments (counters, histograms)

Design notes:
- Avoid heavy imports at module import time (lazy when possible)
- Ensure idempotent initialization (safe to call bootstrap() once in worker entry
- Support fallback when Mongo or Redis are unavailable (handled later in worker/storage layer)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING
import asyncio
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import time

import structlog
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Optional / future: we import lazily inside functions to avoid
# forcing dependencies when only part of the system is used.
try:
    from motor.motor_asyncio import AsyncIOMotorClient  # type: ignore
except Exception:  # pragma: no cover - if not installed or during type checking
    AsyncIOMotorClient = Any  # type: ignore

try:
    import redis.asyncio as aioredis  # type: ignore
except Exception:  # pragma: no cover
    aioredis = None  # type: ignore

from prometheus_client import Counter, Histogram, Gauge

# ------------------------------------------------------------
# Settings
# ------------------------------------------------------------

class Settings(BaseSettings):
    """Application settings loaded from environment.

    Uses Pydantic BaseSettings to automatically read from env vars.
    Provide defaults that are safe for local development.
    """

    app_name: str = Field("linkedin-scraper", alias="APP_NAME")
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    log_file: str | None = Field(None, alias="LOG_FILE")
    log_max_bytes: int = Field(2_000_000, alias="LOG_MAX_BYTES")  # ~2MB
    log_backup_count: int = Field(5, alias="LOG_BACKUP_COUNT")
    scraping_enabled: bool = Field(True, alias="SCRAPING_ENABLED")
    playwright_headless: bool = Field(True, alias="PLAYWRIGHT_HEADLESS")
    playwright_mock_mode: bool = Field(False, alias="PLAYWRIGHT_MOCK_MODE")  # Synthetic data mode (no real browser)
    max_mock_posts: int = Field(5, alias="MAX_MOCK_POSTS")
    # Login UX & flow
    playwright_headless_scrape: bool = Field(True, alias="PLAYWRIGHT_HEADLESS_SCRAPE")  # scraping runs headless
    playwright_login_timeout_ms: int = Field(90_000, alias="PLAYWRIGHT_LOGIN_TIMEOUT_MS")
    captcha_max_wait_ms: int = Field(600_000, alias="CAPTCHA_MAX_WAIT_MS")
    browser_force_close: bool = Field(False, alias="BROWSER_FORCE_CLOSE")

    # Concurrency & pacing
    concurrency_limit: int = Field(2, alias="CONCURRENCY_LIMIT")
    per_keyword_delay_ms: int = Field(500, alias="PER_KEYWORD_DELAY_MS")  # extra pacing between keywords
    global_rate_limit_per_min: int = Field(120, alias="GLOBAL_RATE_LIMIT_PER_MIN")  # soft token bucket
    rate_limit_bucket_size: int = Field(120, alias="RATE_LIMIT_BUCKET_SIZE")
    rate_limit_refill_per_sec: float = Field(2.0, alias="RATE_LIMIT_REFILL_PER_SEC")  # tokens per second

    # Keywords & limits
    scrape_keywords_raw: str = Field("juriste;avocat;legal counsel;notaire", alias="SCRAPE_KEYWORDS")
    # Semicolon-separated list of keywords to always ignore (case-insensitive)
    blacklisted_keywords_raw: str = Field("python;ai", alias="BLACKLISTED_KEYWORDS")
    max_posts_per_keyword: int = Field(30, alias="MAX_POSTS_PER_KEYWORD")
    # Extraction scrolling controls
    max_scroll_steps: int = Field(5, alias="MAX_SCROLL_STEPS")  # Max scroll iterations per keyword page
    scroll_wait_ms: int = Field(1200, alias="SCROLL_WAIT_MS")  # Wait after each scroll to allow lazy load
    min_posts_target: int = Field(10, alias="MIN_POSTS_TARGET")  # Target minimum posts before considering extraction complete
    recruitment_signal_threshold: float = Field(0.05, alias="RECRUITMENT_SIGNAL_THRESHOLD")  # Score threshold for recruitment classification

    # Timeouts & retries
    navigation_timeout_ms: int = Field(15000, alias="NAVIGATION_TIMEOUT_MS")
    element_timeout_ms: int = Field(8000, alias="ELEMENT_TIMEOUT_MS")
    max_retries: int = Field(4, alias="MAX_RETRIES")

    # Cache / lock
    cache_ttl_seconds: int = Field(300, alias="CACHE_TTL_SECONDS")
    lock_file: str = Field(".scrape.lock", alias="LOCK_FILE")

    # Sleep jitter (rate-limit friendly)
    min_sleep_ms: int = Field(900, alias="MIN_SLEEP_MS")
    max_sleep_ms: int = Field(2500, alias="MAX_SLEEP_MS")

    # Mongo
    mongo_uri: str = Field("mongodb://localhost:27017", alias="MONGO_URI")
    mongo_db: str = Field("linkedin_scrape", alias="MONGO_DB")
    mongo_collection_posts: str = Field("posts", alias="MONGO_COLLECTION_POSTS")
    mongo_collection_meta: str = Field("meta", alias="MONGO_COLLECTION_META")
    mongo_connect_timeout_ms: int = Field(5000, alias="MONGO_CONNECT_TIMEOUT_MS")

    # Redis
    redis_url: str = Field("redis://localhost:6379/0", alias="REDIS_URL")
    redis_queue_key: str = Field("jobs:scrape", alias="REDIS_QUEUE_KEY")
    job_visibility_timeout: int = Field(300, alias="JOB_VISIBILITY_TIMEOUT")
    job_poll_interval: int = Field(3, alias="JOB_POLL_INTERVAL")

    # Optional: disable remote backends entirely (useful for pure-local SQLite mode)
    disable_mongo: bool = Field(False, alias="DISABLE_MONGO")
    disable_redis: bool = Field(False, alias="DISABLE_REDIS")

    # Fallback storage
    sqlite_path: str = Field("fallback.sqlite3", alias="SQLITE_PATH")
    csv_fallback_file: str = Field("exports/fallback_posts.csv", alias="CSV_FALLBACK_FILE")

    # Auth (optional internal)
    internal_auth_user: Optional[str] = Field(None, alias="INTERNAL_AUTH_USER")
    internal_auth_pass_hash: Optional[str] = Field(None, alias="INTERNAL_AUTH_PASS_HASH")
    internal_auth_pass: Optional[str] = Field(None, alias="INTERNAL_AUTH_PASS")  # Plaintext convenience (auto-hash)

    # Language / scoring
    default_lang: str = Field("fr", alias="DEFAULT_LANG")
    weight_length: float = Field(0.4, alias="WEIGHT_LENGTH")
    weight_media: float = Field(0.3, alias="WEIGHT_MEDIA")
    weight_keyword_density: float = Field(0.2, alias="WEIGHT_KEYWORD_DENSITY")
    weight_lang_match: float = Field(0.1, alias="WEIGHT_LANG_MATCH")

    # Misc
    enable_metrics: bool = Field(True, alias="ENABLE_METRICS")
    httpx_timeout: int = Field(15, alias="HTTPX_TIMEOUT")
    disable_ssl_verify: bool = Field(False, alias="DISABLE_SSL_VERIFY")
    trigger_token: Optional[str] = Field(None, alias="TRIGGER_TOKEN")  # Shared secret for /trigger endpoint
    shutdown_token: Optional[str] = Field(None, alias="SHUTDOWN_TOKEN")  # Shared secret for /shutdown endpoint
    api_rate_limit_per_min: int = Field(60, alias="API_RATE_LIMIT_PER_MIN")  # per-IP simple bucket
    api_rate_limit_burst: int = Field(20, alias="API_RATE_LIMIT_BURST")

    # Files / artifacts
    screenshot_dir: str = Field("screenshots", alias="SCREENSHOT_DIR")
    trace_dir: str = Field("traces", alias="TRACE_DIR")
    storage_state: str = Field("storage_state.json", alias="STORAGE_STATE")
    storage_state_b64: Optional[str] = Field(None, alias="STORAGE_STATE_B64")  # Base64-encoded storage_state content
    session_store_path: str = Field("session_store.json", alias="SESSION_STORE_PATH")
    # Initial manual login grace period (seconds) before first navigation to allow completing MFA / captcha
    login_initial_wait_seconds: int = Field(0, alias="LOGIN_INITIAL_WAIT_SECONDS")
    # Search hints and strict filters
    # When set, this hint will be appended to each keyword to bias results to a region (e.g., "France")
    search_geo_hint: str = Field("France", alias="SEARCH_GEO_HINT")
    # If true, only keep posts whose detected language matches DEFAULT_LANG
    filter_language_strict: bool = Field(True, alias="FILTER_LANGUAGE_STRICT")
    # If true, discard posts that do not meet recruitment signal threshold
    filter_recruitment_only: bool = Field(True, alias="FILTER_RECRUITMENT_ONLY")
    # If true, discard posts missing author or permalink (quality gate)
    filter_require_author_and_permalink: bool = Field(True, alias="FILTER_REQUIRE_AUTHOR_AND_PERMALINK")
    # Batch & resilience settings
    keywords_session_batch_size: int = Field(8, alias="KEYWORDS_SESSION_BATCH_SIZE")
    adaptive_pause_every: int = Field(0, alias="ADAPTIVE_PAUSE_EVERY")  # 0 = disabled
    adaptive_pause_seconds: float = Field(8.0, alias="ADAPTIVE_PAUSE_SECONDS")
    navigation_retry_attempts: int = Field(2, alias="NAVIGATION_RETRY_ATTEMPTS")  # extra attempts besides first
    navigation_retry_backoff_ms: int = Field(1200, alias="NAVIGATION_RETRY_BACKOFF_MS")
    # Public dashboard & autonomous worker
    dashboard_public: bool = Field(False, alias="DASHBOARD_PUBLIC")
    autonomous_worker_interval_seconds: int = Field(0, alias="AUTONOMOUS_WORKER_INTERVAL_SECONDS")  # 0=disabled

    # Quiet startup logs (suppresses info-level boot messages)
    quiet_startup: bool = Field(False, alias="QUIET_STARTUP")

    @field_validator("scrape_keywords_raw")
    @classmethod
    def _sanitize_keywords(cls, v: str) -> str:  # noqa: D401
        return v.strip()

    @property
    def keywords(self) -> list[str]:
        kws = [k.strip() for k in self.scrape_keywords_raw.split(";") if k.strip()]
        bl = {b.strip().lower() for b in (self.blacklisted_keywords_raw or "").split(";") if b.strip()}
        if bl:
            kws = [k for k in kws if k.lower() not in bl]
        return kws

    # Pydantic-settings v2 configuration
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        validate_assignment=True,
        extra="ignore",
        populate_by_name=True,
    )


# ------------------------------------------------------------
# Runtime state persistence (scraping_enabled toggle) stored in lightweight JSON file.
# ------------------------------------------------------------
_RUNTIME_STATE_FILE = Path("runtime_state.json")

def _load_runtime_state() -> dict[str, Any]:
    if _RUNTIME_STATE_FILE.exists():
        try:
            import json as _json
            return _json.loads(_RUNTIME_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def _save_runtime_state(data: dict[str, Any]) -> None:
    try:
        import json as _json
        _RUNTIME_STATE_FILE.write_text(_json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


# ------------------------------------------------------------
# Logging configuration (structlog)
# ------------------------------------------------------------

def configure_logging(level: str = "INFO", settings: Settings | None = None) -> None:
    """Configure structured logging with structlog.

    Uses a standard logging handler + structlog processors for JSON output.
    Rotating handlers could be added; for simplicity we rely on size/time rotation
    at a later refinement stage (or when implementing the logging improvements task).
    """
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    def add_request_id(logger, method_name, event_dict):  # noqa: D401
        rid = structlog.contextvars.get_contextvars().get("request_id")
        if rid:
            event_dict["request_id"] = rid
        return event_dict

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            timestamper,
            add_request_id,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper(), logging.INFO)),
        cache_logger_on_first_use=True,
    )

    handlers: list[logging.Handler] = []
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(logging.Formatter("%(message)s"))
    handlers.append(stream_handler)

    if settings and settings.log_file:
        try:
            log_path = Path(settings.log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                settings.log_file,
                maxBytes=settings.log_max_bytes,
                backupCount=settings.log_backup_count,
                encoding="utf-8",
            )
            file_handler.setFormatter(logging.Formatter("%(message)s"))
            handlers.append(file_handler)
        except Exception as e:  # pragma: no cover
            print(f"Failed to set file handler: {e}", file=sys.stderr)

    root = logging.getLogger()
    root.handlers = handlers
    root.setLevel(getattr(logging, level.upper(), logging.INFO))


# ------------------------------------------------------------
# Metrics instruments
# ------------------------------------------------------------
SCRAPE_JOBS_TOTAL = Counter(
    "scrape_jobs_total", "Total scrape jobs processed", labelnames=("status",)
)
SCRAPE_DURATION_SECONDS = Histogram(
    "scrape_duration_seconds", "Duration of a scrape job in seconds"
)
SCRAPE_POSTS_EXTRACTED = Counter(
    "scrape_posts_extracted_total", "Number of posts extracted per job"
)
SCRAPE_MOCK_POSTS_EXTRACTED = Counter(
    "scrape_mock_posts_extracted_total", "Number of synthetic mock posts generated"
)

# Extended metrics
SCRAPE_STORAGE_ATTEMPTS = Counter(
    "scrape_storage_attempts_total", "Storage attempts by backend", labelnames=("backend", "result")
)
SCRAPE_QUEUE_DEPTH = Gauge(
    "scrape_queue_depth", "Current depth of the scrape jobs queue"
)
SCRAPE_JOB_FAILURES = Counter(
    "scrape_job_failures_total", "Number of job failures (exceptions)"
)
SCRAPE_STEP_DURATION = Histogram(
    "scrape_step_duration_seconds", "Duration of internal scrape steps", labelnames=("step",)
)

# Rate limit metrics
SCRAPE_RATE_LIMIT_WAIT = Counter(
    "scrape_rate_limit_wait_seconds_total", "Cumulative seconds spent waiting for rate limit tokens"
)
SCRAPE_RATE_LIMIT_TOKENS = Gauge(
    "scrape_rate_limit_tokens", "Approximate current number of available tokens"
)

# API rate limit metric
API_RATE_LIMIT_REJECTIONS = Counter(
    "api_rate_limit_rejections_total", "Total API requests rejected due to rate limiting"
)

# Scrolling / extraction completeness metrics
SCRAPE_SCROLL_ITERATIONS = Counter(
    "scrape_scroll_iterations_total", "Total scroll iterations performed during extraction"
)
SCRAPE_EXTRACTION_INCOMPLETE = Counter(
    "scrape_extraction_incomplete_total", "Extractions that ended below the configured MIN_POSTS_TARGET"
)

# Recruitment classified posts
SCRAPE_RECRUITMENT_POSTS = Counter(
    "scrape_recruitment_posts_total", "Posts classified as recruitment-related (above threshold)"
)


# ------------------------------------------------------------
# Context dataclass
# ------------------------------------------------------------
@dataclass(slots=True)
class AppContext:
    settings: Settings
    logger: structlog.BoundLogger
    mongo_client: Optional[Any] = None
    redis: Optional[Any] = None
    token_bucket: Optional["TokenBucket"] = None
    # quick helper
    def has_valid_session(self) -> bool:
        try:
            return Path(self.settings.storage_state).exists() and Path(self.settings.storage_state).stat().st_size > 4
        except Exception:
            return False

if TYPE_CHECKING:  # pragma: no cover
    from .rate_limit import TokenBucket

    def mongo_db(self):  # type: ignore[override]
        if self.mongo_client:
            return self.mongo_client[self.settings.mongo_db]
        return None


_context_singleton: Optional[AppContext] = None
_context_lock = asyncio.Lock()


# ------------------------------------------------------------
# Initialization helpers
# ------------------------------------------------------------
async def init_mongo(settings: Settings, logger: structlog.BoundLogger) -> Optional[Any]:
    """Initialize Mongo client or return None if connection fails.

    We do a lightweight ping to validate connectivity. Fallback handled elsewhere.
    """
    if AsyncIOMotorClient is Any:  # missing dependency
        logger.warning("mongo_dependency_missing")
        return None

    try:
        client = AsyncIOMotorClient(
            settings.mongo_uri,
            serverSelectionTimeoutMS=settings.mongo_connect_timeout_ms,
            tz_aware=True,
        )
        await client.admin.command("ping")
        logger.info("mongo_connected", uri=settings.mongo_uri)
        return client
    except Exception as exc:  # pragma: no cover - depends on environment
        # If pointing to a local default instance (localhost:27017), treat as optional and avoid noisy error logs.
        uri = settings.mongo_uri or ""
        if (("localhost" in uri) or ("127.0.0.1" in uri)) and (":27017" in uri):
            logger.debug("mongo_unavailable_local_fallback", error=str(exc))
        else:
            logger.error("mongo_connection_failed", error=str(exc))
        return None


async def init_redis(settings: Settings, logger: structlog.BoundLogger) -> Optional[Any]:
    """Initialize Redis client if library available else return None."""
    if aioredis is None:
        logger.warning("redis_dependency_missing")
        return None
    try:
        redis_client = aioredis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
        # Simple ping
        await redis_client.ping()
        logger.info("redis_connected", url=settings.redis_url)
        return redis_client
    except Exception as exc:  # pragma: no cover
        # If pointing to a local default instance (localhost:6379), treat as optional and avoid noisy error logs.
        url = settings.redis_url or ""
        if (("localhost" in url) or ("127.0.0.1" in url)) and (":6379" in url):
            logger.debug("redis_unavailable_local_fallback", error=str(exc))
        else:
            logger.error("redis_connection_failed", error=str(exc))
        return None


async def bootstrap(force: bool = False) -> AppContext:
    """Create (or return existing) application context.

    Args:
        force: Recreate the context even if already initialized (rarely needed).
    """
    global _context_singleton
    if _context_singleton and not force:
        return _context_singleton

    async with _context_lock:
        if _context_singleton and not force:
            return _context_singleton

        settings = Settings()  # Loads from env automatically
        # Merge persisted runtime state (only known keys to avoid pollution)
        rt = _load_runtime_state()
        if isinstance(rt, dict) and "scraping_enabled" in rt:
            try:
                settings.scraping_enabled = bool(rt["scraping_enabled"])  # type: ignore[attr-defined]
            except Exception:
                pass

        # Lightweight Basic Auth convenience: if INTERNAL_AUTH_PASS provided (plaintext) and no hash, generate one
        if settings.internal_auth_pass and not settings.internal_auth_pass_hash:
            try:
                from passlib.hash import bcrypt  # type: ignore
                settings.internal_auth_pass_hash = bcrypt.hash(settings.internal_auth_pass)  # type: ignore[attr-defined]
            except Exception:
                print("[bootstrap] Impossible de générer le hash bcrypt (passlib manquant?)", file=sys.stderr)

        # Base64 storage_state injection (Playwright session) if file absent and STORAGE_STATE_B64 defined
        try:
            if settings.storage_state_b64 and settings.storage_state and not Path(settings.storage_state).exists():
                import base64, json as _json
                decoded = base64.b64decode(settings.storage_state_b64)
                # Validation basique: vérifier que c'est un JSON
                try:
                    _json.loads(decoded.decode("utf-8", errors="ignore"))
                except Exception:
                    print("[bootstrap] STORAGE_STATE_B64 décodé mais JSON invalide (écriture brute quand même)")
                Path(settings.storage_state).write_bytes(decoded)
                print(f"[bootstrap] storage_state.json créé depuis STORAGE_STATE_B64 ({len(decoded)} octets)")
        except Exception as e:
            print(f"[bootstrap] Décodage STORAGE_STATE_B64 échoué: {e}", file=sys.stderr)
        configure_logging(settings.log_level, settings)
        logger = structlog.get_logger().bind(component="bootstrap")

        # Ensure directories
        for d in (settings.screenshot_dir, settings.trace_dir, Path(settings.csv_fallback_file).parent):
            try:
                Path(d).mkdir(parents=True, exist_ok=True)
            except Exception as e:  # pragma: no cover
                logger.warning("directory_creation_failed", path=d, error=str(e))

        t0 = time.perf_counter()
        # Respect opt-out flags for remote backends
        if settings.disable_mongo:
            logger.debug("mongo_disabled_by_env")
            mongo_client = None
        else:
            mongo_client = await init_mongo(settings, logger)

        if settings.disable_redis:
            logger.debug("redis_disabled_by_env")
            redis_client = None
        else:
            redis_client = await init_redis(settings, logger)
        elapsed = time.perf_counter() - t0

        # Lazy import to avoid circular (rate_limit imports bootstrap metrics)
        from .rate_limit import TokenBucket  # noqa: WPS433

        token_bucket = TokenBucket.create(settings.rate_limit_bucket_size, settings.rate_limit_refill_per_sec)

        ctx = AppContext(
            settings=settings,
            logger=logger.bind(subsystem="core"),
            mongo_client=mongo_client,
            redis=redis_client,
            token_bucket=token_bucket,
        )
        log_method = logger.debug if settings.quiet_startup else logger.info
        log_method(
            "bootstrap_complete",
            mongo=bool(mongo_client),
            redis=bool(redis_client),
            elapsed=f"{elapsed:.3f}s",
            keywords=settings.keywords,
            scraping_enabled=settings.scraping_enabled,
        )
        _context_singleton = ctx
        return ctx


# ------------------------------------------------------------
# Helper accessors
# ------------------------------------------------------------
async def get_context() -> AppContext:
    """Public accessor for the global application context."""
    return await bootstrap()


# For ad-hoc manual test (python -m scraper.bootstrap)
if __name__ == "__main__":  # pragma: no cover
    async def _demo():
        ctx = await bootstrap(force=True)
        print("Context ready. Mongo?", bool(ctx.mongo_client), "Redis?", bool(ctx.redis))

    asyncio.run(_demo())
