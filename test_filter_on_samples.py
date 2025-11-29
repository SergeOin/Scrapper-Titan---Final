"""Script de test du filtre legal_filter sur des exemples réalistes de posts LinkedIn."""
from scraper.legal_filter import is_legal_job_post
from datetime import datetime, timezone, timedelta

# Exemples réalistes de posts LinkedIn
SAMPLE_POSTS = [
    # === POSTS VALIDES (devraient passer) ===
    {
        "id": "1",
        "text": """🚀 Notre cabinet d'avocats recrute !
        
        Nous recherchons un(e) Avocat(e) Collaborateur(trice) spécialisé(e) en 
        droit des affaires pour rejoindre notre équipe parisienne.
        
        📍 Paris 8ème
        📝 CDI
        💼 3-5 ans d'expérience
        
        Envoyez votre CV ! #recrutement #avocat #droit""",
        "expected": True,
        "description": "Recrutement avocat CDI Paris"
    },
    {
        "id": "2", 
        "text": """💼 OPPORTUNITÉ CDI - JURISTE CORPORATE
        
        Je recrute pour mon équipe un(e) juriste corporate confirmé(e).
        Vous intégrerez la direction juridique d'un groupe international
        basé à La Défense.
        
        Profil recherché :
        - 4/6 ans d'expérience
        - Droit des sociétés / M&A
        - Anglais courant
        
        Intéressé(e) ? Contactez-moi !""",
        "expected": True,
        "description": "Juriste corporate CDI"
    },
    {
        "id": "3",
        "text": """Notre étude notariale recherche un(e) clerc de notaire expérimenté(e).
        
        Poste en CDI à pourvoir dès que possible.
        Basé à Lyon, vous rejoindrez une équipe de 8 personnes.
        
        Rémunération attractive selon profil.""",
        "expected": True,
        "description": "Clerc de notaire CDI Lyon"
    },
    {
        "id": "4",
        "text": """🎯 Nous recrutons un Directeur Juridique !
        
        Pour accompagner notre croissance, nous cherchons notre futur(e) 
        Directeur(trice) Juridique. Poste stratégique, CDI, basé à Bordeaux.
        
        Vous piloterez une équipe de 3 juristes et serez membre du CODIR.""",
        "expected": True,
        "description": "Directeur juridique CDI"
    },
    {
        "id": "5",
        "text": """Rejoignez notre équipe juridique !
        
        Je recherche un(e) paralegal pour notre département M&A.
        CDI - Paris - Démarrage ASAP
        
        Missions : due diligence, closing, corporate housekeeping""",
        "expected": True,
        "description": "Paralegal CDI Paris"
    },
    {
        "id": "6",
        "text": """🔔 Poste à pourvoir : Responsable Juridique
        
        Notre PME en forte croissance recrute son premier Responsable Juridique.
        Contrats, propriété intellectuelle, RGPD seront vos domaines.
        
        CDI - Nantes - 50-60k€""",
        "expected": True,
        "description": "Responsable juridique CDI"
    },
    {
        "id": "7",
        "text": """Nous recrutons ! 🚀
        
        Avocat(e) collaborateur en droit social recherché(e) pour notre 
        cabinet à Marseille. Belle clientèle, ambiance conviviale.
        
        4/7 ans d'expérience minimum. CDD 12 mois renouvelable.""",
        "expected": True,
        "description": "Avocat CDD Marseille"
    },
    
    # === POSTS INVALIDES - STAGE/ALTERNANCE ===
    {
        "id": "10",
        "text": """🎓 OFFRE DE STAGE M2
        
        Notre cabinet recherche un(e) stagiaire pour une durée de 6 mois.
        Stage conventionné, gratification légale.
        
        Domaine : droit social / droit du travail
        Lieu : Lyon 3ème""",
        "expected": False,
        "description": "Stage M2 - exclu"
    },
    {
        "id": "11",
        "text": """Alternance juriste droit des contrats
        
        Nous recrutons un(e) alternant(e) pour 2 ans dans notre 
        direction juridique. Formation Master 2 droit des affaires.""",
        "expected": False,
        "description": "Alternance juriste - exclu"
    },
    {
        "id": "12",
        "text": """Contrat d'apprentissage - Assistant juridique
        
        Notre étude notariale propose un contrat d'apprentissage 
        pour préparer un BTS Notariat.""",
        "expected": False,
        "description": "Apprentissage - exclu"
    },
    
    # === POSTS INVALIDES - FREELANCE ===
    {
        "id": "15",
        "text": """Mission freelance avocat
        
        Recherche avocat freelance pour mission de 3 mois sur un 
        dossier contentieux commercial. TJM à négocier.""",
        "expected": False,
        "description": "Freelance avocat - exclu"
    },
    {
        "id": "16",
        "text": """Juriste en intérim recherché
        
        Mission de 2 mois pour remplacement congé maternité.
        Direction juridique d'un groupe industriel.""",
        "expected": False,
        "description": "Intérim juriste - exclu"
    },
    
    # === POSTS INVALIDES - HORS FRANCE ===
    {
        "id": "20",
        "text": """We are hiring a Legal Counsel in Geneva!
        
        Join our team in Switzerland. CDI position.
        International environment, competitive salary.""",
        "expected": False,
        "description": "Suisse Geneva - exclu"
    },
    {
        "id": "21",
        "text": """Avocat recherché à Montreal
        
        Notre cabinet canadien recrute un avocat en droit des affaires.
        Poste permanent à Montréal, Canada.""",
        "expected": False,
        "description": "Canada Montreal - exclu"
    },
    {
        "id": "22",
        "text": """Legal position in Brussels
        
        Belgian law firm is looking for a corporate lawyer.
        CDI - Belgium - Bilingual FR/EN required.""",
        "expected": False,
        "description": "Belgique Brussels - exclu"
    },
    
    # === POSTS INVALIDES - CHERCHEUR D'EMPLOI ===
    {
        "id": "25",
        "text": """🔍 #OpenToWork
        
        Avocat avec 8 ans d'expérience en droit des affaires,
        je suis à la recherche de nouvelles opportunités.
        
        Disponible immédiatement.
        Mobilité : Paris / Île-de-France""",
        "expected": False,
        "description": "OpenToWork avocat - exclu"
    },
    {
        "id": "26",
        "text": """Juriste en recherche d'emploi
        
        Après 5 ans en entreprise, je cherche un nouveau poste 
        de juriste corporate. Ouvert à toutes propositions.""",
        "expected": False,
        "description": "Chercheur emploi juriste - exclu"
    },
    
    # === POSTS INVALIDES - CONTENU PROMOTIONNEL ===
    {
        "id": "30",
        "text": """📢 Webinaire gratuit !
        
        "Les évolutions du droit du travail en 2024"
        Jeudi 15 janvier à 14h
        
        Avec Me Dupont, avocat spécialisé.
        Inscription gratuite !""",
        "expected": False,
        "description": "Webinaire juridique - exclu"
    },
    {
        "id": "31",
        "text": """🎓 Formation droit des contrats
        
        Nouvelle session de notre formation certifiante.
        2 jours pour maîtriser la rédaction contractuelle.
        
        Juristes, avocats : inscrivez-vous !""",
        "expected": False,
        "description": "Formation juridique - exclu"
    },
    {
        "id": "32",
        "text": """📚 Mon dernier article sur le blog :
        
        "RGPD : 5 ans après, où en sommes-nous ?"
        
        Analyse des évolutions jurisprudentielles et pratiques.
        Lien en commentaire !""",
        "expected": False,
        "description": "Article blog juridique - exclu"
    },
    
    # === POSTS INVALIDES - CABINETS DE RECRUTEMENT ===
    {
        "id": "35",
        "text": """📢 FED LEGAL recrute pour son client !
        
        Cabinet d'avocats d'affaires recherche un Avocat Associé
        en droit bancaire et financier.
        
        Poste basé à Paris - CDI
        Rémunération attractive""",
        "expected": False,
        "description": "Fed Legal cabinet - exclu"
    },
    {
        "id": "36",
        "text": """Michael Page Legal recrute !
        
        Pour notre client, grand groupe du CAC40, nous recherchons 
        un Juriste M&A senior. CDI Paris.""",
        "expected": False,
        "description": "Michael Page - exclu"
    },
    {
        "id": "37",
        "text": """Robert Walters - Offre confidentielle
        
        Notre client recherche un Directeur Juridique.
        Société confidentielle, secteur luxe.
        
        Contactez-nous pour plus d'infos !""",
        "expected": False,
        "description": "Robert Walters - exclu"
    },
    {
        "id": "38",
        "text": """Hays Legal vous propose :
        
        Poste de juriste contentieux pour un de nos clients.
        CDI - Lyon - 45-55k€""",
        "expected": False,
        "description": "Hays cabinet - exclu"
    },
    
    # === POSTS INVALIDES - MÉTIERS NON JURIDIQUES ===
    {
        "id": "40",
        "text": """🚀 Nous recrutons un Responsable Marketing !
        
        CDI - Paris - Secteur LegalTech
        
        Vous piloterez notre stratégie marketing digital.""",
        "expected": False,
        "description": "Marketing LegalTech - exclu"
    },
    {
        "id": "41",
        "text": """Directeur Financier recherché
        
        Notre cabinet d'avocats recrute son DAF.
        CDI - Paris 8ème
        
        Gestion comptable, reporting, trésorerie.""",
        "expected": False,
        "description": "DAF cabinet avocats - exclu"
    },
    {
        "id": "42",
        "text": """Office Manager H/F - CDI
        
        Cabinet d'avocats parisien recherche son Office Manager.
        Gestion administrative, accueil, organisation.""",
        "expected": False,
        "description": "Office Manager - exclu"
    },
    {
        "id": "43",
        "text": """Data Analyst Legal Tech
        
        Nous recrutons un Data Analyst pour notre équipe.
        CDI - Full remote possible.""",
        "expected": False,
        "description": "Data Analyst - exclu"
    },
    
    # === POSTS INVALIDES - SCORE INSUFFISANT ===
    {
        "id": "50",
        "text": """Belle journée au tribunal aujourd'hui !
        
        L'audience s'est bien passée. Victoire pour notre client !
        #avocat #droit""",
        "expected": False,
        "description": "Post informatif sans recrutement - exclu"
    },
    {
        "id": "51",
        "text": """Notre équipe juridique compte maintenant 5 personnes.
        
        Merci à tous pour votre engagement !""",
        "expected": False,
        "description": "Post interne sans offre - exclu"
    },
]

def run_analysis():
    """Analyse tous les posts et affiche les résultats."""
    print("="*80)
    print("ANALYSE DES POSTS LINKEDIN AVEC LE FILTRE legal_filter")
    print("="*80)
    
    correct = 0
    incorrect = 0
    
    results_valid = []
    results_invalid = []
    results_errors = []
    
    for post in SAMPLE_POSTS:
        result = is_legal_job_post(post["text"], log_exclusions=False)
        
        is_correct = result.is_valid == post["expected"]
        if is_correct:
            correct += 1
        else:
            incorrect += 1
            results_errors.append({
                "post": post,
                "result": result
            })
        
        if result.is_valid:
            results_valid.append({"post": post, "result": result})
        else:
            results_invalid.append({"post": post, "result": result})
    
    # Résumé
    print(f"\n📊 RÉSUMÉ")
    print("-"*40)
    print(f"Total posts testés: {len(SAMPLE_POSTS)}")
    print(f"✅ Prédictions correctes: {correct}")
    print(f"❌ Prédictions incorrectes: {incorrect}")
    print(f"📈 Précision: {correct/len(SAMPLE_POSTS)*100:.1f}%")
    
    # Posts valides
    print(f"\n\n{'='*80}")
    print(f"✅ POSTS VALIDES ({len(results_valid)})")
    print("="*80)
    for item in results_valid:
        post = item["post"]
        result = item["result"]
        status = "✓" if post["expected"] == True else "✗ ERREUR"
        print(f"\n{status} [{post['id']}] {post['description']}")
        print(f"   Legal: {result.legal_score:.2f} | Recruit: {result.recruitment_score:.2f}")
        print(f"   Professions: {result.matched_professions[:3]}")
        print(f"   Signaux: {result.matched_signals[:3]}")
    
    # Posts invalides
    print(f"\n\n{'='*80}")
    print(f"❌ POSTS INVALIDES ({len(results_invalid)})")
    print("="*80)
    for item in results_invalid:
        post = item["post"]
        result = item["result"]
        status = "✓" if post["expected"] == False else "✗ ERREUR"
        print(f"\n{status} [{post['id']}] {post['description']}")
        print(f"   Raison d'exclusion: {result.exclusion_reason}")
        if result.exclusion_terms:
            print(f"   Termes détectés: {result.exclusion_terms}")
    
    # Erreurs de prédiction
    if results_errors:
        print(f"\n\n{'='*80}")
        print(f"⚠️  ERREURS DE PRÉDICTION ({len(results_errors)})")
        print("="*80)
        for item in results_errors:
            post = item["post"]
            result = item["result"]
            print(f"\n[{post['id']}] {post['description']}")
            print(f"   Attendu: {'VALIDE' if post['expected'] else 'INVALIDE'}")
            print(f"   Obtenu: {'VALIDE' if result.is_valid else 'INVALIDE'}")
            print(f"   Raison: {result.exclusion_reason}")
            print(f"   Scores: legal={result.legal_score:.2f}, recruit={result.recruitment_score:.2f}")
            print(f"   Texte: {post['text'][:100]}...")
    
    return correct, incorrect

if __name__ == "__main__":
    run_analysis()
