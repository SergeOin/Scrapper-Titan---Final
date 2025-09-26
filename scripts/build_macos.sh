#!/usr/bin/env bash
set -euo pipefail

APP_NAME="TitanScraper"
VENV=".venv"

if [[ ! -d "$VENV" ]]; then
  python3 -m venv "$VENV"
fi
source "$VENV/bin/activate"

pip install --upgrade pip wheel setuptools
pip install -r requirements.txt
pip install -r desktop/requirements-desktop.txt
pip install pyinstaller==6.10.0 pillow==10.4.0

# Derive version
if [[ -f VERSION ]]; then
  VERSION_STR=$(cat VERSION | tr -d '\n' )
else
  VERSION_STR="1.0.0"
fi

echo "Building macOS app (version $VERSION_STR)"
pyinstaller desktop/pyinstaller.spec

# Package into .app if not already
if [[ -d dist/TitanScraper ]]; then
  APPDIR="dist/${APP_NAME}.app"
  mkdir -p "$APPDIR/Contents/MacOS"
  mkdir -p "$APPDIR/Contents/Resources"
  # Basic Info.plist
  cat > "$APPDIR/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>${APP_NAME}</string>
  <key>CFBundleDisplayName</key><string>${APP_NAME}</string>
  <key>CFBundleIdentifier</key><string>com.example.${APP_NAME,,}</string>
  <key>CFBundleVersion</key><string>${VERSION_STR}</string>
  <key>CFBundleShortVersionString</key><string>${VERSION_STR}</string>
  <key>LSMinimumSystemVersion</key><string>10.15</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSPrincipalClass</key><string>NSApplication</string>
  <key>CFBundleExecutable</key><string>TitanScraper</string>
</dict>
</plist>
EOF
  # Move built content into .app bundle
  cp -R dist/TitanScraper/* "$APPDIR/Contents/MacOS/"
fi

echo "(Optional) Create DMG with create-dmg once installed:"
echo "  create-dmg --volname ${APP_NAME} --background background.png --window-size 800 400 --icon-size 128 --app-drop-link 600 185 ${APP_NAME}-${VERSION_STR}.dmg dist"
