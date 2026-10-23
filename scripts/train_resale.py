"""Entraînement des modèles de revente quantile HistGradientBoosting (Lot 4 - Révisé).

Règles :
- Entraîne uniquement sur les ventes réelles (data/sales.parquet).
- Retire toute variable dérivée du prix de l'annonce.
- Si moins de 200 ventes exploitables ou MAE < 2 €, le modèle est marqué invalide ("valid": false)
  et sera ignoré au runtime.
"""

import os
import sys
import json
import logging
from datetime import datetime

# Assurer l'accès au module racine src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
import pandas as pd
import joblib
from sklearn.decomposition import PCA
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import median_absolute_error

from src.scoring.taxonomy import detect_category, normalize_brand, normalize_size
from src.scoring.rules import evaluate_rules

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("TrainResale")


def load_real_sales_dataset() -> pd.DataFrame:
    """Charge uniquement les ventes réelles depuis data/sales.parquet."""
    sales_path = "data/sales.parquet"
    if not os.path.exists(sales_path):
        logger.error(f"Fichier {sales_path} introuvable.")
        return pd.DataFrame()

    df = pd.read_parquet(sales_path)
    # Filtrer les ventes avec prix valide (> 0)
    df = df[df["price"] > 0].copy()
    logger.info(f"Chargé {len(df)} ventes réelles depuis {sales_path}.")
    return df


def train_models():
    os.makedirs("models", exist_ok=True)
    df = load_real_sales_dataset()

    n_samples = len(df)
    if n_samples < 200:
        logger.warning(f"Moins de 200 ventes exploitables ({n_samples} < 200). Le modèle sera marqué INVALIDE.")
        meta = {
            "valid": False,
            "reason": f"Moins de 200 ventes exploitables ({n_samples})",
            "trained_at": datetime.utcnow().isoformat(),
            "n_samples": n_samples
        }
        with open("models/resale_meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        return

    embeddings_list = []
    features_list = []
    targets = []
    categories = []

    cat_set = set()
    brand_set = set()
    line_set = set()
    mat_set = {"inconnu", "leather", "suede", "fur", "silk_satin", "sequins", "denim", "wool_knit", "cotton_jersey", "synthetic"}
    size_set = set()

    logger.info("Extraction des variables (strictement indépendantes du prix d'annonce)...")
    for _, row in df.iterrows():
        item_id = str(row["id"])
        title = str(row["title"])
        sold_price = float(row["price"])
        raw_brand = str(row.get("brand_raw") or row.get("brand") or "")
        raw_size = str(row.get("size_raw") or row.get("size") or "")

        cat = str(row.get("category_normalized") or detect_category(title))
        brand_canon, brand_line, tier = normalize_brand(raw_brand, title)
        size_norm = normalize_size(raw_size, cat)

        cat_set.add(cat)
        brand_set.add(brand_canon)
        line_set.add(brand_line)
        size_set.add(size_norm)

        # Évaluation des règles
        fake_item = {"title": title, "brand_title": brand_canon, "size_title": size_norm}
        rule_res = evaluate_rules(fake_item)
        bonus_score = sum(rule_res.bonus_hits.values())
        malus_score = sum(rule_res.malus_hits.values())

        # Chargement de l'embedding si présent
        emb_path = f"data/embeddings/{item_id}.npy"
        if os.path.exists(emb_path):
            try:
                emb = np.load(emb_path).astype(np.float32)
                if len(emb) != 512:
                    emb = np.zeros(512, dtype=np.float32)
            except Exception:
                emb = np.zeros(512, dtype=np.float32)
        else:
            emb = np.zeros(512, dtype=np.float32)

        # Mois de la vente si disponible
        month = 10
        dt_str = str(row.get("date") or row.get("created_at") or "")
        if dt_str:
            try:
                month = pd.to_datetime(dt_str).month
            except Exception:
                pass

        embeddings_list.append(emb)
        features_list.append({
            "category": cat,
            "brand_canonical": brand_canon,
            "brand_line": brand_line,
            "tier": tier,
            "material_top": "inconnu",
            "size_normalized": size_norm,
            "distinct_score": 0.5,
            "month": month,
            "bonus_score": bonus_score,
            "malus_score": malus_score,
            "desc_len": len(title)
        })
        # Cible : log du prix réel de revente
        targets.append(np.log(max(sold_price, 2.0)))
        categories.append(cat)

    # 1. Encodage catégoriel
    def build_mapping(s):
        m = {v: idx + 1 for idx, v in enumerate(sorted(list(s)))}
        m["__unknown__"] = 0
        return m

    cat_map = build_mapping(cat_set)
    brand_map = build_mapping(brand_set)
    line_map = build_mapping(line_set)
    mat_map = build_mapping(mat_set)
    size_map = build_mapping(size_set)

    encoders = {
        "category": cat_map,
        "brand_canonical": brand_map,
        "brand_line": line_map,
        "material_top": mat_map,
        "size_normalized": size_map
    }

    # 2. PCA sur les embeddings (32 composantes)
    all_embs = np.stack(embeddings_list).astype(np.float32)
    n_pca = min(32, len(all_embs), all_embs.shape[1])
    pca = PCA(n_components=n_pca, random_state=42)
    embs_32 = pca.fit_transform(all_embs)
    if n_pca < 32:
        pad = np.zeros((len(embs_32), 32 - n_pca), dtype=np.float32)
        embs_32 = np.hstack([embs_32, pad])

    # 3. Construction de la matrice X
    X_rows = []
    for idx, f in enumerate(features_list):
        num_vec = [
            f["tier"],
            f["distinct_score"],
            f["month"],
            f["bonus_score"],
            f["malus_score"],
            float(f["desc_len"]),
            cat_map.get(f["category"], 0),
            brand_map.get(f["brand_canonical"], 0),
            line_map.get(f["brand_line"], 0),
            mat_map.get(f["material_top"], 0),
            size_map.get(f["size_normalized"], 0)
        ]
        row_vec = np.hstack([num_vec, embs_32[idx]])
        X_rows.append(row_vec)

    X = np.stack(X_rows).astype(np.float32)
    y = np.array(targets, dtype=np.float32)
    y_true_eur = np.exp(y)

    logger.info(f"Matrice d'apprentissage : {X.shape}, cible y : {len(y)}")

    # 4. Entraînement et validation croisée sans fuite (5-fold Out-Of-Fold)
    from sklearn.model_selection import KFold

    kf = KFold(n_splits=5, shuffle=True, random_state=42)
    oof_pred_q30 = np.zeros(len(y), dtype=np.float32)
    oof_pred_q50 = np.zeros(len(y), dtype=np.float32)

    for train_idx, val_idx in kf.split(X):
        m_q30_cv = HistGradientBoostingRegressor(
            loss="quantile",
            quantile=0.3,
            max_iter=60,
            min_samples_leaf=15,
            l2_regularization=1.0,
            random_state=42
        )
        m_q50_cv = HistGradientBoostingRegressor(
            loss="quantile",
            quantile=0.5,
            max_iter=60,
            min_samples_leaf=15,
            l2_regularization=1.0,
            random_state=42
        )
        m_q30_cv.fit(X[train_idx], y[train_idx])
        m_q50_cv.fit(X[train_idx], y[train_idx])

        oof_pred_q30[val_idx] = m_q30_cv.predict(X[val_idx])
        oof_pred_q50[val_idx] = m_q50_cv.predict(X[val_idx])

    # 5. Évaluation des erreurs RÉELLES hors-échantillon (Out-of-Fold)
    oof_pred_q30_eur = np.exp(oof_pred_q30)
    oof_pred_q50_eur = np.exp(oof_pred_q50)

    global_mae_q30 = float(median_absolute_error(y_true_eur, oof_pred_q30_eur))
    global_mae_q50 = float(median_absolute_error(y_true_eur, oof_pred_q50_eur))

    logger.info(f"Erreur Médiane Absolue Hors-Échantillon (OOF) q30: {global_mae_q30:.2f} €")
    logger.info(f"Erreur Médiane Absolue Hors-Échantillon (OOF) q50: {global_mae_q50:.2f} €")

    # Modèles finaux entraînés sur l'ensemble complet
    model_q30 = HistGradientBoostingRegressor(
        loss="quantile",
        quantile=0.3,
        max_iter=60,
        min_samples_leaf=15,
        l2_regularization=1.0,
        random_state=42
    )
    model_q30.fit(X, y)

    model_q50 = HistGradientBoostingRegressor(
        loss="quantile",
        quantile=0.5,
        max_iter=60,
        min_samples_leaf=15,
        l2_regularization=1.0,
        random_state=42
    )
    model_q50.fit(X, y)

    # Vérification règle : Si MAE < 2 € -> fuite de données soupçonnée -> marquer invalide
    is_valid = True
    if global_mae_q50 < 2.0:
        logger.warning(f"MAE q50 trop basse ({global_mae_q50:.2f} € < 2.0 €), soupçon de fuite de données -> modèle marqué INVALIDE.")
        is_valid = False
    elif n_samples < 200:
        is_valid = False

    # Erreur hors-échantillon par catégorie
    cat_errors = {}
    for cat in sorted(list(cat_set)):
        mask = np.array([c == cat for c in categories])
        if mask.sum() >= 5:
            cat_mae = float(median_absolute_error(y_true_eur[mask], oof_pred_q50_eur[mask]))
            cat_errors[cat] = round(cat_mae, 2)
            logger.info(f"  * {cat:16s} (n={mask.sum()}): MAE OOF={cat_mae:.2f} €")

    # 6. Sauvegarde
    joblib.dump(model_q30, "models/resale_q30.joblib")
    joblib.dump(model_q50, "models/resale_q50.joblib")
    joblib.dump({"pca": pca, "encoders": encoders}, "models/resale_pipeline.joblib")

    meta = {
        "valid": is_valid,
        "trained_at": datetime.utcnow().isoformat(),
        "n_samples": n_samples,
        "global_mae_q30_eur": round(global_mae_q30, 2),
        "global_mae_q50_eur": round(global_mae_q50, 2),
        "category_mae_eur": cat_errors,
        "n_pca_components": 32,
        "clip_labels_version": "v2_marqo_fashionclip"
    }
    with open("models/resale_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    logger.info(f"Modèles de revente sauvegardés avec succès (valid={is_valid}).")


if __name__ == "__main__":
    train_models()
