#!/usr/bin/env python3
"""Analyse l'état du scraper et diagnostique les problèmes potentiels."""

import sqlite3
import os
from datetime import datetime, timedelta

DB_PATH = "fallback.sqlite3"

def analyze_database():
    """Analyse l'état de la base de données."""
    print("=" * 60)
    print("ANALYSE DE L'ÉTAT DU SCRAPER")
    print("=" * 60)
    
    if not os.path.exists(DB_PATH):
        print(f"❌ Base de données non trouvée: {DB_PATH}")
        return
    
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # Stats générales
    cur.execute("SELECT COUNT(*) FROM posts")
    total = cur.fetchone()[0]
    print(f"\n📊 STATISTIQUES GÉNÉRALES:")
    print(f"   Total posts en base: {total}")
    
    # Posts récents (utiliser collected_at)
    cur.execute("SELECT COUNT(*) FROM posts WHERE collected_at > datetime('now', '-1 hour')")
    last_hour = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM posts WHERE collected_at > datetime('now', '-10 minutes')")
    last_10min = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM posts WHERE collected_at > datetime('now', '-1 day')")
    last_day = cur.fetchone()[0]
    
    print(f"   Posts dernières 10 min: {last_10min}")
    print(f"   Posts dernière heure: {last_hour}")
    print(f"   Posts dernier jour: {last_day}")
    
    # Dernier post ajouté
    cur.execute("SELECT collected_at, SUBSTR(text, 1, 100) FROM posts ORDER BY collected_at DESC LIMIT 1")
    row = cur.fetchone()
    if row:
        print(f"\n📝 DERNIER POST:")
        print(f"   Date: {row[0]}")
        print(f"   Aperçu: {row[1]}...")
    
    # Analyse des rejets possibles (posts sans contenu juridique)
    print(f"\n🔍 ANALYSE DU FILTRAGE JURIDIQUE:")
    
    # Compter les posts avec mots-clés juridiques
    legal_keywords = ['avocat', 'juriste', 'juridique', 'notaire', 'droit', 'contrat', 'CDI', 'CDD', 
                      'recrute', 'recrutement', 'poste', 'embauche', 'opportunité']
    
    for kw in ['avocat', 'juriste', 'juridique', 'recrute', 'CDI', 'CDD']:
        cur.execute(f"SELECT COUNT(*) FROM posts WHERE LOWER(text) LIKE ?", (f'%{kw.lower()}%',))
        count = cur.fetchone()[0]
        print(f"   Posts contenant '{kw}': {count}")
    
    # Vérifier si le filtre est trop strict
    print(f"\n⚙️ TEST DU FILTRE ACTUEL:")
    
    # Récupérer les 10 derniers posts pour test
    cur.execute("SELECT id, text FROM posts ORDER BY collected_at DESC LIMIT 10")
    recent_posts = cur.fetchall()
    
    conn.close()
    
    # Tester le filtre sur ces posts
    try:
        from scraper.legal_filter import is_legal_job_post, FilterConfig
        
        config = FilterConfig()
        passed = 0
        failed = 0
        
        print(f"\n   Test sur les {len(recent_posts)} derniers posts:")
        for post_id, text in recent_posts:
            if not text:
                print(f"   ⚠️ Post {post_id}: contenu vide")
                continue
            result = is_legal_job_post(text, config=config)
            if result.is_valid:
                passed += 1
                status = "✅"
            else:
                failed += 1
                status = "❌"
            
            preview = text[:60].replace('\n', ' ') if text else "N/A"
            print(f"   {status} Post {post_id}: {preview}...")
            if not result.is_valid:
                reason = result.get_rejection_reason() if hasattr(result, 'get_rejection_reason') else result.exclusion_reason
                print(f"      Raison: {reason}")
        
        print(f"\n   📈 Résultat: {passed}/{len(recent_posts)} posts passent le filtre")
        
        if passed == 0 and len(recent_posts) > 0:
            print("\n   ⚠️ ATTENTION: Aucun post ne passe le filtre!")
            print("   Le filtre est peut-être trop strict.")
            
            # Analyser les raisons de rejet
            print("\n   📋 ANALYSE DÉTAILLÉE DES REJETS:")
            for post_id, text in recent_posts[:3]:
                if not text:
                    continue
                print(f"\n   --- Post {post_id} ---")
                result = is_legal_job_post(text, config=config)
                print(f"   Score légal: {result.legal_score:.2f}")
                print(f"   Score recrutement: {result.recruitment_score:.2f}")
                print(f"   Agence de recrutement: {result.is_agency}")
                reason = result.get_rejection_reason() if hasattr(result, 'get_rejection_reason') else result.exclusion_reason
                print(f"   Raison rejet: {reason}")
                
    except Exception as e:
        print(f"   ❌ Erreur lors du test du filtre: {e}")
        import traceback
        traceback.print_exc()

def check_scraper_process():
    """Vérifie si le scraper tourne."""
    print(f"\n🔄 PROCESSUS SCRAPER:")
    try:
        import subprocess
        result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq python.exe'], 
                              capture_output=True, text=True)
        if 'python.exe' in result.stdout:
            print("   ✅ Python est en cours d'exécution")
        else:
            print("   ❌ Aucun processus Python détecté")
    except Exception as e:
        print(f"   ❓ Impossible de vérifier: {e}")

def check_session():
    """Vérifie l'état de la session LinkedIn."""
    print(f"\n🔐 SESSION LINKEDIN:")
    if os.path.exists("storage_state.json"):
        stat = os.stat("storage_state.json")
        mod_time = datetime.fromtimestamp(stat.st_mtime)
        age = datetime.now() - mod_time
        print(f"   Fichier session: storage_state.json")
        print(f"   Dernière modification: {mod_time}")
        print(f"   Âge: {age}")
        if age > timedelta(hours=24):
            print("   ⚠️ Session peut-être expirée (> 24h)")
    else:
        print("   ❌ Pas de fichier de session trouvé")

if __name__ == "__main__":
    analyze_database()
    check_scraper_process()
    check_session()
    print("\n" + "=" * 60)
