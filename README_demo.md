# Demo Guide – LinkedIn Scraper

Ce document fournit un parcours ultra-rapide pour démontrer la plateforme de scraping (mode mock ou réel) : lancement, vérification, filtres, métriques, sécurité.

---
## 1. Prérequis
- Python 3.12 (virtuel: `.venv`)
- Dépendances installées :
  ```powershell
  pip install -r requirements.txt
  ```
- (Si mode réel) Navigateur Playwright Chromium :
  ```powershell
  .\.venv\Scripts\python.exe -m playwright install chromium
  ```
- Fichier `.env` déjà configuré (voir `.env` ou `.env.example`).

---
## 2. Lancement démo (mode mock recommandé)
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\demo_run.ps1 -Mock 1 -Open
```
Résultat attendu :
- Insertion de posts synthétiques (ex: 15 posts)
- Ouverture du navigateur sur http://localhost:8000/

### Passer en mode réel (optionnel)
1. Dans `.env` : `PLAYWRIGHT_MOCK_MODE=0`
2. Installer Chromium si pas fait (cf ci-dessus)
3. Relancer :
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\demo_run.ps1 -Open
   ```
> Note : nécessite un contexte de session/auth LinkedIn si extraction réelle implémentée.

---
## 3. Dashboard & API
- Dashboard : http://localhost:8000/
- Filtrer par score recrutement : `http://localhost:8000/?min_score=0.07`
- API JSON :
  ```powershell
  (Invoke-WebRequest -Uri "http://localhost:8000/api/posts").Content
  (Invoke-WebRequest -Uri "http://localhost:8000/api/posts?min_score=0.07").Content
  ```
- Métriques Prometheus : http://localhost:8000/metrics

### Champs principaux
| Champ | Description |
|-------|-------------|
| keyword | Mot-clé source de la requête |
| text | Contenu du post (tronqué) |
| recruitment_score | Score heuristique de recrutement |
| permalink | Lien (synthétique en mock) |
| score | Score interne (longueur, densité, etc.) |

---
## 4. Déroulé de présentation (suggestion 5 minutes)
1. Montrer rapidement `.env` (sans mot de passe en clair en public)
2. Lancer script mock
3. Afficher tableau (montrer les colonnes + liens)
4. Appliquer filtre `min_score`
5. Montrer `/api/posts` puis `/metrics`
6. Expliquer le stockage SQLite (principal) avec fallback CSV + instrumentation

---
## 5. Commandes utiles
Repopulation rapide (avec nouveaux mots-clés) :
```powershell
$env:SCRAPE_KEYWORDS = "python;data;ai;cloud"
powershell -ExecutionPolicy Bypass -File .\scripts\demo_run.ps1 -Mock 1
```
Changer le port :
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\demo_run.ps1 -Port 9001 -Mock 1 -Open
```

---
## 6. Troubleshooting
| Problème | Cause probable | Solution |
|----------|----------------|----------|
| `ModuleNotFoundError` | Venv non utilisé | Lancer via script (détecte .venv) |
| Redis error logs | Redis absent | Ignorer ou installer Redis |
| Dashboard vide | Aucun run effectué | Relancer `demo_run.ps1` |
| Lien vide | Pas de permalink trouvé (réel) | Mock pour la démo |
| 429 API | Rate limit interne | Ralentir / ajuster env vars API_RATE_LIMIT_* |
| Port déjà utilisé | Conflit processus | Changer `-Port` |

---
## 7. Sécurité & Bonnes Pratiques
### Mode réel (authentifié) – IMPORTANT
L’utilisation réelle de LinkedIn implique :
- Respect strict des CGU LinkedIn (ne pas utiliser massivement / commercialement sans accord).
- Utilisation interne et limitée (démo / R&D). 
- Stockage sécurisé des identifiants (ne jamais commiter). 

### Préparation session authentifiée
1. Générer un fichier d’état Playwright :
  ```powershell
  python scripts/generate_storage_state.py --url https://www.linkedin.com/login
  ```
  (Se connecter manuellement, puis presser ENTER dans le terminal)
2. Vérifier qu’un `storage_state.json` est créé à la racine.
3. Mettre dans `.env` :
  ```
  PLAYWRIGHT_MOCK_MODE=0
  STORAGE_STATE=storage_state.json
  ```
4. Lancer un run ciblé (par ex. un seul mot-clé) :
  ```powershell
  $env:SCRAPE_KEYWORDS = "python"
  powershell -ExecutionPolicy Bypass -File .\scripts\demo_run.ps1 -Open
  ```

### Sélecteurs & robustesse
Les sélecteurs peuvent changer fréquemment côté LinkedIn. Le code utilise :
```
POST_SELECTOR=article[data-urn*='urn:li:activity']
AUTHOR_SELECTOR=span.update-components-actor__meta a, a.update-components-actor__sub-description, a.app-aware-link
TEXT_SELECTOR=div.update-components-text, div.feed-shared-update-v2__description-wrapper, span.break-words, div[dir='ltr']
```
Adaptable dans `scraper/worker.py` si markup modifié.

### Génération de permaliens
- Priorité : liens directs /posts/ ou /feed/update
- Fallback : reconstruction `https://www.linkedin.com/feed/update/urn:li:activity:<ID>/` à partir de `data-urn`.

### Bonnes pratiques supplémentaires
- Limiter `MAX_SCROLL_STEPS` et `MAX_POSTS_PER_KEYWORD`.
- Ajouter des délais aléatoires supplémentaires si usage prolongé.
- Journaliser uniquement ce qui est nécessaire (éviter d’exposer des données personnelles inutiles dans les logs).

- Ne pas committer le vrai mot de passe : utiliser `.env` privé & `.env.example` public.
- Ne pas committer de fichiers sensibles : utiliser `.env` privé & `.env.example` public.`X-Trigger-Token`.
- Auth dashboard : `INTERNAL_AUTH_USER` + `INTERNAL_AUTH_PASS_HASH` (bcrypt via `passlib`).
- Journalisation : logs JSON (fichier si `LOG_FILE` défini).

---
## 8. Nettoyage
```powershell
# Arrêter le serveur: Ctrl + C
Remove-Item Env:SCRAPE_KEYWORDS -ErrorAction SilentlyContinue
# (Optionnel) Désactiver mock pour test réel : éditer .env
```

---
## 9. Prochaines améliorations possibles
- Test automatisé pour `/api/posts` + présence `permalink`
- Export CSV on-demand endpoint
- 
---
## 9.1 Génération mock orientée métiers juridiques
En mode mock (`PLAYWRIGHT_MOCK_MODE=1`), les posts synthétiques sont désormais générés autour de métiers du domaine légal / notarial / fiscal en FRANÇAIS uniquement.

### Rôles couverts
```
avocat collaborateur, avocat associé, avocat counsel, paralegal, legal counsel, juriste,
responsable juridique, directeur juridique, notaire stagiaire, notaire associé, notaire salarié,
notaire assistant, clerc de notaire, rédacteur d’actes, responsable fiscal, directeur fiscal,
comptable taxateur, formaliste
```

### Champs enrichis
- Variation de contrat: `CDI`, `CDD`, `Stage`, `Alternance`, `Freelance`
- Contexte urgence / motif: `prise de poste immédiate`, `démarrage sous 30 jours`, `urgence recrutement`, `création de poste`, `remplacement départ retraite`, `renforcement d’équipe`
- Modèles de phrases dynamiques injectant `{role}`, `{contrat}`, `{urgence}`
- Hashtag occasionnel `#<keyword>` pour refléter le mot-clé déclencheur

### Objectif
Donner une démonstration réaliste de tri par `recruitment_score` avec un corpus homogène juridique sans dépendre de données réelles.

### Personnalisation
Modifier la section mock dans `scraper/worker.py` (bloc `if ctx.settings.playwright_mock_mode:`) :
- Ajouter / retirer des rôles (liste `roles`)
- Ajouter de nouveaux types de contrat (liste `contrats`)
- Ajuster l’intensité de la variation d’urgence (liste `urgences`)
- Ajouter des templates (liste `templates`)

### Effet sur le scoring
Les rôles sont injectés dans la liste de mots-clés lors du calcul de score interne pour accroître la densité lexicale pertinente. Le `recruitment_score` monte grâce à la présence de termes typiques : `recherch`, `poste`, `recrut`, etc.

### Limites
- Les permaliens restent synthétiques (non cliquables vers de vrais contenus LinkedIn).
- Les dates sont uniformes (timestamp génération) – on peut étendre avec un décalage aléatoire.
- Pas encore de distinction géographique ou de niveau d’expérience (peut être ajouté ultérieurement).

---

---
## 10. Références internes
- `scripts/demo_run.ps1` : orchestration démo
- `scripts/run_once.py` : job unique sans queue
- `scraper/bootstrap.py` : config & clients (Redis optionnel)
- `scraper/worker.py` : extraction / mock / persistence
- `server/routes.py` : endpoints API + SQLite
- `server/templates/dashboard.html` : UI tableau

Bonnes démos !
