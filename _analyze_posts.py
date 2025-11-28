#!/usr/bin/env python3
"""Analyse des posts pour identifier les problèmes de pertinence."""
import json
from collections import Counter

# Charger les posts
with open('posts.json', 'r', encoding='utf-8') as f:
    raw = json.load(f)

# Handle both list and dict formats
if isinstance(raw, dict):
    data = raw.get('items', [])
else:
    data = raw

print(f"=== ANALYSE DES {len(data)} POSTS ===\n")

# 1. Distribution des intents
intents = Counter(p.get('intent', 'N/A') for p in data)
print("1. DISTRIBUTION DES INTENTS:")
for intent, count in intents.most_common():
    print(f"   {intent}: {count} ({100*count/len(data):.1f}%)")

# 2. Distribution des scores de pertinence
print("\n2. DISTRIBUTION DES SCORES DE PERTINENCE:")
scores = [p.get('relevance_score', 0) or 0 for p in data]
ranges = [(0, 0.1), (0.1, 0.2), (0.2, 0.3), (0.3, 0.5), (0.5, 1.0)]
for low, high in ranges:
    count = sum(1 for s in scores if low <= s < high)
    print(f"   [{low:.1f}-{high:.1f}): {count} posts")

# 3. Keywords utilisés
print("\n3. KEYWORDS LES PLUS FRÉQUENTS:")
keywords = Counter(p.get('keyword', 'N/A') for p in data)
for kw, count in keywords.most_common(15):
    print(f"   {kw}: {count}")

# 4. Exemples de posts potentiellement hors sujet (intent='autre' ou score bas)
print("\n4. EXEMPLES DE POSTS 'AUTRE' (potentiellement hors sujet):")
autres = [p for p in data if p.get('intent') == 'autre'][:10]
for i, p in enumerate(autres, 1):
    text = (p.get('text') or '')[:200]
    print(f"\n   [{i}] Keyword: {p.get('keyword', 'N/A')}")
    print(f"       Author: {p.get('author', 'N/A')}")
    print(f"       Score: {p.get('relevance_score', 'N/A')}")
    print(f"       Text: {text}...")

# 5. Analyse des posts avec score bas mais intent='recherche_profil'
print("\n\n5. POSTS 'RECHERCHE_PROFIL' AVEC SCORE < 0.3 (faux positifs potentiels):")
low_score_recrut = [p for p in data if p.get('intent') == 'recherche_profil' and (p.get('relevance_score') or 0) < 0.3][:10]
for i, p in enumerate(low_score_recrut, 1):
    text = (p.get('text') or '')[:200]
    print(f"\n   [{i}] Keyword: {p.get('keyword', 'N/A')}")
    print(f"       Author: {p.get('author', 'N/A')}")
    print(f"       Score: {p.get('relevance_score', 'N/A')}")
    print(f"       Text: {text}...")

# 6. Détection de patterns hors sujet
print("\n\n6. DÉTECTION DE PATTERNS HORS SUJET:")
hors_sujet_patterns = [
    "formation", "webinaire", "conférence", "événement", "salon", 
    "article", "publication", "livre", "ouvrage", "interview",
    "félicitations", "anniversaire", "promotion", "nomination",
    "stage", "alternance", "stagiaire", "apprenti",
    "recherche d'emploi", "open to work", "disponible",
    "cabinet de recrutement", "chasseur de têtes"
]

pattern_counts = {}
for pattern in hors_sujet_patterns:
    count = sum(1 for p in data if pattern.lower() in (p.get('text') or '').lower())
    if count > 0:
        pattern_counts[pattern] = count

print("   Patterns détectés dans les posts:")
for pattern, count in sorted(pattern_counts.items(), key=lambda x: -x[1]):
    print(f"   - '{pattern}': {count} posts")

# 7. Posts sans signal de recrutement clair
print("\n\n7. POSTS SANS MOTS-CLÉS DE RECRUTEMENT:")
recruit_keywords = ["recrute", "recrutons", "recherche", "cherchons", "poste", "offre", "cdi", "cdd", "embauche", "hiring"]
no_recruit = []
for p in data:
    text = (p.get('text') or '').lower()
    if not any(kw in text for kw in recruit_keywords):
        no_recruit.append(p)

print(f"   {len(no_recruit)} posts sans mots-clés de recrutement sur {len(data)} ({100*len(no_recruit)/len(data):.1f}%)")
print("\n   Exemples:")
for i, p in enumerate(no_recruit[:5], 1):
    text = (p.get('text') or '')[:150]
    print(f"   [{i}] {text}...")

print("\n=== FIN DE L'ANALYSE ===")
