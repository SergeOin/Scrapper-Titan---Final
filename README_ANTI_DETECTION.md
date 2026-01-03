# 🛡️ Système Anti-Détection Titan

Ce document décrit le système anti-détection intégré au scraper Titan, conçu pour minimiser les risques de détection par LinkedIn tout en maintenant une efficacité de scraping optimale.

## 🎯 Philosophie

> **La non-détection et la stabilité du compte LinkedIn priment largement sur la vitesse ou le volume.**

Le système adopte une approche **progressive et configurable** : toutes les fonctionnalités avancées sont désactivées par défaut et peuvent être activées individuellement via des variables d'environnement.

---

## 📋 Variables d'environnement

| Variable | Défaut | Description |
|----------|--------|-------------|
| `TITAN_ULTRA_SAFE_MODE` | `1` ✅ | Mode ultra-prudent avec multiplicateur x3 sur les délais |
| `TITAN_ENHANCED_TIMING` | `0` | Utilise le module `timing.py` pour des délais intelligents |
| `TITAN_ENHANCED_STEALTH` | `0` | Active l'anti-fingerprinting via `stealth.py` |
| `TITAN_FORCED_BREAKS` | `0` | Pauses automatiques toutes les 15-30 actions |
| `TITAN_STRICT_HOURS` | `0` | Limite le scraping aux heures ouvrables (9h-22h) |

---

## 🔧 Configuration

### Windows (PowerShell)

```powershell
# Activer une fonctionnalité
$env:TITAN_ENHANCED_TIMING = "1"

# Désactiver une fonctionnalité
$env:TITAN_ENHANCED_TIMING = "0"

# Configuration complète recommandée
$env:TITAN_ULTRA_SAFE_MODE = "1"
$env:TITAN_ENHANCED_TIMING = "1"
$env:TITAN_ENHANCED_STEALTH = "1"
$env:TITAN_FORCED_BREAKS = "1"
```

### Linux/macOS (Bash)

```bash
# Activer une fonctionnalité
export TITAN_ENHANCED_TIMING=1

# Configuration complète recommandée
export TITAN_ULTRA_SAFE_MODE=1
export TITAN_ENHANCED_TIMING=1
export TITAN_ENHANCED_STEALTH=1
export TITAN_FORCED_BREAKS=1
```

### Fichier .env

```env
TITAN_ULTRA_SAFE_MODE=1
TITAN_ENHANCED_TIMING=1
TITAN_ENHANCED_STEALTH=1
TITAN_FORCED_BREAKS=1
TITAN_STRICT_HOURS=0
```

---

## 📦 Modules

### 1. `timing.py` - Gestion intelligente des délais

**Activation :** `TITAN_ENHANCED_TIMING=1`

Fournit des délais réalistes avec distribution gaussienne et multiplicateur configurable.

```python
from scraper.timing import random_delay, human_delay, is_ultra_safe_mode

# Délai aléatoire entre 1-2 secondes (x3 en mode ultra-safe = 3-6s)
delay_ms = random_delay(1000, 2000)

# Délai "humain" avec variance naturelle
delay_ms = human_delay(1500)

# Vérifier le mode actuel
if is_ultra_safe_mode():
    print("Mode ultra-prudent actif (x3)")
```

**Comportement selon le mode :**

| Mode | Multiplicateur | Délai pour `random_delay(1000, 2000)` |
|------|----------------|---------------------------------------|
| Normal | x1 | 1000-2000ms |
| Ultra-Safe | x3 | 3000-6000ms |

---

### 2. `stealth.py` - Anti-fingerprinting

**Activation :** `TITAN_ENHANCED_STEALTH=1`

Protège contre la détection par empreinte du navigateur.

```python
from scraper.stealth import (
    apply_stealth_scripts,
    apply_advanced_stealth,
    get_stealth_context_options,
    detect_restriction_page
)

# Options de contexte furtif pour Playwright
context_options = get_stealth_context_options()
context = await browser.new_context(**context_options)

# Appliquer les scripts anti-détection
await apply_stealth_scripts(page)

# Protection avancée (WebGL, Canvas, Audio)
await apply_advanced_stealth(page)

# Détecter une page de restriction LinkedIn
if await detect_restriction_page(page):
    print("⚠️ Restriction détectée !")
```

**Protections incluses :**
- ✅ Masquage `navigator.webdriver`
- ✅ Spoofing des plugins et langues
- ✅ Protection Canvas fingerprinting
- ✅ Protection WebGL fingerprinting
- ✅ Protection Audio fingerprinting
- ✅ Détection des pages de restriction LinkedIn

---

### 3. `human_patterns.py` - Comportement humain

**Activation :** `TITAN_FORCED_BREAKS=1` et/ou `TITAN_STRICT_HOURS=1`

Simule des patterns de navigation humains.

```python
from scraper.human_patterns import (
    is_good_time_to_scrape,
    should_take_break,
    generate_session_profile
)

# Vérifier si c'est un bon moment (heures ouvrables)
if not is_good_time_to_scrape():
    print("En dehors des heures recommandées")

# Vérifier si une pause est nécessaire
break_needed, break_duration = should_take_break(actions_count=25)
if break_needed:
    await asyncio.sleep(break_duration)

# Générer un profil de session réaliste
profile = generate_session_profile()
# {'max_actions': 45, 'session_duration': 1800, 'break_frequency': 20}
```

---

### 4. `human_actions.py` - Actions simulées

**Activation :** Utilisé automatiquement avec `TITAN_FORCED_BREAKS=1`

Simule des pauses et actions humaines réalistes.

```python
from scraper.human_actions import (
    should_take_session_break,
    simulate_session_break,
    reset_session_counters
)

# Vérifier si une pause session est nécessaire
if should_take_session_break():
    await simulate_session_break(page)

# Réinitialiser les compteurs en début de session
reset_session_counters()
```

---

## 🚀 Guide d'activation progressive

Pour une transition en douceur, activez les fonctionnalités **une par une** avec 24-48h d'observation entre chaque étape.

### Étape 1 : Mode Ultra-Safe (défaut)
```powershell
$env:TITAN_ULTRA_SAFE_MODE = "1"
```
> ✅ Déjà actif par défaut. Multiplie tous les délais par 3.

### Étape 2 : Timing amélioré
```powershell
$env:TITAN_ENHANCED_TIMING = "1"
```
> Délais avec distribution gaussienne plus naturelle.

### Étape 3 : Anti-fingerprinting
```powershell
$env:TITAN_ENHANCED_STEALTH = "1"
```
> Protection contre la détection par empreinte navigateur.

### Étape 4 : Pauses automatiques
```powershell
$env:TITAN_FORCED_BREAKS = "1"
```
> Pauses naturelles toutes les 15-30 actions.

### Étape 5 : Heures strictes (optionnel)
```powershell
$env:TITAN_STRICT_HOURS = "1"
```
> Limite le scraping à 9h-22h. Utile pour simuler un usage "bureau".

---

## 📊 Monitoring

### Logs à surveiller

Le système génère des logs indicatifs :

```
[TIMING] Mode ULTRA_SAFE actif (x3.0)
[STEALTH] Scripts anti-détection appliqués
[BREAK] Pause de 45s après 23 actions
[HOURS] Hors heures ouvrables, attente...
```

### Indicateurs de problème

| Symptôme | Cause probable | Action |
|----------|----------------|--------|
| Captchas fréquents | Délais trop courts | Augmenter `TITAN_ULTRA_SAFE_MODE` |
| Page "restriction" | Fingerprinting détecté | Activer `TITAN_ENHANCED_STEALTH` |
| Compte limité | Volume trop élevé | Activer `TITAN_FORCED_BREAKS` |
| Suspension temporaire | Activité suspecte | Activer tous les flags + réduire volume |

---

## ⚠️ Bonnes pratiques

1. **Ne jamais désactiver `TITAN_ULTRA_SAFE_MODE`** sauf pour des tests rapides
2. **Limiter le volume quotidien** : 50-100 posts/jour maximum recommandé
3. **Varier les heures** : Ne pas scraper toujours aux mêmes horaires
4. **Surveiller les captchas** : Plus de 2 captchas/jour = réduire l'activité
5. **Respecter les pauses** : Si le système demande une pause, ne pas la bypasser

---

## 🔍 Dépannage

### Le multiplicateur ne s'applique pas

```powershell
# Vérifier que TITAN_ULTRA_SAFE_MODE est bien à "1"
python -c "from scraper.timing import is_ultra_safe_mode, get_delay_multiplier; print(f'Ultra-Safe: {is_ultra_safe_mode()}, Multiplier: {get_delay_multiplier()}x')"
```

### Les modules ne se chargent pas

```powershell
# Tester les imports
python -c "from scraper import timing, stealth, human_patterns, human_actions; print('OK')"
```

### Vérifier l'état des flags

```powershell
python -c "
import os
flags = ['TITAN_ULTRA_SAFE_MODE', 'TITAN_ENHANCED_TIMING', 'TITAN_ENHANCED_STEALTH', 'TITAN_FORCED_BREAKS', 'TITAN_STRICT_HOURS']
for f in flags:
    v = os.environ.get(f, '0')
    status = '✅' if v == '1' else '❌'
    print(f'{status} {f} = {v}')
"
```

---

## 📁 Structure des fichiers

```
scraper/
├── timing.py          # Gestion des délais
├── stealth.py         # Anti-fingerprinting
├── human_patterns.py  # Patterns comportementaux
├── human_actions.py   # Actions simulées
├── scrape_subprocess.py  # Intégration (wrappers)
└── worker.py          # Orchestration (feature blocks)
```

---

## 📝 Changelog

### v1.0.0 (Janvier 2026)
- ✅ Création des 4 modules anti-détection
- ✅ Intégration conditionnelle via flags
- ✅ Mode ULTRA_SAFE avec multiplicateur x3
- ✅ Wrappers pour activation progressive
- ✅ Documentation complète
