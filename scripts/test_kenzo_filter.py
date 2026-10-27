import sys
sys.path.insert(0, '.')
from src.filters import DealEvaluator
from src.scoring.rules import evaluate_rules
import json

conf = json.load(open('config.json', 'r', encoding='utf-8'))
s_kenzo = [s for s in conf.get('searches', []) if s.get('id') == 'b_kenzo'][0]

items_to_test = [
    ({'id': 1, 'title': 'KENZO Paris Embroidered Tiger Sweatshirt', 'price': {'amount': '15.0'}, 'brand_title': 'Kenzo'}, False),
    ({'id': 2, 'title': 'Pull Kenzo avec tete de lion brodee', 'price': {'amount': '15.0'}, 'brand_title': 'Kenzo'}, False),
    ({'id': 3, 'title': 'T-shirt Kenzo tiger head vert', 'price': {'amount': '10.0'}, 'brand_title': 'Kenzo'}, False),
    ({'id': 4, 'title': 'Sweatshirt Kenzo tete de tigre', 'price': {'amount': '15.0'}, 'brand_title': 'Kenzo'}, False),
    ({'id': 5, 'title': 'Veste de costume Kenzo vintage en laine', 'price': {'amount': '15.0'}, 'brand_title': 'Kenzo'}, True),
    ({'id': 6, 'title': 'Robe longue en soie Kenzo Jungle fleurs', 'price': {'amount': '18.0'}, 'brand_title': 'Kenzo'}, True)
]

print('--- Test Prefilter ---')
for it, should_pass in items_to_test:
    ok, reason = DealEvaluator.prefilter(it, s_kenzo)
    status = 'PASS' if ok else 'REJECT'
    expected = 'PASS' if should_pass else 'REJECT'
    match = (status == expected)
    title_short = it['title'][:40]
    print(f"{title_short:<42} -> {status} (Expected: {expected}) | {reason}")
    assert match, f"Mismatch on {it['title']}"

print('\n--- Test Rules ---')
for it, should_pass in items_to_test:
    res = evaluate_rules(it)
    status = 'REJECT' if res.hard_reject else 'PASS'
    expected = 'PASS' if should_pass else 'REJECT'
    match = (status == expected)
    title_short = it['title'][:40]
    print(f"{title_short:<42} -> {status} (Expected: {expected}) | Reasons: {res.reasons}")
    assert match, f"Mismatch on {it['title']}"

print('\nAll Kenzo tiger/lion filtering tests passed with 100% precision!')
