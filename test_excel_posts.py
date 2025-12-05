"""
Script pour tester le filtre sur un fichier Excel de posts scrapés.

Usage:
    python test_excel_posts.py [chemin_excel]
    
Si aucun chemin n'est fourni, cherche linkedin_posts_*.xlsx dans le répertoire courant.
"""

import sys
import os
import glob

sys.path.insert(0, '.')

# Import du filtre
from scraper.legal_filter import is_legal_job_post, FilterConfig

# Configuration stricte avec les nouveaux flags
config = FilterConfig(
    legal_threshold=0.30,
    recruitment_threshold=0.35,
    exclude_formation_education=True,
    exclude_recrutement_passe=True,
    exclude_candidat_individu=True,
    exclude_contenu_informatif=True,
)

def find_excel_file():
    """Trouve le fichier Excel le plus récent."""
    patterns = [
        "linkedin_posts_*.xlsx",
        "exports/linkedin_posts_*.xlsx",
    ]
    files = []
    for pattern in patterns:
        files.extend(glob.glob(pattern))
    
    if not files:
        return None
    
    # Trier par date de modification (plus récent en premier)
    files.sort(key=os.path.getmtime, reverse=True)
    return files[0]


def main():
    # Déterminer le fichier Excel à utiliser
    if len(sys.argv) > 1:
        excel_file = sys.argv[1]
    else:
        excel_file = find_excel_file()
    
    if not excel_file:
        print("❌ Aucun fichier Excel trouvé.")
        print("Usage: python test_excel_posts.py [chemin_excel]")
        sys.exit(1)
    
    print(f"📁 Fichier: {excel_file}")
    
    # Vérifier que pandas est installé
    try:
        import pandas as pd
    except ImportError:
        print("❌ pandas n'est pas installé. Installez-le avec: pip install pandas openpyxl")
        sys.exit(1)
    
    # Charger l'Excel
    try:
        df = pd.read_excel(excel_file)
    except Exception as e:
        print(f"❌ Erreur lors du chargement: {e}")
        sys.exit(1)
    
    print(f"📊 {len(df)} posts chargés")
    
    # Trouver la colonne de texte
    text_columns = ['Texte', 'text', 'content', 'Content', 'message', 'Message', 'post', 'Post']
    text_col = None
    for col in text_columns:
        if col in df.columns:
            text_col = col
            break
    
    if not text_col:
        print(f"❌ Colonne de texte non trouvée. Colonnes disponibles: {list(df.columns)}")
        sys.exit(1)
    
    print(f"📝 Colonne de texte: {text_col}")
    print(f"\n{'='*80}")
    print("CONFIGURATION DU FILTRE")
    print(f"{'='*80}")
    print(f"  legal_threshold: {config.legal_threshold}")
    print(f"  recruitment_threshold: {config.recruitment_threshold}")
    print(f"  exclude_formation_education: {config.exclude_formation_education}")
    print(f"  exclude_recrutement_passe: {config.exclude_recrutement_passe}")
    print(f"  exclude_candidat_individu: {config.exclude_candidat_individu}")
    print(f"  exclude_contenu_informatif: {config.exclude_contenu_informatif}")
    
    # Tester chaque post
    resultats = []
    raisons_rejet = {}
    
    for idx, row in df.iterrows():
        text = str(row[text_col]) if pd.notna(row[text_col]) else ""
        
        result = is_legal_job_post(text, config=config)
        
        # Collecter les infos de l'auteur/entreprise si disponibles
        auteur = row.get('Auteur', row.get('auteur', row.get('author', 'Inconnu')))
        entreprise = row.get('Entreprise', row.get('entreprise', row.get('company', 'Inconnue')))
        
        resultats.append({
            'index': idx + 1,
            'auteur': auteur,
            'entreprise': entreprise,
            'texte_preview': text[:100] + '...' if len(text) > 100 else text,
            'valide': result.is_valid,
            'raison': result.exclusion_reason if not result.is_valid else "ACCEPTÉ",
            'legal_score': result.legal_score,
            'recruitment_score': result.recruitment_score,
            'target_jobs': result.target_jobs,
        })
        
        # Compter les raisons de rejet
        if not result.is_valid:
            reason = result.exclusion_reason
            raisons_rejet[reason] = raisons_rejet.get(reason, 0) + 1
    
    # Créer un DataFrame des résultats
    df_results = pd.DataFrame(resultats)
    
    # Afficher le résumé
    print(f"\n{'='*80}")
    print("RÉSUMÉ DES RÉSULTATS")
    print(f"{'='*80}")
    
    total = len(df_results)
    acceptes = df_results['valide'].sum()
    rejetes = total - acceptes
    
    print(f"\nTotal posts analysés: {total}")
    print(f"✅ Acceptés: {acceptes} ({100*acceptes//total}%)")
    print(f"❌ Rejetés: {rejetes} ({100*rejetes//total}%)")
    
    # Afficher les raisons de rejet
    print(f"\n{'='*80}")
    print("RAISONS DE REJET (triées par fréquence)")
    print(f"{'='*80}")
    
    for reason, count in sorted(raisons_rejet.items(), key=lambda x: -x[1]):
        pct = 100 * count // total
        print(f"  {reason}: {count} ({pct}%)")
    
    # Afficher les posts acceptés
    print(f"\n{'='*80}")
    print("POSTS ACCEPTÉS")
    print(f"{'='*80}")
    
    for _, row in df_results[df_results['valide']].iterrows():
        print(f"\n✅ POST #{row['index']}")
        print(f"   Auteur: {row['auteur']}")
        print(f"   Entreprise: {row['entreprise']}")
        print(f"   Métiers: {row['target_jobs']}")
        print(f"   Scores: legal={row['legal_score']:.2f}, recruitment={row['recruitment_score']:.2f}")
        print(f"   Aperçu: {row['texte_preview']}")
    
    # Sauvegarder les résultats
    output_file = "test_results.csv"
    df_results.to_csv(output_file, index=False, encoding='utf-8')
    print(f"\n\n📄 Résultats sauvegardés dans {output_file}")
    
    # Statistiques par nouvelle exclusion
    print(f"\n{'='*80}")
    print("IMPACT DES NOUVELLES EXCLUSIONS")
    print(f"{'='*80}")
    
    nouvelles_exclusions = ['formation_education', 'recrutement_passe', 'candidat_individu', 'contenu_informatif']
    for excl in nouvelles_exclusions:
        count = raisons_rejet.get(excl, 0)
        pct = 100 * count // total if total > 0 else 0
        print(f"  {excl}: {count} rejetés ({pct}%)")


if __name__ == "__main__":
    main()
