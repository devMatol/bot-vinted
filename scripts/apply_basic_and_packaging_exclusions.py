import os
import re

def update_i18n_keywords():
    path = "src/i18n_keywords.py"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    new_definitions = '''
TOILETRY_KEYWORDS = [
    # Français
    "trousse", "trousses", "trousse de toilette", "trousse toilette", "trousse maquillage",
    "trousse de beaute", "trousse beauté", "trousse de voyage", "vanity", "vanity case",
    "beauty case", "beauty-case", "necessaire de toilette", "nécessaire de toilette",
    "pochette maquillage", "pochette parfum", "pochette beaute", "pochette beauté",
    "pochette cosmetique", "pochette cosmétique",
    # Anglais
    "toiletry", "toiletry bag", "wash bag", "washbag", "cosmetic bag", "cosmetics bag",
    "makeup bag", "make-up bag", "beauty case", "beauty bag", "dopp kit",
    # Italien
    "necessaire", "nécessaire", "borsa da toilette", "pochette trucco", "trousse trucco",
    # Espagnol
    "neceser", "neceser de viaje", "neceser de aseo", "bolsa de aseo", "bolsa de maquillaje",
    # Allemand
    "kulturbeutel", "kosmetiktasche", "waschtasche", "toilettentasche"
]

BOUTIQUE_PACKAGING_KEYWORDS = [
    # Français
    "sac boutique", "sac de boutique", "sac papier", "sac en papier", "sac carton",
    "sac en carton", "sac kraft", "sac cabas papier", "sac shopping papier", "sachet boutique",
    "sac magasin", "sac de magasin", "shopping bag papier", "dustbag", "dust bag",
    "dust-bag", "housse de protection", "sac anti poussiere", "sac anti-poussière",
    # Anglais
    "paper bag", "carrier bag", "boutique bag", "store bag", "shopping bag paper",
    "gift bag", "retail bag",
    # Italien
    "busta carta", "busta boutique", "busta negozio", "shopper carta", "sacchetto carta",
    # Espagnol
    "bolsa de papel", "bolsa papel", "bolsa tienda", "bolsa de tienda", "bolsa kraft",
    # Allemand
    "papiertüte", "papiertasche", "einkaufstüte", "boutique tüte", "geschenktüte"
]

BASIC_ITEMS_KEYWORDS = [
    # T-shirts basiques
    "t-shirt basique", "t shirt basique", "tshirt basique", "tee basique",
    "t-shirt simple", "t shirt simple", "tshirt simple", "tee simple",
    "t-shirt uni", "t shirt uni", "tshirt uni", "tee uni",
    "basic tee", "basic t-shirt", "basic tshirt", "plain t-shirt", "plain tee",
    "maglietta basica", "maglia basica", "camiseta básica", "camiseta basica",
    "t-shirt basico", "t-shirt basic",
    # Jeans basiques / bleus classiques
    "jean basique", "jeans basique", "jean classique", "jeans classique",
    "jean bleu classique", "jeans bleu classique", "jean droit classique",
    "jean regular bleu", "basic jeans", "classic blue jeans", "classic jeans",
    "vaquero basico", "vaqueros basicos", "jeans basico", "jeans classico"
]
'''

    if "TOILETRY_KEYWORDS" not in content:
        # Insert before JUNK_KEYWORDS
        content = content.replace("JUNK_KEYWORDS = [", new_definitions + "\nJUNK_KEYWORDS = TOILETRY_KEYWORDS + BOUTIQUE_PACKAGING_KEYWORDS + [\n")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print("Updated src/i18n_keywords.py with new keyword lists")
    else:
        print("src/i18n_keywords.py already has TOILETRY_KEYWORDS")


def update_filters():
    path = "src/filters.py"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Add imports
    if "TOILETRY_KEYWORDS" not in content:
        content = content.replace("    JUNK_KEYWORDS,", "    JUNK_KEYWORDS,\n    TOILETRY_KEYWORDS,\n    BOUTIQUE_PACKAGING_KEYWORDS,\n    BASIC_ITEMS_KEYWORDS,")

    # Add checks to prefilter
    prefilter_checks = '''
        # 3d. Exclusion stricte des trousses de toilette, vanity, pochettes beauté / cosmétique
        for tk in TOILETRY_KEYWORDS:
            if contains_whole_word(norm_title, tk):
                return False, f"Article exclu (trousse de toilette / cosmétique : '{tk}')"

        # 3e. Exclusion des sacs de boutique, sacs papier, emballages, dustbags
        for bk in BOUTIQUE_PACKAGING_KEYWORDS:
            if contains_whole_word(norm_title, bk):
                return False, f"Article exclu (sac de boutique / packaging : '{bk}')"

        # 3f. Exclusion des pièces basiques (t-shirts simples / unis, jeans bleus classiques)
        for bi in BASIC_ITEMS_KEYWORDS:
            if contains_whole_word(norm_title, bi):
                return False, f"Pièce basique exclue ('{bi}')"
'''

    if "3d. Exclusion stricte des trousses" not in content:
        target_pre = '# 4. Gestion du Genre : Homme vs Femme vs Unisexe'
        content = content.replace(target_pre, prefilter_checks + "\n        " + target_pre)

    # Add checks to full_filter
    full_filter_checks = '''
        # 3d. Exclusion stricte trousse de toilette / cosmétique (sur texte complet)
        norm_full = normalize_text(full_text)
        for tk in TOILETRY_KEYWORDS:
            if contains_whole_word(norm_full, tk):
                return False, f"Article exclu (trousse de toilette / cosmétique : '{tk}')"

        # 3e. Exclusion sac de boutique / packaging (sur texte complet)
        for bk in BOUTIQUE_PACKAGING_KEYWORDS:
            if contains_whole_word(norm_full, bk):
                return False, f"Article exclu (sac de boutique / packaging : '{bk}')"

        # 3f. Exclusion pièces basiques (sur texte complet)
        for bi in BASIC_ITEMS_KEYWORDS:
            if contains_whole_word(norm_full, bi):
                return False, f"Pièce basique exclue ('{bi}')"
'''
    if "3d. Exclusion stricte trousse de toilette" not in content:
        target_full = '# 4. Contrôle de la note d\'évaluation du vendeur'
        content = content.replace(target_full, full_filter_checks + "\n        " + target_full)

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("Updated src/filters.py with prefilter and full_filter exclusions")


def update_rules():
    path = "src/scoring/rules.py"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Import keywords if not imported
    if "TOILETRY_KEYWORDS" not in content:
        content = content.replace(
            "from src.filters import (",
            "from src.i18n_keywords import (\n    TOILETRY_KEYWORDS,\n    BOUTIQUE_PACKAGING_KEYWORDS,\n    BASIC_ITEMS_KEYWORDS\n)\nfrom src.filters import ("
        )

    rules_check = '''
    # 3d-ter. Exclusion trousses de toilette, vanity, sacs de boutique et pièces basiques
    for tk in TOILETRY_KEYWORDS:
        if contains_whole_word(norm_full_text, tk, text_is_normalized=True):
            return RuleResult(
                category=category,
                brand_canonical=brand_canonical,
                brand_line=brand_line,
                tier=tier,
                score=0.0,
                hard_reject=True,
                reasons=[f"Trousse de toilette / cosmétique exclue : '{tk}'"],
                size_normalized=size_norm
            )

    for bk in BOUTIQUE_PACKAGING_KEYWORDS:
        if contains_whole_word(norm_full_text, bk, text_is_normalized=True):
            return RuleResult(
                category=category,
                brand_canonical=brand_canonical,
                brand_line=brand_line,
                tier=tier,
                score=0.0,
                hard_reject=True,
                reasons=[f"Sac de boutique / emballage exclu : '{bk}'"],
                size_normalized=size_norm
            )

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
            )
'''

    if "3d-ter. Exclusion trousses de toilette" not in content:
        target_rule = '# 3e-bis. Basiques des lignes diffusion'
        content = content.replace(target_rule, rules_check + "\n    " + target_rule)

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("Updated src/scoring/rules.py with hard rejects")


def update_clip_scorer():
    path = "src/scoring/clip_scorer.py"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Add packaging_format to default_sets
    pkg_set = '''            "packaging_format": {
                "real_fashion_item": "a luxury fashion garment or authentic leather handbag or shoes",
                "toiletry_pouch": "a small nylon or synthetic cosmetic toiletry bag washbag or makeup pouch",
                "shopping_paper_bag": "a paper shopping boutique gift bag or cardboard bag packaging"
            },
'''
    if '"packaging_format":' not in content:
        content = content.replace('"kenzo_tiger": {', pkg_set + '            "kenzo_tiger": {')

    # 2. Add visual rejection in evaluate_item
    vis_check = '''
        # Rejet visuel trousse de toilette / sac de boutique papier
        if image_features is not None:
            pkg_keys, pkg_probs = self._compute_zero_shot_probs(image_features, "packaging_format")
            p_toiletry = float(pkg_probs[:, pkg_keys.index("toiletry_pouch")].max()) if "toiletry_pouch" in pkg_keys else 0.0
            p_shopbag = float(pkg_probs[:, pkg_keys.index("shopping_paper_bag")].max()) if "shopping_paper_bag" in pkg_keys else 0.0
            if p_toiletry >= 0.55:
                hard_reject = True
                reasons.append(f"CLIP rejet visuel : trousse de toilette / trousse beauté détectée ({p_toiletry*100:.0f}%)")
            elif p_shopbag >= 0.55:
                hard_reject = True
                reasons.append(f"CLIP rejet visuel : sac de boutique en papier / packaging détecté ({p_shopbag*100:.0f}%)")

        # Rejet visuel des pièces basiques (t-shirts simples unis et jeans bleus classiques)
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
'''

    if "Rejet visuel trousse de toilette" not in content:
        target_clip = '# Rejet visuel hauts Kenzo tête de tigre / lion'
        content = content.replace(target_clip, vis_check + "\n        " + target_clip)

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("Updated src/scoring/clip_scorer.py with visual packaging & basic piece filters")


if __name__ == '__main__':
    update_i18n_keywords()
    update_filters()
    update_rules()
    update_clip_scorer()
