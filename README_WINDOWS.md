# Windows – Lancer et Packager (EXE + MSI)

## Lancer en local (mode réel, sans démo)

```powershell
$env:PORT = '8001'
$env:PLAYWRIGHT_MOCK_MODE = '0'
$env:DISABLE_MONGO = '1'
$env:DISABLE_REDIS = '1'
$env:QUIET_STARTUP = '1'
python scripts/run_server.py
```

Ouvrir: <http://127.0.0.1:8001/>

Déclencher un run ponctuel (ex: Juriste):

```powershell
$env:PLAYWRIGHT_HEADLESS = '0'
python scripts/run_once.py --keywords 'Juriste'
```

## Construction d'un EXE (PyInstaller)

Prérequis: Python + pip.

```powershell
.\scripts\build_exe.ps1 -Name 'TitanScraperDashboard'
```

Le binaire est généré dans `dist\TitanScraperDashboard.exe`.

Notes:

- Le premier run réel peut nécessiter les navigateurs Playwright:
  
  ```powershell
  playwright install chromium
  ```

## Construction d'un MSI (WiX Toolset)

Prérequis: WiX v3 (candle.exe, light.exe dans PATH).

```powershell
.\scripts\build_msi.ps1 -Name 'TitanScraperDashboard' -Manufacturer 'Titan Partners' -Version '1.0.0'
```

Le MSI est produit dans `dist\msi\TitanScraperDashboard-1.0.0.msi` et installe un raccourci menu Démarrer qui lance l'EXE.

## Limitations et conseils

- Le packaging EXE/MSI embarque l'appli; pour le scraping réel, assurez-vous que `storage_state.json` est fourni et que Playwright a ses navigateurs installés.
- Pour une prod serveur, privilégier Docker/Render (voir `Dockerfile`, `docker-compose.yml`, `render.yaml`).

## Variables d'environnement utiles (Windows Desktop)

| Variable | Effet | Valeur par défaut |
|----------|-------|-------------------|
| AUTONOMOUS_WORKER_INTERVAL_SECONDS | Pause (s) entre cycles autonomes si mode autonome | 3600 |
| SQLITE_PATH | Force le chemin du fallback SQLite | %LOCALAPPDATA%/TitanScraper/fallback.sqlite3 |
| PLAYWRIGHT_MOCK_MODE | 1 = posts synthétiques (aucun navigateur) | 0 |
| PLAYWRIGHT_HEADLESS | 1 = sans UI, 0 = affiche Chromium | 1 |
| FORCE_PLAYWRIGHT_DISABLED | 1 = désactive totalement Playwright et active directement le mock | 0 |
| AUTO_ENABLE_MOCK_ON_PLAYWRIGHT_FAILURE | 1 = bascule auto en mock si échec Playwright (NotImplementedError) | 1 |
| PLAYWRIGHT_FORCE_SYNC | 1 = utilise l'API sync Playwright dans un thread (contournement subprocess) | 0 |
| EVENT_LOOP_POLICY | selector / proactor (forcer loop Windows) | selector |
| WIN_LOOP | Alias historique pour choisir la policy (selector/proactor) | selector |

Astuce: pour forcer le mock si le packagé refuse toujours de lancer Chromium:

```powershell
$env:FORCE_PLAYWRIGHT_DISABLED='1'; $env:PLAYWRIGHT_MOCK_MODE='1'; .\TitanScraper.exe
```

Ensuite l'appli génèrera des posts synthétiques et créera quand même `fallback.sqlite3` pour tests UI.

Contournement expérimental (sync fallback):

Si l'async Playwright échoue (NotImplementedError subprocess) mais vous voulez tester un lancement minimal Chromium:

```powershell
$env:PLAYWRIGHT_FORCE_SYNC='1'; .\TitanScraper.exe
```

Le mode sync actuel ne fait qu'un cycle de navigation superficiel (sans extraction avancée) et journalise `playwright_sync_cycle`. Il sert de base pour une future extraction complète.
