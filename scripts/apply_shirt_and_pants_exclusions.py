import os
import re

def update_i18n_keywords():
    path = "src/i18n_keywords.py"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    new_definitions = '''BASIC_SHIRTS_KEYWORDS = [
    # Français
    "chemise classique", "chemise de bureau", "chemise basique", "chemise homme classique", "chemise homme",
    "chemise blanche classique", "chemise blanche", "chemise bleue classique", "chemise bleue", "chemise ciel",
    "chemise popeline", "chemise unie", "chemise coton basique", "chemise regular", "chemise slim fit",
    "chemise a rayures", "chemise à rayures", "chemise rayee", "chemise rayée", "chemise business",
    "chemisier classique", "chemisier basique", "chemisier blanc", "chemisier uni",
    # Italien
    "camicia classica", "camicia uomo", "camicia uomo classica", "camicia bianca", "camicia celeste",
    "camicia azzurra", "camicia blu", "camicia basica", "camicia ufficio", "camicia cotone basica",
    "camicia regular", "camicia slim fit", "camicia a righe", "camicia righe", "camicia business",
    # Espagnol
    "camisa clasica", "camisa clásica", "camisa hombre clasica", "camisa hombre", "camisa basica", "camisa básica",
    "camisa blanca clasica", "camisa blanca", "camisa azul clasica", "camisa azul", "camisa oficina",
    "camisa a rayas", "camisa rayas", "camisa popelin", "camisa lisa",
    # Anglais
    "basic shirt", "classic shirt", "plain shirt", "office shirt", "formal shirt", "dress shirt",
    "white dress shirt", "blue dress shirt", "regular shirt", "striped shirt", "oxford shirt",
    "white shirt", "plain button shirt", "business shirt",
    # Allemand / Néerlandais
    "klassisches hemd", "business hemd", "basis hemd", "weisses hemd", "weißes hemd", "blaues hemd", "streifenhemd",
    "effen hemd", "klassiek hemd", "wit overhemd", "blauw overhemd"
]

BASIC_PANTS_KEYWORDS = [
    # Français
    "pantalon classique", "pantalon droit classique", "pantalon de bureau", "pantalon tailleur basique",
    "pantalon tailleur classique", "pantalon noir classique", "pantalon gris classique", "pantalon basique",
    "pantalon simple", "pantalon chino basique", "pantalon regular classique", "pantalon a pinces classique",
    "pantalon à pinces classique", "pantalon costume", "pantalon de costume", "pantalon ville",
    "pantalon droit noir", "pantalon droit basique", "pantalon uni",
    # Italien
    "pantaloni classici", "pantalone classico", "pantaloni sartoriali", "pantalone sartoriale",
    "pantaloni ufficio", "pantalone ufficio", "pantalone basico", "pantaloni basici",
    "pantalone nero classico", "pantalone grigio classico", "pantalone abito", "pantaloni da abito",
    "pantalone dritto", "pantaloni dritti", "pantaloni eleganti basic",
    # Espagnol
    "pantalon clasico", "pantalón clásico", "pantalones clasicos", "pantalones clásicos",
    "pantalon sastre clasico", "pantalones de vestir basicos", "pantalon oficina", "pantalon traje",
    "pantalones traje", "pantalon basico", "pantalon recto clasico", "pantalon negro basico",
    # Anglais
    "classic trousers", "plain trousers", "basic trousers", "formal trousers", "office trousers",
    "dress pants", "classic slacks", "basic pants", "plain pants", "suit trousers",
    "straight trousers", "regular trousers", "work trousers", "black trousers",
    # Allemand / Néerlandais
    "klassische hose", "anzughose", "business hose", "schwarze hose",
    "klassieke pantalon", "nette broek", "zwarte pantalon"
]

DISTINCTIVE_SHIELD_KEYWORDS = [
    # Matières nobles / luxueuses
    "soie", "silk", "seta", "seda", "seide",
    "cuir", "leather", "pelle", "cuero", "leder",
    "velours", "velvet", "velluto", "terciopelo", "samt",
    "dentelle", "lace", "pizzo", "encaje", "spitze",
    "satin", "raso",
    "lin", "linen", "lino", "leinen",
    "mousseline", "chiffon", "georgette", "organza", "tulle",
    "cachemire", "cashmere", "kaschmir",
    # Motifs et imprimés iconiques
    "tartan", "nova check", "check", "carreaux", "quadri", "cuadros", "vichy", "gingham",
    "imprime", "imprimé", "print", "printed", "stampa", "stampato", "estampado", "druck", "bedruckt", "patterned",
    "fleur", "fleurs", "floral", "florale", "floreale", "blumen", "flower", "flowers",
    "barocco", "baroque", "barroco", "foulard",
    "animalier", "leopard", "léopard", "leopardo", "zebra", "zebre", "zèbre",
    # Détails / finitions couture
    "brode", "brodé", "broderie", "embroidered", "embroidery", "ricamato", "ricamo", "bordado",
    "sequin", "sequins", "strass", "paillette", "paillettes", "glitter", "lurex", "perles", "beaded",
    "volant", "volants", "jabot", "plisse", "plissé", "pleated", "drape", "drapé",
    # Défilés / Archives
    "runway", "defile", "défilé", "sfilata", "desfile", "archive", "collector",
    # Coupes très spécifiques pantalon non-classique
    "cargo", "palazzo", "flare", "patte d'eph", "patte d eph", "wide leg"
]
'''

    if "BASIC_SHIRTS_KEYWORDS" not in content:
        # We place new definitions before BASIC_ITEMS_KEYWORDS and extend BASIC_ITEMS_KEYWORDS
        content = content.replace("BASIC_ITEMS_KEYWORDS = [", new_definitions + "\nBASIC_ITEMS_KEYWORDS = BASIC_SHIRTS_KEYWORDS + BASIC_PANTS_KEYWORDS + [\n")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print("Updated src/i18n_keywords.py with BASIC_SHIRTS_KEYWORDS, BASIC_PANTS_KEYWORDS and DISTINCTIVE_SHIELD_KEYWORDS")
    else:
        print("src/i18n_keywords.py already contains BASIC_SHIRTS_KEYWORDS")


def update_filters():
    path = "src/filters.py"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Add import of DISTINCTIVE_SHIELD_KEYWORDS
    if "DISTINCTIVE_SHIELD_KEYWORDS" not in content:
        content = content.replace(
            "    BASIC_ITEMS_KEYWORDS,",
            "    BASIC_ITEMS_KEYWORDS,\n    DISTINCTIVE_SHIELD_KEYWORDS,"
        )

    # In prefilter, wrap 3f with DISTINCTIVE_SHIELD_KEYWORDS check
    old_3f_prefilter = """        # 3f. Exclusion des pièces basiques (t-shirts simples / unis, jeans bleus classiques)
        for bi in BASIC_ITEMS_KEYWORDS:
            if contains_whole_word(norm_title, bi):
                return False, f"Pièce basique exclue ('{bi}')"

        basic_markers = ["basique", "basica", "básica", "basico", "básico", "simple", "semplice"]
        if any(contains_whole_word(norm_title, bm) for bm in basic_markers):
            cloth_markers = ["tshirt", "t-shirt", "tee", "top", "pull", "sweat", "jean", "jeans", "pantalon", "camicia", "chemise", "maglia", "camiseta"]
            if any(contains_whole_word(norm_title, cm) for cm in cloth_markers):
                return False, "Pièce explicitement qualifiée de basique / simple\""""

    new_3f_prefilter = """        # 3f. Exclusion des pièces basiques (t-shirts simples, jeans classiques, chemises et pantalons basiques)
        has_shield = any(contains_whole_word(norm_title, sk) for sk in DISTINCTIVE_SHIELD_KEYWORDS)
        if not has_shield:
            for bi in BASIC_ITEMS_KEYWORDS:
                if contains_whole_word(norm_title, bi):
                    return False, f"Pièce basique exclue ('{bi}')"

            basic_markers = ["basique", "basica", "básica", "basico", "básico", "simple", "semplice"]
            if any(contains_whole_word(norm_title, bm) for bm in basic_markers):
                cloth_markers = ["tshirt", "t-shirt", "tee", "top", "pull", "sweat", "jean", "jeans", "pantalon", "camicia", "chemise", "maglia", "camiseta"]
                if any(contains_whole_word(norm_title, cm) for cm in cloth_markers):
                    return False, "Pièce explicitement qualifiée de basique / simple\""""

    if old_3f_prefilter in content:
        content = content.replace(old_3f_prefilter, new_3f_prefilter)
        print("Updated DealEvaluator.prefilter in src/filters.py with shield check")
    else:
        print("Pre-filter 3f block already updated or not matched exactly")

    # In full_filter, add shield and basic check on description
    full_filter_target = """        # 3c. Exclusion des hauts Kenzo tête de tigre / lion (sur description et texte complet)
        if "kenzo" in normalize_text(title) or "kenzo" in norm_brand:
            feline_kws = ["tigre", "tiger", "tigers", "tigres", "lion", "lions", "leone", "leoni", "tigerhead", "tiger head", "tete de tigre", "tete de lion"]
            norm_full = normalize_text(full_text)
            if any(contains_whole_word(norm_full, fk) for fk in feline_kws):
                top_kws = ["sweat", "pull", "tshirt", "t-shirt", "tee", "top", "hoodie", "cardigan", "gilet", "chemise", "debardeur", "maglia", "sudadera", "camiseta", "haut"]
                detected_c = item.get("detected_category") or ""
                if detected_c in {"tshirt", "top", "chemise_blouse", "sweat", "pull_maille"} or any(contains_whole_word(norm_full, tk) for tk in top_kws):
                    return False, "Haut Kenzo tête de tigre / lion exclu\""""

    full_filter_addition = full_filter_target + """

        # 3d. Exclusion des pièces basiques (chemises, pantalons, t-shirts, jeans) sur texte complet
        norm_full_item = normalize_text(full_text)
        has_shield_full = any(contains_whole_word(norm_full_item, sk) for sk in DISTINCTIVE_SHIELD_KEYWORDS)
        if not has_shield_full:
            for bi in BASIC_ITEMS_KEYWORDS:
                if contains_whole_word(norm_full_item, bi):
                    return False, f"Pièce basique exclue ('{bi}')\""""

    if full_filter_target in content and "# 3d. Exclusion des pièces basiques" not in content:
        content = content.replace(full_filter_target, full_filter_addition)
        print("Updated DealEvaluator.full_filter in src/filters.py with basic items check")

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def update_rules():
    path = "src/scoring/rules.py"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Add import of DISTINCTIVE_SHIELD_KEYWORDS
    if "DISTINCTIVE_SHIELD_KEYWORDS" not in content:
        content = content.replace(
            "    BASIC_ITEMS_KEYWORDS\n)",
            "    BASIC_ITEMS_KEYWORDS,\n    DISTINCTIVE_SHIELD_KEYWORDS\n)"
        )

    # In DIFFUSION_BASIC_CATEGORIES add pantalon
    if '"jean"' in content and '"pantalon"' not in content:
        content = content.replace(
            'DIFFUSION_BASIC_CATEGORIES = {"tshirt", "top", "chemise_blouse", "sweat", "pull_maille", "jean"}',
            'DIFFUSION_BASIC_CATEGORIES = {"tshirt", "top", "chemise_blouse", "sweat", "pull_maille", "jean", "pantalon"}'
        )

    # In evaluate_rules, wrap BASIC_ITEMS_KEYWORDS with shield
    old_basic_rules = """    for bi in BASIC_ITEMS_KEYWORDS:
        if contains_whole_word(norm_full_text, bi, text_is_normalized=True):
            return RuleResult(
                category=category,
                brand_canonical=brand_canonical,
                brand_line=brand_line,
                tier=tier,
                score=0.0,
                hard_reject=True,
                reasons=[f"Pièce basique exclue : '{bi}'"],
                size_normalized=size_norm
            )"""

    new_basic_rules = """    has_shield = any(contains_whole_word(norm_full_text, sk, text_is_normalized=True) for sk in DISTINCTIVE_SHIELD_KEYWORDS)
    if not has_shield:
        for bi in BASIC_ITEMS_KEYWORDS:
            if contains_whole_word(norm_full_text, bi, text_is_normalized=True):
                return RuleResult(
                    category=category,
                    brand_canonical=brand_canonical,
                    brand_line=brand_line,
                    tier=tier,
                    score=0.0,
                    hard_reject=True,
                    reasons=[f"Pièce basique exclue : '{bi}'"],
                    size_normalized=size_norm
                )"""

    if old_basic_rules in content:
        content = content.replace(old_basic_rules, new_basic_rules)
        print("Updated evaluate_rules in src/scoring/rules.py with shield check")

    # In rule 8 (Plafond Règle Bas), extend to chemise_blouse
    old_rule_8 = """    has_bottom_detail = bool(cuts_hits or patterns_hits or materials_hits)
    if category in ("pantalon", "jean", "short", "jupe") and not has_bottom_detail:
        if score > 40.0:
            score = 40.0
            reasons.append("Plafond Règle Bas : aucun détail de coupe/motif/matière (score max 40)")"""

    new_rule_8 = """    has_bottom_detail = bool(cuts_hits or patterns_hits or materials_hits)
    if category in ("chemise_blouse", "pantalon", "jean", "short", "jupe") and not has_bottom_detail:
        if score > 38.0:
            score = 38.0
            reasons.append("Plafond Basique : chemise ou bas sans détail distinctif (score max 38)")"""

    if old_rule_8 in content:
        content = content.replace(old_rule_8, new_rule_8)
        print("Updated rule 8 in src/scoring/rules.py with chemise and pantalon ceiling")

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def update_clip_scorer():
    path = "src/scoring/clip_scorer.py"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    old_clip_block = """        # Rejet visuel des pièces basiques (t-shirts simples unis et jeans bleus classiques)
        p_plain = pattern_scores.get("plain", 0.0)
        if clip_category == "tshirt":
            if p_plain >= 0.58 and distinct_score < 0.42:
                hard_reject = True
                reasons.append(f"CLIP rejet pièce basique : t-shirt simple uni sans motif ({p_plain*100:.0f}%, distinctivité {distinct_score*100:.0f}%)")
        elif clip_category == "jean":
            is_plain_jean = (p_plain >= 0.55 and distinct_score < 0.38)
            is_runway = style_scores.get("runway_luxury", 0.0) >= 0.45 or style_scores.get("vintage_designer", 0.0) >= 0.50
            if is_plain_jean and not is_runway:
                hard_reject = True
                reasons.append(f"CLIP rejet pièce basique : jean bleu classique standard sans distinctivité (distinctivité {distinct_score*100:.0f}%)")"""

    new_clip_block = """        # Rejet visuel des pièces basiques (t-shirts, jeans, chemises et pantalons)
        p_plain = pattern_scores.get("plain", 0.0)
        if clip_category == "tshirt":
            if p_plain >= 0.58 and distinct_score < 0.42:
                hard_reject = True
                reasons.append(f"CLIP rejet pièce basique : t-shirt simple uni sans motif ({p_plain*100:.0f}%, distinctivité {distinct_score*100:.0f}%)")
        elif clip_category == "jean":
            is_plain_jean = (p_plain >= 0.55 and distinct_score < 0.38)
            is_runway = style_scores.get("runway_luxury", 0.0) >= 0.45 or style_scores.get("vintage_designer", 0.0) >= 0.50
            if is_plain_jean and not is_runway:
                hard_reject = True
                reasons.append(f"CLIP rejet pièce basique : jean bleu classique standard sans distinctivité (distinctivité {distinct_score*100:.0f}%)")
        elif clip_category == "chemise_blouse":
            is_plain_shirt = (p_plain >= 0.55 and distinct_score < 0.42)
            is_noble_fabric = material_top in ("silk_satin", "leather")
            is_runway_shirt = style_scores.get("runway_luxury", 0.0) >= 0.45 or style_scores.get("vintage_designer", 0.0) >= 0.50
            if is_plain_shirt and not is_noble_fabric and not is_runway_shirt:
                hard_reject = True
                reasons.append(f"CLIP rejet pièce basique : chemise/blouse unie classique sans motif ni matière noble ({p_plain*100:.0f}%, distinctivité {distinct_score*100:.0f}%)")
        elif clip_category == "pantalon":
            is_plain_pant = (p_plain >= 0.52 and distinct_score < 0.40)
            is_noble_fabric_pant = material_top in ("leather", "suede", "silk_satin")
            is_runway_pant = style_scores.get("runway_luxury", 0.0) >= 0.45 or style_scores.get("vintage_designer", 0.0) >= 0.50
            if is_plain_pant and not is_noble_fabric_pant and not is_runway_pant:
                hard_reject = True
                reasons.append(f"CLIP rejet pièce basique : pantalon uni classique standard ({p_plain*100:.0f}%, distinctivité {distinct_score*100:.0f}%)")"""

    if old_clip_block in content:
        content = content.replace(old_clip_block, new_clip_block)
        print("Updated CLIP scorer in src/scoring/clip_scorer.py with chemise and pantalon visual rejection")
    else:
        print("CLIP scorer block already updated or not matched exactly")

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


if __name__ == "__main__":
    update_i18n_keywords()
    update_filters()
    update_rules()
    update_clip_scorer()
    print("All updates applied successfully.")
