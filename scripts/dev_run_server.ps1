$ErrorActionPreference = 'Stop'
$Env:APP_PORT = '8001'
$Env:LOG_LEVEL = 'INFO'
$Env:DISABLE_REDIS = '1'
# Use repo-root storage_state.json for source-run
$Env:STORAGE_STATE = 'storage_state.json'
Write-Host "Starting dev server on :$($Env:APP_PORT)" -ForegroundColor Cyan
Start-Process -FilePath "C:/Users/plogr/Desktop/Scrapper-Titan---Final/.venv/Scripts/python.exe" -ArgumentList "scripts/run_server.py" | Out-Null
Start-Sleep -Seconds 3
