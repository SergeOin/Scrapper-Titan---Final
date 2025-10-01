"""Minimal standalone diagnostic for Playwright launch.

Usage (PowerShell):
  C:/Users/plogr/Desktop/Scrapper-Titan---Final/.venv/Scripts/python.exe scripts/diag_playwright.py

Environment overrides:
  PLAYWRIGHT_DISABLE_HEADLESS=1 to show window
  PLAYWRIGHT_EXTRA_ARGS="--disable-gpu --no-sandbox" etc.

It prints JSON lines with status. Exit code 0 = success, 1 = failure.
"""
from __future__ import annotations
import asyncio, os, json, sys, tempfile
from pathlib import Path

async def main():
    try:
        from playwright.async_api import async_playwright  # type: ignore
    except Exception as e:  # pragma: no cover
        print(json.dumps({"event": "import_failed", "error": str(e)}))
        return 1
    disable_headless = os.environ.get("PLAYWRIGHT_DISABLE_HEADLESS", "0").lower() in ("1","true","yes","on")
    extra_args_env = os.environ.get("PLAYWRIGHT_EXTRA_ARGS", "")
    extra_args = [a.strip() for a in extra_args_env.split(" ") if a.strip()] if extra_args_env else []
    if not extra_args:
        extra_args = ["--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage"]
    storage_state = Path("storage_state.json")
    async with async_playwright() as pw:
        try:
            print(json.dumps({"event": "launch_attempt", "headless": not disable_headless, "args": extra_args}))
            browser = await pw.chromium.launch(headless=not disable_headless, args=extra_args)
        except Exception as e:
            print(json.dumps({"event": "launch_failed", "error": str(e)}))
            return 1
        try:
            ctx_arg = str(storage_state) if storage_state.exists() else None
            print(json.dumps({"event": "new_context", "storage": ctx_arg, "exists": storage_state.exists()}))
            context = await browser.new_context(storage_state=ctx_arg)
        except Exception as e:
            print(json.dumps({"event": "new_context_failed", "error": str(e)}))
            await browser.close()
            # Try persistent fallback
            tmp = Path(tempfile.mkdtemp(prefix="pw_diag_"))
            try:
                print(json.dumps({"event": "persistent_fallback_attempt", "dir": str(tmp)}))
                persistent = await pw.chromium.launch_persistent_context(str(tmp), headless=not disable_headless, args=extra_args)
                page = persistent.pages[0] if persistent.pages else await persistent.new_page()
                await page.goto("https://www.linkedin.com/feed/", timeout=20000)
                print(json.dumps({"event": "persistent_success", "url": page.url}))
                await persistent.close()
                return 0
            except Exception as e2:
                print(json.dumps({"event": "persistent_failed", "error": str(e2)}))
                return 1
        try:
            page = await context.new_page()
            await page.goto("https://www.linkedin.com/feed/", timeout=20000)
            print(json.dumps({"event": "page_navigated", "url": page.url}))
        except Exception as e:
            print(json.dumps({"event": "navigation_failed", "error": str(e)}))
            await browser.close()
            return 1
        await browser.close()
        print(json.dumps({"event": "success"}))
        return 0

if __name__ == "__main__":
    code = asyncio.run(main())
    sys.exit(code)
