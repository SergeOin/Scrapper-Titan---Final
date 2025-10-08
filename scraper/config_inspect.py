"""Utilities to inspect and safely log runtime configuration.

We avoid leaking potentially sensitive values by masking any key that matches
secret-ish patterns (case-insensitive): token, key, secret, pass, pwd, hash.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable
import os
import re

SENSITIVE_PATTERN = re.compile(r"(token|secret|pass|pwd|key|hash)", re.IGNORECASE)


def is_sensitive(key: str) -> bool:
    return bool(SENSITIVE_PATTERN.search(key))


def collect_env(prefixes: Iterable[str] | None = None) -> Dict[str, str]:
    """Return environment variables filtered by optional prefixes.

    If prefixes is None -> return all. Otherwise only keep keys that start with
    one of the prefixes (case-insensitive).
    """
    data = {}
    for k, v in os.environ.items():
        if prefixes:
            kl = k.lower()
            if not any(kl.startswith(p.lower()) for p in prefixes):
                continue
        data[k] = v
    return data


def mask_value(key: str, value: Any) -> Any:
    if value is None:
        return value
    if is_sensitive(key):
        if isinstance(value, str) and len(value) > 6:
            return value[:3] + "***" + value[-2:]
        return "***"  # generic mask
    return value


def safe_snapshot(custom: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Build a safe snapshot of selected runtime config.

    custom: optional dictionary of already loaded settings (e.g. pydantic model .model_dump()).
    Env precedence: custom dict keys override environment variable view.
    """
    snapshot: Dict[str, Any] = {}
    # Base: environment (limit to relevant prefixes for noise reduction)
    env_subset = collect_env(prefixes=[
        "DAILY_", "BOOSTER_", "ADAPTIVE_", "GLOBAL_", "RATE_LIMIT_", "PER_KEYWORD_",
        "MAX_", "RECRUITMENT_", "SCRAPING_", "PLAYWRIGHT_", "APP_"
    ])
    for k, v in env_subset.items():
        snapshot[k] = v
    if custom:
        for k, v in custom.items():  # override / extend
            snapshot[k] = v
    # Mask sensitive
    masked = {k: mask_value(k, v) for k, v in snapshot.items()}
    return dict(sorted(masked.items()))


def format_snapshot(snapshot: Dict[str, Any]) -> str:
    width = max((len(k) for k in snapshot), default=0)
    lines = [f"{k.ljust(width)} = {snapshot[k]}" for k in sorted(snapshot)]
    return "\n".join(lines)


def log_safe(logger, custom: Dict[str, Any] | None = None) -> None:
    try:
        snap = safe_snapshot(custom=custom)
        logger.info("runtime_config", message="Effective runtime configuration (safe subset)", **snap)
    except Exception as exc:  # defensive to never break startup
        try:
            logger.warning("config_inspect_failure", error=str(exc))
        except Exception:
            pass


__all__ = [
    "safe_snapshot",
    "format_snapshot",
    "log_safe",
]
