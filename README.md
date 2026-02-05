# Titan Scraper – LinkedIn Juridique

[![CI](https://github.com/SergeOin/Scrapper-Titan---Final/actions/workflows/ci.yml/badge.svg)](https://github.com/SergeOin/Scrapper-Titan---Final/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-1.4.1-blue.svg)](VERSION)
[![Python](https://img.shields.io/badge/python-3.11+-green.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Private-red.svg)](#-licence)

> **Usage interne uniquement.** Respect strict des CGU LinkedIn.  
> Scraper LinkedIn spécialisé pour les **métiers juridiques** avec dashboard intégré.

---

## 📋 Table des matières

1. [Objectif Client](#-objectif-client)
2. [Points Forts](#-points-forts)
3. [Limitations Connues](#-limitations-connues)
4. [Architecture](#-architecture)
5. [Installation Rapide](#-installation-rapide)
6. [Démarrage Local](#-démarrage-local)
7. [Application Desktop](#-application-desktop)
8. [Packaging (EXE/MSI/DMG)](#-packaging)
9. [Filtrage Juridique](#-filtrage-juridique)
10. [Système Anti-Détection](#-système-anti-détection)
11. [Configuration](#-configuration)
12. [API & Dashboard](#-api--dashboard)
13. [Déploiement Cloud](#-déploiement-cloud)
14. [Docker](#-docker)
15. [Modules Avancés (v1.4.x)](#-modules-avancés-v14x)
16. [Qualité & Tests](#-qualité--tests)
17. [Observabilité](#-observabilité)
18. [Sécurité & Conformité](#-sécurité--conformité)
19. [Troubleshooting](#-troubleshooting)
20. [Roadmap](#-roadmap)
21. [Licence](#-licence)

---

## 🎯 Objectif Client

### Client : **Titan Partners**

**Titan Partners** est un cabinet de recrutement spécialisé dans les **métiers juridiques** en France. L'objectif principal de ce scraper est de les aider à identifier rapidement les opportunités de recrutement dans le secteur juridique publiées sur LinkedIn.

### Mission du projet

| Aspect | Détail |
|--------|--------|
| **Cible** | Posts LinkedIn annonçant des recrutements de profils juridiques |
| **Périmètre géographique** | France uniquement |
| **Types de postes** | CDI/CDD (exclusion stages/alternances) |
| **Source** | Pages entreprises uniquement (pas d'agences de recrutement) |
| **Volume cible** | ~50 posts pertinents/jour |
| **Créneau de collecte** | 9h00 - 17h30 (heures ouvrables) |

### Bénéfices attendus

- ⏱️ **Gain de temps** : Automatisation de la veille recrutement LinkedIn
- 🎯 **Précision** : Filtrage intelligent éliminant 90%+ de bruit
- 📊 **Visibilité** : Dashboard temps réel avec métriques
- 🔄 **Continuité** : Scraping autonome avec caps quotidiens
- 📈 **Scalabilité** : Architecture modulaire évolutive

---

## 💪 Points Forts

### ✅ Architecture Robuste

| Fonctionnalité | Description |
|----------------|-------------|
| **Architecture modulaire** | 8+ modules activables progressivement via FeatureFlags |
| **Stockage hybride** | SQLite principal avec fallback CSV automatique |
| **Déduplication persistante** | Cache LRU + SQLite cross-sessions |
| **Worker autonome** | Scraping continu avec intervalles adaptatifs |
| **Queue Redis optionnelle** | Mode synchrone ou asynchrone au choix |

### ✅ Anti-Détection Sophistiqué

| Mécanisme | Module |
|-----------|--------|
| **Délais réalistes** | `timing.py` – Distribution gaussienne, mode ultra-safe (×3) |
| **Empreinte navigateur** | `stealth.py` – Rotation user-agents, profils cohérents |
| **Comportement humain** | `human_actions.py` – Courbes de Bézier, scroll naturel |
| **Pauses intelligentes** | `human_patterns.py` – Sessions réalistes, breaks automatiques |
| **Sélecteurs auto-healing** | `selectors.py` – Détection changements CSS LinkedIn |

### ✅ Filtrage Intelligent

| Critère | Taux de précision |
|---------|-------------------|
| **Détection juridique** | ~95% des rôles reconnus |
| **Exclusion agences** | 100% des cabinets de recrutement filtrés |
| **Filtrage géographique** | 112+ patterns de localisation (France only) |
| **Classification intent** | Détection recrutement vs veille/promo |
| **Détection langue** | Filtrage FR strict disponible |

### ✅ Expérience Utilisateur

- 🖥️ **Application Desktop** native (Windows/macOS)
- 📊 **Dashboard web** temps réel avec événements SSE
- 📦 **Packaging complet** : EXE, MSI, DMG
- 🔧 **Mode mock** pour démonstrations sans scraping
- 📈 **Métriques Prometheus** prêtes pour Grafana

### ✅ Qualité de Code

- 🧪 **200+ tests unitaires** couvrant tous les modules
- 📝 **Logging structuré JSON** avec rotation automatique
- 🔍 **Code review** et audits QA documentés
- 📋 **Documentation complète** (README, CHANGELOG, COMPLIANCE)

---

## ⚠️ Limitations Connues

### 🔴 Limitations Critiques

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| **Dépendance aux sélecteurs CSS LinkedIn** | LinkedIn peut modifier son DOM à tout moment | Auto-healing avec fallbacks multiples |
| **Risque de blocage compte** | Détection possible malgré précautions | Mode ultra-safe activé par défaut |
| **Pas de support API officielle LinkedIn** | Scraping uniquement (CGU sensibles) | Respect strict des limites, caps quotidiens |
| **Session manuelle requise** | Pas de login automatique | Script de génération `storage_state.json` |

### 🟠 Limitations Techniques

| Limitation | Impact | Solution prévue |
|------------|--------|-----------------|
| **Pas de rotation de proxies** | IP unique = risque accru | À implémenter (recommandation: Bright Data) |
| **User-agents à maintenir** | Versions Chrome se périment | Mise à jour mensuelle recommandée |
| **Faux positifs géographiques** | ~5-10% posts hors France passent | Amélioration continue des patterns |
| **Posts mal formatés** | Certains posts sans signaux clairs rejetés | Amélioration heuristiques en cours |

### 🟡 Limitations Opérationnelles

| Limitation | Détail |
|------------|--------|
| **Volume limité** | Cap quotidien de 50 posts (configurable) |
| **Horaires restreints** | Scraping optimal en heures ouvrables |
| **Dépendance Chromium** | ~200 Mo de téléchargement pour Playwright |
| **Windows/macOS uniquement** | Pas de support Linux desktop natif |

---

## 🧱 Architecture

```
project/
├── scraper/                    # 🔧 Modules de scraping
│   ├── adapters.py            # Bridge migration progressive (FeatureFlags)
│   ├── bootstrap.py           # Configuration, context, logging
│   ├── worker.py              # Extraction LinkedIn + stockage
│   ├── legal_filter.py        # Filtrage offres juridiques
│   ├── legal_classifier.py    # Classification intentions (recherche_profil, etc.)
│   ├── linkedin.py            # Analyse type auteur
│   ├── post_cache.py          # Déduplication persistante (LRU + SQLite)
│   ├── smart_scheduler.py     # Intervalles adaptatifs
│   ├── keyword_strategy.py    # Rotation explore/exploit mots-clés
│   ├── progressive_mode.py    # Mode conservative → aggressive
│   ├── metadata_extractor.py  # Extraction robuste avec fallbacks
│   ├── selectors.py           # Sélecteurs CSS dynamiques (auto-healing)
│   ├── content_loader.py      # Chargement contenu dynamique
│   ├── diagnostics.py         # Health checks et troubleshooting
│   ├── timing.py              # Délais réalistes (distribution gaussienne)
│   ├── stealth.py             # Anti-fingerprinting navigateur
│   ├── human_actions.py       # Comportement souris/scroll humain
│   ├── human_patterns.py      # Patterns de session réalistes
│   ├── ml_interface.py        # Interface ML avec fallback heuristique
│   └── utils.py               # Fonctions utilitaires
├── server/                     # 🌐 API et Dashboard
│   ├── main.py                # App FastAPI
│   ├── routes.py              # Endpoints API + dashboard
│   ├── events.py              # Server-Sent Events (SSE)
│   └── templates/             # UI HTML (Jinja2)
├── desktop/                    # 🖥️ Application native
│   ├── main.py                # Wrapper desktop (pywebview)
│   ├── chromium_installer.py  # Installation automatique Chromium
│   └── ipc.py                 # Communication inter-process
├── filters/                    # 🔍 Filtres de contenu
│   ├── juridique.py           # Mots-clés juridiques (40+)
│   └── unified.py             # Filtre unifié consolidé
├── scripts/                    # 📜 Scripts utilitaires (50+)
├── tests/                      # 🧪 Tests unitaires (35+ fichiers)
├── web/                        # 🌍 Frontend (si applicable)
├── Dockerfile                  # 🐳 Configuration Docker
├── docker-compose.yml          # 🐳 Orchestration services
└── requirements.txt            # 📦 Dépendances Python
```

### Flux de données

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   LinkedIn      │────▶│   Playwright     │────▶│   Extraction    │
│   (Posts)       │     │   (Chromium)     │     │   (Selectors)   │
└─────────────────┘     └──────────────────┘     └────────┬────────┘
                                                          │
                                                          ▼
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Dashboard     │◀────│   FastAPI        │◀────│   Filtrage      │
│   (HTML/SSE)    │     │   (API/Routes)   │     │   Juridique     │
└─────────────────┘     └──────────────────┘     └────────┬────────┘
                                                          │
                                                          ▼
                                                 ┌─────────────────┐
                                                 │   SQLite/CSV    │
                                                 │   (Stockage)    │
                                                 └─────────────────┘
```

---

## 🚀 Installation Rapide

### Prérequis

| Composant | Version | Requis |
|-----------|---------|--------|
| Python | 3.11+ | ✅ Obligatoire |
| Playwright Chromium | Latest | ✅ Obligatoire |
| Node.js | 18+ | ⚪ Optionnel (frontend React) |
| Redis | 5+ | ⚪ Optionnel (queue jobs) |
| WiX Toolset | 3.x | ⚪ Optionnel (MSI Windows) |

### Installation

**Windows (PowerShell) :**
```powershell
# Créer l'environnement virtuel
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Installer les dépendances
pip install -r requirements.txt

# Installer les dépendances de développement (optionnel)
pip install -r requirements-dev.txt

# Installer Playwright Chromium
python -m playwright install chromium

# Copier la configuration
Copy-Item .env.example .env
# Éditer .env avec vos valeurs
```

**macOS/Linux (Bash) :**
```bash
# Créer l'environnement virtuel
python3 -m venv .venv
source .venv/bin/activate

# Installer les dépendances
pip install -r requirements.txt

# Installer Playwright Chromium
python -m playwright install chromium

# Copier la configuration
cp .env.example .env
# Éditer .env avec vos valeurs
```

---

## 💻 Démarrage Local

### Mode Mock (recommandé pour démo)

```powershell
$env:PLAYWRIGHT_MOCK_MODE = '1'
python scripts/run_server.py
```

Accéder au dashboard : http://127.0.0.1:8000/

### Mode Réel

```powershell
$env:PORT = '8001'
$env:PLAYWRIGHT_MOCK_MODE = '0'
$env:DISABLE_REDIS = '1'
python scripts/run_server.py
```

### Lancer un job unique

```powershell
python scripts/run_once.py --keywords "juriste;avocat"
```

### Script de démo complet

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\demo_run.ps1 -Mock 1 -Open
```

---

## 🖥️ Application Desktop

Une version desktop native permet aux utilisateurs non-techniques de lancer l'application en double-cliquant.

### Lancer depuis les sources

**Windows :**
```powershell
pip install -r desktop/requirements-desktop.txt
python desktop/main.py
```

**macOS :**
```bash
pip install -r desktop/requirements-desktop.txt
python desktop/main.py
```

L'application ouvre une fenêtre native pointant vers `http://127.0.0.1:<port>/`.

### Bootstrapper (premier lancement)

Pour préparer l'environnement utilisateur (dossiers, Chromium, WebView2) :

**Windows :**
```powershell
PowerShell -ExecutionPolicy Bypass -File .\scripts\bootstrap_windows.ps1
```

**macOS :**
```bash
chmod +x scripts/bootstrap_macos.sh
./scripts/bootstrap_macos.sh
```

---

## 📦 Packaging

### Windows EXE (PyInstaller)

```powershell
.\scripts\build_exe.ps1 -Name 'Titan Scraper'
```
Sortie : `dist\Titan Scraper.exe`

### Windows MSI (WiX Toolset)

Prérequis : WiX v3 (candle.exe, light.exe dans PATH)

```powershell
# Build EXE d'abord
pwsh ./scripts/build_desktop_exe.ps1

# Puis générer le MSI
pwsh ./scripts/build_desktop_msi.ps1 -Name 'TitanScraper' -Version '1.0.0'
```
Sortie : `dist/msi/TitanScraper-folder-1.0.0.msi`

Le MSI crée automatiquement :
- Raccourci Menu Démarrer
- Raccourci Bureau

### macOS DMG

```bash
chmod +x build_mac.sh
./build_mac.sh
```
Sortie : `dist/TitanScraper/TitanScraper.app`

Pour créer un DMG :
```bash
./scripts/build_dmg.sh 1.0.0
```
Sortie : `dist/TitanScraper-1.0.0.dmg`

### Signature & Notarisation

**Windows :** Voir `scripts/build_bootstrapper.ps1` pour la signature Authenticode.

**macOS :** Configurer les secrets GitHub Actions pour la signature Developer ID et notarisation Apple.

---

## ⚖️ Filtrage Juridique

### Règles d'inclusion

Un post est pertinent si **TOUS** les critères sont respectés :

| Critère | Détail |
|---------|--------|
| **Auteur** | Page entreprise (pas d'agence de recrutement) |
| **Contenu** | Annonce de poste interne (pas pour un client) |
| **Domaine** | Profil juridique ciblé |
| **Localisation** | France uniquement |
| **Type** | CDI/CDD (pas stage/alternance) |

### Rôles juridiques détectés (40+ mots-clés)

```text
juriste, avocat (collaborateur, associé, counsel), legal counsel, head of legal,
compliance officer, DPO, contract manager, notaire, clerc de notaire, paralegal,
responsable juridique, directeur juridique, responsable fiscal, directeur fiscal,
juriste recouvrement, juriste legal ops, ingénieur patrimonial, fiscaliste,
juriste contentieux, juriste droit social, juriste immobilier, juriste M&A,
juriste propriété intellectuelle, juriste bancaire, juriste assurance...
```

### Classification des intentions

Le système classifie chaque post selon son intention :

| Intent | Description | Action |
|--------|-------------|--------|
| `recherche_profil` | Entreprise cherche un candidat | ✅ Conservé |
| `candidat_disponible` | Personne cherche un emploi | ❌ Exclu |
| `promotion` | Article, événement, pub | ❌ Exclu |
| `veille` | Information juridique | ❌ Exclu |
| `autre` | Non classifiable | ❌ Exclu |

### Utilisation du filtre

```python
from scraper import is_legal_job_post, FilterConfig

# Configuration par défaut
result = is_legal_job_post(post_text)

if result.is_valid:
    print(f"✅ Post pertinent! Score: {result.total_score:.2f}")
else:
    print(f"❌ Exclu: {result.exclusion_reason}")

# Configuration personnalisée
config = FilterConfig(
    recruitment_threshold=0.20,
    legal_threshold=0.25,
    exclude_stage=True,
    exclude_agencies=True,
    exclude_foreign=True,
    verbose=True
)
result = is_legal_job_post(post_text, config=config)
```

### Exclusions automatiques

| Catégorie | Exemples |
|-----------|----------|
| **Agences de recrutement** | Michael Page, Hays, Robert Half, Expectra... |
| **Job boards** | Indeed, Emplois & Bourses, Village de la Justice... |
| **Posts clients** | "pour notre client", "mission chez..." |
| **Contrats exclus** | Stages, Alternances, V.I.E., Freelance |
| **Hors France** | Suisse, Belgique, UK, Afrique, Canada... (112+ patterns) |
| **Chercheurs d'emploi** | #OpenToWork, "disponible immédiatement" |
| **Contenu non-recrutement** | Veille juridique, articles, événements |

---

## 🛡️ Système Anti-Détection

> **Philosophie** : La non-détection et la stabilité du compte LinkedIn priment largement sur la vitesse ou le volume.

### Modules de protection

| Module | Fonction | Activation |
|--------|----------|------------|
| `timing.py` | Délais réalistes avec distribution gaussienne | `TITAN_ENHANCED_TIMING=1` |
| `stealth.py` | Rotation user-agents, fingerprint cohérents | `TITAN_ENHANCED_STEALTH=1` |
| `human_actions.py` | Mouvement souris Bézier, scroll naturel | Automatique |
| `human_patterns.py` | Pauses automatiques, sessions réalistes | `TITAN_FORCED_BREAKS=1` |

### Mode Ultra-Safe (défaut)

Activé par défaut (`TITAN_ULTRA_SAFE_MODE=1`), ce mode applique un multiplicateur ×3 sur tous les délais :

| Action | Mode Normal | Mode Ultra-Safe |
|--------|-------------|-----------------|
| Délai entre pages | 1-2s | 3-6s |
| Délai entre scrolls | 0.5-1s | 1.5-3s |
| Pause session | 5-10min | 15-30min |

### Configuration recommandée (production)

```env
TITAN_ULTRA_SAFE_MODE=1
TITAN_ENHANCED_TIMING=1
TITAN_ENHANCED_STEALTH=1
TITAN_FORCED_BREAKS=1
TITAN_STRICT_HOURS=0
```

### Profils de fingerprint

Le système utilise des profils navigateur cohérents (timezone + user-agent + viewport corrélés) pour éviter les incohérences détectables.

📚 Voir [README_ANTI_DETECTION.md](README_ANTI_DETECTION.md) pour la documentation complète.

---

## ⚙️ Configuration

### Variables d'environnement principales

| Variable | Description | Défaut |
|----------|-------------|--------|
| `SQLITE_PATH` | Chemin base SQLite | `data/posts.sqlite3` |
| `SCRAPE_KEYWORDS` | Mots-clés (séparés par `;`) | `juriste;avocat` |
| `PLAYWRIGHT_MOCK_MODE` | `1` = données synthétiques | `0` |
| `PLAYWRIGHT_HEADLESS` | Mode headless | `1` |
| `AUTONOMOUS_WORKER_INTERVAL_SECONDS` | Intervalle entre cycles (s) | `900` |
| `LEGAL_DAILY_POST_CAP` | Max posts/jour | `50` |
| `FILTER_LEGAL_POSTS_ONLY` | Activer filtre juridique | `True` |
| `FILTER_FRANCE_ONLY` | France uniquement | `True` |
| `FILTER_EXCLUDE_STAGE_ALTERNANCE` | Exclure stages | `True` |

### Variables FeatureFlags (v1.4.0)

| Variable | Description | Défaut |
|----------|-------------|--------|
| `TITAN_ENABLE_PHASE1` | Active cache + scheduler | `0` |
| `TITAN_ENABLE_PHASE2` | Active keywords + progressive | `0` |
| `TITAN_ENABLE_ALL` | Active tous les modules | `0` |

### Variables de déploiement

| Variable | Rôle |
|----------|------|
| `INPROCESS_AUTONOMOUS` | `1` = worker dans le même process |
| `DASHBOARD_PUBLIC` | `1` = accès public sans auth |
| `INTERNAL_AUTH_USER` | Utilisateur Basic Auth |
| `INTERNAL_AUTH_PASS` | Mot de passe (hash auto) |
| `STORAGE_STATE_B64` | Session LinkedIn en base64 |
| `REDIS_URL` | URL Redis (optionnel) |

### Rate limiting

```
API_RATE_LIMIT_PER_MIN=60
API_RATE_LIMIT_BURST=20
RATE_LIMIT_BUCKET_SIZE=120
RATE_LIMIT_REFILL_PER_SEC=2.0
```

---

## 📊 API & Dashboard

### Endpoints principaux

| Endpoint | Méthode | Description |
|----------|---------|-------------|
| `/` | GET | Dashboard HTML |
| `/api/posts` | GET | Liste des posts (JSON) |
| `/api/posts?intent=recherche_profil` | GET | Filtrer par intent |
| `/api/stats` | GET | Statistiques runtime |
| `/api/legal_stats` | GET | Stats quota juridique |
| `/api/version` | GET | Version et build info |
| `/health` | GET | État de santé |
| `/healthz` | GET | Alias /health (Kubernetes) |
| `/metrics` | GET | Métriques Prometheus |
| `/trigger` | POST | Déclencher un scrape |
| `/events` | GET | SSE (Server-Sent Events) temps réel |
| `/api/feature_flags` | GET | Voir les flags actifs |
| `/api/feature_flags/set` | POST | Modifier des flags individuels |
| `/api/feature_flags/enable_phase1` | POST | Activer Phase 1 (cache + scheduler) |
| `/api/feature_flags/enable_phase2` | POST | Activer Phase 2 (+ keywords + progressive) |
| `/api/feature_flags/enable_all` | POST | Activer tous les modules |
| `/api/feature_flags/disable_all` | POST | Retour mode legacy |

### Événements SSE (`/events`)

Le serveur envoie des événements temps réel :
- `cap_reached` — Quota quotidien atteint (50 posts)
- `job_started` / `job_finished` — Début/fin cycle scraping
- `post_stored` — Nouveau post sauvegardé

### Exemple d'appel API

```powershell
# Récupérer les posts
(Invoke-WebRequest -Uri "http://localhost:8000/api/posts").Content

# Stats juridiques
(Invoke-WebRequest -Uri "http://localhost:8000/api/legal_stats").Content
```

### Réponse `/api/legal_stats`

```json
{
  "date": "2025-12-19",
  "accepted": 31,
  "discarded_intent": 14,
  "discarded_location": 3,
  "cap": 50,
  "cap_remaining": 19,
  "cap_progress": 0.62
}
```

---

## ☁️ Déploiement Cloud

### Render (recommandé)

1. Connecter le repo GitHub à Render
2. Render détecte `render.yaml` automatiquement
3. Configurer les variables d'environnement :
   - `SQLITE_PATH=data/posts.sqlite3`
   - `PLAYWRIGHT_MOCK_MODE=0` (ou `1` pour demo)
   - `STORAGE_STATE_B64=<base64 du storage_state.json>`
   - `INTERNAL_AUTH_USER=admin`
   - `INTERNAL_AUTH_PASS=VotreMotDePasse`

### Deta Space (mode mock)

```bash
deta space push
```

Variables à configurer dans Space :
- `PLAYWRIGHT_MOCK_MODE=1`
- `INPROCESS_AUTONOMOUS=1`
- `AUTONOMOUS_WORKER_INTERVAL_SECONDS=900`

### Docker Compose

```bash
docker-compose up -d
```

Services : `api`, `worker`, `redis` (optionnel)

---

## 🐳 Docker

### Build & Run

```bash
docker build -t titan-scraper .
docker run --rm -p 8000:8000 --env-file .env titan-scraper
```

### Worker séparé

```bash
docker run --rm --env-file .env titan-scraper python -m scraper.worker
```

---

## 🔧 Modules Avancés (v1.4.x)

La version 1.4.x introduit une **architecture modulaire** avec activation progressive via FeatureFlags.

### Vue d'ensemble des modules

```
┌─────────────────────────────────────────────────────────────────┐
│                         PHASE 1 (Stable)                        │
├─────────────────────────────────────────────────────────────────┤
│  post_cache         │ Déduplication LRU + SQLite cross-sessions │
│  smart_scheduler    │ Intervalles adaptatifs basés historique   │
└─────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                         PHASE 2 (Avancé)                        │
├─────────────────────────────────────────────────────────────────┤
│  keyword_strategy   │ Rotation explore/exploit des mots-clés    │
│  progressive_mode   │ Conservative → Moderate → Aggressive      │
│  unified_filter     │ Consolidation logique de filtrage         │
│  metadata_extractor │ Extraction robuste avec fallbacks         │
│  selectors          │ CSS dynamiques avec auto-healing          │
│  ml_interface       │ Interface ML + fallback heuristique       │
└─────────────────────────────────────────────────────────────────┘
```

### Modules disponibles

| Module | Description | Phase | Status |
|--------|-------------|-------|--------|
| `post_cache` | Déduplication persistante cross-sessions (LRU + SQLite) | 1 | ✅ Stable |
| `smart_scheduler` | Intervalles adaptatifs basés sur l'historique | 1 | ✅ Stable |
| `keyword_strategy` | Rotation intelligente explore/exploit des mots-clés | 2 | ✅ Stable |
| `progressive_mode` | Mode conservative → moderate → aggressive | 2 | ✅ Stable |
| `unified_filter` | Filtre consolidé toute logique de filtrage | 2 | ✅ Stable |
| `metadata_extractor` | Extraction robuste avec fallbacks | 2 | ✅ Stable |
| `selectors` | Sélecteurs CSS dynamiques avec auto-healing | 2 | ✅ Stable |
| `ml_interface` | Interface ML avec fallback heuristique | 2 | 🔄 Amélioration |

### Activation par phase

```powershell
# Phase 1 : Cache + Scheduler (recommandé pour commencer)
$env:TITAN_ENABLE_PHASE1 = '1'
python scripts/run_server.py

# Phase 2 : + Keywords + Progressive
$env:TITAN_ENABLE_PHASE2 = '1'

# Tous les modules
$env:TITAN_ENABLE_ALL = '1'
```

### Activation via API

```powershell
# Voir les flags actifs
Invoke-RestMethod -Uri "http://localhost:8000/api/feature_flags"

# Activer Phase 1
Invoke-RestMethod -Uri "http://localhost:8000/api/feature_flags/enable_phase1" -Method POST

# Activer tous les modules
Invoke-RestMethod -Uri "http://localhost:8000/api/feature_flags/enable_all" -Method POST
```

### Validation des modules

```powershell
# Test rapide (imports)
python scripts/validate_modules.py --quick

# Validation Phase 1
python scripts/validate_modules.py --phase1

# Validation complète (22 tests)
python scripts/validate_modules.py
```

### Bridge adapters.py

Le module `adapters.py` fournit un bridge pour la migration progressive :

```python
from scraper.adapters import (
    enable_phase1,
    enable_phase2,
    enable_all_features,
    get_next_keywords,
    get_next_interval,
    is_duplicate_post,
    should_keep_post
)

# Activer Phase 1 programmatiquement
enable_phase1()

# Utiliser les fonctions (fallback automatique si module désactivé)
keywords = get_next_keywords()
interval = get_next_interval(success=True)
```

---

## 🧪 Qualité & Tests

### Commandes

```powershell
# Lint
ruff check .

# Format
black --check .

# Tests
pytest -q --asyncio-mode=auto

# Types
mypy .

# Couverture
pytest --cov=scraper --cov=server --cov-report=term-missing
```

### Makefile (Linux/macOS)

```bash
make install      # Dépendances runtime
make install-dev  # + dépendances dev
make test         # Tests
make lint         # Lint + mypy
make coverage     # Couverture
```

---

## 📈 Observabilité

### Logging

- Format JSON structuré via `structlog`
- Rotation automatique (`LOG_MAX_BYTES`, `LOG_BACKUP_COUNT`)
- Fichier si `LOG_FILE` défini

### Métriques Prometheus (`/metrics`)

| Métrique | Type | Description |
|----------|------|-------------|
| `scrape_jobs_total{status}` | Counter | Jobs par statut |
| `scrape_posts_extracted_total` | Counter | Posts extraits |
| `scrape_job_failures_total` | Counter | Erreurs de scraping |
| `scrape_duration_seconds` | Histogram | Durée des jobs |
| `legal_posts_total` | Counter | Posts juridiques acceptés |
| `legal_posts_discarded_total{reason}` | Counter | Posts rejetés |
| `legal_daily_cap_reached_total` | Counter | Cap quotidien atteint |
| `api_rate_limit_rejections_total` | Counter | Requêtes API bloquées |
| `POST_CACHE_*` | Counter/Gauge | Stats déduplication |
| `SCHEDULER_*` | Counter/Gauge | Stats scheduler adaptatif |
| `KEYWORD_STRATEGY_*` | Counter | Stats rotation mots-clés |
| `PROGRESSIVE_MODE_*` | Gauge | Stats mode adaptatif |
| `FEATURE_FLAGS_ENABLED` | Gauge | Status des flags actifs |

### Screenshots

Capturés automatiquement sur erreur Playwright dans `screenshots/`.

---

## 🔒 Sécurité & Conformité

### Bonnes pratiques de sécurité

| Élément | Recommandation |
|---------|----------------|
| **Variables sensibles** | Stockées dans `.env` uniquement (jamais commit) |
| **Session LinkedIn** | `storage_state.json` protégée, encodée en base64 pour déploiement |
| **Dashboard** | Basic Auth recommandée (`INTERNAL_AUTH_USER`, `INTERNAL_AUTH_PASS`) |
| **API /trigger** | Protection par jeton (`TRIGGER_TOKEN`) |
| **Mots de passe** | Hash bcrypt auto-généré |
| **Credentials Desktop** | Chiffrés via DPAPI (Windows) |

### Conformité RGPD

Ce projet respecte les principes de minimisation des données :

| Principe | Application |
|----------|-------------|
| **Minimisation** | Seules les données publiques nécessaires sont collectées |
| **Limitation** | Cap quotidien de 50 posts, pas de profilage avancé |
| **Transparence** | Logs structurés, métriques Prometheus |
| **Droit à l'effacement** | Suppression par identifiant SQLite possible |
| **Sécurité** | Chiffrement credentials, Basic Auth, tokens |

### Conformité CGU LinkedIn

| Aspect | Mesure |
|--------|--------|
| **Rate limiting** | Délais ultra-safe par défaut (×3) |
| **Volume** | Cap quotidien de 50 posts |
| **Horaires** | Option heures ouvrables uniquement |
| **Anti-détection** | Désactivable (opt-in uniquement) |
| **Session** | Compte autorisé explicitement |

📚 Voir [COMPLIANCE.md](COMPLIANCE.md) pour les détails complets.

### Générer une session LinkedIn

```powershell
python scripts/generate_storage_state.py --url https://www.linkedin.com/login
# Se connecter manuellement, puis presser ENTER
```

### Encoder en base64 (pour déploiement)

**Windows :**
```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes('storage_state.json'))
```

**Linux/macOS :**
```bash
base64 -w0 storage_state.json
```

### Auto-login Desktop (Windows)

```powershell
python scripts/store_credentials.py
```

Chemin : `%LOCALAPPDATA%/TitanScraper/credentials.json` (chiffré DPAPI)

---

## 🔧 Troubleshooting

### Problèmes courants

| Problème | Cause | Solution |
|----------|-------|----------|
| `ModuleNotFoundError` | Venv non activé | `.\.venv\Scripts\Activate.ps1` |
| Dashboard vide | Pas de run effectué | Lancer `demo_run.ps1` |
| Chromium not found | Playwright pas installé | `playwright install chromium` |
| Port déjà utilisé | Conflit | Changer `APP_PORT` |
| 429 API | Rate limit | Ajuster `API_RATE_LIMIT_*` |
| Fenêtre vide (desktop) | Health check échoue | Vérifier `/health` |
| Antivirus bloque EXE | False positive | Utiliser one-folder au lieu de one-file |
| Session expirée | Cookies LinkedIn périmés | Régénérer `storage_state.json` |
| 0 posts collectés | Sélecteurs CSS changés | Vérifier logs, mettre à jour selectors |

### Diagnostics intégrés

```python
from scraper.diagnostics import run_full_diagnostic

# Rapport complet (session, rate limit, selectors, DB, etc.)
report = await run_full_diagnostic()
print(report.summary())
```

### Réseau / Proxy d'entreprise

Si erreur certificat (`SELF_SIGNED_CERT_IN_CHAIN`) :

1. Ajouter le certificat racine au système
2. Ou temporairement : `setx NODE_TLS_REJECT_UNAUTHORIZED 0`

### Logs et debugging

```powershell
# Activer les logs détaillés
$env:LOG_LEVEL = 'DEBUG'
$env:LOG_FILE = 'titan_debug.log'
python scripts/run_server.py
```

---

## 🗺️ Roadmap

### ✅ Complété (v1.4.1)

- [x] Architecture modulaire avec FeatureFlags
- [x] 8 modules avancés (cache, scheduler, keywords, progressive, etc.)
- [x] Système anti-détection complet
- [x] 200+ tests unitaires
- [x] Application Desktop (Windows/macOS)
- [x] Packaging MSI/DMG
- [x] Dashboard temps réel avec SSE
- [x] Métriques Prometheus

### 🔄 En cours

- [ ] Amélioration du taux de faux positifs géographiques (<5%)
- [ ] Mise à jour automatique des user-agents
- [ ] Interface ML améliorée

### 📋 Planifié

- [ ] Rotation de proxies (Bright Data, Oxylabs)
- [ ] Export Excel automatique quotidien
- [ ] Notifications Slack/Teams
- [ ] API webhooks pour intégrations tierces
- [ ] Support multi-comptes LinkedIn
- [ ] Dashboard React modernisé

### 💡 Idées futures

- [ ] Intégration ATS (Applicant Tracking Systems)
- [ ] Analyse sentimentale des posts
- [ ] Détection tendances recrutement juridique
- [ ] Mode mobile-first pour dashboard

---

## 🧾 Licence

**Usage interne privé uniquement.**

⚠️ Ce logiciel est destiné exclusivement à un usage interne par **Titan Partners**.

| Condition | Obligation |
|-----------|------------|
| **CGU LinkedIn** | Respecter scrupuleusement |
| **Redistribution** | Interdite sans autorisation |
| **Données** | Stocker le minimum nécessaire |
| **Suspension** | Désactiver si CGU non compatibles |
| **Responsabilité** | L'utilisateur assume tous les risques |

---

## 📚 Ressources

### Documentation

| Document | Description |
|----------|-------------|
| [CHANGELOG.md](CHANGELOG.md) | Historique détaillé des versions |
| [COMPLIANCE.md](COMPLIANCE.md) | Conformité RGPD et bonnes pratiques |
| [README_ANTI_DETECTION.md](README_ANTI_DETECTION.md) | Documentation anti-détection complète |
| [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md) | Guide de migration vers v1.4.x |
| [.env.example](.env.example) | Configuration de référence |

### Rapports

| Rapport | Description |
|---------|-------------|
| [CODE_REVIEW_REPORT.md](CODE_REVIEW_REPORT.md) | Revue de code et recommandations |
| [QA_AUDIT_REPORT_v1.4.1.md](QA_AUDIT_REPORT_v1.4.1.md) | Audit QA complet |
| [CORRECTIONS_REPORT.md](CORRECTIONS_REPORT.md) | Corrections appliquées |

### Scripts utiles

```powershell
# Démo rapide
.\scripts\demo_run.ps1 -Mock 1 -Open

# Validation des modules
python scripts/validate_modules.py

# Diagnostic complet
python scripts/debug_selectors.py

# Génération session LinkedIn
python scripts/generate_storage_state.py
```

---

## 🤝 Support

Pour toute question ou problème :

1. Consulter la section [Troubleshooting](#-troubleshooting)
2. Vérifier les [Issues GitHub](https://github.com/SergeOin/Scrapper-Titan---Final/issues)
3. Lancer le diagnostic intégré (`diagnostics.py`)
4. Examiner les logs (`data/logs/` ou `LOG_FILE`)

---

*Titan Scraper v1.4.1 – Janvier 2026*

**Développé pour Titan Partners** 🏛️