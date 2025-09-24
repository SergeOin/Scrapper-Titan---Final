import asyncio
import pytest
from scraper.rate_limit import TokenBucket

@pytest.mark.asyncio
async def test_token_bucket_basic_consume():
    bucket = TokenBucket.create(capacity=3, refill_per_sec=10)
    # consume available tokens fast
    w1 = await bucket.consume(1)
    w2 = await bucket.consume(1)
    w3 = await bucket.consume(1)
    assert w1 == 0 and w2 == 0 and w3 == 0
    # next consume should wait because tokens=0; refill rate 10/s so ~0.1s
    start = asyncio.get_event_loop().time()
    w4 = await bucket.consume(1)
    elapsed = asyncio.get_event_loop().time() - start
    assert w4 > 0
    assert elapsed >= 0.09

@pytest.mark.asyncio
async def test_token_bucket_parallel_consumers():
    bucket = TokenBucket.create(capacity=2, refill_per_sec=2)
    # Two immediate consumes ok, third waits ~0.5s (needs 0.5 token * 2/s)
    results = []
    async def worker():
        w = await bucket.consume(1)
        results.append(w)
    await asyncio.gather(worker(), worker())
    # bucket empty now
    w3 = await bucket.consume(1)
    assert w3 > 0

@pytest.mark.asyncio
async def test_integration_mock_mode_rate_limit(monkeypatch):
    # Force mock mode and small bucket to exercise path
    from scraper import bootstrap
    ctx = await bootstrap.bootstrap(force=True)
    ctx.settings.playwright_mock_mode = True
    # Replace token bucket with small capacity
    from scraper.rate_limit import TokenBucket
    ctx.token_bucket = TokenBucket.create(2, 5)  # 2 tokens, fast refill

    from scraper.worker import process_job
    # Run with more keywords than capacity to trigger waits
    keywords = ["k1", "k2", "k3"]
    count = await process_job(keywords, ctx)
    assert count >= 1  # posts generated in mock mode
