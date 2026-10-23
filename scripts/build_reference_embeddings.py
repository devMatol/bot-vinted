"""Génère l'index d'embeddings de référence pour les comparables visuels de la boutique.

Les références ne contiennent QUE :
- Des ventes réelles (sales.parquet)
- Des articles de vitrine vendus (wardrobe.parquet avec is_closed == True ou status == 'sold')
JAMAIS les annonces vues par le bot ni deal_feedback.
"""

import os
import sys
import glob

# Assurer l'accès au module racine src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
import pandas as pd
import torch
import requests
from PIL import Image

from src.scoring.clip_scorer import get_clip_scorer
from src.scoring.taxonomy import detect_category


def download_image(url: str, dest_path: str, timeout: int = 5) -> bool:
    if not url or os.path.exists(dest_path):
        return os.path.exists(dest_path)
    try:
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200 and len(r.content) > 1000:
            with open(dest_path, "wb") as f:
                f.write(r.content)
            return True
    except Exception:
        pass
    return False


def build_embeddings_index(output_path: str = "data/shop_reference_embeddings.npz"):
    print("Initialisation FashionCLIP...")
    scorer = get_clip_scorer()

    all_ids = []
    all_titles = []
    all_prices = []
    all_categories = []
    all_embeddings = []

    # 1. Ventes réelles de la boutique (sales.parquet)
    sales_path = "data/sales.parquet"
    if os.path.exists(sales_path):
        s_df = pd.read_parquet(sales_path)
        print(f"Traitement de {len(s_df)} ventes réelles de la boutique...")
        for _, row in s_df.iterrows():
            item_id = str(row["id"])
            if item_id in all_ids:
                continue

            # Trouver le chemin de l'image
            img_path = str(row.get("image_path") or "")
            if not os.path.exists(img_path):
                img_path = f"data/images/sales/{item_id}.jpg"
            if not os.path.exists(img_path):
                img_path = f"data/images/wardrobe/{item_id}.jpg"
            
            photo_url = str(row.get("photo_url") or "")
            if not os.path.exists(img_path) and photo_url and photo_url.startswith("http"):
                download_image(photo_url, img_path)

            emb_cache = os.path.join(scorer.embeddings_dir, f"{item_id}.npy")
            try:
                if os.path.exists(emb_cache):
                    emb = np.load(emb_cache).astype(np.float32)
                    if emb.shape[-1] != scorer.embedding_dim:
                        emb = None
                else:
                    emb = None

                if emb is None and os.path.exists(img_path):
                    img = Image.open(img_path).convert("RGB")
                    tensor = scorer.preprocess(img).unsqueeze(0)
                    with torch.no_grad():
                        feat = scorer.model.encode_image(tensor)
                        feat = feat / feat.norm(dim=-1, keepdim=True)
                        emb = feat.squeeze(0).cpu().numpy().astype(np.float32)
                    os.makedirs(scorer.embeddings_dir, exist_ok=True)
                    np.save(emb_cache, emb)
                
                if emb is None:
                    continue

                all_ids.append(item_id)
                all_titles.append(str(row["title"]))
                all_prices.append(float(row["price"]))
                all_categories.append(str(row.get("category_normalized") or detect_category(str(row["title"]))))
                all_embeddings.append(emb)
            except Exception as e:
                print(f"Erreur sur vente {item_id}: {e}")

    # 2. Articles de vitrine VENDUS (wardrobe.parquet où is_closed == True ou status == 'sold')
    wardrobe_path = "data/wardrobe.parquet"
    if os.path.exists(wardrobe_path):
        w_df = pd.read_parquet(wardrobe_path)
        # Filtrer strictement sur les articles vendus
        sold_mask = (w_df.get("is_closed") == True) | (w_df.get("status") == "sold")
        sold_w_df = w_df[sold_mask] if "is_closed" in w_df or "status" in w_df else pd.DataFrame()
        
        print(f"Traitement de {len(sold_w_df)} articles de vitrine vendus...")
        for _, row in sold_w_df.iterrows():
            item_id = str(row["id"])
            if item_id in all_ids:
                continue

            img_path = str(row.get("image_path") or "")
            if not os.path.exists(img_path):
                img_path = f"data/images/wardrobe/{item_id}.jpg"
            photo_url = str(row.get("photo_url") or "")
            if not os.path.exists(img_path) and photo_url and photo_url.startswith("http"):
                download_image(photo_url, img_path)

            emb_cache = os.path.join(scorer.embeddings_dir, f"{item_id}.npy")
            try:
                if os.path.exists(emb_cache):
                    emb = np.load(emb_cache).astype(np.float32)
                    if emb.shape[-1] != scorer.embedding_dim:
                        emb = None
                else:
                    emb = None

                if emb is None and os.path.exists(img_path):
                    img = Image.open(img_path).convert("RGB")
                    tensor = scorer.preprocess(img).unsqueeze(0)
                    with torch.no_grad():
                        feat = scorer.model.encode_image(tensor)
                        feat = feat / feat.norm(dim=-1, keepdim=True)
                        emb = feat.squeeze(0).cpu().numpy().astype(np.float32)
                    os.makedirs(scorer.embeddings_dir, exist_ok=True)
                    np.save(emb_cache, emb)
                
                if emb is None:
                    continue

                all_ids.append(item_id)
                all_titles.append(str(row["title"]))
                all_prices.append(float(row["price"]))
                all_categories.append(str(row.get("category_normalized") or detect_category(str(row["title"]))))
                all_embeddings.append(emb)
            except Exception as e:
                print(f"Erreur sur vitrine vendue {item_id}: {e}")

    if all_embeddings:
        stacked_embeddings = np.stack(all_embeddings).astype(np.float32)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        np.savez_compressed(
            output_path,
            ids=np.array(all_ids),
            titles=np.array(all_titles),
            prices=np.array(all_prices, dtype=np.float32),
            categories=np.array(all_categories),
            embeddings=stacked_embeddings
        )
        print(f"Index sauvegardé dans {output_path} avec {len(all_ids)} ventes réelles.")
    else:
        print("Aucun embedding de vente réelle à sauvegarder.")


if __name__ == "__main__":
    build_embeddings_index()
