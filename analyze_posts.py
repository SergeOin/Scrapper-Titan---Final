import sqlite3

db_path = r'C:\Users\plogr\AppData\Local\TitanScraper\fallback.sqlite3'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

cursor.execute('SELECT id, author, company, text, keyword FROM posts ORDER BY collected_at DESC')
rows = cursor.fetchall()

# Cabinets de recrutement à exclure
cabinets = [
    'michael page', 'robert half', 'hays', 'fed legal', 'fed juridique',
    'page personnel', 'expectra', 'adecco', 'manpower', 'randstad',
    'spring professional', 'lincoln', 'laurence simons', 'taylor root',
    'approach people', 'major hunter', 'cabinet de recrutement', 'recrutement',
    'recruitment', 'headhunter', 'chasseur', 'rh externe', 'talent acquisition',
    'morgan philips', 'spencer stuart', 'russell reynolds', 'egon zehnder',
    'executive search', 'legal&hr', 'legal & hr', 'legalhrconsulting',
    'jobteaser', 'indeed', 'linkedin talent', 'welcometothejungle',
    'cadremploi', 'apec ', 'notre client', 'pour le compte de',
    'kpmg avocat', 'mazars', 'ey avocat', 'deloitte legal', 'pwc avocat'
]

# Métiers cibles
metiers = [
    'avocat', 'juriste', 'paralegal', 'paralégal', 'notaire', 'clerc',
    'responsable juridique', 'directeur juridique', 'directrice juridique',
    'legal counsel', 'general counsel', 'head of legal', 'chief legal'
]

# Formulations de recrutement direct
formulations = [
    'je recrute', 'nous recrutons', 'on recrute', 'on recherche', 'nous recherchons',
    'nous cherchons', 'hiring', 'join the team', 'join our team', 'rejoignez',
    'rejoint notre', 'recherche un', 'recherche une', 'recrute un', 'recrute une',
    'poste de', 'offre cdi', 'offre cdd', 'cdi', 'cdd', 'poste à pourvoir',
    'opportunité', 'opportunity', 'looking for', 'we are looking', 'cherche à recruter'
]

print(f'Total posts analysés: {len(rows)}')
print('='*80)

conformes = []
exclus_cabinet = []
exclus_autre = []

for row in rows:
    post_id, author, company, text, keyword = row
    author_low = (author or '').lower()
    company_low = (company or '').lower()
    text_low = (text or '').lower()
    
    # Vérifier si cabinet de recrutement
    is_cabinet = False
    cabinet_found = None
    for cab in cabinets:
        if cab in author_low or cab in company_low or cab in text_low[:400]:
            is_cabinet = True
            cabinet_found = cab
            break
    
    if is_cabinet:
        exclus_cabinet.append((post_id, author, cabinet_found))
        continue
    
    # Vérifier si contient un métier cible
    has_metier = False
    metier_found = None
    for m in metiers:
        if m in text_low:
            has_metier = True
            metier_found = m
            break
    
    if not has_metier:
        exclus_autre.append((post_id, author, 'pas de métier cible'))
        continue
    
    # Vérifier si formulation de recrutement
    has_formulation = False
    for f in formulations:
        if f in text_low:
            has_formulation = True
            break
    
    if has_formulation:
        conformes.append({
            'id': post_id,
            'author': author,
            'company': company,
            'text': text[:500] if text else '',
            'metier': metier_found
        })
    else:
        exclus_autre.append((post_id, author, 'pas de formulation recrutement'))

print(f'\n✅ POSTS CONFORMES AUX CRITÈRES: {len(conformes)}')
print('='*80)
for i, p in enumerate(conformes, 1):
    print(f"\n--- POST {i} ---")
    print(f"👤 Auteur: {p['author']}")
    print(f"🏢 Entreprise: {p['company'] or 'N/A'}")
    print(f"💼 Métier détecté: {p['metier']}")
    print(f"📝 Texte: {p['text'][:350]}...")
    print("-"*60)

print(f'\n\n❌ EXCLUS (cabinets de recrutement): {len(exclus_cabinet)}')
for e in exclus_cabinet[:10]:
    print(f"  - {e[1][:40]} (raison: {e[2]})")
if len(exclus_cabinet) > 10:
    print(f"  ... et {len(exclus_cabinet)-10} autres")

print(f'\n⚠️ EXCLUS (autres raisons): {len(exclus_autre)}')

conn.close()
