#!/usr/bin/env python
"""Increment semantic version stored in VERSION file (with optional pre-release suffix).

Usage:
    python scripts/bump_version.py [major|minor|patch] [--pre beta.1]

If --pre is supplied, resulting version will be: MAJOR.MINOR.PATCH-<suffix>
The numeric core (MAJOR.MINOR.PATCH) is still incremented according to the bump kind.

Notes:
 - Pre-release suffix is NOT suitable for MSI Version field; callers must strip after '-'.
 - When the existing VERSION already contains a suffix (e.g. 1.2.3-beta.1) we ignore it for the bump math.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION"


def read_version() -> tuple[int, int, int, str | None]:
    if not VERSION_FILE.exists():
        return (0, 1, 0, None)
    raw = VERSION_FILE.read_text(encoding="utf-8").strip()
    suffix = None
    if '-' in raw:
        core, suffix = raw.split('-', 1)
    else:
        core = raw
    parts = core.split(".")
    try:
        major, minor, patch = (int(parts[0]), int(parts[1]), int(parts[2]))
    except Exception:
        return (0, 1, 0, suffix)
    return major, minor, patch, suffix


def write_version(v: tuple[int, int, int], suffix: str | None) -> str:
    s = f"{v[0]}.{v[1]}.{v[2]}"
    if suffix:
        s += f"-{suffix}"
    VERSION_FILE.write_text(s + "\n", encoding="utf-8")
    return s


def bump(kind: str, pre: str | None) -> str:
    major, minor, patch, _old_suffix = read_version()
    if kind == "major":
        major += 1; minor = 0; patch = 0
    elif kind == "minor":
        minor += 1; patch = 0
    else:
        patch += 1
    return write_version((major, minor, patch), pre)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Bump semantic version")
    parser.add_argument("kind", nargs="?", default="patch", choices=["major","minor","patch"], help="Bump kind")
    parser.add_argument("--pre", dest="pre", help="Optional pre-release suffix (e.g. beta.1)")
    args = parser.parse_args()
    new_v = bump(args.kind, args.pre)
    print(new_v)


if __name__ == "__main__":  # pragma: no cover
    main()
