"""Scraping subprocess module.

This module runs Playwright scraping in a separate process to avoid
event loop conflicts with uvicorn/asyncio/pywebview in the main process.

Usage:
    Called via subprocess from worker.py when scraping needs to be isolated.
    Communicates via JSON over stdin/stdout.
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

# Global debug logging function
_DEBUG_LOG_PATH = None

def _init_debug_log():
    global _DEBUG_LOG_PATH
    localappdata = os.environ.get("LOCALAPPDATA", "")
    if localappdata:
        _DEBUG_LOG_PATH = Path(localappdata) / "TitanScraper" / "scrape_subprocess_debug.txt"
    else:
        _DEBUG_LOG_PATH = Path(".") / "scrape_subprocess_debug.txt"
    _DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

def _debug_log(msg: str):
    """Log message to debug file."""
    global _DEBUG_LOG_PATH
    if _DEBUG_LOG_PATH is None:
        _init_debug_log()
    try:
        with open(_DEBUG_LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(f"{msg}\n")
    except Exception:
        pass

# Initialize on import
_init_debug_log()


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
# TITAN PARTNERS FILTERING - Exclusion lists
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
# RATE LIMITING - Délais de sécurité pour éviter le blocage LinkedIn
# ============================================================
# Ces valeurs sont augmentées pour réduire les risques de détection
import random

# Délai après chargement de page (ms)
PAGE_LOAD_DELAY_MIN = 3000  # 3 secondes minimum
PAGE_LOAD_DELAY_MAX = 5000  # 5 secondes maximum

# Délai entre chaque scroll (ms)
SCROLL_DELAY_MIN = 1500   # 1.5 secondes minimum
SCROLL_DELAY_MAX = 3000   # 3 secondes maximum

# Délai entre chaque mot-clé recherché (ms)
KEYWORD_DELAY_MIN = 4000  # 4 secondes minimum
KEYWORD_DELAY_MAX = 8000  # 8 secondes maximum

# Nombre de scrolls par page (réduit pour moins de requêtes)
MAX_SCROLLS_PER_PAGE = 2

# Fonction utilitaire pour délai aléatoire
def random_delay(min_ms: int, max_ms: int) -> int:
    """Retourne un délai aléatoire entre min et max millisecondes."""
    return random.randint(min_ms, max_ms)
# ============================================================

# Selectors (duplicated from worker.py to keep subprocess self-contained)
POST_CONTAINER_SELECTORS = [
    "div.feed-shared-update-v2",
    "div.occludable-update",
    "div[data-urn*='urn:li:activity:']",
]

# Improved author selectors - try multiple patterns
# IMPORTANT: Order matters - most specific selectors first
AUTHOR_SELECTORS = [
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

TEXT_SELECTOR = "div.feed-shared-update-v2__description, div.update-components-text, span.break-words"

# Improved date selectors
DATE_SELECTORS = [
    "span.update-components-actor__sub-description time",
    "a.update-components-actor__sub-description-link time",
    "span.update-components-actor__sub-description span[aria-hidden='true']",
    "time.update-components-actor__sub-description",
    "span.feed-shared-actor__sub-description time",
    ".update-components-actor__sub-description",
]

# Company selectors - look for the company/title line
COMPANY_SELECTORS = [
    "span.update-components-actor__description",
    "span.feed-shared-actor__description", 
    "span.update-components-actor__second-line",
]

# Profile link selectors
PROFILE_LINK_SELECTORS = [
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
    
    # English-specific indicators
    en_indicators = [
        "the", "is", "are", "we", "our", "you", "your", "this", "that",
        "hiring", "looking", "seeking", "join", "team", "role", "position",
        "candidate", "apply", "opportunity", "company", "job",
    ]
    
    # Count occurrences
    fr_count = sum(1 for w in fr_indicators if f" {w} " in f" {text_lower} " or text_lower.startswith(f"{w} ") or text_lower.endswith(f" {w}"))
    en_count = sum(1 for w in en_indicators if f" {w} " in f" {text_lower} " or text_lower.startswith(f"{w} ") or text_lower.endswith(f" {w}"))
    
    # Determine language
    if fr_count >= 3 and fr_count > en_count:
        return "fr"
    elif en_count >= 3 and en_count > fr_count:
        return "en"
    elif fr_count >= 2:
        return "fr"
    elif en_count >= 2:
        return "en"
    
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
    
    # Reject if primarily English
    lang = detect_language(text, default="unknown")
    if lang == "en":
        return False
    
    # Also reject if unknown - be conservative
    if lang == "unknown":
        return False
    
    return lang == "fr"


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
    """
    author = post.get("author", "")
    author_profile = post.get("author_profile")
    company = post.get("company")
    text = post.get("text", "")
    published_at = post.get("published_at")
    
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
    
    # Wait for posts to load with randomized delay to appear more human
    await page.wait_for_timeout(random_delay(PAGE_LOAD_DELAY_MIN, PAGE_LOAD_DELAY_MAX))
    
    # Scroll to load more content (limited scrolls with random delays)
    for _ in range(MAX_SCROLLS_PER_PAGE):
        await page.evaluate("window.scrollBy(0, 800)")
        await page.wait_for_timeout(random_delay(SCROLL_DELAY_MIN, SCROLL_DELAY_MAX))
    
    # Find post elements
    elements = []
    for selector in POST_CONTAINER_SELECTORS:
        try:
            found = await page.query_selector_all(selector)
            if found:
                elements.extend(found)
        except Exception:
            continue
    
    for el in elements:
        if len(posts) >= max_items:
            break
        
        try:
            # Author - try multiple selectors
            # Use empty string instead of "Unknown" - leave blank if not found
            author = ""
            author_profile = None
            
            # First, try to get the profile link - this helps validate the author
            for link_sel in PROFILE_LINK_SELECTORS:
                try:
                    link_el = await el.query_selector(link_sel)
                    if link_el:
                        href = await link_el.get_attribute("href")
                        if href and "/in/" in href:
                            author_profile = href.split("?")[0]  # Remove query params
                            break
                        elif href and "/company/" in href:
                            # Company profile - extract company name from URL
                            import re
                            match = re.search(r'/company/([^/?]+)', href)
                            if match:
                                # Use company name as author for company posts
                                pass
                except Exception:
                    continue
            
            # Now try to extract author name
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
            
            # Text
            text = ""
            text_el = await el.query_selector(TEXT_SELECTOR)
            if text_el:
                text = normalize_whitespace(await text_el.inner_text())
            
            if not text or len(text) < 20:
                continue
            
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
                                break
                except Exception:
                    continue
            
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
                                break
                            else:
                                company = None
                except Exception:
                    continue
            
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
            
            # MANDATORY: Skip posts without a permalink
            # Every post must have a link to be useful
            if not permalink:
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
            
            posts.append({
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
            })
        
        except Exception as e:
            # Skip this element on error
            continue
    
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
    
    import re  # Import re at the top of function scope
    
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
    if not company or company.strip() == "":
        return False
    
    company_lower = company.lower().strip()
    
    # Reject if it's EXACTLY a job title (standalone)
    standalone_job_titles = [
        'notaire', 'avocat', 'avocate', 'juriste', 'magistrat', 'magistrate',
        'mandataire', 'consultant', 'consultante', 'recruteur', 'recruteuse',
        'manager', 'directeur', 'directrice', 'responsable', 'chef',
        'associate', 'counsel', 'paralegal', 'stagiaire', 'alternant',
        'senior', 'junior', 'notaire associé', 'notaire associée',
        'mandataire judiciaire', 'magistrate administrative',
        'talent acquisition', 'head of legal',
    ]
    
    # Only reject if the entire company name is exactly a job title
    if company_lower in standalone_job_titles:
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


async def scrape_keywords(keywords: list[str], storage_state: str, max_per_keyword: int = 10, headless: bool = True, apply_titan_filter: bool = True) -> dict:
    """Main scraping function - runs in isolated process."""
    from playwright.async_api import async_playwright
    
    results = {
        "success": True,
        "posts": [],
        "errors": [],
        "keywords_processed": 0,
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
            # Launch browser
            _debug_log(f"launching browser, headless={headless}")
            browser = await pw.chromium.launch(headless=headless)
            _debug_log("browser launched")
            
            # Create context with storage state
            context_opts = {}
            if storage_state and os.path.exists(storage_state):
                context_opts["storage_state"] = storage_state
                _debug_log(f"using storage_state from {storage_state}")
            else:
                _debug_log(f"WARNING: storage_state missing or not found: {storage_state}")
            
            context = await browser.new_context(**context_opts)
            page = await context.new_page()
            _debug_log("page created")
            
            # Navigate to feed first to check auth
            _debug_log("navigating to LinkedIn feed...")
            await page.goto("https://www.linkedin.com/feed/", timeout=30000)
            await page.wait_for_timeout(random_delay(PAGE_LOAD_DELAY_MIN, PAGE_LOAD_DELAY_MAX))
            _debug_log(f"page title: {await page.title()}")
            
            # Check if authenticated
            cookies = await context.cookies("https://www.linkedin.com")
            cookie_names = [c.get("name") for c in cookies]
            _debug_log(f"cookies found: {len(cookies)}, names: {cookie_names[:10]}")
            has_li_at = any(c.get("name") == "li_at" and c.get("value") for c in cookies)
            
            if not has_li_at:
                results["success"] = False
                results["errors"].append("Not authenticated - no li_at cookie")
                _debug_log("ERROR: Not authenticated - no li_at cookie found")
                await browser.close()
                return results
            
            _debug_log("authentication OK, starting keyword scraping")
            
            # Process each keyword
            for kw_idx, keyword in enumerate(keywords):
                _debug_log(f"Processing keyword {kw_idx+1}/{len(keywords)}: {keyword}")
                try:
                    search_url = f"https://www.linkedin.com/search/results/content/?keywords={keyword}"
                    _debug_log(f"navigating to search: {search_url[:80]}...")
                    await page.goto(search_url, timeout=30000)
                    _debug_log("search page loaded, waiting random delay...")
                    # Délai aléatoire entre les mots-clés pour paraître plus humain
                    await page.wait_for_timeout(random_delay(KEYWORD_DELAY_MIN, KEYWORD_DELAY_MAX))
                    
                    # Scrape more posts than needed to account for filtering
                    scrape_count = max_per_keyword * 3 if apply_titan_filter else max_per_keyword
                    _debug_log(f"calling extract_posts_simple with count={scrape_count}")
                    raw_posts = await extract_posts_simple(page, keyword, scrape_count)
                    _debug_log(f"extract_posts_simple returned {len(raw_posts)} posts")
                    results["stats"]["total_scraped"] += len(raw_posts)
                    
                    # Apply Titan Partners filtering if enabled
                    for post in raw_posts:
                        # Check for duplicates first
                        post_hash = get_post_hash(post)
                        if post_hash in seen_posts:
                            results["stats"]["rejected_duplicate"] += 1
                            continue
                        seen_posts.add(post_hash)
                        
                        # FILTRE LANGUE: Rejeter les posts non-français
                        # Titan Partners recherche uniquement des publications en France
                        if not is_french_post(post.get("text", "")):
                            results["stats"]["rejected_non_french"] += 1
                            continue
                        
                        if apply_titan_filter:
                            is_valid, reason = filter_post_titan_partners(post)
                            if is_valid:
                                results["posts"].append(post)
                                results["stats"]["accepted"] += 1
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
                        else:
                            results["posts"].append(post)
                            results["stats"]["accepted"] += 1
                    
                    results["keywords_processed"] += 1
                    
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
    
    # Set browsers path if provided
    browsers_path = input_data.get("browsers_path")
    if browsers_path:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = browsers_path
    _log(f"PLAYWRIGHT_BROWSERS_PATH={os.environ.get('PLAYWRIGHT_BROWSERS_PATH', 'NOT SET')}")
    
    # Run scraping
    try:
        _log("about to call asyncio.run(scrape_keywords())")
        result = asyncio.run(scrape_keywords(keywords, storage_state, max_per_keyword, headless))
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
