"""Lightweight extraction facade (delegating to legacy extract_posts for now)."""
from __future__ import annotations
from typing import Any

async def extract_posts_for_keyword(page: Any, keyword: str, max_posts: int, ctx):
    # Thin wrapper so future refactor can swap implementation
    from ..worker import extract_posts as _legacy_extract  # deferred import to avoid cycle until full split
    return await _legacy_extract(page, keyword, max_posts, ctx)
