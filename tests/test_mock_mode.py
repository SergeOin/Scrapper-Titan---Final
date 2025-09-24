import pytest
from scraper.bootstrap import Settings, AppContext, configure_logging
from scraper import utils
from scraper import worker as worker_mod
from scraper.worker import process_keyword, Post
import structlog

@pytest.mark.asyncio
async def test_process_keyword_mock_mode(monkeypatch):
    # Rely on field population by name (populate_by_name=True in config)
    settings = Settings(playwright_mock_mode=True)  # type: ignore[arg-type]
    configure_logging(settings.log_level, settings)
    logger = structlog.get_logger().bind(test="mock_mode")
    ctx = AppContext(settings=settings, logger=logger, mongo_client=None, redis=None)

    # Simule absence playwright même si lib installée
    worker_mod.async_playwright = None  # type: ignore
    posts = await process_keyword("python", ctx)
    assert posts, "Expected synthetic posts"
    assert all(isinstance(p, Post) for p in posts)
    assert all(p.raw.get("mode") == "mock" for p in posts)
    # Score sanity
    assert 0 <= posts[0].score <= 1
