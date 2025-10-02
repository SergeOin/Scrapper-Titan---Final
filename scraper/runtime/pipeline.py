from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from scraper.core.ids import canonical_permalink, content_hash
from scraper.runtime.dedup import deduplicate
from scraper.runtime.models import JobResult, RuntimePost
from scraper.utils import make_post_id


_POST_KEYS = (
    "id",
    "keyword",
    "author",
    "author_profile",
    "company",
    "text",
    "language",
    "published_at",
    "collected_at",
    "permalink",
    "score",
    "raw",
)


def finalize_job_result(
    posts: Iterable[Any],
    ctx,
    *,
    mode: str,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> JobResult:
    """Deduplicate and normalize posts before storage.

    Parameters
    ----------
    posts:
        Iterable of post payloads (dicts or objects with matching attributes).
    ctx:
        Application context providing settings and logger.
    mode:
        Effective execution mode (mock | sync | async | other).
    started_at / finished_at:
        Timestamps bounding the job execution. When omitted, current UTC time is used.
    """

    started = started_at or datetime.now(timezone.utc)
    finished = finished_at or datetime.now(timezone.utc)

    raw_dicts: list[dict[str, Any]] = []
    for item in posts:
        payload = _coerce_post_dict(item)
        if not payload:
            continue
        normalized = _normalize_post_dict(payload)
        raw_dicts.append(normalized)

    deduped_dicts = deduplicate(raw_dicts)
    fallback_ts = started.isoformat()
    materialized: list[RuntimePost] = []
    for data in deduped_dicts:
        materialized.append(_dict_to_runtime_post(data, ctx, fallback_ts))

    unknown_authors = sum(1 for p in materialized if p.author == "Unknown")
    return JobResult(
        posts=materialized,
        unknown_authors=unknown_authors,
        mode=mode,
        started_at=started,
        finished_at=finished,
    )


def _coerce_post_dict(item: Any) -> dict[str, Any] | None:
    if item is None:
        return None
    if isinstance(item, RuntimePost):
        return asdict(item)
    if isinstance(item, Mapping):
        return dict(item)
    payload: dict[str, Any] = {}
    for key in _POST_KEYS:
        if hasattr(item, key):
            payload[key] = getattr(item, key)
    return payload or None


def _normalize_post_dict(data: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(data)
    keyword = normalized.get("keyword")
    if keyword is None:
        normalized["keyword"] = ""
    author = normalized.get("author")
    if author is None or author == "":
        normalized["author"] = "Unknown"
    text = normalized.get("text") or ""
    normalized["text"] = text
    if normalized.get("permalink"):
        try:
            normalized["permalink"] = canonical_permalink(normalized["permalink"])
        except Exception:
            pass
    if not normalized.get("collected_at"):
        normalized["collected_at"] = datetime.now(timezone.utc).isoformat()
    if not normalized.get("id"):
        normalized["id"] = make_post_id(
            normalized.get("keyword"),
            normalized.get("author"),
            normalized.get("published_at"),
        )
    if not normalized.get("content_hash"):
        try:
            normalized["content_hash"] = content_hash(normalized.get("author"), text)
        except Exception:
            pass
    if "raw" not in normalized or normalized["raw"] is None:
        normalized["raw"] = {}
    return normalized


def _dict_to_runtime_post(data: Mapping[str, Any], ctx, fallback_ts: str) -> RuntimePost:
    return RuntimePost(
        id=str(data.get("id", "")),
        keyword=str(data.get("keyword", "")),
        author=str(data.get("author", "Unknown")),
        author_profile=data.get("author_profile"),
        text=str(data.get("text", "")),
        language=str(data.get("language") or ctx.settings.default_lang),
        published_at=data.get("published_at"),
        collected_at=str(data.get("collected_at") or fallback_ts),
        company=data.get("company"),
        permalink=data.get("permalink"),
        score=data.get("score"),
        raw=data.get("raw") or {},
    )