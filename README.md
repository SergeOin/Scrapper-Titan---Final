# LinkedIn Scraper & Minimal Dashboard

[![CI](https://github.com/SergeOin/Scrapper-Titan---Final/actions/workflows/ci.yml/badge.svg)](https://github.com/SergeOin/Scrapper-Titan---Final/actions/workflows/ci.yml) [![Coverage](https://codecov.io/gh/SergeOin/Scrapper-Titan---Final/branch/main/graph/badge.svg?token=CODECOV_TOKEN_PLACEHOLDER)](https://codecov.io/gh/SergeOin/Scrapper-Titan---Final)

> (Si le badge coverage est gris, le token ou l’upload n’est pas encore configuré; voir section Qualité pour fallback.)

> Usage interne uniquement. Respect strict des CGU LinkedIn. Ce projet fournit un worker de scraping découplé d'un serveur FastAPI avec un mini dashboard pour visualiser les posts collectés et déclencher un nouveau scrape de façon contrôlée.

---
## 🎯 Objectifs
- Scraping de posts LinkedIn à partir de mots-clés ciblés (recherche)
- Stockage principal MongoDB (Atlas), fallback automatique SQLite ou CSV
- Worker asynchrone (séparé du serveur) + file/queue Redis pour jobs
- Dashboard FastAPI minimal (table paginée + stats + bouton "Forcer scrape")
- Cache TTL & verrou anti-concurrence pour éviter sur-scraping
- Logging structuré JSON + rotation + métriques Prometheus `/metrics`
- Tests unitaires (pytest), linting Ruff, format Black, typage mypy
- Docker multi-stage prêt pour déploiement serveur Linux (Playwright installé)

### Extension Domaine Juridique (Classification)
Pipeline intégré de qualification des posts juridiques en France :
* Filtrage langue FR + heuristique géographique France (détection mots FR + mentions FR/Paris/provinces)
* Classifieur heuristique (`scraper/legal_classifier.py`) ⇒ intent `recherche_profil` vs `autre`
* Scoring `relevance_score` (0..1) + `confidence` + `keywords_matched` (liste dé-dupliquée)
* Limite dure quotidienne `LEGAL_DAILY_POST_CAP` (par défaut 50) – métrique `legal_daily_cap_reached_total`
* Cap visible via endpoint `/api/legal_stats` + barre de progression sur le dashboard
* Filtrage API & UI: query param `?intent=recherche_profil|autre`
* Script de purge ciblée par intent: `python scripts/purge_intent.py --intent recherche_profil`
* Champs persistés (Mongo / SQLite colonnes dédiées / CSV fallback enrichi) :
  - `intent`
  - `relevance_score`
  - `confidence`
  - `keywords_matched`
  - `location_ok`
* Nouvelles colonnes SQLite (migration auto best‑effort) : `intent`, `relevance_score`, `confidence`, `keywords_matched`, `location_ok`
* Métriques Prometheus :
  - `legal_posts_total`
  - `legal_posts_discarded_total{reason="intent|location"}`
  - `legal_intent_classifications_total{intent}`
  - `legal_daily_cap_reached_total`
* Paramètres environnement spécifiques :
  | Variable | Rôle | Défaut |
  |----------|------|--------|
  | `LEGAL_DAILY_POST_CAP` | Nombre max de posts légaux persistés / jour UTC | 50 |
  | `LEGAL_INTENT_THRESHOLD` | Seuil score combiné pour passer en `recherche_profil` | 0.35 |
  | `LEGAL_KEYWORDS` | (Optionnel) liste ; séparée de mots-clés métiers pour override/extension | — |
  | `FILTER_LEGAL_DOMAIN_ONLY` | Si `1`, force le worker à ne garder que le domaine juridique (pré-filtrage) | 0 |
* Objet classification (exemple) :
```jsonc
{
  "intent": "recherche_profil",
  "relevance_score": 0.74,
  "confidence": 0.78,
  "keywords_matched": ["avocat", "juriste"],
  "location_ok": true
}
```
* Endpoint stats journalières :
```bash
GET /api/legal_stats
→ {
  "date": "2025-10-03",
  "accepted": 31,
  "discarded_intent": 14,
  "discarded_location": 3,
  "discarded_total": 17,
  "total_classified": 48,
  "cap": 50,
  "cap_remaining": 19,
  "cap_progress": 0.62,
  "rejection_rate": 0.3542,
  "intent_threshold": 0.35
}
```
* Paramètre debug `include_raw=1` (API `/api/posts`) pour exposer le bloc `classification_debug` (intent, scores, keywords) – omis par défaut pour réduire la taille.
* Conformité: voir `COMPLIANCE.md` (minimisation, usage interne, absence de techniques de contournement)
* Suivi interne supplémentaire (non persisté dans les documents de posts mais exposé via `/api/legal_stats`) :
  - `accepted` (posts retenus)
  - `discarded_intent` (intent != recherche_profil)
  - `discarded_location` (rejets localisation)
  - `cap_remaining`, `cap_progress` (quota)

---
## 🧱 Architecture (vue d'ensemble)
```
project/
│-- scraper/
│   │-- bootstrap.py      # Initialisation context: settings, clients, logging
│   │-- utils.py          # Outils communs (UA random, parse date, langue, etc.)
│   │-- worker.py         # Logique scraping + retries + stockage + screenshots
│-- server/
│   │-- main.py           # App FastAPI, montage routes, middlewares, metrics
│   │-- routes.py         # Endpoints API + dashboard HTML
│   │-- templates/
│   │    └─ dashboard.html# UI unique minimaliste
│-- scripts/
│   │-- run_once.py       # Lance un job de scraping isolé (sans queue)
│   │-- start_server.ps1  # Démarrage serveur (Windows)
│   │-- run_scraper.ps1   # Démarrage worker (Windows)
│-- tests/                # Tests unitaires & snapshots sélecteurs
│-- Dockerfile
│-- requirements.txt
│-- .env.example
│-- README.md
│-- .gitignore
```

---
## ⚙️ Flux Fonctionnel
1. L'utilisateur (interne) ouvre le dashboard ⇒ voit les posts + stats (dernier run, total, état queue)
2. Il clique sur "Forcer scrape" (POST) ⇒ push d'un job keyword(s) dans Redis
3. Le worker (process séparé) consomme la queue ⇒ Playwright + login via `storage_state.json`
4. Le worker applique les sélecteurs (abstraction testée) ⇒ extrait posts (texte, auteur, date, langue, score heuristique)
5. Stockage MongoDB (ou fallback) + mise à jour métadonnées (last_run, counts)
6. Logs JSON + snapshots d'erreur (screenshots) + métriques incrementées
7. Le dashboard affiche les nouvelles données via pagination / query params.

---
## 🗄️ Stockage
Ordre de priorité :
1. MongoDB (Motor + collection `posts` & `meta`) – backend principal
2. SQLite (fichier local `fallback.sqlite3`) si Mongo indisponible
3. CSV (append dans `exports/fallback_posts.csv`) si SQLite échoue

Schéma persistant actuel (champs de score supprimés) :
```jsonc
{
  "_id": "hash(post_url|timestamp)",
  "keyword": "python ai",
  "author": "Nom Auteur",
  "author_profile": "https://www.linkedin.com/in/...",
  "company": "Entreprise XYZ", // si détectée ou dérivée heuristiquement
  "text": "Contenu du post...",
  "language": "fr",
  "published_at": "2025-09-18T08:21:00Z",
  "collected_at": "2025-09-18T08:25:12Z",
  "permalink": "https://www.linkedin.com/feed/update/urn:li:activity:XXXX/",
  "raw": { /* fragments bruts pour debug */ }
}
```

---
## 🔒 Sécurité & Conformité
- Variables sensibles uniquement via `.env` (jamais commit) : credentials, URIs
- Aucune redistribution publique des données collectées
- Respect des limitations implicites (sleep jitter, random UA)
- Possibilité de désactiver le scraping global via variable `SCRAPING_ENABLED=0`
- Option d'activer une auth basique interne (`INTERNAL_AUTH_USER/PASS`)
- Jeton de protection déclenchement job (`TRIGGER_TOKEN`) activé si défini : envoyer le header `X-Trigger-Token: <valeur>` sur `POST /trigger`
- HTTPS géré en amont (reverse proxy) — possibilité future d'ajouter TLS local

---
## 📦 Variables d'environnement (voir `.env.example`)
| Variable | Description | Exemple |
|----------|-------------|---------|
| `MONGO_URI` | URI MongoDB Atlas | `mongodb+srv://user:pass@cluster/db` |
| `MONGO_DB` | Nom DB | `linkedin_scrape` |
| `REDIS_URL` | Redis queue/cache | `redis://localhost:6379/0` |
| `SCRAPE_KEYWORDS` | Liste mots-clés (séparés par ;) | `python;ai;data` |
| `SCRAPING_ENABLED` | 1/0 activer désactiver | `1` |
| `PLAYWRIGHT_HEADLESS` | Mode headless | `1` |
| `CACHE_TTL_SECONDS` | TTL cache en secondes | `300` |
| `LOCK_FILE` | Fichier de verrou | `.scrape.lock` |
| `INTERNAL_AUTH_USER` | (Optionnel) utilisateur dashboard | `admin` |
| `INTERNAL_AUTH_PASS_HASH` | Hash bcrypt si activé | `$2b$...` |
| `LOG_LEVEL` | Niveau logs | `INFO` |
| `MAX_POSTS_PER_KEYWORD` | Limite extraction par mot-clé | `30` |
| `JOB_VISIBILITY_TIMEOUT` | Timeout réapparition job (s) | `300` |
| `EXPORT_DIR` | Dossier exports CSV | `exports` |
| `RECRUITMENT_SIGNAL_THRESHOLD` | Seuil compteur métrique recrutement (champ non stocké) | `0.35` |
| `SHUTDOWN_TOKEN` | Jeton requis pour POST `/shutdown` | `secret123` |

---
## 🚀 Démarrage Local (Windows PowerShell)
```powershell
python -m venv .venv
. .venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
Copy-Item .env.example .env
# Éditer .env avec vos valeurs

# Lancer serveur API seul
uvicorn server.main:app --reload --port 8000

# Lancer worker seul
python scripts/run_worker.py

# Lancer serveur + worker ensemble (démo rapide)
python scripts/run_all.py
```
Accéder au dashboard: http://127.0.0.1:8000/

Déclencher manuellement un job (sans UI) :
```powershell
python scripts\run_once.py --keywords "python;ai"
```

#### Cache Playwright (CI)
Le workflow `release.yml` met en cache les navigateurs via `actions/cache` (clé `playwright-browsers-...`).
Invalider le cache après upgrade Playwright : modifier la clé dans le workflow.

---
## 🐳 Docker
Build & run :
```bash
docker build -t linkedin-scraper .
# Créer un réseau si usage conteneurs Redis/Mongo
# docker network create internal_net

# Exemple (avec variables inline de test)
docker run --rm -p 8000:8000 --env-file .env linkedin-scraper
```
Le worker peut être un second conteneur (même image) avec commande override :
```bash
docker run --rm --env-file .env linkedin-scraper python -m scraper.worker
```
Pour Playwright dans Docker : Chromium installé au build + dépendances system (voir `Dockerfile`).

---
## 🧪 Qualité & Tests
Commandes :
```powershell
ruff check .
black --check .
pytest -q --asyncio-mode=auto --maxfail=1 --disable-warnings
mypy .
```
Couverture :
```powershell
pytest --cov=scraper --cov=server --cov-report=term-missing
```
Auto-fix format :
```powershell
ruff check . --fix
black .
```

---
## 📊 Observabilité
| Aspect | Détails |
|--------|---------|
| Logs | JSON via `structlog`, enrichis `request_id`, niveau configurable `LOG_LEVEL` |
| Rotation | Handler `RotatingFileHandler` (variables ci‑dessous) |
| Metrics | Endpoint `/metrics` (Prometheus) exposant compteurs & histogrammes |
| Screenshots | Capturés sur échecs critiques Playwright dans `screenshots/` |
| Traces futures | OpenTelemetry (roadmap) |

### Métriques exposées
| Nom | Type | Description |
|-----|------|-------------|
| `scrape_jobs_total{status=success|error}` | Counter | Nombre de jobs traités par statut |
| `scrape_posts_extracted_total` | Counter | Total de posts extraits (par job) |
| `scrape_duration_seconds` | Histogram | Durée des jobs de scraping |
| `scrape_mock_posts_extracted_total` | Counter | Posts synthétiques générés (mode mock) |
| `scrape_storage_attempts_total{backend,result}` | Counter | Succès/erreurs par backend (mongo/sqlite/csv) |
| `scrape_queue_depth` | Gauge | Profondeur actuelle de la file de jobs Redis |
| `scrape_job_failures_total` | Counter | Nombre de jobs échoués (exceptions) |
| `scrape_step_duration_seconds{step}` | Histogram | Durée de sous-étapes (mongo_insert, sqlite_insert, etc.) |
| `scrape_rate_limit_wait_seconds_total` | Counter | Secondes cumulées d'attente dues au rate limiting |
| `scrape_rate_limit_tokens` | Gauge | Jetons disponibles (bucket courant) |
| `api_rate_limit_rejections_total` | Counter | Requêtes API rejetées (limitation IP) |
| `scrape_scroll_iterations_total` | Counter | Nombre total d'itérations de scroll exécutées |
| `scrape_extraction_incomplete_total` | Counter | Extractions arrêtées sous le seuil `MIN_POSTS_TARGET` |
| `scrape_recruitment_posts_total` | Counter | Posts détectés recrutement (heuristique interne, score non stocké) |

Endpoints opérationnels additionnels :
| Endpoint | Méthode | Description |
|----------|---------|-------------|
| `/health` | GET | Santé enrichie (ping Mongo, last_run, age, queue_depth, flags) |
| `/shutdown` | POST | Arrêt contrôlé (token + éventuellement basic auth) |
| `/debug/auth` | GET | Diagnostic session Playwright (storage_state, modes) |
| `/debug/last_batch` | GET | Derniers posts (auteur, company, keyword, timestamps) pour debug extraction |
| `/api/stats` | GET | Statistiques runtime agrégées (mock_mode, intervalle autonome, posts_count, âge last_run, queue_depth) |
| `/api/version` | GET | Métadonnées build (commit, timestamp) pour traçabilité |

### Statistiques supplémentaires (meta)
Le document meta Mongo (`_id: "global"`) contient désormais :
```jsonc
{
  "posts_count": 1234,
  "last_run": "2025-09-19T09:10:11.123456+00:00",
  "last_job_posts": 42,
  "last_job_unknown_authors": 5,
  "last_job_unknown_ratio": 0.119,
  "scraping_enabled": true
}
```
Ces champs apparaissent partiellement dans `/health` : `last_job_unknown_authors`, `last_job_posts`, `last_job_unknown_ratio` pour rapidement suivre la qualité de détection auteur.

### Capture d'authentification
Un screenshot `screenshots/auth_state.png` est généré à chaque tentative d'initialisation de session (utile si auteurs restent `Unknown`).

### Variables de configuration Logging
| Variable | Rôle | Exemple |
|----------|------|---------|
| `LOG_FILE` | Active la sortie fichier si défini | `logs/app.log` |
| `LOG_MAX_BYTES` | Taille max d'un fichier avant rotation | `2000000` |
| `LOG_BACKUP_COUNT` | Nombre de fichiers conservés | `5` |

### Contexte de configuration
Les settings utilisent désormais `pydantic-settings` (Pydantic v2) — `BaseSettings` ayant été déplacé hors du core. Le chargement se fait automatiquement depuis `.env` + variables d'environnement.

---
## 🔁 Stratégie de Retry (Tenacity)
- Backoff exponentiel + jitter (aléa contrôlé) pour limiter les patterns détectables
- Nombre de tentatives configurable (`MAX_RETRIES`)
- Erreurs transitoires encapsulées (ex: navigation timeouts) pour réessai ciblé
- Extension future : circuit-breaker / compteur d'échecs consécutifs

---
## 🧪 Tests Clés Prévus
| Test | Description |
|------|-------------|
| Selectors snapshot | Vérifie structure DOM attendue / fallback si changement |
| Storage fallback | Simule indisponibilité Mongo ⇒ bascule SQLite/CSV |
| API pagination | Vérification limites, pages vides |
| Queue job lifecycle | Insert → consume → ack timeout |
| Lock anti-concurrent | Double lancement worker refusé |
| Lang detection | Multi-langue texte court/long |

---
## 🧬 Scores supprimés
Les champs `score` et `recruitment_score` ont été retirés du modèle persistant pour simplifier l'usage métier. La logique de détection recrutement subsiste uniquement comme incrément de métrique `scrape_recruitment_posts_total`. Toute donnée legacy est migrée (SQLite) ou simplement ignorée (Mongo déjà sans nouveau champ lors d'insertion). Aucune action manuelle requise.

---
## ⚖️ Avertissement Légal & Éthique
- Ne pas surcharger LinkedIn (delais random + limites strictes)
- Ne pas republier / revendre le contenu extrait
- Désactiver immédiatement si modification CGU non compatible
- Stocker minimum de données nécessaires

---
## 🗺️ Roadmap Potentielle
- Intégration OpenTelemetry traces
- Export parquet / Data Lake
- Scheduling cron (APScheduler) au lieu d'appui manuel
- Support login rotation comptes
- Détection CAPTCHA & pause adaptative

---
## 🤝 Contributions Internes
1. Créer branche feature
2. Ajouter tests + docs brèves
3. Lint & format avant PR
4. Revue par pair interne

---
## 🧾 Licence
Usage interne privé (pas de distribution publique).

---
## ✅ Statut
MVP fonctionnel livré : worker Playwright, stockage multi-niveaux, API & dashboard, métriques, logging structuré + rotation, tests de base. Prochaines étapes optionnelles : durcir sélecteurs, enrichir CI/CD, ajout d'une stratégie anti-CAPTCHA.

---
## 🧩 Installation (Binaires Desktop / Serveur Local)

Des installateurs sont produits automatiquement à chaque tag `v*` via GitHub Actions (workflow `build-release`).

### Windows (.msi)
1. Télécharger `LinkedInScraper_<version>.msi` depuis **Releases**.
2. Lancer l'installateur (scope machine par défaut).
3. Un raccourci bureau "LinkedInScraper" est créé.
4. Démarrer l'application puis ouvrir http://127.0.0.1:8000
5. Première exécution : téléchargement éventuel de Chromium Playwright (réseau requis).

#### Cache Playwright (CI)
Le workflow `release.yml` met en cache les navigateurs via `actions/cache` (clé `playwright-browsers-...`).
Invalider le cache après upgrade Playwright : modifier la clé dans le workflow.

### macOS (.dmg)
1. Télécharger `LinkedInScraper_<version>.dmg`.
2. Glisser l'application dans `Applications`.
3. Si Gatekeeper bloque : clic droit → Ouvrir.
4. Accéder ensuite à http://127.0.0.1:8000

#### (Optionnel) Signature & Notarisation macOS
Bloc commenté prêt dans `release.yml` : dé‑commenter + secrets (`MACOS_CERT_B64`, `MACOS_CERT_PASSWORD`, `MACOS_NOTARY_APPLE_ID`, `MACOS_NOTARY_TEAM_ID`, `MACOS_NOTARY_PASSWORD`) pour activer codesign + notarisation.

### Mises à jour
Installer simplement la nouvelle version (.msi ou .dmg). Sauvegarder `fallback.sqlite3` si vous utilisez le mode sans Mongo.

### Variables d'environnement
Placer un fichier `.env` à côté de l'exécutable ou définir dans l'environnement système :
```
MONGO_URI=...
SCRAPE_KEYWORDS=avocat;juriste
LEGAL_DAILY_POST_CAP=50
INTERNAL_AUTH_USER=admin
INTERNAL_AUTH_PASS=ChangeMe!
```

### Stockage local
Sans `MONGO_URI`, un fichier `fallback.sqlite3` est créé dans le dossier courant.

### Désinstallation
Windows : Paramètres → Applications → LinkedInScraper → Désinstaller.
macOS : Supprimer l'app dans Applications + supprimer les artefacts locaux si désiré.

### Génération locale rapide
Windows :
```powershell
pwsh scripts/packaging/build_installer_windows.ps1 -Version 1.2.3
```
macOS :
```bash
VERSION=1.2.3 bash scripts/packaging/macos/build_dmg.sh
```
Le binaire combine serveur + worker via un « entrypoint » unifié (`entrypoint.py`) qui démarre simultanément le serveur FastAPI et le worker et respawne le worker en cas de crash (cooldown 300s configurable via `WORKER_RESPAWN_COOLDOWN_SECONDS`).

### Entrypoint Unifié & Mode Test
Orchestre : serveur FastAPI + worker supervisé + chargement `.env` + rotation logs.
Mode test rapide (utilisé dans la suite Pytest) :
```powershell
ENTRYPOINT_TEST_MODE=1 python entrypoint.py
```

---
## 🌐 Déploiement Gratuit / Low-Cost

Priorité: Deta Space (gratuit), sinon Render (Free plan) ou Railway (Free trial / low-cost). Le scraping réel continu avec Playwright nécessite un runtime supportant Chromium (Deta Space n'exécute pas de navigateur complet de façon fiable) ⇒ mode mock recommandé sur Deta Space.

### Variables Clés de Déploiement
| Variable | Rôle |
|----------|------|
| `PLAYWRIGHT_MOCK_MODE` | `1` pour données synthétiques (CI / Deta) ; `0` pour vrai scraping |
| `AUTONOMOUS_WORKER_INTERVAL_SECONDS` | Intervalle secondes entre cycles auto (ex: 900) |
| `INPROCESS_AUTONOMOUS` | `1` pour exécuter le worker dans le même process FastAPI (utile Deta) |
| `DASHBOARD_PUBLIC` | `1` rendu public, sinon activer auth interne |
| `MONGO_URI` | Connexion MongoDB Atlas (persistance) sinon fallback SQLite |
| `WORKER_RESTART_DELAY_SECONDS` | Délai redémarrage worker dédié (Render/Railway) |
| `PORT` | Port imposé par la plateforme (Render/Railway) |
| `INTERNAL_AUTH_USER` | Active Basic Auth si défini (toujours appliqué même avec `DASHBOARD_PUBLIC=1`) |
| `INTERNAL_AUTH_PASS_HASH` | Hash bcrypt explicite si déjà généré |
| `INTERNAL_AUTH_PASS` | Mot de passe en clair (hash généré automatiquement si HASH absent) |
| `STORAGE_STATE_B64` | Contenu base64 de `storage_state.json` injecté au démarrage si fichier manquant |

### 1. Deta Space (Mock Mode Conseillé)
1. Installer l'outil Deta & login.
2. Ajouter le `Spacefile` fourni à la racine (déjà présent).
3. Déployer: `deta space push`.
4. Dans l'interface Space, ajouter les variables d'environnement souhaitées (ex: `PLAYWRIGHT_MOCK_MODE=1`, `INPROCESS_AUTONOMOUS=1`, `AUTONOMOUS_WORKER_INTERVAL_SECONDS=900`).
5. (Optionnel) Ajouter `MONGO_URI` vers un cluster Atlas pour persistance; sinon les données seront dans `fallback.sqlite3` interne (éphémère sur rebuilds).

Limitations Deta:
- Pas de navigateur Chrome complet stable ⇒ mode réel non garanti.
- Utiliser le mode mock pour démonstration du dashboard + SSE.

### 2. Render (Web + Worker séparés)
Fichiers utilisés: `render.yaml`, `Procfile`..
1. Créer un nouveau Blueprint dans Render à partir du repo (connect GitHub).
2. Render détecte `render.yaml` et provisionne deux services :
  - Web: lance `python scripts/run_server.py` sur le port `$PORT`.
  - Worker: lance `python scripts/run_worker.py` avec redémarrage automatique.
3. Dans l'onglet Environment, ajouter (exemple réel minimal):
  - `MONGO_URI=...` (Atlas)
  - `PLAYWRIGHT_MOCK_MODE=0`
  - `STORAGE_STATE_B64=<base64 du storage_state.json>` (ou montez le fichier via volume privé)
  - `INTERNAL_AUTH_USER=admin` + `INTERNAL_AUTH_PASS=ChangeMe!` (hash auto)
  - `AUTONOMOUS_WORKER_INTERVAL_SECONDS=0` (si worker dédié séparé) ou >0 si vous supprimez le service worker.
  - (Optionnel) `DASHBOARD_PUBLIC=1` pour accès sans auth si aucune variable INTERNAL_AUTH_*.
4. (Optionnel) Ajouter un Redis managé. Sinon le worker autonome tournant périodiquement suffit.
5. Fournir la session: soit via `STORAGE_STATE_B64`, soit en attachant après déploiement un fichier `storage_state.json`. Le bootstrap décodera automatiquement la variable si le fichier est absent.

SSE: Render supporte les connexions persistantes HTTP/1.1 ⇒ `/stream` fonctionne.

### 3. Railway
1. Rails nouveau projet → connecter repository.
2. Ajouter deux services manuels si souhaité: `web` (FastAPI) & `worker` (même image, commande différente) ou un seul service avec `INPROCESS_AUTONOMOUS=1`.
3. Dans Variables, définir valeurs analogues à Render.
4. S'assurer d'installer Playwright dans postinstall (ex: `nixpacks` build détecte requirements puis ajouter hook: `python -m playwright install --with-deps chromium`).

### 4. Docker Compose (Auto- hébergement VPS)
Utiliser `docker-compose.yml` existant: un service API + un worker + Redis + Mongo si souhaité. Adapter `.env`.

### 5. Authentification & Public
- Démo publique: `DASHBOARD_PUBLIC=1`, laisser `INTERNAL_AUTH_USER` vide.
- Production interne: `DASHBOARD_PUBLIC=0` puis définir `INTERNAL_AUTH_USER` + `INTERNAL_AUTH_PASS_HASH`.


### 6. Fournir `storage_state.json`
Scraping réel LinkedIn nécessite une session authentifiée:
1. En local: lancer `playwright codegen https://www.linkedin.com/feed/` ou navigation manuelle via script pour login.
2. Exporter storage state: adapter un petit script Playwright pour sauvegarder `storage_state.json`.
3. Ne jamais committer ce fichier. Le fournir à l'environnement (ex: Render) via un secret base64:
  - Encoder (PowerShell): `Set-Content -Path storage_state.b64 -Value ([Convert]::ToBase64String([IO.File]::ReadAllBytes('storage_state.json')))`
  - Encoder (Linux/macOS): `base64 -w0 storage_state.json > storage_state.b64`
  - Variable: `STORAGE_STATE_B64=<contenu du fichier .b64>`
  - Le bootstrap décode automatiquement si `storage_state.json` est absent.

### 6bis. Basic Auth légère même en mode public
Si `DASHBOARD_PUBLIC=1` mais que vous définissez `INTERNAL_AUTH_USER` + ( `INTERNAL_AUTH_PASS_HASH` ou `INTERNAL_AUTH_PASS` ):
- CORS large activé (accès JS depuis ailleurs) mais endpoints protégés par Basic Auth.
- Utiliser un header: `Authorization: Basic base64(user:password)`.
- Pour éviter stocker un hash manuellement: mettre `INTERNAL_AUTH_PASS=monmotdepasse` et laisser vide `INTERNAL_AUTH_PASS_HASH`.


### 7. Mode Autonome In-Process
Activez `INPROCESS_AUTONOMOUS=1` et `AUTONOMOUS_WORKER_INTERVAL_SECONDS>0`. Le serveur FastAPI démarrera une tâche asynchrone de scraping périodique (même logique que le worker) — utile quand la plateforme ne permet pas de process séparé.

### 8. Export CSV Minimal
```
python scripts/export_csv.py --out exports/posts_snapshot.csv --limit 1000
```
Colonne: `_id, keyword, author, company, text, language, published_at, collected_at, permalink`.

### 9. Surveillance / Fiabilité
- Redémarrage worker automatique (script `run_worker.py`) → log en stdout sur crash.
- Métriques Prometheus (`/metrics`) : vérifier `scrape_jobs_total`, `scrape_post_extracted_total`, `scrape_recruitment_posts_total`.
- SSE temps réel: navigateur écoute `/stream` (événements `job_complete`, `toggle`).

### 10. Plans d'évolution Cloud
| Besoin | Option |
|--------|--------|
| Multi-instance / scaling | Redis externe pour queue + cache rate limit |
| Observabilité avancée | Ajouter OpenTelemetry + exporter traces |
| Persist de session Playwright | Stocker storage_state chiffré (KMS) |
| Anti blocage | Proxy rotatif / user-agents dynamiques |

---

### Note Playwright (réseau / proxy interne)
Si l'installation du navigateur échoue avec une erreur de certificat (`SELF_SIGNED_CERT_IN_CHAIN`) :
1. Vérifier le proxy d'entreprise (ex: config système / variables `HTTP_PROXY` / `HTTPS_PROXY`).
2. Ajouter le certificat racine interne dans le magasin système.
3. En dernier recours (non recommandé long terme) :
  ```powershell
  setx NODE_TLS_REJECT_UNAUTHORIZED 0
  # puis dans un nouveau terminal
  python -m playwright install chromium
  ```
4. Pour CI sans navigateur : utiliser `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1` puis installer au runtime contrôlé.

Retirer la désactivation TLS aussitôt que la chaîne de confiance est corrigée.

---
## 🎯 Détection Signal Recrutement (Nouveauté)
Objectif : identifier les posts susceptibles d'être des signaux de recrutement (annonce explicite, sourcing, besoins équipe, ouverture de poste) dans les domaines juridiques / fiscaux / data / tech.

### Heuristique
La fonction `compute_recruitment_signal(text)` applique :
1. Normalisation (lowercase, accents retirés, ponctuation simplifiée)
2. Tokenisation + stemming très léger (suffixes français usuels)
3. Pondération :
   - Mots/lemmes indicateurs (ex: `recrut`, `poste`, `hiring`, `rejoindre`, `talent`, `cdi`, `alternance`) ⇒ poids individuel
   - Phrases clés (bigrammes / trigrammes) comme `nous recrutons`, `on recrute`, `offre d emploi`, `recherche son/sa`, `hiring for`, `join our team` ⇒ bonus supplémentaire
4. Score brut lissé et clampé dans [0,1] (log / normalisation longueur pour éviter sur-pondération de répétitions).

### Seuil & Métrique
- Le seuil configuré via `RECRUITMENT_SIGNAL_THRESHOLD` (ex: 0.35) détermine l'incrément de la métrique `scrape_recruitment_posts_total`.
- Tous les posts stockent de toute façon `recruitment_score` (nullable si ancienne donnée ou mode legacy).

### Filtrage Dashboard & API
- Dashboard : champ numérique "Score recrutement ≥" (query param `min_score`).
- API `/api/posts?min_score=0.4` renvoie uniquement les posts dont `recruitment_score` ≥ valeur.
  - Si `min_score` absent ⇒ pas de filtrage.

### Stockage & Compatibilité
- Mongo : champ `recruitment_score` ajouté dans chaque document (nullable).
- SQLite : colonne ajoutée automatiquement si base créée après la fonctionnalité; pour une base existante exécuter :
  ```sql
  ALTER TABLE posts ADD COLUMN recruitment_score REAL;
  ```
  (Optionnel : laisser NULL pour historiques.)
- CSV : nouvelle colonne `recruitment_score` après `score`.

### Tests
`tests/test_recruitment_scoring.py` couvre :
- Bas niveau sur texte neutre (score faible)
- Texte riche en signaux (score élevé)
- Stabilité du domaine [0,1]

### Ajustements Futurs (Idées)
- Pondération contextuelle (ex: présence d'un lien vers une offre)
- Détection langue + mapping lexiques multi-langues
- Modèle ML léger (TF-IDF / logreg) si corpus étiqueté interne disponible
- Décorrélation bruit marketing vs. véritables annonces via pattern négatifs

---
## 🔄 Fallback Storage Testé
Un test (`tests/test_fallback_storage.py`) vérifie :
1. Insertion SQLite quand Mongo absent.
2. Fallback CSV forcé en simulant une erreur SQLite.

---
## 🧪 Configuration Lint & Type
Fichiers ajoutés : `ruff.toml`, `mypy.ini` pour cohérence multi-environnements.

---
## ⚙️ Nouveautés Techniques (v1.2.0+)
- **Champs quotidiens juridiques** : suivi des posts acceptés et rejetés par intent/location + quota journalier.
- **Rate limiting** : protection basique par IP (en mémoire) + seau de jetons (token bucket) pour limiter le scraping excessif.
- **Scrolling amélioré** : extraction progressive des résultats avec détection de complétude.
- **Signal de recrutement** : détection heuristique des posts à potentiel de recrutement dans les domaines cibles.
- **Fallback storage** : mécanisme de secours testable pour MongoDB → SQLite → CSV.
- **Tests & CI** : couverture accrue des tests, intégration continue avec GitHub Actions.

### Champs Quotidiens (Quota Juridique)
Suivi runtime (réinitialisé à minuit UTC):
| Champ | Description |
|-------|-------------|
| `legal_daily_date` | Date UTC suivie |
| `legal_daily_count` | Posts acceptés dans la journée |
| `legal_daily_discard_intent` | Rejets (intent) |
| `legal_daily_discard_location` | Rejets (location) |
Exposé via `/api/legal_stats`.

### Rate Limiting (IP In-Memory)
Paramètres :
```
API_RATE_LIMIT_PER_MIN=60
API_RATE_LIMIT_BURST=20
```
Limitation de base par IP (LRU ~512 IP). À distribuer via Redis pour déploiements multi-instances. Métrique de rejet: `api_rate_limit_rejections_total`.

### Token Bucket (Rate Limit Réel)
### Scrolling & Complétude (Nouveautés)
Nouveaux paramètres pour affiner l'extraction progressive des résultats paresseusement chargés :
```
MAX_SCROLL_STEPS=5      # Limite dure d'itérations de scroll supplémentaires
SCROLL_WAIT_MS=1200     # Attente (ms) après chaque scroll pour laisser charger le DOM
MIN_POSTS_TARGET=10     # Seuil minimal de posts avant d'accepter un arrêt anticipé
```
Logique d'arrêt :
1. Posts >= `MAX_POSTS_PER_KEYWORD` ⇒ stop
2. Posts >= `MIN_POSTS_TARGET` ET aucune augmentation après une itération ⇒ stop
3. `MAX_SCROLL_STEPS` atteint ⇒ stop (marqué incomplete si < seuil)

Métriques associées :
- `scrape_scroll_iterations_total` : incrémentée à chaque scroll tenté
- `scrape_extraction_incomplete_total` : incrément si extraction < `MIN_POSTS_TARGET` en fin de boucle

Objectif : instrumenter la « profondeur » requise pour atteindre la complétude et calibrer les valeurs par environnement (CI vs prod restreinte).

Paramètres :
```
RATE_LIMIT_BUCKET_SIZE=120      # Capacité maximale (burst autorisé)
RATE_LIMIT_REFILL_PER_SEC=2.0   # Débit de régénération
```

---
## 🔧 Classifier Tuning (Legal Intent)
Le classifieur heuristique privilégie la précision (faible taux de faux positifs). Pour augmenter le rappel :

### Paramètres rapides
| Levier | Effet | Recommandation |
|--------|-------|----------------|
| `LEGAL_INTENT_THRESHOLD` | Abaisse le seuil d'acceptation | Descendre par paliers de 0.05 (min conseillé 0.20) |
| `FILTER_LEGAL_DOMAIN_ONLY` | Pré-filtre hors domaine | Désactiver (`0`) si couverture multi-domaine souhaitée |
| `RECRUITMENT_SIGNAL_THRESHOLD` | Influence posts retenus avant classification (filtre opportunités) | Synchroniser avec intention si trop strict |

### Stratégies d'amélioration rappel
1. Ajouter des expressions explicites dans les phrases de recrutement (liste `RECRUITMENT_PHRASES`) – pull request ciblée.
2. Étendre `LEGAL_ROLE_KEYWORDS` pour nouveaux intitulés rares (ex: "compliance officer", "juriste propriété intellectuelle").
3. Introduire un mode "exploratoire" : activer une variable `LEGAL_EXPLORATORY_MODE=1` (à implémenter) qui :
   - Abaisse le seuil de 0.05 automatiquement sur les 10 premiers posts rejetés.
   - Loggue chaque acceptation marginale avec un tag `exploratory_accept`.
4. Collecter un corpus étiqueté interne (≥300 exemples) pour calibrer un modèle léger (logreg TF-IDF) – future optional.

### Indicateurs à surveiller
| Métrique | Interprétation | Action si anomalie |
|----------|----------------|--------------------|
| `legal_posts_discarded_total{reason="intent"}` / `legal_intent_classifications_total` | Taux de rejet intent élevé | Vérifier faux négatifs, ajuster seuil |
| `legal_daily_cap_reached_total` | Cap atteint tôt dans la journée | Augmenter cap ou restreindre mots-clés |
| `rejection_rate` (API stats) > 0.7 | Classifieur trop strict | Ajouter phrases / baisser seuil |

### Procédure de tuning contrôlé
1. Baisser `LEGAL_INTENT_THRESHOLD` de 0.35 → 0.30 sur un run test (mock ou dataset capturé).
2. Comparer : nombre d'acceptations + spot-check manuel (échantillon 20 posts nouveaux).
3. Si <10% d'acceptations semblent des faux positifs, conserver ; sinon revenir et enrichir phrases clés.
4. Documenter la décision dans `CHANGELOG.md`.

### Future Idea: Adaptive Threshold
Pseudocode (non implémenté) :
```python
if last_50_decisions and rejection_rate_last_50 > 0.85:
    threshold = max(base_threshold - 0.05, 0.20)
else:
    threshold = base_threshold
```
Avantage: augmente rappel lors de phases de sous-couverture sans relâcher durablement la précision.

---

