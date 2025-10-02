from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from scraper.core import mock as core_mock
from scraper.runtime.models import RuntimePost
from .. import utils


def _resolve_limit(ctx, limit: Optional[int]) -> int:
    """Determine the number of mock posts to generate for a keyword."""
    max_mock = int(getattr(ctx.settings, "max_mock_posts", 5) or 5)
    per_keyword_cap = int(getattr(ctx.settings, "max_posts_per_keyword", max_mock) or max_mock)
    if limit is None:
        return min(max_mock, per_keyword_cap)
    return max(0, min(limit, max_mock, per_keyword_cap))


def generate_posts(keyword: str, ctx, *, limit: Optional[int] = None, now: Optional[datetime] = None) -> list[RuntimePost]:
    """Generate deterministic mock posts for the given keyword.

    Parameters
    ----------
    keyword: str
        Keyword associated to the generated posts.
    ctx: AppContext
        The application context providing settings and metrics registry.
    limit: Optional[int]
        Optional explicit cap. Defaults to ``ctx.settings.max_mock_posts``
        while respecting ``ctx.settings.max_posts_per_keyword``.
    now: Optional[datetime]
        Frozen timestamp for testing. Defaults to ``datetime.now(timezone.utc)``.
    """

    resolved_limit = _resolve_limit(ctx, limit)
    if resolved_limit == 0:
        return []

    anchored = now or datetime.now(timezone.utc)
    # The core helper already emits metrics and produces canonical payloads.
    payloads = core_mock.generate_mock_posts(
        keyword,
        resolved_limit,
        ctx.settings,
        ctx.settings.recruitment_signal_threshold,
    )

    iso_override = anchored.isoformat()
    posts: list[RuntimePost] = []
    for payload in payloads:
        # Ensure deterministic timestamps when "now" is provided.
        published_at = payload.get("published_at", iso_override)
        collected_at = payload.get("collected_at", iso_override)
        if now is not None:
            published_at = iso_override
            collected_at = iso_override
        score = payload.get("score")
        if score is None:
            score = utils.compute_recruitment_signal(payload.get("text", ""))
        posts.append(
            RuntimePost(
                id=payload.get("id", ""),
                keyword=payload.get("keyword", keyword),
                author=payload.get("author", "demo_recruteur"),
                author_profile=payload.get("author_profile"),
                company=payload.get("company"),
                text=payload.get("text", ""),
                language=payload.get("language", ctx.settings.default_lang),
                published_at=published_at,
                collected_at=collected_at,
                permalink=payload.get("permalink"),
                score=score,
                raw=payload.get("raw"),
            )
        )
    return posts