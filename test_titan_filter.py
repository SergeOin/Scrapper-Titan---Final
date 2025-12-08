"""Test Titan Partners filtering."""
from scraper.scrape_subprocess import filter_post_titan_partners, classify_author_type

# Test cases
test_posts = [
    # Should PASS: Company recruiting internally
    {'author': 'BKP et Associes Avocats', 'author_profile': None, 'company': None, 
     'text': 'BKP et Associes Avocats recrute ! Nous recherchons un juriste droit social'},
    
    # Should FAIL: Agency
    {'author': 'Law Profiler', 'author_profile': None, 'company': None,
     'text': 'JURISTES - LES DERNIERES OFFRES D EMPLOI legal counsel'},
     
    # Should FAIL: Individual seeking job
    {'author': 'Jean Dupont', 'author_profile': 'https://linkedin.com/in/jean-dupont', 'company': None,
     'text': 'Je recherche un poste de juriste. OpenToWork!'},
     
    # Should FAIL: External recruitment
    {'author': 'Cabinet Conseil', 'author_profile': None, 'company': None,
     'text': 'Pour notre client, nous recherchons un juriste senior'},
     
    # Should PASS: Individual posting for their company
    {'author': 'Marie Martin', 'author_profile': 'https://linkedin.com/in/marie-martin', 'company': 'CEGEDIM',
     'text': 'CEGEDIM recrute un Legal Counsel! Rejoignez notre equipe juridique'},
     
    # Should FAIL: No legal keywords
    {'author': 'TechCorp', 'author_profile': None, 'company': None,
     'text': 'Nous recrutons un developpeur Python senior!'},
]

print('=== TEST DU FILTRE TITAN PARTNERS ===\n')
for i, post in enumerate(test_posts, 1):
    author_type = classify_author_type(post['author'], post.get('author_profile'), post.get('company'))
    is_valid, reason = filter_post_titan_partners(post)
    status = 'PASS' if is_valid else 'FAIL'
    print(f"{status} Post {i}: {post['author']}")
    print(f"   Type auteur: {author_type}")
    print(f"   Resultat: {reason}")
    print()
