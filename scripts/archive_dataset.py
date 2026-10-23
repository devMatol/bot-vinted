import sqlite3
import json
import csv
import os
import shutil
import sys
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

os.makedirs("backups", exist_ok=True)
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

db_path = "vinted_bot.db"
conn = sqlite3.connect(db_path, timeout=30.0)
conn.execute("PRAGMA journal_mode=WAL;")
conn.execute("PRAGMA busy_timeout=30000;")
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# 1. Sauvegarder la base de données entière
db_backup_path = f"backups/vinted_bot_archive_{timestamp}.db"
shutil.copy2(db_path, db_backup_path)
print(f"[OK] Base de donnees copiee vers : {db_backup_path}")

# 2. Exporter la table deal_feedback en JSON et CSV
cursor.execute("SELECT * FROM deal_feedback ORDER BY created_at ASC")
rows = cursor.fetchall()
data = [dict(row) for row in rows]

json_path = f"backups/dataset_feedback_precedent_{timestamp}.json"
with open(json_path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print(f"[OK] Dataset JSON ({len(data)} evaluations) exporte vers : {json_path}")

if data:
    csv_path = f"backups/dataset_feedback_precedent_{timestamp}.csv"
    keys = list(data[0].keys())
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(data)
    print(f"[OK] Dataset CSV exporte vers : {csv_path}")

# 3. Réinitialiser la table deal_feedback pour la nouvelle niche
cursor.execute("DELETE FROM deal_feedback")
conn.commit()
print("[OK] Table deal_feedback reinitialisee pour la nouvelle niche Luxe Homme !")

conn.close()
