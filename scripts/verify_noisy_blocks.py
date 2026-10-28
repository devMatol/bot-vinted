import sys
sys.path.insert(0, '.')
from src.filters import DealEvaluator
from src.scoring.rules import evaluate_rules
import json

conf = json.load(open('config.json', 'r', encoding='utf-8'))
dummy_search = {'id': 'b_test', 'name': 'Test', 'min_price': 5.0, 'max_price': 20.0, 'enabled': True}

noisy_real_cases = [
    {'title': 'Joyero personal para bolso o de viaje', 'brand_title': 'Chloé', 'price': {'amount': '10.0'}},
    {'title': 'Housses chaussures', 'brand_title': 'Givenchy', 'price': {'amount': '10.0'}},
    {'title': 'Housses de chaussures', 'brand_title': 'Givenchy', 'price': {'amount': '10.0'}},
    {'title': 'Pochette porta biancheria', 'brand_title': 'Dolce & Gabbana', 'price': {'amount': '10.0'}},
    {'title': 'Pochette de lunette Gucci', 'brand_title': 'Gucci', 'price': {'amount': '10.0'}},
    {'title': 'Boucle de ceinture Versace Jeans vintage', 'brand_title': 'Versace', 'price': {'amount': '10.0'}},
    {'title': 'Camiseta manga larga Burberry', 'brand_title': 'Burberry', 'price': {'amount': '12.0'}},
    {'title': 'Camicia uomo Burberry', 'brand_title': 'Burberry', 'price': {'amount': '10.0'}},
    {'title': 'T-shirt Moschino basique', 'brand_title': 'Moschino', 'price': {'amount': '6.0'}},
    {'title': 'Pull gris Dolce&Gabbana', 'brand_title': 'Dolce & Gabbana', 'price': {'amount': '10.0'}}
]

print('Testing the 10 real noisy alert titles from today:\n')
for it in noisy_real_cases:
    ok_pre, reason_pre = DealEvaluator.prefilter(it, dummy_search)
    ok_full, reason_full = DealEvaluator.full_filter(it, dummy_search)
    rule_res = evaluate_rules(it)
    
    blocked = (not ok_pre) or (not ok_full) or rule_res.hard_reject
    status = 'BLOCKED' if blocked else 'PASSED'
    reason = reason_pre if not ok_pre else (reason_full if not ok_full else (rule_res.reasons[0] if rule_res.reasons else 'OK'))
    title = it['title']
    print(f"[{status}] {title:<42} -> {reason}")
