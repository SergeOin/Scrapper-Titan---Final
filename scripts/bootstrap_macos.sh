#!/usr/bin/env bash
set -euo pipefail

# macOS bootstrapper for TitanScraper Desktop
# - Ensures Playwright Chromium is installed in user dir
# - Prepares data directories and storage_state path
# - Launches TitanScraper.app if present, else CLI entry

APP_SUPPORT="$HOME/Library/Application Support/TitanScraper"
mkdir -p "$APP_SUPPORT" "$APP_SUPPORT/logs" "$APP_SUPPORT/exports" "$APP_SUPPORT/screenshots" "$APP_SUPPORT/traces"

export LOG_LEVEL=${LOG_LEVEL:-INFO}
export LOG_FILE="$APP_SUPPORT/logs/server.log"
export DISABLE_MONGO=1
export DISABLE_REDIS=1
export SQLITE_PATH="$APP_SUPPORT/fallback.sqlite3"
export STORAGE_STATE="$APP_SUPPORT/storage_state.json"
export SESSION_STORE_PATH="$APP_SUPPORT/session_store.json"
export PLAYWRIGHT_BROWSERS_PATH="$APP_SUPPORT/pw-browsers"

# Install Playwright Chromium if missing
if [ ! -d "$PLAYWRIGHT_BROWSERS_PATH" ] || ! find "$PLAYWRIGHT_BROWSERS_PATH" -type d -name 'chromium*' -maxdepth 3 -print -quit | grep -q .; then
  echo "Installing Playwright Chromium..."
  if [ -x "./.venv/bin/python" ]; then PY="./.venv/bin/python"; else PY="python3"; fi
  "$PY" -m playwright install chromium
fi

# One-time convenience: copy repo storage_state.json if present and user path missing
if [ -f "./storage_state.json" ] && [ ! -f "$STORAGE_STATE" ]; then
  cp "./storage_state.json" "$STORAGE_STATE"
fi

# Try to open the app bundle if available
APP_BUNDLE="dist/TitanScraper.app"
if [ -d "$APP_BUNDLE" ]; then
  echo "Launching $APP_BUNDLE"
  open "$APP_BUNDLE"
  exit 0
fi

# Fallback: run python entrypoint (dev mode)
if [ -f "desktop/main.py" ]; then
  echo "Launching desktop/main.py"
  exec python3 desktop/main.py
fi

echo "TitanScraper app not found. Build it first."
exit 1
