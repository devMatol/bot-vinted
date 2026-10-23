import logging
import json
import os
import re
import threading
from typing import Dict, Any, Optional

logger = logging.getLogger("VintedBot.Translator")

TRANSLATIONS_PATH = "translations.json"
TRANSLATIONS_LOCK = threading.Lock()

# Termes génériques de vêtements en français qui justifient une traduction vers d'autres langues.
# "trench", "vintage", "retro", "denim" sont universels ou intégrés au style/modèle et ne déclenchent pas de traduction s'ils sont associés à une marque.
GENERIC_CLOTHING_TERMS = {
    "manteau", "veste", "pull", "blazer", "robe", "jupe", "pantalon", "foulard", "echarpe",
    "écharpe", "maille", "cardigan", "sweat", "t-shirt", "chemise", "chemisier", "costume",
    "cuir", "laine", "cachemire", "soie", "coton", "homme", "femme"
}

KNOWN_BRANDS = {
    "burberry", "burberrys", "gucci", "prada", "dior", "chanel", "fendi", "celine",
    "saint laurent", "ysl", "louis vuitton", "hermes", "hermès", "balenciaga", "moncler",
    "stone island", "ralph lauren", "lacoste", "barbour", "acne", "acne studios", "miu miu",
    "bottega veneta", "loewe", "margiela", "maison margiela", "givenchy", "valentino",
    "carhartt", "arcteryx", "arc'teryx", "patagonia", "the north face", "north face",
    "stussy", "stüssy", "supreme", "cp company", "c.p. company"
}

MODEL_AND_STYLE_TERMS = {
    "trench", "vintage", "retro", "rétro", "denim", "jean", "jeans", "classic", "nova check"
}

def load_translations(path: str = TRANSLATIONS_PATH) -> Dict[str, Dict[str, str]]:
    """Charge le dictionnaire des traductions depuis translations.json."""
    if not os.path.exists(path):
        return {}
    with TRANSLATIONS_LOCK:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Impossible de lire {path}: {e}")
            return {}

def save_translation(search_text: str, country: str, translated: str, path: str = TRANSLATIONS_PATH):
    """Sauvegarde atomique et thread-safe d'une traduction dans translations.json."""
    with TRANSLATIONS_LOCK:
        data = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        data.setdefault(search_text, {})[country] = translated
        temp_path = f"{path}.tmp"
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(temp_path, path)
        except Exception as e:
            logger.error(f"Erreur sauvegarde atomique {path}: {e}")
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

def is_brand_and_model_only(search_text: str, brand: str = "") -> bool:
    """
    Détermine si une recherche n'est composée que d'une marque, d'un modèle ou de styles universels
    (ex: 'Burberry trench vintage', 'Gucci GG', 'Ralph Lauren Polo'),
    auquel cas aucune traduction n'est nécessaire.
    """
    clean_text = search_text.lower()
    words = re.findall(r'\b[a-zA-ZÀ-ÿ0-9]+\b', clean_text)
    
    # Si des termes purement vêtement français (manteau, veste, pull, laine...) sont présents, traduire
    has_generic_term = any(w in GENERIC_CLOTHING_TERMS for w in words)
    return not has_generic_term

def translate_query(
    search: Dict[str, Any],
    country: str,
    gemini_evaluator = None,
    translations_path: str = TRANSLATIONS_PATH
) -> str:
    """
    Retourne la recherche adaptée au pays :
    - fr ou be -> search_text original (pour 'be', on conserve la requête française)
    - Si translations.json contient la traduction -> utilise le cache
    - Si que marque et modèle (ex: 'burberry trench vintage') -> ne traduit pas
    - Sinon -> génère avec Gemini en conservant les accents, sauvegarde dans translations.json et logge.
    """
    country = country.lower().strip()
    search_text = search.get("search_text", "").strip()

    # Pour 'fr' et 'be', conserver la requête française d'origine
    if country in ("fr", "be") or not search_text:
        return search_text

    # 1. Vérifier si la traduction existe déjà en mémoire ou dans translations.json
    all_translations = load_translations(translations_path)
    cached = all_translations.get(search_text, {}).get(country)
    if cached:
        return cached

    # Vérifier aussi search_text_i18n dans l'objet search si présent
    i18n_dict = search.get("search_text_i18n") or {}
    if country in i18n_dict and i18n_dict[country]:
        save_translation(search_text, country, i18n_dict[country], translations_path)
        return i18n_dict[country]

    # 2. Si la recherche n'est composée que d'une marque et d'un modèle/style (ex: 'burberry trench vintage'), ne pas traduire
    brand = search.get("brand", "")
    if is_brand_and_model_only(search_text, brand):
        return search_text

    # 3. Génération unique de la traduction via Gemini avec conservation des accents
    target_langs = {
        "it": "l'italien",
        "de": "l'allemand",
        "es": "l'espagnol",
        "nl": "le néerlandais",
        "pt": "le portugais",
        "at": "l'allemand"
    }
    lang_name = target_langs.get(country, country)

    translated = search_text
    try:
        client = getattr(gemini_evaluator, "client", None)
        model = getattr(gemini_evaluator, "get_current_model", lambda: "gemini-3.5-flash-lite")()
        if client:
            prompt = (
                f"Traduis cette expression de recherche de vêtements/mode pour le moteur de recherche Vinted du français vers {lang_name}.\n"
                f"Expression source : '{search_text}'\n\n"
                f"Règles strictes :\n"
                f"1. Conserve TOUS les accents de la langue cible (ex: en portugais 'lã' pour laine, ne pas retirer l'accent !).\n"
                f"2. Conserve les noms de marques et modèles connus en l'état (ex: Burberry, trench, vintage).\n"
                f"3. Réponds UNIQUEMENT par la traduction en minuscules, sans guillemets, sans ponctuation finale, sans commentaire."
            )
            response = client.models.generate_content(
                model=model,
                contents=prompt
            )
            if response and response.text:
                candidate = response.text.strip().strip('"\'').lower()
                if candidate and len(candidate) < 100:
                    translated = candidate
                    logger.info(f"🌍 [Traduction IA] '{search_text}' -> [{country.upper()}] '{translated}'")
                    save_translation(search_text, country, translated, translations_path)

    except Exception as e:
        logger.warning(f"Impossible de traduire '{search_text}' pour '{country}': {e}")

    return translated
