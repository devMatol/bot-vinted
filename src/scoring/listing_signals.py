"""Étage D : Signaux annonce et vendeur (Lot 5).

Analyse des signaux contextuels :
- Fraîcheur : âge de l'annonce (< 10 min bonus fort)
- Vélocité favoris : favoris par minute (radar In-Demand)
- Vendeur pressé : mots d'urgence, déménagement, vide-dressing
- Vendeur peu informé : titre court/générique pour une marque premium (sous-évaluation probable)
- Détection de lots / bundles
- Qualité d'annonce : photos, détection d'étiquette, longueur de description
- Fiabilité vendeur : note moyenne et volume d'avis
"""

import os
import re
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional, Tuple

from src.scoring.taxonomy import contains_whole_word, normalize_text


@dataclass
class ListingSignalsResult:
    """Résultat structuré de l'Étage D."""
    score: float  # 0 à 100
    freshness_bonus: float = 0.0
    velocity_bonus: float = 0.0
    urgent_seller_bonus: float = 0.0
    underinformed_bonus: float = 0.0
    bundle_detected: bool = False
    quality_score: float = 0.0
    seller_trust_score: float = 0.0
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def evaluate_listing_signals(
    item: Dict[str, Any],
    tier: float = 1.0,
    label_detected: bool = False,
    config: Optional[Dict[str, Any]] = None
) -> ListingSignalsResult:
    """
    Évalue les signaux de l'annonce et du vendeur.
    Budget calcul : < 1 ms sur CPU.
    """
    cfg = config or {}
    reasons: List[str] = []
    
    # Base score
    total_score = 50.0

    title = str(item.get("title") or "")
    description = str(item.get("description") or "")
    norm_desc = normalize_text(description)
    norm_title = normalize_text(title)

    # 1. Fraîcheur de l'annonce
    freshness_bonus = 0.0
    created_at_val = item.get("created_at_ts") or item.get("created_at")
    age_minutes = None

    if created_at_val:
        try:
            if isinstance(created_at_val, (int, float)):
                item_dt = datetime.fromtimestamp(created_at_val, tz=timezone.utc)
            else:
                item_dt = pd_to_dt(created_at_val)
            if item_dt:
                now_dt = datetime.now(timezone.utc)
                age_minutes = max(0.1, (now_dt - item_dt).total_seconds() / 60.0)
                if age_minutes <= 10.0:
                    freshness_bonus = 15.0
                    reasons.append(f"Ultra-frais : publié il y a {int(age_minutes)} min (+15)")
                elif age_minutes <= 30.0:
                    freshness_bonus = 10.0
                    reasons.append(f"Très frais : publié il y a {int(age_minutes)} min (+10)")
                elif age_minutes <= 60.0:
                    freshness_bonus = 5.0
                    reasons.append(f"Frais : publié il y a {int(age_minutes)} min (+5)")
        except Exception:
            pass

    # 2. Vélocité des favoris
    fav_count = int(item.get("favourite_count") or item.get("favourites_count") or 0)
    velocity_bonus = 0.0
    if age_minutes and age_minutes > 0:
        rate = fav_count / age_minutes
        if rate >= 0.5:
            velocity_bonus = 10.0
            reasons.append(f"Forte vélocité favoris : {rate:.1f} fav/min (+10)")
        elif rate >= 0.2:
            velocity_bonus = 5.0
            reasons.append(f"Vélocité favoris active : {rate:.1f} fav/min (+5)")
    elif fav_count >= 10:
        velocity_bonus = 5.0
        reasons.append(f"Article populaire : {fav_count} favoris (+5)")

    # 3. Vendeur pressé
    urgent_keywords = cfg.get("urgent_seller_words", [
        "urgent", "urgente", "demenagement", "déménagement", "vide dressing", "vide-dressing",
        "faire de la place", "faire du tri", "braderie", "liquidation", "trasloco", "mudanza", "umzug"
    ])
    urgent_seller_bonus = 0.0
    for uk in urgent_keywords:
        if contains_whole_word(norm_desc, uk, text_is_normalized=True):
            urgent_seller_bonus = 10.0
            reasons.append(f"Vendeur pressé détecté : '{uk}' (+10)")
            break

    # 4. Vendeur peu informé
    # Titre très court / générique pour une marque premium (tier >= 1.5)
    underinformed_bonus = 0.0
    title_words = norm_title.split()
    generic_titles = {"pull", "sweat", "jupe", "robe", "pantalon", "jean", "top", "veste", "blazer", "manteau", "giacca", "gonna", "maglia", "vestido"}
    if tier >= 1.5:
        if len(title_words) <= 2 or norm_title in generic_titles:
            underinformed_bonus = 15.0
            reasons.append("Vendeur sous-informé probable (titre générique sur marque premium, +15)")

    # 5. Détection de Lot / Bundle
    bundle_detected = False
    bundle_words = ["lot de", "lot", "pack", "x2", "x3", "x4", "set de", "ensemble"]
    for bw in bundle_words:
        if contains_whole_word(norm_title, bw, text_is_normalized=True):
            bundle_detected = True
            reasons.append(f"Lot / Bundle détecté : '{bw}'")
            break

    # 6. Qualité de l'annonce
    photos_count = len(item.get("photos") or item.get("photo_urls") or [])
    quality_score = 0.0
    if photos_count >= 5:
        quality_score += 5.0
    if label_detected:
        quality_score += 5.0
        reasons.append("Photo d'étiquette détectée (+5)")
    if len(description) >= 60:
        quality_score += 3.0

    # 7. Fiabilité vendeur
    seller_trust_score = 0.0
    user_info = item.get("user") or {}
    feedback_reputation = user_info.get("feedback_reputation")
    feedback_count = int(user_info.get("feedback_count") or user_info.get("positive_feedback_count") or 0)

    if feedback_reputation is not None:
        try:
            rep = float(feedback_reputation)
            if rep >= 0.96 and feedback_count >= 10:
                seller_trust_score = 5.0
            elif rep < 0.80 and feedback_count >= 3:
                seller_trust_score = -10.0
                reasons.append("Avis vendeur faibles (< 80%, -10)")
        except (ValueError, TypeError):
            pass

    # Calcul du score final Étage D borné entre 0 et 100
    total_score = total_score + freshness_bonus + velocity_bonus + urgent_seller_bonus + underinformed_bonus + quality_score + seller_trust_score
    if bundle_detected:
        total_score += 5.0

    total_score = float(max(0.0, min(100.0, total_score)))

    return ListingSignalsResult(
        score=total_score,
        freshness_bonus=freshness_bonus,
        velocity_bonus=velocity_bonus,
        urgent_seller_bonus=urgent_seller_bonus,
        underinformed_bonus=underinformed_bonus,
        bundle_detected=bundle_detected,
        quality_score=quality_score,
        seller_trust_score=seller_trust_score,
        reasons=reasons
    )


def pd_to_dt(val: Any) -> Optional[datetime]:
    """Convertit une chaîne ou timestamp en datetime UTC."""
    try:
        if isinstance(val, datetime):
            return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
        val_str = str(val).strip()
        if val_str.endswith("Z"):
            val_str = val_str[:-1] + "+00:00"
        dt = datetime.fromisoformat(val_str)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None
