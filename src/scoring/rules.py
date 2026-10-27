"""Étage A : Règles heuristiques et scoring local (Lot 2).

Analyse rapide basée sur les mots-clés, la taxonomie et la marque sans appel IA :
- Détection des catégories exclues (objets, accessoires non-sacs, enfants, contrefaçons)
- Application des bonus pondérés (coupes, imprimés, matières, époques, état)
- Application des malus pondérés (basiques, dévalués, défauts)
- Plafond bas (pantalons/jupes sans détail distinctif <= 40)
- Plafond basiques lignes diffusion (sweat/tshirt/pull uni <= 35)
- Pondération selon vitesse de vente par taille
- Seuil d'arrêt rules_min_score (défaut 35)
"""

import os
import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional, Tuple

from src.scoring.taxonomy import (
    detect_category,
    normalize_brand,
    normalize_size,
    contains_whole_word,
    normalize_text
)

logger = logging.getLogger("VintedBot.Scoring.Rules")

CONFIG_PATH = "config.json"


@dataclass
class RuleResult:
    """Résultat structuré de l'évaluation par l'Étage A (Règles)."""
    category: str
    brand_canonical: str
    brand_line: str
    tier: float
    score: float
    bonus_hits: Dict[str, float] = field(default_factory=dict)
    malus_hits: Dict[str, float] = field(default_factory=dict)
    hard_reject: bool = False
    reasons: List[str] = field(default_factory=list)
    size_normalized: str = "NC"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


_CONFIG_CACHE: Optional[Dict[str, Any]] = None
_CONFIG_MTIME: float = 0.0


def load_rules_config(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Charge la configuration ou extrait les sections nécessaires aux règles avec mise en cache."""
    global _CONFIG_CACHE, _CONFIG_MTIME
    if config:
        return config
    if os.path.exists(CONFIG_PATH):
        try:
            mtime = os.path.getmtime(CONFIG_PATH)
            if _CONFIG_CACHE is not None and mtime == _CONFIG_MTIME:
                return _CONFIG_CACHE
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                _CONFIG_CACHE = json.load(f)
                _CONFIG_MTIME = mtime
                return _CONFIG_CACHE
        except Exception as e:
            logger.warning(f"Impossible de lire {CONFIG_PATH}: {e}")
    return _CONFIG_CACHE or {}


DIFFUSION_BASIC_CATEGORIES = {"tshirt", "top", "chemise_blouse", "sweat", "pull_maille", "jean"}
DIFFUSION_TARGET_BRANDS = {
    "armani", "emporio armani", "armani jeans", "kenzo", "love moschino",
    "moschino jeans", "versace jeans", "diesel", "guess"
}


def is_diffusion_target_brand(brand_canonical: str, brand_line: str, raw_brand: str = "") -> bool:
    """Vérifie si la marque appartient aux lignes diffusion ciblées."""
    b_can = normalize_text(brand_canonical)
    b_raw = normalize_text(raw_brand)
    for tb in DIFFUSION_TARGET_BRANDS:
        if tb in b_can or tb in b_raw:
            return True
    return brand_line == "diffusion"


def evaluate_rules(
    item: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
    allow_bags: bool = True,
    distinct_pct: Optional[float] = None
) -> RuleResult:
    """
    Évalue un article selon l'Étage A (Règles locales).
    Budget calcul : < 5 ms par annonce sur CPU.
    """
    cfg = load_rules_config(config)

    # 1. Extraction des champs bruts
    title = str(item.get("title") or "")
    raw_title = str(item.get("raw_title") or "")
    description = str(item.get("description") or "")
    raw_brand = str(item.get("brand_title") or item.get("brand") or "")
    raw_size = str(item.get("size_title") or item.get("size") or "")
    
    full_title = f"{title} {raw_title}".strip()
    full_text = f"{full_title} {description}".strip()
    norm_full_title = normalize_text(full_title)
    norm_full_text = normalize_text(full_text)

    # 2. Taxonomie normalisée
    category = detect_category(full_title, description)
    brand_canonical, brand_line, tier = normalize_brand(raw_brand, full_title)
    size_norm = normalize_size(raw_size, category)

    reasons: List[str] = []
    bonus_hits: Dict[str, float] = {}
    malus_hits: Dict[str, float] = {}
    cuts_hits: Dict[str, float] = {}
    patterns_hits: Dict[str, float] = {}
    materials_hits: Dict[str, float] = {}

    # 3. Vérifications Hard Reject (Objets, Accessoires, Enfants, Contrefaçons)
    # 3a. Objets non vêtements
    if category == "objet":
        return RuleResult(
            category=category,
            brand_canonical=brand_canonical,
            brand_line=brand_line,
            tier=tier,
            score=0.0,
            hard_reject=True,
            reasons=["Objet non vêtement exclu (déco, vaisselle, boîte, cintre, livre, etc.)"],
            size_normalized=size_norm
        )

    # 3b. Accessoires (sauf sac si allow_bags)
    if category == "accessoire":
        return RuleResult(
            category=category,
            brand_canonical=brand_canonical,
            brand_line=brand_line,
            tier=tier,
            score=0.0,
            hard_reject=True,
            reasons=["Accessoire exclu (hors sac)"],
            size_normalized=size_norm
        )

    # 3c. Sac exclu si la recherche interdit les sacs
    if category == "sac" and not allow_bags:
        return RuleResult(
            category=category,
            brand_canonical=brand_canonical,
            brand_line=brand_line,
            tier=tier,
            score=0.0,
            hard_reject=True,
            reasons=["Sac exclu par les filtres de la recherche"],
            size_normalized=size_norm
        )

    # 3d. Contrefaçons & fausses imitations ("style X", "inspiré", "dupe", "tipo"...)
    fake_words = cfg.get("rule_fake_words", [
        "style", "facon", "façon", "genre", "look", "inspire", "inspiré", "dupe", "copie",
        "fausse", "faux", "imitation", "replique", "réplique", "stile", "tipo", "ispirato",
        "falso", "falsa", "imitazione", "replica", "estilo", "inspired", "fake", "simil"
    ])
    for fw in fake_words:
        if contains_whole_word(norm_full_title, fw, text_is_normalized=True):
            return RuleResult(
                category=category,
                brand_canonical=brand_canonical,
                brand_line=brand_line,
                tier=tier,
                score=0.0,
                hard_reject=True,
                reasons=[f"Mention de contrefaçon ou imitation détectée : '{fw}'"],
                size_normalized=size_norm
            )

    # 3d-bis. Exclusion hauts Kenzo tête de tigre / lion
    if "kenzo" in brand_canonical.lower() or "kenzo" in raw_brand.lower():
        feline_words = ["tigre", "tiger", "tigers", "tigres", "lion", "lions", "leone", "leoni", "tigerhead", "tiger head", "tete de tigre", "tete de lion"]
        if any(contains_whole_word(norm_full_text, fw, text_is_normalized=True) for fw in feline_words):
            top_words = ["sweat", "pull", "tshirt", "t-shirt", "tee", "top", "hoodie", "cardigan", "gilet", "chemise", "debardeur", "maglia", "sudadera", "camiseta", "haut"]
            if category in {"tshirt", "top", "chemise_blouse", "sweat", "pull_maille"} or any(contains_whole_word(norm_full_text, tw, text_is_normalized=True) for tw in top_words):
                return RuleResult(
                    category=category,
                    brand_canonical=brand_canonical,
                    brand_line=brand_line,
                    tier=tier,
                    score=0.0,
                    hard_reject=True,
                    reasons=["Haut Kenzo tête de tigre / lion exclu"],
                    size_normalized=size_norm
                )

    # 3e-bis. Basiques des lignes diffusion (catégories basiques + diffusion + distinct_pct < 0.8)
    if distinct_pct is not None:
        if category in DIFFUSION_BASIC_CATEGORIES and is_diffusion_target_brand(brand_canonical, brand_line, raw_brand):
            if distinct_pct < 0.8:
                return RuleResult(
                    category=category,
                    brand_canonical=brand_canonical,
                    brand_line=brand_line,
                    tier=tier,
                    score=0.0,
                    hard_reject=True,
                    reasons=[f"Basique ligne diffusion rejeté : distinct_pct ({distinct_pct:.2f} < 0.80)"],
                    size_normalized=size_norm
                )

    # 3e. Ligne et taille enfant
    if size_norm == "ENFANT":
        return RuleResult(
            category=category,
            brand_canonical=brand_canonical,
            brand_line=brand_line,
            tier=tier,
            score=0.0,
            hard_reject=True,
            reasons=[f"Article enfant exclu (taille enfant '{raw_size}')"],
            size_normalized="ENFANT"
        )

    child_words = cfg.get("rule_child_words", [
        "enfant", "enfants", "kids", "junior", "garcon", "garçon", "fille", "fillette", "fillettes",
        "garconnet", "bebe", "bébé", "baby", "bambino", "bambina", "bambini", "bambine", "kind",
        "kinder", "nino", "niño", "nina", "niña", "toddler", "infant", "youth", "adolescent", "ado"
    ])
    full_search_text = f"{norm_full_text} {normalize_text(raw_brand)} {normalize_text(raw_size)}"
    for cw in child_words:
        if contains_whole_word(full_search_text, cw, text_is_normalized=True):
            return RuleResult(
                category=category,
                brand_canonical=brand_canonical,
                brand_line=brand_line,
                tier=tier,
                score=0.0,
                hard_reject=True,
                reasons=[f"Article enfant détecté : '{cw}'"],
                size_normalized=size_norm
            )

    # 4. Bonus pondérés (patterns, materials, cuts, era, condition)
    bonus_config = cfg.get("rule_bonus_words", {})
    
    # Imprimés
    for word, weight in bonus_config.get("patterns", {}).items():
        if contains_whole_word(norm_full_text, word, text_is_normalized=True):
            bonus_hits[f"pattern:{word}"] = float(weight)
            patterns_hits[word] = float(weight)

    # Matières
    for word, weight in bonus_config.get("materials", {}).items():
        if contains_whole_word(norm_full_text, word, text_is_normalized=True):
            bonus_hits[f"material:{word}"] = float(weight)
            materials_hits[word] = float(weight)

    # Coupes
    for word, weight in bonus_config.get("cuts", {}).items():
        if contains_whole_word(norm_full_text, word, text_is_normalized=True):
            bonus_hits[f"cut:{word}"] = float(weight)
            cuts_hits[word] = float(weight)

    # Époque (vintage, y2k, made in italy)
    for word, weight in bonus_config.get("era", {}).items():
        if contains_whole_word(norm_full_text, word, text_is_normalized=True):
            bonus_hits[f"era:{word}"] = float(weight)

    # État (neuf avec étiquette)
    for word, weight in bonus_config.get("condition", {}).items():
        if contains_whole_word(norm_full_text, word, text_is_normalized=True):
            bonus_hits[f"condition:{word}"] = float(weight)

    # 5. Malus pondérés (basiques, pièces dévaluées, défauts)
    malus_config = cfg.get("rule_malus_words", {})
    for word, weight in malus_config.items():
        if contains_whole_word(norm_full_text, word, text_is_normalized=True):
            malus_hits[word] = float(weight)

    # 6. Score de base selon le palier de marque (Boost grandes marques)
    if tier >= 3.0:
        base_score = 68.0
        reasons.append(f"Marque prestige Tier 3 ({brand_canonical}) : base 68 (boosté)")
    elif tier >= 1.5:
        base_score = 62.0
        reasons.append(f"Marque créateur Tier 1.5 ({brand_canonical}) : base 62 (boosté)")
    elif brand_canonical != "Sans marque":
        base_score = 45.0
        reasons.append(f"Marque diffusion Tier 1.0 ({brand_canonical}) : base 45")
    else:
        if cfg.get("only_target_brands", True):
            return RuleResult(
                category=category,
                brand_canonical=brand_canonical,
                brand_line=brand_line,
                tier=tier,
                score=0.0,
                hard_reject=True,
                reasons=["Pièce sans marque ciblée exclue (Focus marques uniquement)"],
                size_normalized=size_norm
            )
        base_score = 35.0
        reasons.append("Pièce sans marque reconnue : base 35")

    total_bonus = sum(bonus_hits.values())
    total_malus = sum(malus_hits.values())

    # 7. Vitesse de vente par taille
    size_weights = cfg.get("size_velocity_weights", {})
    size_weight = float(size_weights.get(size_norm, 0.0))
    if size_weight != 0:
        reasons.append(f"Taille {size_norm} ({size_weight:+.1f} pts)")

    # Calcul préliminaire
    score = base_score + total_bonus - total_malus + size_weight

    if bonus_hits:
        reasons.append(f"Bonus ({len(bonus_hits)}) : +{total_bonus:.1f} pts")
    if malus_hits:
        reasons.append(f"Malus ({len(malus_hits)}) : -{total_malus:.1f} pts")

    # 8. Règle bas (pantalons, jeans, shorts, jupes) :
    # Sans aucun bonus de coupe, motif ou matière -> score plafonné à 40
    has_bottom_detail = bool(cuts_hits or patterns_hits or materials_hits)
    if category in ("pantalon", "jean", "short", "jupe") and not has_bottom_detail:
        if score > 40.0:
            score = 40.0
            reasons.append("Plafond Règle Bas : aucun détail de coupe/motif/matière (score max 40)")

    # 9. Règle basiques de lignes diffusion :
    # Catégorie tshirt, top, sweat, pull_maille, jean ET ligne diffusion ET aucun bonus -> score plafonné à 35
    has_any_bonus = bool(bonus_hits)
    if (
        category in ("tshirt", "top", "sweat", "pull_maille", "jean")
        and brand_line == "diffusion"
        and not has_any_bonus
    ):
        if score > 35.0:
            score = 35.0
            reasons.append("Plafond Règle Diffusion : basique uni sans bonus (score max 35)")

    # 10. Bornage du score
    score = max(0.0, min(100.0, score))

    # 11. Seuil rules_min_score (défaut 35) : arrêt si en dessous
    rules_min_score = float(cfg.get("rules_min_score", 35.0))
    hard_reject = False

    if score < rules_min_score:
        hard_reject = True
        reasons.append(f"Score règles ({score:.1f}) inférieur au seuil minimal ({rules_min_score:.1f})")

    return RuleResult(
        category=category,
        brand_canonical=brand_canonical,
        brand_line=brand_line,
        tier=tier,
        score=round(score, 1),
        bonus_hits=bonus_hits,
        malus_hits=malus_hits,
        hard_reject=hard_reject,
        reasons=reasons,
        size_normalized=size_norm
    )
