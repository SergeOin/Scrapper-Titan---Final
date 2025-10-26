from __future__ import annotations
import os, asyncio
from pathlib import Path
import sys

# Configure env to mimic desktop DB and force mock mode
appdata = os.environ.get('LOCALAPPDATA', '')
if appdata:
    db = Path(appdata) / 'TitanScraper' / 'fallback.sqlite3'
    os.environ.setdefault('SQLITE_PATH', str(db))
os.environ.setdefault('DISABLE_MONGO', '1')
os.environ.setdefault('DISABLE_REDIS', '1')
os.environ.setdefault('PLAYWRIGHT_MOCK_MODE', '1')
os.environ.setdefault('MAX_MOCK_POSTS', '2')

async def main():
    PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)
    from scraper.bootstrap import get_context
    from scraper.worker import process_job
    ctx = await get_context()
    print({'sqlite_path': ctx.settings.sqlite_path, 'mock': ctx.settings.playwright_mock_mode})
    n = await process_job(ctx.settings.keywords[:2], ctx)
    print({'inserted': n})

if __name__ == '__main__':
    asyncio.run(main())
