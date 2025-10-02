from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scraper import bootstrap
from scraper.runtime.models import RuntimePost
from scraper.runtime.pipeline import finalize_job_result


@pytest.mark.asyncio
async def test_finalize_job_result_deduplicates_and_counts_unknown():
    ctx = await bootstrap.bootstrap(force=True)
    now_iso = datetime.now(timezone.utc).isoformat()
    posts = [
        RuntimePost(
            id="p1",
            keyword="kw",
            author="Alice",
            author_profile=None,
            text="Hello",
            language="fr",
            published_at=now_iso,
            collected_at=now_iso,
            company=None,
            permalink="https://www.linkedin.com/feed/update/123",
            score=0.42,
            raw={"mode": "mock"},
        ),
        RuntimePost(
            id="p2",
            keyword="kw",
            author="Alice",
            author_profile=None,
            text="Hello",
            language="fr",
            published_at=now_iso,
            collected_at=now_iso,
            company=None,
            permalink="https://www.linkedin.com/feed/update/123",
            score=0.42,
            raw={"mode": "mock"},
        ),
        RuntimePost(
            id="p3",
            keyword="kw",
            author="Unknown",
            author_profile=None,
            text="Another",
            language="fr",
            published_at=None,
            collected_at=now_iso,
            company=None,
            permalink=None,
            score=None,
            raw={},
        ),
    ]

    result = finalize_job_result(posts, ctx, mode="mock", started_at=datetime.now(timezone.utc))

    assert len(result.posts) == 2
    assert result.unknown_authors == 1
    assert result.mode == "mock"
    assert result.duration_seconds >= 0


@pytest.mark.asyncio
async def test_finalize_job_result_fills_defaults_for_dict_payloads():
    ctx = await bootstrap.bootstrap(force=True)
    now = datetime.now(timezone.utc)
    payload = {
        "keyword": "fiscal",
        "author": "",
        "text": "Great opportunity",
        "language": None,
        "raw": None,
    }

    result = finalize_job_result([payload], ctx, mode="async", started_at=now, finished_at=now)
    assert len(result.posts) == 1
    post = result.posts[0]
    assert post.author == "Unknown"
    assert post.language == ctx.settings.default_lang
    assert post.id
    assert post.raw == {}
