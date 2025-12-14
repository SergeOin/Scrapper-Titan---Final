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
    # Fiscalistes - AJOUT des 16 métiers
    "fiscaliste", "fiscalistes", "juriste fiscal",
    "directeur fiscal", "directrice fiscale",
    "responsable fiscal", "responsable fiscale",
    # Cabinet/Étude (contexte juridique)
    "cabinet avocat", "cabinet d avocat", "cabinet avocats",
    "law firm", "etude notariale",
]

# Stems for flexible matching (more flexible)
LEGAL_STEMS = ["avocat", "juriste", "notaire", "paralegal", "counsel", "legal", "juridique", "fiscaliste", "fiscal"]

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
    # V.I.E. - Être plus précis pour éviter les faux positifs sur "vie" comme mot courant
    "v.i.e", "v.i.e.", "volontariat international", "volontariat international en entreprise",
    "contrat vie", "mission vie", "offre vie", "poste vie",
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
# IMPORTANT: Éviter les patterns trop génériques qui matchent les recruteurs
# Ex: "je suis à la recherche d'un juriste" = RECRUTEUR, pas chercheur d'emploi
EXCLUSION_JOBSEEKER = [
    "opentowork", "open to work", "#opentowork",
    # LinkedIn automatic "Open to Work" post template phrases
    "je recherche un nouveau poste", "je recherche un nouvel emploi",
    "je recherche mon premier poste", "je recherche mon premier emploi",
    "bonjour a tous je recherche un poste", "bonjour a tous je recherche un emploi",
    "si vous entendez parler d une opportunite", "si vous entendez parler d'une opportunite",
    "j aimerais reprendre contact", "j'aimerais reprendre contact",
    "reconnaissant de m apporter", "reconnaissante de m apporter",
    "reconnaissant(e) de m apporter", "reconnaissant(e) de m'apporter",
    "je vous serais reconnaissant", "je vous serais reconnaissante",
    "a propos de moi et de ce que je recherche",
    "je suis a l ecoute de nouvelles opportunites",
    "je suis a l'ecoute de nouvelles opportunites",
    # NEW: Additional patterns from CSV analysis
    "je suis actuellement en recherche active",
    "nouvelle etape professionnelle en vue",
    "je suis prete a entamer", "je suis pret a entamer",
    "a la recherche d une nouvelle opportunite",
    "si vous recrutez ou si vous connaissez quelqu",
    "si vous recrutez, ou si vous connaissez quelqu",
    "chers membres de mon reseau",
    "je recherche des postes de",
    "dear members of my network",
    "i am currently actively seeking",
    "if you are hiring", "if you know someone who",
    # Clear job-seeking patterns - SPÉCIFIQUES au candidat
    "recherche emploi juridique", "recherche poste juriste", "recherche poste avocat",
    "a l ecoute du marche", "a l'ecoute du marche",
    "ouvert aux opportunites", "ouverte aux opportunites",
    "ouvert a de nouvelles opportunites", "ouverte a de nouvelles opportunites",
    "cherche un premier poste", "premier emploi juridique",
    "en recherche d emploi", "en recherche d un poste",
    "disponible immediatement pour", "disponible des maintenant pour",
    "je suis en recherche d emploi", "je suis en recherche d un poste",
    "je me permets de vous contacter", "je vous contacte car je recherche",
    "mon profil linkedin", "mon parcours professionnel", "mon cv joint",
    "n hesitez pas a me contacter si", "contactez moi si vous",
    # First person job seeking - SPÉCIFIQUES
    "je recherche un poste de juriste", "je recherche un poste d avocat",
    "je cherche un poste de juriste", "je cherche un poste d avocat",
    "je suis juriste en recherche", "je suis avocat en recherche", "je suis avocate en recherche",
    "diplome de l universite", "diplomee de l universite",
    "jeune diplome en droit", "jeune diplomee en droit",
    "recherche premiere experience juridique", "recherche 1ere experience",
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
    # NEW: Additional patterns from CSV analysis
    "j occupe desormais le poste",
    "je prends mes nouvelles fonctions",
    "nous sommes ravis d annoncer la nomination",
    "nomme directeur", "nommee directrice",
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
    # NEW: Webinaire events
    "j-5 avant notre webinaire", "j-4 avant notre webinaire", "j-3 avant notre webinaire",
    "participez a notre webinaire", "prochain webinaire",
    "strategies de recouvrement", "strategie de recouvrement",
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
    # Events/Competitions (not job offers)
    "defi ", "finale", "competition", "concours", "challenge",
    "equipes finalistes", "grande finale", "edition du defi",
    "jury preside par", "jury sera preside",
    "hackathon", "prix ", "trophee",
    # Academic/Exam results (not job offers)
    "felicitations aux etudiants", "admis au concours", "admis a l examen",
    "reussite au", "resultats du concours", "resultats de l examen",
    "crfpa", "iej", "ecole nationale de la magistrature",
    "fiere de leur reussite", "fiers de leur reussite",
    "plein succes dans la suite", "bonne chance a tous",
    # NEW: From CSV analysis - personal achievement posts
    "tres fier de nos", "tres fiere de nos",
    "nul doute que cette experience",
    "fier de nos etudiantes", "fiere de nos etudiantes",
    # Publications/Articles (not job offers)
    "je suis ravi de partager avec vous l article",
    "article recent publie", "publication de",
    "notre dernier article", "nouvel article",
    # NEW: SEO/Marketing content (not job offers)
    "sites que j audite", "taux de conversion", "contenu optimise seo",
    "seo", "referencement", "conversion rate", "marketing digital",
    "intention de recherche", "search intent",
    # NEW: Personal reconversion stories (not job offers)
    "il y a quelques annees j ai pris une decision audacieuse",
    "me reconvertir dans", "reconversion professionnelle",
    "j ai pris la decision de changer", "changement de carriere",
    "ma reconversion", "nouvelle vie professionnelle",
    # NEW: Salon/Congress events (not job offers)
    "salon commerce innov", "salon de", "congres des", "congres national",
    "tres agreable journee de salon", "journee de salon",
    "journee du congres", "congres consulaires",
    "deuxieme journee du congres", "congres des juges",
    "quel plaisir de voir notre ville accueillir",
    # NEW: Photo shooting posts (not job offers)
    "j ai eu le plaisir de realiser le shooting", "shooting photo",
    "seance photo", "reportage photo",
    "valoriser chaque personne", "photographe professionnel",
    # NEW: Real estate sales (not job offers)
    "vends ", "a vendre", "vente immobiliere", "lot de 414 m",
    "990.000", "hyper centre", "r+1 & r+2", "bureau a vendre",
    "chef de projet immobilier", "investissement immobilier accompagne",
    "gestion de projets de renovation", "invest preneur",
    # NEW: Formation announcements
    "france services cadillac", "formation au tribunal",
    "formation juridique", "session de formation",
    # NEW: Property/Real estate market articles
    "un bien renove se vend", "ameliorer le dpe",
    "marche parisien", "prix au m2",
    # NEW: Visa/immigration personal stories
    "renouvlement de mon titre de sejour", "histoire de visa",
    "marathon administratif", "titre de sejour",
    # NEW: Notaires DPE context
    "les notaires de france le confirment",
    # Posts with only a link (no real content)
    "https://lnkd.in",  # LinkedIn shortened links as main content
    # Personal stories without recruitment
    "mon histoire", "mon parcours personnel",
    "retour d experience", "partage d experience",
    # ADV/Commercial roles (not legal)
    "gestionnaire adv", "assistant adv", "charge adv",
    "administration des ventes",
    # Business Developer roles (not legal)
    "business developer", "business developper",
    # Double diplomas/education announcements
    "double diplome", "dual degree",
    "double cursus", "parcours academique",
]

# Institutional announcements (not job offers)
EXCLUSION_INSTITUTIONAL = [
    # Cabinet/firm announcements without recruitment
    "inscrit dans l annuaire", "inscrit a l annuaire",
    "a maintenant sa toque", "a desormais sa toque",
    "inauguration de", "ouverture officielle",
    "ceremonie de", "ceremonie d",
    "anniversaire du cabinet", "ans d existence",
    "fete ses", "fete son",
    "nouveau bureau", "nouveaux locaux",
    "demenagement", "emmenagement",
    # Awards/Rankings (not recruitment)
    "classe parmi", "distingue par", "recompense",
    "palmares", "classement", "ranking",
    "meilleur cabinet", "top cabinet",
]

# Legal news and watch (not job offers)
EXCLUSION_LEGAL_NEWS = [
    # Legislative/Regulatory news
    "reforme de", "nouvelle loi", "projet de loi",
    "jurisprudence", "arret de la cour", "arret rendu",
    "decision de justice", "tribunal a juge",
    "code civil", "code penal", "code du travail",
    "droit europeen", "directive europeenne",
    "rgpd", "cnil", "autorite de",
    # Legal updates
    "flash info", "actualite juridique",
    "veille juridique", "legal news",
    "point sur", "decryptage", "analyse de",
    "commentaire de", "tribune",
    # Academic/Doctrine
    "doctrine", "these de", "memoire de",
    "colloque", "conference sur le droit",
]

# Client testimonials (not job offers)
EXCLUSION_TESTIMONIALS = [
    "temoignage client", "retour client",
    "merci a notre client", "accompagne dans",
    "mission realisee pour", "dossier gagne",
    "affaire remportee", "succes pour notre client",
    "nous avons accompagne", "fiers d avoir accompagne",
    "satisfaction client", "client satisfait",
]

# Networking posts without recruitment
EXCLUSION_NETWORKING = [
    "ravi de retrouver", "plaisir d echanger avec",
    "rencontre enrichissante", "echange passionnant",
    "petit dejeuner avec", "dejeuner avec",
    "afterwork", "cocktail",
    "networking", "soiree",
    "ravi d avoir rencontre", "bel echange",
    "discussion inspirante", "table ronde",
]

# =============================================================================
# NOUVELLES EXCLUSIONS RENFORCÉES (90% faux positifs détectés)
# =============================================================================

# EXCLUSION 1: Formation/Education (pas de recrutement)
EXCLUSION_FORMATION_EDUCATION = [
    # Annonces institutionnelles
    "toque", "a maintenant sa toque", "a obtenu sa toque",
    "inscription a l ordre", "inscrit dans l annuaire",
    "inscrit a l annuaire", "annuaire des avocats",
    "barreau", "ordre des avocats",
    
    # Diplômes et études
    "diplome", "diplome", "jeune diplome", "jeune diplomee",
    "ecole de droit", "universite", "faculte de droit",
    "master", "master ii", "master 2",
    "bar exam", "examen du barreau",
    "formation", "formation initiale", "formation continue",
    "etudiant", "etudiante", "etudiant en droit",
    "doctorat", "these", "recherche",
]

# EXCLUSION 2: Recrutement Passé (annonces terminées)
EXCLUSION_RECRUTEMENT_PASSE = [
    # Annonces de recrutement terminé
    "a rejoint", "vient de rejoindre", "a integre",
    "nous avons recrute", "nous avons embauche",
    "bienvenue a", "bienvenue au", "welcome",
    "nouveau collaborateur", "nouvelle recrue",
    "j ai le plaisir", "je suis heureuse", "je suis ravi",
    "je suis ravie", "je suis heureux",
    "felicitations", "felicitation", "bravo",
    "promotion", "promue", "promu",
    "nouvelle etape", "nouvelle aventure",
    "rejoins", "rejoint", "integre",
]

# EXCLUSION 3: Candidat Individu Cherchant Emploi
# IMPORTANT: Éviter les patterns génériques qui matchent les recruteurs
# Ex: "Je suis à la recherche d'un juriste" = RECRUTEUR, pas candidat
EXCLUSION_CANDIDAT_INDIVIDU = [
    # Candidat cherchant du travail - SPÉCIFIQUE
    "je recherche un nouveau poste", "je recherche un nouvel emploi",
    "je cherche un emploi", "je cherche un poste",
    "je suis a la recherche d un poste", "je suis a la recherche d un emploi",
    "je suis a la recherche d une opportunite",
    "je suis en recherche d emploi", "je suis en recherche de poste",
    "opentowork", "open to work", "hashtag opentowork",
    "vous serais reconnaissant", "vous serais reconnaissante",
    "vous serait reconnaissant", "vous serait reconnaissante",
    "merci de m aider", "merci de m'aider",
    "mon cv est disponible", "mon profil est disponible", 
    "je suis juriste disponible", "je suis avocat disponible", "je suis avocate disponible",
    "je suis notaire disponible", "je suis paralegal disponible",
    "mon parcours professionnel", "mon experience professionnelle",
]

# EXCLUSION 4: Contenu Informatif (Articles, Blogs, Webinaires)
EXCLUSION_CONTENU_INFORMATIF = [
    # Articles et publications
    "article", "blog", "publication", "publie",
    "etude", "rapport", "analyse", "avis",
    "commentaire", "reflexion", "point de vue",
    "partage", "partager", "partageons",
    "decouvrez", "decouvrez notre", "lire l article",
    
    # Webinaires et conférences
    "webinaire", "webinar", "conference", "seminaire",
    "atelier", "formation", "masterclass",
    "j-5 avant", "j-3 avant", "j-1 avant",
    "rendez-vous", "inscrivez-vous",
    
    # Contenus informatifs
    "quelques mots sur", "quelques mots sur l",
    "regards sur", "focus sur", "zoom sur",
    "infographie", "infographique",
    "chiffres cles", "chiffres cles",
    "tendances", "previsions", "previsions",
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
    "mandat de recrutement",
    # NOTE: "nous recrutons pour" retiré car trop de faux positifs
    # Ex: "Nous recrutons pour le poste de Notaire" = légitime
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
    STRICT: Calcule le score de recrutement ACTIF UNIQUEMENT.
    
    RÈGLE CRITIQUE:
    - Seul le recrutement ACTIF (maintenant) est accepté
    - Pas de simple mention du métier
    - Pas de recrutement passé ou futur vague
    
    Score >= 0.20 REQUIS (augmenté de 0.15)
    """
    matched = []
    normalized = normalize_text(text)
    
    # ========== SIGNAUX TRÈS FORTS (Recrutement ACTIF) ==========
    # Ces patterns indiquent une recherche ACTIVE maintenant
    very_strong_signals = [
        # Entreprise qui recrute MAINTENANT
        "nous recrutons", "on recrute", "notre equipe recrute",
        "notre cabinet recrute", "notre direction juridique recrute",
        "notre etude recrute", "etude notariale recrute",
        
        # Poste à pourvoir (MAINTENANT)
        "poste a pourvoir", "poste ouvert", "poste disponible",
        "cdi a pourvoir", "cdd a pourvoir",
        
        # Appel à candidature explicite
        "postulez", "candidatez", "envoyez votre cv",
        "adressez votre candidature", "merci d envoyer",
        
        # Anglais recrutement actif
        "we are hiring", "is hiring", "now hiring", "currently hiring",
        "we are looking for", "is looking for",
        
        # Spécifique aux 16 métiers
        "recrute un avocat", "recrute une avocate",
        "recrute un juriste", "recrute une juriste",
        "recrute un notaire", "recrute une notaire",
        "recrute un paralegal", "recrute une paralegale",
        "recrute un legal counsel", "recrute une legal counsel",
        "recrute un responsable juridique", "recrute une responsable juridique",
        "recrute un directeur juridique", "recrute une directrice juridique",
        "recrute un directeur fiscal", "recrute une directrice fiscale",
        "recrute un responsable fiscal", "recrute une responsable fiscale",
    ]
    
    very_strong_count = sum(1 for s in very_strong_signals if s in normalized)
    
    if very_strong_count == 0:
        # Vérifier les signaux forts avant de rejeter
        strong_signals_check = [
            "nous recherchons", "on recherche", "cdi", "cdd",
            "recherche un avocat", "recherche une avocate",
            "recherche un juriste", "recherche une juriste",
        ]
        has_strong = any(s in normalized for s in strong_signals_check)
        if not has_strong:
            # AUCUN signal fort = REJET
            return 0.0, []
    
    # Score de base pour signaux très forts
    score = 0.35 + min(0.35, very_strong_count * 0.15) if very_strong_count > 0 else 0.20
    
    # ========== SIGNAUX FORTS (Contexte recrutement clair) ==========
    strong_signals = [
        # Recherche active
        "nous recherchons", "on recherche",
        "recherche un avocat", "recherche une avocate",
        "recherche un juriste", "recherche une juriste",
        "recherche un notaire", "recherche une notaire",
        "recherche un paralegal", "recherche une paralegale",
        
        # Contrats
        "cdi", "cdd", "temps plein", "full time",
        
        # Création/Opportunité
        "creation de poste", "nouveau poste", "ouverture de poste",
        "opportunite a saisir",
        
        # Description de poste
        "profil recherche", "missions principales",
        "experience requise", "vous justifiez",
        
        # Anglais
        "join our team", "join the team",
    ]
    
    strong_count = sum(1 for s in strong_signals if s in normalized)
    if strong_count > 0:
        score += 0.15 + min(0.15, strong_count * 0.05)
        matched.extend([s for s in strong_signals if s in normalized])
    
    # ========== BONUS POUR PATTERN "[ENTREPRISE] RECRUTE" ==========
    # Pattern: "Cabinet ABC recrute" ou "Entreprise XYZ recrute"
    recrute_pattern = re.search(r'\b[a-z\s]+\s+recrute\b', normalized)
    if recrute_pattern:
        score += 0.15
        matched.append("[entreprise] recrute")
    
    # ========== MALUS POUR PREMIÈRE PERSONNE (Chasseur de têtes) ==========
    first_person_signals = ["je recrute", "je recherche", "je cherche"]
    if any(fp in normalized for fp in first_person_signals):
        # Première personne = potentiellement chasseur de têtes
        # Exiger des signaux TRÈS FORTS d'entreprise
        if very_strong_count < 2:
            return 0.0, []
        score = max(0, score - 0.20)
    
    # ========== VÉRIFIER QUE CE N'EST PAS UN CANDIDAT ==========
    job_seeker_signals = [
        "je recherche un poste", "je cherche un emploi",
        "disponible immediatement", "opentowork",
        "mon cv", "mon profil", "je suis juriste",
    ]
    if any(js in normalized for js in job_seeker_signals):
        return 0.0, []
    
    # ========== VÉRIFIER QUE LE RECRUTEMENT N'EST PAS TERMINÉ ==========
    recruitment_done_signals = [
        "a rejoint", "vient de rejoindre", "a integre",
        "nous avons recrute", "nous avons embauche",
        "bienvenue a", "welcome",
        "nouveau collaborateur", "nouvelle recrue",
    ]
    if any(rd in normalized for rd in recruitment_done_signals):
        return 0.0, []
    
    # Vérifier les signaux de recrutement génériques
    for signal in RECRUITMENT_SIGNALS:
        if signal in normalized and signal not in matched:
            matched.append(signal)
    
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
                # AMÉLIORATION: Vérifier si c'est un recruteur qui cherche un candidat
                # "je recherche un juriste" = recruteur, "je recherche un poste" = candidat
                recruiter_seeking_candidate = any(rp in normalized for rp in [
                    "je recherche un juriste", "je recherche une juriste",
                    "je recherche un avocat", "je recherche une avocate",
                    "je recherche un paralegal", "je recherche un notaire",
                    "je suis a la recherche d un juriste", "je suis a la recherche d une juriste",
                    "je suis a la recherche d un avocat", "je suis a la recherche d une avocate",
                    "a la recherche d un juriste", "a la recherche d une juriste",
                    "a la recherche d un avocat", "a la recherche d une avocate",
                    "nous recrutons", "on recrute", "recrute un", "recrute une",
                    "poste a pourvoir", "poste de juriste", "poste d avocat",
                    "cdi a pourvoir", "cdd a pourvoir", "postulez", "candidatez",
                ])
                
                if recruiter_seeking_candidate:
                    continue  # C'est un recruteur, ne pas exclure
                
                # Vérifier les signaux de chercheur d'emploi
                candidate_signals = any(fp in normalized for fp in [
                    "je recherche un poste", "je recherche un emploi",
                    "je cherche un poste", "je cherche un emploi",
                    "mon cv", "mon profil est disponible",
                    "je suis juriste", "je suis avocat", "je suis avocate",
                    "disponible immediatement", "disponible des maintenant",
                ])
                
                if candidate_signals:
                    return ExclusionResult(True, "chercheur_emploi", [term])
    
    # 4b. Recruitment already done - Exclude welcome/arrival announcements
    if config.exclude_opentowork:  # Reuse same config flag
        for term in EXCLUSION_RECRUITMENT_DONE:
            if term in normalized:
                # This is announcing someone ALREADY hired, not an active job posting
                return ExclusionResult(True, "recrutement_termine", [term])
    
    # 5. Institutional posts (no recruitment)
    if config.exclude_promo:
        matched_institutional = [term for term in EXCLUSION_INSTITUTIONAL if term in normalized]
        if matched_institutional:
            has_recruitment = any(sig in normalized for sig in [
                "recrute", "recruiting", "hiring", "poste a pourvoir"
            ])
            if not has_recruitment:
                return ExclusionResult(True, "post_institutionnel", matched_institutional)
    
    # 5b. Legal news (not job offers)
    if config.exclude_promo:
        matched_legal_news = [term for term in EXCLUSION_LEGAL_NEWS if term in normalized]
        if matched_legal_news:
            has_recruitment = any(sig in normalized for sig in [
                "recrute", "recruiting", "hiring", "poste a pourvoir", "cdi", "cdd"
            ])
            if not has_recruitment:
                return ExclusionResult(True, "veille_juridique", matched_legal_news)
    
    # 5c. Client testimonials
    if config.exclude_promo:
        matched_testimonials = [term for term in EXCLUSION_TESTIMONIALS if term in normalized]
        if matched_testimonials:
            has_recruitment = any(sig in normalized for sig in [
                "recrute", "recruiting", "hiring", "poste a pourvoir"
            ])
            if not has_recruitment:
                return ExclusionResult(True, "temoignage_client", matched_testimonials)
    
    # 5d. Networking posts
    if config.exclude_promo:
        matched_networking = [term for term in EXCLUSION_NETWORKING if term in normalized]
        if matched_networking:
            has_recruitment = any(sig in normalized for sig in [
                "recrute", "recruiting", "hiring", "poste a pourvoir", "cdi", "cdd"
            ])
            if not has_recruitment:
                return ExclusionResult(True, "post_networking", matched_networking)
    
    # ==========================================================================
    # NOUVELLES EXCLUSIONS RENFORCÉES (réduction 90% faux positifs)
    # ==========================================================================
    
    # 5h. Formation/Education (not recruitment)
    if config.exclude_formation_education:
        matched_formation = [term for term in EXCLUSION_FORMATION_EDUCATION if term in normalized]
        if matched_formation:
            has_recruitment = any(sig in normalized for sig in [
                "recrute", "recherche", "poste a pourvoir", "cdi", "cdd"
            ])
            if not has_recruitment:
                return ExclusionResult(True, "formation_education", matched_formation)
    
    # 5i. Recrutement Passé (not active recruitment)
    if config.exclude_recrutement_passe:
        matched_passe = [term for term in EXCLUSION_RECRUTEMENT_PASSE if term in normalized]
        if matched_passe:
            has_active_recruitment = any(sig in normalized for sig in [
                "nous recrutons", "on recrute", "poste a pourvoir",
                "cdi a pourvoir", "cdd a pourvoir", "postulez"
            ])
            if not has_active_recruitment:
                return ExclusionResult(True, "recrutement_passe", matched_passe)
    
    # 5j. Candidat Individu Cherchant Emploi
    if config.exclude_candidat_individu:
        matched_candidat = [term for term in EXCLUSION_CANDIDAT_INDIVIDU if term in normalized]
        if matched_candidat:
            return ExclusionResult(True, "candidat_individu", matched_candidat)
    
    # 5k. Contenu Informatif (Articles, Blogs, Webinaires)
    if config.exclude_contenu_informatif:
        matched_info = [term for term in EXCLUSION_CONTENU_INFORMATIF if term in normalized]
        if matched_info:
            has_recruitment = any(sig in normalized for sig in [
                "recrute", "recherche", "poste a pourvoir", "cdi", "cdd",
                "postulez", "candidatez"
            ])
            if not has_recruitment:
                return ExclusionResult(True, "contenu_informatif", matched_info)
    
    # 5e. Promotional content - more lenient
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
    
    # 5f. Emotional/Personal posts
    if config.exclude_emotional:
        matched_emotional = [term for term in EXCLUSION_EMOTIONAL if term in normalized]
        if matched_emotional:
            # Don't exclude if clear recruitment signal
            has_recruitment = any(sig in normalized for sig in [
                "recrute", "cdi", "cdd", "poste a pourvoir", "hiring",
                "nous recherchons", "on recherche"
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
    
    # 9. Short posts without explicit recruitment signal
    # Posts < 150 chars need a VERY explicit recruitment signal
    if len(normalized) < 150:
        explicit_signals = [
            "nous recrutons", "on recrute", "poste a pourvoir",
            "cdi", "cdd", "hiring", "postulez"
        ]
        has_explicit = any(sig in normalized for sig in explicit_signals)
        if not has_explicit:
            # Check if it's just a link share
            if "https" in normalized or "lnkd.in" in normalized:
                return ExclusionResult(True, "post_trop_court", ["lien sans contexte"])
    
    # 10. Check for coherence: if recruitment mentioned, ensure it's for a legal job
    recruitment_words = ["recrute", "recherche", "recherchons", "poste de", "poste d"]
    has_recruitment_context = any(word in normalized for word in recruitment_words)
    
    if has_recruitment_context:
        legal_job_titles = [
            "juriste", "avocat", "notaire", "paralegal", "legal",
            "juridique", "counsel", "clerc", "fiscaliste", "compliance"
        ]
        has_legal_job = any(job in normalized for job in legal_job_titles)
        
        # If recruiting but no legal job mentioned, exclude
        if not has_legal_job:
            # Check for non-legal job titles being recruited
            non_legal_jobs = [
                "marketing", "commercial", "finance", "rh", "developpeur",
                "comptable", "gestionnaire", "assistant administratif",
                "chef de projet", "product manager", "data"
            ]
            recruited_non_legal = any(job in normalized for job in non_legal_jobs)
            if recruited_non_legal:
                return ExclusionResult(True, "recrutement_non_juridique", ["poste non juridique"])
    
    return ExclusionResult(False, "", [])


# =============================================================================
# TARGET JOBS - LES 16 MÉTIERS JURIDIQUES CIBLES
# =============================================================================

TARGET_JOBS_16 = {
    "avocat collaborateur": ["avocat collaborateur", "avocate collaboratrice"],
    "avocat associé": ["avocat associe", "avocate associee"],
    "avocat counsel": ["avocat counsel", "avocate counsel"],
    "paralegal": ["paralegal", "paralegale", "assistant juridique", "assistante juridique"],
    "legal counsel": ["legal counsel"],
    "juriste": ["juriste"],
    "responsable juridique": ["responsable juridique"],
    "directeur juridique": ["directeur juridique", "directrice juridique"],
    "notaire stagiaire": ["notaire stagiaire"],
    "notaire associé": ["notaire associe", "notaire associee"],
    "notaire salarié": ["notaire salarie", "notaire salariee"],
    "notaire assistant": ["notaire assistant", "notaire assistante"],
    "clerc de notaire": ["clerc de notaire"],
    "rédacteur d'actes": ["redacteur d actes", "redacteur d'actes"],
    "responsable fiscal": ["responsable fiscal", "responsable fiscale"],
    "directeur fiscal": ["directeur fiscal", "directrice fiscale"],
}


def is_recruitment_agency_strict(text: str) -> Tuple[bool, str]:
    """
    DÉTECTION STRICTE DES CABINETS DE RECRUTEMENT.
    
    Retourne: (is_agency, reason)
    
    RÈGLE: Si c'est une agence de recrutement = REJET IMMÉDIAT
    
    ATTENTION: Ne pas confondre:
    - "cabinet de recrutement" (agence) vs "cabinet d'avocats" (entreprise légitime)
    - "cabinet juridique" est une entreprise légitime
    """
    normalized = normalize_text(text)
    
    # ========== VÉRIFIER D'ABORD SI C'EST UN CABINET JURIDIQUE LÉGITIME ==========
    # Ces termes indiquent une entreprise juridique, pas une agence de recrutement
    legitimate_legal_firms = [
        "cabinet d avocat", "cabinet d'avocat", "cabinet avocat",
        "cabinet juridique", "cabinet legal",
        "etude notariale", "etude de notaire",
        "direction juridique", "service juridique",
    ]
    is_legal_firm = any(lf in normalized for lf in legitimate_legal_firms)
    
    # ========== CABINETS DE RECRUTEMENT CONNUS ==========
    known_agencies = [
        # Cabinets juridiques spécialisés (RECRUTEMENT)
        "fed legal", "fed juridique",
        "michael page", "page group", "page personnel",
        "walters people", "robert walters",
        "hays",
        
        # Autres grands cabinets de recrutement
        "robert half", "expectra", "adecco", "manpower", "randstad",
        "spring professional", "lincoln associates", "laurence simons",
        "taylor root", "morgan philips", "spencer stuart",
        "russell reynolds", "egon zehnder", "korn ferry",
        "boyden", "heidrick struggles", "odgers berndtson",
        
        # Termes explicites d'agence de recrutement
        "cabinet de recrutement", "cabinet recrutement",
        "agence de recrutement", "agence recrutement",
        "chasseur de tetes", "chasseuse de tetes",
        "headhunter", "executive search",
    ]
    
    for agency in known_agencies:
        if agency in normalized:
            # Si c'est aussi un cabinet juridique légitime, ne pas exclure
            if is_legal_firm and agency not in ["cabinet de recrutement", "cabinet recrutement", 
                                                   "agence de recrutement", "agence recrutement"]:
                continue
            return True, f"Cabinet connu: {agency}"
    
    # ========== PATTERNS DE RECRUTEMENT INDIRECT ==========
    # Ces patterns indiquent une agence qui recrute POUR quelqu'un d'autre
    indirect_patterns = [
        # "Pour notre client"
        "pour notre client", "pour l un de nos clients",
        "pour l une de nos clientes", "pour le compte de",
        "pour le compte d un client", "pour le compte d une cliente",
        
        # "Client confidentiel"
        "client confidentiel", "societe confidentielle",
        "entreprise confidentielle",
        
        # "Mandat de recrutement"
        "mandat de recrutement",
        # NOTE: "nous recrutons pour" retiré car trop de faux positifs
        # Ex: "Nous recrutons pour le poste de Notaire" = légitime
        
        # "Au nom de" (attention: pas "pour le compte de notre cabinet")
        "au nom de notre client",
    ]
    
    indirect_count = sum(1 for p in indirect_patterns if p in normalized)
    
    if indirect_count >= 1:
        # Vérifier qu'il y a AUSSI un signal d'entreprise directe
        direct_company_signals = [
            "notre equipe", "notre cabinet", "notre direction",
            "notre etude", "notre groupe", "notre societe",
            "notre entreprise", "notre organisation",
        ]
        
        has_direct_signal = any(ds in normalized for ds in direct_company_signals)
        
        # Si c'est un cabinet juridique avec "notre cabinet", c'est légitime
        if is_legal_firm and has_direct_signal:
            return False, ""
        
        if not has_direct_signal:
            return True, "Recrutement indirect (pour un client)"
    
    # ========== PATTERNS SUSPECTS D'AGENCE ==========
    # Ces patterns suggèrent une agence même sans mention explicite
    # ATTENTION: Réduire les faux positifs
    agency_suspicious_patterns = [
        # Langage très générique d'agence uniquement
        "nous recherchons un profil pour",
        "candidat ideal pour notre client",
    ]
    
    suspicious_count = sum(1 for p in agency_suspicious_patterns if p in normalized)
    
    # Si patterns suspects ET pas de cabinet juridique
    if suspicious_count >= 1 and not is_legal_firm:
        has_direct_signal = any(ds in normalized for ds in [
            "notre equipe", "notre cabinet", "notre direction",
            "notre etude", "notre groupe",
        ])
        
        if not has_direct_signal:
            return True, "Patterns suspects d'agence"
    
    return False, ""


def detect_specialized_job_info(text: str) -> dict:
    """
    Détecte les informations spécialisées sur le poste.
    
    Retourne:
        dict avec:
        - target_jobs: List des 16 métiers détectés
        - specializations: List des spécialisations (droit social, etc.)
        - experience_levels: List des niveaux d'expérience
    """
    normalized = normalize_text(text)
    
    # Détecter les 16 métiers cibles
    target_jobs = []
    for job_name, keywords in TARGET_JOBS_16.items():
        if any(keyword in normalized for keyword in keywords):
            target_jobs.append(job_name)
    
    # Si aucun métier spécifique, vérifier les termes génériques
    if not target_jobs:
        generic_terms = {
            "juriste": ["juriste"],
            "avocat": ["avocat", "avocate"],
            "notaire": ["notaire"],
            "paralegal": ["paralegal", "paralegale"],
        }
        for job_name, keywords in generic_terms.items():
            if any(keyword in normalized for keyword in keywords):
                target_jobs.append(job_name)
    
    # Détecter les spécialisations
    specializations = []
    spec_keywords = {
        "droit social": ["droit social", "droit du travail"],
        "droit des affaires": ["droit des affaires", "business law"],
        "droit fiscal": ["droit fiscal", "fiscalite"],
        "droit immobilier": ["droit immobilier", "real estate"],
        "droit de la propriété intellectuelle": ["propriete intellectuelle", "ip", "brevets"],
        "droit pénal": ["droit penal", "penal"],
        "droit public": ["droit public"],
        "droit des contrats": ["droit des contrats", "contrats"],
        "contentieux": ["contentieux"],
        "compliance": ["compliance", "conformite"],
        "corporate": ["corporate", "m&a", "fusions acquisitions"],
    }
    for spec_name, keywords in spec_keywords.items():
        if any(keyword in normalized for keyword in keywords):
            specializations.append(spec_name)
    
    # Détecter les niveaux d'expérience
    experience_levels = []
    exp_keywords = {
        "junior": ["junior", "debutant", "0-2 ans"],
        "confirmé": ["confirme", "3-5 ans", "3 a 5 ans"],
        "senior": ["senior", "experimente", "5+ ans", "10+ ans"],
        "manager": ["manager", "responsable", "directeur"],
    }
    for exp_name, keywords in exp_keywords.items():
        if any(keyword in normalized for keyword in keywords):
            experience_levels.append(exp_name)
    
    return {
        "target_jobs": target_jobs,
        "specializations": specializations,
        "experience_levels": experience_levels,
    }


def is_first_person_post(text: str) -> bool:
    """
    Détecte si le post est écrit à la première personne par un CANDIDAT cherchant emploi.
    
    Ces posts sont typiquement des candidats qui cherchent du travail,
    pas des entreprises qui recrutent.
    
    AMÉLIORATION: On vérifie si c'est un candidat cherchant du travail,
    PAS un recruteur qui parle à la première personne.
    """
    normalized = normalize_text(text)
    
    # EXCLUSION: Si c'est clairement un recruteur qui parle, NE PAS exclure
    recruiter_patterns = [
        "nous recrutons", "on recrute", "je suis a la recherche d un juriste",
        "je suis a la recherche d une juriste", "je suis a la recherche d un avocat",
        "je suis a la recherche d une avocate", "je recherche un juriste",
        "je recherche une juriste", "je recherche un avocat", "je recherche une avocate",
        "je recherche un paralegal", "je recherche un notaire",
        "poste a pourvoir", "cdi a pourvoir", "cdd a pourvoir",
        "postulez", "candidatez", "envoyez votre cv",
        "rejoindre notre equipe", "rejoindre mon equipe",
        "recrute un", "recrute une", "pour notre cabinet",
    ]
    
    if any(pattern in normalized for pattern in recruiter_patterns):
        return False  # C'est un recruteur, pas un candidat
    
    # Patterns de candidats cherchant du travail
    candidate_patterns = [
        "je recherche un poste", "je recherche un emploi",
        "je cherche un poste", "je cherche un emploi", 
        "je suis en recherche active", "je suis en recherche d emploi",
        "je suis a la recherche d un poste", "je suis a la recherche d un emploi",
        "opentowork", "open to work",
        "mon cv", "mon profil est disponible",
        "je suis juriste disponible", "je suis avocat disponible", 
        "je suis avocate disponible",
        "je me permets de vous contacter", "je suis actuellement a l ecoute",
    ]
    
    return any(pattern in normalized for pattern in candidate_patterns)


def is_coherent_legal_recruitment(text: str) -> bool:
    """
    STRICT: Vérifie que le recrutement concerne BIEN un des 16 métiers.
    
    Rejette les posts qui parlent d'un métier juridique SANS recrutement,
    ou qui recrutent pour un autre métier (ex: courtier, commercial).
    """
    normalized = normalize_text(text)
    
    # ÉTAPE 0: Vérifier si c'est un recrutement pour un métier NON-juridique
    # Ces métiers ne sont PAS des cibles même s'ils mentionnent "notaire" dans le contexte
    non_legal_recruitment_patterns = [
        # Courtiers, agents immobiliers, commerciaux
        "recrutons de nouveaux courtiers", "recrutons des courtiers",
        "recrute des courtiers", "recrute un courtier", "recrute une courtiere",
        "devenir courtier", "devenir agent immobilier",
        "recrutons des commerciaux", "recrute des commerciaux",
        "recrute un commercial", "recrute une commerciale",
        "agent commercial", "agente commerciale", "agents commerciaux",
        "agent e commercial", "commercial e en immobilier",  # variantes inclusives
        "conseiller commercial", "conseillere commerciale",
        "negociateur immobilier", "negociatrice immobiliere",
        # Contexte immobilier où "notaire" est mentionné mais pas recruté
        "au notaire", "chez le notaire",  # "piloter le cycle de vente... au notaire"
        "signature chez le notaire", "acte chez le notaire",
        "rendez-vous chez le notaire", "rdv chez le notaire",
        "passage chez le notaire", "frais de notaire", "frais de notaires",
        "honoraires de notaire", "honoraires du notaire",
        "office du notaire",
        # Agents et conseillers (non juridiques)
        "recrute des conseillers", "recrutons des conseillers",
        "recrute un conseiller", "recrute une conseillere",
        "recrute des agents", "recrutons des agents",
        # Contexte où "notaire" est juste mentionné comme référence
        "ne m appelez plus", "frais de notaire",  # articles d'opinion
    ]
    
    if any(pattern in normalized for pattern in non_legal_recruitment_patterns):
        return False
    
    # Vérifier si un des 16 métiers est mentionné
    target_job_found = False
    found_job = None
    for job_name, keywords in TARGET_JOBS_16.items():
        if any(keyword in normalized for keyword in keywords):
            target_job_found = True
            found_job = job_name
            break
    
    # Si aucun des 16 métiers spécifiques, vérifier les termes génériques
    if not target_job_found:
        generic_legal_jobs = ["juriste", "avocat", "avocate", "notaire", "paralegal", "paralegale", 
                              "legal counsel", "counsel", "clerc", "fiscaliste",
                              "directeur juridique", "directrice juridique",
                              "responsable juridique", "directeur fiscal", "directrice fiscale"]
        for term in generic_legal_jobs:
            if term in normalized:
                target_job_found = True
                found_job = term
                break
    
    if not target_job_found:
        return False
    
    # Vérifier qu'il y a un signal de recrutement
    recruitment_words = [
        "recrute", "recrutons", "recherche", "recherchons",
        "poste", "cdi", "cdd", "hiring"
    ]
    has_recruitment = any(word in normalized for word in recruitment_words)
    
    if not has_recruitment:
        # Métier mentionné SANS recrutement = REJET
        return False
    
    # Vérifier que le poste recruté est bien un des 16 métiers
    # (pas un autre métier dans la même entreprise)
    non_legal_jobs = [
        "developpeur", "developer", "data scientist",
        "marketing manager", "commercial",
        "comptable", "assistant administratif",
    ]
    
    # Si un métier non-juridique est mentionné dans le contexte de recrutement
    for non_legal in non_legal_jobs:
        if non_legal in normalized:
            # Vérifier si c'est le FOCUS du recrutement (après "recrute" ou "recherche")
            # Chercher le pattern "recrute/recherche [quelques mots] métier non-juridique"
            pattern = rf"(recrute|recherche|recherchons)\s+(?:un|une)?\s*{non_legal}"
            if re.search(pattern, normalized):
                return False
    
    return True


# =============================================================================
# MAIN FILTER FUNCTION
# =============================================================================

@dataclass
class FilterResult:
    """Résultat du filtrage avec raison détaillée."""
    is_valid: bool
    recruitment_score: float
    legal_score: float
    total_score: float
    exclusion_reason: str
    exclusion_terms: List[str]
    matched_professions: List[str]
    matched_signals: List[str]
    # Nouveaux champs pour les 16 métiers
    target_jobs: List[str] = field(default_factory=list)
    specializations: List[str] = field(default_factory=list)
    experience_levels: List[str] = field(default_factory=list)
    confidence_score: float = 0.0
    
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
            "target_jobs": self.target_jobs,
            "specializations": self.specializations,
            "experience_levels": self.experience_levels,
            "confidence_score": self.confidence_score,
        }
    
    def get_rejection_reason(self) -> str:
        """Retourne la raison du rejet en français clair."""
        reasons = {
            "cabinet_recrutement": "❌ Cabinet de recrutement détecté (concurrent)",
            "recrutement_insuffisant": "❌ Pas de signal de recrutement actif",
            "score_insuffisant_recrutement": "❌ Pas de signal de recrutement actif",
            "metier_non_cible": "❌ Aucun des 16 métiers cibles détecté",
            "recrutement_non_juridique": "❌ Recrutement pour un métier non-juridique",
            "metier_insuffisant": "❌ Score juridique insuffisant",
            "score_insuffisant_juridique": "❌ Score juridique insuffisant",
            "score_insuffisant_recrutement_et_juridique": "❌ Score recrutement et juridique insuffisants",
            "hors_france": "❌ Localisation hors France",
            "stage_alternance": "❌ Stage/Alternance (hors scope)",
            "freelance_mission": "❌ Freelance/Mission (pas d'embauche directe)",
            "chercheur_emploi": "❌ Candidat cherchant du travail (#OpenToWork)",
            "post_emotionnel": "❌ Post émotionnel sans recrutement",
            "veille_juridique": "❌ Veille juridique/Actualité (pas d'offre)",
            "post_institutionnel": "❌ Annonce institutionnelle (pas d'offre)",
            "temoignage_client": "❌ Témoignage client (pas d'offre)",
            "post_networking": "❌ Post networking (pas d'offre)",
            "recrutement_termine": "❌ Recrutement déjà terminé (annonce d'arrivée)",
            "post_trop_ancien": "❌ Post trop ancien (> 3 semaines)",
            "post_trop_court": "❌ Post trop court sans signal explicite",
            "texte_vide": "❌ Texte vide",
            "contenu_promotionnel": "❌ Contenu promotionnel (pas d'offre)",
            "contenu_sponsorise": "❌ Contenu sponsorisé",
            "metier_non_juridique": "❌ Métier non-juridique recruté",
            # NOUVELLES RAISONS DE REJET (réduction 90% faux positifs)
            "formation_education": "❌ Formation/Éducation (pas d'offre d'emploi)",
            "recrutement_passe": "❌ Recrutement passé/terminé (bienvenue à...)",
            "candidat_individu": "❌ Candidat individuel cherchant emploi",
            "contenu_informatif": "❌ Contenu informatif (article, blog, webinaire)",
        }
        return reasons.get(self.exclusion_reason, f"❌ Rejeté: {self.exclusion_reason}")
    
    # ==========================================================================
    # PROPRIÉTÉS DE RÉTROCOMPATIBILITÉ (pour tests existants)
    # ==========================================================================
    
    @property
    def has_cdi_cdd(self) -> bool:
        """Rétrocompatibilité: retourne True si le post est valide (présume CDI/CDD)."""
        return self.is_valid
    
    @property
    def matched_contracts(self) -> List[str]:
        """Rétrocompatibilité: retourne liste de contrats détectés."""
        if self.is_valid:
            return ["CDI"]  # Par défaut si valide
        return []
    
    @property
    def relevance_score(self) -> float:
        """Rétrocompatibilité: retourne le score total."""
        return self.total_score
    
    @property
    def stages(self) -> List[str]:
        """Rétrocompatibilité: retourne liste vide (stages exclus par nouveau filtre)."""
        return []


@dataclass
class FilterConfig:
    """Configuration for the legal job post filter."""
    # Scoring thresholds - AUGMENTÉS pour stricte conformité (réduction faux positifs)
    recruitment_threshold: float = 0.35  # Augmenté de 0.20 à 0.35
    legal_threshold: float = 0.30  # Augmenté de 0.25 à 0.30
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
    # NOUVEAUX FLAGS POUR EXCLUSIONS RENFORCÉES (réduction 90% faux positifs)
    exclude_formation_education: bool = True
    exclude_recrutement_passe: bool = True
    exclude_candidat_individu: bool = True
    exclude_contenu_informatif: bool = True
    # Logging
    verbose: bool = True
    # Rétrocompatibilité (paramètres ignorés mais acceptés)
    require_fr_location: bool = True  # Alias pour exclude_foreign
    require_contract_type: bool = True  # Ignoré - toujours vérifié


# Default configuration
DEFAULT_FILTER_CONFIG = FilterConfig()


def is_legal_job_post(
    text: str,
    post_date: Optional[datetime] = None,
    log_exclusions: bool = True,
    config: Optional[FilterConfig] = None
) -> FilterResult:
    """
    STRICT: Détecte UNIQUEMENT les posts d'entreprises recrutant ACTIVEMENT
    pour les 16 métiers juridiques.
    
    REJETTE:
    1. Posts sans recrutement actif
    2. Posts de cabinets de recrutement
    3. Posts de candidats cherchant du travail
    4. Posts de formation/éducation sans offre
    5. Posts de recrutement passé/terminé
    6. Contenu informatif (articles, blogs, webinaires)
    
    Args:
        text: Raw post text
        post_date: Optional datetime of the post (for age filtering)
        log_exclusions: Whether to log exclusion reasons
        config: Optional FilterConfig for custom thresholds and exclusion toggles
        
    Returns:
        FilterResult with is_valid=True if post passes all filters
    """
    if config is None:
        config = DEFAULT_FILTER_CONFIG
        
    normalized = normalize_text(text)
    
    # Vérification texte vide
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
    
    # ========== ÉTAPE 0: VÉRIFIER QUE CE N'EST PAS UN CANDIDAT INDIVIDU ==========
    if config.exclude_candidat_individu and is_first_person_post(text):
        result = FilterResult(
            is_valid=False,
            recruitment_score=0.0,
            legal_score=0.0,
            total_score=0.0,
            exclusion_reason="candidat_individu",
            exclusion_terms=["Post écrit à la première personne"],
            matched_professions=[],
            matched_signals=[]
        )
        if log_exclusions and config.verbose:
            print("Post exclu [candidat_individu]: Post écrit à la première personne")
        return result
    
    # ========== ÉTAPE 1: VÉRIFIER QUE CE N'EST PAS UNE AGENCE ==========
    if config.exclude_agencies:
        is_agency, agency_reason = is_recruitment_agency_strict(text)
        if is_agency:
            result = FilterResult(
                is_valid=False,
                recruitment_score=0.0,
                legal_score=0.0,
                total_score=0.0,
                exclusion_reason="cabinet_recrutement",
                exclusion_terms=[agency_reason],
                matched_professions=[],
                matched_signals=[]
            )
            if log_exclusions and config.verbose:
                print(f"Post exclu [cabinet_recrutement]: {agency_reason}")
            return result
    
    # ========== ÉTAPE 2: VÉRIFIER LES EXCLUSIONS STANDARD ==========
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
    
    # ========== ÉTAPE 3: VÉRIFIER LE RECRUTEMENT ACTIF ==========
    recruitment_score, recruitment_matches = calculate_recruitment_score(text)
    
    # STRICT: Recrutement score DOIT être >= threshold
    if recruitment_score < config.recruitment_threshold:
        result = FilterResult(
            is_valid=False,
            recruitment_score=recruitment_score,
            legal_score=0.0,
            total_score=0.0,
            exclusion_reason="score_insuffisant_recrutement",
            exclusion_terms=[f"score: {recruitment_score:.2f} < {config.recruitment_threshold}"],
            matched_professions=[],
            matched_signals=recruitment_matches
        )
        if log_exclusions and config.verbose:
            print(
                f"Post exclu [recrutement_insuffisant]: "
                f"score={recruitment_score:.2f} (min {config.recruitment_threshold})"
            )
        return result
    
    # ========== ÉTAPE 4: VÉRIFIER QUE C'EST UN DES 16 MÉTIERS ==========
    specialized_info = detect_specialized_job_info(text)
    
    if not specialized_info['target_jobs']:
        # Aucun des 16 métiers détecté
        result = FilterResult(
            is_valid=False,
            recruitment_score=recruitment_score,
            legal_score=0.0,
            total_score=0.0,
            exclusion_reason="metier_non_cible",
            exclusion_terms=["Aucun des 16 métiers cibles"],
            matched_professions=[],
            matched_signals=recruitment_matches
        )
        if log_exclusions and config.verbose:
            print("Post exclu [metier_non_cible]: Aucun des 16 métiers cibles détecté")
        return result
    
    # ========== ÉTAPE 5: VÉRIFIER LA COHÉRENCE RECRUTEMENT + MÉTIER ==========
    if not is_coherent_legal_recruitment(text):
        result = FilterResult(
            is_valid=False,
            recruitment_score=recruitment_score,
            legal_score=0.0,
            total_score=0.0,
            exclusion_reason="recrutement_non_juridique",
            exclusion_terms=["Recrutement ne concerne pas un métier juridique"],
            matched_professions=[],
            matched_signals=recruitment_matches
        )
        if log_exclusions and config.verbose:
            print("Post exclu [recrutement_non_juridique]: Le recrutement ne concerne pas un des 16 métiers")
        return result
    
    # ========== ÉTAPE 6: CALCULER LES SCORES ==========
    legal_score, legal_matches = calculate_legal_profession_score(text)
    
    # STRICT: Legal score DOIT être >= threshold
    if legal_score < config.legal_threshold:
        result = FilterResult(
            is_valid=False,
            recruitment_score=recruitment_score,
            legal_score=legal_score,
            total_score=(legal_score * 0.5) + (recruitment_score * 0.5),
            exclusion_reason="score_insuffisant_juridique",
            exclusion_terms=[f"score: {legal_score:.2f} < {config.legal_threshold}"],
            matched_professions=legal_matches,
            matched_signals=recruitment_matches,
            target_jobs=specialized_info['target_jobs'],
            specializations=specialized_info['specializations'],
            experience_levels=specialized_info['experience_levels']
        )
        if log_exclusions and config.verbose:
            print(
                f"Post exclu [score_insuffisant_juridique]: "
                f"score={legal_score:.2f} (min {config.legal_threshold})"
            )
        return result
    
    # ========== ÉTAPE 7: VÉRIFIER LA LOCALISATION ==========
    if config.exclude_foreign:
        france_indicators = [
            "france", "paris", "lyon", "marseille", "bordeaux",
            "toulouse", "nantes", "lille", "strasbourg", "nice",
            "rennes", "grenoble", "montpellier", "la defense",
        ]
        has_france = any(f in normalized for f in france_indicators)
        
        foreign_indicators = [
            "canada", "usa", "belgique", "suisse", "uk",
            "allemagne", "espagne", "italie", "singapour",
        ]
        has_foreign = any(f in normalized for f in foreign_indicators)
        
        if has_foreign and not has_france:
            result = FilterResult(
                is_valid=False,
                recruitment_score=recruitment_score,
                legal_score=legal_score,
                total_score=(legal_score * 0.5) + (recruitment_score * 0.5),
                exclusion_reason="hors_france",
                exclusion_terms=["Localisation hors France détectée"],
                matched_professions=legal_matches,
                matched_signals=recruitment_matches,
                target_jobs=specialized_info['target_jobs'],
                specializations=specialized_info['specializations'],
                experience_levels=specialized_info['experience_levels']
            )
            if log_exclusions and config.verbose:
                print("Post exclu [hors_france]: Localisation hors France")
            return result
    
    # ========== ÉTAPE 8: ACCEPTER LE POST ==========
    total_score = (legal_score * 0.5) + (recruitment_score * 0.5)
    confidence_score = min(legal_score, recruitment_score)
    
    if log_exclusions:
        logger.debug(
            f"Post accepté: recruitment_score={recruitment_score:.2f}, "
            f"legal_score={legal_score:.2f}, "
            f"professions={legal_matches}, signals={recruitment_matches}, "
            f"target_jobs={specialized_info['target_jobs']}"
        )
    
    return FilterResult(
        is_valid=True,
        recruitment_score=recruitment_score,
        legal_score=legal_score,
        total_score=total_score,
        exclusion_reason="",
        exclusion_terms=[],
        matched_professions=legal_matches,
        matched_signals=recruitment_matches,
        target_jobs=specialized_info['target_jobs'],
        specializations=specialized_info['specializations'],
        experience_levels=specialized_info['experience_levels'],
        confidence_score=confidence_score
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
    # Nouvelles fonctions pour détection stricte
    "is_recruitment_agency_strict",
    "is_coherent_legal_recruitment",
    "detect_specialized_job_info",
    "is_first_person_post",  # NOUVEAU
    "TARGET_JOBS_16",
    # Listes de données
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
    "EXCLUSION_INSTITUTIONAL",
    "EXCLUSION_LEGAL_NEWS",
    "EXCLUSION_TESTIMONIALS",
    "EXCLUSION_NETWORKING",
    # NOUVELLES LISTES D'EXCLUSION (réduction 90% faux positifs)
    "EXCLUSION_FORMATION_EDUCATION",
    "EXCLUSION_RECRUTEMENT_PASSE",
    "EXCLUSION_CANDIDAT_INDIVIDU",
    "EXCLUSION_CONTENU_INFORMATIF",
    "DEFAULT_FILTER_CONFIG",
]
