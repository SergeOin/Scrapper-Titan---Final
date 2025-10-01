"""Navigation helpers (placeholder stub to be expanded)."""
from __future__ import annotations
from typing import Any

async def navigate_search(page: Any, keyword: str, timeout_ms: int):
    url = f"https://www.linkedin.com/search/results/content/?keywords={keyword}"
    await page.goto(url, timeout=timeout_ms)
    await page.wait_for_timeout(1200)
    return url
