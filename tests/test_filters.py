import pytest
from src.filters import DealEvaluator, contains_whole_word

@pytest.fixture
def base_search_config():
    return {
        "id": "test_search",
        "name": "🧥 [Burberry] burberry trench vintage < 35€",
        "search_text": "burberry trench vintage",
        "brand": "Burberry",
        "brand_variants": ["burberry", "burberrys"],
        "min_price": 10.0,
        "max_price": 50.0,
        "min_seller_rating": 4.0,
        "exclude_keywords": ["parfum", "vide", "boite", "fake", "casquette", "cap", "bonnet"]
    }

def test_contains_whole_word():
    # 'cap' ne doit PAS matcher 'cape' ou 'capuche'
    assert not contains_whole_word("Superbe cape en laine", "cap")
    assert not contains_whole_word("Veste avec capuche chaude", "cap")
    # 'box' ne doit PAS matcher 'boxy'
    assert not contains_whole_word("T-shirt coupe boxy", "box")
    # 'cover' ne doit PAS matcher 'discover'
    assert not contains_whole_word("Discover vintage piece", "cover")

    # Doit matcher le mot entier exact, insensible casse et accents
    assert contains_whole_word("Belle casquette vintage", "casquette")
    assert contains_whole_word("Superbe cap vintage", "cap")
    assert contains_whole_word("Boîte vide d'origine", "boite")
    assert contains_whole_word("Boite vide d'origine", "boîte")
    assert contains_whole_word("Échantillon gratuit", "echantillon")

def test_cape_laine_accepted():
    search_config = {
        "id": "sniper_cape",
        "name": "🧥 Cape laine vintage < 50€",
        "search_text": "cape laine vintage",
        "min_price": 10.0,
        "max_price": 50.0,
        "exclude_keywords": ["cap", "casquette", "bonnet", "boite"]
    }
    item = {
        "id": 1001,
        "title": "Superbe cape laine vintage",
        "raw_title": "Superbe cape laine vintage",
        "price": {"amount": 25.0, "currency_code": "EUR"},
        "brand_title": "Vintage",
        "status": "Très bon état",
        "description": "Magnifique cape en pure laine vintage années 80."
    }
    is_ok, reason = DealEvaluator.prefilter(item, search_config)
    assert is_ok, f"Prefilter a rejeté à tort: {reason}"
    is_ok_full, reason_full = DealEvaluator.full_filter(item, search_config)
    assert is_ok_full, f"Full filter a rejeté à tort: {reason_full}"

def test_casquette_rejected(base_search_config):
    item = {
        "id": 1002,
        "title": "Casquette Burberry vintage",
        "raw_title": "Casquette Burberry vintage",
        "price": {"amount": 20.0, "currency_code": "EUR"},
        "brand_title": "Burberry",
        "status": "Très bon état",
        "description": "Casquette à motif tartan."
    }
    is_ok, reason = DealEvaluator.prefilter(item, base_search_config)
    assert not is_ok
    assert "casquette" in reason.lower() or "cap" in reason.lower()

def test_fast_fashion_brand_rejected(base_search_config):
    # En prefilter, la marque n'est pas encore connue si elle n'est pas dans le titre
    item = {
        "id": 1003,
        "title": "Trench vintage beige",
        "raw_title": "Trench vintage beige",
        "price": {"amount": 25.0, "currency_code": "EUR"},
        "brand_title": "Zara",
        "status": "Très bon état",
        "description": "Trench style vintage de chez Zara."
    }
    # En full_filter, la marque fast-fashion Zara doit être impérativement rejetée
    is_ok, reason = DealEvaluator.full_filter(item, base_search_config)
    assert not is_ok
    assert "fast-fashion" in reason.lower() or "zara" in reason.lower()

def test_satisfaisant_condition_rejected(base_search_config):
    item = {
        "id": 1004,
        "title": "Burberry trench vintage",
        "raw_title": "Burberry trench vintage",
        "price": {"amount": 30.0, "currency_code": "EUR"},
        "brand_title": "Burberry",
        "status": "Satisfaisant",
        "description": "Trench vintage avec quelques traces d'usure."
    }
    is_ok, reason = DealEvaluator.full_filter(item, base_search_config)
    assert not is_ok
    assert "satisfaisant" in reason.lower()

def test_two_pass_filtering(base_search_config):
    # Un article avec un prix hors limites doit être rejeté dès le prefilter (sans faire d'appel réseau)
    item_cheap = {
        "id": 1005,
        "title": "Burberry trench vintage",
        "price": {"amount": 2.0, "currency_code": "EUR"}
    }
    is_ok, reason = DealEvaluator.prefilter(item_cheap, base_search_config)
    assert not is_ok
    assert "inférieur" in reason.lower()

def test_full_filter_rechecks_price(base_search_config):
    # Cas où le prix initial du catalogue paraissait bon, mais le prix certifié extrait en JSON-LD dépasse max_price
    item = {
        "id": 1006,
        "title": "Burberry trench vintage",
        "raw_title": "Burberry trench vintage",
        "price": {"amount": 30.0, "currency_code": "EUR"},
        "brand_title": "Burberry",
        "status": "Très bon état",
        "description": "Superbe trench vintage Burberry."
    }
    is_ok, _ = DealEvaluator.prefilter(item, base_search_config)
    assert is_ok

    # Après enrichissement réseau, le prix réel est de 85€ (supérieur à max_price 50€)
    item["price"] = {"amount": 85.0, "currency_code": "EUR"}
    is_ok_full, reason_full = DealEvaluator.full_filter(item, base_search_config)
    assert not is_ok_full
    assert "supérieur" in reason_full.lower()
