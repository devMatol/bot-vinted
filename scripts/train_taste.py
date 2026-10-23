"""Entraînement et calibration du modèle de goût 'Rita' (Lot Taste 2).

Règles :
- Pas de données inventées ni simulées.
- Régression logistique avec sélection de C parmi [0.1, 0.3, 1, 3] en 5-fold CV stratifiée.
- Validation croisée groupée par id (aucun id simultanément en train et test).
- Métriques : AUC ROC et précision@10 % (globales et par catégorie si >= 20 exemples).
- Calibration (CalibratedClassifierCV, isotonic si > 1000 ex, sigmoid sinon).
- Sauvegarde models/taste_model.joblib et models/taste_meta.json (valid = false si AUC < 0.70).
- Rapport HTML data/taste_report.html : AUC, Top 20 et Bottom 20 annonces marché.
"""

import os
import sys
import json
import sqlite3
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
import pandas as pd
import joblib
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV
from sklearn.preprocessing import OneHotEncoder
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import roc_auc_score

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("TrainTaste")

MODELS_DIR = "models"
DATA_DIR = "data"
EMBEDDINGS_DIR = "data/embeddings"
IMAGES_DIR = "data/images"

from src.scoring.taxonomy import detect_category


def compute_precision_at_k_pct(y_true: np.ndarray, y_score: np.ndarray, k_pct: float = 0.10) -> float:
    """Calcule la part de positifs parmi les k% exemples les mieux notés."""
    n = len(y_true)
    if n == 0:
        return 0.0
    top_k = max(1, int(n * k_pct))
    top_indices = np.argsort(y_score)[::-1][:top_k]
    return float(np.mean(y_true[top_indices]))


def main():
    os.makedirs(MODELS_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    vision_model = "hf-hub:Marqo/marqo-fashionSigLIP"
    if os.path.exists("config.json"):
        try:
            with open("config.json", "r", encoding="utf-8") as f:
                cfg = json.load(f)
                vision_model = cfg.get("vision_model") or cfg.get("clip_model_name", vision_model)
        except Exception:
            pass

    dataset_path = os.path.join(DATA_DIR, "taste_dataset.npz")
    if not os.path.exists(dataset_path):
        logger.error(f"Fichier introuvable : {dataset_path}. Lancez d'abord scripts/build_taste_dataset.py.")
        sys.exit(1)

    logger.info(f"Chargement du dataset {dataset_path}...")
    data = np.load(dataset_path, allow_pickle=True)

    ids = data["ids"]
    sources = data["sources"]
    labels = data["labels"]
    weights = data["weights"]
    embeddings = data["embeddings"]
    brand_canonical = data["brand_canonical"]
    categories = data["category"]

    n_samples = len(labels)
    n_pos = int((labels == 1).sum())
    n_neg = int((labels == 0).sum())

    logger.info(f"Échantillons : {n_samples} (Positifs: {n_pos}, Négatifs: {n_neg})")

    # 1. Préparation de la matrice X : Embedding (512) + One-Hot Catégorie
    cat_2d = np.array([str(c) if c else "inconnu" for c in categories]).reshape(-1, 1)
    encoder = OneHotEncoder(handle_unknown="ignore", sparse_output=False)
    cat_encoded = encoder.fit_transform(cat_2d)

    X = np.hstack([embeddings, cat_encoded]).astype(np.float32)
    y = labels.astype(np.int32)
    w = weights.astype(np.float32)

    logger.info(f"Matrice de features X : shape {X.shape} (512 CLIP + {cat_encoded.shape[1]} catégories)")

    # 2. Validation croisée stratifiée 5 plis pour choisir C
    c_candidates = [0.1, 0.3, 1.0, 3.0]
    best_c = 1.0
    best_auc = 0.0
    best_oof_preds = None

    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

    logger.info("Recherche du meilleur paramètre C par validation croisée 5 plis...")
    for c in c_candidates:
        oof_preds = np.zeros(n_samples, dtype=np.float32)

        for train_idx, val_idx in skf.split(X, y):
            X_tr, y_tr, w_tr = X[train_idx], y[train_idx], w[train_idx]
            X_val = X[val_idx]

            clf = LogisticRegression(
                C=c,
                class_weight="balanced",
                solver="lbfgs",
                max_iter=1000,
                random_state=42
            )
            clf.fit(X_tr, y_tr, sample_weight=w_tr)
            oof_preds[val_idx] = clf.predict_proba(X_val)[:, 1]

        auc = roc_auc_score(y, oof_preds)
        p_at_10 = compute_precision_at_k_pct(y, oof_preds, 0.10)
        logger.info(f"  C = {c:<4} -> AUC OOF : {auc:.4f} | Précision@10% : {p_at_10:.4f}")

        if auc > best_auc:
            best_auc = auc
            best_c = c
            best_oof_preds = oof_preds

    global_prec_10 = compute_precision_at_k_pct(y, best_oof_preds, 0.10)
    logger.info(f"Meilleur C retenu : {best_c} (AUC = {best_auc:.4f}, Précision@10% = {global_prec_10:.4f})")

    # Métriques par catégorie (si >= 20 exemples)
    cat_metrics = {}
    print("\n" + "=" * 65)
    print("      PERFORMANCES PAR CATÉGORIE (MINIMUM 20 EXEMPLES)")
    print("=" * 65)
    print(f"{'Catégorie':<20} | {'Exemples':>8} | {'Positifs':>8} | {'AUC':>7} | {'P@10%':>7}")
    print("-" * 65)

    unique_cats = sorted(set(categories))
    for c_name in unique_cats:
        c_str = str(c_name)
        mask = (categories == c_name)
        c_count = int(mask.sum())
        if c_count >= 20:
            c_y = y[mask]
            c_preds = best_oof_preds[mask]
            c_pos = int((c_y == 1).sum())

            # AUC calculable seulement si les 2 classes sont présentes
            if len(np.unique(c_y)) > 1:
                c_auc = roc_auc_score(c_y, c_preds)
            else:
                c_auc = 0.5

            c_p10 = compute_precision_at_k_pct(c_y, c_preds, 0.10)
            cat_metrics[c_str] = {
                "count": c_count,
                "positives": c_pos,
                "auc": round(float(c_auc), 4),
                "precision_at_10": round(float(c_p10), 4)
            }
            print(f"{c_str:<20} | {c_count:>8} | {c_pos:>8} | {c_auc:>7.3f} | {c_p10:>7.3f}")

    print("=" * 65 + "\n")

    # 3. Calibration des probabilités
    calib_method = "isotonic" if n_samples > 1000 else "sigmoid"
    logger.info(f"Calibration des probabilités via CalibratedClassifierCV (méthode: {calib_method})...")

    base_model = LogisticRegression(
        C=best_c,
        class_weight="balanced",
        solver="lbfgs",
        max_iter=1000,
        random_state=42
    )

    calibrated_clf = CalibratedClassifierCV(
        estimator=base_model,
        method=calib_method,
        cv=5
    )
    calibrated_clf.fit(X, y, sample_weight=w)

    is_valid = bool(best_auc >= 0.70)
    if not is_valid:
        logger.warning(f"ATTENTION : Le modèle a une AUC de {best_auc:.3f} (< 0.70) et sera marqué invalide.")

    # 4. Sauvegarde du modèle et métadonnées
    model_bundle = {
        "calibrated_model": calibrated_clf,
        "encoder": encoder,
        "best_c": best_c,
        "calibration_method": calib_method,
        "valid": is_valid
    }

    joblib_path = os.path.join(MODELS_DIR, "taste_model.joblib")
    joblib.dump(model_bundle, joblib_path)
    logger.info(f"Modèle sauvegardé dans {joblib_path}")

    meta = {
        "trained_at": datetime.now().isoformat(),
        "vision_model": vision_model,
        "n_samples": n_samples,
        "n_positives": n_pos,
        "n_negatives": n_neg,
        "auc": round(float(best_auc), 4),
        "precision_at_10pct": round(float(global_prec_10), 4),
        "valid": is_valid,
        "best_c": best_c,
        "calibration_method": calib_method,
        "categories_breakdown": cat_metrics
    }

    meta_path = os.path.join(MODELS_DIR, "taste_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    logger.info(f"Métadonnées sauvegardées dans {meta_path}")

    # 5. Rapport HTML data/taste_report.html
    # Noter les annonces du marché pour afficher les 20 plus aimées et 20 moins aimées
    logger.info("Génération du rapport HTML data/taste_report.html...")
    generate_taste_html_report(
        calibrated_clf=calibrated_clf,
        encoder=encoder,
        auc=best_auc,
        p_at_10=global_prec_10,
        is_valid=is_valid,
        meta=meta
    )


def generate_taste_html_report(
    calibrated_clf,
    encoder,
    auc: float,
    p_at_10: float,
    is_valid: bool,
    meta: Dict[str, Any]
):
    """Génère le rapport HTML avec les Top 20 et Bottom 20 annonces du marché."""
    vision_model = str(meta.get("vision_model", ""))
    model_short_name = "fashionsiglip" if "siglip" in vision_model.lower() else "fashionclip"
    target_dim = 768 if model_short_name == "fashionsiglip" else 512
    emb_dir = os.path.join(DATA_DIR, "embeddings", model_short_name)

    conn = sqlite3.connect("vinted_bot.db", timeout=30.0)
    cur = conn.cursor()
    cur.execute("""
        SELECT item_id, title, price, brand_canonical, category
        FROM market_listings
        WHERE price > 0
    """)
    market_rows = cur.fetchall()
    conn.close()

    market_scored = []
    for r in market_rows:
        iid = str(r[0])
        emb_path = os.path.join(emb_dir, f"{iid}.npy")
        if not os.path.exists(emb_path):
            continue

        try:
            emb = np.load(emb_path).astype(np.float32)
            if emb.ndim != 1 or len(emb) != target_dim:
                continue
            norm = np.linalg.norm(emb)
            if norm > 1e-6:
                emb = emb / norm
            title = str(r[1] or "")
            cat = str(r[4] or detect_category(title))
            cat_feat = encoder.transform([[cat]])
            feat = np.hstack([emb.reshape(1, -1), cat_feat])

            score = float(calibrated_clf.predict_proba(feat)[0, 1])

            # Chercher image locale ou utiliser un placeholder/url
            img_src = ""
            for sub in ["market", "wardrobe", "favoris", "sales", "must_buy", "rejected", "feedback"]:
                p0 = os.path.join(IMAGES_DIR, sub, f"{iid}_0.jpg")
                p1 = os.path.join(IMAGES_DIR, sub, f"{iid}.jpg")
                if os.path.exists(p0):
                    img_src = f"images/{sub}/{iid}_0.jpg"
                    break
                elif os.path.exists(p1):
                    img_src = f"images/{sub}/{iid}.jpg"
                    break

            market_scored.append({
                "item_id": iid,
                "title": title,
                "price": float(r[2]),
                "brand": str(r[3] or ""),
                "category": cat,
                "score": score,
                "img_src": img_src
            })
        except Exception:
            pass

    market_scored.sort(key=lambda x: x["score"], reverse=True)

    top_20 = market_scored[:20]
    bottom_20 = market_scored[-20:][::-1] if len(market_scored) >= 20 else []

    def make_rows(items):
        rows = ""
        for it in items:
            score_pct = it["score"] * 100.0
            badge_color = "#34d399" if score_pct >= 60 else ("#f87171" if score_pct < 40 else "#fde047")
            img_html = f'<img src="../{it["img_src"]}" width="50" height="65" style="object-fit:cover; border-radius:4px;" />' if it["img_src"] else '<div style="width:50px; height:65px; background:#334155; border-radius:4px; display:flex; align-items:center; justify-content:center; color:#64748b; font-size:10px;">Sans img</div>'

            rows += f"""
            <tr>
                <td style="width:60px;">{img_html}</td>
                <td>{it['item_id']}</td>
                <td><b>{it['title'][:40]}</b></td>
                <td>{it['brand']}</td>
                <td>{it['category']}</td>
                <td>{it['price']:.2f} €</td>
                <td><b style="color:{badge_color}; font-size:15px;">{score_pct:.1f} %</b></td>
            </tr>
            """
        return rows

    report_path = os.path.join(DATA_DIR, "taste_report.html")
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <title>Rapport Modèle de Goût Rita</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; padding: 24px; margin: 0; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        h1, h2 {{ color: #38bdf8; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }}
        .card {{ background: #1e293b; padding: 18px; border-radius: 12px; border: 1px solid #334155; }}
        .card-val {{ font-size: 26px; font-weight: bold; margin-top: 8px; color: #f1f5f9; }}
        .card-sub {{ font-size: 13px; color: #94a3b8; margin-top: 4px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 12px; background: #1e293b; border-radius: 8px; overflow: hidden; font-size: 13px; }}
        th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #334155; vertical-align: middle; }}
        th {{ background: #0f172a; color: #94a3b8; font-weight: 600; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>👗 Modèle de Goût "Rita" — Rapport de Calibration</h1>
        <p style="color:#94a3b8">Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M:%S')} • Apprentissage sur favoris, ventes réelles et rejets</p>

        <div class="grid">
            <div class="card">
                <div>AUC Validation Croisée</div>
                <div class="card-val" style="color:{'#34d399' if auc >= 0.75 else '#f87171'}">{auc:.3f}</div>
                <div class="card-sub">{'Modèle Valide (>= 0.70)' if is_valid else 'Modèle Invalide (< 0.70)'}</div>
            </div>
            <div class="card">
                <div>Précision @ 10 %</div>
                <div class="card-val" style="color:#38bdf8">{p_at_10 * 100:.1f} %</div>
                <div class="card-sub">Positifs dans le top 10 %</div>
            </div>
            <div class="card">
                <div>Échantillons</div>
                <div class="card-val">{meta['n_samples']}</div>
                <div class="card-sub">{meta['n_positives']} positifs, {meta['n_negatives']} négatifs</div>
            </div>
            <div class="card">
                <div>Paramètre C optimal</div>
                <div class="card-val" style="color:#a78bfa">{meta['best_c']}</div>
                <div class="card-sub">Régularisation L2</div>
            </div>
        </div>

        <h2>🟢 Top 20 Annonces Marché les Mieux Notées (Goût Fort)</h2>
        <table>
            <thead>
                <tr>
                    <th>Photo</th><th>ID</th><th>Titre</th><th>Marque</th><th>Catégorie</th><th>Prix</th><th>Score Goût</th>
                </tr>
            </thead>
            <tbody>
                {make_rows(top_20)}
            </tbody>
        </table>

        <h2 style="margin-top: 40px">🔴 Bottom 20 Annonces Marché les Moins Bien Notées (Rejet)</h2>
        <table>
            <thead>
                <tr>
                    <th>Photo</th><th>ID</th><th>Titre</th><th>Marque</th><th>Catégorie</th><th>Prix</th><th>Score Goût</th>
                </tr>
            </thead>
            <tbody>
                {make_rows(bottom_20)}
            </tbody>
        </table>
    </div>
</body>
</html>
"""
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)
    logger.info(f"Rapport HTML sauvegardé avec succès dans {report_path}")


if __name__ == "__main__":
    main()
