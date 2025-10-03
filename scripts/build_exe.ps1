Param(
  [string]$Name = 'Titan Scraper',
  [string]$Slug = '',
  [ValidateSet('server','desktop')][string]$Mode = 'desktop',
  [switch]$Console,
  [switch]$NoPlaywright,
  [switch]$KillPrevious
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

# Derive a filesystem-safe slug for build artifacts (e.g. TitanScraper)
if(-not $Slug -or $Slug.Trim() -eq ''){
  $Slug = ($Name -replace '[^A-Za-z0-9]', '')
  if(-not $Slug){ $Slug = 'TitanScraper' }
}

if($Mode -eq 'desktop'){
  Write-Host "[build_exe] Mode=desktop (desktop/main.py entrypoint)" -ForegroundColor Yellow
  $entry = 'desktop/main.py'
  # Hidden imports needed when freezing from desktop layer
  $hidden = @('--hidden-import','server.main','--hidden-import','scraper.bootstrap')
} else {
  Write-Host "[build_exe] Mode=server (scripts/run_server.py entrypoint)" -ForegroundColor Yellow
  $entry = 'scripts/run_server.py'
  $hidden = @('--hidden-import','server.main','--hidden-import','scraper.bootstrap')
}

# Build EXE (GUI app by default; pass -Console switch to keep terminal visible)
$cmd = @('pyinstaller','--noconfirm','--clean','--name', $Slug,'--onefile','--icon','build/icon.ico','--paths','.')
if(-not $Console){ $cmd += '--windowed' }

# Desktop mode may require ensuring playwright browsers path exists locally (optional optimization)
if($Mode -eq 'desktop' -and -not $NoPlaywright){
  $pwDir = Join-Path $env:LOCALAPPDATA 'TitanScraper\\pw-browsers'
  if(!(Test-Path $pwDir)){ New-Item -ItemType Directory -Force -Path $pwDir | Out-Null }
  $env:PLAYWRIGHT_BROWSERS_PATH = $pwDir
  Write-Host "[build_exe] PLAYWRIGHT_BROWSERS_PATH=$pwDir" -ForegroundColor DarkCyan
}

$cmd += $hidden + $addData + @($entry)
Write-Host "[build_exe] Running: $($cmd -join ' ')"
& $cmd[0] $cmd[1..($cmd.Length-1)]

if($LASTEXITCODE -ne 0){ throw "PyInstaller failed ($LASTEXITCODE)" }

$slugExe = Join-Path 'dist' ("{0}.exe" -f $Slug)
if(!(Test-Path $slugExe)){ throw "EXE not found: $slugExe" }

$finalExe = Join-Path 'dist' ("{0}.exe" -f $Name)
if($KillPrevious){
  Write-Host "[build_exe] Attempting to terminate existing processes..." -ForegroundColor DarkYellow
  $procNames = @('TitanScraper','Titan Scraper')
  foreach($pn in $procNames){
    Get-Process -Name $pn -ErrorAction SilentlyContinue | ForEach-Object {
      try { Stop-Process -Id $_.Id -Force -ErrorAction Stop; Write-Host "  - Killed PID=$($_.Id) ($pn)" -ForegroundColor DarkYellow } catch { }
    }
  }
  Start-Sleep -Milliseconds 350
}

$renamed = $false
if(Test-Path $finalExe){
  try {
    Remove-Item $finalExe -Force -ErrorAction Stop
  } catch {
    Write-Host "[build_exe] WARN: could not remove existing '$finalExe' (locked) -- will keep slug exe as fallback" -ForegroundColor Red
  }
}
if(-not (Test-Path $finalExe)){
  try {
    Move-Item $slugExe $finalExe -ErrorAction Stop
    $renamed = $true
  } catch {
    Write-Host "[build_exe] WARN: rename failed ($_)" -ForegroundColor Red
  }
}
if(-not $renamed){
  # Keep the slug exe; also copy to a _new variant to make it obvious
  $alt = Join-Path 'dist' ("{0}_new.exe" -f $Slug)
  try { Copy-Item $slugExe $alt -Force } catch { }
  Write-Host "[build_exe] Fallback executables:" -ForegroundColor Yellow
  Write-Host "  - Slug:   $slugExe" -ForegroundColor Yellow
  if(Test-Path $alt){ Write-Host "  - Copy :  $alt" -ForegroundColor Yellow }
  if(Test-Path $finalExe){ Write-Host "  - Old  : $finalExe (locked?)" -ForegroundColor Yellow }
} else {
  Write-Host "[build_exe] Built: $finalExe" -ForegroundColor Green
}
Write-Host "[build_exe] Launch test suggestion: '& \"$slugExe\"' (uses latest bits)" -ForegroundColor DarkCyan
