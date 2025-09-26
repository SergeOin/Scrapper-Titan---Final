Param(
  [string]$SourceDir = (Join-Path (Join-Path $PSScriptRoot '..') 'dist/TitanScraper'),
  [string]$Name = 'TitanScraper',
  [string]$Manufacturer = 'Titan Partners',
  [string]$Version = '',
  [string]$ExeName = 'TitanScraper.exe',
  [switch]$Sign = $false,
  [string]$CertPfxPath = '',
  [string]$CertPfxPassword = '',
  [string]$TimestampUrl = 'http://timestamp.digicert.com'
)

$ErrorActionPreference = 'Stop'

if(!(Test-Path $SourceDir)){
  Write-Error "SourceDir not found: $SourceDir. Build the app first (build_windows.ps1)."; exit 1
}

# Resolve version automatically
if(-not $Version -or $Version -eq ''){
  if($env:BUILD_VERSION){
    $Version = $env:BUILD_VERSION
  } elseif (Test-Path (Join-Path (Join-Path $PSScriptRoot '..') 'VERSION')) {
    try { $Version = (Get-Content (Join-Path (Join-Path $PSScriptRoot '..') 'VERSION') -Raw).Trim() } catch { }
  } elseif (Test-Path (Join-Path (Join-Path $PSScriptRoot '..') 'package.json')){
    try{
      $pkg = Get-Content (Join-Path (Join-Path $PSScriptRoot '..') 'package.json') -Raw | ConvertFrom-Json
      if($pkg.version){ $Version = [string]$pkg.version }
    } catch { }
  }
  if(-not $Version -or $Version -eq ''){ $Version = '1.0.0' }
}

# Locate WiX Toolset (heat.exe, candle.exe, light.exe)
$heat = Get-Command heat.exe -ErrorAction SilentlyContinue
$candle = Get-Command candle.exe -ErrorAction SilentlyContinue
$light = Get-Command light.exe -ErrorAction SilentlyContinue
$signtool = Get-Command signtool.exe -ErrorAction SilentlyContinue
if(!$heat -or !$candle -or !$light){
  Write-Error "WiX Toolset not found in PATH. Install WiX v3.x (heat/candle/light)."; exit 1
}

function Invoke-CodeSign([string]$file){
  if(-not $Sign){ return }
  if(-not $signtool){ Write-Warning "signtool.exe not found; skipping signing for $file"; return }
  if(-not (Test-Path $file)){ Write-Warning "File not found to sign: $file"; return }
  $args = @('sign','/fd','sha256')
  if($TimestampUrl){ $args += @('/tr',$TimestampUrl,'/td','sha256') }
  if($CertPfxPath){ $args += @('/f',$CertPfxPath) }
  if($CertPfxPassword){ $args += @('/p',$CertPfxPassword) }
  $args += @($file)
  & $signtool.Path @args
  if($LASTEXITCODE -ne 0){ throw "signtool failed ($LASTEXITCODE) for $file" }
}

$buildDir = Join-Path (Join-Path $PSScriptRoot '..') 'build/msi'
$distDir  = Join-Path (Join-Path $PSScriptRoot '..') 'dist/msi'
New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
New-Item -ItemType Directory -Force -Path $distDir  | Out-Null

# Harvest the directory with heat (ComponentGroup: CG_AppFiles)
$appWxs = Join-Path $buildDir 'AppFiles.wxs'
& $heat.Path dir $SourceDir -cg CG_AppFiles -gg -sfrag -srd -dr INSTALLFOLDER -var var.AppDir -out $appWxs | Out-Null
if($LASTEXITCODE -ne 0){ throw "heat.exe failed ($LASTEXITCODE)" }

# Product definition referencing harvested files and adding Start Menu shortcut
# Compute optional ARP icon XML if icon exists
$iconPath = Join-Path (Join-Path $PSScriptRoot '..') 'build/icon.ico'
$iconXml = ''
if(Test-Path $iconPath){
  $iconXml = @"
    <Icon Id="AppIcon" SourceFile="$iconPath" />
    <Property Id="ARPPRODUCTICON" Value="AppIcon" />
"@
}

${productWxs} = @"
<?xml version="1.0" encoding="UTF-8"?>
<Wix xmlns="http://schemas.microsoft.com/wix/2006/wi">
  <Product Id="*" Name="$Name" Language="1036" Codepage="1252" Version="$Version" Manufacturer="$Manufacturer" UpgradeCode="{F08A2A29-7F9F-4DC8-9B68-8E0D7A0B4C11}">
    <Package InstallerVersion="500" Compressed="yes" InstallScope="perMachine" />
    <MajorUpgrade DowngradeErrorMessage="A newer version is already installed." />
    <MediaTemplate/>
${iconXml}
    

    <Feature Id="MainFeature" Title="$Name" Level="1">
      <ComponentGroupRef Id="CG_AppFiles" />
      <ComponentRef Id="cmpStartMenu" />
      <ComponentRef Id="cmpDesktopShortcut" />
    </Feature>

    <Directory Id="TARGETDIR" Name="SourceDir">
      <Directory Id="ProgramFilesFolder">
        <Directory Id="INSTALLFOLDER" Name="$Name" />
      </Directory>
      <Directory Id="ProgramMenuFolder">
        <Directory Id="AppProgramMenu" Name="$Name" />
      </Directory>
      <Directory Id="DesktopFolder" />
    </Directory>

    <DirectoryRef Id="AppProgramMenu">
      <Component Id="cmpStartMenu" Guid="*">
        <Shortcut Id="StartMenuShortcut" Name="$Name" Directory="AppProgramMenu" WorkingDirectory="INSTALLFOLDER" Target="[INSTALLFOLDER]$ExeName" />
        <RemoveFolder Id="RemoveAppProgramMenu" Directory="AppProgramMenu" On="uninstall" />
  <RegistryValue Root="HKCU" Key="Software\$Manufacturer\$Name" Name="installed" Type="integer" Value="1" KeyPath="yes"/>
      </Component>
    </DirectoryRef>

    <DirectoryRef Id="DesktopFolder">
      <Component Id="cmpDesktopShortcut" Guid="*">
        <Shortcut Id="DesktopShortcut" Name="$Name" Directory="DesktopFolder" WorkingDirectory="INSTALLFOLDER" Target="[INSTALLFOLDER]$ExeName" />
        <RegistryValue Root="HKCU" Key="Software\$Manufacturer\$Name" Name="desktop" Type="integer" Value="1" KeyPath="yes"/>
      </Component>
    </DirectoryRef>

  </Product>
</Wix>
"@

$outWxs = Join-Path $buildDir 'Product.wxs'
$productWxs | Set-Content -Path $outWxs -Encoding UTF8

# Compile and link with var for source dir
& $candle.Path -dAppDir="$SourceDir" -o (Join-Path $buildDir 'AppFiles.wixobj') $appWxs
if($LASTEXITCODE -ne 0){ throw "candle.exe (AppFiles) failed ($LASTEXITCODE)" }
& $candle.Path -dAppDir="$SourceDir" -o (Join-Path $buildDir 'Product.wixobj') $outWxs
if($LASTEXITCODE -ne 0){ throw "candle.exe (Product) failed ($LASTEXITCODE)" }

${msiPath} = Join-Path $distDir ("{0}-{1}.msi" -f $Name,$Version)

# Sign the EXE prior to MSI linking (optional)
Invoke-CodeSign (Join-Path $SourceDir $ExeName)

& $light.Path -dAppDir="$SourceDir" -sice:ICE60 -sice:ICE69 -o $msiPath (Join-Path $buildDir 'Product.wixobj') (Join-Path $buildDir 'AppFiles.wixobj')
if($LASTEXITCODE -ne 0){ throw "light.exe failed ($LASTEXITCODE)" }

# Sign the MSI (optional)
Invoke-CodeSign $msiPath

Write-Host "[build_msi_folder] MSI created in $distDir" -ForegroundColor Green
