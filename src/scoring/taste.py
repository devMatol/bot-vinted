"""Module de Goût 'Rita' (Lot Taste 3).

Fournit :
- get_taste_score(embedding, category) -> float [0.0 - 1.0]
- is_taste_model_valid() -> bool
- find_top_matching_favourites(embedding, top_k=2) -> list[dict]
"""

import os
import json
import logging
from typing import Dict, Any, List, Optional, Tuple

import sqlite3
import threading
from collections import deque

import numpy as np
import joblib

logger = logging.getLogger("VintedBot.Scoring.Taste")

MODEL_PATH = "models/taste_model.joblib"
META_PATH = "models/taste_meta.json"
DATASET_PATH = "data/taste_dataset.npz"

_TASTE_MODEL = None
_TASTE_ENCODER = None
_TASTE_META = None
_IS_VALID = False

# Cache pour les favoris de Rita (pour comparables cosinus dans l'alerte)
_FAVOURITES_EMBEDDINGS: Optional[np.ndarray] = None
_FAVOURITES_METADATA: List[Dict[str, Any]] = []


def init_taste_scorer() -> bool:
    """Charge le modèle de goût et l'index des favoris."""
    global _TASTE_MODEL, _TASTE_ENCODER, _TASTE_META, _IS_VALID
    global _FAVOURITES_EMBEDDINGS, _FAVOURITES_METADATA

    if not os.path.exists(MODEL_PATH) or not os.path.exists(META_PATH):
        logger.warning(f"Modèle de goût absent ({MODEL_PATH} ou {META_PATH}).")
        _IS_VALID = False
        return False

    try:
        with open(META_PATH, "r", encoding="utf-8") as f:
            _TASTE_META = json.load(f)

        _IS_VALID = bool(_TASTE_META.get("valid", False))
        if not _IS_VALID:
            logger.warning("Modèle de goût marqué comme invalide (AUC < 0.70).")
            return False

        # Vérification stricte de cohérence du modèle de vision
        expected_vision = "hf-hub:Marqo/marqo-fashionSigLIP"
        if os.path.exists("config.json"):
            try:
                with open("config.json", "r", encoding="utf-8") as f_cfg:
                    cfg = json.load(f_cfg)
                    expected_vision = cfg.get("vision_model") or cfg.get("clip_model_name", expected_vision)
            except Exception:
                pass

        saved_vision = _TASTE_META.get("vision_model")
        if saved_vision and saved_vision != expected_vision:
            logger.warning(
                f"Modèle de goût incompatible : entraîné avec '{saved_vision}', "
                f"mais le modèle actif est '{expected_vision}'. Ré-entraînement requis."
            )
            _IS_VALID = False
            return False

        bundle = joblib.load(MODEL_PATH)
        _TASTE_MODEL = bundle.get("calibrated_model")
        _TASTE_ENCODER = bundle.get("encoder")

        logger.info(f"Modèle de goût 'Rita' chargé avec succès (AUC={_TASTE_META.get('auc')}, P@10%={_TASTE_META.get('precision_at_10pct')}).")

        # Chargement des favoris pour la recherche par similarité cosinus
        _init_favourites_index()
        return True
    except Exception as e:
        logger.error(f"Erreur au chargement du modèle de goût: {e}")
        _IS_VALID = False
        return False


def _init_favourites_index():
    """Charge les favoris de Rita pour la recherche de pièces similaires."""
    global _FAVOURITES_EMBEDDINGS, _FAVOURITES_METADATA

    if not os.path.exists(DATASET_PATH):
        return

    try:
        data = np.load(DATASET_PATH, allow_pickle=True)
        sources = data["sources"]
        labels = data["labels"]
        embs = data["embeddings"]
        ids = data["ids"]

        # Favoris ou positifs
        fav_mask = (sources == "favoris") & (labels == 1)
        if not np.any(fav_mask):
            fav_mask = (labels == 1)

        fav_embs = embs[fav_mask]
        fav_ids = ids[fav_mask]

        # Normalisation L2
        norms = np.linalg.norm(fav_embs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        _FAVOURITES_EMBEDDINGS = (fav_embs / norms).astype(np.float32)

        # Charger titres et prix depuis favourites.parquet si disponible
        fav_info_map = {}
        if os.path.exists("data/favourites.parquet"):
            import pandas as pd
            df_fav = pd.read_parquet("data/favourites.parquet")
            for _, r in df_fav.iterrows():
                fav_info_map[str(r["id"])] = {
                    "title": str(r.get("title") or ""),
                    "price": float(r.get("price") or 0.0),
                    "brand": str(r.get("brand_canonical") or "")
                }

        _FAVOURITES_METADATA = []
        for iid in fav_ids:
            iid_str = str(iid)
            meta = fav_info_map.get(iid_str, {"title": f"Favori #{iid_str}", "price": 0.0, "brand": ""})
            _FAVOURITES_METADATA.append(meta)

        logger.info(f"Index de {len(_FAVOURITES_METADATA)} favoris de Rita prêt pour comparables cosinus.")
    except Exception as e:
        logger.debug(f"Erreur indexation des favoris de Rita: {e}")


def is_taste_model_valid() -> bool:
    """Retourne True si le modèle de goût est prêt et validé."""
    if _TASTE_MODEL is None:
        init_taste_scorer()
    return _IS_VALID


# --- Calibrage relatif (ajout 23/10) -------------------------------------------------------
# Le modèle est entraîné "favoris de Rita" contre "annonces des recherches marques" : il donne
# donc une proba brute proche de 0 à presque toutes les annonces que le bot voit (vu en prod :
# 0-1 % sur la majorité). On convertit la proba brute en RANG PERCENTILE parmi les 1000
# dernières annonces vues : 0.9 = l'annonce plaît plus que 90 % de ce que le bot voit passer.
RAW_BUFFER_PATH = "data/taste_raw_buffer.npy"
_RAW_BUFFER: deque = deque(maxlen=1000)
_RAW_LOCK = threading.Lock()
_RAW_WARMED = False
_RAW_SINCE_SAVE = 0
LAST_RAW_SCORE: Optional[float] = None


def _warmup_raw_buffer():
    global _RAW_WARMED
    if _RAW_WARMED:
        return
    _RAW_WARMED = True
    try:
        if os.path.exists(RAW_BUFFER_PATH):
            for v in np.load(RAW_BUFFER_PATH).tolist()[-1000:]:
                _RAW_BUFFER.append(float(v))
            logger.info(f"Goût Rita : {len(_RAW_BUFFER)} scores bruts rechargés pour le percentile.")
            return
        con = sqlite3.connect("vinted_bot.db", timeout=30.0)
        rows = con.execute("SELECT details_json FROM decisions WHERE details_json LIKE '%taste_score%' ORDER BY id DESC LIMIT 1000").fetchall()
        con.close()
        for (dj,) in rows:
            try:
                v = json.loads(dj or "{}").get("taste_score")
                if v is not None:
                    _RAW_BUFFER.append(float(v))
            except Exception:
                pass
        logger.info(f"Goût Rita : {len(_RAW_BUFFER)} scores bruts récupérés depuis la table decisions.")
    except Exception as e:
        logger.warning(f"Goût Rita : préchauffage du percentile impossible ({e}).")


def _to_percentile(raw: float) -> float:
    global _RAW_SINCE_SAVE
    with _RAW_LOCK:
        _warmup_raw_buffer()
        ref = list(_RAW_BUFFER)
        _RAW_BUFFER.append(raw)
        _RAW_SINCE_SAVE += 1
        if _RAW_SINCE_SAVE >= 50:
            _RAW_SINCE_SAVE = 0
            try:
                np.save(RAW_BUFFER_PATH, np.array(_RAW_BUFFER, dtype=np.float32))
            except Exception:
                pass
    if len(ref) < 50:
        return raw
    below = sum(1 for v in ref if v < raw)
    equal = sum(1 for v in ref if v == raw)
    return (below + 0.5 * equal) / len(ref)


def get_taste_score(embedding: Optional[np.ndarray], category: str) -> Optional[float]:
    """
    Calcule la probabilité d'affinité avec le goût de Rita (entre 0.0 et 1.0).
    Retourne None si l'embedding est absent ou si le modèle est invalide.
    """
    if embedding is None:
        return None

    if _TASTE_MODEL is None:
        if not init_taste_scorer():
            return None

    if not _IS_VALID:
        return None

    try:
        emb = embedding.astype(np.float32).reshape(1, -1)
        norm = np.linalg.norm(emb)
        if norm > 1e-6:
            emb = emb / norm

        cat_str = str(category) if category else "inconnu"
        cat_encoded = _TASTE_ENCODER.transform([[cat_str]])

        feat = np.hstack([emb, cat_encoded])
        proba = float(_TASTE_MODEL.predict_proba(feat)[0, 1])
        raw = max(0.0, min(1.0, proba))
        global LAST_RAW_SCORE
        LAST_RAW_SCORE = raw
        pct = _to_percentile(raw)
        logger.debug(f"Goût Rita : brut {raw:.4f} -> percentile {pct:.2f}")
        return pct
    except Exception as e:
        logger.debug(f"Erreur prédiction goût Rita: {e}")
        return None


def find_top_matching_favourites(embedding: Optional[np.ndarray], top_k: int = 2) -> List[Dict[str, Any]]:
    """
    Trouve les top_k favoris de Rita les plus proches de l'article par similarité cosinus.
    """
    if embedding is None or _FAVOURITES_EMBEDDINGS is None or len(_FAVOURITES_METADATA) == 0:
        return []

    try:
        emb = embedding.astype(np.float32).flatten()
        norm = np.linalg.norm(emb)
        if norm > 1e-6:
            emb = emb / norm

        sims = np.dot(_FAVOURITES_EMBEDDINGS, emb)
        top_indices = np.argsort(sims)[::-1][:top_k]

        results = []
        for idx in top_indices:
            score = float(sims[idx])
            meta = _FAVOURITES_METADATA[idx]
            results.append({
                "title": meta.get("title", ""),
                "price": meta.get("price", 0.0),
                "brand": meta.get("brand", ""),
                "similarity": round(score, 3)
            })
        return results
    except Exception as e:
        logger.debug(f"Erreur recherche favoris similaires: {e}")
        return []
