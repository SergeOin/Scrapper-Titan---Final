# Titan Scraper — Desktop Edition

This adds a native desktop wrapper around the existing FastAPI app, so non-technical users can double‑click to run the scraper and dashboard locally on Windows and macOS.

What’s inside:

- Reuses the existing FastAPI server (`server/main.py`, templates, routes)
- Boots Uvicorn in‑process
- Opens a native window using pywebview pointing to `http://127.0.0.1:<port>/`
- Packages with PyInstaller into:
  - Windows: `TitanScraper` folder with `TitanScraper.exe`
  - macOS: `TitanScraper.app`

## Folder additions

- `desktop/main.py`: desktop entrypoint (no changes to server code)
- `desktop/pyinstaller.spec`: build recipe
- `desktop/requirements-desktop.txt`: extra deps for the desktop shell
- `build_windows.ps1` and `build_mac.sh`: one‑shot platform builds
- `scripts/util_make_icon.py`: converts `Titan Scraper logo.png` to `.ico`/`.icns`

## Quick start (from source)

- Windows (PowerShell):
  1) Create venv and install
     - `py -3 -m venv .venv`
     - `.\\.venv\\Scripts\\Activate.ps1`
     - `pip install -r requirements.txt`
     - `pip install -r desktop/requirements-desktop.txt`
     - Optional (first run smoother): `python -m playwright install chromium --with-deps`
  2) Run the desktop app
     - `python desktop/main.py`

- macOS (Terminal):
  1) `python3 -m venv .venv && source .venv/bin/activate`
  2) `pip install -r requirements.txt -r desktop/requirements-desktop.txt`
  3) Optional: `python -m playwright install chromium --with-deps`
  4) `python desktop/main.py`

If login to LinkedIn is required, use the in‑app “Login” page. Artifacts are saved next to the executable/source tree (e.g., `exports/`, `screenshots/`, `fallback.sqlite3`).

## Build — Windows

- Requirements: Python 3.11+, PowerShell, Visual C++ build tools (if required by some deps)
- Run:
  - `./build_windows.ps1`
- Output: `dist/TitanScraper/TitanScraper.exe`
- Optional one‑file: `./build_windows.ps1 -OneFile`

### Créer un installeur MSI (Windows)

- Installer WiX Toolset v3 (ajouter `candle.exe`, `light.exe`, `heat.exe` au PATH).
- Construire l’app (ci‑dessus), puis:
  - `pwsh ./scripts/build_msi_folder.ps1 -Version 1.0.0`
- Sortie: `dist/msi/TitanScraper-1.0.0.msi`

## Build — macOS

- Requirements: Xcode command line tools, Python 3.11+
- Run:
  - `chmod +x build_mac.sh`
  - `./build_mac.sh`
- Output: `dist/TitanScraper/TitanScraper.app`
- Optional one‑file: `ONEFILE=1 ./build_mac.sh`

### Créer une image DMG (macOS)

- Après build de l’app:
  - `chmod +x scripts/build_dmg.sh`
  - `./scripts/build_dmg.sh 1.0.0`
- Sortie: `dist/TitanScraper-1.0.0.dmg`

## CI/CD (GitHub Actions)

You can add a workflow to build artifacts per platform. Example skeleton:

- Windows job: setup Python, install deps, run `build_windows.ps1`, upload `dist/`.
- macOS job: setup Python, run `build_mac.sh`, upload `dist/`.

## Packaging notes

- FastAPI templates are embedded via the spec file; Docker/Render deployments continue to use `scripts/run_server.py` and `uvicorn` normally.
- We exclude `.venv`, tests, caches from the bundle.
- The desktop wrapper auto‑selects a free localhost port if `8000` is busy.
- The first run may download a Playwright browser if not already installed.

## Configuration and persistence

- Environment variables still work (e.g., `APP_PORT`, `DASHBOARD_PUBLIC`, `INPROCESS_AUTONOMOUS`).
- SQLite fallback file `fallback.sqlite3` is shipped alongside the app; you can replace it with your own.
- Local session files (`storage_state.json`, `session_store.json`) remain next to the app unless configured otherwise.

## Troubleshooting

- “Chromium not found” → run `python -m playwright install chromium` once.
- Window opens blank → ensure the health check responds at `http://127.0.0.1:<port>/health`.
- Antivirus flags `.exe` → try the one‑folder build instead of `--onefile`.

## License and third‑party

- pywebview is used to render the dashboard window.
- PyInstaller is used for packaging.
- Your existing licenses for FastAPI/Playwright dependencies still apply.
