# Refactor Plan (Sprints)

> Version initiale – généré le 2025-10-02. Ce document structure la transformation progressive du scraper LinkedIn (Titan) vers une architecture plus modulaire, testable et observable. Les sprints supposent une cadence de 2 semaines et une équipe de 1–2 développeurs.

---

## Vue d’Ensemble (Roadmap)

| Sprint | Thème Principal | Objectif Synthétique |
|--------|-----------------|----------------------|
| S1 | Cartographie & Hardening | Stabiliser, éliminer code mort, smoke path fiable |
| S2 | Refactor Worker | Décomposer orchestration / réduire complexité |
| S3 | Stockage & Queue | Pipeline de persistence robuste + job tracking |
| S4 | Tests & Schéma | Couverture élevée, migrations versionnées |
| S5 | Observabilité & Performance | Traces, histogrammes, optimisations ciblées |
| S6 | Sécurité & Conformité | Durcissement headers, rate limit distribué, audit |
| S7 | DX & CI/CD & Packaging | Pipelines complets, packaging formalisé |
| S8* | Valeur Métier (Optionnel) | Export parquet, webhooks, scoring ML léger |

\* S8 dépend de finalisation S1–S5.

---

## Principes Généraux

- **Refactor progressif**: feature flags / variables d’env `NEW_*` pour activer les modules réécrits.
- **Tests avant suppression**: ajouter tests de comportement (snapshot / endpoints) avant retirer legacy.
- **Incrémentalité**: chaque sprint livrable en production sans régression.
- **Observabilité early**: instrumentation dès S2 sur nouveaux modules pour comparer perfs.
- **Documentation vivante**: chaque sprint met à jour ce fichier + `ARCHITECTURE_CURRENT.md` / `ARCHITECTURE_TARGET.md`.

---

## Sprint 1 — Analyse Profonde & Hardening Minimal

**Objectif**: Réduire incertitude et poser base du refactor.

### Périmètre (S1)

- Générer diagramme dépendances (imports internes) – Mermaid ou PlantUML.
- Identifier code mort / unreachable (`worker.py` post-return blocks).
- Script smoke end-to-end (mode mock): `scripts/smoke_mock.py` (POST /trigger → stockage SQLite → /api/stats non vide).
- Verrouiller versions critiques (Playwright, FastAPI) / pré-config pour lock futur.
- Documentation de l’architecture actuelle (`docs/ARCHITECTURE_CURRENT.md`).
- Vérifier `.gitignore` secrets (storage_state, sessions) + alerte si présent.
- Créer fixtures de tests de base (posts synthétiques standardisés).

### Livrables (S1)

- Diagramme `docs/dep_graph.md` (LIVRÉ).
- Rapport code mort + PR supprimant sections obsolètes (ANNOTÉ: bloc unreachable marqué, suppression planifiée S2 pour commit dédié).
- Script smoke + README section “Smoke Test” (EXISTANT: réutilisation `scripts/smoke_test.py`, ajout lien README prévu).
- Doc architecture actuelle `docs/ARCHITECTURE_CURRENT.md` (LIVRÉ).

### Critères d’Acceptation (S1)

- Smoke test renvoie statut 0 et ≥1 post mock (À VALIDER par exécution locale/CI).
- Code unreachable supprimé (DÉCALÉ: suppression en Sprint 2 pour commit isolé — annotation présente).
- README mis à jour (PARTIEL: liens vers plan & architecture ajoutés; ajouter section "Smoke Test" restante).

### KPIs (S1)

- Temps smoke < 15 s local (À MESURER).
- 100% modules cartographiés (COUVERT par `dep_graph.md`).
- LOC supprimées (dette) ≥ seuil défini (REPORT: suppression différée — KPI recalculé début S2).

### Risques / Mitigations (S1)

| Risque | Mitigation |
|--------|-----------|
| Suppression code utilisé indirectement | Step: tracer imports + tests avant suppression |
| Dérive du scope (diagrammes complexes) | Limiter à un niveau profondeur (ex: 2) |

---

## Sprint 2 — Refactor Orchestration du Worker

**Objectif**: Diminuer complexité cyclomatique, clarifier responsabilités.

### Périmètre (S2)

Créer sous-paquet `scraper/runtime/` avec modules :

- `pacing.py` (human-mode & adaptive pauses)
- `risk.py` (counters & cooldown)
- `session.py` (lancement / navigation / screenshots fin de batch)
- `mock.py` (génération de posts synthétiques)
- `dedup.py` (logique de déduplication multi-niveaux)
- `pipeline.py` (exécution job → materialisation → storage)

Introduire:

- `JobResult` dataclass (posts, unknown_authors, mode, duration_sec).
- Facteur unique fast-first-cycle.
- Point d’entrée: `run_job(keywords, ctx)`.

### Livrables (S2)

- Nouveau worker orchestré par modules.
- Tests unitaires ≥60% couverture nouveaux modules.
- `docs/ARCHITECTURE_TARGET.md` (vision après refactor worker).

### Critères d’Acceptation (S2)

- Smoke test passe.
- Complexité cyclomatique `worker.py` réduit >50%.
- Temps job mock variation ≤ ±10% baseline.

### KPIs (S2)

- Couverture modules refactor ≥60%.
- Taille `worker.py` < 800 lignes.
- Nouveau code testé: 6+ fichiers.

### Risques / Mitigations (S2)

| Risque | Mitigation |
|--------|-----------|
| Over-splitting (fragmentation) | Garder modules >80 LOC cohérents |
| Cycles d’import | Intégration continue mypy + script cycle detector |

---

## Sprint 3 — Chaîne de Stockage & Queue Robuste

**Objectif**: Assurer fiabilité des insertions et résilience job.

### Périmètre (S3)

- Interface `StorageBackend` (MongoStorage, SQLiteStorage, CsvFallback).
- `StoragePipeline` avec métriques (succès / erreurs / latence par backend).
- Indexes Mongo (permalink unique sparse, author+published_at, content_hash; script idempotent).
- Fiabilisation queue: visibilité / réinjection (Redis zset + timestamps) OU heartbeat + requeue simple.
- Table `jobs` (job_id, started_at, finished_at, status, mode, posts_count).
- Endpoints `/api/jobs/latest`, `/api/jobs/{id}`.

### Livrables (S3)

- Module `storage/` + tests fallback.
- Script `scripts/create_indexes.py`.
- Nouveaux endpoints jobs.

### Critères d’Acceptation (S3)

- Test simulate Mongo failure → SQLite success.
- Crash mid-job → job reprocessable / pas de pertes silencieuses.
- Index script ré-exécuté sans erreur.

### KPIs (S3)

- Couverture stockage ≥70%.
- Temps insertion 50 posts Mongo <300 ms (local).
- Taux d’erreurs pipeline test load = 0 faux positifs.

### Risques / Mitigations

| Risque | Mitigation |
|--------|-----------|
| Sur-architecture queue | Choisir pattern minimal (requeue TTL) d’abord |
| Écriture concurrente SQLite contention | Mode WAL + tests contention |

---

## Sprint 4 — Tests Étendus, Migration Schéma & Qualité Stricte

**Objectif**: Sécuriser l’évolution avec base de tests solide.

### Périmètre (S4)

- Versioning schéma SQLite (dossier `migrations/`).
- Script `scripts/migrate.py` (idempotent).
- Tests snapshot endpoints (`/api/stats`, `/health`, `/api/version`).
- Tests rate limiting API (burst → 429 / métrique incrémentée).
- Factories de tests (fixtures `conftest.py`).
- mypy mode strict sur nouveaux modules + utils.
- Pre-commit (ruff, black, mypy, pytest fast subset).

### Livrables (S4)

- `migrations/001_init.sql`, `002_add_job_table.sql`.
- Snapshots tests.
- Pre-commit config.

### Critères d’Acceptation (S4)

- Couverture globale scraper ≥80%, globale projet ≥60%.
- Migrations rejouables sans perte données.
- mypy strict zero errors cibles.

### KPIs (S4)

- Flakiness tests <2% (réexécution x5 stable).
- Durée suite complète <120 s local (hors Playwright réel).

### Risques / Mitigations (S4)

| Risque | Mitigation |
|--------|-----------|
| Explosion temps CI | Séparer fast suite vs full suite (cron / nightly) |
| Faux positifs snapshot (dérive timestamps) | Normaliser champs dynamiques |

---

## Sprint 5 — Observabilité Avancée & Performance

**Objectif**: Visibilité profonde et optimisation mesurée.

### Périmètre (S5)

- OpenTelemetry (traces job, navigation, extraction, storage) + exporter OTLP.
- Histogrammes additionnels: `navigation_time_seconds`, `extraction_time_seconds`, `store_time_seconds`, `queue_wait_seconds`.
- Profilage (pyinstrument) pre/post optimisation.
- Tuning SQLite (PRAGMA WAL, synchronous NORMAL) via flag.
- Cache LRU sur `compute_recruitment_signal` (text identique) – clé hash.
- Script bench `scripts/benchmark_job.py` (résultats -> `docs/perf/`).
- Dashboard Grafana JSON exemples.

### Livrables (S5)

- Traces visibles (console + option OTLP endpoint).
- Dashboard exemple.
- Rapport benchmark avant/après.

### Critères d’Acceptation (S5)

- Overhead instrumentation <10% sur job mock.
- P95 durée job mock -10% vs baseline (ou stable si déjà optimisée).
- Rapport bench committé.

### KPIs (S5)

- Spans/job <200.
- Gain insertion SQLite ≥10% (tuning activé).

### Risques / Mitigations (S5)

| Risque | Mitigation |
|--------|-----------|
| Bruit excessif traces | Regrouper spans micro-étapes |
| Optimisation prématurée | N’appliquer que si metrics > objectifs |

---

## Sprint 6 — Sécurité & Conformité

**Objectif**: Durcir surface d’attaque et conformité interne.

### Périmètre (S6)

- Middleware sécurité: CSP, HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy.
- Masquage conditionnel champs `raw` (config `SCRUB_RAW_FIELDS`).
- Rate limit distribué Redis (sliding window or token bucket IP).
- Audit dépendances (pip-audit / safety) intégré CI.
- Script rotation tokens secrets (`rotate_tokens.py`).
- Désactivation endpoints debug en prod (`DEBUG_ENDPOINTS=0`).

### Livrables (S6)

- Middleware + tests headers.
- Pipeline audit (fail on HIGH vuln non ignorée).
- Script rotation tokens.

### Critères d’Acceptation (S6)

- Headers présents et corrects (tests).
- 0 vulnérabilité HIGH non justifiée.
- Ratelimit distribué valide (2 instances simulées → compte partagé).

### KPIs (S6)

- Overhead middleware <5% latence.
- Taux rejet API (limite) cohérent test scénario (≥ attendu).

### Risques / Mitigations (S6)

| Risque | Mitigation |
|--------|-----------|
| Faux positifs audit | Fichier allowlist commenté |
| Ratelimit contournable (IP spoof) | Option future: clé session/auth renforcée |

---

## Sprint 7 — Expérience Développeur & CI/CD & Packaging

**Objectif**: Industrialiser le cycle de livraison.

### Périmètre (S7)

- Workflows CI (lint, mypy, tests, build image, scan vuln).
- Workflow CD (tag → image registry + publication wheel).
- `pyproject.toml` (PEP 621), séparation `requirements-dev.txt`.
- Templates PR / Issues, CONTRIBUTING.md, CODEOWNERS.
- Changelog automatique (conventional commits + script).

### Livrables (S7)

- `.github/workflows/ci.yml` & `cd.yml`.
- `pyproject.toml`, wheels générées.
- CONTRIBUTING + templates.

### Critères d’Acceptation (S7)

- CI <6 min exécution complète.
- Tag `vX.Y.Z` → image + wheel publiées.
- Smoke post-déploiement automatique réussi.

### KPIs (S7)

- Taux échec CI main <5%.
- Temps moyen merge PR réduit.

### Risques / Mitigations (S7)

| Risque | Mitigation |
|--------|-----------|
| Pipeline lent | Cache deps + matrix sélective |
| Divergence spec vs PyInstaller | Phase transition, tests binaires séparés |

---

## Sprint 8 (Optionnel) — Valeur Métier & Extensions

**Objectif**: Accroître valeur pour utilisateurs internes.

### Périmètre (S8 – Potentiel)

- Export Parquet (`export_parquet.py`) + stockage Data Lake (S3/MinIO).
- Webhooks `JOB_COMPLETE` (retries + DLQ locale).
- Endpoint GraphQL read-only (Strawberry/Ariadne) pour filtres complexes.
- Prototype scoring ML (logreg TF-IDF) si dataset labellisé.
- Dashboard enrichi (charts volumétrie, ratio unknown, progression quotas).
- Self-check selectors (alerte si extraction < seuil).

### Livrables (S8)

- Scripts export parquet.
- Webhook configurable (`WEBHOOK_URLS`).
- GraphQL schema + doc.
- Notebook ML expérimental.

### Critères d’Acceptation (S8)

- Export parquet ≤5% overhead vs CSV.
- Webhook retry 3x puis DLQ.
- GraphQL latence <150 ms requête simple.

### KPIs (S8)

- Adoption interne (feedback qualitatif).
- Décroissance temps d’analyse manuelle.

### Risques / Mitigations (S8)

| Risque | Mitigation |
|--------|-----------|
| Manque de données label ML | Phase collecte labels avant dev modèle |
| Surface attaque GraphQL | Depth limit + auth mandatory |

---

## KPIs Globaux Résumés

| Domaine | KPI | Cible |
|---------|-----|-------|
| Complexité | Cyclomatique worker | -50% fin S2 |
| Qualité | Couverture tests scraper | ≥80% fin S4 |
| Observabilité | P95 job mock | -10% fin S5 |
| Sécurité | Vulnérabilités HIGH | 0 fin S6 |
| DX | Durée pipeline CI | ≤6 min fin S7 |

### Baseline Mesures (S1)

| Indicateur | Valeur initiale | Méthode mesure | Statut |
|------------|-----------------|----------------|--------|
| Durée smoke test (mock) | (à mesurer) | `scripts/smoke_test.py` local/CI | PENDING |
| Posts mock générés/job | (attendu 5–10 selon keywords) | Log `smoke_test_summary` | PENDING |
| Taille `worker.py` (LOC) | >1200 | `cloc` ciblé | CAPTURÉ |
| Couverture actuelle globale | (à extraire) | `pytest --cov` | PENDING |

---

## Gestion des Risques Générale

| Risque | Impact | Stratégie |
|--------|--------|-----------|
| Régression silencieuse | Haute | Tests snapshot & smoke par sprint |
| Sur-refactor prématuré | Moyen | Découpage minimal viable (S2) |
| Dette tests accumulée | Haute | Sprint 4 dédié avant instrumentation avancée |
| Instabilité Playwright | Moyen | Auto-mock + monitoring launch_failures |
| Dérive sécurité | Haute | Sprint 6 dédié + audit automatisé |

---

## Plan de Communication Interne

| Jalons | Communication |
|--------|--------------|
| Fin S1 | Diffusion doc BEFORE + suppression code mort |
| Fin S2 | Démo worker modulaire + metrics invariantes |
| Fin S3 | Présentation tracking jobs + pipeline storage |
| Fin S4 | Badge couverture + rapport dette résiduelle |
| Fin S5 | Dashboard observabilité + traces exemple |
| Fin S6 | Rapport sécurité & correctifs |
| Fin S7 | Démo pipeline CI/CD tag→déploiement |
| Fin S8 | Démo valeur métier (webhooks/export/parquet) |

---

## Prochaines Actions Immédiates (Transition S1 → S2)

1. Ajouter section README "Smoke Test" (exécution & exit codes) pointant `scripts/smoke_test.py`.
2. Exécuter smoke dans CI (ajouter job rapide si non présent) et capturer durée baseline.
3. Préparer branche `feat/runtime_refactor_s2` pour extraction modules (pacing, dedup, mock...).
4. Déplacer suppression code unreachable dans PR dédiée en début S2 (après création tests de non-régression).
5. Lister fonctions cibles à extraire avec contrat succinct (pré-spécification S2).

---

*Fin du document – tenir ce fichier synchronisé avec l’avancement réel.*
