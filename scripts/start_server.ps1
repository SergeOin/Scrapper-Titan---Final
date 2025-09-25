Param(
  [int]$Port = 8002,
  [switch]$Headless
)

Write-Host "Starting FastAPI server on port $Port (Headless: $($Headless.IsPresent))" -ForegroundColor Cyan
# Ensure virtual env active if exists
if (Test-Path .venv/Scripts/Activate.ps1) { . .venv/Scripts/Activate.ps1 }

# Prefer Python wrapper that enforces Windows Selector event loop policy before Uvicorn starts
$env:PORT = "$Port"
if ($Headless.IsPresent) { $env:PLAYWRIGHT_HEADLESS = "1" } else { $env:PLAYWRIGHT_HEADLESS = "0" }

python scripts/run_server.py
