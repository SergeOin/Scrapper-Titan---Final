#!/usr/bin/env bash
set -euo pipefail

NAME="TitanScraper"
APP_PATH="dist/${NAME}/${NAME}.app"
DMG_PATH="dist/${NAME}-${1:-1.0.0}.dmg"

# If the .app bundle is missing, but the one-folder dist exists, construct the .app now (best-effort)
if [ ! -d "$APP_PATH" ]; then
  if [ -d "dist/${NAME}" ]; then
    echo "App bundle not found; constructing $APP_PATH from one-folder dist..."
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
  <key>CFBundleIdentifier</key><string>com.example.${NAME,,}</string>
  <key>CFBundleVersion</key><string>1.0.0</string>
  <key>CFBundleShortVersionString</key><string>1.0.0</string>
  <key>LSMinimumSystemVersion</key><string>10.15</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSPrincipalClass</key><string>NSApplication</string>
  <key>CFBundleExecutable</key><string>${NAME}</string>
  <key>CFBundlePackageType</key><string>APPL</string>
</dict>
</plist>
EOF
    if command -v rsync >/dev/null 2>&1; then
      rsync -a --exclude "${NAME}.app" "dist/${NAME}/" "$STAGE_APP/Contents/MacOS/"
    else
      cp -R "dist/${NAME}/"* "$STAGE_APP/Contents/MacOS/" 2>/dev/null || true
    fi
    mkdir -p "dist/${NAME}"
    rm -rf "$APP_PATH"
    cp -R "$STAGE_APP" "$APP_PATH"
  fi
fi

if [ ! -d "$APP_PATH" ]; then
  echo "App not found at $APP_PATH. Build it first (./build_mac.sh)." >&2
  exit 1
fi

TMPDIR=$(mktemp -d)
STAGE="$TMPDIR/${NAME}-stage"
mkdir -p "$STAGE"

cp -R "$APP_PATH" "$STAGE/"
ln -s /Applications "$STAGE/Applications"

hdiutil create -volname "$NAME" -srcfolder "$STAGE" -ov -format UDZO "$DMG_PATH"
echo "DMG created: $DMG_PATH"
