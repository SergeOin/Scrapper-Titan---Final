"""Utility functions for the LinkedIn scraping subsystem.

This module groups stateless helpers used by the worker:
- Random User-Agent generation (realistic desktop browsers)
- Jitter sleep (respect rate limiting heuristics)
- Language detection (graceful fallback)
- Text normalization & keyword density
- Scoring heuristic (combines several signals)
- Stable post identifier hashing
- Retry decorator wrapping Tenacity with standard config
- Lightweight date parsing (LinkedIn relative date patterns may later be mapped)

All functions are pure (no side effects) except for those doing async sleeps or
logging. They accept primitives / simple structures for easier testing.
"""
from __future__ import annotations

import asyncio
import hashlib
import math
import random
import re
import time
from datetime import datetime, timedelta, timezone
import unicodedata
from typing import Iterable, Callable, Awaitable, Any, Optional

try:
    from user_agents import parse as parse_ua  # type: ignore
except Exception:  # pragma: no cover
    def parse_ua(_ua: str):  # type: ignore
        """Fallback parser noop if user_agents not installed.

        Returns a minimal object with attributes referenced nowhere else; keeps interface harmless.
        """
        class _Dummy:  # noqa: D401
            browser = device = os = None
        return _Dummy()
try:
    from langdetect import detect  # type: ignore
except Exception:  # pragma: no cover
    detect = None  # type: ignore

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

# Local import kept light to avoid circular imports (only for Settings type hints)
try:  # pragma: no cover - type checking friendly
    from .bootstrap import Settings  # noqa: F401
except Exception:  # pragma: no cover
    Settings = Any  # type: ignore

# ---------------------------------------------------------------------------
# User-Agent generation
# ---------------------------------------------------------------------------
_DESKTOP_UA_TEMPLATES = [
    # Chrome (Win / Mac / Linux) variants
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.{build}.100 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/{safari_major}.1 Safari/605.1.15 Chrome/{major}.0.{build}.100",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.{build}.120 Safari/537.36",
]


def random_user_agent(seed: Optional[int] = None) -> str:
    """Return a pseudo-realistic desktop User-Agent string.

    Args:
        seed: Optional seed for deterministic output in tests.
    """
    rnd = random.Random(seed)
    template = rnd.choice(_DESKTOP_UA_TEMPLATES)
    major = rnd.randint(115, 125)
    build = rnd.randint(4000, 5900)
    safari_major = rnd.randint(16, 18)
    ua = template.format(major=major, build=build, safari_major=safari_major)
    # Quick validation (parse; not used but ensures plausible structure)
    try:
        parse_ua(ua)
    except Exception:  # pragma: no cover - parse should not fail
        pass
    return ua


# ---------------------------------------------------------------------------
# Sleep with jitter
# ---------------------------------------------------------------------------
async def jitter_sleep(min_ms: int, max_ms: int) -> float:
    """Async sleep for a random duration between bounds.

    Returns actual seconds slept (float) to allow instrumentation.
    """
    if max_ms < min_ms:
        max_ms = min_ms
    duration_ms = random.randint(min_ms, max_ms)
    seconds = duration_ms / 1000.0
    await asyncio.sleep(seconds)
    return seconds


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------
_LANG_REGEXP = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+")


def detect_language(text: str, default: str = "fr") -> str:
    """Detect language of the text with graceful fallback.

    - If langdetect not available or detection fails, returns default
    - If text too short / empty, returns default
    """
    cleaned = " ".join(_LANG_REGEXP.findall(text))
    if not cleaned or len(cleaned) < 4:
        return default
    if detect is None:  # library missing
        return default
    try:
        lang = detect(cleaned)
        if len(lang) == 2:
            return lang
    except Exception:  # pragma: no cover - depends on library behavior
        return default
    return default


# ---------------------------------------------------------------------------
# Text normalization & keyword density
# ---------------------------------------------------------------------------
_WS_RE = re.compile(r"\s+")


def normalize_whitespace(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def keyword_density(text: str, keywords: Iterable[str]) -> float:
    """Compute a naive keyword density (0..1)."""
    text_lc = text.lower()
    total_hits = 0
    total_len = max(len(text_lc), 1)
    for kw in keywords:
        kw = kw.strip().lower()
        if not kw:
            continue
        total_hits += text_lc.count(kw)
    # scale by log to reduce huge bias for repeated words
    score = min(1.0, math.log1p(total_hits) / math.log1p(total_len / 15))
    return max(0.0, score)


# ---------------------------------------------------------------------------
# Scoring heuristic
# ---------------------------------------------------------------------------

def compute_score(
    *,
    text: str,
    language: str,
    expected_lang: str,
    has_media: bool,
    keywords: list[str],
    settings,
) -> float:
    """Compute a relevance score combining several weighted factors.

    Formula (simplified):
        length_norm * W_length + media * W_media + kw_density * W_kw + lang_match * W_lang
    Clamped into [0, 1].
    """
    length_norm = min(1.0, len(text) / 800)  # saturates at ~800 chars
    lang_match = 1.0 if language == expected_lang else 0.0
    kw_density = keyword_density(text, keywords)
    media_val = 1.0 if has_media else 0.0

    raw = (
        length_norm * settings.weight_length
        + media_val * settings.weight_media
        + kw_density * settings.weight_keyword_density
        + lang_match * settings.weight_lang_match
    )
    return max(0.0, min(1.0, raw))


# ---------------------------------------------------------------------------
# Stable post identifier
# ---------------------------------------------------------------------------

def make_post_id(*parts: str) -> str:
    """Return a deterministic hash ID from provided parts.

    Any None/empty parts are ignored; uses SHA256 truncated to 16 hex chars.
    """
    filtered = [p for p in parts if p]
    blob = "||".join(filtered).encode("utf-8", errors="ignore")
    return hashlib.sha256(blob).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Retry helper (wrapping Tenacity)
# ---------------------------------------------------------------------------
class TransientScrapeError(Exception):
    """An error type that indicates a retryable transient failure."""


def retryable(*exc_types: type[BaseException]):
    """Decorator factory for retry logic with exponential backoff + jitter.

    Example:
        @retryable(TimeoutError, TransientScrapeError)
        async def fragile(): ...
    """
    if not exc_types:
        exc_types = (Exception,)  # type: ignore

    def _decorator(fn: Callable[..., Awaitable[Any]]):
        return retry(
            reraise=True,
            stop=stop_after_attempt(4),
            wait=wait_exponential_jitter(multiplier=0.4, max=6),
            retry=retry_if_exception_type(exc_types),
        )(fn)

    return _decorator


# ---------------------------------------------------------------------------
# Lightweight date parsing - OPTIMISÉ pour LinkedIn
# ---------------------------------------------------------------------------
# Mapping de fragments courants vers des minutes
_RELATIVE_MAP = {
    "1 h": 60,
    "1h": 60,
    "1 j": 1440,
    "1j": 1440,
}

# Maximum age for posts in days (3 weeks = 21 days) - STRICTEMENT APPLIQUÉ
MAX_POST_AGE_DAYS = 21

# Pattern étendu pour capturer toutes les unités de temps LinkedIn (FR et EN)
# IMPORTANT: Ordre des alternatives compte - les plus longs d'abord pour éviter
# que "sem" soit capturé comme "s" (secondes)
# IMPORTANT: LinkedIn utilise "sem." (avec point abréviatif) donc on ajoute \.? après sem
# NOUVEAU: Support des formats avec "il y a", "ago", etc.
_RELATIVE_PATTERN_EXTENDED = re.compile(
    r"(?:il\s+y\s+a\s+)?(\d+)\s*(semaines?|seconde?s?|minutes?|heures?|jours?|weeks?|months?|mois|ans?|years?|sem\.?|min\.?|sec\.?|day|wk|hr|mo|yr|h|j|d|w|s|m)(?:\s+ago)?",
    re.IGNORECASE
)


def is_post_too_old(published_at: str | datetime | None, max_age_days: int = MAX_POST_AGE_DAYS) -> bool:
    """Return True if the post is older than max_age_days (default 3 weeks).
    
    Args:
        published_at: ISO datetime string or datetime object
        max_age_days: Maximum age in days (default 21 = 3 weeks)
    
    Returns:
        True if post is too old and should be filtered out.
        False if post is recent enough.
    
    CRITIQUE: Cette fonction est STRICTE - un post sans date valide est REJETÉ
    pour garantir la fraîcheur des données collectées.
    """
    if not published_at:
        # CRITIQUE: Rejeter les posts sans date pour garantir la fraîcheur
        return True
    
    now = datetime.now(timezone.utc)
    max_age = timedelta(days=max_age_days)
    
    try:
        pub_date: Optional[datetime] = None
        
        if isinstance(published_at, datetime):
            pub_date = published_at
        elif isinstance(published_at, str):
            # Nettoyer la chaîne d'entrée
            clean_str = published_at.strip()
            if not clean_str:
                return True
            
            # Essayer d'abord le format ISO standard
            try:
                pub_date = datetime.fromisoformat(clean_str.replace('Z', '+00:00'))
            except ValueError:
                # Sinon, essayer de parser comme date relative LinkedIn
                pub_date = parse_possible_date(clean_str, now)
        
        if pub_date is None:
            # CRITIQUE: Rejeter si on ne peut pas déterminer la date
            return True
        
        # Ensure timezone aware
        if pub_date.tzinfo is None:
            pub_date = pub_date.replace(tzinfo=timezone.utc)
        
        age = now - pub_date
        
        # Log pour diagnostic (en mode debug seulement)
        # print(f"DEBUG: Post age = {age.days} days, max = {max_age_days}, reject = {age > max_age}")
        
        return age > max_age
    except Exception:
        # CRITIQUE: Rejeter en cas d'erreur de parsing (sécurité)
        return True

# Pattern simple pour compatibilité arrière (déprécié, utiliser _RELATIVE_PATTERN_EXTENDED)
_RELATIVE_PATTERN = re.compile(r"(\d+)\s*(s|min|h|j)")


def parse_possible_date(raw: str, now: Optional[datetime] = None) -> Optional[datetime]:
    """Parse relative LinkedIn-like timestamps into datetime.

    OPTIMISÉ v3: Supporte tous les formats LinkedIn FR et EN:
        '5 min'   => now - 5 minutes
        '2 h'     => now - 2 hours  
        '1 j'     => now - 1 day
        '3 j'     => now - 3 days
        '2 sem'   => now - 2 weeks (CRITIQUE pour filtre 3 semaines)
        '2 sem.'  => now - 2 weeks (avec point)
        '1 w'     => now - 1 week
        '2 wk'    => now - 2 weeks
        '1 mo'    => now - 1 month
        '2 mois'  => now - 2 months
        '1 an'    => now - 1 year (REJETÉ automatiquement par is_post_too_old)
        'il y a 2 semaines' => now - 2 weeks
        '3 weeks ago' => now - 3 weeks

    Returns timezone-aware UTC datetime or None if not parsed.
    """
    if not raw:
        return None
    
    # Nettoyer le texte: retirer •, Modifié, etc.
    raw_clean = raw.strip().lower()
    raw_clean = raw_clean.replace("•", " ").replace("·", " ")
    raw_clean = raw_clean.replace("modifié", "").replace("modified", "")
    raw_clean = raw_clean.replace("édité", "").replace("edited", "")
    raw_clean = re.sub(r"\s+", " ", raw_clean).strip()
    
    if not raw_clean:
        return None
    
    now = now or datetime.now(timezone.utc)

    # Utiliser le pattern étendu pour capturer toutes les unités
    m = _RELATIVE_PATTERN_EXTENDED.search(raw_clean)
    if m:
        value = int(m.group(1))
        unit = m.group(2).lower().rstrip('.')  # Retirer le point abréviatif si présent
        delta: timedelta
        
        # Secondes
        if unit in ("s", "sec", "seconde", "secondes"):
            delta = timedelta(seconds=value)
        # Minutes
        elif unit in ("min", "minute", "minutes", "m"):
            # Attention: "m" peut être mois en anglais, mais LinkedIn utilise "mo"
            # Donc "m" seul = minutes
            delta = timedelta(minutes=value)
        # Heures
        elif unit in ("h", "hr", "heure", "heures"):
            delta = timedelta(hours=value)
        # Jours
        elif unit in ("j", "d", "day", "days", "jour", "jours"):
            delta = timedelta(days=value)
        # Semaines (CRITIQUE pour le filtre 3 semaines)
        elif unit in ("sem", "semaine", "semaines", "w", "wk", "week", "weeks"):
            delta = timedelta(weeks=value)
        # Mois (approximation 30 jours)
        elif unit in ("mo", "mois", "month", "months"):
            delta = timedelta(days=value * 30)
        # Années (approximation 365 jours - ces posts seront rejetés)
        elif unit in ("an", "ans", "yr", "year", "years"):
            delta = timedelta(days=value * 365)
        else:
            return None
        
        return now - delta

    # Fallback: fragments explicites dans le mapping
    for frag, minutes in _RELATIVE_MAP.items():
        if frag in raw_clean:
            return now - timedelta(minutes=minutes)
    
    # Dernière tentative: détecter des patterns textuels courants
    # "il y a 2 semaines", "posted 3 weeks ago", etc.
    week_patterns = [
        (r"il y a (\d+)\s*semaine", "week"),
        (r"(\d+)\s*semaine", "week"),
        (r"(\d+)\s*weeks?\s*ago", "week"),
        (r"il y a (\d+)\s*mois", "month"),
        (r"(\d+)\s*months?\s*ago", "month"),
        (r"il y a (\d+)\s*jour", "day"),
        (r"(\d+)\s*days?\s*ago", "day"),
        (r"(\d+)\s*ans?", "year"),
        (r"(\d+)\s*years?\s*ago", "year"),
    ]
    
    for pattern, unit_type in week_patterns:
        match = re.search(pattern, raw_clean, re.IGNORECASE)
        if match:
            val = int(match.group(1))
            if unit_type == "week":
                return now - timedelta(weeks=val)
            elif unit_type == "month":
                return now - timedelta(days=val * 30)
            elif unit_type == "day":
                return now - timedelta(days=val)
            elif unit_type == "year":
                return now - timedelta(days=val * 365)

    return None


# ---------------------------------------------------------------------------
# Utility for timing blocks (context manager)
# ---------------------------------------------------------------------------
class Timer:
    """Simple async-compatible timer context for performance metrics."""

    def __init__(self) -> None:
        self._start: float | None = None
        self.elapsed: float | None = None

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc_info):
        if self._start is not None:
            self.elapsed = time.perf_counter() - self._start
        return False


# ---------------------------------------------------------------------------
# France location filter - OPTIMISÉ v3 avec liste complète
# ---------------------------------------------------------------------------
FRANCE_POSITIVE_MARKERS = [
    # Termes généraux France
    "france", "french", "français", "francais", "française", "francaise",
    "hexagone", "sur le territoire", "en france",
    # Île-de-France et Paris (exhaustif)
    "paris", "parisien", "parisienne", "idf", "ile-de-france", "île-de-france",
    "la défense", "la defense", "neuilly", "puteaux", "levallois",
    "boulogne-billancourt", "versailles", "saint-denis", "nanterre",
    "courbevoie", "issy-les-moulineaux", "cergy", "evry", "évry",
    "creteil", "créteil", "bobigny", "montreuil", "vincennes",
    "rueil", "rueil-malmaison", "suresnes", "colombes",
    "asnieres", "asnières", "clamart", "meudon", "sevres", "sèvres",
    "saint-germain", "le vesinet", "maisons-laffitte",
    "paris 1", "paris 2", "paris 3", "paris 4", "paris 5",
    "paris 6", "paris 7", "paris 8", "paris 9", "paris 10",
    "paris 11", "paris 12", "paris 13", "paris 14", "paris 15",
    "paris 16", "paris 17", "paris 18", "paris 19", "paris 20",
    # Grandes métropoles
    "lyon", "marseille", "bordeaux", "lille", "toulouse", "nice", "nantes",
    "rennes", "strasbourg", "grenoble", "montpellier", "tours", "nancy",
    "rouen", "reims", "clermont", "toulon", "dijon", "angers", "metz",
    # Villes moyennes importantes
    "aix-en-provence", "aix en provence", "brest", "limoges", "nîmes", "nimes", "amiens",
    "perpignan", "orléans", "orleans", "mulhouse", "caen", "besançon", "besancon",
    "saint-etienne", "saint etienne", "le havre", "avignon", "pau", "poitiers", "bayonne",
    "la rochelle", "chambery", "chambéry", "annecy", "valence", "troyes",
    "lorient", "quimper", "vannes", "saint-nazaire", "cholet", "niort",
    "chartres", "laval", "colmar", "bourges", "cherbourg", "calais",
    # Régions administratives
    "normandie", "bretagne", "occitanie", "paca", "auvergne", "rhône-alpes", "rhone-alpes",
    "nouvelle-aquitaine", "nouvelle aquitaine", "grand-est", "grand est", 
    "hauts-de-france", "hauts de france", "centre-val", "centre val de loire",
    "pays de la loire", "bourgogne", "franche-comté", "franche comte",
    "alsace", "lorraine", "picardie", "champagne",
    # Départements (codes)
    "75", "77", "78", "91", "92", "93", "94", "95",
    "69", "13", "31", "33", "59", "06", "44", "67",
    # Expressions de localisation
    "basé à paris", "base a paris", "poste à paris", "poste a paris",
    "bureau de paris", "bureau de lyon", "agence de paris",
    "localisation paris", "localisation lyon", "localisation france",
]

FRANCE_NEGATIVE_MARKERS = [
    # Amérique du Nord
    "canada", "usa", "united states", "etats-unis", "états-unis", "american",
    "montreal", "montréal", "toronto", "vancouver", "ottawa", "quebec", "québec",
    "new york", "san francisco", "california", "californie",
    "los angeles", "chicago", "boston", "washington", "miami", "seattle",
    "texas", "florida", "floride",
    # Belgique
    "belgium", "belgique", "belge", "bruxelles", "brussels", "anvers",
    "antwerp", "gent", "gand", "liege", "liège", "charleroi",
    # Suisse
    "switzerland", "swiss", "suisse", "genève", "geneve", "geneva",
    "zurich", "zürich", "lausanne", "berne", "bern", "basel", "bâle",
    "canton de", "zürichsee",
    # Autres pays francophones
    "luxembourg", "luxembourgeois", "monaco",
    # UK
    "uk ", "u.k.", "united kingdom", "royaume-uni", "british", "britannique",
    "london", "londres", "manchester", "birmingham", "edinburgh", "édimbourg",
    "liverpool", "leeds", "glasgow", "bristol", "cardiff",
    # Allemagne
    "germany", "allemagne", "deutschland", "german", "allemand",
    "berlin", "munich", "münchen", "frankfurt", "francfort",
    "hamburg", "hambourg", "düsseldorf", "dusseldorf", "cologne", "köln",
    "stuttgart", "hannover", "hanovre",
    # Autres pays européens
    "spain", "espagne", "españa", "spanish", "espagnol", "madrid", "barcelona", "barcelone",
    "portugal", "portugais", "lisbonne", "lisbon", "lisboa", "porto",
    "italy", "italie", "italia", "italian", "italien", "milan", "milano", "rome", "roma", "turin", "florence",
    "netherlands", "pays-bas", "holland", "hollande", "dutch", "amsterdam", "rotterdam", "la haye",
    "ireland", "irlande", "irish", "irlandais", "dublin",
    "poland", "pologne", "warsaw", "varsovie", "cracovie",
    "austria", "autriche", "vienna", "vienne",
    "sweden", "suède", "stockholm", "denmark", "danemark", "copenhagen", "copenhague",
    # Asie/Moyen-Orient
    "singapore", "singapour", "hong kong", "shanghai", "tokyo", "beijing", "pékin",
    "dubai", "dubaï", "émirats", "emirats", "abu dhabi", "qatar", "doha",
    "saudi", "arabie", "israel", "israël", "tel aviv",
    # Océanie
    "australia", "australie", "australian", "australien", "sydney", "melbourne", "brisbane",
    "new zealand", "nouvelle-zélande", "auckland",
    # Afrique
    "maroc", "morocco", "marocain", "casablanca", "rabat",
    "tunisie", "tunisia", "tunis",
    "alger", "algerie", "algérie", "algeria",
    "sénégal", "senegal", "dakar",
    "cote d ivoire", "côte d'ivoire", "abidjan",
    # Expressions de remote non-FR
    "remote us", "remote usa", "remote uk", "remote canada",
    "hiring in uk", "hiring in us", "hiring globally",
    "remote global", "worldwide", "international remote",
    "work from anywhere", "travail à distance international",
]


def is_location_france(text: str | None, strict: bool = True) -> bool:
    """Check if the post location is likely France.
    
    Args:
        text: Post text content
        strict: If True, requires positive France marker when negative markers present
    
    Returns:
        True if location appears to be France, False otherwise.
    
    LOGIQUE:
    - Si aucun marqueur de localisation: ACCEPTER (assume France par défaut)
    - Si marqueur France présent: ACCEPTER
    - Si marqueur étranger présent SANS marqueur France: REJETER (en mode strict)
    - Si les deux sont présents: ACCEPTER (le post mentionne France + autre pays)
    """
    if not text:
        return True  # No location info, assume France OK
    
    low = text.lower()
    
    # Compter les marqueurs trouvés
    positive_matches = [marker for marker in FRANCE_POSITIVE_MARKERS if marker in low]
    negative_matches = [marker for marker in FRANCE_NEGATIVE_MARKERS if marker in low]
    
    has_positive = len(positive_matches) > 0
    has_negative = len(negative_matches) > 0
    
    # Si aucun marqueur géographique: assume France (posts sans localisation explicite)
    if not has_positive and not has_negative:
        return True
    
    if strict:
        # Mode strict: si pays étranger mentionné, exiger une mention France aussi
        if has_negative:
            # Exception: si le post mentionne "France" et un autre pays, accepter
            # (ex: "Cabinet à Paris avec bureaux à Londres" = OK)
            return has_positive
        # Pas de pays étranger = assume France
        return True
    else:
        # Mode non-strict: accept si France mentionné OU si pas d'étranger
        return has_positive or not has_negative


__all__ = [
    "random_user_agent",
    "jitter_sleep",
    "detect_language",
    "normalize_whitespace",
    "normalize_for_search",
    "build_search_norm",
    "keyword_density",
    "compute_score",
    "compute_recruitment_signal",
    "is_promotional_content",
    "PROMOTIONAL_CONTENT_KEYWORDS",
    "is_opportunity",
    "make_post_id",
    "retryable",
    "TransientScrapeError",
    "parse_possible_date",
    "Timer",
    "is_stage_or_alternance",
    "is_post_too_old",
    "is_location_france",
    "STAGE_ALTERNANCE_KEYWORDS",
    "MAX_POST_AGE_DAYS",
    "FRANCE_POSITIVE_MARKERS",
    "FRANCE_NEGATIVE_MARKERS",
]

# ---------------------------------------------------------------------------
# Recruitment signal scoring - OPTIMISÉ avec plus de tokens
# ---------------------------------------------------------------------------
_RECRUIT_TOKENS = [
    # Tokens principaux
    "recrut",  # recrutement / recrute / recrutons
    "offre",
    "poste",
    "opportunité",
    "opportunite",
    "hiring",
    "job",
    # Expressions de recherche
    "nous cherchons",
    "on recherche",
    "rejoignez",
    "join the team",
    "join our team",
    "embauche",
    # Contrats (hors stage/alternance)
    "cdi",
    "cdd",
    "mission",
    # Expressions complètes
    "nous recherchons",
    "je recrute",
    "je recherche",
    # NOUVEAUX TOKENS pour augmenter la couverture
    "candidat",
    "profil recherché",
    "postulez",
    "envoyez cv",
    "intégrer",
    "renforcer",
    "équipe juridique",
    "création de poste",
]

# ---------------------------------------------------------------------------
# Stage/Alternance exclusion keywords - RENFORCÉ avec variantes complètes
# ---------------------------------------------------------------------------
STAGE_ALTERNANCE_KEYWORDS = [
    # Stage (variantes)
    "stage", "stages", "stagiaire", "stagiaires",
    "stage juridique", "stage avocat", "stage notaire",
    "offre de stage", "stage pfe", "stage fin d'études",
    "stage de fin", "stage m1", "stage m2", "stage l3",
    "stage 6 mois", "stage 3 mois", "stage 4 mois",
    "recherche stage", "propose un stage", "proposons un stage",
    "accueillir un stagiaire", "accueillir une stagiaire",
    "recrute un stagiaire", "recrute une stagiaire",
    "recrutons un stagiaire", "recrutons une stagiaire",
    # Alternance (variantes)
    "alternance", "alternant", "alternante", "alternants",
    "contrat alternance", "en alternance", "poste alternance",
    "poste en alternance", "offre alternance", "offre d'alternance",
    "recrute en alternance", "recrutons en alternance",
    "recherche alternance", "cherche alternance",
    "profil alternant", "profil alternance",
    "contrat en alternance", "formation en alternance",
    "master en alternance", "licence en alternance",
    # Apprentissage (variantes)
    "apprentissage", "apprenti", "apprentie", "apprentis",
    "contrat d'apprentissage", "contrat apprentissage",
    "recrute un apprenti", "recrute une apprentie",
    "recherche apprenti", "offre apprentissage",
    # Contrat pro
    "contrat pro", "contrat de professionnalisation",
    # Termes anglais
    "work-study", "internship", "intern ",  # espace après intern pour éviter "internal"
    "interns", "trainee", "traineeship", "working student",
    # V.I.E.
    "v.i.e", "vie ", "volontariat international",
    # Patterns spécifiques
    "#stage", "#alternance", "#apprentissage", "#stagiaire", "#alternant",
]


def is_stage_or_alternance(text: str | None) -> bool:
    """Return True if text contains stage/alternance/apprentissage keywords.
    
    These posts should be excluded from collection.
    """
    if not text:
        return False
    low = text.lower()
    for kw in STAGE_ALTERNANCE_KEYWORDS:
        if kw in low:
            return True
    return False


# ---------------------------------------------------------------------------
# Exclusion des cabinets de recrutement (concurrents)
# ---------------------------------------------------------------------------
RECRUITMENT_AGENCY_KEYWORDS = [
    # Termes génériques
    "cabinet de recrutement", "cabinet recrutement", "agence de recrutement",
    "chasseur de têtes", "chasseurs de têtes", "headhunter", "headhunting",
    "executive search", "talent acquisition agency", "talent acquisition",
    "rh externalisé", "rh externe", "externalisation rh",
    # Formulations typiques des recruteurs (variations apostrophes et possessifs)
    "notre client recherche", "pour le compte de notre client",
    "pour notre client", "notre client, un", "client final",
    "mission pour", "nous recrutons pour", "mandat de recrutement",
    "pour un de nos clients", "pour un de mes clients",
    "l'un de nos clients", "l'un de mes clients",
    "un de mes clients", "un de nos clients",
    "client confidentiel", "recrute pour un client",
    "je recrute pour", "recrute pour l'un",
    # Cabinets connus (FR) - Legal/Juridique
    "fed legal", "fed juridique", "fed group",
    "michael page", "michael page legal", "page personnel",
    "robert half", "robert half legal",
    "hays", "hays legal", "hays france",
    "lincoln associates", "laurence simons", "taylor root",
    "austin bright", "edge executive", "veni consulting",
    "altea consulting", "abries rh", "llg executive", "llg search",
    "co-efficience", "coefficience", "andrea partners",
    "jo&co recrutement", "laboure recrutement", "laboure avocats",
    "approach people", "major hunter", "approachpeople", "majorhunter",
    "morgan philips", "spencer stuart", "russell reynolds", "egon zehnder",
    "korn ferry", "boyden", "eric salmon", "odgers berndtson",
    "heidrick & struggles", "vidal associates",
    # Cabinets généraux
    "expectra", "adecco", "manpower", "randstad",
    "spring professional", "kelly services", "synergie", "proman",
    "start people", "crit interim", "supplay", "actual group",
    # Job boards / intermédiaires
    "indeed", "monster", "cadremploi", "apec.fr", "keljob", "jobteaser",
    "welcometothejungle", "meteojob", "regionsjob", "hellowork",
    # Expressions révélatrices
    "consultant recrutement", "consultante recrutement", "recruiter",
    "chargé de recrutement", "chargée de recrutement",
    "talent manager", "talent partner", "talent specialist",
    "nous recherchons pour l'un de nos clients",
    "notre cabinet recrute", "en cabinet de recrutement",
]


# ---------------------------------------------------------------------------
# Posts promotionnels/informationnels à exclure (pas de recrutement)
# ---------------------------------------------------------------------------
PROMOTIONAL_CONTENT_KEYWORDS = [
    # Événements
    "webinaire", "webinar", "conférence", "conference", "salon", "forum",
    "événement", "evenement", "event", "séminaire", "seminaire",
    "inscrivez-vous", "inscrivez vous", "inscription gratuite",
    "replay disponible", "en replay", "live demain", "en direct",
    # Formation/Cours
    "formation", "masterclass", "atelier", "workshop",
    "cours de", "apprendre à", "certifiante", "certification",
    # Publications/Articles
    "nouvel article", "mon article", "article de blog", "article publié",
    "nouvelle publication", "ma publication", "lire l'article",
    "interview de", "interview avec", "podcast", "épisode",
    "livre", "ouvrage", "parution", "vient de paraître",
    # Célébrations/Annonces personnelles
    "félicitations", "felicitations", "bravo", "fier de", "fière de",
    "anniversaire", "promotion de", "nommé", "nommée",
    "nouvelle aventure", "nouveau chapitre", "nouvelle étape",
    "heureux d'annoncer", "heureuse d'annoncer",
    "j'ai le plaisir", "j'ai l'honneur",
    # Self-promo services
    "nos services", "notre cabinet propose", "nous accompagnons",
    "besoin d'un avocat", "besoin d'accompagnement",
    "consultation gratuite", "premier rendez-vous offert",
    "contactez-nous", "contactez nous", "découvrez nos",
    # Actualités juridiques (pas recrutement)
    "nouvelle loi", "réforme", "jurisprudence", "décision de",
    "arrêt de la cour", "ce qu'il faut savoir", "décryptage",
    "point sur", "analyse de",
]


def is_promotional_content(text: str | None) -> bool:
    """Return True if post is promotional/informational rather than recruitment.
    
    These posts should be excluded as they don't offer jobs.
    """
    if not text:
        return False
    low = text.lower()
    
    # Must NOT contain recruitment phrases to be excluded
    recruit_signals = [
        "recrute", "recrutons", "poste à pourvoir", "offre d'emploi",
        "cdi", "cdd", "nous recherchons un", "recherche un(e)"
    ]
    has_recruit = any(sig in low for sig in recruit_signals)
    if has_recruit:
        return False  # Has recruitment signal, don't exclude
    
    # Check promotional content
    for kw in PROMOTIONAL_CONTENT_KEYWORDS:
        if kw in low:
            return True
    return False


def is_from_recruitment_agency(text: str | None, author: str | None = None) -> bool:
    """Return True if post appears to come from a recruitment agency.
    
    These posts should be excluded as they are competitors.
    """
    if not text and not author:
        return False
    
    # Check text content
    if text:
        low = text.lower()
        for kw in RECRUITMENT_AGENCY_KEYWORDS:
            if kw in low:
                return True
        
        # Additional pattern: "Je recrute" + "pour un/le cabinet" = external recruiter
        if "je recrute" in low and ("pour un cabinet" in low or "pour le cabinet" in low or "pour le bureau" in low):
            return True
        
        # Recruitment platform keywords
        recruitment_platform_markers = [
            "recrutement juridique", "legaltech", "legal tech",
            "plateforme de recrutement", "site de recrutement",
            "#recrutementjuridique",
        ]
        for marker in recruitment_platform_markers:
            if marker in low:
                return True
    
    # Check author name
    if author:
        author_low = author.lower()
        agency_author_markers = [
            "michael page", "robert half", "hays", "fed legal",
            "page personnel", "expectra", "adecco", "manpower", "randstad",
            "recruteur", "recruteuse", "recruitment", "headhunter", "talent acquisition",
            "lawpic", "legaltech", "jobboard", "job board",
        ]
        for marker in agency_author_markers:
            if marker in author_low:
                return True
    
    return False


_MULTI_TOKEN_PRIORITY = {"nous recherchons": 2.2, "je recrute": 2.0, "je recherche": 1.6}


def compute_recruitment_signal(text: str) -> float:
    """Return a heuristic recruitment intent score in ~[0,1]."""
    if not text:
        return 0.0
    low = text.lower()
    raw = 0.0
    for tok in _RECRUIT_TOKENS:
        cnt = low.count(tok)
        if cnt:
            raw += cnt * _MULTI_TOKEN_PRIORITY.get(tok, 1.0)
    norm = raw / (len(low) / 60.0 + 1.0)
    score = min(1.0, math.log1p(norm) / math.log1p(10))
    return max(0.0, score)


def is_opportunity(text: str | None, *, threshold: float = 0.05) -> bool:
    """Unified opportunity / recruitment signal predicate.

    A post is considered an "opportunity" if its recruitment signal score
    (compute_recruitment_signal) is above the configured threshold OR it contains
    high-salience imperative phrases frequently used in hiring posts.

    Centralising this logic prevents divergence between auto-favorite, UI badges
    and API summarisation.
    """
    if not text:
        return False
    score = compute_recruitment_signal(text)
    if score >= threshold:
        return True
    low = text.lower()
    phrase_hits = [
        # existants
        "nous recrutons", "on recrute", "je recrute", "recrutement en cours",
        "poste a pourvoir", "poste à pourvoir", "apply now", "we are hiring",
        "we're hiring", "join our team", "envoyez votre cv", "postulez",
        # nouveaux
        "hiring", "on recherche un juriste", "nous cherchons", "join the team",
        "rejoignez la direction juridique",
    ]
    return any(p in low for p in phrase_hits)


# ---------------------------------------------------------------------------
# Normalization helpers for accent-insensitive search
# ---------------------------------------------------------------------------
def normalize_for_search(s: str | None) -> str:
    """Lowercase and strip accents/diacritics for accent-insensitive search.

    Returns an ASCII-ish string (but keeps non-letter chars except diacritics).
    """
    if not s:
        return ""
    s = s.lower().strip()
    # NFD decomposition, drop non-spacing marks (Mn)
    nfd = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in nfd if unicodedata.category(ch) != "Mn").strip()


def build_search_norm(*parts: str | None) -> str:
    """Build a normalized search blob from multiple fields (text, author, company, keyword).

    Joins normalized parts with spaces and trims size to a safe length.
    """
    normed = [normalize_for_search(p) for p in parts if p]
    blob = " ".join(filter(None, normed))
    # clamp to avoid extreme size
    return blob[:4000]
