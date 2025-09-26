Param(
  [string]$Name = 'TitanScraperDashboard',
  [string]$Manufacturer = 'Titan Partners',
  [string]$Version = '1.0.0',
  [string]$ExeName = ''
)

if(-not $ExeName -or $ExeName.Trim() -eq '') { $ExeName = "$Name.exe" }

$exe = Join-Path (Join-Path $PSScriptRoot '..') (Join-Path 'dist' $ExeName)
if(!(Test-Path $exe)){
  Write-Error "EXE not found at $exe. Run scripts/build_exe.ps1 first."; exit 1
}

# Locate WiX Toolset (candle.exe, light.exe)
$candle = Get-Command candle.exe -ErrorAction SilentlyContinue
$light = Get-Command light.exe -ErrorAction SilentlyContinue
if(!$candle -or !$light){
  Write-Error "WiX Toolset not found in PATH. Install WiX v3.x and ensure candle.exe/light.exe are available."; exit 1
}

$buildDir = Join-Path (Join-Path $PSScriptRoot '..') 'build/msi'
$distDir  = Join-Path (Join-Path $PSScriptRoot '..') 'dist/msi'
New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
New-Item -ItemType Directory -Force -Path $distDir  | Out-Null

# Generate Product.wxs
<#
Notes:
 - We pass -dSourceExe=<full path> to candle; in WiX you reference $(var.SourceExe)
 - Include basic ARP metadata and an (optional) icon if present.
 - UpgradeCode is fixed to allow upgrades; change only if you intentionally fork product identity.
#>
$iconPath = Join-Path (Join-Path $PSScriptRoot '..') 'build/icon.ico'
$hasIcon = Test-Path $iconPath

<# We embed resolved absolute paths directly to avoid needing -d preprocessor vars for WiX. #>
$resolvedExe = [IO.Path]::GetFullPath($exe)
if($hasIcon){
  $resolvedIcon = [IO.Path]::GetFullPath($iconPath)
} else {
  $resolvedIcon = ''
}

$iconXml = ''
if($hasIcon){
  $iconXml = @"
    <Icon Id="AppIcon" SourceFile="${resolvedIcon}" />
    <Property Id="ARPPRODUCTICON" Value="AppIcon" />
"@
}

$productWxs = @"
<?xml version="1.0" encoding="UTF-8"?>
<Wix xmlns="http://schemas.microsoft.com/wix/2006/wi">
  <Product Id="*" Name="$Name" Language="1036" Version="$Version" Manufacturer="$Manufacturer" UpgradeCode="{5C7C7B8C-1E2D-4B0E-8B93-1F6C7B0C2F71}" Codepage="1252">
  <Package InstallerVersion="500" Compressed="yes" InstallScope="perMachine" />
  <MajorUpgrade DowngradeErrorMessage="Une version plus recente est deja installee." />
    <MediaTemplate/>
    <Property Id="ARPNOREPAIR" Value="1" />
    <Property Id="ARPNOMODIFY" Value="1" />
  <!-- Removed ARPINSTALLLOCATION to avoid CNDL1077 warning -->
${iconXml}

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
    </Directory>

    <!-- Application files -->
    <ComponentGroup Id="AppComponents" Directory="INSTALLFOLDER">
      <Component Id="cmpMain" Guid="{A3E3AC9F-6DD4-4E65-93D8-4F8A2B4D1001}">
        <File Id="filExe" Source="$resolvedExe" KeyPath="yes" />
        <Shortcut Id="StartMenuShortcut" Advertise="yes" Directory="AppProgramMenu" Name="$Name" WorkingDirectory="INSTALLFOLDER" />
        <RemoveFolder Id="RemoveAppProgramMenu" Directory="AppProgramMenu" On="uninstall" />
      </Component>
    </ComponentGroup>
  </Product>
</Wix>
"@

$outWxs = Join-Path $buildDir 'Product.wxs'
$productWxs | Set-Content -Path $outWxs -Encoding UTF8

# Compile and link (pass both exe and icon as variables)
Write-Host "[build_msi] Compiling WiX (exe=$resolvedExe, icon=$resolvedIcon)" -ForegroundColor Cyan
& $candle.Path -o (Join-Path $buildDir 'Product.wixobj') $outWxs
if($LASTEXITCODE -ne 0){ throw "candle.exe failed ($LASTEXITCODE)" }
& $light.Path -o (Join-Path $distDir ("{0}-{1}.msi" -f $Name,$Version)) (Join-Path $buildDir 'Product.wixobj')
if($LASTEXITCODE -ne 0){ throw "light.exe failed ($LASTEXITCODE)" }

Write-Host "[build_msi] MSI created in $distDir" -ForegroundColor Green
