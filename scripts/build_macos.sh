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

# Build frontend (web/blocked) if Node is available
if [[ -f "web/blocked/package.json" ]]; then
  if command -v npm >/dev/null 2>&1; then
    echo "Building frontend: web/blocked (Vite)"
    pushd web/blocked >/dev/null
    set +e
    npm ci && npm run build
    code=$?
    set -e
    popd >/dev/null
    if [[ $code -ne 0 ]]; then
      echo "WARNING: Frontend build failed; /blocked will show a fallback message." >&2
    fi
  else
    echo "npm not found; skipping frontend build. The app will use fallback content for /blocked." >&2
  fi
fi

# Derive version (robust against locale issues)
if [[ -f VERSION ]]; then
  VERSION_STR=$(awk 'NR==1{print; exit}' VERSION || echo "1.0.0")
else
  VERSION_STR="1.0.0"
fi

echo "Building macOS app (version $VERSION_STR)"
pyinstaller desktop/pyinstaller.spec

# Package into nested .app expected by downstream scripts without recursive self-copy
if [[ -d dist/TitanScraper ]]; then
  STAGE_APP="build/${APP_NAME}.app"
  rm -rf "$STAGE_APP"
  mkdir -p "$STAGE_APP/Contents/MacOS"
  mkdir -p "$STAGE_APP/Contents/Resources"
  # Basic Info.plist
  cat > "$STAGE_APP/Contents/Info.plist" <<EOF
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
  # Move built content into .app bundle (avoid copying into itself)
  rsync -a --exclude "${APP_NAME}.app" "dist/TitanScraper/" "$STAGE_APP/Contents/MacOS/"
  # Place .app at expected location
  mkdir -p "dist/${APP_NAME}"
  rm -rf "dist/${APP_NAME}/${APP_NAME}.app"
  rsync -a "$STAGE_APP/" "dist/${APP_NAME}/${APP_NAME}.app/"
fi

echo "App bundle prepared at: dist/${APP_NAME}/${APP_NAME}.app"
