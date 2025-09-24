<#
.SYNOPSIS
  Demo launcher for LinkedIn scraper dashboard.

.DESCRIPTION
  1. Loads .env (key=value lines) into current PowerShell process
  2. Optionally overrides PLAYWRIGHT_MOCK_MODE via parameter
  3. Runs one one-off scrape job (scripts/run_once.py)
  4. Starts the FastAPI server (uvicorn) in the foreground
  5. Optionally opens the browser automatically

.PARAMETER Mock
  Force mock mode (1 or 0). If omitted uses value from .env

.PARAMETER Port
  HTTP port for the uvicorn server (default 8000)

.PARAMETER Host
  Host bind (default 0.0.0.0)

.PARAMETER Open
  If specified, opens the dashboard URL in default browser

.EXAMPLE
  ./scripts/demo_run.ps1 -Mock 1 -Open

.EXAMPLE
  ./scripts/demo_run.ps1 -Port 9000 -Open

.NOTES
  - Requires Python & dependencies already installed.
  - Does NOT daemonize uvicorn; Ctrl+C to stop.
  - .env lines starting with # or blank are ignored.
#>
[CmdletBinding()]
param(
  [Parameter(Position=0)][ValidateSet('0','1')]$Mock,
  [int]$Port = 8000,
  [string]$BindHost = '0.0.0.0',
  [switch]$Open
)

$ErrorActionPreference = 'Stop'

function Write-Info($msg) { Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Warn($msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Err($msg) { Write-Host "[ERR ] $msg" -ForegroundColor Red }

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

# Detect virtual environment python
$venvPython = Join-Path $repoRoot '.venv/Scripts/python.exe'
if (Test-Path $venvPython) {
  $Python = $venvPython
  Write-Info "Using virtual environment: $Python"
} else {
  $Python = 'python'
  Write-Warn "Virtual environment not found (.venv). Falling back to system python."
}

# 1. Load .env if present
$envFile = Join-Path $repoRoot '.env'
if (Test-Path $envFile) {
    Write-Info "Loading environment vars from .env"
  Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith('#')) { return }
    if ($line -match '^(.*?)=(.*)$') {
      $k = $matches[1].Trim(); $v = $matches[2].Trim()
      if (-not [string]::IsNullOrWhiteSpace($k)) {
        # Do not overwrite if already present in environment before script
        if (-not (Test-Path Env:$k)) {
          Set-Item -Path Env:$k -Value $v
        }
      }
    }
  }
} else {
    Write-Warn ".env not found. Continuing with existing environment."
}

# 2. Mock override
if ($PSBoundParameters.ContainsKey('Mock')) {
  Set-Item Env:PLAYWRIGHT_MOCK_MODE $Mock
  Write-Info "PLAYWRIGHT_MOCK_MODE forced to $Mock"
}

# 3. One-off population
Write-Info "Running one-off scrape job (mock=$($env:PLAYWRIGHT_MOCK_MODE))"
try {
  & $Python scripts/run_once.py | Write-Host
} catch {
    Write-Err "Failed running run_once.py: $_"; exit 1
}

# 4. Optionally open browser (before start to allow quick refresh once up)
$dashboardUrl = "http://localhost:$Port/"
if ($Open) {
    Write-Info "Will open browser at $dashboardUrl in a few seconds..."
    Start-Job -ScriptBlock { param($u) Start-Sleep -Seconds 3; Start-Process $u } -ArgumentList $dashboardUrl | Out-Null
}

# 5. Start uvicorn (foreground)
Write-Info ("Starting FastAPI (uvicorn) on {0}:{1}" -f $BindHost,$Port)
$cmd = "$Python -m uvicorn server.main:app --host $BindHost --port $Port"
if ($env:LOG_LEVEL -and $env:LOG_LEVEL.ToUpper() -eq 'DEBUG') { Write-Info "Command: $cmd" }

# Pass through stdout/stderr directly
& $Python -m uvicorn server.main:app --host $BindHost --port $Port

# When uvicorn exits
Write-Info "Uvicorn stopped."