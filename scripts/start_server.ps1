Param(
  [int]$Port = 8000
)

Write-Host "Starting FastAPI server on port $Port" -ForegroundColor Cyan
# Ensure virtual env active if exists
if (Test-Path .venv/Scripts/Activate.ps1) { . .venv/Scripts/Activate.ps1 }

uvicorn server.main:app --host 0.0.0.0 --port $Port --workers 1
