import pytest
from fastapi.testclient import TestClient
from scraper import bootstrap
from server.main import app

@pytest.mark.asyncio
async def test_trigger_requires_token_when_set(monkeypatch):
    ctx = await bootstrap.bootstrap(force=True)
    ctx.settings.trigger_token = "secret123"
    ctx.settings.playwright_mock_mode = True
    client = TestClient(app)
    # Missing token
    r = client.post('/trigger', data={})
    assert r.status_code == 401
    # Wrong token
    r = client.post('/trigger', headers={'X-Trigger-Token': 'bad'}, data={})
    assert r.status_code == 401
    # Correct token (will 204 even without queue)
    r = client.post('/trigger', headers={'X-Trigger-Token': 'secret123'}, data={})
    assert r.status_code in (204, 200)

@pytest.mark.asyncio
async def test_rate_limit_rejections(monkeypatch):
    ctx = await bootstrap.bootstrap(force=True)
    # Lower limits for test
    ctx.settings.api_rate_limit_per_min = 2
    ctx.settings.api_rate_limit_burst = 2
    ctx.settings.playwright_mock_mode = True
    client = TestClient(app)
    accepted = 0
    rejected = 0
    for i in range(5):
        r = client.get('/health')  # excluded from rate limit in middleware
    for i in range(30):  # large number to exceed low limits
        r = client.get('/')  # dashboard calls (will attempt fetch posts)
        if r.status_code == 429:
            rejected += 1
        else:
            accepted += 1
    assert rejected > 0
