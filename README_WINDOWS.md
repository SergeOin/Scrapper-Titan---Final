# Windows – Lancer et Packager (EXE + MSI)

## Lancer en local (mode réel, sans démo)
```powershell
$env:PORT = '8001'
$env:PLAYWRIGHT_MOCK_MODE = '0'
$env:DISABLE_REDIS = '1'
$env:QUIET_STARTUP = '1'
python scripts/run_server.py
```
Ouvrir: http://127.0.0.1:8001/

Déclencher un run ponctuel (ex: Juriste):
```powershell
$env:PLAYWRIGHT_HEADLESS = '0'
python scripts/run_once.py --keywords 'Juriste'
```

## Construction d'un EXE (PyInstaller)
Prérequis: Python + pip.
```powershell
.\scripts\build_exe.ps1 -Name 'Titan Scraper'
```
Le binaire est généré dans `dist\Titan Scraper.exe`.

Notes:
- Le premier run réel peut nécessiter les navigateurs Playwright: 
  ```powershell
  playwright install chromium
  ```

### Bootstrapper Desktop (recommandé)
Pour un premier lancement fluide côté utilisateur (WebView2, navigateurs Playwright, répertoires), lancez le bootstrapper:
```powershell
PowerShell -ExecutionPolicy Bypass -File .\scripts\bootstrap_windows.ps1
```
Ce script:
- Vérifie/installe WebView2 Runtime si nécessaire
- Installe Chromium pour Playwright dans un dossier utilisateur (`%LOCALAPPDATA%\TitanScraper\pw-browsers`)
- Prépare les dossiers applicatifs (`logs`, `exports`, `screenshots`, `traces`)
- Positionne des variables d'environnement sûres (SQLite, storage_state)
- Démarre automatiquement `dist/TitanScraper/TitanScraper.exe` si présent

## Construction d'un MSI (WiX Toolset)
Prérequis: WiX v3 (candle.exe, light.exe dans PATH).
```powershell
.\scripts\build_msi.ps1 -Name 'Titan Scraper' -Manufacturer 'Titan Partners' -Version '1.0.0'
```
Le MSI est produit dans `dist\msi\Titan Scraper-1.0.0.msi` et installe un raccourci menu Démarrer qui lance l'EXE.

## Limitations et conseils
- Le packaging EXE/MSI embarque l'appli; pour le scraping réel, assurez-vous que `storage_state.json` est fourni et que Playwright a ses navigateurs installés.
- Pour une prod serveur, privilégier Docker/Render (voir `Dockerfile`, `docker-compose.yml`, `render.yaml`).
