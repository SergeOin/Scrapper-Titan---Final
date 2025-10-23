#!/usr/bin/env bash
set -euo pipefail

# Build .app bundle with PyInstaller (via build_mac.sh) and package into a DMG.
# Also ensures the desktop icon is generated from Titan Scraper logo.png and assigned.

VERSION="${1:-}"
if [[ -z "${VERSION}" ]]; then
  if [[ -f VERSION ]]; then VERSION=$(awk 'NR==1{print; exit}' VERSION || echo "1.0.0"); else VERSION="1.0.0"; fi
fi
# Sanitize non-printable/BOM characters just in case
VERSION=$(printf '%s' "$VERSION" | LC_ALL=C tr -cd '[:print:]')
if [[ -z "$VERSION" ]]; then VERSION="1.0.0"; fi

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

echo "==> Packaging Titan Scraper for macOS (version $VERSION)"

echo "Building .app bundle via build_mac.sh..."
chmod +x build_mac.sh || true
bash ./build_mac.sh

APP_DIR="dist/TitanScraper/TitanScraper.app"
if [[ ! -d "$APP_DIR" ]]; then
  echo "WARN: App bundle not found at $APP_DIR; continuing — DMG builder will construct it from one-folder output if needed." >&2
fi

# Ensure Info.plist has icon set when ICNS exists and app already exists
if [[ -d "$APP_DIR" && -f build/icon.icns ]]; then
  PLIST="$APP_DIR/Contents/Info.plist"
  if /usr/libexec/PlistBuddy -c "Print :CFBundleIconFile" "$PLIST" >/dev/null 2>&1; then
    /usr/libexec/PlistBuddy -c "Set :CFBundleIconFile icon.icns" "$PLIST" || true
  else
    /usr/libexec/PlistBuddy -c "Add :CFBundleIconFile string icon.icns" "$PLIST" || true
  fi
  if [[ ! -f "$APP_DIR/Contents/Resources/icon.icns" ]]; then
    mkdir -p "$APP_DIR/Contents/Resources"
    cp build/icon.icns "$APP_DIR/Contents/Resources/icon.icns" || true
  fi
fi

echo "Creating DMG..."
./scripts/build_dmg.sh "$VERSION"
echo "DMG ready at dist/TitanScraper-$VERSION.dmg"

# If the app was constructed during DMG build, set icon now so PKG picks it up
if [[ -d "$APP_DIR" && -f build/icon.icns ]]; then
  PLIST="$APP_DIR/Contents/Info.plist"
  if /usr/libexec/PlistBuddy -c "Print :CFBundleIconFile" "$PLIST" >/dev/null 2>&1; then
    /usr/libexec/PlistBuddy -c "Set :CFBundleIconFile icon.icns" "$PLIST" || true
  else
    /usr/libexec/PlistBuddy -c "Add :CFBundleIconFile string icon.icns" "$PLIST" || true
  fi
  if [[ ! -f "$APP_DIR/Contents/Resources/icon.icns" ]]; then
    mkdir -p "$APP_DIR/Contents/Resources"
    cp build/icon.icns "$APP_DIR/Contents/Resources/icon.icns" || true
  fi
fi

echo "Creating PKG (bootstrapper-like installer)..."
./scripts/build_pkg.sh "$VERSION"
echo "PKG ready at dist/TitanScraper-$VERSION.pkg"

echo "Creating bootstrap DMG (includes PKG + Install.command)..."
./scripts/build_bootstrap_dmg.sh "$VERSION"
echo "Bootstrap DMG ready at dist/TitanScraper-bootstrap-$VERSION.dmg"
