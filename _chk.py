import asyncio
from scraper.bootstrap import bootstrap
async def main():
    ctx = await bootstrap(force=True)
    print('risk_init', hasattr(ctx,'_risk_auth_suspect'), hasattr(ctx,'_risk_empty_runs'))
asyncio.run(main())
