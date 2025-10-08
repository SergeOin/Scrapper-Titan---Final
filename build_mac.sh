#!/usr/bin/env bash
set -euo pipefail

echo "==> Titan Scraper Desktop - macOS build"

PY=${PYTHON:-python3}

if [ ! -d .venv ]; then
  echo "Creating virtual environment..."
  $PY -m venv .venv
fi
source .venv/bin/activate

echo "Installing Python dependencies..."
pip install -U pip wheel setuptools
pip install -r requirements.txt
pip install -r desktop/requirements-desktop.txt
pip install pyinstaller==6.10.0 pillow==10.4.0

echo "Ensuring Playwright Chromium is available (best effort)..."
$PY -m playwright install chromium --with-deps || echo "Playwright install skipped or failed (non-fatal)"

mkdir -p build
if [ -f "Titan Scraper logo.png" ]; then
  echo "Generating macOS ICNS from PNG..."
  $PY scripts/util_make_icon.py -i "Titan Scraper logo.png" -o build/icon.icns
fi

rm -rf dist build/TitanScraper
mkdir -p dist

EXTRA=""
if [ "${ONEFILE:-0}" = "1" ]; then
  EXTRA="--onefile"
fi

echo "Running PyInstaller..."
# Capture PyInstaller output to a log so that CI can display it on failure.
set +e
if [ -f "TitanScraper.spec" ]; then
  pyinstaller TitanScraper.spec $EXTRA --log-level WARN 2>&1 | tee build/pyinstaller.log
elif [ -f "desktop/pyinstaller.spec" ]; then
  # Spec desktop alternative
  pyinstaller desktop/pyinstaller.spec $EXTRA --log-level WARN 2>&1 | tee build/pyinstaller.log
else
  # Fallback one-shot generation without spec
  pyinstaller desktop/main.py --name TitanScraper ${EXTRA} \
    --icon build/icon.icns \
    --noconsole \
    --add-data "server/templates:server/templates" \
    --log-level WARN 2>&1 | tee build/pyinstaller.log
fi
status=${PIPESTATUS[0]}
set -e
if [ $status -ne 0 ]; then
  echo "PyInstaller a échoué (code $status). Contenu du log :" >&2
  sed -n '1,300p' build/pyinstaller.log >&2 || true
  exit $status
fi

if [ ! -d dist/TitanScraper ]; then
  echo "WARN: dist/TitanScraper absent après PyInstaller (structure différente?). Listing dist/ :" >&2
  ls -R dist || true
  # Try to locate TitanScraper.app anywhere in dist
  APP_CANDIDATE=$(find dist -maxdepth 3 -name 'TitanScraper.app' | head -n1 || true)
  if [ -n "$APP_CANDIDATE" ]; then
     echo "Found app at $APP_CANDIDATE; normalizing into dist/TitanScraper" >&2
     mkdir -p dist/TitanScraper
     rsync -a "$APP_CANDIDATE" dist/TitanScraper/
  else
     echo "ERROR: TitanScraper.app introuvable; DMG ne pourra pas être généré." >&2
     exit 1
  fi
fi

echo "Build complete. Check dist/TitanScraper" 
echo "Listing dist/TitanScraper:" || true
ls -R dist/TitanScraper || true
