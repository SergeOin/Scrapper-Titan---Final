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

# Optional: ensure Playwright browsers fetched at build time (makes first run smoother)
Write-Host "Ensuring Playwright Chromium is available (best effort)..." -ForegroundColor Yellow
python -m playwright install chromium --with-deps
if ($LASTEXITCODE -ne 0) { Write-Host "Playwright install skipped or failed (non-fatal)" -ForegroundColor DarkYellow }

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

$spec = ".\desktop\pyinstaller.spec"
$extra = ""
if ($OneFile) { $extra = "--onefile" }

Write-Host "Running PyInstaller..." -ForegroundColor Cyan
pyinstaller $spec $extra
if ($LASTEXITCODE -ne 0) { Write-Error "PyInstaller failed with code $LASTEXITCODE"; exit $LASTEXITCODE }

Write-Host "Build complete. Output in .\\dist\\TitanScraper" -ForegroundColor Green
