import os
import sys
import time
import logging
from typing import List, Dict, Set
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.auth import VintedSessionManager
from src.rate_limiter import VintedRateLimiter
from src.scraper import VintedScraper
from src.translator import translate_query

# Force UTF-8 pour Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("TestOverlap")

# 5 recherches représentatives avec requêtes traduites
TEST_SEARCHES = [
    {
        "name": "🧥 Manteau en laine",
        "search_text": "manteau laine",
        "search_text_i18n": {
            "it": "cappotto lana",
            "de": "wollmantel",
            "es": "abrigo lana",
            "nl": "wollen jas",
            "pt": "casaco lã"
        }
    },
    {
        "name": "🧶 Pull en cachemire",
        "search_text": "pull cachemire",
        "search_text_i18n": {
            "it": "maglione cashmere",
            "de": "kaschmir pullover",
            "es": "jersey cachemira",
            "nl": "kasjmier trui",
            "pt": "camisola caxemira"
        }
    },
    {
        "name": "🧥 Veste en cuir vintage",
        "search_text": "veste cuir vintage",
        "search_text_i18n": {
            "it": "giacca pelle vintage",
            "de": "vintage lederjacke",
            "es": "chaqueta cuero vintage",
            "nl": "leren jas vintage",
            "pt": "casaco couro vintage"
        }
    },
    {
        "name": "🧥 Trench Burberry vintage",
        "search_text": "burberry trench vintage",
        "brand": "Burberry",
        "search_text_i18n": {
            "it": "burberry trench vintage",
            "de": "burberry trench vintage",
            "es": "burberry trench vintage",
            "nl": "burberry trench vintage",
            "pt": "burberry trench vintage"
        }
    },
    {
        "name": "👔 Chemise en soie",
        "search_text": "chemise soie",
        "search_text_i18n": {
            "it": "camicia seta",
            "de": "seidenhemd",
            "es": "camisa seda",
            "nl": "zijden overhemd",
            "pt": "camisa seda"
        }
    }
]

FOREIGN_COUNTRIES = ["it", "es", "de", "nl"]

def get_item_ids_for_query(domain: str, query: str, session_manager: VintedSessionManager, rate_limiter: VintedRateLimiter) -> Set[int]:
    """Récupère les IDs d'articles renvoyés sur un domaine pour une requête donnée."""
    scraper = VintedScraper(session_manager, rate_limiter=rate_limiter)
    items = scraper.search_items({"search_text": query, "name": f"{query}@{domain}"})
    return {item["id"] for item in items if item.get("id")}

def main():
    print("=" * 80)
    print("🔬 TEST DE RECOUVREMENT DES ANNONCES ENTRE VINTED.FR ET LES DOMAINES ÉTRANGERS")
    print("=" * 80)
    print("Ce script compare pour 5 recherches les ID renvoyés par vinted.fr (avec la requête traduite)")
    print("et par le domaine étranger du pays.\n")

    # Initialiser les sessions
    fr_session_mgr = VintedSessionManager(domain="vinted.fr", country="fr")
    fr_rate_limiter = VintedRateLimiter(min_interval_seconds=3.0)

    foreign_session_mgrs = {
        c: VintedSessionManager(domain=f"vinted.{c}", country=c) for c in FOREIGN_COUNTRIES
    }
    foreign_rate_limiters = {
        c: VintedRateLimiter(min_interval_seconds=3.0) for c in FOREIGN_COUNTRIES
    }

    results = []

    for idx, search in enumerate(TEST_SEARCHES, 1):
        search_title = search["name"]
        print(f"\n--- [{idx}/5] Recherche : {search_title} ---")
        
        for country in FOREIGN_COUNTRIES:
            domain = f"vinted.{country}"
            query = search["search_text_i18n"].get(country, search["search_text"])

            print(f"  👉 Test sur {country.upper()} avec requête : '{query}'")

            # 1. Requête sur vinted.fr avec la requête traduite
            ids_on_fr = get_item_ids_for_query("vinted.fr", query, fr_session_mgr, fr_rate_limiter)
            time.sleep(1.0)

            # 2. Requête sur le domaine du pays
            ids_on_country = get_item_ids_for_query(
                domain, query, foreign_session_mgrs[country], foreign_rate_limiters[country]
            )
            time.sleep(1.0)

            overlap = ids_on_fr.intersection(ids_on_country)
            total_unique = len(ids_on_fr.union(ids_on_country))

            if total_unique > 0:
                overlap_pct = (len(overlap) / len(ids_on_country) * 100) if ids_on_country else 0.0
                jaccard_pct = (len(overlap) / total_unique * 100)
            else:
                overlap_pct = 0.0
                jaccard_pct = 0.0

            print(f"     • Sur vinted.fr  : {len(ids_on_fr)} articles")
            print(f"     • Sur {domain} : {len(ids_on_country)} articles")
            print(f"     • En commun      : {len(overlap)} articles")
            print(f"     • Taux de couverture de {domain} par vinted.fr : {overlap_pct:.1f}%")

            results.append({
                "search": search["search_text"],
                "country": country,
                "fr_count": len(ids_on_fr),
                "country_count": len(ids_on_country),
                "overlap_count": len(overlap),
                "coverage_pct": overlap_pct
            })

    print("\n" + "=" * 80)
    print("📊 RÉSUMÉ GLOBAL DU TAUX DE RECOUVREMENT")
    print("=" * 80)
    print(f"{'Recherche':<25} | {'Pays':<6} | {'vinted.fr':<10} | {'Domaine':<10} | {'Commun':<8} | {'Couverture':<10}")
    print("-" * 80)
    avg_coverage = 0.0
    for r in results:
        print(f"{r['search'][:25]:<25} | {r['country'].upper():<6} | {r['fr_count']:<10} | {r['country_count']:<10} | {r['overlap_count']:<8} | {r['coverage_pct']:.1f}%")
        avg_coverage += r["coverage_pct"]

    if results:
        avg_coverage /= len(results)
        print("-" * 80)
        print(f"📈 TAUX DE COUVERTURE MOYEN PAR VINTED.FR : {avg_coverage:.1f}%")
    print("=" * 80)

if __name__ == "__main__":
    main()
