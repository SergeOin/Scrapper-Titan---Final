#!/usr/bin/env python
"""Increment semantic version stored in VERSION file.

Usage:
  python scripts/bump_version.py [major|minor|patch]

Defaults to patch increment if no argument provided.
Writes updated version back to VERSION and prints it to stdout.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION"


def read_version() -> tuple[int, int, int]:
    if not VERSION_FILE.exists():
        return (0, 1, 0)
    raw = VERSION_FILE.read_text(encoding="utf-8").strip()
    parts = raw.split(".")
    try:
        major, minor, patch = (int(parts[0]), int(parts[1]), int(parts[2]))
    except Exception:
        return (0, 1, 0)
    return major, minor, patch


def write_version(v: tuple[int, int, int]) -> str:
    s = f"{v[0]}.{v[1]}.{v[2]}"
    VERSION_FILE.write_text(s + "\n", encoding="utf-8")
    return s


def bump(kind: str) -> str:
    major, minor, patch = read_version()
    if kind == "major":
        major += 1; minor = 0; patch = 0
    elif kind == "minor":
        minor += 1; patch = 0
    else:
        patch += 1
    return write_version((major, minor, patch))


def main():
    kind = sys.argv[1] if len(sys.argv) > 1 else "patch"
    if kind not in {"major", "minor", "patch"}:
        print("Invalid bump kind (use major|minor|patch)", file=sys.stderr)
        sys.exit(2)
    new_v = bump(kind)
    print(new_v)


if __name__ == "__main__":  # pragma: no cover
    main()
