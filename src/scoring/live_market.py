"""
src/scoring/live_market.py
--------------------------
Confrontation Marché Vinted en Temps Réel (Live Market Check).
Interroge le catalogue Vinted en direct (sans filtre de prix) pour extraire
la vraie distribution des prix concurrents (Médiane, P25, P75, Volume d'offres).
Maintient un cache mémoire TTL (2 heures) pour maximiser les performances.
"""

import time
import logging
import threading
from typing import Dict, Any, List, Optional
import numpy as np

logger = logging.getLogger("VintedBot.Scoring.LiveMarket")

# Mappage des catégories vers les mots-clés de recherche les plus percutants
CATEGORY_SEARCH_TERMS: Dict[str, str] = {
    "manteau_fourrure": "manteau fourrure",
    "manteau": "manteau",
    "blazer": "blazer veste",
    "veste": "veste blouson",
    "escarpins": "escarpins talons",
    "bottes": "bottes bottines",
    "chaussures": "chaussures sneakers",
    "sweat": "sweat hoodie",
    "pull_maille": "pull maille",
    "tshirt": "t-shirt",
    "top": "top debardeur",
    "chemise_blouse": "chemise",
    "robe": "robe",
    "jupe": "jupe",
    "jean": "jean denim",
    "short": "short",
    "combinaison": "combinaison",
    "pantalon": "pantalon",
    "sac": "sac a main",
    "accessoire": "accessoire"
}


class LiveMarketService:
    """Service de vérification et d'extraction des prix réels du marché Vinted en direct."""

    def __init__(self, ttl_seconds: int = 7200):
        self.ttl_seconds = ttl_seconds
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def get_live_market_data(
        self,
        brand: str,
        category: str,
        scraper,
        domain: str = "vinted.fr",
        extra_keywords: str = ""
    ) -> Optional[Dict[str, Any]]:
        """
        Récupère la distribution réelle des prix sur Vinted pour une marque et une catégorie.
        Utilise le cache TTL (2h) si disponible pour une réponse instantanée.
        """
        clean_brand = (brand or "").strip()
        clean_cat = (category or "").strip().lower()

        if not clean_brand or clean_brand.lower() in ("sans marque", "unknown", "inconnu"):
            return None

        cat_term = CATEGORY_SEARCH_TERMS.get(clean_cat, clean_cat)
        search_query = f"{clean_brand} {cat_term}".strip()
        if extra_keywords:
            search_query += f" {extra_keywords}".strip()

        cache_key = f"{domain}_{search_query.lower()}"

        now = time.time()
        with self._lock:
            if cache_key in self._cache:
                entry = self._cache[cache_key]
                if (now - entry["cached_at"]) < self.ttl_seconds:
                    logger.debug(f"⚡ [LiveMarket Cache Hit] {search_query} : Médiane {entry['median_price']}€ ({entry['sample_count']} annonces)")
                    return entry

        if scraper is None:
            return None

        # Exécution de la recherche sur Vinted sans plafond de prix
        try:
            logger.info(f"🔍 [LiveMarket Query] Confrontation réelle sur Vinted : '{search_query}' ({domain})...")
            search_cfg = {
                "name": f"LiveMarket_{search_query}",
                "search_text": search_query,
                "order": "relevance"
            }

            items = scraper.search_items(search_cfg, priority="high")
            if not items:
                return None

            prices = []
            sample_titles = []
            for it in items:
                price_obj = it.get("price")
                p = 0.0
                if isinstance(price_obj, dict):
                    p = float(price_obj.get("amount", 0.0))
                elif isinstance(price_obj, (int, float, str)):
                    try:
                        p = float(price_obj)
                    except ValueError:
                        p = 0.0
                if p > 2.0:
                    prices.append(p)
                    t = str(it.get("title") or "")
                    if t and len(sample_titles) < 5:
                        sample_titles.append(t)

            if len(prices) < 3:
                return None

            # Nettoyage des valeurs aberrantes (trimming des extrêmes)
            prices_arr = np.array(prices, dtype=np.float32)
            # Éliminer le top 2% d'annonces fantaisistes (ex: 5000€ pour une robe)
            p98 = float(np.percentile(prices_arr, 98))
            filtered_prices = prices_arr[prices_arr <= p98]

            med_price = float(np.median(filtered_prices))
            p25_price = float(np.percentile(filtered_prices, 25))
            p75_price = float(np.percentile(filtered_prices, 75))
            min_p = float(np.min(filtered_prices))
            max_p = float(np.max(filtered_prices))

            result = {
                "brand": clean_brand,
                "category": clean_cat,
                "search_query": search_query,
                "sample_count": len(filtered_prices),
                "median_price": round(med_price, 2),
                "p25_price": round(p25_price, 2),
                "p75_price": round(p75_price, 2),
                "min_price": round(min_p, 2),
                "max_price": round(max_p, 2),
                "sample_titles": sample_titles,
                "cached_at": now,
                "domain": domain
            }

            with self._lock:
                self._cache[cache_key] = result

            logger.info(
                f"✅ [LiveMarket Observé] '{search_query}' : {len(filtered_prices)} annonces en vente | "
                f"Min {min_p:.0f}€ | P25 {p25_price:.0f}€ | Médiane {med_price:.0f}€ | P75 {p75_price:.0f}€"
            )
            return result

        except Exception as e:
            logger.warning(f"Erreur lors du LiveMarket Check pour '{search_query}': {e}")
            return None


_LIVE_MARKET_INSTANCE: Optional[LiveMarketService] = None
_LIVE_MARKET_LOCK = threading.Lock()


def get_live_market_service() -> LiveMarketService:
    global _LIVE_MARKET_INSTANCE
    if _LIVE_MARKET_INSTANCE is None:
        with _LIVE_MARKET_LOCK:
            if _LIVE_MARKET_INSTANCE is None:
                _LIVE_MARKET_INSTANCE = LiveMarketService(ttl_seconds=7200)
    return _LIVE_MARKET_INSTANCE
