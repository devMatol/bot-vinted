import json
import sqlite3

def update_resale_knowledge():
    with open('src/scoring/resale_knowledge.py', 'r', encoding='utf-8') as f:
        text = f.read()

    lines = text.splitlines(keepends=True)
    new_lines = []
    in_kenzo = False
    for line in lines:
        if '"Kenzo": {' in line:
            in_kenzo = True
        elif in_kenzo and line.strip().startswith('},'):
            in_kenzo = False

        if in_kenzo:
            if '"pull_maille":' in line:
                line = '        "pull_maille": (22.0, 38.0, 65.0, "Pull laine Kenzo vintage ou maille archive (hors tigre)"),\n'
            elif '"sweat":' in line:
                line = '        "sweat": (20.0, 35.0, 58.0, "Sweat logo classique ou vintage Kenzo (hors tigre)"),\n'
            elif '"chemise_blouse":' in line:
                line = '        "chemise_blouse": (20.0, 35.0, 58.0, "Chemise fleurs ou imprimé Kenzo Jungle (hors tigre)"),\n'
            elif '"top":' in line:
                line = '        "top": (14.0, 22.0, 36.0, "Top léger Kenzo (hors tigre)"),\n'
            elif '"tshirt":' in line:
                line = '        "tshirt": (12.0, 20.0, 32.0, "T-shirt logo Kenzo classique (hors tigre)"),\n'

        new_lines.append(line)

    with open('src/scoring/resale_knowledge.py', 'w', encoding='utf-8') as f:
        f.writelines(new_lines)

    print("Updated Kenzo entries in src/scoring/resale_knowledge.py")


def update_sqlite_db():
    conn = sqlite3.connect('vinted_bot.db')
    cur = conn.cursor()
    new_kenzo_vals = [
        ("Kenzo", "pull_maille", 22.0, 38.0, 65.0, "Pull laine Kenzo vintage ou maille archive (hors tigre)"),
        ("Kenzo", "sweat", 20.0, 35.0, 58.0, "Sweat logo classique ou vintage Kenzo (hors tigre)"),
        ("Kenzo", "chemise_blouse", 20.0, 35.0, 58.0, "Chemise fleurs ou imprimé Kenzo Jungle (hors tigre)"),
        ("Kenzo", "top", 14.0, 22.0, 36.0, "Top léger Kenzo (hors tigre)"),
        ("Kenzo", "tshirt", 12.0, 20.0, 32.0, "T-shirt logo Kenzo classique (hors tigre)")
    ]
    for b, c, f_val, tgt, max_v, desc in new_kenzo_vals:
        cur.execute("""
            INSERT OR REPLACE INTO resale_knowledge_base
            (brand, category, resale_min_flash, resale_target, resale_max_high, description, source)
            VALUES (?, ?, ?, ?, ?, ?, 'curated_benchmark')
        """, (b, c, f_val, tgt, max_v, desc))
    conn.commit()
    conn.close()
    print("Updated Kenzo rows in SQLite resale_knowledge_base")


def update_config_json():
    with open('config.json', 'r', encoding='utf-8') as f:
        conf = json.load(f)

    feline_excludes = ["tigre", "tiger", "tigers", "tigres", "lion", "lions", "leone", "leoni", "tigerhead", "tiger head", "tete de tigre", "tete de lion"]

    for s in conf.get('searches', []):
        if s.get('id') == 'b_kenzo':
            current_excludes = s.get('exclude_keywords', [])
            for w in feline_excludes:
                if w not in current_excludes:
                    current_excludes.append(w)
            s['exclude_keywords'] = current_excludes
            print("Added feline exclude keywords to b_kenzo in config.json:", s['exclude_keywords'])

    with open('config.json', 'w', encoding='utf-8') as f:
        json.dump(conf, f, indent=2, ensure_ascii=False)


if __name__ == '__main__':
    update_resale_knowledge()
    update_sqlite_db()
    update_config_json()
