"""Scraper Diagnostics - Health checks and troubleshooting utilities.

This module provides diagnostic tools for identifying and resolving
common scraping issues:

1. Session Diagnostics - Verify LinkedIn authentication
2. Selector Health - Test CSS selectors against live pages
3. Rate Limit Status - Check current token bucket state
4. Network Analysis - Detect blocking/throttling
5. Browser Fingerprint - Verify stealth configuration

Usage:
    from scraper.diagnostics import run_full_diagnostic
    
    results = await run_full_diagnostic()
    print(results.summary())

Author: Titan Scraper Team
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, List, Dict

import structlog

logger = structlog.get_logger(__name__)


# =============================================================================
# DIAGNOSTIC RESULT TYPES
# =============================================================================

@dataclass
class DiagnosticResult:
    """Result of a single diagnostic check."""
    name: str
    status: str  # "ok", "warning", "error"
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp,
        }


@dataclass  
class DiagnosticReport:
    """Complete diagnostic report."""
    results: List[DiagnosticResult] = field(default_factory=list)
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None
    
    def add(self, result: DiagnosticResult) -> None:
        self.results.append(result)
    
    @property
    def has_errors(self) -> bool:
        return any(r.status == "error" for r in self.results)
    
    @property
    def has_warnings(self) -> bool:
        return any(r.status == "warning" for r in self.results)
    
    @property
    def overall_status(self) -> str:
        if self.has_errors:
            return "error"
        if self.has_warnings:
            return "warning"
        return "ok"
    
    def summary(self) -> str:
        """Generate human-readable summary."""
        lines = [
            f"=== Diagnostic Report ===",
            f"Status: {self.overall_status.upper()}",
            f"Started: {self.started_at}",
            f"Completed: {self.completed_at or 'in progress'}",
            "",
        ]
        
        for r in self.results:
            icon = "✓" if r.status == "ok" else ("⚠" if r.status == "warning" else "✗")
            lines.append(f"{icon} {r.name}: {r.message}")
            
        return "\n".join(lines)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_status": self.overall_status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "results": [r.to_dict() for r in self.results],
        }


# =============================================================================
# SESSION DIAGNOSTICS
# =============================================================================

async def check_session_status() -> DiagnosticResult:
    """Check if LinkedIn session is valid.
    
    Verifies:
    - storage_state.json exists
    - Contains li_at cookie
    - Cookie is not expired
    """
    try:
        from .session import session_status
        from .bootstrap import get_context
        
        ctx = get_context()
        status = await session_status(ctx)
        
        if status.valid:
            expires = status.details.get("li_at_expires")
            if expires and expires > 0:
                expires_dt = datetime.fromtimestamp(expires, tz=timezone.utc)
                days_left = (expires_dt - datetime.now(timezone.utc)).days
                if days_left < 7:
                    return DiagnosticResult(
                        name="session",
                        status="warning",
                        message=f"Session expiring in {days_left} days",
                        details=status.details
                    )
            return DiagnosticResult(
                name="session",
                status="ok",
                message="LinkedIn session is valid",
                details=status.details
            )
        else:
            return DiagnosticResult(
                name="session",
                status="error",
                message="LinkedIn session is invalid or expired",
                details=status.details
            )
            
    except Exception as e:
        return DiagnosticResult(
            name="session",
            status="error",
            message=f"Session check failed: {str(e)}",
            details={"error": str(e)}
        )


# =============================================================================
# RATE LIMIT DIAGNOSTICS
# =============================================================================

def check_rate_limit_status() -> DiagnosticResult:
    """Check current rate limit token bucket status."""
    try:
        from .bootstrap import get_context
        
        ctx = get_context()
        bucket = ctx.token_bucket
        
        capacity = bucket.capacity
        current = bucket.tokens
        refill_rate = bucket.refill_per_sec
        
        utilization = 1 - (current / capacity) if capacity > 0 else 0
        
        if utilization > 0.9:
            return DiagnosticResult(
                name="rate_limit",
                status="warning",
                message=f"Token bucket nearly depleted ({current:.0f}/{capacity} tokens)",
                details={
                    "tokens": current,
                    "capacity": capacity,
                    "refill_rate": refill_rate,
                    "utilization_pct": utilization * 100
                }
            )
        
        return DiagnosticResult(
            name="rate_limit",
            status="ok",
            message=f"Rate limit healthy ({current:.0f}/{capacity} tokens)",
            details={
                "tokens": current,
                "capacity": capacity,
                "refill_rate": refill_rate,
                "utilization_pct": utilization * 100
            }
        )
        
    except Exception as e:
        return DiagnosticResult(
            name="rate_limit",
            status="error",
            message=f"Rate limit check failed: {str(e)}",
            details={"error": str(e)}
        )


# =============================================================================
# PROGRESSIVE MODE DIAGNOSTICS
# =============================================================================

def check_progressive_mode() -> DiagnosticResult:
    """Check current progressive mode status."""
    try:
        from .progressive_mode import ProgressiveModeManager
        
        manager = ProgressiveModeManager()
        limits = manager.get_current_limits()
        history = manager.get_session_history(days=7)
        
        mode = limits.mode.value
        restrictions = sum(1 for s in history if s.get("had_restriction"))
        
        if restrictions > 2:
            return DiagnosticResult(
                name="progressive_mode",
                status="warning",
                message=f"Mode: {mode} (multiple recent restrictions)",
                details={
                    "current_mode": mode,
                    "restrictions_7d": restrictions,
                    "limits": limits.to_dict()
                }
            )
        
        return DiagnosticResult(
            name="progressive_mode",
            status="ok",
            message=f"Mode: {mode}",
            details={
                "current_mode": mode,
                "restrictions_7d": restrictions,
                "limits": limits.to_dict()
            }
        )
        
    except Exception as e:
        return DiagnosticResult(
            name="progressive_mode",
            status="warning",
            message=f"Progressive mode not available: {str(e)}",
            details={"error": str(e)}
        )


# =============================================================================
# STEALTH DIAGNOSTICS
# =============================================================================

def check_stealth_config() -> DiagnosticResult:
    """Check stealth/anti-detection configuration."""
    try:
        from .stealth import (
            stealth_enabled,
            get_consistent_fingerprint,
        )
        
        enabled = stealth_enabled()
        
        if not enabled:
            return DiagnosticResult(
                name="stealth",
                status="warning",
                message="Stealth mode is DISABLED - high detection risk",
                details={"stealth_enabled": False}
            )
        
        fp = get_consistent_fingerprint()
        
        # Check for outdated user agent
        ua = fp.get("user_agent", "")
        if "Chrome/1" in ua:  # Chrome 1xx
            chrome_version = int(ua.split("Chrome/")[1].split(".")[0]) if "Chrome/" in ua else 0
            if chrome_version < 125:
                return DiagnosticResult(
                    name="stealth",
                    status="warning",
                    message=f"User agent may be outdated (Chrome {chrome_version})",
                    details={"stealth_enabled": True, "fingerprint": fp}
                )
        
        return DiagnosticResult(
            name="stealth",
            status="ok",
            message="Stealth configuration active",
            details={"stealth_enabled": True, "fingerprint": fp}
        )
        
    except Exception as e:
        return DiagnosticResult(
            name="stealth",
            status="error",
            message=f"Stealth check failed: {str(e)}",
            details={"error": str(e)}
        )


# =============================================================================
# SELECTOR DIAGNOSTICS
# =============================================================================

async def check_selector_health() -> DiagnosticResult:
    """Check CSS selector success rates."""
    try:
        from .css_selectors import get_selector_manager
        
        manager = get_selector_manager()
        await manager.initialize()
        
        # Get all stats
        all_stats = manager.get_all_stats()
        
        # Find selectors with low success rates
        problematic = []
        for name, stat in all_stats.items():
            if stat.total_attempts >= 5 and stat.success_rate < 0.5:
                problematic.append({
                    "name": name,
                    "success_rate": stat.success_rate,
                    "attempts": stat.total_attempts
                })
        
        if problematic:
            return DiagnosticResult(
                name="selectors",
                status="warning",
                message=f"{len(problematic)} selectors have low success rate",
                details={
                    "problematic_selectors": problematic[:5],  # Top 5
                    "total_tracked": len(all_stats)
                }
            )
        
        return DiagnosticResult(
            name="selectors",
            status="ok",
            message="Selectors are working normally",
            details={"total_tracked": len(all_stats)}
        )
        
    except Exception as e:
        return DiagnosticResult(
            name="selectors",
            status="warning",
            message=f"Selector check not available: {str(e)}",
            details={"error": str(e)}
        )


# =============================================================================
# TIMING DIAGNOSTICS
# =============================================================================

def check_timing_config() -> DiagnosticResult:
    """Check timing/delay configuration."""
    try:
        from .timing import (
            is_ultra_safe_mode,
            is_safe_mode,
            get_delay_multiplier,
            get_keyword_delay,
        )
        
        ultra_safe = is_ultra_safe_mode()
        safe = is_safe_mode()
        multiplier = get_delay_multiplier()
        keyword_delay = get_keyword_delay()
        
        mode_name = "ultra-safe" if ultra_safe else ("safe" if safe else "normal")
        
        return DiagnosticResult(
            name="timing",
            status="ok",
            message=f"Timing mode: {mode_name} (x{multiplier})",
            details={
                "mode": mode_name,
                "multiplier": multiplier,
                "keyword_delay_range_ms": keyword_delay,
            }
        )
        
    except Exception as e:
        return DiagnosticResult(
            name="timing",
            status="warning",
            message=f"Timing module not available: {str(e)}",
            details={"error": str(e)}
        )


# =============================================================================
# DATABASE DIAGNOSTICS
# =============================================================================

def check_database_status() -> DiagnosticResult:
    """Check SQLite database status."""
    try:
        from .bootstrap import get_context
        import sqlite3
        
        ctx = get_context()
        db_path = ctx.settings.sqlite_path
        
        if not Path(db_path).exists():
            return DiagnosticResult(
                name="database",
                status="warning",
                message="Database file does not exist yet",
                details={"path": db_path}
            )
        
        conn = sqlite3.connect(db_path)
        
        # Check table existence
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = [row[0] for row in cursor.fetchall()]
        
        # Get post count
        post_count = 0
        if "posts" in tables:
            cursor = conn.execute("SELECT COUNT(*) FROM posts")
            post_count = cursor.fetchone()[0]
        
        # Get database size
        db_size = Path(db_path).stat().st_size
        
        conn.close()
        
        return DiagnosticResult(
            name="database",
            status="ok",
            message=f"Database OK ({post_count} posts, {db_size / 1024 / 1024:.1f} MB)",
            details={
                "path": db_path,
                "tables": tables,
                "post_count": post_count,
                "size_bytes": db_size
            }
        )
        
    except Exception as e:
        return DiagnosticResult(
            name="database",
            status="error",
            message=f"Database check failed: {str(e)}",
            details={"error": str(e)}
        )


# =============================================================================
# FULL DIAGNOSTIC RUNNER
# =============================================================================

async def run_full_diagnostic() -> DiagnosticReport:
    """Run all diagnostic checks and return a complete report.
    
    Returns:
        DiagnosticReport with all check results
    """
    report = DiagnosticReport()
    
    # Run checks in order
    checks = [
        ("session", check_session_status),
        ("rate_limit", lambda: check_rate_limit_status()),
        ("progressive_mode", lambda: check_progressive_mode()),
        ("stealth", lambda: check_stealth_config()),
        ("timing", lambda: check_timing_config()),
        ("database", lambda: check_database_status()),
        ("selectors", check_selector_health),
    ]
    
    for name, check_fn in checks:
        try:
            if asyncio.iscoroutinefunction(check_fn):
                result = await check_fn()
            else:
                result = check_fn()
            report.add(result)
        except Exception as e:
            report.add(DiagnosticResult(
                name=name,
                status="error",
                message=f"Check crashed: {str(e)}",
                details={"error": str(e)}
            ))
    
    report.completed_at = datetime.now(timezone.utc).isoformat()
    
    logger.info(
        "diagnostic_complete",
        overall_status=report.overall_status,
        checks=len(report.results),
        errors=sum(1 for r in report.results if r.status == "error"),
        warnings=sum(1 for r in report.results if r.status == "warning")
    )
    
    return report


# =============================================================================
# QUICK HEALTH CHECK
# =============================================================================

async def quick_health_check() -> Dict[str, Any]:
    """Perform a quick health check for the /health endpoint.
    
    Returns minimal status information without detailed diagnostics.
    """
    try:
        from .bootstrap import get_context
        
        ctx = get_context()
        
        # Basic checks
        session_ok = Path(ctx.settings.storage_state).exists()
        db_ok = Path(ctx.settings.sqlite_path).exists()
        
        status = "ok" if (session_ok and db_ok) else "degraded"
        
        return {
            "status": status,
            "session": "ok" if session_ok else "missing",
            "database": "ok" if db_ok else "missing",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    "DiagnosticResult",
    "DiagnosticReport",
    "run_full_diagnostic",
    "quick_health_check",
    "check_session_status",
    "check_rate_limit_status",
    "check_progressive_mode",
    "check_stealth_config",
    "check_selector_health",
    "check_timing_config",
    "check_database_status",
]
