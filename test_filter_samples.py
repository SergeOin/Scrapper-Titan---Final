#!/usr/bin/env python3
"""Test the is_legal_job_post filter with sample posts."""

import sys
sys.path.insert(0, '.')

from scraper.legal_filter import is_legal_job_post

# Sample posts from previous analysis (58 posts)
SAMPLE_POSTS = [
    # Valid legal job posts
    "🔔 RECRUTEMENT - Juriste en droit social (H/F) - CDI - Paris Notre cabinet recherche un(e) juriste spécialisé(e) en droit social pour rejoindre notre équipe. Expérience : 3-5 ans minimum. Contact : recrutement@cabinet.fr #emploi #juridique",
    
    "Direction juridique - Nous recrutons ! Poste de Juriste Contrats H/F en CDI à Lyon. Rattaché au Directeur Juridique, vous gérez les contrats commerciaux et accompagnez les équipes opérationnelles. Postulez sur notre site.",
    
    "🚀 Offre d'emploi : Avocat droit des affaires (H/F) CDI Paris. Cabinet international recherche avocat 5-7 ans d'expérience pour son département M&A. Rémunération attractive selon profil.",
    
    # Invalid posts - promotional content
    "Séminaire juridique : Découvrez les dernières évolutions du droit du travail. Inscrivez-vous à notre webinar du 15 novembre ! #formation #juridique",
    
    "📚 Formation continue pour juristes : Maîtrisez le RGPD en 2 jours ! Inscription sur notre site. #formation #RGPD",
    
    # Invalid posts - #opentowork
    "#OpenToWork Juriste en recherche d'emploi, 5 ans d'expérience en droit des affaires. Disponible immédiatement. Contactez-moi !",
    
    # Invalid posts - internship/alternance
    "Stage juriste droit social 6 mois - Paris. Notre cabinet recherche un stagiaire pour son département social. Début janvier 2024.",
    
    "Alternance juriste contrats - Lyon. Vous préparez un Master 2 droit des affaires ? Rejoignez-nous en alternance !",
    
    # Invalid posts - freelance
    "Freelance disponible : Consultant juridique RGPD, j'accompagne les PME dans leur mise en conformité. Devis sur demande.",
    
    # Invalid posts - recruitment agency
    "Michael Page recrute pour son client un Juriste Corporate H/F. CDI - Paris. Salaire : 50-60K€. Postulez vite !",
    
    # Invalid posts - not legal profession
    "Nous recrutons un développeur Python confirmé (H/F) CDI Paris. Stack : Django, PostgreSQL, Docker. 5+ ans exp.",
    
    "RH : Nous recherchons un Chargé de recrutement H/F en CDI à Bordeaux. Expérience : 3 ans minimum.",
    
    # Invalid posts - outside France
    "Juriste Corporate CDI Genève. Notre client suisse recherche un juriste pour son siège. Package attractif.",
    
    # Valid but borderline
    "Le groupe X renforce sa direction juridique et recrute un Juriste M&A confirmé. CDI basé à Paris La Défense. Envoyez vos candidatures.",
    
    # Edge cases
    "Après 3 ans chez nous, notre juriste quitte l'équipe pour de nouvelles aventures. Bonne continuation Marine !",
]

def main():
    print("=" * 80)
    print("TEST DU FILTRE is_legal_job_post SUR DES EXEMPLES")
    print("=" * 80)
    
    valid_count = 0
    invalid_count = 0
    
    for i, post in enumerate(SAMPLE_POSTS, 1):
        result = is_legal_job_post(post)
        status = "✅ VALIDE" if result.is_valid else "❌ EXCLU"
        
        print(f"\n--- Post #{i} ---")
        print(f"Texte: {post[:100]}...")
        print(f"Résultat: {status}")
        print(f"  - Score légal: {result.legal_score:.2f}")
        print(f"  - Score recrutement: {result.recruitment_score:.2f}")
        if result.exclusion_reason:
            print(f"  - Raison d'exclusion: {result.exclusion_reason}")
        
        if result.is_valid:
            valid_count += 1
        else:
            invalid_count += 1
    
    print("\n" + "=" * 80)
    print("RÉSUMÉ")
    print("=" * 80)
    print(f"Total posts analysés: {len(SAMPLE_POSTS)}")
    print(f"Posts VALIDES: {valid_count} ({100*valid_count/len(SAMPLE_POSTS):.1f}%)")
    print(f"Posts EXCLUS: {invalid_count} ({100*invalid_count/len(SAMPLE_POSTS):.1f}%)")

if __name__ == "__main__":
    main()
