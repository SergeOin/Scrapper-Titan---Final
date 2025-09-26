"""Desktop IPC helpers for window focus & state (Windows-focused).

This module is imported optionally by the API layer to allow triggering UI
actions (focus / restore) from an HTTP endpoint (/focus). It degrades safely
when running the API outside of the packaged desktop launcher.
"""
from __future__ import annotations

import ctypes
import threading
from typing import Optional

_LOCK = threading.Lock()
_WINDOW_TITLE = "Titan Scraper"


def set_window_title(title: str) -> None:
    global _WINDOW_TITLE
    with _LOCK:
        _WINDOW_TITLE = title


def focus_window() -> bool:
    """Best-effort bring the existing desktop window to foreground.

    Uses FindWindowW by title (simpler than tracking handle across pywebview).
    Returns True if a window handle was found.
    """
    try:
        import sys
        if not sys.platform.startswith("win"):
            return False
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        FindWindowW = user32.FindWindowW  # type: ignore
        ShowWindow = user32.ShowWindow  # type: ignore
        SetForegroundWindow = user32.SetForegroundWindow  # type: ignore
        SW_RESTORE = 9
        with _LOCK:
            title = _WINDOW_TITLE
        hwnd = FindWindowW(None, title)
        if hwnd:
            # Restore (if minimized) then bring to foreground
            ShowWindow(hwnd, SW_RESTORE)
            SetForegroundWindow(hwnd)
            return True
    except Exception:
        pass
    return False


__all__ = ["focus_window", "set_window_title"]
