import os
import json

def update_config_bonus_words():
    path = "config.json"
    with open(path, "r", encoding="utf-8") as f:
        conf = json.load(f)

    bonus = conf.get("rule_bonus_words", {})
    patterns = bonus.get("patterns", {})
    materials = bonus.get("materials", {})

    new_patterns = {
        "tartan": 8.0,
        "nova check": 9.0,
        "check": 6.0,
        "carreaux": 6.0,
        "vichy": 5.0,
        "barocco": 8.0,
        "baroque": 8.0
    }
    for k, v in new_patterns.items():
        if k not in patterns:
            patterns[k] = v

    new_materials = {
        "dentelle": 7.0,
        "lace": 7.0,
        "pizzo": 7.0,
        "lin": 5.0,
        "linen": 5.0,
        "lino": 5.0
    }
    for k, v in new_materials.items():
        if k not in materials:
            materials[k] = v

    bonus["patterns"] = patterns
    bonus["materials"] = materials
    conf["rule_bonus_words"] = bonus

    with open(path, "w", encoding="utf-8") as f:
        json.dump(conf, f, indent=2, ensure_ascii=False)
    print("Updated config.json with new patterns and materials bonus words.")


def update_rules_shield():
    path = "src/scoring/rules.py"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    old_ceiling = """    has_bottom_detail = bool(cuts_hits or patterns_hits or materials_hits)
    if category in ("chemise_blouse", "pantalon", "jean", "short", "jupe") and not has_bottom_detail:
        if score > 38.0:
            score = 38.0
            reasons.append("Plafond Basique : chemise ou bas sans détail distinctif (score max 38)")"""

    new_ceiling = """    has_bottom_detail = bool(cuts_hits or patterns_hits or materials_hits or has_shield)
    if category in ("chemise_blouse", "pantalon", "jean", "short", "jupe") and not has_bottom_detail:
        if score > 38.0:
            score = 38.0
            reasons.append("Plafond Basique : chemise ou bas sans détail distinctif (score max 38)")"""

    if old_ceiling in content:
        content = content.replace(old_ceiling, new_ceiling)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print("Updated rule 8 in src/scoring/rules.py to include has_shield in has_bottom_detail")
    else:
        print("Rule 8 ceiling already updated or not matched exactly")


if __name__ == "__main__":
    update_config_bonus_words()
    update_rules_shield()
