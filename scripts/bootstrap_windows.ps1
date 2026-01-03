# Windows bootstrapper for TitanScraper Desktop
# - Ensures WebView2 Runtime
# - Ensures Playwright Chromium installed to user dir
# - Prepares data directories and storage_state path
# - Starts TitanScraper.exe

$ErrorActionPreference = 'Stop'

function Get-LocalDataDir { Join-Path $Env:LOCALAPPDATA 'TitanScraper' }
function Get-ExePath {
  $p1 = Join-Path (Join-Path $PSScriptRoot '..\dist\TitanScraper') 'TitanScraper.exe'
  $p2 = Join-Path (Join-Path $PSScriptRoot 'dist\TitanScraper') 'TitanScraper.exe'
  if(Test-Path $p1){ return $p1 }
  if(Test-Path $p2){ return $p2 }
  throw "TitanScraper.exe introuvable sous dist/TitanScraper"
}

# Ensure user-writable runtime dirs
$ud = Get-LocalDataDir
$null = New-Item -ItemType Directory -Force -Path $ud | Out-Null
$null = New-Item -ItemType Directory -Force -Path (Join-Path $ud 'logs') | Out-Null
$null = New-Item -ItemType Directory -Force -Path (Join-Path $ud 'exports') | Out-Null
$null = New-Item -ItemType Directory -Force -Path (Join-Path $ud 'screenshots') | Out-Null
$null = New-Item -ItemType Directory -Force -Path (Join-Path $ud 'traces') | Out-Null

# Set env vars used by desktop/main.py
$Env:APP_HOST = '127.0.0.1'
$Env:LOG_LEVEL = 'INFO'
$Env:LOG_FILE = (Join-Path $ud 'logs\server.log')
$Env:DISABLE_REDIS = '1'
$Env:SQLITE_PATH = (Join-Path $ud 'fallback.sqlite3')
$Env:STORAGE_STATE = (Join-Path $ud 'storage_state.json')
$Env:SESSION_STORE_PATH = (Join-Path $ud 'session_store.json')
$Env:PLAYWRIGHT_BROWSERS_PATH = (Join-Path $ud 'pw-browsers')

# Ensure WebView2 Runtime (if missing). Silent install best-effort
function Ensure-WebView2 {
  try {
    $key = 'HKLM:SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients'
    $has = Get-ChildItem $key -ErrorAction Stop | Where-Object { $_.PSChildName -match 'WebView2' }
    if($has){ return }
  } catch { }
  Write-Host 'Installing WebView2 Runtime (silent)...' -ForegroundColor Yellow
  $tmp = New-TemporaryFile
  Remove-Item $tmp -Force
  $tmp = [System.IO.Path]::Combine([System.IO.Path]::GetTempPath(),'MicrosoftEdgeWebview2Setup.exe')
  Invoke-WebRequest -Uri 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile $tmp -UseBasicParsing -TimeoutSec 120
  Start-Process -FilePath $tmp -ArgumentList '/silent','/install' -Wait
}

# Ensure Playwright browsers
function Ensure-Playwright {
  try {
    if (Test-Path $Env:PLAYWRIGHT_BROWSERS_PATH) {
      $chrom = Get-ChildItem -Recurse -Directory -Path $Env:PLAYWRIGHT_BROWSERS_PATH -ErrorAction SilentlyContinue | Where-Object { $_.Name -match 'chromium' } | Select-Object -First 1
      if ($chrom) { return }
    }
  } catch { }
  Write-Host 'Installing Playwright Chromium...' -ForegroundColor Yellow
  $py = (Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe')
  if (!(Test-Path $py)) { $py = 'python' }
  & $py -m playwright install chromium
}

# Optionally copy a storage_state.json if provided next to script (first time convenience)
$repoSS = Join-Path $PSScriptRoot '..\storage_state.json'
if ((Test-Path $repoSS) -and (-not (Test-Path $Env:STORAGE_STATE))) {
  Copy-Item -Path $repoSS -Destination $Env:STORAGE_STATE -Force
}

Ensure-WebView2
Ensure-Playwright

# Start the app
$exe = Get-ExePath
Write-Host "Launching: $exe" -ForegroundColor Cyan
Start-Process -FilePath $exe
