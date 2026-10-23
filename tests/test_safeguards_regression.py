import pytest
from unittest.mock import MagicMock
from src.filters import DealEvaluator, is_clothing_shoes_or_bag, get_category_cap_and_multiplier
from src.vision_evaluator import VisionEvaluator
from src.notifier import TelegramNotifier
from main import evaluate_and_notify_ai_worker, load_config

def test_six_real_cases_safeguards():
    """
    Test de non-régression (Point 3) :
    6 cas réels :
    1. sweat Armani Jeans 8 € (rejet : basique diffusion, score <= 55, pas de distinctive_features, marge faible)
    2. t-shirt D&G 5 € (rejet : basique, score < 80, pas de distinctive_features)
    3. coupe à fruits Blumarine 15 € (rejet : non-vêtement exclu avant Gemini)
    4. 2 cintres Gucci 12 € (rejet : non-vêtement exclu avant Gemini)
    5. jupe ananas D&G 30 € (VALIDÉ : pièce recherchée, imprimé signature, score >= 80, marge >= 15€)
    6. cargo Mugler 20 € (VALIDÉ : pièce recherchée, coupe cargo signature, score >= 80, marge >= 15€)

    Vérifie que SEULS la jupe D&G et le cargo Mugler peuvent être validés.
    """
    config = load_config()
    search_config = {
        "id": "test_search",
        "name": "Test Search",
        "search_text": "vintage",
        "min_price": 2.0,
        "max_price": 100.0,
        "exclude_keywords": []
    }

    test_cases = [
        {
            "name": "sweat_armani_jeans",
            "item": {
                "id": 1001,
                "title": "Sweat Armani Jeans uni",
                "raw_title": "Sweat Armani Jeans uni noir col rond",
                "price": {"amount": 8.0},
                "brand_title": "Armani Jeans",
                "status": "Très bon état",
                "description": "Sweat basique uni noir Armani Jeans."
            },
            "price": 8.0,
            "ai_response": {
                "score": 55,
                "verdict": "REJECT",
                "summary": "Basique uni Armani Jeans sans signe distinctif",
                "resale_estimate_eur": 18.0,
                "condition_assessment": "Correct",
                "defects_detected": [],
                "distinctive_features": []
            },
            "expected_validated": False
        },
        {
            "name": "tshirt_dg",
            "item": {
                "id": 1002,
                "title": "T-shirt D&G basique blanc",
                "raw_title": "T-shirt D&G basique blanc",
                "price": {"amount": 5.0},
                "brand_title": "D&G",
                "status": "Bon état",
                "description": "T-shirt blanc D&G simple."
            },
            "price": 5.0,
            "ai_response": {
                "score": 50,
                "verdict": "REJECT",
                "summary": "T-shirt basique ordinaire sans détail distinctif",
                "resale_estimate_eur": 18.0,
                "condition_assessment": "Normal",
                "defects_detected": [],
                "distinctive_features": []
            },
            "expected_validated": False
        },
        {
            "name": "coupe_a_fruits_blumarine",
            "item": {
                "id": 1003,
                "title": "Coupe à fruits Blumarine vintage",
                "raw_title": "Coupe à fruits Blumarine céramique vintage",
                "price": {"amount": 15.0},
                "brand_title": "Blumarine",
                "status": "Très bon état",
                "description": "Superbe coupe à fruits en céramique."
            },
            "price": 15.0,
            "ai_response": None,  # Ne doit même pas être appelé
            "expected_validated": False
        },
        {
            "name": "cintres_gucci",
            "item": {
                "id": 1004,
                "title": "Lot de 2 cintres Gucci velours",
                "raw_title": "2 cintres Gucci vintage",
                "price": {"amount": 12.0},
                "brand_title": "Gucci",
                "status": "Bon état",
                "description": "Deux cintres Gucci originaux."
            },
            "price": 12.0,
            "ai_response": None,  # Ne doit même pas être appelé
            "expected_validated": False
        },
        {
            "name": "jupe_ananas_dg",
            "item": {
                "id": 1005,
                "title": "Jupe trapèze Dolce & Gabbana motif ananas",
                "raw_title": "Rock Dolce & Gabbana motif ananas",
                "price": {"amount": 30.0},
                "brand_title": "Dolce & Gabbana",
                "status": "Très bon état",
                "description": "Jupe Dolce & Gabbana jacquard imprimé ananas iconique."
            },
            "price": 30.0,
            "ai_response": {
                "score": 95,
                "verdict": "MUST_BUY",
                "summary": "Jupe jacquard texturé motif ananas signature iconique Dolce & Gabbana",
                "resale_estimate_eur": 120.0,
                "condition_assessment": "Parfait",
                "defects_detected": [],
                "distinctive_features": ["motif ananas signature", "jacquard texturé", "doublure satin imprimée"]
            },
            "expected_validated": True
        },
        {
            "name": "cargo_mugler",
            "item": {
                "id": 1006,
                "title": "Pantalon cargo Thierry Mugler vintage",
                "raw_title": "Cargo Mugler vintage",
                "price": {"amount": 20.0},
                "brand_title": "Thierry Mugler",
                "status": "Très bon état",
                "description": "Pantalon cargo Mugler finitions zippées signature."
            },
            "price": 20.0,
            "ai_response": {
                "score": 95,
                "verdict": "MUST_BUY",
                "summary": "Pantalon cargo vintage Thierry Mugler très recherché finitions zippées",
                "resale_estimate_eur": 120.0,
                "condition_assessment": "Excellent",
                "defects_detected": [],
                "distinctive_features": ["coupe cargo structurée", "surpiqûres et poches zippées signature"]
            },
            "expected_validated": True
        }
    ]

    results = {}

    for case in test_cases:
        item = case["item"]
        name = case["name"]
        price = case["price"]
        expected = case["expected_validated"]

        # 1. Test du préfiltrage (doit éliminer les non-vêtements)
        is_prefiltered, prefilter_reason = DealEvaluator.prefilter(item, search_config)
        
        if not is_prefiltered:
            # Rejeté dès le préfiltrage
            results[name] = False
            assert not expected, f"'{name}' a été rejeté au préfiltrage à tort : {prefilter_reason}"
            continue

        # Si l'annonce passe le préfiltrage, simuler l'analyse IA et les garde-fous
        ai_resp = case["ai_response"]
        assert ai_resp is not None, f"'{name}' aurait dû être bloqué au préfiltrage mais ne l'a pas été !"

        notifier_mock = MagicMock(spec=TelegramNotifier)
        notifier_mock.is_configured.return_value = True
        notifier_mock.send_deal_alert.return_value = 12345
        notifier_mock.edit_deal_alert_result.return_value = True

        db_mock = MagicMock()
        db_mock.get_recent_feedback_examples.return_value = {"MUST_BUY": [], "REJECTED": []}

        vision_mock = MagicMock(spec=VisionEvaluator)
        vision_mock.evaluate_deal.return_value = ai_resp

        evaluate_and_notify_ai_worker(
            item=item,
            search_name="Test",
            domain="vinted.fr",
            display_country="fr",
            price=price,
            shipping_cost=3.0,
            min_margin_eur=15.0,
            message_id=None,
            vision_evaluator=vision_mock,
            notifier=notifier_mock,
            db=db_mock,
            search_id="s1"
        )

        is_validated = notifier_mock.send_deal_alert.called
        results[name] = is_validated

    # Vérification stricte : SEULS la jupe D&G et le cargo Mugler doivent être validés
    assert results["sweat_armani_jeans"] is False, "Le sweat Armani Jeans ne doit PAS être validé"
    assert results["tshirt_dg"] is False, "Le t-shirt D&G ne doit PAS être validé"
    assert results["coupe_a_fruits_blumarine"] is False, "La coupe à fruits Blumarine ne doit PAS être validée"
    assert results["cintres_gucci"] is False, "Les 2 cintres Gucci ne doivent PAS être validés"
    assert results["jupe_ananas_dg"] is True, "La jupe ananas D&G DOIT être validée"
    assert results["cargo_mugler"] is True, "Le cargo Mugler DOIT être validé"

    # Vérification globale de la liste des validés
    validated_names = [k for k, v in results.items() if v]
    assert set(validated_names) == {"jupe_ananas_dg", "cargo_mugler"}, (
        f"Seuls jupe_ananas_dg et cargo_mugler doivent être validés, or nous avons : {validated_names}"
    )
