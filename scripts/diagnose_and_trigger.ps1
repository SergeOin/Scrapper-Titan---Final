param(
  [string]$Keywords = 'avocat',
  [int]$TimeoutSec = 600,
  [switch]$Relaxed,
  [string]$Base,
  [switch]$Sync = $false
)
$ErrorActionPreference = 'Stop'
function Get-BaseUrl {
  $srvInfo = Join-Path $env:LOCALAPPDATA 'TitanScraper\last_server.json'
  if ($Base) { return $Base }
  if (Test-Path $srvInfo) {
    try { $data = Get-Content $srvInfo -Raw | ConvertFrom-Json; return "http://$($data.host):$($data.port)" } catch { }
  }
  return 'http://127.0.0.1:8000'
}
function Get-AuthHeader {
  if ($Env:INTERNAL_AUTH_USER -and $Env:INTERNAL_AUTH_PASS) {
    $bytes = [Text.Encoding]::ASCII.GetBytes("$($Env:INTERNAL_AUTH_USER):$($Env:INTERNAL_AUTH_PASS)")
    return @{ Authorization = "Basic " + [Convert]::ToBase64String($bytes) }
  }
  return @{}
}
function Ensure-Exe {
  $exe1 = Join-Path (Join-Path 'dist' 'TitanScraper') 'TitanScraper.exe'
  $exe2 = Join-Path (Join-Path $PSScriptRoot '..\dist\TitanScraper') 'TitanScraper.exe'
  $exe = $null
  if (Test-Path $exe1) { $exe = $exe1 } elseif (Test-Path $exe2) { $exe = $exe2 }
  if (-not $exe) { throw "EXE not found under dist/TitanScraper" }
  # If a server is already up, don't start a new one
  $base = Get-BaseUrl
  try { $h = Invoke-RestMethod -Uri "$base/health" -Headers (Get-AuthHeader) -TimeoutSec 3 } catch { $h = $null }
  if (-not $h) {
    Write-Host "Starting EXE..." -ForegroundColor Cyan
    Start-Process -FilePath $exe | Out-Null
    Start-Sleep -Seconds 10
  }
}

$base = Get-BaseUrl
Ensure-Exe
$base = Get-BaseUrl
Write-Host "Base=$base" -ForegroundColor Yellow

# 1) Health
try {
  $health = Invoke-RestMethod -Uri "$base/health" -Headers (Get-AuthHeader) -TimeoutSec 10
  Write-Host "Health: status=$($health.status) active=$($health.active) posts=$($health.posts_count) last_run=$($health.last_run)" -ForegroundColor Green
} catch { Write-Host "Health error: $_" -ForegroundColor Red }

# 2) Auth debug
try {
  $auth = Invoke-RestMethod -Uri "$base/debug/auth" -Headers (Get-AuthHeader) -TimeoutSec 10
  Write-Host "Auth: storage_state_exists=$($auth.storage_state_exists) size=$($auth.storage_state_size) path=$($auth.storage_state_path) mock=$($auth.playwright_mock_mode)" -ForegroundColor Cyan
  if (-not $auth.storage_state_exists) {
    Write-Host "Importing cookies from local browsers..." -ForegroundColor Cyan
    try {
      $imp = Invoke-RestMethod -Uri "$base/api/session/import_cookies" -Method POST -Headers (Get-AuthHeader) -TimeoutSec 60
      Write-Host "Import: ok=$($imp.ok) used=$($imp.used) cookies=$($imp.cookies_count)" -ForegroundColor Cyan
    } catch { Write-Host "Import error: $_" -ForegroundColor Red }
  }
} catch { Write-Host "Auth debug error: $_" -ForegroundColor Red }

# 3) Trigger
$body = "keywords=$Keywords"
try {
  Write-Host "Triggering run (keywords=$Keywords; sync=$($Sync.IsPresent); timeout=$TimeoutSec s; relaxed=$($Relaxed.IsPresent))..." -ForegroundColor Yellow
  $url = "$base/trigger"
  if ($Sync) { $url += "?sync=1" } else { $url += "?" }
  if ($Relaxed) { $url += "&relaxed=1" }
  $resp = Invoke-WebRequest -Uri $url -Method POST -UseBasicParsing -ContentType 'application/x-www-form-urlencoded' -Body $body -Headers (Get-AuthHeader) -TimeoutSec $TimeoutSec
  Write-Host ("TriggerStatus=" + $resp.StatusCode)
  Write-Host ("TriggerBody=" + $resp.Content)
} catch { Write-Host ("TriggerErr=" + $_) -ForegroundColor Red }

# 4) Last batch
try {
  $last = Invoke-RestMethod -Uri "$base/debug/last_batch?limit=5" -Headers (Get-AuthHeader) -TimeoutSec 20
  Write-Host "LastBatch: count=$($last.count)" -ForegroundColor Green
  $last.items | ForEach-Object { Write-Host ("- " + $_.author + " | " + $_.company + " | " + $_.keyword + " | " + $_.permalink) }
} catch { Write-Host "Last batch error: $_" -ForegroundColor Red }
