"""Quick diagnostic script to validate LinkedIn feed/content selectors.

Usage (PowerShell):
    python scripts/check_selectors.py --keyword "python" --headful

Requires:
    - Playwright installed (chromium)
    - Optional existing storage_state.json for authenticated context

Outputs:
    - Counts of elements for each selector
    - Sample extracted text snippets (truncated)
    - Optional save of page HTML (--dump-html)

This does NOT store anything in DB; it's purely a local inspection tool.
"""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
from textwrap import shorten

# Align selectors with scraper.worker for accurate diagnostics
POST_SELECTORS = [
    "div.feed-shared-update-v2",
    "div.occludable-update",
    "div[data-urn*='urn:li:activity:']"
]
AUTHOR_SELECTOR = (
    "span.update-components-actor__name, "
    "a.app-aware-link.update-components-actor__meta-link, "
    "span.feed-shared-actor__name, "
    "span.update-components-actor__name span"
)
TEXT_SELECTOR = (
    "div.update-components-text, "
    "div.feed-shared-update-v2__comments-container, "
    "div.update-components-text.relative"
)
DATE_SELECTOR = "time"
MEDIA_INDICATOR_SELECTOR = "img, video"


async def run(keyword: str, headless: bool, dump_html: bool, max_posts: int, storage_state: str | None,
              scroll_steps: int, scroll_wait_ms: int, export_json: str | None):
    try:
        from playwright.async_api import async_playwright  # type: ignore
    except Exception as exc:  # pragma: no cover
        print(f"Playwright import failed: {exc}. Did you install it? 'playwright install chromium'")
        return 1

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        context_args = {}
        if storage_state and os.path.exists(storage_state):
            context_args["storage_state"] = storage_state
        context = await browser.new_context(**context_args)
        page = await context.new_page()
        url = f"https://www.linkedin.com/search/results/content/?keywords={keyword}"
        print(f"Navigating to {url}")
        await page.goto(url, timeout=20000)
        await page.wait_for_timeout(2000)

        # Collect posts with optional scrolling
        posts = []
        seen_ids = set()
        for step in range(scroll_steps + 1):
            current = []
            for sel in POST_SELECTORS:
                found = await page.query_selector_all(sel)
                if step == 0:
                    print(f"Selector {sel!r}: {len(found)} matches")
                current.extend(found)
            print(f"Iteration {step}: {len(current)} raw containers (dedup next)")
            # Simple attempt to deduplicate by element handle id (repr)
            for el in current:
                rep = repr(el)
                if rep in seen_ids:
                    continue
                seen_ids.add(rep)
                posts.append(el)
            if step < scroll_steps:
                try:
                    await page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
                except Exception:  # pragma: no cover
                    pass
                await page.wait_for_timeout(scroll_wait_ms)
        print(f"Total unique containers after scrolling: {len(posts)}")

        results = []
        for el in posts[:max_posts]:
            try:
                author_el = await el.query_selector(AUTHOR_SELECTOR)
                text_el = await el.query_selector(TEXT_SELECTOR)
                date_el = await el.query_selector(DATE_SELECTOR)
                media_el = await el.query_selector(MEDIA_INDICATOR_SELECTOR)
                author = (await author_el.inner_text()) if author_el else "<no author>"
                text = (await text_el.inner_text()) if text_el else ""
                date_val = (await date_el.get_attribute("datetime")) if date_el else None
                has_media = bool(media_el)
                results.append({
                    "author": author.strip(),
                    "text": shorten(text.strip(), width=140, placeholder="…"),
                    "date": date_val,
                    "media": has_media,
                })
            except Exception as e:  # pragma: no cover
                print(f"Error extracting one post: {e}")

        for idx, r in enumerate(results, start=1):
            print(f"[{idx}] author={r['author']!r} media={r['media']} date={r['date']} text={r['text']}")

        if export_json:
            import json as _json
            out_path = Path(export_json)
            out_path.write_text(_json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"Exported {len(results)} samples to {out_path.resolve()}")

        if dump_html:
            out = Path("selector_dump.html")
            content = await page.content()
            out.write_text(content, encoding="utf-8")
            print(f"Full page HTML dumped to {out.resolve()}")

        await browser.close()
    return 0


def main():
    parser = argparse.ArgumentParser(description="LinkedIn selector diagnostic")
    parser.add_argument("--keyword", required=True, help="Search keyword")
    parser.add_argument("--headful", action="store_true", help="Run browser in non-headless mode")
    parser.add_argument("--dump-html", action="store_true", help="Dump page HTML to selector_dump.html")
    parser.add_argument("--max-posts", type=int, default=5, help="Max sample posts to print")
    parser.add_argument("--storage-state", default="storage_state.json", help="Path to storage_state.json if exists")
    parser.add_argument("--scroll-steps", type=int, default=3, help="Number of additional scroll iterations")
    parser.add_argument("--scroll-wait-ms", type=int, default=1200, help="Wait between scroll iterations (ms)")
    parser.add_argument("--export-json", help="Optional path to export extracted sample posts JSON")
    args = parser.parse_args()
    headless = not args.headful
    code = asyncio.run(run(
        keyword=args.keyword,
        headless=headless,
        dump_html=args.dump_html,
        max_posts=args.max_posts,
        storage_state=args.storage_state,
        scroll_steps=args.scroll_steps,
        scroll_wait_ms=args.scroll_wait_ms,
        export_json=args.export_json,
    ))
    raise SystemExit(code)


if __name__ == "__main__":  # pragma: no cover
    main()
