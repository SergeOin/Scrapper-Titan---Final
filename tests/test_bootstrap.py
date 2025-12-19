from __future__ import annotations

import pytest
import asyncio

from scraper.bootstrap import bootstrap


@pytest.mark.asyncio
async def test_bootstrap_basic():
    ctx = await bootstrap(force=True)
    assert ctx.settings.app_name
    # Redis may be None in test environment; that's acceptable.
    assert ctx.logger is not None
