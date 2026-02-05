"""Scraping subprocess module.

This module runs Playwright scraping in a separate process to avoid
event loop conflicts with uvicorn/asyncio/pywebview in the main process.

Usage:
    Called via subprocess from worker.py when scraping needs to be isolated.
    Communicates via JSON over stdin/stdout.
    
Migration Note:
    This module can use the new adapters for filtering via FeatureFlags.
    Set use_unified_filter=True to use UnifiedFilter instead of EXCLUSION lists.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Ensure project root is in path for imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# =============================================================================
# ADAPTERS - Progressive migration to new modular architecture
# =============================================================================
try:
    from scraper.adapters import (
        get_feature_flags,
        should_keep_post,
        is_duplicate_post,
        mark_post_seen,
    )
    _ADAPTERS_AVAILABLE = True
except ImportError:
    _ADAPTERS_AVAILABLE = False
    
    def get_feature_flags():
        """Stub when adapters not available."""
        class _StubFlags:
            use_unified_filter = False
            use_ml_interface = False
            use_post_cache = False
        return _StubFlags()
    
    def should_keep_post(text, author="", company="", legacy_exclusions=None):
        return True, "no_filter", 0.5
    
    def is_duplicate_post(text="", url="", post_id="", author=""):
        return False
    
    def mark_post_seen(text="", url="", post_id="", author=""):
        pass

# =============================================================================
# PRE-QUALIFICATION - v2 "Qualify Early, Extract Late" strategy
# =============================================================================
try:
    from scraper.pre_qualifier import (
        pre_qualify_post,
        is_excluded_author,
        PreQualificationResult,
        PreQualificationMetrics,
    )
    _PRE_QUALIFIER_AVAILABLE = True
    _PRE_QUAL_METRICS = PreQualificationMetrics()  # Global metrics instance
except ImportError:
    _PRE_QUALIFIER_AVAILABLE = False
    _PRE_QUAL_METRICS = None
    
    def pre_qualify_post(preview_text="", author_name="", company_name=None, known_companies=None):
        """Stub: accept all posts when pre_qualifier not available."""
        class _StubResult:
            should_extract = True
            reason = None
            rejection_reason = None
            confidence = 1.0
        return _StubResult()
    
    def is_excluded_author(author_name=""):
        return (False, "")

# Global debug logging function
_DEBUG_LOG_PATH = None
_DEBUG_LOG_MAX_SIZE = 1024 * 1024  # 1MB max size

def _init_debug_log():
    global _DEBUG_LOG_PATH
    localappdata = os.environ.get("LOCALAPPDATA", "")
    if localappdata:
        _DEBUG_LOG_PATH = Path(localappdata) / "TitanScraper" / "scrape_subprocess_debug.txt"
    else:
        _DEBUG_LOG_PATH = Path(".") / "scrape_subprocess_debug.txt"
    _DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

def _rotate_log_if_needed():
    """Rotate log file if it exceeds max size."""
    global _DEBUG_LOG_PATH
    if _DEBUG_LOG_PATH is None:
        return
    try:
        if _DEBUG_LOG_PATH.exists() and _DEBUG_LOG_PATH.stat().st_size > _DEBUG_LOG_MAX_SIZE:
            # Keep last half of the file
            content = _DEBUG_LOG_PATH.read_text(encoding='utf-8', errors='ignore')
            lines = content.splitlines()
            half = len(lines) // 2
            _DEBUG_LOG_PATH.write_text('\n'.join(lines[half:]) + '\n', encoding='utf-8')
    except Exception:
        pass

def _debug_log(msg: str):
    """Log message to debug file with rotation."""
    global _DEBUG_LOG_PATH
    if _DEBUG_LOG_PATH is None:
        _init_debug_log()
    try:
        _rotate_log_if_needed()
        with open(_DEBUG_LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(f"{msg}\n")
    except Exception:
        pass

# Initialize on import
_init_debug_log()


# =============================================================================
# PHASE 2: IMPORTS CONDITIONNELS - Modules anti-détection (désactivés par défaut)
# =============================================================================
# Ces modules sont chargés mais NE SONT PAS UTILISÉS tant que les flags sont à 0.
# Comportement actuel = strictement identique si flags désactivés.

# FLAGS DE CONTRÔLE (désactivés par défaut - aucun impact sur le comportement existant)
_USE_ENHANCED_TIMING = os.environ.get("TITAN_ENHANCED_TIMING", "0").lower() in ("1", "true", "yes")
_USE_ENHANCED_STEALTH = os.environ.get("TITAN_ENHANCED_STEALTH", "0").lower() in ("1", "true", "yes")

# Import conditionnel du module timing (délais ultra-safe)
_TIMING_MODULE_AVAILABLE = False
try:
    from .timing import (
        is_ultra_safe_mode,
        get_delay_multiplier,
        random_delay as timing_random_delay,
        human_delay as timing_human_delay,
        should_take_long_pause as timing_should_take_long_pause,
        get_long_pause_duration as timing_get_long_pause_duration,
    )
    _TIMING_MODULE_AVAILABLE = True
    _debug_log(f"[PHASE2] timing module loaded, ULTRA_SAFE={is_ultra_safe_mode()}, enabled={_USE_ENHANCED_TIMING}")
except ImportError as e:
    _debug_log(f"[PHASE2] timing module not available: {e}")

# Import conditionnel du module stealth (anti-fingerprinting avancé)
_STEALTH_MODULE_AVAILABLE = False
try:
    from .stealth import (
        apply_stealth_scripts as stealth_apply_scripts,
        apply_advanced_stealth as stealth_apply_advanced,
        get_stealth_context_options as stealth_get_context_options,
        detect_restriction_page as stealth_detect_restriction,
    )
    _STEALTH_MODULE_AVAILABLE = True
    _debug_log(f"[PHASE2] stealth module loaded, enabled={_USE_ENHANCED_STEALTH}")
except ImportError as e:
    _debug_log(f"[PHASE2] stealth module not available: {e}")

# Log status at import time
_debug_log(f"[PHASE2] Module status: timing={_TIMING_MODULE_AVAILABLE}, stealth={_STEALTH_MODULE_AVAILABLE}")
_debug_log(f"[PHASE2] Flags status: enhanced_timing={_USE_ENHANCED_TIMING}, enhanced_stealth={_USE_ENHANCED_STEALTH}")


@dataclass
class ScrapedPost:
    """Lightweight post data returned from subprocess."""
    id: str
    keyword: str
    author: str
    author_profile: Optional[str]
    text: str
    language: str
    published_at: Optional[str]
    collected_at: str
    company: Optional[str] = None
    permalink: Optional[str] = None
    raw: dict[str, Any] | None = None


# =============================================================================
# TITAN PARTNERS FILTERING - UNIFIED SOURCE OF TRUTH
# =============================================================================
# NOTE: Les listes ci-dessous sont DÉPRÉCIÉES.
# La source de vérité unique est maintenant filters/unified.py
# Ces listes locales sont conservées temporairement pour compatibilité
# mais seront supprimées dans une version future.
# 
# TODO: Migrer tout le code vers:
#   from filters.unified import (
#       AGENCY_PATTERNS, EXTERNAL_RECRUITMENT_PATTERNS, 
#       STAGE_ALTERNANCE_PATTERNS, FREELANCE_PATTERNS,
#       NON_RECRUITMENT_PATTERNS, classify_post, is_relevant_post
#   )
# =============================================================================

# Import depuis unified.py pour les nouvelles utilisations
try:
    from filters.unified import (
        AGENCY_PATTERNS as UNIFIED_AGENCY_PATTERNS,
        EXTERNAL_RECRUITMENT_PATTERNS as UNIFIED_EXTERNAL_PATTERNS,
        STAGE_ALTERNANCE_PATTERNS as UNIFIED_STAGE_PATTERNS,
        FREELANCE_PATTERNS as UNIFIED_FREELANCE_PATTERNS,
        NON_RECRUITMENT_PATTERNS as UNIFIED_NON_RECRUITMENT_PATTERNS,
        LEGAL_ROLES as UNIFIED_LEGAL_ROLES,
        classify_post as unified_classify_post,
    )
    _UNIFIED_AVAILABLE = True
except ImportError:
    _UNIFIED_AVAILABLE = False

# =============================================================================
# LEGACY LISTS (DEPRECATED - kept for backward compatibility)
# =============================================================================

# Agences de recrutement / Job boards à EXCLURE
EXCLUSION_AGENCIES = [
    "profiler", "jobs.red", "jobs red", "jobfinder", "tsylana", "lapins.ai",
    "village de la justice", "emploi & carriere", "droit-inc", "afje jobs",
    "cabinet de recrutement", "staffing", "headhunt", "talent acquisition",
    "chasseur de tete", "chasseur de têtes", "recruteur", "rh", "ressources humaines",
    "interim", "intérim", "manpower", "adecco", "randstad", "michael page", 
    "hays", "robert half", "expectra", "spring", "keljob", "indeed",
    "linkedin talent", "monster", "cadremploi", "apec", "meteojob",
    "page personnel", "fed legal", "laurence simons", "major", "lincoln",
]

# Signaux de recrutement EXTERNE (pour un client) - à EXCLURE
EXCLUSION_EXTERNAL_RECRUITMENT = [
    "pour notre client", "pour l'un de nos clients", "pour un de nos clients",
    "notre client recrute", "notre client recherche", "for our client",
    "un de nos clients", "l'un de nos partenaires", "pour le compte de",
    "mandaté par", "mandatés par", "nous recherchons pour",
    # Recrute POUR des clients/cabinets (pas pour soi-même)
    "je recrute pour", "recrute pour des cabinets", "recrute pour mes clients",
    "pour mes clients", "pour nos clients", "pour des cabinets",
    "pour un cabinet", "pour une étude", "pour un de mes clients",
    "clients monégasques", "clients luxembourgeois", "clients suisses",
    "breja partners", "recrutement pour le compte",
    # English variants
    "our client is seeking", "our client is looking", "my client is looking",
    "our client needs", "my client needs", "on behalf of our client",
    "client is hiring", "clients are hiring", "for my clients",
    "i'm recruiting for", "recruiting for my client", "recruiting on behalf",
    # Recrutement pour un tiers
    "le fils de", "la fille de", "un ami", "une amie", "un proche",
    "une connaissance", "recherche un poste", "recherche du travail",
]

# EXCLUSION: Postes hors France - Titan Partners se concentre sur la France uniquement
EXCLUSION_LOCATIONS = [
    # Monaco
    "monaco", "monégasque", "principauté de monaco", "monte-carlo", "monte carlo",
    # Maroc
    "maroc", "morocco", "casablanca", "rabat", "marrakech", "tanger", "fès",
    "barreau de casablanca", "barreau de rabat", "marocain", "marocaine",
    # Canada (y compris emails .ca et cabinets canadiens)
    "canada", "québec", "quebec", "montréal", "montreal", "toronto", "vancouver",
    "ottawa", "canadian", "canadien", "canadienne", "barreau du québec",
    ".ca ", "@.ca", ".ca/", "miller.ca", "christinamiller.ca",  # Canadian email domains
    # Cabinets d'avocats canadiens connus
    "lavery", "stikeman", "osler", "blakes", "mccarthy", "fasken", "dentons canada",
    "norton rose canada", "gowling", "torys", "davies ward", "borden ladner",
    # Belgique
    "belgique", "belgium", "bruxelles", "brussels", "liège", "anvers",
    "barreau de bruxelles", "belge",
    # Suisse
    "suisse", "switzerland", "genève", "geneva", "lausanne", "zurich", "zürich",
    "berne", "bern", "barreau de genève", "suisse romande",
    # Luxembourg
    "luxembourg", "luxembourgeois",
    # Autres pays
    "dubai", "dubaï", "émirats", "emirats", "abu dhabi",
    "royaume-uni", "united kingdom", "uk", "london", "londres",
    "allemagne", "germany", "berlin", "frankfurt", "francfort", "munich",
    "espagne", "spain", "madrid", "barcelona", "barcelone",
    "italie", "italy", "rome", "milan", "milano",
    "états-unis", "etats-unis", "usa", "new york", "washington",
    # Afrique
    "algérie", "algerie", "tunisia", "tunisie", "sénégal", "senegal",
    "côte d'ivoire", "cote d'ivoire", "cameroun",
]

# EXCLUSION: Secteurs non-juridiques - Titan Partners ne cherche que des postes juridiques
EXCLUSION_NON_LEGAL_SECTORS = [
    # Immobilier (courtiers, agents)
    "courtier immobilier", "courtier", "courtière", "real estate broker", "real estate agent",
    "agent immobilier", "real estate", "listings", "acheteurs et vendeurs",
    "buyers and sellers", "property", "propriété",
    # Banque / Finance (non juridique)
    "trader", "trading", "asset management",
    # IT / Tech (sauf si juridique)
    "développeur", "developer", "software engineer", "data scientist",
    # Ventes
    "commercial", "sales representative", "account manager",
]

# Signaux d'auteur cherchant un emploi (pas un recruteur)
EXCLUSION_JOBSEEKER = [
    "opentowork", "open to work", "#opentowork",
    "je recherche un poste", "je recherche un emploi", "je cherche un poste",
    "je recherche un nouveau poste", "vous serais reconnaissant",
    "je suis à la recherche", "je suis en recherche", "recherche active",
    "disponible immédiatement", "à l'écoute du marché", "ouvert aux opportunités",
    "bonjour à tous ! je recherche", "bonjour à tous! je recherche",
    "je suis actuellement en recherche", "en quête d'un nouveau défi",
    # Annonces de nouveau poste personnel (pas une offre d'emploi)
    "je suis ravie d'annoncer", "je suis ravi d'annoncer", 
    "d'annoncer le début d'un nouveau poste", "nouveau poste en tant que",
    "annonce mon nouveau poste", "happy to announce", "excited to share",
    "i'm thrilled to share", "début d'un nouveau poste", "début de mon nouveau poste",
    "a rejoint", "just started", "heureux d'annoncer", "heureuse d'annoncer",
    "nouveau chapitre", "new chapter", "j'ai le plaisir d'annoncer",
    # Présentations d'étudiants cherchant un stage
    "présentation individuelle", "portrait individuel", "presentation individuelle",
    "actuellement en deuxième année", "actuellement en première année",
    "à la recherche d'un stage", "recherche un stage", "cherche un stage",
    "stage de fin d'étude", "stage de fin d'études", "looking for an internship",
]

# EXCLUSION: Types de contrats non désirés (stage, alternance, apprentissage, intérim)
# Titan Partners recherche uniquement des CDI/CDD
EXCLUSION_CONTRACT_TYPES = [
    # Stage
    "stage", "stagiaire", "intern", "internship",
    # Alternance / Apprentissage  
    "alternance", "alternant", "apprentissage", "apprenti", "contrat d'apprentissage",
    "contrat de professionnalisation", "work-study", "apprenticeship",
    # Intérim (sauf si explicitement CDI après)
    "intérim", "interim", "mission temporaire",
    # Élève-avocat (pas encore avocat)
    "élève-avocat", "eleve-avocat", "élève avocat", "eleve avocat",
]

# Contenu non-recrutement à exclure
EXCLUSION_NON_RECRUITMENT = [
    "retour sur notre", "retour sur la", "retour sur l'", 
    "journée événement", "journee evenement",
    "conférence", "conference", "séminaire", "seminaire",
    "formation", "webinaire", "webinar",
    "article", "publication", "tribune",
    "félicitations", "felicitations", "bravo",
    "bienvenue à", "bienvenue a", "welcome",
    "a rejoint", "vient de rejoindre", "nous accueillons",
]

# Signaux de recrutement INTERNE (entreprise qui recrute = BON)
RECRUITMENT_INTERNAL_SIGNALS = [
    "nous recrutons", "on recrute", "nous recherchons", "on recherche",
    "notre équipe recrute", "notre cabinet recrute", "we are hiring", 
    "we're hiring", "is hiring", "rejoint notre équipe", "poste à pourvoir",
    "opportunité", "cdi", "rejoignez-nous", "recrute un", "recrute une",
    "recrute!", "recrute !", "recrute!!",  # For "Goodwin recrute!"
    "je recrute", "cherche son", "cherche sa", "looking for",
    "we're looking for", "we are looking for", "seeking a",
]

# Mots-clés juridiques (requis pour pertinence)
LEGAL_KEYWORDS = [
    "juriste", "legal counsel", "avocat", "compliance", "contract manager",
    "privacy", "dpo", "juridique", "legal", "notaire", "paralegal",
    "directeur juridique", "responsable juridique", "head of legal",
]

# Durée maximale des posts (en jours)
MAX_POST_AGE_DAYS = 21  # 3 semaines

# ============================================================
# RATE LIMITING - MODE CONSERVATEUR pour éviter le blocage LinkedIn
# ============================================================
# VALEURS SÉCURISÉES: Délais longs et randomisés pour simuler
# un comportement humain très naturel. Priorité = éviter la détection.
import random
import math

# Délai après chargement de page (ms) - LONG pour paraître humain
PAGE_LOAD_DELAY_MIN = 5000   # 5 secondes minimum
PAGE_LOAD_DELAY_MAX = 12000  # 12 secondes maximum

# Délai entre chaque scroll (ms) - LONG et variable
SCROLL_DELAY_MIN = 3000    # 3 secondes minimum
SCROLL_DELAY_MAX = 7000    # 7 secondes maximum

# Délai entre chaque mot-clé recherché (ms) - TRÈS LONG pour sécurité
KEYWORD_DELAY_MIN = 30000   # 30 secondes minimum
KEYWORD_DELAY_MAX = 60000   # 60 secondes maximum

# Nombre de scrolls par page - RÉDUIT (v2: de 2 à 1 pour réduire les actions)
# Avec la stratégie whitelist, on visite des pages ciblées donc 1 scroll suffit
MAX_SCROLLS_PER_PAGE = 1

# Délai de "lecture" simulée d'un post (ms) - LONG
POST_READ_DELAY_MIN = 2000   # 2 secondes
POST_READ_DELAY_MAX = 5000   # 5 secondes

# Pause longue occasionnelle pour simuler une distraction (ms)
LONG_PAUSE_MIN = 30000       # 30 secondes
LONG_PAUSE_MAX = 90000       # 90 secondes
LONG_PAUSE_PROBABILITY = 0.15  # 15% de chance par keyword (augmenté)

# Pause très courte pour micro-hésitations (ms)
MICRO_PAUSE_MIN = 300
MICRO_PAUSE_MAX = 1000

def random_delay(min_ms: int, max_ms: int) -> int:
    """Retourne un délai aléatoire avec distribution gaussienne centrée.
    
    Utilise une distribution normale tronquée pour des délais plus naturels
    (les humains ont tendance à se grouper autour d'une moyenne).
    """
    # Distribution gaussienne centrée sur la moyenne
    mean = (min_ms + max_ms) / 2
    std_dev = (max_ms - min_ms) / 4  # 95% des valeurs dans l'intervalle
    
    value = random.gauss(mean, std_dev)
    # Tronquer aux limites + ajouter un peu de bruit
    noise = random.randint(-200, 200)
    return max(min_ms, min(max_ms, int(value + noise)))

def human_delay(base_ms: int, variance_percent: float = 0.4) -> int:
    """Génère un délai humain avec variance naturelle.
    
    Args:
        base_ms: Délai de base en millisecondes
        variance_percent: Pourcentage de variance (0.4 = ±40%)
    """
    variance = base_ms * variance_percent
    return int(base_ms + random.uniform(-variance, variance))

def should_take_long_pause() -> bool:
    """Détermine si on doit prendre une longue pause (simulation de distraction)."""
    return random.random() < LONG_PAUSE_PROBABILITY

def get_long_pause_duration() -> int:
    """Retourne une durée de pause longue aléatoire."""
    return random_delay(LONG_PAUSE_MIN, LONG_PAUSE_MAX)


# =============================================================================
# PHASE 3: WRAPPERS CONDITIONNELS - Délais ultra-safe (timing.py)
# =============================================================================
# Ces wrappers délèguent au module timing.py SI le flag TITAN_ENHANCED_TIMING=1,
# sinon ils utilisent les fonctions locales existantes (comportement inchangé).
# Cela garantit une rétrocompatibilité totale quand le flag est désactivé.

def _get_random_delay(min_ms: int, max_ms: int) -> int:
    """Wrapper: utilise timing.py si TITAN_ENHANCED_TIMING=1, sinon local.
    
    Quand activé, timing.py applique:
    - Distribution gaussienne améliorée
    - Multiplicateur ULTRA_SAFE (x3 sur tous les délais)
    - Micro-variations naturelles
    """
    if _USE_ENHANCED_TIMING and _TIMING_MODULE_AVAILABLE:
        result = timing_random_delay(min_ms, max_ms)
        _debug_log(f"[PHASE3] _get_random_delay({min_ms}, {max_ms}) -> {result} (enhanced)")
        return result
    return random_delay(min_ms, max_ms)

def _get_human_delay(base_ms: int, variance_percent: float = 0.4) -> int:
    """Wrapper: utilise timing.py si TITAN_ENHANCED_TIMING=1, sinon local.
    
    Quand activé, timing.py applique:
    - Variance naturelle améliorée
    - Multiplicateur ULTRA_SAFE (x3)
    """
    if _USE_ENHANCED_TIMING and _TIMING_MODULE_AVAILABLE:
        result = timing_human_delay(base_ms, variance_percent)
        _debug_log(f"[PHASE3] _get_human_delay({base_ms}) -> {result} (enhanced)")
        return result
    return human_delay(base_ms, variance_percent)

def _should_take_long_pause() -> bool:
    """Wrapper: utilise timing.py si TITAN_ENHANCED_TIMING=1, sinon local.
    
    Quand activé, timing.py a une probabilité plus élevée (mode conservateur).
    """
    if _USE_ENHANCED_TIMING and _TIMING_MODULE_AVAILABLE:
        result = timing_should_take_long_pause()
        if result:
            _debug_log("[PHASE3] _should_take_long_pause() -> True (enhanced)")
        return result
    return should_take_long_pause()

def _get_long_pause_duration() -> int:
    """Wrapper: utilise timing.py si TITAN_ENHANCED_TIMING=1, sinon local.
    
    Quand activé, timing.py génère des pauses plus longues (2-5 min vs 30-90s).
    """
    if _USE_ENHANCED_TIMING and _TIMING_MODULE_AVAILABLE:
        result = timing_get_long_pause_duration()
        _debug_log(f"[PHASE3] _get_long_pause_duration() -> {result}ms (enhanced)")
        return result
    return get_long_pause_duration()

# Log du statut des wrappers timing au chargement
if _USE_ENHANCED_TIMING and _TIMING_MODULE_AVAILABLE:
    _debug_log("[PHASE3] Timing wrappers ACTIVE - using timing.py with ULTRA_SAFE mode")
else:
    _debug_log("[PHASE3] Timing wrappers INACTIVE - using local functions (default behavior)")


# ============================================================
# ANTI-DETECTION: Mode Stealth et comportement humain
# ============================================================

def stealth_enabled() -> bool:
    """Mode stealth ACTIVÉ PAR DÉFAUT pour éviter la détection LinkedIn.
    
    Peut être désactivé avec STEALTH_ENABLED=0 si nécessaire pour le debug.
    """
    import os
    val = os.environ.get("STEALTH_ENABLED", "1")  # Activé par défaut
    return val.lower() not in ("0", "false", "no", "off")

# Probabilité de pause café (par session de scraping)
COFFEE_BREAK_PROBABILITY = 0.03  # 3% de chance par keyword

# Pages de restriction/warning LinkedIn à détecter
# NOTE: Ces indicateurs doivent être TRÈS spécifiques pour éviter les faux positifs
# LinkedIn affiche parfois des checkpoints normaux (vérification email, captcha) qui ne sont PAS des blocages
RESTRICTION_INDICATORS = [
    "temporairement restreint",
    "temporarily restricted",
    "compte est restreint",
    "account is restricted",
    "account has been restricted",
    "votre compte a été restreint",
    "your account has been suspended",
    "compte suspendu",
    "logiciels d'automatisation",
    "automation software detected",
    "automated behavior",
    "comportement automatisé détecté",
]

# Indicateurs IGNORÉS (faux positifs fréquents) - checkpoint normal, pas de blocage
# Ces termes apparaissent lors de connexions normales et ne signifient PAS que le compte est bloqué
FALSE_POSITIVE_INDICATORS = [
    "security verification",  # Vérification normale de sécurité
    "vérification de sécurité",
    "unusual activity",  # Peut apparaître pour simple changement d'IP
    "activité inhabituelle", 
    "prove you're not a robot",  # Captcha normal
    "prouvez que vous n'êtes pas un robot",
    "checkpoint",  # URL checkpoint normale lors de la 1ère connexion
    "we've detected",  # Trop générique
    "nous avons détecté",
]

# User agents réalistes (rotation)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

# Cache du fingerprint persisté (évite les rechargements fréquents)
_PERSISTED_FINGERPRINT: Optional[dict] = None


def _get_fingerprint_storage_path() -> Path:
    """Retourne le chemin de stockage du fingerprint persisté."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "TitanScraper" / "fingerprint.json"


def _load_persisted_fingerprint() -> Optional[dict]:
    """Charge le fingerprint persisté depuis le disque."""
    global _PERSISTED_FINGERPRINT
    if _PERSISTED_FINGERPRINT is not None:
        return _PERSISTED_FINGERPRINT
    
    fp_path = _get_fingerprint_storage_path()
    if fp_path.exists():
        try:
            with open(fp_path, "r", encoding="utf-8") as f:
                _PERSISTED_FINGERPRINT = json.load(f)
                _debug_log(f"[STEALTH] Loaded persisted fingerprint from {fp_path}")
                return _PERSISTED_FINGERPRINT
        except Exception as e:
            _debug_log(f"[STEALTH] Failed to load fingerprint: {e}")
    return None


def _save_fingerprint(fingerprint: dict) -> None:
    """Sauvegarde le fingerprint sur le disque."""
    global _PERSISTED_FINGERPRINT
    _PERSISTED_FINGERPRINT = fingerprint
    
    fp_path = _get_fingerprint_storage_path()
    try:
        fp_path.parent.mkdir(parents=True, exist_ok=True)
        with open(fp_path, "w", encoding="utf-8") as f:
            json.dump(fingerprint, f, indent=2)
        _debug_log(f"[STEALTH] Saved fingerprint to {fp_path}")
    except Exception as e:
        _debug_log(f"[STEALTH] Failed to save fingerprint: {e}")


def _clean_expired_cookies(storage_state_path: str) -> str:
    """Nettoie les cookies expirés du fichier storage_state.
    
    Les cookies expirés peuvent causer des problèmes si le serveur les rejette.
    Cette fonction supprime uniquement les cookies dont la date d'expiration
    est dépassée, mais conserve tous les autres cookies (y compris les
    cookies transitoires comme __cf_bm, lidc, JSESSIONID).
    
    Note: Les cookies transitoires sont régénérés par le serveur lors de 
    la navigation, donc les supprimer n'est pas nécessaire et peut même
    causer des problèmes.
    
    Args:
        storage_state_path: Chemin vers le fichier storage_state.json
        
    Returns:
        Le même chemin si succès, chaîne vide si échec
    """
    import time
    
    if not storage_state_path or not os.path.exists(storage_state_path):
        return storage_state_path
    
    try:
        with open(storage_state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        if "cookies" not in data:
            return storage_state_path
        
        original_count = len(data["cookies"])
        now_ts = time.time()
        
        # Filtrer: supprimer uniquement les cookies vraiment expirés
        # expires == 0 ou -1 signifie cookie de session (pas d'expiration)
        cleaned_cookies = []
        removed_expired = []
        
        for cookie in data["cookies"]:
            cookie_name = cookie.get("name", "")
            expires = cookie.get("expires", 0)
            
            # Cookie de session (expires <= 0) ou cookie non expiré (expires > now)
            if expires <= 0 or expires > now_ts:
                cleaned_cookies.append(cookie)
            else:
                removed_expired.append(cookie_name)
        
        if removed_expired:
            _debug_log(f"[COOKIES] Removed {len(removed_expired)} expired cookies: {', '.join(removed_expired)}")
            data["cookies"] = cleaned_cookies
            
            # Sauvegarder le fichier nettoyé
            with open(storage_state_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            _debug_log(f"[COOKIES] Saved cleaned storage_state: {len(cleaned_cookies)}/{original_count} cookies kept")
        else:
            _debug_log(f"[COOKIES] All {original_count} cookies are valid, no cleanup needed")
        
        return storage_state_path
        
    except Exception as e:
        _debug_log(f"[COOKIES] Error cleaning cookies: {e}")
        return storage_state_path


def get_stealth_context_options() -> dict:
    """Retourne les options de contexte pour le mode stealth.
    
    Le fingerprint est persisté sur disque pour maintenir une identité
    cohérente entre les sessions et éviter les alertes de sécurité LinkedIn.
    """
    if not stealth_enabled():
        return {}
    
    # Essayer de charger un fingerprint existant
    existing = _load_persisted_fingerprint()
    if existing:
        _debug_log("[STEALTH] Using persisted fingerprint")
        # Ajouter les headers HTTP basés sur le fingerprint persisté
        result = existing.copy()
        # S'assurer que les extra_http_headers sont cohérents
        if "extra_http_headers" not in result:
            result["extra_http_headers"] = {
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            }
        return result
    
    # Générer un nouveau fingerprint et le persister
    _debug_log("[STEALTH] Generating new persistent fingerprint")
    # Viewport fixe pour cette installation (pas aléatoire à chaque fois)
    viewport_width = 1920  # Standard full HD
    viewport_height = 1080
    device_scale = 1.0  # Standard, pas aléatoire
    
    fingerprint = {
        "viewport": {"width": viewport_width, "height": viewport_height},
        "user_agent": random.choice(USER_AGENTS),
        "locale": "fr-FR",
        "timezone_id": "Europe/Paris",
        "geolocation": {"latitude": 48.8566, "longitude": 2.3522},  # Paris
        "permissions": ["geolocation"],
        "color_scheme": "light",
        "device_scale_factor": device_scale,
        "has_touch": False,
        "is_mobile": False,
        "java_script_enabled": True,
        "extra_http_headers": {
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        },
    }
    
    # Persister pour les prochaines sessions
    _save_fingerprint(fingerprint)
    
    return fingerprint

async def apply_stealth_scripts(page) -> None:
    """Applique des scripts anti-détection au navigateur.
    
    Ces scripts masquent les signatures d'automatisation Playwright.
    """
    if not stealth_enabled():
        return
    # Masquer webdriver
    await page.add_init_script("""
        // Masquer la propriété webdriver
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
        
        // Masquer les plugins Playwright
        Object.defineProperty(navigator, 'plugins', {
            get: () => [
                { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
                { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
                { name: 'Native Client', filename: 'internal-nacl-plugin' },
            ]
        });
        
        // Masquer les langues
        Object.defineProperty(navigator, 'languages', {
            get: () => ['fr-FR', 'fr', 'en-US', 'en']
        });
        
        // Chrome runtime
        window.chrome = {
            runtime: {},
            loadTimes: function() {},
            csi: function() {},
            app: {}
        };
        
        // Permissions API
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );
        
        // Console.debug leak prevention
        window.console.debug = () => {};
    """)

async def detect_restriction_page(page) -> tuple[bool, str]:
    """Détecte si la page actuelle est une page de restriction LinkedIn.
    
    NOTE: Cette fonction est maintenant plus conservatrice pour éviter les faux positifs.
    Les checkpoints normaux (captcha, vérification email) ne sont PAS considérés comme des blocages.
    Seuls les vrais messages de restriction/suspension déclenchent l'alerte.
    
    Returns:
        (is_restricted, reason)
    """
    try:
        page_content = await page.content()
        page_content_lower = page_content.lower()
        page_url = page.url.lower()
        page_title = (await page.title()).lower()
        
        # Vérifier les vrais indicateurs de restriction (très spécifiques)
        for indicator in RESTRICTION_INDICATORS:
            if indicator.lower() in page_content_lower or indicator.lower() in page_title:
                return True, f"Detected: {indicator}"
        
        # URL-based detection - SEULEMENT pour les vrais blocages
        # NOTE: "checkpoint" et "challenge" sont des pages NORMALES, pas des blocages!
        if "restricted" in page_url or "suspended" in page_url:
            return True, f"Restricted URL: {page_url}"
            
    except Exception as e:
        _debug_log(f"Error detecting restriction: {e}")
    
    return False, ""


# =============================================================================
# PHASE 3: WRAPPERS CONDITIONNELS - Stealth avancé (stealth.py)
# =============================================================================
# Ces wrappers délèguent au module stealth.py SI le flag TITAN_ENHANCED_STEALTH=1,
# sinon ils utilisent les fonctions locales existantes (comportement inchangé).
# Cela garantit une rétrocompatibilité totale quand le flag est désactivé.

def _get_stealth_context_options() -> dict:
    """Wrapper: utilise stealth.py si TITAN_ENHANCED_STEALTH=1, sinon local.
    
    Quand activé, stealth.py applique:
    - Plus de presets de viewport (6 vs 1)
    - Plus de user-agents (7 vs 5)
    - Randomisation du device_scale_factor plus fine
    """
    if _USE_ENHANCED_STEALTH and _STEALTH_MODULE_AVAILABLE:
        result = stealth_get_context_options()
        _debug_log(f"[PHASE3] _get_stealth_context_options() -> enhanced (viewport={result.get('viewport', {})})")
        return result
    return get_stealth_context_options()

async def _apply_stealth_scripts(page) -> None:
    """Wrapper: utilise stealth.py si TITAN_ENHANCED_STEALTH=1, sinon local.
    
    Quand activé, stealth.py applique:
    - Scripts anti-fingerprinting basiques (comme local)
    - PLUS: WebGL vendor/renderer masking
    - PLUS: Canvas fingerprint randomization
    - PLUS: AudioContext protection
    - PLUS: Hardware concurrency masking
    """
    if _USE_ENHANCED_STEALTH and _STEALTH_MODULE_AVAILABLE:
        _debug_log("[PHASE3] _apply_stealth_scripts() -> applying enhanced stealth")
        await stealth_apply_scripts(page)
        # Appliquer également les protections avancées
        try:
            await stealth_apply_advanced(page)
            _debug_log("[PHASE3] Advanced stealth scripts applied (WebGL, Canvas, Audio)")
        except Exception as adv_exc:
            _debug_log(f"[PHASE3] Advanced stealth error (non-blocking): {adv_exc}")
    else:
        await apply_stealth_scripts(page)

async def _detect_restriction_page(page) -> tuple[bool, str]:
    """Wrapper: utilise stealth.py si TITAN_ENHANCED_STEALTH=1, sinon local.
    
    Quand activé, stealth.py a potentiellement des indicateurs supplémentaires.
    """
    if _USE_ENHANCED_STEALTH and _STEALTH_MODULE_AVAILABLE:
        is_restricted, reason = await stealth_detect_restriction(page)
        if is_restricted:
            _debug_log(f"[PHASE3] _detect_restriction_page() -> RESTRICTED: {reason} (enhanced)")
        return is_restricted, reason
    return await detect_restriction_page(page)

# Log du statut des wrappers stealth au chargement
if _USE_ENHANCED_STEALTH and _STEALTH_MODULE_AVAILABLE:
    _debug_log("[PHASE3] Stealth wrappers ACTIVE - using stealth.py with advanced fingerprint protection")
else:
    _debug_log("[PHASE3] Stealth wrappers INACTIVE - using local functions (default behavior)")


async def simulate_human_mouse_movement(page, target_x: int = None, target_y: int = None) -> None:
    """Simule un mouvement de souris humain avec courbe de Bézier."""
    try:
        viewport = page.viewport_size
        if not viewport:
            return
            
        # Position cible ou aléatoire
        end_x = target_x if target_x else random.randint(100, viewport['width'] - 100)
        end_y = target_y if target_y else random.randint(100, viewport['height'] - 100)
        
        # Position de départ aléatoire
        start_x = random.randint(50, viewport['width'] - 50)
        start_y = random.randint(50, viewport['height'] - 50)
        
        # Nombre de pas
        steps = random.randint(5, 15)
        
        for i in range(steps):
            # Interpolation avec un peu de bruit
            progress = i / steps
            # Courbe non-linéaire (ease-in-out)
            progress = progress * progress * (3 - 2 * progress)
            
            x = int(start_x + (end_x - start_x) * progress + random.randint(-5, 5))
            y = int(start_y + (end_y - start_y) * progress + random.randint(-5, 5))
            
            await page.mouse.move(x, y)
            await page.wait_for_timeout(random.randint(10, 50))
            
    except Exception:
        pass  # Ignorer les erreurs de mouvement souris

async def simulate_human_scroll(page, direction: str = "down", amount: int = None) -> None:
    """Simule un scroll humain avec vitesse variable."""
    try:
        if amount is None:
            amount = random.randint(200, 500)
        
        if direction == "up":
            amount = -amount
        
        # Scroll en plusieurs étapes avec vitesse variable
        steps = random.randint(3, 7)
        per_step = amount // steps
        
        for _ in range(steps):
            await page.mouse.wheel(0, per_step + random.randint(-20, 20))
            await page.wait_for_timeout(random.randint(50, 150))
            
    except Exception:
        # Fallback au scroll JavaScript
        try:
            await page.evaluate(f"window.scrollBy(0, {amount})")
        except Exception:
            pass

async def simulate_reading_pause(page) -> None:
    """Simule une pause de lecture naturelle."""
    # PHASE 3: Utilise le wrapper conditionnel
    await page.wait_for_timeout(_get_random_delay(POST_READ_DELAY_MIN, POST_READ_DELAY_MAX))
    
    # Parfois, simuler un petit mouvement de souris pendant la lecture
    if random.random() < 0.3:
        await simulate_human_mouse_movement(page)


# ============================================================
# COMPORTEMENT HUMAIN AVANCÉ - Actions réalistes
# ============================================================

# Probabilités d'actions humaines (par post)
LIKE_PROBABILITY = 0.08          # 8% de chance de liker un post
PROFILE_VISIT_PROBABILITY = 0.05  # 5% de chance de visiter le profil
EXPAND_POST_PROBABILITY = 0.15   # 15% de chance d'étendre un post "voir plus"

# Délais pour actions humaines (ms)
LIKE_DELAY_MIN = 500
LIKE_DELAY_MAX = 1500
PROFILE_VISIT_DURATION_MIN = 3000
PROFILE_VISIT_DURATION_MAX = 8000

# Sélecteurs pour les boutons d'action LinkedIn
LIKE_BUTTON_SELECTORS = [
    "button.react-button__trigger[aria-label*='J\\'aime']",
    "button.react-button__trigger[aria-label*='Like']",
    "button.reactions-react-button[aria-label*='J\\'aime']",
    "button.reactions-react-button[aria-label*='Like']",
    "button[aria-label*='Réagir'][aria-pressed='false']",
    "button[aria-label*='React'][aria-pressed='false']",
    "span.reactions-react-button button",
    "button.artdeco-button[aria-label*='aime']",
]

EXPAND_POST_SELECTORS = [
    "button.feed-shared-inline-show-more-text__see-more-less-toggle",
    "button[aria-label*='voir plus']",
    "button[aria-label*='see more']",
    "span.feed-shared-inline-show-more-text__see-more-less-toggle",
]


async def simulate_like_post(page, post_element) -> bool:
    """
    Simule un like sur un post de manière humaine.
    
    Args:
        page: Page Playwright
        post_element: Élément DOM du post
        
    Returns:
        True si le like a été effectué, False sinon
    """
    try:
        # Ne pas liker tous les posts - vérifier la probabilité
        if random.random() > LIKE_PROBABILITY:
            return False
        
        # Chercher le bouton like dans le post
        like_button = None
        for selector in LIKE_BUTTON_SELECTORS:
            try:
                like_button = await post_element.query_selector(selector)
                if like_button:
                    # Vérifier que le bouton n'est pas déjà "liké"
                    aria_pressed = await like_button.get_attribute("aria-pressed")
                    if aria_pressed == "true":
                        return False  # Déjà liké
                    break
            except Exception:
                continue
        
        if not like_button:
            return False
        
        # Simuler le comportement humain avant de cliquer
        # 1. Mouvement de souris vers le bouton
        try:
            box = await like_button.bounding_box()
            if box:
                target_x = int(box['x'] + box['width'] / 2 + random.randint(-5, 5))
                target_y = int(box['y'] + box['height'] / 2 + random.randint(-3, 3))
                await simulate_human_mouse_movement(page, target_x, target_y)
        except Exception:
            pass
        
        # 2. Petite pause avant le clic (hésitation humaine)
        await page.wait_for_timeout(random.randint(MICRO_PAUSE_MIN, MICRO_PAUSE_MAX))
        
        # 3. Cliquer sur le bouton like
        await like_button.click()
        
        # 4. Pause après le like (satisfaction humaine)
        await page.wait_for_timeout(random_delay(LIKE_DELAY_MIN, LIKE_DELAY_MAX))
        
        _debug_log("ACTION: Liked a post (human behavior simulation)")
        return True
        
    except Exception as e:
        _debug_log(f"Error simulating like: {e}")
        return False


async def simulate_expand_post(page, post_element) -> bool:
    """
    Simule un clic sur "voir plus" pour étendre un post.
    
    Args:
        page: Page Playwright
        post_element: Élément DOM du post
        
    Returns:
        True si l'expansion a été effectuée, False sinon
    """
    try:
        # Vérifier la probabilité
        if random.random() > EXPAND_POST_PROBABILITY:
            return False
        
        # Chercher le bouton "voir plus"
        expand_button = None
        for selector in EXPAND_POST_SELECTORS:
            try:
                expand_button = await post_element.query_selector(selector)
                if expand_button:
                    # Vérifier que le bouton est visible
                    is_visible = await expand_button.is_visible()
                    if is_visible:
                        break
                    expand_button = None
            except Exception:
                continue
        
        if not expand_button:
            return False
        
        # Mouvement souris naturel
        try:
            box = await expand_button.bounding_box()
            if box:
                await simulate_human_mouse_movement(
                    page, 
                    int(box['x'] + box['width'] / 2),
                    int(box['y'] + box['height'] / 2)
                )
        except Exception:
            pass
        
        # Micro-pause puis clic
        await page.wait_for_timeout(random.randint(MICRO_PAUSE_MIN, MICRO_PAUSE_MAX))
        await expand_button.click()
        
        # Pause pour "lire" le contenu étendu
        await page.wait_for_timeout(random_delay(POST_READ_DELAY_MIN * 2, POST_READ_DELAY_MAX * 2))
        
        _debug_log("ACTION: Expanded a post (see more)")
        return True
        
    except Exception as e:
        _debug_log(f"Error expanding post: {e}")
        return False


async def simulate_visit_profile(page, profile_url: str) -> bool:
    """
    Simule une visite de profil occasionnelle.
    
    Cette action est très humaine - les utilisateurs cliquent souvent
    sur les profils des personnes qui postent des offres intéressantes.
    
    Args:
        page: Page Playwright
        profile_url: URL du profil à visiter
        
    Returns:
        True si la visite a été effectuée, False sinon
    """
    try:
        # Vérifier la probabilité
        if random.random() > PROFILE_VISIT_PROBABILITY:
            return False
        
        if not profile_url or not profile_url.startswith("https://"):
            return False
        
        # Sauvegarder l'URL actuelle pour revenir
        current_url = page.url
        
        # Naviguer vers le profil
        _debug_log(f"ACTION: Visiting profile {profile_url[:50]}...")
        await page.goto(profile_url, timeout=15000)
        
        # Attendre le chargement
        await page.wait_for_timeout(random_delay(2000, 4000))
        
        # Simuler la lecture du profil
        await simulate_human_scroll(page, "down", random.randint(200, 400))
        await page.wait_for_timeout(random_delay(PROFILE_VISIT_DURATION_MIN, PROFILE_VISIT_DURATION_MAX))
        
        # Parfois scroller un peu plus
        if random.random() < 0.4:
            await simulate_human_scroll(page, "down", random.randint(150, 300))
            await page.wait_for_timeout(random_delay(1500, 3000))
        
        # Revenir à la page précédente
        await page.goto(current_url, timeout=15000)
        await page.wait_for_timeout(random_delay(2000, 4000))
        
        _debug_log("ACTION: Profile visit completed, returned to search")
        return True
        
    except Exception as e:
        _debug_log(f"Error visiting profile: {e}")
        # Essayer de revenir à la page de recherche
        try:
            await page.go_back()
        except Exception:
            pass
        return False


async def perform_human_actions_on_post(page, post_element, post_data: dict) -> dict:
    """
    Effectue des actions humaines aléatoires sur un post.
    
    Cette fonction orchestre les différentes actions possibles
    (like, expand, visit profile) de manière naturelle.
    
    Args:
        page: Page Playwright
        post_element: Élément DOM du post
        post_data: Données du post extrait
        
    Returns:
        Dict avec les actions effectuées
    """
    actions = {
        "liked": False,
        "expanded": False,
        "profile_visited": False,
    }
    
    try:
        # 1. Parfois étendre le post d'abord (voir plus)
        actions["expanded"] = await simulate_expand_post(page, post_element)
        
        # 2. Simuler la lecture
        await simulate_reading_pause(page)
        
        # 3. Parfois liker le post
        actions["liked"] = await simulate_like_post(page, post_element)
        
        # 4. Très rarement, visiter le profil de l'auteur
        # Seulement si on n'a pas fait trop d'actions déjà
        if not actions["liked"] and not actions["expanded"]:
            profile_url = post_data.get("author_profile")
            if profile_url:
                actions["profile_visited"] = await simulate_visit_profile(page, profile_url)
        
    except Exception as e:
        _debug_log(f"Error in human actions: {e}")
    
    return actions


async def simulate_coffee_break(page) -> None:
    """
    Simule une pause café (longue inactivité naturelle).
    
    Cette fonction est appelée occasionnellement pour simuler
    le comportement d'un utilisateur qui fait une pause.
    """
    # Durée de la pause (2-5 minutes)
    pause_duration = random.randint(120000, 300000)
    
    _debug_log(f"ACTION: Taking coffee break ({pause_duration/1000:.0f}s)")
    
    # Parfois, revenir au feed pendant la pause
    if random.random() < 0.3:
        try:
            await page.goto("https://www.linkedin.com/feed/", timeout=15000)
        except Exception:
            pass
    
    # Attendre
    await page.wait_for_timeout(pause_duration)
    
    # Petit mouvement de souris au retour
    await simulate_human_mouse_movement(page)

# ============================================================

# Selectors (duplicated from worker.py to keep subprocess self-contained)
# 2025-01: LinkedIn SDUI uses div[role="listitem"] for search results
POST_CONTAINER_SELECTORS = [
    'div[role="listitem"]',  # NEW 2025: SDUI search results - MUST BE FIRST
    "article[data-urn*='urn:li:activity']",  # Article format
    "div[data-urn*='urn:li:activity:']",  # Div format with urn
    "div.feed-shared-update-v2",  # Classic feed format
    "div.update-components-feed-update",  # Update components format
    "div.occludable-update",  # Occludable update format
]

# Improved author selectors - try multiple patterns
# IMPORTANT: Order matters - most specific selectors first
# 2025-01: Added SDUI selectors with data-view-name attributes
AUTHOR_SELECTORS = [
    # NEW SDUI 2025: Use data-view-name attributes
    "[data-view-name='feed-actor-image'] + a p",  # Company/author name in SDUI
    "a[href*='/company/'] p:first-of-type",  # Company name from link
    "a[href*='/in/'] p:first-of-type",  # Person name from link
    # Primary: The actual visible name in the actor container
    "a.update-components-actor__container-link span.update-components-actor__name span.hoverable-link-text span[aria-hidden='true']",
    "a.app-aware-link.update-components-actor__container-link span.update-components-actor__name span[aria-hidden='true']",
    # Secondary: actor name with aria-hidden (visible text)
    "span.update-components-actor__name span.hoverable-link-text span[aria-hidden='true']",
    "span.update-components-actor__name span[aria-hidden='true']",
    "span.feed-shared-actor__name span[aria-hidden='true']",
    # Tertiary: link to profile with actor title
    "a.update-components-actor__meta-link span.update-components-actor__title span[aria-hidden='true']",
    # Fallback: direct actor name (without aria-hidden)
    "span.update-components-actor__name",
    "span.feed-shared-actor__name",
]

# Words that indicate the text is NOT an author name
INVALID_AUTHOR_PATTERNS = [
    "présentation", "presentation", "master", "université", "university",
    "erasmus", "stage", "cdi", "cdd", "recrutement", "nous recrutons",
    "offre", "poste", "recherche", "looking", "hiring", "welcome",
    "diplôme", "diplome", "licence", "bachelor", "experience",
    "actuellement", "currently", "annonce", "announcement",
]

# 2025-01: Updated text selectors for SDUI structure
# The post content is now in elements with data-view-name="feed-commentary"
TEXT_SELECTOR = "[data-view-name='feed-commentary'], [data-testid='expandable-text-box'], div.feed-shared-update-v2__description, div.update-components-text, span.break-words"

# Improved date selectors - 2025-01: SDUI uses relative time in specific elements
DATE_SELECTORS = [
    # NEW SDUI 2025: Time is in the 3rd <p> inside the author link section
    # Looking for patterns like "1 sem •", "2 j •", "1 mois •"
    "[data-view-name='feed-actor-image'] ~ a div div:nth-of-type(3) p",  # SDUI 2025 exact path
    "[data-view-name='feed-actor-image'] ~ a p:nth-of-type(3)",  # "1 sem •" in SDUI
    "a[href*='/in/'] div div:last-child p",  # Last p in author block
    "span.update-components-actor__sub-description time",
    "a.update-components-actor__sub-description-link time",
    "span.update-components-actor__sub-description span[aria-hidden='true']",
    "time.update-components-actor__sub-description",
    "span.feed-shared-actor__sub-description time",
    ".update-components-actor__sub-description",
    "time[datetime]",
    "time",
]

# Company selectors - look for the company/title line
# 2025-01: SDUI puts company info in links to /company/ OR in 2nd <p> of author block
COMPANY_SELECTORS = [
    "a[href*='/company/'] p:first-of-type",  # Company name from SDUI link
    "[data-view-name='feed-actor-image'] ~ a div div:nth-of-type(2) p",  # 2nd line = title/company in SDUI
    "a[href*='/in/'] div div:nth-of-type(2) p",  # 2nd div = title/company
    "span.update-components-actor__description",
    "span.feed-shared-actor__description", 
    "span.update-components-actor__second-line",
]

# Profile link selectors - 2025-01: SDUI uses data-view-name="feed-actor-image" 
PROFILE_LINK_SELECTORS = [
    "[data-view-name='feed-actor-image']",  # NEW SDUI 2025
    "a[href*='/company/']",  # Company profile link
    "a[href*='/in/']",  # Person profile link
    "a.update-components-actor__meta-link",
    "a.app-aware-link.update-components-actor__container-link",
    "a.feed-shared-actor__container-link",
]


def normalize_whitespace(s: str) -> str:
    """Collapse whitespace and strip."""
    import re
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def clean_author_name(name: str) -> str:
    """Clean author name - remove duplicates and noise.
    Returns empty string if name is invalid (not 'Unknown')."""
    import re
    if not name:
        return ""
    
    # Normalize whitespace first
    name = normalize_whitespace(name)
    
    # Remove common suffixes like "• 3e et +" or "Premium" or "Vérifié"
    name = re.sub(r'\s*[•·]\s*(?:3e\s+et\s+\+|2e|1er|Premium|Vérifié|Verified|Follow).*$', '', name, flags=re.IGNORECASE)
    name = name.strip()
    
    # Check for duplicated name (e.g., "John Doe John Doe")
    words = name.split()
    if len(words) >= 4:
        half = len(words) // 2
        first_half = words[:half]
        second_half = words[half:half*2]
        if first_half == second_half:
            name = ' '.join(first_half)
    
    # Also check for exact duplicate (entire name repeated)
    if len(name) > 4:
        mid = len(name) // 2
        if name[:mid].strip() == name[mid:].strip():
            name = name[:mid].strip()
    
    return name.strip() if name.strip() else ""


def is_valid_author_name(name: str) -> bool:
    """Check if the extracted name looks like a real person/company name."""
    if not name or name == "Unknown" or name == "":
        return False
    
    name_lower = name.lower()
    
    # Reject if name is too long (likely description/text, not a name)
    if len(name) > 80:
        return False
    
    # Reject if name contains invalid patterns
    for pattern in INVALID_AUTHOR_PATTERNS:
        if pattern in name_lower:
            return False
    
    # Reject if name has too many words (real names usually 2-5 words)
    words = name.split()
    if len(words) > 8:
        return False
    
    # Reject if name starts with articles or prepositions (likely a sentence)
    sentence_starters = ['le', 'la', 'les', 'un', 'une', 'des', 'nous', 'je', 'il', 'elle', 
                         'the', 'a', 'an', 'we', 'i', 'he', 'she', 'our', 'my']
    first_word = words[0].lower() if words else ""
    if first_word in sentence_starters:
        return False
    
    # Reject if it looks like a degree/program name
    degree_patterns = ['master', 'licence', 'bachelor', 'bac+', 'diplôme', 'université']
    if any(p in name_lower for p in degree_patterns):
        return False
    
    return True


def detect_language(text: str, default: str = "fr") -> str:
    """
    Language detection - returns 'fr' for French, 'en' for English, or other codes.
    Used to filter out non-French posts.
    """
    if not text:
        return default
    
    text_lower = text.lower()
    
    # French-specific indicators (common words that are distinctly French)
    fr_indicators = [
        # Articles and prepositions
        "le", "la", "les", "du", "des", "un", "une", "au", "aux",
        # Conjunctions and common words
        "et", "ou", "mais", "donc", "pour", "que", "qui", "dans", "sur", "avec",
        # Verbs (conjugated forms typical of French)
        "nous", "vous", "est", "sont", "avons", "êtes", "être", "avoir",
        "recherche", "recrute", "cherche", "souhaite", "rejoint",
        # French-specific terms
        "poste", "emploi", "équipe", "entreprise", "société", "cabinet",
        "candidat", "profil", "mission", "cdi", "cdd", "stage",
        # Legal terms in French
        "juriste", "avocat", "juridique", "contrat", "contentieux",
    ]
    
    # Strong French indicators that alone indicate French content
    strong_fr_indicators = ["recrute", "recherche", "cherche", "juriste", "avocat", "juridique"]
    
    # English-specific indicators
    en_indicators = [
        "the", "is", "are", "we", "our", "you", "your", "this", "that",
        "hiring", "looking", "seeking", "join", "team", "role", "position",
        "candidate", "apply", "opportunity", "company", "job",
    ]
    
    # Count occurrences
    fr_count = sum(1 for w in fr_indicators if f" {w} " in f" {text_lower} " or text_lower.startswith(f"{w} ") or text_lower.endswith(f" {w}"))
    en_count = sum(1 for w in en_indicators if f" {w} " in f" {text_lower} " or text_lower.startswith(f"{w} ") or text_lower.endswith(f" {w}"))
    
    # Check for strong French indicators
    has_strong_fr = any(f" {w} " in f" {text_lower} " or text_lower.startswith(f"{w} ") or text_lower.endswith(f" {w}") for w in strong_fr_indicators)
    
    # Determine language
    if fr_count >= 3 and fr_count > en_count:
        return "fr"
    elif en_count >= 3 and en_count > fr_count:
        return "en"
    elif fr_count >= 2:
        return "fr"
    elif has_strong_fr and en_count < 2:
        # Strong French indicator with no/little English = French
        return "fr"
    elif en_count >= 2:
        return "en"
    elif fr_count >= 1 and en_count == 0:
        # At least one French indicator and no English = likely French
        return "fr"
    
    return default


def is_french_post(text: str) -> bool:
    """
    Check if a post is in French.
    Returns True only for posts that are clearly in French.
    Used to filter posts for France-only requirements.
    
    EXCLUDES:
    - Posts primarily in English
    - Bilingual posts (Canada, international orgs) - these often have French translation
      appended but are primarily aimed at non-French markets
    """
    if not text:
        return False
    
    text_lower = text.lower()
    
    # ===== HANDLE ENCODING ISSUES =====
    # Sometimes text comes with UTF-8 encoding issues (e.g., "Ã©" instead of "é")
    # Try to decode/normalize
    try:
        if "ã" in text_lower or "â" in text_lower:
            # Likely double-encoded UTF-8
            try:
                text_lower = text.encode('latin-1').decode('utf-8').lower()
            except (UnicodeDecodeError, UnicodeEncodeError):
                pass
    except Exception:
        pass
    
    # Reject posts that are bilingual (common in Canada/international)
    # These typically have both languages separated by "--" or "---"
    bilingual_markers = [
        "-- vous", "-- à ", "--- à", "-- en français", "---",
        "looking for trusted legal guidance",  # Canadian bar post
        "cba find-a-lawyer", "abc trouver un avocat",  # Specific Canadian content
    ]
    if any(marker in text_lower for marker in bilingual_markers):
        # Check if it's genuinely bilingual (has significant English)
        en_words = ["the ", "is ", "are ", "we ", "our ", "you ", "your ", "this ", "that ",
                    "hiring ", "looking ", "join ", "team ", "role ", "candidate ", "apply "]
        en_count = sum(1 for w in en_words if w in text_lower)
        if en_count >= 5:  # Significant English presence
            return False
    
    # ===== QUICK FRENCH DETECTION =====
    # If we find clear French signals, accept it immediately
    strong_fr_signals = [
        "recrute", "recherche", "poste à pourvoir", "nous recherchons",
        "rejoignez", "cabinet", "juriste", "avocat", "juridique",
        "contrat", "cdi", "cdd", "alternance", "équipe",
        "cher réseau", "chers tous", "rejoindre notre équipe",
    ]
    if any(signal in text_lower for signal in strong_fr_signals):
        # But still reject if too much English
        en_words = ["the ", "is ", "are ", "we ", "our ", "you ", "your "]
        en_count = sum(1 for w in en_words if w in text_lower)
        if en_count < 5:
            return True
    
    # Reject if primarily English
    lang = detect_language(text, default="unknown")
    if lang == "en":
        return False
    
    # Accept French or unknown (be less conservative to avoid missing French posts
    # with encoding issues)
    if lang == "fr":
        return True
    
    # For unknown, do a final check for French content
    # If there are French-looking words, accept it
    fr_fallback_signals = [
        "notre", "nous", "vous", "pour", "dans", "avec", "sur", "les", "des",
        "une", "est", "sont", "cette", "ces", "aussi", "ainsi", "donc",
    ]
    fr_found = sum(1 for signal in fr_fallback_signals if f" {signal} " in f" {text_lower} ")
    if fr_found >= 2:
        return True
    
    # Default: reject unknown language
    return False


def make_post_id(*parts) -> str:
    """Generate a deterministic post ID."""
    import hashlib
    blob = "|".join(str(p) for p in parts if p)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def classify_author_type(author: str, author_profile: Optional[str], company: Optional[str]) -> str:
    """
    Classify author type for Titan Partners filtering.
    Returns: 'company', 'individual', 'agency', 'unknown'
    """
    author_lower = (author or "").lower()
    
    # Check if it's an agency/job board
    for agency_kw in EXCLUSION_AGENCIES:
        if agency_kw in author_lower:
            return "agency"
    
    # Check if author has a personal profile (/in/) - indicates individual
    if author_profile and "/in/" in str(author_profile):
        return "individual"
    
    # Check if author name suggests company (legal entity markers)
    company_markers = ['sas', 'sarl', 'sa ', 's.a.', 'eurl', 'sasu', 'inc', 'ltd', 'llp', 
                       'group', 'groupe', 'company', 'cabinet', 'associés', 'partners',
                       'associes', '& associés', '& associes']
    if any(marker in author_lower for marker in company_markers):
        return "company"
    
    # If author name is ALL CAPS or mostly caps, likely a company
    if author and len(author) > 3:
        upper_ratio = sum(1 for c in author if c.isupper()) / len(author.replace(" ", ""))
        if upper_ratio > 0.7:
            return "company"
    
    return "unknown"


def is_external_recruitment(text: str) -> bool:
    """Check if post is about external recruitment (for a client)."""
    text_lower = (text or "").lower()
    for pattern in EXCLUSION_EXTERNAL_RECRUITMENT:
        if pattern in text_lower:
            return True
    return False


def is_outside_france(text: str, author: str = "", company: str = "") -> bool:
    """
    Check if post is about a job outside France.
    Titan Partners only wants positions in France.
    
    Returns True if the post should be EXCLUDED (outside France).
    """
    # Combine all text sources to check
    combined_text = f"{text} {author} {company}".lower()
    
    # Check for excluded locations
    for location in EXCLUSION_LOCATIONS:
        if location in combined_text:
            # Exception: if "France" is explicitly mentioned, allow it
            # (some posts mention Monaco office but France position)
            if "france" in combined_text.lower():
                # More specific check: if the location appears more prominently than France
                loc_pos = combined_text.find(location)
                france_pos = combined_text.find("france")
                # If excluded location appears before France mention, exclude
                if loc_pos < france_pos:
                    return True
                # If France appears first, keep the post
                continue
            return True
    
    return False


def is_non_legal_sector(text: str) -> bool:
    """
    Check if post is about a non-legal sector (real estate, IT, sales, etc.).
    Titan Partners only wants legal/juridique positions.
    
    Returns True if the post should be EXCLUDED.
    """
    text_lower = (text or "").lower()
    for sector in EXCLUSION_NON_LEGAL_SECTORS:
        if sector in text_lower:
            return True
    return False


def is_jobseeker_post(text: str) -> bool:
    """Check if post is from someone seeking a job (not recruiting)."""
    text_lower = (text or "").lower()
    for pattern in EXCLUSION_JOBSEEKER:
        if pattern in text_lower:
            return True
    return False


def is_non_recruitment_content(text: str) -> bool:
    """Check if post is NOT about recruitment (events, articles, welcomes, etc.)."""
    text_lower = (text or "").lower()
    for pattern in EXCLUSION_NON_RECRUITMENT:
        if pattern in text_lower:
            return True
    return False


def is_excluded_contract_type(text: str) -> bool:
    """
    Check if post is about excluded contract types (stage, alternance, apprentissage, intérim).
    Titan Partners only wants CDI/CDD positions.
    
    Returns True if the post should be EXCLUDED.
    """
    text_lower = (text or "").lower()
    
    # First check if it's explicitly a CDI/CDD - these are OK
    cdi_cdd_signals = ["cdi", "cdd", "contrat à durée", "temps plein", "temps partiel"]
    has_cdi_cdd = any(signal in text_lower for signal in cdi_cdd_signals)
    
    # Check for excluded contract types
    for pattern in EXCLUSION_CONTRACT_TYPES:
        if pattern in text_lower:
            # If it also mentions CDI/CDD prominently, it might be OK
            # But if stage/alternance is the main subject, exclude
            # Simple heuristic: if "stage" appears before "cdi", it's a stage offer
            pattern_pos = text_lower.find(pattern)
            cdi_pos = text_lower.find("cdi")
            cdd_pos = text_lower.find("cdd")
            
            # If no CDI/CDD mentioned, definitely exclude
            if not has_cdi_cdd:
                return True
            
            # If stage/alternance appears in first 200 chars, likely the main subject
            if pattern_pos < 200:
                return True
    
    return False


def has_internal_recruitment_signal(text: str) -> bool:
    """Check if post has signals of internal/direct recruitment."""
    text_lower = (text or "").lower()
    for signal in RECRUITMENT_INTERNAL_SIGNALS:
        if signal in text_lower:
            return True
    return False


def has_legal_keywords(text: str) -> bool:
    """Check if post contains legal profession keywords."""
    text_lower = (text or "").lower()
    for kw in LEGAL_KEYWORDS:
        if kw in text_lower:
            return True
    return False


def is_post_too_old(published_at: Optional[str]) -> bool:
    """Check if post is older than MAX_POST_AGE_DAYS (3 weeks)."""
    if not published_at:
        return False  # If no date, don't exclude (we'll try to get it)
    
    try:
        from datetime import datetime, timezone, timedelta
        
        # Parse ISO format date
        if published_at.endswith('Z'):
            pub_date = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
        elif '+' in published_at or published_at.endswith('00:00'):
            pub_date = datetime.fromisoformat(published_at)
        else:
            pub_date = datetime.fromisoformat(published_at)
            pub_date = pub_date.replace(tzinfo=timezone.utc)
        
        now = datetime.now(timezone.utc)
        age = now - pub_date
        
        return age.days > MAX_POST_AGE_DAYS
    except Exception:
        return False  # If parsing fails, don't exclude


def filter_post_titan_partners(post: dict) -> tuple[bool, str]:
    """
    Apply Titan Partners filtering rules.
    
    Returns: (is_valid, rejection_reason)
    - is_valid=True: post should be kept
    - is_valid=False: post should be excluded, reason explains why
    
    [ADAPTER] If use_unified_filter is enabled, delegates to UnifiedFilter.
    """
    author = post.get("author", "")
    author_profile = post.get("author_profile")
    company = post.get("company")
    text = post.get("text", "")
    published_at = post.get("published_at")
    
    # [ADAPTER] Use UnifiedFilter if enabled
    flags = get_feature_flags()
    if _ADAPTERS_AVAILABLE and (flags.use_unified_filter or flags.use_ml_interface):
        keep, category, confidence = should_keep_post(
            text=text, 
            author=author, 
            company=company or "",
        )
        _debug_log(f"[ADAPTER] UnifiedFilter: keep={keep}, category={category}, confidence={confidence:.2f}")
        if not keep:
            return False, f"UNIFIED_FILTER:{category}"
        # Still check post age (not in unified filter)
        if is_post_too_old(published_at):
            return False, f"TOO_OLD: post older than {MAX_POST_AGE_DAYS} days"
        return True, "OK"
    
    # Legacy filtering logic below
    # Rule 1: Check post age (max 3 weeks)
    if is_post_too_old(published_at):
        return False, f"TOO_OLD: post older than {MAX_POST_AGE_DAYS} days"
    
    # Rule 2: Classify author type
    author_type = classify_author_type(author, author_profile, company)
    
    # Rule 3: Exclude agencies/job boards
    if author_type == "agency":
        return False, f"AGENCY: {author}"
    
    # Rule 4: Exclude external recruitment
    if is_external_recruitment(text):
        return False, "EXTERNAL_RECRUITMENT: pour un client ou tiers"
    
    # Rule 4b: Exclude positions outside France
    if is_outside_france(text, author, company or ""):
        return False, "OUTSIDE_FRANCE: poste hors France"
    
    # Rule 5: Exclude job seekers
    if is_jobseeker_post(text):
        return False, "JOBSEEKER: auteur cherche un emploi"
    
    # Rule 5b: Exclude stage/alternance/apprentissage (only CDI/CDD wanted)
    if is_excluded_contract_type(text):
        return False, "EXCLUDED_CONTRACT: stage/alternance/apprentissage"
    
    # Rule 5c: Exclude non-legal sectors (real estate, IT, sales, etc.)
    if is_non_legal_sector(text):
        return False, "NON_LEGAL_SECTOR: secteur hors juridique"
    
    # Rule 6: Must have legal keywords
    if not has_legal_keywords(text):
        return False, "NO_LEGAL_KEYWORDS"
    
    # Rule 7: Recruitment signals - RELAXED
    # If post has legal keywords AND job-related terms, accept it even without explicit "recrute"
    has_recruitment_signal = has_internal_recruitment_signal(text)
    text_lower = text.lower()
    
    # Additional job-related signals that indicate a job posting
    job_related_signals = [
        "cdi", "cdd", "temps plein", "temps partiel", "full time", "part time",
        "salaire", "rémunération", "package", "compensation",
        "expérience", "experience", "profil recherché", "mission",
        "candidature", "postuler", "candidat", "candidate",
        "contrat", "poste", "opportunité", "opportunity",
        "cabinet", "étude", "department", "équipe juridique", "legal team",
        "basé à", "based in", "localisation", "location",
        "rattaché", "reporting to", "sous la responsabilité",
    ]
    has_job_signal = any(signal in text_lower for signal in job_related_signals)
    
    # Accept if: has recruitment signal OR has job-related signals
    if not has_recruitment_signal and not has_job_signal:
        return False, "NO_RECRUITMENT_SIGNAL: pas de signal de recrutement ou poste"
    
    # Rule 8: Exclude non-recruitment content ONLY if no strong signals
    if is_non_recruitment_content(text):
        strong_signals = ["recrute", "nous recherchons", "on recherche", "hiring", 
                         "poste à pourvoir", "postes à pouvoir", "rejoignez-nous",
                         "cdi", "cdd", "opportunité", "mission", "contrat"]
        if not any(signal in text_lower for signal in strong_signals):
            return False, "NON_RECRUITMENT: contenu non-recrutement"
    
    return True, "OK"


def parse_relative_date(txt: str) -> Optional[datetime]:
    """Parse LinkedIn relative date like '3 j', '1 sem', '2 mois', '3d', '1w'.
    
    Supports both French and English formats:
    - French: j, jour, h, heure, min, minute, sem, semaine, mois, an
    - English: d, day, h, hour, m, min, w, week, mo, month, y, year
    """
    import re
    if not txt:
        return None
    
    # Clean up the text
    txt = txt.lower().strip()
    # Remove common prefixes like "Edited •" or "• "
    txt = re.sub(r'^[•\s]+|modifié[•\s]+|edited[•\s]+', '', txt, flags=re.IGNORECASE)
    txt = txt.strip()
    
    now = datetime.now(timezone.utc)
    
    # Try to find a number followed by a time unit
    # French patterns
    patterns = [
        # Minutes
        (r"(\d+)\s*(?:min(?:ute)?s?)", "minutes"),
        # Hours
        (r"(\d+)\s*(?:h(?:eure)?s?|hour?s?)", "hours"),
        # Days
        (r"(\d+)\s*(?:j(?:our)?s?|d(?:ay)?s?)", "days"),
        # Weeks
        (r"(\d+)\s*(?:sem(?:aine)?s?|w(?:eek)?s?)", "weeks"),
        # Months
        (r"(\d+)\s*(?:mois|mo(?:nth)?s?)", "months"),
        # Years
        (r"(\d+)\s*(?:an(?:née)?s?|y(?:ear)?s?)", "years"),
    ]
    
    from datetime import timedelta
    
    for pattern, unit in patterns:
        match = re.search(pattern, txt)
        if match:
            try:
                value = int(match.group(1))
                if unit == "minutes":
                    return now - timedelta(minutes=value)
                elif unit == "hours":
                    return now - timedelta(hours=value)
                elif unit == "days":
                    return now - timedelta(days=value)
                elif unit == "weeks":
                    return now - timedelta(weeks=value)
                elif unit == "months":
                    return now - timedelta(days=value * 30)
                elif unit == "years":
                    return now - timedelta(days=value * 365)
            except Exception:
                pass
    
    # Check for "aujourd'hui" / "today" / "now" / "à l'instant"
    if any(x in txt for x in ["aujourd", "today", "now", "instant", "maintenant"]):
        return now
    
    # Check for "hier" / "yesterday"
    if any(x in txt for x in ["hier", "yesterday"]):
        return now - timedelta(days=1)
    
    return None


async def extract_posts_simple(page, keyword: str, max_items: int = 10) -> list[dict]:
    """Simple post extraction - returns raw dicts."""
    posts = []
    seen_ids = set()
    
    # Attendre que le contenu réel de LinkedIn soit chargé
    # LinkedIn utilise un skeleton loader qui disparaît quand le contenu est prêt
    _debug_log("Waiting for LinkedIn content to load...")
    content_loaded = False
    
    # Attendre jusqu'à 15 secondes que le contenu apparaisse
    for attempt in range(15):
        # Vérifier si le skeleton loader a disparu
        skeleton = await page.query_selector("div.app-boot-bg-skeleton")
        if skeleton:
            is_visible = await skeleton.is_visible()
            if is_visible:
                _debug_log(f"Skeleton loader still visible, waiting... (attempt {attempt+1})")
                await page.wait_for_timeout(1000)
                continue
        
        # Vérifier si les conteneurs de posts sont présents
        for selector in POST_CONTAINER_SELECTORS:
            elements = await page.query_selector_all(selector)
            if elements and len(elements) > 0:
                _debug_log(f"Content loaded! Found {len(elements)} posts with selector '{selector}'")
                content_loaded = True
                break
        
        if content_loaded:
            break
        
        await page.wait_for_timeout(1000)
    
    if not content_loaded:
        _debug_log("WARNING: Content may not be fully loaded after 15 seconds")
    
    # Wait for posts to load with randomized delay to appear more human
    # PHASE 3: Utilise le wrapper conditionnel
    await page.wait_for_timeout(_get_random_delay(PAGE_LOAD_DELAY_MIN, PAGE_LOAD_DELAY_MAX))
    
    # Scroll to load more content (limited scrolls with random delays)
    for _ in range(MAX_SCROLLS_PER_PAGE):
        await page.evaluate("window.scrollBy(0, 800)")
        # PHASE 3: Utilise le wrapper conditionnel
        await page.wait_for_timeout(_get_random_delay(SCROLL_DELAY_MIN, SCROLL_DELAY_MAX))
    
    # DEBUG: Sauvegarder un extrait du HTML pour diagnostic si aucun élément trouvé
    try:
        html_snippet = await page.evaluate("() => document.body.innerHTML.substring(0, 10000)")
        _debug_log(f"Page HTML snippet (first 2000 chars): {html_snippet[:2000]}")
    except Exception as e:
        _debug_log(f"Could not capture HTML: {e}")
    
    # Find post elements
    elements = []
    _debug_log(f"Looking for post containers with {len(POST_CONTAINER_SELECTORS)} selectors")
    for selector in POST_CONTAINER_SELECTORS:
        try:
            found = await page.query_selector_all(selector)
            _debug_log(f"Selector '{selector}' found {len(found) if found else 0} elements")
            if found:
                elements.extend(found)
        except Exception as e:
            _debug_log(f"Selector '{selector}' error: {e}")
            continue
    _debug_log(f"Total elements found: {len(elements)}")
    
    # Debug: log structure of first element to understand new SDUI layout
    if elements:
        try:
            first_el = elements[0]
            inner_html = await first_el.evaluate("el => el.innerHTML.substring(0, 5000)")
            _debug_log(f"FIRST ELEMENT HTML (5000 chars): {inner_html}")
        except Exception as e:
            _debug_log(f"Could not get first element HTML: {e}")
    
    for idx, el in enumerate(elements):
        if len(posts) >= max_items:
            break
        
        try:
            _debug_log(f"Processing element {idx+1}/{len(elements)}")
            # Author - try multiple selectors
            # Use empty string instead of "Unknown" - leave blank if not found
            author = ""
            author_profile = None
            
            # NEW 2025: Try SDUI author extraction first
            # In SDUI, author/company name is in link to /company/ or /in/
            try:
                # Try company link first
                company_link = await el.query_selector("a[href*='/company/']")
                if company_link:
                    href = await company_link.get_attribute("href")
                    if href:
                        author_profile = href.split("?")[0]
                    # Get company name from first <p> inside or adjacent
                    name_el = await company_link.query_selector("p")
                    if name_el:
                        author = normalize_whitespace(await name_el.inner_text())
                        if author:
                            _debug_log(f"  Found author from company link: '{author}'")
                
                # If no company, try person link
                if not author:
                    person_link = await el.query_selector("a[href*='/in/']")
                    if person_link:
                        href = await person_link.get_attribute("href")
                        if href:
                            author_profile = href.split("?")[0]
                        name_el = await person_link.query_selector("p")
                        if name_el:
                            author = normalize_whitespace(await name_el.inner_text())
                            if author:
                                _debug_log(f"  Found author from person link: '{author}'")
            except Exception as e:
                _debug_log(f"  SDUI author extraction error: {e}")
            
            # Fallback: classic selectors for author
            if not author:
                for author_sel in AUTHOR_SELECTORS:
                    try:
                        author_el = await el.query_selector(author_sel)
                        if author_el:
                            raw_author = await author_el.inner_text()
                            raw_author = clean_author_name(raw_author)
                            # Validate the extracted name
                            if raw_author and raw_author != "Unknown" and len(raw_author) > 2:
                                if raw_author.lower().startswith("view"):
                                    continue
                                # Use the validation function to check if it's a real name
                                if is_valid_author_name(raw_author):
                                    author = raw_author
                                    break
                    except Exception:
                        continue
            
            # If author is still unknown but we have a profile link, try to extract from URL
            if author == "Unknown" and author_profile:
                import re
                # Extract name from profile URL like /in/john-doe-1234/
                match = re.search(r'/in/([^/?]+)', author_profile)
                if match:
                    url_name = match.group(1)
                    # Convert URL slug to name: "john-doe-1234" -> "John Doe"
                    # Remove trailing numbers
                    url_name = re.sub(r'-\d+$', '', url_name)
                    # Replace dashes with spaces and capitalize
                    name_parts = url_name.replace('-', ' ').split()
                    if len(name_parts) >= 2 and len(name_parts) <= 5:
                        author = ' '.join(p.capitalize() for p in name_parts)
            
            _debug_log(f"  Element {idx+1}: author='{author}', author_profile={author_profile}")
            
            # ===== PRE-QUALIFICATION PHASE 1: Author check (0 HTTP cost) =====
            # Skip immediately if author is a known excluded entity (agency, competitor, etc.)
            if _PRE_QUALIFIER_AVAILABLE and author:
                is_excluded, exclusion_reason = is_excluded_author(author)
                if is_excluded:
                    _debug_log(f"  SKIPPING element {idx+1}: pre-qual rejected author '{author}' ({exclusion_reason})")
                    if _PRE_QUAL_METRICS:
                        _PRE_QUAL_METRICS.record("rejected_author_only")
                    continue
            
            # Text - try multiple selectors for new SDUI structure
            text = ""
            
            # NEW 2025: Try SDUI selectors first (data-view-name based)
            sdui_text_selectors = [
                "[data-view-name='feed-commentary']",
                "[data-testid='expandable-text-box']",
            ]
            for sdui_sel in sdui_text_selectors:
                try:
                    text_el = await el.query_selector(sdui_sel)
                    if text_el:
                        text = normalize_whitespace(await text_el.inner_text())
                        if text and len(text) > 20:
                            _debug_log(f"  Found text with SDUI selector '{sdui_sel}', length={len(text)}")
                            break
                except Exception as e:
                    _debug_log(f"  SDUI selector '{sdui_sel}' error: {e}")
            
            # If no text found with SDUI, try classic selectors
            if not text or len(text) < 20:
                classic_text_selectors = [
                    "div.feed-shared-update-v2__description",
                    "div.update-components-text",
                    "span.break-words",
                ]
                for classic_sel in classic_text_selectors:
                    try:
                        text_el = await el.query_selector(classic_sel)
                        if text_el:
                            candidate = normalize_whitespace(await text_el.inner_text())
                            if candidate and len(candidate) > 20:
                                text = candidate
                                _debug_log(f"  Found text with classic selector '{classic_sel}'")
                                break
                    except Exception:
                        continue
            
            # Last fallback - any text in div[dir='ltr']
            if not text or len(text) < 20:
                try:
                    text_el = await el.query_selector("div[dir='ltr']")
                    if text_el:
                        candidate = normalize_whitespace(await text_el.inner_text())
                        if candidate and len(candidate) > 50:  # Higher threshold for generic selector
                            text = candidate
                            _debug_log("  Found text with fallback div[dir='ltr']")
                except Exception:
                    pass
            
            _debug_log(f"  Element {idx+1}: text length={len(text)}, text preview='{text[:100] if text else 'EMPTY'}..'")
            
            if not text or len(text) < 20:
                _debug_log(f"  SKIPPING element {idx+1}: text too short or empty")
                continue
            
            # ===== PRE-QUALIFICATION PHASE 2: Text preview check =====
            # Use only first 400 chars for pre-qual (sufficient for pattern matching)
            # This avoids expensive full extraction for posts that will be rejected anyway
            if _PRE_QUALIFIER_AVAILABLE:
                text_preview = text[:400] if len(text) > 400 else text
                pre_qual_result = pre_qualify_post(
                    preview_text=text_preview,
                    author_name=author,
                    company_name=None,  # Company not extracted yet
                    known_companies=None,  # Could be populated from whitelist
                )
                if not pre_qual_result.should_extract:
                    rejection_reason = getattr(pre_qual_result, 'rejection_reason', None) or getattr(pre_qual_result, 'reason', 'unknown')
                    _debug_log(f"  SKIPPING element {idx+1}: pre-qual rejected - {rejection_reason}")
                    if _PRE_QUAL_METRICS:
                        _PRE_QUAL_METRICS.record(f"rejected_{rejection_reason}")
                    continue
                else:
                    _debug_log(f"  Element {idx+1} PASSED pre-qual (reason={getattr(pre_qual_result, 'reason', 'unknown')})")
                    if _PRE_QUAL_METRICS:
                        _PRE_QUAL_METRICS.record("passed_to_full_extraction")
            else:
                _debug_log(f"  Element {idx+1} BYPASSED pre-qual (module not available)")
            
            # Date - try multiple selectors for published_at (NOT collected_at)
            published_at = None
            for date_sel in DATE_SELECTORS:
                try:
                    date_el = await el.query_selector(date_sel)
                    if date_el:
                        date_txt = await date_el.inner_text()
                        if date_txt:
                            dt = parse_relative_date(date_txt)
                            if dt:
                                published_at = dt.isoformat()
                                _debug_log(f"  Found date '{date_txt}' via selector {date_sel}")
                                break
                except Exception:
                    continue
            
            # SDUI fallback: search for date pattern in all <p> elements
            if not published_at:
                try:
                    all_p = await el.query_selector_all("p")
                    for p_el in all_p:
                        p_txt = await p_el.inner_text()
                        if p_txt:
                            # Look for patterns like "3 sem •", "1 mois •", "2 j •"
                            import re
                            if re.search(r'\d+\s*(sem|mois|jour|j|h|min|an)\s*[•·]', p_txt, re.IGNORECASE):
                                dt = parse_relative_date(p_txt)
                                if dt:
                                    published_at = dt.isoformat()
                                    _debug_log(f"  Found date in <p>: '{p_txt[:30]}...'")
                                    break
                except Exception:
                    pass
            
            # Company - extract just the company name, not the full description
            company = None
            for csel in COMPANY_SELECTORS:
                try:
                    c_el = await el.query_selector(csel)
                    if c_el:
                        raw_company = normalize_whitespace(await c_el.inner_text())
                        if raw_company:
                            # Skip if it's too long (likely full text, not company)
                            if len(raw_company) > 100:
                                continue
                            # Try to extract company from patterns like "Title at Company" or "Company • Location"
                            company = extract_company_name(raw_company)
                            if company and len(company) <= 60:
                                _debug_log(f"  Found company via selector: '{company}'")
                                break
                            else:
                                company = None
                except Exception:
                    continue
            
            # SDUI fallback: Look for "chez" or "@" pattern in all <p> elements
            if not company:
                try:
                    all_p = await el.query_selector_all("p")
                    for p_el in all_p:
                        p_txt = await p_el.inner_text()
                        if p_txt and len(p_txt) < 150:
                            company = extract_company_name(p_txt)
                            if company and is_valid_company_name(company):
                                _debug_log(f"  Found company in <p>: '{company}' from '{p_txt[:40]}...'")
                                break
                            else:
                                company = None
                except Exception:
                    pass
            
            # If still no company, try to extract from author description
            if not company and author and author != "Unknown" and author != "":
                # Sometimes the company is in the same element as the author
                try:
                    for desc_sel in ["span.update-components-actor__description span[aria-hidden='true']"]:
                        desc_el = await el.query_selector(desc_sel)
                        if desc_el:
                            desc_text = normalize_whitespace(await desc_el.inner_text())
                            if desc_text and len(desc_text) < 100:
                                company = extract_company_name(desc_text)
                                if company and len(company) <= 60:
                                    break
                except Exception:
                    pass
            
            # Permalink - try multiple methods
            permalink = None
            try:
                # Method 1: data-urn attribute
                urn = await el.get_attribute("data-urn")
                if urn and "activity:" in urn:
                    activity_id = urn.split("activity:")[-1].strip()
                    # Remove any trailing characters that aren't digits
                    import re
                    activity_match = re.match(r"(\d+)", activity_id)
                    if activity_match:
                        permalink = f"https://www.linkedin.com/feed/update/urn:li:activity:{activity_match.group(1)}"
            except Exception:
                pass
            
            if not permalink:
                # Method 2: Look for share link
                try:
                    share_link = await el.query_selector("a[href*='/feed/update/']")
                    if share_link:
                        href = await share_link.get_attribute("href")
                        if href:
                            permalink = href.split("?")[0]
                except Exception:
                    pass
            
            if not permalink:
                # Method 3: SDUI - Look for direct links to /feed/update/ with URN
                try:
                    import re
                    # SDUI uses href with full URN path
                    for link_sel in [
                        "a[href*='/feed/update/urn:li:']",  # Direct URN link
                        "a[href*='/feed/update/']",  # Any update link
                        "a[href*='/activity/']", 
                        "a[href*='activity:']", 
                        "button[data-urn*='activity']"
                    ]:
                        link_el = await el.query_selector(link_sel)
                        if link_el:
                            href = await link_el.get_attribute("href") or await link_el.get_attribute("data-urn")
                            if href:
                                # Extract URN from href like /feed/update/urn:li:share:7416215400826253312/
                                urn_match = re.search(r'/feed/update/(urn:li:(?:activity|share|ugcPost):\d+)', href)
                                if urn_match:
                                    permalink = f"https://www.linkedin.com/feed/update/{urn_match.group(1)}"
                                    _debug_log(f"  Found SDUI permalink via {link_sel}: {permalink[:80]}")
                                    break
                                # Also try activity ID pattern
                                activity_match = re.search(r'activity[:/](\d+)', href)
                                if activity_match:
                                    permalink = f"https://www.linkedin.com/feed/update/urn:li:activity:{activity_match.group(1)}"
                                    _debug_log(f"  Found activity ID in {link_sel}")
                                    break
                except Exception:
                    pass
            
            if not permalink:
                # Method 4: SDUI - Look for share/comment buttons with URN data
                try:
                    import re
                    # Try to find any element with data attributes containing activity/share IDs
                    for sel in [
                        "button[aria-label*='commentaire']",  # Comment button
                        "button[aria-label*='comment']",
                        "button[aria-label*='Commenter']",
                        "[data-urn*='share:']",  # Share URN
                        "[data-urn*='ugcPost:']",  # UGC post URN
                        "a[href*='/posts/']",  # Company posts link
                    ]:
                        try:
                            btn = await el.query_selector(sel)
                            if btn:
                                # Check multiple data attributes
                                for attr in ["data-urn", "data-id", "data-activity-id", "href"]:
                                    val = await btn.get_attribute(attr)
                                    if val:
                                        # Look for activity ID pattern
                                        match = re.search(r'(?:activity|share|ugcPost)[:/](\d+)', val)
                                        if match:
                                            permalink = f"https://www.linkedin.com/feed/update/urn:li:activity:{match.group(1)}"
                                            _debug_log(f"  Found permalink via {sel} attr={attr}")
                                            break
                                if permalink:
                                    break
                        except Exception:
                            continue
                except Exception:
                    pass
            
            if not permalink:
                # Method 5: Extract from full HTML of the element (search for URN patterns)
                try:
                    import re
                    outer_html = await el.evaluate("el => el.outerHTML")
                    if outer_html:
                        # Look for activity URN in HTML - try multiple patterns
                        # SDUI 2025 uses escaped JSON like \"activityId\":\"7416515147957137414\"
                        patterns = [
                            # SDUI 2025 specific patterns (with escaped quotes)
                            (r'\\?"activityId\\?"\\s*:\\s*\\?"(\d{19,20})\\?"', 'activity'),
                            (r'activityId["\s:]+(\d{19,20})', 'activity'),
                            # Standard URN patterns
                            (r'urn:li:activity:(\d+)', 'activity'),
                            (r'urn:li:share:(\d+)', 'share'),
                            (r'urn:li:ugcPost:(\d+)', 'ugcPost'),
                            (r'/feed/update/urn:li:(activity|share|ugcPost):(\d+)', None),
                            (r'"activityUrn"[:\s]+"urn:li:activity:(\d+)"', 'activity'),
                            (r'"entityUrn"[:\s]+"urn:li:(activity|share|ugcPost):(\d+)"', None),
                            (r'data-activity-id="(\d+)"', 'activity'),
                            (r'share:(\d{19,20})', 'share'),
                            (r'activity:(\d{19,20})', 'activity'),
                        ]
                        for pattern_tuple in patterns:
                            pattern = pattern_tuple[0]
                            urn_type = pattern_tuple[1] if len(pattern_tuple) > 1 else None
                            match = re.search(pattern, outer_html)
                            if match:
                                # Handle patterns with multiple groups
                                if match.lastindex and match.lastindex > 1:
                                    urn_type = match.group(1)
                                    urn_id = match.group(2)
                                else:
                                    urn_id = match.group(1)
                                    if not urn_type:
                                        urn_type = 'activity'
                                
                                # Validate ID length (LinkedIn IDs are 19-20 digits)
                                if len(urn_id) >= 10:
                                    permalink = f"https://www.linkedin.com/feed/update/urn:li:{urn_type}:{urn_id}"
                                    _debug_log(f"  Found permalink in HTML via pattern: {pattern[:50]}")
                                    break
                except Exception as e:
                    _debug_log(f"  Error extracting permalink from HTML: {e}")
                    pass
            
            if not permalink:
                # Method 6: Use author profile + hash as stable fallback (better than search URL)
                # This creates a more stable identifier based on content
                # The fallback points to the author's profile since we can't get the exact post URL
                if author and author != "Unknown" and text and author_profile:
                    import hashlib
                    text_hash = hashlib.md5(text[:200].encode('utf-8')).hexdigest()[:12]
                    # Use author profile as the clickable link (better UX than search results)
                    # Add hash fragment for uniqueness in deduplication
                    base_profile = author_profile.split('?')[0].rstrip('/')
                    permalink = f"{base_profile}#post-{text_hash}"
                    _debug_log(f"  Using author profile as fallback permalink for element {idx+1}: {permalink[:80]}")
            
            # Log if still no permalink
            if not permalink:
                _debug_log(f"  SKIPPING element {idx+1}: no permalink found")
                continue
            
            # Final validation: ensure company is not a job title or post content
            # Use the is_valid_company_name function for thorough validation
            if company and not is_valid_company_name(company):
                company = None
            
            # Generate ID based on content for deduplication
            post_id = make_post_id(permalink or text[:100], author, keyword)
            if post_id in seen_ids:
                continue
            seen_ids.add(post_id)
            
            # Store author_profile for later human actions (after all posts are extracted)
            # We can't do human actions during extraction because they navigate away and invalidate DOM
            post_with_profile = {
                "id": post_id,
                "keyword": keyword,
                "author": author,
                "author_profile": author_profile,
                "text": text,
                "language": detect_language(text),
                "published_at": published_at,
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "company": company,
                "permalink": permalink,
                "raw": None,
            }
            posts.append(post_with_profile)
            _debug_log(f"  ✓ ADDED post from element {idx+1}: author={author[:30]}, permalink={permalink[:60] if permalink else 'None'}")
        
        except Exception as e:
            # Skip this element on error - log full traceback for debugging
            import traceback
            tb_str = traceback.format_exc()
            _debug_log(f"  ERROR on element {idx+1}: {type(e).__name__}: {str(e)[:100]}")
            _debug_log(f"  TRACEBACK:\n{tb_str}")
            continue
    
    # ========== ACTIONS HUMAINES SUR LES POSTS (APRÈS EXTRACTION) ==========
    # Maintenant que tous les éléments sont extraits, on peut faire les actions humaines
    # sans risquer d'invalider les références DOM
    if posts:
        _debug_log(f"Starting human actions on {len(posts)} collected posts")
        for post_data in posts[:3]:  # Limit to first 3 posts to avoid too much time
            if post_data.get("author_profile"):
                try:
                    await perform_human_actions_on_post(page, None, {"author_profile": post_data["author_profile"]})
                except Exception as e:
                    _debug_log(f"Human action error: {e}")
    
    return posts


def extract_company_name(description: str) -> Optional[str]:
    """Extract company name from LinkedIn description like 'Title at Company' or 'Company • Location'.
    
    IMPORTANT: Returns None if only a job title is found (not a company name).
    """
    import re
    
    if not description:
        return None
    
    # Clean up the description
    description = normalize_whitespace(description)
    
    # Skip if it's too long to be a simple company/title line
    if len(description) > 80:
        return None
    
    # === JOB TITLES TO EXCLUDE ===
    # These are job titles, NOT company names - if the entire description is just this, return None
    job_titles_only = [
        # Notaires
        'notaire', 'notaire associé', 'notaire associée', 'clerc de notaire',
        'notaire salarié', 'notaire salariée', 'notaire stagiaire',
        # Avocats
        'avocat', 'avocate', 'avocat associé', 'avocat collaborateur',
        'avocat counsel', 'counsel', 'of counsel',
        # Juristes
        'juriste', 'juriste senior', 'juriste junior', 'juriste confirmé',
        'legal counsel', 'general counsel', 'head of legal',
        # Magistrats
        'magistrat', 'magistrate', 'magistrat administratif', 'magistrate administrative',
        'juge', 'procureur',
        # Mandataires
        'mandataire', 'mandataire judiciaire', 'administrateur judiciaire',
        'liquidateur', 'liquidateur judiciaire',
        # RH / Recrutement
        'talent acquisition', 'recruteur', 'recruteuse', 'rh', 'drh',
        'responsable rh', 'directeur rh', 'chargé de recrutement',
        # Autres titres
        'directeur', 'directrice', 'manager', 'responsable',
        'chef de projet', 'consultant', 'consultante',
        'senior', 'junior', 'stagiaire', 'alternant',
        'associate', 'partner', 'paralegal', 'secrétaire juridique',
        'assistant juridique', 'assistante juridique',
        'compliance officer', 'dpo', 'data protection officer',
        'contract manager', 'gestionnaire de contrats',
    ]
    
    description_lower = description.lower().strip()
    
    
    # Helper function to remove job titles from company name
    def clean_company_from_job_titles(company_name: str) -> str:
        """Remove job titles that may follow or precede company name."""
        if not company_name:
            return company_name
        
        result = company_name.strip()
        
        # Also remove common job title words at the end (multiple passes)
        job_words = ['talent', 'acquisition', 'recrutement', 'recruitment', 'hr', 'rh', 
                     'manager', 'associate', 'consultant', 'specialist', 'senior', 'junior',
                     'director', 'directeur', 'directrice', 'responsable', 'head', 'lead',
                     'officer', 'partner', 'avocat', 'notaire', 'juriste']
        
        # Multiple passes to remove chained job words like "Talent Acquisition Manager"
        changed = True
        while changed:
            changed = False
            for word in job_words:
                pattern = re.compile(r'\s+' + re.escape(word) + r'$', re.IGNORECASE)
                new_result = pattern.sub('', result)
                if new_result != result:
                    result = new_result
                    changed = True
        
        # Remove trailing job titles from job_titles_only list
        for title in job_titles_only:
            # Check if ends with job title (case insensitive)
            pattern = re.compile(r'\s+' + re.escape(title) + r'$', re.IGNORECASE)
            result = pattern.sub('', result)
        
        return result.strip() if result else company_name
    
    # FIRST: Try to extract company after @ or "chez" or "at" markers
    # Examples: "Talent Acquisition @GroupeEDH" -> "GroupeEDH"
    #           "Avocat chez Goodwin" -> "Goodwin"
    
    # Pattern: "... @Company" or "... @ Company"
    at_symbol_match = re.search(r'@\s*([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9\s&\-\.\']+)', description)
    if at_symbol_match:
        company = at_symbol_match.group(1).strip()
        # Clean up
        company = re.sub(r'\s*[-–|•].*$', '', company)
        # Remove trailing job titles
        company = clean_company_from_job_titles(company)
        if company and len(company) >= 2 and len(company) <= 50:
            return company
    
    # Pattern: "... chez Company" or "... at Company"
    # Pattern: "... chez Company" or "... at Company" (with word boundaries)
    chez_at_match = re.search(r'\b(?:chez|at)\s+([A-Z][A-Za-zÀ-ÿ0-9\s&\-\.\']+?)(?:\s*[-–|•,]|$)', description, re.IGNORECASE)
    if chez_at_match:
        company = chez_at_match.group(1).strip()
        company = re.sub(r'\s*[-–|•].*$', '', company)
        # Remove trailing job titles
        company = clean_company_from_job_titles(company)
        if company and len(company) >= 2 and len(company) <= 50:
            # Make sure it's not a job title
            if not any(company.lower() == t or company.lower().startswith(t + ' ') for t in job_titles_only):
                return company
    
    # If the entire description is just a job title (without company), return None
    for title in job_titles_only:
        if description_lower == title or description_lower.startswith(title + ' ') or description_lower.endswith(' ' + title):
            # No company found after markers, so return None
            return None
    
    # Skip if it looks like post content (has hashtags, emojis, or multiple sentences)
    content_markers = [
        '#', '🚀', '📢', '📍', '🔍', '📌', '💼', '🎯', '👤', '📩', '‼️', '✨', '??',
        '!', '?', '\n', 
        'PRÉSENTATION', 'PRESENTATION', 'INDIVIDUELLE', 'PORTRAIT',
        'recrute', 'hiring', 'recherche', 'looking',
        'Cher réseau', 'Cher Réseau', 'Bonjour', 'Hello',
        'Notre client', 'notre client', 'Our client',
        'Nous recherchons', 'nous recherchons', 'On recherche',
        'Je recrute', 'je recrute',
        'CDI', 'CDD', 'Stage', 'Alternance',
        'Master', 'Licence', 'Diplôme',
        'actuellement', 'currently',
        # Job title words that shouldn't be in company name
        'Responsable', 'responsable', 'Directeur', 'directeur',
        'Manager', 'manager', 'Head of', 'head of',
        'régional', 'regional', 'national',
    ]
    if any(marker in description for marker in content_markers):
        return None
    
    # Skip if it looks like just a subscriber count (e.g., "1234 abonnés")
    if re.match(r'^[\d\s]+abonn', description, re.IGNORECASE):
        return None
    
    # Skip if starts with a sentence starter (article, pronoun)
    sentence_starters = ['le ', 'la ', 'les ', 'un ', 'une ', 'nous ', 'je ', 'il ', 'elle ',
                         'the ', 'a ', 'an ', 'we ', 'i ', 'our ', 'my ', 'this ', 'that ']
    description_lower = description.lower()
    if any(description_lower.startswith(s) for s in sentence_starters):
        return None
    
    # Skip if contains job title indicators (likely "Company + Job Title")
    job_title_indicators = ['responsable', 'directeur', 'manager', 'head', 'chef', 
                           'senior', 'junior', 'lead', 'principal', 'associate',
                           'régional', 'national', 'europe', 'france', 'commercial']
    # If description has multiple words and contains job title, be more strict
    words = description.split()
    if len(words) > 3:
        if any(ind in description_lower for ind in job_title_indicators):
            # Try to extract just the first part (company name)
            # Pattern: "Company Name Title Words" -> extract "Company Name"
            for i, word in enumerate(words):
                if word.lower() in job_title_indicators:
                    potential_company = ' '.join(words[:i])
                    if len(potential_company) > 2 and len(potential_company) < 50:
                        return potential_company.strip()
            return None
    
    # Skip if it's a job title (starts with title words)
    title_words = ['director', 'manager', 'head', 'chief', 'lead', 'senior', 'junior', 
                  'associate', 'directeur', 'responsable', 'chef', 'juriste', 'avocat', 
                  'consultant', 'ingénieur', 'engineer', 'developer', 'analyst',
                  'recruitment', 'recrutement', 'specialiste', 'specialist', 'expert',
                  'stagiaire', 'intern', 'founder', 'ceo', 'cfo', 'coo', 'cto',
                  'fondateur', 'fondatrice', 'president', 'président', 'gérant',
                  'master', 'licence', 'étudiant', 'student', 'diplômé', 'graduate']
    
    if any(description_lower.startswith(t) for t in title_words):
        # Try to find company after "at" or "chez"
        pass
    
    # Pattern 1: "... at Company" or "... chez Company" - extract company after at/chez
    at_match = re.search(r'(?:^|\s)(?:at|chez|@)\s+([A-Z][A-Za-zÀ-ÿ0-9\s&\-\.\']+?)(?:\s*[-–•|,]|$)', description, re.IGNORECASE)
    if at_match:
        company = at_match.group(1).strip()
        # Remove trailing noise
        company = re.sub(r'\s*[-–]\s*(?:We are hiring|Hiring|Recrute).*$', '', company, flags=re.IGNORECASE)
        company = re.sub(r'\s*[•|].*$', '', company)
        # Remove "abonn" patterns
        company = re.sub(r'\s*\d+\s*abonn.*$', '', company, flags=re.IGNORECASE)
        if company and len(company) > 2 and len(company) < 50:
            # Validate it's not a sentence fragment
            if not any(company.lower().startswith(s.strip()) for s in sentence_starters):
                return company.strip()
    
    # Pattern 2: "Position | COMPANY" or "Position • COMPANY" 
    pipe_match = re.search(r'[|•]\s*([A-Z][A-Za-zÀ-ÿ0-9\s&\-\.\']+?)(?:\s*[-–|•,]|$)', description)
    if pipe_match:
        company = pipe_match.group(1).strip()
        # Remove subscriber count noise
        company = re.sub(r'\s*\d+\s*abonn.*$', '', company, flags=re.IGNORECASE)
        if company and len(company) > 2 and len(company) < 50:
            if not any(company.lower().startswith(t) for t in title_words):
                return company.strip()
    
    # Pattern 3: Look for company patterns
    company_patterns = [
        # Pattern: "Title chez COMPANY" (French)
        r'chez\s+([A-Z][A-Za-zÀ-ÿ0-9\s&\-\.\']+)',
        # Pattern: "Title at COMPANY"
        r'\bat\s+([A-Z][A-Za-zÀ-ÿ0-9\s&\-\.\']+)',
    ]
    
    for pattern in company_patterns:
        match = re.search(pattern, description)
        if match:
            company = match.group(1).strip()
            company = re.sub(r'\s*\d+\s*abonn.*$', '', company, flags=re.IGNORECASE)
            if not any(company.lower().startswith(t) for t in title_words):
                if len(company) > 2 and len(company) < 50:
                    return company.strip()
    
    # If description is short and looks like just a company name (no spaces or 1-2 words)
    if len(words) <= 3 and len(description) < 40:
        # Check it's not a job title
        if not any(t in description_lower for t in title_words):
            if not any(description_lower.startswith(s.strip()) for s in sentence_starters):
                # Final check: make sure it's not a known job title
                known_titles = [
                    'notaire', 'avocat', 'avocate', 'juriste', 'magistrat', 'magistrate',
                    'mandataire', 'consultant', 'recruteur', 'recruteuse', 'manager',
                    'directeur', 'directrice', 'responsable', 'chef', 'associate',
                    'counsel', 'paralegal', 'stagiaire', 'alternant', 'senior', 'junior',
                    'administratif', 'administrative', 'judiciaire', 'associé', 'associée',
                    'salarié', 'salariée', 'collaborateur', 'collaboratrice',
                ]
                if any(kt in description_lower for kt in known_titles):
                    return None
                return description.strip()
    
    return None


def is_valid_company_name(company: Optional[str]) -> bool:
    """
    Final validation: check if the extracted company name is actually a company,
    not a job title or other invalid value.
    
    NOTE: This is a final check - the extraction should already have filtered most issues.
    Here we just reject obvious cases of post content or standalone job titles.
    """
    import re
    
    if not company or company.strip() == "":
        return False
    
    company_lower = company.lower().strip()
    
    # ===== REJECT DATE PATTERNS =====
    # Patterns like "2 h •", "1 j •", "3 sem •" are dates, not companies
    # The bullet may appear as UTF-8 encoded "â€¢" or as actual "•" or "·"
    # Use regex to match these patterns directly
    
    # First, check if it starts with a number followed by time unit
    date_match = re.match(r'^(\d+)\s*(h|j|min|sem|mois|an)s?', company_lower, re.IGNORECASE)
    if date_match:
        # Get what follows the time unit
        after_unit = company_lower[date_match.end():].strip()
        # If nothing follows, or if what follows looks like bullet/separator/garbage
        # (includes "•", "·", "â€¢" or any non-letter garbage)
        if not after_unit or not re.search(r'[a-zA-ZàâäéèêëïîôùûüçÀÂÄÉÈÊËÏÎÔÙÛÜÇ]', after_unit):
            return False
    
    # Also check longer date formats
    date_match_long = re.match(r'^(\d+)\s*(heure|jour|semaine|mois|année)s?', company_lower, re.IGNORECASE)
    if date_match_long:
        after_unit = company_lower[date_match_long.end():].strip()
        if not after_unit or not re.search(r'[a-zA-ZàâäéèêëïîôùûüçÀÂÄÉÈÊËÏÎÔÙÛÜÇ]', after_unit):
            return False
    
    # Reject pure time indicators
    time_words = ['h', 'j', 'min', 'sem', 'mois', 'an', 'heure', 'jour', 'semaine', 'année']
    # Check if the cleaned version (only letters) is a time word
    letters_only = re.sub(r'[^a-zA-ZàâäéèêëïîôùûüçÀÂÄÉÈÊËÏÎÔÙÛÜÇ]', '', company_lower)
    if letters_only.lower() in time_words:
        return False
    
    # Reject if it's EXACTLY a job title (standalone)
    standalone_job_titles = [
        'notaire', 'avocat', 'avocate', 'juriste', 'magistrat', 'magistrate',
        'mandataire', 'consultant', 'consultante', 'recruteur', 'recruteuse',
        'manager', 'directeur', 'directrice', 'responsable', 'chef',
        'associate', 'counsel', 'paralegal', 'stagiaire', 'alternant',
        'senior', 'junior', 'notaire associé', 'notaire associée',
        'mandataire judiciaire', 'magistrate administrative',
        'talent acquisition', 'head of legal',
        # Added: common non-company terms
        'technical skills', 'soft skills', 'skills', 'expertise',
        'legal intern', 'intern', 'stage', 'alternance',
        'data protection', 'compliance', 'gdpr', 'rgpd',
        # Date-related words that should not be company names
        'modifié', 'edited', 'modified', 'suivre', 'follow',
        'abonnés', 'abonnes', 'followers', 'subscriber', 'subscribers',
    ]
    
    # Only reject if the entire company name is exactly a job title
    if company_lower in standalone_job_titles:
        return False
    
    # Reject partial matches for clearly non-company terms
    non_company_patterns = [
        'legal intern', 'intern in', 'stage en', 'alternance en',
        'skills', 'expertise in', 'specialist in',
        'abonné', 'abonne', 'follower', 'subscriber',  # Reject "37 258 abonnés" etc.
        'réaction', 'reaction',  # Reject "1 réaction", "16 réactions"
        'commentaire', 'comment',  # Reject comment counts
        ' page', 'pages',  # Reject "2 pages" etc.
        '.com', '.fr', '.org', '.net', '.io', '.co',  # Reject URLs
    ]
    for pattern in non_company_patterns:
        if pattern in company_lower:
            return False
    
    # Reject obvious post content indicators
    post_content_markers = [
        'recrute', 'hiring', 'recherche', 'cherche', 'poste à pourvoir',
        'offre d\'emploi', 'nous recherchons', 'je recrute',
        '#', '!', '?', 'http', 'www.', '📢', '🚀', '📍',
        'bonjour', 'cher réseau', 'hello', 'chers tous',
    ]
    
    for marker in post_content_markers:
        if marker in company_lower:
            return False
    
    # Must be at least 3 characters (reject things like "gu.tz")
    if len(company.strip()) < 3:
        return False
    
    # Reject if looks like a URL fragment or code
    import re
    if re.match(r'^[a-z]{1,3}\.[a-z]{1,3}$', company_lower):  # e.g., "gu.tz"
        return False
    
    # Must not be too long (likely text content)
    if len(company.strip()) > 50:
        return False
    
    return True


async def scrape_keywords(keywords: list[str], storage_state: str, max_per_keyword: int = 10, headless: bool = True, apply_titan_filter: bool = True, session_quota: int = 0) -> dict:
    """Main scraping function - runs in isolated process.
    
    Args:
        keywords: List of search keywords
        storage_state: Path to browser storage state (cookies)
        max_per_keyword: Max posts to extract per keyword
        headless: Run browser in headless mode
        apply_titan_filter: Apply Titan Partners filtering rules
        session_quota: Max total posts to accept this session (0 = no limit)
                       Used for v2 micro-session strategy (~10 posts per session)
    """
    from playwright.async_api import async_playwright
    
    results = {
        "success": True,
        "posts": [],
        "errors": [],
        "keywords_processed": 0,
        "session_quota_reached": False,  # v2: Track if we hit the quota
        "stats": {
            "total_scraped": 0,
            "accepted": 0,
            "rejected_agency": 0,
            "rejected_external": 0,
            "rejected_jobseeker": 0,
            "rejected_contract_type": 0,
            "rejected_non_recruitment": 0,
            "rejected_no_legal": 0,
            "rejected_no_signal": 0,
            "rejected_too_old": 0,
            "rejected_non_french": 0,
            "rejected_other": 0,
            "rejected_duplicate": 0,
            # v2 pre-qualification metrics
            "prequal_rejected_author": 0,
            "prequal_rejected_text": 0,
            "prequal_passed": 0,
        }
    }
    
    # Track seen posts to avoid duplicates (based on author + text hash)
    seen_posts = set()
    
    def get_post_hash(post):
        """Generate a unique hash for a post based on author and text."""
        import hashlib
        author = (post.get('author') or '').strip().lower()
        text = (post.get('text') or '').strip().lower()[:200]  # First 200 chars
        key = f"{author}|{text}"
        return hashlib.md5(key.encode('utf-8', errors='ignore')).hexdigest()
    
    try:
        async with async_playwright() as pw:
            # Launch browser with anti-detection args
            _debug_log(f"launching browser headless={headless} stealth={stealth_enabled()}")
            args = [
                "--disable-dev-shm-usage",
                "--disable-web-security",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-infobars",
                "--window-position=0,0",
                "--ignore-certificate-errors",
                "--ignore-certificate-errors-spki-list",
                "--disable-features=IsolateOrigins,site-per-process",
            ]
            if stealth_enabled():
                args.insert(0, "--disable-blink-features=AutomationControlled")
            browser = await pw.chromium.launch(
                headless=headless,
                args=args,
            )
            if stealth_enabled():
                _debug_log("browser launched with stealth args")
            
            # Create context with storage state AND stealth options
            # PHASE 3: Utilise le wrapper conditionnel
            stealth_opts = _get_stealth_context_options()
            context_opts = {**stealth_opts}
            if storage_state and os.path.exists(storage_state):
                # Clean expired and transient cookies before loading to avoid ERR_TOO_MANY_REDIRECTS
                storage_state = _clean_expired_cookies(storage_state)
                context_opts["storage_state"] = storage_state
                _debug_log(f"using storage_state from {storage_state}")
            else:
                _debug_log(f"WARNING: storage_state missing or not found: {storage_state}")
            
            context = await browser.new_context(**context_opts)
            page = await context.new_page()
            
            # Apply anti-detection scripts
            # PHASE 3: Utilise le wrapper conditionnel (stealth avancé si TITAN_ENHANCED_STEALTH=1)
            await _apply_stealth_scripts(page)
            if stealth_enabled():
                _debug_log("page created with stealth scripts applied")
            
            # Initial human-like behavior: random mouse movement
            await simulate_human_mouse_movement(page)
            
            # ========== WARM-UP: Régénérer les cookies Cloudflare/LinkedIn ==========
            # Les cookies __cf_bm et lidc sont régénérés en visitant d'abord la page publique
            # Cela évite ERR_TOO_MANY_REDIRECTS causé par des cookies transitoires manquants
            _debug_log("warm-up: navigating to LinkedIn homepage first...")
            try:
                await page.goto("https://www.linkedin.com/", timeout=20000)
                await page.wait_for_timeout(_get_random_delay(2000, 4000))
                _debug_log("warm-up: homepage loaded, Cloudflare/LinkedIn cookies regenerated")
            except Exception as warmup_err:
                _debug_log(f"warm-up: homepage navigation warning (non-fatal): {str(warmup_err)[:100]}")
                # Continue anyway - this is just a warm-up
            
            # Navigate to feed to check auth
            _debug_log("navigating to LinkedIn feed...")
            await page.goto("https://www.linkedin.com/feed/", timeout=30000)
            # PHASE 3: Utilise le wrapper conditionnel (délais ultra-safe si TITAN_ENHANCED_TIMING=1)
            await page.wait_for_timeout(_get_random_delay(PAGE_LOAD_DELAY_MIN, PAGE_LOAD_DELAY_MAX))
            
            # Simulate reading the page
            await simulate_human_mouse_movement(page)
            
            page_title = await page.title()
            current_url = page.url
            _debug_log(f"page title: {page_title}, url: {current_url}")
            
            # ========== DETECTION DE RESTRICTION ==========
            # PHASE 3: Utilise le wrapper conditionnel
            is_restricted, restriction_reason = await _detect_restriction_page(page)
            if is_restricted:
                _debug_log(f"RESTRICTION DETECTED: {restriction_reason}")
                results["success"] = False
                results["account_restricted"] = True
                results["restriction_reason"] = restriction_reason
                results["errors"].append(f"Account restricted by LinkedIn: {restriction_reason}")
                await browser.close()
                return results
            
            # Check if authenticated - get cookies from both domains
            cookies = await context.cookies(["https://www.linkedin.com", "https://linkedin.com"])
            cookie_names = [c.get("name") for c in cookies]
            _debug_log(f"cookies found: {len(cookies)}, names: {cookie_names[:15]}")
            has_li_at = any(c.get("name") == "li_at" and c.get("value") for c in cookies)
            
            # Detect if we're on the login page (session revoked by LinkedIn)
            login_page_indicators = [
                "S'identifier" in page_title,  # French
                "Sign In" in page_title,  # English
                "login" in current_url.lower(),
                "checkpoint" in current_url.lower(),  # Security checkpoint
                "authwall" in current_url.lower(),
            ]
            is_on_login_page = any(login_page_indicators)
            
            if not has_li_at:
                results["success"] = False
                # Determine if this is a revocation (had storage_state but cookie rejected)
                # vs never authenticated (no storage_state file)
                had_storage_state = storage_state and os.path.exists(storage_state)
                if had_storage_state and is_on_login_page:
                    results["session_revoked"] = True
                    results["errors"].append("Session revoked - LinkedIn rejected the authentication cookie")
                    _debug_log("ERROR: Session REVOKED by LinkedIn - cookie rejected, redirected to login page")
                else:
                    results["session_revoked"] = False
                    results["errors"].append("Not authenticated - no li_at cookie")
                    _debug_log("ERROR: Not authenticated - no li_at cookie found")
                # Log more details for debugging
                results["auth_debug"] = {
                    "page_title": page_title,
                    "current_url": current_url[:100],
                    "is_on_login_page": is_on_login_page,
                    "had_storage_state": had_storage_state,
                    "cookies_count": len(cookies),
                }
                _debug_log(f"Auth debug: {results['auth_debug']}")
                await browser.close()
                return results
            
            _debug_log("authentication OK, starting keyword scraping")
            
            # ========== SAVE REGENERATED COOKIES ==========
            # After successful auth check, save the storage state with regenerated 
            # transient cookies (__cf_bm, lidc, JSESSIONID) to prevent future
            # ERR_TOO_MANY_REDIRECTS errors
            if storage_state and os.path.exists(storage_state):
                try:
                    await context.storage_state(path=storage_state)
                    _debug_log(f"[COOKIES] Saved updated storage_state with regenerated cookies to {storage_state}")
                except Exception as save_err:
                    _debug_log(f"[COOKIES] Warning: failed to save storage_state: {str(save_err)[:100]}")
            
            # Process each keyword
            for kw_idx, keyword in enumerate(keywords):
                # ===== v2 EARLY EXIT: Stop if session quota reached =====
                if session_quota > 0 and results["stats"]["accepted"] >= session_quota:
                    _debug_log(f"SESSION QUOTA REACHED ({session_quota} posts) - stopping early")
                    results["session_quota_reached"] = True
                    break
                
                _debug_log(f"Processing keyword {kw_idx+1}/{len(keywords)}: {keyword}")
                try:
                    search_url = f"https://www.linkedin.com/search/results/content/?keywords={keyword}"
                    _debug_log(f"navigating to search: {search_url[:80]}...")
                    
                    # Simuler mouvement souris avant navigation
                    await simulate_human_mouse_movement(page)
                    
                    await page.goto(search_url, timeout=30000)
                    _debug_log("search page loaded, waiting random delay...")
                    
                    # ========== VÉRIFIER RESTRICTION APRÈS CHAQUE NAVIGATION ==========
                    # PHASE 3: Utilise le wrapper conditionnel
                    is_restricted, restriction_reason = await _detect_restriction_page(page)
                    if is_restricted:
                        _debug_log(f"RESTRICTION DETECTED during scraping: {restriction_reason}")
                        results["success"] = False
                        results["account_restricted"] = True
                        results["restriction_reason"] = restriction_reason
                        results["errors"].append(f"Account restricted during scraping: {restriction_reason}")
                        await browser.close()
                        return results
                    
                    # Délai humain avec scroll simulé
                    await simulate_human_scroll(page, "down", random.randint(100, 300))
                    # PHASE 3: Utilise le wrapper conditionnel (délais ultra-safe si TITAN_ENHANCED_TIMING=1)
                    await page.wait_for_timeout(_get_random_delay(PAGE_LOAD_DELAY_MIN, PAGE_LOAD_DELAY_MAX))
                    
                    # Simuler lecture de la page de résultats
                    await simulate_reading_pause(page)
                    await simulate_human_mouse_movement(page)
                    
                    # Scrape more posts than needed to account for filtering
                    scrape_count = max_per_keyword * 3 if apply_titan_filter else max_per_keyword
                    _debug_log(f"calling extract_posts_simple with count={scrape_count}")
                    raw_posts = await extract_posts_simple(page, keyword, scrape_count)
                    _debug_log(f"extract_posts_simple returned {len(raw_posts)} posts")
                    results["stats"]["total_scraped"] += len(raw_posts)
                    
                    # Apply Titan Partners filtering if enabled
                    _debug_log(f"Starting post filtering loop, apply_titan_filter={apply_titan_filter}")
                    for post_idx, post in enumerate(raw_posts):
                        try:
                            _debug_log(f"Processing post {post_idx+1}/{len(raw_posts)}: author={post.get('author', 'N/A')[:30]}")
                            # Simuler lecture du post occasionnellement
                            if random.random() < 0.2:
                                await simulate_reading_pause(page)
                            
                            # Check for duplicates - use persistent cache if enabled
                            flags = get_feature_flags()
                            post_text = post.get("text", "")
                            post_author = post.get("author", "")
                            post_url = post.get("permalink", "") or post.get("author_profile", "")
                            post_id = post.get("id", "")
                            
                            if _ADAPTERS_AVAILABLE and flags.use_post_cache:
                                # Use persistent cache for deduplication across sessions
                                if is_duplicate_post(
                                    text=post_text, 
                                    url=post_url, 
                                    post_id=post_id, 
                                    author=post_author
                                ):
                                    results["stats"]["rejected_duplicate"] += 1
                                    _debug_log("[ADAPTER] PostCache: duplicate detected")
                                    continue
                            else:
                                # Legacy in-memory deduplication
                                post_hash = get_post_hash(post)
                                if post_hash in seen_posts:
                                    results["stats"]["rejected_duplicate"] += 1
                                    continue
                                seen_posts.add(post_hash)
                            
                            # FILTRE LANGUE: Rejeter les posts non-français
                            # Titan Partners recherche uniquement des publications en France
                            if not is_french_post(post.get("text", "")):
                                results["stats"]["rejected_non_french"] += 1
                                _debug_log(f"  Post {post_idx+1}: rejected (non-french)")
                                continue
                            
                            if apply_titan_filter:
                                is_valid, reason = filter_post_titan_partners(post)
                                _debug_log(f"  Post {post_idx+1}: filter result valid={is_valid}, reason={reason}")
                                if is_valid:
                                    results["posts"].append(post)
                                    results["stats"]["accepted"] += 1
                                    # [ADAPTER] Mark post as seen in persistent cache
                                    if _ADAPTERS_AVAILABLE and flags.use_post_cache:
                                        mark_post_seen(
                                            text=post_text,
                                            url=post_url,
                                            post_id=post_id,
                                            author=post_author,
                                        )
                                    # ===== v2 EARLY EXIT: Check quota after each accepted post =====
                                    if session_quota > 0 and results["stats"]["accepted"] >= session_quota:
                                        _debug_log(f"SESSION QUOTA ({session_quota}) reached mid-keyword - breaking post loop")
                                        break
                                else:
                                    # Track rejection reason
                                    if "AGENCY" in reason:
                                        results["stats"]["rejected_agency"] += 1
                                    elif "EXTERNAL" in reason:
                                        results["stats"]["rejected_external"] += 1
                                    elif "JOBSEEKER" in reason:
                                        results["stats"]["rejected_jobseeker"] += 1
                                    elif "EXCLUDED_CONTRACT" in reason:
                                        results["stats"]["rejected_contract_type"] += 1
                                    elif "NON_RECRUITMENT" in reason:
                                        results["stats"]["rejected_non_recruitment"] += 1
                                    elif "NO_LEGAL" in reason:
                                        results["stats"]["rejected_no_legal"] += 1
                                    elif "NO_RECRUITMENT_SIGNAL" in reason:
                                        results["stats"]["rejected_no_signal"] += 1
                                    elif "TOO_OLD" in reason:
                                        results["stats"]["rejected_too_old"] += 1
                                    else:
                                        results["stats"]["rejected_other"] += 1
                                        _debug_log(f"  Post {post_idx+1}: rejected_other, reason={reason}")
                            else:
                                results["posts"].append(post)
                                results["stats"]["accepted"] += 1
                                _debug_log(f"  Post {post_idx+1}: accepted (no filter)")
                                # [ADAPTER] Mark post as seen in persistent cache even without filter
                                if _ADAPTERS_AVAILABLE and flags.use_post_cache:
                                    mark_post_seen(
                                        text=post_text,
                                        url=post_url,
                                        post_id=post_id,
                                        author=post_author,
                                    )
                                # ===== v2 EARLY EXIT: Check quota even without filter =====
                                if session_quota > 0 and results["stats"]["accepted"] >= session_quota:
                                    _debug_log(f"SESSION QUOTA ({session_quota}) reached - breaking post loop")
                                    break
                        except Exception as filter_err:
                            _debug_log(f"ERROR processing post {post_idx+1}: {filter_err}")
                            results["stats"]["rejected_other"] += 1
                    
                    results["keywords_processed"] += 1
                    
                    # ========== PAUSE LONGUE OCCASIONNELLE ==========
                    # Simule une distraction humaine (regarder autre chose, pause café, etc.)
                    if should_take_long_pause() and kw_idx < len(keywords) - 1:
                        pause_duration = get_long_pause_duration()
                        _debug_log(f"Taking LONG PAUSE of {pause_duration/1000:.1f}s (simulating human distraction)")
                        await page.wait_for_timeout(pause_duration)
                    # ========== PAUSE CAFÉ TRÈS OCCASIONNELLE ==========
                    # Simule une vraie pause café (2-5 minutes) - très rare
                    elif random.random() < COFFEE_BREAK_PROBABILITY and kw_idx < len(keywords) - 1:
                        _debug_log("Taking COFFEE BREAK (2-5 min) - simulating real human behavior")
                        await simulate_coffee_break(page)
                    else:
                        # Délai normal entre keywords (AUGMENTÉ)
                        delay = random_delay(KEYWORD_DELAY_MIN, KEYWORD_DELAY_MAX)
                        _debug_log(f"Waiting {delay/1000:.1f}s before next keyword")
                        await page.wait_for_timeout(delay)
                    
                except Exception as e:
                    results["errors"].append(f"Keyword '{keyword}': {str(e)}")
            
            await browser.close()
    
    except Exception as e:
        results["success"] = False
        results["errors"].append(f"Browser error: {str(e)}")
    
    return results


def main():
    """Entry point when run as subprocess.
    
    Communication modes:
    1. File-based (for Windows GUI exe without console): 
       --input-file <path> --output-file <path>
    2. Stdin/stdout (for console apps or dev mode):
       Reads JSON from stdin, writes JSON to stdout
    """
    # Debug logging
    import os as _os
    debug_path = Path(_os.environ.get("LOCALAPPDATA", ".")) / "TitanScraper" / "scrape_subprocess_debug.txt"
    def _log(msg):
        try:
            with open(debug_path, 'a', encoding='utf-8') as f:
                f.write(f"{msg}\n")
        except Exception:
            pass
    
    _log(f"main() started, argv={sys.argv}")
    
    # Check for file-based communication (needed for console=False PyInstaller exe)
    input_file = None
    output_file = None
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--input-file" and i < len(sys.argv) - 1:
            input_file = sys.argv[i + 1]
        elif arg == "--output-file" and i < len(sys.argv) - 1:
            output_file = sys.argv[i + 1]
    
    _log(f"input_file={input_file}, output_file={output_file}")
    
    # Read input
    try:
        if input_file:
            with open(input_file, 'r', encoding='utf-8-sig') as f:  # utf-8-sig handles BOM
                input_data = json.load(f)
        else:
            input_data = json.loads(sys.stdin.read())
        _log(f"input_data loaded, keywords count={len(input_data.get('keywords', []))}")
    except Exception as e:
        _log(f"ERROR loading input: {e}")
        error_result = {"success": False, "error": f"Invalid input: {e}", "posts": []}
        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(error_result, f)
        else:
            print(json.dumps(error_result))
        sys.exit(1)
    
    keywords = input_data.get("keywords", [])
    storage_state = input_data.get("storage_state", "")
    max_per_keyword = input_data.get("max_per_keyword", 10)
    headless = input_data.get("headless", True)
    session_quota = input_data.get("session_quota", 0)  # v2: optional session quota
    
    # Set browsers path if provided
    browsers_path = input_data.get("browsers_path")
    if browsers_path:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = browsers_path
    _log(f"PLAYWRIGHT_BROWSERS_PATH={os.environ.get('PLAYWRIGHT_BROWSERS_PATH', 'NOT SET')}")
    
    # Run scraping
    try:
        _log(f"about to call asyncio.run(scrape_keywords()) with session_quota={session_quota}")
        result = asyncio.run(scrape_keywords(keywords, storage_state, max_per_keyword, headless, session_quota=session_quota))
        _log(f"scrape_keywords returned, success={result.get('success')}, posts_count={len(result.get('posts', []))}")
        # Log filtering stats for debugging
        stats = result.get('stats', {})
        if stats:
            _log(f"STATS: scraped={stats.get('total_scraped',0)} accepted={stats.get('accepted',0)} dup={stats.get('rejected_duplicate',0)} non_fr={stats.get('rejected_non_french',0)} agency={stats.get('rejected_agency',0)} ext={stats.get('rejected_external',0)} jobseeker={stats.get('rejected_jobseeker',0)} contract={stats.get('rejected_contract_type',0)} no_legal={stats.get('rejected_no_legal',0)} no_signal={stats.get('rejected_no_signal',0)} old={stats.get('rejected_too_old',0)} other={stats.get('rejected_other',0)}")
    except Exception as e:
        import traceback
        _log(f"ERROR in asyncio.run: {e}\n{traceback.format_exc()}")
        result = {"success": False, "error": str(e), "posts": []}
    
    # Write output
    _log(f"about to write output to {output_file}")
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f)
        _log("output written successfully")
    else:
        print(json.dumps(result))
    
    _log("exiting")
    sys.exit(0 if result.get("success", False) else 1)
    
    # Write output
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f)
    else:
        print(json.dumps(result))
    
    sys.exit(0 if result.get("success", False) else 1)


if __name__ == "__main__":
    main()
