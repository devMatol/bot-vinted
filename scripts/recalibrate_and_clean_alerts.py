import json
import sqlite3
import re

# 1. Update src/i18n_keywords.py
def update_keywords():
    path = "src/i18n_keywords.py"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    new_packaging_extras = [
        # Housses de chaussures / vêtements
        "housse", "housses", "housse chaussure", "housses chaussures", "housse de chaussure",
        "housses de chaussures", "housse de vêtement", "housse vetement", "housse sac",
        "copriscarpe", "funda zapatos", "dust cover", "shoe cover",
        # Boîtes à bijoux & vanity voyage
        "joyero", "joyeros", "portagioie", "boite a bijoux", "boîte à bijoux", "boite bijoux",
        "boîte bijoux", "jewelry box", "jewellery box", "travel jewelry",
        # Linge & lunettes
        "porta biancheria", "pochette biancheria", "sac a linge",
        "etui lunette", "étui à lunettes", "etui a lunette", "étui lunettes",
        "pochette lunette", "pochette de lunette", "portaocchiali", "funda gafas",
        # Boucles seules
        "boucle de ceinture", "boucle seule", "fibbia", "hebilla", "belt buckle"
    ]

    new_basic_extras = [
        # Hauts manches longues basiques
        "camiseta manga larga", "camiseta de manga larga", "t-shirt manches longues",
        "t shirt manches longues", "tshirt manches longues", "maglia maniche lunghe",
        "maglia a maniche lunghe", "longsleeve", "long sleeve",
        # Chemises classiques de bureau sans motif
        "camicia uomo", "camicia classica", "chemise classique", "chemise de bureau",
        "camisa hombre clasica", "chemise homme classique", "camicia celeste", "camicia bianca",
        # Pantalons classiques de bureau
        "pantalon classique", "pantalone classico", "pantaloni classici", "pantaloni sartoriali",
        # Pulls et mailles simples
        "pull gris", "pull noir uni", "sueter basico", "maglia basica", "maglione basico"
    ]

    # Insert into lists in i18n_keywords.py
    for w in new_packaging_extras:
        if f'"{w}"' not in content:
            content = content.replace('BOUTIQUE_PACKAGING_KEYWORDS = [', f'BOUTIQUE_PACKAGING_KEYWORDS = [\n    "{w}",')

    for w in new_basic_extras:
        if f'"{w}"' not in content:
            content = content.replace('BASIC_ITEMS_KEYWORDS = [', f'BASIC_ITEMS_KEYWORDS = [\n    "{w}",')

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("Updated src/i18n_keywords.py with extended packaging and basic piece keywords")


# 2. Update config.json
def update_config():
    path = "config.json"
    with open(path, "r", encoding="utf-8") as f:
        conf = json.load(f)

    # 1. Raise margin & score thresholds
    conf["min_margin_eur"] = 25.0       # Was 12.0€ -> Require at least 25€ NET profit
    conf["final_min_score"] = 76.0      # Was 70.0  -> Require higher conviction score
    conf["rules_min_score"] = 45.0      # Was 35.0  -> Stricter pre-filtering
    conf["min_multiple"] = 2.0          # Was 1.5   -> Minimum 2.0x money multiplier

    # 2. Lower max_price on noisy brands where 15-20€ attracts low-end basic shirts
    price_adjustments = {
        "b_burberry": 14.0,     # Stop buying 19€ plain office shirts
        "b_dg": 15.0,           # Stop buying 20€ standard basic items
        "b_maxmara": 14.0,      # Stop buying plain wool blend trousers at 20€
        "b_moschino": 12.0,     # Stop buying basic Moschino Jeans at 18€
        "b_kenzo": 14.0,        # Stop buying basic tops at 20€
        "b_armani": 12.0,       # Stop buying basic Armani Jeans tees/shirts
        "b_guess": 8.0,         # Cap Guess to true bargain range
        "b_diesel": 8.0         # Cap Diesel to true bargain range
    }

    for s in conf.get("searches", []):
        sid = s.get("id")
        if sid in price_adjustments:
            old_p = s.get("max_price")
            s["max_price"] = price_adjustments[sid]
            print(f"Adjusted {sid}: max_price {old_p}€ -> {s['max_price']}€")

    with open(path, "w", encoding="utf-8") as f:
        json.dump(conf, f, indent=2, ensure_ascii=False)
    print("Updated config.json: min_margin_eur=25.0€, final_min_score=76.0, min_multiple=2.0")


# 3. Recalibrate resale_knowledge.py
def update_resale_benchmarks():
    conn = sqlite3.connect("vinted_bot.db")
    cur = conn.cursor()

    # Recalibrate shirts / tops across noisy brands in SQLite
    recalibrations = [
        # Burberry
        ("Burberry", "chemise_blouse", 20.0, 32.0, 55.0, "Chemise Burberry (coton standard / hors Nova Check)"),
        ("Burberry", "tshirt", 15.0, 24.0, 40.0, "T-shirt Burberry coton standard"),
        ("Burberry", "pantalon", 18.0, 30.0, 50.0, "Pantalon chino ou tailleur Burberry classique"),
        # Dolce & Gabbana
        ("Dolce & Gabbana", "chemise_blouse", 18.0, 30.0, 52.0, "Chemise D&G classique coton"),
        ("Dolce & Gabbana", "tshirt", 14.0, 24.0, 38.0, "T-shirt D&G basique"),
        ("Dolce & Gabbana", "pull_maille", 22.0, 38.0, 65.0, "Pull laine standard D&G"),
        ("Dolce & Gabbana", "pantalon", 18.0, 32.0, 55.0, "Pantalon habillé D&G classique"),
        # Max Mara
        ("Max Mara", "chemise_blouse", 16.0, 28.0, 48.0, "Chemise coton ou popeline Max Mara classique"),
        ("Max Mara", "tshirt", 12.0, 20.0, 32.0, "Top / T-shirt Max Mara basique"),
        ("Max Mara", "pantalon", 20.0, 34.0, 55.0, "Pantalon habillé laine Max Mara classique"),
        ("Max Mara", "pull_maille", 22.0, 38.0, 62.0, "Pull ou gilet maille Max Mara"),
        # Moschino
        ("Moschino", "chemise_blouse", 15.0, 25.0, 42.0, "Chemise Moschino Jeans standard"),
        ("Moschino", "tshirt", 12.0, 20.0, 32.0, "T-shirt Moschino Jeans coton simple"),
        ("Moschino", "pull_maille", 18.0, 30.0, 50.0, "Pull ou sweat Moschino standard"),
        # Armani
        ("Armani", "chemise_blouse", 14.0, 24.0, 38.0, "Chemise homme Armani classique coton"),
        ("Armani", "tshirt", 10.0, 18.0, 28.0, "T-shirt Armani Jeans / EA7 basique"),
        ("Armani", "jean", 12.0, 20.0, 32.0, "Jean Armani Jeans classique"),
        # Diesel
        ("Diesel", "tshirt", 8.0, 14.0, 22.0, "T-shirt Diesel classique"),
        ("Diesel", "chemise_blouse", 12.0, 20.0, 32.0, "Chemise denim ou coton Diesel standard")
    ]

    for b, c, f_val, tgt, max_v, desc in recalibrations:
        cur.execute("""
            INSERT OR REPLACE INTO resale_knowledge_base
            (brand, category, resale_min_flash, resale_target, resale_max_high, description, source)
            VALUES (?, ?, ?, ?, ?, ?, 'curated_cleaned_benchmark')
        """, (b, c, f_val, tgt, max_v, desc))

    conn.commit()
    conn.close()
    print("Recalibrated benchmarks in SQLite resale_knowledge_base successfully")


if __name__ == '__main__':
    update_keywords()
    update_config()
    update_resale_benchmarks()
