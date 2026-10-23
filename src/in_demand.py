import logging
import time
import html
import requests
from typing import Dict, Any, List, Optional, Set
from src.auth import VintedSessionManager
from src.scraper import VintedScraper
from src.notifier import TelegramNotifier
from src.database import DatabaseManager

logger = logging.getLogger("VintedBot.InDemand")

class InDemandTracker:
    """
    Moteur 2 : Suivi temporel des vêtements pour détecter les explosions de favoris (In-Demand) 
    et calculer le potentiel de profit.
    """

    def __init__(self, check_delay_seconds: int = 1200, min_favourites: int = 7, max_item_age_seconds: int = 7200):
        self.check_delay_seconds = check_delay_seconds  # Ex: 20 minutes (1200s)
        self.min_favourites = min_favourites          # Seuil minimum de favoris (ex: 7 ❤️)
        self.max_item_age_seconds = max_item_age_seconds  # Nettoyage au bout de 2h
        self.pending_items: Dict[int, Dict[str, Any]] = {}

    def add_to_tracker(self, item: Dict[str, Any], search_name: str):
        """Ajoute un nouvel article à la file d'observation temporisée."""
        item_id = item.get("id")
        if not item_id or item_id in self.pending_items:
            return

        self.pending_items[item_id] = {
            "item": item,
            "search_name": search_name,
            "added_at": time.time(),
            "initial_favourites": item.get("favourite_count", 0)
        }
        logger.debug(f"Article ID {item_id} ('{item.get('title')}') ajouté au Radar In-Demand (Vérification dans 20 min).")

    def process_due_items(self, scraper_or_scrapers: Any, notifier: TelegramNotifier, db: DatabaseManager):
        """Vérifie tous les articles arrivés à échéance (20 min) pour évaluer la demande."""
        now = time.time()
        due_item_ids = [
            item_id for item_id, data in self.pending_items.items()
            if (now - data["added_at"]) >= self.check_delay_seconds
        ]

        if not due_item_ids:
            return

        logger.debug(f"🔎 Radar In-Demand : Vérification de {len(due_item_ids)} article(s) arrivés à 20 min d'observation...")

        for item_id in due_item_ids:
            data = self.pending_items.pop(item_id, None)
            if not data:
                continue

            item_raw = data["item"]
            item_domain = item_raw.get("domain", "vinted.fr")

            if isinstance(scraper_or_scrapers, dict):
                active_scraper = scraper_or_scrapers.get(item_domain) or next(iter(scraper_or_scrapers.values()))
            else:
                active_scraper = scraper_or_scrapers

            session = active_scraper.session_manager.get_session()

            # Phase 2.1 & Correction 1 : Ne saute QUE les annonces déjà notifiées (par item_id seul)
            if db.is_item_notified(item_id):
                continue

            search_name = data["search_name"]
            added_at = data["added_at"]
            elapsed_minutes = int((now - added_at) / 60)

            headers = {
                "Accept": "application/json, text/plain, */*",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"https://www.{item_domain}/catalog"
            }

            item_url_api = f"https://www.{item_domain}/api/v2/items/{item_id}"
            
            try:
                res = session.get(item_url_api, headers=headers, timeout=10)
                if res.status_code == 200:
                    item_detail = res.json().get("item", {})
                    item_detail["domain"] = item_domain
                    fav_count = item_detail.get("favourite_count", item_detail.get("favourited_count", 0))
                    view_count = item_detail.get("view_count", 0)

                    # Vérification du seuil In-Demand
                    if fav_count >= self.min_favourites:
                        raw_url = item_detail.get("url", "")
                        item_url = raw_url if raw_url.startswith("http") else f"https://www.{item_domain}/items/{item_id}"
                        
                        price_obj = item_detail.get("price") or {}
                        price = float(price_obj.get("amount", 0.0)) if isinstance(price_obj, dict) else float(price_obj or 0.0)
                        
                        logger.info(f"🔥 IN-DEMAND | 🏷️ {item_detail.get('title')} ({price}€) | ❤️ {fav_count} favs en {elapsed_minutes}m | 🔗 {item_url}")
                        
                        # Marquer comme notifié et sauvegarder l'annonce complète dans deal_feedback
                        db.mark_item_notified(item_id, domain=item_domain, search_id="in_demand", title=item_detail.get("title", ""), price=price)
                        db.save_deal_alert(
                            item_detail,
                            search_name=f"IN-DEMAND ({search_name})",
                            domain=item_domain,
                            vision_result={"score": 85, "verdict": "IN_DEMAND", "summary": f"{fav_count} favoris en {elapsed_minutes} min"}
                        )
                        self._send_in_demand_alert(notifier, item_detail, search_name, fav_count, view_count, elapsed_minutes)
                    else:
                        logger.debug(f"Article ID {item_id} ignoré (seulement {fav_count} ❤️ après {elapsed_minutes} min).")

            except Exception as e:
                logger.debug(f"Erreur lors de la vérification In-Demand pour l'article ID {item_id}: {e}")

            time.sleep(1.0)

    def _send_in_demand_alert(
        self, 
        notifier: TelegramNotifier, 
        item: Dict[str, Any], 
        search_name: str, 
        fav_count: int, 
        view_count: int, 
        elapsed_minutes: int
    ):
        """Formate et envoie une alerte spéciale IN-DEMAND sur Telegram."""
        if not notifier.is_configured():
            return

        item_id = item.get("id")
        item_domain = item.get("domain", "vinted.fr")
        title = html.escape(str(item.get("title", "Sans titre")))
        search_name_esc = html.escape(str(search_name))
        
        price_obj = item.get("price")
        price = float(price_obj.get("amount", 0.0)) if isinstance(price_obj, dict) else float(price_obj or 0.0)
        
        brand = html.escape(str(item.get("brand_title") or "Non spécifié"))
        size = html.escape(str(item.get("size_title") or "Non spécifié"))
        status = html.escape(str(item.get("status") or "Non spécifié"))

        user_info = item.get("user") or {}
        seller_login = html.escape(str(user_info.get("login", "Inconnu")))
        feedback_rep = user_info.get("feedback_reputation")
        rating_stars = f"⭐ {float(feedback_rep) * 5.0:.1f}/5" if feedback_rep is not None else "Pas d'évaluations"

        estimated_resell = max(price * 1.8, price + 20.0)
        estimated_profit = estimated_resell - (price + 2.5)

        raw_url = item.get("url", "")
        item_url = raw_url if raw_url.startswith("http") else f"https://www.{item_domain}/items/{item_id}"

        photo_url = None
        photos = item.get("photos") or []
        if photos and len(photos) > 0:
            photo_url = photos[0].get("url") or photos[0].get("full_size_url")

        caption = (
            f"🔥 <b>ALERTE IN-DEMAND & TENDANCE !</b> 🔥\n\n"
            f"❤️ <b>Popularité :</b> {fav_count} favoris en {elapsed_minutes} min !\n"
            f"👁️ <b>Vues :</b> {view_count} vues\n"
            f"📌 <b>Catégorie :</b> {search_name_esc}\n"
            f"🏷️ <b>Titre :</b> {title}\n"
            f"💰 <b>Prix d'achat :</b> {price:.2f} €\n"
            f"💵 <b>Profit Estimé :</b> <b>+{estimated_profit:.2f} €</b> <i>(Revente ~{estimated_resell:.2f}€)</i>\n"
            f"📏 <b>Taille :</b> {size} | 🏢 <b>Marque :</b> {brand}\n"
            f"👤 <b>Vendeur :</b> {seller_login} ({rating_stars})\n\n"
            f"⚡ <a href='{item_url}'>👉 ACHETER MAINTENANT SUR VINTED</a>"
        )

        try:
            if photo_url:
                requests.post(
                    f"{notifier.base_url}/sendPhoto",
                    data={"chat_id": notifier.chat_id, "photo": photo_url, "caption": caption, "parse_mode": "HTML"},
                    timeout=10
                )
            else:
                requests.post(
                    f"{notifier.base_url}/sendMessage",
                    data={"chat_id": notifier.chat_id, "text": caption, "parse_mode": "HTML"},
                    timeout=10
                )
        except Exception as e:
            logger.error(f"Erreur envoi alerte In-Demand Telegram: {e}")
