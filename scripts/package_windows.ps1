Param(
  [string]$Version = '',
  [switch]$OneFile,
  [switch]$PerMachine,
  [switch]$NoEmbedCab,
  # Signing (forwarded to build_desktop_msi.ps1)
  [string]$SignPfxPath,
  [string]$SignPfxPassword,
  [string]$CertThumbprint,
  [ValidateSet('CurrentUser','LocalMachine')][string]$CertStoreLocation = 'CurrentUser',
  [string]$CertStoreName = 'My',
  [switch]$AutoPickCert,
  [string]$CertSubjectFilter,
  # Burn bootstrapper
  [switch]$WithBootstrapper
)

$ErrorActionPreference = 'Stop'

Write-Host "==> Packaging Titan Scraper for Windows" -ForegroundColor Cyan

if([string]::IsNullOrWhiteSpace($Version)){
  if(Test-Path .\VERSION){ try { $Version = (Get-Content .\VERSION -Raw).Trim() } catch { $Version = '1.0.0' } } else { $Version = '1.0.0' }
}

# 1) Build app bundle (one-folder recommended for MSI)
Write-Host "Building desktop app (PyInstaller)" -ForegroundColor Yellow
& .\build_windows.ps1 -OneFile:$OneFile

# 2) Build MSI from dist folder with robust harvesting script
if (!(Test-Path .\dist\TitanScraper)){
  # One-file fallback: if we only have dist/TitanScraper.exe, stage a folder for MSI harvest
  $oneFilePath = Join-Path (Get-Location) 'dist/TitanScraper.exe'
  if (Test-Path $oneFilePath) {
    Write-Host "Staging one-file EXE into dist/TitanScraper for MSI..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Force -Path .\dist\TitanScraper | Out-Null
    Copy-Item $oneFilePath .\dist\TitanScraper\TitanScraper.exe -Force
    # Copy WebView2 bootstrapper if available to improve first-run experience
    if (Test-Path .\build\MicrosoftEdgeWebView2Setup.exe) {
      Copy-Item .\build\MicrosoftEdgeWebView2Setup.exe .\dist\TitanScraper\MicrosoftEdgeWebView2Setup.exe -Force
    }
    # If frontend was built, copy it so server can serve /blocked from exe_dir
    if (Test-Path .\web\blocked\dist) {
      New-Item -ItemType Directory -Force -Path .\dist\TitanScraper\web\blocked | Out-Null
      Copy-Item .\web\blocked\dist -Destination .\dist\TitanScraper\web\blocked -Recurse -Force
    }
  } else {
    Write-Error "dist/TitanScraper missing and no dist/TitanScraper.exe found."; exit 1
  }
}


# Build named parameter map (hashtable splatting) for Windows PowerShell 5.1 compatibility
$msiParams = @{}
if($PerMachine){ $msiParams['PerMachine'] = $true }
if($NoEmbedCab){ $msiParams['NoEmbedCab'] = $true }
if($SignPfxPath){ $msiParams['SignPfxPath'] = $SignPfxPath }
if($SignPfxPassword){ $msiParams['SignPfxPassword'] = $SignPfxPassword }
if($CertThumbprint){ $msiParams['CertThumbprint'] = $CertThumbprint }
if($CertStoreLocation){ $msiParams['CertStoreLocation'] = $CertStoreLocation }
if($CertStoreName){ $msiParams['CertStoreName'] = $CertStoreName }
if($AutoPickCert){ $msiParams['AutoPickCert'] = $true }
if($CertSubjectFilter){ $msiParams['CertSubjectFilter'] = $CertSubjectFilter }

Write-Host "Building MSI (WiX)..." -ForegroundColor Yellow
& .\scripts\build_desktop_msi.ps1 @msiParams

Write-Host "Windows package ready in dist/msi" -ForegroundColor Green

# 3) Optional: Build Burn-based bootstrapper (bundles prerequisites + MSI)
if($WithBootstrapper){
  Write-Host "Building Bootstrapper (Burn)..." -ForegroundColor Cyan
  $bbParams = @{'PerMachine'=$PerMachine}
  if($SignPfxPath){ $bbParams['SignPfxPath'] = $SignPfxPath }
  if($SignPfxPassword){ $bbParams['SignPfxPassword'] = $SignPfxPassword }
  if($CertThumbprint){ $bbParams['CertThumbprint'] = $CertThumbprint }
  if($CertStoreLocation){ $bbParams['CertStoreLocation'] = $CertStoreLocation }
  if($CertStoreName){ $bbParams['CertStoreName'] = $CertStoreName }
  if($AutoPickCert){ $bbParams['AutoPickCert'] = $true }
  if($CertSubjectFilter){ $bbParams['CertSubjectFilter'] = $CertSubjectFilter }
  & .\scripts\build_bootstrapper.ps1 @bbParams
}
