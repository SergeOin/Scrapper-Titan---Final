#!/usr/bin/env bash
set -euo pipefail

# Build .app bundle with PyInstaller (via build_mac.sh) and package into a DMG.
# Also ensures the desktop icon is generated from Titan Scraper logo.png and assigned.

VERSION="${1:-}"
if [[ -z "${VERSION}" ]]; then
  if [[ -f VERSION ]]; then VERSION=$(awk 'NR==1{print; exit}' VERSION || echo "1.0.0"); else VERSION="1.0.0"; fi
fi

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

echo "==> Packaging Titan Scraper for macOS (version $VERSION)"

if [[ -f "Titan Scraper logo.png" ]]; then
  echo "Generating ICNS from PNG..."
  # Prefer venv python if available (will have Pillow), fallback to system python.
  if [[ -x .venv/bin/python ]]; then
    .venv/bin/python scripts/util_make_icon.py -i "Titan Scraper logo.png" -o build/icon.icns || true
  else
    python3 scripts/util_make_icon.py -i "Titan Scraper logo.png" -o build/icon.icns || true
  fi
fi

echo "Building .app bundle via build_mac.sh..."
chmod +x build_mac.sh || true
bash ./build_mac.sh

APP_DIR="dist/TitanScraper/TitanScraper.app"
if [[ ! -d "$APP_DIR" ]]; then
  echo "ERROR: App bundle not found at $APP_DIR" >&2
  exit 1
fi

# Ensure Info.plist has icon set when ICNS exists
if [[ -f build/icon.icns ]]; then
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

echo "Creating PKG (bootstrapper-like installer)..."
./scripts/build_pkg.sh "$VERSION"
echo "PKG ready at dist/TitanScraper-$VERSION.pkg"

echo "Creating bootstrap DMG (includes PKG + Install.command)..."
./scripts/build_bootstrap_dmg.sh "$VERSION"
echo "Bootstrap DMG ready at dist/TitanScraper-bootstrap-$VERSION.dmg"
