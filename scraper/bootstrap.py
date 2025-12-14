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
    per_keyword_delay_ms: int = Field(300, alias="PER_KEYWORD_DELAY_MS")  # reduced delay between keywords for faster collection
    global_rate_limit_per_min: int = Field(120, alias="GLOBAL_RATE_LIMIT_PER_MIN")  # soft token bucket
    rate_limit_bucket_size: int = Field(120, alias="RATE_LIMIT_BUCKET_SIZE")
    rate_limit_refill_per_sec: float = Field(2.0, alias="RATE_LIMIT_REFILL_PER_SEC")  # tokens per second

    # Keywords & limits
    # OPTIMISÉ v4: 50+ keywords pour 70-100+ posts/jour
    # Stratégie: Combiner "signal de recrutement" + "rôle juridique" + "localisation France"
    # IMPORTANT: Plus de keywords = plus de cycles = plus de posts/jour
    scrape_keywords_raw: str = Field(
        # === RECRUTEMENT DIRECT (précision maximale) - 12 keywords ===
        "recrute juriste;recrute avocat;recrute notaire;recrute paralegal;"
        "nous recrutons juriste;nous recrutons avocat;nous recrutons notaire;"
        "on recrute juriste;on recrute avocat;on recrute notaire;"
        "je recrute juriste;je recrute avocat;"
        # === OFFRES D'EMPLOI EXPLICITES - 10 keywords ===
        "poste juriste;poste avocat;poste notaire;poste paralegal;"
        "offre emploi juriste;offre emploi avocat;offre emploi notaire;"
        "cdi juriste;cdi avocat;cdi notaire;"
        # === RECHERCHE DE PROFILS - 8 keywords ===
        "recherche juriste;recherche avocat;recherche notaire;recherche paralegal;"
        "cherche juriste;cherche avocat;cherche notaire;cherche paralegal;"
        # === POSTES DIRECTION JURIDIQUE - 8 keywords ===
        "recrute responsable juridique;recrute directeur juridique;"
        "poste responsable juridique;poste directeur juridique;"
        "head of legal;general counsel;legal counsel;chief legal officer;"
        # === VILLES FRANCE (volume) - 15 keywords ===
        "juriste Paris;avocat Paris;juriste Lyon;avocat Lyon;"
        "juriste Bordeaux;avocat Bordeaux;juriste Marseille;avocat Marseille;"
        "juriste Lille;avocat Lille;juriste Nantes;avocat Nantes;"
        "juriste Toulouse;juriste Strasbourg;juriste Nice;"
        # === SPÉCIALISATIONS JURIDIQUES - 12 keywords ===
        "juriste droit social;juriste contrats;juriste corporate;juriste M&A;"
        "avocat droit des affaires;avocat corporate;compliance officer;DPO;"
        "juriste conformite;juriste contentieux;juriste RGPD;juriste propriete intellectuelle;"
        # === CABINET / ENTREPRISE - 6 keywords ===
        "cabinet avocat recrute;cabinet juridique recrute;etude notariale recrute;"
        "direction juridique recrute;equipe juridique recrute;departement juridique recrute",
        alias="SCRAPE_KEYWORDS",
    )
    # Semicolon-separated list of keywords to always ignore (case-insensitive)
    blacklisted_keywords_raw: str = Field("python;ai;formation;webinaire;article", alias="BLACKLISTED_KEYWORDS")
    # Raise cap per keyword to collect more candidates before classifier filtering
    max_posts_per_keyword: int = Field(50, alias="MAX_POSTS_PER_KEYWORD")  # Réduit 80→50 pour qualité
    # Extraction scrolling controls
    # OPTIMISÉ v3: Scroll plus profond mais timeout raisonnable
    max_scroll_steps: int = Field(20, alias="MAX_SCROLL_STEPS")  # Max scroll iterations (augmenté 15→20)
    scroll_wait_ms: int = Field(800, alias="SCROLL_WAIT_MS")  # Wait après scroll (réduit 1000→800 pour rapidité)
    min_posts_target: int = Field(15, alias="MIN_POSTS_TARGET")  # Target minimum (réduit 30→15 pour éviter timeout)
    # Seuil de signal de recrutement - AUGMENTÉ pour exiger un vrai signal de recrutement
    # 0.15 = nécessite des termes explicites comme "recrute", "poste", "offre d'emploi"
    recruitment_signal_threshold: float = Field(0.15, alias="RECRUITMENT_SIGNAL_THRESHOLD")

    # Post age filter (3 weeks = 21 days - STRICTEMENT APPLIQUÉ)
    max_post_age_days: int = Field(21, alias="MAX_POST_AGE_DAYS")  # CRITIQUE: Posts > 21 jours REJETÉS
    
    # Stage/Alternance exclusion filter (enabled by default)
    filter_exclude_stage_alternance: bool = Field(True, alias="FILTER_EXCLUDE_STAGE_ALTERNANCE")

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

    # Fallback storage - use absolute path in LOCALAPPDATA for packaged app
    @staticmethod
    def _default_sqlite_path() -> str:
        """Return absolute path to SQLite database in LOCALAPPDATA."""
        if sys.platform == "win32":
            base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
            db_dir = os.path.join(base, "TitanScraper")
            os.makedirs(db_dir, exist_ok=True)
            return os.path.join(db_dir, "fallback.sqlite3")
        elif sys.platform == "darwin":
            base = os.path.expanduser("~/Library/Application Support/TitanScraper")
            os.makedirs(base, exist_ok=True)
            return os.path.join(base, "fallback.sqlite3")
        else:
            base = os.path.expanduser("~/.local/share/TitanScraper")
            os.makedirs(base, exist_ok=True)
            return os.path.join(base, "fallback.sqlite3")
    
    sqlite_path: str = Field(default_factory=lambda: Settings._default_sqlite_path(), alias="SQLITE_PATH")
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
    httpx_timeout: int = Field(20, alias="HTTPX_TIMEOUT")  # Augmenté 15→20 pour stabilité réseau
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
    # If true, discard posts that do not meet recruitment signal threshold (ACTIVÉ pour pertinence)
    filter_recruitment_only: bool = Field(True, alias="FILTER_RECRUITMENT_ONLY")
    # If true, discard posts missing author or permalink (quality gate)
    filter_require_author_and_permalink: bool = Field(True, alias="FILTER_REQUIRE_AUTHOR_AND_PERMALINK")
    # Domain filtering: ACTIVÉ - exige au moins un mot-clé juridique dans le post
    filter_legal_domain_only: bool = Field(True, alias="FILTER_LEGAL_DOMAIN_ONLY")
    # LEGAL FILTER: Filtre complet pour offres d'emploi juridiques (scoring + exclusions)
    filter_legal_posts_only: bool = Field(True, alias="FILTER_LEGAL_POSTS_ONLY")
    # Seuils de scoring pour le filtre légal (ajustables)
    legal_filter_recruitment_threshold: float = Field(0.15, alias="LEGAL_FILTER_RECRUITMENT_THRESHOLD")
    legal_filter_legal_threshold: float = Field(0.20, alias="LEGAL_FILTER_LEGAL_THRESHOLD")
    # Exclusions granulaires (toutes activées par défaut)
    legal_filter_exclude_stage: bool = Field(True, alias="LEGAL_FILTER_EXCLUDE_STAGE")
    legal_filter_exclude_freelance: bool = Field(True, alias="LEGAL_FILTER_EXCLUDE_FREELANCE")
    legal_filter_exclude_opentowork: bool = Field(True, alias="LEGAL_FILTER_EXCLUDE_OPENTOWORK")
    legal_filter_exclude_promo: bool = Field(True, alias="LEGAL_FILTER_EXCLUDE_PROMO")
    legal_filter_exclude_agencies: bool = Field(True, alias="LEGAL_FILTER_EXCLUDE_AGENCIES")
    legal_filter_exclude_foreign: bool = Field(True, alias="LEGAL_FILTER_EXCLUDE_FOREIGN")
    legal_filter_exclude_non_legal: bool = Field(True, alias="LEGAL_FILTER_EXCLUDE_NON_LEGAL")
    # Log verbose des exclusions (utile pour debug)
    legal_filter_verbose: bool = Field(True, alias="LEGAL_FILTER_VERBOSE")
    auto_favorite_opportunities: bool = Field(False, alias="AUTO_FAVORITE_OPPORTUNITIES")
    # Batch & resilience settings - ANTI-DETECTION: Optimisé pour 100 posts/jour en 7h
    keywords_session_batch_size: int = Field(5, alias="KEYWORDS_SESSION_BATCH_SIZE")  # 5 keywords/session
    adaptive_pause_every: int = Field(0, alias="ADAPTIVE_PAUSE_EVERY")  # 0 = disabled
    adaptive_pause_seconds: float = Field(8.0, alias="ADAPTIVE_PAUSE_SECONDS")
    navigation_retry_attempts: int = Field(2, alias="NAVIGATION_RETRY_ATTEMPTS")  # extra attempts besides first
    navigation_retry_backoff_ms: int = Field(1200, alias="NAVIGATION_RETRY_BACKOFF_MS")
    # Public dashboard & autonomous worker
    dashboard_public: bool = Field(False, alias="DASHBOARD_PUBLIC")
    # ANTI-DETECTION v5: Optimisé pour 100 posts/jour en 7h actives (1200s = 20min)
    # 7h = 420min ÷ 20min = 21 cycles × 5 posts/cycle = 105 posts/jour
    autonomous_worker_interval_seconds: int = Field(1200, alias="AUTONOMOUS_WORKER_INTERVAL_SECONDS")
    # Human-like cadence (optional) - Mode recommandé pour éviter détection anti-bot
    human_mode_enabled: bool = Field(True, alias="HUMAN_MODE_ENABLED")  # ACTIVÉ par défaut
    human_active_hours_start: int = Field(8, alias="HUMAN_ACTIVE_HOURS_START")   # Début 8h
    human_active_hours_end: int = Field(22, alias="HUMAN_ACTIVE_HOURS_END")      # Fin 22h (plage 8h-22h)
    # Jours actifs: 0=Lundi, 1=Mardi, 2=Mercredi, 3=Jeudi, 4=Vendredi (pas weekend)
    human_active_weekdays: str = Field("0,1,2,3,4", alias="HUMAN_ACTIVE_WEEKDAYS")  # Lundi-Vendredi
    human_min_cycle_pause_seconds: int = Field(30, alias="HUMAN_MIN_CYCLE_PAUSE_SECONDS")  # Pause min 30s
    human_max_cycle_pause_seconds: int = Field(90, alias="HUMAN_MAX_CYCLE_PAUSE_SECONDS")  # Pause max 90s
    human_long_break_probability: float = Field(0.05, alias="HUMAN_LONG_BREAK_PROBABILITY")  # 5% de chance de pause longue
    human_long_break_min_seconds: int = Field(300, alias="HUMAN_LONG_BREAK_MIN_SECONDS")
    human_long_break_max_seconds: int = Field(600, alias="HUMAN_LONG_BREAK_MAX_SECONDS")
    human_night_mode: bool = Field(True, alias="HUMAN_NIGHT_MODE")
    human_night_pause_min_seconds: int = Field(1800, alias="HUMAN_NIGHT_PAUSE_MIN_SECONDS")
    human_night_pause_max_seconds: int = Field(3600, alias="HUMAN_NIGHT_PAUSE_MAX_SECONDS")
    human_max_cycles_per_hour: int = Field(5, alias="HUMAN_MAX_CYCLES_PER_HOUR")  # 5 cycles/h max (augmenté pour volume)
    # Daily quota objective - 70-100+ posts/jour en 7h actives (PAS DE MAXIMUM)
    daily_post_target: int = Field(100, alias="DAILY_POST_TARGET")  # Objectif 100 posts/jour
    daily_post_soft_target: int = Field(70, alias="DAILY_POST_SOFT_TARGET")  # Seuil minimum 70
    # Legal domain classification & quota - PAS DE LIMITE HAUTE
    legal_daily_post_cap: int = Field(500, alias="LEGAL_DAILY_POST_CAP")  # Augmenté 150→500 (pas de max effectif)
    # Seuil de recrutement: augmenté pour plus de pertinence (0.25 = exige signal de recrutement clair)
    legal_intent_threshold: float = Field(0.25, alias="LEGAL_INTENT_THRESHOLD")
    legal_keywords_override: str | None = Field(None, alias="LEGAL_KEYWORDS")  # Optional semicolon list to extend/override builtin
    # Exclusion explicite de certaines sources (auteurs / entreprises) séparées par ';'
    # Inclut les cabinets de recrutement (concurrents) et sources non pertinentes
    excluded_authors_raw: str = Field(
        "village de la justice;michael page;robert half;hays;fed legal;fed juridique;"
        "page personnel;expectra;adecco;manpower;randstad;spring professional;"
        "lincoln associates;laurence simons;taylor root;major hunter;approach people;"
        "keljob;monster;cadremploi",
        alias="EXCLUDED_AUTHORS"
    )
    # Keywords de renfort (booster) injectés dynamiquement quand quota < 80%
    # OPTIMISÉ v3: Focus sur recrutement direct + variété géographique
    booster_keywords_raw: str = Field(
        # Volume général France
        "recrute juriste France;recrute avocat France;cdi juriste Paris;"
        "cdi avocat Paris;poste juriste France;poste avocat France;"
        # Directions juridiques
        "direction juridique recrute;entreprise recrute juriste;"
        "responsable juridique recrute;directeur juridique recrute;"
        # Autres villes pour diversité
        "juriste Nantes;juriste Toulouse;juriste Strasbourg;"
        "avocat Bordeaux;avocat Nice;avocat Rennes;"
        # Spécialisations en demande
        "juriste rgpd;juriste dpo;compliance manager;"
        "legal counsel France;head of legal Paris;"
        # Cabinets
        "cabinet avocat Paris recrute;etude notariale Paris;"
        "cabinet affaires recrute",
        alias="BOOSTER_KEYWORDS"
    )
    # Si True on assouplit certains filtres (recruitment threshold -10%) quand quota pas atteint
    relax_filters_below_target: bool = Field(True, alias="RELAX_FILTERS_BELOW_TARGET")
    # Ratio d'activation du booster (ex: 0.7 => si < 70% de l'objectif, on active)
    booster_activate_ratio: float = Field(0.7, alias="BOOSTER_ACTIVATE_RATIO")
    # Rotation automatique des booster keywords
    booster_rotation_enabled: bool = Field(True, alias="BOOSTER_ROTATION_ENABLED")
    # Taille du sous-ensemble rotatif utilisé par cycle (0 = tous)
    booster_rotation_subset_size: int = Field(5, alias="BOOSTER_ROTATION_SUBSET_SIZE")
    # Mélange aléatoire à chaque cycle (sinon round-robin stable)
    booster_rotation_shuffle: bool = Field(True, alias="BOOSTER_ROTATION_SHUFFLE")

    # Risk & pacing heuristics (anti-ban)
    # OPTIMISÉ: Seuils anti-ban plus tolérants pour éviter les cooldowns excessifs
    risk_auth_suspect_threshold: int = Field(3, alias="RISK_AUTH_SUSPECT_THRESHOLD")  # Augmenté 2→3
    risk_empty_keywords_threshold: int = Field(5, alias="RISK_EMPTY_KEYWORDS_THRESHOLD")  # Augmenté 3→5
    risk_cooldown_min_seconds: int = Field(90, alias="RISK_COOLDOWN_MIN_SECONDS")  # Réduit 120→90
    risk_cooldown_max_seconds: int = Field(180, alias="RISK_COOLDOWN_MAX_SECONDS")  # Réduit 300→180
    human_jitter_min_ms: int = Field(800, alias="HUMAN_JITTER_MIN_MS")
    human_jitter_max_ms: int = Field(2500, alias="HUMAN_JITTER_MAX_MS")
    adaptive_scroll_enabled: bool = Field(True, alias="ADAPTIVE_SCROLL")
    adaptive_scroll_min: int = Field(2, alias="ADAPTIVE_SCROLL_MIN")
    adaptive_scroll_max: int = Field(7, alias="ADAPTIVE_SCROLL_MAX")
    # Number of keywords window to compute moving average posts
    adaptive_scroll_window: int = Field(5, alias="ADAPTIVE_SCROLL_WINDOW")

    # Quiet startup logs (suppresses info-level boot messages)
    quiet_startup: bool = Field(False, alias="QUIET_STARTUP")
    # Fast first cycle (desktop UX): temporarily lower scroll steps & posts per keyword on very first run
    fast_first_cycle: bool = Field(True, alias="FAST_FIRST_CYCLE")
    # Company normalization background interval (seconds). 0 disables.
    company_norm_interval_seconds: int = Field(0, alias="COMPANY_NORM_INTERVAL_SECONDS")
    # Content filters: exclude job-seeker posts, enforce France locale
    filter_exclude_job_seekers: bool = Field(True, alias="FILTER_EXCLUDE_JOB_SEEKERS")
    filter_france_only: bool = Field(True, alias="FILTER_FRANCE_ONLY")
    # Hard disable flag (dev reload, maintenance). If true we never start scraping even if runtime toggle tries to enable it.
    disable_scraper: bool = Field(False, alias="DISABLE_SCRAPER")
    # When true, automatically disable scraper if a live reload environment is detected (uvicorn --reload)
    auto_disable_on_reload: bool = Field(True, alias="AUTO_DISABLE_ON_RELOAD")

    def __init__(self, **data):  # type: ignore[override]
        explicit = dict(data)
        super().__init__(**data)
        # Force assign provided keyword values by field name (not alias) to ensure tests overriding defaults work
        for k, v in explicit.items():
            if k in self.model_fields:  # type: ignore[attr-defined]
                try:
                    object.__setattr__(self, k, v)
                except Exception:
                    continue

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

    def redact_sensitive(logger, method_name, event_dict):  # noqa: D401
        """Best-effort redaction of secrets/PII in logs.

        This is intentionally conservative and shallow: it avoids logging tokens/cookies
        and obvious credentials if they accidentally get added to log context.
        """
        sensitive_keys = {
            "password",
            "pass",
            "pwd",
            "email",
            "authorization",
            "cookie",
            "cookies",
            "li_at",
            "token",
            "trigger_token",
            "shutdown_token",
            "x-trigger-token",
            "x-shutdown-token",
            "x-desktop-trigger",
        }

        def _scrub(value):
            if isinstance(value, dict):
                out = {}
                for k, v in value.items():
                    ks = str(k).lower()
                    if ks in sensitive_keys or any(sk in ks for sk in ("token", "password", "cookie", "authorization")):
                        out[k] = "[REDACTED]"
                    else:
                        out[k] = _scrub(v)
                return out
            if isinstance(value, (list, tuple)):
                return [_scrub(v) for v in value]
            return value

        return _scrub(event_dict)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            timestamper,
            add_request_id,
            structlog.processors.add_log_level,
            redact_sensitive,
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

# Filter reasons metrics (post-level rejections before persistence)
SCRAPE_FILTERED_POSTS = Counter(
    "scrape_filtered_posts_total", "Posts filtered out before persistence", labelnames=("reason",)
)

# Legal domain classification metrics
LEGAL_POSTS_TOTAL = Counter(
    "legal_posts_total", "Total legal-domain posts retained after classification"
)
LEGAL_POSTS_DISCARDED_TOTAL = Counter(
    "legal_posts_discarded_total", "Posts discarded by legal classifier", labelnames=("reason",)
)
LEGAL_INTENT_CLASSIFICATIONS_TOTAL = Counter(
    "legal_intent_classifications_total", "Intent decisions taken by classifier", labelnames=("intent",)
)
LEGAL_DAILY_CAP_REACHED = Counter(
    "legal_daily_cap_reached_total", "Times the legal daily cap was reached"
)

# Legal Filter metrics (is_legal_job_post)
LEGAL_FILTER_TOTAL = Counter(
    "legal_filter_total", "Total posts processed by legal filter"
)
LEGAL_FILTER_ACCEPTED = Counter(
    "legal_filter_accepted_total", "Posts accepted by legal filter"
)
LEGAL_FILTER_REJECTED = Counter(
    "legal_filter_rejected_total", "Posts rejected by legal filter", labelnames=("reason",)
)
LEGAL_FILTER_AVG_SCORE = Gauge(
    "legal_filter_avg_score", "Average score of accepted posts", labelnames=("score_type",)
)


# ------------------------------------------------------------
# Helper: Build FilterConfig from Settings
# ------------------------------------------------------------
def build_filter_config(settings: Settings) -> "FilterConfig":
    """Build FilterConfig from bootstrap Settings.
    
    Centralizes the creation of FilterConfig to ensure consistency
    between worker, API, and other components.
    """
    from .legal_filter import FilterConfig
    return FilterConfig(
        recruitment_threshold=getattr(settings, 'legal_filter_recruitment_threshold', 0.15),
        legal_threshold=getattr(settings, 'legal_filter_legal_threshold', 0.20),
        exclude_stage=getattr(settings, 'legal_filter_exclude_stage', True),
        exclude_freelance=getattr(settings, 'legal_filter_exclude_freelance', True),
        exclude_opentowork=getattr(settings, 'legal_filter_exclude_opentowork', True),
        exclude_promo=getattr(settings, 'legal_filter_exclude_promo', True),
        exclude_agencies=getattr(settings, 'legal_filter_exclude_agencies', True),
        exclude_foreign=getattr(settings, 'legal_filter_exclude_foreign', True),
        exclude_non_legal=getattr(settings, 'legal_filter_exclude_non_legal', True),
        verbose=getattr(settings, 'legal_filter_verbose', True),
    )


# ------------------------------------------------------------
# Session Filter Statistics
# ------------------------------------------------------------
@dataclass
class FilterSessionStats:
    """Track filter statistics for a scraping session."""
    total_processed: int = 0
    total_accepted: int = 0
    total_rejected: int = 0
    # Rejection reasons
    rejected_stage_alternance: int = 0
    rejected_freelance: int = 0
    rejected_opentowork: int = 0
    rejected_promo: int = 0
    rejected_agencies: int = 0
    rejected_foreign: int = 0
    rejected_non_legal: int = 0
    rejected_low_recruitment_score: int = 0
    rejected_low_legal_score: int = 0
    rejected_old_post: int = 0
    rejected_empty: int = 0
    # Score aggregates
    sum_recruitment_scores: float = 0.0
    sum_legal_scores: float = 0.0
    
    def record_result(self, filter_result: "FilterResult") -> None:
        """Record a filter result and update statistics."""
        self.total_processed += 1
        if filter_result.is_valid:
            self.total_accepted += 1
            self.sum_recruitment_scores += filter_result.recruitment_score
            self.sum_legal_scores += filter_result.legal_score
        else:
            self.total_rejected += 1
            reason = filter_result.exclusion_reason
            if reason == "stage_alternance":
                self.rejected_stage_alternance += 1
            elif reason == "freelance_mission":
                self.rejected_freelance += 1
            elif reason == "chercheur_emploi":
                self.rejected_opentowork += 1
            elif reason == "contenu_promotionnel":
                self.rejected_promo += 1
            elif reason == "cabinet_recrutement":
                self.rejected_agencies += 1
            elif reason == "hors_france":
                self.rejected_foreign += 1
            elif reason == "metier_non_juridique":
                self.rejected_non_legal += 1
            elif reason == "score_insuffisant_recrutement":
                self.rejected_low_recruitment_score += 1
            elif reason == "score_insuffisant_juridique":
                self.rejected_low_legal_score += 1
            elif reason == "post_trop_ancien":
                self.rejected_old_post += 1
            elif reason == "texte_vide":
                self.rejected_empty += 1
    
    @property
    def acceptance_rate(self) -> float:
        """Return acceptance rate (0-100%)."""
        if self.total_processed == 0:
            return 0.0
        return (self.total_accepted / self.total_processed) * 100
    
    @property
    def avg_recruitment_score(self) -> float:
        """Average recruitment score of accepted posts."""
        if self.total_accepted == 0:
            return 0.0
        return self.sum_recruitment_scores / self.total_accepted
    
    @property
    def avg_legal_score(self) -> float:
        """Average legal score of accepted posts."""
        if self.total_accepted == 0:
            return 0.0
        return self.sum_legal_scores / self.total_accepted
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON/API responses."""
        return {
            "total_processed": self.total_processed,
            "total_accepted": self.total_accepted,
            "total_rejected": self.total_rejected,
            "acceptance_rate_percent": round(self.acceptance_rate, 1),
            "avg_recruitment_score": round(self.avg_recruitment_score, 3),
            "avg_legal_score": round(self.avg_legal_score, 3),
            "rejections": {
                "stage_alternance": self.rejected_stage_alternance,
                "freelance": self.rejected_freelance,
                "opentowork": self.rejected_opentowork,
                "promotional": self.rejected_promo,
                "agencies": self.rejected_agencies,
                "foreign": self.rejected_foreign,
                "non_legal": self.rejected_non_legal,
                "low_recruitment_score": self.rejected_low_recruitment_score,
                "low_legal_score": self.rejected_low_legal_score,
                "old_post": self.rejected_old_post,
                "empty": self.rejected_empty,
            }
        }
    
    def summary(self) -> str:
        """Return a human-readable summary."""
        return (
            f"📊 Filtre: {self.total_accepted}/{self.total_processed} acceptés "
            f"({self.acceptance_rate:.1f}%)\n"
            f"   Scores moyens: recrutement={self.avg_recruitment_score:.2f}, "
            f"juridique={self.avg_legal_score:.2f}\n"
            f"   Rejets: stage={self.rejected_stage_alternance}, "
            f"freelance={self.rejected_freelance}, "
            f"opentowork={self.rejected_opentowork}, "
            f"promo={self.rejected_promo}, "
            f"agences={self.rejected_agencies}, "
            f"étranger={self.rejected_foreign}, "
            f"non-juridique={self.rejected_non_legal}"
        )


if TYPE_CHECKING:
    from .legal_filter import FilterConfig, FilterResult


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
    # Risk counters (anti-ban heuristics)
    _risk_auth_suspect: int = 0
    _risk_empty_runs: int = 0
    # Daily quota tracking
    daily_post_count: int = 0
    daily_post_date: Optional[str] = None
    # Legal domain daily quota & discard tracking (must be explicit due to slots)
    legal_daily_date: Optional[str] = None
    legal_daily_count: int = 0
    legal_daily_discard_intent: int = 0
    legal_daily_discard_location: int = 0
    # UI stats tracking date marker used by /api/legal_stats
    legal_stats_date: Optional[str] = None
    # Relaxed mode flag (bypass strict legal filters for autonomous worker testing)
    _relaxed_filters: bool = False
    # Autonomous worker active flag
    _autonomous_worker_active: bool = False
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
    except asyncio.CancelledError:
        # Don't let CancelledError crash the app - just skip Mongo
        logger.warning("mongo_connection_cancelled", hint="Connexion annulée, utilisation de SQLite")
        return None
    except Exception as exc:  # pragma: no cover - depends on environment
        # If pointing to a local default instance (localhost:27017), treat as optional and avoid noisy error logs.
        uri = settings.mongo_uri or ""
        if (("localhost" in uri) or ("127.0.0.1" in uri)) and (":27017" in uri):
            logger.warning(
                "mongo_unavailable_local_fallback",
                error=str(exc),
                hint="Démarrez MongoDB ou définissez DISABLE_MONGO=1 pour rester sur SQLite",
            )
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
    except asyncio.CancelledError:
        # Don't let CancelledError crash the app - just skip Redis
        logger.warning("redis_connection_cancelled", hint="Connexion annulée, utilisation du mode local")
        return None
    except Exception as exc:  # pragma: no cover
        # If pointing to a local default instance (localhost:6379), treat as optional and avoid noisy error logs.
        url = settings.redis_url or ""
        if (("localhost" in url) or ("127.0.0.1" in url)) and (":6379" in url):
            logger.warning(
                "redis_unavailable_local_fallback",
                error=str(exc),
                hint="Lancez Redis ou exportez DISABLE_REDIS=1 pour désactiver la queue",
            )
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
        # Safe config logging (startup snapshot without secrets)
        try:
            from .config_inspect import log_safe  # local import to avoid overhead if module unused
            log_safe(logger, custom={
                "daily_post_target": settings.daily_post_target,
                "booster_activate_ratio": getattr(settings, "booster_activate_ratio", None),
                "adaptive_scroll_enabled": getattr(settings, "adaptive_scroll_enabled", None),
                "max_scroll_steps": settings.max_scroll_steps,
                "max_posts_per_keyword": settings.max_posts_per_keyword,
            })
        except Exception:  # pragma: no cover - defensive
            pass

        # Auto-disable logic in dev reload context (avoid Playwright subprocess issues on Windows)
        try:
            if settings.auto_disable_on_reload and not settings.disable_scraper:
                # Common env vars when using uvicorn --reload
                if os.environ.get("UVICORN_RELOAD") or os.environ.get("RUN_MAIN") == "true":
                    settings.disable_scraper = True  # type: ignore[attr-defined]
                    logger.info("scraper_auto_disabled_reload_detected")
        except Exception:
            pass

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
        # Initialize legal quota tracking attributes (used in worker classification quota logic)
        for attr, default in [
            ("legal_daily_date", None),
            ("legal_daily_count", 0),
            ("legal_daily_discard_intent", 0),
            ("legal_daily_discard_location", 0),
            # UI stats tracking for /api/legal_stats expects this date marker
            ("legal_stats_date", None),
        ]:
            if not hasattr(ctx, attr):
                try:
                    setattr(ctx, attr, default)  # type: ignore[attr-defined]
                except Exception:
                    pass
        # Pre-initialize risk counters (avoid attribute errors in early worker loop)
        try:
            setattr(ctx, "_risk_auth_suspect", 0)
            setattr(ctx, "_risk_empty_runs", 0)
        except Exception:
            pass
        log_method = logger.debug if settings.quiet_startup else logger.info
        log_method(
            "bootstrap_complete",
            mongo=bool(mongo_client),
            redis=bool(redis_client),
            elapsed=f"{elapsed:.3f}s",
            keywords=settings.keywords,
            scraping_enabled=settings.scraping_enabled,
            disabled_flag=settings.disable_scraper,
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
