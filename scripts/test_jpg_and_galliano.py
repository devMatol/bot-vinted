import sys
sys.path.insert(0, '.')
import json
import sqlite3
from src.scoring.taxonomy import normalize_brand
from src.scoring.rules import evaluate_rules
from src.filters import DealEvaluator

print("=== 1. VERIFY BRAND NORMALIZATION ===")
test_brands = [
    ("Jean Paul Gaultier", "Top mesh soleil archive", "Jean Paul Gaultier", 1.5),
    ("Jean Paul Gautier", "Pull mariniere vintage", "Jean Paul Gaultier", 1.5),
    ("JPG", "Veste deconstruite tailoring", "Jean Paul Gaultier", 1.5),
    ("John Galliano", "Robe en soie coupe en biais", "John Galliano", 1.5),
    ("Galliano", "Top imprime Gazette newspaper", "John Galliano", 1.5),
]

for b_title, title, expected_canon, expected_tier in test_brands:
    canon, line, tier = normalize_brand(b_title, title)
    assert canon == expected_canon, f"Expected {expected_canon}, got {canon}"
    assert tier == expected_tier, f"Expected {expected_tier}, got {tier}"
    print(f"[OK] {b_title:<20} -> Canonical: {canon:<20} | Line: {line:<10} | Tier: {tier}")

print("\n=== 2. VERIFY CONFIG.JSON SEARCHES ===")
conf = json.load(open("config.json", "r", encoding="utf-8"))
searches_by_id = {s["id"]: s for s in conf.get("searches", [])}

for bid, bname, exp_brand_ids, exp_max_price in [
    ("b_jpg", "Jean Paul Gaultier", [4129], 18.0),
    ("b_galliano", "John Galliano", [10613, 7011975], 16.0),
]:
    assert bid in searches_by_id, f"Search {bid} missing from config.json!"
    s = searches_by_id[bid]
    assert s.get("enabled") is True, f"{bid} not enabled!"
    assert s.get("brand_ids") == exp_brand_ids, f"{bid} brand_ids mismatch: {s.get('brand_ids')} vs {exp_brand_ids}"
    assert s.get("max_price") == exp_max_price, f"{bid} max_price mismatch: {s.get('max_price')} vs {exp_max_price}"
    assert s.get("allow_bags") is True, f"{bid} allow_bags is not True!"
    clean_name = s.get('name', '').encode('ascii', 'ignore').decode('ascii').strip()
    print(f"[OK] Search {bid:<12} | Name: {clean_name:<20} | Brand IDs: {s.get('brand_ids')} | Max: {s.get('max_price')} EUR | Bags: {s.get('allow_bags')}")

print("\n=== 3. VERIFY RESALE KNOWLEDGE BASE (SQLITE) ===")
conn = sqlite3.connect("vinted_bot.db")
c = conn.cursor()
for brand in ["Jean Paul Gaultier", "John Galliano"]:
    count = c.execute("SELECT count(*) FROM resale_knowledge_base WHERE brand=?", (brand,)).fetchone()[0]
    assert count >= 18, f"Brand {brand} has only {count} benchmarks in SQLite!"
    robe_row = c.execute("SELECT resale_min_flash, resale_target, resale_max_high, description FROM resale_knowledge_base WHERE brand=? AND category='robe'", (brand,)).fetchone()
    top_row = c.execute("SELECT resale_min_flash, resale_target, resale_max_high, description FROM resale_knowledge_base WHERE brand=? AND category='top'", (brand,)).fetchone()
    print(f"[OK] {brand:<20} has {count} categories in DB")
    print(f"     -> Robe: Flash {robe_row[0]} EUR / Cible {robe_row[1]} EUR / Max {robe_row[2]} EUR")
    print(f"     -> Top:  Flash {top_row[0]} EUR / Cible {top_row[1]} EUR / Max {top_row[2]} EUR")

conn.close()

print("\n=== 4. TEST RULES SCORING & PREFILTER ===")
items = [
    ({"id": 1, "title": "Top en tulle mesh soleil Jean Paul Gaultier archive", "price": {"amount": "15.0"}, "brand_title": "Jean Paul Gaultier"}, "b_jpg"),
    ({"id": 2, "title": "Pull mariniere Jean Paul Gaultier rayures", "price": {"amount": "14.0"}, "brand_title": "Jean Paul Gaultier"}, "b_jpg"),
    ({"id": 3, "title": "Robe en soie imprime Gazette John Galliano", "price": {"amount": "15.0"}, "brand_title": "John Galliano"}, "b_galliano"),
    ({"id": 4, "title": "Top dechire Gazette Galliano vintage", "price": {"amount": "12.0"}, "brand_title": "Galliano"}, "b_galliano"),
]

for item, search_id in items:
    s_conf = searches_by_id[search_id]
    ok_pre, reason_pre = DealEvaluator.prefilter(item, s_conf)
    assert ok_pre, f"Prefilter failed for {item['title']}: {reason_pre}"
    res = evaluate_rules(item, allow_bags=s_conf.get("allow_bags", True))
    assert not res.hard_reject, f"Rules hard rejected: {res.reasons}"
    assert res.score >= 50.0, f"Score too low for {item['title']}: {res.score}"
    print(f"[OK] {item['brand_title']:<20} deal valid! Prefilter OK | Rule score: {res.score:.1f} pts | Category: {res.category} | Tier: {res.tier}")

print("\n[SUCCESS] Jean Paul Gaultier and Galliano are fully operational across all components!")
