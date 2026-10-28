import sqlite3
import json
from collections import Counter
from datetime import datetime

conn = sqlite3.connect('vinted_bot.db')
cur = conn.cursor()

# Get recent notifications from deal_feedback
rows = cur.execute('''
    SELECT id, created_at, brand, price, title, search_name, score
    FROM deal_feedback 
    ORDER BY id DESC LIMIT 150
''').fetchall()

print(f"Total rows in deal_feedback: {len(rows)}")

# Count by brand
brand_counts = Counter([r[2] for r in rows if r[2]])
print("\n--- Alert counts by brand (Last 150 alerts) ---")
for b, count in brand_counts.most_common(20):
    print(f"  {b:<22} : {count} alertes")

# Price distribution
prices = [float(r[3]) for r in rows if r[3] is not None]
if prices:
    print(f"\n--- Price distribution ---")
    print(f"  Min: {min(prices)}€, Max: {max(prices)}€, Avg: {sum(prices)/len(prices):.1f}€")
    print(f"  Under 10€: {sum(1 for p in prices if p < 10)}")
    print(f"  10€ - 15€: {sum(1 for p in prices if 10 <= p <= 15)}")
    print(f"  15€ - 20€: {sum(1 for p in prices if p > 15)}")

# Examine sample titles of the top noisy brands
print("\n--- Sample alert titles of top brands ---")
for b, _ in brand_counts.most_common(8):
    sample_titles = [r[4] for r in rows if r[2] == b][:6]
    print(f"\n[{b.upper()}] :")
    for st in sample_titles:
        print(f"   • {st}")

# Check decisions table for margins & multiples on VALIDATED items
val_decisions = cur.execute('''
    SELECT price, total_cost, revente_retenue, margin, multiple, details_json, created_at
    FROM decisions
    WHERE decision = 'VALIDATED'
    ORDER BY id DESC LIMIT 100
''').fetchall()

print(f"\n--- Validated decisions sample (last 100) ---")
margins = [r[3] for r in val_decisions if r[3] is not None]
multiples = [r[4] for r in val_decisions if r[4] is not None]
if margins:
    print(f"  Margins: Min={min(margins):.1f}€, Median={sorted(margins)[len(margins)//2]:.1f}€, Max={max(margins):.1f}€")
    print(f"  Under 15€ margin: {sum(1 for m in margins if m < 15)}")
    print(f"  15€ - 25€ margin: {sum(1 for m in margins if 15 <= m < 25)}")
    print(f"  25€ - 50€ margin: {sum(1 for m in margins if 25 <= m < 50)}")
    print(f"  > 50€ margin: {sum(1 for m in margins if m >= 50)}")

conn.close()
