#!/usr/bin/env bash
set -euo pipefail

APP_PATH="${1:-/Applications/TitanScraper.app}"
WAIT="${2:-20}"

echo "Post-install verification for macOS..."
if [[ ! -d "$APP_PATH" ]]; then
  echo "App not found at $APP_PATH" >&2
  exit 1
fi

open -a "$APP_PATH"
sleep "$WAIT"

set +e
code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/health)
if [[ "$code" == "200" ]]; then echo "Health OK"; else echo "Health returned $code"; fi
code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/blocked-accounts)
if [[ "$code" == "200" ]]; then echo "/blocked-accounts OK"; else echo "blocked-accounts returned $code"; fi
set -e

echo "Done."
