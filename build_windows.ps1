Param(
    [switch]$OneFile
)

$ErrorActionPreference = 'Stop'

Write-Host "==> Titan Scraper Desktop - Windows build" -ForegroundColor Cyan

# Ensure venv
if (!(Test-Path -Path ".venv")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    py -3 -m venv .venv
}

& .\.venv\Scripts\Activate.ps1

Write-Host "Installing Python dependencies..." -ForegroundColor Yellow
pip install --upgrade pip wheel setuptools
pip install -r requirements.txt
pip install -r .\desktop\requirements-desktop.txt
pip install pyinstaller==6.10.0 pillow==10.4.0

# Purge local persistence (SQLite + CSV) so packaged app ships with empty data
Write-Host "Purging local database & export artifacts (fallback.sqlite3, exports/*.csv)..." -ForegroundColor Yellow
Try {
    if (Test-Path .\fallback.sqlite3) { Remove-Item .\fallback.sqlite3 -Force }
    if (Test-Path .\runtime_state.json) { Remove-Item .\runtime_state.json -Force }
    if (Test-Path .\exports) {
        Get-ChildItem .\exports -Recurse -Include *.csv | ForEach-Object { Remove-Item $_.FullName -Force }
    }
    # Optional: clear session store posts cache (keep storage_state.json to avoid losing login unless explicitly removed)
    if (Test-Path .\session_store.json) { Remove-Item .\session_store.json -Force }
    Write-Host "Purge complete." -ForegroundColor DarkGreen
} Catch {
    Write-Warning "Purge encountered an issue: $_"
}

# Optional: prefetch Playwright Chromium into build/prebrowsers so MSI/EXE ships browser (faster first run)
$preBrowsers = Join-Path (Get-Location) 'build/prebrowsers'
if (!(Test-Path $preBrowsers)) { New-Item -ItemType Directory -Force -Path $preBrowsers | Out-Null }
$env:PLAYWRIGHT_BROWSERS_PATH = $preBrowsers
Write-Host "Prefetching Playwright Chromium into $preBrowsers (best effort)..." -ForegroundColor Yellow
python -m playwright install chromium --with-deps
if ($LASTEXITCODE -ne 0) { Write-Host "Playwright prefetch failed (continuing, will fallback to runtime install)" -ForegroundColor DarkYellow }

# Prepare build assets (icons)
New-Item -ItemType Directory -Force -Path .\build | Out-Null
if (Test-Path "Titan Scraper logo.png") {
    Write-Host "Generating Windows ICO from PNG..." -ForegroundColor Yellow
    python .\scripts\util_make_icon.py -i "Titan Scraper logo.png" -o .\build\icon.ico
}

# Fetch WebView2 evergreen bootstrapper (for first-run installation)
$wv2 = "./build/MicrosoftEdgeWebView2Setup.exe"
if (!(Test-Path $wv2)) {
    Write-Host "Downloading WebView2 bootstrapper..." -ForegroundColor Yellow
    $url = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"  # Evergreen Bootstrapper x64
    try {
        Invoke-WebRequest -Uri $url -OutFile $wv2 -UseBasicParsing
    } catch {
        Write-Warning "Failed to download WebView2 bootstrapper: $_"
    }
}

# Clean previous dist
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue .\dist
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue .\build\TitanScraper

$spec = ".\TitanScraper.spec"
if (-not (Test-Path $spec)) {
    if (Test-Path ".\desktop\pyinstaller.spec") { $spec = ".\desktop\pyinstaller.spec" }
    else { $spec = $null }
}
$extra = @()
if ($OneFile) { $extra += "--onefile" }

Write-Host "Running PyInstaller..." -ForegroundColor Cyan
if ($spec) {
    pyinstaller --noconfirm $spec @extra
    if ($LASTEXITCODE -ne 0) { Write-Error "PyInstaller failed with code $LASTEXITCODE"; exit $LASTEXITCODE }
}
else {
    Write-Host "Spec file not found. Building via direct entrypoint (desktop/main.py)." -ForegroundColor Yellow
    pyinstaller --noconfirm .\desktop\main.py --name TitanScraper @extra --noconsole --icon .\build\icon.ico --add-data "server/templates;server/templates"
    if ($LASTEXITCODE -ne 0) { Write-Error "PyInstaller adhoc build failed with code $LASTEXITCODE"; exit $LASTEXITCODE }
}

Write-Host "Build complete. Output in .\\dist\\TitanScraper" -ForegroundColor Green
