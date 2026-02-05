"""Company whitelist management for targeted scraping.

This module manages a curated list of companies to monitor,
replacing broad keyword searches with targeted company page visits.

Key benefits:
    - 70% reduction in pages visited
    - Natural browsing pattern (following companies)
    - Auto-enrichment from successful posts
    - Tiered prioritization (T1 daily, T2 weekly, T3 monthly)

Architecture:
    - SQLite persistence for companies and visit history
    - Automatic tier promotion/demotion based on yield
    - Integration with session_orchestrator for scheduling

Author: Titan Scraper Team
Version: 2.0.0
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import IntEnum
from pathlib import Path
from typing import List, Optional, Set
import os

import structlog

logger = structlog.get_logger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

class CompanyTier(IntEnum):
    """Company priority tiers."""
    TIER_1 = 1  # High priority: Visit daily (major law firms, CAC40 legal depts)
    TIER_2 = 2  # Medium: Visit 2-3x/week (mid-size companies)
    TIER_3 = 3  # Low: Visit 1x/week (exploration, new discoveries)
    INACTIVE = 9  # Temporarily disabled (no posts in 30+ days)


# Tier visit frequency (minimum hours between visits)
TIER_VISIT_INTERVALS = {
    CompanyTier.TIER_1: 24,     # Once per day
    CompanyTier.TIER_2: 48,     # Every 2 days
    CompanyTier.TIER_3: 168,    # Once per week
    CompanyTier.INACTIVE: 720,  # Once per month (check if active again)
}

# Auto-promotion thresholds
PROMOTE_TO_TIER1_THRESHOLD = 5   # Posts found in last 30 days
PROMOTE_TO_TIER2_THRESHOLD = 2   # Posts found in last 30 days
DEMOTE_AFTER_DAYS_NO_POST = 30   # Demote if no posts in N days


@dataclass
class Company:
    """A company in the whitelist."""
    id: int
    name: str
    linkedin_url: str
    tier: CompanyTier = CompanyTier.TIER_2
    posts_found_30d: int = 0
    posts_qualified_30d: int = 0
    last_visited: Optional[datetime] = None
    last_post_found: Optional[datetime] = None
    added_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    notes: str = ""

    @property
    def is_due_for_visit(self) -> bool:
        """Check if company should be visited based on tier schedule."""
        if self.last_visited is None:
            return True

        interval_hours = TIER_VISIT_INTERVALS.get(self.tier, 48)
        next_visit = self.last_visited + timedelta(hours=interval_hours)
        return datetime.now(timezone.utc) >= next_visit

    @property
    def yield_rate(self) -> float:
        """Qualified posts / total posts found."""
        if self.posts_found_30d == 0:
            return 0.0
        return self.posts_qualified_30d / self.posts_found_30d

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "linkedin_url": self.linkedin_url,
            "tier": self.tier,
            "posts_found_30d": self.posts_found_30d,
            "posts_qualified_30d": self.posts_qualified_30d,
            "last_visited": self.last_visited.isoformat() if self.last_visited else None,
            "last_post_found": self.last_post_found.isoformat() if self.last_post_found else None,
            "yield_rate": round(self.yield_rate, 3),
            "is_due": self.is_due_for_visit,
        }


# =============================================================================
# INITIAL SEED DATA - Tier 1 Companies
# =============================================================================

# Major law firms in France (high legal recruitment activity)
SEED_TIER1_LAW_FIRMS = [
    ("Bredin Prat", "https://www.linkedin.com/company/bredin-prat/"),
    ("Gide Loyrette Nouel", "https://www.linkedin.com/company/gide-loyrette-nouel/"),
    ("Darrois Villey Maillot Brochier", "https://www.linkedin.com/company/darrois-villey-maillot-brochier/"),
    ("Cleary Gottlieb", "https://www.linkedin.com/company/cleary-gottlieb-steen-&-hamilton-llp/"),
    ("Clifford Chance", "https://www.linkedin.com/company/clifford-chance/"),
    ("Linklaters", "https://www.linkedin.com/company/linklaters/"),
    ("Allen & Overy", "https://www.linkedin.com/company/allen-&-overy/"),
    ("Freshfields Bruckhaus Deringer", "https://www.linkedin.com/company/freshfields-bruckhaus-deringer/"),
    ("Herbert Smith Freehills", "https://www.linkedin.com/company/herbert-smith-freehills/"),
    ("Latham & Watkins", "https://www.linkedin.com/company/latham-&-watkins/"),
    ("White & Case", "https://www.linkedin.com/company/white-&-case-llp/"),
    ("Hogan Lovells", "https://www.linkedin.com/company/hogan-lovells/"),
    ("Jones Day", "https://www.linkedin.com/company/jones-day/"),
    ("Willkie Farr & Gallagher", "https://www.linkedin.com/company/willkie-farr-&-gallagher-llp/"),
    ("De Pardieu Brocas Maffei", "https://www.linkedin.com/company/de-pardieu-brocas-maffei/"),
    ("August Debouzy", "https://www.linkedin.com/company/august-debouzy/"),
    ("Racine", "https://www.linkedin.com/company/racine-avocats/"),
    ("Fidal", "https://www.linkedin.com/company/fidal/"),
    ("CMS Francis Lefebvre", "https://www.linkedin.com/company/cms-francis-lefebvre-avocats/"),
    ("Dechert", "https://www.linkedin.com/company/dechert/"),
    # Additional strategic French law firms (January 2026)
    ("Franklin", "https://www.linkedin.com/company/franklin-paris/"),
    ("Aramis", "https://www.linkedin.com/company/aramis-avocats/"),
    ("LPA-CGR Avocats", "https://www.linkedin.com/company/lpa-cgr-avocats/"),
    ("Lexcase", "https://www.linkedin.com/company/lexcase/"),
    ("Flichy Grangé Avocats", "https://www.linkedin.com/company/flichy-grange-avocats/"),
    ("Capstan Avocats", "https://www.linkedin.com/company/capstan-avocats/"),
    ("LexisNexis France", "https://www.linkedin.com/company/lexisnexis-france/"),
    ("Proskauer", "https://www.linkedin.com/company/proskauer-rose-llp/"),
]

# CAC40 and major French companies with active legal departments
SEED_TIER1_CORPORATES = [
    ("LVMH", "https://www.linkedin.com/company/lvmh/"),
    ("TotalEnergies", "https://www.linkedin.com/company/totalenergies/"),
    ("Sanofi", "https://www.linkedin.com/company/sanofi/"),
    ("L'Oréal", "https://www.linkedin.com/company/loreal/"),
    ("BNP Paribas", "https://www.linkedin.com/company/bnp-paribas/"),
    ("AXA", "https://www.linkedin.com/company/axa/"),
    ("Société Générale", "https://www.linkedin.com/company/societe-generale/"),
    ("Airbus", "https://www.linkedin.com/company/airbus/"),
    ("Schneider Electric", "https://www.linkedin.com/company/schneider-electric/"),
    ("Danone", "https://www.linkedin.com/company/danone/"),
    ("Engie", "https://www.linkedin.com/company/engie/"),
    ("Capgemini", "https://www.linkedin.com/company/capgemini/"),
    ("Crédit Agricole", "https://www.linkedin.com/company/credit-agricole/"),
    ("Carrefour", "https://www.linkedin.com/company/carrefour/"),
    ("EDF", "https://www.linkedin.com/company/edf/"),
    ("Orange", "https://www.linkedin.com/company/orange/"),
    ("Renault Group", "https://www.linkedin.com/company/renault-group/"),
    ("Stellantis", "https://www.linkedin.com/company/stellantis/"),
    ("Kering", "https://www.linkedin.com/company/kering/"),
    ("Thales", "https://www.linkedin.com/company/thales/"),
]

# Tier 2: Mid-size companies and boutique law firms
SEED_TIER2_COMPANIES = [
    ("Goodwin", "https://www.linkedin.com/company/goodwin-procter-llp/"),
    ("Mayer Brown", "https://www.linkedin.com/company/mayer-brown/"),
    ("DLA Piper", "https://www.linkedin.com/company/dla-piper/"),
    ("Bird & Bird", "https://www.linkedin.com/company/bird-&-bird/"),
    ("Ashurst", "https://www.linkedin.com/company/ashurst/"),
    ("Shearman & Sterling", "https://www.linkedin.com/company/shearman-&-sterling-llp/"),
    ("Orrick", "https://www.linkedin.com/company/orrick/"),
    ("Paul Hastings", "https://www.linkedin.com/company/paul-hastings/"),
    ("Weil Gotshal & Manges", "https://www.linkedin.com/company/weil-gotshal-&-manges-llp/"),
    ("Covington & Burling", "https://www.linkedin.com/company/covington-&-burling-llp/"),
    ("Veil Jourde", "https://www.linkedin.com/company/veil-jourde/"),
    ("Jeantet", "https://www.linkedin.com/company/jeantet/"),
    ("Gowling WLG", "https://www.linkedin.com/company/gowlingwlg/"),
    ("Norton Rose Fulbright", "https://www.linkedin.com/company/norton-rose-fulbright/"),
    ("Dentons", "https://www.linkedin.com/company/dentons/"),
    ("Accor", "https://www.linkedin.com/company/accor/"),
    ("Bouygues", "https://www.linkedin.com/company/bouygues/"),
    ("Vinci", "https://www.linkedin.com/company/vinci/"),
    ("Safran", "https://www.linkedin.com/company/safran/"),
    ("Sodexo", "https://www.linkedin.com/company/sodexo/"),
]


# =============================================================================
# WHITELIST MANAGER
# =============================================================================

class CompanyWhitelist:
    """Manages the company whitelist with SQLite persistence."""

    def __init__(self, db_path: Optional[str] = None):
        """Initialize whitelist manager.
        
        Args:
            db_path: Path to SQLite database. Defaults to user data dir.
        """
        self.db_path = db_path or self._default_db_path()
        self._ensure_db()
        self._seed_if_empty()

    @staticmethod
    def _default_db_path() -> str:
        if os.name == 'nt':
            base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
            return str(Path(base) / "TitanScraper" / "company_whitelist.sqlite3")
        else:
            return str(Path.home() / ".local" / "share" / "TitanScraper" / "company_whitelist.sqlite3")

    def _ensure_db(self) -> None:
        """Create database tables if they don't exist."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS companies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                linkedin_url TEXT UNIQUE NOT NULL,
                tier INTEGER DEFAULT 2,
                posts_found_30d INTEGER DEFAULT 0,
                posts_qualified_30d INTEGER DEFAULT 0,
                last_visited TEXT,
                last_post_found TEXT,
                added_at TEXT NOT NULL,
                notes TEXT DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS visit_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                visited_at TEXT NOT NULL,
                posts_found INTEGER DEFAULT 0,
                posts_qualified INTEGER DEFAULT 0,
                FOREIGN KEY (company_id) REFERENCES companies(id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_companies_tier ON companies(tier)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_companies_last_visited ON companies(last_visited)
        """)
        conn.commit()
        conn.close()

    def _seed_if_empty(self) -> None:
        """Seed with initial companies if database is empty."""
        conn = sqlite3.connect(self.db_path)
        count = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]

        if count == 0:
            seed_count = (len(SEED_TIER1_LAW_FIRMS) +
                          len(SEED_TIER1_CORPORATES) +
                          len(SEED_TIER2_COMPANIES))
            logger.info("seeding_whitelist", seed_count=seed_count)
            now = datetime.now(timezone.utc).isoformat()

            # Seed Tier 1
            for name, url in SEED_TIER1_LAW_FIRMS + SEED_TIER1_CORPORATES:
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO companies (name, linkedin_url, tier, added_at) VALUES (?, ?, ?, ?)",
                        (name, url, CompanyTier.TIER_1, now)
                    )
                except sqlite3.IntegrityError:
                    pass

            # Seed Tier 2
            for name, url in SEED_TIER2_COMPANIES:
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO companies (name, linkedin_url, tier, added_at) VALUES (?, ?, ?, ?)",
                        (name, url, CompanyTier.TIER_2, now)
                    )
                except sqlite3.IntegrityError:
                    pass

            conn.commit()

        conn.close()

    def _row_to_company(self, row: tuple) -> Company:
        """Convert database row to Company object."""
        return Company(
            id=row[0],
            name=row[1],
            linkedin_url=row[2],
            tier=CompanyTier(row[3]),
            posts_found_30d=row[4] or 0,
            posts_qualified_30d=row[5] or 0,
            last_visited=datetime.fromisoformat(row[6]) if row[6] else None,
            last_post_found=datetime.fromisoformat(row[7]) if row[7] else None,
            added_at=datetime.fromisoformat(row[8]),
            notes=row[9] or "",
        )

    def get_companies_for_session(
        self,
        session_focus: str,
        max_companies: int = 10,
    ) -> List[Company]:
        """Get companies to visit for a given session type.
        
        Args:
            session_focus: Type of session (tier1_check, exploration, etc.)
            max_companies: Maximum number of companies to return
        
        Returns:
            List of Company objects due for visit
        """
        conn = sqlite3.connect(self.db_path)

        # Build query based on session focus
        if session_focus == "tier1_check":
            # Priority: Tier 1 companies due for visit
            query = """
                SELECT * FROM companies 
                WHERE tier = ? 
                ORDER BY last_visited ASC NULLS FIRST
                LIMIT ?
            """
            cursor = conn.execute(query, (CompanyTier.TIER_1, max_companies))

        elif session_focus == "tier2_check":
            query = """
                SELECT * FROM companies 
                WHERE tier = ? 
                ORDER BY last_visited ASC NULLS FIRST
                LIMIT ?
            """
            cursor = conn.execute(query, (CompanyTier.TIER_2, max_companies))

        elif session_focus == "exploration":
            # Mix of Tier 2 and Tier 3
            query = """
                SELECT * FROM companies 
                WHERE tier IN (?, ?) 
                ORDER BY last_visited ASC NULLS FIRST
                LIMIT ?
            """
            cursor = conn.execute(query, (CompanyTier.TIER_2, CompanyTier.TIER_3, max_companies))

        else:
            # Default: All active tiers, prioritize least recently visited
            query = """
                SELECT * FROM companies 
                WHERE tier < ?
                ORDER BY tier ASC, last_visited ASC NULLS FIRST
                LIMIT ?
            """
            cursor = conn.execute(query, (CompanyTier.INACTIVE, max_companies))

        companies = [self._row_to_company(row) for row in cursor.fetchall()]
        conn.close()

        # Filter to only due companies
        due_companies = [c for c in companies if c.is_due_for_visit]

        logger.debug("companies_for_session",
                    focus=session_focus,
                    total=len(companies),
                    due=len(due_companies))

        return due_companies[:max_companies]

    def get_all_company_names(self) -> Set[str]:
        """Get all company names for pre-qualification matching."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("SELECT LOWER(name) FROM companies WHERE tier < ?", (CompanyTier.INACTIVE,))
        names = {row[0] for row in cursor.fetchall()}
        conn.close()
        return names

    def record_visit(
        self,
        company_id: int,
        posts_found: int = 0,
        posts_qualified: int = 0,
    ) -> None:
        """Record a company page visit.
        
        Args:
            company_id: ID of the visited company
            posts_found: Number of posts extracted
            posts_qualified: Number of posts that passed filtering
        """
        now = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(self.db_path)

        # Update company record
        conn.execute("""
            UPDATE companies SET 
                last_visited = ?,
                posts_found_30d = posts_found_30d + ?,
                posts_qualified_30d = posts_qualified_30d + ?
            WHERE id = ?
        """, (now, posts_found, posts_qualified, company_id))

        if posts_found > 0:
            conn.execute("""
                UPDATE companies SET last_post_found = ? WHERE id = ?
            """, (now, company_id))

        # Record in history
        conn.execute("""
            INSERT INTO visit_history (company_id, visited_at, posts_found, posts_qualified)
            VALUES (?, ?, ?, ?)
        """, (company_id, now, posts_found, posts_qualified))

        conn.commit()
        conn.close()

        # Check for tier adjustment
        self._maybe_adjust_tier(company_id)

    def add_company(
        self,
        name: str,
        linkedin_url: str,
        tier: CompanyTier = CompanyTier.TIER_3,
        notes: str = "",
    ) -> Optional[int]:
        """Add a new company to the whitelist.
        
        Used for auto-discovery: when a qualified post comes from a new company,
        add it to Tier 3 for future monitoring.
        
        Returns:
            Company ID if added, None if already exists
        """
        conn = sqlite3.connect(self.db_path)
        now = datetime.now(timezone.utc).isoformat()

        try:
            cursor = conn.execute("""
                INSERT INTO companies (name, linkedin_url, tier, added_at, notes)
                VALUES (?, ?, ?, ?, ?)
            """, (name, linkedin_url, tier, now, notes))
            company_id = cursor.lastrowid
            conn.commit()
            logger.info("company_added", name=name, tier=tier, id=company_id)
            return company_id
        except sqlite3.IntegrityError:
            # Already exists
            return None
        finally:
            conn.close()

    def discover_from_post(self, author_name: str, company_url: Optional[str] = None) -> None:
        """Auto-discover company from a qualified post.
        
        Called when a post is accepted - if the company is new, add to Tier 3.
        """
        if not author_name:
            return

        # Check if already in whitelist
        conn = sqlite3.connect(self.db_path)
        exists = conn.execute(
            "SELECT id FROM companies WHERE LOWER(name) = LOWER(?)",
            (author_name,)
        ).fetchone()
        conn.close()

        if not exists and company_url:
            self.add_company(
                name=author_name,
                linkedin_url=company_url,
                tier=CompanyTier.TIER_3,
                notes="Auto-discovered from qualified post"
            )

    def _maybe_adjust_tier(self, company_id: int) -> None:
        """Check if company should be promoted/demoted based on performance."""
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT tier, posts_qualified_30d, last_post_found FROM companies WHERE id = ?",
            (company_id,)
        ).fetchone()

        if not row:
            conn.close()
            return

        current_tier, posts_30d, last_post_str = row
        new_tier = current_tier

        # Promotion logic
        if posts_30d >= PROMOTE_TO_TIER1_THRESHOLD and current_tier > CompanyTier.TIER_1:
            new_tier = CompanyTier.TIER_1
        elif posts_30d >= PROMOTE_TO_TIER2_THRESHOLD and current_tier > CompanyTier.TIER_2:
            new_tier = CompanyTier.TIER_2

        # Demotion logic
        if last_post_str:
            last_post = datetime.fromisoformat(last_post_str)
            days_since_post = (datetime.now(timezone.utc) - last_post).days

            if days_since_post > DEMOTE_AFTER_DAYS_NO_POST:
                if current_tier < CompanyTier.INACTIVE:
                    new_tier = CompanyTier.INACTIVE

        if new_tier != current_tier:
            conn.execute(
                "UPDATE companies SET tier = ? WHERE id = ?",
                (new_tier, company_id)
            )
            conn.commit()
            logger.info("company_tier_changed",
                       company_id=company_id,
                       old_tier=current_tier,
                       new_tier=new_tier)

        conn.close()

    def reset_monthly_stats(self) -> None:
        """Reset 30-day rolling stats (call monthly)."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE companies SET posts_found_30d = 0, posts_qualified_30d = 0")
        conn.commit()
        conn.close()
        logger.info("monthly_stats_reset")

    def get_stats(self) -> dict:
        """Get whitelist statistics."""
        conn = sqlite3.connect(self.db_path)

        tier_counts = {}
        for tier in CompanyTier:
            count = conn.execute(
                "SELECT COUNT(*) FROM companies WHERE tier = ?",
                (tier,)
            ).fetchone()[0]
            tier_counts[tier.name] = count

        total = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]

        due_for_visit = conn.execute("""
            SELECT COUNT(*) FROM companies 
            WHERE tier < ? AND (
                last_visited IS NULL OR 
                datetime(last_visited, '+24 hours') < datetime('now')
            )
        """, (CompanyTier.INACTIVE,)).fetchone()[0]

        conn.close()

        return {
            "total_companies": total,
            "by_tier": tier_counts,
            "due_for_visit": due_for_visit,
        }


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_whitelist_instance: Optional[CompanyWhitelist] = None


def get_whitelist() -> CompanyWhitelist:
    """Get the global whitelist instance."""
    global _whitelist_instance
    if _whitelist_instance is None:
        _whitelist_instance = CompanyWhitelist()
    return _whitelist_instance


# Alias for adapters.py compatibility
get_company_whitelist = get_whitelist


def reset_whitelist() -> None:
    """Reset the global whitelist instance."""
    global _whitelist_instance
    _whitelist_instance = None
