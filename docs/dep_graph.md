# Graphe de Dépendances (Snapshot Sprint 1)

Ce fichier illustre les dépendances internes majeures (niveau dossier / module principal). Il NE couvre pas chaque fonction mais permet d’identifier les zones de couplage fort avant refactor.

## Légende

- (ctx) : utilisation du contexte initialisé dans `bootstrap`
- (metrics) : exposition / incrément de métriques Prometheus
- (db) : accès direct Mongo / SQLite / CSV

```mermaid
graph TD
  subgraph Server
    A[server/main.py] --> B[server/routes.py]
  end
  subgraph Scraper Core
    C[scraper/bootstrap.py]
    D[scraper/worker.py]
    E[scraper/utils.py]
    F[scraper/playwright_sync.py]
    G[scraper/session.py]
    H[scraper/rate_limit.py]
    I[scraper/maintenance.py]
  end
  subgraph Domain
    J[domain/models.py]
  end
  subgraph Scripts
    K[scripts/smoke_test.py]
  end

  A -->|mounts| B
  A -->|init ctx| C
  B -->|ctx (read/write)| C
  B -->|import| E
  B -->|raw sqlite ops| C
  D -->|ctx| C
  D -->|utils| E
  D -->|playwright async/sync| F
  D -->|session mgmt| G
  D -->|rate limiting| H
  D -->|maintenance trigger| I
  D -->|models| J
  D -->|metrics| C
  K -->|ctx| C
  K -->|worker orchestrator| D
  J -->|used by| B

  C -->|creates| H
  C -->|creates| metrics[(Prometheus Collectors)]
```

## Observations

- `worker.py` dépend d’un large ensemble (goulot principal de complexité).
- `routes.py` accède au stockage SQLite via le contexte sans abstraction.
- Les scripts (ex: smoke) consomment directement le worker – aucune couche API interne.

## Points d’attention pour S2–S3

- Introduire une façade `runtime/` pour réduire les imports directs de `worker.py`.
- Extraire un module `storage/` pour que `routes.py` cesse d’accéder au DB driver brut.
- Créer un bus d’événements interne pour découpler SSE du worker.

_Généré manuellement Sprint 1. Une version automatisée (pydeps) pourra être ajoutée plus tard._
