"""Unified filtering configuration - Single source of truth.

This module consolidates ALL filtering lists from the project into a single,
versioned, and testable source. It replaces fragmented definitions scattered
across juridique.py, legal_filter.py, legal_classifier.py, and scrape_subprocess.py.

Usage:
    from filters.unified import UnifiedFilterConfig, get_filter_config
    
    config = get_filter_config()
    result = config.classify_post(text, author, company)

Integration:
    1. All other modules should import from here
    2. Old imports can be aliased for backward compatibility
    3. All changes go through this file → easy to audit

Author: Titan Scraper Team
Version: 1.0.0
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

import structlog

logger = structlog.get_logger(__name__)


# =============================================================================
# VERSION & METADATA
# =============================================================================

FILTER_VERSION = "1.0.0"
FILTER_LAST_UPDATED = "2025-01-15"


# =============================================================================
# CLASSIFICATION RESULT
# =============================================================================

class PostCategory(str, Enum):
    """Classification categories for posts."""
    RELEVANT = "relevant"           # Recrutement juridique interne
    AGENCY = "agency"               # Cabinet de recrutement (concurrent)
    STAGE_ALTERNANCE = "stage"      # Stage, alternance, VIE
    NON_RECRUITMENT = "non_recruitment"  # Contenu non-recrutement
    FREELANCE = "freelance"         # Freelance, consultant indépendant
    EXTERNAL = "external"           # Recrutement pour compte de tiers
    LOW_SCORE = "low_score"         # Score trop faible
    EXCLUDED = "excluded"           # Exclusion générale
    
    def __str__(self) -> str:
        return self.value


@dataclass
class ClassificationResult:
    """Result of post classification."""
    category: PostCategory
    is_relevant: bool
    legal_score: float
    recruitment_score: float
    combined_score: float
    exclusion_reason: Optional[str]
    matched_patterns: List[str]
    confidence: float  # 0-1, certainty of classification
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": str(self.category),
            "is_relevant": self.is_relevant,
            "legal_score": round(self.legal_score, 3),
            "recruitment_score": round(self.recruitment_score, 3),
            "combined_score": round(self.combined_score, 3),
            "exclusion_reason": self.exclusion_reason,
            "matched_patterns": self.matched_patterns[:10],  # Limit for display
            "confidence": round(self.confidence, 2),
        }


# =============================================================================
# UNIFIED KEYWORD LISTS
# =============================================================================

# --- LEGAL ROLES (inclusion) ---
LEGAL_ROLES: FrozenSet[str] = frozenset([
    # Juristes
    "juriste", "juriste junior", "juriste confirmé", "juriste confirme",
    "juriste senior", "juriste d'entreprise", "juriste entreprise",
    "juriste corporate", "juriste droit social", "juriste droit des affaires",
    "juriste contrats", "juriste contentieux", "juriste conformité",
    "juriste conformite", "juriste compliance", "juriste recouvrement",
    "juriste legal ops", "juriste généraliste", "juriste generaliste",
    "juriste droit public", "juriste droit privé", "juriste droit prive",
    "juriste immobilier", "juriste bancaire", "juriste assurances",
    "juriste propriété intellectuelle", "juriste pi", "juriste it",
    "juriste rgpd", "juriste data", "juriste m&a",
    
    # Legal Counsel
    "legal counsel", "senior legal counsel", "junior legal counsel",
    "legal manager", "legal operations", "legal ops", "legal director",
    
    # Avocats
    "avocat", "avocate", "avocat collaborateur", "avocate collaboratrice",
    "avocat associé", "avocat associe", "avocate associée", "avocate associee",
    "avocat counsel", "avocate counsel", "avocat junior", "avocat senior",
    "collaborateur avocat", "collaboratrice avocate",
    
    # Direction
    "responsable juridique", "directeur juridique", "directrice juridique",
    "head of legal", "chief legal officer", "clo", "general counsel",
    "secrétaire général", "secretaire general",
    "directeur des affaires juridiques",
    
    # Compliance / DPO
    "compliance officer", "compliance manager", "responsable conformité",
    "responsable conformite", "dpo", "data protection officer",
    "délégué à la protection des données", "privacy officer", "privacy manager",
    
    # Contract Management
    "contract manager", "gestionnaire de contrats", "responsable contrats",
    
    # Paralegal
    "paralegal", "paralegale", "assistant juridique", "assistante juridique",
    "legal assistant",
    
    # Notariat
    "notaire", "notaire associé", "notaire associe", "notaire salarié",
    "notaire salarie", "clerc de notaire", "clerc principal",
    "rédacteur d'actes", "redacteur actes",
    
    # Fiscalistes
    "fiscaliste", "juriste fiscal", "tax lawyer", "tax counsel",
])

# Short stems for flexible matching
LEGAL_STEMS: FrozenSet[str] = frozenset([
    "juriste", "avocat", "notaire", "paralegal", "counsel", "legal",
    "juridique", "fiscaliste", "compliance", "dpo", "contract manager",
])

# --- RECRUITMENT SIGNALS (inclusion) ---
RECRUITMENT_SIGNALS: FrozenSet[str] = frozenset([
    # French explicit
    "nous recrutons", "on recrute", "je recrute",
    "nous cherchons", "on cherche", "je cherche",
    "poste à pourvoir", "poste a pourvoir",
    "opportunité", "opportunite",
    "rejoignez notre équipe", "rejoignez notre equipe",
    "rejoindre notre équipe", "rejoindre notre equipe",
    
    # Contract types
    "cdi", "cdd", "temps plein", "full time",
    
    # Recruitment indicators
    "offre d'emploi", "offre emploi", "recrutement", "recrute",
    "recruiting", "hiring", "we are hiring", "we're hiring", "is hiring",
    "join our team", "join the team", "looking for",
    
    # Offer details
    "profil recherché", "profil recherche", "missions principales",
    "rattaché à", "rattache a", "expérience requise", "experience requise",
    "vous justifiez", "compétences requises", "competences requises",
    "postulez", "candidature", "envoyez cv", "envoyez votre cv",
    
    # Position creation
    "création de poste", "creation de poste", "nouveau poste",
    "poste ouvert", "à pourvoir", "a pourvoir", "prise de poste",
    
    # Team context
    "renforcer notre équipe", "renforcer notre equipe",
    "agrandir notre équipe", "se renforcer",
    "équipe juridique recrute", "equipe juridique recrute",
    "direction juridique recrute", "cabinet recrute",
])

# --- INTERNAL RECRUITMENT (strong positive signals) ---
INTERNAL_RECRUITMENT_PATTERNS: FrozenSet[str] = frozenset([
    "nous recrutons", "on recrute", "notre entreprise recrute",
    "notre cabinet recrute", "notre équipe recrute", "notre equipe recrute",
    "notre société recrute", "notre societe recrute", "notre groupe recrute",
    "notre direction juridique recherche", "nous recherchons", "nous cherchons",
    "je recrute pour mon équipe", "je recrute pour mon equipe",
    "rejoindre notre équipe", "rejoindre notre equipe",
    "intégrer notre équipe", "integrer notre equipe",
    "we are hiring", "we're hiring", "we are recruiting", "we're recruiting",
    "we are looking for", "we're looking for", "join our team", "join us",
    "our team is hiring", "our company is hiring",
])


# =============================================================================
# EXCLUSION PATTERNS (consolidated)
# =============================================================================

# --- AGENCIES (competitors) ---
AGENCY_PATTERNS: FrozenSet[str] = frozenset([
    # Generic terms
    "cabinet de recrutement", "cabinet recrutement", "agence de recrutement",
    "agence recrutement", "chasseur de têtes", "chasseur de tetes",
    "chasseurs de têtes", "chasseurs de tetes", "headhunter", "headhunting",
    "executive search", "talent acquisition agency", "rh externalisé",
    "rh externalisee", "rh externe", "externalisation rh",
    "interim", "intérim", "société d'intérim", "societe interim",
    "esn", "ssii", "société de conseil rh",
    
    # Agency formulations
    "notre client recherche", "pour le compte de notre client",
    "pour notre client", "notre client, un", "notre client recrute",
    "client final", "mission pour", "nous recrutons pour",
    "mandat de recrutement", "pour un de nos clients",
    "pour l'un de nos clients", "l'un de nos clients",
    "un de nos partenaires", "confidentiel", "client confidentiel",
    "société confidentielle", "entreprise confidentielle",
    
    # Known agencies (France)
    "michael page", "robert half", "hays", "fed legal", "fed juridique",
    "page personnel", "page group", "expectra", "adecco", "manpower",
    "randstad", "spring professional", "lincoln associates", "laurence simons",
    "taylor root", "legadvisor", "approach people", "legal staffing",
    "major hunter", "morgan philips", "spencer stuart", "russell reynolds",
    "egon zehnder", "korn ferry", "boyden", "eric salmon", "odgers berndtson",
    "heidrick & struggles", "heidrick struggles", "vidal associates",
    "cadreo", "walters people", "robert walters",
    
    # Legal-specific agencies
    "legal&hr", "legal & hr", "legalhrconsulting", "avoconseil",
    "lawpic", "juriwork", "juritalents", "legalplace recrutement",
    
    # Job boards
    "keljob", "monster", "cadremploi", "apec", "indeed", "linkedin talent",
    "welcometothejungle", "welcome to the jungle", "jobteaser", "meteojob",
    "regionsjob", "hellowork", "lemonde emploi", "village de la justice",
    
    # Revealer expressions
    "cabinet spécialisé", "cabinet specialise", "acteur du recrutement",
    "expert en recrutement", "recruteur spécialisé", "recruteur specialise",
    "recruteur juridique", "consultant recrutement", "consultante recrutement",
    "chargé de recrutement", "charge de recrutement",
    "chargée de recrutement", "chargee de recrutement",
    "recruiter", "talent manager", "talent partner", "sourceur", "sourcing",
])

# --- EXTERNAL RECRUITMENT (recruiting for others) ---
EXTERNAL_RECRUITMENT_PATTERNS: FrozenSet[str] = frozenset([
    "pour l'un de nos clients", "pour l un de nos clients",
    "pour un de nos clients", "notre client recrute", "notre client recherche",
    "pour le compte de", "en mission chez", "mission chez notre client",
    "détaché chez", "detache chez", "mis à disposition", "mis a disposition",
])

# --- NON-RECRUITMENT CONTENT ---
NON_RECRUITMENT_PATTERNS: FrozenSet[str] = frozenset([
    # Legal watch / Articles
    "veille juridique", "actualité juridique", "actualite juridique",
    "article juridique", "analyse juridique", "décryptage", "decryptage",
    "tribune", "point de vue", "chronique", "revue de presse",
    
    # Events / Conferences
    "conférence", "conference", "séminaire", "seminaire", "webinar",
    "webinaire", "colloque", "forum", "salon", "petit déjeuner",
    "petit dejeuner", "afterwork", "networking", "masterclass",
    
    # Training
    "formation", "e-learning", "elearning", "mooc", "certification",
    "diplôme", "diplome", "examen", "concours",
    "résultats du barreau", "resultats barreau",
    
    # Publications
    "livre blanc", "white paper", "ebook", "e-book", "publication",
    "parution", "ouvrage", "guide pratique",
    
    # Testimonials
    "retour d'expérience", "retour d experience", "témoignage", "temoignage",
    "interview de", "portrait de", "parcours de",
    
    # Promotional
    "sponsorisé", "sponsorise", "sponsored", "publicité", "publicite",
    "partenariat", "#ad", "#pub", "#sponsored",
    
    # Company life (non-recruitment)
    "team building", "séminaire d'équipe", "seminaire equipe",
    "fête de fin d'année", "fete fin annee", "anniversaire entreprise",
    "inauguration", "déménagement", "demenagement", "nouveaux locaux",
    
    # Emotional / Congratulations
    "fier de", "fière de", "fiere de", "félicitations", "felicitations",
    "bravo à", "bravo a", "merci à", "merci a",
    "heureux d'annoncer", "heureux d annoncer",
    "heureuse d'annoncer", "heureuse d annoncer",
    "bienvenue à", "bienvenue a",
    
    # News
    "breaking news", "flash info", "dernière minute", "derniere minute",
])

# --- STAGE / ALTERNANCE / VIE ---
STAGE_ALTERNANCE_PATTERNS: FrozenSet[str] = frozenset([
    # Stage
    "stage", "stagiaire", "stages", "stagiaires", "offre de stage",
    "stage pfe", "stage fin d'études", "stage fin d etudes",
    "élève avocat", "eleve avocat", "élève-avocat", "eleve-avocat",
    
    # Alternance
    "alternance", "alternant", "alternante", "contrat alternance",
    "en alternance", "poste en alternance",
    
    # Apprentissage
    "apprentissage", "apprenti", "apprentie", "contrat d'apprentissage",
    "contrat apprentissage",
    
    # Contrat pro
    "contrat pro", "contrat de professionnalisation",
    
    # VIE
    "vie", "v.i.e", "v.i.e.", "volontariat international",
    
    # English
    "internship", "intern", "trainee", "work-study", "work study",
    "working student", "graduate program",
])

# --- FREELANCE / INDEPENDENT ---
FREELANCE_PATTERNS: FrozenSet[str] = frozenset([
    "freelance", "free-lance", "indépendant", "independant",
    "consultant indépendant", "consultant independant",
    "auto-entrepreneur", "autoentrepreneur", "cabinet rh",
    "consultant rh", "consultante rh", "jobboard", "job board",
    "plateforme emploi",
])


# =============================================================================
# COMPILED REGEX PATTERNS
# =============================================================================

@lru_cache(maxsize=1)
def _compile_patterns() -> Dict[str, re.Pattern]:
    """Compile all patterns into regex (cached)."""
    def compile_set(patterns: FrozenSet[str]) -> re.Pattern:
        if not patterns:
            return re.compile(r"(?!)")  # Never matches
        escaped = [re.escape(p) for p in patterns]
        return re.compile(r"\b(" + "|".join(escaped) + r")\b", re.IGNORECASE)
    
    return {
        "legal_roles": compile_set(LEGAL_ROLES),
        "legal_stems": compile_set(LEGAL_STEMS),
        "recruitment_signals": compile_set(RECRUITMENT_SIGNALS),
        "internal_recruitment": compile_set(INTERNAL_RECRUITMENT_PATTERNS),
        "agency": compile_set(AGENCY_PATTERNS),
        "external": compile_set(EXTERNAL_RECRUITMENT_PATTERNS),
        "non_recruitment": compile_set(NON_RECRUITMENT_PATTERNS),
        "stage_alternance": compile_set(STAGE_ALTERNANCE_PATTERNS),
        "freelance": compile_set(FREELANCE_PATTERNS),
    }


# =============================================================================
# UNIFIED FILTER CONFIG
# =============================================================================

@dataclass
class UnifiedFilterConfig:
    """Unified configuration for post filtering.
    
    This is the single source of truth for all filtering decisions.
    """
    
    # Scoring weights (Titan Partners formula)
    legal_weight: float = 0.6
    recruitment_weight: float = 0.4
    
    # Score thresholds
    min_legal_score: float = 0.20
    min_recruitment_score: float = 0.15
    min_combined_score: float = 0.25
    
    # Feature flags
    exclude_stage_alternance: bool = True
    exclude_agencies: bool = True
    exclude_external: bool = True
    exclude_non_recruitment: bool = True
    exclude_freelance: bool = True
    
    # Post age
    max_post_age_days: int = 21
    
    # Additional exclusion keywords (can be extended)
    custom_exclusions: Set[str] = field(default_factory=set)
    custom_inclusions: Set[str] = field(default_factory=set)
    
    def _get_patterns(self) -> Dict[str, re.Pattern]:
        """Get compiled patterns."""
        return _compile_patterns()
    
    def _count_matches(self, text: str, pattern: re.Pattern) -> Tuple[int, List[str]]:
        """Count matches and return matched strings."""
        matches = pattern.findall(text)
        return len(matches), list(set(matches))
    
    def _calculate_legal_score(self, text: str) -> Tuple[float, List[str]]:
        """Calculate legal relevance score (0-1)."""
        patterns = self._get_patterns()
        
        # Count role matches
        role_count, role_matches = self._count_matches(text, patterns["legal_roles"])
        stem_count, stem_matches = self._count_matches(text, patterns["legal_stems"])
        
        # Role matches are worth more than stems
        score = min(1.0, (role_count * 0.3) + (stem_count * 0.1))
        
        # Boost for multiple distinct roles
        if role_count >= 2:
            score = min(1.0, score + 0.2)
        
        return score, role_matches + stem_matches
    
    def _calculate_recruitment_score(self, text: str) -> Tuple[float, List[str]]:
        """Calculate recruitment signal score (0-1)."""
        patterns = self._get_patterns()
        
        # General recruitment signals
        signal_count, signal_matches = self._count_matches(text, patterns["recruitment_signals"])
        
        # Internal recruitment (stronger signal)
        internal_count, internal_matches = self._count_matches(text, patterns["internal_recruitment"])
        
        score = min(1.0, (signal_count * 0.15) + (internal_count * 0.35))
        
        return score, signal_matches + internal_matches
    
    def _check_exclusions(self, text: str, author: str = "", company: str = "") -> Tuple[bool, PostCategory, str, List[str]]:
        """Check if post should be excluded.
        
        Returns:
            (is_excluded, category, reason, matched_patterns)
        """
        patterns = self._get_patterns()
        full_text = f"{text} {author} {company}".lower()
        
        # Check stage/alternance
        if self.exclude_stage_alternance:
            count, matches = self._count_matches(full_text, patterns["stage_alternance"])
            # Except if it says "hors stage" or "pas de stage"
            if count > 0 and "hors stage" not in full_text and "pas de stage" not in full_text:
                return True, PostCategory.STAGE_ALTERNANCE, "Stage/Alternance/VIE", matches
        
        # Check agency
        if self.exclude_agencies:
            count, matches = self._count_matches(full_text, patterns["agency"])
            if count >= 2:  # Need at least 2 matches to be sure
                return True, PostCategory.AGENCY, "Cabinet de recrutement", matches
        
        # Check external recruitment
        if self.exclude_external:
            count, matches = self._count_matches(full_text, patterns["external"])
            if count > 0:
                return True, PostCategory.EXTERNAL, "Recrutement externe", matches
        
        # Check freelance
        if self.exclude_freelance:
            count, matches = self._count_matches(full_text, patterns["freelance"])
            if count >= 2:  # Author might mention "ex-freelance"
                return True, PostCategory.FREELANCE, "Freelance/Indépendant", matches
        
        # Check non-recruitment content
        if self.exclude_non_recruitment:
            count, matches = self._count_matches(full_text, patterns["non_recruitment"])
            if count >= 3:  # Multiple signals needed
                return True, PostCategory.NON_RECRUITMENT, "Contenu non-recrutement", matches
        
        # Check custom exclusions
        for excl in self.custom_exclusions:
            if excl.lower() in full_text:
                return True, PostCategory.EXCLUDED, f"Exclusion personnalisée: {excl}", [excl]
        
        return False, PostCategory.RELEVANT, "", []
    
    def classify_post(self, text: str, author: str = "", 
                      company: str = "") -> ClassificationResult:
        """Classify a post.
        
        Args:
            text: Post content
            author: Author name/title
            company: Company name
            
        Returns:
            ClassificationResult with full details
        """
        all_matched: List[str] = []
        
        # Check exclusions first
        is_excluded, excl_category, excl_reason, excl_matches = self._check_exclusions(
            text, author, company)
        
        if is_excluded:
            return ClassificationResult(
                category=excl_category,
                is_relevant=False,
                legal_score=0.0,
                recruitment_score=0.0,
                combined_score=0.0,
                exclusion_reason=excl_reason,
                matched_patterns=excl_matches,
                confidence=0.8,  # Exclusions are fairly certain
            )
        
        # Calculate scores
        legal_score, legal_matches = self._calculate_legal_score(text)
        recruit_score, recruit_matches = self._calculate_recruitment_score(text)
        all_matched.extend(legal_matches)
        all_matched.extend(recruit_matches)
        
        # Combined score (Titan Partners formula)
        combined_score = (legal_score * self.legal_weight) + (recruit_score * self.recruitment_weight)
        
        # Custom inclusions boost
        full_text = text.lower()
        for incl in self.custom_inclusions:
            if incl.lower() in full_text:
                combined_score = min(1.0, combined_score + 0.1)
                all_matched.append(f"+{incl}")
        
        # Determine if relevant
        is_relevant = (
            legal_score >= self.min_legal_score and
            recruit_score >= self.min_recruitment_score and
            combined_score >= self.min_combined_score
        )
        
        # Calculate confidence
        if is_relevant:
            # Higher scores = more confidence
            confidence = min(1.0, 0.5 + (combined_score * 0.5))
        else:
            # Low score but close to threshold = less confident
            if combined_score > self.min_combined_score * 0.7:
                confidence = 0.6
            else:
                confidence = 0.9  # Clearly not relevant
        
        category = PostCategory.RELEVANT if is_relevant else PostCategory.LOW_SCORE
        reason = None if is_relevant else f"Score insuffisant: {combined_score:.2f} < {self.min_combined_score}"
        
        return ClassificationResult(
            category=category,
            is_relevant=is_relevant,
            legal_score=legal_score,
            recruitment_score=recruit_score,
            combined_score=combined_score,
            exclusion_reason=reason,
            matched_patterns=list(set(all_matched)),
            confidence=confidence,
        )
    
    def get_config_hash(self) -> str:
        """Get hash of current configuration for versioning."""
        config_dict = {
            "version": FILTER_VERSION,
            "weights": (self.legal_weight, self.recruitment_weight),
            "thresholds": (self.min_legal_score, self.min_recruitment_score, self.min_combined_score),
            "flags": (self.exclude_stage_alternance, self.exclude_agencies, 
                     self.exclude_external, self.exclude_non_recruitment,
                     self.exclude_freelance),
            "lists_hash": hashlib.md5(
                json.dumps([
                    sorted(LEGAL_ROLES),
                    sorted(AGENCY_PATTERNS),
                    sorted(STAGE_ALTERNANCE_PATTERNS),
                ], ensure_ascii=False).encode()
            ).hexdigest()[:8],
        }
        return hashlib.md5(
            json.dumps(config_dict, sort_keys=True).encode()
        ).hexdigest()[:16]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the filter configuration."""
        return {
            "version": FILTER_VERSION,
            "last_updated": FILTER_LAST_UPDATED,
            "config_hash": self.get_config_hash(),
            "counts": {
                "legal_roles": len(LEGAL_ROLES),
                "legal_stems": len(LEGAL_STEMS),
                "recruitment_signals": len(RECRUITMENT_SIGNALS),
                "internal_patterns": len(INTERNAL_RECRUITMENT_PATTERNS),
                "agency_patterns": len(AGENCY_PATTERNS),
                "external_patterns": len(EXTERNAL_RECRUITMENT_PATTERNS),
                "non_recruitment_patterns": len(NON_RECRUITMENT_PATTERNS),
                "stage_patterns": len(STAGE_ALTERNANCE_PATTERNS),
                "freelance_patterns": len(FREELANCE_PATTERNS),
            },
            "total_patterns": (
                len(LEGAL_ROLES) + len(RECRUITMENT_SIGNALS) + 
                len(AGENCY_PATTERNS) + len(STAGE_ALTERNANCE_PATTERNS) +
                len(FREELANCE_PATTERNS) + len(NON_RECRUITMENT_PATTERNS)
            ),
            "thresholds": {
                "min_legal_score": self.min_legal_score,
                "min_recruitment_score": self.min_recruitment_score,
                "min_combined_score": self.min_combined_score,
            },
            "weights": {
                "legal": self.legal_weight,
                "recruitment": self.recruitment_weight,
            },
        }


# =============================================================================
# SINGLETON & CONVENIENCE
# =============================================================================

_config_instance: Optional[UnifiedFilterConfig] = None


def get_filter_config() -> UnifiedFilterConfig:
    """Get or create unified filter config singleton."""
    global _config_instance
    if _config_instance is None:
        _config_instance = UnifiedFilterConfig()
    return _config_instance


def reset_filter_config() -> None:
    """Reset singleton (for testing)."""
    global _config_instance
    _config_instance = None
    _compile_patterns.cache_clear()


def classify_post(text: str, author: str = "", company: str = "") -> ClassificationResult:
    """Convenience function to classify a post."""
    return get_filter_config().classify_post(text, author, company)


def is_relevant_post(text: str, author: str = "", company: str = "") -> bool:
    """Convenience function to check if post is relevant."""
    return get_filter_config().classify_post(text, author, company).is_relevant


# =============================================================================
# BACKWARD COMPATIBILITY
# =============================================================================

# Aliases for old imports from filters.juridique
LEGAL_ROLE_KEYWORDS = list(LEGAL_ROLES)
RECRUITMENT_SIGNALS_LIST = list(RECRUITMENT_SIGNALS)
EXCLUSION_AGENCY_PATTERNS = list(AGENCY_PATTERNS)
EXCLUSION_STAGE_ALTERNANCE = list(STAGE_ALTERNANCE_PATTERNS)


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Core
    "UnifiedFilterConfig",
    "ClassificationResult", 
    "PostCategory",
    "get_filter_config",
    "reset_filter_config",
    "classify_post",
    "is_relevant_post",
    
    # Pattern sets
    "LEGAL_ROLES",
    "LEGAL_STEMS",
    "RECRUITMENT_SIGNALS",
    "INTERNAL_RECRUITMENT_PATTERNS",
    "AGENCY_PATTERNS",
    "EXTERNAL_RECRUITMENT_PATTERNS",
    "NON_RECRUITMENT_PATTERNS",
    "STAGE_ALTERNANCE_PATTERNS",
    "FREELANCE_PATTERNS",
    
    # Version
    "FILTER_VERSION",
    "FILTER_LAST_UPDATED",
    
    # Backward compat
    "LEGAL_ROLE_KEYWORDS",
    "RECRUITMENT_SIGNALS_LIST",
    "EXCLUSION_AGENCY_PATTERNS",
    "EXCLUSION_STAGE_ALTERNANCE",
]
