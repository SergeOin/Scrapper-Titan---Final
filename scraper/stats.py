"""
Module de statistiques et logging pour le scraper Titan Partners.

Ce module fournit:
- Statistiques détaillées sur les posts traités
- Logs structurés des raisons d'exclusion
- Métriques de performance et de pertinence
- Rapports de fin de session

USAGE:
    from scraper.stats import ScraperStats, log_filtering_decision
    
    stats = ScraperStats()
    stats.record_post_found("keyword1")
    stats.record_post_filtered("keyword1", "stage_alternance", ["stage"])
    stats.record_post_accepted("keyword1", 0.85, ["juriste", "cdi"])
    
    # En fin de session
    report = stats.generate_report()
    print(report)
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from pathlib import Path

logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTES
# =============================================================================

# Catégories de raisons d'exclusion (pour regroupement dans les stats)
EXCLUSION_CATEGORIES = {
    # Stage/Alternance
    "stage_alternance": "Stage/Alternance",
    "stage": "Stage/Alternance",
    "alternance": "Stage/Alternance",
    "apprentissage": "Stage/Alternance",
    "vie": "Stage/Alternance",
    
    # Agences de recrutement
    "cabinet_recrutement": "Agence de recrutement",
    "cabinet_recrutement_texte": "Agence de recrutement",
    "recruitment_agency": "Agence de recrutement",
    
    # Recrutement externe
    "recrutement_externe": "Recrutement externe",
    "external_recruitment": "Recrutement externe",
    
    # Freelance
    "freelance": "Freelance/Indépendant",
    "freelance_independant": "Freelance/Indépendant",
    "freelance_mission": "Freelance/Indépendant",
    
    # Localisation
    "hors_france": "Hors France",
    "non_france": "Hors France",
    
    # Score insuffisant
    "score_insuffisant": "Score insuffisant",
    "score_insuffisant_recrutement": "Score insuffisant",
    "score_insuffisant_juridique": "Score insuffisant",
    "score_insuffisant_recrutement_et_juridique": "Score insuffisant",
    
    # Contenu non pertinent
    "contenu_non_recrutement": "Contenu non-recrutement",
    "contenu_promotionnel": "Contenu non-recrutement",
    "post_emotionnel": "Contenu non-recrutement",
    "contenu_sponsorise": "Contenu non-recrutement",
    
    # Technique
    "post_trop_ancien": "Post trop ancien",
    "texte_vide": "Texte vide",
    "chercheur_emploi": "Chercheur d'emploi",
    "metier_non_juridique": "Métier non juridique",
}


# =============================================================================
# DATACLASSES
# =============================================================================

@dataclass
class FilteringDecision:
    """Enregistrement d'une décision de filtrage."""
    timestamp: str
    keyword: str
    author: str
    text_preview: str  # 100 premiers caractères
    accepted: bool
    reason: str
    terms_found: List[str]
    score: Optional[float]
    legal_keywords: List[str]
    recruitment_signals: List[str]


@dataclass
class KeywordStats:
    """Statistiques pour un mot-clé de recherche."""
    found: int = 0
    accepted: int = 0
    filtered: int = 0
    exclusion_reasons: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    avg_score: float = 0.0
    scores: List[float] = field(default_factory=list)


@dataclass 
class SessionReport:
    """Rapport de session de scraping."""
    start_time: str
    end_time: str
    duration_seconds: float
    
    # Compteurs globaux
    total_posts_found: int
    total_posts_accepted: int
    total_posts_filtered: int
    acceptance_rate: float
    
    # Par raison d'exclusion
    exclusions_by_category: Dict[str, int]
    exclusions_detailed: Dict[str, int]
    
    # Par mot-clé
    stats_by_keyword: Dict[str, Dict[str, Any]]
    
    # Top termes
    top_legal_keywords: List[tuple]
    top_exclusion_terms: List[tuple]
    
    # Performance
    posts_per_hour: float
    avg_relevance_score: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Conversion en dictionnaire."""
        return {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_seconds": self.duration_seconds,
            "total_posts_found": self.total_posts_found,
            "total_posts_accepted": self.total_posts_accepted,
            "total_posts_filtered": self.total_posts_filtered,
            "acceptance_rate": self.acceptance_rate,
            "exclusions_by_category": self.exclusions_by_category,
            "exclusions_detailed": self.exclusions_detailed,
            "stats_by_keyword": self.stats_by_keyword,
            "top_legal_keywords": self.top_legal_keywords,
            "top_exclusion_terms": self.top_exclusion_terms,
            "posts_per_hour": self.posts_per_hour,
            "avg_relevance_score": self.avg_relevance_score,
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Export JSON."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


# =============================================================================
# CLASSE PRINCIPALE DE STATISTIQUES
# =============================================================================

class ScraperStats:
    """
    Collecteur de statistiques pour le scraper Titan Partners.
    
    Enregistre toutes les décisions de filtrage et génère des rapports.
    
    Usage:
        stats = ScraperStats()
        
        # Pour chaque post trouvé
        stats.record_post_found("recrute juriste")
        
        # Si le post est filtré
        stats.record_post_filtered("recrute juriste", "stage_alternance", ["stage"])
        
        # Si le post est accepté
        stats.record_post_accepted("recrute juriste", 0.75, ["juriste"], ["recrute"])
        
        # En fin de session
        report = stats.generate_report()
    """
    
    def __init__(self, session_name: Optional[str] = None):
        """
        Initialise le collecteur de stats.
        
        Args:
            session_name: Nom optionnel de la session pour les logs
        """
        self.session_name = session_name or f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.start_time = datetime.now(timezone.utc)
        
        # Compteurs globaux
        self.total_found = 0
        self.total_accepted = 0
        self.total_filtered = 0
        
        # Stats par mot-clé
        self.keyword_stats: Dict[str, KeywordStats] = defaultdict(KeywordStats)
        
        # Historique des décisions
        self.decisions: List[FilteringDecision] = []
        
        # Compteurs d'exclusion
        self.exclusion_counts: Dict[str, int] = defaultdict(int)
        self.exclusion_terms: Dict[str, int] = defaultdict(int)
        
        # Mots-clés juridiques détectés
        self.legal_keywords_found: Dict[str, int] = defaultdict(int)
        
        # Scores
        self.all_scores: List[float] = []
        
        logger.info(f"📊 Session de stats initialisée: {self.session_name}")
    
    def record_post_found(self, keyword: str) -> None:
        """Enregistre un post trouvé (avant filtrage)."""
        self.total_found += 1
        self.keyword_stats[keyword].found += 1
    
    def record_post_filtered(
        self,
        keyword: str,
        reason: str,
        terms_found: List[str],
        author: str = "Unknown",
        text_preview: str = ""
    ) -> None:
        """
        Enregistre un post filtré (exclu).
        
        Args:
            keyword: Mot-clé de recherche utilisé
            reason: Raison d'exclusion
            terms_found: Termes ayant déclenché l'exclusion
            author: Auteur du post
            text_preview: Aperçu du texte
        """
        self.total_filtered += 1
        self.keyword_stats[keyword].filtered += 1
        self.keyword_stats[keyword].exclusion_reasons[reason] += 1
        
        # Comptabiliser la raison
        self.exclusion_counts[reason] += 1
        
        # Comptabiliser les termes d'exclusion
        for term in terms_found:
            self.exclusion_terms[term] += 1
        
        # Enregistrer la décision
        decision = FilteringDecision(
            timestamp=datetime.now(timezone.utc).isoformat(),
            keyword=keyword,
            author=author,
            text_preview=text_preview[:100] if text_preview else "",
            accepted=False,
            reason=reason,
            terms_found=terms_found,
            score=None,
            legal_keywords=[],
            recruitment_signals=[]
        )
        self.decisions.append(decision)
        
        # Log
        category = EXCLUSION_CATEGORIES.get(reason, reason)
        logger.debug(
            f"❌ POST FILTRÉ [{category}] - Keyword: {keyword}, "
            f"Raison: {reason}, Termes: {terms_found[:3]}"
        )
    
    def record_post_accepted(
        self,
        keyword: str,
        score: float,
        legal_keywords: List[str],
        recruitment_signals: List[str] = None,
        author: str = "Unknown",
        text_preview: str = ""
    ) -> None:
        """
        Enregistre un post accepté (pertinent).
        
        Args:
            keyword: Mot-clé de recherche utilisé
            score: Score de pertinence (0-1)
            legal_keywords: Mots-clés juridiques détectés
            recruitment_signals: Signaux de recrutement détectés
            author: Auteur du post
            text_preview: Aperçu du texte
        """
        self.total_accepted += 1
        self.keyword_stats[keyword].accepted += 1
        self.keyword_stats[keyword].scores.append(score)
        
        # Score global
        self.all_scores.append(score)
        
        # Comptabiliser les mots-clés juridiques
        for kw in legal_keywords:
            self.legal_keywords_found[kw] += 1
        
        # Enregistrer la décision
        decision = FilteringDecision(
            timestamp=datetime.now(timezone.utc).isoformat(),
            keyword=keyword,
            author=author,
            text_preview=text_preview[:100] if text_preview else "",
            accepted=True,
            reason="",
            terms_found=[],
            score=score,
            legal_keywords=legal_keywords,
            recruitment_signals=recruitment_signals or []
        )
        self.decisions.append(decision)
        
        # Log
        logger.info(
            f"✅ POST ACCEPTÉ - Keyword: {keyword}, Score: {score:.2f}, "
            f"Legal: {legal_keywords[:3]}, Auteur: {author[:30]}"
        )
    
    def get_acceptance_rate(self) -> float:
        """Retourne le taux d'acceptation global."""
        if self.total_found == 0:
            return 0.0
        return self.total_accepted / self.total_found
    
    def get_avg_score(self) -> float:
        """Retourne le score moyen des posts acceptés."""
        if not self.all_scores:
            return 0.0
        return sum(self.all_scores) / len(self.all_scores)
    
    def get_exclusions_by_category(self) -> Dict[str, int]:
        """Agrège les exclusions par catégorie."""
        by_category: Dict[str, int] = defaultdict(int)
        for reason, count in self.exclusion_counts.items():
            category = EXCLUSION_CATEGORIES.get(reason, "Autre")
            by_category[category] += count
        return dict(sorted(by_category.items(), key=lambda x: -x[1]))
    
    def generate_report(self) -> SessionReport:
        """
        Génère un rapport complet de la session.
        
        Returns:
            SessionReport avec toutes les statistiques
        """
        end_time = datetime.now(timezone.utc)
        duration = (end_time - self.start_time).total_seconds()
        
        # Stats par mot-clé
        stats_by_kw = {}
        for kw, stats in self.keyword_stats.items():
            if stats.scores:
                avg = sum(stats.scores) / len(stats.scores)
            else:
                avg = 0.0
            stats_by_kw[kw] = {
                "found": stats.found,
                "accepted": stats.accepted,
                "filtered": stats.filtered,
                "avg_score": round(avg, 3),
                "top_exclusions": dict(sorted(
                    stats.exclusion_reasons.items(),
                    key=lambda x: -x[1]
                )[:5])
            }
        
        # Top mots-clés juridiques
        top_legal = sorted(
            self.legal_keywords_found.items(),
            key=lambda x: -x[1]
        )[:10]
        
        # Top termes d'exclusion
        top_exclusion_terms = sorted(
            self.exclusion_terms.items(),
            key=lambda x: -x[1]
        )[:10]
        
        # Posts par heure
        hours = duration / 3600 if duration > 0 else 1
        posts_per_hour = self.total_accepted / hours if hours > 0 else 0
        
        return SessionReport(
            start_time=self.start_time.isoformat(),
            end_time=end_time.isoformat(),
            duration_seconds=round(duration, 1),
            total_posts_found=self.total_found,
            total_posts_accepted=self.total_accepted,
            total_posts_filtered=self.total_filtered,
            acceptance_rate=round(self.get_acceptance_rate(), 3),
            exclusions_by_category=self.get_exclusions_by_category(),
            exclusions_detailed=dict(sorted(
                self.exclusion_counts.items(),
                key=lambda x: -x[1]
            )),
            stats_by_keyword=stats_by_kw,
            top_legal_keywords=top_legal,
            top_exclusion_terms=top_exclusion_terms,
            posts_per_hour=round(posts_per_hour, 1),
            avg_relevance_score=round(self.get_avg_score(), 3)
        )
    
    def print_summary(self) -> None:
        """Affiche un résumé dans les logs."""
        rate = self.get_acceptance_rate()
        avg_score = self.get_avg_score()
        
        logger.info("=" * 60)
        logger.info("📊 RÉSUMÉ DE SESSION TITAN PARTNERS")
        logger.info("=" * 60)
        logger.info(f"  Posts trouvés:    {self.total_found}")
        logger.info(f"  Posts acceptés:   {self.total_accepted}")
        logger.info(f"  Posts filtrés:    {self.total_filtered}")
        logger.info(f"  Taux acceptation: {rate:.1%}")
        logger.info(f"  Score moyen:      {avg_score:.2f}")
        logger.info("-" * 60)
        
        # Top exclusions
        exclusions = self.get_exclusions_by_category()
        if exclusions:
            logger.info("Top raisons d'exclusion:")
            for reason, count in list(exclusions.items())[:5]:
                logger.info(f"    {reason}: {count}")
        
        # Top mots-clés juridiques
        if self.legal_keywords_found:
            logger.info("Top mots-clés juridiques détectés:")
            for kw, count in sorted(
                self.legal_keywords_found.items(),
                key=lambda x: -x[1]
            )[:5]:
                logger.info(f"    {kw}: {count}")
        
        logger.info("=" * 60)
    
    def save_report(self, output_dir: str = "exports") -> str:
        """
        Sauvegarde le rapport en JSON.
        
        Args:
            output_dir: Répertoire de sortie
            
        Returns:
            Chemin du fichier créé
        """
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        report = self.generate_report()
        filename = f"scraper_report_{self.session_name}.json"
        filepath = Path(output_dir) / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(report.to_json())
        
        logger.info(f"📄 Rapport sauvegardé: {filepath}")
        return str(filepath)
    
    def save_decisions_log(self, output_dir: str = "exports") -> str:
        """
        Sauvegarde l'historique détaillé des décisions.
        
        Args:
            output_dir: Répertoire de sortie
            
        Returns:
            Chemin du fichier créé
        """
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        filename = f"filtering_decisions_{self.session_name}.jsonl"
        filepath = Path(output_dir) / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            for decision in self.decisions:
                line = json.dumps({
                    "timestamp": decision.timestamp,
                    "keyword": decision.keyword,
                    "author": decision.author,
                    "text_preview": decision.text_preview,
                    "accepted": decision.accepted,
                    "reason": decision.reason,
                    "terms_found": decision.terms_found,
                    "score": decision.score,
                    "legal_keywords": decision.legal_keywords,
                    "recruitment_signals": decision.recruitment_signals,
                }, ensure_ascii=False)
                f.write(line + "\n")
        
        logger.info(f"📄 Historique des décisions sauvegardé: {filepath}")
        return str(filepath)


# =============================================================================
# FONCTIONS UTILITAIRES DE LOGGING
# =============================================================================

def log_filtering_decision(
    keyword: str,
    author: str,
    accepted: bool,
    reason: str = "",
    score: Optional[float] = None,
    legal_keywords: List[str] = None,
    terms_found: List[str] = None
) -> None:
    """
    Log une décision de filtrage de manière structurée.
    
    À utiliser directement dans le worker si on ne veut pas
    instancier ScraperStats.
    """
    if accepted:
        logger.info(
            f"✅ ACCEPTÉ | Keyword: {keyword} | Auteur: {author[:30]} | "
            f"Score: {score:.2f if score else 'N/A'} | Legal: {legal_keywords or []}"
        )
    else:
        category = EXCLUSION_CATEGORIES.get(reason, reason)
        logger.info(
            f"❌ FILTRÉ | Keyword: {keyword} | Auteur: {author[:30]} | "
            f"Raison: {category} | Termes: {terms_found or []}"
        )


def format_stats_for_prometheus(stats: ScraperStats) -> Dict[str, float]:
    """
    Formate les stats pour export Prometheus.
    
    Returns:
        Dict avec les métriques au format Prometheus
    """
    return {
        "scraper_posts_found_total": float(stats.total_found),
        "scraper_posts_accepted_total": float(stats.total_accepted),
        "scraper_posts_filtered_total": float(stats.total_filtered),
        "scraper_acceptance_rate": stats.get_acceptance_rate(),
        "scraper_avg_relevance_score": stats.get_avg_score(),
    }


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Classes
    "ScraperStats",
    "SessionReport",
    "FilteringDecision",
    "KeywordStats",
    
    # Fonctions
    "log_filtering_decision",
    "format_stats_for_prometheus",
    
    # Constantes
    "EXCLUSION_CATEGORIES",
]
