import pytest
from scraper.bootstrap import Settings, AppContext, configure_logging
from scraper.worker import process_keyword
import structlog

@pytest.mark.asyncio
async def test_mock_respects_max_limit():
    settings = Settings(playwright_mock_mode=True, max_mock_posts=2, max_posts_per_keyword=10)  # type: ignore[arg-type]
    configure_logging(settings.log_level, settings)
    logger = structlog.get_logger().bind(test="mock_limit")
    ctx = AppContext(settings=settings, logger=logger, mongo_client=None, redis=None)

    posts = await process_keyword("data", ctx)
    assert len(posts) == 2
