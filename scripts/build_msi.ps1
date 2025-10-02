Param(
  [string]$Name = 'TitanScraper',
  [string]$Manufacturer = 'Titan Partners',
  [string]$Version = '1.0.0',
  [string]$ExeName = ''
)

if(-not $ExeName -or $ExeName.Trim() -eq '') { $ExeName = "$Name.exe" }

$root    = Join-Path $PSScriptRoot '..'
$exe     = Join-Path $root (Join-Path 'dist' $ExeName)
if(!(Test-Path $exe)){
  Write-Error "EXE not found at $exe. Run scripts/build_exe.ps1 first."; exit 1
}

# Strip prerelease suffix for MSI numeric version (WiX requires x.y.z[.w])
$CoreVersionString = $Version.Split('-')[0]

# Basic size sanity check (>5MB typical for onefile)
$exeInfo = Get-Item $exe -ErrorAction SilentlyContinue
if($exeInfo -and $exeInfo.Length -lt 5000000){
  Write-Warning "Executable seems unexpectedly small ($([Math]::Round($exeInfo.Length/1MB,2)) MB) - build may be incomplete."
}

# Locate WiX Toolset
$candle = Get-Command candle.exe -ErrorAction SilentlyContinue
$light  = Get-Command light.exe  -ErrorAction SilentlyContinue
if(!$candle -or !$light){
  Write-Error "WiX Toolset not found in PATH. Install WiX 3.x (https://wixtoolset.org/) and ensure candle.exe/light.exe are available."; exit 1
}

$buildDir = Join-Path $root 'build/msi'
$distDir  = Join-Path $root 'dist/msi'
New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
New-Item -ItemType Directory -Force -Path $distDir  | Out-Null

$msiName = "$Name-$Version.msi"
$msiPath = Join-Path $distDir $msiName

# Optional icon
$iconPath = Join-Path $root 'build/icon.ico'
$hasIcon  = Test-Path $iconPath
$resolvedExe  = [IO.Path]::GetFullPath($exe)
$resolvedIcon = if($hasIcon){ [IO.Path]::GetFullPath($iconPath) } else { '' }
$desktopIconAttr = if($hasIcon){ ' Icon="AppIcon"' } else { '' }
$shortcutIconAttr = if($hasIcon){ ' Icon="AppIcon"' } else { '' }

$iconXml = ''
if($hasIcon){
$iconXml = @"
    <Icon Id="AppIcon" SourceFile="$resolvedIcon" />
    <Property Id="ARPPRODUCTICON" Value="AppIcon" />
"@
}

<#
 Generates a minimal WiX installer: copies the EXE to Program Files\$Name,
 adds Start Menu shortcut (and optional icon), supports upgrades via constant UpgradeCode.
#>
$productWxs = @"
<?xml version="1.0" encoding="UTF-8"?>
<Wix xmlns="http://schemas.microsoft.com/wix/2006/wi">
  <Product Id="*" Name="$Name" Language="1036" Version="$CoreVersionString" Manufacturer="$Manufacturer" UpgradeCode="{5C7C7B8C-1E2D-4B0E-8B93-1F6C7B0C2F71}" Codepage="1252">
    <Package InstallerVersion="500" Compressed="yes" InstallScope="perMachine" />
    <MajorUpgrade DowngradeErrorMessage="Une version plus recente est deja installee." />
    <MediaTemplate />
    <Property Id="ARPNOREPAIR" Value="1" />
    <Property Id="ARPNOMODIFY" Value="1" />
    $iconXml
    <Feature Id="MainFeature" Title="$Name" Level="1">
      <ComponentGroupRef Id="AppComponents" />
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
    <ComponentGroup Id="AppComponents">
      <Component Id="cmpMain" Directory="INSTALLFOLDER" Guid="{A3E3AC9F-6DD4-4E65-93D8-4F8A2B4D1001}">
        <File Id="filExe" Source="$resolvedExe" KeyPath="yes" />
        <Shortcut Id="StartMenuShortcut" Advertise="yes" Directory="AppProgramMenu" Name="$Name" WorkingDirectory="INSTALLFOLDER" />
        <RemoveFolder Id="RemoveAppProgramMenu" Directory="AppProgramMenu" On="uninstall" />
      </Component>
  <Component Id="cmpDesktopShortcut" Directory="DesktopFolder" Guid="{F4A374FE-5C8E-4F62-9E50-7B94B9A3E6E7}">
        <Shortcut Id="DesktopShortcut" Name="$Name" Target="[INSTALLFOLDER]$ExeName" WorkingDirectory="INSTALLFOLDER"$desktopIconAttr Description="Lancer $Name" />
  <RegistryValue Root="HKCU" Key="Software\TitanScraper" Name="DesktopShortcut" Type="integer" Value="1" KeyPath="yes" />
      </Component>
    </ComponentGroup>
    <CustomAction Id="LaunchApplication" FileKey="filExe" ExeCommand="" Return="asyncNoWait" Impersonate="yes" />
    <InstallExecuteSequence>
      <Custom Action="LaunchApplication" After="InstallFinalize">NOT Installed</Custom>
    </InstallExecuteSequence>
  </Product>
</Wix>
"@

$outWxs = Join-Path $buildDir 'Product.wxs'
$productWxs | Set-Content -Path $outWxs -Encoding UTF8

Write-Host "[build_msi] Compiling WiX source: $outWxs" -ForegroundColor Cyan
$wixObj = Join-Path $buildDir 'Product.wixobj'
& $candle.Path -nologo -out $wixObj $outWxs
if($LASTEXITCODE -ne 0){ throw "candle.exe failed ($LASTEXITCODE)" }

Write-Host "[build_msi] Linking MSI: $msiPath" -ForegroundColor Cyan
& $light.Path -nologo -ext WixUIExtension -out $msiPath $wixObj
if($LASTEXITCODE -ne 0){ throw "light.exe failed ($LASTEXITCODE)" }

Write-Host "[build_msi] MSI created: $msiPath" -ForegroundColor Green

# Remove legacy artifacts (old product name patterns) to avoid confusion
Get-ChildItem $distDir -Filter 'TitanScraperDashboard*' -ErrorAction SilentlyContinue | ForEach-Object {
  try {
    Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
    Write-Host "[build_msi] Removed legacy artifact: $($_.Name)" -ForegroundColor DarkGray
  } catch {}
}

exit 0
