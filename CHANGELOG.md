# Changelog

All notable changes to this project will be documented in this file.

The format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and uses semantic versioning when practical.

## [Unreleased]
### Added
- (placeholder) Future enhancements will be listed here.

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

[Unreleased]: https://github.com/SergeOin/Scrapper-Titan---Final/compare/v1.3.3...HEAD
[1.3.3]: https://github.com/SergeOin/Scrapper-Titan---Final/releases/tag/v1.3.3
[1.3.2]: https://github.com/SergeOin/Scrapper-Titan---Final/releases/tag/v1.3.2
[1.3.1]: https://github.com/SergeOin/Scrapper-Titan---Final/releases/tag/v1.3.1
[1.3.0]: https://github.com/SergeOin/Scrapper-Titan---Final/releases/tag/v1.3.0
