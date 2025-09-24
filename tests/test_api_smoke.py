from __future__ import annotations

import pytest
from httpx import AsyncClient

from fastapi import FastAPI

from server.main import app


@pytest.mark.asyncio
async def test_health_endpoint():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
