"""GitHub Releases update check and install."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import tempfile
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


def can_self_update() -> bool:
    return get_app_bundle_path() is not None


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
    with zipfile.ZipFile(zip_path, "r") as archive:
        archive.extractall(work_dir)

    for path in work_dir.rglob("*.app"):
        if path.name == APP_BUNDLE_NAME:
            return path

    apps = list(work_dir.rglob("*.app"))
    if len(apps) == 1:
        return apps[0]

    raise FileNotFoundError(f"{APP_BUNDLE_NAME} not found inside the update archive.")


def _update_log_path() -> Path:
    log_dir = Path.home() / "Library" / "Logs" / "CS2ServerPicker"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "update.log"


def _write_updater_script(current_app: Path, staged_app: Path, pid: int) -> Path:
    script_path = Path(tempfile.gettempdir()) / f"cs2picker-update-{pid}.sh"
    log_path = _update_log_path()
    script = f"""#!/bin/bash
set -u
TARGET={shlex.quote(str(current_app))}
STAGED={shlex.quote(str(staged_app))}
WORKDIR={shlex.quote(str(staged_app.parent.parent))}
PID={pid}
LOG={shlex.quote(str(log_path))}
MACOS_BIN="$TARGET/Contents/MacOS/CS2ServerPicker"

log() {{
  echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"
}}

log "Updater started (pid=$$, waiting for app pid=$PID)"

for _ in $(seq 1 300); do
  if ! kill -0 "$PID" 2>/dev/null; then
    break
  fi
  sleep 0.2
done

sleep 1

log "Replacing $TARGET"
rm -rf "$TARGET"
if ! ditto "$STAGED" "$TARGET"; then
  log "ditto failed"
  exit 1
fi

xattr -cr "$TARGET" 2>/dev/null || true
chmod -R u+rwX "$TARGET" 2>/dev/null || true

log "Launching updated app"
if [ -x "$MACOS_BIN" ]; then
  /usr/bin/open -n "$TARGET" || "$MACOS_BIN" &
else
  /usr/bin/open -n "$TARGET"
fi

sleep 1
rm -rf "$WORKDIR"
rm -f {shlex.quote(str(script_path))}
log "Update complete"
"""
    script_path.write_text(script, encoding="utf-8")
    script_path.chmod(0o755)
    return script_path


def apply_update(release: ReleaseInfo, progress=None) -> None:
    current_app = get_app_bundle_path()
    if current_app is None:
        raise RuntimeError("Self-update is only available from the packaged .app bundle.")

    work_dir = Path(tempfile.mkdtemp(prefix="cs2picker-update-"))
    zip_path = work_dir / "update.zip"

    try:
        download_file(release.zip_url, zip_path, progress=progress)
        staged_app = extract_app_from_zip(zip_path, work_dir / "extract")
        script = _write_updater_script(current_app, staged_app, os.getpid())
        subprocess.Popen(
            ["/bin/bash", str(script)],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            cwd="/",
        )
    except Exception:
        import shutil

        shutil.rmtree(work_dir, ignore_errors=True)
        raise
