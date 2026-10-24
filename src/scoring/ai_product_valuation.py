"""
src/scoring/ai_product_valuation.py
------------------------------------
Module d'identification visuelle multimodale et d'estimation précise de revente par IA (Gemini Vision).

Rôle :
1. Examiner les photos réelles de l'annonce pour identifier avec exactitude la pièce (ex: 'Sac shopping en papier boutique' vs 'Sac à main cuir matelassé').
2. Écarter impitoyablement tout ce qui n'est pas une pièce de mode revendable (sacs en papier magasin, boîtes vides, cintres, goodies, packaging).
3. Estimer le prix de revente réel du produit identifié sur le marché de la seconde main (Vinted / boutique).
4. Calculer la marge nette réelle avant tout envoi d'alerte Telegram.
"""

import os
import re
import json
import time
import logging
import requests
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("VintedBot.Scoring.AIValuation")

@dataclass
class ProductValuationResult:
    """Résultat de l'analyse et valorisation IA multimodale."""
    is_resalable_fashion: bool = True
    product_name: str = ""
    category_detected: str = ""
    estimated_resale_eur: float = 0.0
    resale_min_flash: float = 0.0
    resale_max_high: float = 0.0
    margin_net: float = 0.0
    verdict: str = "VALIDATED"  # VALIDATED | REJECTED
    reason: str = ""
    model: str = "gemini-3.5-flash-lite"
    execution_ms: float = 0.0

class AIProductValuator:
    """Expert IA Multimodal chargé d'identifier la pièce exacte et de fixer son vrai prix de revente."""

    def __init__(self, config: Optional[Dict[str, Any]] = None, db_manager=None):
        self.config = config or {}
        self.db_manager = db_manager

        # Clés API Gemini
        key = self.config.get("gemini_api_key", "")
        keys_list = self.config.get("gemini_api_keys", [])
        if keys_list and isinstance(keys_list, list):
            self.api_keys = [k.strip() for k in keys_list if k and isinstance(k, str) and k.strip()]
        elif key:
            self.api_keys = [key.strip()]
        else:
            self.api_keys = []

        self.models = ["gemini-3.5-flash-lite", "gemini-flash-latest"]
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        })

    def _extract_image_part(self, item: Dict[str, Any]) -> Optional[Any]:
        """Récupère l'image principale de l'annonce pour Gemini."""
        from google.genai import types

        # 1. Vérifier si une photo locale existe
        local_path = item.get("_local_image_path")
        if local_path and os.path.exists(local_path):
            try:
                with open(local_path, "rb") as f:
                    b = f.read()
                mime = "image/png" if local_path.endswith(".png") else "image/jpeg"
                return types.Part.from_bytes(data=b, mime_type=mime)
            except Exception:
                pass

        # 2. Chercher les URLs de photos
        urls = []
        photos = item.get("photos") or []
        for p in photos:
            if isinstance(p, dict) and p.get("url"):
                urls.append(p.get("url"))
            elif isinstance(p, str) and p.startswith("http"):
                urls.append(p)
        if not urls and item.get("photo_urls"):
            raw_p = item.get("photo_urls")
            if isinstance(raw_p, list):
                urls = raw_p
            elif isinstance(raw_p, str):
                try:
                    urls = json.loads(raw_p)
                except Exception:
                    pass
        if not urls and item.get("photo", {}).get("url"):
            urls.append(item.get("photo", {}).get("url"))

        if not urls:
            return None

        # Télécharger la première photo en mémoire
        url = urls[0]
        domain = item.get("domain", "vinted.fr")
        headers = {"Referer": f"https://www.{domain}/"} if "vinted" in url else {}
        try:
            resp = self.session.get(url, headers=headers, timeout=6)
            if resp.status_code == 200 and len(resp.content) > 1000:
                c_type = resp.headers.get("Content-Type", "")
                mime = "image/webp"
                if "jpeg" in c_type or "jpg" in c_type or ".jpg" in url or ".jpeg" in url:
                    mime = "image/jpeg"
                elif "png" in c_type or ".png" in url:
                    mime = "image/png"
                return types.Part.from_bytes(data=resp.content, mime_type=mime)
        except Exception as e:
            logger.debug(f"Échec téléchargement photo pour AIValuator: {e}")

        return None

    def evaluate_product(
        self,
        item: Dict[str, Any],
        total_cost: float,
        min_margin_eur: float = 12.0
    ) -> ProductValuationResult:
        """
        Interroge Gemini Vision pour identifier la pièce exacte et estimer son vrai prix de revente.
        """
        t0 = time.perf_counter()

        if not self.api_keys:
            # Pas de clé Gemini configurée
            return ProductValuationResult(
                is_resalable_fashion=True,
                product_name="Article non vérifié IA (Pas de clé)",
                verdict="VALIDATED",
                reason="Clé API Gemini absente, passage sans valorisation IA"
            )

        image_part = self._extract_image_part(item)
        if not image_part:
            return ProductValuationResult(
                is_resalable_fashion=True,
                product_name="Article sans photo",
                verdict="VALIDATED",
                reason="Impossible de charger la photo"
            )

        title = item.get("title", "")
        brand = item.get("brand_title") or item.get("brand") or "Inconnue"
        desc = (item.get("description") or "")[:250].strip()
        price = item.get("price", 0.0)
        price_val = float(price.get("amount", 0.0)) if isinstance(price, dict) else float(price or 0.0)

        prompt = f"""Tu es un expert mondial en valorisation et revente d'articles de mode et luxe sur le marché de la seconde main (Vinted, friperies haut de gamme).

Analyse attentivement cette photo d'annonce :
• Titre vendeur : "{title}"
• Marque déclarée : "{brand}"
• Prix proposé : {price_val:.2f} € (Coût total acheteur avec port : {total_cost:.2f} €)
• Description : "{desc or '(Aucune description)'}"

MISSION :
1. Identifie avec PRÉCISION ce que montre la photo (nom précis du vêtement, de la pièce ou de l'objet).
2. Vérifie s'il s'agit d'une VRAIE pièce de mode/vêtement/maroquinerie/chaussure OU d'un simple emballage/goodies (ex: sac shopping en papier de magasin, boîte en carton vide, cintre en plastique, ruban promo, pochon vide, catalogue).
   -> Si c'est un emballage, sac en papier de magasin ou goodies : "is_resalable_fashion": false, "verdict": "REJECTED".
3. Estime le PRIX DE REVENTE RÉALISTE en euros (€) sur Vinted pour CETTE pièce spécifique dans l'état observé (pas un prix théorique abstrait, le prix auquel elle se vend vraiment).

Réponds STRICTEMENT avec cet objet JSON valide (sans backticks ni markdown) :
{{
  "product_identified": "<Nom précis de la pièce, ex: 'Sac shopping papier boutique' ou 'Veste blazer en laine' ou 'Jupe jacquard'>",
  "category": "<PACKAGING_GOODIES | VETEMENT | CHAUSSURES | SAC_MAROQUINERIE | ACCESSOIRE>",
  "is_resalable_fashion": true_ou_false,
  "estimated_resale_eur": <montant réaliste en euros>,
  "resale_range": {{"min_flash": <prix vente rapide>, "max_high": <prix haut acheteur coup de coeur>}},
  "reason": "<Explication concise en 1 phrase>"
}}"""

        from google import genai
        from google.genai import types

        for model_name in self.models:
            for api_key in self.api_keys:
                try:
                    client = genai.Client(api_key=api_key)
                    res = client.models.generate_content(
                        model=model_name,
                        contents=[image_part, prompt],
                        config=types.GenerateContentConfig(
                            media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW,
                            temperature=0.1
                        )
                    )

                    # Log usage tokens
                    usage_meta = getattr(res, "usage_metadata", None)
                    if usage_meta and self.db_manager:
                        try:
                            p_tok = getattr(usage_meta, "prompt_token_count", 0) or 0
                            c_tok = getattr(usage_meta, "candidates_token_count", 0) or 0
                            t_tok = getattr(usage_meta, "total_token_count", 0) or (p_tok + c_tok)
                            self.db_manager.record_token_usage(
                                prompt_tokens=p_tok,
                                candidates_tokens=c_tok,
                                total_tokens=t_tok,
                                model=model_name
                            )
                        except Exception:
                            pass

                    raw = res.text.strip()
                    if raw.startswith("```"):
                        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

                    data = json.loads(raw)
                    ms = (time.perf_counter() - t0) * 1000

                    p_name = str(data.get("product_identified") or title)
                    cat = str(data.get("category") or "VETEMENT")
                    is_fashion = bool(data.get("is_resalable_fashion", True))
                    resale = float(data.get("estimated_resale_eur") or 0.0)
                    r_range = data.get("resale_range") or {}
                    r_min = float(r_range.get("min_flash") or resale * 0.75)
                    r_max = float(r_range.get("max_high") or resale * 1.25)
                    reason = str(data.get("reason") or "")

                    # Si emballage ou goodies ou sac en papier
                    if not is_fashion or cat == "PACKAGING_GOODIES" or any(w in p_name.lower() for w in ["papier", "packaging", "carton", "emballage", "cintre", "pochon", "dustbag", "shopping bag"]):
                        return ProductValuationResult(
                            is_resalable_fashion=False,
                            product_name=p_name,
                            category_detected=cat,
                            estimated_resale_eur=resale,
                            resale_min_flash=r_min,
                            resale_max_high=r_max,
                            margin_net=resale - total_cost,
                            verdict="REJECTED",
                            reason=f"Objet non vestimentaire / Packaging ({p_name}) : {reason}",
                            model=model_name,
                            execution_ms=ms
                        )

                    # Vérification rentabilité réelle
                    margin = resale - total_cost
                    if margin < min_margin_eur:
                        return ProductValuationResult(
                            is_resalable_fashion=True,
                            product_name=p_name,
                            category_detected=cat,
                            estimated_resale_eur=resale,
                            resale_min_flash=r_min,
                            resale_max_high=r_max,
                            margin_net=margin,
                            verdict="REJECTED",
                            reason=f"Marge réelle insuffisante (+{margin:.1f}€ < min {min_margin_eur:.0f}€) pour {p_name} : {reason}",
                            model=model_name,
                            execution_ms=ms
                        )

                    return ProductValuationResult(
                        is_resalable_fashion=True,
                        product_name=p_name,
                        category_detected=cat,
                        estimated_resale_eur=resale,
                        resale_min_flash=r_min,
                        resale_max_high=r_max,
                        margin_net=margin,
                        verdict="VALIDATED",
                        reason=reason,
                        model=model_name,
                        execution_ms=ms
                    )

                except Exception as e:
                    logger.debug(f"Essai AI Valuation ({model_name}) échoué: {e}")
                    continue

        return ProductValuationResult(
            is_resalable_fashion=True,
            product_name="Article non identifié (Erreur API)",
            verdict="VALIDATED",
            reason="Tous les essais d'analyse IA ont échoué",
            execution_ms=(time.perf_counter() - t0) * 1000
        )


_VALUATOR_INSTANCE: Optional[AIProductValuator] = None

def get_ai_product_valuator(config: Optional[Dict[str, Any]] = None, db_manager=None) -> AIProductValuator:
    global _VALUATOR_INSTANCE
    if _VALUATOR_INSTANCE is None:
        _VALUATOR_INSTANCE = AIProductValuator(config=config, db_manager=db_manager)
    return _VALUATOR_INSTANCE
