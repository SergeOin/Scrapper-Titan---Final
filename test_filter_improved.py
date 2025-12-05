#!/usr/bin/env python3
"""Test du filtre amélioré sur les posts problématiques."""

from scraper.legal_filter import is_legal_job_post

# Test posts problematiques
tests = [
    ('OpenToWork candidat', 'Bonjour a tous ! Je recherche un nouveau poste et vous serais reconnaissant(e) de mapporter votre aide. Si vous entendez parler dune opportunite'),
    ('Evenement/Defi', 'Felicitations aux 4 equipes finalistes de la 6eme edition du Defi Paris-Saclay / White Case. Rendez-vous le 10 decembre pour la Grande Finale'),
    ('Exam results', 'jadresse mes chaleureuses felicitations aux 78 etudiants de IEJ Paris admis au 1er concours de Ecole nationale de la Magistrature'),
    ('Publication/Article', 'Je suis ravi de partager avec vous article recent publie par Euractiv France issu de deux interviews celle de juriste chez BEUC'),
    ('Offre valide', 'Nous recrutons un juriste en droit des affaires pour rejoindre notre direction juridique en CDI'),
    ('Offre valide 2', 'Cabinet avocat Paris recrute avocat collaborateur droit social CDI'),
]

print("=== TEST DU FILTRE AMELIORE ===\n")

for name, text in tests:
    result = is_legal_job_post(text)
    status = 'OK' if result.is_valid else 'REJETE'
    reason = result.exclusion_reason[:70] + '...' if result.exclusion_reason and len(result.exclusion_reason) > 70 else (result.exclusion_reason or 'valide')
    print(f'[{status}] {name}')
    print(f'    Raison: {reason}')
    print()
