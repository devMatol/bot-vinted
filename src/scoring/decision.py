"""Moteur de décision central et enregistrement en base (Lot 5).

Calculs économiques et combinatoires :
- coût_total = prix + port (selon pays) + 0.70 + 5 % du prix
- marge = revente_retenue - coût_total
- multiple = revente_retenue / coût_total
- score_final 0-100 pondéré (règles 0.25, distinct 0.25, marge 0.30, marché 0.10, annonce 0.10)
- Validation si : score_final >= final_min_score (70) ET marge >= min_margin_eur (15) ET multiple >= min_multiple (2.0)
- Niveaux d'alerte :
  * 🟢 PEPITE (score >= 85 et multiple >= 3.0)
  * 🟡 A_REGARDER (70 à 84)
- Enregistrement systématique de toutes les décisions dans la table decisions
"""

import os
import json
import sqlite3
import logging
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("VintedBot.Scoring.Decision")

DEFAULT_DB_PATH = "vinted_bot.db"


@dataclass
class DecisionResult:
    """Résultat complet et auditable de la décision d'achat."""
    item_id: str
    decision: str  # "VALIDATED" ou "REJECTED"
    alert_tier: str  # "PEPITE", "A_REGARDER", "NONE"
    score_final: float
    price: float
    total_cost: float
    revente_retenue: float
    margin: float
    multiple: float
    market_ratio: float = 1.0
    stage_reached: str = "D"
    stop_reason: str = ""
    reasons: List[str] = field(default_factory=list)
    execution_times: Dict[str, float] = field(default_factory=dict)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _get_db_conn(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    return conn


def init_decisions_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Crée la table decisions dans SQLite pour l'audit et l'apprentissage continu."""
    conn = _get_db_conn(db_path)
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id TEXT,
                    decision TEXT,
                    alert_tier TEXT,
                    score_final REAL,
                    price REAL,
                    total_cost REAL,
                    revente_retenue REAL,
                    margin REAL,
                    multiple REAL,
                    stage_reached TEXT,
                    stop_reason TEXT,
                    details_json TEXT,
                    execution_time_total_ms REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_decisions_item ON decisions(item_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_decisions_decision ON decisions(decision)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_decisions_created ON decisions(created_at)")
    finally:
        conn.close()


def calculate_total_cost(
    price: float,
    country: str = "fr",
    shipping_cost: Optional[float] = None,
    packaging_fee: float = 0.80
) -> float:
    """
    Coût total net déboursé :
    coût_total = prix + port (selon pays vendeur) + protection Vinted (0,70 + 5 % du prix) + logistique/emballage (0,80 €)
    """
    if shipping_cost is not None and shipping_cost > 0:
        port = shipping_cost
    else:
        # Grille indicative par pays
        shipping_by_country = {
            "fr": 3.49,
            "it": 4.59,
            "es": 4.29,
            "be": 3.79,
            "nl": 4.59,
            "de": 4.99,
            "pt": 4.89
        }
        port = shipping_by_country.get(country.lower(), 3.80)

    buyer_fee = 0.70 + (0.05 * price)
    return round(price + port + buyer_fee + packaging_fee, 2)


def make_decision(
    item_id: str,
    price: float,
    rule_score: float,
    distinct_score: float,
    revente_retenue: float,
    market_median_price: float,
    listing_signal_score: float,
    country: str = "fr",
    shipping_cost: Optional[float] = None,
    stock_photo_score: float = 0.0,
    damage_score: float = 0.0,
    distinct_pct: Optional[float] = None,
    taste_score: Optional[float] = None,
    config: Optional[Dict[str, Any]] = None,
    execution_times: Optional[Dict[str, float]] = None,
    resale_details: Optional[Dict[str, Any]] = None
) -> DecisionResult:
    """
    Agrège les composantes des étages A, B, C, D en un verdict final.
    Utilise taste_score (Goût Rita) en priorité, sinon distinct_pct / distinct_score.
    Calcule la marge nette déboursée et la grille de scénarios (Flash, Cible, Optimiste).
    """
    cfg = config or {}
    exec_times = execution_times or {}
    r_details = resale_details or {}

    min_margin = float(cfg.get("min_margin_eur", 15.0))
    final_min_score = float(cfg.get("final_min_score", 70.0))
    min_multiple = float(cfg.get("min_multiple", 2.0))
    weights = cfg.get("decision_weights", {
        "rules": 0.25,
        "taste": 0.25,
        "distinct": 0.25,
        "margin": 0.30,
        "market": 0.10,
        "signals": 0.10
    })

    packaging_fee = float(cfg.get("packaging_fee_eur", 0.80))
    total_cost = calculate_total_cost(price, country, shipping_cost, packaging_fee=packaging_fee)
    margin = round(revente_retenue - total_cost, 2)
    multiple = round(revente_retenue / max(1.0, total_cost), 2)

    market_ratio = round(price / max(1.0, market_median_price), 2) if market_median_price > 0 else 1.0

    # 1. Sous-score de marge/multiple (0 à 100)
    if multiple <= 1.0:
        margin_score = 0.0
    elif multiple <= 2.0:
        margin_score = (multiple - 1.0) * 70.0
    elif multiple <= 3.0:
        margin_score = 70.0 + (multiple - 2.0) * 20.0
    else:
        margin_score = min(100.0, 90.0 + (multiple - 3.0) * 10.0)

    # 2. Sous-score de ratio de marché (0 à 100)
    if market_ratio <= 0.4:
        market_score = 100.0
    elif market_ratio <= 0.6:
        market_score = 80.0
    elif market_ratio <= 0.8:
        market_score = 60.0
    elif market_ratio <= 1.0:
        market_score = 45.0
    else:
        market_score = max(0.0, 30.0 - (market_ratio - 1.0) * 30.0)

    # 3. Sous-score de goût / distinctivité (0 à 100)
    # Si le modèle de goût est présent et valide, on utilise taste_score
    if taste_score is not None:
        eff_taste_score = taste_score
    else:
        eff_taste_score = distinct_pct if distinct_pct is not None else distinct_score

    taste_score_100 = eff_taste_score * 100.0
    taste_weight = float(weights.get("taste", weights.get("distinct", 0.25)))

    # 4. Combinaison linéaire pondérée
    raw_final_score = (
        float(weights.get("rules", 0.25)) * rule_score +
        taste_weight * taste_score_100 +
        float(weights.get("margin", 0.30)) * margin_score +
        float(weights.get("market", 0.10)) * market_score +
        float(weights.get("signals", 0.10)) * listing_signal_score
    )

    # Malus qualité photo
    stock_photo_thresh = float(cfg.get("clip_stock_photo_threshold", 0.5))
    damage_malus_thresh = float(cfg.get("clip_damage_malus_threshold", 0.70))
    if stock_photo_score >= stock_photo_thresh:
        raw_final_score -= (stock_photo_score * 15.0)
    if damage_score >= damage_malus_thresh:
        raw_final_score -= (damage_score * 15.0)

    score_final = float(round(max(0.0, min(100.0, raw_final_score)), 1))

    reasons: List[str] = []
    stop_reason = ""
    decision = "REJECTED"
    alert_tier = "NONE"

    # Vérification des 3 critères obligatoires
    if score_final < final_min_score:
        stop_reason = f"Score final insuffisant ({score_final:.1f} < {final_min_score})"
    elif margin < min_margin:
        stop_reason = f"Marge nette insuffisante ({margin:.2f} € < {min_margin:.2f} €)"
    elif multiple < min_multiple:
        stop_reason = f"Multiple insuffisant ({multiple:.1f}x < {min_multiple:.1f}x)"
    else:
        decision = "VALIDATED"
        # Niveaux d'alerte : PEPITE vs A_REGARDER
        if score_final >= 85.0 and multiple >= 3.0:
            alert_tier = "PEPITE"
            reasons.append(f"🟢 PÉPITE : Score {score_final:.1f}/100, Marge +{margin:.2f}€ ({multiple:.1f}x)")
        else:
            alert_tier = "A_REGARDER"
            reasons.append(f"🟡 À REGARDER : Score {score_final:.1f}/100, Marge +{margin:.2f}€ ({multiple:.1f}x)")

    # Calcul des scénarios de marge (Vente flash, Cible, Optimiste)
    revente_pessimiste = float(r_details.get("revente_pessimiste") or (revente_retenue * 0.78))
    revente_optimiste = float(r_details.get("revente_optimiste") or (revente_retenue * 1.22))
    revente_cible = float(r_details.get("revente_cible") or (revente_retenue / 0.88))
    nego_discount = float(cfg.get("resale_negotiation_discount", 0.12))

    revente_flash_nette = round(revente_pessimiste * (1.0 - nego_discount), 2)
    revente_opt_nette = round(revente_optimiste * (1.0 - nego_discount), 2)

    scenarios = {
        "revente_cible": revente_cible,
        "revente_flash_nette": revente_flash_nette,
        "revente_opt_nette": revente_opt_nette,
        "margin_flash": round(revente_flash_nette - total_cost, 2),
        "margin_cible": margin,
        "margin_opt": round(revente_opt_nette - total_cost, 2),
    }

    total_time_ms = sum(exec_times.values())

    details = {
        "rule_score": rule_score,
        "distinct_score": distinct_score,
        "distinct_pct": round(eff_taste_score, 4),
        "taste_score": round(taste_score, 4) if taste_score is not None else None,
        "damage_score": round(damage_score, 3),
        "stock_photo_score": round(stock_photo_score, 3),
        "margin_score": round(margin_score, 1),
        "market_score": round(market_score, 1),
        "listing_signal_score": listing_signal_score,
        "market_median_price": market_median_price,
        "scenarios": scenarios,
        "clip": r_details.get("clip", {}),
        "resale": r_details,
        "weights": weights
    }

    result = DecisionResult(
        item_id=str(item_id),
        decision=decision,
        alert_tier=alert_tier,
        score_final=score_final,
        price=price,
        total_cost=total_cost,
        revente_retenue=revente_retenue,
        margin=margin,
        multiple=multiple,
        market_ratio=market_ratio,
        stage_reached="D",
        stop_reason=stop_reason,
        reasons=reasons,
        execution_times=exec_times,
        details=details
    )

    # Sauvegarde en base SQLite
    record_decision(result)

    return result


def record_decision(res: DecisionResult, db_path: str = DEFAULT_DB_PATH) -> None:
    """Enregistre la décision dans la table SQLite decisions."""
    init_decisions_db(db_path)
    conn = _get_db_conn(db_path)
    try:
        total_ms = sum(res.execution_times.values()) if res.execution_times else 0.0
        details_str = json.dumps(res.details, ensure_ascii=False)
        with conn:
            conn.execute("""
                INSERT INTO decisions (
                    item_id, decision, alert_tier, score_final, price, total_cost,
                    revente_retenue, margin, multiple, stage_reached, stop_reason,
                    details_json, execution_time_total_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                res.item_id,
                res.decision,
                res.alert_tier,
                res.score_final,
                res.price,
                res.total_cost,
                res.revente_retenue,
                res.margin,
                res.multiple,
                res.stage_reached,
                res.stop_reason,
                details_str,
                total_ms
            ))
    except Exception as e:
        logger.debug(f"Erreur enregistrement décision {res.item_id}: {e}")
    finally:
        conn.close()
