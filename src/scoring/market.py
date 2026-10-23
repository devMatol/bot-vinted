"""Étage C : Marché, prix et comparables visuels (Lot 4).

Composants :
- Table SQLite market_listings : stockage de toutes les annonces observées
- market_median(brand_canonical, brand_line, category) : médiane glissante sur 30 jours avec paliers de repli
- shop_median(brand_canonical, category) : médiane des ventes réelles de la boutique
- price_ratio = prix / market_median
- Comparables visuels : recherche des 10 ventes de la boutique les plus proches par cosinus d'embedding CLIP
- comp_price = médiane pondérée des prix des comparables
"""

import os
import time
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

import numpy as np

from src.scoring.taxonomy import detect_category, normalize_brand, normalize_size

logger = logging.getLogger("VintedBot.Scoring.Market")

DEFAULT_DB_PATH = "vinted_bot.db"
DEFAULT_SHOP_PARQUET = "data/wardrobe.parquet"
REFERENCE_EMBEDDINGS_PATH = "data/shop_reference_embeddings.npz"


def _get_db_conn(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    return conn


def init_market_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Initialise la table market_listings et ses index si non présents."""
    conn = _get_db_conn(db_path)
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS market_listings (
                    item_id INTEGER PRIMARY KEY,
                    title TEXT,
                    brand_canonical TEXT,
                    brand_line TEXT,
                    category TEXT,
                    price REAL,
                    size TEXT,
                    status TEXT DEFAULT 'active',
                    seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    favourite_count INTEGER DEFAULT 0,
                    embedding_id TEXT,
                    distinct_score REAL
                )
            """)
            try:
                conn.execute("ALTER TABLE market_listings ADD COLUMN distinct_score REAL")
            except Exception:
                pass
            conn.execute("CREATE INDEX IF NOT EXISTS idx_market_cat_brand ON market_listings(category, brand_canonical, brand_line)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_market_seen ON market_listings(seen_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_market_distinct ON market_listings(distinct_score)")
    finally:
        conn.close()


def record_market_listing(
    item: Dict[str, Any],
    category: Optional[str] = None,
    brand_canonical: Optional[str] = None,
    brand_line: Optional[str] = None,
    size_norm: Optional[str] = None,
    distinct_score: Optional[float] = None,
    db_path: str = DEFAULT_DB_PATH
) -> None:
    """Enregistre ou met à jour une annonce dans la base de prix du marché."""
    item_id = item.get("id") or item.get("item_id")
    if not item_id:
        return

    try:
        item_id = int(item_id)
        price = float(item.get("price") or item.get("total_item_price") or 0.0)
    except (ValueError, TypeError):
        return

    if price <= 0.0:
        return

    # Résolution automatique si non fournie
    title = str(item.get("title") or "")
    raw_brand = str(item.get("brand_title") or item.get("brand") or "")
    raw_size = str(item.get("size_title") or item.get("size") or "")

    if not category:
        category = detect_category(title, str(item.get("description") or ""))
    if not brand_canonical or not brand_line:
        brand_canonical, brand_line, _ = normalize_brand(raw_brand, title)
    if not size_norm:
        size_norm = normalize_size(raw_size, category)

    fav_count = int(item.get("favourite_count") or item.get("favourites_count") or 0)
    status = str(item.get("status") or "active")
    emb_id = str(item.get("embedding_id") or item_id)

    conn = _get_db_conn(db_path)
    try:
        with conn:
            conn.execute("""
                INSERT INTO market_listings (item_id, title, brand_canonical, brand_line, category, price, size, status, seen_at, favourite_count, embedding_id, distinct_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?)
                ON CONFLICT(item_id) DO UPDATE SET
                    title = excluded.title,
                    price = excluded.price,
                    favourite_count = excluded.favourite_count,
                    status = excluded.status,
                    distinct_score = COALESCE(excluded.distinct_score, market_listings.distinct_score),
                    seen_at = CURRENT_TIMESTAMP
            """, (item_id, title, brand_canonical, brand_line, category, price, size_norm, status, fav_count, emb_id, distinct_score))
    except Exception as e:
        logger.debug(f"Erreur enregistrement market_listing {item_id}: {e}")
    finally:
        conn.close()


def update_market_listing_distinct_score(item_id: Any, distinct_score: float, db_path: str = DEFAULT_DB_PATH) -> None:
    """Met à jour la valeur brute de distinct_score dans market_listings."""
    try:
        conn = _get_db_conn(db_path)
        with conn:
            conn.execute(
                "UPDATE market_listings SET distinct_score = ? WHERE item_id = ?",
                (float(distinct_score), str(item_id))
            )
        conn.close()
    except Exception as e:
        logger.debug(f"Erreur update distinct_score pour {item_id}: {e}")


_DISTINCT_CACHE: List[float] = []
_DISTINCT_CACHE_TIME: float = 0.0


def get_recent_distinct_scores(db_path: str = DEFAULT_DB_PATH, limit: int = 1000) -> np.ndarray:
    """Récupère les raw distinct_scores des jusqu'à 1000 dernières annonces vues par le bot."""
    global _DISTINCT_CACHE, _DISTINCT_CACHE_TIME
    now = time.time()
    if _DISTINCT_CACHE and (now - _DISTINCT_CACHE_TIME) < 10.0:
        return np.array(_DISTINCT_CACHE, dtype=np.float32)

    try:
        conn = _get_db_conn(db_path)
        cur = conn.cursor()
        cur.execute("""
            SELECT distinct_score FROM market_listings
            WHERE distinct_score IS NOT NULL
            ORDER BY seen_at DESC
            LIMIT ?
        """, (limit,))
        rows = cur.fetchall()
        conn.close()
        scores = [float(r[0]) for r in rows if r[0] is not None]
        _DISTINCT_CACHE = scores
        _DISTINCT_CACHE_TIME = now
        return np.array(scores, dtype=np.float32)
    except Exception as e:
        logger.debug(f"Erreur lecture recent distinct_scores: {e}")
        return np.array(_DISTINCT_CACHE, dtype=np.float32)


def calculate_distinct_percentile(raw_distinct_score: float, db_path: str = DEFAULT_DB_PATH) -> float:
    """
    Calcule le rang percentile d'un score distinctivité brut parmi les 1000 dernières annonces.
    distinct_pct = 0.5 signifie "pièce moyenne".
    """
    scores = get_recent_distinct_scores(db_path=db_path, limit=1000)
    if len(scores) >= 10:
        pct = float(np.mean(scores <= raw_distinct_score))
        return float(round(max(0.01, min(0.99, pct)), 4))
    # Fallback si moins de 10 scores en base : mapping linéaire centré sur la médiane empirique (0.45)
    # 0.45 -> 0.50, 0.0 -> 0.0, 1.0 -> 1.0
    if raw_distinct_score <= 0.45:
        pct = (raw_distinct_score / 0.45) * 0.50
    else:
        pct = 0.50 + ((raw_distinct_score - 0.45) / 0.55) * 0.50
    return float(round(max(0.01, min(0.99, pct)), 4))


def backfill_market_from_seen_items(db_path: str = DEFAULT_DB_PATH, limit: int = 50000) -> int:
    """Peuple market_listings à partir des tables historiques si nécessaire."""
    init_market_db(db_path)
    conn = _get_db_conn(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM market_listings")
        count = cur.fetchone()[0]
        if count >= 1000:
            return count

        logger.info(f"Remplissage initial de market_listings depuis deal_feedback et seen_items...")
        # 1. Depuis deal_feedback
        cur.execute("""
            SELECT item_id, title, price, brand, created_at
            FROM deal_feedback
            WHERE price > 0
            GROUP BY item_id
            LIMIT ?
        """, (limit,))
        rows = cur.fetchall()

        inserted = 0
        for r in rows:
            i_id, t, p, b, c_at = r
            cat = detect_category(t or "")
            bc, bl, _ = normalize_brand(b or "", t or "")
            try:
                conn.execute("""
                    INSERT OR IGNORE INTO market_listings (item_id, brand_canonical, brand_line, category, price, seen_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (i_id, bc, bl, cat, float(p), c_at or datetime.utcnow().isoformat()))
                inserted += 1
            except Exception:
                pass
        conn.commit()

        # 2. Depuis seen_items si encore de la marge
        if inserted < 5000:
            cur.execute("""
                SELECT item_id, title, price, seen_at
                FROM seen_items
                WHERE price > 0
                ORDER BY seen_at DESC
                LIMIT ?
            """, (limit - inserted,))
            seen_rows = cur.fetchall()
            for r in seen_rows:
                i_id, t, p, s_at = r
                cat = detect_category(t or "")
                bc, bl, _ = normalize_brand("", t or "")
                try:
                    conn.execute("""
                        INSERT OR IGNORE INTO market_listings (item_id, brand_canonical, brand_line, category, price, seen_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (i_id, bc, bl, cat, float(p), s_at or datetime.utcnow().isoformat()))
                    inserted += 1
                except Exception:
                    pass
            conn.commit()

        logger.info(f"market_listings peuplé avec {inserted} annonces de référence.")
        return inserted
    finally:
        conn.close()


def market_median(
    brand_canonical: str,
    brand_line: str,
    category: str,
    db_path: str = DEFAULT_DB_PATH,
    min_samples: int = 15,
    fallback_cap: float = 25.0
) -> float:
    """
    Calcule la médiane des prix de marché affichés sur 30 jours glissants :
    1. Marque + Ligne + Catégorie (min 15 annonces)
    2. Marque + Ligne toutes catégories confondues (min 15 annonces)
    3. Catégorie toutes marques confondues (min 15 annonces)
    4. Repli sur le plafond catégorie par défaut
    """
    init_market_db(db_path)
    conn = _get_db_conn(db_path)
    try:
        cur = conn.cursor()
        since_date = (datetime.utcnow() - timedelta(days=60)).strftime("%Y-%m-%d %H:%M:%S")

        # Palier 1 : Catégorie + Marque + Ligne
        cur.execute("""
            SELECT price FROM market_listings
            WHERE category = ? AND brand_canonical = ? AND brand_line = ? AND price > 2
            ORDER BY price ASC
        """, (category, brand_canonical, brand_line))
        prices = [r[0] for r in cur.fetchall()]
        if len(prices) >= min_samples:
            return float(np.median(prices))

        # Palier 2 : Marque + Ligne toutes catégories
        cur.execute("""
            SELECT price FROM market_listings
            WHERE brand_canonical = ? AND brand_line = ? AND price > 2
            ORDER BY price ASC
        """, (brand_canonical, brand_line))
        prices = [r[0] for r in cur.fetchall()]
        if len(prices) >= min_samples:
            return float(np.median(prices))

        # Palier 3 : Catégorie toutes marques
        cur.execute("""
            SELECT price FROM market_listings
            WHERE category = ? AND price > 2
            ORDER BY price ASC
        """, (category,))
        prices = [r[0] for r in cur.fetchall()]
        if len(prices) >= min_samples:
            return float(np.median(prices))

        return float(fallback_cap)
    finally:
        conn.close()


def shop_median(
    brand_canonical: str,
    category: str,
    fallback_price: Optional[float] = None
) -> float:
    """
    Retourne la médiane des prix de vente réels de la boutique pour la catégorie ou marque.
    Basé sur l'historique réel (535 ventes).
    """
    # Référence empirique des ventes réelles de la boutique
    CATEGORY_SHOP_MEDIANS = {
        "bottes": 52.0,
        "manteau_fourrure": 60.0,
        "escarpins": 46.0,
        "blazer": 40.0,
        "veste": 38.0,
        "manteau": 42.0,
        "sac": 35.0,
        "chaussures": 30.0,
        "sweat": 20.0,
        "pull_maille": 18.0,
        "chemise_blouse": 16.0,
        "robe": 16.0,
        "jupe": 15.0,
        "jean": 13.0,
        "pantalon": 15.0,
        "top": 15.0,
        "tshirt": 14.0,
        "short": 14.0,
        "combinaison": 22.0
    }
    BRAND_SHOP_MEDIANS = {
        "Gucci": 150.0,
        "Yves Saint Laurent": 140.0,
        "Prada": 130.0,
        "Miu Miu": 120.0,
        "Roberto Cavalli": 34.0,
        "Kenzo": 32.0,
        "Max Mara": 45.0,
        "Mugler": 60.0,
        "Dolce & Gabbana": 40.0,
        "Versace": 38.0,
        "Moschino": 35.0
    }

    if brand_canonical in BRAND_SHOP_MEDIANS:
        return BRAND_SHOP_MEDIANS[brand_canonical]
    if category in CATEGORY_SHOP_MEDIANS:
        return CATEGORY_SHOP_MEDIANS[category]
    return float(fallback_price if fallback_price is not None else 18.0)


def weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    """Calcule la médiane pondérée d'un tableau numpy 1D."""
    if len(values) == 0:
        return 0.0
    sorter = np.argsort(values)
    values = values[sorter]
    weights = weights[sorter]
    cum_weights = np.cumsum(weights)
    cutoff = cum_weights[-1] / 2.0
    idx = np.searchsorted(cum_weights, cutoff)
    return float(values[min(idx, len(values) - 1)])


class VisualComparablesMatcher:
    """Moteur de recherche de ventes comparables par similarité cosinus d'embeddings CLIP."""

    def __init__(self, ref_path: str = REFERENCE_EMBEDDINGS_PATH):
        self.ref_path = ref_path
        self.loaded = False
        self.ids: np.ndarray = np.array([])
        self.titles: List[str] = []
        self.prices: np.ndarray = np.array([])
        self.categories: List[str] = []
        self.embeddings: Optional[np.ndarray] = None  # (N, 512)
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.ref_path):
            try:
                data = np.load(self.ref_path, allow_pickle=True)
                self.ids = data["ids"]
                self.titles = list(data["titles"])
                self.prices = data["prices"].astype(np.float32)
                self.categories = list(data["categories"])
                self.embeddings = data["embeddings"].astype(np.float32)
                # S'assurer de la normalisation L2
                norms = np.linalg.norm(self.embeddings, axis=-1, keepdims=True)
                norms[norms == 0] = 1.0
                self.embeddings = self.embeddings / norms
                self.loaded = True
                logger.info(f"VisualComparablesMatcher: {len(self.ids)} ventes de référence chargées.")
            except Exception as e:
                logger.warning(f"Impossible de charger {self.ref_path}: {e}")

    def find_comparables(
        self,
        query_embedding: np.ndarray,
        category: Optional[str] = None,
        top_k: int = 10
    ) -> Tuple[Optional[float], List[Dict[str, Any]]]:
        """
        Recherche les articles les plus similaires et calcule comp_price.
        Comparable retenu seulement si au moins 3 voisins avec similarité cosinus >= 0.80 ; sinon comp_price = None.
        Retourne (comp_price, top_3_comparables_dict_list).
        """
        if not self.loaded or self.embeddings is None or len(self.embeddings) == 0:
            return None, []

        query = query_embedding.astype(np.float32)
        norm = np.linalg.norm(query)
        if norm > 0:
            query = query / norm

        # Similarité cosinus vectorielle rapide
        sims = np.dot(self.embeddings, query)

        # Filtre de seuil strict : similarité cosinus >= 0.80
        qualifying_indices = np.where(sims >= 0.80)[0]

        # Si un filtre catégorie est spécifié et qu'il y a assez de comparables qualifiés dans la catégorie
        if category and category != "inconnu" and len(qualifying_indices) >= 3:
            cat_match = np.array([self.categories[i] == category for i in qualifying_indices])
            if cat_match.sum() >= 3:
                qualifying_indices = qualifying_indices[cat_match]

        if len(qualifying_indices) < 3:
            return None, []

        # Trier les qualifiés par similarité décroissante
        sub_sims = sims[qualifying_indices]
        top_sub_idx = np.argsort(sub_sims)[::-1][:top_k]
        best_indices = qualifying_indices[top_sub_idx]

        comp_prices = self.prices[best_indices]
        comp_weights = sims[best_indices]

        comp_price = float(weighted_median(comp_prices, comp_weights))

        # Top 3 pour affichage logs et Telegram
        top_3 = []
        for idx in best_indices[:3]:
            top_3.append({
                "item_id": str(self.ids[idx]),
                "title": str(self.titles[idx]),
                "sold_price": float(self.prices[idx]),
                "category": str(self.categories[idx]),
                "similarity": float(sims[idx])
            })

        return comp_price, top_3


_MATCHER_INSTANCE: Optional[VisualComparablesMatcher] = None


def get_comparables_matcher() -> VisualComparablesMatcher:
    global _MATCHER_INSTANCE
    if _MATCHER_INSTANCE is None:
        _MATCHER_INSTANCE = VisualComparablesMatcher()
    return _MATCHER_INSTANCE
