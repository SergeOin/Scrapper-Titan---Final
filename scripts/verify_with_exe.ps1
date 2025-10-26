Param(
    [string]$ExePath = (Join-Path (Join-Path 'dist' 'TitanScraper') 'TitanScraper.exe'),
    [int]$WarmupSeconds = 10,
    [int]$PollSeconds = 90
)
$ErrorActionPreference = 'Stop'
if (!(Test-Path -LiteralPath $ExePath)) { throw "EXE not found at: $ExePath" }

# Start the EXE
Write-Host "Launching: $ExePath" -ForegroundColor Cyan
$p = Start-Process -FilePath $ExePath -PassThru
Start-Sleep -Seconds $WarmupSeconds

# Resolve server base URL from last_server.json
$infoPath = Join-Path $env:LOCALAPPDATA 'TitanScraper\last_server.json'
$base = 'http://127.0.0.1:8000'
if (Test-Path -LiteralPath $infoPath) {
  try {
    $info = Get-Content $infoPath -Raw | ConvertFrom-Json
    if ($info.host -and $info.port) { $base = "http://$($info.host):$($info.port)" }
  } catch {}
}
Write-Host "Base=$base" -ForegroundColor Gray

# Helper to fetch JSON safely
function Get-Json($url) {
  try {
    $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 20
    if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 300) {
      return ($r.Content | ConvertFrom-Json)
    }
  } catch {}
  return $null
}

# Snapshot initial health
$h0 = Get-Json "$base/health"
$lastRun0 = $null; $posts0 = $null
if ($h0) {
  $lastRun0 = $h0.last_run
  $posts0 = $h0.posts_count
}
Write-Host ("Initial: last_run={0} posts={1}" -f $lastRun0, $posts0) -ForegroundColor DarkGray

# Fire a non-sync trigger to avoid request timeouts
try {
  Invoke-WebRequest -Uri "$base/trigger" -Method POST -UseBasicParsing -TimeoutSec 10 | Out-Null
  Write-Host "Trigger queued (non-sync)" -ForegroundColor Green
} catch {
  Write-Host ("Trigger queue error: {0}" -f $_) -ForegroundColor Yellow
}

# Poll /health for progress
$deadline = (Get-Date).AddSeconds($PollSeconds)
$advanced = $false
$increased = $false
$hLast = $h0
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 10
  $h = Get-Json "$base/health"
  if (-not $h) { continue }
  $hLast = $h
  if ($lastRun0 -and $h.last_run) {
    if ($h.last_run -ne $lastRun0) { $advanced = $true }
  } elseif ($h.last_run) {
    $advanced = $true
  }
  if ($posts0 -ne $null -and $h.posts_count -ne $null) {
    if ([int]$h.posts_count -gt [int]$posts0) { $increased = $true }
  }
  if ($advanced -and $increased) { break }
}

Write-Host ("Health final: last_run={0} posts={1} auto={2} active={3}" -f $hLast.last_run, $hLast.posts_count, $hLast.autonomous_worker, $hLast.autonomous_worker_active) -ForegroundColor Cyan

# Fetch a small sample of posts for display
try {
  $posts = Get-Json "$base/api/posts?limit=5&order=desc"
  if ($posts -and $posts.items) {
    $sample = $posts.items | Select-Object -First 5 | ForEach-Object { $_.id + ' | ' + ($_.author) + ' | ' + ($_.collected_at) }
    Write-Host "Posts sample:" -ForegroundColor Cyan
    $sample | ForEach-Object { Write-Host "  $_" }
  } else {
    Write-Host "No posts returned or API unavailable" -ForegroundColor Yellow
  }
} catch {
  Write-Host ("Posts fetch error: {0}" -f $_) -ForegroundColor Yellow
}

# Stop the EXE
try {
  if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force }
} catch {}

# Emit a compact result code for CI/automation
if ($advanced) {
  if ($increased) { Write-Host "RESULT=advanced_and_increased" } else { Write-Host "RESULT=advanced_only" }
} else {
  Write-Host "RESULT=no_change"
}
