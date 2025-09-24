Param(
  [string]$Name = 'TitanScraperDashboard',
  [string]$Manufacturer = 'Titan Partners',
  [string]$Version = '1.0.0'
)

$exe = Join-Path (Join-Path $PSScriptRoot '..') (Join-Path 'dist' ("{0}.exe" -f $Name))
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
$productWxs = @"
<?xml version="1.0" encoding="UTF-8"?>
<Wix xmlns="http://schemas.microsoft.com/wix/2006/wi">
  <Product Id="*" Name="$Name" Language="1036" Version="$Version" Manufacturer="$Manufacturer" UpgradeCode="{5C7C7B8C-1E2D-4B0E-8B93-1F6C7B0C2F71}">
    <Package InstallerVersion="500" Compressed="yes" InstallScope="perMachine" />
    <MajorUpgrade DowngradeErrorMessage="Une version plus récente est déjà installée." />
    <MediaTemplate/>

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
      <Component Id="cmpExe" Guid="*">
        <File Id="filExe" Source="$(var.SourceExe)" KeyPath="yes"/>
        <Shortcut Id="StartMenuShortcut" Directory="AppProgramMenu" Name="$Name" WorkingDirectory="INSTALLFOLDER" Target="[#filExe]" />
        <RemoveFolder Id="RemoveAppProgramMenu" Directory="AppProgramMenu" On="uninstall" />
        <RegistryValue Root="HKCU" Key="Software\\$Manufacturer\\$Name" Name="installed" Type="integer" Value="1" KeyPath="yes"/>
      </Component>
    </ComponentGroup>
  </Product>
</Wix>
"@

$outWxs = Join-Path $buildDir 'Product.wxs'
$productWxs | Set-Content -Path $outWxs -Encoding UTF8

# Compile and link
& $candle.Path -dSourceExe=$exe -o (Join-Path $buildDir 'Product.wixobj') $outWxs
if($LASTEXITCODE -ne 0){ throw "candle.exe failed ($LASTEXITCODE)" }
& $light.Path -o (Join-Path $distDir ("{0}-{1}.msi" -f $Name,$Version)) (Join-Path $buildDir 'Product.wixobj')
if($LASTEXITCODE -ne 0){ throw "light.exe failed ($LASTEXITCODE)" }

Write-Host "[build_msi] MSI created in $distDir" -ForegroundColor Green
