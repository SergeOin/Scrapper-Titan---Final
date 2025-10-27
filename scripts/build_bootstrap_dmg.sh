#!/usr/bin/env bash
set -euo pipefail

# Build a "bootstrapper" DMG for macOS that contains a one-click Install.command
# which installs the TitanScraper.pkg to /Applications and launches the app.
#
# Optional signing:
# - If SIGN_DMG_IDENTITY is set to a valid codesign identity (e.g., "Developer ID Application: Your Org (TEAMID)"),
#   the DMG will be code-signed after creation. Note: code-signing a DMG is optional; Gatekeeper primarily checks the
#   app/PKG signature and notarization. For public distribution, use Apple Developer ID and notarization.
#
# Output: dist/TitanScraper-bootstrap-<version>.dmg

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  if [[ -f VERSION ]]; then VERSION=$(awk 'NR==1{print; exit}' VERSION || echo "1.0.0"); else VERSION="1.0.0"; fi
fi

APP_NAME="TitanScraper"
PKG_PATH="dist/${APP_NAME}-${VERSION}.pkg"
DMG_PATH="dist/${APP_NAME}-bootstrap-${VERSION}.dmg"

if [[ ! -f "$PKG_PATH" ]]; then
  echo "PKG not found at $PKG_PATH — building PKG first..."
  ./scripts/build_pkg.sh "$VERSION"
fi

if [[ ! -f "$PKG_PATH" ]]; then
  echo "ERROR: PKG still not found at $PKG_PATH" >&2
  exit 1
fi

TMPDIR=$(mktemp -d)
STAGE="$TMPDIR/${APP_NAME}-bootstrap-stage"
mkdir -p "$STAGE"

# Copy the PKG
cp -f "$PKG_PATH" "$STAGE/"

# Create Install.command that runs the installer and opens the app
cat > "$STAGE/Install.command" <<'SH'
#!/bin/bash
set -e
cd "$(dirname "$0")"

# Find the pkg in the DMG contents
PKG_FILE=$(ls -1 *.pkg 2>/dev/null | head -n 1)
if [[ -z "$PKG_FILE" ]]; then
  echo "Aucun fichier .pkg trouvé dans ce disque."
  exit 1
fi

echo "Installation de TitanScraper (sudo peut être requis)..."
sudo /usr/sbin/installer -pkg "$PKG_FILE" -target /

APP="/Applications/TitanScraper.app"
if [[ -d "$APP" ]]; then
  # Retirer le flag de quarantaine si présent (best-effort)
  xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true
  echo "Ouverture de l'application..."
  open "$APP" 2>/dev/null || true
fi

echo "Installation terminée. Vous pouvez éjecter ce disque."
exit 0
SH
chmod +x "$STAGE/Install.command"

# Add a short README
cat > "$STAGE/README.txt" <<TXT
TitanScraper – Installation

1) Double-cliquez sur "Install.command".
2) Entrez votre mot de passe si demandé (installation système standard).
3) L'application sera copiée dans /Applications puis lancée.

Alternative: vous pouvez aussi double-cliquer sur le fichier .pkg pour lancer
l'installateur Apple par défaut.
TXT

# Optional convenience: Applications symlink for drag-and-drop scenarios
ln -s /Applications "$STAGE/Applications" 2>/dev/null || true

echo "Creating bootstrap DMG..."
hdiutil create -volname "$APP_NAME Installer" -srcfolder "$STAGE" -ov -format UDZO "$DMG_PATH"
echo "Bootstrap DMG created: $DMG_PATH"

# Optionally sign the DMG if identity provided
if [[ -n "${SIGN_DMG_IDENTITY:-}" ]]; then
  echo "Signing DMG with identity: $SIGN_DMG_IDENTITY"
  codesign --force --timestamp --sign "$SIGN_DMG_IDENTITY" "$DMG_PATH"
  echo "Signed DMG at: $DMG_PATH"
fi
