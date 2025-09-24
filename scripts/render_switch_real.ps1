<#!
.SYNOPSIS
  Bascule du mode mock -> mode réel local (simulation Render) avec injection STORAGE_STATE_B64.
.DESCRIPTION
  1. Vérifie présence ou demande base64.
  2. Optionnel: active auth basique.
  3. (Re)lance le serveur en mode réel sans interval puis propose d'activer l'autonome.
.PARAMETER Base64
  Chaîne base64 du storage_state (si non fournie, lit $Env:STORAGE_STATE_B64 ou invite utilisateur).
.PARAMETER WithAuth
  Active Basic Auth interne (demande login + pass si non fournis via variables).
.PARAMETER Interval
  Intervalle autonome à activer après validations (défaut 600). 0 = ne pas activer.
.PARAMETER Port
  Port d'écoute (défaut 8000).
.EXAMPLE
  ./render_switch_real.ps1 -Base64 (Get-Content storage_state.b64 -Raw) -WithAuth -Interval 900
#>
[CmdletBinding()]
param(
  [string]$Base64,
  [switch]$WithAuth,
  [int]$Interval = 600,
  [int]$Port = 8000
)
function Write-Info($m){ Write-Host "[INFO] $m" -ForegroundColor Cyan }
function Write-Step($m){ Write-Host "[STEP] $m" -ForegroundColor Magenta }
function Write-Warn($m){ Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Write-Err($m){ Write-Host "[ERR] $m" -ForegroundColor Red }

$ErrorActionPreference='Stop'

Write-Step "Bascule en mode REAL"
if(-not $Base64){
  if($Env:STORAGE_STATE_B64){ $Base64 = $Env:STORAGE_STATE_B64 }
  else { Write-Info "Colle la chaîne base64 (entrée valide puis Enter):"; $Base64 = Read-Host }
}
if(-not $Base64){ Write-Err "Aucune base64 fournie"; exit 1 }

# Validation basique
try {
  $decoded = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Base64))
  $null = $decoded | ConvertFrom-Json
  Write-Info "Base64 décodée, JSON valide (taille=$($decoded.Length))"
} catch { Write-Warn "Décodage JSON a échoué: $_ (on continue mais Playwright peut échouer)" }

$Env:STORAGE_STATE_B64 = $Base64
$Env:PLAYWRIGHT_MOCK_MODE = '0'
$Env:INPROCESS_AUTONOMOUS = '1'
$Env:AUTONOMOUS_WORKER_INTERVAL_SECONDS = '0'   # D'abord désactivé
$Env:DASHBOARD_PUBLIC = '0'
$Env:PORT = "$Port"

if($WithAuth){
  if(-not $Env:INTERNAL_AUTH_USER){ $Env:INTERNAL_AUTH_USER = Read-Host "Login" }
  if(-not $Env:INTERNAL_AUTH_PASS -and -not $Env:INTERNAL_AUTH_PASS_HASH){ $Env:INTERNAL_AUTH_PASS = Read-Host "Mot de passe (plaintext)" }
  Write-Info "Auth interne activée pour l'UI & API"
}

Write-Info "Variables courantes:";
@('PLAYWRIGHT_MOCK_MODE','INPROCESS_AUTONOMOUS','AUTONOMOUS_WORKER_INTERVAL_SECONDS','DASHBOARD_PUBLIC','PORT','INTERNAL_AUTH_USER','INTERNAL_AUTH_PASS','INTERNAL_AUTH_PASS_HASH','STORAGE_STATE_B64') | ForEach-Object {
  $name = $_
  $valItem = Get-Item -Path Env:$name -ErrorAction SilentlyContinue
  if($valItem){
    $val = $valItem.Value
    if($val.Length -gt 60){ $val = $val.Substring(0,60) + '...' }
    Write-Host "  $name=\"$val\""
  }
}

Write-Step "Lancement serveur en mode réel (autonome OFF). Ctrl+C pour stopper"
python .\scripts\run_server.py

if($Interval -gt 0){
  Write-Step "Relance avec autonome interval=$Interval"
  $Env:AUTONOMOUS_WORKER_INTERVAL_SECONDS = "$Interval"
  python .\scripts\run_server.py
}
