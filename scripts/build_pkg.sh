#!/usr/bin/env bash
set -euo pipefail

# Build a signed/unsigned macOS .pkg installer that installs TitanScraper.app to /Applications
# and optionally creates a Desktop alias for the console user (best-effort) via postinstall script.
#
# Signing (optional):
# - Set SIGN_IDENTITY_INSTALLER="Developer ID Installer: Your Org (TEAMID)" to sign with productsign.
# - The identity must be in the current keychain (typically login) and unlocked.
# - For dev-only internal usage you can leave it unsigned; Gatekeeper will warn on first open unless bypassed.

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  if [[ -f VERSION ]]; then VERSION=$(awk 'NR==1{print; exit}' VERSION || echo "1.0.0"); else VERSION="1.0.0"; fi
fi

NAME="TitanScraper"
APP_DIR="dist/${NAME}/${NAME}.app"

# If the .app bundle is missing, but the one-folder dist exists, construct the .app now
if [[ ! -d "$APP_DIR" ]]; then
  if [[ -d "dist/${NAME}" ]]; then
    echo "App bundle not found; constructing $APP_DIR from one-folder dist..."
    STAGE_APP="build/${NAME}.app"
    rm -rf "$STAGE_APP"
    mkdir -p "$STAGE_APP/Contents/MacOS" "$STAGE_APP/Contents/Resources"
    cat > "$STAGE_APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>${NAME}</string>
  <key>CFBundleDisplayName</key><string>${NAME}</string>
  <key>CFBundleIdentifier</key><string>com.titanpartners.titanscraper</string>
  <key>CFBundleVersion</key><string>${VERSION}</string>
  <key>CFBundleShortVersionString</key><string>${VERSION}</string>
  <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
  <key>LSMinimumSystemVersion</key><string>10.15</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSPrincipalClass</key><string>NSApplication</string>
  <key>CFBundleExecutable</key><string>${NAME}</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleIconFile</key><string>icon.icns</string>
</dict>
</plist>
EOF
    if command -v rsync >/dev/null 2>&1; then
      rsync -a --exclude "${NAME}.app" "dist/${NAME}/" "$STAGE_APP/Contents/MacOS/"
    else
      cp -R "dist/${NAME}/"* "$STAGE_APP/Contents/MacOS/" 2>/dev/null || true
    fi
    # Ensure main executable exists and is executable
    if [[ -f "$STAGE_APP/Contents/MacOS/${NAME}" ]]; then
      chmod +x "$STAGE_APP/Contents/MacOS/${NAME}" || true
    fi
    # If icon exists from build step, include it
    if [[ -f "build/icon.icns" ]]; then
      cp -f "build/icon.icns" "$STAGE_APP/Contents/Resources/icon.icns" || true
    fi
    mkdir -p "dist/${NAME}"
    rm -rf "$APP_DIR"
    cp -R "$STAGE_APP" "$APP_DIR"
    echo "App bundle created at $APP_DIR"
  fi
fi

if [[ ! -d "$APP_DIR" ]]; then
  echo "TitanScraper.app not found at $APP_DIR — building app first..."
  ./build_mac.sh
fi

if [[ ! -d "$APP_DIR" ]]; then
  echo "ERROR: App bundle still not found at $APP_DIR" >&2
  exit 1
fi

PKG_WORK="build/pkg"
SCRIPTS_DIR="$PKG_WORK/scripts"
OUT_DIR="dist"
IDENTIFIER="com.titanpartners.titanscraper"

rm -rf "$PKG_WORK"
mkdir -p "$SCRIPTS_DIR" "$OUT_DIR"

# Create postinstall script (best-effort Desktop alias)
cat > "$SCRIPTS_DIR/postinstall" <<'POST'
#!/bin/bash
set -e

# Attempt to create a Desktop symlink for the console user (best-effort)
APP_PATH="/Applications/TitanScraper.app"
USER_NAME=$(stat -f%Su /dev/console 2>/dev/null || true)
if [[ -n "$USER_NAME" && -d "/Users/$USER_NAME" ]]; then
  USER_HOME=$(dscl . -read "/Users/$USER_NAME" NFSHomeDirectory 2>/dev/null | awk '{print $2}')
  if [[ -z "$USER_HOME" ]]; then USER_HOME="/Users/$USER_NAME"; fi
  DESKTOP="$USER_HOME/Desktop"
  if [[ -d "$DESKTOP" && -w "$DESKTOP" ]]; then
    ln -sf "$APP_PATH" "$DESKTOP/Titan Scraper.app" 2>/dev/null || true
  fi
fi

exit 0
POST
chmod +x "$SCRIPTS_DIR/postinstall"

COMPONENT_PKG="$PKG_WORK/TitanScraper-component.pkg"
FINAL_PKG="$OUT_DIR/TitanScraper-$VERSION.pkg"

echo "Building component pkg..."
pkgbuild \
  --component "$APP_DIR" \
  --install-location "/Applications" \
  --scripts "$SCRIPTS_DIR" \
  --identifier "$IDENTIFIER" \
  --version "$VERSION" \
  "$COMPONENT_PKG"

echo "Wrapping with productbuild..."
productbuild \
  --package "$COMPONENT_PKG" \
  --identifier "$IDENTIFIER" \
  --version "$VERSION" \
  "$FINAL_PKG"

echo "PKG ready at $FINAL_PKG"

# Optional signing using productsign if an identity is provided
if [[ -n "${SIGN_IDENTITY_INSTALLER:-}" ]]; then
  SIGNED_PKG="$OUT_DIR/TitanScraper-$VERSION-signed.pkg"
  echo "Signing PKG with identity: $SIGN_IDENTITY_INSTALLER"
  productsign --sign "$SIGN_IDENTITY_INSTALLER" "$FINAL_PKG" "$SIGNED_PKG"
  mv -f "$SIGNED_PKG" "$FINAL_PKG"
  echo "Signed PKG ready at $FINAL_PKG"
fi
