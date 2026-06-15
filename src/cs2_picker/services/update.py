"""GitHub Releases update check and install."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

import requests

from cs2_picker._version import __version__
from cs2_picker.core.constants import GITHUB_REPO

APP_BUNDLE_NAME = "CS2 Server Picker.app"
USER_AGENT = f"CS2ServerPicker/{__version__}"


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    tag: str
    zip_url: str
    html_url: str


def parse_version(version: str) -> tuple[int, ...]:
    cleaned = version.strip().lstrip("v").split("-")[0]
    parts = cleaned.split(".")
    nums: list[int] = []
    for part in parts[:4]:
        match = re.match(r"(\d+)", part)
        nums.append(int(match.group(1)) if match else 0)
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)


def is_newer_version(latest: str, current: str) -> bool:
    if latest == current:
        return False
    return parse_version(latest) > parse_version(current)


def fetch_latest_release() -> ReleaseInfo | None:
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    try:
        response = requests.get(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": USER_AGENT,
            },
            timeout=20,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        return None

    tag = str(data.get("tag_name", "")).strip()
    if not tag:
        return None

    version = tag.lstrip("v")
    zip_url = ""
    for asset in data.get("assets") or []:
        name = str(asset.get("name", ""))
        if name.endswith(".zip") and "macOS" in name:
            zip_url = str(asset.get("browser_download_url", ""))
            break

    if not zip_url:
        return None

    return ReleaseInfo(
        version=version,
        tag=tag,
        zip_url=zip_url,
        html_url=str(data.get("html_url", f"https://github.com/{GITHUB_REPO}/releases/latest")),
    )


def check_for_update(current_version: str | None = None) -> ReleaseInfo | None:
    current = current_version or __version__
    latest = fetch_latest_release()
    if not latest:
        return None
    if is_newer_version(latest.version, current):
        return latest
    return None


def get_app_bundle_path() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None

    exe = Path(sys.executable).resolve()
    if exe.parent.name == "MacOS" and exe.parent.parent.name == "Contents":
        bundle = exe.parent.parent.parent
        if bundle.suffix == ".app":
            return bundle
    return None


def get_update_log_path() -> Path:
    log_dir = Path.home() / "Library" / "Logs" / "CS2ServerPicker"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "update.log"


def is_app_translocated(app_path: Path) -> bool:
    return "AppTranslocation" in str(app_path)


def validate_self_update_target() -> Path:
    current_app = get_app_bundle_path()
    if current_app is None:
        raise RuntimeError("Self-update is only available from the packaged .app bundle.")

    if is_app_translocated(current_app):
        raise RuntimeError(
            "Move CS2 Server Picker.app to /Applications before using self-update.\n"
            "macOS App Translocation breaks in-place updates."
        )

    parent = current_app.parent
    if not os.access(parent, os.W_OK):
        raise RuntimeError(
            f"Cannot write to {parent}.\n"
            "Move the app to a folder you own (e.g. /Applications)."
        )

    return current_app


def can_self_update() -> bool:
    try:
        validate_self_update_target()
        return True
    except RuntimeError:
        return False


def download_file(url: str, dest: Path, progress=None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(
        url,
        stream=True,
        timeout=120,
        headers={"User-Agent": USER_AGENT},
    ) as response:
        response.raise_for_status()
        total = int(response.headers.get("Content-Length") or 0)
        downloaded = 0
        with dest.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if not chunk:
                    continue
                handle.write(chunk)
                downloaded += len(chunk)
                if progress and total > 0:
                    progress(downloaded, total)


def extract_app_from_zip(zip_path: Path, work_dir: Path) -> Path:
    """Used by tests/dev helpers; production updater extracts with ditto in shell."""
    with zipfile.ZipFile(zip_path, "r") as archive:
        archive.extractall(work_dir)

    for path in work_dir.rglob("*.app"):
        if path.name == APP_BUNDLE_NAME:
            return path

    apps = list(work_dir.rglob("*.app"))
    if len(apps) == 1:
        return apps[0]

    raise FileNotFoundError(f"{APP_BUNDLE_NAME} not found inside the update archive.")


def _write_updater_script() -> Path:
    script_path = Path(tempfile.gettempdir()) / f"cs2picker-update-{os.getpid()}.sh"
    script = r"""#!/bin/bash
set -uo pipefail

ZIP="$1"
TARGET="$2"
PID="$3"
WORKDIR="$4"
LOG="$5"
APP_NAME="CS2 Server Picker.app"

mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1

log() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') $*"
}

log "==== CS2 Server Picker update started (pid=$$) ===="
log "zip=$ZIP"
log "target=$TARGET"
log "waiting for app pid=$PID"

for _ in $(seq 1 400); do
  if ! kill -0 "$PID" 2>/dev/null; then
    log "app process exited"
    break
  fi
  sleep 0.25
done

sleep 2

EXTRACT="$WORKDIR/extract"
BACKUP="$WORKDIR/backup.app"
rm -rf "$EXTRACT" "$BACKUP"
mkdir -p "$EXTRACT"

log "extracting update zip"
if ditto -x -k "$ZIP" "$EXTRACT" 2>/dev/null; then
  log "extracted with ditto"
elif /usr/bin/unzip -qq "$ZIP" -d "$EXTRACT"; then
  log "extracted with unzip"
else
  log "extract failed"
  exit 1
fi

STAGED=$(find "$EXTRACT" -name "$APP_NAME" -maxdepth 4 -print -quit)"
if [ -z "$STAGED" ] || [ ! -d "$STAGED" ]; then
  log "staged app not found in archive"
  exit 1
fi

MACOS_BIN="$STAGED/Contents/MacOS/CS2ServerPicker"
if [ ! -f "$MACOS_BIN" ]; then
  log "missing MacOS executable in staged app"
  exit 1
fi

chmod -R u+rwX "$STAGED" 2>/dev/null || true
chmod +x "$MACOS_BIN" "$STAGED/Contents/MacOS/"* 2>/dev/null || true

if [ -d "$TARGET" ]; then
  log "backing up current app"
  ditto "$TARGET" "$BACKUP" || cp -R "$TARGET" "$BACKUP"
fi

log "installing update"
rm -rf "$TARGET"
if ! ditto "$STAGED" "$TARGET"; then
  log "install ditto failed — restoring backup"
  rm -rf "$TARGET"
  if [ -d "$BACKUP" ]; then
    ditto "$BACKUP" "$TARGET" || cp -R "$BACKUP" "$TARGET"
  fi
  exit 1
fi

MACOS_BIN="$TARGET/Contents/MacOS/CS2ServerPicker"
chmod -R u+rwX "$TARGET" 2>/dev/null || true
chmod +x "$MACOS_BIN" "$TARGET/Contents/MacOS/"* 2>/dev/null || true
xattr -cr "$TARGET" 2>/dev/null || true
/usr/bin/codesign --force --deep --sign - "$TARGET" 2>/dev/null || log "codesign skipped"

log "launching updated app"
if /usr/bin/open "$TARGET"; then
  log "open succeeded"
elif [ -x "$MACOS_BIN" ]; then
  log "open failed, launching binary directly"
  nohup "$MACOS_BIN" >/dev/null 2>&1 &
else
  log "could not launch updated app"
  exit 1
fi

sleep 2
rm -rf "$WORKDIR"
log "update complete"
"""
    script_path.write_text(script, encoding="utf-8")
    script_path.chmod(0o755)
    return script_path


def apply_update(release: ReleaseInfo, progress=None) -> None:
    current_app = validate_self_update_target()
    work_dir = Path(tempfile.mkdtemp(prefix="cs2picker-update-"))
    zip_path = work_dir / "update.zip"
    log_path = get_update_log_path()

    try:
        download_file(release.zip_url, zip_path, progress=progress)
        if zip_path.stat().st_size < 1024:
            raise RuntimeError("Downloaded update file is empty or corrupt.")

        script = _write_updater_script()
        subprocess.Popen(
            [
                "/bin/bash",
                str(script),
                str(zip_path),
                str(current_app),
                str(os.getpid()),
                str(work_dir),
                str(log_path),
            ],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            cwd="/",
        )
        # Give the detached updater time to start before the app exits.
        time.sleep(1.5)
    except Exception:
        import shutil

        shutil.rmtree(work_dir, ignore_errors=True)
        raise
