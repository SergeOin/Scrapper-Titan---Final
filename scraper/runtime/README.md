# Runtime Refactor Skeleton (Sprint 2)

Ce répertoire accueillera la décomposition du worker monolithique.

## Modules prévus

- `pacing.py` : gestion des délais adaptatifs / human-mode
- `risk.py` : compteurs de risques, cooldown
- `session.py` : gestion session navigateur (init, screenshots, fermeture)
- `mock.py` : génération de posts synthétiques isolée
- `dedup.py` : fonctions pures de déduplication
- `pipeline.py` : orchestrateur `run_job(keywords, ctx)` retournant `JobResult`

## Contrat cible (draft)

```python
@dataclass
class JobResult:
    posts: list[PostModel]
    unknown_authors: int
    mode: str  # 'mock' | 'async' | 'sync'
    duration_seconds: float
    started_at: datetime
    finished_at: datetime
```

## Principes

- Zéro dépendance circulaire : utilitaires communs dans `runtime/_base.py` si nécessaire.
- Pas d'accès direct SQLite/Mongo ici : utiliser une future abstraction `storage`.
- Toute métrique émise via fonctions wrapper (facile à mocker en tests).

_Mis en place en fin de Sprint 1 pour préparation Sprint 2._
