# Master Delivery Playbook – Titan Scraper

Date: 2025-10-02
Mainteneur: Chef de projet (toi ici)

## 1. Résumé Exécutif

Objectif: livrer une solution clé en main qui permet de scraper des posts LinkedIn ciblés, de les afficher dans un dashboard ergonomique, et de distribuer facilement l’application via un installateur MSI Windows, tout en assurant un fonctionnement robuste (tests, sécurité, observabilité, opérations).

Principes:

- Expérience utilisateur immédiate (zero-config): installation MSI → lancement → posts mock ou réels affichés.
- Architecture modulaire: séparation runtime worker, stockage, API/dashboard pour faciliter maintenance.
- Automatisation bout-en-bout: CI/CD, tests, packaging.
- Documentation vivante et traçable.

## 2. Étapes Macro

| Phase | Description | Livrables | Justification |
|-------|-------------|-----------|---------------|
| Analyse | Compréhension existant, risques, cartographie | `ARCHITECTURE_CURRENT.md`, `dep_graph.md`, backlog risque | Base objective pour refactor/planification |
| Conception | Plan technique & produit | `REFRACTOR_PLAN.md`, `DELIVERY_PLAN.md`, ce playbook | Alignement vision ↔ exécution |
| Développement | Implémentation itérative (Sprints S2–S6) | Modules runtime, storage pipeline, sécurité, observabilité | Réduction dette + fiabilisation |
| Tests | Approfondissement couv. tests + scénarios E2E | Suites pytest, smoke CI, bench, checklist QA | Garantit non-régression |
| Packaging | Build MSI, Docker images, versioning | Scripts build, pipeline CI release, MSI signé | Distribution simple |
| Livraison | Release candidate puis GA | MSI, doc, changelog, check-list signée | Produit prêt à l’emploi |

## 3. Découpage Sprint (rappel enrichi)

| Sprint | Thème | Livrables principaux | Justification |
|--------|-------|----------------------|---------------|
| S1 (done) | Analyse & hardening | Docs architecture, smoke, annotation code mort | Vision claire avant refactor |
| S2 | Refactor runtime | `scraper/runtime/` modules (dedup, mock, pacing, pipeline) + tests | Réduction complexité worker |
| S3 | Stockage & queue | `StoragePipeline`, job tracking, endpoints jobs | Fiabilité persistance |
| S4 | Tests & migrations | Migrations SQLite, couverture ≥80% modules, tests API | Sécurité des refactors |
| S5 | Observabilité | Traces OpenTelemetry, benchmarks, tuning perf | Supervision et performance |
| S6 | Sécurité | Middleware headers, rate limit distribué, audit deps | Durcissement production |
| S7 | Packaging & CI/CD | MSI build/sign, pipeline release, versioning | Distribution clé en main |
| S8 (opt.) | Valeur métier | Parquet, webhooks, ML scoring | Bonus business |

## 4. Architecture Cible

```text
client (desktop/web) → server (FastAPI) → runtime (job orchestrator) → storage pipeline → backends (Mongo/SQLite/CSV)
                                                  ↑
                                           filters/dedup/pacing modules
```

### Choix technologiques

- **FastAPI** (existant): rapide, async, extensible (SSE, API).
- **Python runtime**: Playwright + modules custom pour heuristiques; maintenabilité accrue via modules `runtime/`.
- **Storage**: Mongo + SQLite fallback (pragmatique, déjà en place). Ajout pipeline abstraction.
- **Packaging**: PyInstaller (existant) + WiX Toolset ou `PyInstaller --msi` (à valider). Justification: intégration Windows + scripts existants.

## 5. Décisions Techniques Clés

1. **Modularisation worker** (S2) → facilite tests unitaires, améliore réutilisation, prépare pipeline storage.
2. **StoragePipeline** (S3) → standardise insertions et métriques, évite duplication.
3. **Migrations SQLite** (S4) → sécurité des évolutions schema.
4. **Observabilité** (S5) → instrumentation pour prouver performance & debugging rapide.
5. **Sécurité** (S6) → défense en profondeur avant packaging.
6. **Packaging** (S7) → MSI Reproducible, pipeline release, doc utilisateur.

## 6. Dépendances & Gestion

| Catégorie | Détails | Gestion |
|-----------|---------|---------|
| Playwright | Installation via CI + scripts; mode mock par défaut | `PLAYWRIGHT_MOCK_MODE`, job smoke |
| Mongo / Redis | Optionnels selon env; fallback SQLite | variables `.env`, documentées |
| Librairies Python | `requirements.txt` (verrouillage ~=) | pip + future `requirements-dev.txt` |
| MSI Tooling | PyInstaller + WiX (scripts `build_msi.ps1`) | Runner Windows CI + docs |
| WebView2 (desktop) | `MicrosoftEdgeWebView2Setup.exe` déjà dans `build/` | Inclure dans MSI |
| Dashboard (UI) | Jinja2 + HTMX (si extension) | Maintien template dans `server/templates` |

## 7. Plan de Tests

| Type | Outils | Exemples |
|------|--------|----------|
| Unitaires | pytest | `runtime/dedup`, `runtime/mock` |
| Intégration | pytest async | pipeline job mock → storage |
| API | httpx AsyncClient | `/api/posts`, `/api/stats` |
| E2E mock | `scripts/smoke_test.py` + job CI | baseline < 15s |
| Performance | script bench | temps job mock + latence API |
| MSI QA | script QA manuel + check auto | install/uninstall, smoke |

### Organisation tests

- Dossiers `tests/` existants enrichis (S2–S4).
- Ajout tests runtime extraits lors création des modules.
- Ajout bench script (S5).
- Pipeline CI (jobs `smoke` + `build-test` + `release`).

## 8. Packaging & Livraison

### MSI Workflow (S7)

1. Préparer spec PyInstaller dédiée (desktop + worker).
2. Exécuter `scripts/build_msi.ps1` (adapter si besoin). Utiliser WiX pour MSI.
3. Inclure assets (icône, WebView2 installer, config `.env.example`).
4. Signer MSI (cert interne ou script stub si pas dispo).
5. Tests: install/uninstall, smoke, vérification logs.
6. Publier artefact (CI `release` job).

### Livraison Server/Cloud

- Dockerfile existant → pipeline release (S7) push image.
- Docs `README`, `DELIVERY_PLAN`, ce playbook.
- `VERSION` bump + changelog auto.

## 9. Gouvernance & Communication

- RACI détaillé dans `DELIVERY_PLAN.md`.
- Communication fin de sprint: doc + démo (voir plan).
- Issues Git correspondant aux backlog items (B1..B9) + risques (R1..R6).

## 10. Risques & Mitigations (complément)

| ID | Risque | Impact | Mitigation |
|----|--------|--------|-----------|
| R7 | Temps smoke trop long | Medium | Optimiser init mock (pacing/module) |
| R8 | MSI dépendances manquantes | High | Checklist asset + tests VM |
| R9 | Incompatibilité Windows (Python 3.12) | Medium | Tests sur Windows 10/11 |

## 11. Checklists

### Pré-Sprint S2

- [x] Branche refactor S2 créée.
- [x] Extraction `dedup` initiale.
- [ ] Extraire `mock` + tests.
- [ ] Initialiser `runtime/pipeline.py` skeleton.

### Pré-Sprint S7 (Packaging)

- [ ] Vérifier build PyInstaller → exe fonctionnel.
- [ ] Documenter scripts MSI (inputs/outputs).
- [ ] Préparer environnement CI Windows (certs, outils).
- [ ] Définir test QA MSI (script + doc).

### Pré-Livraison GA

- Voir `DELIVERY_PLAN.md` section 15 (checklist pré-release).

## 12. Annexes & Références

- `docs/REFRACTOR_PLAN.md`
- `docs/DELIVERY_PLAN.md`
- `docs/ARCHITECTURE_CURRENT.md`
- `docs/dep_graph.md`

Mise à jour continue : ce playbook doit être révisé à chaque jalon majeur.
