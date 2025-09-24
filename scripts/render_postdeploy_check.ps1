<#!
.SYNOPSIS
  Script de vérification post-déploiement Render.
.DESCRIPTION
  Effectue des requêtes clés (health, stats, posts, SSE court) et affiche un résumé.
.PARAMETER BaseUrl
  URL de base du service (ex: https://monapp.onrender.com).
.PARAMETER User
  Login Basic Auth si actif.
.PARAMETER Pass
  Mot de passe plaintext si hash non fourni; sinon ignorer et donner l'en-tête manuellement.
.PARAMETER TimeoutSSE
  Durée en secondes d'écoute du flux SSE (défaut 8).
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory)] [string]$BaseUrl,
  [string]$User,
  [string]$Pass,
  [int]$TimeoutSSE = 8
)
function Write-Info($m){ Write-Host "[INFO] $m" -ForegroundColor Cyan }
function Write-Step($m){ Write-Host "[STEP] $m" -ForegroundColor Magenta }
function Write-Warn($m){ Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Write-Err($m){ Write-Host "[ERR] $m" -ForegroundColor Red }

$ErrorActionPreference='Continue'
$headers = @{}
if($User -and $Pass){
  $pair = "$User:$Pass"
  $basic = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))
  $headers['Authorization'] = "Basic $basic"
}

function Invoke-Json($path){
  try { return Invoke-RestMethod -Uri ("$BaseUrl$path") -Headers $headers -TimeoutSec 30 }
  catch { Write-Err "Erreur requête $path : $_"; return $null }
}

Write-Step "Health"
$health = Invoke-Json '/health'
if($health){ Write-Info ("Health status: " + ($health.status)) }

Write-Step "Stats"
$stats = Invoke-Json '/api/stats'
if($stats){
  Write-Info "Mode mock: $($stats.playwright_mock_mode)"
  if($stats.autonomous_interval -ge 0){ Write-Info "Autonomous interval: $($stats.autonomous_interval)" }
}

Write-Step "Posts (limit=3)"
$posts = Invoke-Json '/api/posts?limit=3'
if($posts){ Write-Info "Posts retournés: $($posts | Measure-Object | Select -ExpandProperty Count)" }

Write-Step "SSE ($TimeoutSSE s)"
try {
  $req = [System.Net.HttpWebRequest]::Create("$BaseUrl/stream")
  foreach($k in $headers.Keys){ $req.Headers.Add($k, $headers[$k]) }
  $resp = $req.GetResponse()
  $stream = $resp.GetResponseStream()
  $reader = New-Object System.IO.StreamReader($stream)
  $end = (Get-Date).AddSeconds($TimeoutSSE)
  $lines = @()
  while((Get-Date) -lt $end -and -not $reader.EndOfStream){
    $line = $reader.ReadLine()
    if($line){ $lines += $line }
  }
  Write-Info "Lignes SSE capturées: $($lines.Count)"
  if($lines.Count -gt 0){ $lines | Select-Object -First 5 | ForEach-Object { Write-Host "  $_" } }
} catch { Write-Warn "SSE test partiel: $_" }

Write-Step "Résumé synthétique"
if($health -and $stats){
  Write-Host ("OK: health='" + $health.status + "' mock=$($stats.playwright_mock_mode) posts=$($posts.Count) sseLines=$($lines.Count)") -ForegroundColor Green
} else {
  Write-Warn "Vérifier les erreurs ci-dessus."
}
