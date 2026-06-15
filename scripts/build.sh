#!/usr/bin/env bash
if [ -z "${BASH_VERSION:-}" ]; then
  exec /usr/bin/env bash "$0" "$@"
fi

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"
cd "$ROOT"

resolve_version() {
  if [ -n "${CS2_PICKER_VERSION:-}" ]; then
    echo "${CS2_PICKER_VERSION#v}"
    return
  fi
  if git describe --tags --exact-match >/dev/null 2>&1; then
    git describe --tags --exact-match | sed 's/^v//'
    return
  fi
  if git describe --tags --abbrev=0 >/dev/null 2>&1; then
    git describe --tags --abbrev=0 | sed 's/^v//'
    return
  fi
  echo "0.0.0-dev"
}

VERSION="$(resolve_version)"
echo "Building CS2 Server Picker v${VERSION} for macOS..."

ensure_venv
PY="$(venv_python)"

pip_install -q -r requirements-build.txt

"$PY" scripts/write_version.py "$VERSION"
export CS2_PICKER_VERSION="$VERSION"

require_macos_build_tools

rm -rf .pyinstaller-work dist
"$PY" -m PyInstaller --noconfirm --workpath .pyinstaller-work packaging/CS2ServerPicker.spec

APP_PATH="dist/CS2 Server Picker.app"
if [ ! -d "$APP_PATH" ]; then
  echo "Build failed: $APP_PATH not found"
  exit 1
fi

ZIP_NAME="CS2-Server-Picker-v${VERSION}-macOS.zip"
DMG_NAME="CS2-Server-Picker-v${VERSION}-macOS.dmg"

zip_app_bundle "$APP_PATH" "dist/${ZIP_NAME}"

hdiutil create \
  -volname "CS2 Server Picker" \
  -ov \
  -srcfolder "$APP_PATH" \
  -format UDZO \
  "dist/${DMG_NAME}" >/dev/null

echo ""
echo "Build complete:"
echo "  $APP_PATH"
echo "  dist/${ZIP_NAME}"
echo "  dist/${DMG_NAME}"
