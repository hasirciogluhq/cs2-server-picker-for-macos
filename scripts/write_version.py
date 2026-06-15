#!/usr/bin/env python3
"""Git tag veya argümandan _version.py yazar."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "src" / "cs2_picker" / "_version.py"

SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


def write_version(version: str) -> None:
    if not SEMVER.match(version):
        raise SystemExit(f"Gecersiz versiyon: {version!r} (ornek: 1.0.2)")

    VERSION_FILE.write_text(f'__version__ = "{version}"\n', encoding="utf-8")
    print(f"Version embedded: {version}")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"Kullanim: {Path(sys.argv[0]).name} <versiyon>")
    write_version(sys.argv[1].lstrip("v"))


if __name__ == "__main__":
    main()
