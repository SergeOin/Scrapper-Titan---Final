"""
Module de scraping LinkedIn dédié pour Titan Partners.

Ce module fournit des fonctionnalités spécifiques pour:
- Détecter le type d'auteur (Entreprise vs Individu vs Agence)
- Extraire les métadonnées pertinentes des posts LinkedIn
- Appliquer les filtres spécifiques Titan Partners

ARCHITECTURE:
    Ce module s'intègre avec:
    - scraper/worker.py : extraction bas niveau des posts
    - filters/juridique.py : configuration des mots-clés
    - scraper/legal_filter.py : filtrage détaillé

USAGE:
    from scraper.linkedin import LinkedInPostAnalyzer, AuthorType
    
    analyzer = LinkedInPostAnalyzer()
    result = analyzer.analyze_post(text, author, author_profile)
    
    if result.author_type == AuthorType.COMPANY:
        # Post d'une entreprise
        ...
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum, auto
from typing import List, Optional, Tuple, Dict, Any
import logging

# Import de la configuration juridique
try:
    from filters.juridique import (
        JuridiqueConfig,
        get_default_config,
        EXCLUSION_AGENCY_PATTERNS,
        EXCLUSION_EXTERNAL_RECRUITMENT,
        INTERNAL_RECRUITMENT_PATTERNS,
    )
except ImportError:
    # Fallback si filters n'est pas dans le path
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from filters.juridique import (
        JuridiqueConfig,
        get_default_config,
        EXCLUSION_AGENCY_PATTERNS,
        EXCLUSION_EXTERNAL_RECRUITMENT,
        INTERNAL_RECRUITMENT_PATTERNS,
    )

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS ET CONSTANTES
# =============================================================================

class AuthorType(Enum):
    """Type d'auteur d'un post LinkedIn."""
    COMPANY = auto()          # Page entreprise (cible)
    INDIVIDUAL = auto()       # Profil personnel
    RECRUITMENT_AGENCY = auto()  # Agence de recrutement (à exclure)
    FREELANCE = auto()        # Indépendant (à exclure)
    UNKNOWN = auto()          # Non déterminé


class PostRelevance(Enum):
    """Niveau de pertinence d'un post pour Titan Partners."""
    HIGH = auto()      # Recrutement interne juridique confirmé
    MEDIUM = auto()    # Probable recrutement juridique
    LOW = auto()       # Signal faible
    EXCLUDED = auto()  # Post exclu (agence, externe, etc.)


# Patterns pour détecter les pages entreprise (vs profils individuels)
COMPANY_PAGE_INDICATORS = [
    # Suffixes typiques de pages entreprise
    r"\b(SAS|SARL|SA|SASU|SNC|GIE|SCM|SCP|SELARL|GmbH|AG|Ltd|LLC|Inc|Corp|PLC)\b",
    # Termes indiquant une entreprise
    r"\b(groupe|group|cabinet|étude|etude|société|societe|company|entreprise|agence|banque|assurance)\b",
    # Indicateurs de taille
    r"\b\d+[\s,.]?\d*\s*(employés|employees|collaborateurs|salariés|salaries|abonnés|followers)\b",
]

# Patterns pour détecter les profils individuels
INDIVIDUAL_PROFILE_INDICATORS = [
    # Titres de poste typiques (l'auteur parle de lui-même)
    r"^(juriste|avocat|notaire|legal counsel|directeur juridique|responsable juridique)\b",
    # Certifications individuelles
    r"\b(barreau de|inscrit au barreau|membre du barreau|ll\.?m|ph\.?d|master)\b",
    # Expressions personnelles
    r"\b(je suis|i am|passionné par|passionate about|spécialisé en|specialized in)\b",
]

# Patterns d'agences de recrutement (basés sur filters/juridique.py)
AGENCY_INDICATORS = [
    r"\b(cabinet de recrutement|recruitment agency|headhunter|executive search)\b",
    r"\b(michael page|robert half|hays|fed legal|fed juridique)\b",
    r"\b(randstad|adecco|manpower|expectra)\b",
    r"\bnotre client (recherche|recrute)\b",
    r"\bpour (le compte de|l'un de) nos? clients?\b",
]


# =============================================================================
# DATACLASSES DE RÉSULTAT
# =============================================================================

@dataclass
class AuthorAnalysis:
    """Résultat de l'analyse du type d'auteur."""
    author_type: AuthorType
    confidence: float  # 0.0 à 1.0
    indicators_found: List[str] = field(default_factory=list)
    is_excluded: bool = False
    exclusion_reason: str = ""


@dataclass
class PostAnalysisResult:
    """Résultat complet de l'analyse d'un post LinkedIn."""
    # Analyse de l'auteur
    author_type: AuthorType
    author_confidence: float
    
    # Type de recrutement
    is_internal_recruitment: bool  # True si l'entreprise recrute pour elle-même
    is_external_recruitment: bool  # True si c'est pour un client (agence)
    
    # Pertinence
    relevance: PostRelevance
    relevance_score: float  # 0.0 à 1.0
    
    # Signaux détectés
    legal_keywords_found: List[str] = field(default_factory=list)
    recruitment_signals_found: List[str] = field(default_factory=list)
    
    # Exclusions
    is_excluded: bool = False
    exclusion_reason: str = ""
    exclusion_terms: List[str] = field(default_factory=list)
    
    # Métadonnées
    company_name: Optional[str] = None
    post_age_days: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Conversion en dictionnaire pour sérialisation."""
        return {
            "author_type": self.author_type.name,
            "author_confidence": self.author_confidence,
            "is_internal_recruitment": self.is_internal_recruitment,
            "is_external_recruitment": self.is_external_recruitment,
            "relevance": self.relevance.name,
            "relevance_score": self.relevance_score,
            "legal_keywords_found": self.legal_keywords_found,
            "recruitment_signals_found": self.recruitment_signals_found,
            "is_excluded": self.is_excluded,
            "exclusion_reason": self.exclusion_reason,
            "exclusion_terms": self.exclusion_terms,
            "company_name": self.company_name,
            "post_age_days": self.post_age_days,
        }


# =============================================================================
# CLASSE PRINCIPALE D'ANALYSE
# =============================================================================

class LinkedInPostAnalyzer:
    """
    Analyseur de posts LinkedIn pour Titan Partners.
    
    Responsabilités:
    - Déterminer le type d'auteur (entreprise, individu, agence)
    - Détecter le type de recrutement (interne vs externe)
    - Calculer un score de pertinence
    - Appliquer les exclusions configurées
    
    Usage:
        analyzer = LinkedInPostAnalyzer()
        result = analyzer.analyze_post(
            text="Nous recrutons un juriste...",
            author="Société ABC",
            author_profile="https://linkedin.com/company/abc"
        )
    """
    
    def __init__(self, config: Optional[JuridiqueConfig] = None):
        """
        Initialise l'analyseur avec une configuration.
        
        Args:
            config: Configuration des mots-clés et règles.
                   Si None, utilise la config par défaut Titan Partners.
        """
        self.config = config or get_default_config()
        self._compiled_patterns = self.config.compile_patterns()
        
        # Compile les patterns additionnels
        self._company_patterns = [re.compile(p, re.IGNORECASE) for p in COMPANY_PAGE_INDICATORS]
        self._individual_patterns = [re.compile(p, re.IGNORECASE) for p in INDIVIDUAL_PROFILE_INDICATORS]
        self._agency_patterns = [re.compile(p, re.IGNORECASE) for p in AGENCY_INDICATORS]
    
    def _normalize_text(self, text: str) -> str:
        """Normalise le texte pour l'analyse."""
        if not text:
            return ""
        # Lowercase
        text = text.lower()
        # Remove accents
        text = unicodedata.normalize('NFKD', text)
        text = ''.join(c for c in text if not unicodedata.combining(c))
        # Remove emojis
        text = re.sub(r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF]+', '', text)
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    
    def analyze_author(
        self,
        author: str,
        author_profile: Optional[str] = None,
        author_description: Optional[str] = None
    ) -> AuthorAnalysis:
        """
        Analyse le type d'auteur d'un post.
        
        Args:
            author: Nom de l'auteur
            author_profile: URL du profil LinkedIn (si disponible)
            author_description: Description/bio de l'auteur (si disponible)
        
        Returns:
            AuthorAnalysis avec le type déterminé et la confiance
        """
        indicators: List[str] = []
        author_norm = self._normalize_text(author or "")
        desc_norm = self._normalize_text(author_description or "")
        combined = f"{author_norm} {desc_norm}"
        
        # Vérifier si c'est une agence de recrutement (exclusion prioritaire)
        for pattern in self._agency_patterns:
            if pattern.search(combined):
                indicators.append(f"agency_pattern: {pattern.pattern[:50]}")
                return AuthorAnalysis(
                    author_type=AuthorType.RECRUITMENT_AGENCY,
                    confidence=0.9,
                    indicators_found=indicators,
                    is_excluded=True,
                    exclusion_reason="cabinet_recrutement"
                )
        
        # Vérifier les patterns d'exclusion d'agence depuis la config
        for agency_term in self.config.agency_patterns[:30]:  # Top 30 pour perf
            if agency_term.lower() in combined:
                indicators.append(f"agency_term: {agency_term}")
                return AuthorAnalysis(
                    author_type=AuthorType.RECRUITMENT_AGENCY,
                    confidence=0.85,
                    indicators_found=indicators,
                    is_excluded=True,
                    exclusion_reason="cabinet_recrutement"
                )
        
        # Vérifier si c'est un freelance
        freelance_terms = ["freelance", "indépendant", "independant", "auto-entrepreneur", "consultant indépendant"]
        for term in freelance_terms:
            if term in combined:
                indicators.append(f"freelance_term: {term}")
                return AuthorAnalysis(
                    author_type=AuthorType.FREELANCE,
                    confidence=0.8,
                    indicators_found=indicators,
                    is_excluded=True,
                    exclusion_reason="freelance_independant"
                )
        
        # Score entreprise vs individu
        company_score = 0.0
        individual_score = 0.0
        
        # URL de profil company vs personal
        if author_profile:
            if "/company/" in author_profile.lower():
                company_score += 0.5
                indicators.append("url_type: company_page")
            elif "/in/" in author_profile.lower():
                individual_score += 0.3
                indicators.append("url_type: personal_profile")
        
        # Patterns d'entreprise
        for pattern in self._company_patterns:
            if pattern.search(combined):
                company_score += 0.2
                indicators.append(f"company_pattern: {pattern.pattern[:30]}")
        
        # Patterns d'individu
        for pattern in self._individual_patterns:
            if pattern.search(combined):
                individual_score += 0.2
                indicators.append(f"individual_pattern: {pattern.pattern[:30]}")
        
        # Nombre d'abonnés/followers (indicateur de page entreprise)
        follower_match = re.search(r'(\d[\d\s,.]*)+(k|m)?\s*(abonné|follower|employé|employee)', combined)
        if follower_match:
            company_score += 0.15
            indicators.append("has_follower_count")
        
        # Déterminer le type
        if company_score > individual_score and company_score >= 0.3:
            return AuthorAnalysis(
                author_type=AuthorType.COMPANY,
                confidence=min(0.95, 0.5 + company_score),
                indicators_found=indicators,
                is_excluded=False,
                exclusion_reason=""
            )
        elif individual_score > company_score and individual_score >= 0.3:
            return AuthorAnalysis(
                author_type=AuthorType.INDIVIDUAL,
                confidence=min(0.95, 0.5 + individual_score),
                indicators_found=indicators,
                is_excluded=False,
                exclusion_reason=""
            )
        else:
            return AuthorAnalysis(
                author_type=AuthorType.UNKNOWN,
                confidence=0.3,
                indicators_found=indicators,
                is_excluded=False,
                exclusion_reason=""
            )
    
    def detect_recruitment_type(self, text: str) -> Tuple[bool, bool, List[str]]:
        """
        Détecte si le post est un recrutement interne ou externe.
        
        Args:
            text: Contenu du post
            
        Returns:
            Tuple (is_internal, is_external, signals_found)
        """
        text_norm = self._normalize_text(text)
        signals: List[str] = []
        
        # Détecter recrutement externe (agence pour client)
        is_external = False
        for pattern in self.config.external_recruitment:
            if pattern.lower() in text_norm:
                is_external = True
                signals.append(f"external: {pattern}")
        
        # Détecter recrutement interne
        is_internal = False
        for pattern in self.config.internal_patterns:
            if pattern.lower() in text_norm:
                is_internal = True
                signals.append(f"internal: {pattern}")
        
        # Si on a des signaux internes mais pas externes, c'est probablement interne
        if not is_external and not is_internal:
            # Chercher des signaux de recrutement génériques
            for signal in self.config.recruitment_signals[:20]:  # Top 20
                if signal.lower() in text_norm:
                    is_internal = True  # Présume interne par défaut
                    signals.append(f"recruitment: {signal}")
                    break
        
        return is_internal, is_external, signals
    
    def calculate_relevance_score(
        self,
        text: str,
        author_analysis: AuthorAnalysis,
        is_internal: bool,
        is_external: bool
    ) -> Tuple[float, List[str], List[str]]:
        """
        Calcule le score de pertinence global du post.
        
        Returns:
            Tuple (score, legal_keywords, recruitment_signals)
        """
        text_norm = self._normalize_text(text)
        legal_keywords: List[str] = []
        recruitment_signals: List[str] = []
        score = 0.0
        
        # Bonus si auteur est une entreprise
        if author_analysis.author_type == AuthorType.COMPANY:
            score += 0.2
        
        # Pénalité si recrutement externe
        if is_external:
            score -= 0.5
        
        # Bonus si recrutement interne
        if is_internal:
            score += 0.15
        
        # Détecter les mots-clés juridiques
        legal_pattern = self._compiled_patterns.get("legal_roles")
        if legal_pattern:
            matches = legal_pattern.findall(text_norm)
            legal_keywords = list(set(matches))
            score += min(0.3, len(legal_keywords) * 0.1)
        
        # Détecter les signaux de recrutement
        recruit_pattern = self._compiled_patterns.get("recruitment_signals")
        if recruit_pattern:
            matches = recruit_pattern.findall(text_norm)
            recruitment_signals = list(set(matches))
            score += min(0.2, len(recruitment_signals) * 0.05)
        
        # Bonus pour combinaison legal + recruitment
        if legal_keywords and recruitment_signals:
            score += 0.15
        
        return min(1.0, max(0.0, score)), legal_keywords, recruitment_signals
    
    def check_exclusions(
        self,
        text: str,
        author_analysis: AuthorAnalysis,
        post_date: Optional[datetime] = None
    ) -> Tuple[bool, str, List[str]]:
        """
        Vérifie si le post doit être exclu.
        
        Returns:
            Tuple (is_excluded, reason, terms_found)
        """
        text_norm = self._normalize_text(text)
        
        # Exclusion si auteur déjà exclu
        if author_analysis.is_excluded:
            return True, author_analysis.exclusion_reason, []
        
        # Stage/Alternance
        if self.config.exclude_stage_alternance:
            stage_pattern = self._compiled_patterns.get("stage_alternance")
            if stage_pattern:
                matches = stage_pattern.findall(text_norm)
                if matches:
                    return True, "stage_alternance", list(set(matches))
        
        # Agences (double vérification dans le texte)
        if self.config.exclude_agencies:
            agency_pattern = self._compiled_patterns.get("agency_patterns")
            if agency_pattern:
                matches = agency_pattern.findall(text_norm)
                if matches:
                    return True, "cabinet_recrutement_texte", list(set(matches))
        
        # Recrutement externe
        if self.config.exclude_external_recruitment:
            external_pattern = self._compiled_patterns.get("external_recruitment")
            if external_pattern:
                matches = external_pattern.findall(text_norm)
                if matches:
                    return True, "recrutement_externe", list(set(matches))
        
        # Contenu non-recrutement
        if self.config.exclude_non_recruitment:
            non_recruit_pattern = self._compiled_patterns.get("non_recruitment")
            if non_recruit_pattern:
                matches = non_recruit_pattern.findall(text_norm)
                if matches:
                    # Vérifier si des signaux de recrutement sont présents
                    recruit_pattern = self._compiled_patterns.get("recruitment_signals")
                    has_recruitment = recruit_pattern and recruit_pattern.search(text_norm)
                    if not has_recruitment:
                        return True, "contenu_non_recrutement", list(set(matches))
        
        # Âge du post
        if post_date and self.config.max_post_age_days > 0:
            now = datetime.now(timezone.utc)
            if post_date.tzinfo is None:
                post_date = post_date.replace(tzinfo=timezone.utc)
            age = now - post_date
            if age.days > self.config.max_post_age_days:
                return True, "post_trop_ancien", [f"{age.days} jours"]
        
        return False, "", []
    
    def analyze_post(
        self,
        text: str,
        author: str,
        author_profile: Optional[str] = None,
        author_description: Optional[str] = None,
        company_name: Optional[str] = None,
        post_date: Optional[datetime] = None
    ) -> PostAnalysisResult:
        """
        Analyse complète d'un post LinkedIn.
        
        C'est la méthode principale à utiliser.
        
        Args:
            text: Contenu du post
            author: Nom de l'auteur
            author_profile: URL du profil LinkedIn
            author_description: Description/bio de l'auteur
            company_name: Nom de l'entreprise (si connu)
            post_date: Date de publication du post
            
        Returns:
            PostAnalysisResult avec toutes les métriques
        """
        # 1. Analyser l'auteur
        author_analysis = self.analyze_author(author, author_profile, author_description)
        
        # 2. Vérifier les exclusions
        is_excluded, exclusion_reason, exclusion_terms = self.check_exclusions(
            text, author_analysis, post_date
        )
        
        if is_excluded:
            return PostAnalysisResult(
                author_type=author_analysis.author_type,
                author_confidence=author_analysis.confidence,
                is_internal_recruitment=False,
                is_external_recruitment=False,
                relevance=PostRelevance.EXCLUDED,
                relevance_score=0.0,
                is_excluded=True,
                exclusion_reason=exclusion_reason,
                exclusion_terms=exclusion_terms,
                company_name=company_name,
                post_age_days=None
            )
        
        # 3. Détecter le type de recrutement
        is_internal, is_external, recruit_signals = self.detect_recruitment_type(text)
        
        # 4. Calculer le score de pertinence
        score, legal_keywords, recruitment_signals = self.calculate_relevance_score(
            text, author_analysis, is_internal, is_external
        )
        
        # 5. Déterminer le niveau de pertinence
        if is_external:
            relevance = PostRelevance.EXCLUDED
            is_excluded = True
            exclusion_reason = "recrutement_externe"
        elif score >= 0.6 and legal_keywords and is_internal:
            relevance = PostRelevance.HIGH
        elif score >= 0.35 and legal_keywords:
            relevance = PostRelevance.MEDIUM
        elif score > 0.15:
            relevance = PostRelevance.LOW
        else:
            relevance = PostRelevance.EXCLUDED
            is_excluded = True
            exclusion_reason = "score_insuffisant"
        
        # 6. Calculer l'âge du post
        post_age_days = None
        if post_date:
            now = datetime.now(timezone.utc)
            if post_date.tzinfo is None:
                post_date = post_date.replace(tzinfo=timezone.utc)
            post_age_days = (now - post_date).days
        
        return PostAnalysisResult(
            author_type=author_analysis.author_type,
            author_confidence=author_analysis.confidence,
            is_internal_recruitment=is_internal,
            is_external_recruitment=is_external,
            relevance=relevance,
            relevance_score=score,
            legal_keywords_found=legal_keywords,
            recruitment_signals_found=recruitment_signals + recruit_signals,
            is_excluded=is_excluded,
            exclusion_reason=exclusion_reason,
            exclusion_terms=exclusion_terms,
            company_name=company_name,
            post_age_days=post_age_days
        )


# =============================================================================
# FONCTIONS UTILITAIRES
# =============================================================================

def is_relevant_for_titan(
    text: str,
    author: str,
    author_profile: Optional[str] = None,
    post_date: Optional[datetime] = None,
    config: Optional[JuridiqueConfig] = None
) -> bool:
    """
    Fonction rapide pour vérifier si un post est pertinent pour Titan Partners.
    
    Usage simplifié:
        if is_relevant_for_titan(text, author):
            # Traiter le post
    """
    analyzer = LinkedInPostAnalyzer(config)
    result = analyzer.analyze_post(
        text=text,
        author=author,
        author_profile=author_profile,
        post_date=post_date
    )
    return result.relevance in (PostRelevance.HIGH, PostRelevance.MEDIUM)


def get_post_summary(result: PostAnalysisResult) -> str:
    """
    Génère un résumé textuel de l'analyse d'un post.
    
    Utile pour les logs.
    """
    status = "✅ PERTINENT" if result.relevance in (PostRelevance.HIGH, PostRelevance.MEDIUM) else "❌ EXCLU"
    
    lines = [
        f"{status} - Score: {result.relevance_score:.2f}",
        f"  Type auteur: {result.author_type.name} (confiance: {result.author_confidence:.0%})",
        f"  Recrutement: {'Interne' if result.is_internal_recruitment else 'Externe' if result.is_external_recruitment else 'Non déterminé'}",
    ]
    
    if result.legal_keywords_found:
        lines.append(f"  Mots-clés juridiques: {', '.join(result.legal_keywords_found[:5])}")
    
    if result.is_excluded:
        lines.append(f"  Raison exclusion: {result.exclusion_reason}")
        if result.exclusion_terms:
            lines.append(f"  Termes détectés: {', '.join(result.exclusion_terms[:3])}")
    
    return "\n".join(lines)


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Classes principales
    "LinkedInPostAnalyzer",
    "PostAnalysisResult",
    "AuthorAnalysis",
    
    # Enums
    "AuthorType",
    "PostRelevance",
    
    # Fonctions utilitaires
    "is_relevant_for_titan",
    "get_post_summary",
]
