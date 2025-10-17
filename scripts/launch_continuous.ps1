<#
Automatise purge + lancement continu (server + worker) pour le scraper LinkedIn.

Usage:
  powershell -ExecutionPolicy Bypass -File scripts\launch_continuous.ps1 -Interval 900 -Headless:$false -Mock:$false -Keywords "python;ai" -LoginWait 0

Paramètres principaux:
  -Interval (seconds) : fréquence entre cycles autonomes (worker). 0 = désactivé (un seul passage)
  -Headless           : $true pour navigateur invisible, $false pour debug
  -Mock               : $true active le mode posts synthétiques (aucun accès web réel)
  -Keywords           : chaîne séparée par ';'
  -LoginWait          : secondes d'attente initiale dans le navigateur (MFA / SSO)
  -ForcePurge         : ne demande pas de confirmation (supprime données directement)
  -ServerOnly         : ne lance que l'API (pas le worker)
  -WorkerOnly         : ne lance que le worker (pas l'API)

Le script:
  1. Active l'environnement virtuel
  2. Définit les variables d'environnement
  3. Exécute la purge (optionnelle)
  4. Lance soit run_all.py (server + worker) soit server/worker séparés

Arrêt:
  - Ctrl+C dans chaque terminal
  - OU endpoint /shutdown avec SHUTDOWN_TOKEN si configuré
#>
param(
  [int]$Interval = 900,
  [switch]$Headless,
  [switch]$Mock,
  [string]$Keywords = "python;ai",
  [int]$LoginWait = 0,
  [switch]$ForcePurge,
  [switch]$ServerOnly,
  [switch]$WorkerOnly
)

function Set-Env {
  param($Name,$Value)
  Write-Host "[env] $Name=$Value" -ForegroundColor DarkCyan
  try {
    # PowerShell 5.1-compatible dynamic env var assignment
    Set-Item -Path ("Env:{0}" -f $Name) -Value ($Value.ToString()) -Force | Out-Null
  } catch {
    [System.Environment]::SetEnvironmentVariable($Name, [string]$Value, 'Process')
  }
}

# 1. Activer venv
if (-not (Test-Path .venv)) {
  Write-Host "[venv] Création environnement virtuel" -ForegroundColor Cyan
  python -m venv .venv
}
. .\.venv\Scripts\Activate.ps1

# 2. Variables d'environnement essentielles
Set-Env SCRAPING_ENABLED 1
if ($Mock.IsPresent) { Set-Env PLAYWRIGHT_MOCK_MODE 1 } else { Set-Env PLAYWRIGHT_MOCK_MODE 0 }
if ($Headless.IsPresent) { Set-Env PLAYWRIGHT_HEADLESS 1 } else { Set-Env PLAYWRIGHT_HEADLESS 0 }
Set-Env SCRAPE_KEYWORDS $Keywords
Set-Env AUTONOMOUS_WORKER_INTERVAL_SECONDS $Interval
Set-Env LOGIN_INITIAL_WAIT_SECONDS $LoginWait
Set-Env LOG_LEVEL info

# Prefer local SQLite fallback unless explicitly overridden
if (-not $Env:DISABLE_MONGO) { Set-Env DISABLE_MONGO 1 }
if (-not $Env:DISABLE_REDIS) { Set-Env DISABLE_REDIS 1 }

# (Optionnel) tokens pour endpoints protégés si vous voulez les utiliser
if (-not $Env:TRIGGER_TOKEN) { Set-Env TRIGGER_TOKEN (New-Guid).Guid.Substring(0,8) }
if (-not $Env:SHUTDOWN_TOKEN) { Set-Env SHUTDOWN_TOKEN (New-Guid).Guid.Substring(0,8) }

# 3. Purge des données si souhaité
if ($ForcePurge.IsPresent) {
  Write-Host "[purge] Suppression des données existantes" -ForegroundColor Yellow
  python scripts/purge_data.py --force
  if ($LASTEXITCODE -ne 0) { Write-Warning "La purge a échoué (code $LASTEXITCODE)" }
}

# 4. Lancement
if ($ServerOnly -and $WorkerOnly) {
  Write-Error "Ne pas spécifier -ServerOnly et -WorkerOnly en même temps"; exit 1
}

if ($ServerOnly) {
  Write-Host "[start] API uniquement" -ForegroundColor Green
  python scripts/run_server.py
  exit $LASTEXITCODE
}
if ($WorkerOnly) {
  Write-Host "[start] Worker uniquement" -ForegroundColor Green
  python scripts/run_worker.py
  exit $LASTEXITCODE
}

Write-Host "[start] Server + Worker (run_all.py)" -ForegroundColor Green
python scripts/run_all.py
