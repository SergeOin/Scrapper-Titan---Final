Param(
  [string]$Name = 'TitanScraperDashboard'
)

Write-Host "[build_exe] Creating single-file EXE ($Name)" -ForegroundColor Cyan
if (Test-Path .venv/Scripts/Activate.ps1) { . .venv/Scripts/Activate.ps1 }

# Ensure tools
pip install --upgrade pip > $null
pip install pyinstaller > $null
# App deps (in case not installed)
pip install -r requirements.txt > $null

# Include Jinja templates (and any other app data) into the bundle
$addData = @()
if(Test-Path 'server/templates'){
  $addData += "--add-data"
  $addData += "server/templates;server/templates"
}

# Build EXE (console app)
$cmd = @('pyinstaller','--noconfirm','--clean','--name', $Name,'--onefile') + $addData + @('scripts/run_server.py')
Write-Host "[build_exe] Running: $($cmd -join ' ')"
& $cmd[0] $cmd[1..($cmd.Length-1)]

if($LASTEXITCODE -ne 0){ throw "PyInstaller failed ($LASTEXITCODE)" }

$exe = Join-Path 'dist' ("{0}.exe" -f $Name)
if(!(Test-Path $exe)){ throw "EXE not found: $exe" }
Write-Host "[build_exe] Built: $exe" -ForegroundColor Green
