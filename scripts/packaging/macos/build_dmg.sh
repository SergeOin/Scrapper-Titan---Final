#!/usr/bin/env bash
set -euo pipefail
APP_NAME="LinkedInScraper"
VERSION="${VERSION:-0.0.0}"
SPEC_FILE="${SPEC_FILE:-linkedin_scraper.spec}"

echo "==> Building macOS app bundle with PyInstaller"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
source .venv/bin/activate
pip install -U pip wheel setuptools
pip install -r requirements.txt
pip install pyinstaller==6.10.0

pyinstaller "$SPEC_FILE" -y --clean --name "$APP_NAME"
APP_DIR="dist/$APP_NAME"
if [ ! -d "$APP_DIR" ]; then
  echo "PyInstaller output missing: $APP_DIR" >&2; exit 1
fi

DMG_TMP="build/${APP_NAME}_dmg"
rm -rf "$DMG_TMP"; mkdir -p "$DMG_TMP"/dmg
cp -R "$APP_DIR" "$DMG_TMP"/dmg/
# Create symlink to /Applications for drag-and-drop style
ln -s /Applications "$DMG_TMP"/dmg/Applications

DMG_NAME="${APP_NAME}_${VERSION}.dmg"

hdiutil create -volname "$APP_NAME" -srcfolder "$DMG_TMP/dmg" -ov -format UDZO "build/$DMG_NAME"

echo "DMG created: build/$DMG_NAME"
