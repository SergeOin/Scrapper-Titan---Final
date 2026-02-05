from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
import contextlib
from pathlib import Path
from typing import Any, Optional
import sys
import asyncio as _asyncio

# Ensure Windows uses Selector event loop policy at import time (affects new loops in any thread)
if sys.platform.startswith("win"):
    try:
        _asyncio.set_event_loop_policy(_asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

import structlog

try:
    from playwright.async_api import async_playwright
except Exception:  # pragma: no cover
    async_playwright = None  # type: ignore

try:
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover
    sync_playwright = None  # type: ignore

try:
    import browser_cookie3 as bc3  # type: ignore
except Exception:  # pragma: no cover
    bc3 = None  # type: ignore

from .bootstrap import AppContext


@dataclass
class SessionStatus:
    valid: bool
    details: dict[str, Any]


def _save_session_store(ctx: AppContext, cookies: dict[str, Any]) -> None:
    try:
        Path(ctx.settings.session_store_path).write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _read_session_store(ctx: AppContext) -> dict[str, Any]:
    try:
        if Path(ctx.settings.session_store_path).exists():
            return json.loads(Path(ctx.settings.session_store_path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {}


def _fix_linkedin_cookie_domains(storage_path: str) -> None:
    """Fix LinkedIn cookie domains from .www.linkedin.com to .linkedin.com.
    
    This is critical because cookies with .www.linkedin.com domain won't be
    sent to linkedin.com (without www), causing authentication failures.
    This function should be called after every storage_state save.
    """
    try:
        path = Path(storage_path)
        if not path.exists():
            return
        
        data = json.loads(path.read_text(encoding="utf-8"))
        cookies = data.get("cookies", [])
        changes = 0
        
        for cookie in cookies:
            domain = cookie.get("domain", "")
            # Fix .www.linkedin.com -> .linkedin.com
            if domain.startswith(".www."):
                cookie["domain"] = domain.replace(".www.", ".", 1)
                changes += 1
        
        if changes > 0:
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            structlog.get_logger().debug("fixed_cookie_domains", changes=changes, path=storage_path)
    except Exception:
        pass  # Silently fail - not critical


async def session_status(ctx: AppContext) -> SessionStatus:
    # basic validation: storage_state.json presence and contains cookies
    details: dict[str, Any] = {"storage_state": ctx.settings.storage_state}
    try:
        storage_path = Path(ctx.settings.storage_state)
        if storage_path.exists():
            data = json.loads(storage_path.read_text(encoding="utf-8"))
            cookies = data.get("cookies") or []
            li_cookie = None
            for c in cookies:
                if c.get("name") == "li_at":
                    li_cookie = c
                    break
            jsess = any(c.get("name", "").upper().startswith("JSESSIONID") for c in cookies)
            import time as _time
            li_expires = None
            li_expired = False
            now = _time.time()
            if li_cookie is not None:
                li_expires = li_cookie.get("expires")
                try:
                    # LinkedIn cookies use Unix timestamps in seconds
                    # -1 or 0 means session cookie (no explicit expiration)
                    if isinstance(li_expires, (int, float)) and li_expires > 0:
                        # Sanity check: if expires is way in the past (before 2020), skip expiration check
                        # This handles edge cases with weird timestamp formats
                        if li_expires > 1577836800:  # 2020-01-01
                            li_expired = now > float(li_expires)
                except Exception:  # pragma: no cover
                    li_expired = False
            valid = bool(li_cookie) and not li_expired
            details.update({
                "cookies_count": len(cookies),
                "has_li_at": bool(li_cookie),
                "li_at_expires": li_expires,
                "li_at_expired": li_expired,
                "has_jsessionid": jsess,
                "storage_state_size": storage_path.stat().st_size,
            })
            return SessionStatus(valid=valid, details=details)
        else:
            details["storage_state_exists"] = False
    except Exception as e:
        details["error"] = str(e)
    return SessionStatus(valid=False, details=details)


def _maybe_force_close_browsers(ctx: AppContext) -> None:
    if not ctx.settings.browser_force_close:
        return
    # Best-effort: try closing Chrome/Edge/Firefox on Windows
    for exe in ("chrome", "msedge", "firefox", "chrome.exe", "msedge.exe", "firefox.exe"):
        with contextlib.suppress(Exception):  # type: ignore
            subprocess.run(["taskkill", "/IM", exe, "/F"], check=False, capture_output=True)


def force_close_browsers() -> None:
    """Always attempt to close common browsers regardless of settings.

    Used by the forced cookie import endpoint to release file locks.
    """
    for exe in ("chrome", "msedge", "firefox", "chrome.exe", "msedge.exe", "firefox.exe"):
        with contextlib.suppress(Exception):  # type: ignore
            subprocess.run(["taskkill", "/IM", exe, "/F"], check=False, capture_output=True)


def _diagnose_browser_sync(result: dict[str, Any], err: str) -> None:
    result.setdefault("attempts", []).append(err)


def _export_storage_state_from_cookies(cookies: list[dict[str, Any]], out_path: str) -> None:
    # Create a minimal storage state file compatible with Playwright: {cookies: [...]}
    Path(out_path).write_text(json.dumps({"cookies": cookies}, ensure_ascii=False, indent=2), encoding="utf-8")


def browser_sync(ctx: AppContext) -> tuple[bool, dict[str, Any]]:
    """Try to import cookies from local browsers and write storage_state.json.

    Returns (success, diagnostics)
    """
    diag: dict[str, Any] = {"used": None, "attempts": []}
    if bc3 is None:
        _diagnose_browser_sync(diag, "browser-cookie3 not installed")
        return False, diag
    _maybe_force_close_browsers(ctx)
    # Try Edge then Chrome then Firefox
    for name, getter in ("edge", getattr(bc3, "edge", None)), ("chrome", getattr(bc3, "chrome", None)), ("firefox", getattr(bc3, "firefox", None)):
        if not getter:
            continue
        try:
            jar = getter(domain_name=".linkedin.com")
            cookies = []
            for c in jar:
                cookies.append({
                    "name": c.name,
                    "value": c.value,
                    "domain": c.domain,
                    "path": c.path,
                    "expires": c.expires or 0,
                    "httpOnly": c.has_nonstandard_attr("HttpOnly"),
                    "secure": c.secure,
                    "sameSite": "Lax",
                })
            li_at = any(c["name"] == "li_at" for c in cookies)
            if cookies and li_at:
                _export_storage_state_from_cookies(cookies, ctx.settings.storage_state)
                _save_session_store(ctx, {"source": name, "cookies_count": len(cookies)})
                diag.update({"used": name, "cookies_count": len(cookies)})
                return True, diag
            _diagnose_browser_sync(diag, f"{name}: cookies found={len(cookies)} li_at={li_at}")
        except Exception as e:  # pragma: no cover
            _diagnose_browser_sync(diag, f"{name}: {e}")
    return False, diag


async def login_via_playwright(ctx: AppContext, email: str, password: str, mfa_code: Optional[str] = None) -> tuple[bool, dict[str, Any]]:
    if async_playwright is None:
        return False, {"error": "playwright not installed"}
    diag: dict[str, Any] = {}
    # For login specifically, default to a visible window to allow MFA/CAPTCHA interactions.
    # Users can force headless via PLAYWRIGHT_HEADLESS=1
    def _login_headless() -> bool:
        try:
            v = os.environ.get("PLAYWRIGHT_HEADLESS")
            if v is None or v == "":
                return False  # default: visible window for login
            return str(v).lower() in ("1", "true", "yes", "on")
        except Exception:
            return False
    _headless = _login_headless()
    
    # Extract settings values BEFORE entering worker thread to avoid thread-safety issues
    _login_timeout_ms = ctx.settings.playwright_login_timeout_ms
    _captcha_max_wait_ms = ctx.settings.captcha_max_wait_ms
    _storage_state_path = ctx.settings.storage_state
    _session_store_path = ctx.settings.session_store_path
    
    # On Windows, prefer sync Playwright executed in a worker thread to avoid asyncio subprocess limitations
    if sys.platform.startswith("win") and sync_playwright is not None:
        def _sync_login_impl() -> tuple[bool, dict[str, Any]]:
            try:
                with sync_playwright() as spw:
                    # Use persistent browser profile to preserve session across logins
                    # This helps LinkedIn recognize the browser and reduces security emails
                    user_data_dir = Path(os.environ.get("LOCALAPPDATA", ".")) / "TitanScraper" / "chrome-profile"
                    user_data_dir.mkdir(parents=True, exist_ok=True)
                    
                    print(f"[LOGIN] Launching persistent context in: {user_data_dir}")
                    
                    context = spw.chromium.launch_persistent_context(
                        user_data_dir=str(user_data_dir),
                        channel="chrome",  # Use system Chrome instead of Playwright's Chromium
                        headless=_headless,
                        locale="fr-FR",
                        timezone_id="Europe/Paris",
                        viewport={"width": 1920, "height": 1080},
                        # Anti-detection flags
                        args=[
                            "--disable-blink-features=AutomationControlled",
                            "--disable-dev-shm-usage",
                            "--no-first-run",
                            "--no-default-browser-check",
                        ],
                    )
                    
                    print(f"[LOGIN] Context launched, existing pages: {len(context.pages)}")
                    
                    # Always get or create a page
                    if context.pages:
                        page = context.pages[0]
                        print(f"[LOGIN] Using existing page, current URL: {page.url}")
                    else:
                        page = context.new_page()
                        print("[LOGIN] Created new page")
                    
                    try:
                        print(f"[LOGIN] Navigating to LinkedIn login...")
                        page.goto("https://www.linkedin.com/login", timeout=_login_timeout_ms)
                        print(f"[LOGIN] Navigation complete, current URL: {page.url}")
                        page.fill("input#username", email)
                        page.fill("input#password", password)
                        page.click("button[type=submit]")
                        if mfa_code:
                            try:
                                page.wait_for_selector("input[name=pin]", timeout=20000)
                                page.fill("input[name=pin]", mfa_code)
                                page.click("button[type=submit]")
                            except Exception:
                                pass
                        total_wait = 0
                        step = 2000
                        has_li_at = False
                        blocking_reason = None
                        while total_wait < _captcha_max_wait_ms:
                            try:
                                cookies = page.context.cookies()
                                has_li_at = any(c.get("name") == "li_at" for c in cookies)
                                if has_li_at:
                                    break
                                if page.url.startswith("https://www.linkedin.com/feed"):
                                    break
                                # Detect human validation requirements
                                current_url = page.url.lower()
                                page_content = ""
                                try:
                                    page_content = page.content().lower()
                                except Exception:
                                    pass
                                # Check for various challenge types
                                if "checkpoint" in current_url:
                                    blocking_reason = "security_checkpoint"
                                elif "challenge" in current_url:
                                    blocking_reason = "challenge"
                                elif "captcha" in current_url or "captcha" in page_content:
                                    blocking_reason = "captcha"
                                elif "verification" in current_url or "verify" in current_url:
                                    blocking_reason = "verification"
                                elif "two-step" in current_url or "2fa" in current_url:
                                    blocking_reason = "two_factor_auth"
                            except Exception:
                                pass
                            page.wait_for_timeout(step)
                            total_wait += step
                        if has_li_at or page.url.startswith("https://www.linkedin.com/feed"):
                            # If we reached the feed but don't have li_at yet, wait a bit and re-check cookies
                            if not has_li_at:
                                page.wait_for_timeout(2000)  # Give LinkedIn time to set cookies
                                try:
                                    cookies = page.context.cookies()
                                    has_li_at = any(c.get("name") == "li_at" for c in cookies)
                                except Exception:
                                    pass
                            context.storage_state(path=_storage_state_path)
                            _fix_linkedin_cookie_domains(_storage_state_path)  # Fix .www.linkedin.com -> .linkedin.com
                            # Save session store using extracted path
                            try:
                                Path(_session_store_path).write_text(json.dumps({"source": "playwright_sync", "has_li_at": has_li_at}, ensure_ascii=False, indent=2), encoding="utf-8")
                            except Exception:
                                pass
                            context.close()
                            return True, {"has_li_at": has_li_at}
                        context.close()
                        # Provide detailed error about what's blocking login
                        if blocking_reason:
                            return False, {
                                "error": f"human_validation_required: {blocking_reason}",
                                "blocking_type": blocking_reason,
                                "needs_human_validation": True,
                                "hint": "Veuillez vous connecter manuellement et résoudre la vérification de sécurité.",
                            }
                        return False, {"error": "timeout or captcha/mfa not completed"}
                    except Exception as _e:
                        try:
                            context.close()
                        except Exception:
                            pass
                        msg = str(_e) or _e.__class__.__name__
                        return False, {"error": msg}
            except Exception as _outer:
                msg = str(_outer) or _outer.__class__.__name__
                return False, {"error": msg}
        return await _asyncio.to_thread(_sync_login_impl)
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=_headless)  # login visible by default unless overridden
            page = await browser.new_page()
            try:
                await page.goto("https://www.linkedin.com/login", timeout=ctx.settings.playwright_login_timeout_ms)
                await page.fill("input#username", email)
                await page.fill("input#password", password)
                await page.click("button[type=submit]")
                # MFA handling (best-effort if code provided)
                if mfa_code:
                    try:
                        await page.wait_for_selector("input[name=pin]", timeout=20_000)
                        await page.fill("input[name=pin]", mfa_code)
                        await page.click("button[type=submit]")
                    except Exception:
                        pass
                # Wait for feed or presence of li_at cookie, with extended wait for captcha manual solving
                total_wait = 0
                step = 2000
                has_li_at = False
                blocking_reason = None
                while total_wait < ctx.settings.captcha_max_wait_ms:
                    try:
                        # check cookies
                        cookies = await page.context.cookies()
                        has_li_at = any(c.get("name") == "li_at" for c in cookies)
                        if has_li_at:
                            break
                        if page.url.startswith("https://www.linkedin.com/feed"):
                            break
                        # Detect human validation requirements
                        current_url = page.url.lower()
                        page_content = ""
                        try:
                            page_content = (await page.content()).lower()
                        except Exception:
                            pass
                        # Check for various challenge types
                        if "checkpoint" in current_url:
                            blocking_reason = "security_checkpoint"
                        elif "challenge" in current_url:
                            blocking_reason = "challenge"
                        elif "captcha" in current_url or "captcha" in page_content:
                            blocking_reason = "captcha"
                        elif "verification" in current_url or "verify" in current_url:
                            blocking_reason = "verification"
                        elif "two-step" in current_url or "2fa" in current_url:
                            blocking_reason = "two_factor_auth"
                    except Exception:
                        pass
                    await page.wait_for_timeout(step)
                    total_wait += step
                # success if li_at present
                if has_li_at:
                    await page.context.storage_state(path=ctx.settings.storage_state)
                    _fix_linkedin_cookie_domains(ctx.settings.storage_state)  # Fix .www.linkedin.com -> .linkedin.com
                    _save_session_store(ctx, {"source": "playwright", "has_li_at": True})
                    await browser.close()
                    return True, {"has_li_at": True}
                # Fallback: if on feed even if li_at not inspected
                if page.url.startswith("https://www.linkedin.com/feed"):
                    # Wait a bit and re-check cookies since LinkedIn may set them after page load
                    await page.wait_for_timeout(2000)
                    try:
                        cookies = await page.context.cookies()
                        has_li_at = any(c.get("name") == "li_at" for c in cookies)
                    except Exception:
                        pass
                    await page.context.storage_state(path=ctx.settings.storage_state)
                    _fix_linkedin_cookie_domains(ctx.settings.storage_state)  # Fix .www.linkedin.com -> .linkedin.com
                    _save_session_store(ctx, {"source": "playwright", "on_feed": True, "has_li_at": has_li_at})
                    await browser.close()
                    return True, {"on_feed": True, "has_li_at": has_li_at}
                await browser.close()
                # Provide detailed error about what's blocking login
                if blocking_reason:
                    return False, {
                        "error": f"human_validation_required: {blocking_reason}",
                        "blocking_type": blocking_reason,
                        "needs_human_validation": True,
                        "hint": "Veuillez vous connecter manuellement et résoudre la vérification de sécurité.",
                    }
                return False, {"error": "timeout or captcha/mfa not completed"}
            except Exception as e:
                with contextlib.suppress(Exception):  # type: ignore
                    await browser.close()
                msg = str(e) or e.__class__.__name__
                return False, {"error": msg}
    except NotImplementedError as e:
        # Typical on Windows if ProactorEventLoop is active. Fallback to sync Playwright in a worker thread.
        if sync_playwright is None:
            return False, {
                "error": "playwright_subprocess_not_supported",
                "message": "Sous-processus asyncio non supporté (Windows).",
                "hint": "Essayez via scripts/run_server.py (policy WindowsSelector) et installez Chromium: python -m playwright install chromium",
                "exception": str(e),
            }
        def _sync_login_impl() -> tuple[bool, dict[str, Any]]:
            try:
                with sync_playwright() as spw:
                    browser = spw.chromium.launch(headless=_headless)
                    page = browser.new_page()
                    try:
                        page.goto("https://www.linkedin.com/login", timeout=ctx.settings.playwright_login_timeout_ms)
                        page.fill("input#username", email)
                        page.fill("input#password", password)
                        page.click("button[type=submit]")
                        if mfa_code:
                            try:
                                page.wait_for_selector("input[name=pin]", timeout=20000)
                                page.fill("input[name=pin]", mfa_code)
                                page.click("button[type=submit]")
                            except Exception:
                                pass
                        total_wait = 0
                        step = 2000
                        has_li_at = False
                        blocking_reason = None
                        while total_wait < ctx.settings.captcha_max_wait_ms:
                            try:
                                cookies = page.context.cookies()
                                has_li_at = any(c.get("name") == "li_at" for c in cookies)
                                if has_li_at:
                                    break
                                if page.url.startswith("https://www.linkedin.com/feed"):
                                    break
                                # Detect human validation requirements
                                current_url = page.url.lower()
                                page_content = ""
                                try:
                                    page_content = page.content().lower()
                                except Exception:
                                    pass
                                if "checkpoint" in current_url:
                                    blocking_reason = "security_checkpoint"
                                elif "challenge" in current_url:
                                    blocking_reason = "challenge"
                                elif "captcha" in current_url or "captcha" in page_content:
                                    blocking_reason = "captcha"
                                elif "verification" in current_url or "verify" in current_url:
                                    blocking_reason = "verification"
                                elif "two-step" in current_url or "2fa" in current_url:
                                    blocking_reason = "two_factor_auth"
                            except Exception:
                                pass
                            page.wait_for_timeout(step)
                            total_wait += step
                        if has_li_at or page.url.startswith("https://www.linkedin.com/feed"):
                            page.context.storage_state(path=ctx.settings.storage_state)
                            _fix_linkedin_cookie_domains(ctx.settings.storage_state)  # Fix .www.linkedin.com -> .linkedin.com
                            _save_session_store(ctx, {"source": "playwright_sync", "has_li_at": has_li_at})
                            browser.close()
                            return True, {"has_li_at": has_li_at}
                        browser.close()
                        if blocking_reason:
                            return False, {
                                "error": f"human_validation_required: {blocking_reason}",
                                "blocking_type": blocking_reason,
                                "needs_human_validation": True,
                                "hint": "Veuillez vous connecter manuellement et résoudre la vérification de sécurité.",
                            }
                        return False, {"error": "timeout or captcha/mfa not completed"}
                    except Exception as _e:
                        try:
                            browser.close()
                        except Exception:
                            pass
                        return False, {"error": str(_e)}
            except Exception as _outer:
                msg = str(_outer) or _outer.__class__.__name__
                return False, {"error": msg}
        return await _asyncio.to_thread(_sync_login_impl)
