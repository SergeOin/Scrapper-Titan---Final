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

# Build one-folder (recommended for desktop so Playwright browser path works). Use --noconfirm --clean
$cmd = @('pyinstaller','--noconfirm','--clean', $spec)
Write-Host "[build_desktop_exe] Running: $($cmd -join ' ')"
& $cmd[0] $cmd[1..($cmd.Length-1)]
if($LASTEXITCODE -ne 0){ throw "PyInstaller failed ($LASTEXITCODE)" }

$distDir = Join-Path 'dist' 'TitanScraper'
if(!(Test-Path $distDir)){ throw "Expected dist/TitanScraper folder not found" }
Write-Host "[build_desktop_exe] Built folder app at $distDir" -ForegroundColor Green

# Optionally run a quick smoke test by launching and probing /health
try {
  Write-Host "[build_desktop_exe] Smoke test starting..." -ForegroundColor Yellow
  $exe = Join-Path $distDir 'TitanScraper.exe'
  if(!(Test-Path $exe)){ throw "Executable not found: $exe" }
  $p = Start-Process -FilePath $exe -PassThru
  $maxWait = 12
  $elapsed = 0
  $healthOk = $false
  while($elapsed -lt $maxWait -and -not $healthOk){
    Start-Sleep -Seconds 2
    $elapsed += 2
    try {
      $resp = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/health' -UseBasicParsing -TimeoutSec 3
      if($resp.StatusCode -eq 200){
        Write-Host "[build_desktop_exe] Health OK after ${elapsed}s" -ForegroundColor Green
        $healthOk = $true
      }
    } catch {}
  }
  if(-not $healthOk){ Write-Warning "Health endpoint not reachable within ${maxWait}s (continuing build)" }
  try { Stop-Process -Id $p.Id -Force } catch {}
} catch { Write-Warning "Smoke test failed: $_" }
