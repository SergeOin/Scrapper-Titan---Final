import pytest
from prometheus_client import REGISTRY

from scraper import bootstrap


@pytest.mark.asyncio
async def test_extraction_metrics_registration():
    # Force fresh context to ensure metric objects imported
    await bootstrap.bootstrap(force=True)
    # Touch metrics to guarantee at least one sample family exported
    bootstrap.SCRAPE_SCROLL_ITERATIONS.inc(0)
    bootstrap.SCRAPE_EXTRACTION_INCOMPLETE.inc(0)

    collected = list(REGISTRY.collect())
    family_names = {m.name for m in collected}
    sample_names = {s.name for m in collected for s in m.samples}
    # Accept either family or sample naming (prometheus_client versions may differ)
    assert (
        'scrape_scroll_iterations_total' in family_names
        or 'scrape_scroll_iterations_total' in sample_names
        or 'scrape_scroll_iterations' in family_names
    )
    assert (
        'scrape_extraction_incomplete_total' in family_names
        or 'scrape_extraction_incomplete_total' in sample_names
        or 'scrape_extraction_incomplete' in family_names
    )
