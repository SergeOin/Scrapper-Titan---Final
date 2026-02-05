"""Unified Titan Scraper logging module.

This module provides a single, centralized logging solution to replace
the scattered _debug_log() functions in worker.py and scrape_subprocess.py.

Features:
- Single rotating log file: titan_scraper.log
- Automatic rotation at 2MB
- Keeps 3 backup files
- Console output for development
- structlog integration for structured logs

Usage:
    from scraper.titan_logger import get_logger, debug_log

    logger = get_logger(__name__)
    logger.info("message", key="value")
    
    # Or for quick debug (replaces _debug_log)
    debug_log("My debug message")

Author: Titan Scraper Team
Created: 2026-01-12 (Stabilization Phase)
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

import structlog


# =============================================================================
# CONFIGURATION
# =============================================================================

LOG_MAX_BYTES = 2 * 1024 * 1024  # 2MB
LOG_BACKUP_COUNT = 3
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _get_log_directory() -> Path:
    """Get the log directory based on platform."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        log_dir = Path(base) / "TitanScraper" / "logs"
    elif sys.platform == "darwin":
        log_dir = Path.home() / "Library" / "Logs" / "TitanScraper"
    else:
        log_dir = Path.home() / ".local" / "share" / "TitanScraper" / "logs"
    
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def _get_log_file_path() -> Path:
    """Get the main log file path."""
    return _get_log_directory() / "titan_scraper.log"


# =============================================================================
# LOGGER SETUP
# =============================================================================

_logger_initialized = False
_file_handler: Optional[RotatingFileHandler] = None


def _setup_logging() -> None:
    """Initialize the unified logging system."""
    global _logger_initialized, _file_handler
    
    if _logger_initialized:
        return
    
    log_file = _get_log_file_path()
    
    # Create rotating file handler
    _file_handler = RotatingFileHandler(
        log_file,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    _file_handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
    _file_handler.setLevel(logging.DEBUG)
    
    # Configure root logger for titan modules
    titan_logger = logging.getLogger("titan")
    titan_logger.setLevel(logging.DEBUG)
    titan_logger.addHandler(_file_handler)
    
    # Also capture scraper module logs
    scraper_logger = logging.getLogger("scraper")
    scraper_logger.setLevel(logging.DEBUG)
    scraper_logger.addHandler(_file_handler)
    
    # Add console handler for development (INFO level)
    if os.environ.get("TITAN_DEBUG_CONSOLE", "0") == "1":
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
        console_handler.setLevel(logging.INFO)
        titan_logger.addHandler(console_handler)
        scraper_logger.addHandler(console_handler)
    
    _logger_initialized = True


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance for the given module name.
    
    Args:
        name: Module name (typically __name__)
        
    Returns:
        Configured logger instance
    """
    _setup_logging()
    
    # Normalize name to use titan prefix
    if not name.startswith("titan.") and not name.startswith("scraper."):
        name = f"titan.{name}"
    
    return logging.getLogger(name)


def get_structlogger(name: str) -> structlog.BoundLogger:
    """Get a structlog logger for structured logging.
    
    Args:
        name: Module name
        
    Returns:
        Bound structlog logger
    """
    _setup_logging()
    return structlog.get_logger(name)


# =============================================================================
# CONVENIENCE FUNCTIONS (replaces _debug_log)
# =============================================================================

_quick_logger: Optional[logging.Logger] = None


def debug_log(msg: str, **kwargs) -> None:
    """Quick debug logging function - replacement for _debug_log().
    
    This is a drop-in replacement for the scattered _debug_log() calls.
    All messages go to the unified log file.
    
    Args:
        msg: Debug message
        **kwargs: Additional context (will be appended to message)
    """
    global _quick_logger
    
    if _quick_logger is None:
        _setup_logging()
        _quick_logger = logging.getLogger("titan.debug")
    
    if kwargs:
        context = " | ".join(f"{k}={v}" for k, v in kwargs.items())
        msg = f"{msg} | {context}"
    
    _quick_logger.debug(msg)


def info_log(msg: str, **kwargs) -> None:
    """Quick info logging - for important events."""
    global _quick_logger
    
    if _quick_logger is None:
        _setup_logging()
        _quick_logger = logging.getLogger("titan.debug")
    
    if kwargs:
        context = " | ".join(f"{k}={v}" for k, v in kwargs.items())
        msg = f"{msg} | {context}"
    
    _quick_logger.info(msg)


def warning_log(msg: str, **kwargs) -> None:
    """Quick warning logging."""
    global _quick_logger
    
    if _quick_logger is None:
        _setup_logging()
        _quick_logger = logging.getLogger("titan.debug")
    
    if kwargs:
        context = " | ".join(f"{k}={v}" for k, v in kwargs.items())
        msg = f"{msg} | {context}"
    
    _quick_logger.warning(msg)


def error_log(msg: str, **kwargs) -> None:
    """Quick error logging."""
    global _quick_logger
    
    if _quick_logger is None:
        _setup_logging()
        _quick_logger = logging.getLogger("titan.debug")
    
    if kwargs:
        context = " | ".join(f"{k}={v}" for k, v in kwargs.items())
        msg = f"{msg} | {context}"
    
    _quick_logger.error(msg)


# =============================================================================
# LOG FILE MANAGEMENT
# =============================================================================

def get_log_file_path() -> str:
    """Return the path to the main log file."""
    return str(_get_log_file_path())


def get_log_directory_path() -> str:
    """Return the path to the log directory."""
    return str(_get_log_directory())


def get_recent_logs(lines: int = 100) -> list[str]:
    """Get the last N lines from the log file.
    
    Useful for diagnostics and dashboard display.
    
    Args:
        lines: Number of lines to retrieve (default 100)
        
    Returns:
        List of log lines (most recent last)
    """
    log_file = _get_log_file_path()
    
    if not log_file.exists():
        return []
    
    try:
        with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
            all_lines = f.readlines()
            return [line.rstrip() for line in all_lines[-lines:]]
    except Exception:
        return []


# =============================================================================
# MIGRATION HELPER
# =============================================================================

def migrate_old_logs() -> None:
    """Migrate old debug log files to the new unified location.
    
    This function consolidates:
    - worker_debug.txt
    - scrape_subprocess_debug.txt
    
    Into the new unified log system.
    """
    log_dir = _get_log_directory()
    
    # Check for old log files
    if sys.platform == "win32":
        old_base = Path(os.environ.get("LOCALAPPDATA", "")) / "TitanScraper"
    else:
        old_base = Path(".")
    
    old_files = [
        old_base / "worker_debug.txt",
        old_base / "scrape_subprocess_debug.txt",
    ]
    
    migrated_count = 0
    for old_file in old_files:
        if old_file.exists():
            try:
                # Move to logs/archive/
                archive_dir = log_dir / "archive"
                archive_dir.mkdir(exist_ok=True)
                
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                new_name = f"{old_file.stem}_{timestamp}.txt"
                old_file.rename(archive_dir / new_name)
                migrated_count += 1
            except Exception:
                pass
    
    if migrated_count > 0:
        info_log(f"Migrated {migrated_count} old log file(s) to archive")


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    "get_logger",
    "get_structlogger",
    "debug_log",
    "info_log", 
    "warning_log",
    "error_log",
    "get_log_file_path",
    "get_log_directory_path",
    "get_recent_logs",
    "migrate_old_logs",
]
