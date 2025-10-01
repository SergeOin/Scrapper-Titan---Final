"""Playwright DOM extraction logic.

This module contains all LinkedIn page parsing logic previously embedded in
``worker.extract_posts``. Isolated here to decouple extraction from orchestration
and storage concerns. The function ``extract_posts`` returns a list of ``Post``
dataclass instances (declared in ``worker``) to minimise churn in the rest of
the pipeline. A deferred import is used to avoid circular imports.

Design notes:
* Selector variability: multiple fallback selectors embrace frequent DOM shifts.
* Adaptive scroll: dynamic max scroll window based on recent density metrics.
* Filtering: language, recruitment, legal domain, author/permalink presence,
  job-seeker exclusion, France-only heuristic (all governed by settings flags).
* Diagnostics: optional HTML snapshots & verbose element logs via env flags.
* Canonicalisation: permalink canonicalised early to stabilise IDs.
* Content hash is computed later in orchestrator; not required here.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
import contextlib, os, re as _re

from .. import utils
from ..bootstrap import (
    SCRAPE_SCROLL_ITERATIONS,
    SCRAPE_RECRUITMENT_POSTS,
    SCRAPE_FILTERED_POSTS,
    SCRAPE_EXTRACTION_INCOMPLETE,
)
from .ids import canonical_permalink

# ------------------------------------------------------------
# Selector sets (broad to tolerate layout churn)
# ------------------------------------------------------------
POST_CONTAINER_SELECTORS = [
    "article[data-urn*='urn:li:activity']",
    "div.feed-shared-update-v2",
    "div.update-components-feed-update",
    "div.occludable-update",
    "div[data-urn*='urn:li:activity:']",
    "div.feed-shared-update-v3",
    "div.update-components-actor__container",
]
AUTHOR_SELECTOR = (
    "a.update-components-actor__meta-link, "
    "span.update-components-actor__meta a, "
    "a.update-components-actor__sub-description, "
    "a.update-components-actor__meta, "
    "a.app-aware-link, "
    "span.feed-shared-actor__name, "
    "span.update-components-actor__name"
)
TEXT_SELECTOR = (
    "div.update-components-text, "
    "div.feed-shared-update-v2__description-wrapper, "
    "span.break-words, "
    "div[dir='ltr']"
)
DATE_SELECTOR = "time"
MEDIA_INDICATOR_SELECTOR = "img, video"
PERMALINK_LINK_SELECTORS = [
    "a[href*='/feed/update/']",
    "a.app-aware-link[href*='activity']",
    "a[href*='/posts/']",
    "a[href*='activity']",
]
COMPANY_SELECTORS = [
    "span.update-components-actor__company",
    "span.update-components-actor__supplementary-info",
    "div.update-components-actor__meta span",
    "div.feed-shared-actor__subtitle span",
    "span.feed-shared-actor__description",
    "span.update-components-actor__description",
]

# Follower count cleaning (company pages sometimes appear as author)
_FOLLOWER_SEG_PATTERN = _re.compile(r"\b\d[\d\s\.,]*\s*(k|m)?\s*(abonn[eé]s?|followers)\b", _re.IGNORECASE)
_FOLLOWER_FULL_PATTERN = _re.compile(r"^\s*\d[\d\s\.,]*\s*(k|m)?\s*(abonn[eé]s?|followers)\s*$", _re.IGNORECASE)


def _dedupe_repeated_author(name: str) -> str:
    if not name:
        return name
    toks = name.split()
    if len(toks) % 2 == 0 and len(toks) >= 4:
        half = len(toks)//2
        if toks[:half] == toks[half:]:
            return " ".join(toks[:half])
    # Remove network level markers like "3e et +"
    name = _re.sub(r"\b\d+e?\s+et\s*\+\b", "", name, flags=_re.IGNORECASE)
    # Remove residual double spaces
    name = _re.sub(r"\s+", " ", name).strip()
    return name


def _strip_follower_segment(value: str) -> str:
    if not value:
        return value
    raw = value.strip()
    seps = [" • ", " · ", " | ", " - ", " – ", " — "]
    for sep in seps:
        if sep in raw:
            parts = [p.strip() for p in raw.split(sep) if p.strip()]
            filtered = [p for p in parts if not _FOLLOWER_FULL_PATTERN.match(p)]
            if filtered and len(filtered) != len(parts):
                raw = sep.join(filtered)
    if _FOLLOWER_FULL_PATTERN.match(raw):
        return ""
    if _FOLLOWER_SEG_PATTERN.search(raw):
        raw = _FOLLOWER_SEG_PATTERN.sub("", raw).strip()
    return raw.strip()


async def _scroll_and_wait(page: Any, ctx) -> None:  # type: ignore[no-untyped-def]
    try:
        await page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
    except Exception:  # pragma: no cover
        pass
    SCRAPE_SCROLL_ITERATIONS.inc()
    await page.wait_for_timeout(ctx.settings.scroll_wait_ms)


async def extract_posts(page: Any, keyword: str, max_items: int, ctx) -> list[Any]:  # returns list[Post]
    # Deferred import to avoid circular dependency at module import time.
    from ..worker import Post  # type: ignore

    posts: list[Post] = []
    seen_ids: set[str] = set()
    last_count = 0

    # Basic auth suspicion heuristic
    try:
        body_html = (await page.content()).lower()
        if any(marker in body_html for marker in ["se connecter", "join now", "créez votre profil", "s’inscrire"]):
            ctx.logger.warning("auth_suspect", detail="Texte suggérant une page non authentifiée")
    except Exception:
        pass

    dynamic_max_scroll = ctx.settings.max_scroll_steps
    try:
        if ctx.settings.adaptive_scroll_enabled and hasattr(ctx, "_recent_density"):
            dens = getattr(ctx, "_recent_density") or []
            if dens:
                avg = sum(dens)/len(dens)
                if avg < 1.5:
                    dynamic_max_scroll = min(ctx.settings.adaptive_scroll_max, ctx.settings.max_scroll_steps + 2)
                elif avg > 3:
                    dynamic_max_scroll = max(ctx.settings.adaptive_scroll_min, ctx.settings.max_scroll_steps - 1)
    except Exception:
        pass

    reject_stats: dict[str, int] = {}
    diagnostics_enabled = bool(int(os.environ.get("PLAYWRIGHT_DEBUG_SNAPSHOTS", "0")))
    for step in range(dynamic_max_scroll + 1):
        elements: list[Any] = []
        for selector in POST_CONTAINER_SELECTORS:
            try:
                found = await page.query_selector_all(selector)
                if found:
                    if step == 0:
                        ctx.logger.info("post_container_selector_match", selector=selector, count=len(found))
                    elements.extend(found)
            except Exception:
                continue
        if step == 0 and not elements:
            with contextlib.suppress(Exception):
                await page.wait_for_timeout(1200)
            if diagnostics_enabled:
                with contextlib.suppress(Exception):
                    html = await page.content()
                    snap_path = Path(ctx.settings.screenshot_dir) / f"debug_{keyword}_step0.html"
                    snap_path.write_text(html[:200_000], encoding="utf-8", errors="ignore")
                    ctx.logger.warning("debug_snapshot_written", path=str(snap_path), keyword=keyword)
            if not elements:
                with contextlib.suppress(Exception):
                    await page.evaluate("window.scrollBy(0, 600)")
                    await page.wait_for_timeout(800)
                for selector in POST_CONTAINER_SELECTORS:
                    with contextlib.suppress(Exception):
                        found2 = await page.query_selector_all(selector)
                        if found2:
                            elements.extend(found2)
                if diagnostics_enabled:
                    with contextlib.suppress(Exception):
                        html2 = await page.content()
                        snap_path2 = Path(ctx.settings.screenshot_dir) / f"debug_{keyword}_after_rescan.html"
                        snap_path2.write_text(html2[:200_000], encoding="utf-8", errors="ignore")
                        ctx.logger.warning("debug_snapshot_after_rescan", path=str(snap_path2), keyword=keyword, found=len(elements))
        verbose_el = bool(int(os.environ.get("PLAYWRIGHT_DEBUG_VERBOSE", "0")))
        if verbose_el:
            ctx.logger.info("elements_batch", keyword=keyword, step=step, count=len(elements))
        for idx_el, el in enumerate(elements):
            if len(posts) >= max_items:
                break
            author_el = await el.query_selector(AUTHOR_SELECTOR)
            if not author_el:
                with contextlib.suppress(Exception):
                    author_el = await el.query_selector("span.update-components-actor__name, span.feed-shared-actor__name")
            if not author_el:
                with contextlib.suppress(Exception):
                    author_el = await el.query_selector("span[dir='ltr'] strong, span[dir='ltr'] a")
            text_el = await el.query_selector(TEXT_SELECTOR) or await el.query_selector("div.update-components-text, div.feed-shared-update-v2__commentary")
            date_el = await el.query_selector(DATE_SELECTOR)
            media_el = await el.query_selector(MEDIA_INDICATOR_SELECTOR)

            company_val: Optional[str] = None
            for csel in COMPANY_SELECTORS:
                try:
                    c_el = await el.query_selector(csel)
                    if c_el:
                        raw_company = await c_el.inner_text()
                        if raw_company:
                            company_val = utils.normalize_whitespace(raw_company).strip()
                            if company_val:
                                break
                except Exception:
                    continue

            author = (await author_el.inner_text()) if author_el else "Unknown"
            if author:
                author = utils.normalize_whitespace(author).strip()
                for sep in [" •", "·", "Verified", "Vérifié"]:
                    if sep in author:
                        author = author.split(sep, 1)[0].strip()
                if author.endswith("Premium"):
                    author = author.replace("Premium", "").strip()
            if author and _FOLLOWER_SEG_PATTERN.search(author.lower()):
                cleaned = _strip_follower_segment(author)
                author = cleaned or "Unknown"
            if not author or author.lower() == "unknown":
                with contextlib.suppress(Exception):
                    meta_link = await el.query_selector("a.update-components-actor__meta-link")
                    if meta_link:
                        aria = await meta_link.get_attribute("aria-label")
                        if aria:
                            cut = aria
                            for sep in [" •", "·", "Vérifié", "Verified", "•"]:
                                if sep in cut:
                                    cut = cut.split(sep, 1)[0]
                                    break
                            cut = utils.normalize_whitespace(cut).strip()
                            if cut:
                                author = cut
                        if (not author or author.lower() == "unknown"):
                            txt = await meta_link.inner_text()
                            if txt:
                                txt = utils.normalize_whitespace(txt).strip()
                                if txt:
                                    author = txt
            if not author or author.lower() == "unknown":
                with contextlib.suppress(Exception):
                    title_span = await el.query_selector("span.update-components-actor__title span[dir='ltr']")
                    if title_span:
                        txt = await title_span.inner_text()
                        if txt:
                            author = utils.normalize_whitespace(txt).strip()
                if not company_val and author and author != "Unknown":
                    for sep in ["•", "-", "|", "·"]:
                        if sep in author:
                            parts = [p.strip() for p in author.split(sep) if p.strip()]
                            if len(parts) >= 2:
                                derived_company = parts[-1]
                                base_name = parts[0].lower()
                                if derived_company.lower() == base_name:
                                    continue
                                role_markers = ("juriste","avocat","counsel","lawyer","associate","stagiaire","intern","paralegal","legal","notaire")
                                if any(derived_company.lower().startswith(rm) for rm in role_markers):
                                    continue
                                if 2 < len(derived_company) <= 80 and not derived_company.lower().startswith("chez "):
                                    company_val = derived_company
                                    break
                if company_val and _FOLLOWER_SEG_PATTERN.search(company_val.lower()):
                    company_val = _strip_follower_segment(company_val) or None

            text_raw = ""
            with contextlib.suppress(Exception):
                text_raw = (await text_el.inner_text()) if text_el else ""
            text_norm = utils.normalize_whitespace(text_raw)
            if not company_val:
                candidates = []
                with contextlib.suppress(Exception):
                    desc_el2 = await el.query_selector("span.update-components-actor__description")
                    if desc_el2:
                        rd = await desc_el2.inner_text()
                        if rd:
                            rd = utils.normalize_whitespace(rd).strip()
                            candidates.append(rd)
                if text_norm:
                    candidates.append(text_norm)
                comp = None
                for blob in candidates:
                    blob_clean = blob.replace(" at ", " chez ")
                    for marker in ["@ ", "chez "]:
                        if marker in blob_clean:
                            tail = blob_clean.split(marker, 1)[1].strip()
                            for stop in [" |", " -", ",", " •", "  "]:
                                if stop in tail:
                                    tail = tail.split(stop, 1)[0].strip()
                            if 2 <= len(tail) <= 80:
                                comp = tail
                                break
                    if comp:
                        break
                if comp and (not author or comp.lower() != author.lower()):
                    company_val = comp

            published_raw = None
            published_iso = None
            with contextlib.suppress(Exception):
                published_raw = (await date_el.get_attribute("datetime")) if date_el else None
            if published_raw:
                published_iso = published_raw
            else:
                txt_for_date = ""
                if date_el:
                    with contextlib.suppress(Exception):
                        txt_for_date = await date_el.inner_text()
                if not txt_for_date:
                    with contextlib.suppress(Exception):
                        subdesc = await el.query_selector("span.update-components-actor__sub-description")
                        if subdesc:
                            txt_for_date = await subdesc.inner_text()
                dt = utils.parse_possible_date(txt_for_date)
                if dt:
                    published_iso = dt.isoformat()

            language = utils.detect_language(text_norm, ctx.settings.default_lang)
            provisional_pid = utils.make_post_id(keyword, author, published_iso or text_norm[:30] or str(idx_el))
            if provisional_pid in seen_ids:
                if verbose_el:
                    ctx.logger.info("element_skipped_duplicate", keyword=keyword, idx=idx_el)
                continue
            seen_ids.add(provisional_pid)
            recruitment_score = utils.compute_recruitment_signal(text_norm)

            permalink = None
            permalink_source = None
            try:
                for sel_link in PERMALINK_LINK_SELECTORS:
                    l = await el.query_selector(sel_link)
                    if l:
                        href = await l.get_attribute("href") or ""
                        if href:
                            if href.startswith('/'):
                                href = "https://www.linkedin.com" + href
                            if '?' in href:
                                href = href.split('?', 1)[0]
                            permalink = href
                            permalink_source = f"selector:{sel_link}"
                            break
            except Exception:
                pass
            if not permalink and date_el:
                with contextlib.suppress(Exception):
                    parent_link = await date_el.evaluate("el => el.closest('a') ? el.closest('a').href : null")  # type: ignore
                    if parent_link:
                        if '?' in parent_link:
                            parent_link = parent_link.split('?', 1)[0]
                        if parent_link.startswith('/'):
                            parent_link = "https://www.linkedin.com" + parent_link
                        permalink = parent_link
                        permalink_source = "time:closest"
            if not permalink:
                with contextlib.suppress(Exception):
                    a_el = await el.query_selector("a[href*='feed/update'], a[href*='activity']")
                    if a_el:
                        href = await a_el.get_attribute("href")
                        if href:
                            if '?' in href:
                                href = href.split('?', 1)[0]
                            if href.startswith('/'):
                                href = "https://www.linkedin.com" + href
                            permalink = href
                            permalink_source = "container:any-anchor"
            if not permalink:
                with contextlib.suppress(Exception):
                    urn = await el.get_attribute("data-urn") or ""
                    if "urn:li:activity:" in urn:
                        activity_id = urn.split("urn:li:activity:")[-1].strip()
                        if activity_id and activity_id.isdigit():
                            permalink = f"https://www.linkedin.com/feed/update/urn:li:activity:{activity_id}/"
                            permalink_source = "constructed_activity_id"
            if not permalink:
                with contextlib.suppress(Exception):
                    html_blob = await el.inner_html()
                    if html_blob and "urn:li:activity:" in html_blob:
                        m_act = _re.search(r"urn:li:activity:(\d+)", html_blob)
                        if m_act:
                            activity_id = m_act.group(1)
                            permalink = f"https://www.linkedin.com/feed/update/urn:li:activity:{activity_id}"
                            permalink_source = "html_scan_activity_id"
            if permalink_source:
                ctx.logger.debug("permalink_resolved", source=permalink_source)
            if recruitment_score >= ctx.settings.recruitment_signal_threshold:
                SCRAPE_RECRUITMENT_POSTS.inc()
            if permalink:
                permalink = canonical_permalink(permalink)
            final_id = utils.make_post_id(permalink) if permalink else provisional_pid
            if author:
                author = _dedupe_repeated_author(author)
            post = Post(
                id=final_id,
                keyword=keyword,
                author=author,
                author_profile=None,
                company=company_val,
                text=text_norm,
                language=language,
                published_at=published_iso,
                collected_at=datetime.now(timezone.utc).isoformat(),
                permalink=permalink,
                raw={"published_raw": published_raw, "recruitment_threshold": ctx.settings.recruitment_signal_threshold, "debug_idx": idx_el},
            )
            disable_filters = bool(int(os.environ.get("PLAYWRIGHT_DISABLE_STRICT_FILTERS", "0")))
            keep = True
            reject_reason = None
            if not disable_filters:
                try:
                    if ctx.settings.filter_language_strict and language.lower() != (ctx.settings.default_lang or "fr").lower():
                        keep = False; reject_reason = "language"
                    if keep and getattr(ctx.settings, 'filter_legal_domain_only', False):
                        tl = (text_norm or "").lower()
                        legal_markers = (
                            "juriste","avocat","legal","counsel","paralegal","notaire","droit","fiscal","conformité","compliance","secrétaire général","secretaire general","contentieux","litige","corporate law","droit des affaires"
                        )
                        if not any(m in tl for m in legal_markers):
                            keep = False; reject_reason = reject_reason or "non_domain"
                    if keep and ctx.settings.filter_recruitment_only and recruitment_score < ctx.settings.recruitment_signal_threshold:
                        keep = False; reject_reason = reject_reason or "recruitment"
                    if keep and ctx.settings.filter_require_author_and_permalink and (not post.author or post.author.lower() == "unknown" or not post.permalink):
                        keep = False; reject_reason = reject_reason or "missing_core_fields"
                    if keep and getattr(ctx.settings, 'filter_exclude_job_seekers', True):
                        tl = (text_norm or "").lower()
                        job_markers = (
                            "recherche d'emploi", "recherche d\u2019emploi", "cherche un stage", "cherche un emploi",
                            "à la recherche d'une opportunité", "a la recherche d'une opportunité",
                            "disponible immédiatement", "disponible immediatement", "open to work", "#opentowork",
                            "je suis à la recherche", "je suis a la recherche", "contactez-moi pour", "merci de me contacter",
                            "mobilité géographique", "mobilite geographique", "reconversion professionnelle"
                        )
                        if any(m in tl for m in job_markers):
                            keep = False; reject_reason = reject_reason or "job_seeker"
                    if keep and getattr(ctx.settings, 'filter_france_only', True):
                        tl = (text_norm or "").lower()
                        fr_positive = ("france","paris","idf","ile-de-france","lyon","marseille","bordeaux","lille","toulouse","nice","nantes","rennes")
                        foreign_negative = ("hiring in uk","remote us","canada","usa","australia","dubai","switzerland","swiss","belgium","belgique","luxembourg","portugal","espagne","spain","germany","deutschland","italy","singapore")
                        if any(f in tl for f in foreign_negative) and not any(p in tl for p in fr_positive):
                            keep = False; reject_reason = reject_reason or "not_fr"
                except Exception:
                    pass
            else:
                post.raw["filters_bypassed"] = True
            if keep:
                if post.company and post.author and post.company.lower() == post.author.lower():
                    post.company = None
                posts.append(post)
                if verbose_el:
                    ctx.logger.info("element_kept", keyword=keyword, idx=idx_el, author=post.author, has_permalink=bool(post.permalink), text_len=len(post.text))
            else:
                reason = reject_reason or "other"
                reject_stats[reason] = reject_stats.get(reason, 0) + 1
                with contextlib.suppress(Exception):
                    SCRAPE_FILTERED_POSTS.labels(reason).inc()
                if verbose_el:
                    ctx.logger.info("element_rejected", keyword=keyword, idx=idx_el, reason=reason, author=post.author, has_permalink=bool(post.permalink), text_len=len(post.text))
        if len(posts) >= max_items:
            break
        if len(posts) >= ctx.settings.min_posts_target and len(posts) == last_count:
            break
        last_count = len(posts)
        if step < dynamic_max_scroll:
            await _scroll_and_wait(page, ctx)

    if len(posts) < ctx.settings.min_posts_target:
        SCRAPE_EXTRACTION_INCOMPLETE.inc()
    try:
        if ctx.settings.adaptive_scroll_enabled:
            dens_list = getattr(ctx, "_recent_density", [])
            scrolls = max(1, min(dynamic_max_scroll, step + 1))
            dens_list.append(len(posts)/scrolls)
            win = ctx.settings.adaptive_scroll_window
            if len(dens_list) > win:
                dens_list = dens_list[-win:]
            setattr(ctx, "_recent_density", dens_list)
    except Exception:
        pass
    try:
        if reject_stats and os.environ.get("DEBUG_FILTER_SUMMARY", "1") != "0":
            kept = len(posts)
            total_rej = sum(reject_stats.values())
            ctx.logger.info(
                "extract_filter_summary",
                keyword=keyword,
                kept=kept,
                rejected=total_rej,
                **{f"rej_{k}": v for k, v in reject_stats.items()},
            )
    except Exception:
        pass
    return posts

__all__ = [
    "extract_posts",
    "POST_CONTAINER_SELECTORS",
]
