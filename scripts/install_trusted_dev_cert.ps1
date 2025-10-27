<#!
.SYNOPSIS
  Installs a public .cer (self-signed dev certificate) into CurrentUser Trusted Root and Trusted Publishers,
  making locally signed EXE/MSI validate on this machine.

.DESCRIPTION
  Use this on machines that should trust binaries signed with your self-signed dev certificate.
  For production/public distribution, use a real commercial Code Signing certificate instead.

.PARAMETER CerPath
  Path to the .cer file exported by dev_codesign_setup.ps1.

.EXAMPLE
  .\scripts\install_trusted_dev_cert.ps1 -CerPath C:\path\to\dev-codesign.cer
#>
[CmdletBinding(SupportsShouldProcess=$true)]
param(
  [Parameter(Mandatory=$true)][string]$CerPath
)
$ErrorActionPreference = 'Stop'
if(!(Test-Path $CerPath)){ throw "CER non trouvé: $CerPath" }

Write-Host "[dev-codesign] Installing trust for $CerPath" -ForegroundColor Yellow
$root = 'Cert:\CurrentUser\Root'
$pub  = 'Cert:\CurrentUser\TrustedPublisher'
Import-Certificate -FilePath $CerPath -CertStoreLocation $root | Out-Null
Import-Certificate -FilePath $CerPath -CertStoreLocation $pub  | Out-Null
Write-Host '[dev-codesign] Trust installed.' -ForegroundColor Green
