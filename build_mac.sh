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

EXTRA=""
if [ "${ONEFILE:-0}" = "1" ]; then
  EXTRA="--onefile"
fi

pyinstaller desktop/pyinstaller.spec $EXTRA \
  --osx-bundle-identifier com.titan.scraper \
  --name TitanScraper \
  --icon build/icon.icns || true

echo "Build complete. Check dist/TitanScraper" 
