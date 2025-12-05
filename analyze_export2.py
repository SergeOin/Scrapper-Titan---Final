#!/usr/bin/env python3
"""Analyse les posts scrapés pour évaluer la pertinence du filtre."""

import csv
from collections import Counter

# Lire le CSV avec le bon encodage
posts = []
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

print(f'\n=== ANALYSE DES {len(posts)} POSTS SCRAPES ===\n')

# Afficher les colonnes disponibles
if posts:
    print(f"Colonnes disponibles: {list(posts[0].keys())}\n")

# Catégoriser les posts
pertinents = []
non_pertinents = []
categories_rejet = Counter()

for p in posts:
    # Adapter aux vraies colonnes
    texte = (p.get('Texte', '') or '').lower()
    auteur = (p.get('Auteur', '') or '').lower()
    entreprise = (p.get('Entreprise', '') or '').lower()
    metier = (p.get('Métier', '') or p.get('M\x82tier', '') or '').lower()
    opportunite = (p.get('Opportunité', '') or p.get('Opportunit\x82', '') or '').lower()
    keyword = (p.get('Keyword', '') or '').lower()
    
    raison_rejet = None
    
    # 1. Candidat #OpenToWork cherchant un poste
    if '#opentowork' in texte or 'opentowork' in texte:
        if 'nous recrutons' not in texte and 'on recrute' not in texte and 'recrutement' not in texte:
            raison_rejet = 'Candidat #OpenToWork'
    
    # 2. Candidat cherchant un poste (formulations courantes)
    elif any(phrase in texte for phrase in [
        'je recherche un nouveau poste',
        'je suis à la recherche',
        'je recherche activement',
        'je me lance dans la recherche',
        'en quête de nouvelles opportunités',
        'je cherche un poste',
        'looking for a new position',
        'looking for opportunities',
        "bonjour à tous ! je recherche",
        "j'aimerais reprendre contact"
    ]):
        if 'nous recrutons' not in texte and 'on recrute' not in texte:
            raison_rejet = 'Candidat en recherche'
    
    # 3. Annonce de prise de poste (bienvenue, a rejoint, félicitations personnelles)
    elif any(phrase in texte for phrase in [
        "j'ai le plaisir de vous annoncer que j'occupe",
        "je suis ravi de vous annoncer que j'ai rejoint",
        "je suis heureuse de vous annoncer",
        "j'ai rejoint",
        "a rejoint notre équipe",
        "bienvenue à",
        "nous sommes heureux d'accueillir",
        "a rejoint l'équipe",
        "je viens de rejoindre",
        "j'ai intégré",
        "je prends mes nouvelles fonctions"
    ]):
        raison_rejet = 'Annonce de prise de poste'
    
    # 4. Félicitations étudiants/examens (pas une offre d'emploi)
    elif any(phrase in texte for phrase in [
        'félicitations aux',
        'félicitation aux',
        'admis au',
        'admis à l\'examen',
        'résultats du concours',
        'plein succès dans la suite',
        'fière de leur réussite',
        'défi',
        'finale',
        'compétition'
    ]) and 'recrut' not in texte and 'poste' not in texte:
        raison_rejet = 'Événement/Félicitations'
    
    # 5. Article/publication académique sans offre
    elif 'article' in texte[:100] or 'publication' in texte[:100] or 'ouvrage' in texte[:100]:
        if 'recrut' not in texte and 'poste' not in texte:
            raison_rejet = 'Publication/Article'
    
    # 6. Hors France sans mention France
    elif any(pays in texte for pays in ['tunisie', 'morocco', 'maroc', 'algérie', 'dubai', 'usa']):
        if 'france' not in texte and 'paris' not in texte and 'lyon' not in texte:
            raison_rejet = 'Hors France'
    
    # 7. Arnaque potentielle (email outlook pour grande entreprise)
    elif 'outlook.com' in texte and any(e in texte for e in ['general electric', 'google', 'microsoft', 'amazon']):
        raison_rejet = 'Arnaque potentielle'
    
    if raison_rejet:
        non_pertinents.append((p, raison_rejet))
        categories_rejet[raison_rejet] += 1
    else:
        pertinents.append(p)

print(f'[OK] POSTS PERTINENTS: {len(pertinents)}/{len(posts)} ({100*len(pertinents)//max(len(posts),1)}%)')
print(f'[X] POSTS NON PERTINENTS: {len(non_pertinents)}/{len(posts)} ({100*len(non_pertinents)//max(len(posts),1)}%)')
print()
print('=== RAISONS DE REJET ===')
for raison, count in categories_rejet.most_common():
    print(f'  {raison}: {count}')
print()

print('=== LISTE DES POSTS NON PERTINENTS ===')
for i, (p, raison) in enumerate(non_pertinents):
    print(f'\n[X] [{raison}] {p.get("Auteur", "N/A")}')
    texte = (p.get('Texte', '') or '')[:150].replace('\n', ' ')
    print(f"   {texte}...")
    print(f"   Lien: {p.get('Lien', 'N/A')}")

print('\n\n=== LISTE DES POSTS PERTINENTS ===')
for i, p in enumerate(pertinents):
    print(f'\n[OK] [{i+1}] {p.get("Auteur", "N/A")} - {p.get("Entreprise", "N/A")}')
    print(f"   Keyword: {p.get('Keyword', 'N/A')}")
    print(f"   Métier: {p.get('Métier', '') or p.get('M\x82tier', 'N/A')}")
    print(f"   Opportunité: {p.get('Opportunité', '') or p.get('Opportunit\x82', 'N/A')}")
    texte = (p.get('Texte', '') or '')[:200].replace('\n', ' ')
    print(f"   Extrait: {texte}...")

# Résumé final
print('\n\n' + '='*60)
print('RÉSUMÉ FINAL')
print('='*60)
print(f'Total posts scrapés: {len(posts)}')
print(f'Posts pertinents (offres d\'emploi actives): {len(pertinents)}')
print(f'Posts non pertinents: {len(non_pertinents)}')
print(f'Taux de pertinence: {100*len(pertinents)//max(len(posts),1)}%')
print()
if non_pertinents:
    print('⚠️  AMÉLIORATION DU FILTRE RECOMMANDÉE:')
    for raison, count in categories_rejet.most_common(5):
        print(f'  - Exclure "{raison}": {count} posts')
