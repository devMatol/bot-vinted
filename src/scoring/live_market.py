"""
src/scoring/live_market.py
--------------------------
Service de Prix de Référence du Marché Local & Persistant (Ultra-Rapide < 1 ms).
Enregistre et consolide les prix de référence au fur et à mesure dans SQLite (vinted_bot.db).
Recherche instantanée en mémoire RAM (0 ms) avec repli SQLite et calcul local,
et rafraîchissement asynchrone non-bloquant en arrière-plan.
"""

import time
import queue
import logging
import sqlite3
import threading
from typing import Dict, Any, List, Optional
import numpy as np

logger = logging.getLogger("VintedBot.Scoring.LiveMarket")

DEFAULT_DB_PATH = "vinted_bot.db"

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


def _get_db_conn(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    return conn


def init_live_market_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Initialise la table persistante live_market_cache dans SQLite."""
    conn = _get_db_conn(db_path)
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS live_market_cache (
                    cache_key TEXT PRIMARY KEY,
                    brand TEXT,
                    category TEXT,
                    median_price REAL,
                    p25_price REAL,
                    p75_price REAL,
                    min_price REAL,
                    max_price REAL,
                    sample_count INTEGER,
                    domain TEXT,
                    source TEXT DEFAULT 'local',
                    updated_at REAL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_live_mkt_brand_cat ON live_market_cache(brand, category)")
    except Exception as e:
        logger.debug(f"Erreur init live_market_cache: {e}")
    finally:
        conn.close()


class LiveMarketService:
    """
    Service local ultra-rapide (< 1 ms) de prix de référence du marché Vinted.
    Stocke les prix de référence en SQLite et les maintient en mémoire RAM.
    Ne bloque JAMAIS le pipeline d'évaluation des annonces.
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH, ttl_seconds: int = 86400 * 7):
        self.db_path = db_path
        self.ttl_seconds = ttl_seconds
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._bg_queue: queue.Queue = queue.Queue(maxsize=100)
        self._bg_pending_keys = set()

        init_live_market_db(self.db_path)
        self._load_cache_from_db()

        # Démarrage du worker de rafraîchissement d'arrière-plan discret (non-bloquant)
        self._bg_thread = threading.Thread(
            target=self._background_worker,
            name="LiveMarket-Background",
            daemon=True
        )
        self._bg_thread.start()

    def _load_cache_from_db(self) -> None:
        """Charge l'intégralité du cache SQLite persistant en mémoire RAM au démarrage."""
        try:
            conn = _get_db_conn(self.db_path)
            cur = conn.cursor()
            cur.execute("""
                SELECT cache_key, brand, category, median_price, p25_price, p75_price,
                       min_price, max_price, sample_count, domain, source, updated_at
                FROM live_market_cache
            """)
            rows = cur.fetchall()
            conn.close()

            with self._lock:
                for r in rows:
                    self._cache[r[0]] = {
                        "brand": r[1],
                        "category": r[2],
                        "median_price": float(r[3]),
                        "p25_price": float(r[4]),
                        "p75_price": float(r[5]),
                        "min_price": float(r[6]),
                        "max_price": float(r[7]),
                        "sample_count": int(r[8]),
                        "domain": r[9],
                        "source": r[10] or "local_cache",
                        "cached_at": float(r[11]),
                        "search_query": f"{r[1]} {r[2]}"
                    }
            logger.info(f"⚡ [LiveMarket] {len(self._cache)} prix de référence locaux chargés en mémoire RAM (réponse < 1 ms).")
        except Exception as e:
            logger.debug(f"Erreur chargement live_market_cache: {e}")

    def _save_entry_to_db(self, entry: Dict[str, Any], cache_key: str) -> None:
        """Sauvegarde une nouvelle référence de prix dans SQLite."""
        try:
            conn = _get_db_conn(self.db_path)
            with conn:
                conn.execute("""
                    INSERT OR REPLACE INTO live_market_cache
                    (cache_key, brand, category, median_price, p25_price, p75_price, min_price, max_price, sample_count, domain, source, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    cache_key,
                    entry["brand"],
                    entry["category"],
                    entry["median_price"],
                    entry["p25_price"],
                    entry["p75_price"],
                    entry["min_price"],
                    entry["max_price"],
                    entry["sample_count"],
                    entry.get("domain", "vinted.fr"),
                    entry.get("source", "local"),
                    entry.get("cached_at", time.time())
                ))
            conn.close()
        except Exception as e:
            logger.debug(f"Erreur sauvegarde live_market_cache: {e}")

    def compute_from_local_db(self, brand: str, category: str, domain: str = "vinted.fr") -> Optional[Dict[str, Any]]:
        """
        Calcule instantanément (< 1 ms) la médiane et les quantiles depuis les annonces
        déjà enregistrées dans la table market_listings de vinted_bot.db.
        """
        try:
            conn = _get_db_conn(self.db_path)
            cur = conn.cursor()

            # 1. Requête spécifique Marque x Catégorie
            cur.execute("""
                SELECT price FROM market_listings
                WHERE brand_canonical = ? AND category = ? AND price > 2
                ORDER BY price ASC
            """, (brand, category))
            prices = [float(r[0]) for r in cur.fetchall()]

            # 2. Si moins de 3 annonces, requêter la marque toutes catégories confondues
            source = "local_db_pair"
            if len(prices) < 3:
                cur.execute("""
                    SELECT price FROM market_listings
                    WHERE brand_canonical = ? AND price > 2
                    ORDER BY price ASC
                """, (brand,))
                brand_prices = [float(r[0]) for r in cur.fetchall()]
                if len(brand_prices) >= 3:
                    prices = brand_prices
                    source = "local_db_brand"

            conn.close()

            if len(prices) < 3:
                return None

            prices_arr = np.array(prices, dtype=np.float32)
            p98 = float(np.percentile(prices_arr, 98))
            filtered = prices_arr[prices_arr <= p98]

            now = time.time()
            cache_key = f"{domain}_{brand.lower()}_{category.lower()}"
            result = {
                "brand": brand,
                "category": category,
                "search_query": f"{brand} {category}",
                "sample_count": len(filtered),
                "median_price": round(float(np.median(filtered)), 2),
                "p25_price": round(float(np.percentile(filtered, 25)), 2),
                "p75_price": round(float(np.percentile(filtered, 75)), 2),
                "min_price": round(float(np.min(filtered)), 2),
                "max_price": round(float(np.max(filtered)), 2),
                "sample_titles": [],
                "cached_at": now,
                "domain": domain,
                "source": source
            }

            with self._lock:
                self._cache[cache_key] = result
            self._save_entry_to_db(result, cache_key)
            return result
        except Exception as e:
            logger.debug(f"Erreur compute_from_local_db: {e}")
            return None

    def get_live_market_data(
        self,
        brand: str,
        category: str,
        scraper=None,
        domain: str = "vinted.fr",
        extra_keywords: str = ""
    ) -> Optional[Dict[str, Any]]:
        """
        Récupère instantanément (< 1 ms) le prix de référence du marché pour une marque et une catégorie.
        1. Vérifie le cache RAM (0 ms).
        2. Si absent ou expiré, calcule instantanément depuis la base locale SQLite market_listings (1 ms).
        3. Si toujours absent, déclenche un rafraîchissement d'arrière-plan ASYNCHRONE et renvoie un fallback immédiat
           sans JAMAIS bloquer l'analyse !
        """
        clean_brand = (brand or "").strip()
        clean_cat = (category or "").strip().lower()

        if not clean_brand or clean_brand.lower() in ("sans marque", "unknown", "inconnu"):
            return None

        cache_key = f"{domain}_{clean_brand.lower()}_{clean_cat}"
        now = time.time()

        # 1. Vérification RAM (0 ms)
        with self._lock:
            if cache_key in self._cache:
                entry = self._cache[cache_key]
                if (now - entry["cached_at"]) < self.ttl_seconds:
                    return entry

        # 2. Calcul depuis la base locale SQLite (1 ms)
        local_res = self.compute_from_local_db(clean_brand, clean_cat, domain)
        if local_res:
            logger.debug(f"⚡ [Prix Référence Local] {clean_brand} {clean_cat} : Médiane {local_res['median_price']}€ ({local_res['sample_count']} annonces en base)")
            return local_res

        # 3. Si absent de la base, enfile un rafraîchissement discret en tâche de fond SANS BLOQUER
        if scraper and cache_key not in self._bg_pending_keys:
            try:
                self._bg_pending_keys.add(cache_key)
                self._bg_queue.put_nowait((clean_brand, clean_cat, scraper, domain, extra_keywords))
            except Exception:
                pass

        # Retourne None immédiatement : le modèle de revente utilisera son benchmark boutique sans attendre
        return None

    def _background_worker(self) -> None:
        """
        Traite discrètement en arrière-plan les rafraîchissements de prix sur Vinted
        sans jamais ralentir le radar ni les juges.
        """
        while True:
            try:
                item = self._bg_queue.get()
                brand, cat, scraper, domain, extra_kw = item

                cat_term = CATEGORY_SEARCH_TERMS.get(cat, cat)
                query = f"{brand} {cat_term}".strip()
                if extra_kw:
                    query += f" {extra_kw}".strip()

                search_cfg = {
                    "name": f"LiveMarket_bg_{query}",
                    "search_text": query,
                    "order": "relevance"
                }

                # Pause discrète de 3s pour ne pas saturer le rate limiter du RADAR
                time.sleep(3.0)

                items = scraper.search_items(search_cfg, priority="low")
                if items:
                    prices = []
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

                    if len(prices) >= 3:
                        arr = np.array(prices, dtype=np.float32)
                        p98 = float(np.percentile(arr, 98))
                        f_arr = arr[arr <= p98]
                        cache_key = f"{domain}_{brand.lower()}_{cat.lower()}"
                        res = {
                            "brand": brand,
                            "category": cat,
                            "search_query": query,
                            "sample_count": len(f_arr),
                            "median_price": round(float(np.median(f_arr)), 2),
                            "p25_price": round(float(np.percentile(f_arr, 25)), 2),
                            "p75_price": round(float(np.percentile(f_arr, 75)), 2),
                            "min_price": round(float(np.min(f_arr)), 2),
                            "max_price": round(float(np.max(f_arr)), 2),
                            "sample_titles": [],
                            "cached_at": time.time(),
                            "domain": domain,
                            "source": "vinted_background_sync"
                        }
                        with self._lock:
                            self._cache[cache_key] = res
                        self._save_entry_to_db(res, cache_key)
                        logger.info(f"📥 [LiveMarket Sync Fond] '{query}' actualisé : Médiane {res['median_price']}€ ({len(f_arr)} annonces)")

                cache_key = f"{domain}_{brand.lower()}_{cat.lower()}"
                self._bg_pending_keys.discard(cache_key)
                self._bg_queue.task_done()
            except Exception as e:
                logger.debug(f"Erreur LiveMarket _background_worker: {e}")
                time.sleep(2.0)


_LIVE_MARKET_INSTANCE: Optional[LiveMarketService] = None
_LIVE_MARKET_LOCK = threading.Lock()


def get_live_market_service() -> LiveMarketService:
    global _LIVE_MARKET_INSTANCE
    if _LIVE_MARKET_INSTANCE is None:
        with _LIVE_MARKET_LOCK:
            if _LIVE_MARKET_INSTANCE is None:
                _LIVE_MARKET_INSTANCE = LiveMarketService()
    return _LIVE_MARKET_INSTANCE
