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

Deux scénarios :

1. MSI simple (emballe l'exécutable one‑file ou one‑folder minimal)
2. MSI "folder" (harvest complet du dossier PyInstaller avec raccourcis Desktop + Menu Démarrer)

Prérequis : Installer WiX Toolset v3 et ajouter `candle.exe`, `light.exe`, `heat.exe` au PATH.

#### 1. MSI simple (one‑file)

```
pwsh ./scripts/build_msi.ps1 -Name 'TitanScraper' -Manufacturer 'Pierre LOGRE' -Version '1.0.0'
```
Sortie: `dist/msi/TitanScraper-1.0.0.msi`

#### 2. MSI folder (recommandé, avec raccourcis)

Construire d'abord le dossier PyInstaller (one‑folder) :
```
pwsh ./scripts/build_desktop_exe.ps1
```
Puis générer l'installeur avec les métadonnées demandées :
```
pwsh ./scripts/build_desktop_msi.ps1 -Name 'TitanScraper' -DisplayName 'Titan Scraper' -Manufacturer 'Pierre LOGRE' -Version '1.0.0'
```
Sortie : `dist/msi/TitanScraper-folder-1.0.0.msi`

Le script ajoute automatiquement :
- Raccourci Menu Démarrer (Current User)
- Raccourci Bureau
- Lancement optionnel post‑install

Notes sur les warnings ICE91 (LGHT1076) : ils indiquent que certains fichiers sont installés dans un dossier utilisateur qui ne varie pas selon ALLUSERS. Dans notre cas (installation per‑user par défaut) c'est bénin. Pour une installation machine‑wide propre, il faudrait déplacer les données dynamiques (logs, state) vers `%PROGRAMDATA%` ou `%LOCALAPPDATA%` et/ou ajuster les composants WiX.

## Build — macOS

- Requirements: Xcode command line tools, Python 3.11+
- Run:
  - `chmod +x build_mac.sh`
  - `./build_mac.sh`
- Output: `dist/TitanScraper/TitanScraper.app`
- Optional one‑file: `ONEFILE=1 ./build_mac.sh`

### Bootstrapper (macOS)
Pour un démarrage facilité (installation des navigateurs Playwright, préparation des dossiers), vous pouvez utiliser:
```
chmod +x scripts/bootstrap_macos.sh
./scripts/bootstrap_macos.sh
```
Ce script prépare `~/Library/Application Support/TitanScraper` (logs, exports, screenshots, traces), configure les variables d'environnement usuelles (SQLite, storage_state) et tente d'ouvrir `dist/TitanScraper.app` lorsqu'il est présent.

### Créer une image DMG (macOS)

- Après build de l’app:
  - `chmod +x scripts/build_dmg.sh`
  - `./scripts/build_dmg.sh 1.0.0`
- Sortie: `dist/TitanScraper-1.0.0.dmg`

## CI/CD (GitHub Actions)

You can add a workflow to build artifacts per platform. Example skeleton:

- Windows job: setup Python, install deps, run `build_windows.ps1`, upload `dist/`.
- macOS job: setup Python, run `build_mac.sh`, upload `dist/`.

Un workflow prêt-à-l'emploi a été ajouté: `.github/workflows/build_macos.yml`. Il:
- installe Python et les dépendances, Playwright Chromium
- exécute `scripts/build_macos.sh` puis `scripts/build_dmg.sh` (si présent)
- publie `dist/TitanScraper.app` et tout `.dmg` généré en artefacts

## Packaging notes

- FastAPI templates are embedded via the spec file; Docker/Render deployments continue to use `scripts/run_server.py` and `uvicorn` normally.
- We exclude `.venv`, tests, caches from the bundle.
- The desktop wrapper auto‑selects a free localhost port if `8000` is busy.
- The first run may download a Playwright browser if not already installed.

## Auto‑login (Windows uniquement pour l'instant)

Le wrapper desktop peut effectuer automatiquement la connexion LinkedIn si des identifiants chiffrés sont présents.

### Fichier `credentials.json`

Chemin : `%LOCALAPPDATA%/TitanScraper/credentials.json`

Format :
```jsonc
{
  "email": "user@example.com",
  "password_protected": "<base64 DPAPI>",
  "auto_login": true,
  "version": 1
}
```
`password_protected` contient le mot de passe chiffré via DPAPI (scopé à l'utilisateur Windows courant). Le fichier n'est donc déchiffrable que sur la même session utilisateur.

Si `auto_login` est `true` et que la page cible initiale est `/login`, l'application tente une requête POST `POST /api/session/login` avec les identifiants. En cas de succès, la fenêtre charge directement le dashboard `/`.

### Génération du fichier (script helper)

Un script d'aide est fourni :
```
pwsh -File scripts/store_credentials.ps1   # (si vous ajoutez un wrapper PowerShell) 
python scripts/store_credentials.py        # version Python directe
```
Le script Python interactif :
- Demande l'email
- Demande le mot de passe (caché)
- Produit / met à jour `credentials.json` avec le mot de passe protégé.

### Sécurité

- DPAPI (CryptProtectData) = chiffrement lié au profil utilisateur (pas multi‑machine).
- Tous les processus du même utilisateur peuvent déchiffrer ; ne stockez pas d'identifiants sensibles sur une machine partagée.
- Pour révoquer : supprimer le fichier `credentials.json`.

### Désactivation

Mettre `auto_login` à `false` ou supprimer le fichier.

## Répertoires et données utilisateur

Nouveaux répertoires utilisés :
```
%LOCALAPPDATA%/TitanScraper/logs/              (logs rotatifs)
%LOCALAPPDATA%/TitanScraper/credentials.json   (auto‑login)
```
Les données de session Playwright (`storage_state.json`) restent près de l'exécutable si générées côté serveur, sinon locales.

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
