#!/usr/bin/env bash
set -euo pipefail

# Build a signed/unsigned macOS .pkg installer that installs TitanScraper.app to /Applications
# and optionally creates a Desktop alias for the console user (best-effort) via postinstall script.

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  if [[ -f VERSION ]]; then VERSION=$(tr -d '\r\n' < VERSION); else VERSION="1.0.0"; fi
fi

APP_DIR="dist/TitanScraper/TitanScraper.app"
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
