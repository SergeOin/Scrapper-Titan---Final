import pytest

from scraper import utils


@pytest.mark.parametrize(
    "text,expected_min",
    [
        ("Nous recherchons un juriste pour un poste en CDI", 0.05),
        ("Offre de poste: responsable fiscal en alternance", 0.04),
        ("Je recrute un legal counsel senior", 0.05),
        ("Article général sans lien emploi", 0.0),
    ],
)
def test_compute_recruitment_signal(text, expected_min):
    score = utils.compute_recruitment_signal(text)
    assert 0.0 <= score <= 1.0
    # Loose floor check (except for neutral case)
    if expected_min == 0.0:
        assert score < 0.02
    else:
        assert score >= expected_min