import pytest
from src.translator import translate_query, is_brand_and_model_only

def test_is_brand_and_model_only():
    # Marque et modèle uniquement : pas de traduction nécessaire
    assert is_brand_and_model_only("Burberry Nova Check", brand="Burberry")
    assert is_brand_and_model_only("Gucci GG", brand="Gucci")
    assert is_brand_and_model_only("Ralph Lauren Polo", brand="Ralph Lauren")
    # 'burberry trench vintage' ne doit pas être traduit (Correction 3)
    assert is_brand_and_model_only("burberry trench vintage", brand="Burberry")

    # Mots génériques français de vêtement : traduction nécessaire
    assert not is_brand_and_model_only("burberry manteau laine", brand="Burberry")
    assert not is_brand_and_model_only("gucci veste vintage", brand="Gucci")
    assert not is_brand_and_model_only("pull cachemire", brand="")

def test_translate_query_cache(tmp_path):
    trans_file = tmp_path / "test_translations.json"
    search = {
        "id": "test_search",
        "search_text": "manteau laine",
        "search_text_i18n": {
            "it": "cappotto lana",
            "de": "wollmantel"
        }
    }
    # France : retourne la recherche originale
    assert translate_query(search, "fr", translations_path=str(trans_file)) == "manteau laine"
    # Belgique ('be') : conserve toujours la requête française (Correction 3)
    assert translate_query(search, "be", translations_path=str(trans_file)) == "manteau laine"
    # Italie : utilise le cache
    assert translate_query(search, "it", translations_path=str(trans_file)) == "cappotto lana"
    # Allemagne : utilise le cache
    assert translate_query(search, "de", translations_path=str(trans_file)) == "wollmantel"

def test_burberry_trench_vintage_not_translated(tmp_path):
    trans_file = tmp_path / "test_translations.json"
    search = {
        "id": "burberry_trench",
        "search_text": "burberry trench vintage",
        "brand": "Burberry"
    }
    # Pour n'importe quel pays, ne doit jamais être traduit
    for country in ["it", "de", "es", "be", "nl", "pt", "at"]:
        assert translate_query(search, country, translations_path=str(trans_file)) == "burberry trench vintage"
