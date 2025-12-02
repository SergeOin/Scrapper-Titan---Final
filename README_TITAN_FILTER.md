# 🎯 Titan Partners - Scraper LinkedIn Juridique

## Objectif

Scraper LinkedIn conçu pour **Titan Partners**, cabinet de recrutement spécialisé dans les métiers juridiques. L'objectif est de collecter **au moins 50 posts pertinents en 7 heures** d'exécution (créneau 9h-17h30).

## Architecture des Modules

```
scraper/
├── __init__.py          # Exports principaux du package
├── bootstrap.py         # Configuration et contexte applicatif
├── worker.py            # Worker principal d'extraction LinkedIn
├── legal_filter.py      # Filtrage des offres d'emploi juridiques
├── legal_classifier.py  # Classification des intentions
├── linkedin.py          # Analyse spécifique LinkedIn (type auteur)
├── stats.py             # Statistiques et logging détaillé
└── utils.py             # Fonctions utilitaires

filters/
├── __init__.py          # Package des filtres
└── juridique.py         # Configuration mots-clés juridiques
```

## Règles de Filtrage

### ✅ Posts à Récupérer (Inclusions)

Un post est pertinent si **TOUS** les critères suivants sont respectés :

#### 1. Auteur = Entreprise
- ✅ Pages entreprise LinkedIn
- ❌ Agences de recrutement
- ❌ Cabinets RH
- ❌ Sociétés d'intérim
- ❌ Freelances / Indépendants

#### 2. Contenu = Recrutement Interne
Le post doit annoncer un poste **interne** à l'organisation.

Signaux positifs détectés :
- "nous recrutons", "on recrute", "je recrute"
- "nous cherchons", "on recherche"
- "poste à pourvoir", "opportunité"
- "CDI", "CDD" (hors stage/alternance)
- "rejoignez notre équipe"

#### 3. Domaine = Juridique
Le post doit cibler un profil juridique.

Mots-clés détectés :
- Juriste (toutes spécialisations)
- Avocat (collaborateur, associé, counsel)
- Legal counsel / Head of Legal
- Compliance officer / DPO
- Contract manager
- Notaire / Clerc de notaire
- Paralegal

### ❌ Posts Exclus (Exclusions)

#### 1. Recrutement Externe
- "Pour l'un de nos clients, nous cherchons…"
- "Notre client recrute…"

#### 2. Auteurs Recrutement
- Cabinets de recrutement (Michael Page, Hays, etc.)
- ESN / SSII
- RH externalisées

#### 3. Non-Recrutement
- Veille juridique / Articles
- Événements / Conférences
- Retours d'expérience
- Actualités

#### 4. Stage / Alternance
- Tous les stages
- Alternances
- Apprentissages
- V.I.E.

#### 5. Hors France
Posts ciblant d'autres pays (Suisse, Belgique, UK, etc.)

## Utilisation

### Configuration Simple

```python
from scraper import is_legal_job_post, FilterConfig

# Utiliser la config par défaut
result = is_legal_job_post(post_text)

if result.is_valid:
    print(f"✅ Post pertinent! Score: {result.total_score:.2f}")
else:
    print(f"❌ Exclu: {result.exclusion_reason}")
```

### Configuration Personnalisée

```python
from scraper import FilterConfig, is_legal_job_post

config = FilterConfig(
    recruitment_threshold=0.20,  # Seuil signal recrutement
    legal_threshold=0.25,        # Seuil signal juridique
    exclude_stage=True,          # Exclure stages
    exclude_agencies=True,       # Exclure agences recrutement
    exclude_foreign=True,        # Exclure hors France
    verbose=True                 # Logs détaillés
)

result = is_legal_job_post(post_text, config=config)
```

### Analyse LinkedIn Complète

```python
from scraper.linkedin import LinkedInPostAnalyzer, AuthorType

analyzer = LinkedInPostAnalyzer()

result = analyzer.analyze_post(
    text="Nous recrutons un juriste CDI à Paris...",
    author="Entreprise ABC",
    author_profile="https://linkedin.com/company/abc",
    post_date=datetime.now()
)

# Vérifier le type d'auteur
if result.author_type == AuthorType.COMPANY:
    print("✅ Post d'une entreprise")

# Vérifier le type de recrutement
if result.is_internal_recruitment:
    print("✅ Recrutement interne (pas une agence)")

# Score de pertinence
print(f"Score: {result.relevance_score:.2f}")
```

### Statistiques de Session

```python
from scraper.stats import ScraperStats

stats = ScraperStats(session_name="session_20251202")

# Pour chaque post trouvé
stats.record_post_found("juriste paris")

# Si filtré
stats.record_post_filtered(
    keyword="juriste paris",
    reason="stage_alternance",
    terms_found=["stage", "alternance"]
)

# Si accepté
stats.record_post_accepted(
    keyword="juriste paris",
    score=0.85,
    legal_keywords=["juriste", "cdi"],
    author="Entreprise XYZ"
)

# Rapport final
report = stats.generate_report()
print(f"Taux acceptation: {report.acceptance_rate:.0%}")
stats.save_report("exports/")
```

## Extension des Mots-clés

Pour ajouter de nouveaux mots-clés, modifier `filters/juridique.py` :

```python
from filters.juridique import get_default_config

config = get_default_config()

# Ajouter un nouveau rôle juridique
config.add_legal_role("chief legal officer")

# Ajouter un signal de recrutement
config.add_recruitment_signal("hiring now")

# Ajouter un pattern d'agence à exclure
config.add_agency_pattern("nouveau cabinet recrutement")
```

## Performance

### Objectif : 50+ posts en 7h

Configuration optimisée dans `bootstrap.py` :

```python
# Intervalle entre cycles
autonomous_worker_interval_seconds = 900  # 15 min

# Keywords ciblés recrutement juridique
scrape_keywords = [
    "recrute juriste",
    "recrute avocat", 
    "poste juriste",
    "cdi avocat",
    "direction juridique recrute",
    ...
]

# Filtres stricts activés
filter_legal_posts_only = True
filter_exclude_stage_alternance = True
filter_france_only = True
```

### Anti-Ban

- Mode human-like avec pauses aléatoires
- Throttling adaptatif
- Rotation des keywords
- Heures actives 6h-23h

## Logs et Monitoring

### Métriques Prometheus

- `scraper_posts_found_total` - Posts trouvés
- `scraper_posts_accepted_total` - Posts acceptés
- `scraper_posts_filtered_total` - Posts filtrés
- `legal_filter_accepted` - Passent le filtre légal
- `legal_filter_rejected{reason}` - Rejetés par raison

### Export des Statistiques

```bash
# Rapport JSON de session
exports/scraper_report_session_YYYYMMDD.json

# Historique des décisions (JSONL)
exports/filtering_decisions_session_YYYYMMDD.jsonl
```

## Commandes

```bash
# Lancer le scraper
python entrypoint.py

# Serveur web avec dashboard
python scripts/dev_server.py

# Script de démonstration
python scripts/example_titan_scraper.py

# Tests
pytest tests/ -v
```

## Structure des Données

### FilterResult

```python
@dataclass
class FilterResult:
    is_valid: bool              # Post pertinent ?
    recruitment_score: float    # Score recrutement (0-1)
    legal_score: float          # Score juridique (0-1)
    total_score: float          # Score combiné
    exclusion_reason: str       # Raison si exclu
    exclusion_terms: List[str]  # Termes déclencheurs
    matched_professions: List[str]  # Rôles juridiques détectés
    matched_signals: List[str]  # Signaux recrutement détectés
```

### PostAnalysisResult

```python
@dataclass
class PostAnalysisResult:
    author_type: AuthorType     # COMPANY, INDIVIDUAL, AGENCY
    is_internal_recruitment: bool
    is_external_recruitment: bool
    relevance: PostRelevance    # HIGH, MEDIUM, LOW, EXCLUDED
    relevance_score: float
    legal_keywords_found: List[str]
    recruitment_signals_found: List[str]
    is_excluded: bool
    exclusion_reason: str
```

## Licence

Usage interne Titan Partners uniquement. Respecter les conditions d'utilisation de LinkedIn.
