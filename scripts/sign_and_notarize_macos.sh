#!/usr/bin/env bash
set -euo pipefail

# Sign and notarize the macOS app and DMG/PKG artifacts.
# Requirements:
# - Developer ID Application certificate installed or provided as base64 P12 via env
# - Optional: Developer ID Installer for PKG signing
# - App Store Connect API key (preferred) or Apple ID + app-specific password
#
# Env variables (recommended via CI secrets):
#   APP_PATH: path to .app (default: dist/TitanScraper/TitanScraper.app)
#   DMG_PATH: path to .dmg (optional)
#   PKG_PATH: path to .pkg (optional)
#   APPLE_CERT_P12_BASE64, APPLE_CERT_PASSWORD (optional; import to keychain)
#   APPLE_DEVELOPER_ID_APP (optional; CN like "Developer ID Application: Your Org (TEAMID)")
#   APPLE_DEVELOPER_ID_INSTALLER (optional; CN for Installer signing)
#   APPLE_API_KEY_ID, APPLE_API_ISSUER_ID, APPLE_API_KEY_BASE64 (preferred for notarytool)
#   or APPLE_ID, APPLE_TEAM_ID, APPLE_APP_SPECIFIC_PASSWORD (fallback for notarytool)

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

APP_PATH=${APP_PATH:-"dist/TitanScraper/TitanScraper.app"}
DMG_PATH=${DMG_PATH:-}
PKG_PATH=${PKG_PATH:-}
ENTITLEMENTS=${ENTITLEMENTS:-"scripts/macos-entitlements.plist"}

if [[ ! -d "$APP_PATH" ]]; then
  echo "App bundle not found at $APP_PATH" >&2
  exit 1
fi

# Prepare keychain and import P12 if provided
if [[ -n "${APPLE_CERT_P12_BASE64:-}" ]]; then
  KEYCHAIN="build/signing.keychain-db"
  KEYCHAIN_PWD="$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 20)"
  echo "Creating temporary keychain and importing Developer ID cert..."
  security create-keychain -p "$KEYCHAIN_PWD" "$KEYCHAIN"
  security set-keychain-settings -lut 21600 "$KEYCHAIN"
  security unlock-keychain -p "$KEYCHAIN_PWD" "$KEYCHAIN"
  echo "$APPLE_CERT_P12_BASE64" | base64 --decode > build/cert.p12
  security import build/cert.p12 -k "$KEYCHAIN" -P "${APPLE_CERT_PASSWORD:-}" -T /usr/bin/codesign -T /usr/bin/security
  security list-keychain -d user -s "$KEYCHAIN" $(security list-keychains -d user | sed 's/\"//g')
fi

# Determine signing identity
if [[ -z "${APPLE_DEVELOPER_ID_APP:-}" ]]; then
  # Pick the first Developer ID Application identity
  APPLE_DEVELOPER_ID_APP=$(security find-identity -v -p codesigning 2>/dev/null | awk -F '"' '/Developer ID Application/{print $2; exit}') || true
fi
if [[ -z "$APPLE_DEVELOPER_ID_APP" ]]; then
  echo "No Developer ID Application identity available. Skipping signing/notarization." >&2
  exit 2
fi

echo "Using signing identity: $APPLE_DEVELOPER_ID_APP"

# Sign inner binaries and libs first
sign_one() {
  local target="$1"
  if codesign --display --verbose=2 "$target" >/dev/null 2>&1; then
    # Already signed — re-sign to ensure hardened runtime
    :
  fi
  codesign --force --timestamp --options runtime \
    --entitlements "$ENTITLEMENTS" \
    -s "$APPLE_DEVELOPER_ID_APP" "$target"
}

# Recursively sign dylibs, frameworks, .so, and executables under Contents
find "$APP_PATH/Contents" -type f \( -name "*.dylib" -o -name "*.so" -o -perm -111 \) -print0 | while IFS= read -r -d '' f; do
  sign_one "$f" || { echo "WARN: failed to sign $f" >&2; }
done
# Sign any embedded frameworks bundles
find "$APP_PATH/Contents/Frameworks" -type d -name "*.framework" -print0 2>/dev/null | while IFS= read -r -d '' fw; do
  sign_one "$fw" || true
done

# Finally sign the .app
sign_one "$APP_PATH"

# Verify signature
codesign --verify --deep --strict --verbose=2 "$APP_PATH"
spctl -a -vv "$APP_PATH" || true

# Optionally sign PKG (if provided)
if [[ -n "$PKG_PATH" && -f "$PKG_PATH" ]]; then
  if [[ -z "${APPLE_DEVELOPER_ID_INSTALLER:-}" ]]; then
    APPLE_DEVELOPER_ID_INSTALLER=$(security find-identity -v -p codesigning 2>/dev/null | awk -F '"' '/Developer ID Installer/{print $2; exit}') || true
  fi
  if [[ -n "$APPLE_DEVELOPER_ID_INSTALLER" ]]; then
    echo "Signing PKG with $APPLE_DEVELOPER_ID_INSTALLER"
    productsign --timestamp --sign "$APPLE_DEVELOPER_ID_INSTALLER" "$PKG_PATH" "${PKG_PATH%.pkg}-signed.pkg"
    PKG_PATH="${PKG_PATH%.pkg}-signed.pkg"
  else
    echo "WARN: No Developer ID Installer identity; PKG will remain unsigned."
  fi
fi

# Prepare notary credentials
NOTARY_ARGS=()
if [[ -n "${APPLE_API_KEY_ID:-}" && -n "${APPLE_API_ISSUER_ID:-}" && -n "${APPLE_API_KEY_BASE64:-}" ]]; then
  echo "$APPLE_API_KEY_BASE64" | base64 --decode > build/AuthKey.p8
  NOTARY_ARGS=("--key-id" "$APPLE_API_KEY_ID" "--issuer" "$APPLE_API_ISSUER_ID" "--key" "build/AuthKey.p8")
elif [[ -n "${APPLE_ID:-}" && -n "${APPLE_TEAM_ID:-}" && -n "${APPLE_APP_SPECIFIC_PASSWORD:-}" ]]; then
  NOTARY_ARGS=("--apple-id" "$APPLE_ID" "--team-id" "$APPLE_TEAM_ID" "--password" "$APPLE_APP_SPECIFIC_PASSWORD")
else
  echo "No notarization credentials provided; skipping notarization." >&2
  exit 0
fi

# Choose primary artifact to notarize: prefer DMG, else zip the .app
PRIMARY_ARTIFACT=""
if [[ -n "$DMG_PATH" && -f "$DMG_PATH" ]]; then
  PRIMARY_ARTIFACT="$DMG_PATH"
else
  mkdir -p build
  PRIMARY_ARTIFACT="build/TitanScraper.zip"
  ditto -c -k --sequesterRsrc --keepParent "$APP_PATH" "$PRIMARY_ARTIFACT"
fi

echo "Submitting to Apple Notary Service: $PRIMARY_ARTIFACT"
xcrun notarytool submit "$PRIMARY_ARTIFACT" "${NOTARY_ARGS[@]}" --wait --timeout 15m

# Staple tickets
if [[ -f "$PRIMARY_ARTIFACT" && "${PRIMARY_ARTIFACT##*.}" == "dmg" ]]; then
  xcrun stapler staple "$PRIMARY_ARTIFACT" || true
fi
xcrun stapler staple "$APP_PATH" || true

echo "Sign + Notarize completed."
