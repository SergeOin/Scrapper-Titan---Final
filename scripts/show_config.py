#!/usr/bin/env python
"""CLI helper to display the effective runtime configuration (safe subset).

Usage:
  python -m scripts.show_config
or
  python scripts/show_config.py

Loads the Settings (pydantic) and prints a masked snapshot.
"""
from __future__ import annotations

from scraper.bootstrap import Settings  # noqa: E402
from scraper.config_inspect import safe_snapshot, format_snapshot  # noqa: E402


def main():
    settings = Settings()
    snap = safe_snapshot(custom=settings.model_dump())
    print("== Effective Runtime Configuration (safe) ==")
    print(format_snapshot(snap))


if __name__ == "__main__":  # pragma: no cover
    main()
