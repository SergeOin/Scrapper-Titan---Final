# Titan Scraper – Packaging and Installation

This guide shows how to build cross-platform installers (.MSI for Windows and .DMG for macOS) that bundle the backend, frontend and database, create a desktop shortcut, and auto-install missing prerequisites.

## What gets packaged
- Backend: FastAPI server (packaged via PyInstaller) with bundled `server/templates` and static `web/blocked` build when available.
- Frontend: The React UI in `web/blocked` (if Node is available during build; a fallback page is served otherwise).
- Database: Local SQLite file path is set to a per-user data directory, created on first run.
- Icon: The app icon is generated from `Titan Scraper logo.png`.
- Shortcuts:
  - Windows: Start Menu and Desktop shortcuts created by the MSI.
  - macOS: A Desktop alias is created on first launch (best-effort) and the DMG includes an Applications link.
- Prerequisites auto-install:
  - Windows: Microsoft Edge WebView2 Runtime is auto-detected and installed silently on first run if missing. Playwright Chromium is fetched on first launch if not found.
  - macOS: Playwright Chromium is fetched on first launch if not found.

## Windows (.MSI)
Prerequisites:
- Python 3.11+ (for building) and WiX Toolset v3 in PATH (candle.exe, light.exe, heat.exe)
- Node.js (optional) for building the frontend

Build steps:
1) Build the app and MSI
```
./scripts/package_windows.ps1
```
Artifacts:
- App: `dist/TitanScraper/`
- MSI: `dist/msi/TitanScraper-folder-<version>.msi`

Notes:
- The MSI embeds CABs by default so installation succeeds even if a .cab file would otherwise be missing.
- Desktop and Start Menu shortcuts are created automatically.
- If WebView2 Runtime is missing, the app will install it silently on first run (using a bootstrapper bundled when available, or by prompting the official installer).

## macOS (.DMG and .PKG)
Prerequisites:
- Xcode command line tools (for hdiutil)
- Python 3.11+ for building
- Node.js (optional) for building the frontend

Build steps:
1) Build the app and both DMG and PKG
```
./scripts/package_macos.sh
```
Artifacts:
- .app bundle: `dist/TitanScraper/TitanScraper.app`
- DMG: `dist/TitanScraper-<version>.dmg`
- PKG: `dist/TitanScraper-<version>.pkg`

Notes:
- The DMG includes a link to Applications for easy drag-and-drop.
- The PKG installs the app into `/Applications` and, in postinstall, best-effort creates a Desktop alias for the console user.
- On first launch, the app attempts to fetch Playwright browsers if missing; this may take a few minutes.

## Post-install verification
- Windows:
```
./scripts/post_install_verify_windows.ps1
```
- macOS:
```
./scripts/post_install_verify_macos.sh
```
These probes check `/health` and `/blocked-accounts` to confirm the backend is running and the frontend route responds.

## Troubleshooting
- If the `web/blocked` frontend isn’t built, the app serves a fallback informational page at `/blocked`.
- Playwright browsers are installed on first run to a per-user cache. This may take a few minutes depending on your network.
- For MSI signing, see `scripts/build_desktop_msi.ps1` which supports both PFX and certificate store signing.