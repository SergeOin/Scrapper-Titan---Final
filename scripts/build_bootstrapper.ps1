Param(
  [switch]$PerMachine,
  [string]$VCppUrl = 'https://aka.ms/vs/17/release/vc_redist.x64.exe',
  [string]$WebView2Url = 'https://go.microsoft.com/fwlink/p/?LinkId=2124703',
  [string]$MsiPath = '',
  # Optional signing (signtool discovery similar to build_desktop_msi.ps1)
  [string]$SignPfxPath,
  [string]$SignPfxPassword,
  [string]$CertThumbprint,
  [ValidateSet('CurrentUser','LocalMachine')][string]$CertStoreLocation = 'CurrentUser',
  [string]$CertStoreName = 'My',
  [switch]$AutoPickCert,
  [string]$CertSubjectFilter
)

$ErrorActionPreference = 'Stop'

$root = (Join-Path $PSScriptRoot '..')
$outDir = Join-Path $root 'dist/msi'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

# Pick MSI automatically if not provided
if([string]::IsNullOrWhiteSpace($MsiPath)){
  $candidates = Get-ChildItem (Join-Path $outDir '*.msi') | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if($candidates){ $MsiPath = $candidates.FullName } else { Write-Error 'No MSI found in dist/msi. Build MSI first.'; exit 1 }
}

$candle = Get-Command candle.exe -ErrorAction SilentlyContinue
$light  = Get-Command light.exe  -ErrorAction SilentlyContinue
if(!$candle -or !$light){ Write-Error 'WiX Toolset not found in PATH'; exit 1 }

$tmp = Join-Path $root 'build/bootstrapper'
if(Test-Path $tmp){ try { Remove-Item -Recurse -Force $tmp } catch {} }
New-Item -ItemType Directory -Force -Path $tmp | Out-Null

$arch = 'x64'
$scope = if($PerMachine){ 'perMachine' } else { 'perUser' }
<# Use single-quoted here-string to prevent PowerShell from expanding $(var.*) placeholders #>
$bundleWxs = @'
<?xml version='1.0' encoding='UTF-8'?>
<Wix xmlns='http://schemas.microsoft.com/wix/2006/wi' xmlns:bal='http://schemas.microsoft.com/wix/BalExtension'>
  <Bundle Name='Titan Scraper Bootstrapper' Version='1.0.0.0' Manufacturer='Titan Partners' UpgradeCode='{7A1B21F7-0789-4EE8-84A7-698E20E72FA9}'
          Compressed='yes' IconSourceFile='$(var.IconFile)'>
    
    <!-- Variable pour le chemin d'installation -->
    <Variable Name='LaunchTargetPath' Type='string' Value='[ProgramFilesFolder]TitanScraper\TitanScraper.exe' />
    
    <BootstrapperApplicationRef Id='WixStandardBootstrapperApplication.HyperlinkLicense'>
      <bal:WixStandardBootstrapperApplication LicenseUrl='https://example.com/license' LogoFile='$(var.IconFile)' SuppressOptionsUI='yes' LaunchTarget='[LaunchTargetPath]' />
    </BootstrapperApplicationRef>
    <Chain>
      <PackageGroupRef Id='Prerequisites' />
      <MsiPackage SourceFile='$(var.ProductMsi)' InstallCondition='1' Vital='yes' DisplayName='Titan Scraper' />
    </Chain>
  </Bundle>

  <Fragment>
    <PackageGroup Id='Prerequisites'>
      <ExePackage Id='VCpp' SourceFile='$(var.VCppExe)' PerMachine='yes' Compressed='yes' Vital='no'
                  InstallCommand='/install /quiet /norestart' RepairCommand='/repair /quiet /norestart' UninstallCommand='/uninstall /quiet /norestart' />
      <ExePackage Id='WebView2' SourceFile='$(var.Wv2Exe)' PerMachine='no' Compressed='yes' Vital='no'
                  InstallCommand='/silent /install' />
    </PackageGroup>
  </Fragment>
</Wix>
'@

$icon = Join-Path $root 'build/icon.ico'
if(!(Test-Path $icon) -and (Test-Path (Join-Path $root 'Titan Scraper logo.png'))){
  try { & (Get-Command python).Source (Join-Path $root 'scripts/util_make_icon.py') -i (Join-Path $root 'Titan Scraper logo.png') -o $icon } catch {}
}

# Download prerequisite EXEs to build folder
$vcExe = Join-Path $tmp 'vc_redist.x64.exe'
$wv2Exe = Join-Path $tmp 'MicrosoftEdgeWebView2Setup.exe'

function Download-WithRetry {
  param([string]$Url,[string]$OutFile,[int]$Retries=3)
  for($i=1; $i -le $Retries; $i++){
    try {
      Invoke-WebRequest -Uri $Url -OutFile $OutFile -UseBasicParsing -TimeoutSec 120
      if(Test-Path $OutFile -PathType Leaf){ return }
    } catch {
      if($i -eq $Retries){ throw }
      Start-Sleep -Seconds ([Math]::Min(5*$i,15))
    }
  }
}

Download-WithRetry -Url $VCppUrl -OutFile $vcExe
Download-WithRetry -Url $WebView2Url -OutFile $wv2Exe

$wxs = Join-Path $tmp 'Bundle.wxs'
$bundleWxs | Set-Content -Path $wxs -Encoding UTF8

& $candle.Path -ext WixBalExtension -dProductMsi="$MsiPath" -dIconFile="$icon" -dVCppExe="$vcExe" -dWv2Exe="$wv2Exe" -o (Join-Path $tmp 'Bundle.wixobj') $wxs
& $light.Path -ext WixBalExtension -dProductMsi="$MsiPath" -dIconFile="$icon" -dVCppExe="$vcExe" -dWv2Exe="$wv2Exe" -o (Join-Path $outDir 'TitanScraper-Bootstrapper.exe') (Join-Path $tmp 'Bundle.wixobj')

Write-Host "Bootstrapper created: $(Join-Path $outDir 'TitanScraper-Bootstrapper.exe')" -ForegroundColor Green

# Optional code signing for the bootstrapper
$sigRequested = $false
if($SignPfxPath -or $CertThumbprint -or $AutoPickCert){ $sigRequested = $true }

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
  return $null
}

function New-SignArgs {
  param([string]$TargetPath)
  $args = @('sign','/fd','sha256','/td','sha256')
  if($SignPfxPath){
    if(!(Test-Path $SignPfxPath)){ throw "PFX non trouvé: $SignPfxPath" }
    $args += @('/f', $SignPfxPath)
    if($SignPfxPassword){ $args += @('/p', $SignPfxPassword) }
  } elseif($CertThumbprint){
    $args += @('/sha1', $CertThumbprint, '/s', $CertStoreName)
    if($CertStoreLocation -eq 'LocalMachine'){ $args += '/sm' }
  }
  $args += @('/tr','http://timestamp.digicert.com')
  $args += @($TargetPath)
  return ,$args
}

if($sigRequested){
  # Try auto-pick cert if requested and nothing else specified
  if($AutoPickCert -and -not $SignPfxPath -and -not $CertThumbprint){
    try {
      $storePath = "Cert:\$CertStoreLocation\$CertStoreName"
      if(Test-Path $storePath){
        $now = Get-Date
        $candidates = Get-ChildItem $storePath |
          Where-Object { $_.HasPrivateKey -and $_.NotAfter -gt $now -and $_.EnhancedKeyUsageList -and ($_.EnhancedKeyUsageList | Where-Object { $_.Oid.Value -eq '1.3.6.1.5.5.7.3.3' }) }
        if($CertSubjectFilter){ $candidates = $candidates | Where-Object { $_.Subject -like ("*$CertSubjectFilter*") } }
        $pick = $candidates | Sort-Object NotAfter -Descending | Select-Object -First 1
        if($pick){ $CertThumbprint = $pick.Thumbprint }
      }
    } catch {}
  }
  $sigPath = Resolve-SignTool
  if($sigPath){
    try {
      $bundlePath = Join-Path $outDir 'TitanScraper-Bootstrapper.exe'
      if(Test-Path $bundlePath){
        $args = New-SignArgs -TargetPath $bundlePath
        & $sigPath @args
        if($LASTEXITCODE -ne 0){ Write-Warning "Signature du bootstrapper échouée (code $LASTEXITCODE)." } else { Write-Host "Bootstrapper signé avec succès." -ForegroundColor Green }
      }
    } catch { Write-Warning "Erreur pendant la signature du bootstrapper: $_" }
  } else {
    Write-Warning 'signtool.exe introuvable; bootstrapper non signé.'
  }
}
