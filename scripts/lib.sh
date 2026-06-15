#!/usr/bin/env bash
# Re-exec with bash if invoked via sh
if [ -z "${BASH_VERSION:-}" ]; then
  exec /usr/bin/env bash "$0" "$@"
fi

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python_is_healthy() {
  local py="$1"
  [ -n "$py" ] && [ -x "$py" ] || return 1
  "$py" -c "import ssl, venv, xml.parsers.expat" >/dev/null 2>&1
}

python_version_major_minor() {
  local py="$1"
  "$py" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "?"
}

find_python() {
  local candidates=()

  if [ -n "${CS2_PICKER_PYTHON:-}" ]; then
    candidates+=("$CS2_PICKER_PYTHON")
  fi

  candidates+=(
    python3.12
    python3.11
    python3.13
    /opt/homebrew/bin/python3.12
    /opt/homebrew/opt/python@3.12/bin/python3.12
    /opt/homebrew/bin/python3.11
    /opt/homebrew/opt/python@3.11/bin/python3.11
    /usr/local/bin/python3.12
    /usr/local/bin/python3.11
    /usr/bin/python3
    python3
    /opt/homebrew/bin/python3
  )

  local seen=""
  local candidate py ver
  for candidate in "${candidates[@]}"; do
    [ -z "$candidate" ] && continue
    case "$seen" in *"|${candidate}|"*) continue ;; esac
    seen="${seen}|${candidate}|"

    if ! command -v "$candidate" >/dev/null 2>&1; then
      continue
    fi
    py="$(command -v "$candidate")"
    if ! python_is_healthy "$py"; then
      ver="$(python_version_major_minor "$py")"
      if [ "$ver" = "3.14" ]; then
        echo "Skipped: $py (Python 3.14 — Homebrew pyexpat issue, unsupported)" >&2
      else
        echo "Skipped: $py (health check failed)" >&2
      fi
      continue
    fi
    echo "$py"
    return 0
  done
  return 1
}

print_python_help() {
  cat <<'EOF'
No suitable Python interpreter found.

Homebrew Python 3.14 has a known pyexpat/libexpat issue.
Use Python 3.11 or 3.12 for this project.

Option A (recommended):
  brew install python@3.12
  rm -rf .venv
  ./scripts/build.sh

Option B (uv — downloads Python automatically):
  curl -LsSf https://astral.sh/uv/install.sh | sh
  rm -rf .venv
  ./scripts/build.sh

Option C (manual):
  CS2_PICKER_PYTHON=/opt/homebrew/bin/python3.12 ./scripts/build.sh
EOF
}

bootstrap_pip() {
  local venv_py="$1"
  local venv_bin
  venv_bin="$(dirname "$venv_py")"

  if [ -x "$venv_bin/pip" ]; then
    return 0
  fi
  if "$venv_py" -m ensurepip --upgrade >/dev/null 2>&1; then
    return 0
  fi
  if ! command -v curl >/dev/null 2>&1; then
    echo "Error: could not install pip and curl is missing."
    return 1
  fi
  echo "Bootstrapping pip..."
  curl -fsSL https://bootstrap.pypa.io/get-pip.py | "$venv_py"
}

create_venv_with_python() {
  local py="$1"
  rm -rf "$ROOT/.venv"

  if ! "$py" -m venv "$ROOT/.venv"; then
    rm -rf "$ROOT/.venv"
    return 1
  fi

  if [ ! -x "$ROOT/.venv/bin/python" ]; then
    rm -rf "$ROOT/.venv"
    return 1
  fi

  if ! bootstrap_pip "$ROOT/.venv/bin/python"; then
    rm -rf "$ROOT/.venv"
    return 1
  fi

  "$ROOT/.venv/bin/python" -m pip install -q --upgrade pip
}

create_venv_with_uv() {
  rm -rf "$ROOT/.venv"
  echo "Creating Python 3.12 virtualenv with uv..."
  uv venv "$ROOT/.venv" --python 3.12
  python_is_healthy "$ROOT/.venv/bin/python"
}

ensure_venv() {
  if [ -x "$ROOT/.venv/bin/python" ] && python_is_healthy "$ROOT/.venv/bin/python"; then
    if [ -x "$ROOT/.venv/bin/pip" ] || command -v uv >/dev/null 2>&1; then
      return 0
    fi
  fi

  rm -rf "$ROOT/.venv"

  if command -v uv >/dev/null 2>&1; then
    create_venv_with_uv
    return 0
  fi

  local py
  py="$(find_python)" || {
    print_python_help
    exit 1
  }

  echo "Preparing virtualenv ($py)..."
  if ! create_venv_with_python "$py"; then
    print_python_help
    exit 1
  fi
}

venv_python() {
  echo "$ROOT/.venv/bin/python"
}

pip_install() {
  if command -v uv >/dev/null 2>&1; then
    uv pip install --python "$ROOT/.venv/bin/python" "$@"
  else
    "$ROOT/.venv/bin/python" -m pip install "$@"
  fi
}

require_macos_build_tools() {
  if [ "$(uname -s)" != "Darwin" ]; then
    echo "Error: .app builds are only supported on macOS."
    exit 1
  fi
  if ! xcode-select -p >/dev/null 2>&1; then
    cat <<'EOF'
Error: Xcode Command Line Tools are not installed (required for PyInstaller lipo).

Install:
  xcode-select --install

Then run:
  rm -rf .pyinstaller-work dist
  ./scripts/build.sh
EOF
    exit 1
  fi
  if ! command -v lipo >/dev/null 2>&1; then
    echo "Error: lipo not found. Reinstall Xcode Command Line Tools."
    exit 1
  fi
}

zip_app_bundle() {
  local app_path="$1"
  local zip_path="$2"
  local app_dir app_name zip_dir zip_file

  app_dir="$(cd "$(dirname "$app_path")" && pwd)"
  app_name="$(basename "$app_path")"
  zip_dir="$(cd "$(dirname "$zip_path")" && pwd)"
  zip_file="$(basename "$zip_path")"

  rm -f "$zip_dir/$zip_file"

  if ditto -c -k --sequesterResource --keepParent "$app_path" "$zip_dir/$zip_file" 2>/dev/null; then
    return 0
  fi

  if ditto -c -k --keepParent "$app_path" "$zip_dir/$zip_file"; then
    return 0
  fi

  echo "ditto failed, falling back to zip..."
  (cd "$app_dir" && zip -ry "$zip_dir/$zip_file" "$app_name")
}
