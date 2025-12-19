# Guide de Migration - Nouveaux Modules Scraper

Ce guide explique comment activer progressivement les nouveaux modules du scraper.

## 🚀 Activation Rapide

### Via les Variables d'Environnement (recommandé en production)

```bash
# ===== ACTIVATION PAR PHASE (RECOMMANDÉ) =====

# Phase 1 - Faible risque: Cache + Scheduler
TITAN_ENABLE_PHASE1=1

# Phase 2 - Moyen risque: Phase1 + Keywords + Progressive
TITAN_ENABLE_PHASE2=1

# Tous les modules d'un coup
TITAN_ENABLE_ALL=1

# ===== ACTIVATION INDIVIDUELLE =====
TITAN_USE_POST_CACHE=1          # Déduplication
TITAN_USE_SMART_SCHEDULER=1     # Intervalles intelligents
TITAN_USE_KEYWORD_STRATEGY=1    # Rotation intelligente des mots-clés
TITAN_USE_PROGRESSIVE_MODE=1    # Limites adaptatives
TITAN_USE_UNIFIED_FILTER=1      # Filtre unifié
TITAN_USE_METADATA_EXTRACTOR=1  # Extraction robuste
TITAN_USE_SELECTOR_MANAGER=1    # Sélecteurs CSS dynamiques
TITAN_USE_ML_CLASSIFIER=1       # Classification ML
```

### Via l'API REST

```bash
# Voir les flags actuels
curl http://localhost:5050/api/feature_flags

# Activer Phase 1 (cache + scheduler)
curl -X POST http://localhost:5050/api/feature_flags/enable_phase1

# Activer Phase 2 (phase1 + keywords + progressive)  
curl -X POST http://localhost:5050/api/feature_flags/enable_phase2

# Activer tout
curl -X POST http://localhost:5050/api/feature_flags/enable_all

# Désactiver tout (retour mode legacy)
curl -X POST http://localhost:5050/api/feature_flags/disable_all

# Modifier un flag individuel
curl -X POST http://localhost:5050/api/feature_flags/set \
  -H "Content-Type: application/json" \
  -d '{"use_post_cache": true, "use_smart_scheduler": true}'
```

### Via le Code Python

```python
from scraper.adapters import (
    set_feature_flags, 
    enable_phase1, 
    enable_phase2, 
    enable_all_features,
    reload_flags_from_env,
)

# Activer Phase 1 (faible risque)
enable_phase1()

# Activer Phase 2 (après validation)
enable_phase2()

# Activer tous les modules
enable_all_features()

# Recharger depuis les variables d'environnement
reload_flags_from_env()

# Ou activer individuellement
set_feature_flags(
    use_keyword_strategy=True,    # Rotation intelligente des mots-clés
    use_progressive_mode=True,    # Limites adaptatives
    use_smart_scheduler=True,     # Intervalles intelligents
    use_post_cache=True,          # Déduplication
)
```

## 🧪 Validation avant Activation

Exécutez le script de validation pour vérifier que tous les modules fonctionnent :

```bash
# Test rapide (imports seulement)
python scripts/validate_modules.py --quick

# Validation Phase 1
python scripts/validate_modules.py --phase1

# Validation Phase 2
python scripts/validate_modules.py --phase2

# Validation complète
python scripts/validate_modules.py
```

## 📊 Nouveaux Endpoints API

| Endpoint | Méthode | Description |
|----------|---------|-------------|
| `/api/feature_flags` | GET | **Vue des flags actifs + phase courante** |
| `/api/feature_flags/set` | POST | Modifier des flags individuels |
| `/api/feature_flags/enable_phase1` | POST | Activer Phase 1 (cache + scheduler) |
| `/api/feature_flags/enable_phase2` | POST | Activer Phase 2 (+ keywords + progressive) |
| `/api/feature_flags/enable_all` | POST | Activer tous les modules |
| `/api/feature_flags/disable_all` | POST | Retour au mode legacy |
| `/api/selector_health` | GET | Santé des sélecteurs CSS |
| `/api/keyword_stats` | GET | Stats rotation mots-clés |
| `/api/progressive_mode` | GET | Mode actuel (conservative/moderate/aggressive) |
| `/api/progressive_mode/set` | POST | Changer le mode manuellement |
| `/api/scheduler_status` | GET | Status du scheduler |
| `/api/scheduler/pause` | POST | Pause le scraping |
| `/api/scheduler/resume` | POST | Reprend le scraping |
| `/api/cache_stats` | GET | Stats déduplication |
| `/api/cache/clear` | POST | Vider le cache |
| `/api/ml_status` | GET | Status ML |
| `/api/ml/switch_backend` | POST | Changer backend ML |
| `/api/system_health` | GET | **Santé unifiée de tous les modules** |

## 🔧 Migration Progressive

### Étape 1: Tester les modules individuellement

```python
# Dans worker.py, remplacer:
batch_size = 3
# Par:
from scraper.adapters import get_scraping_limits
limits = get_scraping_limits()
batch_size = limits.keywords_per_run
```

### Étape 2: Utiliser les adaptateurs

```python
# Au lieu de la rotation manuelle:
# _keyword_rotation_index = (_keyword_rotation_index + batch_size) % total

# Utiliser:
from scraper.adapters import get_next_keywords
keywords = get_next_keywords(all_keywords, batch_size=3)
```

### Étape 3: Enregistrer les résultats

```python
# Après chaque cycle de scraping:
from scraper.adapters import record_scrape_result

record_scrape_result(
    keywords_processed=keywords,
    posts_found=len(posts),
    posts_stored=stored_count,
    had_restriction=False,
    duration_seconds=elapsed,
)
```

## 📁 Structure des Fichiers

```
scraper/
├── adapters.py           # 🆕 Bridge pour migration progressive
├── selectors.py          # 🆕 Sélecteurs CSS dynamiques
├── keyword_strategy.py   # 🆕 Rotation intelligente
├── progressive_mode.py   # 🆕 Limites adaptatives
├── smart_scheduler.py    # 🆕 Intervalles intelligents
├── post_cache.py         # 🆕 Déduplication
├── metadata_extractor.py # 🆕 Extraction robuste
├── ml_interface.py       # 🆕 Classification ML
├── integration.py        # 🆕 Guide + exemples
├── worker.py             # Existant (à migrer)
└── scrape_subprocess.py  # Existant (à migrer)

filters/
└── unified.py            # 🆕 Filtre unifié

tests/
├── test_selectors.py     # 🆕
├── test_keyword_strategy.py # 🆕
├── test_progressive_mode.py # 🆕
├── test_unified_filter.py   # 🆕
├── test_metadata_extractor.py # 🆕
├── test_post_cache.py       # 🆕
├── test_smart_scheduler.py  # 🆕
├── test_ml_interface.py     # 🆕
└── test_adapters.py         # 🆕
```

## ⚠️ Points d'Attention

1. **Persistence**: Les modules stockent leur état dans `~/.titan_scraper/` ou `%LOCALAPPDATA%/TitanScraper/`

2. **Singletons**: Utiliser `reset_*()` entre les tests pour réinitialiser l'état

3. **Rollback**: Désactiver un module = retour au comportement legacy instantané

4. **Monitoring**: Vérifier `/api/system_health` après activation

## 🧪 Exécuter les Tests

```bash
# Tous les nouveaux tests
pytest tests/test_selectors.py tests/test_keyword_strategy.py tests/test_progressive_mode.py tests/test_unified_filter.py tests/test_metadata_extractor.py tests/test_post_cache.py tests/test_smart_scheduler.py tests/test_ml_interface.py tests/test_adapters.py -v

# Un module spécifique
pytest tests/test_smart_scheduler.py -v
```

## 📈 Prochaines Étapes

1. ✅ Tests unitaires créés (194 tests passent)
2. ✅ Endpoints API ajoutés (6 nouveaux endpoints feature_flags)
3. ✅ Module adapters.py créé avec FeatureFlags
4. ✅ Variables d'environnement pour activation (TITAN_ENABLE_PHASE1, etc.)
5. ✅ Script de validation `scripts/validate_modules.py`
6. ⏳ Migrer `worker.py` en utilisant `adapters.py`
7. ⏳ Migrer `scrape_subprocess.py` en utilisant `adapters.py`
8. ⏳ Ajouter métriques Prometheus pour les nouveaux modules
9. ⏳ Interface UI pour contrôler les feature flags

## 🔐 Recommandation de Déploiement

### En Développement/Test
```bash
# Tout activer pour tester
TITAN_ENABLE_ALL=1
```

### En Production (approche progressive)

**Semaine 1:** Phase 1 (cache + scheduler)
```bash
TITAN_ENABLE_PHASE1=1
```
→ Surveiller `/api/system_health` et `/api/cache_stats`

**Semaine 2:** Phase 2 (+ keywords + progressive)
```bash
TITAN_ENABLE_PHASE2=1
```
→ Surveiller `/api/keyword_stats` et `/api/progressive_mode`

**Semaine 3:** Tous les modules
```bash
TITAN_ENABLE_ALL=1
```
→ Activation complète après validation
