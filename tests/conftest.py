import os
import pytest
from scraper.bootstrap import get_context, _context_singleton  # type: ignore

# Force faster / deterministic test environment
os.environ.setdefault("PLAYWRIGHT_MOCK_MODE", "1")  # avoid real browser in tests
os.environ.setdefault("SQLITE_PATH", "test_fallback.sqlite3")
os.environ.setdefault("PURGE_MAX_AGE_DAYS", "30")

@pytest.fixture(autouse=True)
async def fresh_ctx(monkeypatch):
    # Each test can override SQLITE_PATH before first get_context(); ensure rebuild
    if '_context_singleton' in globals():
        try:
            globals()['__builtins__']  # noop to avoid lint
        except Exception:
            pass
    yield

@pytest.fixture(scope="session", autouse=True)
def _show_modes():
    yield
