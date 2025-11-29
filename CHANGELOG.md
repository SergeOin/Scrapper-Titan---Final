# Changelog

All notable changes to this project will be documented in this file.

The format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and uses semantic versioning when practical.

## [1.3.25] - 2025-11-28
### Improved
- **Filtre légal amélioré**: Taux de pertinence des posts passé de 29% à 59%
  - Ajout de nouveaux mots-clés de professions juridiques (juriste recouvrement, juriste legal ops, ingénieur patrimonial, etc.)
  - Enrichissement des signaux de recrutement (patterns "[Company] recrute", "recrute des juriste/avocat", etc.)
  - Amélioration de la fonction de scoring de recrutement avec détection regex de "[X] recrute"
  - Réduction des faux positifs dans les exclusions promotionnelles
  - Meilleure gestion des exclusions de chercheurs d'emploi

### Fixed
- Exclusion "hors_france" trop permissive : suppression de la logique "CDI implique France"

## [Unreleased]
### Added
- Fusion SBOM auto (cyclonedx-cli) si plusieurs fichiers détectés.
- Scan Trivy filesystem (vuln/secret/misconfig) non bloquant dans `supply-chain`.

### Security / Supply Chain
- Documentation README section "Supply Chain & Provenance".

## [1.3.14] - 2025-10-08
### Added
- Test sentinelle `test_spec_presence.py` garantissant la présence et l'intégrité de `TitanScraper.spec`.
- Workflow manuel `publish-release` (promotion d'une release draft en release publiée via `workflow_dispatch`).

### Changed
- Nettoyage `release.yml`: suppression des étapes redondantes SBOM / merge / scans / provenance (désormais centralisées dans `supply-chain`).

### Internal
- Consolidation de la responsabilité supply-chain (SBOM & scans) vs build pur (release).

## [1.3.13] - 2025-10-08
### Fixed
- Échec build macOS: suppression des options PyInstaller incompatibles avec l'usage d'un fichier `.spec` (plus d'erreur "option(s) not allowed").
- Échec build Windows: absence de `desktop/pyinstaller.spec` corrigée par priorité à `TitanScraper.spec` puis fallback ad hoc.
- Installation SBOM: pin cyclonedx-bom invalide (`3.19.6`) remplacée par version existante `7.1.0` + fallback no-pin.
- Échecs potentiels greenlet sur Python 3.13 évités en conservant usage spec sous l'interpréteur 3.11.

### Changed
- Étapes SBOM dans `release.yml` rendues explicitement non bloquantes; génération principale confiée au workflow `supply-chain`.
- Scripts build (mac/windows) robustifiés avec fallback sans spec.

### Internal
- Ajout logique fallback PyInstaller (mac & windows) et simplification pipeline.

### Notes
- Prochain tag confirmera la réussite complète (MSI + DMG) avec corrections; signature macOS toujours désactivée.

## [1.3.12] - 2025-10-08
### Added
- Workflow `supply-chain` séparé (SBOM CycloneDX, scan OSV via pip-audit, tentative de téléchargement des assets de release pour attestation provenance) déclenché sur tags `v*` et `workflow_dispatch`.
- Réintégration lint (ruff), format check (black --check) et mypy dans le workflow CI unifié.
- Workflow auto bump version réintroduit (patch increment) après contributions sur `main`.

### Changed
- Consolidation de `release.yml`: suppression du bloc hérité massif, conservation d'une version claire (build Windows/macOS, validation assets, checksums, manifest, changelog extraction, attachements). Étape signature macOS retirée pour simplifier (placeholder comment).
- VERSION bump -> 1.3.12.

### Removed
- Bloc legacy `build-release` dupliqué (redondant avec version minimaliste).
- Étape de signature macOS (pour éviter erreurs lint et simplifier; pourra être réintroduite proprement avec secrets configurés).

### Security / Supply Chain
- SBOM générée indépendamment du build principal (meilleure isolation & possibilité de ré-exécuter sur tag existant).
- Attestation provenance produite si assets présents.

### Notes
- Prochaine étape potentielle: fusion/merge avancée des SBOM multi-OS via cyclonedx-cli, ajout Trivy FS/Container scan, réintroduction étape de signature macOS conditionnelle.

## [1.3.11] - 2025-10-08
### Added
- Réintroduction d'un workflow CI minimal (tests + couverture optionnelle) après neutralisation totale précédente.
- Nouveau workflow de release minimal (build Windows/macOS + release draft sur tag v*).

### Notes
- Fonctions avancées (SBOM, provenance, nightly, auto-bump) restent désactivées.

## [1.3.10] - 2025-10-08
### Changed
- Neutralisation complète de tous les workflows GitHub Actions (tous les fichiers remplacés par des commentaires inertes).

### Removed
- CI (tests, coverage), nightly report, auto bump version, desktop build/release workflows.

### Notes
- Plus aucun workflow actif: aucun build automatisé ni test ne se lancera jusqu'à réintroduction ciblée.


## [1.3.9] - 2025-10-08
### Added
- Séparation des dépendances runtime vs développement (`requirements.txt` / `requirements-dev.txt`).
- Script d'inspection de configuration sécurisé (`scraper/config_inspect.py`) + commande `make show-config` / `scripts/show_config.py`.
- Génération automatique d'un badge de couverture `coverage_badge.svg` (script `scripts/generate_badge.py`) intégrée au workflow CI.
- Makefile développeur (install, lint, test, coverage, format, run, etc.).

### Changed
- Workflows CI: installation des dépendances de dev séparées, génération du badge coverage comme artefact.
- Logging bootstrap: affichage snapshot configuration masquée pour visibilité sans fuite de secrets.

### Internal
- Nettoyage du fichier `requirements.txt` (suppression des affectations d'environnement invalides, déplacement vers `.env`).
- Amélioration ergonomie développeur (cibles Make, documentation README mise à jour avec nouvelle section couverture et usage Makefile).

## [1.3.6] - 2025-10-08
### Added
- Rotation automatique des booster keywords (paramètres: `BOOSTER_ROTATION_ENABLED`, `BOOSTER_ROTATION_SUBSET_SIZE`, `BOOSTER_ROTATION_SHUFFLE`).
- Exclusion configurable des sources (`EXCLUDED_AUTHORS` incluant par défaut "village de la justice").
- Booster adaptatif + assouplissement du seuil recrutement (-10% si en retard sur l'objectif).
- Installation automatique de `numpy` et `pandas` dans le script MSI (`build_msi_folder.ps1`) si absents du dossier dist.
- Test automatisé `test_msi_numpy_pandas.py` vérifiant la présence du bloc d'installation.

### Changed
- Scroll dynamique poussé au maximum adaptatif quand la progression journalière est insuffisante.

### Fixed
- Prévention de régression packaging scientifique: garde-fou test sur script MSI.

### Internal
- Ajout champs config (`BOOSTER_KEYWORDS`, `BOOSTER_ACTIVATE_RATIO`, `RELAX_FILTERS_BELOW_TARGET`).

## [1.3.4] - 2025-10-03
## [1.3.5] - 2025-10-03
### Added
- Sidecar `.sha256` par fichier (MSI / DMG / EXE / ZIP portable) + maintien `checksums.txt` global.
- Diagnostics détaillés: listing récursif `build` & `dist` côté job Windows, tree artefacts côté job release.

### Changed
- Globs d'assets élargis (exe, dll, app, zip) pour réduire risques de non-attachement.

### Fixed
- Problème persistant d'assets manquants (élargissement patterns + visibilité pré-publication).

### Internal
- Prépare prochaine étape: signature macOS & post-release validation.

### Fixed
- Release missing MSI/ZIP assets: corrected artifact globs to include `dist/msi/*.msi` (actual output path) plus portable ZIP in publish step.

### Added
- Portable ZIP now explicitly attached to Release assets list.

### Internal
- Fallback legacy path `build/msi/*.msi` kept for safety while transition confirmed.


## [1.3.3] - 2025-10-03
### Added
- Archive portable Windows (`TitanScraper-<version>-portable.zip`).
- Génération automatique des notes de release depuis le CHANGELOG.
- Suffixe architecture (ex: `-x64`) ajouté au nom du MSI.

### Changed
- Workflow release : création ZIP, extraction section CHANGELOG avec awk avant publication.

### Security / Signing
- Signature conditionnelle EXE/MSI si secrets `WINDOWS_CERT_PFX` (Base64) + `WINDOWS_CERT_PASSWORD` fournis.

### Removed
- Étape d’upload manifest dupliquée (nettoyage).

## [1.3.2] - 2025-10-03
### Fixed
- Release assets manquants (seulement code source) : correction des chemins d'artefacts (`dist/TitanScraper/**`, `dist/*.dmg`).
- Remplacement des références obsolètes `LinkedInScraper` et spec précédente par processus build unifié (scripts `build_windows.ps1`, `build_mac.sh`, `scripts/build_dmg.sh`).

### Changed
- MSI construit via `build_msi_folder.ps1` après PyInstaller au lieu d'un script packaging externe.

### Added
- Inclusion DMG et MSI cohérente avec nom produit `TitanScraper`.

## [1.3.1] - 2025-10-03
### Added
- Manifest `DOWNLOADS.txt` automatique listant MSI, DMG et binaires Windows dans la Release.
- Intégration MSI + DMG directement dans le workflow tag (réordonnancement pour inclure le manifest avant création de la Release).

### Changed
- Réorganisation du workflow `build-release` : génération checksums + manifest avant attachement des assets.

### Fixed
- Asset manifest auparavant généré après la Release (non inclus) – maintenant présent.

### Internal
- Nettoyage étapes superflues d’upload manifest.

## [1.3.0] - 2025-10-03
### Added
- Legal domain classification stabilization with stricter heuristic (negation-aware recruitment phrase requirement).
- Daily legal quota tracking (`legal_daily_date`, `legal_daily_count`, `legal_daily_discard_intent`, `legal_daily_discard_location`).
- `/api/legal_stats` exposing accepted vs discarded counts and cap progress.
- On-demand reclassification & `classification_debug` via `include_raw=1` parameter.
- Dynamic SQLite column selection & automatic migration for legal classification fields.
- Unified `entrypoint.py` orchestrating server + supervised worker with respawn & log rotation.
- Windows service install/uninstall PowerShell scripts (`windows_service_install.ps1`, `windows_service_uninstall.ps1`).
- Playwright browser cache in release workflow (faster CI builds).
- README documentation for service mode, macOS signing template, quota fields.

### Changed
- Conservative classifier logic reduces false positives (requires validated recruitment phrase; penalizes generic/legal words without intent).
- Replaced previous combined run script usage in packaging with entrypoint-focused PyInstaller spec.
- Stricter early filtering for domain + recruitment signals before persistence.

### Fixed
- AttributeError for missing legal quota attributes under `AppContext` due to `slots=True`.
- Missing classification fields on `Post` dataclass (slots) causing runtime errors during enrichment.
- False positive low-signal posts misclassified as recruitment.
- `include_raw` API path lacking `classification_debug` for legacy SQLite rows.
- SQLite query failing when certain columns absent (`author_profile` etc.) via dynamic column introspection.

### Removed
- Implicit dynamic attribute additions for quota fields (now explicit in dataclasses).

### Internal / Tooling
- Added targeted tests for entrypoint test mode and legal classification outcomes.
- Improved logging around permalink resolution & worker lifecycle.

## [1.2.x] - 2025-09-xx
### Overview
Initial public-internal MVP iterations: multi-backend storage (Mongo/SQLite/CSV), recruitment signal metric, basic dashboard, Prometheus metrics, fallback logic, mock mode, packaging groundwork.

[Unreleased]: https://github.com/SergeOin/Scrapper-Titan---Final/compare/v1.3.14...HEAD
[1.3.14]: https://github.com/SergeOin/Scrapper-Titan---Final/releases/tag/v1.3.14
[1.3.13]: https://github.com/SergeOin/Scrapper-Titan---Final/releases/tag/v1.3.13
[1.3.12]: https://github.com/SergeOin/Scrapper-Titan---Final/releases/tag/v1.3.12
[1.3.9]: https://github.com/SergeOin/Scrapper-Titan---Final/releases/tag/v1.3.9
[1.3.6]: https://github.com/SergeOin/Scrapper-Titan---Final/releases/tag/v1.3.6
[1.3.5]: https://github.com/SergeOin/Scrapper-Titan---Final/releases/tag/v1.3.5
[1.3.4]: https://github.com/SergeOin/Scrapper-Titan---Final/releases/tag/v1.3.4
[1.3.3]: https://github.com/SergeOin/Scrapper-Titan---Final/releases/tag/v1.3.3
[1.3.2]: https://github.com/SergeOin/Scrapper-Titan---Final/releases/tag/v1.3.2
[1.3.1]: https://github.com/SergeOin/Scrapper-Titan---Final/releases/tag/v1.3.1
[1.3.0]: https://github.com/SergeOin/Scrapper-Titan---Final/releases/tag/v1.3.0
