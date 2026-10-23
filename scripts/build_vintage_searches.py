import json
import re
import sys

raw_data = """
Manteaux et vestes

trench burberry vintage : 35 €
burberry manteau laine : 40 €
burberry veste vintage : 30 €
aquascutum trench : 30 €
max mara manteau : 45 €
max mara manteau camel : 50 €
manteau cachemire femme : 40 €
manteau cachemire homme : 40 €
loden manteau : 25 €
loden steinbock : 25 €
cape laine vintage : 20 €
manteau laine made in italy : 25 €
manteau made in france laine vintage : 20 €
barbour veste vintage : 30 €
ralph lauren manteau laine : 30 €
cerruti 1881 manteau : 25 €
daniel hechter manteau : 20 €
hugo boss manteau laine ancien : 25 €

Cuir

perfecto cuir vintage : 30 €
blouson cuir agneau vintage : 25 €
schott perfecto : 45 €
veste cuir années 80 : 20 €
peau lainée vintage : 30 €
daniel hechter blouson cuir : 20 €

Maille

pull cachemire loro piana : 40 €
pull cachemire max mara : 30 €
pull cachemire pur : 15 €
pull mohair vintage : 12 €
pull alpaga : 15 €
pull jacquard vintage : 12 €
pull shetland : 12 €
gilet cachemire : 15 €
gaultier maille : 25 €
kenzo pull vintage : 20 €
ralph lauren pull laine : 15 €
burberry pull : 25 €

Blazers et costumes

blazer yves saint laurent : 25 €
ysl rive gauche veste : 30 €
dior veste vintage : 40 €
lanvin blazer : 25 €
ungaro veste : 20 €
mugler veste vintage : 40 €
veste croisée laine vintage : 15 €
blazer harris tweed : 15 €
veste tweed vintage : 15 €

Accessoires

carré hermès : 60 €
hermès foulard soie : 60 €
carré soie vintage : 12 €
burberry écharpe : 20 €
écharpe cachemire : 12 €
ceinture hermès : 80 €
celine foulard : 25 €
dior foulard : 20 €
ysl foulard : 15 €
lanvin foulard : 15 €

Recherches "annonces mal titrées" (les plus rentables)

manteau beige laine femme : 15 €
manteau camel : 20 €
manteau long laine : 15 €
trench beige : 15 €
veste laine homme vintage : 10 €
pull laine vintage : 8 €
manteau grand-mère : 10 €
manteau sans étiquette : 10 €
étiquette coupée manteau : 10 €
lot foulards soie : 15 €
lot pulls laine : 20 €
foulard soie signé : 10 €
"""

categories = {
    "Manteaux et vestes": "🧥",
    "Cuir": "🏍️",
    "Maille": "🧶",
    "Blazers et costumes": "👔",
    "Accessoires": "🧣",
    'Recherches "annonces mal titrées" (les plus rentables)': "🎯"
}

current_cat = "Manteaux et vestes"
searches = []

def slugify(text):
    text = text.lower()
    text = re.sub(r'[éèêë]', 'e', text)
    text = re.sub(r'[àâä]', 'a', text)
    text = re.sub(r'[îï]', 'i', text)
    text = re.sub(r'[ôö]', 'o', text)
    text = re.sub(r'[ùûü]', 'u', text)
    text = re.sub(r'[^a-z0-9]+', '_', text)
    return text.strip('_')

for line in raw_data.strip().split("\n"):
    line = line.strip()
    if not line:
        continue
    if line in categories:
        current_cat = line
        continue

    # Format: query : price €
    if ":" in line:
        parts = line.split(":")
        query = parts[0].strip()
        price_str = parts[1].replace("€", "").strip()
        try:
            max_price = float(price_str)
        except ValueError:
            continue

        emoji = categories.get(current_cat, "⚡")
        search_id = f"sniper_{slugify(query)}"
        
        # Déterminer un prix minimum anti-poubelle adapté
        if max_price <= 10.0:
            min_price = 4.0
        elif max_price <= 15.0:
            min_price = 5.0
        elif max_price <= 25.0:
            min_price = 8.0
        else:
            min_price = 10.0

        searches.append({
            "id": search_id,
            "enabled": True,
            "category": current_cat,
            "name": f"{emoji} [{current_cat}] {query} < {int(max_price)}€",
            "search_text": query,
            "min_price": min_price,
            "max_price": max_price,
            "min_favourites": 0,
            "currency": "EUR",
            "min_seller_rating": 4.0,
            "exclude_keywords": [
                "parfum", "échantillon", "vide", "boite", "fake", "imitation", "copie", 
                "lunettes", "étui", "coque", "casquette", "cap", "bonnet"
            ]
        })

print(f"Total searches parsed: {len(searches)}")

with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

config["searches"] = searches
config["polling_interval_seconds"] = 1.0

with open("config.json", "w", encoding="utf-8") as f:
    json.dump(config, f, ensure_ascii=False, indent=2)

print("config.json updated successfully!")
