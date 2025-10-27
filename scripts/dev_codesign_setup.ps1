<#!
.SYNOPSIS
  Creates a self-signed Code Signing certificate for development/testing, exports a .cer (public) and optionally a .pfx (with private key),
  and can install local trust so signed EXEs/MSIs validate on this machine.

.DESCRIPTION
  This is a FREE option for internal/dev scenarios. It will NOT build SmartScreen reputation and is not suitable for public distribution.
  For production releases, use a real commercial Code Signing certificate.

.PARAMETER Subject
  X.509 subject used for the certificate (e.g., 'CN=TitanScraper Dev').

.PARAMETER OutputDir
  Directory where .cer and .pfx will be written (default: dist/signing).

.PARAMETER ExportPfx
  When set, export a password-protected PFX containing the private key.

.PARAMETER PfxPassword
  Password for the exported PFX. If omitted and -ExportPfx is set, you'll be prompted.

.PARAMETER InstallTrust
  When set, installs the public certificate under CurrentUser Trusted Root and Trusted Publishers so Authenticode validation succeeds locally.

.EXAMPLE
  # Create cert, export CER+PFX, and install trust on this machine
  .\scripts\dev_codesign_setup.ps1 -ExportPfx -InstallTrust -Subject 'CN=TitanScraper Dev'

.EXAMPLE
  # Create cert and only export CER for distribution to teammates
  .\scripts\dev_codesign_setup.ps1 -Subject 'CN=TitanScraper Dev'
#>
[CmdletBinding(SupportsShouldProcess=$true)]
param(
  [string]$Subject = 'CN=TitanScraper Dev',
  [string]$OutputDir = (Join-Path (Split-Path $PSScriptRoot -Parent) 'dist/signing'),
  [switch]$ExportPfx,
  [securestring]$PfxPassword,
  [switch]$InstallTrust
)

$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

Write-Host "[dev-codesign] Creating self-signed Code Signing certificate..." -ForegroundColor Cyan
$notAfter = (Get-Date).AddYears(2)
$cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject $Subject -CertStoreLocation 'Cert:\CurrentUser\My' -KeyAlgorithm RSA -KeyLength 3072 -HashAlgorithm SHA256 -NotAfter $notAfter -FriendlyName ($Subject + ' Code Signing')

if(-not $cert){ throw 'Certificate creation failed.' }

# Export CER (public)
$cerPath = Join-Path $OutputDir 'dev-codesign.cer'
Export-Certificate -Cert $cert -FilePath $cerPath | Out-Null
Write-Host "[dev-codesign] Exported CER: $cerPath" -ForegroundColor Green

# Optionally export PFX (private)
$pfxPath = $null
if($ExportPfx){
  if(-not $PfxPassword){ try { $sec = Read-Host -AsSecureString -Prompt 'Enter PFX password'; } catch { $sec = $null } } else { $sec = $PfxPassword }
  if(-not $sec){ throw 'PFX password is required to export PFX.' }
  $pfxPath = Join-Path $OutputDir 'dev-codesign.pfx'
  Export-PfxCertificate -Cert $cert -FilePath $pfxPath -Password $sec -ChainOption BuildChain | Out-Null
  Write-Host "[dev-codesign] Exported PFX: $pfxPath" -ForegroundColor Green
}

# Optional: install trust into CurrentUser stores
if($InstallTrust){
  Write-Host '[dev-codesign] Installing trust to CurrentUser Root and TrustedPublisher...' -ForegroundColor Yellow
  $root = 'Cert:\CurrentUser\Root'
  $pub  = 'Cert:\CurrentUser\TrustedPublisher'
  Import-Certificate -FilePath $cerPath -CertStoreLocation $root | Out-Null
  Import-Certificate -FilePath $cerPath -CertStoreLocation $pub  | Out-Null
  Write-Host '[dev-codesign] Trust installed.' -ForegroundColor Green
}

# Output guidance
Write-Host "`n[dev-codesign] Thumbprint: $($cert.Thumbprint)" -ForegroundColor Cyan
Write-Host "[dev-codesign] Use with bootstrapper signing:" -ForegroundColor Cyan
Write-Host "  .\\scripts\\build_bootstrapper.ps1 -CertThumbprint '$($cert.Thumbprint)' -CertStoreLocation CurrentUser -CertStoreName My" -ForegroundColor Gray
if($pfxPath){ Write-Host "  or: .\\scripts\\build_bootstrapper.ps1 -SignPfxPath '$pfxPath' -SignPfxPassword '<your-password>'" -ForegroundColor Gray }

Write-Host '[dev-codesign] Done.' -ForegroundColor Green
