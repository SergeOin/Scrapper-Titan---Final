<#!
.SYNOPSIS
 Installs TitanScraper as a Windows service using sc.exe.
.DESCRIPTION
 Assumes a PyInstaller-built exe (TitanScraper.exe) or python source environment.
 If EXE_PATH not supplied, attempts to locate TitanScraper.exe relative to script.
.PARAMETER ServiceName
 Name of the Windows service (default TitanScraper).
.PARAMETER DisplayName
 Display name (default Titan Scraper Service).
.PARAMETER ExePath
 Full path to executable. If omitted, auto-detects in ../build or current folder.
.PARAMETER WorkingDir
 Working directory for the service process (used for logs & relative paths).
.EXAMPLE
 .\windows_service_install.ps1 -ExePath C:\Apps\TitanScraper\TitanScraper.exe
#>
param(
    [string]$ServiceName = 'TitanScraper',
    [string]$DisplayName = 'Titan Scraper Service',
    [string]$ExePath,
    [string]$WorkingDir
)

Write-Host "[service-install] Starting install for $ServiceName" -ForegroundColor Cyan

if (-not $ExePath) {
    $candidate1 = Join-Path $PSScriptRoot '..\build\TitanScraper\TitanScraper.exe'
    $candidate2 = Join-Path $PSScriptRoot '..\dist\TitanScraper.exe'
    $candidate3 = Join-Path (Get-Location) 'TitanScraper.exe'
    foreach ($c in @($candidate1,$candidate2,$candidate3)) { if (Test-Path $c) { $ExePath = (Resolve-Path $c).Path; break } }
}
if (-not $ExePath) { throw 'Could not auto-detect TitanScraper executable. Provide -ExePath.' }
if (-not (Test-Path $ExePath)) { throw "Executable not found: $ExePath" }

if (-not $WorkingDir) { $WorkingDir = Split-Path $ExePath -Parent }
$binQuoted = '"' + $ExePath + '"'

# Create service
Write-Host "[service-install] Creating service pointing to $ExePath" -ForegroundColor Yellow
& sc.exe create $ServiceName binPath= $binQuoted start= auto DisplayName= "$DisplayName" | Write-Host

# Set working dir via registry ImagePath hack if needed (sc doesn't let us set cwd). Alternative: wrap with cmd /c "cd /d dir && exe"
$wrapper = "cmd /c cd /d `"$WorkingDir`" && $binQuoted"
& sc.exe config $ServiceName binPath= "$wrapper" | Write-Host

# Description
& sc.exe description $ServiceName "Titan Scraper headless service (server + worker)." | Write-Host

# Allow service to interact with desktop? Not needed. Logon stays LocalSystem unless changed.

# Start service
Write-Host "[service-install] Starting service" -ForegroundColor Yellow
& sc.exe start $ServiceName | Write-Host

Write-Host "[service-install] Done." -ForegroundColor Green
