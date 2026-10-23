"""Import prioritaire des fichiers CSV boutique vers Parquet (Correctif 1).

Source :
data/import/sales.csv
data/import/purchases.csv
data/import/wardrobe.csv
data/import/favourites.csv

Colonnes attendues :
id, title, price, date, brand, size, status, photo_url, image_path

Destination :
data/sales.parquet
data/purchases.parquet
data/wardrobe.parquet
data/favourites.parquet
"""

import os
import sys
import logging
from typing import Dict, Any, List, Optional

# Assurer l'accès au module racine src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pandas as pd
import numpy as np

from src.scoring.taxonomy import detect_category, normalize_brand, normalize_size

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ImportShopCSV")

IMPORT_DIR = "data/import"
DATA_DIR = "data"


def import_csv_to_parquet(name: str) -> Optional[pd.DataFrame]:
    """Importe un fichier CSV depuis data/import/{name}.csv et génère data/{name}.parquet."""
    csv_path = os.path.join(IMPORT_DIR, f"{name}.csv")
    parquet_path = os.path.join(DATA_DIR, f"{name}.parquet")

    if not os.path.exists(csv_path):
        return None

    try:
        df = pd.read_csv(csv_path, encoding="utf-8")
    except UnicodeDecodeError:
        try:
            df = pd.read_csv(csv_path, encoding="latin1")
        except Exception as e:
            logger.error(f"Impossible de lire {csv_path}: {e}")
            return None

    if len(df) == 0:
        logger.warning(f"Le fichier {csv_path} est vide.")
        return None

    # Normalisation des colonnes
    cols = {c.lower().strip(): c for c in df.columns}
    
    id_col = cols.get("id") or cols.get("item_id")
    title_col = cols.get("title") or cols.get("titre") or cols.get("name")
    price_col = cols.get("price") or cols.get("prix")
    date_col = cols.get("date") or cols.get("created_at") or cols.get("sold_at")
    brand_col = cols.get("brand") or cols.get("marque") or cols.get("brand_title")
    size_col = cols.get("size") or cols.get("taille")
    status_col = cols.get("status") or cols.get("etat") or cols.get("state")
    photo_col = cols.get("photo_url") or cols.get("url_photo") or cols.get("photo")
    image_path_col = cols.get("image_path") or cols.get("local_image")

    rows = []
    for _, r in df.iterrows():
        item_id = str(r[id_col]) if id_col and pd.notna(r[id_col]) else str(np.random.randint(1000000000, 9999999999))
        title = str(r[title_col]) if title_col and pd.notna(r[title_col]) else ""
        try:
            price = float(r[price_col]) if price_col and pd.notna(r[price_col]) else 0.0
        except (ValueError, TypeError):
            price = 0.0

        date_val = str(r[date_col]) if date_col and pd.notna(r[date_col]) else "2026-01-01"
        brand_raw = str(r[brand_col]) if brand_col and pd.notna(r[brand_col]) else ""
        size_raw = str(r[size_col]) if size_col and pd.notna(r[size_col]) else ""
        status_val = str(r[status_col]).lower() if status_col and pd.notna(r[status_col]) else ("sold" if name == "sales" else "active")
        photo_url = str(r[photo_col]) if photo_col and pd.notna(r[photo_col]) else ""
        image_path = str(r[image_path_col]) if image_path_col and pd.notna(r[image_path_col]) else ""

        # Normalisations
        cat_norm = detect_category(title)
        b_canon, b_line, b_tier = normalize_brand(brand_raw, title)
        s_norm = normalize_size(size_raw, cat_norm)

        # Détermination is_closed
        is_closed = True if (name == "sales" or status_val in ("sold", "closed", "vendu", "vendue", "cloturé", "cloture")) else False

        rows.append({
            "id": item_id,
            "title": title,
            "price": price,
            "date": date_val,
            "created_at": date_val,
            "brand_raw": brand_raw,
            "brand_canonical": b_canon,
            "brand_line": b_line,
            "brand_tier": b_tier,
            "size_raw": size_raw,
            "size_normalized": s_norm,
            "status": status_val,
            "is_closed": is_closed,
            "category_normalized": cat_norm,
            "photo_url": photo_url,
            "image_path": image_path
        })

    out_df = pd.DataFrame(rows)
    os.makedirs(DATA_DIR, exist_ok=True)
    out_df.to_parquet(parquet_path, index=False)
    logger.info(f"Importé {len(out_df)} lignes depuis {csv_path} vers {parquet_path}")
    return out_df


def ensure_shop_data_imported() -> Dict[str, int]:
    """Exécute l'import prioritaire pour les 4 datasets."""
    os.makedirs(IMPORT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    counts = {}
    datasets = ["sales", "purchases", "wardrobe", "favourites"]
    for ds in datasets:
        df = import_csv_to_parquet(ds)
        if df is not None:
            counts[ds] = len(df)
        else:
            p_path = os.path.join(DATA_DIR, f"{ds}.parquet")
            if os.path.exists(p_path):
                try:
                    existing = pd.read_parquet(p_path)
                    counts[ds] = len(existing)
                except Exception:
                    counts[ds] = 0
            else:
                counts[ds] = 0
    return counts


if __name__ == "__main__":
    res = ensure_shop_data_imported()
    print("État des imports Parquet :", res)
