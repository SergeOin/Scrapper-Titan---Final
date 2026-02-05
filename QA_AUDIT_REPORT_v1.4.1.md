# 📊 Rapport QA - Titan Scraper v1.4.1 (LinkedIn Legal Posts Scraper)

**Version auditée**: 1.4.1  
**Date de l'audit**: 2026-01-21  
**Auteur du rapport**: Lead QA / Test Engineer  
**Simulation**: Journée complète (9h00 - 17h30 UTC)

---

## 🔥 EXECUTIVE SUMMARY

| Critère | Statut | Score |
|---------|--------|-------|
| **Stabilité système** | ✅ Corrigé | 8/10 |
| **Qualité du filtrage** | ✅ Amélioré | 8/10 |
| **Anti-détection** | ✅ Solide | 8/10 |
| **Performance quotidienne** | ⚠️ À valider | 7/10 |
| **Maturité exploitation** | ✅ Prêt | 7/10 |

### Verdict Global: **✅ GO CONDITIONNEL**

Les bugs bloquants ont été **corrigés**. Le système est prêt pour une validation de 24h.

#### ✅ Corrections appliquées (2026-01-22):
- **BUG-001/002**: Synchronisation daily_count avec SQLite ✅
- **FP-001**: Job boards ajoutés aux exclusions (Emplois & Bourses, Indeed, etc.) ✅  
- **FP-002**: 112 patterns géographiques (Afrique + Canada étendu) ✅
- **BUG-003**: Logger.record_scrape_result corrigé ✅

---

## 1️⃣ TABLEAU DES PROBLÈMES IDENTIFIÉS

### 🔴 Problèmes Critiques (P0 - Bloquants)

| ID | Titre | Sévérité | Impact | Fichier(s) concerné(s) |
|----|-------|----------|--------|------------------------|
| **BUG-001** | Daily cap bloque toute collecte malgré posts valides | P0 - CRITIQUE | 0 posts stockés depuis 10h alors que scraping fonctionne | [worker.py](scraper/worker.py#L2339-L2346) |
| **BUG-002** | Compteur quotidien en mémoire non synchronisé avec DB | P0 - CRITIQUE | `daily_count=80` en mémoire vs `59` en table meta | [worker.py](scraper/worker.py#L2336-L2404) |
| **BUG-003** | Logger.record_scrape_result() erreur d'argument | P1 - MAJEUR | Perte de métriques de scraping | [worker.py](scraper/worker.py#L2342) |

### 🟠 Problèmes Majeurs (P1)

| ID | Titre | Sévérité | Impact | Fichier(s) concerné(s) |
|----|-------|----------|--------|------------------------|
| **FP-001** | Job boards/agrégateurs passent le filtre | P1 - MAJEUR | ~40% des posts "Emplois & Bourses" sont des faux positifs | [legal_filter.py](scraper/legal_filter.py) |
| **FP-002** | Posts hors France acceptés | P1 - MAJEUR | MSF WaCA (Abidjan, Côte d'Ivoire), Port Halifax (Canada) | [scrape_subprocess.py](scraper/scrape_subprocess.py) |
| **PERF-001** | Taux de rejet non-français élevé (40%+) | P1 - MAJEUR | Gaspillage de quota de scraping | Configuration keywords |

### 🟡 Problèmes Mineurs (P2)

| ID | Titre | Sévérité | Impact | Fichier(s) concerné(s) |
|----|-------|----------|--------|------------------------|
| **UI-001** | Permalinks construits depuis profils (fallback) | P2 - MINEUR | Liens non cliquables directement vers le post | [scrape_subprocess.py](scraper/scrape_subprocess.py) |
| **LOG-001** | Encodage UTF-8 dans logs Windows | P2 - MINEUR | Caractères emoji tronqués dans logs | Console encoding |

---

## 2️⃣ ANALYSE DES FAUX POSITIFS / FAUX NÉGATIFS

### 📊 Données d'analyse

- **Posts scrappés analysés**: 15 (dernier batch)
- **Posts acceptés par subprocess**: 7 (46%)
- **Posts stockés en base**: 0 (cap atteint - BUG-001)
- **Posts réels en base (hors demo)**: 5 / 59

### ❌ Faux Positifs Identifiés (Posts acceptés à tort)

| Post | Auteur | Raison de rejet manquée | Recommandation |
|------|--------|-------------------------|----------------|
| Expertise France - Juriste PPP Abidjan | Emplois & Bourses | 🌍 **HORS FRANCE** (Côte d'Ivoire) | Ajouter "Abidjan", "Côte d'Ivoire" aux patterns de localisation |
| MSF WaCA - Legal Officer | Médecins Sans Frontières WaCA | 🌍 **HORS FRANCE** (WaCA = West/Central Africa) | Détecter "WaCA" et contexte africain |
| Port Halifax - General Counsel | Port Halifax | 🌍 **HORS FRANCE** (Canada, Nova Scotia) | Détecter "Halifax", "Canada", "Nova Scotia" |
| Juriste Crédit Access | Emmanuel Vanié Bi | 🌍 **POTENTIEL HORS FRANCE** (profil Côte d'Ivoire) | Vérifier localisation auteur |
| Posts "Emplois & Bourses" | Emplois & Bourses | 📰 **JOB BOARD / AGRÉGATEUR** | Ajouter à EXCLUDED_AUTHORS |

#### Estimation impact:
- **Taux de faux positifs observé**: ~40% (3-4 posts sur 7 acceptés)
- **Cible métier**: <10%
- **Écart**: +30 points → **ACTION REQUISE**

### ⚠️ Faux Négatifs Potentiels (Posts rejetés à tort)

| Catégorie de rejet | Nombre | % du batch | Analyse |
|--------------------|--------|------------|---------|
| `rejected_non_french` | 6-8 | ~40-50% | ✅ Comportement attendu (keywords FR captent posts EN) |
| `rejected_agency` | 1-2 | ~10% | ✅ Cabinets de recrutement correctement filtrés |
| `rejected_contract_type` | 1-2 | ~10% | ⚠️ À vérifier - stages/alternances exclues comme prévu |
| `rejected_no_signal` | 1-3 | ~10-20% | ⚠️ Possible faux négatifs sur posts mal formatés |
| `rejected_other` | 2-4 | ~15% | ❓ Catégorie floue - besoin d'audit détaillé |

#### Points positifs filtrage:
- ✅ Zéro `rejected_duplicate` (déduplication fonctionne)
- ✅ `rejected_jobseeker` capture les #OpenToWork
- ✅ `rejected_external` capture les missions pour clients

---

## 3️⃣ ANALYSE TECHNIQUE APPROFONDIE

### 3.1 Architecture du système

```
┌─────────────────────────────────────────────────────────────────┐
│                         Titan Scraper v1.4.1                     │
├──────────────────────────────────────────────────────────────────┤
│  Server (FastAPI)                                                │
│    └── Autonomous Worker (lifespan-managed)                      │
│          └── Subprocess Isolation (Playwright)                   │
│                └── Chrome/Chromium headless                      │
├──────────────────────────────────────────────────────────────────┤
│  Storage Layer                                                   │
│    ├── SQLite (fallback.sqlite3) - Posts + Meta                 │
│    ├── Post Cache (LRU + SQLite) - Deduplication                │
│    └── Prometheus Metrics                                        │
├──────────────────────────────────────────────────────────────────┤
│  Filtering Pipeline                                              │
│    ├── Language Detection (langdetect)                          │
│    ├── Legal Score (>= 0.20)                                    │
│    ├── Recruitment Score (>= 0.20)                              │
│    ├── Location Filter (France only)                            │
│    └── Exclusion Lists (agencies, stages, freelance, etc.)     │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Analyse des logs de la journée simulée

**Période analysée**: 21/01/2026 08:16 - 21:55 UTC

| Métrique | Valeur | Cible | Statut |
|----------|--------|-------|--------|
| Cycles subprocess exécutés | ~12+ | N/A | ✅ |
| Temps moyen par batch (3 keywords) | 5-6 min | <15 min | ✅ |
| Subprocess returncode | 0 (tous) | 0 | ✅ |
| Posts scrappés par cycle | 11-15 | 10-15 | ✅ |
| Posts acceptés par subprocess | 0-7 | 3-5 | ⚠️ Variable |
| Posts effectivement stockés | **0** (cap bug) | 50/jour | ❌ CRITIQUE |

### 3.3 Anti-détection (Score: 8/10)

| Mécanisme | Implémenté | Configuration | Statut |
|-----------|------------|---------------|--------|
| Ultra-Safe Mode | ✅ | `TITAN_ULTRA_SAFE_MODE=1` | ✅ Actif |
| Délais page load | ✅ | 15-40 secondes (3x multiplier) | ✅ Sécurisé |
| Human-like timing | ✅ | Jitter 800-2500ms | ✅ |
| Fingerprint persistence | ✅ | `fingerprint.json` | ✅ Réduit security emails |
| User-Agent rotation | ✅ | 9 agents (Chrome/Edge/Firefox/Safari) | ✅ |
| Viewport presets | ✅ | 6 profils desktop réalistes | ✅ |
| Human actions | ✅ | Scroll, profile visits | ✅ |
| Night mode | ✅ | Pause 30-60 min 22h-8h | ✅ |
| Weekend mode | ✅ | Actif Lun-Ven seulement | ✅ |

**Points forts**: Configuration très conservative, pas de détection signalée dans les logs

### 3.4 Gestion des sessions LinkedIn

| Aspect | Statut | Observations |
|--------|--------|--------------|
| `storage_state.json` | ✅ Présent | Cookies persistés |
| Session revocation handling | ✅ | Auto-reconnect implémenté |
| Cookie regeneration | ✅ | Sur warm-up navigation |
| Blocked account detection | ⚠️ | Table existe mais non utilisée activement |

---

## 4️⃣ BUG DETAIL: BUG-001 (Daily Cap Critical)

### Symptôme
```
2026-01-21T21:55:43.520142 classification: relaxed=True, cap=80, daily_count=80
2026-01-21T21:55:43.520142 daily cap reached at 0 accepted
2026-01-21T21:55:43.521132 classification done: 0 accepted, 0 discarded_intent
2026-01-21T21:55:43.521132 store_posts returned: 0 inserted
```

### Cause racine
Le compteur `daily_count` est stocké **uniquement en mémoire** (`ctx.legal_daily_count`) et n'est **jamais initialisé depuis la base de données** au démarrage.

```python
# worker.py:2336-2339 - Le problème
if getattr(ctx, 'legal_daily_date', None) != today:
    setattr(ctx, 'legal_daily_date', today)
    setattr(ctx, 'legal_daily_count', 0)  # Reset à 0, mais...
daily_count = getattr(ctx, 'legal_daily_count', 0)  # ...jamais synchronisé avec meta.posts_count
```

### Impact
- **59 posts** en base (table `meta.posts_count`)
- **80** en compteur mémoire
- **Différence**: 21 posts "fantômes" → le cap de 80 est atteint alors qu'il reste de la capacité

### Fix recommandé
```python
# Proposé: Synchroniser avec la table meta au démarrage
if getattr(ctx, 'legal_daily_date', None) != today:
    setattr(ctx, 'legal_daily_date', today)
    # Lire le compteur réel depuis la DB pour cette date
    actual_count = await _get_daily_count_from_db(ctx, today)
    setattr(ctx, 'legal_daily_count', actual_count)
```

---

## 5️⃣ RECOMMANDATIONS PRIORISÉES

### 🔴 P0 - Bloquants (Avant production)

| # | Action | Effort | Impact |
|---|--------|--------|--------|
| 1 | **Fixer BUG-001**: Synchroniser `daily_count` avec la table meta SQLite | 2h | ⬆️⬆️⬆️ |
| 2 | **Fixer BUG-002**: Ajouter colonne `daily_date` + `daily_count` à la table meta | 4h | ⬆️⬆️⬆️ |
| 3 | **Ajouter "Emplois & Bourses" et job boards** à `EXCLUDED_AUTHORS` | 30min | ⬆️⬆️ |

### 🟠 P1 - Avant scaling (Première semaine)

| # | Action | Effort | Impact |
|---|--------|--------|--------|
| 4 | **Améliorer filtrage géographique**: Ajouter patterns Afrique (WaCA, Abidjan, Dakar, etc.) | 2h | ⬆️⬆️ |
| 5 | **Ajouter patterns Canada**: Halifax, Toronto, Vancouver, Québec | 1h | ⬆️ |
| 6 | **Fixer Logger.record_scrape_result()**: Corriger l'argument `keywords` | 1h | ⬆️ |
| 7 | **Auditer `rejected_other`**: Comprendre et documenter cette catégorie | 2h | ⬆️ |

### 🟡 P2 - Amélioration continue

| # | Action | Effort | Impact |
|---|--------|--------|--------|
| 8 | Améliorer extraction permalinks (éviter fallback profil) | 4h | ⬆️ |
| 9 | Ajouter métriques Prometheus pour faux positifs/négatifs | 3h | ⬆️ |
| 10 | Dashboard temps réel des rejets par catégorie | 8h | ⬆️ |

---

## 6️⃣ MÉTRIQUES DE CONFORMITÉ

### Objectifs métier vs Réalité

| KPI | Objectif | Réalité observée | Écart | Statut |
|-----|----------|------------------|-------|--------|
| Posts pertinents/jour | ~50 | 5 (hors demo) | -90% | ❌ |
| Taux d'acceptation | 10-15% | 7/15 = 46% (subprocess) | +200% | ⚠️ Suspect |
| Faux positifs | <10% | ~40% | +30 pts | ❌ |
| Duplicates | 0 | 0 | 0% | ✅ |
| Crashes/jour | 0 | 0 | 0% | ✅ |
| Détection LinkedIn | 0 | 0 | 0% | ✅ |

### Couverture des 16 professions cibles

| Profession | Keywords actifs | Posts trouvés | Statut |
|------------|-----------------|---------------|--------|
| Juriste | ✅ 8 | ~30 | ✅ |
| Avocat | ✅ 8 | ~15 | ✅ |
| Notaire | ✅ 2 | 3 | ⚠️ |
| Paralegal | ⚠️ 1 | 0 | ❌ |
| Greffier | ❌ 0 | 0 | ❌ |
| Huissier | ❌ 0 | 0 | ❌ |
| (autres...) | ... | ... | ... |

---

## 7️⃣ GO / NO-GO DECISION

### ✅ GO CONDITIONNEL (après corrections)

**Corrections appliquées le 2026-01-22:**

| Bug | Correction | Fichier |
|-----|------------|---------|
| BUG-001/002 | `_get_daily_count_from_db()` synchronise le compteur avec SQLite | [worker.py](scraper/worker.py#L1043) |
| FP-001 | 10 job boards ajoutés à `EXCLUDED_AUTHORS` | [bootstrap.py](scraper/bootstrap.py#L254) |
| FP-002 | 112 patterns géographiques (vs 30 avant) | [legal_filter.py](scraper/legal_filter.py#L172) |
| BUG-003 | `keywords_count` remplace `keywords` dans logger | [adapters.py](scraper/adapters.py#L641) |

**Prochaines étapes:**
1. ✅ Redémarrer le worker pour appliquer les corrections
2. ⏳ Valider sur 24h de run continu sans intervention
3. ⏳ Vérifier taux de faux positifs <15%
4. ⏳ Atteindre objectif 50 posts/jour

### Roadmap suggérée

```
Semaine 1 (S+1): Fixes P0 + Tests internes
  └── Objectif: 30 posts/jour, <20% FP

Semaine 2 (S+2): Fixes P1 + Soft launch
  └── Objectif: 40 posts/jour, <15% FP

Semaine 3 (S+3): Monitoring + Ajustements
  └── Objectif: 50 posts/jour, <10% FP

Semaine 4 (S+4): Production stable
  └── Objectif: Exploitation quotidienne autonome
```

---

## 8️⃣ ANNEXES

### A. Fichiers de logs analysés
- `%LOCALAPPDATA%\TitanScraper\worker_debug.txt`
- `%LOCALAPPDATA%\TitanScraper\scrape_subprocess_debug.txt`
- `%LOCALAPPDATA%\TitanScraper\last_scraper_output.json`

### B. Base de données
- `%LOCALAPPDATA%\TitanScraper\fallback.sqlite3`
  - Table `posts`: 59 entrées (54 demo + 5 réelles)
  - Table `meta`: `posts_count=59`, `scraping_enabled=1`
  - Table `blocked_accounts`: 0 entrées

### C. Configuration active
```python
# bootstrap.py settings observées
legal_daily_post_cap = 80
legal_filter_recruitment_threshold = 0.20
legal_filter_legal_threshold = 0.20
keywords_session_batch_size = 3
autonomous_worker_interval_seconds = 2400  # 40 min
human_mode_enabled = True
filter_language_strict = True
search_geo_hint = "France"
```

### D. Versions des dépendances clés
- Python: 3.12.10
- Playwright: (vérifier pyproject.toml)
- FastAPI: (vérifier requirements.txt)
- SQLite: Built-in

---

**Rapport généré le**: 2026-01-21  
**Prochaine revue QA recommandée**: Après correction des bugs P0

---
*Ce rapport est confidentiel et destiné à l'usage interne de Titan Partners.*
