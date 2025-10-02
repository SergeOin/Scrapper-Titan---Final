Param(
  [string]$Name = 'TitanScraper',
  [switch]$OneDir
)

Write-Host "[build_exe] Creating desktop build ($Name)" -ForegroundColor Cyan
if (Test-Path .venv/Scripts/Activate.ps1) { . .venv/Scripts/Activate.ps1 }

# Ensure tools
pip install --upgrade pip > $null
pip install pyinstaller > $null
# App deps (in case not installed)
pip install -r requirements.txt > $null
# Desktop wrapper extra deps (pywebview, requests)
if(Test-Path 'desktop/requirements-desktop.txt'){
  pip install -r desktop/requirements-desktop.txt > $null
}

# Configure build mode for spec
$prevOneFile = $env:TS_ONEFILE
$prevBuildName = $env:TS_BUILD_NAME
try {
  if($OneDir.IsPresent){
    $env:TS_ONEFILE = '0'
    Write-Host "[build_exe] Mode: one-dir" -ForegroundColor Yellow
  } else {
    $env:TS_ONEFILE = '1'
    Write-Host "[build_exe] Mode: one-file" -ForegroundColor Yellow
  }
  $env:TS_BUILD_NAME = $Name

  $cmd = @('pyinstaller','--noconfirm','--clean','desktop/pyinstaller.spec')
  Write-Host "[build_exe] Running: $($cmd -join ' ')"
  & $cmd[0] $cmd[1..($cmd.Length-1)]
} finally {
  if($null -ne $prevOneFile){ $env:TS_ONEFILE = $prevOneFile } else { Remove-Item Env:TS_ONEFILE -ErrorAction SilentlyContinue }
  if($null -ne $prevBuildName){ $env:TS_BUILD_NAME = $prevBuildName } else { Remove-Item Env:TS_BUILD_NAME -ErrorAction SilentlyContinue }
}

if($LASTEXITCODE -ne 0){ throw "PyInstaller failed ($LASTEXITCODE)" }

$exe = Join-Path 'dist' ("{0}.exe" -f $Name)
if(!(Test-Path $exe)){ throw "EXE not found: $exe" }
Write-Host "[build_exe] Built: $exe" -ForegroundColor Green
