Write-Host "Starting scraper worker" -ForegroundColor Cyan
if (Test-Path .venv/Scripts/Activate.ps1) { . .venv/Scripts/Activate.ps1 }
python -m scraper.worker
