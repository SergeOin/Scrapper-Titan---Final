Param(
  [string]$ArtifactsDir = (Join-Path (Split-Path $PSScriptRoot -Parent) 'dist\msi'),
  [string]$SignPfxPath,
  [securestring]$SignPfxPasswordSecure,
  [string]$CertThumbprint,
  [ValidateSet('CurrentUser','LocalMachine')][string]$CertStoreLocation = 'CurrentUser',
  [string]$CertStoreName = 'My',
  [switch]$AutoPickCert,
  [string]$CertSubjectFilter
)

$ErrorActionPreference = 'Stop'

function Resolve-SignTool {
  $st = Get-Command signtool.exe -ErrorAction SilentlyContinue
  if($st){ return $st.Path }
  $kitsRoot = 'C:\Program Files (x86)\Windows Kits\10\bin'
  if(Test-Path $kitsRoot){
    $candidates = Get-ChildItem -Path $kitsRoot -Directory -Recurse -ErrorAction SilentlyContinue | Sort-Object FullName -Descending
    foreach($c in $candidates){
      foreach($sub in @('x64','x86','arm64')){
        $p = Join-Path $c.FullName "$sub\signtool.exe"
        if(Test-Path $p){ return $p }
      }
    }
  }
  throw 'signtool.exe introuvable. Installez Windows SDK.'
}

function Convert-ToPlainText {
  param([securestring]$Secure)
  if(-not $Secure){ return $null }
  $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
  try { return [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr) } finally { if($bstr -ne [IntPtr]::Zero){ [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) } }
}

function New-SignArgs {
  param([string]$TargetPath)
  $signArgs = @('sign','/fd','sha256','/td','sha256','/tr','http://timestamp.digicert.com')
  if($SignPfxPath){
    if(!(Test-Path $SignPfxPath)){ throw "PFX non trouvé: $SignPfxPath" }
    $signArgs += @('/f', $SignPfxPath)
    $pwdPlain = $null
  if($SignPfxPasswordSecure){ $pwdPlain = Convert-ToPlainText -Secure $SignPfxPasswordSecure }
    else {
      # Prompt securely when running interactively
      try {
        if(-not $env:CI){ $pwdPlain = Convert-ToPlainText -Secure (Read-Host -AsSecureString -Prompt 'Mot de passe du PFX') }
      } catch {}
    }
    if($pwdPlain){ $signArgs += @('/p', $pwdPlain) }
  } elseif($CertThumbprint){
    $signArgs += @('/sha1', $CertThumbprint, '/s', $CertStoreName)
    if($CertStoreLocation -eq 'LocalMachine'){ $signArgs += '/sm' }
  } elseif($AutoPickCert){
    # Try to auto-pick a Code Signing cert from the store
    $storePath = "Cert:\$CertStoreLocation\$CertStoreName"
    if(Test-Path $storePath){
      $now = Get-Date
      $candidates = Get-ChildItem $storePath |
        Where-Object { $_.HasPrivateKey -and $_.NotAfter -gt $now -and $_.EnhancedKeyUsageList -and ($_.EnhancedKeyUsageList | Where-Object { $_.Oid.Value -eq '1.3.6.1.5.5.7.3.3' }) }
      if($CertSubjectFilter){ $candidates = $candidates | Where-Object { $_.Subject -like ("*$CertSubjectFilter*") } }
      $pick = $candidates | Sort-Object NotAfter -Descending | Select-Object -First 1
      if($pick){ $CertThumbprint = $pick.Thumbprint; $signArgs += @('/sha1', $CertThumbprint, '/s', $CertStoreName); if($CertStoreLocation -eq 'LocalMachine'){ $signArgs += '/sm' } }
    }
  }
  $signArgs += @($TargetPath)
  return ,$signArgs
}

$signTool = Resolve-SignTool

if(!(Test-Path $ArtifactsDir)){ throw "ArtifactsDir introuvable: $ArtifactsDir" }
$targets = @()
$targets += Get-ChildItem $ArtifactsDir -Filter '*.exe' -File -ErrorAction SilentlyContinue
$targets += Get-ChildItem $ArtifactsDir -Filter '*.msi' -File -ErrorAction SilentlyContinue
if($targets.Count -eq 0){ Write-Error "Aucun artefact .exe/.msi trouvé dans $ArtifactsDir"; exit 1 }

if(-not $SignPfxPath -and -not $CertThumbprint -and -not $AutoPickCert){
  Write-Error 'Aucune identité de signature fournie (-SignPfxPath ou -CertThumbprint ou -AutoPickCert).'; exit 1
}

foreach($t in $targets){
  Write-Host "Signing $($t.FullName) ..." -ForegroundColor Yellow
  $signArgs = New-SignArgs -TargetPath $t.FullName
  & $signTool @signArgs
  if($LASTEXITCODE -ne 0){ Write-Warning "Signature failed for $($t.Name) (code $LASTEXITCODE)" } else { Write-Host "Signed: $($t.Name)" -ForegroundColor Green }
}

Write-Host "Done." -ForegroundColor Green
