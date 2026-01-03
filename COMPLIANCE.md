# Conformité & Bonnes Pratiques (Pipeline Posts Juridiques)

Ce document récapitule les garde‑fous implémentés et les actions attendues pour rester conforme aux CGU LinkedIn et au cadre légal (RGPD si applicable).

## 1. Portée & Usage
- Usage strictement interne (pas de redistribution publique des données collectées).
- Objectif limité : identification d'offres / signaux de recrutement de profils juridiques en France (~50 posts/jour max).

## 2. Collecte & Accès
- Priorité à l'usage d'API officielles si/et quand disponibles. Le module Playwright ne doit pas contourner de protections.
- Le projet contient du code de "stealth/anti-detection" (ex: scripts d'empreinte navigateur) **désactivé par défaut** et uniquement activable explicitement (opt-in). Son usage est un point de conformité sensible (risque CGU/plateforme) et doit être évité sans validation.
- Session authentifiée fournie explicitement par un compte autorisé (pas de contournement d'authentification).
- Pas d'extraction massive: pacing + token bucket + limites quotidiennes.

## 3. Filtrage & Minimisation
- Filtrage langue: uniquement contenus détectés FR (`FILTER_LANGUAGE_STRICT`).
- Filtrage géographique France (heuristique) + rejet posts ciblant exclusivement des localisations étrangères.
- Domain filtering légal + classification intent => seuls les posts avec intention de recrutement claire (`intent = recherche_profil`) sont persistés.
- Limitation quantitative: `LEGAL_DAILY_POST_CAP` (par défaut 50) – arrêt anticipé une fois atteint.

## 4. Schéma & Données
- Données stockées : texte du post, auteur, date, lien, indicateurs de classification (score, keywords, intent, location_ok).
- Aucune donnée sensible non nécessaire (emails privés, IDs internes) n'est collectée.
- Possibilité de suppression sélective : supprimer par clé primaire SQLite.

## 5. Journalisation & Audit
- Logs structurés (JSON) incluant événements de classification / filtrage / quota.
- Métriques Prometheus : `legal_posts_total`, `legal_posts_discarded_total{reason}`, `legal_daily_cap_reached_total` pour supervision.
- Traçabilité build: endpoint `/api/version`.

## 6. Droits Individus / RGPD (si applicable)
- Données limitées à ce qui est déjà public ; pas de profilage avancé.
- Procédure de purge : suppression par identifiant sur demande (script dédié possible).
- Aucune base nominative exportée sans justification.

## 7. Sécurité
- Variables sensibles dans `.env` (jamais commit).
- Possibilité d'activer une Basic Auth interne pour protéger le dashboard.
- Hash bcrypt auto-généré pour mots de passe `INTERNAL_AUTH_PASS`.

## 8. Extension Futur Conforme
- Intégrer éventuellement un consentement explicite / API partenaire.
- Ajouter anonymisation (hachage noms) si conservation long terme non justifiée.
- Ajout d'un module ML : conserver explicabilité (feature importance) + seuils documentés.

## 9. Points de Vigilance
- Surveiller l'évolution des CGU LinkedIn.
- Ajuster / réduire la fréquence si signaux d'éventuel blocage.
- Vérifier régulièrement l'absence de collecte hors scope (ex: posts purement marketing ou personnels).

---
Dernière mise à jour : automatique à l'ajout du classifieur juridique.