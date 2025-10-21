Param(
  [string]$AppFolderName = 'TitanScraper',
  # Nom "technique" (dossier, exe). Gardé sans espace.
  [string]$Name = 'TitanScraper',
  # Nom affiché (Add/Remove Programs, menu démarrer, raccourcis) – demandé: "Titan Scraper"
  [string]$DisplayName = 'Titan Scraper',
  [string]$Manufacturer = 'Titan Partners',
  [string]$Version = '',
  [switch]$Aggressive, # active des exclusions plus larges (playwright lib js, scripts reinstall multi-OS, pw-browsers, etc.)
  [switch]$SkipPrune, # diagnostique: ne retire aucun fichier (pour vérifier heat + existence)
  [switch]$KeepTzData, # si défini, on conserve tzdata/pytz zoneinfo
  [switch]$PerMachine, # si défini, installe sous ProgramFiles (nécessite élévation). Par défaut: per-user (LocalAppData)
  [switch]$NoEmbedCab, # si défini, laisse le/les cab(s) externes (cab1.cab). Par défaut on EMBED pour éviter l'erreur fichier manquant.
  # Signing (optionnel) – si fourni, signe le MSI à la fin
  [string]$SignPfxPath,
  [string]$SignPfxPassword,
  [string]$TimestampUrl = 'http://timestamp.digicert.com',
  # Alternative: signer via certificat installé (magasin Windows)
  [string]$CertThumbprint,
  [ValidateSet('CurrentUser','LocalMachine')][string]$CertStoreLocation = 'CurrentUser',
  [string]$CertStoreName = 'My',
  # Auto-sélection d'un certificat de signature de code depuis le magasin indiqué
  [switch]$AutoPickCert,
  # Filtre optionnel sur le Subject (ex: 'Titan Partners' ) lors de l'auto-sélection
  [string]$CertSubjectFilter
)

$ErrorActionPreference = 'Stop'

$root = (Join-Path $PSScriptRoot '..')
$verFile = Join-Path $root 'VERSION'
if([string]::IsNullOrWhiteSpace($Version)){
  if(Test-Path $verFile){
    try { $Version = (Get-Content $verFile -Raw).Trim() } catch { $Version = '1.0.0' }
  } else {
    $Version = '1.0.0'
  }
}
$distFolder = Join-Path $root (Join-Path 'dist' $AppFolderName)
if(!(Test-Path $distFolder)){ Write-Error "Folder distribution not found at $distFolder. Run scripts/build_desktop_exe.ps1 first."; exit 1 }

$candle = Get-Command candle.exe -ErrorAction SilentlyContinue
$light  = Get-Command light.exe  -ErrorAction SilentlyContinue
$heat   = Get-Command heat.exe   -ErrorAction SilentlyContinue
if(!$candle -or !$light -or !$heat){ Write-Error 'WiX Toolset (candle, light, heat) not all found in PATH.'; exit 1 }

$work = Join-Path $root 'build/msi-desktop'
$stage = Join-Path $root 'build/msi-stage'
$out  = Join-Path $root 'dist/msi'

# Nettoyage des artefacts précédents pour éviter le déphasage (wixobj obsolètes / Harvest ancien)
if(Test-Path $work){ try { Remove-Item -Recurse -Force $work } catch { Write-Warning "Impossible de nettoyer $work : $_" } }
if(Test-Path $stage){ try { Remove-Item -Recurse -Force $stage } catch { Write-Warning "Impossible de nettoyer $stage : $_" } }
New-Item -ItemType Directory -Force -Path $work  | Out-Null
New-Item -ItemType Directory -Force -Path $stage | Out-Null
New-Item -ItemType Directory -Force -Path $out   | Out-Null

# Préparation STAGING : on copie l'arborescence dist dans un répertoire isolé que l'on va alléger AVANT heat
Write-Host "[build_desktop_msi] Création répertoire de staging: $stage" -ForegroundColor DarkCyan
robocopy "$distFolder" "$stage" /E /NFL /NDL /NJH /NJS /NC /NS | Out-Null

if(-not $SkipPrune){
  $dirsToRemove = @()
  if(-not $KeepTzData){
    $dirsToRemove += @(
      '_internal/tzdata/zoneinfo',
      '_internal/pytz/zoneinfo'
    )
  }
  if($Aggressive){
    $dirsToRemove += @(
      '_internal/pw-browsers',
      '_internal/playwright/driver/package/lib',
      '_internal/playwright/driver/package/bin/reinstall_',
      '_internal/playwright/driver/package/bin/install_media_pack.ps1'
    )
  }
  foreach($d in $dirsToRemove){
    $p = Join-Path $stage $d
    if(Test-Path $p){
      Write-Host "[build_desktop_msi] STAGE prune: $d" -ForegroundColor DarkYellow
      try { Remove-Item -Recurse -Force $p } catch { Write-Warning "Echec suppression $p : $_" }
    }
  }
} else {
  Write-Host '[build_desktop_msi] SkipPrune actif: aucun répertoire supprimé avant harvest.' -ForegroundColor Yellow
}

<#
 Harvest sur le répertoire de staging (déjà épuré). On utilise des chemins absolus (pas de variable).
 Cela évite les cascades d'erreurs LGHT0103 liées à des fichiers fantômes supprimés après coup.
#>
$harvestWxs = Join-Path $work 'Harvest.wxs'
& $heat.Path dir $stage -gg -g1 -srd -dr INSTALLFOLDER -cg AppFiles -out $harvestWxs | Out-Null

# Post-process harvest to drop components referencing files that are (a) unneeded (huge tz/pytz zoneinfo sets)
# or (b) no longer present in the dist folder, which would otherwise generate LGHT0103 errors during light.
try {
  [xml]$hx = Get-Content -Path $harvestWxs -Encoding UTF8
  $nsm = New-Object System.Xml.XmlNamespaceManager($hx.NameTable)
  $nsm.AddNamespace('w','http://schemas.microsoft.com/wix/2006/wi') | Out-Null
  # Diagnostic: ensure we know the absolute dist path early
  Write-Host ("[build_desktop_msi] Dist folder absolute path: {0}" -f $distFolder) -ForegroundColor DarkCyan

  $fileNodes = @($hx.SelectNodes('//w:File',$nsm))
  Write-Host ("[build_desktop_msi] Harvest (staging) contient {0} <File>." -f $fileNodes.Count) -ForegroundColor DarkCyan
  if($fileNodes.Count -eq 0){ throw "Aucun fichier détecté par heat sur le staging ($stage). Abandon." }
  # Conversion des chemins relatifs 'SourceDir\' en chemins absolus -> fiabilise Test-Path & évite résolutions hasardeuses
  $converted = 0
  foreach($fn in $fileNodes){
    $srcAttr = $fn.GetAttribute('Source')
    if($srcAttr -like 'SourceDir*'){
      $rel = $srcAttr.Substring(9) # longueur 'SourceDir'
      $abs = Join-Path $stage ($rel -replace '/', '\')
      $fn.SetAttribute('Source',$abs)
      $converted++
    }
  }
  Write-Host "[build_desktop_msi] Chemins convertis en absolu: $converted" -ForegroundColor DarkCyan
  # Suppression des entrées de registre COM (HKCR) générées par pythonnet qui provoquent ICE03/ICE69 et sont inutiles pour l'app standalone.
  $regNodes = @($hx.SelectNodes('//w:RegistryValue',$nsm) | Where-Object { $_.Root -eq 'HKCR' })
  if($regNodes.Count -gt 0){
    foreach($r in $regNodes){ $null = $r.ParentNode.RemoveChild($r) }
    Write-Host "[build_desktop_msi] HKCR registry entries removed: $($regNodes.Count)" -ForegroundColor DarkYellow
  }
  ($fileNodes | Select-Object -First 5).ForEach({
    $pSrc = $_.GetAttribute('Source');
    Write-Host ("   Sample: {0} (exists={1})" -f (Split-Path $pSrc -Leaf),(Test-Path $pSrc)) -ForegroundColor DarkGray
  })

  # Plus de suppression XML (déjà fait côté staging). On sauvegarde tel quel.
  $hx.Save($harvestWxs)
} catch {
  Write-Warning "Post-harvest pruning failed: $_"
}

# Product definition referencing harvested group
if($PerMachine){
  $installScope = 'perMachine'
  $parentFolderId = 'ProgramFilesFolder'
} else {
  $installScope = 'perUser'
  $parentFolderId = 'LocalAppDataFolder'
}
# Aligner la racine de registre sur le scope d'installation
if($PerMachine){
  $registryRoot = 'HKLM'
} else {
  $registryRoot = 'HKCU'
}
if($NoEmbedCab){
  $embedAttr = ''
} else {
  $embedAttr = " EmbedCab='yes'"
}
 $productWxs = @"
<?xml version='1.0' encoding='UTF-8'?>
<Wix xmlns='http://schemas.microsoft.com/wix/2006/wi'>
  <Product Id='*' Name='$DisplayName' Language='1036' Version='$Version' Manufacturer='$Manufacturer' UpgradeCode='{9B5C7D24-38B2-4D4F-A0E5-4AA8F0F4B6C2}'>
    <Package InstallerVersion='500' Compressed='yes' InstallScope='$installScope' />
    <MajorUpgrade DowngradeErrorMessage='Une version plus recente est deja installee.' />
    <MediaTemplate$embedAttr />
    <Property Id='ARPNOREPAIR' Value='1' />
    <Property Id='ARPNOMODIFY' Value='1' />
    <Directory Id='TARGETDIR' Name='SourceDir'>
      <Directory Id='$parentFolderId'>
        <Directory Id='INSTALLFOLDER' Name='$Name' />
      </Directory>
      <Directory Id='ProgramMenuFolder'>
        <Directory Id='AppProgramMenu' Name='$DisplayName' />
      </Directory>
      <Directory Id='DesktopFolder' />
    </Directory>
    <DirectoryRef Id='AppProgramMenu'>
      <!-- Explicit GUID; provide HKCU registry value as KeyPath for per-user or per-machine consistent marker -->
      <Component Id='CmpShortcut' Guid='{3F6A7A42-9E38-4E53-A31B-8B66F9D5A4C1}'>
  <RegistryValue Root='HKCU' Key='Software\$DisplayName' Name='InstallPath' Type='string' Value='[INSTALLFOLDER]' KeyPath='yes' />
        <Shortcut Id='StartMenuShortcut' Name='$DisplayName' Target='[INSTALLFOLDER]TitanScraper.exe' WorkingDirectory='INSTALLFOLDER' />
        <Shortcut Id='DesktopShortcut' Directory='DesktopFolder' Name='$DisplayName' Target='[INSTALLFOLDER]TitanScraper.exe' WorkingDirectory='INSTALLFOLDER' />
        <RemoveFolder Id='RemoveAppProgramMenu' Directory='AppProgramMenu' On='uninstall' />
        <CreateFolder />
      </Component>
    </DirectoryRef>
    <Feature Id='MainFeature' Title='$DisplayName' Level='1'>
      <ComponentGroupRef Id='AppFiles' />
      <ComponentRef Id='CmpShortcut' />
    </Feature>
    <!-- Custom action to launch the application immediately after first install -->
    <CustomAction Id='LaunchApp' Directory='INSTALLFOLDER' ExeCommand='"[INSTALLFOLDER]TitanScraper.exe"' Return='asyncNoWait' Impersonate='yes' />
    <InstallExecuteSequence>
      <Custom Action='LaunchApp' After='InstallFinalize'>NOT Installed</Custom>
    </InstallExecuteSequence>
  </Product>
</Wix>
"@

$productFile = Join-Path $work 'Product.wxs'
$productWxs | Set-Content -Path $productFile -Encoding UTF8

Write-Host '[build_desktop_msi] Diagnostics avant compilation (échantillon de 5 fichiers):' -ForegroundColor DarkCyan
# Échantillon avant compilation (après sauvegarde)
[xml]$diag = Get-Content -Path $harvestWxs -Encoding UTF8
$nsm2 = New-Object System.Xml.XmlNamespaceManager($diag.NameTable)
$nsm2.AddNamespace('w','http://schemas.microsoft.com/wix/2006/wi') | Out-Null
$sample = @($diag.SelectNodes('//w:File',$nsm2) | Select-Object -First 5)
foreach($f in $sample){
  $src = $f.Source
  $exists = Test-Path $src
  if($exists){ $status='OK'; $color='Gray' } else { $status='MISSING'; $color='Red' }
  Write-Host ("  -> {0} : {1}" -f ($src -replace [regex]::Escape($stage+'\\'), ''), $status) -ForegroundColor $color
}

Write-Host '[build_desktop_msi] Compiling (candle)...' -ForegroundColor Cyan
& $candle.Path -o (Join-Path $work 'Harvest.wixobj') $harvestWxs
& $candle.Path -o (Join-Path $work 'Product.wixobj') $productFile

Write-Host '[build_desktop_msi] Linking (light)...' -ForegroundColor Cyan
$msiName = "$Name-folder-$Version.msi"
& $light.Path -sice:ICE38 -sice:ICE64 -o (Join-Path $out $msiName) (Join-Path $work 'Product.wixobj') (Join-Path $work 'Harvest.wixobj')

$msiOut = (Join-Path $out $msiName)
Write-Host "[build_desktop_msi] MSI created: $msiOut" -ForegroundColor Green

# Signature optionnelle (EXE interne + MSI) si paramètres fournis
$sigRequested = $false
if($SignPfxPath -or $CertThumbprint){ $sigRequested = $true }

# Si demandé: tenter d'auto-sélectionner un certificat de signature de code depuis le magasin spécifié
if($AutoPickCert -and -not $SignPfxPath -and -not $CertThumbprint){
  try {
    $storePath = "Cert:\$CertStoreLocation\$CertStoreName"
    if(Test-Path $storePath){
      $now = Get-Date
      $candidates = Get-ChildItem $storePath |
        Where-Object { $_.HasPrivateKey -and $_.NotAfter -gt $now -and $_.EnhancedKeyUsageList -and ($_.EnhancedKeyUsageList | Where-Object { $_.Oid.Value -eq '1.3.6.1.5.5.7.3.3' }) }
      if($CertSubjectFilter){ $candidates = $candidates | Where-Object { $_.Subject -like ("*{0}*" -f $CertSubjectFilter) } }
      $pick = $candidates | Sort-Object NotAfter -Descending | Select-Object -First 1
      if($pick){
        $CertThumbprint = $pick.Thumbprint
        Write-Host ("[build_desktop_msi] Cert auto-sélectionné: {0} (thumbprint={1}, expiration={2})" -f $pick.Subject, $pick.Thumbprint, $pick.NotAfter) -ForegroundColor DarkCyan
        $sigRequested = $true
      } else {
        Write-Warning "Aucun certificat de signature de code valide trouvé pour l'auto-sélection ($storePath)."
      }
    } else {
      Write-Warning "Magasin de certificats introuvable: $storePath"
    }
  } catch {
    Write-Warning "Erreur lors de l'auto-sélection du certificat: $_"
  }
}

function Resolve-SignTool {
  $st = Get-Command signtool.exe -ErrorAction SilentlyContinue
  if($st){ return $st.Path }
  # Tentative de localisation dans le Windows SDK (Windows Kits)
  $kitsRoot = 'C:\Program Files (x86)\Windows Kits\10\bin'
  if(Test-Path $kitsRoot){
    $candidates = Get-ChildItem -Path $kitsRoot -Directory -Recurse -ErrorAction SilentlyContinue | Sort-Object FullName -Descending
    foreach($c in $candidates){
      $x64 = Join-Path $c.FullName 'x64\signtool.exe'
      if(Test-Path $x64){ return $x64 }
      $x86 = Join-Path $c.FullName 'x86\signtool.exe'
      if(Test-Path $x86){ return $x86 }
      $arm64 = Join-Path $c.FullName 'arm64\signtool.exe'
      if(Test-Path $arm64){ return $arm64 }
    }
  }
  return $null
}

function New-SignArgs {
  param(
    [string]$TargetPath
  )
  $args = @('sign','/fd','sha256','/td','sha256')
  if($SignPfxPath){
    if(!(Test-Path $SignPfxPath)){
      throw "PFX non trouvé: $SignPfxPath"
    }
    $args += @('/f', $SignPfxPath)
    if($SignPfxPassword){ $args += @('/p', $SignPfxPassword) }
  } elseif($CertThumbprint){
    $args += @('/sha1', $CertThumbprint, '/s', $CertStoreName)
    if($CertStoreLocation -eq 'LocalMachine'){ $args += '/sm' }
  } else {
    throw 'Aucun certificat spécifié pour la signature.'
  }
  if($TimestampUrl){ $args += @('/tr', $TimestampUrl) }
  $args += @($TargetPath)
  return ,$args
}

if($sigRequested){
  $sigPath = Resolve-SignTool
  if(-not $sigPath){
    Write-Warning "signtool.exe introuvable. Installez le Windows SDK ou ajoutez signtool au PATH. Étape de signature sautée."
  } else {
    # 1) Tenter de signer l'EXE mis en scène pour que l'EXE embarqué soit également signé
    try {
      $exeToSign = Join-Path $stage 'TitanScraper.exe'
      if(Test-Path $exeToSign){
        Write-Host "[build_desktop_msi] Signature de l'EXE interne: $exeToSign" -ForegroundColor Cyan
        $exeArgs = New-SignArgs -TargetPath $exeToSign
        & $sigPath @exeArgs
        if($LASTEXITCODE -ne 0){ Write-Warning "Signature EXE échouée (code $LASTEXITCODE)." } else { Write-Host "[build_desktop_msi] EXE signé avec succès." -ForegroundColor Green }
      } else {
        Write-Host "[build_desktop_msi] Aucun EXE interne à signer trouvé à $exeToSign (ok)." -ForegroundColor DarkGray
      }
    } catch {
      Write-Warning "Erreur pendant la signature de l'EXE: $_"
    }
  }
}

# ... (compilation/link déjà effectués ci-dessus) ...

if($sigRequested){
  $sigPath = $sigPath
  if(-not $sigPath){ $sigPath = Resolve-SignTool }
  if(-not $sigPath){
    Write-Warning "signtool.exe introuvable. MSI final non signé."
  } else {
    try {
      Write-Host "[build_desktop_msi] Signature du MSI..." -ForegroundColor Cyan
      $msiArgs = New-SignArgs -TargetPath $msiOut
      & $sigPath @msiArgs
      if($LASTEXITCODE -ne 0){ Write-Warning "Echec de la signature du MSI (code $LASTEXITCODE)." } else { Write-Host "[build_desktop_msi] MSI signé avec succès." -ForegroundColor Green }
    } catch {
      Write-Warning "Erreur pendant la signature du MSI: $_"
    }
  }
}
