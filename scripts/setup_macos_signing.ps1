#!/usr/bin/env pwsh
# =============================================================================
# Script de configuration automatique pour la signature macOS via GitHub Actions
# =============================================================================

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "   CONFIGURATION AUTOMATIQUE - SIGNATURE macOS pour GitHub Actions   " -ForegroundColor Cyan  
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Ce script va vous guider pour configurer la signature et notarisation"
Write-Host "Apple afin de creer des installateurs macOS (.dmg/.pkg) signes."
Write-Host ""
Write-Host "PREREQUIS :"
Write-Host "  - Compte Apple Developer (99 dollars/an)"
Write-Host "  - GitHub CLI installe (gh)"
Write-Host "  - Acces au repo GitHub"
Write-Host ""

# Verifier GitHub CLI
$ghInstalled = Get-Command gh -ErrorAction SilentlyContinue
if (-not $ghInstalled) {
    Write-Host "GitHub CLI (gh) n'est pas installe." -ForegroundColor Yellow
    Write-Host "Installation avec winget..." -ForegroundColor Yellow
    winget install GitHub.cli
    Write-Host "Veuillez relancer ce script apres l'installation." -ForegroundColor Yellow
    exit 1
}

# Verifier authentification GitHub
try {
    $null = gh auth status 2>&1
} catch {
    Write-Host "Vous n'etes pas connecte a GitHub CLI." -ForegroundColor Yellow
    Write-Host "Lancement de l'authentification..." -ForegroundColor Yellow
    gh auth login
}

Write-Host "----------------------------------------------------------------------" -ForegroundColor DarkGray

# =============================================================================
# ETAPE 1 : Informations Apple Developer
# =============================================================================
Write-Host ""
Write-Host "ETAPE 1/4 : INFORMATIONS APPLE DEVELOPER" -ForegroundColor Green
Write-Host ""
Write-Host "Connectez-vous a : https://developer.apple.com/account"
Write-Host ""
Write-Host "Appuyez sur Entree quand vous etes connecte..." -ForegroundColor Yellow
Read-Host | Out-Null

# =============================================================================
# ETAPE 2 : Cle API App Store Connect
# =============================================================================
Write-Host ""
Write-Host "----------------------------------------------------------------------" -ForegroundColor DarkGray
Write-Host ""
Write-Host "ETAPE 2/4 : CREATION DE LA CLE API APP STORE CONNECT" -ForegroundColor Green
Write-Host ""
Write-Host "Cette cle permet la notarisation automatique (validation Apple)."
Write-Host ""
Write-Host "INSTRUCTIONS :"
Write-Host "1. Allez sur : https://appstoreconnect.apple.com/access/integrations/api"
Write-Host "2. Cliquez sur le '+' pour creer une nouvelle cle"
Write-Host "3. Nom : 'TitanScraper CI' (ou ce que vous voulez)"
Write-Host "4. Acces : 'Developer' (suffisant pour notarisation)"
Write-Host "5. Cliquez 'Generate'"
Write-Host "6. IMPORTANT : Telechargez le fichier .p8 (une seule fois possible !)"
Write-Host "7. Notez l'ID de la cle et l'Issuer ID affiches sur la page"
Write-Host ""
Write-Host "Appuyez sur Entree quand vous avez cree la cle et telecharge le .p8..." -ForegroundColor Yellow
Read-Host | Out-Null

# Demander les informations
Write-Host ""
Write-Host "Entrez les informations de votre cle API :" -ForegroundColor Cyan

$keyId = Read-Host "   Key ID (ex: ABC123XYZ)"
$issuerId = Read-Host "   Issuer ID (ex: 12345678-1234-1234-1234-123456789012)"
$p8Path = Read-Host "   Chemin vers le fichier .p8 telecharge (glissez-deposez)"

# Nettoyer le chemin
$p8Path = $p8Path.Trim('"').Trim("'")

if (-not (Test-Path $p8Path)) {
    Write-Host "Fichier .p8 introuvable : $p8Path" -ForegroundColor Red
    exit 1
}

# Encoder en base64
$p8Content = Get-Content $p8Path -Raw
$p8Base64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($p8Content))

Write-Host "Cle API encodee avec succes" -ForegroundColor Green

# =============================================================================
# ETAPE 3 : Certificat Developer ID
# =============================================================================
Write-Host ""
Write-Host "----------------------------------------------------------------------" -ForegroundColor DarkGray
Write-Host ""
Write-Host "ETAPE 3/4 : CERTIFICAT DEVELOPER ID" -ForegroundColor Green
Write-Host ""
Write-Host "Vous avez besoin d'un certificat 'Developer ID Installer' pour signer."
Write-Host ""
Write-Host "OPTION A - Si vous avez DEJA un certificat exporte en .p12 :"
Write-Host "   Entrez le chemin du fichier .p12"
Write-Host ""
Write-Host "OPTION B - Si vous n'avez PAS de certificat :"
Write-Host "   Tapez 'skip' pour continuer sans (vous pourrez l'ajouter plus tard)"
Write-Host ""

$certChoice = Read-Host "Chemin du .p12 OU 'skip'"

$p12Base64 = ""
$p12PasswordPlain = ""
$identityInstaller = ""
$identityApp = ""

if ($certChoice -ne "skip" -and $certChoice -ne "") {
    $p12Path = $certChoice.Trim('"').Trim("'")
    
    if (Test-Path $p12Path) {
        $p12PasswordSecure = Read-Host "   Mot de passe du .p12" -AsSecureString
        $p12PasswordPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
            [Runtime.InteropServices.Marshal]::SecureStringToBSTR($p12PasswordSecure)
        )
        
        # Encoder en base64
        $p12Bytes = [System.IO.File]::ReadAllBytes($p12Path)
        $p12Base64 = [Convert]::ToBase64String($p12Bytes)
        
        Write-Host ""
        Write-Host "Entrez le nom exact de l'identite de signature :" -ForegroundColor Cyan
        Write-Host "(Format: 'Developer ID Installer: Votre Nom (TEAMID)')" -ForegroundColor Gray
        $identityInstaller = Read-Host "   Identity Installer"
        
        Write-Host "(Format: 'Developer ID Application: Votre Nom (TEAMID)' - optionnel)" -ForegroundColor Gray
        $identityApp = Read-Host "   Identity Application (optionnel, Entree pour ignorer)"
        
        Write-Host "Certificat encode avec succes" -ForegroundColor Green
    } else {
        Write-Host "Fichier .p12 introuvable, on continue sans certificat." -ForegroundColor Yellow
    }
} else {
    Write-Host ""
    Write-Host "Pas de certificat configure pour l'instant." -ForegroundColor Yellow
    Write-Host "Le build fonctionnera mais ne sera pas signe." -ForegroundColor Yellow
    Write-Host "Vous pourrez ajouter les secrets GitHub manuellement plus tard." -ForegroundColor Yellow
}

# =============================================================================
# ETAPE 4 : Configuration GitHub Secrets
# =============================================================================
Write-Host ""
Write-Host "----------------------------------------------------------------------" -ForegroundColor DarkGray
Write-Host ""
Write-Host "ETAPE 4/4 : CONFIGURATION DES SECRETS GITHUB" -ForegroundColor Green
Write-Host ""

# Determiner le repo
$repoOwner = "SergeOin"
$repoName = "Scrapper-Titan---Final"
$repo = "$repoOwner/$repoName"

Write-Host "Configuration des secrets pour : $repo" -ForegroundColor Cyan
Write-Host ""

# Generer un mot de passe aleatoire pour le keychain
$keychainPassword = -join ((65..90) + (97..122) + (48..57) | Get-Random -Count 32 | ForEach-Object {[char]$_})

# Preparer les secrets
$secrets = @{}
$secrets["NOTARY_API_KEY_ID"] = $keyId
$secrets["NOTARY_API_ISSUER_ID"] = $issuerId
$secrets["NOTARY_API_KEY_BASE64"] = $p8Base64
$secrets["MAC_KEYCHAIN_PASSWORD"] = $keychainPassword

if ($p12Base64) {
    $secrets["MAC_CERT_P12"] = $p12Base64
    $secrets["MAC_CERT_PASSWORD"] = $p12PasswordPlain
    $secrets["MAC_CERT_IDENTITY_INSTALLER"] = $identityInstaller
    if ($identityApp) {
        $secrets["MAC_CERT_IDENTITY_APPLICATION"] = $identityApp
    }
}

Write-Host "Secrets a configurer :" -ForegroundColor Yellow
foreach ($key in $secrets.Keys) {
    $val = $secrets[$key]
    if ($val) {
        if ($val.Length -gt 20) {
            $displayValue = $val.Substring(0, 20) + "..."
        } else {
            $displayValue = $val
        }
        Write-Host "  + $key = $displayValue" -ForegroundColor Gray
    }
}

Write-Host ""
$confirm = Read-Host "Voulez-vous configurer ces secrets sur GitHub ? (o/n)"

if ($confirm -eq "o" -or $confirm -eq "O" -or $confirm -eq "oui" -or $confirm -eq "y") {
    Write-Host ""
    Write-Host "Configuration des secrets GitHub..." -ForegroundColor Cyan
    
    foreach ($key in $secrets.Keys) {
        $val = $secrets[$key]
        if ($val) {
            Write-Host "  Configuring $key..." -NoNewline
            try {
                $val | gh secret set $key -R $repo 2>$null
                Write-Host " OK" -ForegroundColor Green
            } catch {
                Write-Host " ERREUR" -ForegroundColor Red
            }
        }
    }
    
    Write-Host ""
    Write-Host "----------------------------------------------------------------------" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "CONFIGURATION TERMINEE !" -ForegroundColor Green
    Write-Host ""
    
} else {
    Write-Host ""
    Write-Host "Configuration annulee. Vous pouvez relancer le script plus tard." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "                        PROCHAINES ETAPES                             " -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "1. Pour lancer le build macOS :" -ForegroundColor White
Write-Host ""
Write-Host "   Option A - Via tag (recommande pour releases) :" -ForegroundColor Gray
Write-Host "     git tag v1.3.19" -ForegroundColor Yellow
Write-Host "     git push origin v1.3.19" -ForegroundColor Yellow
Write-Host ""
Write-Host "   Option B - Manuellement :" -ForegroundColor Gray
Write-Host "     GitHub > Actions > 'build-macos-bootstrapper' > Run workflow" -ForegroundColor Yellow
Write-Host ""
Write-Host "2. Les artifacts seront dans l'onglet Actions de GitHub :" -ForegroundColor White
Write-Host "     TitanScraper-bootstrap-X.X.X.dmg (installateur complet)" -ForegroundColor Gray
Write-Host "     TitanScraper-X.X.X.pkg (package seul)" -ForegroundColor Gray
Write-Host ""
Write-Host "3. Telechargez les artifacts et distribuez-les !" -ForegroundColor White
Write-Host ""
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""

# Sauvegarder un fichier de reference
$refContent = "# Configuration macOS Signing - Reference`n"
$refContent += "# Genere le $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')`n`n"
$refContent += "NOTARY_API_KEY_ID=$keyId`n"
$refContent += "NOTARY_API_ISSUER_ID=$issuerId`n"
$refContent += "MAC_CERT_IDENTITY_INSTALLER=$identityInstaller`n"
$refContent += "MAC_CERT_IDENTITY_APPLICATION=$identityApp`n`n"
$refContent += "# Les valeurs sensibles sont stockees uniquement dans GitHub Secrets.`n"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$refPath = Join-Path (Split-Path -Parent $scriptDir) "macos_signing_reference.txt"
$refContent | Out-File -FilePath $refPath -Encoding UTF8
Write-Host "Reference sauvegardee : $refPath" -ForegroundColor Gray
Write-Host ""

Write-Host "Appuyez sur Entree pour terminer..." -ForegroundColor Yellow
Read-Host | Out-Null
