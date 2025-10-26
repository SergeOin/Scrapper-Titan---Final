Param(
  [string]$Name = 'TitanScraperDesktop'
)

Write-Host "[build_desktop_exe] Creating desktop EXE ($Name)" -ForegroundColor Cyan
if (Test-Path .venv/Scripts/Activate.ps1) { . .venv/Scripts/Activate.ps1 }

pip install --upgrade pip > $null
pip install pyinstaller > $null
pip install -r requirements.txt > $null
pip install -r .\desktop\requirements-desktop.txt > $null

# Use existing spec (desktop/pyinstaller.spec) which already includes templates & assets
$spec = 'desktop/pyinstaller.spec'

# Pre-clean: stop any running TitanScraper.exe and remove previous dist folder to avoid file locks
try {
  Get-Process -Name 'TitanScraper' -ErrorAction SilentlyContinue | Stop-Process -Force
  Start-Sleep -Milliseconds 400
} catch { }
$prevDist = Join-Path 'dist' 'TitanScraper'
if(Test-Path $prevDist){
  try { Remove-Item -Recurse -Force $prevDist } catch { Write-Warning "Pre-clean: unable to remove $prevDist : $_" }
}

# Build one-folder (recommended for desktop so Playwright browser path works). Use --noconfirm --clean
$cmd = @('pyinstaller','--noconfirm','--clean', $spec)
Write-Host "[build_desktop_exe] Running: $($cmd -join ' ')"
& $cmd[0] $cmd[1..($cmd.Length-1)]
if($LASTEXITCODE -ne 0){ throw "PyInstaller failed ($LASTEXITCODE)" }

$distDir = Join-Path 'dist' 'TitanScraper'
if(!(Test-Path $distDir)){ throw "Expected dist/TitanScraper folder not found" }
Write-Host "[build_desktop_exe] Built folder app at $distDir" -ForegroundColor Green

# Copy bootstrapper for convenience
try {
  $bootstrap = Join-Path 'scripts' 'bootstrap_windows.ps1'
  if(Test-Path $bootstrap){
    Copy-Item -Force -Path $bootstrap -Destination (Join-Path $distDir 'Start-TitanScraper.ps1')
    Write-Host "[build_desktop_exe] Added Start-TitanScraper.ps1 to dist/TitanScraper" -ForegroundColor Green
  }
} catch { Write-Warning "Unable to copy bootstrapper: $_" }

# Optionally run a quick smoke test by launching and probing /health
try {
  Write-Host "[build_desktop_exe] Smoke test starting..." -ForegroundColor Yellow
  $exe = Join-Path $distDir 'TitanScraper.exe'
  if(!(Test-Path $exe)){ throw "Executable not found: $exe" }
  $p = Start-Process -FilePath $exe -PassThru
  # Give it a moment to start and write last_server.json
  Start-Sleep -Seconds 8
  $ud = Join-Path $env:LOCALAPPDATA 'TitanScraper'
  $srvInfo = Join-Path $ud 'last_server.json'
  $healthUrl = 'http://127.0.0.1:8000/health'
  if(Test-Path $srvInfo){
    try {
      $j = Get-Content $srvInfo -Raw | ConvertFrom-Json
      if($j.host -and $j.port){ $healthUrl = ('http://{0}:{1}/health' -f $j.host, $j.port) }
    } catch {}
  }
  try {
    $resp = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 4
    if($resp.StatusCode -eq 200){ Write-Host "[build_desktop_exe] Health OK ($healthUrl)" -ForegroundColor Green }
    else { Write-Warning "Health endpoint returned $($resp.StatusCode) ($healthUrl)" }
  } catch { Write-Warning "Unable to contact health endpoint ($healthUrl): $_" }
  try { Stop-Process -Id $p.Id -Force } catch {}
} catch { Write-Warning "Smoke test failed: $_" }
