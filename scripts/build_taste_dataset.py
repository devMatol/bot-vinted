"""Construction du jeu de données d'apprentissage du goût 'Rita' (v2 strict).

Règles absolues :
- Aucune donnée inventée, simulée ou générée.
- POSITIFS :
  * data/favourites.parquet (497 favoris de Rita, poids 1.0)
  * data/sales.parquet avec photo (poids 1.5)
  * data/wardrobe.parquet is_closed=True avec photo (53 articles, poids 1.5)
  * deal_feedback MUST_BUY UNIQUEMENT si source = 'telegram_click' (poids 3.0)
- NÉGATIFS :
  * deal_feedback REJECTED UNIQUEMENT si source = 'telegram_click' (poids 3.0)
  * Marché : tirage aléatoire de 3x les positifs parmi les annonces des recherches
    ACTUELLEMENT actives dans config.json (poids 1.0), en excluant tout id positif.
- Plus JAMAIS de verdict Gemini ni de décision moteur comme étiquettes.
- Écrit data/taste_dataset.npz
- Si moins de 300 positifs avec image : arrêt immédiat.
"""

import os
import sys
import json
import random
import sqlite3
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, List, Optional, Tuple, Set

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
import pandas as pd
import requests
from PIL import Image
import torch

from src.scoring.taxonomy import detect_category, normalize_brand
from src.scoring.clip_scorer import get_clip_scorer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("BuildTasteDataset")

EMBEDDINGS_DIR = "data/embeddings"
IMAGES_DIR = "data/images"


def get_active_search_criteria(config: Dict[str, Any]) -> Tuple[Set[str], List[str]]:
    """Extrait les marques et mots-clés des recherches actuellement actives dans config.json."""
    active_brands = set()
    active_keywords = []

    for s in config.get("searches", []):
        if not s.get("enabled", True):
            continue
        name = str(s.get("name") or "").lower()
        stext = str(s.get("search_text") or "").lower()
        bc, _, _ = normalize_brand(stext, name)
        if bc and bc != "Sans marque":
            active_brands.add(bc.lower())

        for kw in ["fourrure", "pelliccia", "manteau", "laine", "coat", "blazer", "cuir", "leather", "veste"]:
            if kw in name or kw in stext:
                active_keywords.append(kw)

    return active_brands, list(set(active_keywords))


def is_active_search_match(title: str, brand: str, active_brands: Set[str], active_keywords: List[str]) -> bool:
    """Vérifie si une annonce appartient aux recherches actuellement actives."""
    t_low = title.lower()
    b_low = brand.lower()
    if any(b in b_low or b in t_low for b in active_brands):
        return True
    if any(kw in t_low for kw in active_keywords):
        return True
    return False


def download_single_image(url: str, save_path: str, session: requests.Session, timeout: int = 10) -> bool:
    """Télécharge une image et la sauvegarde en local."""
    if os.path.exists(save_path) and os.path.getsize(save_path) > 500:
        return True
    try:
        resp = session.get(url, timeout=timeout)
        if resp.status_code == 200 and len(resp.content) > 500:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(resp.content)
            return True
    except Exception:
        pass
    return False


def download_item_images(items_to_download: List[Dict[str, Any]], max_workers: int = 8) -> None:
    """Télécharge les images manquantes en multithread."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    })

    tasks = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for it in items_to_download:
            urls = it.get("urls", [])[:2]
            item_id = it["id"]
            source = it["source"]
            for idx, u in enumerate(urls):
                save_p = os.path.join(IMAGES_DIR, source, f"{item_id}_{idx}.jpg")
                tasks.append(executor.submit(download_single_image, u, save_p, session))

        completed = 0
        total = len(tasks)
        for fut in as_completed(tasks):
            completed += 1
            if completed % 100 == 0 or completed == total:
                logger.info(f"Téléchargement images : {completed}/{total}")


def get_or_compute_embedding(
    item_id: str,
    local_image_paths: List[str],
    clip_scorer
) -> Optional[np.ndarray]:
    """Récupère l'embedding depuis le cache du modèle de vision ou le calcule."""
    cache_path = os.path.join(clip_scorer.embeddings_dir, f"{item_id}.npy")
    if os.path.exists(cache_path):
        try:
            emb = np.load(cache_path).astype(np.float32)
            if emb.ndim == 1 and len(emb) == clip_scorer.embedding_dim:
                norm = np.linalg.norm(emb)
                if norm > 1e-6:
                    return emb / norm
        except Exception:
            pass

    valid_images = []
    for p in local_image_paths:
        if p and os.path.exists(p):
            try:
                img = Image.open(p).convert("RGB")
                valid_images.append(img)
            except Exception:
                pass

    if not valid_images:
        return None

    try:
        tensors = torch.stack([clip_scorer.preprocess(img) for img in valid_images])
        with torch.no_grad():
            raw_feats = clip_scorer.model.encode_image(tensors)
            feats = raw_feats / raw_feats.norm(dim=-1, keepdim=True)
            mean_feat = feats.mean(dim=0, keepdim=True)
            mean_feat = mean_feat / mean_feat.norm(dim=-1, keepdim=True)
            emb = mean_feat.squeeze(0).cpu().numpy().astype(np.float32)

        os.makedirs(clip_scorer.embeddings_dir, exist_ok=True)
        np.save(cache_path, emb)
        return emb
    except Exception as e:
        logger.debug(f"Erreur calcul embedding {item_id}: {e}")
        return None


def main():
    os.makedirs(EMBEDDINGS_DIR, exist_ok=True)
    os.makedirs(IMAGES_DIR, exist_ok=True)

    with open("config.json", "r", encoding="utf-8") as f:
        config = json.load(f)

    active_brands, active_kws = get_active_search_criteria(config)
    logger.info(f"Recherches actives dans config.json : {len(active_brands)} marques, {len(active_kws)} mots-clés.")

    logger.info("Chargement FashionCLIP...")
    clip_scorer = get_clip_scorer(config)

    positives: Dict[str, Dict[str, Any]] = {}

    # 1. Favoris de Rita (data/favourites.parquet, 497 favoris)
    if os.path.exists("data/favourites.parquet"):
        df_fav = pd.read_parquet("data/favourites.parquet")
        logger.info(f"Chargement de {len(df_fav)} favoris...")
        for _, r in df_fav.iterrows():
            iid = str(r["id"])
            u = str(r.get("photo_url") or "").strip()
            title = str(r.get("title") or "")
            cat = str(r.get("category_normalized") or detect_category(title))
            brand = str(r.get("brand_canonical") or normalize_brand(str(r.get("brand_raw") or ""), title)[0])
            positives[iid] = {
                "id": iid,
                "title": title,
                "source": "favoris",
                "label": 1,
                "weight": 1.0,
                "category": cat,
                "brand_canonical": brand,
                "urls": [u] if u.startswith("http") else [],
                "local_images": [os.path.join(IMAGES_DIR, "favoris", f"{iid}_0.jpg")]
            }

    # 2. Ventes de la boutique avec photo (data/sales.parquet)
    if os.path.exists("data/sales.parquet"):
        df_sales = pd.read_parquet("data/sales.parquet")
        for _, r in df_sales.iterrows():
            iid = str(r["id"])
            u = str(r.get("photo_url") or "").strip()
            w_img = f"data/images/wardrobe/{iid}.jpg"
            has_photo = (u.startswith("http")) or os.path.exists(w_img)
            if not has_photo:
                continue

            title = str(r.get("title") or "")
            cat = str(r.get("category_normalized") or detect_category(title))
            brand = str(r.get("brand_canonical") or normalize_brand(str(r.get("brand_raw") or ""), title)[0])
            local_imgs = [w_img] if os.path.exists(w_img) else [os.path.join(IMAGES_DIR, "sales", f"{iid}_0.jpg")]

            positives[iid] = {
                "id": iid,
                "title": title,
                "source": "ventes",
                "label": 1,
                "weight": 1.5,
                "category": cat,
                "brand_canonical": brand,
                "urls": [u] if u.startswith("http") else [],
                "local_images": local_imgs
            }

    # 3. Vitrine vendue avec photo (data/wardrobe.parquet, is_closed=True)
    if os.path.exists("data/wardrobe.parquet"):
        df_w = pd.read_parquet("data/wardrobe.parquet")
        closed = df_w[df_w.get("is_closed") == True]
        for _, r in closed.iterrows():
            iid = str(r["id"])
            w_img = str(r.get("image_path") or f"data/images/wardrobe/{iid}.jpg")
            if not os.path.exists(w_img):
                continue

            title = str(r.get("title") or "")
            cat = str(r.get("category_normalized") or detect_category(title))
            brand = str(r.get("brand_canonical") or normalize_brand(str(r.get("brand_raw") or ""), title)[0])

            positives[iid] = {
                "id": iid,
                "title": title,
                "source": "vitrine_vendue",
                "label": 1,
                "weight": 1.5,
                "category": cat,
                "brand_canonical": brand,
                "urls": [],
                "local_images": [w_img]
            }

    # 4. MUST_BUY UNIQUEMENT si source = 'telegram_click' (pas de verdict Gemini, pas de décision moteur)
    conn = sqlite3.connect("vinted_bot.db")
    cur = conn.cursor()
    cur.execute("""
        SELECT item_id, title, brand, photo_urls
        FROM deal_feedback
        WHERE classification = 'MUST_BUY' AND source = 'telegram_click'
    """)
    for r in cur.fetchall():
        iid = str(r[0])
        title = str(r[1] or "")
        cat = detect_category(title)
        bc, _, _ = normalize_brand(str(r[2] or ""), title)

        urls = []
        try:
            raw_u = json.loads(r[3]) if r[3] else []
            if isinstance(raw_u, list):
                urls = [u for u in raw_u if isinstance(u, str) and u.startswith("http")]
        except Exception:
            pass

        positives[iid] = {
            "id": iid,
            "title": title,
            "source": "must_buy",
            "label": 1,
            "weight": 3.0,
            "category": cat,
            "brand_canonical": bc,
            "urls": urls,
            "local_images": [
                os.path.join(IMAGES_DIR, "must_buy", f"{iid}_0.jpg"),
                os.path.join(IMAGES_DIR, "must_buy", f"{iid}_1.jpg")
            ]
        }

    positive_ids = set(positives.keys())
    logger.info(f"Total positifs candidats réels (dédupliqués) : {len(positives)}")

    # Téléchargement photos manquantes si nécessaire
    to_download = []
    for it in positives.values():
        iid = it["id"]
        if os.path.exists(os.path.join(clip_scorer.embeddings_dir, f"{iid}.npy")):
            continue
        if any(os.path.exists(p) for p in it["local_images"]):
            continue
        if it["urls"]:
            to_download.append(it)

    if to_download:
        logger.info(f"Téléchargement de {len(to_download)} positifs sans image locale...")
        download_item_images(to_download, max_workers=8)

    # Récupération/calcul des embeddings positifs
    valid_positives = []
    for it in positives.values():
        emb = get_or_compute_embedding(it["id"], it["local_images"], clip_scorer)
        if emb is not None:
            it["embedding"] = emb
            valid_positives.append(it)

    n_pos = len(valid_positives)
    logger.info(f"Positifs réels avec embedding validé : {n_pos}")

    if n_pos < 300:
        logger.error(f"ARRÊT STRICT : Moins de 300 positifs avec image trouvés ({n_pos} < 300).")
        sys.exit(1)

    # 5. REJECTED UNIQUEMENT si source = 'telegram_click' (pas de faux rejets automatiques)
    cur.execute("""
        SELECT item_id, title, brand, photo_urls
        FROM deal_feedback
        WHERE classification = 'REJECTED' AND source = 'telegram_click'
    """)
    valid_rejected = []
    for r in cur.fetchall():
        iid = str(r[0])
        if iid in positive_ids:
            continue
        title = str(r[1] or "")
        cat = detect_category(title)
        bc, _, _ = normalize_brand(str(r[2] or ""), title)
        local_imgs = [
            os.path.join(IMAGES_DIR, "rejected", f"{iid}_0.jpg"),
            os.path.join(IMAGES_DIR, "rejected", f"{iid}_1.jpg")
        ]
        emb = get_or_compute_embedding(iid, local_imgs, clip_scorer)
        if emb is not None:
            valid_rejected.append({
                "id": iid,
                "title": title,
                "source": "rejected",
                "label": 0,
                "weight": 3.0,
                "category": cat,
                "brand_canonical": bc,
                "embedding": emb
            })

    logger.info(f"Négatifs REJECTED (clics réels Telegram) : {len(valid_rejected)}")

    # 6. Négatifs marché : Tirage aléatoire de 3x les positifs parmi les recherches ACTIVES
    target_market_count = 3 * n_pos
    logger.info(f"Tirage de {target_market_count} négatifs marché (3 x {n_pos} positifs) parmi les recherches actives...")

    cur.execute("""
        SELECT m.item_id, m.title, m.brand_canonical, m.category, d.photo_urls
        FROM market_listings m
        JOIN deal_feedback d ON m.item_id = d.item_id
        WHERE m.price > 0 AND d.photo_urls IS NOT NULL
    """)
    all_mkt = cur.fetchall()
    conn.close()

    market_candidates = []
    for r in all_mkt:
        iid = str(r[0])
        if iid in positive_ids:
            continue
        t = str(r[1] or "")
        b = str(r[2] or "")
        if not is_active_search_match(t, b, active_brands, active_kws):
            continue

        raw_urls = []
        try:
            parsed = json.loads(r[4]) if r[4] else []
            if isinstance(parsed, list):
                raw_urls = [u for u in parsed if isinstance(u, str) and u.startswith("http")]
        except Exception:
            pass

        loc_imgs = []
        for cand_dir in ["market", "feedback", "rejected"]:
            p = os.path.join(IMAGES_DIR, cand_dir, f"{iid}_0.jpg")
            if os.path.exists(p):
                loc_imgs.append(p)
                break

        if not loc_imgs and not raw_urls:
            continue

        cat = str(r[3] or detect_category(t))
        bc = str(b or normalize_brand("", t)[0])
        market_candidates.append({
            "id": iid,
            "title": t,
            "source": "market",
            "label": 0,
            "weight": 1.0,
            "category": cat,
            "brand_canonical": bc,
            "urls": raw_urls,
            "local_images": loc_imgs or [os.path.join(IMAGES_DIR, "market", f"{iid}_0.jpg")]
        })

    random.seed(42)
    if len(market_candidates) > target_market_count:
        selected_market = random.sample(market_candidates, target_market_count)
    else:
        selected_market = market_candidates
        logger.info(f"Candidats marché disponibles issus des recherches actives : {len(selected_market)}")

    mkt_to_download = []
    for it in selected_market:
        iid = it["id"]
        if os.path.exists(os.path.join(clip_scorer.embeddings_dir, f"{iid}.npy")):
            continue
        if any(os.path.exists(p) for p in it["local_images"]):
            continue
        if it["urls"]:
            mkt_to_download.append(it)

    if mkt_to_download:
        logger.info(f"Téléchargement de {len(mkt_to_download)} images marché pour les négatifs...")
        download_item_images(mkt_to_download, max_workers=8)

    valid_market = []
    for it in selected_market:
        emb = get_or_compute_embedding(it["id"], it["local_images"], clip_scorer)
        if emb is not None:
            it["embedding"] = emb
            valid_market.append(it)

    logger.info(f"Négatifs marché retenus issus des recherches actives : {len(valid_market)}")

    # 7. Assemblage final
    all_items = valid_positives + valid_rejected + valid_market
    random.shuffle(all_items)

    ids = np.array([it["id"] for it in all_items], dtype=object)
    sources = np.array([it["source"] for it in all_items], dtype=object)
    labels = np.array([it["label"] for it in all_items], dtype=np.int32)
    weights = np.array([it["weight"] for it in all_items], dtype=np.float32)
    embeddings = np.stack([it["embedding"] for it in all_items]).astype(np.float32)
    brand_canonical = np.array([it["brand_canonical"] for it in all_items], dtype=object)
    category = np.array([it["category"] for it in all_items], dtype=object)

    out_path = "data/taste_dataset.npz"
    np.savez_compressed(
        out_path,
        ids=ids,
        sources=sources,
        labels=labels,
        weights=weights,
        embeddings=embeddings,
        brand_canonical=brand_canonical,
        category=category
    )
    logger.info(f"Dataset de goût sauvegardé sans fuite dans {out_path} ({len(all_items)} articles).")

    # 8. Affichage du décompte par source et par label
    print("\n" + "=" * 65)
    print("       DÉCOMPTE DU JEU DE DONNÉES DU GOÛT 'RITA' (v2 strict)")
    print("=" * 65)
    df_summary = pd.DataFrame({
        "source": sources,
        "label": labels,
        "weight": weights
    })
    breakdown = df_summary.groupby(["label", "source"]).size().reset_index(name="count")
    for _, row in breakdown.iterrows():
        lbl_str = "POSITIF (1)" if row["label"] == 1 else "NÉGATIF (0)"
        print(f"  {lbl_str:<12} | Source: {row['source']:<15} | Count: {row['count']:>5}")

    print("-" * 65)
    total_pos = (labels == 1).sum()
    total_neg = (labels == 0).sum()
    print(f"  TOTAL POSITIFS : {total_pos}")
    print(f"  TOTAL NÉGATIFS : {total_neg}")
    print(f"  TOTAL GLOBAL   : {len(labels)}")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
