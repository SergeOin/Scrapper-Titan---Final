Param(
  # Rebuild steps
  [switch]$SkipExe,
  [switch]$SkipMsi,
  [switch]$SkipBootstrapper,

  # MSI options (forwarded)
  [switch]$Aggressive,
  [switch]$SkipPrune,
  [switch]$KeepTzData,
  [switch]$PerMachine,
  [switch]$NoEmbedCab,

  # Signing options (forwarded)
  [string]$SignPfxPath,
  [string]$SignPfxPassword,
  [string]$TimestampUrl = 'http://timestamp.digicert.com',
  [string]$CertThumbprint,
  [ValidateSet('CurrentUser','LocalMachine')][string]$CertStoreLocation = 'CurrentUser',
  [string]$CertStoreName = 'My',
  [switch]$AutoPickCert,
  [string]$CertSubjectFilter
)

$ErrorActionPreference = 'Stop'

$root = (Join-Path $PSScriptRoot '..')
Set-Location $root

function Invoke-Step {
  param(
    [string]$Title,
    [scriptblock]$Action
  )
  Write-Host "== $Title ==" -ForegroundColor Cyan
  & $Action
}

if(-not $SkipExe){
  Invoke-Step -Title 'Build desktop EXE (PyInstaller)' -Action {
    & (Join-Path $root 'scripts/build_desktop_exe.ps1')
  }
}

$msiPath = $null
if(-not $SkipMsi){
  Invoke-Step -Title 'Build MSI' -Action {
    $msiSplat = @{}
    if($Aggressive){ $msiSplat.Aggressive = $true }
    if($SkipPrune){ $msiSplat.SkipPrune = $true }
    if($KeepTzData){ $msiSplat.KeepTzData = $true }
    if($PerMachine){ $msiSplat.PerMachine = $true }
    if($NoEmbedCab){ $msiSplat.NoEmbedCab = $true }

    if($SignPfxPath){ $msiSplat.SignPfxPath = $SignPfxPath }
    if($SignPfxPassword){ $msiSplat.SignPfxPassword = $SignPfxPassword }
    if($TimestampUrl){ $msiSplat.TimestampUrl = $TimestampUrl }

    # Ne forwarder les paramètres de store/cert que si une signature est réellement demandée
    if($CertThumbprint){
      $msiSplat.CertThumbprint = $CertThumbprint
      $msiSplat.CertStoreLocation = $CertStoreLocation
      $msiSplat.CertStoreName = $CertStoreName
    }
    if($AutoPickCert){
      $msiSplat.AutoPickCert = $true
      $msiSplat.CertStoreLocation = $CertStoreLocation
      $msiSplat.CertStoreName = $CertStoreName
    }
    if($CertSubjectFilter){ $msiSplat.CertSubjectFilter = $CertSubjectFilter }

    & (Join-Path $root 'scripts/build_desktop_msi.ps1') @msiSplat
  }

  # Pick the most recent "-folder-*.msi" built in dist/msi
  $msiDir = Join-Path $root 'dist/msi'
  $msiCandidate = Get-ChildItem -Path $msiDir -Filter '*-folder-*.msi' -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

  if(-not $msiCandidate){
    throw "MSI introuvable dans $msiDir après build (pattern: *-folder-*.msi)"
  }

  $msiPath = $msiCandidate.FullName
  Write-Host "MSI sélectionné: $msiPath" -ForegroundColor DarkGreen
}

if(-not $SkipBootstrapper){
  Invoke-Step -Title 'Build bootstrapper (Burn)' -Action {
    $bootSplat = @{}
    if($PerMachine){ $bootSplat.PerMachine = $true }
    if($msiPath){ $bootSplat.MsiPath = $msiPath }

    if($SignPfxPath){ $bootSplat.SignPfxPath = $SignPfxPath }
    if($SignPfxPassword){ $bootSplat.SignPfxPassword = $SignPfxPassword }

    if($CertThumbprint){
      $bootSplat.CertThumbprint = $CertThumbprint
      $bootSplat.CertStoreLocation = $CertStoreLocation
      $bootSplat.CertStoreName = $CertStoreName
    }
    if($AutoPickCert){
      $bootSplat.AutoPickCert = $true
      $bootSplat.CertStoreLocation = $CertStoreLocation
      $bootSplat.CertStoreName = $CertStoreName
    }
    if($CertSubjectFilter){ $bootSplat.CertSubjectFilter = $CertSubjectFilter }

    & (Join-Path $root 'scripts/build_bootstrapper.ps1') @bootSplat
  }
}

Write-Host "Terminé. Artefacts dans: $(Join-Path $root 'dist/msi')" -ForegroundColor Green
