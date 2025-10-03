Param(
  [string]$Version = "0.0.0",
  [string]$PyInstallerSpec = "linkedin_scraper.spec",
  [string]$ProductName = "LinkedInScraper"
)
$ErrorActionPreference='Stop'
Write-Host "==> Building Windows executable via PyInstaller" -ForegroundColor Cyan
if (!(Test-Path .venv)) { py -3 -m venv .venv }
. .\.venv\Scripts\Activate.ps1
pip install -U pip wheel setuptools
pip install -r requirements.txt
pip install pyinstaller==6.10.0

if (!(Test-Path $PyInstallerSpec)) { Write-Error "Spec file $PyInstallerSpec not found" }
pyinstaller $PyInstallerSpec -y --clean

$exePath = Join-Path dist $ProductName
if (!(Test-Path $exePath)) { Write-Error "PyInstaller output not found: $exePath" }

# Optional: create a minimal WiX toolset based MSI (assumes candle/light on PATH)
$wix = Get-Command candle.exe -ErrorAction SilentlyContinue
if (-not $wix) {
  Write-Warning "WiX Toolset not installed or candle.exe not in PATH. Skipping MSI generation."
  return
}
Write-Host "==> Generating WiX MSI" -ForegroundColor Cyan
$msiBuildDir = "build/msi"
New-Item -ItemType Directory -Force -Path $msiBuildDir | Out-Null
$wxsFile = Join-Path $msiBuildDir "Product.wxs"
$guid = [guid]::NewGuid().ToString()
$upgradeCode = [guid]::NewGuid().ToString()
$exeFile = Join-Path $exePath "$ProductName.exe"
if (!(Test-Path $exeFile)) { Write-Error "Expected executable not present: $exeFile" }
@"
<?xml version="1.0" encoding="UTF-8"?>
<Wix xmlns="http://schemas.microsoft.com/wix/2006/wi">
  <Product Id="$guid" Name="$ProductName" Language="1033" Version="$Version" Manufacturer="Internal" UpgradeCode="$upgradeCode">
    <Package InstallerVersion="500" Compressed="yes" InstallScope="perMachine" />
    <MediaTemplate />
    <Directory Id="TARGETDIR" Name="SourceDir">
      <Directory Id="ProgramFilesFolder">
        <Directory Id="INSTALLFOLDER" Name="$ProductName" />
      </Directory>
      <Directory Id="DesktopFolder" Name="Desktop" />
    </Directory>
    <DirectoryRef Id="INSTALLFOLDER">
      <Component Id="cmpMainExe" Guid="*">
        <File Id="filMainExe" Source="$exeFile" KeyPath="yes" />
        <Shortcut Id="AppDesktopShortcut" Directory="DesktopFolder" Name="$ProductName" WorkingDirectory="INSTALLFOLDER" Icon="AppIcon.ico" Advertise="no" Target="[#filMainExe]" />
      </Component>
    </DirectoryRef>
    <Feature Id="DefaultFeature" Level="1">
      <ComponentRef Id="cmpMainExe" />
    </Feature>
    <Icon Id="AppIcon.ico" SourceFile="build/icon.ico" />
  </Product>
</Wix>
"@ | Out-File -Encoding UTF8 $wxsFile

Push-Location $msiBuildDir
candle.exe Product.wxs -o Product.wixobj
light.exe Product.wixobj -o "$($ProductName)_$Version.msi"
Pop-Location
Write-Host "MSI generated: $msiBuildDir/$ProductName_$Version.msi" -ForegroundColor Green
