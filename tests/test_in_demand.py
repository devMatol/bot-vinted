import pytest
from unittest.mock import MagicMock
from src.in_demand import InDemandTracker
from src.database import DatabaseManager

def test_in_demand_skips_only_notified(tmp_path):
    db_file = tmp_path / "test_in_demand.db"
    db = DatabaseManager(db_path=str(db_file))

    tracker = InDemandTracker(check_delay_seconds=0) # Échéance immédiate pour le test

    item = {
        "id": 5555,
        "title": "Veste Cuir Vintage",
        "domain": "vinted.fr",
        "price": {"amount": 25.0}
    }

    # 1. L'annonce est vue dès la découverte (comme le fait main.py)
    db.mark_item_seen(5555, domain="vinted.fr", title="Veste Cuir Vintage", price=25.0)
    tracker.add_to_tracker(item, "Veste Cuir")

    # Mocks pour scraper et notifier
    scraper_mock = MagicMock()
    session_mock = MagicMock()
    scraper_mock.session_manager.domain = "vinted.fr"
    scraper_mock.session_manager.get_session.return_value = session_mock

    # Réponse simulant 10 favoris (au-dessus du seuil de 7)
    response_mock = MagicMock()
    response_mock.status_code = 200
    response_mock.json.return_value = {
        "item": {
            "id": 5555,
            "title": "Veste Cuir Vintage",
            "favourite_count": 10,
            "view_count": 50,
            "price": {"amount": 25.0}
        }
    }
    session_mock.get.return_value = response_mock

    notifier_mock = MagicMock()
    notifier_mock.is_configured.return_value = True

    # 2. Exécuter la vérification du radar :
    # Avant Phase 2.1, l'item était sauté car 'db.is_item_seen' était True.
    # Maintenant, il NE DOIT PAS être sauté car 'is_item_notified' est False !
    tracker.process_due_items(scraper_mock, notifier_mock, db)

    # L'annonce a bien été notifiée et enregistrée
    assert db.is_item_notified(5555, domain="vinted.fr")
    # L'alerte In-Demand a bien été envoyée
    assert notifier_mock.is_configured.called

    # 3. Si on ré-ajoute et qu'elle est maintenant notifiée :
    tracker.add_to_tracker(item, "Veste Cuir")
    notifier_mock.reset_mock()
    tracker.process_due_items(scraper_mock, notifier_mock, db)
    # Cette fois, elle est sautée car déjà notifiée !
    assert not notifier_mock.is_configured.called
