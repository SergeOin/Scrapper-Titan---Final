"""Analyse des 58 posts fournis par l'utilisateur avec le filtre legal_filter."""
from scraper.legal_filter import is_legal_job_post
from collections import Counter

# Les 58 posts fournis (texte principal extrait)
POSTS = [
    {"id": 1, "keyword": "cdi avocat Paris", "author": "Law Profiler", "text": "DEHENG SHI CHEN ASSOCIES Paris Beijing CDI - ASSISTANT(E) JURIDIQUE - H/F - REMUNERATION SELON PROFIL. ASAP PRESENTATION DE L'ENTREPRISE : DEHENG - SHI & CHEN ASSOCIES est un cabinet d'avocats specialise en droit des affaires ayant, en plus la clientele francaise, une importante clientele en provenance de l'Asie. DESCRIPTIF DE L'OFFRE Assistant juridique - H/F Le Cabinet d'avocats DEHENG - SHI & CHEN ASSOCIES, sis a Paris 17eme et specialise en droit des affaires, recherche un(e) assitant(e) juridique. Missions principales : Support administratif.. Formalites aupres des tribunaux ou sur l'INPI Suivi de la facturation Poste en CDI a temps plein"},
    {"id": 2, "keyword": "recrute juriste France", "author": "Emplois & Bourses", "text": "Action contre la Faim recherche un Juriste - Droit social (H/F), France"},
    {"id": 3, "keyword": "recrute juriste France", "author": "Emplois & Bourses", "text": "Medecins du Monde recrute un Juriste en droit social (F/H), Saint-Denis, France Plus de details ici"},
    {"id": 4, "keyword": "direction juridique recrute", "author": "Gaelle Roger-Dalbert", "text": "Veolia Franciliane recrute un(e) juriste confirme(e) - responsabilite, contrats et construction Vous souhaitez mettre vos competences juridiques au service d'un projet d'envergure qui touche plus de 4 millions de consommateurs d'eau potable en Ile-de-France CDI Lieu : Puteaux / La Defense"},
    {"id": 5, "keyword": "direction juridique recrute", "author": "EG Retail France SAS", "text": "Nous recrutons ! La Direction Juridique EG Retail France SAS recherche son/sa futur(e) Juriste en Droit des Affaires pour un CDD de 6 mois, a pourvoir des que possible. Ta mission ? Contribuer a la securite juridique des activites de l'entreprise"},
    {"id": 6, "keyword": "direction juridique recrute", "author": "Hal Scott Davis", "text": "see the light offres LIGHT Consultants"},
    {"id": 7, "keyword": "direction juridique recrute", "author": "Cyrille Raymond", "text": "job Vous etes expert(e) en montage de projets europeens ? La Direction d'ingenierie de Projets et de la Strategie Europe de l'Universite de Lorraine recrute : un(e) ingenieur(e) projets experimente(e) - Specialiste Erasmus Mundus"},
    {"id": 8, "keyword": "poste juriste France", "author": "Concours Jean-Pictet Competition", "text": "Rencontrez David Kootz - Membre du Comite du Concours Jean-Pictet Nous avons le plaisir de vous presenter David Kootz, juriste et professionnel humanitaire chevronne, actuellement Responsable des Affaires juridiques"},
    {"id": 9, "keyword": "poste juriste France", "author": "Ekomind", "text": "Ca recrute par ici ! On vous partage 7 nouveaux postes a retrouver sur Welcome to the Jungle France et LinkedIn. Juridique Juriste Legal Ops - Dipeeo"},
    {"id": 10, "keyword": "poste juriste France", "author": "Recruter - Jobs", "text": "COMAR recrute des Juriste Plus d'offre d'emploi"},
    {"id": 11, "keyword": "poste juriste France", "author": "Mehdi Taboulot", "text": "DATA4 recrute ! Contactez-moi en DM si vous souhaitez recevoir la fiche de poste. France: Juriste senior droit des contrats (Paris) - Responsable juridique compliance (Paris)"},
    {"id": 12, "keyword": "recrute avocat France", "author": "Law Profiler", "text": "Aramis Law Firm recrute 2 Avocat(e)s collaborateurs(trices) - Paris 9 : AVOCAT(E) COLLABORATEUR(TRICE) - TECH&DATA (2 A 3 ANS D'EXPERIENCE) AVOCAT(E) COLLABORATEUR(TRICE) EN DROIT SOCIAL (0 A 2 ANS D'EXPERIENCE)"},
    {"id": 13, "keyword": "recrute avocat France", "author": "Le Monde du Droit", "text": "Eversheds Sutherland France recrute Anne-Marie Lacoste pour se renforcer en arbitrage international avocats nominations"},
    {"id": 14, "keyword": "directeur juridique France", "author": "Fragmentalis", "text": "Are our data and conversation really protected? This is an interesting article of Heise Online dated 21/07/2025 It starts from the debate on Cloud Act"},
    {"id": 15, "keyword": "directeur juridique France", "author": "Nitza Agrait", "text": "Chere communaute LinkedIn, Grace a l'incomparable Stephanie C., j'ai decouvert que je fais partie des 20 directeurs juridiques a suivre sur LinkedIn, publie par LJA"},
    {"id": 16, "keyword": "cabinet avocat recrute", "author": "Zarine Ghazaryan", "text": "After reading this incredible article about the health risks of these German spa towns, the choice is quickly made for spa lovers: Long live the French Pyrenees."},
    {"id": 17, "keyword": "cabinet avocat recrute", "author": "Sarah DIANKEBA", "text": "LinkedInTopCompanies LinkedInActualites"},
    {"id": 18, "keyword": "cabinet avocat recrute", "author": "Jean-Marie Bellew", "text": "ZORIN recrute : Dans le cadre de notre developpement, le cabinet ZORIN recherche : H/F possedant un tres bon relationnel et de haut niveau (banques privees, family offices, avocats d'affaires...)"},
    {"id": 19, "keyword": "etude notariale recrute", "author": "NCE Notaires", "text": "OFFRE DU JOUR CDI - Ingenieur Patrimonial Junior CHOLET (49) - NEOLIA NOTAIRES Vous etes passionne(e) par le conseil patrimonial aupres des dirigeants d'entreprise ? Une des etudes notariales membres de NCE recherche activement un Ingenieur Patrimonial"},
    {"id": 20, "keyword": "etude notariale recrute", "author": "Marianne Genevrier", "text": "Le Notaire a la recherche du candidat ideal. Reflexions et conseils pour lutter contre le mercato actuel"},
    {"id": 21, "keyword": "etude notariale recrute", "author": "C B Martinot", "text": "recrute Administration Commercial Communication, Creation Direction d'Entreprise Etudes, R&D Gestion, finance Informatique Marketing Production Industrielle"},
    {"id": 22, "keyword": "etude notariale recrute", "author": "Marianne Genevrier", "text": "Le recrutement des Office managers s'intensifie progressivement dans le Notariat. Pourquoi est-ce une bonne nouvelle ?"},
    {"id": 23, "keyword": "etude notariale recrute", "author": "LexGO.be", "text": "Etude notariale Anne-France Hames recrute un juriste generaliste. Gerez des dossiers immobiliers et familiaux"},
    {"id": 24, "keyword": "poste avocat France", "author": "Avocats Sans Frontieres France", "text": "OFFRE DE RECRUTEMENT - Chef/fe de projet Samos Legal Centre Nous recherchons un ou une Chef/fe de projet pour assurer la coordination du projet Samos Legal Centre, en Grece"},
    {"id": 25, "keyword": "poste avocat France", "author": "Mathias CURNIER", "text": "Nouveaux defis! Tres heureux d'annoncer mon arrivee au Cabinet d'Avocats Vey & Associes au poste nouvellement creee de Directeur de la Strategie Communication"},
    {"id": 26, "keyword": "entreprise recrute juriste", "author": "Pierre-Adrien Blanchard", "text": "La Direction juridique de Veolia Eau France recrute un(e) juriste confirme(e) en droit prive. Les missions, redaction et conseils en : Droit des contrats Droit de la consommation RGPD. Profil : Master II en droit des affaires, 5/6 ans CDI"},
    {"id": 27, "keyword": "entreprise recrute juriste", "author": "Angelique M.", "text": "Atradius France recrute ! Plusieurs opportunites a saisir ! Nous recherchons en CDI, nos futur(e)s : Juriste Recouvrement / Compiegne"},
    {"id": 28, "keyword": "entreprise recrute juriste", "author": "Hayet BAKHTAR", "text": "POMA recrute un.e Juriste (H/F) pour accompagner l'Entreprise sur les questions de droit public et de droit des affaires. CDI base a Voreppe (38)"},
    {"id": 29, "keyword": "responsable juridique France", "author": "Helene Maizeroi Eugene", "text": "We're hiring a Head of Legal & Compliance for an international non-profit! Location: France, Belgium, Germany, Spain or Italy 100% remote"},
    {"id": 30, "keyword": "responsable juridique France", "author": "Caterina C.", "text": "My team at Data4 is growing and I'm currently looking for a Senior Legal Counsel/Legal Manager (Contracts) to join us! Paris"},
    {"id": 31, "keyword": "responsable juridique France", "author": "Dentons", "text": "Decouvrez l'interview realisee par Global Investigations Review avec Joydeep Sengupta, associe charge de la conformite chez Dentons"},
    {"id": 32, "keyword": "cdi juriste Paris", "author": "Olivier Beuchet", "text": "RECAP JOBS DU MOMENT !! Salut les juristes, les fiscalistes, les notaires. Il y a de la reactivite sur le marche jusqu'a Noel ! juriste corporate M&A - CDI - region parisienne ; juriste / legal counsel insurance - CDI"},
    {"id": 33, "keyword": "cdi juriste Paris", "author": "Mory Kadoch", "text": "Charles Gautier cherche un premier poste en CDD/CDI en droit fiscal des affaires ou fiscalite patrimoniale, base en France"},
    {"id": 34, "keyword": "cdi juriste Paris", "author": "EvalCommunity Jobs", "text": "Explore 300 exciting career opportunities in Monitoring & Evaluation (M&E) and International Development"},
    {"id": 35, "keyword": "cdi juriste Paris", "author": "Law Profiler", "text": "DEHENG - SHI & CHEN ASSOCIES Paris Beijing CDI - ASSISTANT(E) JURIDIQUE - H/F Le Cabinet d'avocats DEHENG recherche un(e) assitant(e) juridique. Poste en CDI a temps plein"},
    {"id": 36, "keyword": "legal counsel France", "author": "Qiong S.", "text": "We're Hiring - In-House Legal Counsel (F/M) Chery France is expanding its operations in France and is recruiting an experienced In-House Legal Counsel"},
    {"id": 37, "keyword": "legal counsel France", "author": "Nomos Avocats", "text": "Lexology Panoramic Intelligence artificielle Notre equipe Tech-PI-Medias est a nouveau contributrice du chapitre France"},
    {"id": 38, "keyword": "legal counsel France", "author": "Morgan Richez", "text": "The French employment market is often considered the most legally complicated globally, posing high risk for foreign principals"},
    {"id": 39, "keyword": "general counsel France", "author": "School of Law", "text": "Day 2 - Senior Executive Development Programme in International Aviation Law & Management A highlight of the day was the Valedictory Address"},
    {"id": 40, "keyword": "general counsel France", "author": "Rose K.", "text": "Miss Bernadette Utaatu, Crown Counsel and Acting Head of the CLF Division represents the Attorney General's Office and the Kingdom at the 33rd Plenary"},
    {"id": 41, "keyword": "general counsel France", "author": "Legal 500 GC", "text": "On behalf of Legal 500, we are delighted to introduce the GC Powerlist: France 2025"},
    {"id": 42, "keyword": "head of legal France", "author": "Alexis Pelletreau", "text": "New Chapter - Nissan West Europe France Honored to join the leadership team of Nissan France as Head of Legal"},
    {"id": 43, "keyword": "head of legal France", "author": "Ken Ebanks", "text": "Bonjour a mes amis et contacts francais! Come join the eBay team as our new Head of Legal, France! We're looking for a dynamic, experienced and personable lawyer"},
    {"id": 44, "keyword": "head of legal France", "author": "Shahdin Ali", "text": "Thank you to everyone who has expressed interest and reached out regarding the Head of Sales and Customer Service role in Paris, France"},
    {"id": 45, "keyword": "avocat senior", "author": "Stephane Alexandre", "text": "Crypto Act II - From Pledge to Practice: Secured Financing in the Web3 Era After the April 2025 DDADUE 5 Law, France continues its digital-asset transformation"},
    {"id": 46, "keyword": "avocat senior", "author": "Tsylana", "text": "05 novembre, Offres d'emploi a Paris Goldman Sachs CMS Francis Lefebvre Avocats - Avocat(e) Titrisation et financements structures"},
    {"id": 47, "keyword": "avocat senior", "author": "Zoe Watson", "text": "PARIS - France. - Private Equity / M&A Lawyer / Avocat a la Cour. - Senior Paris. Senior tier level 6-8 yrs. Please contact to discuss further."},
    {"id": 48, "keyword": "juriste senior", "author": "EUSupplyChainJobs", "text": "Several Supply Chain Jobs in EU. Acheteur /juriste experimente en droit public des affaire et contrats CDD 1 an Autorite des marches financiers (AMF) France Paris"},
    {"id": 49, "keyword": "juriste senior", "author": "Recruter - Jobs", "text": "job = un Juriste Senior Apply / Detail"},
    {"id": 50, "keyword": "juriste senior", "author": "Kalexius", "text": "We're hiring a new Mid-level/Senior Lawyer/Juriste IT Contracts in Paris, Ile-de-France. Apply today or share this post with your network."},
    {"id": 51, "keyword": "juriste senior", "author": "Giovanna Civello", "text": "I am hiring in France R51041 Juriste Senior F/H (Open)"},
    {"id": 52, "keyword": "juriste confirme", "author": "Unknown", "text": ""},
    {"id": 53, "keyword": "juriste confirme", "author": "Tsylana", "text": "15 octobre, Offres d'emploi en France. JPMorganChase La Banque Postale - Juriste confirme M&A et Gouvernance d'entreprise"},
    {"id": 54, "keyword": "juriste confirme", "author": "James D. Touati", "text": "CRYPTO 2025 : Portefeuille investisseur confirme : Que choisir ?!"},
    {"id": 55, "keyword": "juriste confirme", "author": "Talentia Software", "text": "We're hiring a new Juriste confirme H/F in Puteaux, Ile-de-France. Apply today or share this post with your network."},
    {"id": 56, "keyword": "avocat droit des affaires France", "author": "ALCEE AVOCATS", "text": "Doing business in France? Need contracts in English? At Alcee Avocats, we help entrepreneurs and companies navigate French business law seamlessly"},
    {"id": 57, "keyword": "avocat droit des affaires France", "author": "Sofiane Cherchali", "text": "Je suis ravi de vous annoncer le lancement de mon cabinet d'avocat d'affaires, SCH Avocat, situe au 37 Boulevard Victor Hugo, 06000 Nice"},
    {"id": 58, "keyword": "avocat droit des affaires France", "author": "Frederic DAL VECCHIO", "text": "Avec mes etudiants du Master Droit des affaires franco-asiatiques a Phnom Penh pour mon cours de droit fiscal international"},
]

def analyze_posts():
    print("="*100)
    print("ANALYSE DES 58 POSTS LINKEDIN AVEC LE FILTRE legal_filter")
    print("="*100)
    
    valid_posts = []
    invalid_posts = []
    exclusion_reasons = Counter()
    
    for post in POSTS:
        result = is_legal_job_post(post["text"], log_exclusions=False)
        post["result"] = result
        
        if result.is_valid:
            valid_posts.append(post)
        else:
            invalid_posts.append(post)
            if result.exclusion_reason:
                exclusion_reasons[result.exclusion_reason] += 1
    
    # Resume
    print(f"\n### RESUME ###")
    print(f"Total posts analyses: {len(POSTS)}")
    print(f"Posts VALIDES (a conserver): {len(valid_posts)}")
    print(f"Posts INVALIDES (a exclure): {len(invalid_posts)}")
    print(f"Taux de filtrage: {len(invalid_posts)/len(POSTS)*100:.1f}%")
    
    # Raisons d'exclusion
    print(f"\n### RAISONS D'EXCLUSION ###")
    for reason, count in exclusion_reasons.most_common():
        print(f"  {reason}: {count}")
    
    # Posts valides
    print(f"\n{'='*100}")
    print(f"### POSTS VALIDES ({len(valid_posts)}) - A CONSERVER ###")
    print("="*100)
    for post in valid_posts:
        r = post["result"]
        print(f"\n[{post['id']}] {post['author'][:40]}")
        print(f"    Keyword: {post['keyword']}")
        print(f"    Scores: legal={r.legal_score:.2f}, recruit={r.recruitment_score:.2f}")
        print(f"    Professions: {r.matched_professions[:3]}")
        print(f"    Signaux: {r.matched_signals[:3]}")
        print(f"    Texte: {post['text'][:120]}...")
    
    # Posts invalides
    print(f"\n{'='*100}")
    print(f"### POSTS INVALIDES ({len(invalid_posts)}) - A EXCLURE ###")
    print("="*100)
    for post in invalid_posts:
        r = post["result"]
        print(f"\n[{post['id']}] {post['author'][:40]}")
        print(f"    Keyword: {post['keyword']}")
        print(f"    Raison: {r.exclusion_reason}")
        if r.exclusion_terms:
            print(f"    Termes: {r.exclusion_terms}")
        if r.legal_score > 0 or r.recruitment_score > 0:
            print(f"    Scores: legal={r.legal_score:.2f}, recruit={r.recruitment_score:.2f}")
        print(f"    Texte: {post['text'][:100]}...")
    
    return valid_posts, invalid_posts

if __name__ == "__main__":
    analyze_posts()
