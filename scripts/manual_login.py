"""Backward-compatible wrapper to launch the interactive Playwright login helper.

Historically the manual login helper lived in this module; we now re-export
``generate_storage_state`` so existing documentation and scripts keep working.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
import sys


def _resolve_generate_storage_state():
    """Import the async entrypoint from ``generate_storage_state`` safely.

    We modify ``sys.path`` at runtime to support direct execution via
    ``python scripts/manual_login.py`` without requiring the project root on
    PYTHONPATH.
    """

    scripts_dir = Path(__file__).resolve().parent
    root_dir = scripts_dir.parent
    if str(root_dir) not in sys.path:
        sys.path.insert(0, str(root_dir))

    # Local import to avoid issues when tools introspect this module without the
    # repository root on sys.path.
    from scripts.generate_storage_state import main as _async_main  # type: ignore

    return _async_main


def main() -> None:
    """Run the interactive storage-state generator."""
    async_main = _resolve_generate_storage_state()
    asyncio.run(async_main())


if __name__ == "__main__":  # pragma: no cover
    main()
