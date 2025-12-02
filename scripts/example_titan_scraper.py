#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script d'exemple pour le scraper LinkedIn Titan Partners.

Ce script démontre comment utiliser les différents modules du scraper:
1. Configuration des filtres juridiques
2. Analyse de posts LinkedIn
3. Collecte de statistiques
4. Export des résultats

EXECUTION:
    python scripts/example_titan_scraper.py

ENVIRONNEMENT:
    Assurez-vous que storage_state.json existe avec une session LinkedIn valide.
"""
from __future__ import annotations

import asyncio
import json
import sys
import io
from datetime import datetime, timezone
from pathlib import Path

# Force UTF-8 output for Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Ajouter le répertoire racine au path
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))

# Imports du scraper
from scraper import (
    is_legal_job_post,
    FilterConfig,
    FilterResult,
    classify_legal_post,
)
from scraper.linkedin import (
    LinkedInPostAnalyzer,
    AuthorType,
    PostRelevance,
    is_relevant_for_titan,
    get_post_summary,
)
from scraper.stats import ScraperStats, log_filtering_decision
from filters.juridique import get_default_config, JuridiqueConfig


def demo_filter_posts():
    """Démonstration du filtrage de posts."""
    print("\n" + "=" * 70)
    print("DÉMONSTRATION DU FILTRAGE TITAN PARTNERS")
    print("=" * 70)
    
    # Exemples de posts à analyser
    test_posts = [
        # Post PERTINENT: Recrutement interne juridique
        {
            "text": """🚀 Nous recrutons un(e) Juriste Droit Social en CDI à Paris !
            
            Notre direction juridique recherche un profil confirmé (3-5 ans) 
            pour renforcer notre équipe. Vous interviendrez sur le conseil 
            aux opérationnels et la gestion du contentieux prud'homal.
            
            Envoyez votre CV à recrutement@societe-exemple.fr
            #recrutement #juridique #CDI #Paris""",
            "author": "Société Exemple",
            "author_profile": "https://linkedin.com/company/societe-exemple",
        },
        
        # Post EXCLU: Agence de recrutement
        {
            "text": """🔍 Pour l'un de nos clients, nous recherchons un Avocat 
            Collaborateur en droit des affaires (M&A). Notre client est un cabinet 
            d'avocats international basé à Paris.
            
            Contactez notre équipe pour plus d'informations.
            #hiring #avocat #Paris""",
            "author": "Michael Page Legal",
            "author_profile": "https://linkedin.com/company/michael-page",
        },
        
        # Post EXCLU: Stage
        {
            "text": """📢 Offre de stage - Juriste Junior
            
            Notre cabinet recherche un(e) stagiaire pour une durée de 6 mois 
            à compter de septembre 2025. Vous êtes étudiant en M2 Droit des 
            affaires, rejoignez-nous !
            
            #stage #alternance #juridique""",
            "author": "Cabinet ABC",
            "author_profile": "https://linkedin.com/company/cabinet-abc",
        },
        
        # Post PERTINENT: Compliance Officer
        {
            "text": """Recrutement : Compliance Officer / Responsable Conformité
            
            Notre groupe recrute son/sa futur(e) Compliance Officer pour piloter 
            la conformité réglementaire (RGPD, LCB-FT, Sapin 2). Poste en CDI 
            basé à Lyon, rattaché à la Direction Juridique.
            
            Expérience min 5 ans. Postulez directement sur notre site carrières.
            #compliance #CDI #Lyon #juridique""",
            "author": "Groupe XYZ",
            "author_profile": "https://linkedin.com/company/groupe-xyz",
        },
        
        # Post EXCLU: Article/Veille juridique (pas de recrutement)
        {
            "text": """📚 Nouvelle jurisprudence importante : la Cour de Cassation 
            vient de trancher sur la question du télétravail et du droit à la 
            déconnexion. Notre analyse complète dans cet article.
            
            #droitsocial #jurisprudence #veille""",
            "author": "Cabinet Juridique Conseil",
            "author_profile": "https://linkedin.com/company/cabinet-conseil",
        },
        
        # Post EXCLU: Hors France
        {
            "text": """We are hiring a Legal Counsel for our Zurich office!
            
            Join our legal team in Switzerland. You will handle corporate matters 
            and M&A transactions for our German-speaking clients.
            
            #hiring #legal #Zurich #Switzerland""",
            "author": "International Law Firm",
            "author_profile": "https://linkedin.com/company/intl-firm",
        },
        
        # Post PERTINENT: Notaire
        {
            "text": """🏛️ Notre étude notariale recrute un(e) Notaire Salarié(e)
            
            Étude bien implantée à Bordeaux (33), nous recherchons un confrère/
            une consœur pour développer notre activité immobilière et droit 
            de la famille. Poste en CDI, rémunération attractive.
            
            Contact : etude@notaire-bordeaux.fr
            #notaire #Bordeaux #recrutement""",
            "author": "Étude Notariale Dupont",
            "author_profile": "https://linkedin.com/company/etude-dupont",
        },
    ]
    
    # Créer l'analyseur et les stats
    analyzer = LinkedInPostAnalyzer()
    stats = ScraperStats(session_name="demo_titan")
    
    print("\n📋 Analyse de {} posts de test:\n".format(len(test_posts)))
    
    for i, post in enumerate(test_posts, 1):
        print(f"\n--- Post #{i} ---")
        print(f"Auteur: {post['author']}")
        print(f"Texte (aperçu): {post['text'][:100]}...")
        
        # Enregistrer le post trouvé
        stats.record_post_found("demo_keyword")
        
        # Analyser avec LinkedInPostAnalyzer
        result = analyzer.analyze_post(
            text=post["text"],
            author=post["author"],
            author_profile=post.get("author_profile"),
            post_date=datetime.now(timezone.utc)
        )
        
        # Afficher le résumé
        print(get_post_summary(result))
        
        # Enregistrer dans les stats
        if result.is_excluded:
            stats.record_post_filtered(
                keyword="demo_keyword",
                reason=result.exclusion_reason,
                terms_found=result.exclusion_terms,
                author=post["author"],
                text_preview=post["text"][:100]
            )
        else:
            stats.record_post_accepted(
                keyword="demo_keyword",
                score=result.relevance_score,
                legal_keywords=result.legal_keywords_found,
                recruitment_signals=result.recruitment_signals_found,
                author=post["author"],
                text_preview=post["text"][:100]
            )
    
    # Afficher le résumé des stats
    print("\n")
    stats.print_summary()
    
    return stats


def demo_filter_config():
    """Démonstration de la configuration des filtres."""
    print("\n" + "=" * 70)
    print("CONFIGURATION DES FILTRES JURIDIQUES")
    print("=" * 70)
    
    # Configuration par défaut
    config = get_default_config()
    
    print("\n📌 Configuration par défaut:")
    print(f"  - Seuil recrutement: {config.min_recruitment_score}")
    print(f"  - Seuil juridique: {config.min_legal_score}")
    print(f"  - Exclure stages: {config.exclude_stage_alternance}")
    print(f"  - Exclure agences: {config.exclude_agencies}")
    print(f"  - Exclure hors France: {config.exclude_foreign}")
    print(f"  - Âge max posts: {config.max_post_age_days} jours")
    
    print(f"\n📝 Nombre de rôles juridiques configurés: {len(config.legal_roles)}")
    print(f"   Exemples: {config.legal_roles[:5]}...")
    
    print(f"\n📝 Nombre de signaux de recrutement: {len(config.recruitment_signals)}")
    print(f"   Exemples: {config.recruitment_signals[:5]}...")
    
    print(f"\n🚫 Nombre de patterns d'agence à exclure: {len(config.agency_patterns)}")
    print(f"   Exemples: {config.agency_patterns[:5]}...")
    
    # Exemple d'extension
    print("\n✨ Extension de la config:")
    config.add_legal_role("chief compliance officer")
    config.add_recruitment_signal("hiring immediately")
    config.add_agency_pattern("nouveau cabinet recrutement")
    print("   - Ajouté: 'chief compliance officer' aux rôles")
    print("   - Ajouté: 'hiring immediately' aux signaux")
    print("   - Ajouté: 'nouveau cabinet recrutement' aux exclusions")


def demo_legal_classifier():
    """Démonstration du classificateur légal."""
    print("\n" + "=" * 70)
    print("CLASSIFICATION DES POSTS (INTENT)")
    print("=" * 70)
    
    texts = [
        "Nous recrutons un juriste droit social pour notre équipe à Paris. CDI.",
        "Superbe article sur la réforme du droit du travail. À lire absolument !",
        "Pour notre client, cabinet d'avocats, nous recherchons un avocat M&A.",
        "Stage 6 mois - Juriste junior - Alternance possible",
    ]
    
    print("\nClassification des intentions:\n")
    
    for text in texts:
        result = classify_legal_post(text, language="fr")
        intent_emoji = "✅" if result.intent == "recherche_profil" else "❌"
        print(f"{intent_emoji} Intent: {result.intent}")
        print(f"   Score: {result.relevance_score:.2f}, Confiance: {result.confidence:.0%}")
        print(f"   Mots-clés: {result.keywords_matched[:3]}")
        print(f"   Location OK: {result.location_ok}")
        print(f"   Texte: {text[:60]}...")
        print()


def demo_quick_filter():
    """Démonstration du filtre rapide is_legal_job_post."""
    print("\n" + "=" * 70)
    print("FILTRE RAPIDE is_legal_job_post()")
    print("=" * 70)
    
    # Configuration personnalisée (plus stricte)
    config = FilterConfig(
        recruitment_threshold=0.20,
        legal_threshold=0.25,
        exclude_stage=True,
        exclude_agencies=True,
        verbose=False  # Pas de logs
    )
    
    texts = [
        "Notre cabinet recrute un avocat collaborateur en CDI à Paris.",
        "Séminaire gratuit : les nouvelles obligations RGPD",
        "Je suis juriste et recherche un nouveau poste #opentowork",
        "Responsable juridique recherché(e) pour notre direction - Lyon",
    ]
    
    print("\nTests avec config stricte (recruit=0.20, legal=0.25):\n")
    
    for text in texts:
        result: FilterResult = is_legal_job_post(
            text=text,
            config=config,
            log_exclusions=False
        )
        
        status = "✅ VALIDE" if result.is_valid else "❌ EXCLU"
        print(f"{status}")
        print(f"   Recruit: {result.recruitment_score:.2f}, Legal: {result.legal_score:.2f}")
        if not result.is_valid:
            print(f"   Raison: {result.exclusion_reason}")
        print(f"   Texte: {text[:50]}...")
        print()


def main():
    """Point d'entrée principal."""
    print("\n" + "🎯" * 35)
    print("TITAN PARTNERS - SCRAPER LINKEDIN JURIDIQUE")
    print("🎯" * 35)
    print("\nCe script démontre les capacités du scraper pour collecter")
    print("des posts de recrutement juridique pertinents.\n")
    
    # Démos
    demo_filter_config()
    demo_legal_classifier()
    demo_quick_filter()
    stats = demo_filter_posts()
    
    # Sauvegarder le rapport
    print("\n" + "=" * 70)
    print("EXPORT DU RAPPORT")
    print("=" * 70)
    
    report = stats.generate_report()
    print(f"\n📊 Rapport de session:")
    print(f"   Posts trouvés: {report.total_posts_found}")
    print(f"   Posts acceptés: {report.total_posts_accepted}")
    print(f"   Posts filtrés: {report.total_posts_filtered}")
    print(f"   Taux d'acceptation: {report.acceptance_rate:.0%}")
    print(f"   Score moyen: {report.avg_relevance_score:.2f}")
    
    # Sauvegarder en JSON
    export_path = ROOT_DIR / "exports" / "demo_report.json"
    export_path.parent.mkdir(exist_ok=True)
    with open(export_path, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
    print(f"\n📄 Rapport exporté: {export_path}")
    
    print("\n" + "=" * 70)
    print("✅ DÉMONSTRATION TERMINÉE")
    print("=" * 70)
    print("\nPour lancer le scraper complet:")
    print("  python entrypoint.py")
    print("\nOu via le serveur web:")
    print("  python scripts/dev_server.py")
    print()


if __name__ == "__main__":
    main()
