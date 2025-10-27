# Titan Scraper – Packaging and Installation

This guide shows how to build cross-platform installers (.MSI for Windows and .DMG for macOS) that bundle the backend, frontend and database, create a desktop shortcut, and auto-install missing prerequisites.

## What gets packaged
- Backend: FastAPI server (packaged via PyInstaller) with bundled `server/templates` and static `web/blocked` build when available.
- Frontend: The React UI in `web/blocked` (if Node is available during build; a fallback page is served otherwise).
- Database: Local SQLite file path is set to a per-user data directory, created on first run.
- Icon: The app icon is generated from `Titan Scraper logo.png`.
- Shortcuts:
  - Windows: Start Menu and Desktop shortcuts created by the MSI.
  - macOS: A Desktop alias is created on first launch (best-effort) and the DMG includes an Applications link.
- Prerequisites auto-install:
  - Windows: Microsoft Edge WebView2 Runtime is auto-detected and installed silently on first run if missing. Playwright Chromium is fetched on first launch if not found.
  - macOS: Playwright Chromium is fetched on first launch if not found.

## Windows (.MSI)
Prerequisites:
- Python 3.11+ (for building) and WiX Toolset v3 in PATH (candle.exe, light.exe, heat.exe)
- Node.js (optional) for building the frontend

Build steps:
1) Build the app and MSI
```
./scripts/package_windows.ps1
```
Artifacts:
- App: `dist/TitanScraper/`
- MSI: `dist/msi/TitanScraper-folder-<version>.msi`

Notes:
- The MSI embeds CABs by default so installation succeeds even if a .cab file would otherwise be missing.
- Desktop and Start Menu shortcuts are created automatically.
- If WebView2 Runtime is missing, the app will install it silently on first run (using a bootstrapper bundled when available, or by prompting the official installer).

### Optional: Bootstrapper (WiX Burn) and code signing
You can produce a self-contained bootstrapper EXE that installs prerequisites (VC++ Redistributable and WebView2) and then your MSI. The bootstrapper builder supports Authenticode signing via Microsoft SignTool.

Build + sign in one step using a PFX:
```
./scripts/build_bootstrapper.ps1 -SignPfxPath C:\path\to\codesign.pfx -SignPfxPassword 'your-password'
```

Build + sign using a certificate already installed in the Windows certificate store (thumbprint):
```
./scripts/build_bootstrapper.ps1 -CertThumbprint 'YOURTHUMBPRINTHEX' -CertStoreLocation LocalMachine -CertStoreName My
```

Let the script auto-pick a valid Code Signing cert from your store (optionally filtered by subject):
```
./scripts/build_bootstrapper.ps1 -AutoPickCert -CertSubjectFilter 'Your Org Name'
```

Notes:
- The script will auto-locate `signtool.exe` from the Windows 10/11 SDK (or fall back to PATH). Install the Windows SDK if not already present.
- Timestamping uses `http://timestamp.digicert.com` with SHA-256 for file and timestamp digest.
- Output: `dist/msi/TitanScraper-Bootstrapper.exe` (signed when signing options provided).

You can also (re)sign existing `.msi` and `.exe` artifacts with:
```
./scripts/sign_windows_artifacts.ps1 -ArtifactsDir .\dist\msi -SignPfxPath C:\path\to\codesign.pfx
```

### Free option for development: self-signed certificate
For internal/testing only, you can use a self-signed Code Signing certificate. This is free but will not build SmartScreen reputation; users may still see "Application inconnue" with the option to "Exécuter quand même".

Create a dev certificate, export PFX/CER, and trust it locally:
```
./scripts/dev_codesign_setup.ps1 -ExportPfx -InstallTrust -Subject 'CN=TitanScraper Dev'
```

Sign the bootstrapper using the installed cert (thumbprint is printed at the end):
```
./scripts/build_bootstrapper.ps1 -CertThumbprint '<PRINTED_THUMBPRINT>' -CertStoreLocation CurrentUser -CertStoreName My
```

Trust the cert on other developer/test machines (use the CER produced in dist/signing):
```
./scripts/install_trusted_dev_cert.ps1 -CerPath .\dist\signing\dev-codesign.cer
```

Note:
- Self-signed is suitable for lab, CI test, or internal distribution. Public releases should use a commercial Code Signing certificate.
- If you prefer, you can skip PFX and just use `-AutoPickCert` to let the build script select the dev cert from your store.

## macOS (.DMG and .PKG)
Prerequisites:
- Xcode command line tools (for hdiutil)
- Python 3.11+ for building
- Node.js (optional) for building the frontend

Build steps:
1) Build the app and both DMG and PKG
```
./scripts/package_macos.sh
```
Artifacts:
- .app bundle: `dist/TitanScraper/TitanScraper.app`
- DMG: `dist/TitanScraper-<version>.dmg`
- PKG: `dist/TitanScraper-<version>.pkg`

Notes:
- The DMG includes a link to Applications for easy drag-and-drop.
- The PKG installs the app into `/Applications` and, in postinstall, best-effort creates a Desktop alias for the console user.
- On first launch, the app attempts to fetch Playwright browsers if missing; this may take a few minutes.

### Optional: macOS bootstrapper DMG and signing
You can build a bootstrap DMG that includes the PKG plus a one-click `Install.command` script:

```
./scripts/build_bootstrap_dmg.sh <version>
```

Signing options:
- Sign the PKG (recommended for public distribution): set an environment variable with your Apple Developer ID Installer identity, then build:
  - macOS (zsh/bash):
    ```
    export SIGN_IDENTITY_INSTALLER="Developer ID Installer: Your Org (TEAMID)"
    ./scripts/build_pkg.sh <version>
    ```
  - The signed PKG is then picked up by `build_bootstrap_dmg.sh`.

- Optionally sign the DMG itself (less critical than PKG/app signing):
  - macOS (zsh/bash):
    ```
    export SIGN_DMG_IDENTITY="Developer ID Application: Your Org (TEAMID)"
    ./scripts/build_bootstrap_dmg.sh <version>
    ```

Notarization (public releases):
- For best end-user experience (no Gatekeeper prompts), notarize the signed app/PKG via Apple (Developer account required). This repo includes a template in CI for macOS signing/notarization; adapt it with your credentials.

Free dev/internal option (no Apple Developer account):
- CI: Build, sign, and notarize the bootstrapper DMG
To automate distribution, use the GitHub Actions workflow `.github/workflows/build-macos-bootstrapper.yml`. Configure the following repository secrets:

- MAC_CERT_P12: Base64 of your Developer ID Installer .p12
- MAC_CERT_PASSWORD: Password for the .p12
- MAC_KEYCHAIN_PASSWORD: Arbitrary password used to create a temporary keychain on the runner
- MAC_CERT_IDENTITY_INSTALLER: Exact installer identity string (e.g., Developer ID Installer: Your Org (TEAMID))
- NOTARY_API_KEY_ID: App Store Connect API Key ID
- NOTARY_API_ISSUER_ID: App Store Connect Issuer ID
- NOTARY_API_KEY_BASE64: Base64 of the API key .p8 file
- (Optional) MAC_CERT_IDENTITY_APPLICATION: If set, the DMG itself will be codesigned

How to run:
- Trigger manually: Actions > build-macos-bootstrapper > Run workflow, optionally provide a version string. If omitted, it uses the git tag (vX.Y.Z) or the VERSION file.
- On tag push vX.Y.Z: the workflow runs automatically, producing:
  - dist/TitanScraper-<version>.pkg (signed and stapled when secrets provided)
  - dist/TitanScraper-bootstrap-<version>.dmg (signed/notarized when configured)
  - Both files uploaded as workflow artifacts.
- You can ship unsigned PKG/DMG for internal testing, but Gatekeeper may warn on first open. Users can Control-click → Open to bypass once, or remove the quarantine attribute after copying locally:
  - `xattr -dr com.apple.quarantine /Applications/TitanScraper.app`
- This is only suitable for internal/lab usage; public distribution should use a Developer ID and notarization.

## Post-install verification
- Windows:
```
./scripts/post_install_verify_windows.ps1
```
- macOS:
```
./scripts/post_install_verify_macos.sh
```
These probes check `/health` and `/blocked-accounts` to confirm the backend is running and the frontend route responds.

## Troubleshooting
- If the `web/blocked` frontend isn’t built, the app serves a fallback informational page at `/blocked`.
- Playwright browsers are installed on first run to a per-user cache. This may take a few minutes depending on your network.
- For MSI signing, see `scripts/build_desktop_msi.ps1` which supports both PFX and certificate store signing.