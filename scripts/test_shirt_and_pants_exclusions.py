import sys
sys.path.insert(0, '.')
import json
from src.filters import DealEvaluator
from src.scoring.rules import evaluate_rules

dummy_search = {"id": "b_luxury", "name": "Luxury Test", "min_price": 5.0, "max_price": 100.0, "enabled": True}

test_cases = [
    # 1. Chemises basiques (DOIVENT ETRE REJETEES)
    ({'id': 101, 'title': 'Camicia uomo Burberry celeste', 'price': {'amount': '15.0'}, 'brand_title': 'Burberry'}, False, 'camicia uomo classique'),
    ({'id': 102, 'title': 'Chemise blanche classique Max Mara', 'price': {'amount': '14.0'}, 'brand_title': 'Max Mara'}, False, 'chemise blanche classique'),
    ({'id': 103, 'title': 'Chemise de bureau en coton rayee', 'price': {'amount': '12.0'}, 'brand_title': 'Armani'}, False, 'chemise de bureau'),
    ({'id': 104, 'title': 'Camisa blanca clasica hombre', 'price': {'amount': '10.0'}, 'brand_title': 'Hugo Boss'}, False, 'camisa clasica'),
    ({'id': 105, 'title': 'Classic white dress shirt regular fit', 'price': {'amount': '15.0'}, 'brand_title': 'Ralph Lauren'}, False, 'classic dress shirt'),
    ({'id': 106, 'title': 'Camicia classica Giorgio Armani bianca', 'price': {'amount': '12.0'}, 'brand_title': 'Giorgio Armani'}, False, 'camicia classica bianca'),

    # 2. Pantalons basiques (DOIVENT ETRE REJETES)
    ({'id': 201, 'title': 'Pantalone classico sartoriale Armani', 'price': {'amount': '15.0'}, 'brand_title': 'Armani'}, False, 'pantalone classico sartoriale'),
    ({'id': 202, 'title': 'Pantalon droit classique noir de bureau', 'price': {'amount': '14.0'}, 'brand_title': 'Max Mara'}, False, 'pantalon droit classique'),
    ({'id': 203, 'title': 'Pantalon costume gris laine classique', 'price': {'amount': '15.0'}, 'brand_title': 'Dior'}, False, 'pantalon costume classique'),
    ({'id': 204, 'title': 'Basic office trousers black', 'price': {'amount': '12.0'}, 'brand_title': 'Prada'}, False, 'basic trousers'),
    ({'id': 205, 'title': 'Pantalones clasicos de vestir regular', 'price': {'amount': '10.0'}, 'brand_title': 'Gucci'}, False, 'pantalones clasicos'),
    ({'id': 206, 'title': 'Pantalon tailleur basique noir', 'price': {'amount': '14.0'}, 'brand_title': 'YSL'}, False, 'pantalon tailleur basique'),

    # 3. Pieces Distinctives & Luxe avec Bouclier (DOIVENT PASSER)
    ({'id': 301, 'title': 'Chemise en soie imprime baroque Versace', 'price': {'amount': '50.0'}, 'brand_title': 'Versace'}, True, 'chemise soie baroque'),
    ({'id': 302, 'title': 'Chemise Burberry tartan Nova Check vintage', 'price': {'amount': '45.0'}, 'brand_title': 'Burberry'}, True, 'chemise tartan nova check'),
    ({'id': 303, 'title': 'Chemise Dolce & Gabbana brodee dentelle noire', 'price': {'amount': '40.0'}, 'brand_title': 'Dolce & Gabbana'}, True, 'chemise brodee dentelle'),
    ({'id': 304, 'title': 'Pantalon en cuir noir Prada vintage', 'price': {'amount': '60.0'}, 'brand_title': 'Prada'}, True, 'pantalon cuir'),
    ({'id': 305, 'title': 'Pantalon fluide imprime leopard Roberto Cavalli', 'price': {'amount': '45.0'}, 'brand_title': 'Roberto Cavalli'}, True, 'pantalon leopard'),
    ({'id': 306, 'title': 'Pantalon cargo archive Helmut Lang', 'price': {'amount': '55.0'}, 'brand_title': 'Helmut Lang'}, True, 'pantalon cargo archive'),
    ({'id': 307, 'title': 'Chemise en lin Ralph Lauren bleu pastel', 'price': {'amount': '30.0'}, 'brand_title': 'Ralph Lauren'}, True, 'chemise lin noble')
]

print('=== 1. TEST PREFILTER (Fast reject) ===')
all_prefilters_ok = True
for it, should_pass, label in test_cases:
    ok_pre, reason_pre = DealEvaluator.prefilter(it, dummy_search)
    expected = should_pass
    status = 'PASS' if ok_pre else 'REJECT'
    match = (ok_pre == expected)
    if not match:
        all_prefilters_ok = False
    print(f"[{status:<6}] (Exp: {'PASS' if expected else 'REJECT'}) | {label:<32} | {it['title'][:50]}")
    if not ok_pre:
        print(f"       -> Motif: {reason_pre}")

print('\n=== 2. TEST RULES (ETAGE A) ===')
all_rules_ok = True
for it, should_pass, label in test_cases:
    res = evaluate_rules(it)
    ok = not res.hard_reject and res.score >= 45.0
    expected = should_pass
    status = 'PASS' if ok else 'REJECT'
    match = (ok == expected)
    if not match:
        all_rules_ok = False
    print(f"[{status:<6}] (Exp: {'PASS' if expected else 'REJECT'}) | {label:<32} | Score: {res.score:.1f} | Reasons: {res.reasons[:1] if res.reasons else 'None'}")

assert all_prefilters_ok, "Some prefilter tests failed!"
assert all_rules_ok, "Some rules tests failed!"
print('\n[SUCCESS] All tests passed with 100% precision! Zero false positives, full rejection of basic shirts and pants!')
