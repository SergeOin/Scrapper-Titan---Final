# Changelog

All notable changes to this project will be documented here.

## 1.2.20-beta.1 - 2025-10-02

### Chore / Build
- chore(release): bump version to 1.2.19 (6847e23)
- chore(release): bump version to 1.2.18 for session gating refactor (6731b63)

### Features
- feat(dashboard): remove automatic initial cycle trigger and add manual 'Lancer un cycle' button with updated empty-state messages (c03bd76)
- feat(dashboard): improved contextual empty-state messages for posts table (8685a37)
- feat: diagnostics page, playwright reinstall endpoint, health playwright readiness, log noise reduction (b992b8e)
- feat(maintenance+metrics+tests): purge/vacuum settings, maintenance module, /metrics.json, initial test suite (hash, mock, language, integration sqlite) (812edcc)
- feat(security+errors): add Playwright failure registry + storage_state Fernet encryption support (2e43d24)
- feat: subprocess preflight forcing mock + /debug/status consolidated endpoint (631e97d)
- feat: add sync Playwright fallback (PLAYWRIGHT_FORCE_SYNC) + centralized error logging and docs (73ee973)
- feat(desktop): enforce LinkedIn session gating by default (ENFORCE_LINKEDIN_SESSION=1) (be91f5f)
- feat: stronger template fallback + debug endpoint and pywebview early diagnostic (52099e8)
- feat(desktop): robust template resolution + user data storage_state/session paths (1513e1c)
- feat(build): add scripts for building desktop EXE and MSI installers with smoke testing (047852b)
- feat(filters): improve company extraction heuristics, add legal domain filter, stricter language/company sanitation, Windows loop fix for Playwright (0049315)
- feat: add disable scraper flags, filter metrics, admin normalization endpoint, health enhancements and UI banner (4802ef3)
- feat(filters): company_norm index, job-seeker exclusion, France-only heuristic, new settings (969027d)
- feat(company): add company_norm field derivation, periodic normalization task, UI preference, dev settings (21d82a1)
- feat: company derivation heuristic (sqlite + mongo), normalization script, dev server entrypoint (acbd624)
- feat: Enhance MSI build script with improved icon handling and metadata (485dcdc)
- feat: Optimize initial scraping cycle and enhance user feedback during startup (185831d)
- feat: Enhance server and scraper functionality (2e5cd25)
- feat(desktop): window focus endpoint, watchdog, VERSION-driven builds, CI workflow, macOS script (a382e93)
- feat(desktop): add launch storm guard & restore immediate exit on mutex denial (v1.2.14) (78ead77)
- feat: Clean up login page UI by removing session expiration message; streamline dashboard export button and add admin script for soft-deleting posts in SQLite (eb7e365)
- feat: Implement Windows Proactor event loop policy for asyncio compatibility; enhance login process with credential storage options and improve error handling in login UI (2f4dd3a)
- feat: Enhance rate limiting and post flag management; update dashboard actions for better UX (82b1c9d)
- feat: Add post flagging and trash management features (c5fb811)

### Fixes
- fix: restore test expectations (mock mode overrides, sqlite hashing, rate limit bucket refresh) (181ef36)
- fix(playwright): graceful handling of NotImplementedError under reload (adds defensive try/except) (99c79ac)

### Other
- Enhance SQLite operations: update post count query to exclude demo users, add backfill-search task, and implement search_norm updates with indices in backfill_search_norm.py. (e843f22)
- first commit (644aabc)

### Refactors
- refactor: move extraction logic to core.extract and simplify worker; adjust tests for dedup/content-hash behavior (dea00a1)
- refactor(core): introduce modular core package (ids, mock, storage, navigation, extract, strategy, scheduler) + remove redundant loop policy code (0fddbb5)
- refactor(session): always log and optionally enforce LinkedIn session even in mock mode via ENFORCE_LINKEDIN_SESSION env (a47ac81)
- Refactor code structure for improved readability and maintainability (579db7d)
- Refactor code structure for improved readability and maintainability (03b2c4c)

## 1.2.21-beta.2 - 2025-10-02

### Chore / Build
- chore(release): bump version to 1.2.19 (6847e23)
- chore(release): bump version to 1.2.18 for session gating refactor (6731b63)

### Features
- feat(dashboard): remove automatic initial cycle trigger and add manual 'Lancer un cycle' button with updated empty-state messages (c03bd76)
- feat(dashboard): improved contextual empty-state messages for posts table (8685a37)
- feat: diagnostics page, playwright reinstall endpoint, health playwright readiness, log noise reduction (b992b8e)
- feat(maintenance+metrics+tests): purge/vacuum settings, maintenance module, /metrics.json, initial test suite (hash, mock, language, integration sqlite) (812edcc)
- feat(security+errors): add Playwright failure registry + storage_state Fernet encryption support (2e43d24)
- feat: subprocess preflight forcing mock + /debug/status consolidated endpoint (631e97d)
- feat: add sync Playwright fallback (PLAYWRIGHT_FORCE_SYNC) + centralized error logging and docs (73ee973)
- feat(desktop): enforce LinkedIn session gating by default (ENFORCE_LINKEDIN_SESSION=1) (be91f5f)
- feat: stronger template fallback + debug endpoint and pywebview early diagnostic (52099e8)
- feat(desktop): robust template resolution + user data storage_state/session paths (1513e1c)
- feat(build): add scripts for building desktop EXE and MSI installers with smoke testing (047852b)
- feat(filters): improve company extraction heuristics, add legal domain filter, stricter language/company sanitation, Windows loop fix for Playwright (0049315)
- feat: add disable scraper flags, filter metrics, admin normalization endpoint, health enhancements and UI banner (4802ef3)
- feat(filters): company_norm index, job-seeker exclusion, France-only heuristic, new settings (969027d)
- feat(company): add company_norm field derivation, periodic normalization task, UI preference, dev settings (21d82a1)
- feat: company derivation heuristic (sqlite + mongo), normalization script, dev server entrypoint (acbd624)
- feat: Enhance MSI build script with improved icon handling and metadata (485dcdc)
- feat: Optimize initial scraping cycle and enhance user feedback during startup (185831d)
- feat: Enhance server and scraper functionality (2e5cd25)
- feat(desktop): window focus endpoint, watchdog, VERSION-driven builds, CI workflow, macOS script (a382e93)
- feat(desktop): add launch storm guard & restore immediate exit on mutex denial (v1.2.14) (78ead77)
- feat: Clean up login page UI by removing session expiration message; streamline dashboard export button and add admin script for soft-deleting posts in SQLite (eb7e365)
- feat: Implement Windows Proactor event loop policy for asyncio compatibility; enhance login process with credential storage options and improve error handling in login UI (2f4dd3a)
- feat: Enhance rate limiting and post flag management; update dashboard actions for better UX (82b1c9d)
- feat: Add post flagging and trash management features (c5fb811)

### Fixes
- fix: restore test expectations (mock mode overrides, sqlite hashing, rate limit bucket refresh) (181ef36)
- fix(playwright): graceful handling of NotImplementedError under reload (adds defensive try/except) (99c79ac)

### Other
- Enhance SQLite operations: update post count query to exclude demo users, add backfill-search task, and implement search_norm updates with indices in backfill_search_norm.py. (e843f22)
- first commit (644aabc)

### Refactors
- refactor: move extraction logic to core.extract and simplify worker; adjust tests for dedup/content-hash behavior (dea00a1)
- refactor(core): introduce modular core package (ids, mock, storage, navigation, extract, strategy, scheduler) + remove redundant loop policy code (0fddbb5)
- refactor(session): always log and optionally enforce LinkedIn session even in mock mode via ENFORCE_LINKEDIN_SESSION env (a47ac81)
- Refactor code structure for improved readability and maintainability (579db7d)
- Refactor code structure for improved readability and maintainability (03b2c4c)

