#!/usr/bin/env python3
"""Analyse des posts actuellement scrappés."""

from scraper import is_legal_job_post, FilterSessionStats

# Posts fournis par l'utilisateur
posts_data = [
    {"keyword": "cabinet avocat recrute", "author": "Zarine Ghazaryan", "text": "After reading this incredible article about the health risks of these German spa towns, the choice is quickly made for spa lovers: Long live the French Pyrenees."},
    {"keyword": "cabinet avocat recrute", "author": "Sarah DIANKEBA", "text": "#LinkedInTopCompanies #LinkedInActualités"},
    {"keyword": "poste avocat France", "author": "Avocats Sans Frontières France", "text": "📌OFFRE DE RECRUTEMENT - Chef/fe de projet Samos Legal Centre Nous recherchons un ou une Chef/fe de projet pour assurer la coordination du projet Samos Legal Centre, en Grèce"},
    {"keyword": "poste avocat France", "author": "Mathias CURNIER", "text": "Nouveaux défis! Très heureux d'annoncer mon arrivée au Cabinet d'Avocats Vey & Associés au poste nouvellement créée de Directeur de la Stratégie Communication"},
    {"keyword": "entreprise recrute juriste", "author": "Angélique M.", "text": "🚀 Atradius France recrute ! Plusieurs opportunités à saisir ! Nous recherchons en CDI: Juriste Recouvrement / Compiègne"},
    {"keyword": "entreprise recrute juriste", "author": "Hayet BAKHTAR", "text": "🚡 POMA recrute un.e Juriste (H/F) pour accompagner l'Entreprise sur les questions de droit public et de droit des affaires. CDI basé à Voreppe"},
    {"keyword": "recrute avocat France", "author": "Law Profiler", "text": "Aramis Law Firm recrute 2 Avocat(e)s collaborateurs(trices) - Paris 9 : AVOCAT(E) COLLABORATEUR(TRICE) - TECH&DATA"},
    {"keyword": "recrute avocat France", "author": "Jean-Marie Bellew", "text": "ZORÏN recrute : Dans le cadre de notre développement, le cabinet ZORÏN recherche H/F possédant un très bon relationnel"},
    {"keyword": "recrute avocat France", "author": "Le Monde du Droit", "text": "Eversheds Sutherland France recrute Anne-Marie Lacoste pour se renforcer en arbitrage international #avocats"},
    {"keyword": "direction juridique recrute", "author": "Gaëlle Roger-Dalbert", "text": "💧 Veolia Franciliane recrute un(e) juriste confirmé(e) - responsabilité, contrats et construction CDI"},
    {"keyword": "direction juridique recrute", "author": "EG Retail France SAS", "text": "🔎 Nous recrutons ! La Direction Juridique recherche son/sa futur(e) Juriste en Droit des Affaires pour un CDD de 6 mois"},
    {"keyword": "direction juridique recrute", "author": "Pierre-Adrien Blanchard", "text": "💧 La Direction juridique de Veolia Eau France recrute un(e) juriste confirmé(e) en droit privé. CDI"},
    {"keyword": "direction juridique recrute", "author": "Hal Scott Davis", "text": "🇫🇷 see the light offres LIGHT Consultants"},
    {"keyword": "direction juridique recrute", "author": "Cyrille Raymond", "text": "#job Vous êtes expert(e) en montage de projets européens ? La Direction d'ingénierie de Projets recrute : un(e) ingénieur(e) projets expérimenté(e) - Spécialiste Erasmus Mundus"},
    {"keyword": "recrute juriste France", "author": "Emplois & Bourses", "text": "Action contre la Faim recherche un Juriste - Droit social (H/F), France"},
    {"keyword": "recrute juriste France", "author": "Emplois & Bourses", "text": "Médecins du Monde recrute un Juriste en droit social (F/H), Saint-Denis, France"},
    {"keyword": "responsable juridique France", "author": "Hélène Maizeroi Eugene", "text": "🚨 We're hiring a Head of Legal & Compliance for an international non-profit! Location: France, Belgium, Germany 100% remote"},
    {"keyword": "responsable juridique France", "author": "Caterina C.", "text": "My team at Data4 is growing and I'm currently looking for a Senior Legal Counsel/Legal Manager (Contracts) to join us!"},
    {"keyword": "responsable juridique France", "author": "Dentons", "text": "Découvrez l'interview réalisée par Global Investigations Review avec Joydeep Sengupta, associé chargé de la conformité chez Dentons"},
    {"keyword": "poste juriste France", "author": "Concours Jean-Pictet", "text": "Rencontrez David Kootz – Membre du Comité du Concours Jean-Pictet juriste et professionnel humanitaire chevronné"},
    {"keyword": "poste juriste France", "author": "Ekomind", "text": "📣 Ca recrute par ici ! Juriste Legal Ops - Dipeeo"},
    {"keyword": "poste juriste France", "author": "Recruter - Jobs", "text": "🚨Un #JAIME peut aider plusieurs personnes. 📢 COMAR recrute des Juriste"},
    {"keyword": "poste juriste France", "author": "Mehdi Taboulot", "text": "DATA4 recrute ! Juriste senior droit des contrats (Paris) - Responsable juridique compliance (Paris)"},
    {"keyword": "etude notariale recrute", "author": "NCE Notaires", "text": "💼 OFFRE DU JOUR | CDI - Ingénieur Patrimonial Junior CHOLET - NEOLIA NOTAIRES"},
    {"keyword": "etude notariale recrute", "author": "Marianne Genévrier", "text": "Le Notaire à la recherche du candidat idéal. Réflexions et conseils pour lutter contre le mercato actuel"},
    {"keyword": "etude notariale recrute", "author": "C B Martinot", "text": "#recrute Administration Commercial Communication, Création Direction d'Entreprise"},
    {"keyword": "etude notariale recrute", "author": "Marianne Genévrier", "text": "🔵 Le recrutement des Office managers s'intensifie progressivement dans le Notariat"},
    {"keyword": "etude notariale recrute", "author": "LexGO.be", "text": "Étude notariale Anne-France Hames recrute un juriste généraliste. Gérez des dossiers immobiliers et familiaux"},
    {"keyword": "cdi avocat Paris", "author": "Law Profiler", "text": "DEHENG SHI CHEN ASSOCIES Paris CDI - ASSISTANT(E) JURIDIQUE - H/F"},
    {"keyword": "cdi juriste Paris", "author": "Olivier Beuchet", "text": "!! RECAP JOBS DU MOMENT !! Salut les juristes, les fiscalistes, les notaires. CDI région parisienne"},
    {"keyword": "cdi juriste Paris", "author": "Mory Kadoch", "text": "Charles Gautier cherche un premier poste en CDD/CDI en droit fiscal des affaires"},
    {"keyword": "cdi juriste Paris", "author": "EvalCommunity Jobs", "text": "Explore 300 exciting career opportunities in Monitoring & Evaluation and International Development"},
    {"keyword": "cdi juriste Paris", "author": "Law Profiler", "text": "DEHENG - SHI & CHEN ASSOCIÉS Paris CDI - ASSISTANT(E) JURIDIQUE"},
    {"keyword": "cdi juriste Paris", "author": "EUSupplyChainJobs", "text": "Several Supply Chain Jobs in EU. Acheteur juriste expérimenté en droit public des affaires"},
]

def main():
    print("\n" + "=" * 100)
    print("📊 ANALYSE DE PERTINENCE DES 34 POSTS SCRAPPÉS")
    print("=" * 100)
    
    stats = FilterSessionStats()
    valid_posts = []
    invalid_posts = []
    
    for i, post in enumerate(posts_data, 1):
        result = is_legal_job_post(post["text"], log_exclusions=False)
        stats.record_result(result)
        
        post_info = {
            "num": i,
            "keyword": post["keyword"],
            "author": post["author"],
            "text_preview": post["text"][:100],
            "recruitment_score": result.recruitment_score,
            "legal_score": result.legal_score,
            "exclusion_reason": result.exclusion_reason,
            "is_valid": result.is_valid,
        }
        
        if result.is_valid:
            valid_posts.append(post_info)
        else:
            invalid_posts.append(post_info)
    
    # Posts VALIDES
    print(f"\n✅ POSTS VALIDES ({len(valid_posts)}/{len(posts_data)}) - À CONSERVER")
    print("-" * 100)
    for p in valid_posts:
        print(f"#{p['num']:2d} | {p['author'][:25]:<25} | rec={p['recruitment_score']:.2f} leg={p['legal_score']:.2f} | {p['keyword']}")
    
    # Posts INVALIDES
    print(f"\n\n❌ POSTS INVALIDES ({len(invalid_posts)}/{len(posts_data)}) - À EXCLURE")
    print("-" * 100)
    for p in invalid_posts:
        print(f"#{p['num']:2d} | {p['author'][:25]:<25} | {p['exclusion_reason']:<35} | {p['keyword']}")
        print(f"     Texte: {p['text_preview'][:80]}...")
    
    # Résumé
    print("\n\n" + "=" * 100)
    print(stats.summary())
    
    # Analyse par catégorie d'exclusion
    print("\n\n📈 DÉTAIL DES PROBLÈMES")
    print("-" * 50)
    details = stats.to_dict()
    
    problems = []
    if details['rejections']['stage_alternance'] > 0:
        problems.append(f"  ⚠️  Stages/alternances: {details['rejections']['stage_alternance']}")
    if details['rejections']['freelance'] > 0:
        problems.append(f"  ⚠️  Freelance: {details['rejections']['freelance']}")
    if details['rejections']['opentowork'] > 0:
        problems.append(f"  ⚠️  Chercheurs d'emploi: {details['rejections']['opentowork']}")
    if details['rejections']['promotional'] > 0:
        problems.append(f"  ⚠️  Contenu promotionnel: {details['rejections']['promotional']}")
    if details['rejections']['agencies'] > 0:
        problems.append(f"  ⚠️  Cabinets recrutement: {details['rejections']['agencies']}")
    if details['rejections']['foreign'] > 0:
        problems.append(f"  ⚠️  Hors France: {details['rejections']['foreign']}")
    if details['rejections']['non_legal'] > 0:
        problems.append(f"  ⚠️  Métiers non-juridiques: {details['rejections']['non_legal']}")
    if details['rejections']['low_recruitment_score'] > 0:
        problems.append(f"  ⚠️  Score recrutement insuffisant: {details['rejections']['low_recruitment_score']}")
    if details['rejections']['low_legal_score'] > 0:
        problems.append(f"  ⚠️  Score juridique insuffisant: {details['rejections']['low_legal_score']}")
    
    if problems:
        for p in problems:
            print(p)
    else:
        print("  ✅ Aucun problème majeur détecté")
    
    print(f"\n\n🎯 CONCLUSION")
    print("-" * 50)
    print(f"  Taux de pertinence actuel: {details['acceptance_rate_percent']:.1f}%")
    if details['acceptance_rate_percent'] < 50:
        print(f"  ⚠️  Le filtre devrait exclure {len(invalid_posts)} posts non pertinents")
    else:
        print(f"  ✅ La majorité des posts sont pertinents")

if __name__ == "__main__":
    main()
