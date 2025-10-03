import os
import asyncio
import importlib

# Lightweight test: ensure entrypoint loads and honors test mode without launching uvicorn or worker.

async def _call_main():
    os.environ['ENTRYPOINT_TEST_MODE'] = '1'
    mod = importlib.import_module('entrypoint')
    # Re-import to ensure settings path added
    if hasattr(mod, 'main'):
        await mod.main()  # type: ignore
    else:  # pragma: no cover
        raise AssertionError('entrypoint.main missing')


def test_entrypoint_test_mode():
    asyncio.run(_call_main())
