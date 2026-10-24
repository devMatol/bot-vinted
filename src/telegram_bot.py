import sys
import logging
import json
import time
import threading
import requests
import os
import re
import html
import shutil
import numpy as np
from datetime import datetime
from typing import Dict, Any, List, Optional

from src.dataset_analyzer import DatasetAnalyzer

logger = logging.getLogger("VintedBot.TelegramBot")

CONFIG_PATH = "config.json"
CONFIG_LOCK = threading.Lock()

COUNTRY_FLAGS = {
    "fr": "🇫🇷 France",
    "it": "🇮🇹 Italie",
    "de": "🇩🇪 Allemagne",
    "es": "🇪🇸 Espagne",
    "be": "🇧🇪 Belgique",
    "nl": "🇳🇱 Pays-Bas",
    "pt": "🇵🇹 Portugal",
    "at": "🇦🇹 Autriche"
}

COUNTRY_DOMAINS = {
    "fr": "vinted.fr",
    "it": "vinted.it",
    "de": "vinted.de",
    "es": "vinted.es",
    "be": "vinted.be",
    "nl": "vinted.nl",
    "pt": "vinted.pt",
    "at": "vinted.at"
}

ALL_SUPPORTED_COUNTRIES = ["fr", "it", "de", "es", "be", "nl", "pt", "at"]

FLAW_LABELS = {
    "DEFECT": "🧵 Défaut / Abîmé / Tache",
    "STYLE": "👗 Pas mon style",
    "PRICE": "💸 Trop cher",
    "FAKE": "⚠️ Faux / Dupe",
    "CHILD": "👶 Vêtement enfant",
    "COMMENT": "💬 Commentaire libre",
    "CUSTOM_TEXT": "✍️ Motif écrit sur mesure"
}

class TelegramCommandHandler:
    """Écoute et exécute les commandes et évaluations interactives Telegram."""

    def __init__(self, telegram_config: Dict[str, Any], db_manager=None):
        self.config = telegram_config
        self.bot_token = telegram_config.get("bot_token", "")
        self.chat_id = str(telegram_config.get("chat_id", ""))
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.db_manager = db_manager
        self.analyzer = DatasetAnalyzer(db_manager)
        self.running = False
        self.last_update_id = 0
        self._thread = None

    def is_valid(self) -> bool:
        return bool(
            self.bot_token 
            and self.bot_token != "VOTRE_BOT_TOKEN_TELEGRAM_ICI"
            and self.chat_id 
            and self.chat_id != "VOTRE_CHAT_ID_TELEGRAM_ICI"
        )

    def start(self):
        """Démarre le thread d'écoute des commandes Telegram."""
        if not self.is_valid():
            logger.info("TelegramCommandHandler non démarré (jeton non configuré).")
            return

        self.running = True
        self._thread = threading.Thread(target=self._poll_updates, daemon=True)
        self._thread.start()
        logger.info("🤖 Écouteur de commandes et d'évaluations Telegram démarré !")

    def stop(self):
        self.running = False

    def _poll_updates(self):
        """Boucle de polling Telegram getUpdates."""
        while self.running:
            try:
                url = f"{self.base_url}/getUpdates?offset={self.last_update_id + 1}&timeout=10"
                response = requests.get(url, timeout=15)
                if response.status_code == 200:
                    data = response.json()
                    for update in data.get("result", []):
                        self.last_update_id = update.get("update_id", self.last_update_id)
                        
                        # Traiter les messages texte
                        message = update.get("message") or update.get("edited_message")
                        if message:
                            self._handle_message(message)

                        # Traiter les clics sur boutons interactifs (callback queries)
                        callback_query = update.get("callback_query")
                        if callback_query:
                            self._handle_callback_query(callback_query)

            except Exception as e:
                logger.debug(f"Erreur lors du polling Telegram getUpdates: {e}")
                time.sleep(3)

            # Vérification du réentraînement automatique chaque nuit à 4h
            self._check_nightly_retrain()

            time.sleep(1)

    def _check_nightly_retrain(self):
        """Réentraînement automatique chaque nuit à 4h si plus de 20 nouveaux clics."""
        try:
            now = datetime.now()
            if now.hour == 4 and now.minute <= 2:
                today_str = now.strftime("%Y-%m-%d")
                if getattr(self, "_last_nightly_check_date", None) != today_str:
                    self._last_nightly_check_date = today_str
                    last_trained_ts = "2020-01-01"
                    meta_path = "models/taste_meta.json"
                    if os.path.exists(meta_path):
                        try:
                            with open(meta_path, "r", encoding="utf-8") as f:
                                last_trained_ts = json.load(f).get("trained_at", "2020-01-01")
                        except Exception:
                            pass

                    import sqlite3
                    conn = sqlite3.connect("vinted_bot.db", timeout=30.0)
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT COUNT(*) FROM deal_feedback
                        WHERE classification IN ('MUST_BUY', 'REJECTED')
                          AND evaluated_by != 'System'
                          AND created_at > ?
                    """, (last_trained_ts,))
                    new_clicks = cur.fetchone()[0]
                    conn.close()

                    if new_clicks >= 20:
                        logger.info(f"🌙 Réentraînement automatique nocturne à 4h : {new_clicks} nouveaux clics détectés.")
                        self._reply(f"🌙 <b>Réentraînement nocturne automatique (4h)</b> : {new_clicks} nouveaux clics détectés.")
                        self._cmd_retrain_gout()
        except Exception as e:
            logger.debug(f"Erreur _check_nightly_retrain: {e}")

    def _handle_message(self, message: Dict[str, Any]):
        sender_id = str(message.get("from", {}).get("id", ""))
        if sender_id != self.chat_id:
            logger.warning(f"Message ignoré d'un utilisateur non autorisé ID {sender_id}")
            return

        text = (message.get("text") or "").strip()
        if not text:
            return

        # 1. Vérification réponse (Reply) à une alerte envoyée par le bot
        reply_to = message.get("reply_to_message")
        if reply_to and not text.startswith("/"):
            self._handle_reply_annotation(message, reply_to, text, sender_info=message.get("from", {}))
            return

        logger.info(f"Commande Telegram reçue : '{text}'")

        if text.startswith("/start") or text.startswith("/help"):
            self._cmd_help()
        elif text.startswith("/on"):
            self._cmd_toggle_bot(True)
        elif text.startswith("/off"):
            self._cmd_toggle_bot(False)
        elif text.startswith("/status"):
            self._cmd_status()
        elif text.startswith("/stats"):
            self._cmd_stats()
        elif text.startswith("/annotations"):
            self._cmd_annotations()
        elif text.startswith("/seuils"):
            self._cmd_seuils(text[7:].strip())
        elif text.startswith("/why"):
            self._cmd_why(text[4:].strip())
        elif text.startswith("/retrain_vision") or text.startswith("/train_vision"):
            self._cmd_retrain_vision()
        elif text.startswith("/retrain_gout"):
            self._cmd_retrain_gout()
        elif text.startswith("/retrain"):
            self._cmd_retrain()
        elif text.startswith("/dataset"):
            self._cmd_dataset()
        elif text.startswith("/cout") or text.startswith("/cost"):
            self._cmd_cout()
        elif text.startswith("/list"):
            self._cmd_list()
        elif text.startswith("/countries"):
            self._cmd_countries(text[10:].strip())
        elif text.startswith("/add"):
            self._cmd_add(text[4:].strip())
        elif text.startswith("/del"):
            self._cmd_del(text[4:].strip())

    def _handle_callback_query(self, query: Dict[str, Any]):
        """Gère les clics sur les boutons d'évaluation interactifs Telegram et les motifs de rejet."""
        query_id = query.get("id")
        data = query.get("data", "")
        sender_info = query.get("from", {})
        user_name = sender_info.get("first_name", "Utilisateur")

        # Cas 1 : Sous-menu de motif de défaut / rejet (flaw:TYPE:item_id)
        if data.startswith("flaw:"):
            parts = data.split(":")
            if len(parts) >= 3:
                flaw_type = parts[1]
                try:
                    item_id = int(parts[2])
                    self._handle_flaw_selection(query, item_id, flaw_type, user_name)
                except ValueError:
                    pass
            return

        # Cas 2 : Boutons d'action principaux (fb:ACTION:item_id)
        if not data.startswith("fb:"):
            return

        parts = data.split(":")
        if len(parts) < 3:
            return

        action_type = parts[1]
        try:
            item_id = int(parts[2])
        except ValueError:
            return

        # Si Rejet : présenter les boutons de motifs pour l'entraînement IA Vision
        if action_type == "reject":
            self._prompt_reject_reasons(query, item_id)
            return

        classification = "UNKNOWN"
        popup_text = ""

        if action_type == "must_buy":
            classification = "MUST_BUY"
            popup_text = "🎯 Enregistré comme 🟢 MUST BUY !"
        elif action_type == "wife_opinion":
            classification = "NEED_WIFE_OPINION"
            popup_text = "🤔 Enregistré comme 🟡 AVIS MAMA !"

        if self.db_manager:
            self.db_manager.update_deal_feedback_classification(
                item_id=item_id,
                classification=classification,
                evaluated_by=user_name
            )

        try:
            requests.post(
                f"{self.base_url}/answerCallbackQuery",
                json={
                    "callback_query_id": query_id,
                    "text": popup_text,
                    "show_alert": False
                },
                timeout=5
            )
        except Exception as e:
            logger.error(f"Erreur answerCallbackQuery: {e}")

        # Modifier le message d'origine
        msg = query.get("message")
        if msg:
            chat_id = msg.get("chat", {}).get("id")
            message_id = msg.get("message_id")
            existing_caption = msg.get("caption") or msg.get("text") or ""
            eval_badge = f"\n\n✅ <b>ÉVALUATION REGISTRÉE :</b> {popup_text}"
            new_caption = existing_caption + eval_badge if eval_badge not in existing_caption else existing_caption

            direct_url = f"https://www.vinted.fr/items/{item_id}"
            single_markup = json.dumps({
                "inline_keyboard": [[{"text": "⚡ OUVRIR DANS L'APPLI VINTED 🛍️", "url": direct_url}]]
            })

            try:
                if msg.get("photo"):
                    requests.post(
                        f"{self.base_url}/editMessageCaption",
                        data={
                            "chat_id": chat_id,
                            "message_id": message_id,
                            "caption": new_caption,
                            "parse_mode": "HTML",
                            "reply_markup": single_markup
                        },
                        timeout=5
                    )
                else:
                    requests.post(
                        f"{self.base_url}/editMessageText",
                        data={
                            "chat_id": chat_id,
                            "message_id": message_id,
                            "text": new_caption,
                            "parse_mode": "HTML",
                            "reply_markup": single_markup
                        },
                        timeout=5
                    )
            except Exception as e:
                logger.error(f"Erreur mise a jour caption evaluation: {e}")

    def _prompt_reject_reasons(self, query: Dict[str, Any], item_id: int):
        """Affiche les sous-boutons de motifs détaillés pour enrichir l'IA Vision."""
        query_id = query.get("id")
        msg = query.get("message")
        if not msg:
            return

        chat_id = msg.get("chat", {}).get("id")
        message_id = msg.get("message_id")

        reason_markup = json.dumps({
            "inline_keyboard": [
                [
                    {"text": "✍️ Écrire la raison exacte 💬", "callback_data": f"flaw:CUSTOM_TEXT:{item_id}"}
                ],
                [
                    {"text": "🧵 Défaut / Abîmé / Tache", "callback_data": f"flaw:DEFECT:{item_id}"},
                    {"text": "👗 Pas mon style", "callback_data": f"flaw:STYLE:{item_id}"}
                ],
                [
                    {"text": "💸 Trop cher", "callback_data": f"flaw:PRICE:{item_id}"},
                    {"text": "⚠️ Faux / Dupe", "callback_data": f"flaw:FAKE:{item_id}"}
                ],
                [
                    {"text": "👶 Enfant", "callback_data": f"flaw:CHILD:{item_id}"},
                    {"text": "↩️ Annuler", "callback_data": f"flaw:CANCEL:{item_id}"}
                ]
            ]
        })

        try:
            requests.post(
                f"{self.base_url}/answerCallbackQuery",
                json={
                    "callback_query_id": query_id,
                    "text": "Précisez la raison du rejet 👇",
                    "show_alert": False
                },
                timeout=5
            )
            requests.post(
                f"{self.base_url}/editMessageReplyMarkup",
                data={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "reply_markup": reason_markup
                },
                timeout=5
            )
        except Exception as e:
            logger.error(f"Erreur _prompt_reject_reasons: {e}")

    def _handle_flaw_selection(self, query: Dict[str, Any], item_id: int, flaw_type: str, user_name: str):
        """Enregistre le motif précis de rejet et archive photo + embedding pour l'IA."""
        query_id = query.get("id")
        msg = query.get("message")
        if not msg:
            return

        chat_id = msg.get("chat", {}).get("id")
        message_id = msg.get("message_id")
        direct_url = f"https://www.vinted.fr/items/{item_id}"

        # 1. Annulation : restaurer le clavier initial
        if flaw_type == "CANCEL":
            initial_markup = json.dumps({
                "inline_keyboard": [
                    [{"text": "⚡ OUVRIR DANS L'APPLI VINTED 🛍️", "url": direct_url}],
                    [
                        {"text": "🎯 🟢 MUST BUY", "callback_data": f"fb:must_buy:{item_id}"},
                        {"text": "🤔 🟡 AVIS MAMA", "callback_data": f"fb:wife_opinion:{item_id}"},
                        {"text": "❌ 🔴 REJET", "callback_data": f"fb:reject:{item_id}"}
                    ]
                ]
            })
            try:
                requests.post(
                    f"{self.base_url}/answerCallbackQuery",
                    json={"callback_query_id": query_id, "text": "Action annulée", "show_alert": False},
                    timeout=5
                )
                requests.post(
                    f"{self.base_url}/editMessageReplyMarkup",
                    data={"chat_id": chat_id, "message_id": message_id, "reply_markup": initial_markup},
                    timeout=5
                )
            except Exception as e:
                logger.error(f"Erreur annulation rejet: {e}")
            return

        # 2. Cas spécifique : L'utilisateur veut écrire la raison exacte
        if flaw_type == "CUSTOM_TEXT":
            try:
                requests.post(
                    f"{self.base_url}/answerCallbackQuery",
                    json={"callback_query_id": query_id, "text": "✍️ Écrivez votre raison en réponse...", "show_alert": False},
                    timeout=5
                )
            except Exception:
                pass

            prompt_text = (
                f"✍️ <b>Précisez la raison exacte du rejet pour l'article #{item_id} :</b>\n\n"
                f"<i>Exemples précis de défauts ou motifs :</i>\n"
                f"• <code>Semelle décollée / trouée</code>\n"
                f"• <code>Cuir craquelé / griffé</code>\n"
                f"• <code>Tache de graisse manche gauche</code>\n"
                f"• <code>Doublure déchirée</code>\n"
                f"• <code>Fermeture éclair / zip cassé</code>\n"
                f"• <code>Bouloches / matière feutrée</code>\n\n"
                f"💬 <b>Répondez directement à ce message avec vos mots :</b>"
            )
            force_reply_markup = json.dumps({
                "force_reply": True,
                "input_field_placeholder": "Ex: semelle usée, trou manche...",
                "selective": True
            })
            try:
                requests.post(
                    f"{self.base_url}/sendMessage",
                    data={
                        "chat_id": chat_id,
                        "text": prompt_text,
                        "parse_mode": "HTML",
                        "reply_markup": force_reply_markup
                    },
                    timeout=10
                )
            except Exception as e:
                logger.error(f"Erreur envoi ForceReply prompt: {e}")
            return

        # 3. Motif prédéfini choisi : archiver et enregistrer en base
        flaw_label = FLAW_LABELS.get(flaw_type, flaw_type)
        self._archive_vision_data(item_id, msg, flaw_type, user_comment="", user_name=user_name)

        if self.db_manager:
            self.db_manager.update_deal_feedback_classification(
                item_id=item_id,
                classification="REJECTED",
                evaluated_by=user_name
            )

        popup_text = f"✅ Rejet enregistré : {flaw_label}"
        try:
            requests.post(
                f"{self.base_url}/answerCallbackQuery",
                json={"callback_query_id": query_id, "text": popup_text, "show_alert": False},
                timeout=5
            )
        except Exception as e:
            logger.error(f"Erreur answerCallbackQuery flaw: {e}")

        # Clavier final sans boutons d'action
        single_markup = json.dumps({
            "inline_keyboard": [[{"text": "⚡ OUVRIR DANS L'APPLI VINTED 🛍️", "url": direct_url}]]
        })

        existing_caption = msg.get("caption") or msg.get("text") or ""
        badge = (
            f"\n\n❌ <b>REJETÉ :</b> {flaw_label}\n"
            f"🧠 <i>Photo et motif indexés pour l'apprentissage IA.</i>\n"
            f"💬 <i>(Vous pouvez aussi répondre à ce message avec du texte pour préciser le défaut)</i>"
        )
        new_caption = existing_caption + badge if badge not in existing_caption else existing_caption

        try:
            if msg.get("photo"):
                requests.post(
                    f"{self.base_url}/editMessageCaption",
                    data={"chat_id": chat_id, "message_id": message_id, "caption": new_caption, "parse_mode": "HTML", "reply_markup": single_markup},
                    timeout=5
                )
            else:
                requests.post(
                    f"{self.base_url}/editMessageText",
                    data={"chat_id": chat_id, "message_id": message_id, "text": new_caption, "parse_mode": "HTML", "reply_markup": single_markup},
                    timeout=5
                )
        except Exception as e:
            logger.error(f"Erreur mise à jour caption flaw: {e}")

    def _archive_vision_data(self, item_id: int, msg: Dict[str, Any], flaw_type: str, user_comment: str, user_name: str) -> bool:
        """Télécharge la photo haute définition et préserve l'embedding pour l'entraînement."""
        try:
            img_dir = "data/vision_dataset/images"
            emb_dir = "data/vision_dataset/embeddings"
            os.makedirs(img_dir, exist_ok=True)
            os.makedirs(emb_dir, exist_ok=True)

            local_img_path = os.path.join(img_dir, f"{item_id}.jpg")
            local_emb_path = os.path.join(emb_dir, f"{item_id}.npy")

            photo_url = ""
            photos = msg.get("photo") or []
            if photos and not os.path.exists(local_img_path):
                largest_photo = photos[-1]
                file_id = largest_photo.get("file_id")
                if file_id:
                    file_res = requests.get(f"{self.base_url}/getFile?file_id={file_id}", timeout=5)
                    if file_res.status_code == 200:
                        file_path = file_res.json().get("result", {}).get("file_path")
                        if file_path:
                            dl_url = f"https://api.telegram.org/file/bot{self.bot_token}/{file_path}"
                            img_data = requests.get(dl_url, timeout=10)
                            if img_data.status_code == 200:
                                with open(local_img_path, "wb") as f:
                                    f.write(img_data.content)
                                photo_url = dl_url

            # Repli si le message n'avait pas de photo directe (ex: réponse au ForceReply texte)
            if not os.path.exists(local_img_path) and self.db_manager:
                try:
                    with self.db_manager._get_connection() as conn:
                        c = conn.cursor()
                        c.execute("SELECT photo_urls FROM deal_feedback WHERE item_id = ?", (item_id,))
                        row = c.fetchone()
                        if row and row[0]:
                            urls = json.loads(row[0])
                            if urls and isinstance(urls, list) and urls[0]:
                                img_res = requests.get(urls[0], timeout=10)
                                if img_res.status_code == 200:
                                    with open(local_img_path, "wb") as f:
                                        f.write(img_res.content)
                                    photo_url = urls[0]
                except Exception as e:
                    logger.debug(f"Erreur téléchargement photo fallback #{item_id}: {e}")

            cache_emb_path = os.path.join("data/embeddings", f"{item_id}.npy")
            cache_siglip = os.path.join("data/embeddings", "siglip", f"{item_id}.npy")
            if not os.path.exists(local_emb_path):
                if os.path.exists(cache_siglip):
                    shutil.copyfile(cache_siglip, local_emb_path)
                elif os.path.exists(cache_emb_path):
                    shutil.copyfile(cache_emb_path, local_emb_path)
                elif os.path.exists(local_img_path):
                    try:
                        from PIL import Image
                        from src.scoring.clip_scorer import get_clip_scorer
                        scorer = get_clip_scorer()
                        with Image.open(local_img_path) as pil_img:
                            emb = scorer.encode_pil_image(pil_img)
                            if emb is not None:
                                np.save(local_emb_path, emb)
                    except Exception as e:
                        logger.debug(f"Impossible de calculer l'embedding à la volée pour #{item_id}: {e}")

            if self.db_manager:
                self.db_manager.record_vision_annotation(
                    item_id=item_id,
                    flaw_type=flaw_type,
                    user_comment=user_comment,
                    photo_url=photo_url,
                    local_image_path=local_img_path if os.path.exists(local_img_path) else "",
                    embedding_path=local_emb_path if os.path.exists(local_emb_path) else "",
                    annotated_by=user_name
                )
            return True
        except Exception as e:
            logger.error(f"Erreur _archive_vision_data: {e}")
            return False

    def _handle_reply_annotation(self, message: Dict[str, Any], reply_to: Dict[str, Any], text: str, sender_info: Dict[str, Any]):
        """Traite une réponse par message texte (Reply) sur une alerte ou prompt de motif."""
        user_name = sender_info.get("first_name", "Utilisateur")
        caption_or_text = reply_to.get("caption") or reply_to.get("text") or ""

        item_id = None
        reply_markup = reply_to.get("reply_markup") or {}
        for row in reply_markup.get("inline_keyboard", []):
            for btn in row:
                cb = btn.get("callback_data", "")
                if ":" in cb:
                    try:
                        item_id = int(cb.split(":")[-1])
                        break
                    except ValueError:
                        pass
                url = btn.get("url", "")
                if "/items/" in url:
                    m = re.search(r'/items/(\d+)', url)
                    if m:
                        item_id = int(m.group(1))
                        break
            if item_id:
                break

        if not item_id and caption_or_text:
            m = re.search(r'#(\d+)', caption_or_text)
            if not m:
                m = re.search(r'/items/(\d+)', caption_or_text)
            if m:
                item_id = int(m.group(1))

        if not item_id:
            logger.debug("Impossible d'extraire item_id du message reply_to")
            return

        t_low = text.lower()
        if any(w in t_low for w in ["trou", "tache", "abim", "abîm", "dechir", "déchir", "semelle", "usé", "use", "effiloch", "rayur", "rayé", "sal", "défonc", "defonc", "cassé", "casse", "accroc", "craquel", "decol", "décol", "zipp", "zip", "fermeture", "peluch", "bouloch"]):
            flaw_type = "DEFECT"
        elif any(w in t_low for w in ["style", "moche", "horrible", "ringard", "pas beau", "pas mon style", "laid", "bof", "pas rita"]):
            flaw_type = "STYLE"
        elif any(w in t_low for w in ["cher", "prix", "marge", "rentab", "trop cher", "euro"]):
            flaw_type = "PRICE"
        elif any(w in t_low for w in ["faux", "fake", "dupe", "copie", "contrefa", "imitation"]):
            flaw_type = "FAKE"
        elif any(w in t_low for w in ["enfant", "fille", "garçon", "garcon", "bébé", "bebe", "kid", "ans", "junior"]):
            flaw_type = "CHILD"
        else:
            flaw_type = "DEFECT"

        flaw_label = FLAW_LABELS.get(flaw_type, flaw_type)

        self._archive_vision_data(item_id, reply_to, flaw_type, user_comment=text, user_name=user_name)

        if self.db_manager:
            self.db_manager.update_deal_feedback_classification(
                item_id=item_id,
                classification="REJECTED",
                evaluated_by=user_name
            )

        self._reply(
            f"🎯 <b>Raison du rejet enregistrée avec précision !</b>\n\n"
            f"📌 <b>Article :</b> <code>#{item_id}</code>\n"
            f"🏷️ <b>Catégorie :</b> {flaw_label}\n"
            f"✍️ <b>Votre motif précis :</b> <i>\"{html.escape(text)}\"</i>\n\n"
            f"🧠 <i>Photo HD, motif textuel et embedding indexés pour la détection IA.</i>\n"
            f"💡 <i>Tapez <code>/retrain_vision</code> pour étalonner l'IA sur vos retours !</i>"
        )

    def _reply(self, text: str):
        try:
            requests.post(
                f"{self.base_url}/sendMessage",
                data={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "HTML"
                },
                timeout=10
            )
        except Exception as e:
            logger.error(f"Erreur envoi réponse Telegram: {e}")

    def _load_full_config(self) -> Dict[str, Any]:
        with CONFIG_LOCK:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)

    def _save_full_config(self, config_data: Dict[str, Any]):
        """Écriture atomique et thread-safe du fichier de configuration."""
        with CONFIG_LOCK:
            temp_path = f"{CONFIG_PATH}.tmp"
            try:
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(config_data, f, indent=2, ensure_ascii=False)
                os.replace(temp_path, CONFIG_PATH)
            except Exception as e:
                logger.error(f"Erreur sauvegarde atomique {CONFIG_PATH}: {e}")
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass

    def _cmd_help(self):
        msg = (
            "🤖 <b>COMMANDES DISPONIBLES :</b>\n\n"
            "⚡ <b>/on</b> : Activer le scan du bot\n"
            "⏸️ <b>/off</b> : Mettre le bot en pause\n"
            "📊 <b>/status</b> : Voir l'état du bot\n"
            "📸 <b>/annotations</b> : Statistiques du dataset Vision IA\n"
            "🧠 <b>/retrain_vision</b> : Étalonner la vision sur vos rejets écrits\n"
            "💰 <b>/cout</b> : Suivi des tokens et coût IA du jour\n"
            "🌍 <b>/countries</b> : Voir ou modifier les pays Vinted surveillés\n"
            "📈 <b>/dataset</b> : Statistiques d'apprentissage Auto-Buy\n"
            "📜 <b>/list</b> : Afficher vos recherches actives\n"
            "➕ <b>/add Nom | Recherche | PrixMax</b>\n"
            "   <i>Ex: /add Nike Tech | nike tech fleece | 40</i>\n"
            "🗑️ <b>/del NuméroOuNom</b> : Supprimer une recherche\n"
            "❓ <b>/help</b> : Afficher ce menu\n\n"
            "💡 <b>Conseil Rejets :</b> Sur chaque alerte, cliquez sur ❌ 🔴 REJET puis sur <b>✍️ Écrire la raison</b> pour taper un motif précis (ex: <i>semelle décollée</i>) !"
        )
        self._reply(msg)

    def _cmd_annotations(self):
        """Affiche les statistiques des annotations et retours enregistrés pour l'entraînement Vision."""
        if not self.db_manager:
            self._reply("❌ Base de données indisponible.")
            return

        stats = self.db_manager.get_vision_annotations_stats()
        total = stats.get("TOTAL", 0)

        img_dir = "data/vision_dataset/images"
        nb_images = len(os.listdir(img_dir)) if os.path.exists(img_dir) else 0

        msg = (
            f"📸 <b>DATASET D'ENTRAÎNEMENT VISION IA</b>\n\n"
            f"• <b>Total annotations enregistrées :</b> <b>{total}</b>\n"
            f"• <b>Photos HD archivées en local :</b> <b>{nb_images}</b>\n\n"
            f"<b>Répartition des motifs de rejet :</b>\n"
            f"  🧵 Défauts visuels : <b>{stats.get('DEFECT', 0)}</b>\n"
            f"  👗 Pas mon style : <b>{stats.get('STYLE', 0)}</b>\n"
            f"  💸 Trop cher / Marge faible : <b>{stats.get('PRICE', 0)}</b>\n"
            f"  ⚠️ Faux / Dupe : <b>{stats.get('FAKE', 0)}</b>\n"
            f"  👶 Enfant : <b>{stats.get('CHILD', 0)}</b>\n\n"
            f"💡 <i>Pour annoter : cliquez sur [❌ REJET] sous une alerte pour choisir le motif, ou répondez-y simplement par message texte !</i>"
        )
        self._reply(msg)

    def _cmd_countries(self, args: str):
        """Affiche ou met à jour les pays Vinted actifs (Phase 3.8)."""
        config = self._load_full_config()
        current_countries = [c.lower() for c in config.get("countries", ["fr"])]

        if not args:
            lines = ["🌍 <b>PAYS VINTED SURVEILLÉS :</b>\n"]
            for code in ALL_SUPPORTED_COUNTRIES:
                is_active = code in current_countries
                status = "🟢 ACTIF" if is_active else "⚪ Inactif"
                name = COUNTRY_FLAGS.get(code, code.upper())
                domain = COUNTRY_DOMAINS.get(code, f"vinted.{code}")
                lines.append(f"• {status} : <b>{name}</b> (<code>{domain}</code>)")

            lines.append(
                "\n👉 <b>Pour modifier les pays actifs :</b>\n"
                "• Remplacer : <code>/countries fr,it,es,de</code>\n"
                "• Ajouter : <code>/countries +it</code>\n"
                "• Retirer : <code>/countries -de</code>"
            )
            self._reply("\n".join(lines))
            return

        arg_clean = args.strip().lower()
        if arg_clean.startswith("+"):
            to_add = [c.strip() for c in arg_clean[1:].split(",") if c.strip() in ALL_SUPPORTED_COUNTRIES]
            for c in to_add:
                if c not in current_countries:
                    current_countries.append(c)
        elif arg_clean.startswith("-"):
            to_remove = [c.strip() for c in arg_clean[1:].split(",") if c.strip() in ALL_SUPPORTED_COUNTRIES]
            current_countries = [c for c in current_countries if c not in to_remove]
            if not current_countries:
                current_countries = ["fr"]
        else:
            specified = [c.strip() for c in arg_clean.split(",") if c.strip() in ALL_SUPPORTED_COUNTRIES]
            if specified:
                current_countries = specified
            else:
                self._reply(f"❌ Codes pays invalides. Codes autorisés : {', '.join(ALL_SUPPORTED_COUNTRIES)}")
                return

        config["countries"] = current_countries
        self._save_full_config(config)

        active_str = ", ".join(f"{COUNTRY_FLAGS.get(c, c.upper())}" for c in current_countries)
        self._reply(f"✅ <b>Pays actifs mis à jour avec succès :</b>\n{active_str}")

    def _cmd_toggle_bot(self, enable: bool):
        config = self._load_full_config()
        config["bot_enabled"] = enable
        self._save_full_config(config)
        status_str = "🟢 <b>ACTIVÉ</b> ! Le scan Vinted est en cours." if enable else "🔴 <b>MIS EN PAUSE</b>."
        self._reply(f"⚡ Statut du bot mis à jour : {status_str}")

    def _cmd_status(self):
        config = self._load_full_config()
        enabled = config.get("bot_enabled", False)
        searches = config.get("searches", [])
        active_searches = sum(1 for s in searches if s.get("enabled", True))
        interval = config.get("polling_interval_seconds", 1.5)
        countries = config.get("countries", ["fr"])
        countries_str = ", ".join(COUNTRY_FLAGS.get(c, c.upper()) for c in countries)
        
        seen_count = len(self.db_manager.get_seen_items()) if self.db_manager else "N/A"

        status_icon = "🟢 ACTIF (MULTITHREAD PARALLÈLE)" if enabled else "🔴 EN PAUSE"
        msg = (
            f"📊 <b>STATUT DU BOT VINTED</b>\n\n"
            f"• <b>État :</b> {status_icon}\n"
            f"• <b>Pays actifs :</b> {countries_str}\n"
            f"• <b>Recherches actives :</b> {active_searches} / {len(searches)}\n"
            f"• <b>Fréquence de scan :</b> toutes les {interval}s en parallèle\n"
            f"• <b>Articles enregistrés en cache :</b> {seen_count}\n"
        )
        self._reply(msg)

    def _cmd_dataset(self):
        report = self.analyzer.generate_report()
        self._reply(report)

    def _cmd_cout(self):
        """Affiche les statistiques de tokens et le coût estimé Gemini du jour."""
        if not self.db_manager:
            self._reply("❌ Base de données indisponible.")
            return

        usage = self.db_manager.get_token_usage_for_day()
        date_str = usage["date"]
        calls = usage["calls_count"]
        p_tok = usage["prompt_tokens"]
        c_tok = usage["candidates_tokens"]
        tot_tok = usage["total_tokens"]
        cost_in = usage["cost_input_usd"]
        cost_out = usage["cost_output_usd"]
        total_cost = usage["total_cost_usd"]

        msg = (
            f"💰 <b>CONSOMMATION & COÛT IA DU JOUR ({date_str})</b>\n\n"
            f"• <b>Analyses Vision réalisées :</b> {calls}\n"
            f"• <b>Tokens d'entrée (images/prompt) :</b> {p_tok:,}\n"
            f"• <b>Tokens de sortie (réponses JSON) :</b> {c_tok:,}\n"
            f"• <b>Total tokens :</b> {tot_tok:,}\n\n"
            f"💵 <b>Coût estimé :</b>\n"
            f"  - Entrée (0,30 $/M) : <code>{cost_in:.4f} $</code>\n"
            f"  - Sortie (2,50 $/M) : <code>{cost_out:.4f} $</code>\n"
            f"  👉 <b>Total estimé du jour :</b> <b>{total_cost:.4f} $</b>"
        )
        self._reply(msg)

    def _cmd_list(self):
        config = self._load_full_config()
        searches = config.get("searches", [])
        if not searches:
            self._reply("📜 Aucune recherche configurée pour le moment. Utilisez <code>/add</code> pour en ajouter une !")
            return

        lines = ["📜 <b>VOS RECHERCHES CONFIGURÉES :</b>\n"]
        for idx, s in enumerate(searches, 1):
            status = "🟢" if s.get("enabled", True) else "⚪ (Désactivée)"
            price = f"{s.get('max_price')}€" if s.get('max_price') else "Pas de limite"
            lines.append(f"<b>[{idx}]</b> {status} <b>{s.get('name')}</b>\n   🔍 Mot-clé: <i>{s.get('search_text')}</i>\n   💰 Prix max: <b>{price}</b>\n")

        lines.append("<i>Pour en supprimer une : <code>/del 1</code> (ou le numéro de la liste).</i>")
        self._reply("\n".join(lines))

    def _cmd_add(self, args_text: str):
        if not args_text or "|" not in args_text:
            self._reply(
                "❌ Format incorrect !\n\n"
                "👉 <b>Utilisation :</b>\n"
                "<code>/add Nom | mot clé de recherche | prix max</code>\n\n"
                "<b>Exemple :</b>\n"
                "<code>/add Nike Tech Fleece | nike tech fleece | 40</code>"
            )
            return

        parts = [p.strip() for p in args_text.split("|")]
        if len(parts) < 3:
            self._reply("❌ Veuillez préciser au moins 3 éléments séparés par un symbole '|' : Nom | Recherche | PrixMax")
            return

        name = parts[0]
        search_text = parts[1]
        try:
            max_price = float(parts[2].replace(",", "."))
        except ValueError:
            self._reply(f"❌ Le prix max '{parts[2]}' n'est pas un nombre valide !")
            return

        search_id = f"search_{int(time.time())}"
        new_search = {
            "id": search_id,
            "enabled": True,
            "name": name,
            "search_text": search_text,
            "max_price": max_price,
            "currency": "EUR",
            "min_seller_rating": 4.0,
            "exclude_keywords": ["fake", "imitation", "copie"]
        }

        config = self._load_full_config()
        config.setdefault("searches", []).append(new_search)
        self._save_full_config(config)

        self._reply(
            f"✅ <b>Nouvelle recherche ajoutée avec succès !</b>\n\n"
            f"📌 <b>Nom :</b> {name}\n"
            f"🔍 <b>Recherche :</b> {search_text}\n"
            f"💰 <b>Prix max :</b> {max_price} €"
        )

    def _cmd_del(self, args_text: str):
        if not args_text:
            self._reply("❌ Veuillez préciser le numéro ou le nom de la recherche à supprimer (ex: <code>/del 1</code>).")
            return

        config = self._load_full_config()
        searches = config.get("searches", [])

        removed_item = None
        if args_text.isdigit():
            idx = int(args_text) - 1
            if 0 <= idx < len(searches):
                removed_item = searches.pop(idx)
        else:
            for i, s in enumerate(searches):
                if s.get("id") == args_text or s.get("name").lower() == args_text.lower():
                    removed_item = searches.pop(i)
                    break

        if removed_item:
            self._save_full_config(config)
            self._reply(f"🗑️ Recherche <b>'{removed_item.get('name')}'</b> supprimée avec succès !")
        else:
            self._reply(f"❌ Recherche '{args_text}' introuvable. Tapez <code>/list</code> pour voir vos recherches.")

    def _cmd_stats(self):
        """Affiche les statistiques complètes du jour (Lot 8)."""
        import sqlite3
        conn = sqlite3.connect("vinted_bot.db", timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=30000;")
        try:
            cur = conn.cursor()
            today_str = datetime.utcnow().strftime("%Y-%m-%d")

            # Annonces vues aujourd'hui
            cur.execute("SELECT COUNT(*) FROM seen_items WHERE DATE(seen_at) = DATE('now')")
            seen_today = cur.fetchone()[0]

            # Décisions aujourd'hui
            cur.execute("""
                SELECT 
                    COUNT(*),
                    SUM(CASE WHEN decision = 'VALIDATED' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN alert_tier = 'PEPITE' THEN 1 ELSE 0 END),
                    AVG(execution_time_total_ms)
                FROM decisions
                WHERE DATE(created_at) = DATE('now')
            """)
            dec_row = cur.fetchone()
            total_dec = dec_row[0] or 0
            val_today = dec_row[1] or 0
            pep_today = dec_row[2] or 0
            avg_ms = dec_row[3] or 0.0

            # Coût Gemini du jour
            cur.execute("SELECT cost_usd, input_tokens, output_tokens FROM token_usage WHERE date = DATE('now')")
            t_row = cur.fetchone()
            cost_today = t_row[0] if t_row else 0.0

            # Pass rate
            pass_rate = (val_today / max(1, total_dec)) * 100.0

            msg = (
                f"📊 <b>STATISTIQUES DU JOUR ({today_str})</b>\n\n"
                f"👁️ <b>Annonces vues :</b> {seen_today}\n"
                f"⚡ <b>Décisions analysées :</b> {total_dec}\n"
                f"🟢 <b>Alertes validées :</b> {val_today} (Taux: <b>{pass_rate:.1f}%</b>)\n"
                f"💎 <b>Dont Pépites :</b> {pep_today}\n"
                f"⏱️ <b>Temps moyen local :</b> {avg_ms:.0f} ms / annonce\n"
                f"💵 <b>Coût Gemini :</b> {cost_today:.4f} $\n\n"
                f"<i>Moteur décisionnel local v2 actif.</i>"
            )
            self._reply(msg)
        except Exception as e:
            self._reply(f"❌ Erreur lors de la récupération des stats: {e}")
        finally:
            conn.close()

    def _cmd_seuils(self, args_text: str):
        """Consulte ou modifie les seuils décisionnels (Lot 8)."""
        config = self._load_full_config()
        if not args_text:
            score = config.get("final_min_score", 70.0)
            marge = config.get("min_margin_eur", 15.0)
            mult = config.get("min_multiple", 2.0)
            pep_only = "OUI" if config.get("alert_only_pepites") else "NON"
            msg = (
                f"⚙️ <b>SEUILS DÉCISIONNELS ACTUELS</b>\n\n"
                f"🎯 <b>Score min (final_min_score) :</b> {score}/100\n"
                f"💵 <b>Marge min (min_margin_eur) :</b> {marge:.2f} €\n"
                f"📈 <b>Multiple min (min_multiple) :</b> {mult:.1f}x\n"
                f"💎 <b>Pépites uniquement :</b> {pep_only}\n\n"
                f"<i>Pour modifier un seuil :</i>\n"
                f"• <code>/seuils score 75</code>\n"
                f"• <code>/seuils marge 20</code>\n"
                f"• <code>/seuils multiple 2.5</code>\n"
                f"• <code>/seuils pepites on/off</code>"
            )
            self._reply(msg)
            return

        parts = args_text.split()
        if len(parts) >= 2:
            param = parts[0].lower()
            val_str = parts[1].lower()
            try:
                if param in ("score", "final_min_score"):
                    val = float(val_str)
                    config["final_min_score"] = val
                    self._save_full_config(config)
                    self._reply(f"✅ Seuil <code>final_min_score</code> mis à jour à <b>{val}</b>.")
                elif param in ("marge", "margin", "min_margin_eur"):
                    val = float(val_str)
                    config["min_margin_eur"] = val
                    self._save_full_config(config)
                    self._reply(f"✅ Seuil <code>min_margin_eur</code> mis à jour à <b>{val:.2f} €</b>.")
                elif param in ("multiple", "min_multiple"):
                    val = float(val_str)
                    config["min_multiple"] = val
                    self._save_full_config(config)
                    self._reply(f"✅ Seuil <code>min_multiple</code> mis à jour à <b>{val:.1f}x</b>.")
                elif param in ("pepites", "pepite", "only_pepites"):
                    val_bool = val_str in ("on", "1", "true", "oui")
                    config["alert_only_pepites"] = val_bool
                    self._save_full_config(config)
                    status_str = "ACTIVÉ (uniquement pépites 🟢)" if val_bool else "DÉSACTIVÉ (toutes alertes)"
                    self._reply(f"✅ Filtre pépites exclusives : <b>{status_str}</b>.")
                else:
                    self._reply(f"❌ Paramètre inconnu : '{param}'. Options : score, marge, multiple, pepites.")
            except ValueError:
                self._reply(f"❌ Valeur numérique invalide : '{val_str}'.")
        else:
            self._reply("❌ Format attendu : <code>/seuils [score|marge|multiple] [valeur]</code>")

    def _cmd_why(self, args_text: str):
        """Explique en détail la décision pour un article donné (Lot 8)."""
        if not args_text:
            self._reply("❌ Veuillez préciser l'identifiant de l'annonce : <code>/why &lt;item_id&gt;</code>")
            return

        import sqlite3
        conn = sqlite3.connect("vinted_bot.db", timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=30000;")
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT item_id, decision, alert_tier, score_final, price, total_cost,
                       revente_retenue, margin, multiple, stage_reached, stop_reason, details_json, created_at
                FROM decisions
                WHERE item_id = ?
                ORDER BY id DESC LIMIT 1
            """, (args_text.strip(),))
            row = cur.fetchone()
            if not row:
                self._reply(f"❌ Aucune décision trouvée en base pour l'article <code>{args_text}</code>.")
                return

            i_id, dec, tier, score, p, tc, rev, mg, mult, stg, stop, det_json, c_at = row
            icon = "🟢" if dec == "VALIDATED" else "🔴"
            details = json.loads(det_json) if det_json else {}

            rule_sc = details.get("rule_score", 0.0)
            dist_sc = details.get("distinct_score", 0.0) * 100.0
            sig_sc = details.get("listing_signal_score", 50.0)

            msg = (
                f"{icon} <b>AUDIT DÉCISION — ARTICLE #{i_id}</b>\n\n"
                f"⚖️ <b>Décision :</b> <b>{dec}</b> ({tier})\n"
                f"🎯 <b>Score Final :</b> <b>{score:.1f}/100</b>\n"
                f"💰 <b>Prix affiché :</b> {p:.2f} € | <b>Coût total :</b> {tc:.2f} €\n"
                f"📈 <b>Revente retenue :</b> ~{rev:.2f} €\n"
                f"💵 <b>Marge estimée :</b> {mg:+.2f} € (Multiple: {mult:.1f}x)\n"
                f"🚪 <b>Étage atteint :</b> {stg}\n"
                f"🛑 <b>Motif d'arrêt :</b> {stop or 'Aucun (validé)'}\n\n"
                f"<b>Détail des sous-scores :</b>\n"
                f"• Règles heuristiques : {rule_sc:.1f}/100\n"
                f"• Distinctivité visuelle : {dist_sc:.1f}/100\n"
                f"• Signaux annonce/vendeur : {sig_sc:.1f}/100\n\n"
                f"<i>Horodatage : {c_at}</i>"
            )
            self._reply(msg)
        except Exception as e:
            self._reply(f"❌ Erreur lecture audit: {e}")
        finally:
            conn.close()

    def _cmd_retrain_gout(self):
        """Relance la construction du dataset de goût et l'entraînement du modèle Rita."""
        self._reply("👗 <b>Réentraînement du modèle de goût 'Rita' lancé...</b>\n\n1. Construction du dataset (favoris + clics + marché)\n2. Régression logistique régularisée et calibration\n\n<i>Notification dès la fin.</i>")

        def worker():
            try:
                import subprocess
                py_exe = sys.executable
                # 1. build dataset
                p1 = subprocess.run([py_exe, "scripts/build_taste_dataset.py"], capture_output=True, text=True, timeout=300)
                if p1.returncode != 0:
                    self._reply(f"❌ Échec de la construction du dataset de goût :\n{p1.stderr[:300]}")
                    return

                # 2. train
                p2 = subprocess.run([py_exe, "scripts/train_taste.py"], capture_output=True, text=True, timeout=300)
                if p2.returncode != 0:
                    self._reply(f"❌ Échec de l'entraînement du modèle de goût :\n{p2.stderr[:300]}")
                    return

                # 3. Reload in-memory
                from src.scoring.taste import init_taste_scorer
                init_taste_scorer()

                # 4. Read metrics
                with open("models/taste_meta.json", "r", encoding="utf-8") as f:
                    meta = json.load(f)

                auc = float(meta.get("auc", 0.0))
                p10 = float(meta.get("precision_at_10pct", 0.0)) * 100.0
                n_samples = meta.get("n_samples", 0)

                msg = (
                    f"✅ <b>MODÈLE DE GOÛT 'RITA' RÉENTRAÎNÉ !</b>\n\n"
                    f"📈 <b>AUC OOF :</b> {auc:.3f} {'(Valide ✅)' if auc >= 0.70 else '(Invalide ❌)'}\n"
                    f"🎯 <b>Précision @ 10% :</b> {p10:.1f} %\n"
                    f"👗 <b>Exemples appris :</b> {n_samples} ({meta.get('n_positives')} positifs)\n"
                    f"📄 Rapport HTML actualisé dans <code>data/taste_report.html</code>"
                )
                self._reply(msg)
            except Exception as e:
                self._reply(f"❌ Erreur réentraînement goût: {e}")

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def _cmd_retrain(self):
        """Lance le réentraînement complet des modèles de revente en tâche de fond (Lot 8)."""
        self._reply("⏳ <b>Réentraînement lancé en arrière-plan...</b>\n\n1. Entraînement des modèles de revente\n2. Optimisation des comparables\n3. Backtest et calibration\n\n<i>Vous recevrez une notification à la fin.</i>")

        def worker():
            try:
                from src.scoring.feedback_learner import run_full_retrain
                res = run_full_retrain()
                mae30 = res.get("mae_q30_eur", 0.0)
                mae50 = res.get("mae_q50_eur", 0.0)
                msg = (
                    f"✅ <b>RÉENTRAÎNEMENT TERMINÉ AVEC SUCCÈS !</b>\n\n"
                    f"📉 <b>Erreur médiane revente q30 :</b> {mae30:.2f} €\n"
                    f"📊 <b>Erreur médiane revente q50 :</b> {mae50:.2f} €\n"
                    f"📄 Rapport HTML actualisé dans <code>data/backtest_report.html</code>"
                )
                self._reply(msg)
            except Exception as e:
                self._reply(f"❌ Échec du réentraînement : {e}")

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def _cmd_retrain_vision(self):
        """Lance l'entraînement et l'étalonnage de l'IA Vision sur les motifs de rejet collectés (Phase 3)."""
        self._reply(
            "🧠 <b>Entraînement de l'IA Vision lancé...</b>\n\n"
            "1. Analyse des annotations et raisons de rejets écrites\n"
            "2. Génération des sondes de défauts textuelles et bilingues\n"
            "3. Indexation de la mémoire d'exemplaires de défauts (k-NN)\n"
            "4. Rechargement à chaud du moteur de vision\n\n"
            "<i>Notification dès la fin.</i>"
        )

        def worker():
            try:
                import subprocess
                py_exe = sys.executable
                venv_py = os.path.join(os.getcwd(), "venv", "Scripts", "python.exe")
                if os.path.exists(venv_py):
                    py_exe = venv_py
                p = subprocess.run([py_exe, "scripts/train_vision.py"], capture_output=True, text=True, timeout=300)
                if p.returncode != 0:
                    err_msg = p.stderr or p.stdout or "Erreur inconnue"
                    self._reply(f"❌ Échec de l'entraînement vision :\n{err_msg[:400]}")
                    return

                # Rechargement de la mémoire de défauts à chaud dans le scorer en mémoire
                from src.scoring.clip_scorer import get_clip_scorer
                scorer = get_clip_scorer()
                scorer.reload_defect_memory()

                report_file = "data/vision_dataset/vision_train_report.json"
                if os.path.exists(report_file):
                    with open(report_file, "r", encoding="utf-8") as f:
                        rep = json.load(f)
                    n_annots = rep.get("total_annotations", 0)
                    n_exemplars = rep.get("defect_exemplars", 0)
                    n_probes = rep.get("custom_probes_count", 0)
                    top_reasons = rep.get("top_reasons", [])
                    reasons_str = "\n".join([f"• <i>{r}</i>" for r in top_reasons[:5]]) or "Aucun motif écrit"

                    msg = (
                        f"✅ <b>IA VISION RÉENTRAÎNÉE AVEC SUCCÈS !</b>\n\n"
                        f"📊 <b>Annotations traitées :</b> {n_annots}\n"
                        f"🛡️ <b>Exemplaires de défauts mémorisés (k-NN) :</b> {n_exemplars}\n"
                        f"🎯 <b>Sondes personnalisées créées :</b> {n_probes}\n"
                        f"📝 <b>Vos motifs récurrents appris :</b>\n{reasons_str}\n\n"
                        f"⚡ <i>Le bot détecte désormais automatiquement ces défauts lors des scans !</i>"
                    )
                else:
                    msg = "✅ <b>IA Vision réentraînée !</b> Mémoire de défauts mise à jour."

                self._reply(msg)
            except Exception as e:
                self._reply(f"❌ Erreur entraînement vision: {e}")

        t = threading.Thread(target=worker, daemon=True)
        t.start()
