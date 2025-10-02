from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scraper import bootstrap
from scraper.runtime import RuntimePost
from scraper.runtime.mock import generate_posts


@pytest.mark.asyncio
async def test_generate_posts_default_limit_respected():
    ctx = await bootstrap.bootstrap(force=True)
    ctx.settings.max_mock_posts = 3
    ctx.settings.max_posts_per_keyword = 5

    posts = generate_posts("juriste", ctx)

    assert len(posts) == 3
    assert all(isinstance(post, RuntimePost) for post in posts)
    assert all(post.keyword == "juriste" for post in posts)


@pytest.mark.asyncio
async def test_generate_posts_custom_limit_and_timestamp():
    ctx = await bootstrap.bootstrap(force=True)
    ctx.settings.max_mock_posts = 10
    ctx.settings.max_posts_per_keyword = 10

    frozen = datetime(2024, 1, 1, tzinfo=timezone.utc)
    posts = generate_posts("avocat", ctx, limit=2, now=frozen)

    assert len(posts) == 2
    assert all(post.collected_at == frozen.isoformat() for post in posts)
    assert all(post.published_at == frozen.isoformat() for post in posts)


@pytest.mark.asyncio
async def test_generate_posts_honours_keyword_cap():
    ctx = await bootstrap.bootstrap(force=True)
    ctx.settings.max_mock_posts = 5
    ctx.settings.max_posts_per_keyword = 2

    posts = generate_posts("fiscaliste", ctx)

    assert len(posts) == 2