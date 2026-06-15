#!/usr/bin/env bash
if [ -z "${BASH_VERSION:-}" ]; then
  exec /usr/bin/env bash "$0" "$@"
fi

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

if [ $# -ne 1 ]; then
  echo "Kullanim: ./scripts/release.sh <versiyon>"
  echo "Ornek:   ./scripts/release.sh 1.0.2"
  exit 1
fi

NEW_VERSION="${1#v}"

if git rev-parse "v${NEW_VERSION}" >/dev/null 2>&1; then
  echo "Tag v${NEW_VERSION} zaten var."
  exit 1
fi

git tag -a "v${NEW_VERSION}" -m "Release v${NEW_VERSION}"

echo ""
echo "Tag olusturuldu: v${NEW_VERSION}"
echo ""
echo "GitHub'a gonder:"
echo "  git push origin v${NEW_VERSION}"
