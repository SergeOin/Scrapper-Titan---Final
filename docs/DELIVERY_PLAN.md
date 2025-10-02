# Plan de Livraison Global (Application Clé en Main)

Date de création : 2025-10-02
Révision : initiale

## 1. Vision

Fournir une application prête à l’emploi permettant :

- Collecte automatisée ou à la demande de posts LinkedIn ciblés (mock ou réel selon environnement).
- Visualisation structurée, filtrable et réactive via un dashboard.
- Distribution simple pour utilisateurs internes Windows via installateur **MSI** signé.
- Déploiement serveur (Docker / Cloud) pour exécution continue.
- Observabilité, sécurité, maintenabilité et extensibilité garanties.

## 2. Périmètre Fonctionnel (MVP Clé en Main)

| Domaine | Fonctionnalité | Statut actuel | Gap clé |
|---------|----------------|---------------|---------|
| Scraping | Extraction mots-clés Playwright / mock | Implémenté | Stabilisation worker modulaire (S2) |
| Filtrage | Langue, auteur/permalink, recrutement, démonstration | Implémenté | Externalisation modules (S2–S3) |
| Stockage | Mongo primaire, SQLite fallback, CSV dernier recours | Implémenté | Abstraction pipeline (S3) |
| Dashboard | Tableau posts, stats runtime, SSE | Implémenté | UI ergonomie + filtres avancés (option) |
| Export | CSV snapshot | Partiel | Parquet (optionnel S8) |
| Admin | Purge démo, toggles filtres, shutdown | Implémenté | Auth header durcie (S6) |
| API | /posts, /stats, /health, /version, debug | Implémenté | Segmentation admin vs public (S3) |
| Observabilité | Logs JSON, métriques Prometheus | Implémenté | Traces OpenTelemetry (S5) |
| Sécurité | Basic auth optionnelle + tokens | Partiel | Hardening headers + rate limit distribué (S6) |
| Packaging | PyInstaller + EXE | Partiel | MSI complet (S7) |
| Distribution | Docker image | Présent | Publication CI tag (S7) |

## 3. Périmètre Non-Fonctionnel

| Attribut | Cible | Mesure |
|----------|-------|--------|
| Performance job mock | < 15 s (après refactor) | Timer smoke CI |
| Latence API P95 GET /api/posts (100 items) | < 250 ms (local prod-like) | Bench script |
| Fiabilité stockage (perte silencieuse) | 0 | Tests chaos pipeline |
| Couverture code modules critiques | ≥ 80% | Rapport couverture |
| Reproductibilité build desktop | 100% | Hash binaire stable (hors timestamp) |
| Taille binaire MSI | < 250 MB | Artifact CI |
| Temps installation MSI | < 60 s | Test manuel |

## 4. Jalons & Phases

| Phase | Objectif | Dépend de | Sorties |
|-------|----------|-----------|---------|
| S1 (terminé) | Cartographie + hardening minimal | - | Docs, smoke, annotation code mort |
| S2 | Refactor runtime worker | S1 | Modules runtime + complexité réduite |
| S3 | Abstraction stockage + queue robuste | S2 | StoragePipeline + job tracking |
| S4 | Tests étendus + migrations | S3 | Migrations + couverture |
| S5 | Observabilité avancée + perf | S4 | Traces + bench + tuning |
| S6 | Sécurité renforcée | S5 | Headers + rate limit distribué + audit |
| S7 | Packaging & CI/CD complet | S6 | MSI, image publiée, versioning standard |
| S8 (option) | Valeur métier avancée | S7 | Parquet, webhooks, ML léger |
| Beta Freeze | Stabilisation (no new features) | ≥S7 | Release Candidate |
| GA | Version 1.0 interne | RC | MSI signé + image docker officielle |

## 5. MSI Packaging Stratégie

### Objectifs

- Installer application desktop (mode local) : exécuter dashboard + worker embarqués.
- Gestion configuration via fichier `.env` local + UI minimal de lancement.
- Inclure WebView2 (si dashboard desktop wrapper) ou lancer navigateur système.

### Outils

- PyInstaller (déjà présent).
- MSIX ou WiX Toolset / `wixl` / `msi` PyInstaller plugin (selon scripts existants `build_desktop_msi.ps1`).
- Signature de code (certificat interne) — option : post-sign via script.

### Étapes CI S7

1. Build environnement propre (Windows runner) Python + Playwright (headless assets).
2. `pyinstaller TitanScraperDesktop.spec` (ou spec consolidée).
3. Générer structure MSI :
   - GUID produit/version depuis `VERSION`.
   - Ajout raccourcis menu démarrer.
   - Icône (`build/icon.ico`).
4. (Option) Post build : signature `signtool.exe`.
5. Artifact upload + checksum (SHA256).

### Tests MSI

- Installation fraîche (user non admin si possible).
- Lancement → dashboard accessible.
- Smoke run mock → posts visibles.
- Uninstall → suppression complète (logs optionnels conservés ? décision).

## 6. Architecture Cible Synthétique (Post S3)

```text
server/ (API + dashboard) → runtime/ (job orchestration) → storage/ (abstractions) → backends (mongo/sqlite/csv)
                                                ↑
                                              filters/, dedup/, pacing/ modules purs
```

## 7. Stratégie Tests

| Niveau | But | Outils | Exemples |
|--------|-----|--------|----------|
| Unit | Validation fonctions pures | pytest | dedup, scoring |
| Intégration | Orchestration job → storage | pytest + fixtures | mock job pipeline |
| API | Contrats & pagination | httpx AsyncClient | /api/posts, /api/stats |
| E2E Mock | Pipeline complet (mock) | script smoke | CI job avant tests lourds |
| E2E Réel (manuel) | Sanity Playwright réel | Checklist | 1 run/semaine ou avant release |
| Performance | Temps job / latence API | script bench | bench_job.py |
| Sécurité | Headers + rate limit | tests dédiés | test_security_headers.py |

### Couverture Minimale par Phase

- Fin S2 : 60% modules refactor
- Fin S4 : 80% storage/runtime + 60% global
- Fin S7 : 75% global (packaging code exclu) + 0 test critique manquant

## 8. Plan CI/CD (Cibles)

| Pipeline | Étape | Description |
|----------|-------|-------------|
| CI rapide | smoke | 1 job mock (<2 min visé) |
| CI complète | lint/type/tests | ruff, black check, mypy strict modules nouveaux |
| CI complète | tests | full suite (peut paralléliser) |
| Release | build images | Docker multi-arch (linux/amd64) |
| Release | build MSI | Runner Windows, PyInstaller + MSI |
| Release | version bump | Tag + changelog + artefacts |
| Release | publication | Upload MSI + image + SBOM (option) |

## 9. Gestion Version & Changelog

- Fichier `VERSION` (source vérité).
- Tag Git `vX.Y.Z` déclenche pipeline release.
- Changelog automatique (conventional commits) généré dans `CHANGELOG.md`.
- Politique version : MAJOR (breaking), MINOR (feature), PATCH (fix / safe refactor).

## 10. Classification des Posts (Amélioration Continue)

| Axe | État | Amélioration potentielle |
|-----|------|--------------------------|
| Recrutement heuristique | Implémenté | ML léger / pondération contextuelle |
| Détection langue | Basique (langdetect) | fastText modèle interne |
| Normalisation entreprise | Heuristique | Dictionnaire enrichi / mapping groupe |

## 11. Critères de Sortie (GA)

| Domaine | Critère | Méthode vérif |
|---------|---------|---------------|
| Fonctionnel | Dashboard liste posts réels + filtres de base | Test manuel script + captures |
| Packaging | MSI installe/désinstalle proprement | Procédure QA |
| Fiabilité | 3 runs consécutifs job mock OK | CI historique |
| Performances | Job mock < 15 s | Bench intégré |
| Sécurité | Headers + rate limit actifs | Test automatisé |
| Observabilité | Traces + métriques principales exposées | Curl /metrics + exporter traces dummy |
| Documentation | README, ARCHITECTURE_CURRENT, REFRACTOR_PLAN, DELIVERY_PLAN à jour | Revue doc |
| Couverture | ≥ objectifs phase | Rapport couverture |
| Pas de P1/P2 ouverts | Tableau de suivi issues | Revue finale |

## 12. RACI Simplifié

| Activité | Responsable (R) | Accountable (A) | Consulté (C) | Informé (I) |
|----------|-----------------|-----------------|--------------|-------------|
| Refactor worker | Dev principal | Chef projet | Pair | Équipe |
| Pipeline stockage | Dev principal | Chef projet | DBA (si) | Équipe |
| Packaging MSI | Dev build | Chef projet | Sec/IT | Utilisateurs |
| Sécurité headers | Dev sécurité | Chef projet | Reviewer | Équipe |
| Release GA | Chef projet | Direction interne | Devs | Utilisateurs |

## 13. Registre de Risques

| ID | Description | Prob | Impact | Mitigation | Trigger |
|----|-------------|------|--------|-----------|---------|
| R1 | Explosion complexité refactor | M | H | Découpage itératif + tests early | Couverture chute |
| R2 | Playwright instable CI | M | M | Mock par défaut + retry installation | Erreurs install >2/jour |
| R3 | Taille binaire MSI trop grande | L | M | Exclure pandas (optionnel) / split feature | MSI > 300MB |
| R4 | Fuite données sensibles `raw` | L | H | Masquage configurable + revue sécurité | Audit code |
| R5 | Latence job réelle élevée | M | M | Profiling S5 + instrumentation fine | P95 > objectif |
| R6 | Dépendance critique vulnérable | L | M | Audit S6 + dependabot | CVE HIGH détectée |

## 14. Backlog Ciblé (Extraits Priorisés)

| ID | Titre | Sprint cible | Type |
|----|-------|--------------|------|
| B1 | Extraire `dedup.py` | S2 | Refactor |
| B2 | Implémenter `StoragePipeline` | S3 | Feature infra |
| B3 | Ajouter migrations SQLite | S4 | Maintenabilité |
| B4 | OpenTelemetry traces | S5 | Observabilité |
| B5 | Security middleware (CSP, HSTS) | S6 | Sécurité |
| B6 | Build MSI signé | S7 | Packaging |
| B7 | Publication Docker tag auto | S7 | CI/CD |
| B8 | Export Parquet | S8 | Valeur métier |
| B9 | Webhooks JOB_COMPLETE | S8 | Intégration |

## 15. Checklist Pré-Release (RC → GA)

1. Tous les tests verts (CI complète) + smoke job < 2 min.
2. Couverture rapport respectant seuils.
3. Exécution manuelle : installation MSI → lancement → smoke.
4. Vérification headers sécurité (curl -I) + absence endpoints debug si prod.
5. Génération changelog + validation version bump.
6. Signature binaire (si certificat dispo) + hash publié.
7. Archivage artifact + documentation version.

## 16. Actions Immédiates Suite à ce Plan

- [ ] Maintenir ce fichier synchronisé à chaque fin de sprint.
- [ ] Créer issues Git correspondantes au backlog priorisé (B1..Bx).
- [ ] Ajouter script bench minimal (temps job mock) pour S5 future comparaison.
- [ ] Déterminer besoin d’exclure pandas du build MSI (analyse usage réel export Excel).

---

Ce plan complète `REFRACTOR_PLAN.md` (orientation refactor) par une vue livraison produit final. Toute divergence doit être alignée en comité technique interne.
