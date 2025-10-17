import pytest

from scraper import utils
from scraper.legal_classifier import classify_legal_post


@pytest.mark.parametrize(
    "text",
    [
        "Je recrute un(e) juriste pour rejoindre la direction juridique.",
        "Nous cherchons un avocat collaborateur expérimenté.",
        "On recherche un juriste corporate.",
        "Hiring Paralegal - join the team!",
        "Rejoignez la direction juridique, we are hiring!",
    ],
)
def test_is_opportunity_new_phrases(text):
    assert utils.is_opportunity(text, threshold=0.05) is True


@pytest.mark.parametrize(
    "text, expected_intent",
    [
        ("Je recrute un(e) juriste au sein de notre direction juridique à Paris.", "recherche_profil"),
        ("Nous cherchons un avocat collaborateur pour notre équipe.", "recherche_profil"),
        ("Hiring Paralegal - join the team in Paris!", "recherche_profil"),
        ("On recherche un juriste fiscaliste.", "recherche_profil"),
        ("Rejoignez la direction juridique - poste à pourvoir", "recherche_profil"),
    ],
)
def test_classify_legal_post_new_phrases(text, expected_intent):
    cls = classify_legal_post(text, language="fr", intent_threshold=0.25)
    assert cls.intent == expected_intent
    assert cls.relevance_score >= 0.2
