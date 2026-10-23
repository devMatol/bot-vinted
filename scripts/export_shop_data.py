"""Script d'export des données de référence de la boutique Vinted (Lot 1).

Extrait :
1. Ventes (/api/v2/my_orders?type=sold&status=all)
2. Achats (/api/v2/my_orders?type=purchased&status=all)
3. Vitrine (/api/v2/wardrobe/{user_id}/items)
4. Favoris (/api/v2/users/{user_id}/items/favourites)
5. Feedback bot (table deal_feedback)

Sorties :
- data/sales.parquet
- data/purchases.parquet
- data/wardrobe.parquet
- data/favourites.parquet
- data/feedback.parquet
- data/images/{source}/{id}.jpg (vignettes de taille moyenne)

Affiche un résumé console avec volumes, prix médians, top marques et top catégories.
"""

import os
import sys
import time
import json
import sqlite3
import argparse
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, List, Optional, Tuple

import requests
import pandas as pd
import numpy as np

# Force UTF-8 pour la console Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("ExportShopData")

# Imports internes
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.scoring.taxonomy import detect_category, normalize_brand, normalize_size
from src.auth import VintedSessionManager

CONFIG_PATH = "config.json"
DATA_DIR = "data"
IMAGES_DIR = os.path.join(DATA_DIR, "images")
DB_PATH = "vinted_bot.db"


def load_config(path: str = CONFIG_PATH) -> Dict[str, Any]:
    if not os.path.exists(path):
        logger.warning(f"Configuration '{path}' introuvable, utilisation de paramètres par défaut.")
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_vinted_session(config: Dict[str, Any]) -> Tuple[Any, int, str]:
    """
    Initialise la session de scraping avec VintedSessionManager (Cloudflare + TLS impersonation).
    Tente de déduire user_id via /api/v2/users/current, sinon utilise la config.
    """
    sess_info = config.get("vinted_session", {})
    fallback_uid = int(sess_info.get("v_uid", 68815764))
    session_cookie = sess_info.get("session_cookie")

    sm = VintedSessionManager("vinted.fr", session_cookie=session_cookie)
    session = sm.get_session()

    session.headers.update({
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    })

    # Tester access token si présent
    access_token = sess_info.get("access_token")
    user_id = fallback_uid
    shop_login = "nuzhdina.ri"

    if access_token:
        session.headers["Authorization"] = f"Bearer {access_token}"
        try:
            resp = session.get("https://www.vinted.fr/api/v2/users/current", timeout=8)
            if resp.status_code == 200:
                udata = resp.json().get("user", {})
                user_id = udata.get("id", fallback_uid)
                shop_login = udata.get("login", shop_login)
                logger.info(f"✅ Session Vinted authentifiée : {shop_login} (ID: {user_id})")
            else:
                # Token expiré ou invalide : retirer l'en-tête Authorization pour préserver l'accès aux endpoints publics
                logger.info(f"ℹ️ Jeton Bearer non accepté ({resp.status_code}). Poursuite avec session cookies.")
                session.headers.pop("Authorization", None)
        except Exception as e:
            logger.warning(f"Erreur vérification token utilisateur : {e}")
            session.headers.pop("Authorization", None)
    else:
        try:
            resp = session.get("https://www.vinted.fr/api/v2/users/current", timeout=8)
            if resp.status_code == 200:
                udata = resp.json().get("user", {})
                user_id = udata.get("id", fallback_uid)
                shop_login = udata.get("login", shop_login)
                logger.info(f"✅ Utilisateur connecté identifié : {shop_login} (ID: {user_id})")
        except Exception:
            pass

    return session, user_id, shop_login


def safe_request(session: requests.Session, url: str, params: Optional[Dict[str, Any]] = None) -> Optional[requests.Response]:
    """Exécute une requête avec respect du rate-limit (1s pause) et arrêt propre sur 429."""
    time.sleep(1.0)
    try:
        resp = session.get(url, params=params, timeout=15)
        if resp.status_code == 429:
            logger.error("🛑 Erreur HTTP 429 (Rate Limit) reçue de Vinted. Arrêt propre pour protéger la session.")
            return None
        return resp
    except Exception as e:
        logger.warning(f"Erreur requête {url}: {e}")
        return None


def extract_best_thumb_url(photos: List[Dict[str, Any]]) -> Optional[str]:
    """Extrait l'URL d'une vignette de taille moyenne (thumb310x430 ou f800)."""
    if not photos or not isinstance(photos, list):
        return None
    p = photos[0]
    if isinstance(p, dict):
        thumbnails = p.get("thumbnails", [])
        if isinstance(thumbnails, list):
            for t in thumbnails:
                if isinstance(t, dict) and t.get("type") in ("thumb310x430", "thumb428x624"):
                    return t.get("url")
            for t in thumbnails:
                if isinstance(t, dict) and "url" in t:
                    return t.get("url")
        return p.get("url") or p.get("full_size_url")
    elif isinstance(p, str):
        return p
    return None


def download_thumbnail(url: str, dest_path: str, session: requests.Session) -> bool:
    """Télécharge une vignette JPEG moyenne si elle n'existe pas déjà."""
    if not url or os.path.exists(dest_path):
        return False
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    try:
        resp = session.get(url, timeout=10)
        if resp.status_code == 200 and len(resp.content) > 500:
            with open(dest_path, "wb") as f:
                f.write(resp.content)
            return True
    except Exception:
        pass
    return False


def fetch_orders(
    session: requests.Session,
    order_type: str,
    max_pages: int = 50
) -> List[Dict[str, Any]]:
    """
    Récupère les commandes paginées (sold ou purchased).
    Pour chaque vente/achat, tente d'enrichir via /api/v2/transactions/{id}.
    Exclut commandes annulées et remboursées.
    """
    orders_data: List[Dict[str, Any]] = []
    base_url = "https://www.vinted.fr/api/v2/my_orders"
    logger.info(f"📦 Récupération des commandes '{order_type}'...")

    for page in range(1, max_pages + 1):
        params = {"type": order_type, "status": "all", "page": page, "per_page": 20}
        resp = safe_request(session, base_url, params=params)
        if resp is None:
            break
        if resp.status_code != 200:
            if page == 1:
                logger.warning(f"⚠️ /api/v2/my_orders ({order_type}) a retourné le statut {resp.status_code}.")
            break

        data = resp.json()
        orders = data.get("my_orders") or data.get("orders") or data.get("data") or []  # la clé réelle de l'API est "my_orders"
        if not orders:
            break

        for ord_item in orders:
            status = str(ord_item.get("status") or "").lower()
            if status in ("cancelled", "canceled", "refunded", "annule", "annulée", "rembourse", "remboursée"):
                continue

            item_obj = ord_item.get("item") or {}
            transaction_id = ord_item.get("transaction_id") or ord_item.get("id")
            
            # Tentative de détail enrichi
            detail = {}
            if transaction_id:
                t_resp = safe_request(session, f"https://www.vinted.fr/api/v2/transactions/{transaction_id}")
                if t_resp and t_resp.status_code == 200:
                    detail = t_resp.json().get("transaction", {}) or {}

            # Données fusionnées
            item_data = detail.get("item") or item_obj
            raw_title = item_data.get("title") or ord_item.get("title") or ""
            raw_desc = item_data.get("description") or ""
            price_val = 0.0
            p_obj = item_data.get("price") or ord_item.get("price") or {}
            if isinstance(p_obj, dict):
                price_val = float(p_obj.get("amount", 0.0) or 0.0)
            elif isinstance(p_obj, (int, float, str)):
                try:
                    price_val = float(p_obj)
                except (ValueError, TypeError):
                    price_val = 0.0

            raw_brand = item_data.get("brand_title") or item_data.get("brand") or ord_item.get("brand_title") or ""
            raw_size = item_data.get("size_title") or item_data.get("size") or ""
            raw_status = item_data.get("status") or ""
            category_vinted = item_data.get("category_title") or ""

            # Taxonomie normalisée
            norm_cat = detect_category(raw_title, raw_desc)
            norm_brand_name, brand_line, brand_tier = normalize_brand(raw_brand, raw_title)
            norm_sz = normalize_size(raw_size, norm_cat)

            photos = item_data.get("photos") or ord_item.get("photos") or []
            thumb_url = extract_best_thumb_url(photos)

            orders_data.append({
                "id": int(item_data.get("id") or transaction_id or len(orders_data) + 1),
                "transaction_id": transaction_id,
                "title": raw_title,
                "price": price_val,
                "currency": ord_item.get("currency", "EUR"),
                "brand_raw": raw_brand,
                "brand_canonical": norm_brand_name,
                "brand_line": brand_line,
                "brand_tier": brand_tier,
                "size_raw": raw_size,
                "size_normalized": norm_sz,
                "condition": raw_status,
                "category_vinted": category_vinted,
                "category_normalized": norm_cat,
                "created_at": ord_item.get("created_at") or detail.get("created_at") or "",
                "status": status,
                "thumb_url": thumb_url
            })

        pagination = data.get("pagination", {})
        total_pages = pagination.get("total_pages", page)
        if page >= total_pages:
            break

    logger.info(f"✅ {len(orders_data)} commandes '{order_type}' récupérées avec succès.")
    return orders_data


def fetch_wardrobe(
    session: requests.Session,
    user_id: int,
    max_pages: int = 50
) -> List[Dict[str, Any]]:
    """
    Récupère la vitrine complète (/api/v2/wardrobe/{user_id}/items).
    """
    wardrobe_data: List[Dict[str, Any]] = []
    base_url = f"https://www.vinted.fr/api/v2/wardrobe/{user_id}/items"
    logger.info(f"👗 Récupération de la vitrine pour l'utilisateur {user_id}...")

    for page in range(1, max_pages + 1):
        params = {"page": page, "per_page": 20}
        resp = safe_request(session, base_url, params=params)
        if resp is None:
            break
        if resp.status_code != 200:
            logger.warning(f"Statut {resp.status_code} pour la vitrine page {page}")
            break

        data = resp.json()
        items = data.get("items") or []
        if not items:
            break

        for item in items:
            raw_title = item.get("title") or ""
            raw_desc = item.get("description") or ""
            
            price_val = 0.0
            p_obj = item.get("price") or {}
            if isinstance(p_obj, dict):
                price_val = float(p_obj.get("amount", 0.0) or 0.0)
            elif isinstance(p_obj, (int, float, str)):
                try:
                    price_val = float(p_obj)
                except (ValueError, TypeError):
                    price_val = 0.0

            raw_brand = item.get("brand") or item.get("brand_title") or ""
            raw_size = item.get("size") or item.get("size_title") or ""
            raw_status = item.get("status") or ""

            norm_cat = detect_category(raw_title, raw_desc)
            norm_brand_name, brand_line, brand_tier = normalize_brand(raw_brand, raw_title)
            norm_sz = normalize_size(raw_size, norm_cat)

            photos = item.get("photos") or []
            thumb_url = extract_best_thumb_url(photos)

            wardrobe_data.append({
                "id": int(item.get("id")),
                "title": raw_title,
                "price": price_val,
                "currency": item.get("currency", "EUR"),
                "brand_raw": raw_brand,
                "brand_canonical": norm_brand_name,
                "brand_line": brand_line,
                "brand_tier": brand_tier,
                "size_raw": raw_size,
                "size_normalized": norm_sz,
                "condition": raw_status,
                "category_normalized": norm_cat,
                "is_closed": bool(item.get("is_closed", False)),
                "is_reserved": bool(item.get("is_reserved", False)),
                "favourite_count": int(item.get("favourite_count", 0) or 0),
                "view_count": int(item.get("view_count", 0) or 0),
                "created_at": item.get("created_at") or "",
                "thumb_url": thumb_url
            })

        pagination = data.get("pagination", {})
        total_pages = pagination.get("total_pages", page)
        if page >= total_pages:
            break

    logger.info(f"✅ {len(wardrobe_data)} articles de vitrine récupérés.")
    return wardrobe_data


def fetch_favourites(
    session: requests.Session,
    user_id: int,
    max_pages: int = 50
) -> List[Dict[str, Any]]:
    """
    Récupère les favoris du compte (/api/v2/users/{user_id}/items/favourites),
    dédoublonnés par ID.
    """
    favs_data: List[Dict[str, Any]] = []
    seen_ids = set()
    base_url = f"https://www.vinted.fr/api/v2/users/{user_id}/items/favourites"
    logger.info(f"⭐ Récupération des favoris pour l'utilisateur {user_id}...")

    for page in range(1, max_pages + 1):
        params = {"page": page, "per_page": 20}
        resp = safe_request(session, base_url, params=params)
        if resp is None:
            break
        if resp.status_code != 200:
            if page == 1:
                logger.info(f"ℹ️ /api/v2/users/{user_id}/items/favourites a retourné {resp.status_code} (non accessible ou vide).")
            break

        data = resp.json()
        items = data.get("items") or data.get("data") or []
        if not items:
            break

        for item in items:
            iid = item.get("id")
            if not iid or iid in seen_ids:
                continue
            seen_ids.add(iid)

            raw_title = item.get("title") or ""
            raw_desc = item.get("description") or ""

            price_val = 0.0
            p_obj = item.get("price") or {}
            if isinstance(p_obj, dict):
                price_val = float(p_obj.get("amount", 0.0) or 0.0)
            elif isinstance(p_obj, (int, float, str)):
                try:
                    price_val = float(p_obj)
                except (ValueError, TypeError):
                    price_val = 0.0

            raw_brand = item.get("brand") or item.get("brand_title") or ""
            raw_size = item.get("size") or item.get("size_title") or ""
            raw_status = item.get("status") or ""

            norm_cat = detect_category(raw_title, raw_desc)
            norm_brand_name, brand_line, brand_tier = normalize_brand(raw_brand, raw_title)
            norm_sz = normalize_size(raw_size, norm_cat)

            photos = item.get("photos") or []
            thumb_url = extract_best_thumb_url(photos)

            favs_data.append({
                "id": int(iid),
                "title": raw_title,
                "price": price_val,
                "currency": item.get("currency", "EUR"),
                "brand_raw": raw_brand,
                "brand_canonical": norm_brand_name,
                "brand_line": brand_line,
                "brand_tier": brand_tier,
                "size_raw": raw_size,
                "size_normalized": norm_sz,
                "condition": raw_status,
                "category_normalized": norm_cat,
                "favourite_count": int(item.get("favourite_count", 0) or 0),
                "thumb_url": thumb_url
            })

        pagination = data.get("pagination", {})
        total_pages = pagination.get("total_pages", page)
        if page >= total_pages:
            break

    logger.info(f"✅ {len(favs_data)} favoris récupérés.")
    return favs_data


def fetch_bot_feedback(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """
    Extrait les évaluations de la table deal_feedback de la base SQLite.
    Filtre sur MUST_BUY, NEED_WIFE_OPINION / NEEDS_REVIEW, REJECTED / REJECT.
    """
    if not os.path.exists(db_path):
        logger.warning(f"Base de données '{db_path}' introuvable.")
        return []

    logger.info(f"🤖 Extraction des feedbacks bot depuis '{db_path}'...")
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    query = """
    SELECT id, item_id, search_name, title, price, brand, condition, seller_rating,
           description, photo_urls, classification, verdict, score, created_at, domain
    FROM deal_feedback
    WHERE classification IN ('MUST_BUY', 'NEED_WIFE_OPINION', 'REJECTED')
       OR verdict IN ('MUST_BUY', 'NEEDS_REVIEW', 'REJECT')
    ORDER BY id ASC
    """
    try:
        rows = cursor.execute(query).fetchall()
    except Exception as e:
        logger.error(f"Erreur lecture deal_feedback: {e}")
        conn.close()
        return []

    conn.close()
    feedback_data: List[Dict[str, Any]] = []

    for r in rows:
        row = dict(r)
        raw_title = row.get("title") or ""
        raw_desc = row.get("description") or ""
        raw_brand = row.get("brand") or ""
        raw_cond = row.get("condition") or ""
        price_val = float(row.get("price") or 0.0)

        norm_cat = detect_category(raw_title, raw_desc)
        norm_brand_name, brand_line, brand_tier = normalize_brand(raw_brand, raw_title)

        # Décoder première photo
        photos_raw = row.get("photo_urls") or ""
        first_photo_url = None
        if photos_raw:
            try:
                plist = json.loads(photos_raw) if photos_raw.startswith("[") else [p.strip() for p in photos_raw.split(",")]
                if plist:
                    first_photo_url = plist[0]
            except Exception:
                first_photo_url = photos_raw

        # Normalisation classification
        cls_val = row.get("classification") or ""
        verdict_val = row.get("verdict") or ""
        final_label = cls_val if cls_val in ("MUST_BUY", "NEED_WIFE_OPINION", "REJECTED") else ""
        if not final_label:
            if verdict_val == "MUST_BUY":
                final_label = "MUST_BUY"
            elif verdict_val == "NEEDS_REVIEW":
                final_label = "NEED_WIFE_OPINION"
            elif verdict_val == "REJECT":
                final_label = "REJECTED"

        feedback_data.append({
            "id": int(row.get("item_id") or row.get("id")),
            "db_id": row.get("id"),
            "search_name": row.get("search_name") or "",
            "title": raw_title,
            "price": price_val,
            "brand_raw": raw_brand,
            "brand_canonical": norm_brand_name,
            "brand_line": brand_line,
            "brand_tier": brand_tier,
            "condition": raw_cond,
            "seller_rating": row.get("seller_rating"),
            "category_normalized": norm_cat,
            "classification": final_label,
            "score": float(row.get("score") or 0.0),
            "created_at": row.get("created_at") or "",
            "thumb_url": first_photo_url
        })

    logger.info(f"✅ {len(feedback_data)} feedbacks bot extraits de la table deal_feedback.")
    return feedback_data


def download_thumbnails_pool(items: List[Dict[str, Any]], source_name: str, max_workers: int = 8) -> int:
    """Télécharge les vignettes en parallèle dans data/images/{source_name}/{id}.jpg."""
    out_dir = os.path.join(IMAGES_DIR, source_name)
    os.makedirs(out_dir, exist_ok=True)
    
    tasks = []
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    })

    for it in items:
        url = it.get("thumb_url")
        item_id = it.get("id")
        if url and item_id:
            dest = os.path.join(out_dir, f"{item_id}.jpg")
            tasks.append((url, dest))

    downloaded = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(download_thumbnail, url, dest, session): dest for url, dest in tasks}
        for future in as_completed(futures):
            try:
                if future.result():
                    downloaded += 1
            except Exception:
                pass

    return downloaded


def display_summary_report(
    sales_df: pd.DataFrame,
    purchases_df: pd.DataFrame,
    wardrobe_df: pd.DataFrame,
    favourites_df: pd.DataFrame,
    feedback_df: pd.DataFrame
):
    """Affiche un résumé console structuré : volumes, prix médians, top marques, top catégories."""
    print("\n" + "=" * 70)
    print("📊 RÉSUMÉ DES DONNÉES DE RÉFÉRENCE DE LA BOUTIQUE (LOT 1)")
    print("=" * 70)

    # Volumes
    print(f"📦 Ventes enregistrées     : {len(sales_df)}")
    print(f"🛒 Achats enregistrés     : {len(purchases_df)}")
    print(f"👗 Articles en vitrine    : {len(wardrobe_df)}")
    print(f"⭐ Favoris                 : {len(favourites_df)}")
    print(f"🤖 Feedbacks bot           : {len(feedback_df)}")

    # Prix médians
    if not sales_df.empty and "price" in sales_df.columns:
        p_sales = sales_df[sales_df["price"] > 0]["price"]
        med_sale = p_sales.median() if not p_sales.empty else 0.0
        print(f"\n💰 Prix de vente médian   : {med_sale:.2f} €")
    if not purchases_df.empty and "price" in purchases_df.columns:
        p_purch = purchases_df[purchases_df["price"] > 0]["price"]
        med_purch = p_purch.median() if not p_purch.empty else 0.0
        print(f"💰 Prix d'achat médian    : {med_purch:.2f} €")

    # Analyse des ventes si disponibles
    active_sales = sales_df if not sales_df.empty else wardrobe_df[wardrobe_df.get("is_closed", False) == True] if not wardrobe_df.empty else pd.DataFrame()

    if not active_sales.empty:
        print("\n🏆 TOP CATÉGORIES (Prix de vente moyen & volume) :")
        cat_stats = active_sales.groupby("category_normalized")["price"].agg(["count", "median", "mean"]).sort_values(by="median", ascending=False)
        for cat, row in cat_stats.head(10).iterrows():
            print(f"   • {cat:<18} : {int(row['count']):>3} ventes | Médiane : {row['median']:>5.1f} € | Moyenne : {row['mean']:>5.1f} €")

        print("\n🏷️ TOP MARQUES CANONIQUES :")
        brand_stats = active_sales[active_sales["brand_canonical"] != "Sans marque"].groupby("brand_canonical")["price"].agg(["count", "median"]).sort_values(by="count", ascending=False)
        for brand, row in brand_stats.head(8).iterrows():
            print(f"   • {brand:<22} : {int(row['count']):>3} ventes | Prix médian : {row['median']:>5.1f} €")

        # Pourcentage de pièces sans marque dans le titre
        if "title" in active_sales.columns and "brand_canonical" in active_sales.columns:
            has_no_brand = (active_sales["brand_canonical"] == "Sans marque").mean() * 100.0
            print(f"\n💡 Pièces sans marque détectée : {has_no_brand:.1f}% des ventes")

    print("=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Export des données de référence de la boutique Vinted (Lot 1).")
    parser.add_argument("--max-pages", type=int, default=30, help="Nombre max de pages par endpoint (défaut 30).")
    parser.add_argument("--skip-images", action="store_true", help="Ne pas télécharger les vignettes d'images.")
    args = parser.parse_args()

    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(IMAGES_DIR, exist_ok=True)

    # Import prioritaire depuis data/import/*.csv si présents
    try:
        from scripts.import_shop_csv import ensure_shop_data_imported
        ensure_shop_data_imported()
    except Exception as e:
        logger.warning(f"Note: ensure_shop_data_imported non exécuté: {e}")

    config = load_config(CONFIG_PATH)
    session, user_id, shop_login = get_vinted_session(config)

    # 1. Vitrine (Wardrobe)
    wardrobe_items = fetch_wardrobe(session, user_id, max_pages=args.max_pages)
    wardrobe_path = os.path.join(DATA_DIR, "wardrobe.parquet")
    if wardrobe_items:
        wardrobe_df = pd.DataFrame(wardrobe_items)
        wardrobe_df.to_parquet(wardrobe_path, index=False)
        logger.info(f"💾 Vitrine sauvegardée -> {wardrobe_path} ({len(wardrobe_df)} lignes)")
    else:
        wardrobe_df = pd.read_parquet(wardrobe_path) if os.path.exists(wardrobe_path) else pd.DataFrame()

    # 2. Ventes (Sold orders)
    sales_items = fetch_orders(session, "sold", max_pages=args.max_pages)
    if not sales_items and not wardrobe_df.empty:
        closed_items = wardrobe_df[wardrobe_df.get("is_closed", False) == True].to_dict(orient="records")
        if closed_items:
            logger.info(f"ℹ️ Intégration de {len(closed_items)} articles clôturés/vendus depuis la vitrine dans sales.parquet.")
            sales_items = closed_items
    sales_path = os.path.join(DATA_DIR, "sales.parquet")
    if sales_items:
        sales_df = pd.DataFrame(sales_items)
        sales_df.to_parquet(sales_path, index=False)
        logger.info(f"💾 Ventes sauvegardées -> {sales_path} ({len(sales_df)} lignes)")
    else:
        sales_df = pd.read_parquet(sales_path) if os.path.exists(sales_path) else pd.DataFrame()

    # 3. Achats (Purchased orders)
    purchases_items = fetch_orders(session, "purchased", max_pages=args.max_pages)
    purchases_path = os.path.join(DATA_DIR, "purchases.parquet")
    if purchases_items:
        purchases_df = pd.DataFrame(purchases_items)
        purchases_df.to_parquet(purchases_path, index=False)
        logger.info(f"💾 Achats sauvegardés -> {purchases_path} ({len(purchases_df)} lignes)")
    else:
        purchases_df = pd.read_parquet(purchases_path) if os.path.exists(purchases_path) else pd.DataFrame()

    # 4. Favoris (Favourites)
    favourites_items = fetch_favourites(session, user_id, max_pages=args.max_pages)
    favourites_path = os.path.join(DATA_DIR, "favourites.parquet")
    if favourites_items:
        favourites_df = pd.DataFrame(favourites_items)
        favourites_df.to_parquet(favourites_path, index=False)
        logger.info(f"💾 Favoris sauvegardés -> {favourites_path} ({len(favourites_df)} lignes)")
    else:
        favourites_df = pd.read_parquet(favourites_path) if os.path.exists(favourites_path) else pd.DataFrame()

    # 5. Feedback bot (deal_feedback)
    feedback_items = fetch_bot_feedback(DB_PATH)
    feedback_df = pd.DataFrame(feedback_items)
    feedback_path = os.path.join(DATA_DIR, "feedback.parquet")
    feedback_df.to_parquet(feedback_path, index=False)
    logger.info(f"💾 Feedback bot sauvegardé -> {feedback_path} ({len(feedback_df)} lignes)")

    # 6. Téléchargement des vignettes d'images moyennes
    if not args.skip_images:
        logger.info("🖼️ Téléchargement des vignettes d'images (taille moyenne)...")
        if wardrobe_items:
            nb = download_thumbnails_pool(wardrobe_items, "wardrobe")
            logger.info(f"  • Vitrine : {nb} nouvelles vignettes téléchargées.")
        if sales_items:
            nb = download_thumbnails_pool(sales_items, "sales")
            logger.info(f"  • Ventes : {nb} nouvelles vignettes téléchargées.")
        if feedback_items:
            # Pour le feedback, charger un échantillon des plus pertinents
            nb = download_thumbnails_pool(feedback_items[:200], "feedback")
            logger.info(f"  • Feedback : {nb} nouvelles vignettes téléchargées.")

    # 7. Résumé console
    display_summary_report(sales_df, purchases_df, wardrobe_df, favourites_df, feedback_df)


if __name__ == "__main__":
    main()
