"""
Test du filtre sur les vrais posts scrapés.
"""

import sys
sys.path.insert(0, '.')

import pandas as pd
from scraper.legal_filter import is_legal_job_post, FilterConfig

# Configuration stricte
config = FilterConfig(
    legal_threshold=0.30,
    recruitment_threshold=0.35,
    exclude_formation_education=True,
    exclude_recrutement_passe=True,
    exclude_candidat_individu=True,
    exclude_contenu_informatif=True,
)

# Charger les posts réels
df = pd.read_excel('linkedin_posts_20251202_160325.xlsx')
print(f"📊 {len(df)} posts chargés depuis linkedin_posts_20251202_160325.xlsx")
print(f"\n{'='*80}")
print("ANALYSE DES POSTS RÉELS")
print(f"{'='*80}")

# Analyser chaque post
resultats = []
raisons_rejet = {}

for idx, row in df.iterrows():
    text = str(row['Texte']) if pd.notna(row['Texte']) else ""
    result = is_legal_job_post(text, config=config, log_exclusions=False)
    
    resultats.append({
        'index': idx + 1,
        'auteur': row['Auteur'],
        'entreprise': row['Entreprise'],
        'statut_original': row['Statut'],
        'metier_original': row['Métier'],
        'texte': text[:200] + '...' if len(text) > 200 else text,
        'valide': result.is_valid,
        'raison': result.exclusion_reason if not result.is_valid else "ACCEPTÉ",
        'legal_score': result.legal_score,
        'recruitment_score': result.recruitment_score,
        'target_jobs': result.target_jobs,
    })
    
    if not result.is_valid:
        reason = result.exclusion_reason
        raisons_rejet[reason] = raisons_rejet.get(reason, 0) + 1

# Résumé
df_results = pd.DataFrame(resultats)
total = len(df_results)
acceptes = df_results['valide'].sum()
rejetes = total - acceptes

print(f"\n📈 RÉSUMÉ GLOBAL")
print(f"   Total posts: {total}")
print(f"   ✅ Acceptés: {acceptes} ({100*acceptes//total}%)")
print(f"   ❌ Rejetés: {rejetes} ({100*rejetes//total}%)")

print(f"\n{'='*80}")
print("RAISONS DE REJET (triées par fréquence)")
print(f"{'='*80}")

for reason, count in sorted(raisons_rejet.items(), key=lambda x: -x[1]):
    pct = 100 * count // total
    bar = "█" * (count * 40 // total)
    print(f"  {reason:35} {count:3} ({pct:2}%) {bar}")

# Posts ACCEPTÉS
print(f"\n{'='*80}")
print(f"✅ POSTS ACCEPTÉS ({acceptes} posts)")
print(f"{'='*80}")

for _, row in df_results[df_results['valide']].iterrows():
    print(f"\n--- POST #{row['index']} ---")
    print(f"   Auteur: {row['auteur']}")
    print(f"   Entreprise: {row['entreprise']}")
    print(f"   Métiers détectés: {row['target_jobs']}")
    print(f"   Scores: legal={row['legal_score']:.2f}, recruitment={row['recruitment_score']:.2f}")
    print(f"   Texte: {row['texte'][:150]}...")

# Posts REJETÉS - échantillon par catégorie
print(f"\n{'='*80}")
print(f"❌ EXEMPLES DE POSTS REJETÉS (par catégorie)")
print(f"{'='*80}")

for reason in sorted(raisons_rejet.keys(), key=lambda x: -raisons_rejet[x]):
    posts_reason = df_results[df_results['raison'] == reason]
    if len(posts_reason) > 0:
        sample = posts_reason.iloc[0]
        print(f"\n--- {reason.upper()} ({raisons_rejet[reason]} posts) ---")
        print(f"   Exemple: {sample['texte'][:120]}...")

# Sauvegarder les résultats détaillés
df_results.to_csv("resultats_test_reel.csv", index=False, encoding='utf-8')
print(f"\n\n📄 Résultats détaillés sauvegardés dans resultats_test_reel.csv")

# Comparaison avec le statut original
print(f"\n{'='*80}")
print("COMPARAISON AVEC LE STATUT ORIGINAL")
print(f"{'='*80}")

# Croiser les résultats
for _, row in df_results.iterrows():
    statut_orig = str(row['statut_original']).lower() if pd.notna(row['statut_original']) else ""
    nouveau_valide = row['valide']
    
    # Vérifier cohérence
    if "valide" in statut_orig or "accepté" in statut_orig:
        original_valide = True
    elif "rejet" in statut_orig or "exclu" in statut_orig:
        original_valide = False
    else:
        continue  # Statut original non déterminé
    
    if original_valide != nouveau_valide:
        if original_valide and not nouveau_valide:
            print(f"\n⚠️ POST #{row['index']} - Était ACCEPTÉ, maintenant REJETÉ")
            print(f"   Raison: {row['raison']}")
            print(f"   Texte: {row['texte'][:100]}...")
