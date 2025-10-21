Param(
  [string]$ExePath = "$Env:LOCALAPPDATA\TitanScraper\TitanScraper.exe",
  [int]$WaitSeconds = 45,
  [string]$ServerHost = '127.0.0.1'
)

function Get-LastServerInfo {
  try {
    $jsonPath = Join-Path $Env:LOCALAPPDATA 'TitanScraper\last_server.json'
    if (Test-Path -LiteralPath $jsonPath) {
      $raw = Get-Content -LiteralPath $jsonPath -Raw -ErrorAction Stop
      return $raw | ConvertFrom-Json -ErrorAction Stop
    }
  } catch {}
  return $null
}

function Test-Health([string]$baseUrl, [int]$timeoutSec = 3) {
  try {
    $u = ($baseUrl.TrimEnd('/') + '/health')
    $resp = Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec $timeoutSec
    return $resp.StatusCode -eq 200
  } catch {
    return $false
  }
}

Write-Host "Post-install verification starting..." -ForegroundColor Cyan

if (!(Test-Path -LiteralPath $ExePath)) {
  Write-Warning "Executable not found: $ExePath"
  exit 1
}

Write-Host "Launching: $ExePath" -ForegroundColor Yellow
$p = Start-Process -FilePath $ExePath -PassThru

# Determine candidate ports: last_server.json first, then common fallbacks
$last = Get-LastServerInfo
$ports = @()
if ($last -and $last.port) { $ports += [int]$last.port }
$ports += 8000,8001,8002,8003,8004 | Select-Object -Unique

# Poll for health up to $WaitSeconds
$baseUrl = $null
$deadline = (Get-Date).AddSeconds([Math]::Max(10, $WaitSeconds))
while ((Get-Date) -lt $deadline) {
  foreach ($port in $ports) {
    $candidate = "http://$($ServerHost):$port"
    if (Test-Health -baseUrl $candidate -timeoutSec 2) {
      $baseUrl = $candidate
      break
    }
  }
  if ($baseUrl) { break }
  Start-Sleep -Seconds 1
  # Refresh last_server.json in case app just wrote it
  $last = Get-LastServerInfo
  if ($last -and $last.port -and ($ports -notcontains [int]$last.port)) { $ports = @([int]$last.port) + $ports }
}

if (-not $baseUrl) {
  Write-Warning "Health probe failed: app did not become healthy within $WaitSeconds seconds on ports: $($ports -join ',')"
} else {
  Write-Host "Health OK at $baseUrl/health" -ForegroundColor Green
  # Probe /blocked-accounts
  try {
    $resp = Invoke-WebRequest -Uri ($baseUrl.TrimEnd('/') + '/blocked-accounts') -UseBasicParsing -TimeoutSec 5
    if ($resp.StatusCode -eq 200) { Write-Host "/blocked-accounts OK" -ForegroundColor Green } else { Write-Warning "blocked-accounts status: $($resp.StatusCode)" }
  } catch { Write-Warning "blocked-accounts probe failed: $_" }
}

try { $null = $p.CloseMainWindow(); Start-Sleep 2 } catch {}
if ($p -and -not $p.HasExited) { try { Stop-Process -Id $p.Id -Force } catch {} }

Write-Host "Verification completed." -ForegroundColor Cyan
