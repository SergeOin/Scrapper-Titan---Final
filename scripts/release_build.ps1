Param(
  [ValidateSet('major','minor','patch')][string]$Bump='patch',
  [string]$Name='TitanScraper',
  [string]$Manufacturer='Titan Partners',
  [switch]$SkipMSI,
  [string]$CertThumbprint='',
  [string]$TimestampServer='http://timestamp.digicert.com',
  [string]$PreRelease='',  # ex: beta.1 ; passed through to bump_version
  [switch]$GenerateManifest,
  [switch]$GenerateChangelog,
  [string]$ManifestPath='dist/release_manifest.json'
)

Write-Host "[release] Starting release pipeline (bump=$Bump, name=$Name)" -ForegroundColor Cyan

# 1. Bump version (optionally with prerelease)
if($PreRelease){
  $version = python scripts/bump_version.py $Bump --pre $PreRelease
} else {
  $version = python scripts/bump_version.py $Bump
}
if(!$version){ throw "Version bump failed" }
Write-Host "[release] New version: $version" -ForegroundColor Green

# 1b. Generate changelog section if requested
if($GenerateChangelog){
  Write-Host "[release] Generating CHANGELOG section" -ForegroundColor Cyan
  python scripts/generate_changelog.py | Out-Host
}

# 2. Build EXE
& scripts/build_exe.ps1 -Name $Name
if($LASTEXITCODE -ne 0){ throw "EXE build failed" }

$exePath = Join-Path dist ("{0}.exe" -f $Name)
if(!(Test-Path $exePath)){ throw "Built EXE not found at $exePath" }

# 3. (Optional) Code sign EXE
if($CertThumbprint){
  Write-Host "[release] Signing EXE with certificate thumbprint $CertThumbprint" -ForegroundColor Yellow
  & signtool.exe sign /sha1 $CertThumbprint /tr $TimestampServer /td SHA256 /fd SHA256 "$exePath"
  if($LASTEXITCODE -ne 0){ throw "Code sign (EXE) failed" }
}

# 4. Build MSI (unless skipped) – strip prerelease suffix for MSI numeric version
$coreVersion = $version.Split('-')[0]
if(-not $SkipMSI){
  & scripts/build_msi.ps1 -Name $Name -Manufacturer $Manufacturer -Version $coreVersion -ExeName ("{0}.exe" -f $Name)
  if($LASTEXITCODE -ne 0){ throw "MSI build failed" }
  $msiPath = Join-Path (Join-Path dist 'msi') ("{0}-{1}.msi" -f $Name,$coreVersion)
  if(!(Test-Path $msiPath)){ throw "MSI not found at $msiPath" }
  # 5. (Optional) Code sign MSI
  if($CertThumbprint){
    Write-Host "[release] Signing MSI" -ForegroundColor Yellow
    & signtool.exe sign /sha1 $CertThumbprint /tr $TimestampServer /td SHA256 /fd SHA256 "$msiPath"
    if($LASTEXITCODE -ne 0){ throw "Code sign (MSI) failed" }
  }
}

Write-Host "[release] Done." -ForegroundColor Green
Write-Host "Artifacts:" -ForegroundColor Cyan
Write-Host " - EXE: $exePath"
if(-not $SkipMSI -and (Test-Path (Join-Path dist 'msi'))){ Get-ChildItem dist/msi | Select-Object -Last 3 | Out-Host }

# 6. Manifest (hashes)
if($GenerateManifest){
  if(!(Test-Path dist)){ New-Item -ItemType Directory -Force -Path dist | Out-Null }
  $manifest = [ordered]@{
    version = $version
    core_version = $coreVersion
    timestamp_utc = (Get-Date).ToUniversalTime().ToString('s')+'Z'
    name = $Name
    artifacts = [ordered]@{}
  }
  function Get-Sha256($p){ (Get-FileHash -Algorithm SHA256 -Path $p).Hash.ToLower() }
  if(Test-Path $exePath){
    $manifest.artifacts.exe = [ordered]@{ path = $exePath; sha256 = Get-Sha256 $exePath }
  }
  if(-not $SkipMSI -and (Test-Path $msiPath)){
    $manifest.artifacts.msi = [ordered]@{ path = $msiPath; sha256 = Get-Sha256 $msiPath }
  }
  $json = ($manifest | ConvertTo-Json -Depth 6)
  $manifestFull = Join-Path $PSScriptRoot (Join-Path '..' $ManifestPath)
  $manifestDir = Split-Path $manifestFull -Parent
  if(!(Test-Path $manifestDir)){ New-Item -ItemType Directory -Force -Path $manifestDir | Out-Null }
  $json | Out-File -FilePath $manifestFull -Encoding utf8 -Force
  Write-Host "[release] Manifest written: $manifestFull" -ForegroundColor Green
}

Write-Host "Silent uninstall hint: msiexec /x {PRODUCT-CODE} /qn (wmic product where name='$Name' get IdentifyingNumber)" -ForegroundColor DarkGray
if($PreRelease){ Write-Host "Pre-release build suffix: $PreRelease (MSI uses core version $coreVersion)" -ForegroundColor DarkYellow }
