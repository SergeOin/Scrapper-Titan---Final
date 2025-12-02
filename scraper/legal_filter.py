"""Legal job post filtering module.

This module provides a comprehensive filtering system to identify relevant
legal recruitment posts on LinkedIn and exclude off-target content.

Main function: is_legal_job_post(text, post_date=None) -> FilterResult

Design principles:
- Immediate exclusion if ANY negative keyword is detected
- Scoring system: recruitment signal >= 0.15 + legal job >= 0.2
- Text normalization: lowercase, no accents, no hashtags, no emojis
- Detailed logging explaining why each post is excluded
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple
import logging

# Configure module logger
logger = logging.getLogger(__name__)

# =============================================================================
# LEGAL PROFESSION KEYWORDS (Score >= 0.2 required)
# =============================================================================
LEGAL_PROFESSIONS = [
    # Avocats (toutes déclinaisons)
    "avocat", "avocate", "avocats", "avocates",
    "avocat collaborateur", "avocate collaboratrice",
    "avocat associe", "avocate associee", "avocat counsel", "avocate counsel",
    "collaborateur", "collaboratrice", "associe", "associee", "counsel",
    # Juristes (toutes spécialités)
    "juriste", "juristes", "juriste entreprise", "juriste corporate",
    "juriste droit social", "juriste droit des affaires", "juriste contrats",
    "juriste contentieux", "juriste conformite", "juriste compliance",
    "juriste junior", "juriste senior", "juriste confirme",
    "juriste recouvrement", "juriste legal ops", "juriste generaliste",
    "juriste droit public", "juriste droit prive",
    # Direction juridique
    "responsable juridique", "directeur juridique", "directrice juridique",
    "head of legal", "chief legal officer", "general counsel",
    "legal counsel", "senior legal counsel", "legal manager",
    "head of legal compliance", "legal compliance",
    # Support juridique
    "paralegal", "paralegale", "assistant juridique", "assistante juridique",
    # Notariat
    "notaire", "notaires", "notaire associe", "notaire salarie",
    "clerc de notaire", "clerc principal", "redacteur actes",
    "ingenieur patrimonial",
    # Fiscalistes
    "fiscaliste", "fiscalistes", "juriste fiscal",
    # Cabinet/Étude (contexte juridique)
    "cabinet avocat", "cabinet d avocat", "cabinet avocats",
    "law firm", "etude notariale",
]

# Stems for flexible matching (more flexible)
LEGAL_STEMS = ["avocat", "juriste", "notaire", "paralegal", "counsel", "legal", "juridique", "fiscaliste"]

# =============================================================================
# RECRUITMENT SIGNALS (Score >= 0.15 required)
# =============================================================================
RECRUITMENT_SIGNALS = [
    # === SIGNAUX FORTS DE RECRUTEMENT ACTIF (entreprise qui recrute) ===
    # Formulations entreprise/employeur explicites
    "nous recrutons", "on recrute", "notre equipe recrute",
    "nous recherchons", "on recherche", "notre cabinet recherche",
    "notre direction juridique recherche", "notre etude recherche",
    # Postes à pourvoir (signal très fort)
    "poste a pourvoir", "poste ouvert", "poste disponible",
    "cdi a pourvoir", "cdd a pourvoir", "opportunite a saisir",
    "creation de poste", "nouveau poste", "ouverture de poste",
    # Appels à candidature explicites
    "postulez", "candidatez", "envoyez cv", "envoyez votre cv",
    "candidature a", "pour postuler", "comment postuler",
    "adressez votre candidature", "merci d envoyer",
    # Descriptions de poste (signaux moyens)
    "profil recherche", "missions principales", "rattache a",
    "experience requise", "vous justifiez", "vous disposez",
    "nous offrons", "nous proposons", "package attractif",
    "remuneration attractive", "selon profil",
    # Termes contractuels (contexte emploi)
    "cdi", "cdd", "temps plein", "full time", "temps complet",
    # Anglais entreprise
    "we are hiring", "we're hiring", "we re hiring",
    "is hiring", "now hiring", "currently hiring",
    "looking for", "is looking for", "we are looking for",
    "join our team", "join the team",
    
    # === SIGNAUX SPÉCIFIQUES JURIDIQUE ===
    "cabinet recrute", "cabinet recherche", "cabinet avocat recrute",
    "direction juridique recrute", "equipe juridique recrute",
    "etude notariale recrute", "etude recrute",
    "renforcer equipe juridique", "integrer equipe juridique",
    # Variations avec termes juridiques
    "recrute un juriste", "recrute une juriste",
    "recrute un avocat", "recrute une avocate",
    "recherche un juriste", "recherche une juriste",
    "recherche un avocat", "recherche une avocate",
    "recherche son futur juriste", "recherche sa future juriste",
    "recherche son futur avocat", "recherche sa future avocate",
    
    # === PATTERNS EMPHASE (souvent utilisés par recruteurs) ===
    "recrute !", "recrute!", "urgent", "asap",
    "offre du jour", "offre de recrutement",
    "ca recrute", "ca recrute par ici",
    
    # === À NOTER: "je recrute" et "je recherche" sont retirés ===
    # Car ils peuvent être utilisés par des candidats ou chasseurs de têtes
]

# =============================================================================
# EXCLUSION LISTS - Any match triggers immediate rejection
# =============================================================================

# Stage, Alternance, Apprentissage - LISTE EXHAUSTIVE
EXCLUSION_STAGE_ALTERNANCE = [
    # Stage (toutes variantes)
    "stage", "stagiaire", "stages", "stagiaires",
    "stage juridique", "stage avocat", "stage notaire",
    "offre de stage", "stage pfe", "stage fin d'etudes",
    "stage de fin", "stage m1", "stage m2", "stage l3",
    "stage 6 mois", "stage 3 mois", "stage 4 mois", "stage 2 mois",
    "recherche stage", "propose un stage", "proposons un stage",
    "accueillir un stagiaire", "accueillir une stagiaire",
    "recrute un stagiaire", "recrute une stagiaire",
    "recrutons un stagiaire", "recrutons une stagiaire",
    "stagiaire juridique", "stagiaire avocat", "stagiaire notaire",
    "eleve avocat", "eleve-avocat",
    # Alternance (toutes variantes)
    "alternance", "alternant", "alternante", "alternants",
    "contrat alternance", "en alternance", "poste alternance",
    "poste en alternance", "offre alternance", "offre d alternance",
    "recrute en alternance", "recrutons en alternance",
    "recherche alternance", "cherche alternance",
    "profil alternant", "profil alternance",
    "contrat en alternance", "formation en alternance",
    "master en alternance", "licence en alternance",
    "juriste alternant", "juriste alternance",
    # Apprentissage (variantes)
    "apprentissage", "apprenti", "apprentie", "apprentis",
    "contrat d apprentissage", "contrat apprentissage",
    "recrute un apprenti", "recrute une apprentie",
    "recherche apprenti", "offre apprentissage",
    # Contrat pro
    "contrat pro", "contrat de professionnalisation",
    # Termes anglais
    "internship", "intern ", "interns", "trainee", "work-study", "work study",
    "working student", "student job", "graduate program",
    # V.I.E.
    "vie ", "v.i.e", "volontariat international",
    # Patterns hashtag
    "#stage", "#alternance", "#stagiaire", "#alternant",
]

# Freelance, missions, consultants externes
EXCLUSION_FREELANCE = [
    "freelance", "free-lance", "free lance",
    "mission ponctuelle", "mission courte", "interim", "interimaire",
    "consultant externe", "consultante externe", "prestataire",
    "auto-entrepreneur", "autoentrepreneur", "independant",
    "portage salarial", "temps partiel", "mi-temps",
]

# Locations outside France
EXCLUSION_NON_FRANCE = [
    "canada", "quebec", "montreal", "toronto", "vancouver",
    "usa", "etats-unis", "united states", "new york", "los angeles",
    "belgique", "belgium", "bruxelles", "brussels",
    "suisse", "switzerland", "geneve", "zurich", "lausanne",
    "luxembourg",
    "uk", "united kingdom", "royaume-uni", "london", "londres",
    "allemagne", "germany", "deutschland", "berlin", "munich", "frankfurt",
    "espagne", "spain", "madrid", "barcelona",
    "italie", "italy", "milan", "rome",
    "pays-bas", "netherlands", "amsterdam",
    "singapour", "singapore", "dubai", "hong kong",
    "australie", "australia", "sydney", "melbourne",
    "maroc", "morocco", "casablanca", "tunisie", "tunisia", "algerie", "algeria",
]

# Job seekers (#opentowork) - terms indicating the AUTHOR is job seeking, not recruiting
EXCLUSION_JOBSEEKER = [
    "opentowork", "open to work", "#opentowork",
    # Clear job-seeking patterns (author looking for work, not recruiting)
    "recherche emploi", "recherche poste", "recherche un poste",
    "a l ecoute du marche", "a l'ecoute du marche",
    "ouvert aux opportunites", "ouverte aux opportunites",
    "ouvert a de nouvelles opportunites", "ouverte a de nouvelles opportunites",
    "cherche poste", "cherche emploi", "cherche un poste",
    "cherche un premier poste", "premier emploi",
    "en recherche active", "en recherche d emploi",
    "disponible immediatement", "disponible des maintenant",
    "actuellement en recherche", "je suis en recherche",
    "je suis a la recherche", "je suis a l ecoute",
    "je me permets de", "je vous contacte",
    "mon profil", "mon parcours", "mon cv",
    "n hesitez pas a me contacter", "contactez moi",
    "si vous recrutez", "si vous cherchez",
    # First person job seeking
    "je recherche un poste", "je recherche un emploi",
    "je cherche un poste", "je cherche un emploi",
    "je suis juriste", "je suis avocat", "je suis avocate",
    "diplome de", "diplomee de",
    "jeune diplome", "jeune diplomee",
    "recherche premiere experience", "recherche 1ere experience",
]

# Recruitment already completed - NOT active hiring (announcement of past hire)
EXCLUSION_RECRUITMENT_DONE = [
    # Completed recruitment announcements
    "a rejoint", "a rejoint notre", "a rejoint l equipe",
    "vient de rejoindre", "vient d integrer",
    "nous avons recrute", "nous avons embauche",
    "nous sommes heureux d accueillir", "nous sommes fiers d accueillir",
    "bienvenue a", "bienvenue dans l equipe", "bienvenue dans notre",
    "welcome", "welcome to the team", "welcome on board",
    "nouveau collaborateur", "nouvelle collaboratrice",
    "nouvelle recrue", "notre nouveau", "notre nouvelle",
    "a pris ses fonctions", "a pris son poste",
    "vient de prendre ses fonctions",
    "vient d etre nomme", "vient d etre nommee",
    "a ete nomme", "a ete nommee", "est nomme", "est nommee",
    "a integre", "vient d integrer", "integration reussie",
    "nous felicitons", "felicitations a",
    "est arrive", "est arrivee", "vient d arriver",
    "renforce notre equipe",
    # NOTE: "rejoindre notre equipe" retiré car utilisé dans les offres actives
    # "pour rejoindre notre équipe" est un signal de recrutement actif
    "bonne arrivee", "heureux de compter",
    "accueillons", "nous accueillons",
    # Promotions/Internal moves (not external hiring)
    "promotion", "promu", "promue",
    "evolution interne", "mobilite interne",
    "nouvelle fonction", "nouvelles fonctions",
    "prend la direction", "prend la tete",
]

# Promotional content - Only exclude clear non-recruitment promotional content
# Note: Terms like "article" and "conference" are too generic and cause false positives
EXCLUSION_PROMOTIONAL = [
    "webinar", "webinaire",
    "seminaire", "atelier formation",
    "podcast", "newsletter",
    "livre blanc", "white paper", "ebook", "e-book",
    "inscrivez-vous", "reservez votre place", "places limitees",
    "lien en bio", "lien dans les commentaires",
    "replay", "rediffusion",
]

# Sponsored/Promotional content markers
EXCLUSION_SPONSORED = [
    "sponsorise", "sponsored", "publicite", "pub ",
    "annonce payee", "partenariat", "contenu sponsorise",
    "#ad", "#pub", "#sponsored",
]

# Emotional/Personal posts (not job offers)
EXCLUSION_EMOTIONAL = [
    "fier de", "fiere de", "bravo a", "felicitations a",
    "merci a", "heureux de", "heureuse de",
    "anniversaire", "bon weekend", "bonne annee",
    "joyeux noel", "bonnes fetes", "meilleurs voeux",
    "incroyable equipe", "super equipe", "team building",
    "retour sur", "throwback", "#tbt", "#throwback",
]

# Competing recruitment agencies
EXCLUSION_RECRUITMENT_AGENCIES = [
    # Specific agencies mentioned by client
    "fed legal", "fed juridique",
    "michael page", "page group", "page personnel",
    "walters people", "robert walters",
    "hays",
    # Other major agencies
    "robert half", "expectra", "adecco", "manpower", "randstad",
    "spring professional", "lincoln associates", "laurence simons",
    "taylor root", "morgan philips", "spencer stuart",
    "russell reynolds", "egon zehnder", "korn ferry",
    "boyden", "heidrick struggles", "odgers berndtson",
    # Generic agency indicators
    "cabinet de recrutement", "cabinet recrutement", "agence recrutement",
    "chasseur de tetes", "headhunter", "executive search",
    "notre client recherche", "pour notre client", "pour le compte de",
    "client confidentiel", "societe confidentielle",
    "mandat de recrutement", "nous recrutons pour",
]

# Non-legal professions to exclude
EXCLUSION_NON_LEGAL_JOBS = [
    # Marketing & Communication
    "marketing", "communication", "community manager", "social media",
    "chef de projet digital", "brand manager", "content manager",
    # Finance & Audit (except legal compliance)
    "finance", "comptable", "comptabilite", "audit", "auditeur",
    "controleur de gestion", "tresorier", "credit manager",
    "analyste financier", "directeur financier", "daf", "cfo",
    # RH & Admin (except legal assistant)
    "ressources humaines", "rh ", "drh", "chargee de recrutement",
    "gestionnaire paie", "office manager", "assistant administratif",
    "assistante administrative", "secretaire", "receptionniste",
    # Tech & Data
    "developpeur", "developer", "data scientist", "data analyst",
    "data engineer", "chef de projet it", "product manager",
    "devops", "sysadmin", "cybersecurite", "architecte si",
    # Conformite (sauf juriste conformite explicite)
    "compliance officer", "responsable conformite",
    # Autres
    "commercial", "sales", "business developer", "account manager",
    "acheteur", "supply chain", "logistique", "operations",
]

# =============================================================================
# TEXT CLEANING FUNCTIONS
# =============================================================================

def remove_accents(text: str) -> str:
    """Remove accents from text using unicode normalization."""
    nfkd = unicodedata.normalize('NFKD', text)
    return ''.join(c for c in nfkd if not unicodedata.combining(c))


def remove_emojis(text: str) -> str:
    """Remove emojis and special unicode characters."""
    # Comprehensive emoji pattern
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map symbols
        "\U0001F1E0-\U0001F1FF"  # flags
        "\U00002702-\U000027B0"  # dingbats
        "\U000024C2-\U0001F251"  # enclosed characters
        "\U0001F900-\U0001F9FF"  # supplemental symbols
        "\U0001FA00-\U0001FA6F"  # chess symbols
        "\U0001FA70-\U0001FAFF"  # symbols extended-A
        "\U00002600-\U000026FF"  # misc symbols
        "\U00002700-\U000027BF"  # dingbats
        "]+",
        flags=re.UNICODE
    )
    return emoji_pattern.sub('', text)


def remove_hashtags(text: str) -> str:
    """Remove hashtags but keep the word (e.g., #avocat -> avocat)."""
    return re.sub(r'#(\w+)', r'\1', text)


def normalize_text(text: str) -> str:
    """
    Full text normalization:
    - Convert to lowercase
    - Remove accents
    - Remove emojis
    - Remove hashtags (keep words)
    - Normalize whitespace
    """
    if not text:
        return ""
    
    text = text.lower()
    text = remove_accents(text)
    text = remove_emojis(text)
    text = remove_hashtags(text)
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text)
    # Remove special characters but keep basic punctuation
    text = re.sub(r'[^\w\s\'-]', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()


# =============================================================================
# SCORING FUNCTIONS
# =============================================================================

def calculate_legal_profession_score(text: str) -> Tuple[float, List[str]]:
    """
    Calculate legal profession score.
    Returns (score, matched_terms).
    Score >= 0.2 required for valid post.
    """
    matched = []
    normalized = normalize_text(text)
    
    # Check full profession keywords first (longer matches take precedence)
    for profession in sorted(LEGAL_PROFESSIONS, key=len, reverse=True):
        if profession in normalized:
            matched.append(profession)
    
    # Also check stems for flexible matching
    for stem in LEGAL_STEMS:
        if stem in normalized and stem not in matched:
            matched.append(stem)
    
    # Calculate score based on matches
    if not matched:
        return 0.0, []
    
    # Base score for having at least one match
    score = 0.25  # Increased from 0.2 to be more inclusive
    
    # Bonus for multiple distinct matches (max +0.3)
    unique_matches = set(matched)
    score += min(0.3, len(unique_matches) * 0.1)
    
    # Bonus for specific high-value roles
    high_value_roles = ["directeur juridique", "directrice juridique", 
                        "responsable juridique", "general counsel", 
                        "head of legal", "avocat associe", "notaire",
                        "head of legal compliance", "legal manager",
                        "senior legal counsel", "juriste confirme"]
    if any(role in normalized for role in high_value_roles):
        score += 0.15
    
    # Extra bonus for legal firm context
    firm_context = ["law firm", "cabinet avocat", "cabinet d avocat", 
                    "etude notariale", "direction juridique"]
    if any(ctx in normalized for ctx in firm_context):
        score += 0.1
    
    return min(1.0, score), list(unique_matches)


def calculate_recruitment_score(text: str) -> Tuple[float, List[str]]:
    """
    Calculate recruitment signal score.
    Returns (score, matched_signals).
    Score >= 0.15 required for valid post.
    
    IMPORTANT: Distingue entre:
    - Entreprise qui recrute ACTIVEMENT (score élevé)
    - Simple mention de recrutement sans contexte actif (score faible)
    - Recrutement terminé ou candidat qui cherche (score 0 - exclu ailleurs)
    """
    matched = []
    normalized = normalize_text(text)
    
    # Check standard recruitment signals
    for signal in RECRUITMENT_SIGNALS:
        if signal in normalized:
            matched.append(signal)
    
    # Check for "[Company] recrute" pattern using regex
    import re
    generic_recrute_pattern = re.search(r'\b[a-z]+\s+recrute\b', normalized)
    if generic_recrute_pattern and "recrute" not in matched:
        matched.append("[entreprise] recrute")
    
    if not matched:
        return 0.0, []
    
    # === SCORING SYSTEM REVU ===
    score = 0.0
    
    # SIGNAUX TRÈS FORTS (entreprise qui recrute activement)
    very_strong_signals = [
        "nous recrutons", "on recrute", "notre equipe recrute",
        "poste a pourvoir", "poste ouvert", "cdi a pourvoir", "cdd a pourvoir",
        "postulez", "candidatez", "envoyez cv", "envoyez votre cv",
        "we are hiring", "is hiring", "now hiring", "currently hiring",
        "cabinet recrute", "direction juridique recrute", "equipe juridique recrute",
        "recrute un juriste", "recrute une juriste", "recrute un avocat", "recrute une avocate",
    ]
    very_strong_count = sum(1 for s in very_strong_signals if s in normalized)
    if very_strong_count > 0:
        score += 0.30 + min(0.30, very_strong_count * 0.10)
    
    # SIGNAUX FORTS (contexte recrutement clair)
    strong_signals = [
        "nous recherchons", "on recherche", "recherche un juriste", "recherche une juriste",
        "recherche un avocat", "recherche une avocate", "cdi", "cdd",
        "creation de poste", "opportunite", "temps plein",
        "profil recherche", "missions principales",
        "looking for", "join our team",
    ]
    strong_count = sum(1 for s in strong_signals if s in normalized)
    if strong_count > 0:
        score += 0.20 + min(0.20, strong_count * 0.05)
    
    # SIGNAUX MOYENS (peuvent être ambigus)
    medium_signals = [
        "experience requise", "rattache a", "vous justifiez",
        "package", "remuneration",
    ]
    medium_count = sum(1 for s in medium_signals if s in normalized)
    if medium_count > 0:
        score += min(0.15, medium_count * 0.05)
    
    # BONUS pour pattern "[Entreprise] recrute"
    if generic_recrute_pattern:
        score += 0.20
    
    # MALUS: Première personne du singulier ("je recrute") = potentiellement chasseur de têtes
    first_person_singular = any(fp in normalized for fp in [
        "je recrute", "je recherche", "je cherche"
    ])
    if first_person_singular and very_strong_count == 0:
        # Réduire le score si pas de signal d'entreprise
        score = max(0, score - 0.15)
    
    # BONUS: Contexte juridique + recrutement combiné
    legal_recruitment_patterns = [
        "cabinet recrute", "direction juridique recrute", "etude recrute",
        "etude notariale recrute", "equipe juridique",
    ]
    if any(pat in normalized for pat in legal_recruitment_patterns):
        score += 0.15
    
    return min(1.0, score), matched


# =============================================================================
# EXCLUSION DETECTION
# =============================================================================

@dataclass
class ExclusionResult:
    """Result of exclusion check."""
    excluded: bool
    reason: str
    matched_terms: List[str] = field(default_factory=list)


def check_exclusions(
    text: str, 
    post_date: Optional[datetime] = None,
    config: Optional["FilterConfig"] = None
) -> ExclusionResult:
    """
    Check if post should be excluded.
    Returns ExclusionResult with reason if excluded.
    
    ORDRE DE PRIORITÉ DES FILTRES (optimisé pour performance):
    1. Posts trop anciens (> 3 semaines) - RAPIDE, élimine beaucoup
    2. Stage/Alternance/Apprentissage - CRITIQUE, jamais accepter
    3. Freelance/Missions - Exclure missions courtes
    4. Non-France locations - Filtrage géographique
    5. Job seekers (#opentowork) - Chercheurs d'emploi, pas recruteurs
    6. Promotional content - Contenu non-recrutement
    7. Recruitment agencies - Concurrents
    8. Non-legal professions - Hors domaine juridique
    """
    if config is None:
        config = FilterConfig()  # Use defaults
        
    normalized = normalize_text(text)
    
    # 0. FILTRE DATE - EN PREMIER (rapide et élimine beaucoup de posts)
    if post_date:
        now = datetime.now(timezone.utc)
        if post_date.tzinfo is None:
            post_date = post_date.replace(tzinfo=timezone.utc)
        age = now - post_date
        if age > timedelta(weeks=3):
            return ExclusionResult(True, "post_trop_ancien", 
                                   [f"{age.days} jours"])
    
    # 1. Stage/Alternance - PRIORITÉ MAXIMALE (jamais accepter)
    if config.exclude_stage:
        # Vérification exhaustive avec tous les termes
        for term in EXCLUSION_STAGE_ALTERNANCE:
            if term in normalized:
                # Double vérification: s'assurer que ce n'est pas un faux positif
                # Ex: "stage de développement de carrière" vs "offre de stage"
                false_positive_contexts = [
                    "stade",  # "stade de france" != "stage"
                    "stage de carriere",  # métaphore
                ]
                is_false_positive = any(fp in normalized for fp in false_positive_contexts)
                if not is_false_positive:
                    return ExclusionResult(True, "stage_alternance", [term])
    
    # 2. Freelance/Missions
    if config.exclude_freelance:
        for term in EXCLUSION_FREELANCE:
            if term in normalized:
                return ExclusionResult(True, "freelance_mission", [term])
    
    # 3. Non-France locations - improved logic
    if config.exclude_foreign:
        matched_locations = [loc for loc in EXCLUSION_NON_FRANCE if loc in normalized]
        if matched_locations:
            # Check if France is also mentioned (could be multi-location role OR comparison post)
            # Extended list of French cities/regions
            france_indicators = [
                # Grandes villes
                "france", "paris", "lyon", "marseille", "bordeaux", 
                "toulouse", "nantes", "lille", "strasbourg", "nice",
                "rennes", "grenoble", "montpellier", "la defense",
                # Régions
                "ile-de-france", "ile de france", "idf", "region parisienne",
                "hauts-de-france", "hauts de france", "auvergne", "rhone-alpes",
                "paca", "provence", "normandie", "bretagne", "occitanie",
                "nouvelle-aquitaine", "nouvelle aquitaine", "grand est",
                # Villes moyennes
                "angers", "dijon", "reims", "le havre", "saint-etienne",
                "toulon", "clermont-ferrand", "villeurbanne", "metz", "besancon",
                "orleans", "rouen", "mulhouse", "perpignan", "caen",
                "boulogne-billancourt", "nancy", "argenteuil", "roubaix",
                "tourcoing", "dunkerque", "avignon", "nimes", "poitiers",
                "aix-en-provence", "aix en provence", "versailles", "pau",
                "la rochelle", "limoges", "tours", "amiens", "annecy",
                "brest", "le mans", "saint-nazaire", "colmar", "troyes",
                "lorient", "quimper", "valence", "chambery", "niort",
                "vannes", "chartres", "laval", "cholet", "saint-denis",
                "saint denis", "voreppe", "compiegne", "neuilly",
                # Arrondissements Paris
                "paris 1", "paris 2", "paris 3", "paris 4", "paris 5",
                "paris 6", "paris 7", "paris 8", "paris 9", "paris 10",
                "paris 11", "paris 12", "paris 13", "paris 14", "paris 15",
                "paris 16", "paris 17", "paris 18", "paris 19", "paris 20",
            ]
            has_france = any(f in normalized for f in france_indicators)
            
            # Foreign location explicitly mentioned = exclude (CDI/CDD alone don't prove France)
            # Only accept if a French city/indicator is ALSO mentioned
            if not has_france:
                return ExclusionResult(True, "hors_france", matched_locations)
    
    # 4. Job seekers - Exclude if the author is seeking work, not recruiting
    if config.exclude_opentowork:
        for term in EXCLUSION_JOBSEEKER:
            if term in normalized:
                # Strong first-person job seeking signals = definitely exclude
                first_person_seeking = any(fp in normalized for fp in [
                    "je recherche", "je cherche", "je suis a", "mon cv", "mon profil",
                    "je suis juriste", "je suis avocat", "disponible immediatement"
                ])
                # Only keep if it has VERY strong company recruitment signals
                has_company_recruitment = any(sig in normalized for sig in [
                    "nous recrutons", "on recrute", "notre equipe recrute",
                    "poste a pourvoir", "cdi a pourvoir", "cdd a pourvoir"
                ])
                if first_person_seeking or not has_company_recruitment:
                    return ExclusionResult(True, "chercheur_emploi", [term])
    
    # 4b. Recruitment already done - Exclude welcome/arrival announcements
    if config.exclude_opentowork:  # Reuse same config flag
        for term in EXCLUSION_RECRUITMENT_DONE:
            if term in normalized:
                # This is announcing someone ALREADY hired, not an active job posting
                return ExclusionResult(True, "recrutement_termine", [term])
    
    # 5. Promotional content - more lenient
    if config.exclude_promo:
        matched_promo = [term for term in EXCLUSION_PROMOTIONAL if term in normalized]
        if matched_promo:
            # Don't exclude if ANY recruitment signal is present
            has_recruitment = any(sig in normalized for sig in [
                "recrute", "recruiting", "hiring", "cdi", "cdd", 
                "poste", "offre", "juriste", "avocat", "notaire"
            ])
            if not has_recruitment:
                return ExclusionResult(True, "contenu_promotionnel", matched_promo)
    
    # 5b. Sponsored content
    if config.exclude_sponsored:
        matched_sponsored = [term for term in EXCLUSION_SPONSORED if term in normalized]
        if matched_sponsored:
            # Don't exclude if clear recruitment signal
            has_recruitment = any(sig in normalized for sig in [
                "recrute", "cdi", "cdd", "poste a pourvoir"
            ])
            if not has_recruitment:
                return ExclusionResult(True, "contenu_sponsorise", matched_sponsored)
    
    # 5c. Emotional/Personal posts
    if config.exclude_emotional:
        matched_emotional = [term for term in EXCLUSION_EMOTIONAL if term in normalized]
        if matched_emotional:
            # Don't exclude if clear recruitment signal
            has_recruitment = any(sig in normalized for sig in [
                "recrute", "cdi", "cdd", "poste a pourvoir", "hiring"
            ])
            if not has_recruitment:
                return ExclusionResult(True, "post_emotionnel", matched_emotional)
    
    # 6. Recruitment agencies
    if config.exclude_agencies:
        for term in EXCLUSION_RECRUITMENT_AGENCIES:
            if term in normalized:
                return ExclusionResult(True, "cabinet_recrutement", [term])
    
    # 7. Non-legal professions - Check if the JOB BEING RECRUITED is non-legal
    if config.exclude_non_legal:
        # First check if there's a legal job term - if yes, don't exclude
        has_legal_job = any(term in normalized for term in [
            "juriste", "avocat", "notaire", "legal", "juridique", 
            "counsel", "paralegal", "clerc"
        ])
        
        if not has_legal_job:
            # Only check non-legal exclusions if no legal job is mentioned
            recruitment_patterns = ["recrute", "recherche", "recherchons", "poste de", "poste d"]
            for term in EXCLUSION_NON_LEGAL_JOBS:
                if term in normalized:
                    # Check if this non-legal term is the TARGET of recruitment
                    term_idx = normalized.find(term)
                    # Look at context around the term (50 chars before)
                    context_before = normalized[max(0, term_idx-50):term_idx]
                    is_recruitment_target = any(pat in context_before for pat in recruitment_patterns)
                    
                    # Also check for title patterns like "Directeur Financier recherché"
                    context_after = normalized[term_idx:term_idx+30]
                    is_job_title = "recherche" in context_after or term_idx < 50  # Term appears early = likely the job title
                    
                    if is_recruitment_target or is_job_title:
                        return ExclusionResult(True, "metier_non_juridique", [term])
    
    # 8. Posts older than 3 weeks
    if post_date:
        now = datetime.now(timezone.utc)
        if post_date.tzinfo is None:
            post_date = post_date.replace(tzinfo=timezone.utc)
        age = now - post_date
        if age > timedelta(weeks=3):
            return ExclusionResult(True, "post_trop_ancien", 
                                   [f"{age.days} jours"])
    
    return ExclusionResult(False, "", [])


# =============================================================================
# MAIN FILTER FUNCTION
# =============================================================================

@dataclass
class FilterResult:
    """Result of the is_legal_job_post filter."""
    is_valid: bool
    recruitment_score: float
    legal_score: float
    total_score: float
    exclusion_reason: str
    exclusion_terms: List[str]
    matched_professions: List[str]
    matched_signals: List[str]
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "is_valid": self.is_valid,
            "recruitment_score": self.recruitment_score,
            "legal_score": self.legal_score,
            "total_score": self.total_score,
            "exclusion_reason": self.exclusion_reason,
            "exclusion_terms": self.exclusion_terms,
            "matched_professions": self.matched_professions,
            "matched_signals": self.matched_signals,
        }


@dataclass
class FilterConfig:
    """Configuration for the legal job post filter."""
    # Scoring thresholds
    recruitment_threshold: float = 0.15
    legal_threshold: float = 0.20
    # Exclusion toggles
    exclude_stage: bool = True
    exclude_freelance: bool = True
    exclude_opentowork: bool = True
    exclude_promo: bool = True
    exclude_agencies: bool = True
    exclude_foreign: bool = True
    exclude_non_legal: bool = True
    exclude_sponsored: bool = True
    exclude_emotional: bool = True
    # Logging
    verbose: bool = True


# Default configuration
DEFAULT_FILTER_CONFIG = FilterConfig()


def is_legal_job_post(
    text: str,
    post_date: Optional[datetime] = None,
    log_exclusions: bool = True,
    config: Optional[FilterConfig] = None
) -> FilterResult:
    """
    Main filter function to determine if a post is a valid legal job posting.
    
    Args:
        text: Raw post text
        post_date: Optional datetime of the post (for age filtering)
        log_exclusions: Whether to log exclusion reasons
        config: Optional FilterConfig for custom thresholds and exclusion toggles
        
    Returns:
        FilterResult with is_valid=True if post passes all filters
        
    Criteria for valid post:
    - recruitment_score >= config.recruitment_threshold (default 0.15)
    - legal_score >= config.legal_threshold (default 0.20)
    - No exclusion keywords detected (based on config toggles)
    """
    if config is None:
        config = DEFAULT_FILTER_CONFIG
    if not text or not text.strip():
        result = FilterResult(
            is_valid=False,
            recruitment_score=0.0,
            legal_score=0.0,
            total_score=0.0,
            exclusion_reason="texte_vide",
            exclusion_terms=[],
            matched_professions=[],
            matched_signals=[]
        )
        if log_exclusions and config.verbose:
            logger.debug("Post exclu: texte vide")
        return result
    
    # Step 1: Check exclusions FIRST (immediate rejection) - based on config
    exclusion = check_exclusions(text, post_date, config)
    if exclusion.excluded:
        result = FilterResult(
            is_valid=False,
            recruitment_score=0.0,
            legal_score=0.0,
            total_score=0.0,
            exclusion_reason=exclusion.reason,
            exclusion_terms=exclusion.matched_terms,
            matched_professions=[],
            matched_signals=[]
        )
        if log_exclusions and config.verbose:
            print(
                f"Post exclu [{exclusion.reason}]: "
                f"termes détectés = {exclusion.matched_terms}"
            )
        return result
    
    # Step 2: Calculate scores
    legal_score, legal_matches = calculate_legal_profession_score(text)
    recruitment_score, recruitment_matches = calculate_recruitment_score(text)
    
    # Combined score (weighted)
    total_score = (legal_score * 0.5) + (recruitment_score * 0.5)
    
    # Step 3: Check minimum thresholds (using config values)
    is_valid = (recruitment_score >= config.recruitment_threshold) and (legal_score >= config.legal_threshold)
    
    exclusion_reason = ""
    if not is_valid:
        if recruitment_score < config.recruitment_threshold and legal_score < config.legal_threshold:
            exclusion_reason = "score_insuffisant_recrutement_et_juridique"
        elif recruitment_score < config.recruitment_threshold:
            exclusion_reason = "score_insuffisant_recrutement"
        else:
            exclusion_reason = "score_insuffisant_juridique"
        
        if log_exclusions and config.verbose:
            print(
                f"Post exclu [{exclusion_reason}]: "
                f"recruitment_score={recruitment_score:.2f} (min {config.recruitment_threshold}), "
                f"legal_score={legal_score:.2f} (min {config.legal_threshold})"
            )
    else:
        if log_exclusions:
            logger.debug(
                f"Post accepté: recruitment_score={recruitment_score:.2f}, "
                f"legal_score={legal_score:.2f}, "
                f"professions={legal_matches}, signals={recruitment_matches}"
            )
    
    return FilterResult(
        is_valid=is_valid,
        recruitment_score=recruitment_score,
        legal_score=legal_score,
        total_score=total_score,
        exclusion_reason=exclusion_reason,
        exclusion_terms=[],
        matched_professions=legal_matches,
        matched_signals=recruitment_matches
    )


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    "is_legal_job_post",
    "FilterResult",
    "FilterConfig",
    "ExclusionResult",
    "normalize_text",
    "calculate_legal_profession_score",
    "calculate_recruitment_score",
    "check_exclusions",
    "LEGAL_PROFESSIONS",
    "RECRUITMENT_SIGNALS",
    "EXCLUSION_STAGE_ALTERNANCE",
    "EXCLUSION_FREELANCE",
    "EXCLUSION_NON_FRANCE",
    "EXCLUSION_JOBSEEKER",
    "EXCLUSION_PROMOTIONAL",
    "EXCLUSION_SPONSORED",
    "EXCLUSION_EMOTIONAL",
    "EXCLUSION_RECRUITMENT_AGENCIES",
    "EXCLUSION_NON_LEGAL_JOBS",
    "EXCLUSION_RECRUITMENT_DONE",
    "DEFAULT_FILTER_CONFIG",
]
