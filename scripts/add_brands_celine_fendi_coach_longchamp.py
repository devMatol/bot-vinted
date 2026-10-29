import json
import sqlite3
import re
import os
import time

def update_taxonomy():
    path = "src/scoring/taxonomy.py"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Check if Celine is already in BRAND_REGISTRY
    if '"canonical": "Celine"' not in content:
        # Add Celine, Coach, Longchamp to BRAND_REGISTRY
        # We can find Fendi and insert near it
        new_brand_entries = '''    # Celine
    {
        "canonical": "Celine",
        "line": "principale",
        "tier": 3.0,
        "aliases": ["celine", "céline", "celine paris", "céline paris"]
    },
    # Coach
    {
        "canonical": "Coach",
        "line": "principale",
        "tier": 1.5,
        "aliases": ["coach", "coach new york", "coach 1941"]
    },
    # Longchamp
    {
        "canonical": "Longchamp",
        "line": "principale",
        "tier": 1.5,
        "aliases": ["longchamp", "longchamp paris", "longchamp 1948"]
    },
'''
        fendi_target = '''    # Fendi
    {
        "canonical": "Fendi",
        "line": "principale",
        "tier": 3.0,
        "aliases": ["fendi"]
    },'''

        fendi_replacement = '''    # Fendi
    {
        "canonical": "Fendi",
        "line": "principale",
        "tier": 3.0,
        "aliases": ["fendi", "fendi roma"]
    },
''' + new_brand_entries

        if fendi_target in content:
            content = content.replace(fendi_target, fendi_replacement)
            print("Added Celine, Coach, Longchamp and updated Fendi in src/scoring/taxonomy.py")
        else:
            # Fallback insertion before the end of BRAND_REGISTRY
            content = content.replace('BRAND_REGISTRY: List[Dict[str, Any]] = [', 'BRAND_REGISTRY: List[Dict[str, Any]] = [\n' + new_brand_entries)
            print("Added Celine, Coach, Longchamp at beginning of BRAND_REGISTRY in src/scoring/taxonomy.py")

        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    else:
        print("src/scoring/taxonomy.py already contains Celine")


COACH_BENCHMARKS = {
    "sac": (45.0, 85.0, 180.0, "Sac cuir Tabby, Willis, Rogue, Swagger, Court ou toile monogramme CC Coach"),
    "accessoire": (25.0, 45.0, 85.0, "Portefeuille cuir, porte-monnaie ou ceinture boucle C Coach"),
    "veste": (60.0, 120.0, 240.0, "Blouson en cuir ou perfecto Coach New York"),
    "blazer": (45.0, 85.0, 170.0, "Veste blazer tailoring Coach"),
    "manteau": (70.0, 140.0, 280.0, "Trench-coat ou manteau long en laine Coach"),
    "manteau_fourrure": (90.0, 180.0, 350.0, "Manteau shearling ou col fourrure Coach"),
    "chaussures": (35.0, 65.0, 120.0, "Baskets signature C ou mocassins cuir Coach"),
    "bottes": (45.0, 85.0, 160.0, "Bottines cuir ou bottes cavalières Coach"),
    "escarpins": (30.0, 55.0, 100.0, "Escarpins cuir ou sandales à talon Coach"),
    "robe": (35.0, 65.0, 130.0, "Robe en soie imprimée ou robe cocktail Coach"),
    "jupe": (28.0, 50.0, 95.0, "Jupe cuir ou plissée Coach"),
    "jean": (25.0, 45.0, 80.0, "Jean brodé ou denim signature Coach"),
    "pantalon": (28.0, 50.0, 95.0, "Pantalon en cuir ou tailoring Coach"),
    "pull_maille": (35.0, 65.0, 120.0, "Pull en laine mérinos ou cachemire Coach"),
    "sweat": (35.0, 70.0, 130.0, "Sweat hoodie Rexy dinosaure ou logo Coach"),
    "chemise_blouse": (28.0, 50.0, 95.0, "Chemise en soie ou blouse fluide Coach"),
    "top": (20.0, 40.0, 75.0, "Top en soie ou caraco Coach"),
    "tshirt": (22.0, 42.0, 80.0, "T-shirt graphique Rexy ou signature Coach")
}

LONGCHAMP_BENCHMARKS = {
    "sac": (35.0, 70.0, 160.0, "Sac Roseau cuir, Le Pliage cuir, Amazone ou grand cabas Longchamp"),
    "accessoire": (20.0, 38.0, 70.0, "Compagnon cuir Roseau, pochette ou foulard soie Longchamp"),
    "veste": (50.0, 100.0, 200.0, "Veste en cuir d'agneau ou blouson Longchamp"),
    "blazer": (40.0, 75.0, 150.0, "Veste blazer habillée Longchamp"),
    "manteau": (65.0, 130.0, 260.0, "Manteau drap de laine ou trench Longchamp"),
    "manteau_fourrure": (80.0, 160.0, 320.0, "Manteau peau lainée ou shearling Longchamp"),
    "chaussures": (30.0, 55.0, 100.0, "Mocassins cuir ou espadrilles Longchamp"),
    "bottes": (40.0, 80.0, 150.0, "Bottes cavalières en cuir Longchamp"),
    "escarpins": (28.0, 50.0, 90.0, "Escarpins cuir ou sandales Longchamp"),
    "robe": (30.0, 60.0, 120.0, "Robe en soie ou cocktail Longchamp"),
    "jupe": (25.0, 45.0, 85.0, "Jupe cuir ou trapèze Longchamp"),
    "jean": (22.0, 40.0, 75.0, "Pantalon denim Longchamp"),
    "pantalon": (25.0, 48.0, 90.0, "Pantalon en cuir ou habillé Longchamp"),
    "pull_maille": (30.0, 58.0, 110.0, "Pull cachemire ou maille Longchamp"),
    "sweat": (28.0, 52.0, 100.0, "Sweat logo cavalier Longchamp"),
    "chemise_blouse": (25.0, 45.0, 85.0, "Chemise en soie ou blouse Longchamp"),
    "top": (18.0, 35.0, 65.0, "Top en soie ou sans manches Longchamp"),
    "tshirt": (18.0, 35.0, 65.0, "T-shirt cavalier Longchamp")
}


def update_resale_knowledge_file():
    path = "src/scoring/resale_knowledge.py"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    if '"Coach": {' not in content:
        # Build python block for Coach and Longchamp
        add_lines = []
        for brand_name, benchmarks in [("Coach", COACH_BENCHMARKS), ("Longchamp", LONGCHAMP_BENCHMARKS)]:
            add_lines.append(f'    "{brand_name}": {{')
            for cat, vals in benchmarks.items():
                min_f, target, max_h, desc = vals
                add_lines.append(f'        "{cat}": ({min_f}, {target}, {max_h}, "{desc}"),')
            add_lines.append('    },')

        addition = "\n".join(add_lines) + "\n"

        target_str = 'CURATED_RESALE_BENCHMARKS: Dict[str, Dict[str, Tuple[float, float, float, str]]] = {\n'
        content = content.replace(target_str, target_str + addition)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print("Updated CURATED_RESALE_BENCHMARKS in src/scoring/resale_knowledge.py with Coach and Longchamp")
    else:
        print("src/scoring/resale_knowledge.py already contains Coach")


def update_sqlite_knowledge_base():
    db_path = "vinted_bot.db"
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    total_added = 0

    for brand_name, benchmarks in [("Coach", COACH_BENCHMARKS), ("Longchamp", LONGCHAMP_BENCHMARKS)]:
        for cat, (min_f, target, max_h, desc) in benchmarks.items():
            c.execute("""
                INSERT OR REPLACE INTO resale_knowledge_base
                (brand, category, resale_min_flash, resale_target, resale_max_high, description, source, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'curated_benchmarks', ?)
            """, (brand_name, cat, min_f, target, max_h, desc, now_iso))
            total_added += 1

    conn.commit()
    conn.close()
    print(f"Updated SQLite resale_knowledge_base: {total_added} entries inserted/updated for Coach & Longchamp.")


def update_config_json():
    path = "config.json"
    with open(path, "r", encoding="utf-8") as f:
        conf = json.load(f)

    # 1. Update brand_tiers
    tiers = conf.setdefault("brand_tiers", {})
    t3 = tiers.setdefault("tier_3", {"multiplier": 3.5, "brands": []})
    t3_brands = t3.setdefault("brands", [])
    for b in ["celine", "céline"]:
        if b not in t3_brands:
            t3_brands.append(b)

    t15 = tiers.setdefault("tier_1_5", {"multiplier": 1.8, "brands": []})
    t15_brands = t15.setdefault("brands", [])
    for b in ["coach", "longchamp"]:
        if b not in t15_brands:
            t15_brands.append(b)

    # 2. Update rule_bonus_words with iconic signatures
    bonus = conf.setdefault("rule_bonus_words", {})
    patterns = bonus.setdefault("patterns", {})
    new_signatures = {
        "triomphe": 9.0,
        "macadam": 8.0,
        "zucca": 9.0,
        "zucchino": 8.0,
        "baguette": 8.0,
        "peekaboo": 8.0,
        "roseau": 7.0,
        "rexy": 7.0,
        "le pliage": 6.0
    }
    for k, v in new_signatures.items():
        if k not in patterns:
            patterns[k] = v

    # 3. Update searches
    searches = conf.setdefault("searches", [])

    # Check and update b_celine
    celine_found = False
    for s in searches:
        if s.get("id") == "b_celine":
            celine_found = True
            s["enabled"] = True
            s["brand"] = "Celine"
            s["brand_variants"] = ["celine", "céline"]
            s["brand_ids"] = [1443]
            s["max_price"] = 25.0
            s["order"] = "newest_first"
            s["exclude_accessories"] = True
            s["allow_bags"] = True

    if not celine_found:
        searches.append({
            "id": "b_celine",
            "name": "✨ CELINE",
            "enabled": True,
            "brand": "Celine",
            "brand_variants": ["celine", "céline"],
            "brand_ids": [1443],
            "max_price": 25.0,
            "order": "newest_first",
            "exclude_accessories": True,
            "allow_bags": True
        })

    # Check and update b_fendi
    fendi_found = False
    for s in searches:
        if s.get("id") == "b_fendi":
            fendi_found = True
            s["enabled"] = True
            s["brand"] = "Fendi"
            s["brand_variants"] = ["fendi"]
            s["brand_ids"] = [1189]
            s["max_price"] = 25.0
            s["order"] = "newest_first"
            s["exclude_accessories"] = True
            s["allow_bags"] = True

    if not fendi_found:
        searches.append({
            "id": "b_fendi",
            "name": "✨ Fendi",
            "enabled": True,
            "brand": "Fendi",
            "brand_variants": ["fendi"],
            "brand_ids": [1189],
            "max_price": 25.0,
            "order": "newest_first",
            "exclude_accessories": True,
            "allow_bags": True
        })

    # Check and add b_coach
    coach_found = False
    for s in searches:
        if s.get("id") == "b_coach":
            coach_found = True
            s["enabled"] = True
            s["brand"] = "Coach"
            s["brand_variants"] = ["coach"]
            s["brand_ids"] = [6721]
            s["max_price"] = 16.0
            s["order"] = "newest_first"
            s["exclude_accessories"] = True
            s["allow_bags"] = True

    if not coach_found:
        searches.append({
            "id": "b_coach",
            "name": "✨ Coach",
            "enabled": True,
            "brand": "Coach",
            "brand_variants": ["coach"],
            "brand_ids": [6721],
            "max_price": 16.0,
            "order": "newest_first",
            "exclude_accessories": True,
            "allow_bags": True
        })

    # Check and add b_longchamp
    longchamp_found = False
    for s in searches:
        if s.get("id") == "b_longchamp":
            longchamp_found = True
            s["enabled"] = True
            s["brand"] = "Longchamp"
            s["brand_variants"] = ["longchamp"]
            s["brand_ids"] = [370]
            s["max_price"] = 14.0
            s["order"] = "newest_first"
            s["exclude_accessories"] = True
            s["allow_bags"] = True

    if not longchamp_found:
        searches.append({
            "id": "b_longchamp",
            "name": "✨ Longchamp",
            "enabled": True,
            "brand": "Longchamp",
            "brand_variants": ["longchamp"],
            "brand_ids": [370],
            "max_price": 14.0,
            "order": "newest_first",
            "exclude_accessories": True,
            "allow_bags": True
        })

    with open(path, "w", encoding="utf-8") as f:
        json.dump(conf, f, indent=2, ensure_ascii=False)
    print("Updated config.json: brand_tiers, signatures, and searches for Celine, Fendi, Coach, Longchamp.")


if __name__ == "__main__":
    update_taxonomy()
    update_resale_knowledge_file()
    update_sqlite_knowledge_base()
    update_config_json()
    print("All 4 brands successfully added and configured.")
