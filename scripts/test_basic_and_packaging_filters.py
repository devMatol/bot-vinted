import sys
sys.path.insert(0, '.')
from src.filters import DealEvaluator
from src.scoring.rules import evaluate_rules
import json

conf = json.load(open('config.json', 'r', encoding='utf-8'))
dummy_search = {"id": "b_chanel", "name": "Chanel", "min_price": 5.0, "max_price": 20.0, "enabled": True}

test_cases = [
    # Trousses de toilette / cosmétique
    ({'id': 101, 'title': 'Trousse de toilette Dior beauté blanche', 'price': {'amount': '15.0'}, 'brand_title': 'Dior'}, False, 'trousse de toilette'),
    ({'id': 102, 'title': 'Pochette parfum Givenchy maquillage', 'price': {'amount': '10.0'}, 'brand_title': 'Givenchy'}, False, 'pochette maquillage/parfum'),
    ({'id': 103, 'title': 'Beauty case Prada nylon noir', 'price': {'amount': '18.0'}, 'brand_title': 'Prada'}, False, 'beauty case'),
    ({'id': 104, 'title': 'Neceser de viaje Yves Saint Laurent', 'price': {'amount': '12.0'}, 'brand_title': 'Yves Saint Laurent'}, False, 'neceser'),
    # Sacs de boutique / packaging
    ({'id': 201, 'title': 'Sac boutique Chanel en papier noir', 'price': {'amount': '10.0'}, 'brand_title': 'Chanel'}, False, 'sac boutique'),
    ({'id': 202, 'title': 'Sac en papier kraft Gucci shopping bag', 'price': {'amount': '8.0'}, 'brand_title': 'Gucci'}, False, 'sac papier shopping'),
    ({'id': 203, 'title': 'Dustbag Celine housse de protection sac', 'price': {'amount': '12.0'}, 'brand_title': 'Celine'}, False, 'dustbag'),
    # Pièces basiques
    ({'id': 301, 'title': 'T-shirt basique col rond noir', 'price': {'amount': '10.0'}, 'brand_title': 'Diesel'}, False, 't-shirt basique'),
    ({'id': 302, 'title': 'T-shirt simple uni blanc coton', 'price': {'amount': '10.0'}, 'brand_title': 'Armani'}, False, 't-shirt simple uni'),
    ({'id': 303, 'title': 'Jean bleu classique coupe droite', 'price': {'amount': '15.0'}, 'brand_title': 'Diesel'}, False, 'jean bleu classique'),
    ({'id': 304, 'title': 'Basic tee regular fit noir', 'price': {'amount': '10.0'}, 'brand_title': 'Kenzo'}, False, 'basic tee'),
    # Pièces légitimes qui DOIVENT PASSER
    ({'id': 401, 'title': 'Sac en cuir Chanel Timeless noir matelassé', 'price': {'amount': '20.0'}, 'brand_title': 'Chanel'}, True, 'sac cuir authentique'),
    ({'id': 402, 'title': 'Veste blazer Gucci vintage velours monogramme', 'price': {'amount': '20.0'}, 'brand_title': 'Gucci'}, True, 'veste blazer vintage'),
    ({'id': 403, 'title': 'Robe fluide en soie Dior imprimé fleurs', 'price': {'amount': '20.0'}, 'brand_title': 'Dior'}, True, 'robe soie')
]

print('=== 1. TEST PREFILTER & FULL_FILTER ===')
all_filters_ok = True
for it, should_pass, label in test_cases:
    ok_pre, reason_pre = DealEvaluator.prefilter(it, dummy_search)
    ok_full, reason_full = DealEvaluator.full_filter(it, dummy_search)
    ok = ok_pre and ok_full
    expected = should_pass
    status = 'PASS' if ok else 'REJECT'
    match = (ok == expected)
    if not match:
        all_filters_ok = False
    print(f"[{status:<6}] (Exp: {'PASS' if expected else 'REJECT'}) | {label:<28} | {it['title'][:45]}")
    if not ok:
        print(f"       -> Motif: {reason_pre if not ok_pre else reason_full}")

print('\n=== 2. TEST RULES (ETAGE A) ===')
all_rules_ok = True
for it, should_pass, label in test_cases:
    res = evaluate_rules(it)
    ok = not res.hard_reject
    expected = should_pass
    status = 'PASS' if ok else 'REJECT'
    match = (ok == expected)
    if not match:
        all_rules_ok = False
    print(f"[{status:<6}] (Exp: {'PASS' if expected else 'REJECT'}) | {label:<28} | Reasons: {res.reasons[:1] if res.reasons else 'None'}")

assert all_filters_ok, "Some filter tests failed!"
assert all_rules_ok, "Some rules tests failed!"
print('\n All tests passed with 100% precision!')
