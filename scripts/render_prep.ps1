<#!
.SYNOPSIS
  Prépare un test local (mode mock) simulant un déploiement Render (service unique avec worker in-process).
.DESCRIPTION
  1. Optionnel: installe dépendances Python.
  2. (Optionnel) installe Playwright + deps (si jamais on veut basculer réel plus tard).
  3. Exporte les variables d'environnement pour un run LOCAL mock.
  4. Lance le serveur FastAPI sur le port 8000.
.PARAMETER Install
  Si présent, installe requirements.txt.
.PARAMETER InstallPlaywright
  Si présent, exécute "playwright install chromium".
.PARAMETER Interval
  Intervalle secondes pour le worker autonome (défaut: 60 pour test rapide).
.PARAMETER Port
  Port d'écoute local (défaut 8000).
.PARAMETER NoRun
  Si présent, NE lance PAS le serveur (ne fait que poser les variables + résumé).
.EXAMPLE
  ./render_prep.ps1 -Install -InstallPlaywright -Interval 120
.NOTES
  Interrompre le serveur avec Ctrl+C. Pour passer ensuite en mode réel utiliser le script render_switch_real.ps1.
#>
[CmdletBinding()]
param(
  [switch]$Install,
  [switch]$InstallPlaywright,
  [int]$Interval = 60,
  [int]$Port = 8000,
  [switch]$NoRun
)

function Write-Info($m){ Write-Host "[INFO] $m" -ForegroundColor Cyan }
function Write-Step($m){ Write-Host "[STEP] $m" -ForegroundColor Magenta }
function Write-Warn($m){ Write-Host "[WARN] $m" -ForegroundColor Yellow }

$ErrorActionPreference = 'Stop'

Write-Step "Préparation environnement local (mode MOCK)"
if($Install){
  Write-Info "Installation dépendances Python"; pip install -r requirements.txt | Out-Host
}
if($InstallPlaywright){
  Write-Info "Installation Playwright (chromium)"; playwright install chromium | Out-Host
}

# Variables mock
$Env:PLAYWRIGHT_MOCK_MODE = '1'
$Env:INPROCESS_AUTONOMOUS = '1'
$Env:AUTONOMOUS_WORKER_INTERVAL_SECONDS = "$Interval"
$Env:DASHBOARD_PUBLIC = '1'
$Env:PORT = "$Port"

Write-Info "Variables exportées:";
@('PLAYWRIGHT_MOCK_MODE','INPROCESS_AUTONOMOUS','AUTONOMOUS_WORKER_INTERVAL_SECONDS','DASHBOARD_PUBLIC','PORT') | ForEach-Object {
  $name = $_
  $valItem = Get-Item -Path Env:$name -ErrorAction SilentlyContinue
  $val = if($valItem){ $valItem.Value } else { '' }
  Write-Host "  $name=\"$val\""
}

if($NoRun){
  Write-Warn "NoRun actif: le serveur n'est pas lancé. Exécute: python .\scripts\run_server.py"
  return
}

Write-Step "Lancement serveur (Ctrl+C pour arrêter)"
python .\scripts\run_server.py
