<#
.SYNOPSIS
  End-to-end smoke test for the dashboard and blocked accounts API.

.DESCRIPTION
  - Temporarily avoids loading .env (pydantic strict parsing) by renaming it if present
  - Starts the FastAPI server (mock mode, no Mongo/Redis) on a test port
  - Waits until /health responds
  - Exercises /blocked-accounts endpoints: list, add, count, delete
  - Optionally checks /blocked HTML
  - Stops the server process

.PARAMETER Port
  HTTP port to bind (default 8050)

.PARAMETER Host
  Host bind (default 127.0.0.1)

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts/smoke_e2e.ps1 -Port 8050
#>
[CmdletBinding()]
param(
  [int]$Port = 8050,
  [string]$BindHost = '127.0.0.1'
)

$ErrorActionPreference = 'Stop'

function Write-Info($msg) { Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Warn($msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Err($msg) { Write-Host "[ERR ] $msg" -ForegroundColor Red }

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

# Detect venv python
$venvPy = Join-Path $repoRoot '.venv/Scripts/python.exe'
if (Test-Path $venvPy) { $Python = $venvPy } else { $Python = 'python' }

# Avoid .env parsing issues during smoke
$renamedEnv = $false
if (Test-Path '.env') {
  try {
    Rename-Item -LiteralPath '.env' -NewName '.env.testbak' -Force
    $renamedEnv = $true
    Write-Warn "Temporarily renamed .env -> .env.testbak for the test run"
  } catch {
    Write-Warn "Could not rename .env (continuing): $_"
  }
}

try {
  # Isolate env for the child process
  $env:PLAYWRIGHT_MOCK_MODE = '1'
  $env:DISABLE_MONGO = '1'
  $env:DISABLE_REDIS = '1'
  $env:APP_HOST = $BindHost
  $env:APP_PORT = "$Port"
  $env:LOG_LEVEL = 'info'
  $env:DASHBOARD_PUBLIC = '1'
  $env:INPROCESS_AUTONOMOUS = '0'

  Write-Info "Starting server on ${BindHost}:${Port} (mock mode)"
  $startInfo = New-Object System.Diagnostics.ProcessStartInfo
  $startInfo.FileName = $Python
  $startInfo.Arguments = 'scripts/run_server.py'
  $startInfo.WorkingDirectory = $repoRoot
  $startInfo.UseShellExecute = $false
  $startInfo.RedirectStandardOutput = $true
  $startInfo.RedirectStandardError = $true
  # Inherit current environment
  foreach ($k in [System.Environment]::GetEnvironmentVariables().Keys) { }
  $proc = New-Object System.Diagnostics.Process
  $proc.StartInfo = $startInfo
  $null = $proc.Start()

  # Async read (non-blocking)
  Start-Job -ScriptBlock { param($p) while (-not $p.HasExited) { try { $line = $p.StandardOutput.ReadLine(); if ($line) { Write-Host $line } } catch { break } } } -ArgumentList $proc | Out-Null
  Start-Job -ScriptBlock { param($p) while (-not $p.HasExited) { try { $line = $p.StandardError.ReadLine(); if ($line) { Write-Host $line -ForegroundColor DarkGray } } catch { break } } } -ArgumentList $proc | Out-Null

  # Wait for /health
  $base = "http://${BindHost}:${Port}"
  $healthUrl = "$base/health"
  $ok = $false
  for ($i=0; $i -lt 30; $i++) {
    try {
      $h = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 3
      if ($h.status -eq 'ok') { $ok = $true; break }
    } catch { Start-Sleep -Seconds 1 }
  }
  if (-not $ok) { throw "Server did not become healthy at $healthUrl" }
  Write-Info "Health OK"

  # Exercise blocked accounts API
  $list1 = Invoke-RestMethod -Uri "$base/blocked-accounts" -Method GET
  $count1 = Invoke-RestMethod -Uri "$base/blocked-accounts/count" -Method GET
  Write-Info ("Initial blocked: {0} (count endpoint={1})" -f $list1.items.Count, $count1.count)

  $payload = @{ url = 'linkedin.com/in/smoke-test-user' } | ConvertTo-Json
  $add = Invoke-RestMethod -Uri "$base/blocked-accounts" -Method POST -ContentType 'application/json' -Body $payload
  if (-not $add.ok) { throw "Add blocked account failed" }
  $newId = $add.item.id
  Write-Info "Added blocked item id=$newId url=$($add.item.url)"

  $count2 = Invoke-RestMethod -Uri "$base/blocked-accounts/count" -Method GET
  if ($count2.count -lt (($count1.count | ForEach-Object { $_ }) + 1)) { throw "Blocked count did not increase" }
  Write-Info "Count after add: $($count2.count)"

  $del = Invoke-RestMethod -Uri "$base/blocked-accounts/$newId" -Method DELETE
  if (-not $del.ok) { throw "Delete blocked account failed" }
  $count3 = Invoke-RestMethod -Uri "$base/blocked-accounts/count" -Method GET
  Write-Info "Count after delete: $($count3.count)"

  # Optional: check /blocked HTML delivers content (will show fallback if not built)
  try {
    $blockedHtml = Invoke-WebRequest -Uri "$base/blocked" -TimeoutSec 5
    if ($blockedHtml.StatusCode -eq 200) { Write-Info "/blocked responded 200 (${($blockedHtml.Content.Length)} bytes)" }
  } catch { Write-Warn "/blocked check failed: $_" }

  Write-Host "\n=== Smoke E2E PASSED ===" -ForegroundColor Green
}
catch {
  Write-Err $_
  Write-Host "\n=== Smoke E2E FAILED ===" -ForegroundColor Red
}
finally {
  # Stop server process if running
  if ($proc -and -not $proc.HasExited) {
    try { $proc.Kill() } catch {}
  }
  # Restore .env if we renamed it
  if ($renamedEnv -and (Test-Path '.env.testbak')) {
    try { Rename-Item -LiteralPath '.env.testbak' -NewName '.env' -Force; Write-Info "Restored .env" } catch { Write-Warn "Failed to restore .env: $_" }
  }
}
