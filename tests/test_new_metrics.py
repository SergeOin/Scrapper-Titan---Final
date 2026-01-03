import pytest
from prometheus_client import REGISTRY

from scraper import bootstrap

@pytest.mark.asyncio
async def test_metrics_registration():
    ctx = await bootstrap.bootstrap(force=True)
    # Materialize each metric via a sample update
    bootstrap.SCRAPE_STORAGE_ATTEMPTS.labels('sqlite', 'success').inc(0)
    bootstrap.SCRAPE_QUEUE_DEPTH.set(0)
    bootstrap.SCRAPE_JOB_FAILURES.inc(0)
    bootstrap.SCRAPE_STEP_DURATION.labels(step='sqlite_insert').observe(0.0)

    collected = list(REGISTRY.collect())
    # Build mapping name -> metric family
    fam = {m.name: m for m in collected}
    # Ensure we have at least one sample for each touched metric
    assert any(m.name.startswith('scrape_storage_attempts') for m in collected)
    assert 'scrape_queue_depth' in fam
    assert any(m.name.startswith('scrape_job_failures') for m in collected)
    assert any(m.name.startswith('scrape_step_duration_seconds') for m in collected)

@pytest.mark.asyncio
async def test_storage_attempts_counter_increments(monkeypatch):
    # Force use of sqlite storage path
    ctx = await bootstrap.bootstrap(force=True)

    from scraper.worker import store_posts, Post
    import datetime, json as _json

    post = Post(
        id='id1',
        keyword='kw',
        author='a',
        author_profile=None,
        text='hello world',
        language='fr',
        published_at=datetime.datetime.utcnow().isoformat(),
        collected_at=datetime.datetime.utcnow().isoformat(),
        score=0.5,
        raw={'k': 'v'},
    )

    # Snapshot current value
    storage_metric = None
    for m in REGISTRY.collect():
        if m.name == 'scrape_storage_attempts_total':
            storage_metric = m
            break
    before = 0
    if storage_metric:
        # sum existing samples
        before = sum(sample.value for sample in storage_metric.samples if sample.labels.get('backend') == 'sqlite')

    await store_posts(ctx, [post])

    # Re-collect
    for m in REGISTRY.collect():
        if m.name == 'scrape_storage_attempts_total':
            after = sum(sample.value for sample in m.samples if sample.labels.get('backend') == 'sqlite')
            assert after >= before + 1
            break
