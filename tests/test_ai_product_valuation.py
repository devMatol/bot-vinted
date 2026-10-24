import pytest
from unittest.mock import MagicMock, patch
from src.scoring.ai_product_valuation import AIProductValuator, ProductValuationResult

def test_ai_product_valuator_rejects_packaging():
    """Vérifie que l'IA identifie un sac papier boutique et le rejette directement."""
    valuator = AIProductValuator(config={"gemini_api_key": "fake_key"})

    mock_response = MagicMock()
    mock_response.text = '''{
        "product_identified": "Sac shopping en papier boutique Miu Miu",
        "category": "PACKAGING_GOODIES",
        "is_resalable_fashion": false,
        "estimated_resale_eur": 10.0,
        "resale_range": {"min_flash": 5.0, "max_high": 15.0},
        "reason": "Sac en papier boutique gratuit, valeur négligeable"
    }'''

    item = {
        "title": "Bag Miu Miu",
        "brand_title": "Miu Miu",
        "price": 10.0
    }

    with patch.object(valuator, "_extract_image_part", return_value=MagicMock()):
        with patch("google.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.models.generate_content.return_value = mock_response

            res = valuator.evaluate_product(item, total_cost=20.0, min_margin_eur=12.0)

            assert res.verdict == "REJECTED"
            assert res.is_resalable_fashion is False
            assert "Sac shopping en papier" in res.product_name
            assert res.estimated_resale_eur == 10.0
            assert res.margin_net == -10.0

def test_ai_product_valuator_validates_real_clothing():
    """Vérifie que l'IA identifie un vêtement réel de créateur et calcule sa vraie valeur."""
    valuator = AIProductValuator(config={"gemini_api_key": "fake_key"})

    mock_response = MagicMock()
    mock_response.text = '''{
        "product_identified": "Veste blazer vintage en laine Thierry Mugler",
        "category": "VETEMENT",
        "is_resalable_fashion": true,
        "estimated_resale_eur": 120.0,
        "resale_range": {"min_flash": 90.0, "max_high": 150.0},
        "reason": "Pièce vintage Mugler recherchée avec coupe structurée iconique"
    }'''

    item = {
        "title": "Veste vintage Mugler",
        "brand_title": "Thierry Mugler",
        "price": 25.0
    }

    with patch.object(valuator, "_extract_image_part", return_value=MagicMock()):
        with patch("google.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.models.generate_content.return_value = mock_response

            res = valuator.evaluate_product(item, total_cost=32.0, min_margin_eur=12.0)

            assert res.verdict == "VALIDATED"
            assert res.is_resalable_fashion is True
            assert "Thierry Mugler" in res.product_name
            assert res.estimated_resale_eur == 120.0
            assert res.margin_net == 88.0
