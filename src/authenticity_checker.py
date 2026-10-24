"""
src/authenticity_checker.py
---------------------------
Module d'expertise et de vérification d'authenticité (Legit Check) par IA Multimodale.
Analyse les photos d'annonces (logos, typographies, coutures, étiquettes, quincaillerie)
et croise avec les informations de prix, marque et description pour détecter les contrefaçons.
"""

import os
import re
import json
import time
import logging
import requests
from typing import Dict, Any, List, Optional
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("VintedBot.AuthenticityChecker")

AUTHENTICITY_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-flash-latest",
    "gemini-3.5-flash",
    "gemini-3.8-flash",
    "gemini-flash-lite-latest"
]


class AuthenticityChecker:
    """Expert IA Multimodal spécialisé dans l'authentification et le Legit Check d'articles de mode/luxe."""

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

        models_cfg = self.config.get("gemini_models")
        self.models = [m.strip() for m in models_cfg if m and isinstance(m, str) and m.strip()] if models_cfg else list(AUTHENTICITY_MODELS)
        self.active_key_idx = 0
        self.active_model_idx = 0

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        })

    def _select_auth_photos(self, photo_urls: List[str]) -> List[str]:
        """Sélectionne intelligemment jusqu'à 4 photos clés (vue d'ensemble, étiquette de col, détails/logo, dos)."""
        if not photo_urls:
            return []
        if len(photo_urls) <= 4:
            return list(photo_urls)

        # Prioriser les photos montrant l'étiquette ou les détails
        selected = [photo_urls[0]]
        tag_keywords = ["label", "tag", "etiquette", "logo", "detail", "wash", "care", "serial"]

        tag_photo = None
        for u in photo_urls[1:]:
            u_low = u.lower()
            if any(k in u_low for k in tag_keywords):
                tag_photo = u
                break

        if tag_photo:
            selected.append(tag_photo)

        for u in photo_urls[1:]:
            if u not in selected and len(selected) < 4:
                selected.append(u)

        return selected[:4]

    def _download_images(self, photo_urls: List[str], domain: str = "vinted.fr") -> List[Any]:
        """Télécharge les photos en mémoire pour Gemini."""
        from google.genai import types

        headers = {"Referer": f"https://www.{domain}/"}

        def dl_one(url: str):
            try:
                resp = self.session.get(url, headers=headers, timeout=8)
                if resp.status_code == 200 and len(resp.content) > 1000:
                    c_type = resp.headers.get("Content-Type", "")
                    mime = "image/webp"
                    if "jpeg" in c_type or "jpg" in c_type or ".jpg" in url or ".jpeg" in url:
                        mime = "image/jpeg"
                    elif "png" in c_type or ".png" in url:
                        mime = "image/png"
                    return types.Part.from_bytes(data=resp.content, mime_type=mime)
            except Exception as e:
                logger.debug(f"Échec téléchargement photo pour auth {url[:50]}: {e}")
            return None

        parts = []
        with ThreadPoolExecutor(max_workers=min(4, len(photo_urls))) as pool:
            results = list(pool.map(dl_one, photo_urls))
            for p in results:
                if p:
                    parts.append(p)
        return parts

    def evaluate_authenticity(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Effectue une analyse d'authenticité approfondie via Gemini Vision.
        Retourne un diagnostic clair avec verdict, confiance, points de conformité et alertes.
        """
        title = item.get("title", "")
        brand = item.get("brand_title") or item.get("brand") or "Inconnue"
        price = item.get("price", 0.0)
        price_val = 0.0
        if isinstance(price, dict):
            price_val = float(price.get("amount", 0.0))
        elif isinstance(price, (int, float, str)):
            try:
                price_val = float(price)
            except ValueError:
                price_val = 0.0

        description = (item.get("description") or "").strip()
        domain = item.get("domain", "vinted.fr")

        # Photos
        photos = item.get("photos") or []
        photo_urls = []
        if isinstance(photos, list):
            for p in photos:
                if isinstance(p, dict):
                    u = p.get("url") or p.get("full_size_url")
                    if u:
                        photo_urls.append(u)
                elif isinstance(p, str) and p.startswith("http"):
                    photo_urls.append(p)

        if not photo_urls and "photo_urls" in item:
            try:
                raw_urls = item.get("photo_urls")
                if isinstance(raw_urls, str):
                    photo_urls = json.loads(raw_urls)
                elif isinstance(raw_urls, list):
                    photo_urls = raw_urls
            except Exception:
                pass

        selected_urls = self._select_auth_photos(photo_urls)
        if not selected_urls or not self.api_keys:
            return self._fallback_local_check(item, reason="Clé Gemini absente ou aucune photo")

        image_parts = self._download_images(selected_urls, domain=domain)
        if not image_parts:
            return self._fallback_local_check(item, reason="Échec téléchargement des photos")

        prompt = (
            f"Tu es un expert mondial en authentification de mode, streetwear et luxe vintage (Legit Check authenticator).\n"
            f"Examine avec une rigueur absolue ces {len(image_parts)} photos et les détails de cette annonce Vinted pour déterminer s'il s'agit d'une pièce ORIGINALE/AUTHENTIQUE ou d'une CONTREFAÇON (Fake / Replica / Dupe).\n\n"
            f"--- INFORMATIONS ARTICLE ---\n"
            f"• Marque : {brand}\n"
            f"• Titre : {title}\n"
            f"• Prix proposé : {price_val} €\n"
            f"• Description vendeur : {description or '(Aucune description)'}\n\n"
            f"--- GRILLE D'INSPECTION EXPERTE ---\n"
            f"1. TYPOGRAPHIE & LOGO : conformité de la police (kerning, graisses, alignement), fidélité de l'emblème/logo {brand}, absence de bavures ou de distorsions typiques des répliques.\n"
            f"2. ÉTIQUETTE DE COL (NECK TAG) : matière du ruban, méthode de fixation, régularité des coutures latérales, conformité de la typographie par rapport à l'époque du vêtement.\n"
            f"3. ÉTIQUETTE DE LAVAGE / COMPOSITION (WASH TAG) : présence des codes usine, style de typographie propre au groupe manufacturier, traduction des langues conforme.\n"
            f"4. FINITIONS & QUINCAILLERIE : gravures sur les zips/boutons (ex: logos YKK, Lampo, gravures nettes de la marque), propreté des coutures intérieures, doublure.\n"
            f"5. ANALYSE DU PRIX ET COHÉRENCE : un prix dérisoire (ex: 10€ pour une pièce rare) couplé à une étiquette cartonnée neuve chinoise est un fort indice de fake.\n\n"
            f"Réponds STRICTEMENT avec un objet JSON valide (sans Markdown ```json) ayant cette structure exacte :\n"
            f"{{\n"
            f'  "verdict": "<AUTHENTIQUE_PROBABLE | DOUTEUX | CONTREFACON_SUSPECTEE>",\n'
            f'  "confidence_pct": <entier 0-100>,\n'
            f'  "risk_level": "<FAIBLE | MODÉRÉ | ÉLEVÉ>",\n'
            f'  "summary": "<conclusion concise en 1 ou 2 phrases percutantes>",\n'
            f'  "positive_clues": ["<point conforme 1>", "<point conforme 2>"],\n'
            f'  "suspicious_clues": ["<détail suspect ou incohérence 1>"],\n'
            f'  "missing_checks": ["<ex: photo nette de l étiquette intérieure de lavage>"],\n'
            f'  "recommendation": "<conseil d achat clair pour l utilisateur>"\n'
            f"}}"
        )

        from google import genai
        from google.genai import types

        contents_payload = image_parts + [prompt]

        for model_name in self.models:
            for api_key in self.api_keys:
                try:
                    client = genai.Client(api_key=api_key)
                    gen_config = None
                    try:
                        gen_config = types.GenerateContentConfig(
                            media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW
                        )
                    except Exception:
                        pass

                    if gen_config:
                        response = client.models.generate_content(
                            model=model_name,
                            contents=contents_payload,
                            config=gen_config
                        )
                    else:
                        response = client.models.generate_content(
                            model=model_name,
                            contents=contents_payload
                        )

                    raw_text = response.text.strip()
                    if raw_text.startswith("```"):
                        raw_text = raw_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

                    data = json.loads(raw_text)

                    # Log usage tokens
                    usage_meta = getattr(response, "usage_metadata", None)
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

                    data["source"] = "Gemini Vision"
                    data["model"] = model_name
                    logger.info(f"🛡️ Legit Check réussi ({model_name}) pour #{item.get('id')} : {data.get('verdict')} ({data.get('confidence_pct')}%)")
                    return data

                except Exception as e:
                    logger.debug(f"Essai Legit Check échoué ({model_name}): {e}")
                    continue

        return self._fallback_local_check(item, reason="Tous les modèles Gemini ont échoué")

    def _fallback_local_check(self, item: Dict[str, Any], reason: str = "") -> Dict[str, Any]:
        """Repli d'analyse heuristique et CLIP en cas d'indisponibilité de l'API Gemini."""
        brand = item.get("brand_title") or item.get("brand") or ""
        desc = (item.get("description") or "").lower()
        title = (item.get("title") or "").lower()

        suspicious = []
        positive = []

        fake_indicators = ["fausse", "faux", "dupe", "copie", "réplique", "replique", "fake", "imitation", "style de", "inspiré", "inspire"]
        auth_indicators = ["facture", "ticket", "certificat", "authentique", "acheté en boutique", "acheté chez", "d'origine", "vintage"]

        for ind in fake_indicators:
            if re.search(r'\b' + re.escape(ind) + r'\b', desc) or re.search(r'\b' + re.escape(ind) + r'\b', title):
                suspicious.append(f"Mention textuelle suspecte : '{ind}'")

        for ind in auth_indicators:
            if re.search(r'\b' + re.escape(ind) + r'\b', desc):
                positive.append(f"Mention rassurante : '{ind}'")

        if suspicious:
            verdict = "CONTREFACON_SUSPECTEE"
            conf = 85
            risk = "ÉLEVÉ"
            summary = "L'annonce contient des mentions textuelles suggérant une reproduction ou un dupe."
        elif positive:
            verdict = "AUTHENTIQUE_PROBABLE"
            conf = 70
            risk = "FAIBLE"
            summary = "Éléments déclaratifs en faveur de l'authenticité (facture ou provenance boutique)."
        else:
            verdict = "DOUTEUX"
            conf = 50
            risk = "MODÉRÉ"
            summary = "Analyse visuelle avancée indisponible. Vérification manuelle des étiquettes conseillée."

        return {
            "verdict": verdict,
            "confidence_pct": conf,
            "risk_level": risk,
            "summary": summary,
            "positive_clues": positive or ["Marque bien référencée"],
            "suspicious_clues": suspicious or ["Photos détaillées des étiquettes intérieures non garanties"],
            "missing_checks": ["Photo nette de l'étiquette de lavage et de composition"],
            "recommendation": "Demandez au vendeur une photo de l'étiquette intérieure avant d'acheter.",
            "source": "Analyse heuristique locale (Repli)",
            "model": "Rules/Heuristics"
        }

    @staticmethod
    def format_telegram_report(auth_res: Dict[str, Any], item_id: int, brand: str, title: str) -> str:
        """Formate le rapport d'authenticité pour affichage élégant dans Telegram."""
        verdict = auth_res.get("verdict", "DOUTEUX")
        conf = auth_res.get("confidence_pct", 50)
        risk = auth_res.get("risk_level", "MODÉRÉ")
        summary = auth_res.get("summary", "")
        positives = auth_res.get("positive_clues", [])
        suspects = auth_res.get("suspicious_clues", [])
        missings = auth_res.get("missing_checks", [])
        rec = auth_res.get("recommendation", "")
        model_used = auth_res.get("model", "Gemini Vision")

        if verdict == "AUTHENTIQUE_PROBABLE" or "AUTHENTIQUE" in verdict:
            badge_icon = "🟢"
            badge_title = f"AUTHENTIQUE PROBABLE ({conf}%)"
        elif verdict == "CONTREFACON_SUSPECTEE" or "CONTREFACON" in verdict or "FAUX" in verdict:
            badge_icon = "🔴"
            badge_title = f"CONTREFAÇON SUSPECTÉE / FAUX ({conf}%)"
        else:
            badge_icon = "🟡"
            badge_title = f"DOUTEUX / À VÉRIFIER ({conf}%)"

        risk_color = "🟢" if risk == "FAIBLE" else ("🔴" if risk == "ÉLEVÉ" else "🟡")

        pos_str = "\n".join([f"  • {p}" for p in positives[:4]]) or "  • Aucun point marquant"
        sus_str = "\n".join([f"  • {s}" for s in suspects[:4]]) or "  • Aucun drapeau rouge détecté"
        mis_str = "\n".join([f"  • {m}" for m in missings[:3]]) or "  • Photos actuelles suffisantes"

        msg = (
            f"🛡️ <b>RAPPORT DE VÉRIFICATION D'AUTHENTICITÉ</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📌 <b>Article :</b> <code>#{item_id}</code>\n"
            f"🏢 <b>Marque :</b> <b>{brand}</b>\n"
            f"🏷️ <b>Titre :</b> {title[:60]}\n\n"
            f"⚖️ <b>VERDICT :</b> {badge_icon} <b>{badge_title}</b>\n"
            f"⚠️ <b>Niveau de risque :</b> {risk_color} <b>{risk}</b>\n\n"
            f"📝 <b>Bilan de l'expert :</b>\n"
            f"<i>\"{summary}\"</i>\n\n"
            f"✅ <b>Points conformes :</b>\n{pos_str}\n\n"
            f"🚩 <b>Doutes / Anomalies :</b>\n{sus_str}\n\n"
            f"📸 <b>Vérifications recommandées :</b>\n{mis_str}\n\n"
            f"💡 <b>Conseil :</b> <i>{rec}</i>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🤖 <i>Analysé par {model_used}</i>"
        )
        return msg
