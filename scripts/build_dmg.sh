#!/usr/bin/env bash
set -euo pipefail

NAME="TitanScraper"
APP_PATH="dist/${NAME}/${NAME}.app"
DMG_PATH="dist/${NAME}-${1:-1.0.0}.dmg"

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
