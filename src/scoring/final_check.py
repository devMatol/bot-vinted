"""Étage E optionnel : Contrôle final IA (Gemini ou Ollama) (Lot 7).

Options de configuration ("final_check") :
- "off" : aucun appel IA distant (100% local)
- "gemini" : réutilise l'API Gemini avec un prompt court centré sur l'authenticité, les défauts et l'étiquette (pas de prix)
- "ollama" : appel HTTP local à Ollama (modèle vision local, ex: qwen2.5vl:7b), timeout 60s
- En cas d'échec ou d'indisponibilité, bascule gracieuse sans blocage et alerte marquée "Non vérifié".
"""

import os
import json
import base64
import logging
import requests
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional

logger = logging.getLogger("VintedBot.Scoring.FinalCheck")


@dataclass
class FinalCheckResult:
    """Résultat de l'Étage E."""
    enabled: bool = False
    provider: str = "off"
    verified: bool = False
    authentic: bool = True
    defects_detected: bool = False
    label_verified: bool = False
    confidence: float = 100.0
    notes: str = ""
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


_HOURLY_CHECKS_COUNT = 0
_HOURLY_WINDOW_START = datetime.utcnow()


def perform_final_check(
    item: Dict[str, Any],
    photo_urls: List[str],
    config: Optional[Dict[str, Any]] = None
) -> FinalCheckResult:
    """
    Exécute le contrôle final optionnel si activé dans config.json ("final_check").
    """
    global _HOURLY_CHECKS_COUNT, _HOURLY_WINDOW_START

    cfg = config or {}
    provider = str(cfg.get("final_check", "off")).lower().strip()

    if provider in ("off", "none", "false", ""):
        return FinalCheckResult(enabled=False, provider="off", verified=False, notes="Contrôle final désactivé")

    # Vérification du plafond horaire
    max_per_hour = int(cfg.get("final_check_max_per_hour", 20))
    now = datetime.utcnow()
    if (now - _HOURLY_WINDOW_START).total_seconds() >= 3600:
        _HOURLY_CHECKS_COUNT = 0
        _HOURLY_WINDOW_START = now

    if _HOURLY_CHECKS_COUNT >= max_per_hour:
        logger.info(f"Plafond horaire de contrôle final atteint ({max_per_hour}/h).")
        return FinalCheckResult(
            enabled=True,
            provider=provider,
            verified=False,
            notes="Plafond horaire IA atteint (alerte transmise sans contrôle)"
        )

    _HOURLY_CHECKS_COUNT += 1

    prompt = (
        "Inspecte attentivement ces photos d'un vêtement de marque pour revente boutique. "
        "Vérifie uniquement l'authenticité (finitions, logo), l'absence de défauts cachés "
        "(trous, déchirures, tâches, usure anormale) et la présence d'une étiquette de marque conforme. "
        "Réponds EXCLUSIVEMENT en JSON valide avec ce format :\n"
        "{\n"
        '  "authentic": true,\n'
        '  "defects_detected": false,\n'
        '  "label_verified": true,\n'
        '  "confidence": 90,\n'
        '  "notes": "Une phrase concise de justification."\n'
        "}"
    )

    if provider == "gemini":
        return _check_with_gemini(item, photo_urls, prompt, cfg)
    elif provider == "ollama":
        return _check_with_ollama(item, photo_urls, prompt, cfg)
    else:
        return FinalCheckResult(enabled=False, provider=provider, verified=False, notes=f"Fournisseur inconnu : {provider}")


def _check_with_gemini(
    item: Dict[str, Any],
    photo_urls: List[str],
    prompt: str,
    cfg: Dict[str, Any]
) -> FinalCheckResult:
    """Contrôle via Gemini avec prompt court."""
    api_key = cfg.get("gemini_api_key")
    if isinstance(cfg.get("gemini_api_keys"), list) and cfg["gemini_api_keys"]:
        api_key = cfg["gemini_api_keys"][0]

    if not api_key:
        return FinalCheckResult(enabled=True, provider="gemini", verified=False, notes="Aucune clé Gemini configurée")

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        model_name = cfg.get("gemini_models", ["gemini-3.5-flash-lite"])[0]

        # Télécharger jusqu'à 2 photos max
        parts = []
        for url in photo_urls[:2]:
            if os.path.exists(url):
                with open(url, "rb") as f:
                    data = f.read()
                parts.append(types.Part.from_bytes(data=data, mime_type="image/jpeg"))
            elif url.startswith("http"):
                resp = requests.get(url, timeout=6)
                if resp.status_code == 200:
                    parts.append(types.Part.from_bytes(data=resp.content, mime_type="image/jpeg"))

        parts.append(types.Part.from_text(text=prompt))

        response = client.models.generate_content(
            model=model_name,
            contents=parts,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1
            )
        )

        resp_text = response.text.strip()
        data = json.loads(resp_text)
        return FinalCheckResult(
            enabled=True,
            provider="gemini",
            verified=True,
            authentic=bool(data.get("authentic", True)),
            defects_detected=bool(data.get("defects_detected", False)),
            label_verified=bool(data.get("label_verified", False)),
            confidence=float(data.get("confidence", 80.0)),
            notes=str(data.get("notes", ""))
        )
    except Exception as e:
        logger.warning(f"Échec contrôle final Gemini: {e}")
        return FinalCheckResult(enabled=True, provider="gemini", verified=False, error=str(e), notes="Erreur appel Gemini")


def _check_with_ollama(
    item: Dict[str, Any],
    photo_urls: List[str],
    prompt: str,
    cfg: Dict[str, Any]
) -> FinalCheckResult:
    """Contrôle via serveur Ollama local HTTP."""
    ollama_url = cfg.get("ollama_url", "http://localhost:11434/api/generate")
    ollama_model = cfg.get("ollama_model", "qwen2.5vl:7b")

    try:
        images_b64 = []
        for url in photo_urls[:2]:
            if os.path.exists(url):
                with open(url, "rb") as f:
                    images_b64.append(base64.b64encode(f.read()).decode("utf-8"))
            elif url.startswith("http"):
                resp = requests.get(url, timeout=6)
                if resp.status_code == 200:
                    images_b64.append(base64.b64encode(resp.content).decode("utf-8"))

        payload = {
            "model": ollama_model,
            "prompt": prompt,
            "images": images_b64,
            "format": "json",
            "stream": False
        }

        resp = requests.post(ollama_url, json=payload, timeout=60)
        if resp.status_code == 200:
            res_data = resp.json()
            raw_text = res_data.get("response", "{}")
            data = json.loads(raw_text)
            return FinalCheckResult(
                enabled=True,
                provider="ollama",
                verified=True,
                authentic=bool(data.get("authentic", True)),
                defects_detected=bool(data.get("defects_detected", False)),
                label_verified=bool(data.get("label_verified", False)),
                confidence=float(data.get("confidence", 80.0)),
                notes=str(data.get("notes", ""))
            )
        else:
            return FinalCheckResult(enabled=True, provider="ollama", verified=False, notes=f"Ollama HTTP {resp.status_code}")
    except Exception as e:
        logger.info(f"Ollama local non disponible ou timeout ({e}), poursuite sans blocage.")
        return FinalCheckResult(enabled=True, provider="ollama", verified=False, notes="Ollama non disponible (non vérifié)")
