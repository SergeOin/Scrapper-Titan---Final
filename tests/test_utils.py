from __future__ import annotations

import pytest

from scraper import utils


def test_random_user_agent_deterministic():
    ua1 = utils.random_user_agent(seed=123)
    ua2 = utils.random_user_agent(seed=123)
    assert ua1 == ua2
    assert "Mozilla/5.0" in ua1


def test_keyword_density():
    text = "Python AI python data"
    score = utils.keyword_density(text, ["python", "ai"])
    assert 0 <= score <= 1


def test_make_post_id_stable():
    a = utils.make_post_id("k", "author", "2024-01-01")
    b = utils.make_post_id("k", "author", "2024-01-01")
    assert a == b
    c = utils.make_post_id("k", "author", "2024-01-02")
    assert a != c


def test_parse_possible_date_relative():
    dt = utils.parse_possible_date("5 h")
    assert dt is not None


def test_compute_score_bounds():
    class Dummy:
        weight_length = 0.4
        weight_media = 0.3
        weight_keyword_density = 0.2
        weight_lang_match = 0.1

    s = utils.compute_score(
        text="Some content about python and AI", # length
        language="fr",
        expected_lang="fr",
        has_media=True,
        keywords=["python", "ai"],
        settings=Dummy(),  # type: ignore
    )
    assert 0 <= s <= 1


def test_normalize_for_search_accents():
    assert utils.normalize_for_search("École") == "ecole"
    assert utils.normalize_for_search("  CÔTE  d'Azur  ") == "cote  d'azur"


def test_build_search_norm_concat_and_trim():
    blob = utils.build_search_norm("Été", None, "Société", "Dévéloppé")
    assert "ete" in blob and "societe" in blob and "developpe" in blob
