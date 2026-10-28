import sqlite3
from collections import Counter
import re

conn = sqlite3.connect('vinted_bot.db')
cur = conn.cursor()

today_alerts = cur.execute('''
    SELECT f.title, f.brand, f.price, d.margin, d.multiple, d.score_final, f.created_at, f.search_name
    FROM deal_feedback f
    JOIN decisions d ON f.item_id = d.item_id
    WHERE f.created_at >= '2026-10-28 00:00:00' AND d.decision = 'VALIDATED'
    ORDER BY f.id DESC
''').fetchall()

print(f"Total alerts analyzed today: {len(today_alerts)}")

# 1. By brand
brand_counter = Counter([r[1] for r in today_alerts if r[1]])
print("\n--- Alerts per brand today ---")
for b, c in brand_counter.most_common(15):
    pct = c / len(today_alerts) * 100
    print(f"  {b:<22} : {c:>3} ({pct:>4.1f}%)")

# 2. By price range
prices = [float(r[2]) for r in today_alerts if r[2] is not None]
print(f"\n--- Price breakdown ---")
print(f"  Under 8€ : {sum(1 for p in prices if p < 8)} ({sum(1 for p in prices if p < 8)/len(prices)*100:.1f}%)")
print(f"  8€ - 12€ : {sum(1 for p in prices if 8 <= p < 12)} ({sum(1 for p in prices if 8 <= p < 12)/len(prices)*100:.1f}%)")
print(f"  12€ - 16€: {sum(1 for p in prices if 12 <= p < 16)} ({sum(1 for p in prices if 12 <= p < 16)/len(prices)*100:.1f}%)")
print(f"  16€ - 20€: {sum(1 for p in prices if p >= 16)} ({sum(1 for p in prices if p >= 16)/len(prices)*100:.1f}%)")

# 3. By margin range
margins = [float(r[3]) for r in today_alerts if r[3] is not None]
print(f"\n--- Margin breakdown ---")
print(f"  < 15€ : {sum(1 for m in margins if m < 15)} ({sum(1 for m in margins if m < 15)/len(margins)*100:.1f}%)")
print(f"  15€ - 20€ : {sum(1 for m in margins if 15 <= m < 20)} ({sum(1 for m in margins if 15 <= m < 20)/len(margins)*100:.1f}%)")
print(f"  20€ - 30€ : {sum(1 for m in margins if 20 <= m < 30)} ({sum(1 for m in margins if 20 <= m < 30)/len(margins)*100:.1f}%)")
print(f"  30€ - 50€ : {sum(1 for m in margins if 30 <= m < 50)} ({sum(1 for m in margins if 30 <= m < 50)/len(margins)*100:.1f}%)")
print(f"  >= 50€: {sum(1 for m in margins if m >= 50)} ({sum(1 for m in margins if m >= 50)/len(margins)*100:.1f}%)")

# 4. By score range
scores = [float(r[5]) for r in today_alerts if r[5] is not None]
print(f"\n--- Final score breakdown ---")
print(f"  70 - 75 : {sum(1 for s in scores if 70 <= s < 75)} ({sum(1 for s in scores if 70 <= s < 75)/len(scores)*100:.1f}%)")
print(f"  75 - 80 : {sum(1 for s in scores if 75 <= s < 80)} ({sum(1 for s in scores if 75 <= s < 80)/len(scores)*100:.1f}%)")
print(f"  >= 80   : {sum(1 for s in scores if s >= 80)} ({sum(1 for s in scores if s >= 80)/len(scores)*100:.1f}%)")

# 5. Top keywords in titles today
words = []
for r in today_alerts:
    t = (r[0] or '').lower()
    for w in re.findall(r'[a-zà-ÿ]{4,}', t):
        if w not in {'taille', 'size', 'vintage', 'noir', 'pour', 'avec', 'sans', 'neuf', 'femme', 'homme', 'mujer', 'donna', 'nero', 'uomo'}:
            words.append(w)
word_counts = Counter(words)
print("\n--- Top product keywords in titles today ---")
for w, c in word_counts.most_common(20):
    print(f"  {w:<15} : {c}")

conn.close()
