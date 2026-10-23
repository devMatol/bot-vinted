import pytest
from unittest.mock import MagicMock, patch
from concurrent.futures import ThreadPoolExecutor
import time

from src.vision_evaluator import VisionEvaluator
from src.notifier import TelegramNotifier
from main import evaluate_and_notify_ai_worker

def test_photo_selection_3_max():
    # Test avec 6 photos : doit retourner 3 photos (1ere, etiquette/tag si detectee, detail)
    urls = [
        "https://images1.vinted.net/t/01_front.jpg",
        "https://images1.vinted.net/t/02_side.jpg",
        "https://images1.vinted.net/t/03_care_tag_label.jpg",
        "https://images1.vinted.net/t/04_back.jpg",
        "https://images1.vinted.net/t/05_texture.jpg"
    ]
    selected = VisionEvaluator._select_up_to_3_photos(urls)
    assert len(selected) == 3
    assert selected[0] == urls[0]  # Première photo conservée
    assert urls[2] in selected     # Étiquette détectée via mot-clé 'tag' / 'label'

def test_parallel_ai_worker_and_message_editing():
    # Simuler le flux en deux temps :
    # 1. Alerte immédiate (ai_pending=True)
    # 2. Worker IA en tâche de fond qui évalue et édite le message

    notifier_mock = MagicMock(spec=TelegramNotifier)
    notifier_mock.is_configured.return_value = True
    notifier_mock.send_deal_alert.return_value = 12345  # message_id = 12345
    notifier_mock.edit_deal_alert_result.return_value = True

    db_mock = MagicMock()
    db_mock.get_recent_feedback_examples.return_value = {"MUST_BUY": [], "REJECTED": []}

    vision_mock = MagicMock(spec=VisionEvaluator)
    # Cas 1 : Pépite validée (score 88 >= 75, revente 70€, prix 15€, marge élevée)
    vision_mock.evaluate_deal.return_value = {
        "score": 88,
        "verdict": "MUST_BUY",
        "summary": "Authentique Burberry en excellent état",
        "resale_estimate_eur": 70.0,
        "condition_assessment": "Parfait",
        "defects_detected": [],
        "distinctive_features": ["doublure Nova Check signature", "gabardine vintage"]
    }

    item = {
        "id": 9991,
        "title": "Burberry Trench Vintage",
        "price": {"amount": 15.0},
        "domain": "vinted.fr"
    }

    # Lancer dans un ThreadPoolExecutor (comme dans main.py avec gemini_workers)
    executor = ThreadPoolExecutor(max_workers=2)
    future = executor.submit(
        evaluate_and_notify_ai_worker,
        item=item,
        search_name="Trench",
        domain="vinted.fr",
        display_country="fr",
        price=15.0,
        shipping_cost=3.0,
        min_margin_eur=15.0,
        message_id=12345,
        vision_evaluator=vision_mock,
        notifier=notifier_mock,
        db=db_mock,
        search_id="s1"
    )

    future.result(timeout=3.0)

    # Vérifier que edit_deal_alert_result a bien été appelé avec le message_id
    assert notifier_mock.edit_deal_alert_result.called
    kwargs = notifier_mock.edit_deal_alert_result.call_args[1]
    assert kwargs["message_id"] == 12345
    assert kwargs["margin"] > 15.0
    assert kwargs["resale_estimate"] == 70.0

    # Vérifier la sauvegarde en base
    assert db_mock.save_deal_alert.called

    executor.shutdown(wait=False)

def test_telegram_edit_message_caption_payload():
    # Test unitaire de la méthode edit_deal_alert_result avec mock requests
    notifier = TelegramNotifier({
        "enabled": True,
        "bot_token": "123456:FAKE_TOKEN",
        "chat_id": "987654"
    })

    item = {
        "id": 8881,
        "title": "Veste Vintage",
        "price": 20.0,
        "domain": "vinted.fr"
    }

    # Cas REJECT -> doit afficher "IA : À ÉVITER"
    vision_result = {
        "score": 40,
        "verdict": "REJECT",
        "summary": "Défaut d'usure majeur",
        "resale_estimate_eur": 15.0,
        "condition_assessment": "Mauvais",
        "defects_detected": ["Trous", "Taches"]
    }

    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True}
        mock_post.return_value = mock_resp

        success = notifier.edit_deal_alert_result(
            message_id=777,
            item=item,
            search_name="Veste",
            domain="vinted.fr",
            vision_result=vision_result,
            country="fr",
            shipping_cost=3.0,
            min_margin_eur=15.0
        )

        assert success
        assert mock_post.called
        call_data = mock_post.call_args[1]["data"]
        assert call_data["message_id"] == 777
        caption = call_data["caption"]
        assert "À ÉVITER" in caption
        assert "40/100" in caption
