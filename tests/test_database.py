import pytest
import os
import sqlite3
from src.database import DatabaseManager

@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_vinted.db"
    return DatabaseManager(db_path=str(db_file))

def test_seen_and_notified_separation(temp_db):
    item_id = 99999
    domain = "vinted.it"

    # Au départ, ni vu ni notifié
    assert not temp_db.is_item_seen(item_id)
    assert not temp_db.is_item_notified(item_id)

    # Marquer comme vu sur vinted.it
    temp_db.mark_item_seen(item_id, domain=domain, title="Trench", price=25.0)
    assert temp_db.is_item_seen(item_id)
    # Vu sur n'importe quel domaine signifie vu globalement
    assert item_id in temp_db.get_seen_items()

    # Vérification critique : être 'vu' ne signifie PAS être 'notifié' (Phase 2.1)
    assert not temp_db.is_item_notified(item_id)

    # Marquer comme notifié
    temp_db.mark_item_notified(item_id, domain=domain, search_id="test_search", title="Trench", price=25.0)
    assert temp_db.is_item_notified(item_id)
    # L'item_id est notifié quel que soit le domaine consulté
    assert temp_db.is_item_notified(item_id)

def test_full_deal_alert_and_update_classification(temp_db):
    item = {
        "id": 12345,
        "title": "Burberry Trench Vintage",
        "price": {"amount": 35.0, "currency_code": "EUR"},
        "brand_title": "Burberry",
        "status": "Très bon état",
        "description": "Trench vintage authentique sans défaut.",
        "photos": [{"url": "https://images1.vinted.net/t/01_photo.jpg"}],
        "user": {"login": "vintage_seller", "feedback_reputation": 0.95}
    }
    vision_result = {
        "score": 90,
        "verdict": "MUST_BUY",
        "summary": "Authentique et en parfait état"
    }

    # Sauvegarde complète lors de l'alerte
    temp_db.save_deal_alert(item, search_name="Trench Burberry", domain="vinted.fr", vision_result=vision_result)

    # Vérification dans la base
    with temp_db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT title, price, brand, score, classification FROM deal_feedback WHERE item_id = 12345")
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "Burberry Trench Vintage"
        assert row[1] == 35.0
        assert row[2] == "Burberry"
        assert row[3] == 90.0
        assert row[4] == "ALERT_SENT"

    # Clic utilisateur sur le bouton MUST BUY (Phase 2.5)
    temp_db.update_deal_feedback_classification(item_id=12345, classification="MUST_BUY", evaluated_by="Matthieu")

    with temp_db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT classification, evaluated_by, title FROM deal_feedback WHERE item_id = 12345")
        row = cursor.fetchone()
        assert row[0] == "MUST_BUY"
        assert row[1] == "Matthieu"
        # Les données de l'annonce sont toujours présentes !
        assert row[2] == "Burberry Trench Vintage"

def test_feedback_examples_retrieval(temp_db):
    # Insérer quelques annonces évaluées
    temp_db.save_deal_feedback(
        item_id=1,
        classification="MUST_BUY",
        search_name="burberry trench vintage",
        title="Trench Burberry Beige",
        price=30.0,
        brand="Burberry"
    )
    temp_db.save_deal_feedback(
        item_id=2,
        classification="REJECTED",
        search_name="burberry trench vintage",
        title="Pull Burberry Rétréci",
        price=15.0,
        brand="Burberry"
    )

    examples = temp_db.get_recent_feedback_examples(search_name="burberry trench vintage", limit_each=5)
    assert len(examples["MUST_BUY"]) == 1
    assert examples["MUST_BUY"][0]["title"] == "Trench Burberry Beige"
    assert len(examples["REJECTED"]) == 1
    assert examples["REJECTED"][0]["title"] == "Pull Burberry Rétréci"

def test_token_usage_tracking_and_cost(temp_db):
    import datetime
    today = datetime.date.today().isoformat()

    # Enregistrer 2 appels
    # 1. 2 000 prompt tokens, 100 output tokens
    temp_db.record_token_usage(prompt_tokens=2000, candidates_tokens=100, total_tokens=2100, model="gemini-3.5-flash-lite")
    # 2. 3 000 prompt tokens, 200 output tokens
    temp_db.record_token_usage(prompt_tokens=3000, candidates_tokens=200, total_tokens=3200, model="gemini-3.8-flash")

    usage = temp_db.get_token_usage_for_day(today)
    assert usage["calls_count"] == 2
    assert usage["prompt_tokens"] == 5000
    assert usage["candidates_tokens"] == 300
    assert usage["total_tokens"] == 5300

    # Coût prompt : (5000 / 1 000 000) * 0.30 = 0.0015 $
    assert abs(usage["cost_input_usd"] - 0.0015) < 1e-6
    # Coût output : (300 / 1 000 000) * 2.50 = 0.00075 $
    assert abs(usage["cost_output_usd"] - 0.00075) < 1e-6
    # Total : 0.00225 $
    assert abs(usage["total_cost_usd"] - 0.00225) < 1e-6
