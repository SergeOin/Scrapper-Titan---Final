# Titan Scraper – LinkedIn Juridique

[![CI](https://github.com/SergeOin/Scrapper-Titan---Final/actions/workflows/ci.yml/badge.svg)](https://github.com/SergeOin/Scrapper-Titan---Final/actions/workflows/ci.yml)

> **Usage interne uniquement.** Respect strict des CGU LinkedIn.  
> Scraper LinkedIn spécialisé pour les **métiers juridiques** avec dashboard intégré.

---

## 📋 Table des matières

1. [Objectifs](#-objectifs)
2. [Architecture](#-architecture)
3. [Installation Rapide](#-installation-rapide)
4. [Démarrage Local](#-démarrage-local)
5. [Application Desktop](#-application-desktop)
6. [Packaging (EXE/MSI/DMG)](#-packaging)
7. [Filtrage Juridique](#-filtrage-juridique)
8. [Configuration](#-configuration)
9. [API & Dashboard](#-api--dashboard)
10. [Déploiement Cloud](#-déploiement-cloud)
11. [Docker](#-docker)
12. [Qualité & Tests](#-qualité--tests)
13. [Observabilité](#-observabilité)
14. [Sécurité](#-sécurité)
15. [Troubleshooting](#-troubleshooting)
16. [Licence](#-licence)

---

## 🎯 Objectifs

Scraper LinkedIn conçu pour **Titan Partners**, cabinet de recrutement spécialisé dans les métiers juridiques.

**Fonctionnalités principales :**
- Scraping de posts LinkedIn à partir de mots-clés ciblés
- **Stockage SQLite** (principal) avec fallback CSV
- Filtrage intelligent : domaine juridique, recrutement interne, France uniquement
- Dashboard FastAPI avec stats temps réel
- Worker asynchrone avec queue Redis optionnelle
- Mode mock pour démonstrations sans scraping réel
- Métriques Prometheus + logging structuré JSON

**Objectif de collecte :** 50+ posts pertinents en 7h (créneau 9h-17h30)

---

## 🧱 Architecture

```
project/
├── scraper/
│   ├── bootstrap.py      # Configuration, context, logging
│   ├── worker.py         # Extraction LinkedIn + stockage
│   ├── legal_filter.py   # Filtrage offres juridiques
│   ├── legal_classifier.py  # Classification intentions
│   ├── linkedin.py       # Analyse type auteur
│   └── utils.py          # Fonctions utilitaires
├── server/
│   ├── main.py           # App FastAPI
│   ├── routes.py         # Endpoints API + dashboard
│   └── templates/        # UI HTML
├── desktop/
│   └── main.py           # Wrapper desktop (pywebview)
├── filters/
│   └── juridique.py      # Mots-clés juridiques
├── scripts/              # Scripts utilitaires
├── tests/                # Tests unitaires
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## 🚀 Installation Rapide

### Prérequis
- Python 3.11+
- (Optionnel) Node.js pour le frontend React
- (Optionnel) Redis pour la queue de jobs

### Installation

```powershell
# Créer l'environnement virtuel
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Installer les dépendances
pip install -r requirements.txt

# Installer Playwright Chromium
python -m playwright install chromium

# Copier la configuration
Copy-Item .env.example .env
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

### Rôles juridiques détectés

```
juriste, avocat (collaborateur, associé, counsel), legal counsel, head of legal,
compliance officer, DPO, contract manager, notaire, clerc de notaire, paralegal,
responsable juridique, directeur juridique, responsable fiscal, directeur fiscal
```

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

- Cabinets de recrutement (Michael Page, Hays, etc.)
- Posts "pour notre client"
- Stages / Alternances / V.I.E.
- Hors France (Suisse, Belgique, UK, etc.)
- Veille juridique / Articles / Événements

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
| `/metrics` | GET | Métriques Prometheus |
| `/trigger` | POST | Déclencher un scrape |

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
| `scrape_duration_seconds` | Histogram | Durée des jobs |
| `legal_posts_total` | Counter | Posts juridiques acceptés |
| `legal_posts_discarded_total{reason}` | Counter | Posts rejetés |
| `legal_daily_cap_reached_total` | Counter | Cap quotidien atteint |
| `api_rate_limit_rejections_total` | Counter | Requêtes API bloquées |

### Screenshots

Capturés automatiquement sur erreur Playwright dans `screenshots/`.

---

## 🔒 Sécurité

### Bonnes pratiques

- Variables sensibles dans `.env` uniquement (jamais commit)
- Session LinkedIn (`storage_state.json`) protégée
- Basic Auth recommandée pour le dashboard
- Jeton de protection pour `/trigger` (`TRIGGER_TOKEN`)

### Générer une session LinkedIn

```powershell
python scripts/generate_storage_state.py --url https://www.linkedin.com/login
# Se connecter manuellement, puis presser ENTER
```

### Encoder en base64 (pour déploiement)

```powershell
# Windows
[Convert]::ToBase64String([IO.File]::ReadAllBytes('storage_state.json'))
```

```bash
# Linux/macOS
base64 -w0 storage_state.json
```

### Auto-login Desktop (Windows)

Un fichier `credentials.json` chiffré via DPAPI peut être créé :
```powershell
python scripts/store_credentials.py
```
Chemin : `%LOCALAPPDATA%/TitanScraper/credentials.json`

---

## 🔧 Troubleshooting

| Problème | Cause | Solution |
|----------|-------|----------|
| `ModuleNotFoundError` | Venv non activé | Activer le venv |
| Dashboard vide | Pas de run effectué | Lancer `demo_run.ps1` |
| Chromium not found | Playwright pas installé | `playwright install chromium` |
| Port déjà utilisé | Conflit | Changer `APP_PORT` |
| 429 API | Rate limit | Ajuster `API_RATE_LIMIT_*` |
| Fenêtre vide (desktop) | Health check échoue | Vérifier `/health` |
| Antivirus bloque EXE | False positive | Utiliser one-folder au lieu de one-file |

### Réseau / Proxy d'entreprise

Si erreur certificat (`SELF_SIGNED_CERT_IN_CHAIN`) :
1. Ajouter le certificat racine au système
2. Ou temporairement : `setx NODE_TLS_REJECT_UNAUTHORIZED 0`

---

## 🧾 Licence

**Usage interne privé uniquement.**

- Respecter les CGU LinkedIn
- Ne pas redistribuer publiquement
- Stocker le minimum de données nécessaires
- Désactiver si CGU non compatible

---

## 📚 Ressources

- [CHANGELOG.md](CHANGELOG.md) - Historique des versions
- [COMPLIANCE.md](COMPLIANCE.md) - Conformité et RGPD
- [.env.example](.env.example) - Configuration de référence

---

*Titan Scraper v1.4.0 – Décembre 2025*

