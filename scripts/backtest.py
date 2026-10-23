"""Backtest complet et calibration du moteur de décision local (Lot 6).

Rejoue les étages A à D sans appel Gemini sur :
- Les achats réels de la boutique (calcul du rappel / recall)
- Les ventes réelles de la boutique (calcul de l'erreur de revente en €)
- Les favoris de la boutique
- Un échantillon de 2 000 annonces du marché (market_listings)

Génère :
- Rapport console détaillé
- data/backtest_report.html
- Proposition automatique de seuil final_min_score ciblant 5 à 15 alertes/heure
"""

import os
import sys
import json
import sqlite3
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

# Assurer l'accès au module racine src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
import pandas as pd

from src.scoring.rules import evaluate_rules, DIFFUSION_BASIC_CATEGORIES, is_diffusion_target_brand
from src.scoring.clip_scorer import get_clip_scorer
from src.scoring.market import market_median, get_comparables_matcher
from src.scoring.resale_model import estimate_resale_price
from src.scoring.listing_signals import evaluate_listing_signals
from src.scoring.decision import make_decision, calculate_total_cost
from src.scoring.taste import get_taste_score, is_taste_model_valid, init_taste_scorer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Backtest")


def run_pipeline_on_item(
    item: Dict[str, Any],
    clip_scorer,
    comp_matcher,
    config: Dict[str, Any]
) -> Dict[str, Any]:
    """Exécute les étages A à D sur une annonce unique sans appel Gemini."""
    price = float(item.get("price") or 0.0)
    item_id = str(item.get("id") or item.get("item_id") or "")

    # 1. Étage A : Règles
    rule_res = evaluate_rules(item, config)
    if rule_res.hard_reject or rule_res.score < float(config.get("rules_min_score", 35.0)):
        return {
            "item_id": item_id,
            "title": str(item.get("title") or ""),
            "price": price,
            "category": rule_res.category,
            "brand": rule_res.brand_canonical,
            "decision": "REJECTED",
            "stage_stopped": "A_RULES",
            "stop_reason": rule_res.reasons[0] if rule_res.reasons else "Score règles insuffisant",
            "score_final": rule_res.score,
            "distinct_score": 0.5,
            "distinct_pct": 0.5,
            "revente_retenue": 0.0,
            "margin": 0.0,
            "multiple": 0.0,
            "alert_tier": "NONE"
        }

    # 2. Étage B : Vision CLIP
    clip_res = clip_scorer.evaluate_item(item, rules_category=rule_res.category)
    if clip_res.hard_reject:
        return {
            "item_id": item_id,
            "title": str(item.get("title") or ""),
            "price": price,
            "category": clip_res.clip_category,
            "brand": rule_res.brand_canonical,
            "decision": "REJECTED",
            "stage_stopped": "B_CLIP",
            "stop_reason": clip_res.reasons[0] if clip_res.reasons else "Rejet visuel CLIP",
            "score_final": rule_res.score,
            "distinct_score": clip_res.distinct_score,
            "distinct_pct": clip_res.distinct_pct,
            "taste_score": None,
            "revente_retenue": 0.0,
            "margin": 0.0,
            "multiple": 0.0,
            "alert_tier": "NONE"
        }

    # Évaluation du Goût Rita
    taste_score = get_taste_score(clip_res.embedding, clip_res.clip_category or rule_res.category)

    # 2b. Rejet des basiques de lignes diffusion : taste_score < 0.5 (ou distinct_pct < 0.8 si modèle indisponible)
    if (
        rule_res.category in DIFFUSION_BASIC_CATEGORIES
        and is_diffusion_target_brand(rule_res.brand_canonical, rule_res.brand_line)
    ):
        diff_reject = False
        stop_reason = ""
        if taste_score is not None:
            if taste_score < 0.5:
                diff_reject = True
                stop_reason = f"Basique de ligne diffusion ({rule_res.brand_canonical}) rejeté : Goût Rita faible ({taste_score*100:.0f}% < 50%)"
        else:
            if clip_res.distinct_pct < 0.8:
                diff_reject = True
                stop_reason = f"Basique de ligne diffusion ({rule_res.brand_canonical}) sans élément distinctif fort (distinct_pct={clip_res.distinct_pct:.2f} < 0.80)"

        if diff_reject:
            return {
                "item_id": item_id,
                "title": str(item.get("title") or ""),
                "price": price,
                "category": clip_res.clip_category,
                "brand": rule_res.brand_canonical,
                "decision": "REJECTED",
                "stage_stopped": "A_RULES_DIFFUSION_BASIC",
                "stop_reason": stop_reason,
                "score_final": rule_res.score,
                "distinct_score": clip_res.distinct_score,
                "distinct_pct": clip_res.distinct_pct,
                "taste_score": taste_score,
                "revente_retenue": 0.0,
                "margin": 0.0,
                "multiple": 0.0,
                "alert_tier": "NONE"
            }

    # 3. Étage C : Marché et Revente
    mkt_med = market_median(rule_res.brand_canonical, rule_res.brand_line, clip_res.clip_category)
    comp_price = 0.0
    if clip_res.embedding is not None:
        comp_price, _ = comp_matcher.find_comparables(clip_res.embedding, category=clip_res.clip_category)

    resale_res = estimate_resale_price(
        item=item,
        rules_category=rule_res.category,
        brand_canonical=rule_res.brand_canonical,
        brand_line=rule_res.brand_line,
        tier=rule_res.tier,
        size_norm=rule_res.size_normalized,
        bonus_score=sum(rule_res.bonus_hits.values()),
        malus_score=sum(rule_res.malus_hits.values()),
        clip_category=clip_res.clip_category,
        material_top=clip_res.material_top,
        distinct_score=clip_res.distinct_score,
        distinct_pct=clip_res.distinct_pct,
        taste_score=taste_score,
        embedding=clip_res.embedding,
        comp_price=comp_price,
        config=config
    )

    # 4. Étage D : Signaux annonce
    signals_res = evaluate_listing_signals(
        item=item,
        tier=rule_res.tier,
        label_detected=clip_res.label_detected,
        config=config
    )

    # 5. Décision finale
    dec_res = make_decision(
        item_id=item_id,
        price=price,
        rule_score=rule_res.score,
        distinct_score=clip_res.distinct_score,
        distinct_pct=clip_res.distinct_pct,
        taste_score=taste_score,
        revente_retenue=resale_res.revente_retenue,
        market_median_price=mkt_med,
        listing_signal_score=signals_res.score,
        stock_photo_score=clip_res.stock_photo_score,
        damage_score=clip_res.damage_score,
        config=config
    )

    return {
        "item_id": item_id,
        "title": str(item.get("title") or ""),
        "price": price,
        "category": clip_res.clip_category,
        "brand": rule_res.brand_canonical,
        "decision": dec_res.decision,
        "stage_stopped": "VALIDATED" if dec_res.decision == "VALIDATED" else "DECISION",
        "stop_reason": dec_res.stop_reason,
        "score_final": dec_res.score_final,
        "distinct_score": clip_res.distinct_score,
        "distinct_pct": clip_res.distinct_pct,
        "taste_score": taste_score,
        "revente_retenue": dec_res.revente_retenue,
        "margin": dec_res.margin,
        "multiple": dec_res.multiple,
        "alert_tier": dec_res.alert_tier
    }


def run_backtest():
    with open("config.json", "r", encoding="utf-8") as f:
        config = json.load(f)

    logger.info("Chargement des modèles CLIP et comparables...")
    clip_scorer = get_clip_scorer(config)
    comp_matcher = get_comparables_matcher()

    # 1. Échantillon Marché sans fuite (2 000 annonces des recherches actives, hors dataset de goût)
    logger.info("Chargement de l'échantillon marché sans fuite (2 000 annonces)...")
    taste_ids = set()
    if os.path.exists("data/taste_dataset.npz"):
        data_taste = np.load("data/taste_dataset.npz", allow_pickle=True)
        taste_ids = set(str(i) for i in data_taste["ids"])
        logger.info(f"Exclusion stricte de {len(taste_ids)} IDs d'entraînement du backtest.")

    from scripts.build_taste_dataset import get_active_search_criteria, is_active_search_match
    active_brands, active_kws = get_active_search_criteria(config)

    conn = sqlite3.connect("vinted_bot.db", timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    cur = conn.cursor()
    cur.execute("""
        SELECT m.item_id, m.title, m.price, m.brand_canonical, m.category, d.description, d.photo_urls
        FROM market_listings m
        LEFT JOIN deal_feedback d ON m.item_id = d.item_id
        WHERE m.price > 0
    """)
    market_rows = cur.fetchall()
    conn.close()

    market_items = []
    for r in market_rows:
        iid = str(r[0])
        if iid in taste_ids:
            continue
        title = str(r[1] or "")
        brand = str(r[3] or "")
        if not is_active_search_match(title, brand, active_brands, active_kws):
            continue

        urls = []
        # Vérifier si une photo locale existe déjà
        for sub in ["market", "feedback", "rejected"]:
            p = os.path.join("data", "images", sub, f"{iid}_0.jpg")
            if os.path.exists(p):
                urls.append(p)
                break

        if not urls and r[6]:
            try:
                parsed = json.loads(r[6])
                if isinstance(parsed, list):
                    urls = [u for u in parsed if isinstance(u, str) and u.startswith("http")]
            except Exception:
                pass

        market_items.append({
            "id": iid,
            "title": title,
            "price": float(r[2]),
            "brand_title": brand,
            "description": str(r[5] or ""),
            "photo_urls": urls
        })
        if len(market_items) >= 2000:
            break

    logger.info(f"Échantillon marché sans fuite sélectionné : {len(market_items)} annonces des recherches actives.")

    # 2. Ventes et achats réels de la boutique (purchases.parquet & sales.parquet)
    logger.info("Chargement des achats et ventes réels de la boutique...")
    purchases_items = []
    p_path = "data/purchases.parquet"
    if os.path.exists(p_path):
        p_df = pd.read_parquet(p_path)
        for _, r in p_df.iterrows():
            item_id = str(r["id"])
            img_path = str(r.get("image_path") or "")
            if not os.path.exists(img_path):
                img_path = f"data/images/wardrobe/{item_id}.jpg"
            purchases_items.append({
                "id": item_id,
                "title": str(r["title"]),
                "price": float(r["price"]),
                "brand_title": str(r.get("brand_canonical") or r.get("brand_raw") or ""),
                "description": "",
                "photos": [{"url": img_path}] if os.path.exists(img_path) else []
            })
    logger.info(f"Chargé {len(purchases_items)} achats réels de la boutique.")

    # Exécution sur le marché
    logger.info(f"Évaluation de {len(market_items)} annonces marché...")
    market_results = []
    for idx, item in enumerate(market_items):
        res = run_pipeline_on_item(item, clip_scorer, comp_matcher, config)
        market_results.append(res)
        if (idx + 1) % 500 == 0:
            logger.info(f"  Avancement marché: {idx + 1}/{len(market_items)}")

    # Exécution sur les achats réels de la boutique
    logger.info(f"Évaluation de {len(purchases_items)} achats réels de la boutique...")
    purchases_results = []
    for item in purchases_items:
        res = run_pipeline_on_item(item, clip_scorer, comp_matcher, config)
        purchases_results.append(res)

    # Analyse des métriques
    mkt_df = pd.DataFrame(market_results)
    p_df = pd.DataFrame(purchases_results)

    validated_mkt = mkt_df[mkt_df["decision"] == "VALIDATED"]
    market_validation_rate = (len(validated_mkt) / max(1, len(mkt_df))) * 100.0

    # Hypothèse : 300 annonces vues par heure par le bot
    est_items_per_hour = 300
    est_alerts_per_hour = (market_validation_rate / 100.0) * est_items_per_hour

    # Rappel sur achats réels boutique
    p_validated = p_df[p_df["decision"] == "VALIDATED"]
    shop_recall = (len(p_validated) / max(1, len(p_df))) * 100.0

    # Erreur médiane de revente sur les ventes réelles
    sales_errors_eur = []
    s_path = "data/sales.parquet"
    if os.path.exists(s_path):
        s_df = pd.read_parquet(s_path)
        for _, r in s_df.head(200).iterrows():
            item_id = str(r["id"])
            sold_price = float(r["price"])
            img_path = str(r.get("image_path") or "")
            if not os.path.exists(img_path):
                img_path = f"data/images/wardrobe/{item_id}.jpg"
            eval_res = run_pipeline_on_item({
                "id": item_id,
                "title": str(r["title"]),
                "price": max(4.0, sold_price * 0.35),
                "brand_title": str(r.get("brand_canonical") or r.get("brand_raw") or ""),
                "description": "",
                "photos": [{"url": img_path}] if os.path.exists(img_path) else []
            }, clip_scorer, comp_matcher, config)
            if eval_res["revente_retenue"] > 0:
                sales_errors_eur.append(abs(eval_res["revente_retenue"] - sold_price))

    median_resale_err = float(np.median(sales_errors_eur)) if sales_errors_eur else 0.0

    # Calibration automatique du seuil final_min_score
    # On trie les scores du marché pour trouver le percentile correspondant à 10 alertes/heure (3.3%)
    target_rate = (10.0 / est_items_per_hour) * 100.0
    suggested_score = 70.0
    if len(mkt_df) > 0:
        valid_candidates = mkt_df[(mkt_df["margin"] >= 15.0) & (mkt_df["multiple"] >= 2.0)]
        if len(valid_candidates) > 0:
            cutoff_pct = max(0.0, 100.0 - target_rate)
            suggested_score = float(np.percentile(valid_candidates["score_final"], cutoff_pct))
            suggested_score = round(max(65.0, min(85.0, suggested_score)), 1)

    # Validations douteuses (haut score mais faible distinctivité)
    dubious_df = validated_mkt[validated_mkt["distinct_score"] <= 0.35].sort_values("score_final", ascending=False).head(30)

    # Métadonnées du modèle de goût
    taste_auc = 0.0
    taste_p10 = 0.0
    if os.path.exists("models/taste_meta.json"):
        try:
            with open("models/taste_meta.json", "r", encoding="utf-8") as f:
                t_meta = json.load(f)
                taste_auc = float(t_meta.get("auc", 0.0))
                taste_p10 = float(t_meta.get("precision_at_10pct", 0.0)) * 100.0
        except Exception:
            pass

    # Rapport Console
    print("\n" + "=" * 95)
    print("                    RAPPORT DE BACKTEST BRUT (BOT-VINTED V2)")
    print("=" * 95)
    print(f"Modèle de Goût 'Rita' (AUC)      : {taste_auc:.3f} | Précision@10%: {taste_p10:.1f} %")
    print(f"Annonces marché analysées        : {len(mkt_df)}")
    print(f"Nombre d'alertes validées        : {len(validated_mkt)} sur {len(mkt_df)} ({market_validation_rate:.2f} %)")
    print(f"Volume d'alertes estimé          : {est_alerts_per_hour:.1f} alertes / heure (base 300 annonces/h)")
    print(f"Rappel sur achats réels boutique : {shop_recall:.1f} % ({len(p_validated)}/{len(p_df)})")
    print(f"Erreur médiane de revente        : {median_resale_err:.2f} €")
    print(f"Seuil final_min_score conseillé  : {suggested_score} (cible 5 à 15 alertes/h)")
    print(f"Alertes PÉPITE (marché)          : {len(mkt_df[mkt_df['alert_tier'] == 'PEPITE'])}")
    print(f"Validations à faible distinctivité: {len(dubious_df)}")
    print("=" * 95)
    print("LES 15 PREMIÈRES ALERTES VALIDÉES SUR LE MARCHÉ :")
    print(f"{'#':<3} | {'Titre':<28} | {'Marque':<15} | {'Prix':>7} | {'Revente':>8} | {'Goût Rita':>9} | {'Score Final':>11}")
    print("-" * 95)
    for i, (_, r) in enumerate(validated_mkt.head(15).iterrows(), 1):
        t = (r['title'][:25] + '...') if len(r['title']) > 28 else r['title']
        b = (r['brand'][:13] + '..') if len(r['brand']) > 15 else r['brand']
        t_sc = r.get('taste_score')
        t_str = f"{float(t_sc)*100:.0f} %" if (t_sc is not None and not pd.isna(t_sc)) else "N/A"
        print(f"{i:<3} | {t:<28} | {b:<15} | {r['price']:>6.2f}€ | {r['revente_retenue']:>7.2f}€ | {t_str:>9} | {r['score_final']:>11.1f}")
    print("=" * 95 + "\n")

    # Génération du rapport HTML data/backtest_report.html
    generate_html_report(
        mkt_df=mkt_df,
        w_df=p_df,
        validated_mkt=validated_mkt,
        dubious_df=dubious_df,
        market_val_rate=market_validation_rate,
        alerts_per_hour=est_alerts_per_hour,
        recall=shop_recall,
        resale_err=median_resale_err,
        suggested_threshold=suggested_score
    )


def generate_html_report(
    mkt_df: pd.DataFrame,
    w_df: pd.DataFrame,
    validated_mkt: pd.DataFrame,
    dubious_df: pd.DataFrame,
    market_val_rate: float,
    alerts_per_hour: float,
    recall: float,
    resale_err: float,
    suggested_threshold: float
):
    os.makedirs("data", exist_ok=True)
    report_path = "data/backtest_report.html"

    # Construction des lignes du tableau de validations douteuses
    dubious_rows = ""
    for _, r in dubious_df.iterrows():
        dubious_rows += f"""
        <tr>
            <td>{r['item_id']}</td>
            <td><b>{r['title'][:45]}</b></td>
            <td>{r['brand']}</td>
            <td>{r['category']}</td>
            <td>{r['price']:.2f} €</td>
            <td>{r['revente_retenue']:.2f} €</td>
            <td><b style="color:#10b981">+{r['margin']:.2f} €</b></td>
            <td>{r['multiple']:.1f}x</td>
            <td>{r['distinct_score']:.2f}</td>
            <td><span class="badge badge-warning">{r['score_final']:.1f}</span></td>
        </tr>
        """

    # Top 15 validations pépites
    pepite_df = validated_mkt[validated_mkt["alert_tier"] == "PEPITE"].sort_values("score_final", ascending=False).head(15)
    pepite_rows = ""
    for _, r in pepite_df.iterrows():
        pepite_rows += f"""
        <tr>
            <td>{r['item_id']}</td>
            <td><b>{r['title'][:45]}</b></td>
            <td>{r['brand']}</td>
            <td>{r['category']}</td>
            <td>{r['price']:.2f} €</td>
            <td>{r['revente_retenue']:.2f} €</td>
            <td><b style="color:#10b981">+{r['margin']:.2f} €</b></td>
            <td>{r['multiple']:.1f}x</td>
            <td>{r['distinct_score']:.2f}</td>
            <td><span class="badge badge-success">{r['score_final']:.1f}</span></td>
        </tr>
        """

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <title>Rapport de Backtest - Bot Vinted v2</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; padding: 24px; margin: 0; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        h1, h2 {{ color: #38bdf8; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 24px; }}
        .card {{ background: #1e293b; padding: 18px; border-radius: 12px; border: 1px solid #334155; }}
        .card-val {{ font-size: 28px; font-weight: bold; margin-top: 8px; color: #f1f5f9; }}
        .card-sub {{ font-size: 13px; color: #94a3b8; margin-top: 4px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 12px; background: #1e293b; border-radius: 8px; overflow: hidden; font-size: 13px; }}
        th, td {{ padding: 10px 14px; text-align: left; border-bottom: 1px solid #334155; }}
        th {{ background: #0f172a; color: #94a3b8; font-weight: 600; }}
        .badge {{ padding: 4px 8px; border-radius: 6px; font-weight: 600; font-size: 11px; }}
        .badge-success {{ background: #065f46; color: #34d399; }}
        .badge-warning {{ background: #854d0e; color: #fde047; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Rapport de Backtest — Bot Vinted v2 (Moteur Local)</h1>
        <p style="color:#94a3b8">Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M:%S')} • Pipeline A-D sans dépendance Gemini</p>

        <div class="grid">
            <div class="card">
                <div>Rappel Boutique</div>
                <div class="card-val" style="color:#34d399">{recall:.1f} %</div>
                <div class="card-sub">Articles validés ({len(w_df[w_df['decision']=='VALIDATED'])}/{len(w_df)})</div>
            </div>
            <div class="card">
                <div>Taux d'alerte Marché</div>
                <div class="card-val" style="color:#38bdf8">{market_val_rate:.2f} %</div>
                <div class="card-sub">{len(validated_mkt)} sur {len(mkt_df)} annonces</div>
            </div>
            <div class="card">
                <div>Alertes / Heure estimées</div>
                <div class="card-val" style="color:#fde047">{alerts_per_hour:.1f} / h</div>
                <div class="card-sub">Base 300 annonces vues/h</div>
            </div>
            <div class="card">
                <div>Erreur Médiane Revente</div>
                <div class="card-val">{resale_err:.2f} €</div>
                <div class="card-sub">Écart aux prix boutique</div>
            </div>
            <div class="card">
                <div>Seuil Recommandé</div>
                <div class="card-val" style="color:#a78bfa">{suggested_threshold}</div>
                <div class="card-sub">final_min_score cible 5-15/h</div>
            </div>
        </div>

        <h2>🟢 Top 15 Pépites Détectées</h2>
        <table>
            <thead>
                <tr>
                    <th>ID</th><th>Titre</th><th>Marque</th><th>Catégorie</th><th>Prix</th>
                    <th>Revente</th><th>Marge</th><th>Multiple</th><th>Distinct</th><th>Score</th>
                </tr>
            </thead>
            <tbody>
                {pepite_rows if pepite_rows else "<tr><td colspan='10'>Aucune pépite détectée</td></tr>"}
            </tbody>
        </table>

        <h2 style="margin-top: 36px">⚠️ Validations à Faible Distinctivité (Contrôle Humain)</h2>
        <table>
            <thead>
                <tr>
                    <th>ID</th><th>Titre</th><th>Marque</th><th>Catégorie</th><th>Prix</th>
                    <th>Revente</th><th>Marge</th><th>Multiple</th><th>Distinct</th><th>Score</th>
                </tr>
            </thead>
            <tbody>
                {dubious_rows if dubious_rows else "<tr><td colspan='10'>Aucune validation douteuse détectée</td></tr>"}
            </tbody>
        </table>
    </div>
</body>
</html>
"""
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)
    logger.info(f"Rapport HTML sauvegardé dans {report_path}")


if __name__ == "__main__":
    run_backtest()
