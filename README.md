# LinkedIn Scraper & Minimal Dashboard

> Usage interne uniquement. Respect strict des CGU LinkedIn. Ce projet fournit un worker de scraping découplé d'un serveur FastAPI avec un mini dashboard pour visualiser les posts collectés. Le bouton manuel de déclenchement a été retiré : on utilise désormais `POST /trigger` (script / API) ou l'intervalle autonome / worker dédié.

---
## 🎯 Objectifs
- Scraping de posts LinkedIn à partir de mots-clés ciblés (recherche)
- Stockage principal MongoDB (Atlas), fallback automatique SQLite ou CSV
- Worker asynchrone (séparé du serveur) + file/queue Redis pour jobs
- Dashboard FastAPI minimal (table paginée + stats) — plus de bouton de déclenchement dans l'UI
- Cache TTL & verrou anti-concurrence pour éviter sur-scraping
- Logging structuré JSON + rotation + métriques Prometheus `/metrics`
- Tests unitaires (pytest), linting Ruff, format Black, typage mypy
- Docker multi-stage prêt pour déploiement serveur Linux (Playwright installé)

---
## 🧱 Architecture (vue d'ensemble)

Documentation complémentaire :

- Architecture actuelle détaillée (snapshot pré‑refactor) : `docs/ARCHITECTURE_CURRENT.md`
- Plan de refactor multi-sprints : `docs/REFRACTOR_PLAN.md`

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

## ⚙️ Flux Fonctionnel (mise à jour sans bouton manuel)

1. L'utilisateur ouvre le dashboard ⇒ posts réels visibles (les posts démo sont exclus) + stats.
2. Un job est lancé via :
   - `POST /trigger` (curl / script / Postman / console navigateur)
   - le worker autonome (`AUTONOMOUS_WORKER_INTERVAL_SECONDS > 0`)
   - un worker séparé consommant Redis.
3. Worker ⇒ Playwright + session (`storage_state.json`).
4. Extraction + application des filtres stricts (langue, recrutement, auteur/permalink, France, exclusion job-seekers) sauf si relaxés.
5. Stockage Mongo ou fallback; mise à jour meta.
6. Logs + screenshots + métriques.
7. Dashboard rafraîchi via SSE (`/stream`) ou polling.

### Déclenchement manuel (exemples)

PowerShell :

```powershell
Invoke-RestMethod -Method POST -Uri http://localhost:8000/trigger -Headers @{ 'X-Trigger-From'='manual' }
```

Python :

```python
import requests; requests.post('http://localhost:8000/trigger', headers={'X-Trigger-From':'manual'})
```

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
| `PLAYWRIGHT_FORCE_SYNC` | Force un mode Playwright synchrone (fallback thread) si `1` | `0` |
| `AUTO_ENABLE_MOCK_ON_PLAYWRIGHT_FAILURE` | Active automatiquement mode mock si lancement Playwright échoue | `1` |
| `FORCE_PLAYWRIGHT_DISABLED` | Force désactivation Playwright (scraping réel) et bascule mock | `0` |
| `PLAYWRIGHT_FAILURE_LOG` | Fichier JSONL des erreurs Playwright throttlé | `playwright_failures.log` |
| `STORAGE_STATE_ENCRYPT` | Chiffrer `storage_state.json` sur disque (Fernet) | `1` |
| `STORAGE_STATE_KEY` | Clé base64 32 bytes pour Fernet (si chiffrement) | `gAAAA...` |
| `PURGE_MAX_AGE_DAYS` | Purge SQLite des posts plus vieux que X jours | `30` |
| `VACUUM_INTERVAL_HOURS` | Intervalle maintenance (purge+VACUUM) heures | `6` |
| `FILTER_RECRUITMENT_ONLY` | Ne conserver que les posts recrutement (>= seuil) | `1` |
| `FILTER_REQUIRE_AUTHOR_AND_PERMALINK` | Filtrer posts sans auteur/permalink | `1` |
| `PLAYWRIGHT_MOCK_MODE` | Mode simulation (aucune navigation réelle) | `0` |

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
Accéder au dashboard: <http://127.0.0.1:8000/>

Déclencher manuellement un job (sans UI) :

```powershell
python scripts\run_once.py --keywords "python;ai"
```

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

### 🔥 Smoke Test (Mode Mock)

Objectif : valider rapidement que le pipeline (context → job → stockage → meta) fonctionne sans navigateur réel.

Script : `scripts/smoke_test.py` (réutilisé au lieu de créer `smoke_mock.py`).

Pré‑requis : `PLAYWRIGHT_MOCK_MODE=1` et quelques mots-clés.

Exécution PowerShell :

```powershell
$Env:PLAYWRIGHT_MOCK_MODE='1'
$Env:SCRAPE_KEYWORDS='python;data'
python scripts/smoke_test.py
```

Sortie attendue (logs) : entrée `smoke_test_summary` avec `posts>0`.

Codes de retour :

| Code | Signification |
|------|---------------|
| 0 | Succès (≥1 post mock stocké) |
| 2 | Exécution ok mais 0 post (anormal en mock, investiguer filtres) |
| 3 | Exception inattendue |

Intégration CI recommandée : étape dédiée avant suite complète (rapide <15s). Exemple (GitHub Actions) :

```yaml
  - name: Smoke test
    run: |
      export PLAYWRIGHT_MOCK_MODE=1
      export SCRAPE_KEYWORDS='python;data'
      python scripts/smoke_test.py
```

Baseline durée sera consignée dans `docs/REFRACTOR_PLAN.md` Sprint 1 lorsque mesurée.

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
| `scrape_jobs_total` (label `status`) | Counter | Nombre de jobs traités par statut |
| `scrape_posts_extracted_total` | Counter | Total de posts extraits (par job) |
| `scrape_duration_seconds` | Histogram | Durée des jobs de scraping |
| `scrape_mock_posts_extracted_total` | Counter | Posts synthétiques générés (mode mock) |
| `scrape_storage_attempts_total` (labels `backend,result`) | Counter | Succès/erreurs par backend (mongo/sqlite/csv) |
| `scrape_queue_depth` | Gauge | Profondeur actuelle de la file de jobs Redis |
| `scrape_job_failures_total` | Counter | Nombre de jobs échoués (exceptions) |
| `scrape_step_duration_seconds` (label `step`) | Histogram | Durée de sous-étapes (mongo_insert, sqlite_insert, etc.) |
| `scrape_rate_limit_wait_seconds_total` | Counter | Secondes cumulées d'attente dues au rate limiting |
| `scrape_rate_limit_tokens` | Gauge | Jetons disponibles (bucket courant) |
| `api_rate_limit_rejections_total` | Counter | Requêtes API rejetées (limitation IP) |
| `scrape_scroll_iterations_total` | Counter | Nombre total d'itérations de scroll exécutées |
| `scrape_extraction_incomplete_total` | Counter | Extractions arrêtées (< `MIN_POSTS_TARGET`) |
| `scrape_recruitment_posts_total` | Counter | Posts détectés recrutement |
| `scrape_filtered_posts_total` (label `reason`) | Counter | Posts rejetés (recruitment, author_perma, langue, domaine ...) |

Endpoints opérationnels additionnels :
| Endpoint | Méthode | Description |
|----------|---------|-------------|
| `/health` | GET | Santé enrichie (ping Mongo, last_run, age, queue_depth, flags) |
| `/shutdown` | POST | Arrêt contrôlé (token + éventuellement basic auth) |
| `/debug/auth` | GET | Diagnostic session Playwright (storage_state, modes) |
| `/debug/last_batch` | GET | Derniers posts (auteur, company, keyword, timestamps) pour debug extraction |
| `/api/debug/raw_posts` | GET | Vue brute SQLite (inclure démo: `?include_demo=1`) |
| `/admin/filters/relax` | POST | Bypass filtres stricts extraction (désactive langage/recrutement/auteur/permalink/France/job seekers) |
| `/admin/filters/strict` | POST | Réactive filtres stricts |
| `/admin/purge_demo_posts` | POST | Purge `demo_recruteur` + flags orphelins |
| `/api/stats` | GET | Statistiques runtime agrégées (mock_mode, intervalle autonome, posts_count, âge last_run, queue_depth) |
| `/api/version` | GET | Métadonnées build (commit, timestamp) pour traçabilité |
| `/metrics.json` | GET | Fallback JSON si Prometheus non consommable (mode démo / sandbox) |
| `/debug/mode` | GET | Indique mode courant (mock, async, sync) |
| `/debug/storage/counts` | GET | Compteurs stockage SQLite (lignes) |
| `/debug/status` | GET | Statut synthétique (quotas, mode, risques) |

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
Fichiers utilisés: `render.yaml`, `Procfile`.
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

> Prochain fichier suggéré : `.env.example` ou squelette code (`bootstrap.py`). Dis-moi si on poursuit.

---
### 🔗 Documentation Technique Additionnelle
- Snapshot architecture courante : `docs/ARCHITECTURE_CURRENT.md`
- Roadmap refactor : `docs/REFRACTOR_PLAN.md`

---
### ℹ️ Endpoint `/api/stats`
Expose un sous-ensemble d'informations runtime pratiques pour monitoring léger (différent de `/health`):
```jsonc
{
  "playwright_mock_mode": false,
  "autonomous_interval": 0,
  "scraping_enabled": true,
  "keywords_count": 3,
  "mongo_connected": true,
  "redis_connected": false,
  "posts_count": 124,
  "last_run": "2025-09-19T09:10:11.123456+00:00",
  "last_run_age_seconds": 42,
  "queue_depth": 0
}
```
Utilisation: supervision simple (dashboards externes) sans parser les métriques Prometheus.

### 🔐 Hash Bcrypt automatique
Si vous définissez `INTERNAL_AUTH_PASS` (sans `INTERNAL_AUTH_PASS_HASH`) le hash est généré au démarrage via passlib (bcrypt==3.2.2). Pour changer le mot de passe en production, redéployer avec la nouvelle valeur ou basculer sur un hash explicite.

### 🏷️ Endpoint `/api/version`
Expose des métadonnées de build pour vérifier rapidement la version déployée.
Variables attendues (optionnelles) injectées au déploiement:
```bash
APP_COMMIT=abc1234           # SHA git court ou complet
BUILD_TIMESTAMP=2025-09-19T12:34:56Z
```
Réponse typique:
```jsonc
{
  "app_commit": "abc1234",
  "build_timestamp": "2025-09-19T12:34:56Z",
  "playwright_mock_mode": false
}
```
Sans injection, les valeurs retournent `"unknown"`. Utile pour dashboards légers ou vérifier qu’un redeploy a bien pris effet.

---
## 🧰 Automations & Tooling Ajoutés

### CI (GitHub Actions)
Workflow `ci.yml` : lint (ruff), format check (black), mypy, tests Pytest + couverture. Badge (à ajouter après push sur branche principale) :
```
![CI](https://github.com/<org>/<repo>/actions/workflows/ci.yml/badge.svg)
```

### Docker Compose
Fichier `docker-compose.yml` fourni :
```bash
docker compose up -d --build
# API: http://localhost:8000  | Mongo: 27017 | Redis: 6379
```
Le service `api` lance FastAPI (scraping désactivé), le service `worker` exécute le scraping.

### Script PowerShell `tasks.ps1`
Charger et lister :
```powershell
. .\tasks.ps1
Invoke-Task setup      # venv + deps + playwright
Invoke-Task lint       # ruff + mypy
Invoke-Task format     # ruff --fix + black
Invoke-Task test       # pytest
Invoke-Task coverage   # couverture
Invoke-Task server     # uvicorn
Invoke-Task worker     # worker loop
Invoke-Task compose-up # stack docker
Invoke-Task compose-down
```

### Mode Mock (Sans Navigateur)
Activer un mode de génération synthétique de posts pour tests rapides ou CI sans Playwright :
```
PLAYWRIGHT_MOCK_MODE=1
SCRAPING_ENABLED=1
```
Effets :
- `process_keyword` retourne jusqu'à 5 posts synthétiques par mot-clé sans ouvrir Chromium.
- Champs `raw.mode = "mock"` pour traçabilité.
- Idéal pour valider pipeline stockage / API sans réseau externe.
Limites : pas de vérification de sélecteurs ni réalisme de contenu.

### Gestion des posts de démonstration
- Les posts dont `author` ou `keyword` == `demo_recruteur` sont exclus de `/api/posts` et du dashboard.
- Diagnostics expose `sqlite.demo_posts`, `sqlite.real_posts`, `sqlite.only_demo`.
- Inspection brute : `/api/debug/raw_posts?include_demo=1`.
- Purge : `python scripts/purge_mock_posts.py --purge` ou `POST /admin/purge_demo_posts`.

### Premier cycle réel (checklist)
1. Purger contenu démo (voir ci-dessus).
2. (Option) Relaxer filtres: `POST /admin/filters/relax`.
3. `POST /trigger`.
4. Vérifier `/diagnostics.json` → `real_posts > 0`.
5. `POST /admin/filters/strict`.

### Toggle runtime filtres
```text
POST /admin/filters/relax   # PLAYWRIGHT_DISABLE_STRICT_FILTERS=1
POST /admin/filters/strict  # PLAYWRIGHT_DISABLE_STRICT_FILTERS=0
```
Flag visible dans diagnostics (`filters_relaxed`); posts relaxés portent `raw.filters_bypassed=1`.

### Purge script / endpoint
Script:
```powershell
python scripts/purge_mock_posts.py          # dry-run
python scripts/purge_mock_posts.py --purge  # suppression
```
Endpoint:
```powershell
Invoke-RestMethod -Method POST http://localhost:8000/admin/purge_demo_posts
```
Réponse: `{ removed, orphan_flags, duration_seconds }`.

Personnalisation :
`MAX_MOCK_POSTS` limite configurable (par défaut 5). Métrique associée : `scrape_mock_posts_extracted_total`.

### Concurrency & Rate Limiting (Nouveautés)
Variables :
```
CONCURRENCY_LIMIT=2            # Nombre max de jobs simultanés
PER_KEYWORD_DELAY_MS=500       # Délai entre deux mots-clés dans un même job
GLOBAL_RATE_LIMIT_PER_MIN=120  # Limite douce (placeholder token bucket simple)
```
Objectifs : réduire bursts, préparer extension vers un vrai seau de jetons distribué.
La métrique `scrape_queue_depth` permet de surveiller l'accumulation des jobs.

### API Rate Limit (IP In-Memory)
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
Fonctionnement : avant chaque mot-clé le worker consomme 1 jeton. Si insuffisant ⇒ attente calculée (deficit / refill_per_sec) mesurée dans `scrape_rate_limit_wait_seconds_total`. Le gauge `scrape_rate_limit_tokens` reflète l'état du bucket.

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

---
## 🔄 Fallback Storage Testé
Un test (`tests/test_fallback_storage.py`) vérifie :
1. Insertion SQLite quand Mongo absent.
2. Fallback CSV forcé en simulant une erreur SQLite.

---
## 🧪 Configuration Lint & Type
Fichiers ajoutés : `ruff.toml`, `mypy.ini` pour cohérence multi-environnements.

