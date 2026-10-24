import logging
import time
import re
import json
import html as html_lib
from typing import List, Dict, Any, Optional
from urllib.parse import urlencode

from src.auth import VintedSessionManager
from src.rate_limiter import VintedRateLimiter

logger = logging.getLogger("VintedBot.Scraper")

class VintedScraper:
    """Scraper principal interrogeant le catalogue Vinted avec parsing haute performance et cadence anti-429."""

    def __init__(self, session_manager: VintedSessionManager, rate_limiter: Optional[VintedRateLimiter] = None):
        self.session_manager = session_manager
        self.rate_limiter = rate_limiter or VintedRateLimiter(min_interval_seconds=3.0)

    def search_items(self, search_config: Dict[str, Any], priority: str = "low") -> List[Dict[str, Any]]:
        """
        Interroge le catalogue Vinted et extrait instantanément les annonces avec métadonnées enrichies.
        """
        search_text = search_config.get("search_text", "")
        max_price = search_config.get("max_price")
        order_param = search_config.get("order", "newest_first")
        brand_ids = search_config.get("brand_ids") or []

        query_params = [("order", order_param)]
        if max_price:
            query_params.append(("price_to", str(max_price)))
        for bid in brand_ids:
            query_params.append(("brand_ids[]", str(bid)))
        if search_text and not brand_ids:
            query_params.append(("search_text", search_text))

        domain = getattr(self.session_manager, "domain", "vinted.fr")
        url = f"https://www.{domain}/catalog?{urlencode(query_params)}"

        try:
            session = self.session_manager.get_session()
            self.rate_limiter.wait_for_token(priority=priority)
            response = session.get(url, timeout=12)

            if response.status_code in (401, 403):
                logger.debug(f"Session Vinted à renouveler (Status {response.status_code}). Attente...")
                time.sleep(5)
                session = self.session_manager.get_session(force_refresh=True)
                self.rate_limiter.wait_for_token(priority=priority)
                response = session.get(url, timeout=12)
            elif response.status_code == 429:
                logger.warning(f"⚠️ Rate limit Vinted (HTTP 429) sur {domain}. Pause de 45s...")
                self.rate_limiter.pause(45.0)
                return []

            if response.status_code != 200:
                logger.debug(f"Réponse {response.status_code} pour '{search_config.get('name')}'")
                return []

            # 1. Extraction des métadonnées riches depuis les cartes du catalogue
            # 1a. Titres enrichis overlay: data-testid="product-item-id-<id>--overlay-link" title="..."
            card_meta: Dict[int, Dict[str, Any]] = {}
            for item_id_str, raw_card_title in re.findall(r'data-testid="product-item-id-(\d+)--overlay-link"[^>]*title="([^"]*)"', response.text):
                try:
                    cid = int(item_id_str)
                    meta_entry = {"raw_title": raw_card_title}
                    m_b = re.search(r",\s*Marque:\s*([^,]+)", raw_card_title)
                    if m_b:
                        meta_entry["brand_title"] = html_lib.unescape(m_b.group(1).strip())
                    m_st = re.search(r",\s*(?:État|Etat):\s*([^,]+)", raw_card_title, re.IGNORECASE)
                    if m_st:
                        meta_entry["status"] = html_lib.unescape(m_st.group(1).strip())
                    m_sz = re.search(r",\s*Taille:\s*([^,]+)", raw_card_title)
                    if m_sz:
                        meta_entry["size_title"] = html_lib.unescape(m_sz.group(1).strip())
                    if ", Marque:" in raw_card_title:
                        meta_entry["title"] = raw_card_title.split(", Marque:")[0].strip()
                    else:
                        meta_entry["title"] = raw_card_title.split(",")[0].strip()
                    card_meta[cid] = meta_entry
                except Exception:
                    pass

            # 1b. Brand fallback depuis description-title
            for item_id_str, b_text in re.findall(r'data-testid="product-item-id-(\d+)--description-title">([^<]+)</p>', response.text):
                try:
                    cid = int(item_id_str)
                    card_meta.setdefault(cid, {})["brand_title"] = html_lib.unescape(b_text.strip())
                except Exception:
                    pass

            # 1c. Subtitle (Taille & État)
            for item_id_str, sub_text in re.findall(r'data-testid="product-item-id-(\d+)--description-subtitle">([^<]+)</p>', response.text):
                try:
                    cid = int(item_id_str)
                    cleaned_sub = html_lib.unescape(sub_text.strip())
                    entry = card_meta.setdefault(cid, {})
                    if "•" in cleaned_sub:
                        parts = [p.strip() for p in cleaned_sub.split("•", 1)]
                        entry.setdefault("size_title", parts[0])
                        entry.setdefault("status", parts[1])
                    elif not entry.get("status"):
                        entry["status"] = cleaned_sub
                except Exception:
                    pass

            # 1d. Images directes de haute qualité depuis le catalogue
            card_images: Dict[int, str] = {}
            for item_id_str, img_url in re.findall(r'data-testid="product-item-id-(\d+)--image--img"[^>]*src="([^"]+)"', response.text):
                try:
                    card_images[int(item_id_str)] = img_url
                except Exception:
                    pass

            # 1e. Prix catalog
            catalog_prices: Dict[int, float] = {}
            for item_id_match, price_str in re.findall(r'data-testid="product-item-id-(\d+)--price-text"[^>]*>([^<]+)<', response.text):
                clean_p = price_str.replace("\xa0", "").replace(" ", "").replace("€", "").replace(",", ".").strip()
                try:
                    catalog_prices[int(item_id_match)] = float(clean_p)
                except (ValueError, TypeError):
                    pass

            # JSON streaming Next.js fallback
            for item_id_match, price_str in re.findall(r'"id":(\d+),"productItem":\{.*?"price":\{"amount":"([^"]+)"', response.text):
                try:
                    cid = int(item_id_match)
                    if cid not in catalog_prices:
                        catalog_prices[cid] = float(price_str.replace(",", ".").strip())
                except (ValueError, TypeError):
                    pass

            # Extraction optimisée des annonces depuis le code source HTML du catalogue
            matches = re.findall(r'href="(/items/(\d+)[^"]*)"', response.text)
            seen_ids = set()
            items = []

            for href, item_id_str in matches:
                item_id = int(item_id_str)
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)

                meta_entry = card_meta.get(item_id, {})
                clean_title = meta_entry.get("title")
                raw_title = meta_entry.get("raw_title", "")

                idx = response.text.find(href)
                chunk = response.text[max(0, idx - 500): min(len(response.text), idx + 1000)]

                if not clean_title:
                    title_match = re.search(r'title="([^"]*)"', chunk)
                    raw_title = title_match.group(1) if title_match else ""
                    clean_title = raw_title.split(",")[0].strip() if raw_title else "Article Vinted"

                # Extraction du prix
                price = 0.0
                price_found = False
                if item_id in catalog_prices:
                    price = catalog_prices[item_id]
                    price_found = True
                else:
                    struct_price_match = (
                        re.search(r'itemprop="price"\s+content="([\d.]+)"', chunk) or
                        re.search(r'content="([\d.]+)"\s+itemprop="price"', chunk) or
                        re.search(r'data-price="([\d.]+)"', chunk) or
                        re.search(r'"amount":\s*"([\d.]+)"', chunk)
                    )
                    if struct_price_match:
                        try:
                            price = float(struct_price_match.group(1).replace(",", "."))
                            price_found = True
                        except (ValueError, TypeError):
                            pass

                if not price_found:
                    p_match = re.search(r'([\d,.]+)\s*€', chunk)
                    if p_match:
                        price = float(p_match.group(1).replace(",", "."))
                    else:
                        price = 0.0

                photo_url = card_images.get(item_id, "")
                if not photo_url:
                    img_match = re.search(r'(?:src|data-src)="([^"]*images1\.vinted\.net[^"]*)"', chunk)
                    photo_url = img_match.group(1) if img_match else ""

                item_url = f"https://www.{domain}{href}"

                items.append({
                    "id": item_id,
                    "domain": domain,
                    "title": clean_title,
                    "raw_title": raw_title,
                    "brand_title": meta_entry.get("brand_title", ""),
                    "status": meta_entry.get("status", ""),
                    "size_title": meta_entry.get("size_title", ""),
                    "price": {"amount": price, "currency_code": "EUR"},
                    "url": item_url,
                    "photo": {"url": photo_url},
                    "photos": [{"url": photo_url}] if photo_url else [],
                    "favourite_count": 0,
                    "user": {},
                    "seller_country": "",
                    "description": ""
                })

            logger.debug(f"Recherche '{search_config.get('name')}' ({domain}) : {len(items)} articles récupérés.")
            return items

        except Exception as e:
            logger.debug(f"Problème réseau temporaire pour '{search_config.get('name')}': {e}")
            return []

    def fetch_item_details(self, item: Dict[str, Any], priority: str = "high") -> Dict[str, Any]:
        """
        Récupère la page complète de l'annonce pour en extraire (haute priorité) :
        - La description intégrale rédigée par le vendeur.
        - Le pays du vendeur (seller_country) pour le calcul du port.
        - Toutes les photos haute résolution.
        - brand_title, status, user si manquants.
        """
        item_url = item.get("url")
        if not item_url:
            return item

        try:
            session = self.session_manager.get_session()
            self.rate_limiter.wait_for_token(priority=priority)
            resp = session.get(item_url, timeout=12)

            if resp.status_code != 200:
                logger.debug(f"Impossible de charger les détails (HTTP {resp.status_code}) pour {item_url}")
                return item

            html_text = resp.text

            # 1. Extraction via JSON-LD Product (le plus fiable et standard)
            description = ""
            for script in re.findall(r'<script type="application/ld\+json">([^<]+)</script>', html_text):
                try:
                    data = json.loads(script)
                    if isinstance(data, dict) and data.get("@type") == "Product":
                        # Description
                        description = data.get("description", "").strip()

                        # Marque
                        brand_obj = data.get("brand")
                        if isinstance(brand_obj, dict):
                            item["brand_title"] = brand_obj.get("name", "").strip()
                        elif isinstance(brand_obj, str):
                            item["brand_title"] = brand_obj.strip()

                        # Offres (Prix, État, Vendeur)
                        offers = data.get("offers")
                        if isinstance(offers, dict):
                            # Prix certifié
                            p_val = offers.get("price")
                            if p_val is not None:
                                try:
                                    item["price"] = {
                                        "amount": float(str(p_val).replace(",", ".")),
                                        "currency_code": offers.get("priceCurrency", "EUR")
                                    }
                                except (ValueError, TypeError):
                                    pass

                            # État
                            condition = offers.get("itemCondition")
                            if condition:
                                clean_cond = str(condition).split("/")[-1].replace("Condition", "")
                                if not item.get("status"):
                                    item["status"] = clean_cond

                            # Vendeur
                            seller = offers.get("seller")
                            if isinstance(seller, dict):
                                seller_name = seller.get("name")
                                if seller_name:
                                    item.setdefault("user", {})["login"] = seller_name

                        # Évaluations vendeur
                        agg_rating = data.get("aggregateRating")
                        if isinstance(agg_rating, dict):
                            r_val = agg_rating.get("ratingValue")
                            r_count = agg_rating.get("reviewCount")
                            if r_val is not None:
                                try:
                                    rf = float(r_val)
                                    item.setdefault("user", {})["feedback_reputation"] = (rf / 5.0) if rf > 1.0 else rf
                                except (ValueError, TypeError):
                                    pass
                            if r_count is not None:
                                try:
                                    item.setdefault("user", {})["feedback_count"] = int(r_count)
                                except (ValueError, TypeError):
                                    pass

                        break
                except Exception:
                    pass

            # Fallbacks dans le HTML / balises meta si non trouvés dans le JSON-LD
            # Description fallback
            if not description:
                meta_desc = re.search(r'itemprop="description"\s+content="([^"]*)"', html_text)
                if meta_desc:
                    description = meta_desc.group(1).strip()
            if description:
                item["description"] = html_lib.unescape(description)

            # Marque fallback
            if not item.get("brand_title"):
                b_match = (
                    re.search(r'itemprop="brand"[^>]*content="([^"]*)"', html_text) or
                    re.search(r'<span[^>]*itemprop="brand"[^>]*>([^<]+)</span>', html_text) or
                    re.search(r'"brand_title":\s*"([^"]+)"', html_text) or
                    re.search(r'"brand":\s*"([^"]+)"', html_text)
                )
                if b_match:
                    item["brand_title"] = html_lib.unescape(b_match.group(1).strip())

            # État (status) fallback
            s_match = (
                re.search(r'itemprop="itemCondition"[^>]*>([^<]+)<', html_text) or
                re.search(r'"status":\s*"([^"]+)"', html_text) or
                re.search(r'data-testid="item-attributes-item"[^>]*>.*?<div[^>]*>([^<]+)</div>', html_text, re.DOTALL)
            )
            if s_match:
                extracted_status = html_lib.unescape(s_match.group(1).strip())
                if extracted_status:
                    item["status"] = extracted_status

            # Favoris fallback
            fav_match = (
                re.search(r'"favourite_count":\s*(\d+)', html_text) or
                re.search(r'"favourited_count":\s*(\d+)', html_text) or
                re.search(r'(\d+)\s*(?:favoris?|favourites?|preferiti|favoritos)', html_text, re.IGNORECASE)
            )
            if fav_match:
                try:
                    item["favourite_count"] = int(fav_match.group(1))
                except (ValueError, TypeError):
                    pass

            # Pays du vendeur (Correction 1 : seller_country)
            # Recherche dans JSON embarqué, attributs ou localisation
            seller_country = ""
            sc_match = (
                re.search(r'"country_code":\s*"([A-Za-z]{2})"', html_text) or
                re.search(r'"countryCode":\s*"([A-Za-z]{2})"', html_text) or
                re.search(r'data-testid="[^"]*location[^"]*"[^>]*>([^<]+)<', html_text) or
                re.search(r'data-testid="profile-location[^"]*"[^>]*>([^<]+)<', html_text)
            )
            if sc_match:
                raw_c = sc_match.group(1).strip().lower()
                # Si c'est un code à 2 lettres
                if len(raw_c) == 2 and raw_c in ("fr", "it", "de", "es", "be", "nl", "pt", "at"):
                    seller_country = raw_c
                else:
                    # Recherche du nom de pays dans le texte
                    c_map = {
                        "france": "fr", "italie": "it", "italy": "it", "italia": "it",
                        "allemagne": "de", "germany": "de", "deutschland": "de",
                        "espagne": "es", "spain": "es", "españa": "es",
                        "belgique": "be", "belgium": "be", "belgië": "be",
                        "pays-bas": "nl", "netherlands": "nl", "nederland": "nl",
                        "portugal": "pt", "autriche": "at", "austria": "at", "österreich": "at"
                    }
                    for name, code in c_map.items():
                        if name in raw_c:
                            seller_country = code
                            break
            if seller_country:
                item["seller_country"] = seller_country

            # Vendeur / feedback fallback
            user_dict = item.setdefault("user", {})
            if "feedback_reputation" not in user_dict:
                rep_match = re.search(r'"feedback_reputation":\s*([\d.]+)', html_text)
                if rep_match:
                    try:
                        user_dict["feedback_reputation"] = float(rep_match.group(1))
                    except (ValueError, TypeError):
                        pass
            if "feedback_count" not in user_dict:
                fc_match = re.search(r'"feedback_count":\s*(\d+)', html_text)
                if fc_match:
                    try:
                        user_dict["feedback_count"] = int(fc_match.group(1))
                    except (ValueError, TypeError):
                        pass
            if "login" not in user_dict:
                login_match = re.search(r'"login":\s*"([^"]+)"', html_text)
                if login_match:
                    user_dict["login"] = login_match.group(1)

            # 2. Extraction de toutes les photos haute résolution
            photo_urls = []
            tag_matches = re.findall(r'<figure[^>]*>.*?<img[^>]+src="([^"]+)"[^>]*>.*?</figure>', html_text, re.DOTALL)
            for src in tag_matches:
                if "images1.vinted.net" in src and "/f800/" in src and src not in photo_urls:
                    photo_urls.append(src)

            if not photo_urls:
                all_imgs = re.findall(r'https://images1\.vinted\.net/t/[^"\'\s<>\\]+\?[^"\'\s<>\\]+', html_text)
                for raw_src in all_imgs:
                    src = raw_src.strip().rstrip("\\").rstrip('"').rstrip("'")
                    if "/f800/" in src and src not in photo_urls:
                        photo_urls.append(src)

            existing_photos = item.get("photos") or []
            existing_urls = [p.get("url") for p in existing_photos if isinstance(p, dict) and p.get("url")]
            combined_urls = []
            for u in existing_urls + photo_urls:
                if u and u not in combined_urls and "member_avatar" not in u:
                    combined_urls.append(u)

            if combined_urls:
                item["photos"] = [{"url": u} for u in combined_urls]
                item["photo"] = {"url": combined_urls[0]}

            logger.debug(
                f"📋 Annonce enrichie #{item.get('id')} : Marque='{item.get('brand_title')}', "
                f"État='{item.get('status')}', {len(item.get('photos', []))} photos HD, "
                f"desc ({len(item.get('description', ''))} car.)"
            )

        except Exception as e:
            logger.warning(f"Erreur lors de la récupération des détails de l'annonce {item.get('id')}: {e}")

        return item
