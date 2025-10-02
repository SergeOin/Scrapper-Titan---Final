import os, pytest
from scraper.bootstrap import get_context
from scraper.core.orchestrator import select_mode, run_orchestrator

pytestmark = pytest.mark.mock_long

@pytest.mark.asyncio
async def test_orchestrator_mock_mode(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_MOCK_MODE","1")
    ctx = await get_context()
    assert select_mode(ctx) == 'mock'
    posts = await run_orchestrator(['kw'], ctx, async_batch_callable=lambda kws, c: [])
    assert posts, 'mock mode should generate posts'

@pytest.mark.asyncio
async def test_orchestrator_sync_mode(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_MOCK_MODE","0")
    monkeypatch.setenv("PLAYWRIGHT_FORCE_SYNC","1")
    # Force rebuild context to reflect env changes
    import scraper.bootstrap as boot
    boot._context_singleton = None  # type: ignore
    ctx = await get_context()
    m = select_mode(ctx)
    assert m == 'sync'
    posts = await run_orchestrator(['kw2'], ctx, async_batch_callable=lambda kws, c: [])
    assert any(p.get('raw',{}).get('mode')=='sync' for p in posts)
