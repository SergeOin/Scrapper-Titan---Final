#!/usr/bin/env python3
"""Analyse les posts scrapés pour évaluer la pertinence du filtre."""

import csv
from collections import Counter

# Lire le CSV
posts = []
# Essayer plusieurs encodages
for encoding in ['utf-8', 'utf-8-sig', 'cp1252', 'iso-8859-1', 'latin-1']:
    try:
        with open('linkedin_posts_20251202_160325.csv', 'r', encoding=encoding) as f:
            reader = csv.DictReader(f, delimiter=';')
            for row in reader:
                posts.append(row)
        print(f"Fichier lu avec l'encodage: {encoding}")
        break
    except UnicodeDecodeError:
        posts = []
        continue

print(f'=== ANALYSE DES {len(posts)} POSTS SCRAPES ===\n')

# Catégoriser les posts
pertinents = []
non_pertinents = []
categories_rejet = Counter()

for p in posts:
    texte = (p.get('texte', '') or '').lower()
    auteur = (p.get('auteur', '') or '').lower()
    titre_auteur = (p.get('titre_auteur', '') or '').lower()
    type_contrat = (p.get('type_contrat', '') or '').lower()
    postes_detectes = (p.get('postes_detectes', '') or '').lower()
    is_recruiter = p.get('is_recruiter', '') == 'Oui'
    
    raison_rejet = None
    
    # 1. Candidat #OpenToWork cherchant un poste
    if 'opentowork' in texte or '#opentowork' in texte:
        if 'nous recrutons' not in texte and 'on recrute' not in texte and 'recrutement' not in texte:
            raison_rejet = 'Candidat #OpenToWork'
    
    # 2. Candidat cherchant un poste (formulations courantes)
    elif any(phrase in texte for phrase in [
        'je recherche un nouveau poste',
        'je suis à la recherche',
        'je recherche activement',
        'je me lance dans la recherche',
        'en quête de nouvelles opportunités',
        'disponible immédiatement',
        'je cherche un poste',
        'looking for a new position',
        'looking for opportunities'
    ]):
        if 'nous recrutons' not in texte and 'on recrute' not in texte:
            raison_rejet = 'Candidat en recherche'
    
    # 3. Annonce de prise de poste (bienvenue, a rejoint)
    elif any(phrase in texte for phrase in [
        "j'ai le plaisir de vous annoncer que j'occupe",
        "je suis ravi de vous annoncer que j'ai rejoint",
        "je suis heureuse de vous annoncer",
        "j'ai rejoint",
        "a rejoint notre équipe",
        "bienvenue à",
        "nous sommes heureux d'accueillir",
        "a rejoint l'équipe",
        "je viens de rejoindre"
    ]):
        raison_rejet = 'Annonce de prise de poste'
    
    # 4. Stage ou alternance
    elif 'stage' in type_contrat.lower() or 'alternance' in type_contrat.lower():
        raison_rejet = 'Stage/Alternance'
    
    # 5. Freelance uniquement (sans CDI)
    elif type_contrat.lower() == 'freelance':
        raison_rejet = 'Freelance uniquement'
    
    # 6. Arnaque potentielle (email outlook pour grande entreprise)
    elif 'outlook.com' in texte and any(e in texte for e in ['general electric', 'google', 'microsoft', 'amazon']):
        raison_rejet = 'Arnaque potentielle'
    
    # 7. Hors France sans mention France
    elif any(pays in texte for pays in ['tunisie', 'morocco', 'maroc', 'algérie', 'dubai', 'usa', 'belgique', 'suisse', 'luxembourg']):
        if 'france' not in texte and 'paris' not in texte and 'lyon' not in texte:
            raison_rejet = 'Hors France potentiel'
    
    # 8. Post non-recrutement (événement, article)
    elif not is_recruiter:
        mots_recrutement = ['recrut', 'embauche', 'hiring', 'poste à pourvoir', 'nous cherchons', 'on cherche', 'cdi', 'offre d\'emploi']
        if not any(mot in texte for mot in mots_recrutement):
            if len(texte) > 800:  # Long article sans mention recrutement
                raison_rejet = 'Article/événement sans offre'
    
    if raison_rejet:
        non_pertinents.append((p, raison_rejet))
        categories_rejet[raison_rejet] += 1
    else:
        pertinents.append(p)

print(f'✅ POSTS PERTINENTS: {len(pertinents)}/{len(posts)} ({100*len(pertinents)//len(posts)}%)')
print(f'❌ POSTS NON PERTINENTS: {len(non_pertinents)}/{len(posts)} ({100*len(non_pertinents)//len(posts)}%)')
print()
print('=== RAISONS DE REJET ===')
for raison, count in categories_rejet.most_common():
    print(f'  {raison}: {count}')
print()

print('=== DÉTAIL DES POSTS PERTINENTS ===')
for i, p in enumerate(pertinents):
    print(f'\n--- Post pertinent {i+1} ---')
    print(f"Auteur: {p.get('auteur', 'N/A')}")
    print(f"Titre auteur: {p.get('titre_auteur', 'N/A')[:80]}...")
    print(f"Postes détectés: {p.get('postes_detectes', 'N/A')}")
    print(f"Type contrat: {p.get('type_contrat', 'N/A')}")
    print(f"Recruteur: {p.get('is_recruiter', 'N/A')}")
    print(f"Localisation: {p.get('localisation', 'N/A')}")
    texte = (p.get('texte', '') or '')[:250].replace('\n', ' ')
    print(f"Extrait: {texte}...")

print('\n\n=== DÉTAIL DES POSTS REJETÉS ===')
for i, (p, raison) in enumerate(non_pertinents):
    print(f'\n--- Post rejeté {i+1} ({raison}) ---')
    print(f"Auteur: {p.get('auteur', 'N/A')}")
    print(f"Titre auteur: {p.get('titre_auteur', 'N/A')[:80]}...")
    texte = (p.get('texte', '') or '')[:200].replace('\n', ' ')
    print(f"Extrait: {texte}...")

# Résumé final
print('\n\n' + '='*60)
print('RÉSUMÉ FINAL')
print('='*60)
print(f'Total posts scrapés: {len(posts)}')
print(f'Posts pertinents (offres d\'emploi actives): {len(pertinents)}')
print(f'Posts non pertinents: {len(non_pertinents)}')
print(f'Taux de pertinence: {100*len(pertinents)//len(posts)}%')
print()
print('Pour améliorer le filtre, il faudrait exclure:')
for raison, count in categories_rejet.most_common(5):
    print(f'  - {raison}: {count} posts')
