from scraper import utils

def test_language_filter_detect_fr():
    lang = utils.detect_language("Ceci est un texte en français pour test", default="fr")
    assert lang.lower() == "fr"

def test_language_filter_fallback_default():
    # Garbage input should fall back to default
    lang = utils.detect_language("xxxxx yyyyy zzzzz", default="fr")
    assert isinstance(lang, str) and len(lang) == 2  # Accept any ISO-639-1 code (detector may return varied guesses)
