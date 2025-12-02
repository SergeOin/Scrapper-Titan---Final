"""
Configuration des mots-clés et règles de filtrage juridique pour Titan Partners.

Ce module centralise toutes les listes de mots-clés configurables pour:
- Détecter les posts de recrutement juridique interne
- Exclure les posts hors cible (agences, freelances, stages, etc.)
- Qualifier la pertinence des posts pour le cabinet Titan Partners

USAGE:
    from filters.juridique import get_default_config, JuridiqueConfig
    
    config = get_default_config()
    # ou personnalisé:
    config = JuridiqueConfig(
        legal_roles=["juriste", "avocat"],
        min_recruitment_score=0.2
    )

EXTENSION:
    Pour ajouter de nouveaux mots-clés, modifier les listes ci-dessous
    ou passer des listes personnalisées au constructeur JuridiqueConfig.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Set
import re


# =============================================================================
# MOTS-CLÉS DE PROFILS JURIDIQUES (cibles de Titan Partners)
# =============================================================================

LEGAL_ROLE_KEYWORDS: List[str] = [
    # === JURISTES (toutes variantes) ===
    "juriste",
    "juriste junior",
    "juriste confirmé",
    "juriste confirme",
    "juriste senior",
    "juriste d'entreprise",
    "juriste entreprise",
    "juriste corporate",
    "juriste droit social",
    "juriste droit des affaires",
    "juriste contrats",
    "juriste contentieux",
    "juriste conformité",
    "juriste conformite",
    "juriste compliance",
    "juriste recouvrement",
    "juriste legal ops",
    "juriste generaliste",
    "juriste généraliste",
    "juriste droit public",
    "juriste droit privé",
    "juriste droit prive",
    "juriste immobilier",
    "juriste bancaire",
    "juriste assurances",
    "juriste propriété intellectuelle",
    "juriste pi",
    "juriste it",
    "juriste rgpd",
    "juriste data",
    
    # === LEGAL COUNSEL (FR/EN) ===
    "legal counsel",
    "senior legal counsel",
    "junior legal counsel",
    "legal manager",
    "legal operations",
    "legal ops",
    
    # === AVOCATS (toutes variantes) ===
    "avocat",
    "avocate",
    "avocat collaborateur",
    "avocate collaboratrice",
    "avocat associé",
    "avocat associe",
    "avocate associée",
    "avocate associee",
    "avocat counsel",
    "avocate counsel",
    "avocat junior",
    "avocat senior",
    "collaborateur avocat",
    "collaboratrice avocate",
    
    # === DIRECTION JURIDIQUE ===
    "responsable juridique",
    "directeur juridique",
    "directrice juridique",
    "head of legal",
    "chief legal officer",
    "clo",
    "general counsel",
    "secrétaire général",
    "secretaire general",
    "directeur des affaires juridiques",
    
    # === COMPLIANCE / DPO ===
    "compliance officer",
    "compliance manager",
    "responsable conformité",
    "responsable conformite",
    "dpo",
    "data protection officer",
    "délégué à la protection des données",
    "delegue protection donnees",
    "privacy officer",
    "privacy manager",
    
    # === CONTRACT MANAGEMENT ===
    "contract manager",
    "gestionnaire de contrats",
    "responsable contrats",
    
    # === PARALEGAL / SUPPORT ===
    "paralegal",
    "paralegale",
    "assistant juridique",
    "assistante juridique",
    "legal assistant",
    
    # === NOTARIAT ===
    "notaire",
    "notaire associé",
    "notaire associe",
    "notaire salarié",
    "notaire salarie",
    "clerc de notaire",
    "clerc principal",
    "rédacteur d'actes",
    "redacteur actes",
    
    # === FISCALISTES ===
    "fiscaliste",
    "juriste fiscal",
    "tax lawyer",
    "tax counsel",
]

# Stems courts pour matching flexible
LEGAL_STEMS: Set[str] = {
    "juriste",
    "avocat",
    "notaire",
    "paralegal",
    "counsel",
    "legal",
    "juridique",
    "fiscaliste",
    "compliance",
    "dpo",
}


# =============================================================================
# SIGNAUX DE RECRUTEMENT (indicateurs de vraie offre d'emploi)
# =============================================================================

RECRUITMENT_SIGNALS: List[str] = [
    # === PHRASES EXPLICITES (demandées par Titan Partners) ===
    "nous recrutons",
    "on recrute",
    "je recrute",
    "nous cherchons",
    "on cherche",
    "je cherche",
    "poste à pourvoir",
    "poste a pourvoir",
    "opportunité",
    "opportunite",
    "rejoignez notre équipe",
    "rejoignez notre equipe",
    "rejoindre notre équipe",
    "rejoindre notre equipe",
    
    # === TYPES DE CONTRATS ===
    "cdi",
    "cdd",
    "temps plein",
    "full time",
    "temps partiel",
    
    # === INDICATEURS DE RECRUTEMENT ===
    "offre d'emploi",
    "offre emploi",
    "recrutement",
    "recrute",
    "recruiting",
    "hiring",
    "we are hiring",
    "we're hiring",
    "is hiring",
    "join our team",
    "join the team",
    "looking for",
    "is looking for",
    
    # === DÉTAILS D'OFFRE ===
    "profil recherché",
    "profil recherche",
    "missions principales",
    "rattaché à",
    "rattache a",
    "expérience requise",
    "experience requise",
    "vous justifiez",
    "compétences requises",
    "competences requises",
    "postulez",
    "candidature",
    "envoyez cv",
    "envoyez votre cv",
    
    # === CREATION DE POSTE ===
    "création de poste",
    "creation de poste",
    "nouveau poste",
    "poste ouvert",
    "à pourvoir",
    "a pourvoir",
    "prise de poste",
    
    # === CONTEXTE ÉQUIPE ===
    "renforcer notre équipe",
    "renforcer notre equipe",
    "agrandir notre équipe",
    "se renforcer",
    "équipe juridique recrute",
    "equipe juridique recrute",
    "direction juridique recrute",
    "cabinet recrute",
    "étude recrute",
    "etude recrute",
]


# =============================================================================
# PATTERNS DE RECRUTEMENT INTERNE (l'entreprise recrute pour elle-même)
# =============================================================================

INTERNAL_RECRUITMENT_PATTERNS: List[str] = [
    # Français
    "nous recrutons",
    "on recrute", 
    "notre entreprise recrute",
    "notre cabinet recrute",
    "notre équipe recrute",
    "notre equipe recrute",
    "notre société recrute",
    "notre societe recrute",
    "notre groupe recrute",
    "notre direction juridique recherche",
    "nous recherchons",
    "nous cherchons",
    "je recrute pour mon équipe",
    "je recrute pour mon equipe",
    "rejoindre notre équipe",
    "rejoindre notre equipe",
    "intégrer notre équipe",
    "integrer notre equipe",
    
    # Anglais
    "we are hiring",
    "we're hiring",
    "we are recruiting",
    "we're recruiting",
    "we are looking for",
    "we're looking for",
    "join our team",
    "join us",
    "our team is hiring",
    "our company is hiring",
]


# =============================================================================
# EXCLUSIONS: AGENCES ET CABINETS DE RECRUTEMENT (concurrents)
# =============================================================================

EXCLUSION_AGENCY_PATTERNS: List[str] = [
    # === TERMES GÉNÉRIQUES ===
    "cabinet de recrutement",
    "cabinet recrutement",
    "agence de recrutement",
    "agence recrutement",
    "chasseur de têtes",
    "chasseur de tetes",
    "chasseurs de têtes",
    "chasseurs de tetes",
    "headhunter",
    "headhunting",
    "executive search",
    "talent acquisition agency",
    "rh externalisé",
    "rh externalisee",
    "rh externe",
    "externalisation rh",
    "interim",
    "intérim",
    "société d'intérim",
    "societe interim",
    "esn",
    "ssii",
    "société de conseil rh",
    
    # === FORMULATIONS TYPIQUES DES AGENCES ===
    "notre client recherche",
    "pour le compte de notre client",
    "pour notre client",
    "notre client, un",
    "notre client recrute",
    "client final",
    "mission pour",
    "nous recrutons pour",
    "mandat de recrutement",
    "pour un de nos clients",
    "pour l'un de nos clients",
    "l'un de nos clients",
    "un de nos partenaires",
    "confidentiel",
    "client confidentiel",
    "société confidentielle",
    "entreprise confidentielle",
    
    # === CABINETS CONNUS (France) ===
    "michael page",
    "robert half",
    "hays",
    "fed legal",
    "fed juridique",
    "page personnel",
    "page group",
    "expectra",
    "adecco",
    "manpower",
    "randstad",
    "spring professional",
    "lincoln associates",
    "laurence simons",
    "taylor root",
    "legadvisor",
    "approach people",
    "legal staffing",
    "major hunter",
    "morgan philips",
    "spencer stuart",
    "russell reynolds",
    "egon zehnder",
    "korn ferry",
    "boyden",
    "eric salmon",
    "odgers berndtson",
    "heidrick & struggles",
    "heidrick struggles",
    "vidal associates",
    "cadreo",
    "walters people",
    "robert walters",
    
    # === CABINETS JURIDIQUES SPÉCIALISÉS ===
    "legal&hr",
    "legal & hr",
    "legalhrconsulting",
    "avoconseil",
    "lawpic",
    "juriwork",
    "juritalents",
    "legalplace recrutement",
    
    # === JOB BOARDS / AGRÉGATEURS ===
    "keljob",
    "monster",
    "cadremploi",
    "apec",
    "indeed",
    "linkedin talent",
    "welcometothejungle",
    "welcome to the jungle",
    "jobteaser",
    "meteojob",
    "regionsjob",
    "hellowork",
    "lemonde emploi",
    "village de la justice",
    
    # === EXPRESSIONS RÉVÉLATRICES ===
    "cabinet spécialisé",
    "cabinet specialise",
    "acteur du recrutement",
    "expert en recrutement",
    "recruteur spécialisé",
    "recruteur specialise",
    "recruteur juridique",
    "consultant recrutement",
    "consultante recrutement",
    "chargé de recrutement",
    "charge de recrutement",
    "chargée de recrutement",
    "chargee de recrutement",
    "recruiter",
    "talent manager",
    "talent partner",
    "sourceur",
    "sourcing",
]


# =============================================================================
# EXCLUSIONS: RECRUTEMENT EXTERNE (pas de besoin interne)
# =============================================================================

EXCLUSION_EXTERNAL_RECRUITMENT: List[str] = [
    # Formulations indiquant un recrutement pour compte de tiers
    "pour l'un de nos clients",
    "pour l un de nos clients",
    "pour un de nos clients",
    "notre client recrute",
    "notre client recherche",
    "pour le compte de",
    "en mission chez",
    "mission chez notre client",
    "détaché chez",
    "detache chez",
    "mis à disposition",
    "mis a disposition",
]


# =============================================================================
# EXCLUSIONS: CONTENU NON LIÉ AU RECRUTEMENT
# =============================================================================

EXCLUSION_NON_RECRUITMENT_CONTENT: List[str] = [
    # === VEILLE JURIDIQUE / ARTICLES ===
    "veille juridique",
    "actualité juridique",
    "actualite juridique",
    "article juridique",
    "analyse juridique",
    "décryptage",
    "decryptage",
    "tribune",
    "point de vue",
    "chronique",
    "revue de presse",
    
    # === ÉVÉNEMENTS / CONFÉRENCES ===
    "conférence",
    "conference",
    "séminaire",
    "seminaire",
    "webinar",
    "webinaire",
    "colloque",
    "forum",
    "salon",
    "petit déjeuner",
    "petit dejeuner",
    "afterwork",
    "networking",
    "masterclass",
    
    # === FORMATIONS ===
    "formation",
    "e-learning",
    "elearning",
    "mooc",
    "certification",
    "diplôme",
    "diplome",
    "examen",
    "concours",
    "résultats du barreau",
    "resultats barreau",
    
    # === PUBLICATIONS / LIVRES ===
    "livre blanc",
    "white paper",
    "ebook",
    "e-book",
    "publication",
    "parution",
    "ouvrage",
    "guide pratique",
    
    # === RETOURS D'EXPÉRIENCE / TÉMOIGNAGES ===
    "retour d'expérience",
    "retour d experience",
    "témoignage",
    "temoignage",
    "interview de",
    "portrait de",
    "parcours de",
    
    # === PROMOTIONNEL / MARKETING ===
    "sponsorisé",
    "sponsorise",
    "sponsored",
    "publicité",
    "publicite",
    "partenariat",
    "#ad",
    "#pub",
    "#sponsored",
    
    # === VIE D'ENTREPRISE (sans recrutement) ===
    "team building",
    "séminaire d'équipe",
    "seminaire equipe",
    "fête de fin d'année",
    "fete fin annee",
    "anniversaire entreprise",
    "inauguration",
    "déménagement",
    "demenagement",
    "nouveaux locaux",
    
    # === POSTS ÉMOTIONNELS / FÉLICITATIONS ===
    "fier de",
    "fière de",
    "fiere de",
    "félicitations",
    "felicitations",
    "bravo à",
    "bravo a",
    "merci à",
    "merci a",
    "heureux d'annoncer",
    "heureux d annoncer",
    "heureuse d'annoncer",
    "heureuse d annoncer",
    "bienvenue à",
    "bienvenue a",
    
    # === ACTUALITÉS / NEWS ===
    "breaking news",
    "flash info",
    "dernière minute",
    "derniere minute",
]


# =============================================================================
# EXCLUSIONS: TYPES D'AUTEURS À IGNORER
# =============================================================================

EXCLUSION_AUTHOR_TYPES: List[str] = [
    # Freelances / Indépendants
    "freelance",
    "free-lance",
    "indépendant",
    "independant",
    "consultant indépendant",
    "consultant independant",
    "auto-entrepreneur",
    "autoentrepreneur",
    
    # Cabinets RH
    "cabinet rh",
    "consultant rh",
    "consultante rh",
    
    # Jobboards
    "jobboard",
    "job board",
    "plateforme emploi",
]


# =============================================================================
# EXCLUSIONS: STAGE / ALTERNANCE / VIE
# =============================================================================

EXCLUSION_STAGE_ALTERNANCE: List[str] = [
    # Stage
    "stage",
    "stagiaire",
    "stages",
    "stagiaires",
    "offre de stage",
    "stage pfe",
    "stage fin d'études",
    "stage fin d etudes",
    "élève avocat",
    "eleve avocat",
    "élève-avocat",
    "eleve-avocat",
    
    # Alternance
    "alternance",
    "alternant",
    "alternante",
    "contrat alternance",
    "en alternance",
    "poste en alternance",
    
    # Apprentissage
    "apprentissage",
    "apprenti",
    "apprentie",
    "contrat d'apprentissage",
    "contrat apprentissage",
    
    # Contrat pro
    "contrat pro",
    "contrat de professionnalisation",
    
    # VIE
    "vie",
    "v.i.e",
    "v.i.e.",
    "volontariat international",
    
    # Anglais
    "internship",
    "intern",
    "trainee",
    "work-study",
    "work study",
    "working student",
    "graduate program",
]


# =============================================================================
# CLASSE DE CONFIGURATION
# =============================================================================

@dataclass
class JuridiqueConfig:
    """
    Configuration complète pour le filtrage des posts juridiques.
    
    Tous les paramètres sont personnalisables via le constructeur.
    Utiliser get_default_config() pour la config standard Titan Partners.
    """
    
    # Mots-clés de profils juridiques (inclusion)
    legal_roles: List[str] = field(default_factory=lambda: LEGAL_ROLE_KEYWORDS.copy())
    legal_stems: Set[str] = field(default_factory=lambda: LEGAL_STEMS.copy())
    
    # Signaux de recrutement
    recruitment_signals: List[str] = field(default_factory=lambda: RECRUITMENT_SIGNALS.copy())
    internal_patterns: List[str] = field(default_factory=lambda: INTERNAL_RECRUITMENT_PATTERNS.copy())
    
    # Listes d'exclusion
    agency_patterns: List[str] = field(default_factory=lambda: EXCLUSION_AGENCY_PATTERNS.copy())
    external_recruitment: List[str] = field(default_factory=lambda: EXCLUSION_EXTERNAL_RECRUITMENT.copy())
    non_recruitment_content: List[str] = field(default_factory=lambda: EXCLUSION_NON_RECRUITMENT_CONTENT.copy())
    author_type_exclusions: List[str] = field(default_factory=lambda: EXCLUSION_AUTHOR_TYPES.copy())
    stage_alternance: List[str] = field(default_factory=lambda: EXCLUSION_STAGE_ALTERNANCE.copy())
    
    # Seuils de scoring
    min_recruitment_score: float = 0.15
    min_legal_score: float = 0.20
    
    # Options de filtrage
    exclude_stage_alternance: bool = True
    exclude_agencies: bool = True
    exclude_external_recruitment: bool = True
    exclude_non_recruitment: bool = True
    exclude_freelance: bool = True
    exclude_foreign: bool = True
    
    # Âge maximum des posts (jours)
    max_post_age_days: int = 21
    
    # Logging
    verbose: bool = True
    
    def add_legal_role(self, role: str) -> None:
        """Ajoute un nouveau rôle juridique à la liste."""
        if role.lower() not in [r.lower() for r in self.legal_roles]:
            self.legal_roles.append(role.lower())
    
    def add_recruitment_signal(self, signal: str) -> None:
        """Ajoute un nouveau signal de recrutement."""
        if signal.lower() not in [s.lower() for s in self.recruitment_signals]:
            self.recruitment_signals.append(signal.lower())
    
    def add_agency_pattern(self, pattern: str) -> None:
        """Ajoute un nouveau pattern d'agence à exclure."""
        if pattern.lower() not in [p.lower() for p in self.agency_patterns]:
            self.agency_patterns.append(pattern.lower())
    
    def compile_patterns(self) -> dict:
        """
        Compile les patterns en expressions régulières pour performance.
        Retourne un dict avec les regex compilées.
        """
        def safe_compile(patterns: List[str]) -> re.Pattern:
            escaped = [re.escape(p) for p in patterns if p]
            if not escaped:
                return re.compile(r"(?!)")  # Never matches
            return re.compile(r"\b(" + "|".join(escaped) + r")\b", re.IGNORECASE)
        
        return {
            "legal_roles": safe_compile(self.legal_roles),
            "recruitment_signals": safe_compile(self.recruitment_signals),
            "internal_patterns": safe_compile(self.internal_patterns),
            "agency_patterns": safe_compile(self.agency_patterns),
            "external_recruitment": safe_compile(self.external_recruitment),
            "non_recruitment": safe_compile(self.non_recruitment_content),
            "stage_alternance": safe_compile(self.stage_alternance),
        }


def get_default_config() -> JuridiqueConfig:
    """
    Retourne la configuration par défaut optimisée pour Titan Partners.
    
    Cette config cible:
    - Posts de recrutement interne d'entreprises
    - Profils juridiques (juriste, avocat, compliance, etc.)
    - Exclusion des agences, stages, alternances, freelances
    """
    return JuridiqueConfig()


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Classes
    "JuridiqueConfig",
    "get_default_config",
    
    # Listes de mots-clés (pour accès direct si besoin)
    "LEGAL_ROLE_KEYWORDS",
    "LEGAL_STEMS",
    "RECRUITMENT_SIGNALS",
    "INTERNAL_RECRUITMENT_PATTERNS",
    "EXCLUSION_AGENCY_PATTERNS",
    "EXCLUSION_EXTERNAL_RECRUITMENT",
    "EXCLUSION_NON_RECRUITMENT_CONTENT",
    "EXCLUSION_AUTHOR_TYPES",
    "EXCLUSION_STAGE_ALTERNANCE",
]
