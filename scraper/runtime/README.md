# Runtime Refactor Skeleton (Sprint 2)

Ce répertoire accueille progressivement la décomposition du `worker.py` historique.

## Modules prévus

- `pacing.py` : gestion des délais adaptatifs / human-mode *(à venir)*
- `risk.py` : compteurs de risques, cooldown *(à venir)*
- `session.py` : gestion session navigateur (init, screenshots, fermeture) *(à venir)*
- `mock.py` : génération de posts synthétiques isolée ✅
- `dedup.py` : fonctions pures de déduplication ✅
- `pipeline.py` : `finalize_job_result` (dédup + matérialisation) livrée ; `run_job` reste à implémenter

> Dataclass partagée : `RuntimePost` vit désormais dans `runtime.models` et sert de base commune à l'orchestrateur et aux tests. `JobResult` y décrit l'enveloppe standard des exécutions.

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

*Mise à jour : Sprint 2 — extraction progressive en cours.*
