"""Generate a Playwright storage_state.json after an interactive login.

Usage (headful):
  python scripts/generate_storage_state.py --url https://www.linkedin.com/login

Steps:
 1. A Chromium window opens.
 2. Log in manually (2FA if required).
 3. When you are on the feed (or logged in), press ENTER in the terminal.
 4. Script saves storage_state.json (path from settings or --out).

You can then run real scraping with PLAYWRIGHT_MOCK_MODE=0.
"""
from __future__ import annotations
import argparse
import asyncio
import os

from pathlib import Path

try:
    from playwright.async_api import async_playwright
except Exception as e:  # pragma: no cover
    raise SystemExit("Playwright not installed: pip install playwright && playwright install chromium") from e


DEFAULT_URL = "https://www.linkedin.com/login"


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default=DEFAULT_URL, help="Login/start page (default: LinkedIn login)")
    p.add_argument("--out", default="storage_state.json", help="Output storage state file")
    # New clearer headed flag (mutually exclusive with legacy --headless)
    group = p.add_mutually_exclusive_group()
    group.add_argument("--headless", action="store_true", help="Run headless (no UI) – not recommended for first login")
    group.add_argument("--headed", action="store_true", help="Force headed (browser visible) – default if neither flag provided")
    p.add_argument("--initial-wait", type=int, default=0, help="Optional seconds to wait BEFORE prompting (e.g. to let SSO overlays load)")
    p.add_argument("--capture-after", type=int, default=None, help="Auto-capture after N seconds (no need to press ENTER)")
    return p.parse_args()


async def main():
    args = parse_args()
    headed = True
    if args.headless:
        headed = False
    elif args.headed:
        headed = True
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=not headed)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(args.url)
        print("== Browser launched ==")
        if args.initial_wait > 0:
            print(f"Waiting {args.initial_wait}s before user interaction (initial overlays / SSO)...")
            try:
                await page.wait_for_timeout(args.initial_wait * 1000)
            except Exception:
                pass
        if args.capture_after is not None and args.capture_after > 0:
            print(f"Auto-capture enabled: you have {args.capture_after}s to complete login in the browser window...")
            try:
                await page.wait_for_timeout(args.capture_after * 1000)
            except Exception:
                pass
        else:
            try:
                print("Log in manually if needed, then press ENTER here to capture session.")
                input()
            except EOFError:
                print("No console input available; proceeding to capture immediately.")
        # Try navigating to feed to ensure session works
        try:
            await page.goto("https://www.linkedin.com/feed/", timeout=15000)
        except Exception:
            print("Warning: feed navigation failed; session may still be valid if already there.")
        await context.storage_state(path=args.out)
        await browser.close()
        print(f"Saved storage state to: {args.out}")
        if args.out != "storage_state.json":
            print("Update STORAGE_STATE env variable or .env if different name.")


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
