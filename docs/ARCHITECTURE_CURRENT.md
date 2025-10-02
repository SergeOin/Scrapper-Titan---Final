## Architecture Courante (Etat Actuel avant Refactor S1)

Ce document capture un instantané de l'architecture et des dépendances **avant** l'exécution des refactors structurants (Sprints 2+). Il sert de base de comparaison et de point d'appui pour mesurer la réduction de la complexité et l'isolement des responsabilités.

### Objectifs de ce snapshot

- Figer les responsabilités actuelles (même si elles sont entremêlées)
- Localiser la logique métier dispersée (stockage, filtrage, heuristiques)
- Identifier les dépendances transverses (metrics, logging, SSE, settings)
- Préparer la découpe (worker runtime, pipeline stockage, services API)

---

### Vue Macro

```text
┌──────────────────────────┐        ┌──────────────────┐
│   FastAPI (server/)      │  HTTP  │  Client (Browser)│
│  - main.py               │<──────>│  Dashboard (SSE) │
│  - routes.py             │ SSE    └──────────────────┘
│  - templates/dashboard   │
└──────────┬───────────────┘
           │ calls
           ▼
┌──────────────────────────┐   uses     ┌──────────────────┐
│  scraper/worker.py       │<──────────>│ scraper/utils.py │
│  (job orchestration)     │            └──────────────────┘
│   - scraping réel/mock   │
│   - filtres & heuristiques│  metrics  ┌──────────────────┐
│   - stockage multi-backend│<-------->│ Prometheus client │
│   - SSE broadcast (via ctx)│          └──────────────────┘
└──────────┬────────────────┘
           │ context
           ▼
┌──────────────────────────┐  init   ┌────────────────────┐
│ scraper/bootstrap.py     │<------>│ Settings (env/.env) │
│ - logging / metrics      │         └────────────────────┘
│ - mongo / redis / sqlite │
│ - token bucket           │
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────┐
│   Stockage Actuel        │
│  Mongo (prioritaire)     │
│  SQLite fallback         │
│  CSV (3ème niveau)       │
└──────────────────────────┘
```

---

### Contexte Global & Couplages

Le module `bootstrap.py` construit un objet contexte (`AppContext`) partagé contenant :

- Clients (Mongo, Redis, SQLite cursor)
- Paramètres (Pydantic settings)
- Logger structlog enrichi
- Compteurs / histos Prometheus
- Token bucket (rate limit scraping)

Ce contexte est **consommé directement** par :

- `worker.py` (fort couplage : stockage direct, metrics, SSE, settings mutés)
- `routes.py` (lecture meta, stats, toggles runtime, opérations SQLite directes)

---

### Points de Friction Identifiés

| Domaine | Observation | Impact |
|---------|-------------|--------|
| Orchestration | `worker.py` agrège scraping, filtrage, heuristiques, stockage, SSE | Difficulté test unitaire ciblé |
| Stockage | Insertion Mongo/SQLite/CSV inline dans worker + endpoints | Duplication logique / impossibilité de swap backend sans toucher worker |
| API Routes | `routes.py` contient logique métier (flagging, dérivation company, pagination SQL) | Gonflement fichier + couplage direct SQLite |
| Meta/Stats | Mise à jour meta dispersée | Lecture/écriture non centralisée |
| SSE | Appelé directement depuis worker (pas d'abstraction d'événements) | Freine extension vers file d'événements |
| Filtrage | Heuristiques & filtres codés inline (recruitment, auteur, langue) | Reuse limité / testabilité réduite |
| Gestion erreurs Playwright | Mélangée dans la boucle principale | Lisibilité réduite + branchement fallback mock étroit |
| Code legacy | Bloc post-`return` dans `process_job` toujours unreachable | Risque confusion future / dette |

---

### Mesures de Complexité (qualitatives)

- `worker.py` >1200 lignes (monolithe) : seuil de refactor immédiat.
- `routes.py` volumineux (mix rendu HTML + API JSON + opérations SQL) : séparation prévue.
- Multiples try/except larges : invisibilisent erreurs logiquement récupérables.

---

### Flux d'un Job (Etat Actuel Simplifié)

1. Lecture mots-clés settings (`SCRAPE_KEYWORDS` ou payload job Redis)
2. Préparation navigateur (réel) ou synthèse (mock)
3. Extraction par mot-clé (scroll, parse) accumule posts bruts
4. Filtres inline (auteur/permalink, langue, heuristique recrutement, démo, etc.)
5. Déduplication multi-niveaux (permalink > auteur+date > auteur+hash contenu)
6. Stockage séquentiel (Mongo → fallback SQLite → fallback CSV)
7. Mise à jour meta + métriques + SSE
8. Quota quotidien & compteurs internes

---

### Dépendances Directes Actuelles par Composant

| Composant | Dépendances principales |
|-----------|-------------------------|
| `worker.py` | context (mongo/sqlite/redis/settings), utils, prometheus_client, asyncio, os, heuristiques inline |
| `routes.py` | FastAPI, Jinja2, sqlite (direct), context, settings, utils |
| `bootstrap.py` | pydantic-settings, motor, aioredis/redis, sqlite3, structlog, prometheus_client |
| `utils.py` | random, datetime, regex, scoring heuristics (autonome) |

---

### Risques Courants

- Régression silencieuse lors futur découpage (absence de tests sur pipeline complet).
- Erreurs Playwright masquées (suppression bruit) retardant détection coûts réels.
- Ajout futur d'un backend (par ex. Parquet) hautement intrusif sans abstraction.

---

### Opportunités de Refactor (Alignées sur Plan Sprints)

| Cible | Action (futur) | Bénéfice |
|-------|----------------|----------|
| Orchestration | Extraire `runtime/` (plan S2) | Surface de test réduite |
| Stockage | `storage_pipeline.py` interface + impls (S2) | Swap backend / tests isolés |
| Routes | Séparer dashboard vs. API vs. admin (S3) | Moins de couplage UI / logique |
| SSE | Bus d'événements interne (S3) | Extensibilité (websocket, queue) |
| Filtrage | Module `filters/` (S2-S3) | Réutilisation / tests ciblés |
| Meta | Service `meta_service.py` | Centralisation stats |

---

### Décisions Documentées

- Ne pas supprimer immédiatement le code unreachable : l'annoter (TODO) pour PR dédiée (risque de mélange refactor + suppression).
- Réutiliser `scripts/smoke_test.py` pour Sprint 1 (pas de duplication).
- Documentation architecture figée ici pour comparaison après S4.

---

### Indicateurs de Réduction de Complexité (à mesurer après refactor)

| Indicateur | Actuel | Cible Post S4 |
|------------|--------|---------------|
| Lignes `worker.py` | >1200 | <400 (découpé) |
| Fonctions >150 lignes | Plusieurs | 0 |
| Points d'écriture meta | 3+ | 1 service |
| Accès direct SQLite hors stockage | Oui | Non |

---

### Annexes

Un export statique des imports pourra être régénéré plus tard pour constater la réduction (ex: via `pip install pydeps` en local – non ajouté comme dépendance runtime).

---

### Références

- Plan de refactor : `docs/REFRACTOR_PLAN.md`
- README principal : `README.md`

---

Dernière mise à jour : (Sprint 1, initial)
