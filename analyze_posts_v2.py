#!/usr/bin/env python3
"""Analyse complète des posts scrapés pour améliorer les filtres."""

import csv
from collections import Counter

# Lire le CSV avec le bon encodage
posts = []
for encoding in ['utf-8', 'utf-8-sig', 'cp1252', 'iso-8859-1', 'latin-1']:
    try:
        with open('linkedin_posts_20251202_172900.csv', 'r', encoding=encoding) as f:
            reader = csv.DictReader(f, delimiter=';')
            for row in reader:
                posts.append(row)
        print(f"Fichier lu avec l'encodage: {encoding}")
        break
    except UnicodeDecodeError:
        posts = []
        continue

print(f'\n=== ANALYSE DE {len(posts)} POSTS ===\n')

# Patterns à identifier
candidats_opentowork = []
evenements_concours = []
annonces_prise_poste = []
articles_publications = []
formations_conferences = []
hors_france = []
autres_non_pertinents = []
offres_valides = []

for p in posts:
    texte = (p.get('Texte', '') or '').lower()
    auteur = (p.get('Auteur', '') or '')
    
    raison = None
    
    # 1. Candidats #OpenToWork ou en recherche
    if any(phrase in texte for phrase in [
        'opentowork', '#opentowork', 'open to work',
        'je recherche un nouveau poste',
        'je suis actuellement en recherche active',
        'en recherche active',
        'je recherche des postes de',
        'bonjour a tous ! je recherche',
        'si vous entendez parler d une opportunite',
        'j aimerais reprendre contact',
        'je vous serais reconnaissant',
        'a la recherche d une nouvelle opportunite',
        'si vous recrutez, ou si vous connaissez',
        'disponible immediatement',
        'je suis a l ecoute de nouvelles opportunites'
    ]):
        if 'nous recrutons' not in texte and 'on recrute' not in texte:
            candidats_opentowork.append((auteur, texte[:100]))
            raison = 'candidat_opentowork'
    
    # 2. Événements, concours, défis, compétitions
    if not raison and any(phrase in texte for phrase in [
        'felicitations aux', 'felicitation aux',
        'equipes finalistes', 'grande finale',
        'edition du defi', 'defi ',
        'concours', 'competition',
        'jury preside par', 'jury sera preside',
        'bonne chance a tous', 'bonne chance !',
        'admis au', 'admis a l examen',
        'resultats du concours', 'resultats de l examen',
        'crfpa', 'iej', 'ecole nationale de la magistrature',
        'hackathon', 'challenge'
    ]) and 'recrut' not in texte:
        evenements_concours.append((auteur, texte[:100]))
        raison = 'evenement_concours'
    
    # 3. Annonces de prise de poste / nomination
    if not raison and any(phrase in texte for phrase in [
        "j ai le plaisir de vous annoncer que j occupe",
        "j occupe desormais le poste",
        "je suis ravi de vous annoncer que j ai rejoint",
        "je suis heureuse de vous annoncer",
        "j ai rejoint", "j ai integre",
        "a rejoint notre equipe", "a rejoint l equipe",
        "bienvenue a ", "bienvenue dans l equipe",
        "nous avons le plaisir d accueillir",
        "vient de rejoindre", "vient d integrer",
        "nouvelle recrue", "nouveau collaborateur",
        "a pris ses fonctions", "prend ses fonctions",
        "vient d etre nomme", "a ete nomme",
        "nomination de", "est nomme",
        "je prends mes nouvelles fonctions"
    ]):
        annonces_prise_poste.append((auteur, texte[:100]))
        raison = 'annonce_prise_poste'
    
    # 4. Articles, publications, conférences
    if not raison and any(phrase in texte for phrase in [
        'je suis ravi de partager avec vous l article',
        'publication de', 'nouvel article',
        'notre dernier article', 'mon article',
        'podcast', 'webinar', 'webinaire',
        'seminaire', 'conference',
        'replay', 'rediffusion',
        'livre blanc', 'white paper',
        'newsletter', 'inscrivez-vous'
    ]) and 'recrut' not in texte and 'poste' not in texte:
        articles_publications.append((auteur, texte[:100]))
        raison = 'article_publication'
    
    # 5. Formations, cours, écoles
    if not raison and any(phrase in texte for phrase in [
        'formation', 'masterclass', 'cours de',
        'promotion', 'diplome', 'diplomee',
        'etudiant', 'etudiante', 'etudes',
        'ecole', 'universite', 'master ',
        'licence', 'doctorat'
    ]) and 'recrut' not in texte and 'cdi' not in texte and 'cdd' not in texte:
        formations_conferences.append((auteur, texte[:100]))
        raison = 'formation_ecole'
    
    # 6. Hors France (si pas de mention France/Paris/Lyon etc)
    if not raison:
        pays_etrangers = ['canada', 'quebec', 'montreal', 'usa', 'belgique', 'suisse', 
                          'luxembourg', 'uk', 'london', 'allemagne', 'germany', 'dubai',
                          'maroc', 'tunisie', 'algerie', 'casablanca']
        villes_france = ['france', 'paris', 'lyon', 'marseille', 'bordeaux', 'lille', 
                         'nantes', 'toulouse', 'strasbourg', 'nice', 'rennes']
        
        has_foreign = any(pays in texte for pays in pays_etrangers)
        has_france = any(ville in texte for ville in villes_france)
        
        if has_foreign and not has_france:
            hors_france.append((auteur, texte[:100]))
            raison = 'hors_france'
    
    # Si pas de raison de rejet, c'est potentiellement valide
    if not raison:
        offres_valides.append((auteur, texte[:150]))

# Afficher les résultats
print("="*60)
print("STATISTIQUES")
print("="*60)
print(f"Candidats #OpenToWork: {len(candidats_opentowork)}")
print(f"Événements/Concours: {len(evenements_concours)}")
print(f"Annonces prise de poste: {len(annonces_prise_poste)}")
print(f"Articles/Publications: {len(articles_publications)}")
print(f"Formations/Écoles: {len(formations_conferences)}")
print(f"Hors France: {len(hors_france)}")
print(f"Offres potentiellement valides: {len(offres_valides)}")
print()

total_rejets = (len(candidats_opentowork) + len(evenements_concours) + 
                len(annonces_prise_poste) + len(articles_publications) + 
                len(formations_conferences) + len(hors_france))
print(f"TOTAL REJETS: {total_rejets}/{len(posts)} ({100*total_rejets//len(posts)}%)")
print(f"TAUX PERTINENCE: {100*len(offres_valides)//len(posts)}%")

# Détails des posts problématiques
print("\n" + "="*60)
print("CANDIDATS #OPENTOWORK (à exclure)")
print("="*60)
for auteur, extrait in candidats_opentowork[:10]:
    print(f"- {auteur}: {extrait[:80]}...")

print("\n" + "="*60)
print("ÉVÉNEMENTS/CONCOURS (à exclure)")
print("="*60)
for auteur, extrait in evenements_concours[:10]:
    print(f"- {auteur}: {extrait[:80]}...")

print("\n" + "="*60)
print("ANNONCES PRISE DE POSTE (à exclure)")
print("="*60)
for auteur, extrait in annonces_prise_poste[:10]:
    print(f"- {auteur}: {extrait[:80]}...")

print("\n" + "="*60)
print("OFFRES VALIDES (à garder)")
print("="*60)
for auteur, extrait in offres_valides[:15]:
    print(f"+ {auteur}: {extrait[:100]}...")
