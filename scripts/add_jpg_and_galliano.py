import sys
sys.path.insert(0, '.')
import json
import sqlite3
import time
import os

JPG_BENCHMARKS = {
    "top": (45.0, 95.0, 220.0, "Top en tulle/mesh imprimé soleil, cyber ou tatouage Jean Paul Gaultier"),
    "robe": (60.0, 120.0, 250.0, "Robe trompe l'oeil, résille, maille ou drapée Jean Paul Gaultier"),
    "veste": (55.0, 110.0, 220.0, "Veste blouson ou perfecto déstructuré Jean Paul Gaultier"),
    "blazer": (55.0, 105.0, 190.0, "Blazer tailoring rayures tennis ou coupe cintrée JPG"),
    "manteau": (75.0, 140.0, 260.0, "Manteau long ou caban marin drap de laine JPG"),
    "manteau_fourrure": (85.0, 160.0, 280.0, "Manteau fausse fourrure ou peau lainée JPG"),
    "pull_maille": (45.0, 85.0, 160.0, "Pull marinière iconique ou grosse maille Jean Paul Gaultier"),
    "sweat": (40.0, 75.0, 130.0, "Sweat marinière ou logo brodé Jean Paul Gaultier"),
    "jupe": (35.0, 65.0, 120.0, "Jupe plissée kilt ou jupe trompe l'oeil JPG"),
    "pantalon": (35.0, 65.0, 110.0, "Pantalon tailoring pont marin ou coupe droite JPG"),
    "jean": (30.0, 55.0, 95.0, "Jean Jean's Paul Gaultier coupe vintage"),
    "chemise_blouse": (35.0, 68.0, 120.0, "Chemise en soie imprimée ou marinière fluide JPG"),
    "tshirt": (28.0, 50.0, 95.0, "T-shirt marinière ou imprimé graphique Jean Paul Gaultier"),
    "sac": (50.0, 100.0, 200.0, "Sac cuir, boîte métal ou pochette Jean Paul Gaultier"),
    "chaussures": (35.0, 65.0, 120.0, "Chaussures cuir ou boots à lacets Jean Paul Gaultier"),
    "bottes": (50.0, 95.0, 180.0, "Bottes cuir esprit militaire ou cavalières JPG"),
    "escarpins": (35.0, 65.0, 115.0, "Escarpins ou mules à talon Jean Paul Gaultier"),
    "accessoire": (25.0, 50.0, 95.0, "Ceinture corset, bretelles ou foulard soie JPG")
}

GALLIANO_BENCHMARKS = {
    "robe": (65.0, 130.0, 280.0, "Robe en soie coupée en biais, slip dress dentelle ou Gazette John Galliano"),
    "top": (45.0, 85.0, 160.0, "Top Gazette newspaper, caraco en soie ou lingerie John Galliano"),
    "veste": (60.0, 120.0, 230.0, "Veste tailoring asymétrique ou blouson John Galliano"),
    "blazer": (55.0, 110.0, 200.0, "Veste blazer cintrée couture John Galliano"),
    "manteau": (80.0, 160.0, 300.0, "Manteau victorien long ou redingote John Galliano"),
    "manteau_fourrure": (90.0, 180.0, 320.0, "Manteau col fourrure ou shearling John Galliano"),
    "jupe": (35.0, 70.0, 130.0, "Jupe asymétrique, imprimé Gazette ou plissée Galliano"),
    "jean": (30.0, 58.0, 100.0, "Jean denim imprimé Gazette ou délavé Galliano"),
    "pantalon": (35.0, 68.0, 120.0, "Pantalon en soie fluide ou tailoring John Galliano"),
    "pull_maille": (38.0, 70.0, 130.0, "Pull en maille fine brodée ou cardigan Galliano"),
    "sweat": (35.0, 65.0, 110.0, "Sweat imprimé Gazette ou logo John Galliano"),
    "chemise_blouse": (38.0, 75.0, 130.0, "Chemisier en soie lavallière ou imprimé John Galliano"),
    "tshirt": (25.0, 48.0, 90.0, "T-shirt imprimé Gazette newspaper John Galliano"),
    "sac": (55.0, 110.0, 220.0, "Sac Gazette, sac selle ou cuir John Galliano"),
    "chaussures": (35.0, 70.0, 130.0, "Chaussures cuir, sneakers Gazette Galliano"),
    "bottes": (55.0, 110.0, 190.0, "Bottes cuir lacées ou bottines John Galliano"),
    "escarpins": (38.0, 72.0, 125.0, "Escarpins bride ou mules dentelle John Galliano"),
    "accessoire": (28.0, 50.0, 95.0, "Foulard soie Gazette, ceinture ou bijou John Galliano")
}


def update_taxonomy():
    path = "src/scoring/taxonomy.py"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Update JPG aliases (add 'jean paul gautier', 'gaultier')
    old_jpg_aliases = '"aliases": ["jean paul gaultier", "jpg"]'
    new_jpg_aliases = '"aliases": ["jean paul gaultier", "jean paul gautier", "gaultier", "jpg"]'
    if old_jpg_aliases in content:
        content = content.replace(old_jpg_aliases, new_jpg_aliases)
        print("Updated JPG aliases in src/scoring/taxonomy.py")

    # 2. Add John Galliano if not present
    if '"canonical": "John Galliano"' not in content:
        galliano_entry = '''    # John Galliano
    {
        "canonical": "John Galliano",
        "line": "diffusion",
        "tier": 1.5,
        "aliases": ["galliano"]
    },
    {
        "canonical": "John Galliano",
        "line": "principale",
        "tier": 1.5,
        "aliases": ["john galliano"]
    },
'''
        # Insert before Longchamp or after Coach
        if '# Longchamp' in content:
            content = content.replace('    # Longchamp', galliano_entry + '    # Longchamp')
            print("Added John Galliano into BRAND_REGISTRY in src/scoring/taxonomy.py")
        else:
            content = content.replace('BRAND_REGISTRY: List[Dict[str, Any]] = [', 'BRAND_REGISTRY: List[Dict[str, Any]] = [\n' + galliano_entry)
            print("Added John Galliano at start of BRAND_REGISTRY in src/scoring/taxonomy.py")

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def update_resale_knowledge_file():
    path = "src/scoring/resale_knowledge.py"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    new_entries = []
    if '"Jean Paul Gaultier": {' not in content:
        new_entries.append(('Jean Paul Gaultier', JPG_BENCHMARKS))
    if '"John Galliano": {' not in content:
        new_entries.append(('John Galliano', GALLIANO_BENCHMARKS))

    if new_entries:
        add_lines = []
        for b_name, b_dict in new_entries:
            add_lines.append(f'    "{b_name}": {{')
            for cat, vals in b_dict.items():
                min_f, target, max_h, desc = vals
                add_lines.append(f'        "{cat}": ({min_f}, {target}, {max_h}, "{desc}"),')
            add_lines.append('    },')

        addition = "\n".join(add_lines) + "\n\n"
        target_marker = '    # ==========================================\n    # TIER 1 : DIFFUSION & CONTEMPORARY PREMIUM'
        content = content.replace(target_marker, addition + target_marker)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print("Added JPG and Galliano to CURATED_RESALE_BENCHMARKS in src/scoring/resale_knowledge.py")
    else:
        print("CURATED_RESALE_BENCHMARKS already has JPG and Galliano")


def update_sqlite_db():
    db_path = "vinted_bot.db"
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    total_added = 0

    for b_name, b_dict in [("Jean Paul Gaultier", JPG_BENCHMARKS), ("John Galliano", GALLIANO_BENCHMARKS)]:
        for cat, (min_f, target, max_h, desc) in b_dict.items():
            c.execute("""
                INSERT OR REPLACE INTO resale_knowledge_base
                (brand, category, resale_min_flash, resale_target, resale_max_high, description, source, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'curated_benchmarks', ?)
            """, (b_name, cat, min_f, target, max_h, desc, now_iso))
            total_added += 1

    conn.commit()
    conn.close()
    print(f"Updated SQLite resale_knowledge_base: {total_added} entries inserted for JPG & John Galliano.")


def update_config_json():
    path = "config.json"
    with open(path, "r", encoding="utf-8") as f:
        conf = json.load(f)

    # 1. Update brand_tiers
    tiers = conf.setdefault("brand_tiers", {})
    t15 = tiers.setdefault("tier_1_5", {"multiplier": 1.8, "brands": []})
    t15_brands = t15.setdefault("brands", [])
    for b in ["jean paul gaultier", "jean paul gautier", "gaultier", "jpg", "john galliano", "galliano"]:
        if b not in t15_brands:
            t15_brands.append(b)

    # 2. Add iconic pattern bonuses
    bonus = conf.setdefault("rule_bonus_words", {})
    patterns = bonus.setdefault("patterns", {})
    new_signatures = {
        "gazette": 9.0,
        "newspaper": 9.0,
        "mariniere": 7.0,
        "marinière": 7.0,
        "resille": 8.0,
        "résille": 8.0,
        "mesh": 8.0,
        "trompe l'oeil": 9.0,
        "trompe l oeil": 9.0,
        "corset": 8.0
    }
    for k, v in new_signatures.items():
        if k not in patterns:
            patterns[k] = v

    # 3. Add searches
    searches = conf.setdefault("searches", [])

    # Check and add b_jpg
    jpg_found = False
    for s in searches:
        if s.get("id") == "b_jpg":
            jpg_found = True
            s["enabled"] = True
            s["brand"] = "Jean Paul Gaultier"
            s["brand_variants"] = ["jean paul gaultier", "jean paul gautier", "gaultier", "jpg"]
            s["brand_ids"] = [4129]
            s["max_price"] = 18.0
            s["order"] = "newest_first"
            s["exclude_accessories"] = True
            s["allow_bags"] = True

    if not jpg_found:
        searches.append({
            "id": "b_jpg",
            "name": "✨ Jean Paul Gaultier",
            "enabled": True,
            "brand": "Jean Paul Gaultier",
            "brand_variants": ["jean paul gaultier", "jean paul gautier", "gaultier", "jpg"],
            "brand_ids": [4129],
            "max_price": 18.0,
            "order": "newest_first",
            "exclude_accessories": True,
            "allow_bags": True
        })

    # Check and add b_galliano
    galliano_found = False
    for s in searches:
        if s.get("id") == "b_galliano":
            galliano_found = True
            s["enabled"] = True
            s["brand"] = "John Galliano"
            s["brand_variants"] = ["john galliano", "galliano"]
            s["brand_ids"] = [10613, 7011975]
            s["max_price"] = 16.0
            s["order"] = "newest_first"
            s["exclude_accessories"] = True
            s["allow_bags"] = True

    if not galliano_found:
        searches.append({
            "id": "b_galliano",
            "name": "✨ Galliano",
            "enabled": True,
            "brand": "John Galliano",
            "brand_variants": ["john galliano", "galliano"],
            "brand_ids": [10613, 7011975],
            "max_price": 16.0,
            "order": "newest_first",
            "exclude_accessories": True,
            "allow_bags": True
        })

    with open(path, "w", encoding="utf-8") as f:
        json.dump(conf, f, indent=2, ensure_ascii=False)
    print("Updated config.json: brand_tiers, signatures, and searches for JPG & Galliano.")


if __name__ == "__main__":
    update_taxonomy()
    update_resale_knowledge_file()
    update_sqlite_db()
    update_config_json()
    print("Jean Paul Gaultier and Galliano successfully added and configured.")
