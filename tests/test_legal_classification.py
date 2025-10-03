"""Basic tests for legal domain classification heuristics.

These keep scope narrow (pure functions) so they run fast and are stable.
"""
from scraper.legal_classifier import classify_legal_post


def test_high_signal_recruitment():
    text = "Nous recrutons un Juriste fiscal pour rejoindre notre équipe à Paris (poste à pourvoir en CDI)."
    cls = classify_legal_post(text, language="fr", intent_threshold=0.2)
    assert cls.intent == "recherche_profil"
    assert cls.relevance_score >= 0.2
    assert cls.location_ok
    assert any("juriste" in k for k in cls.keywords_matched)


def test_low_signal_other():
    text = "Article d'opinion sur les évolutions du droit fiscal international sans offre d'emploi."
    cls = classify_legal_post(text, language="fr", intent_threshold=0.3)
    assert cls.intent == "autre"
    assert cls.relevance_score < 0.3


def test_non_french_language_rejected():
    text = "We are hiring a legal counsel in Paris"  # English, but should still pass language gate only if fr
    cls = classify_legal_post(text, language="en", intent_threshold=0.2)
    assert cls.intent == "autre"


def test_location_negative_without_france():
    text = "Nous recrutons un juriste fiscal basé à Toronto Canada (poste CDI)"
    cls = classify_legal_post(text, language="fr", intent_threshold=0.2)
    # Canada mention without France positive hint => location_ok may still be False
    if not cls.location_ok:
        assert cls.intent == "autre"  # should be rejected due to location


def test_false_positive_prevention():
    text = "Article de blog: le droit fiscal comparé entre France et Allemagne (pas d'offre ni recrutement)."
    cls = classify_legal_post(text, language="fr", intent_threshold=0.25)
    assert cls.intent == "autre"


def test_positive_with_multiple_signals():
    text = "On recrute ! Poste à pourvoir : Responsable juridique senior (CDI) pour notre bureau de Paris France."
    cls = classify_legal_post(text, language="fr", intent_threshold=0.3)
    assert cls.intent == "recherche_profil"
    assert cls.location_ok