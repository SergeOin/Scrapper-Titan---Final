"""Pre-qualification module for early post filtering.

This module implements the "Qualify Early, Extract Late" strategy.
It filters out 90% of irrelevant posts BEFORE full extraction,
drastically reducing Playwright cost per qualified post.

Key principle:
    - Use only data already visible in the DOM (preview text, author name)
    - No additional HTTP requests or scrolling
    - Fast regex-based checks, no heavy processing

Integration:
    Called in scrape_subprocess.py BEFORE extract_full_post()
    
Metrics tracked:
    - pre_qual_accepted: Posts that passed pre-qualification
    - pre_qual_rejected_*: Posts rejected by reason

Author: Titan Scraper Team
Version: 2.0.0
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Set, Tuple

# =============================================================================
# CONFIGURATION - Tunable thresholds
# =============================================================================

# Minimum preview length to attempt pre-qualification
MIN_PREVIEW_LENGTH = 20

# If preview is too short, default to cautious extraction
EXTRACT_ON_INSUFFICIENT_DATA = True


class RejectionReason(str, Enum):
    """Reasons for pre-qualification rejection."""
    AGENCY = "agency"
    STAGE_ALTERNANCE = "stage_alternance"
    EXTERNAL_RECRUITMENT = "external_recruitment"
    JOBSEEKER = "jobseeker"
    NON_RECRUITMENT = "non_recruitment"
    LOCATION_FOREIGN = "location_foreign"
    INSUFFICIENT_DATA = "insufficient_data"
    NO_LEGAL_SIGNAL = "no_legal_signal"

    def __str__(self) -> str:
        return self.value


@dataclass
class PreQualificationResult:
    """Result of pre-qualification check."""
    should_extract: bool
    confidence: float  # 0.0 - 1.0
    reason: str
    signals_found: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.should_extract


# =============================================================================
# EXCLUSION PATTERNS - Fast regex-based checks
# =============================================================================

# Agencies and job boards (check against author name)
AGENCY_PATTERNS: Set[str] = {
    # Major agencies
    "michael page", "hays", "robert half", "expectra", "randstad",
    "adecco", "manpower", "spring", "keljob", "indeed", "monster",
    "cadremploi", "apec", "meteojob", "page personnel", "fed legal",
    "lincoln", "major", "laurence simons", "profiler", "tsylana",
    # Job boards
    "village de la justice", "emploi", "jobs", "carriere", "career",
    "talent acquisition", "staffing", "headhunt", "chasseur",
    # Generic recruitment company signals
    "recrutement", "recruiting", "rh ", " rh", "ressources humaines",
    "cabinet de recrutement", "interim",
}

# Compile regex for agencies (case-insensitive)
_AGENCY_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(a) for a in AGENCY_PATTERNS) + r")\b",
    re.IGNORECASE
)

# Contract types to exclude (stages, alternance, etc.)
EXCLUSION_CONTRACT_PATTERNS: Set[str] = {
    "stage", "stagiaire", "intern", "internship",
    "alternance", "alternant", "apprenti", "apprentissage",
    "contrat pro", "work-study", "élève-avocat", "eleve-avocat",
    "v.i.e", "vie ", " vie", "volontariat",
}

_CONTRACT_EXCLUSION_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(c) for c in EXCLUSION_CONTRACT_PATTERNS) + r")\b",
    re.IGNORECASE
)

# External recruitment signals (recruiting for clients, not themselves)
EXTERNAL_RECRUITMENT_PATTERNS: Set[str] = {
    "pour notre client", "pour un client", "pour nos clients",
    "pour le compte de", "mandaté par", "notre client recrute",
    "je recrute pour", "recrute pour des", "for our client",
    "on behalf of", "my client", "our client is",
}

_EXTERNAL_PATTERN = re.compile(
    r"(" + "|".join(re.escape(e) for e in EXTERNAL_RECRUITMENT_PATTERNS) + r")",
    re.IGNORECASE
)

# Job seeker signals (not a job post, person looking for work)
JOBSEEKER_PATTERNS: Set[str] = {
    "opentowork", "open to work", "#opentowork",
    "je recherche un poste", "je cherche un poste", "recherche active",
    "disponible immédiatement", "à l'écoute du marché",
    "looking for a position", "seeking opportunities",
    "nouveau poste en tant que", "happy to announce",
    "thrilled to share", "excited to announce",
}

_JOBSEEKER_PATTERN = re.compile(
    r"(" + "|".join(re.escape(j) for j in JOBSEEKER_PATTERNS) + r")",
    re.IGNORECASE
)

# Non-recruitment content (events, articles, etc.)
NON_RECRUITMENT_PATTERNS: Set[str] = {
    "retour sur", "conférence", "séminaire", "webinaire", "webinar",
    "formation", "article", "publication", "tribune",
    "félicitations", "bravo", "bienvenue à", "welcome",
    "a rejoint", "vient de rejoindre", "nous accueillons",
}

_NON_RECRUITMENT_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(n) for n in NON_RECRUITMENT_PATTERNS) + r")\b",
    re.IGNORECASE
)

# Foreign location signals (France only)
FOREIGN_LOCATION_PATTERNS: Set[str] = {
    # Countries
    "suisse", "switzerland", "belgique", "belgium", "luxembourg",
    "monaco", "canada", "québec", "maroc", "morocco", "uk", "dubai",
    "allemagne", "germany", "espagne", "spain", "italie", "italy",
    "états-unis", "usa", "algérie", "tunisie", "sénégal",
    # Cities
    "genève", "geneva", "bruxelles", "brussels", "montréal", "toronto",
    "casablanca", "rabat", "london", "londres", "berlin", "madrid",
}

_FOREIGN_LOCATION_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(f) for f in FOREIGN_LOCATION_PATTERNS) + r")\b",
    re.IGNORECASE
)

# =============================================================================
# ELITE COMPANIES - Bypass soft exclusions for known high-value employers
# =============================================================================

# Major law firms that should ALWAYS be extracted regardless of preview content
# These are the most valuable recruitment sources for legal positions
ELITE_LAW_FIRMS: Set[str] = {
    # French "Magic Circle" equivalent
    "bredin prat", "gide loyrette nouel", "gide",
    "darrois villey", "darrois", "cleary gottlieb", "cleary",
    "clifford chance", "linklaters", "allen overy", "allen & overy",
    "freshfields", "herbert smith", "latham watkins", "latham",
    "white case", "white & case", "hogan lovells", "jones day",
    "willkie farr", "willkie", "de pardieu", "august debouzy",
    "racine", "fidal", "cms francis lefebvre", "cms",
    # Additional elite firms
    "sullivan cromwell", "davis polk", "skadden", "cravath",
    "wachtell", "simpson thacher", "kirkland ellis", "kirkland",
    "dentons", "dla piper", "baker mckenzie", "norton rose",
}

_ELITE_FIRM_PATTERN = re.compile(
    r"(" + "|".join(re.escape(f) for f in ELITE_LAW_FIRMS) + r")",
    re.IGNORECASE
)


# =============================================================================
# POSITIVE SIGNALS - What we're looking for
# =============================================================================

# Legal profession signals
LEGAL_SIGNALS: Set[str] = {
    "juriste", "avocat", "legal counsel", "head of legal",
    "directeur juridique", "responsable juridique", "compliance",
    "dpo", "contract manager", "notaire", "paralegal",
    "juridique", "legal", "counsel",
}

_LEGAL_SIGNAL_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(sig) for sig in LEGAL_SIGNALS) + r")\b",
    re.IGNORECASE
)

# Recruitment signals (company hiring)
RECRUITMENT_SIGNALS: Set[str] = {
    "recrute", "recruiting", "hiring", "recherche", "looking for",
    "poste à pourvoir", "poste ouvert", "cdi", "cdd",
    "rejoignez", "join", "candidature", "postulez",
}

_RECRUITMENT_SIGNAL_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(r) for r in RECRUITMENT_SIGNALS) + r")\b",
    re.IGNORECASE
)


# =============================================================================
# MAIN PRE-QUALIFICATION FUNCTION
# =============================================================================

def pre_qualify_post(
    preview_text: str,
    author_name: str,
    company_name: Optional[str] = None,
    known_companies: Optional[Set[str]] = None,
) -> PreQualificationResult:
    """Pre-qualify a post based on minimal visible data.
    
    This function is designed to be FAST and filter out obvious
    non-relevant posts before expensive full extraction.
    
    Args:
        preview_text: First 50-150 characters of the post (visible in feed)
        author_name: Name of the post author
        company_name: Optional company name if visible
        known_companies: Optional set of known good companies (whitelist)
    
    Returns:
        PreQualificationResult with decision and reasoning
    
    Cost: 0 HTTP requests, ~0.1ms processing time
    """
    signals: list[str] = []

    # Normalize inputs
    preview_lower = preview_text.lower().strip() if preview_text else ""
    author_lower = author_name.lower().strip() if author_name else ""
    company_lower = company_name.lower().strip() if company_name else ""

    # =================================================================
    # PHASE 1: IMMEDIATE EXCLUSIONS (fastest checks first)
    # =================================================================

    # Check 1: Agency/Job board author (instant reject)
    if author_lower and _AGENCY_PATTERN.search(author_lower):
        return PreQualificationResult(
            should_extract=False,
            confidence=0.95,
            reason=f"rejected:{RejectionReason.AGENCY}",
            signals_found=["author_is_agency"]
        )

    # Check 2: Agency in company name
    if company_lower and _AGENCY_PATTERN.search(company_lower):
        return PreQualificationResult(
            should_extract=False,
            confidence=0.95,
            reason=f"rejected:{RejectionReason.AGENCY}",
            signals_found=["company_is_agency"]
        )

    # Check 3: Insufficient preview data
    if len(preview_lower) < MIN_PREVIEW_LENGTH:
        if EXTRACT_ON_INSUFFICIENT_DATA:
            return PreQualificationResult(
                should_extract=True,
                confidence=0.3,
                reason="insufficient_preview_cautious_extract",
                signals_found=["short_preview"]
            )
        else:
            return PreQualificationResult(
                should_extract=False,
                confidence=0.5,
                reason=f"rejected:{RejectionReason.INSUFFICIENT_DATA}",
                signals_found=["short_preview"]
            )

    # =================================================================
    # PHASE 1.5: ELITE COMPANY BYPASS
    # If author or company is an elite law firm, extract regardless of content
    # (except stage/alternance which we always skip)
    # =================================================================
    
    is_elite_firm = (
        _ELITE_FIRM_PATTERN.search(author_lower) or 
        _ELITE_FIRM_PATTERN.search(company_lower) or
        _ELITE_FIRM_PATTERN.search(preview_lower)
    )
    
    if is_elite_firm:
        signals.append("elite_law_firm")

    # =================================================================
    # PHASE 2: CONTENT-BASED EXCLUSIONS
    # =================================================================

    # Check 4: Stage/Alternance/Apprentissage (always exclude, even for elite)
    if _CONTRACT_EXCLUSION_PATTERN.search(preview_lower):
        return PreQualificationResult(
            should_extract=False,
            confidence=0.9,
            reason=f"rejected:{RejectionReason.STAGE_ALTERNANCE}",
            signals_found=["contract_type_excluded"]
        )

    # Check 5: External recruitment (for a client)
    if _EXTERNAL_PATTERN.search(preview_lower):
        return PreQualificationResult(
            should_extract=False,
            confidence=0.85,
            reason=f"rejected:{RejectionReason.EXTERNAL_RECRUITMENT}",
            signals_found=["external_recruitment"]
        )

    # Check 6: Job seeker post (not a job offer)
    if _JOBSEEKER_PATTERN.search(preview_lower):
        return PreQualificationResult(
            should_extract=False,
            confidence=0.9,
            reason=f"rejected:{RejectionReason.JOBSEEKER}",
            signals_found=["jobseeker_post"]
        )

    # Check 7: Non-recruitment content (bypass for elite firms)
    if _NON_RECRUITMENT_PATTERN.search(preview_lower) and not is_elite_firm:
        return PreQualificationResult(
            should_extract=False,
            confidence=0.75,
            reason=f"rejected:{RejectionReason.NON_RECRUITMENT}",
            signals_found=["non_recruitment_content"]
        )

    # Check 8: Foreign location (bypass for elite - they recruit for Paris offices)
    if _FOREIGN_LOCATION_PATTERN.search(preview_lower) and not is_elite_firm:
        return PreQualificationResult(
            should_extract=False,
            confidence=0.8,
            reason=f"rejected:{RejectionReason.LOCATION_FOREIGN}",
            signals_found=["foreign_location"]
        )

    # =================================================================
    # PHASE 3: POSITIVE SIGNAL DETECTION
    # =================================================================

    has_legal_signal = bool(_LEGAL_SIGNAL_PATTERN.search(preview_lower))
    has_recruitment_signal = bool(_RECRUITMENT_SIGNAL_PATTERN.search(preview_lower))

    if has_legal_signal:
        signals.append("legal_keyword_found")
    if has_recruitment_signal:
        signals.append("recruitment_signal_found")

    # Check if author is in known good companies (whitelist boost)
    is_known_company = False
    if known_companies:
        if author_lower in known_companies or company_lower in known_companies:
            is_known_company = True
            signals.append("known_company")

    # =================================================================
    # PHASE 4: DECISION LOGIC
    # =================================================================

    # Best case: Elite law firm mentioned (highest priority)
    if is_elite_firm:
        return PreQualificationResult(
            should_extract=True,
            confidence=0.95,
            reason="qualified:elite_law_firm",
            signals_found=signals
        )

    # Best case: Both legal AND recruitment signals
    if has_legal_signal and has_recruitment_signal:
        return PreQualificationResult(
            should_extract=True,
            confidence=0.9,
            reason="qualified:legal+recruitment",
            signals_found=signals
        )

    # Good case: Legal signal from known company
    if has_legal_signal and is_known_company:
        return PreQualificationResult(
            should_extract=True,
            confidence=0.85,
            reason="qualified:legal+known_company",
            signals_found=signals
        )

    # Acceptable: Just legal signal (might be worth checking)
    if has_legal_signal:
        return PreQualificationResult(
            should_extract=True,
            confidence=0.6,
            reason="qualified:legal_signal_only",
            signals_found=signals
        )

    # Acceptable: Recruitment signal from known company
    if has_recruitment_signal and is_known_company:
        return PreQualificationResult(
            should_extract=True,
            confidence=0.5,
            reason="qualified:recruitment+known_company",
            signals_found=signals
        )

    # Marginal: Just recruitment signal (low confidence, but extract)
    if has_recruitment_signal:
        return PreQualificationResult(
            should_extract=True,
            confidence=0.4,
            reason="qualified:recruitment_only",
            signals_found=signals
        )

    # Known company with no signals - still worth extracting
    if is_known_company:
        return PreQualificationResult(
            should_extract=True,
            confidence=0.3,
            reason="qualified:known_company_only",
            signals_found=signals
        )

    # No positive signals found - REJECT
    return PreQualificationResult(
        should_extract=False,
        confidence=0.7,
        reason=f"rejected:{RejectionReason.NO_LEGAL_SIGNAL}",
        signals_found=["no_positive_signals"]
    )


def is_excluded_author(author_name: str) -> Tuple[bool, str]:
    """Quick check if author is an agency/job board.
    
    This is the fastest possible check, use before any other processing.
    
    Returns:
        (is_excluded, reason)
    """
    if not author_name:
        return False, ""

    author_lower = author_name.lower().strip()

    if _AGENCY_PATTERN.search(author_lower):
        return True, "agency"

    return False, ""


def has_immediate_exclusion(text: str) -> Tuple[bool, str]:
    """Check if text contains immediate exclusion signals.
    
    Use this for ultra-fast filtering on very short previews.
    
    Returns:
        (is_excluded, reason)
    """
    if not text:
        return False, ""

    text_lower = text.lower()

    if _CONTRACT_EXCLUSION_PATTERN.search(text_lower):
        return True, "stage_alternance"

    if _EXTERNAL_PATTERN.search(text_lower):
        return True, "external_recruitment"

    if _JOBSEEKER_PATTERN.search(text_lower):
        return True, "jobseeker"

    return False, ""


# =============================================================================
# METRICS & MONITORING
# =============================================================================

class PreQualificationMetrics:
    """Track pre-qualification statistics."""

    def __init__(self):
        self.total_checked = 0
        self.accepted = 0
        self.rejected_agency = 0
        self.rejected_stage = 0
        self.rejected_external = 0
        self.rejected_jobseeker = 0
        self.rejected_non_recruitment = 0
        self.rejected_foreign = 0
        self.rejected_no_signal = 0
        # Additional counters for string-based recording
        self.rejected_author_only = 0
        self.passed_to_full_extraction = 0

    def record(self, result) -> None:
        """Record a pre-qualification result or metric name.
        
        Args:
            result: Either a PreQualificationResult object or a string metric name
                   like "rejected_author_only" or "passed_to_full_extraction"
        """
        self.total_checked += 1

        # Handle string-based metric recording (from scrape_subprocess.py)
        if isinstance(result, str):
            if result == "passed_to_full_extraction":
                self.accepted += 1
                self.passed_to_full_extraction += 1
            elif result == "rejected_author_only":
                self.rejected_agency += 1
                self.rejected_author_only += 1
            elif "agency" in result.lower():
                self.rejected_agency += 1
            elif "stage" in result.lower() or "alternance" in result.lower():
                self.rejected_stage += 1
            elif "external" in result.lower():
                self.rejected_external += 1
            elif "jobseeker" in result.lower():
                self.rejected_jobseeker += 1
            elif "non_recruitment" in result.lower():
                self.rejected_non_recruitment += 1
            elif "foreign" in result.lower() or "location" in result.lower():
                self.rejected_foreign += 1
            else:
                self.rejected_no_signal += 1
            return

        # Handle PreQualificationResult object
        if result.should_extract:
            self.accepted += 1
        else:
            reason = result.reason.replace("rejected:", "")
            if reason == RejectionReason.AGENCY:
                self.rejected_agency += 1
            elif reason == RejectionReason.STAGE_ALTERNANCE:
                self.rejected_stage += 1
            elif reason == RejectionReason.EXTERNAL_RECRUITMENT:
                self.rejected_external += 1
            elif reason == RejectionReason.JOBSEEKER:
                self.rejected_jobseeker += 1
            elif reason == RejectionReason.NON_RECRUITMENT:
                self.rejected_non_recruitment += 1
            elif reason == RejectionReason.LOCATION_FOREIGN:
                self.rejected_foreign += 1
            else:
                self.rejected_no_signal += 1

    @property
    def rejection_rate(self) -> float:
        """Percentage of posts rejected."""
        if self.total_checked == 0:
            return 0.0
        return (self.total_checked - self.accepted) / self.total_checked

    @property
    def savings_estimate(self) -> float:
        """Estimated Playwright cost savings (0-1)."""
        # Each rejected post saves ~10 Playwright actions
        return self.rejection_rate * 0.8  # Conservative estimate

    def to_dict(self) -> dict:
        """Export metrics as dictionary."""
        return {
            "total_checked": self.total_checked,
            "accepted": self.accepted,
            "rejection_rate": round(self.rejection_rate, 3),
            "savings_estimate": round(self.savings_estimate, 3),
            "by_reason": {
                "agency": self.rejected_agency,
                "stage_alternance": self.rejected_stage,
                "external": self.rejected_external,
                "jobseeker": self.rejected_jobseeker,
                "non_recruitment": self.rejected_non_recruitment,
                "foreign": self.rejected_foreign,
                "no_signal": self.rejected_no_signal,
            }
        }

    def reset(self) -> None:
        """Reset all counters."""
        self.__init__()


# Global metrics instance
_metrics = PreQualificationMetrics()


def get_prequal_metrics() -> PreQualificationMetrics:
    """Get the global pre-qualification metrics instance."""
    return _metrics


def reset_prequal_metrics() -> None:
    """Reset pre-qualification metrics."""
    _metrics.reset()
