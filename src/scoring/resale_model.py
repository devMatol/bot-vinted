"""Étage C : Modèle de revente locale calibré (Lot 4).

Estimation prudente du prix de revente sur Vinted :
- Modèle HistGradientBoosting quantile regression (q30 & q50)
- Intégration des comparables visuels de la boutique (comp_price)
- Plafond de revente par catégorie et multiplicateur de marque
- Règle de décision :
  revente_retenue = min(pred_q30, comp_price * 1.1, plafond_catégorie * palier_marque)
"""

import os
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("VintedBot.Scoring.Resale")

DEFAULT_RESALE_CAPS = {
    "tshirt": 20.0,
    "top": 20.0,
    "chemise_blouse": 22.0,
    "pull_maille": 25.0,
    "sweat": 25.0,
    "robe": 30.0,
    "jupe": 25.0,
    "jean": 25.0,
    "pantalon": 25.0,
    "short": 20.0,
    "combinaison": 32.0,
    "veste": 45.0,
    "blazer": 45.0,
    "manteau": 55.0,
    "manteau_fourrure": 70.0,
    "chaussures": 45.0,
    "bottes": 60.0,
    "escarpins": 45.0,
    "sac": 50.0,
    "accessoire": 20.0,
    "objet": 10.0
}

MODELS_DIR = "models"
MODEL_Q30_PATH = os.path.join(MODELS_DIR, "resale_q30.joblib")
MODEL_Q50_PATH = os.path.join(MODELS_DIR, "resale_q50.joblib")
MODEL_PIPELINE_PATH = os.path.join(MODELS_DIR, "resale_pipeline.joblib")
MODEL_META_PATH = os.path.join(MODELS_DIR, "resale_meta.json")


@dataclass
class ResaleResult:
    """Résultat de l'estimation de revente."""
    revente_retenue: float
    revente_cible: float = 0.0
    revente_pessimiste: float = 0.0
    revente_optimiste: float = 0.0
    pred_q30: Optional[float] = None
    pred_q50: Optional[float] = None
    comp_price: float = 0.0
    cap_price: float = 0.0
    model_used: bool = False
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ResaleModelManager:
    """Gestionnaire de chargement et d'inférence des modèles de revente quantile."""

    def __init__(self):
        self.model_q30 = None
        self.model_q50 = None
        self.pipeline = None
        self.meta = {}
        self.loaded = False
        self.is_valid = False
        self._load()

    def _load(self):
        import joblib

        if os.path.exists(MODEL_Q30_PATH) and os.path.exists(MODEL_PIPELINE_PATH):
            try:
                self.model_q30 = joblib.load(MODEL_Q30_PATH)
                if os.path.exists(MODEL_Q50_PATH):
                    self.model_q50 = joblib.load(MODEL_Q50_PATH)
                self.pipeline = joblib.load(MODEL_PIPELINE_PATH)
                if os.path.exists(MODEL_META_PATH):
                    with open(MODEL_META_PATH, "r", encoding="utf-8") as f:
                        self.meta = json.load(f)
                    self.is_valid = bool(self.meta.get("valid", False))
                self.loaded = True
                logger.info(f"Modèles de revente quantiles q30/q50 chargés (valid={self.is_valid}).")
            except Exception as e:
                logger.warning(f"Impossible de charger les modèles de revente: {e}")

    def predict(
        self,
        category: str,
        brand_canonical: str,
        brand_line: str,
        tier: float,
        material_top: str,
        distinct_score: float,
        size_norm: str,
        month: int,
        bonus_score: float,
        malus_score: float,
        desc_len: int,
        embedding: Optional[np.ndarray] = None
    ) -> Tuple[Optional[float], Optional[float]]:
        """Calcule les prédictions quantile q30 et q50 en euros. Si invalide, retourne None."""
        if not self.loaded or not self.is_valid or self.model_q30 is None or self.pipeline is None:
            return None, None

        try:
            pca = self.pipeline.get("pca")
            cat_encoders = self.pipeline.get("encoders", {})

            # 1. Réduction PCA 32 dim
            if embedding is not None and pca is not None and len(embedding) == 512:
                emb_32 = pca.transform(embedding.reshape(1, -1))[0]
            else:
                emb_32 = np.zeros(32, dtype=np.float32)

            # 2. Encodage des catégoriels
            def encode_cat(col_name: str, val: str) -> int:
                mapping = cat_encoders.get(col_name, {})
                return mapping.get(str(val), mapping.get("__unknown__", 0))

            cat_code = encode_cat("category", category)
            brand_code = encode_cat("brand_canonical", brand_canonical)
            line_code = encode_cat("brand_line", brand_line)
            mat_code = encode_cat("material_top", material_top)
            size_code = encode_cat("size_normalized", size_norm)

            # Vecteur de features complet
            num_features = [
                tier,
                distinct_score,
                month,
                bonus_score,
                malus_score,
                float(desc_len),
                cat_code,
                brand_code,
                line_code,
                mat_code,
                size_code
            ]
            X = np.hstack([num_features, emb_32]).reshape(1, -1)

            pred_log_q30 = float(self.model_q30.predict(X)[0])
            pred_q30 = float(np.exp(pred_log_q30))

            pred_q50 = None
            if self.model_q50 is not None:
                pred_log_q50 = float(self.model_q50.predict(X)[0])
                pred_q50 = float(np.exp(pred_log_q50))

            return pred_q30, pred_q50
        except Exception as e:
            logger.debug(f"Erreur prédiction modèle de revente: {e}")
            return None, None


_MANAGER_INSTANCE: Optional[ResaleModelManager] = None


def get_resale_manager() -> ResaleModelManager:
    global _MANAGER_INSTANCE
    if _MANAGER_INSTANCE is None:
        _MANAGER_INSTANCE = ResaleModelManager()
    return _MANAGER_INSTANCE


BRAND_BENCHMARK_MEDIANS: Dict[str, float] = {
    # Tier 3 (Luxe prestige)
    "gucci": 180.0,
    "prada": 95.0,
    "miu miu": 90.0,
    "yves saint laurent": 90.0,
    "saint laurent": 90.0,
    "chanel": 220.0,
    "dior": 150.0,
    "fendi": 110.0,
    # Tier 1.5 (Créateurs & Grandes marques)
    "burberry": 45.0,
    "mugler": 42.0,
    "roberto cavalli": 40.0,
    "dolce & gabbana": 40.0,
    "versace": 38.0,
    "max mara": 38.0,
    "jean paul gaultier": 45.0,
    "kenzo": 32.0,
    "moschino": 30.0,
    # Tier 1.0 (Diffusion & Sportswear)
    "diesel": 35.0,
    "armani": 25.0,
    "guess": 18.0,
    "iceberg": 25.0
}

CATEGORY_BENCHMARKS: Dict[str, float] = {
    "manteau_fourrure": 60.0,
    "bottes": 42.0,
    "blazer": 38.0,
    "veste": 32.0,
    "escarpins": 28.0,
    "chaussures": 26.0,
    "sac": 25.0,
    "manteau": 35.0,
    "robe": 18.0,
    "combinaison": 22.0,
    "pull_maille": 16.0,
    "sweat": 18.0,
    "jupe": 16.0,
    "pantalon": 15.0,
    "jean": 15.0,
    "chemise_blouse": 14.0,
    "top": 12.0,
    "tshirt": 12.0,
    "short": 12.0,
    "accessoire": 12.0
}

NOBLE_MATERIALS_FACTORS: Dict[str, float] = {
    "shearling": 1.45,
    "vison": 1.45,
    "fourrure": 1.35,
    "fur": 1.35,
    "pelliccia": 1.35,
    "cachemire": 1.40,
    "cashmere": 1.40,
    "cuir veritable": 1.40,
    "cuir véritable": 1.40,
    "vera pelle": 1.40,
    "real leather": 1.40,
    "cuir": 1.30,
    "leather": 1.30,
    "pelle": 1.30,
    "daim": 1.25,
    "suede": 1.25,
    "camoscio": 1.25,
    "soie": 1.30,
    "silk": 1.30,
    "seta": 1.30,
    "alpaga": 1.25,
    "mohair": 1.25,
    "pure laine": 1.20,
    "pure wool": 1.20,
    "pura lana": 1.20,
    "velours": 1.15,
    "velvet": 1.15,
    "satin": 1.12
}

RARITY_FACTORS: Dict[str, float] = {
    "runway": 1.30,
    "defile": 1.30,
    "défilé": 1.30,
    "archive": 1.25,
    "monogramme": 1.15,
    "monogram": 1.15,
    "y2k": 1.12,
    "made in italy": 1.10,
    "vintage": 1.05
}

_SHOP_MEDIANS_CACHE: Optional[Tuple[
    Dict[Tuple[str, str], float],  # (brand, cat)
    Dict[str, float],               # brand
    Dict[Tuple[str, str], float],  # (line, cat)
    Dict[str, float],               # cat
    float                           # global
]] = None
_SHOP_SALES_MTIME: float = 0.0


def get_shop_medians(sales_path: str = "data/sales.parquet") -> Tuple[
    Dict[Tuple[str, str], float],
    Dict[str, float],
    Dict[Tuple[str, str], float],
    Dict[str, float],
    float
]:
    """Charge et met en cache les médianes de vente réelles de la boutique avec granularité marque."""
    global _SHOP_MEDIANS_CACHE, _SHOP_SALES_MTIME
    if os.path.exists(sales_path):
        try:
            mtime = os.path.getmtime(sales_path)
            if _SHOP_MEDIANS_CACHE is not None and mtime == _SHOP_SALES_MTIME:
                return _SHOP_MEDIANS_CACHE
            import pandas as pd
            df = pd.read_parquet(sales_path)
            global_med = float(df["price"].median()) if len(df) > 0 else 18.0

            # 1. (Marque, Catégorie) min 2 ventes
            brand_cat_medians: Dict[Tuple[str, str], float] = {}
            if "brand_canonical" in df.columns and "category_normalized" in df.columns:
                bc_grp = df.groupby(["brand_canonical", "category_normalized"])["price"].agg(["count", "median"])
                brand_cat_medians = {
                    (str(k[0]).lower().strip(), str(k[1]).lower().strip()): float(v["median"])
                    for k, v in bc_grp[bc_grp["count"] >= 2].iterrows()
                }

            # 2. Marque globale min 2 ventes
            brand_medians: Dict[str, float] = {}
            if "brand_canonical" in df.columns:
                b_grp = df.groupby("brand_canonical")["price"].agg(["count", "median"])
                brand_medians = {
                    str(k).lower().strip(): float(v["median"])
                    for k, v in b_grp[b_grp["count"] >= 2].iterrows()
                }

            # 3. (Ligne diffusion/principale, Catégorie) min 5 ventes
            line_cat_medians: Dict[Tuple[str, str], float] = {}
            if "brand_line" in df.columns and "category_normalized" in df.columns:
                lc_grp = df.groupby(["brand_line", "category_normalized"])["price"].agg(["count", "median"])
                line_cat_medians = {
                    (str(k[0]).lower().strip(), str(k[1]).lower().strip()): float(v["median"])
                    for k, v in lc_grp[lc_grp["count"] >= 5].iterrows()
                }

            # 4. Catégorie seule min 5 ventes
            cat_medians: Dict[str, float] = {}
            if "category_normalized" in df.columns:
                cat_grp = df.groupby("category_normalized")["price"].agg(["count", "median"])
                cat_medians = {
                    str(k).lower().strip(): float(v["median"])
                    for k, v in cat_grp[cat_grp["count"] >= 5].iterrows()
                }

            _SHOP_MEDIANS_CACHE = (brand_cat_medians, brand_medians, line_cat_medians, cat_medians, global_med)
            _SHOP_SALES_MTIME = mtime
            return _SHOP_MEDIANS_CACHE
        except Exception as e:
            logger.warning(f"Erreur chargement des médianes boutique depuis {sales_path}: {e}")

    return {}, {}, {}, {}, 18.0


def estimate_resale_price(
    item: Dict[str, Any],
    rules_category: str,
    brand_canonical: str,
    brand_line: str,
    tier: float,
    size_norm: str,
    bonus_score: float,
    malus_score: float,
    clip_category: Optional[str] = None,
    material_top: str = "inconnu",
    distinct_score: float = 0.5,
    distinct_pct: float = 0.5,
    taste_score: Optional[float] = None,
    embedding: Optional[np.ndarray] = None,
    comp_price: Optional[float] = None,
    config: Optional[Dict[str, Any]] = None,
    live_market: Optional[Dict[str, Any]] = None
) -> ResaleResult:
    """
    Système hybride de revente précis et calibré :
    1. Base Prix : Paire boutique (Marque, Catégorie) > Médiane Marque boutique > Benchmarks luxe > Catégorie > Ligne
    2. Value Boost : Multiplicateur Matières nobles (cuir, cachemire, soie) + Rareté (archive, runway)
    3. Ajustement Goût Rita : Dynamique P25 / P50 / P75 selon la force visuelle (0.80 à 1.30x)
    4. Décote de négociation Vinted (-12% par défaut) pour obtenir la revente nette sécurisée
    5. Fourchette de scénarios : Pessimiste (Vente flash), Cible, Optimiste
    """
    cfg = config or {}
    caps = cfg.get("resale_caps_eur", DEFAULT_RESALE_CAPS)

    # Catégorie retenue
    category = clip_category if clip_category and clip_category != "inconnu" else rules_category
    base_cap = float(caps.get(category, caps.get("robe", 25.0)))

    # Chargement des données historiques boutique
    b_c_map, b_map, line_cat_map, cat_map, global_med = get_shop_medians("data/sales.parquet")
    b_norm = (brand_canonical or "").lower().strip()
    c_norm = (category or "").lower().strip()

    # 1. Sélection de la base médiane la plus précise possible (priorité absolue au Vrai Marché Vinted)
    source = "global"
    has_live_market = False
    if live_market and live_market.get("sample_count", 0) >= 3:
        sample_cnt = live_market["sample_count"]
        med_p = float(live_market["median_price"])
        p25 = float(live_market["p25_price"])
        base_price = med_p
        source = f"vrai_marche_vinted({brand_canonical} x {category}: {sample_cnt} annonces, med {med_p:.0f}€, P25 {p25:.0f}€)"
        has_live_market = True
    elif (b_norm, c_norm) in b_c_map:
        base_price = b_c_map[(b_norm, c_norm)]
        source = f"boutique_pair({brand_canonical} x {category}: {base_price:.0f}€)"
    elif b_norm in b_map:
        base_price = b_map[b_norm]
        source = f"boutique_brand({brand_canonical}: {base_price:.0f}€)"
    elif b_norm in BRAND_BENCHMARK_MEDIANS:
        base_price = BRAND_BENCHMARK_MEDIANS[b_norm]
        source = f"benchmark_brand({brand_canonical}: {base_price:.0f}€)"
    elif (str(brand_line).lower().strip(), c_norm) in line_cat_map:
        base_price = line_cat_map[(str(brand_line).lower().strip(), c_norm)]
        source = f"boutique_line_cat({brand_line} x {category}: {base_price:.0f}€)"
    elif c_norm in cat_map:
        base_price = cat_map[c_norm] * max(1.0, float(tier) * 0.8)
        source = f"boutique_cat({category}: {base_price:.0f}€)"
    elif c_norm in CATEGORY_BENCHMARKS:
        base_price = CATEGORY_BENCHMARKS[c_norm] * max(1.0, float(tier) * 0.85)
        source = f"benchmark_cat({category}: {base_price:.0f}€)"
    else:
        base_price = global_med * max(1.0, float(tier) * 0.85)
        source = f"global_med({base_price:.0f}€)"

    # 2. Facteur Matières Nobles & Rareté (Value Boost)
    full_text = f"{item.get('title', '')} {item.get('raw_title', '')} {item.get('description', '')} {material_top}".lower()
    
    material_mult = 1.0
    detected_materials = []
    for mat_word, mult in NOBLE_MATERIALS_FACTORS.items():
        if mat_word in full_text:
            if mult > material_mult:
                material_mult = mult
            detected_materials.append(mat_word)

    rarity_mult = 1.0
    detected_rarity = []
    for r_word, mult in RARITY_FACTORS.items():
        if r_word in full_text:
            if mult > rarity_mult:
                rarity_mult = mult
            detected_rarity.append(r_word)

    # Multiplicateur combiné plafonné à 1.65
    attribute_boost = min(1.65, round(material_mult * rarity_mult, 2))

    # 3. Ajustement Goût Rita (Désirabilité & Vélocité si actif)
    taste_enabled = True
    if config is not None:
        taste_enabled = bool(config.get("taste_filter_enabled", True))

    if taste_enabled:
        eff_taste = taste_score if taste_score is not None else distinct_pct
        eff_taste = 0.50 if eff_taste is None else float(eff_taste)

        if eff_taste >= 0.80:
            taste_mult = 1.15 + (eff_taste - 0.80) * 0.75  # 1.15 à 1.30
        elif eff_taste >= 0.55:
            taste_mult = 0.95 + (eff_taste - 0.55) * 0.80  # 0.95 à 1.15
        else:
            taste_mult = 0.80 + max(0.0, eff_taste - 0.40) * 0.75  # 0.80 à 0.95
    else:
        taste_mult = 1.00

    # 4. Calcul du Prix de Revente Cible Brut
    revente_brute = base_price * attribute_boost * taste_mult

    # Plafond de sécurité dynamique adapté au prestige et aux matières nobles
    cap_price = round(base_cap * float(tier) * min(1.4, attribute_boost), 2)
    if tier >= 3.0 and cap_price < 150.0:
        cap_price = 150.0
    elif tier >= 1.5 and cap_price < 55.0:
        cap_price = 55.0

    # 5. Scénarios (Pessimiste / Vente flash vs Optimiste / Haut de panier)
    if has_live_market and live_market:
        revente_pessimiste = round(float(live_market.get("p25_price", revente_cible * 0.78)), 2)
        revente_optimiste = round(float(live_market.get("p75_price", revente_cible * 1.22)), 2)
        cap_price = max(cap_price, revente_optimiste)
    else:
        revente_pessimiste = round(revente_cible * 0.78, 2)  # -22% vente flash
        revente_optimiste = round(revente_cible * 1.22, 2)   # +22% acheteur coup de cœur

    revente_cible = round(max(8.0, min(revente_brute, cap_price)), 2)

    # 6. Décote de négociation acheteur Vinted pour la revente nette
    nego_discount = float(cfg.get("resale_negotiation_discount", 0.12))
    revente_retenue = round(revente_cible * (1.0 - nego_discount), 2)
    revente_retenue = max(6.0, revente_retenue)

    details = {
        "category": category,
        "brand_canonical": brand_canonical,
        "brand_line": brand_line,
        "tier": tier,
        "source": source,
        "base_price": base_price,
        "material_mult": material_mult,
        "rarity_mult": rarity_mult,
        "attribute_boost": attribute_boost,
        "detected_materials": detected_materials[:3],
        "detected_rarity": detected_rarity[:3],
        "taste_mult": round(taste_mult, 2),
        "revente_cible": revente_cible,
        "revente_pessimiste": revente_pessimiste,
        "revente_optimiste": revente_optimiste,
        "nego_discount": nego_discount,
        "cap_price": cap_price,
        "comp_price": comp_price or 0.0,
        "live_market": live_market
    }

    return ResaleResult(
        revente_retenue=revente_retenue,
        revente_cible=revente_cible,
        revente_pessimiste=revente_pessimiste,
        revente_optimiste=revente_optimiste,
        pred_q30=None,
        pred_q50=None,
        comp_price=comp_price or 0.0,
        cap_price=cap_price,
        model_used=False,
        details=details
    )
